"""Verified contact enrollment and password recovery. Delivery belongs to the host."""

from contextlib import closing
from email.message import EmailMessage
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import ssl
import time
from threading import BoundedSemaphore, Thread
from uuid import uuid4

from . import access, activity, history, secure_storage

LIFETIME = 600
MAX_TRIES = 5
CHANNELS = ("email", "sms")
_delivery_slots = BoundedSemaphore(2)


def init(db):
    from . import passkeys

    db.execute("""CREATE TABLE IF NOT EXISTS identity_contacts(
        account_id TEXT NOT NULL REFERENCES accounts(id), channel TEXT NOT NULL,
        destination TEXT NOT NULL, verified INTEGER NOT NULL,
        PRIMARY KEY(account_id,channel))""")
    db.execute("""CREATE TABLE IF NOT EXISTS identity_challenges(
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id), purpose TEXT NOT NULL,
        channel TEXT NOT NULL, destination TEXT NOT NULL, proof BLOB NOT NULL,
        expires INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, delivered INTEGER NOT NULL DEFAULT 0)""")
    db.execute(
        "CREATE INDEX IF NOT EXISTS identity_expiry ON identity_challenges(expires)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS identity_limits(
        subject TEXT PRIMARY KEY, since INTEGER NOT NULL, last INTEGER NOT NULL, count INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS identity_reset_links(
        account_id TEXT PRIMARY KEY REFERENCES accounts(id), proof BLOB NOT NULL UNIQUE,
        channel TEXT NOT NULL, destination TEXT NOT NULL, expires INTEGER NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0)""")
    passkeys.init(db)


def destination(channel, raw):
    if not isinstance(raw, str) or len(raw) > 254:
        raise ValueError("请填写有效的验证联系方式")
    raw = raw.strip()
    if channel == "email" and re.fullmatch(
        r"[A-Za-z0-9_%+.-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", raw
    ):
        name, domain = raw.rsplit("@", 1)
        if (
            len(name) <= 64
            and not name.startswith(".")
            and not name.endswith(".")
            and ".." not in name
        ):
            return name + "@" + domain.lower()
    if channel == "sms":
        from .profile_fields import phone_number
        raw = phone_number(raw, mobile=True)
        if re.fullmatch(r"1[3-9][0-9]{9}", raw):
            raw = "+86" + raw
        if re.fullmatch(r"\+[1-9][0-9]{7,14}", raw):
            return raw
    raise ValueError("请填写有效邮箱，或含国家区号的手机号")


def masked(channel, value):
    if channel == "email":
        name, domain = value.rsplit("@", 1)
        return name[0] + "***@" + domain
    return "****" + value[-4:]


def contacts(db, aid):
    return [
        {"channel": r[0], "masked": masked(r[0], r[1]), "verified": bool(r[2])}
        for r in db.execute(
            "SELECT channel,destination,verified FROM identity_contacts WHERE account_id=? AND verified>=0 ORDER BY channel",
            (aid,),
        )
    ]


def smtp_enabled():
    return bool(os.environ.get("NH_SMTP_HOST") and os.environ.get("NH_SMTP_FROM"))


def send_email(address, code):
    _deliver_email(
        address, "医养管理平台 · 账号验证码",
        f"验证码为 {code}，10 分钟内有效。如非本人操作，可忽略本邮件。请勿向他人提供验证码。",
    )


def send_reset_email(address, link):
    _deliver_email(
        address, "医养管理平台 · 设置账号密码",
        f"请在 10 分钟内通过以下链接设置自己的密码：\n\n{link}\n\n如非本人操作，可忽略本邮件。请勿转发此链接。",
    )


def _deliver_email(address, subject, content):
    sender = destination("email", os.environ["NH_SMTP_FROM"])
    mode = os.environ.get("NH_SMTP_TLS", "ssl")
    if mode not in ("ssl", "starttls"):
        raise ValueError("邮件投递必须使用 TLS")
    host = os.environ["NH_SMTP_HOST"]
    port = int(os.environ.get("NH_SMTP_PORT", 465 if mode == "ssl" else 587))
    context = ssl.create_default_context()
    client = (
        smtplib.SMTP_SSL(host, port, timeout=8, context=context)
        if mode == "ssl"
        else smtplib.SMTP(host, port, timeout=8)
    )
    with client:
        if mode == "starttls":
            client.starttls(context=context)
        username = os.environ.get("NH_SMTP_USER")
        if username:
            client.login(username, os.environ["NH_SMTP_PASSWORD"])
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, address, subject
        msg.set_content(content)
        client.send_message(msg)


def senders(store):
    choices = dict(store.code_senders)
    if smtp_enabled():
        choices.setdefault("email", send_email)
    return choices


def _tag(store, *parts):
    key = secure_storage.derive(store._storage_master, b"identity-verification")
    return hmac.new(key, "\0".join(parts).encode(), hashlib.sha256).digest()


def _limit(db, subject, now, window, max_count, gap):
    row = db.execute(
        "SELECT since,last,count FROM identity_limits WHERE subject=?", (subject,)
    ).fetchone()
    if row and now - row[0] < window and (now - row[1] < gap or row[2] >= max_count):
        raise access.LoginThrottled("验证码请求过于频繁，请稍后再试")
    since, count = (row[0], row[2] + 1) if row and now - row[0] < window else (now, 1)
    db.execute(
        "INSERT OR REPLACE INTO identity_limits VALUES(?,?,?,?)",
        (subject, since, now, count),
    )


def _check(db, store, challenge, code, purpose, now, *, aid=None):
    row = db.execute(
        """SELECT c.* FROM identity_challenges c JOIN accounts a ON c.account_id=a.id
        WHERE c.id=? AND c.purpose=? AND c.delivered=1 AND a.enabled=1""",
        (challenge, purpose),
    ).fetchone()
    if (
        not row
        or (aid and row["account_id"] != aid)
        or row["expires"] <= now
        or row["attempts"] >= MAX_TRIES
    ):
        raise ValueError("验证码无效、已使用或已过期")
    db.execute(
        "UPDATE identity_challenges SET attempts=attempts+1 WHERE id=?", (challenge,)
    )
    if (
        not isinstance(code, str)
        or not re.fullmatch(r"[0-9]{8}", code)
        or not hmac.compare_digest(_tag(store, challenge, code), row["proof"])
    ):
        db.commit()  # Incorrect guesses survive the rejected request.
        raise ValueError("验证码不正确或已达尝试上限")
    return row


def _audit(store, db, aid, action, message, *, subject=None):
    actor = access.account(db, aid)
    revision = db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0] + 1
    db.execute("UPDATE workspace SET revision=? WHERE id=1", (revision,))
    person = actor if subject is None else subject
    scope = {"residentId": person["residentId"]} if person["residentId"] else {}
    activity.write(
        db, revision, store.now().isoformat(), action, message, actor, scope, {}
    )
    return revision


def _password_target(db, store, payload, channel, now):
    username = payload.get("username")
    if not isinstance(username, str) or not 1 <= len(username.strip()) <= 40:
        raise ValueError("请填写登录账号")
    account = db.execute(
        "SELECT id FROM accounts WHERE username=? AND enabled=1",
        (username.strip(),),
    ).fetchone()
    aid = account[0] if account else None
    # Use the same throttle and response for registered and unknown usernames.
    _limit(
        db,
        "name:" + _tag(store, username.strip().lower()).hex(),
        now,
        3600,
        6,
        60,
    )
    entry = db.execute(
        "SELECT destination FROM identity_contacts WHERE account_id=? AND channel=? AND verified>=0",
        (aid, channel),
    ).fetchone()
    dst = entry[0] if entry else None
    return aid, dst


def _binding_target(db, store, token, payload, channel, purpose, now, host_owner):
    actor = (
        access.account(
            db,
            db.execute("SELECT id FROM accounts WHERE kind='owner'").fetchone()[0],
        )
        if host_owner
        else store.actor(db, token)
    )
    aid = actor["id"]
    _limit(db, "bind:" + aid + ":" + purpose, now, 3600, 6, 60)
    registered = contacts(db, aid)
    if purpose == "verifyContact":
        if host_owner:
            raise ValueError("请从个人账号操作")
        entry = db.execute(
            "SELECT destination FROM identity_contacts WHERE account_id=? AND channel=? AND verified=1",
            (aid, channel),
        ).fetchone()
        if not entry:
            raise ValueError("请选择本人已核实的验证渠道")
        dst = entry[0]
    else:
        dst = destination(channel, payload.get("destination"))
        if host_owner and registered:
            raise PermissionError("本机首次绑定仅适用于没有恢复渠道的 Owner")
        if not host_owner:
            current = payload.get("currentPassword")
            row = db.execute(
                "SELECT salt,password_hash FROM accounts WHERE id=?", (aid,)
            ).fetchone()
            if (
                not isinstance(current, str)
                or not 1 <= len(current) <= 128
                or not hmac.compare_digest(access._digest(current, row[0]), row[1])
            ):
                db.commit()
                raise ValueError("当前密码不正确")
            if registered:
                old = _check(
                    db,
                    store,
                    payload.get("existingChallenge"),
                    payload.get("existingCode"),
                    "verifyContact",
                    now,
                    aid=aid,
                )
                db.execute("DELETE FROM identity_challenges WHERE id=?", (old["id"],))
    return aid, dst


def request_code(
    store, payload, *, token=None, peer="local", host_owner=False, background=False
):
    if not isinstance(payload, dict) or set(payload) - {
        "username",
        "purpose",
        "channel",
        "destination",
        "currentPassword",
        "existingChallenge",
        "existingCode",
    }:
        raise ValueError("验证码申请格式无效")
    purpose = payload.get("purpose")
    channel = payload.get("channel")
    if purpose not in ("password", "bind", "verifyContact") or channel not in CHANNELS:
        raise ValueError("请选择验证方式")
    for key in ("destination", "currentPassword", "existingChallenge", "existingCode"):
        if key in payload and (
            not isinstance(payload[key], str) or len(payload[key]) > 254
        ):
            raise ValueError("验证码申请字段无效")
    sender = senders(store).get(channel)
    if sender is None:
        raise ValueError("机构尚未接通此验证渠道")
    background = background and purpose == "password"
    if background and not _delivery_slots.acquire(blocking=False):
        raise access.LoginThrottled("验证码投递服务正忙，请稍后再试")
    dispatched = False
    try:
        challenge, code, dst = _issue_challenge(store, payload, purpose, channel, token, peer, host_owner)
        if dst:
            def deliver():
                try:
                    _deliver_challenge(store, sender, dst, code, purpose, challenge)
                finally:
                    if background:
                        _delivery_slots.release()

            if background:
                try:
                    Thread(target=deliver, name="identity-mail", daemon=True).start()
                except RuntimeError:
                    raise access.LoginThrottled("验证码投递服务正忙，请稍后再试") from None
                dispatched = True
            else:
                deliver()
        return {"challenge": challenge, "expiresIn": LIFETIME}
    finally:
        if background and not dispatched:
            _delivery_slots.release()


def _issue_challenge(store, payload, purpose, channel, token, peer, host_owner):
    challenge = uuid4().hex
    code = f"{secrets.randbelow(100_000_000):08d}"
    now = int(time.time())
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM identity_challenges WHERE expires<=?", (now,))
        db.execute("DELETE FROM identity_limits WHERE last<=?", (now - 3600,))
        _limit(db, "ip:" + _tag(store, peer).hex(), now, 3600, 120, 0)
        if purpose == "password":
            aid, dst = _password_target(db, store, payload, channel, now)
        else:
            aid, dst = _binding_target(
                db, store, token, payload, channel, purpose, now, host_owner
            )
        if dst:
            _limit(db, "target:" + _tag(store, channel, dst).hex(), now, 3600, 12, 0)
            db.execute(
                "DELETE FROM identity_challenges WHERE account_id=? AND purpose=?",
                (aid, purpose),
            )
            db.execute(
                "INSERT INTO identity_challenges(id,account_id,purpose,channel,destination,proof,expires) VALUES(?,?,?,?,?,?,?)",
                (
                    challenge,
                    aid,
                    purpose,
                    channel,
                    dst,
                    _tag(store, challenge, code),
                    now + LIFETIME,
                ),
            )

    return challenge, code, dst


def _deliver_challenge(store, sender, dst, code, purpose, challenge):
    try:
        sender(dst, code)
    except (OSError, ValueError, KeyError, smtplib.SMTPException):
        with closing(store.connect()) as db, db:
            db.execute("DELETE FROM identity_challenges WHERE id=?", (challenge,))
        if purpose != "password":
            raise ValueError("渠道未能投递，请检查机构验证服务后重试") from None
    else:
        with closing(store.connect()) as db, db:
            db.execute("UPDATE identity_challenges SET delivered=1 WHERE id=?", (challenge,))


def finish(store, payload, *, token=None, host_owner=False):
    if not isinstance(payload, dict) or set(payload) - {
        "purpose",
        "challenge",
        "code",
        "newPassword",
    }:
        raise ValueError("验证码提交格式无效")
    purpose = payload.get("purpose")
    if purpose not in ("password", "bind") or not isinstance(
        payload.get("challenge"), str
    ):
        raise ValueError("验证码提交格式无效")
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        aid = None
        if purpose == "bind":
            aid = (
                db.execute("SELECT id FROM accounts WHERE kind='owner'").fetchone()[0]
                if host_owner
                else store.actor(db, token)["id"]
            )
        row = _check(
            db,
            store,
            payload["challenge"],
            payload.get("code"),
            purpose,
            int(time.time()),
            aid=aid,
        )
        aid = row["account_id"]
        action = (
            "account.bindContact" if purpose == "bind" else "account.changePassword"
        )
        history.watch(db, action)
        if purpose == "bind":
            if host_owner and contacts(db, aid):
                raise ValueError("请从本人账号更新已绑定的方式")
            db.execute("DELETE FROM identity_reset_links WHERE account_id=?", (aid,))
            db.execute(
                "INSERT OR REPLACE INTO identity_contacts VALUES(?,?,?,1)",
                (aid, row["channel"], row["destination"]),
            )
            if row["channel"] == "sms":
                from . import lead_contacts
                from .store import encode

                state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
                events = len(state.get("leadEvents", ()))
                lead_contacts.reconcile_callbacks(db, state, store.now())
                if len(state.get("leadEvents", ())) != events:
                    db.execute("UPDATE workspace SET data=? WHERE id=1", (encode(state),))
            message = "本人已验证安全联系方式"
        else:
            new = access._password(payload.get("newPassword"))
            current = db.execute(
                "SELECT salt,password_hash FROM accounts WHERE id=?", (aid,)
            ).fetchone()
            if hmac.compare_digest(access._digest(new, current[0]), current[1]):
                raise ValueError("新密码须与原密码不同")
            entry = db.execute(
                "SELECT destination FROM identity_contacts WHERE account_id=? AND channel=? AND verified>=0",
                (aid, row["channel"]),
            ).fetchone()
            if not entry or entry[0] != row["destination"]:
                raise ValueError("验证渠道已变化，请重新申请")
            message = "本人通过验证码设置密码并结束全部登录会话"
            db.execute("UPDATE accounts SET activation_pending=0 WHERE id=?", (aid,))
            access._replace_password(db, access.account(db, aid), new)
            db.execute(
                "UPDATE identity_contacts SET verified=1 WHERE account_id=? AND channel=? AND verified>=0",
                (aid, row["channel"]),
            )
        db.execute("DELETE FROM identity_challenges WHERE account_id=?", (aid,))
        return {"revision": _audit(store, db, aid, action, message)}
