"""Administrative delivery of single-use password-reset links to account holders."""

from contextlib import closing
import hmac
import re
import secrets
import smtplib

from . import access, history, identity, staff_scope


def send(store, token, payload, origin):
    if set(payload) != {"id"}:
        raise ValueError("请选择一个账号")
    senders = dict(store.reset_link_senders)
    if identity.smtp_enabled():
        senders.setdefault("email", identity.send_reset_email)

    secret = secrets.token_urlsafe(32)
    proof = identity._tag(store, "reset-link", secret)
    now = int(store.now().timestamp())
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        access.require(actor, "staff.manage")
        boundary = staff_scope.boundary(db, actor, store.facility_policy)
        target = access._target(db, payload, actor, boundary)
        if target["kind"] == "owner" or not target["enabled"]:
            raise PermissionError("仅可为已启用的员工或顾客账号发送重置链接")
        if not origin:
            raise ValueError("请先设置账号本人可访问的机构 HTTPS 域名")
        if not senders:
            raise ValueError("机构尚未开通短信或邮箱重置链接投递")
        available = db.execute(
            """SELECT channel,destination FROM identity_contacts WHERE account_id=?
            AND (verified=1 OR (channel='sms' AND verified=0 AND ?)) ORDER BY channel DESC""",
            (target["id"], target["activationPending"]),
        )
        contact = next(((channel, address) for channel, address in available if channel in senders), None)
        if contact is None:
            raise ValueError("该账号没有可投递的已登记手机号或已验证邮箱")
        channel, address = contact
        db.execute("DELETE FROM identity_reset_links WHERE expires<=?", (now,))
        identity._limit(db, "reset-actor:" + actor["id"], now, 3600, 80, 0)
        identity._limit(db, "reset-target:" + target["id"], now, 3600, 5, 60)
        db.execute(
            "INSERT OR REPLACE INTO identity_reset_links VALUES(?,?,?,?,?,0)",
            (target["id"], proof, channel, address, now + identity.LIFETIME),
        )

    try:
        senders[channel](address, origin + "/#reset=" + secret)
    except (OSError, ValueError, KeyError, smtplib.SMTPException):
        with closing(store.connect()) as db, db:
            db.execute("DELETE FROM identity_reset_links WHERE proof=?", (proof,))
        raise ValueError("重置链接投递失败，请检查机构投递服务") from None

    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("UPDATE identity_reset_links SET delivered=1 WHERE proof=?", (proof,)).rowcount:
            raise ValueError("账号或投递地址已更新，请重新发送重置链接")
        identity._audit(store, db, actor["id"], "access.sendPasswordReset", "发送密码重置链接给 " + target["username"], subject=target)
    return {"sent": True, "channel": channel, "masked": identity.masked(channel, address)}


def redeem(store, payload):
    if set(payload) != {"token", "newPassword"}:
        raise ValueError("请填写新密码")
    token = payload["token"]
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ValueError("重置链接已失效，请重新申请")
    password = access._password(payload["newPassword"])
    proof = identity._tag(store, "reset-link", token)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            """SELECT a.id,a.username,a.salt,a.password_hash,l.channel FROM identity_reset_links l
            JOIN accounts a ON a.id=l.account_id AND a.enabled=1
            JOIN identity_contacts c ON c.account_id=a.id AND c.channel=l.channel AND c.destination=l.destination
            WHERE l.proof=? AND l.delivered=1 AND l.expires>?
            AND (c.verified=1 OR (c.channel='sms' AND c.verified=0 AND a.activation_pending=1))""",
            (proof, int(store.now().timestamp())),
        ).fetchone()
        if row is None:
            raise ValueError("重置链接已失效，请重新申请")
        aid, username, salt, digest, channel = row
        if hmac.compare_digest(access._digest(password, salt), digest):
            raise ValueError("新密码须与原密码不同")
        history.watch(db, "account.changePassword")
        access._replace_password(db, {"id": aid}, password)
        db.execute("UPDATE accounts SET activation_pending=0 WHERE id=?", (aid,))
        db.execute("UPDATE identity_contacts SET verified=1 WHERE account_id=? AND channel=?", (aid, channel))
        db.execute("DELETE FROM identity_challenges WHERE account_id=?", (aid,))
        return {
            "username": username,
            "revision": identity._audit(store, db, aid, "account.changePassword", "本人通过链接设置密码并结束全部原有会话"),
        }
