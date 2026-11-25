"""Per-recipient consent and the in-platform family edition of a care round."""

import json
from uuid import uuid4

from . import access
from .care.records import lookup
from .dossier import text

CONSENT_METHODS = ("长辈当面确认", "长辈电话确认", "长辈书面确认")
CARE_FIELDS = ("planned", "completed", "pending", "overdue")


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS family_round_preferences(
        resident_id TEXT NOT NULL, account_id TEXT NOT NULL, allowed INTEGER NOT NULL DEFAULT 0,
        evidence TEXT NOT NULL DEFAULT '', method TEXT NOT NULL DEFAULT '', actor_id TEXT NOT NULL DEFAULT '',
        decided_at TEXT NOT NULL DEFAULT '', subscribed INTEGER NOT NULL DEFAULT 0,
        subscribed_at TEXT NOT NULL DEFAULT '', generation INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(resident_id,account_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS family_round_messages(
        id TEXT PRIMARY KEY, resident_id TEXT NOT NULL, account_id TEXT NOT NULL, day TEXT NOT NULL,
        report_id TEXT NOT NULL, generation INTEGER NOT NULL, content TEXT NOT NULL,
        sent_at TEXT NOT NULL, read_at TEXT NOT NULL DEFAULT '',
        UNIQUE(resident_id,account_id,day))""")
    db.execute("""CREATE INDEX IF NOT EXISTS family_round_inbox
        ON family_round_messages(account_id,resident_id,generation,day DESC)""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS family_round_unbind
        AFTER UPDATE OF enabled,resident_id,kind,role ON accounts
        WHEN OLD.kind='family' AND (NEW.enabled=0 OR OLD.resident_id<>NEW.resident_id OR
             NEW.kind<>OLD.kind OR NEW.role<>OLD.role)
        BEGIN UPDATE family_round_preferences SET allowed=0,subscribed=0,generation=generation+1
            WHERE account_id=OLD.id AND (allowed=1 OR subscribed=1); END""")


def _recipient(db, rid, aid):
    if (
        not isinstance(aid, str)
        or not db.execute(
            """SELECT 1 FROM accounts WHERE id=? AND resident_id=? AND kind='family'
           AND role='亲属' AND enabled=1""",
            (aid, rid),
        ).fetchone()
    ):
        raise PermissionError("请选择与这位长辈绑定的有效家属账号")


def _preference(db, rid, aid):
    return db.execute(
        "SELECT * FROM family_round_preferences WHERE resident_id=? AND account_id=?",
        (rid, aid),
    ).fetchone()


def _set_consent(db, rid, aid, p, user, timestamp):
    if user["kind"] == "family":
        if not user["portalSelf"] or user["residentId"] != rid:
            raise PermissionError("只可设置本人的长辈授权")
        method, evidence = "长辈本人账号确认", ""
    else:
        access.require(user, "family.share")
        access.require(user, "relatives")
        method = text(p, "method", 30, required=True).replace("长者", "长辈")
        if method not in CONSENT_METHODS:
            raise ValueError("请选择长辈确认意愿的方式")
        evidence = text(p, "evidence", 240, required=True)
    allowed = p.get("enabled")
    if type(allowed) is not bool:
        raise ValueError("请确认长辈分享意愿")
    db.execute(
        """INSERT INTO family_round_preferences(resident_id,account_id,allowed,method,evidence,actor_id,decided_at)
           VALUES(?,?,?,?,?,?,?) ON CONFLICT(resident_id,account_id) DO UPDATE SET
           generation=generation+(allowed=1 AND excluded.allowed=0), allowed=excluded.allowed,
           method=excluded.method,evidence=excluded.evidence,actor_id=excluded.actor_id,decided_at=excluded.decided_at""",
        (rid, aid, allowed, method, evidence, user["id"], timestamp),
    )
    return ("同意" if allowed else "撤回") + "向指定家属分享每日巡查简报"


def apply(db, state, action, p, user, now):
    rid = text(p, "residentId", 80, required=True)
    if (
        action in ("family.consent", "family.subscribe")
        and p.get("enabled") is True
        and lookup(state, "residents", rid)["status"] != "在住"
    ):
        raise ValueError("仅在住长辈可启用每日巡查分享")
    if user["kind"] == "family" and user["residentId"] != rid:
        raise PermissionError("仅可管理本人绑定的长辈")
    lookup(state, "residents", rid)
    timestamp = now.isoformat(timespec="seconds")
    if action == "family.consent":
        aid = p.get("accountId")
        _recipient(db, rid, aid)
        return _set_consent(db, rid, aid, p, user, timestamp)
    aid = user["id"]
    if p.get("accountId", aid) != aid:
        raise PermissionError("仅可操作本人的订阅和消息")
    _recipient(db, rid, aid)
    if action == "family.subscribe":
        active = p.get("enabled")
        if type(active) is not bool:
            raise ValueError("请选择是否接收简报")
        db.execute(
            """INSERT INTO family_round_preferences(resident_id,account_id,subscribed,subscribed_at)
               VALUES(?,?,?,?) ON CONFLICT(resident_id,account_id) DO UPDATE SET
               generation=generation+(subscribed=1 AND excluded.subscribed=0),
               subscribed=excluded.subscribed,subscribed_at=excluded.subscribed_at""",
            (rid, aid, active, timestamp),
        )
        return ("订阅" if active else "取消订阅") + "每日巡查站内简报"
    if action == "family.read":
        result = db.execute(
            """UPDATE family_round_messages SET read_at=CASE WHEN read_at='' THEN ? ELSE read_at END
              WHERE id=? AND resident_id=? AND account_id=? AND generation=(
                SELECT generation FROM family_round_preferences WHERE resident_id=? AND account_id=?
                   AND allowed=1 AND subscribed=1)""",
            (timestamp, text(p, "messageId", 80, True), rid, aid, rid, aid),
        )
        if not result.rowcount:
            raise PermissionError("这份简报已不可查阅")
        return "家属已阅读每日巡查站内简报"
    raise ValueError("未登记的家属操作")


def deliver(db, state, report, now):
    """Caller supplies the committed evidence and holds a transaction at the scheduled hour."""
    rid, day = report["residentId"], report["day"]
    if day != now.date().isoformat() or not any(
        r["id"] == rid and r["status"] == "在住" for r in state["residents"]
    ):
        return 0
    today = {field: report["today"][field] for field in CARE_FIELDS}
    if any(type(v) is not int or v < 0 for v in today.values()):
        raise ValueError("巡查简报的工单统计无效")
    trend = report.get("cough") or {}
    elevated = trend.get("noticeable", trend.get("status") == "elevated")
    content = json.dumps(
        {"today": today, "coughIncreased": elevated}, ensure_ascii=False
    )
    rows = db.execute(
        """SELECT p.account_id,p.generation FROM family_round_preferences p
           JOIN accounts a ON a.id=p.account_id AND a.resident_id=p.resident_id
           WHERE p.resident_id=? AND p.allowed=1 AND p.subscribed=1
             AND a.kind='family' AND a.role='亲属' AND a.enabled=1""",
        (rid,),
    )
    sent = 0
    for account_id, generation in rows:
        receipt = db.execute(
            """INSERT INTO family_round_messages(id,resident_id,account_id,day,report_id,generation,content,sent_at)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(resident_id,account_id,day) DO NOTHING""",
            (
                uuid4().hex,
                rid,
                account_id,
                day,
                report["id"],
                generation,
                content,
                now.isoformat(timespec="seconds"),
            ),
        )
        sent += receipt.rowcount
    return sent


def project(db, data, user):
    """Current campus projection limits staff roster; each portal gets its own mailbox."""
    visible = {r["id"] for r in data["residents"]}
    if user["kind"] == "family" and not user["portalSelf"]:
        rid, aid = user["residentId"], user["id"]
        if rid not in visible:
            return
        prefs = _preference(db, rid, aid)
        allowed = bool(prefs and prefs["allowed"])
        subscribed = bool(prefs and prefs["subscribed"])
        messages = []
        if allowed and subscribed:
            for row in db.execute(
                """SELECT id,day,content,sent_at,read_at FROM family_round_messages
                   WHERE resident_id=? AND account_id=? AND generation=? ORDER BY day DESC LIMIT 60""",
                (rid, aid, prefs["generation"]),
            ):
                messages.append(
                    {
                        "id": row["id"],
                        "day": row["day"],
                        "sentAt": row["sent_at"],
                        "readAt": row["read_at"],
                        **json.loads(row["content"]),
                    }
                )
        data["familyRoundInbox"] = {
            "allowed": allowed,
            "subscribed": subscribed,
            "messages": messages,
        }
        return
    if "family.consent" not in data["allowedActions"]:
        return
    rows = db.execute(
        """SELECT a.id,a.resident_id,a.display_name,p.allowed,p.method,p.subscribed,p.decided_at,p.evidence
           FROM accounts a LEFT JOIN family_round_preferences p ON p.account_id=a.id AND p.resident_id=a.resident_id
           WHERE a.kind='family' AND a.role='亲属' AND a.enabled=1 ORDER BY a.display_name,a.id"""
    )
    data["familyRoundRecipients"] = [
        {
            "accountId": aid,
            "residentId": rid,
            "name": name,
            "allowed": bool(allowed),
            "method": (method or "").replace("长者", "长辈"),
            "decidedAt": decided or "",
            "subscribed": bool(subscribed),
            **({"evidence": evidence or ""} if user["kind"] != "family" else {}),
        }
        for aid, rid, name, allowed, method, subscribed, decided, evidence in rows
        if rid in visible
    ]
