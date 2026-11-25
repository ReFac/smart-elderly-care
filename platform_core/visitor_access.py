"""Self-service customer accounts and isolated SMS tour sessions."""

from contextlib import closing
import hmac
import re
import secrets
from uuid import uuid4

from . import access, activity, history, identity, portal, wechat_tour

DEMO_PHONE = "+8613900000000"
CODE_TTL = 300
SESSION_TTL = 30 * 24 * 60 * 60


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS visitor_challenges(
      id TEXT PRIMARY KEY, phone TEXT NOT NULL, proof BLOB NOT NULL,
      expires INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
      ready INTEGER NOT NULL DEFAULT 0, demo INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS visitor_sessions(
      proof BLOB PRIMARY KEY, masked TEXT NOT NULL, expires INTEGER NOT NULL,
      demo INTEGER NOT NULL, account_id TEXT REFERENCES accounts(id))""")
    if "account_id" not in {r[1] for r in db.execute("PRAGMA table_info(visitor_sessions)")}:
        db.execute("ALTER TABLE visitor_sessions ADD COLUMN account_id TEXT REFERENCES accounts(id)")
        db.execute("DELETE FROM visitor_sessions WHERE demo=0")
    db.execute("CREATE INDEX IF NOT EXISTS visitor_session_account ON visitor_sessions(account_id)")
    db.execute("""CREATE INDEX IF NOT EXISTS identity_sms_number
      ON identity_contacts(destination) WHERE channel='sms' AND verified>=0""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS visitor_revoke_disabled
      AFTER UPDATE OF enabled ON accounts WHEN NEW.enabled=0 BEGIN
        DELETE FROM visitor_sessions WHERE account_id=NEW.id;
      END""")


def _tag(store, *parts):
    return identity._tag(store, "public-tour", *parts)


def _clock(store):
    return int(store.now().timestamp())


def status(store, visitor_token, account_token, *, demo=False):
    output = {
        "signedIn": False,
        "phoneEnabled": "sms" in identity.senders(store),
        "wechatEnabled": False,
        "wechatContactLink": wechat_tour.contact_link(),
        "demoEnabled": demo,
    }
    with closing(store.connect()) as db:
        user = access.authenticate(db, account_token) if account_token else None
        if user:
            output["signedIn"] = True
            if portal.is_customer(user):
                output["customerUsername"] = user["username"]
        elif visitor_token and len(visitor_token) <= 100:
            session = db.execute(
                """SELECT s.masked,s.demo,a.username,a.kind,a.role FROM visitor_sessions s
                LEFT JOIN accounts a ON a.id=s.account_id
                WHERE s.proof=? AND s.expires>? AND (s.account_id IS NULL OR a.enabled=1)""",
                (_tag(store, "session", visitor_token), _clock(store)),
            ).fetchone()
            if session and (not session["demo"] or demo):
                output.update(signedIn=True, maskedPhone=session["masked"])
                if session["kind"] == "family" and session["role"] == portal.CUSTOMER_ROLE:
                    output["customerUsername"] = session["username"]
    return output


def request_code(store, payload, peer, *, demo=False):
    if set(payload) != {"phone"}:
        raise ValueError("请填写手机号")
    phone = identity.destination("sms", payload["phone"])
    simulated = demo and phone == DEMO_PHONE
    sender = identity.senders(store).get("sms")
    if not (sender or simulated):
        raise ValueError("短信登录暂未开通")
    now = _clock(store)
    challenge = secrets.token_hex(20)
    code = f"{secrets.randbelow(100_000_000):08d}"
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM identity_limits WHERE last<=?", (now - 3600,))
        db.execute("DELETE FROM visitor_challenges WHERE expires<=?", (now,))
        db.execute("DELETE FROM visitor_sessions WHERE expires<=?", (now,))
        identity._limit(db, "visit-ip:" + _tag(store, peer).hex(), now, 3600, 30, 0)
        identity._limit(db, "visit-num:" + _tag(store, phone).hex(), now, 3600, 5, 60)
        db.execute("DELETE FROM visitor_challenges WHERE phone=? AND demo=?", (phone, int(simulated)))
        db.execute(
            "INSERT INTO visitor_challenges(id,phone,proof,expires,demo) VALUES(?,?,?,?,?)",
            (challenge, phone, _tag(store, challenge, code), now + CODE_TTL, int(simulated)),
        )
    try:
        if not simulated:
            sender(phone, code)
    except (OSError, ValueError, KeyError):
        with closing(store.connect()) as db, db:
            db.execute("DELETE FROM visitor_challenges WHERE id=?", (challenge,))
        raise ValueError("验证码暂未投递成功，请稍后重试") from None
    with closing(store.connect()) as db, db:
        db.execute("UPDATE visitor_challenges SET ready=1 WHERE id=?", (challenge,))
    result = {"challengeId": challenge, "retryAfter": 60, "expiresIn": CODE_TTL}
    if simulated:
        result["demoCode"] = code
    return result


def _verified_account(store, db, phone):
    row = db.execute(
        """SELECT a.id,a.enabled FROM identity_contacts c JOIN accounts a ON a.id=c.account_id
        WHERE c.channel='sms' AND c.verified>=0 AND c.destination=?
        ORDER BY a.enabled DESC, c.verified DESC, (a.role=?) ASC, a.id LIMIT 1""",
        (phone, portal.CUSTOMER_ROLE),
    ).fetchone()
    if row:
        return row["id"] if row["enabled"] else None
    aid = uuid4().hex
    salt = secrets.token_bytes(16)
    return _new_customer(store, db, aid, "visitor-" + aid[:20], salt,
                         access._digest(secrets.token_urlsafe(32), salt), verified_phone=phone)


def _new_customer(store, db, aid, username, salt, password_hash, *, verified_phone=None):
    history.watch(db, "access.registerCustomer")
    inserted = db.execute(
        """INSERT INTO accounts(id,username,display_name,kind,role,salt,password_hash)
        VALUES(?,?,?,'family',?,?,?) ON CONFLICT(username) DO NOTHING""",
        (aid, username, "参观顾客", portal.CUSTOMER_ROLE, salt, password_hash),
    )
    if not inserted.rowcount:
        raise ValueError("此登录名已被使用")
    if verified_phone:
        db.execute("INSERT INTO identity_contacts VALUES(?,'sms',?,1)", (aid, verified_phone))
    revision = db.execute("UPDATE workspace SET revision=revision+1 WHERE id=1 RETURNING revision").fetchone()[0]
    activity.write(
        db, revision, store.now().isoformat(), "access.registerCustomer",
        "顾客通过环境导览验证手机号后注册" if verified_phone else "顾客通过公开页面自行注册",
        access.account(db, aid), {}, {},
    )
    return aid


def register(store, payload, peer, current_session=None):
    if not isinstance(payload, dict) or set(payload) != {"username", "password"}:
        raise ValueError("请仅填写登录名和密码")
    username = access.account_username(payload["username"])
    password = access._password(payload["password"])
    store.public_submissions.check(("registration", peer))
    with closing(store.connect()) as db, db:
        if access.authenticate(db, current_session):
            raise PermissionError("请先退出当前账号再注册顾客账号")
        salt = secrets.token_bytes(16)
        password_hash = access._digest(password, salt)
        db.execute("BEGIN IMMEDIATE")
        aid = _new_customer(store, db, uuid4().hex, username, salt, password_hash)
        return access.issue_session(db, aid), access.account(db, aid)


def verify(store, payload, peer, *, demo=False):
    if set(payload) != {"challengeId", "code"}:
        raise ValueError("请填写验证码")
    challenge, code = payload["challengeId"], payload["code"]
    if not isinstance(challenge, str) or not re.fullmatch(r"[0-9a-f]{40}", challenge):
        raise ValueError("验证码无效或已过期")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{8}", code):
        raise ValueError("请填写 8 位验证码")
    now, token = _clock(store), None
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        identity._limit(db, "visit-verify:" + _tag(store, peer).hex(), now, 3600, 90, 0)
        row = db.execute(
            """SELECT * FROM visitor_challenges WHERE id=? AND ready=1
            AND expires>? AND attempts<? AND (demo=0 OR ?)""",
            (challenge, now, identity.MAX_TRIES, int(demo)),
        ).fetchone()
        if row:
            db.execute("UPDATE visitor_challenges SET attempts=attempts+1 WHERE id=?", (challenge,))
            if hmac.compare_digest(row["proof"], _tag(store, challenge, code)):
                db.execute("DELETE FROM visitor_challenges WHERE id=?", (challenge,))
                aid = None if row["demo"] else _verified_account(store, db, row["phone"])
                if row["demo"] or aid:
                    token = secrets.token_urlsafe(32)
                    db.execute(
                        "INSERT INTO visitor_sessions(proof,masked,expires,demo,account_id) VALUES(?,?,?,?,?)",
                        (_tag(store, "session", token), identity.masked("sms", row["phone"]),
                         now + SESSION_TTL, row["demo"], aid),
                    )
    if not token:
        raise ValueError("验证码无效或已过期")
    return token
