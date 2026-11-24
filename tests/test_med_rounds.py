"""Scoped medication observations, separate confirmations and signed order execution."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from platform_core import med_rounds as rounds
from platform_core.store import Store, TIMEZONE, Conflict


class MedicationRounds(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.now = datetime(2026, 11, 24, 9, 30, tzinfo=TIMEZONE)
        self.password = "synthetic-med-rounds-login"
        self.store = Store(
            Path(tmp.name) / "care.db",
            lambda: self.now,
            initial_owner_password=self.password,
        )
        self.owner = self.store.login("owner", self.password)[0]
        self.helper = self.staff("helper", "护工")
        self.nurse = self.staff("nurse", "护士")
        self.room = self.preview(self.owner)["rooms"][0]["id"]
        self.rows = self.preview(self.owner, roomId=self.room)["people"]
        self.rid = self.rows[0]["residentId"]

    def execute(self, token, action, payload):
        return self.store.execute(
            action, payload, self.store.version(token)["revision"], token
        )

    def staff(self, login, role):
        self.execute(
            self.owner,
            "access.create",
            dict(
                username=login,
                displayName=login,
                kind="staff",
                role=role,
                password=self.password,
            ),
        )
        return self.store.login(login, self.password)[0]

    def preview(self, token, **payload):
        return rounds.preview(self.store, token, payload)

    def one(self, token, **scope):
        return self.preview(token, **scope)["people"][0]

    def payload(self, row, **extra):
        return (
            dict(
                residentId=row["residentId"],
                basis=row["basis"],
                outcome="taken",
                slot="早晨",
                day=self.now.date().isoformat(),
                confirmed=True,
            )
            | extra
        )

    def sign(self, token, row, **extra):
        return self.execute(token, "care.confirmMedRound", self.payload(row, **extra))

    def order(self, rid, hour):
        self.execute(
            self.owner,
            "care.addMedication",
            dict(
                residentId=rid,
                name="合成医嘱" + hour,
                instruction="按既有处方核实",
                scheduledAt="2026-11-24T" + hour,
            ),
        )
        m = self.store.snapshot(self.owner)["data"]["medications"][-1]
        self.execute(
            self.owner,
            "care.reviewMedication",
            dict(medicationId=m["id"], note="核对完毕"),
        )
        return m["id"]

    def test_each_resident_signs_separately_and_missed_observation_leaves_order_active(
        self,
    ):
        first, second = self.rows[:2]
        mid = self.order(second["residentId"], "08:15")
        room = first["room"]
        spoken = f"{room} 房所有老人早晨都服药了，除了{second['name']}今日无需服药"

        def parse(store, actor, req, instruction, facts, validate, **kwargs):
            self.assertEqual(facts, {"口述": spoken})
            return validate(
                {
                    "targets": [{"room": room, "bed": "", "name": ""}],
                    "exceptions": [
                        {
                            "room": "",
                            "bed": "",
                            "name": second["name"],
                            "reason": "今日无需服药",
                        }
                    ],
                    "slots": ["早晨"],
                    "outcome": "taken",
                    "reason": "",
                    "unclear": False,
                }
            )

        with patch.object(rounds.generation, "generate", side_effect=parse):
            rows = self.preview(self.helper, text=spoken)["people"]
        self.assertTrue(all(not r["receipt"] and not r["orders"] for r in rows))
        self.sign(self.helper, rows[0])
        self.assertIsNone(
            self.one(self.helper, residentId=second["residentId"])["receipt"]
        )
        self.assertEqual(rows[1]["outcome"], "notGiven")
        self.sign(
            self.helper, rows[1], outcome=rows[1]["outcome"], note=rows[1]["note"]
        )
        state = self.store.snapshot(self.owner)["data"]
        self.assertEqual(
            next(m for m in state["medications"] if m["id"] == mid)["status"], "待执行"
        )
        alert = state["vitals"][-1]
        self.assertEqual(
            (alert["residentId"], alert["status"], alert["note"]),
            (second["residentId"], "待复核", "今日无需服药"),
        )
        proof = self.one(self.helper, residentId=second["residentId"])["receipt"]
        self.assertEqual(
            (proof["actor"], proof["bed"], proof["checkedCardCode"]),
            ("helper", second["bed"], ""),
        )
        self.now += timedelta(days=1)
        self.assertEqual(
            self.one(self.nurse, residentId=second["residentId"])["history"][0], proof
        )

    def test_nurse_checks_only_selected_due_orders_and_rejects_tampered_ids(self):
        target = self.order(self.rid, "07:45")
        keep = self.order(self.rid, "08:25")
        later = self.order(self.rid, "10:25")
        elsewhere = self.order(self.rows[1]["residentId"], "08:00")
        nurse = self.one(self.nurse, residentId=self.rid)
        self.assertIn(target, [m["id"] for m in nurse["orders"]])
        self.assertNotIn(later, [m["id"] for m in nurse["orders"]])
        carer = self.one(self.helper, residentId=self.rid)
        with self.assertRaises(ValueError):
            self.sign(self.helper, carer, medicationIds=[target])
        with self.assertRaises(ValueError):
            self.sign(self.nurse, nurse, medicationIds=[elsewhere])
        with self.assertRaises(ValueError):
            self.sign(
                self.nurse,
                nurse,
                outcome="notGiven",
                medicationIds=[target],
                note="未服",
            )
        self.sign(self.nurse, nurse, medicationIds=[target])
        state = self.store.snapshot(self.owner)["data"]
        meds = {m["id"]: m for m in state["medications"]}
        self.assertEqual(meds[target]["status"], "已执行")
        self.assertEqual(meds[target]["operator"], "nurse")
        self.assertTrue(
            all(meds[k]["status"] == "待执行" for k in (keep, later, elsewhere))
        )

    def test_room_authorization_new_card_and_contending_confirmations(self):
        other = next(
            r for r in self.preview(self.owner)["rooms"] if r["id"] != self.room
        )
        outsider = self.one(self.owner, roomId=other["id"])
        self.store.facility_policy = lambda db, u: (
            {"roomIds": [self.room]} if u["displayName"] == "helper" else {}
        )
        with self.assertRaises(ValueError):
            self.preview(self.helper, roomId=other["id"])
        with self.assertRaises(PermissionError):
            self.sign(self.helper, outsider)
        contents = self.store.snapshot(self.owner)["data"]
        card = next(
            m["cardCode"]
            for m in reversed(contents["bedMoves"])
            if m["residentId"] == self.rid
        )
        self.assertEqual(
            rounds.qr(self.store, self.helper, card, "https://care.example")[:8],
            b"\x89PNG\r\n\x1a\n",
        )
        current = self.one(self.helper, cardCode=card)
        with self.assertRaises(ValueError):
            self.sign(self.helper, current, cardCode="11111111")
        with self.assertRaises(ValueError):
            self.sign(self.helper, current, actor="forged")
        rival = self.one(self.nurse, residentId=self.rid)
        revision = self.store.version(self.nurse)["revision"]

        def submit(pair):
            token, row = pair
            try:
                self.store.execute(
                    "care.confirmMedRound",
                    self.payload(row, cardCode=card),
                    revision,
                    token,
                )
                return True
            except (ValueError, Conflict):
                return False

        with ThreadPoolExecutor(2) as pool:
            results = list(
                pool.map(submit, [(self.helper, current), (self.nurse, rival)])
            )
        self.assertEqual(sum(results), 1)
        self.assertEqual(
            self.one(self.owner, residentId=self.rid)["receipt"]["checkedCardCode"],
            card,
        )
        with self.assertRaises(ValueError):
            self.sign(self.helper, current)
        self.execute(
            self.owner,
            "care.transfer",
            dict(
                residentId=self.rid,
                bedId=next(b["id"] for b in contents["beds"] if not b["residentId"]),
            ),
        )
        with self.assertRaises(FileNotFoundError):
            rounds.qr(self.store, self.owner, card, "https://care.example")

    def test_ambiguous_exceptions_model_invention_wrong_actor_and_time_are_rejected(
        self,
    ):
        record = self.one(self.nurse, residentId=self.rid)
        with self.assertRaises(ValueError):
            self.sign(self.helper, record)
        with self.assertRaises(ValueError):
            self.sign(self.nurse, record, slot="晚上")
        selector = {"room": "101", "bed": "", "name": ""}
        spec = {
            "targets": [selector],
            "exceptions": [],
            "slots": ["早晨"],
            "reason": "",
            "outcome": "taken",
            "unclear": False,
        }
        for text in ("102房已服", "101房已服，除了张某"):
            with self.assertRaises(ValueError):
                rounds.valid_parse(spec, text)
        with self.assertRaises(ValueError):
            rounds.match(
                self.rows, {"room": "", "bed": "", "name": ""}, individual=True
            )
        with closing(self.store.connect()) as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM medication_round_receipts").fetchone()[
                    0
                ],
                0,
            )

    def test_many_rooms_and_slots_keep_selected_chat_boundary_and_future_rounds_unsigned(
        self,
    ):
        self.now = self.now.replace(hour=17)
        other_room = next(
            r["id"] for r in self.preview(self.owner)["rooms"] if r["id"] != self.room
        )
        a, b = self.rows[0], self.one(self.owner, roomId=other_room)
        spoken = f"{a['room']}、{b['room']} 房所有老人早晨、中午、晚上和夜间都服药，除了{b['name']}中午未服，原因是外出"

        def fake(store, actor, req, instruction, facts, validate, **options):
            return validate(
                {
                    "targets": [
                        {"room": r["room"], "bed": "", "name": ""} for r in (a, b)
                    ],
                    "exceptions": [
                        {
                            "room": b["room"],
                            "bed": "",
                            "name": b["name"],
                            "reason": "外出",
                            "slots": ["中午"],
                        }
                    ],
                    "slots": ["早晨", "中午", "晚上", "夜间"],
                    "outcome": "taken",
                    "reason": "",
                    "unclear": False,
                }
            )

        region = {"roomId": self.room}
        with patch.object(rounds.generation, "generate", side_effect=fake):
            with self.assertRaises(ValueError):
                self.preview(self.nurse, text=spoken, region=region)
            result = self.preview(
                self.nurse, text=spoken, region={"floorId": "floor-1"}
            )
        self.assertEqual(result["futureSlots"], ["夜间"])
        selected = [p for p in result["people"] if p["residentId"] == b["residentId"]]
        self.assertEqual(
            [(r["roundSlot"], r["outcome"]) for r in selected],
            [("早晨", "taken"), ("中午", "notGiven"), ("晚上", "taken")],
        )
        for row in selected:
            with self.assertRaises((ValueError, PermissionError)):
                self.sign(self.nurse, row, slot=row["roundSlot"], region=region)
            self.sign(
                self.nurse,
                row,
                slot=row["roundSlot"],
                outcome=row["outcome"],
                note=row["note"],
                region={"floorId": "floor-1"},
            )
        self.assertEqual(
            len(self.one(self.nurse, residentId=b["residentId"])["history"]), 3
        )

    def test_legacy_card_keeps_its_institution_sequence_in_scoped_browser(self):
        from platform_core.store import encode
        from platform_core.care.residency import active_card

        other_room = self.preview(self.owner)["rooms"][1]["id"]
        rid = self.one(self.owner, roomId=other_room)["residentId"]
        with closing(self.store.connect()) as db, db:
            import json

            state = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            for m in state["bedMoves"]:
                m.pop("cardCode", None)
            resident = next(p for p in state["residents"] if p["id"] == rid)
            card = active_card(state, resident)
            db.execute("UPDATE workspace SET data=? WHERE id=1", (encode(state),))
        self.store.facility_policy = lambda db, u: (
            {"roomIds": [other_room]} if u["displayName"] == "helper" else {}
        )
        view = self.store.snapshot(self.helper)["data"]
        self.assertEqual(
            view["currentBedCards"][rid]["code"],
            card,
        )
        self.assertEqual(self.one(self.helper, cardCode=card)["residentId"], rid)
        self.assertTrue(
            rounds.qr(
                self.store, self.helper, card, "https://institution.example"
            ).startswith(b"\x89PNG")
        )

    def test_reciprocal_legacy_beds_without_movements_receive_stable_separate_codes(
        self,
    ):
        import json
        from platform_core.care import legacy_bed_cards
        from platform_core.store import encode

        first, second = self.rows[:2]
        missing = [first["residentId"], second["residentId"]]
        with closing(self.store.connect()) as db, db:
            data = json.loads(
                db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
            )
            data["bedMoves"] = [
                m for m in data["bedMoves"] if m["residentId"] not in missing
            ]
            length = len(data["bedMoves"])
            db.execute("UPDATE workspace SET data=? WHERE id=1", (encode(data),))
            legacy_bed_cards.backfill(db)
        helper = self.store.snapshot(self.helper)["data"]
        cards = helper["currentBedCards"]
        self.assertEqual(len(helper["bedMoves"]), length)
        self.assertEqual(sum(c["code"].startswith("1") for c in cards.values()), 2)
        self.assertNotEqual(cards[missing[0]]["code"], cards[missing[1]]["code"])
        code = cards[missing[0]]["code"]
        self.assertTrue(code.startswith("1"))
        self.store = Store(
            self.store.path, lambda: self.now, initial_owner_password=self.password
        )
        self.assertEqual(
            self.store.snapshot(self.helper)["data"]["currentBedCards"], cards
        )
        row = self.one(self.helper, cardCode=code)
        self.assertEqual(row["residentId"], missing[0])
        self.assertTrue(
            rounds.qr(
                self.store, self.helper, code, "https://institution.example"
            ).startswith(b"\x89PNG")
        )
        with closing(self.store.connect()) as db:
            evidence = db.execute(
                "SELECT source,recorded_at FROM legacy_bed_cards WHERE resident_id=?",
                (missing[0],),
            ).fetchone()
            self.assertTrue(evidence[0].startswith("系统"))
            self.assertTrue(evidence[1].endswith("Z"))
        self.execute(
            self.owner,
            "care.transfer",
            dict(
                residentId=missing[0],
                bedId=next(b["id"] for b in helper["beds"] if not b["residentId"]),
            ),
        )
        self.execute(
            self.owner,
            "care.transfer",
            dict(residentId=missing[0], bedId=first["bedId"]),
        )
        with self.assertRaises(FileNotFoundError):
            rounds.qr(self.store, self.helper, code, "https://institution.example")
        with self.assertRaises(ValueError):
            self.sign(self.helper, row, cardCode=code)
        after = self.store.snapshot(self.helper)["data"]
        new_code = after["bedMoves"][-1]["cardCode"]
        self.assertTrue(new_code.startswith("2"))
        self.assertEqual(
            self.one(self.helper, cardCode=new_code)["residentId"], missing[0]
        )
        self.assertEqual(after["currentBedCards"][missing[0]]["code"], new_code)
