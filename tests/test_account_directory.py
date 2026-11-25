"""Exercise account projection with a volume fixture in the encrypted Store."""

from collections import Counter
from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from platform_core import access, portal
from platform_core.care.residency import TRIAL_PENDING
from platform_core.store import Store, encode


PASSWORD = "directory-volume-fixture"
STAFF = 109
STAY_PER_STATUS = 104
REGISTERED = 1000
STAYS = {
    "正式在住": ("在住", "formal"),
    "试住中": ("在住", "trial"),
    TRIAL_PENDING: (TRIAL_PENDING, "trial"),
    "未入住": ("未入住", ""),
    "已退住": ("已退住", "formal"),
}


def populate_directory(store):
    # Bulk fixture data uses the same schema as live accounts without running the
    # password derivation and SMS sender for every synthetic account.
    salt = b"load-fixture-key"
    verifier = access._digest(PASSWORD, salt)
    staff = [
        (f"staff-{n:04d}", f"员工样本{n:04d}", "staff", "自定义", "", "[]")
        for n in range(STAFF - 2)
    ]
    staff.extend((
        ("directory-manager", "受托管理员", "staff", "自定义", "", '["staff.manage","residents"]'),
        ("clinical-employee", "临床员工", "staff", "护士", "", '["clinical"]'),
    ))
    registered = [
        (f"customer-{n:04d}", f"顾客样本{n:04d}", "family", portal.CUSTOMER_ROLE, "", "[]")
        for n in range(REGISTERED)
    ]
    related = []
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
        sample = state["residents"][0]
        for series, (status, stay) in enumerate(STAYS.values()):
            for n in range(STAY_PER_STATUS):
                number = f"{series}{n:03d}"
                rid = sample["id"] if number == "0000" else "load-resident-" + number
                if rid != sample["id"]:
                    state["residents"].append({
                        **sample, "id": rid, "name": "长辈样本" + number,
                        "status": status, "stayType": stay, "bedId": "",
                        "dischargedAt": store.now().date().isoformat() if status == "已退住" else "",
                    })
                related.append(("relative-" + number, "亲属样本" + number, "family", "亲属", rid, "[]"))
        db.execute("UPDATE workspace SET data=? WHERE id=1", (encode(state),))
        db.executemany(
            """INSERT INTO accounts(id,username,display_name,kind,role,resident_id,permissions,salt,password_hash)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            [(r[0], *r, salt, verifier) for r in (*staff, *related, *registered)],
        )
        db.execute("INSERT INTO identity_contacts VALUES('customer-0999','sms','+8613909999999',1)")


class AccountDirectoryTests(TestCase):
    def test_owner_and_manager_classification_with_large_catalog(self):
        with TemporaryDirectory() as root:
            store = Store(Path(root) / "directory.sqlite3", initial_owner_password=PASSWORD)
            populate_directory(store)
            owner, _ = store.login("owner", PASSWORD)
            data = store.snapshot(owner)["data"]
            accounts = data["accounts"]
            self.assertEqual(Counter(r["directoryGroup"] for r in accounts), {
                "owner": 1, "staff": STAFF, "stay": len(STAYS) * STAY_PER_STATUS,
                "registered": REGISTERED,
            })
            self.assertEqual(Counter(r["directoryStay"] for r in accounts if r["directoryGroup"] == "stay"),
                             dict.fromkeys(STAYS, STAY_PER_STATUS))
            self.assertNotIn("+8613909999999", repr(accounts))
            self.assertTrue(all("password_hash" not in r and "salt" not in r for r in accounts))
            self.assertEqual(data["residentRooms"]["r001"], "101")
            manager, _ = store.login("directory-manager", PASSWORD)
            managed = store.snapshot(manager)["data"]["accounts"]
            self.assertEqual(len(managed), STAFF - 2)
            self.assertTrue(all(r["directoryGroup"] == "staff" for r in managed))
            member, _ = store.login("relative-0000", PASSWORD)
            self.assertNotIn("accounts", store.snapshot(member)["data"])
