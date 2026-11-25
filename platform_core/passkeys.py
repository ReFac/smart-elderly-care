"""Optional, origin-bound WebAuthn credentials for authenticated accounts."""

from contextlib import closing
from importlib.util import find_spec
import json
import re
import secrets
from urllib.parse import urlsplit

from . import access, identity
from .secure_storage import INTEGRITY_ERRORS

LIFETIME = 120
MAX_KEYS = 12


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS identity_passkeys(
        id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
        origin TEXT NOT NULL, public_key BLOB NOT NULL, counter INTEGER NOT NULL, label TEXT NOT NULL,
        created TEXT NOT NULL, used TEXT NOT NULL DEFAULT '')""")
    db.execute("CREATE INDEX IF NOT EXISTS passkey_holder ON identity_passkeys(account_id,origin)")
    db.execute("""CREATE TABLE IF NOT EXISTS identity_passkey_challenges(
        id TEXT PRIMARY KEY, kind TEXT NOT NULL, account_id TEXT NOT NULL, origin TEXT NOT NULL,
        challenge BLOB NOT NULL, expires INTEGER NOT NULL)""")


def available(origin):
    return bool(origin and find_spec("webauthn"))


def _verified_phone(db, actor):
    return bool(db.execute(
        "SELECT 1 FROM identity_contacts WHERE account_id=? AND channel='sms' AND verified=1",
        (actor,),
    ).fetchone())


def listing(store, token, origin):
    if not available(origin):
        return {"enabled": False, "keys": []}
    with closing(store.connect()) as db:
        if not access.authenticate(db, token):
            return {"enabled": True, "keys": []}
        actor = store.actor(db, token)
        keys = db.execute(
            "SELECT id,label,created,used FROM identity_passkeys WHERE account_id=? AND origin=? ORDER BY created DESC",
            (actor["id"], origin),
        )
        return {"enabled": True, "phoneVerified": _verified_phone(db, actor["id"]), "keys": [dict(key) for key in keys]}


def _current_password(db, actor, payload):
    try:
        access.verify_current_password(db, actor, payload.get("currentPassword"))
    except access.SignaturePasswordDenied:
        db.commit()
        raise PermissionError("当前账号密码不正确") from None


def options(store, token, path, payload, origin, peer):
    from webauthn import generate_authentication_options, generate_registration_options, options_to_json
    from webauthn.helpers.structs import AuthenticatorSelectionCriteria, ResidentKeyRequirement, UserVerificationRequirement

    enroll = path == "enroll-options"
    if set(payload) != ({"currentPassword"} if enroll else set()):
        raise ValueError("通行密钥申请字段无效")
    now = int(store.now().timestamp())
    verification = UserVerificationRequirement.REQUIRED
    rp_id = urlsplit(origin).hostname
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor_id = ""
        if enroll:
            actor = store.actor(db, token)
            actor_id = actor["id"]
            _current_password(db, actor, payload)
            if not _verified_phone(db, actor_id):
                raise ValueError("请先验证本人手机号")
            if db.execute("SELECT count(*) FROM identity_passkeys WHERE account_id=?", (actor_id,)).fetchone()[0] >= MAX_KEYS:
                raise ValueError("通行密钥数量已达上限，请先移除旧密钥")
            opts = generate_registration_options(
                rp_id=rp_id, rp_name="医养管理平台", user_id=actor_id.encode(),
                user_name=actor["username"], user_display_name=actor["displayName"],
                authenticator_selection=AuthenticatorSelectionCriteria(
                    resident_key=ResidentKeyRequirement.REQUIRED, user_verification=verification,
                ),
            )
            db.execute("DELETE FROM identity_passkey_challenges WHERE kind=? AND account_id=? AND origin=?", (path, actor_id, origin))
        else:
            identity._limit(db, "passkey:" + identity._tag(store, peer).hex(), now, 120, 60, 0)
            opts = generate_authentication_options(rp_id=rp_id, user_verification=verification)
        ticket = secrets.token_urlsafe(24)
        db.execute("DELETE FROM identity_passkey_challenges WHERE expires<=?", (now,))
        db.execute("DELETE FROM identity_limits WHERE last<=?", (now - 3600,))
        db.execute("INSERT INTO identity_passkey_challenges VALUES(?,?,?,?,?,?)", (ticket, path, actor_id, origin, opts.challenge, now + LIFETIME))
        return {"ticket": ticket, "options": json.loads(options_to_json(opts))}


def finish(store, token, path, payload, origin):
    from webauthn import verify_authentication_response, verify_registration_response
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    from webauthn.helpers.exceptions import WebAuthnException

    enroll = path == "enroll"
    if set(payload) != ({"ticket", "credential", "label"} if enroll else {"ticket", "credential"}):
        raise ValueError("通行密钥提交字段无效")
    ticket, credential = payload["ticket"], payload["credential"]
    if not isinstance(ticket, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", ticket) or not isinstance(credential, dict):
        raise ValueError("通行密钥提交格式无效")
    credential_id = credential.get("id")
    if not isinstance(credential_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,1400}", credential_id):
        raise ValueError("通行密钥编号无效")
    label = access._required(payload["label"], "设备名称", 40) if enroll else ""
    time = store.now()
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor_id = store.actor(db, token)["id"] if enroll else ""
        row = db.execute(
            "SELECT challenge FROM identity_passkey_challenges WHERE id=? AND kind=? AND account_id=? AND origin=? AND expires>?",
            (ticket, path + "-options", actor_id, origin, int(time.timestamp())),
        ).fetchone()
        if not row:
            raise PermissionError("通行密钥请求已失效，请重试")
        db.execute("DELETE FROM identity_passkey_challenges WHERE id=?", (ticket,))
        proof = dict(credential=credential, expected_challenge=row["challenge"], expected_rp_id=urlsplit(origin).hostname,
                     expected_origin=origin, require_user_verification=True)
        try:
            if enroll:
                if not _verified_phone(db, actor_id):
                    raise ValueError("请先验证本人手机号")
                if db.execute("SELECT count(*) FROM identity_passkeys WHERE account_id=?", (actor_id,)).fetchone()[0] >= MAX_KEYS:
                    raise ValueError("通行密钥数量已达上限")
                key = verify_registration_response(**proof)
                db.execute(
                    "INSERT INTO identity_passkeys(id,account_id,origin,public_key,counter,label,created) VALUES(?,?,?,?,?,?,?)",
                    (bytes_to_base64url(key.credential_id), actor_id, origin, key.credential_public_key, key.sign_count, label, time.isoformat()),
                )
            else:
                key = db.execute(
                    """SELECT p.* FROM identity_passkeys p JOIN accounts a ON a.id=p.account_id
                    WHERE p.id=? AND p.origin=? AND a.enabled=1 AND a.activation_pending=0""",
                    (credential_id, origin),
                ).fetchone()
                if not key or not _verified_phone(db, key["account_id"]):
                    raise ValueError("未知或已停用的通行密钥")
                handle = credential.get("response", {}).get("userHandle")
                if not isinstance(handle, str) or base64url_to_bytes(handle) != key["account_id"].encode():
                    raise ValueError("账号与通行密钥不符")
                verified = verify_authentication_response(**proof, credential_public_key=key["public_key"], credential_current_sign_count=key["counter"])
                db.execute("UPDATE identity_passkeys SET counter=?,used=? WHERE id=?", (verified.new_sign_count, time.isoformat(), key["id"]))
                return access.issue_session(db, key["account_id"]), access.account(db, key["account_id"])
        except (WebAuthnException, ValueError, TypeError, KeyError, AttributeError, *INTEGRITY_ERRORS):
            db.commit()  # An invalid signed response cannot reuse its one-time challenge.
            raise PermissionError("未能验证通行密钥，请重试") from None
        return {"revision": identity._audit(store, db, actor_id, "account.addPasskey", "本人添加通行密钥")}


def revoke(store, token, payload, origin):
    if set(payload) != {"id", "currentPassword"} or not isinstance(payload["id"], str):
        raise ValueError("请选择要移除的通行密钥")
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        _current_password(db, actor, payload)
        if not db.execute("DELETE FROM identity_passkeys WHERE id=? AND account_id=? AND origin=?", (payload["id"], actor["id"], origin)).rowcount:
            raise ValueError("未找到此通行密钥")
        return {"revision": identity._audit(store, db, actor["id"], "account.removePasskey", "本人移除通行密钥")}
