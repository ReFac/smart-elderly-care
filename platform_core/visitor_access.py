"""Phone-verified sessions for the public tour, separate from workspace accounts."""

from contextlib import closing
import hmac
import re
import secrets

from . import access, identity

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
      demo INTEGER NOT NULL)""")


def _tag(store, *parts):
    return identity._tag(store, "public-tour", *parts)


def _clock(store):
    return int(store.now().timestamp())


def status(store, visitor_token, account_token, *, demo=False):
    output = {
        "signedIn": False,
        "phoneEnabled": "sms" in identity.senders(store),
        "wechatEnabled": False,
        "demoEnabled": demo,
    }
    with closing(store.connect()) as db:
        if account_token and access.authenticate(db, account_token):
            output["signedIn"] = True
        elif visitor_token and len(visitor_token) <= 100:
            session = db.execute(
                "SELECT masked,demo FROM visitor_sessions WHERE proof=? AND expires>?",
                (_tag(store, "session", visitor_token), _clock(store)),
            ).fetchone()
            if session and (not session["demo"] or demo):
                output.update(signedIn=True, maskedPhone=session["masked"])
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
                token = secrets.token_urlsafe(32)
                db.execute("DELETE FROM visitor_challenges WHERE id=?", (challenge,))
                db.execute(
                    "INSERT INTO visitor_sessions VALUES(?,?,?,?)",
                    (_tag(store, "session", token), identity.masked("sms", row["phone"]),
                     now + SESSION_TTL, row["demo"]),
                )
    if not token:
        raise ValueError("验证码无效或已过期")
    return token
