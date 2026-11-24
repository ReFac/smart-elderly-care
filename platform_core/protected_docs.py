"""Authenticated document downloads tied to current institution, role and consent."""

from contextlib import closing
from hashlib import sha256
import json
import secrets

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from . import access, activity, campus_access
from .secure_storage import derive

MAGIC = b"ANKANG-DOCUMENT\x01"
MAX_PACKET = 16 * 1024 * 1024


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS protected_documents(
        content_hash BLOB PRIMARY KEY, packet_hash BLOB UNIQUE NOT NULL, packet BLOB NOT NULL
    )""")


def validate(spec):
    kind = spec.get("kind")
    if kind == "referral":
        if not isinstance(spec.get("exportId"), str) or set(spec) != {
            "kind",
            "id",
            "exportId",
        }:
            raise ValueError("请指定转介导出凭证")
    elif kind == "report":
        if (
            type(spec.get("version")) is not int
            or spec["version"] < 1
            or set(spec) != {"kind", "id", "version"}
        ):
            raise ValueError("请指定报送版本")
    else:
        raise ValueError("请选择转介包或民政报表")
    if not isinstance(spec.get("id"), str) or not spec["id"]:
        raise ValueError("请指定有效记录")


def authorise(db, state, actor, spec):
    if spec["kind"] == "report":
        access.require(actor, "reports")
        report = next((r for r in state["reports"] if r["id"] == spec["id"]), None)
        if not report:
            raise FileNotFoundError("没有找到报送记录")
        return report, {}
    access.require(actor, "clinical")
    ref = next((r for r in state["referrals"] if r["id"] == spec["id"]), None)
    if not ref:
        raise FileNotFoundError("没有找到转介记录")
    campus_access.require_resident(db, actor, ref["residentId"], state)
    history = ref.get("consents", [])
    receipt = next(
        (e for e in ref.get("exports", []) if e["id"] == spec["exportId"]), None
    )
    if (
        not history
        or history[-1]["decision"] != "同意"
        or receipt is None
        or receipt["consentNumber"] != len(history)
    ):
        raise PermissionError("该交接包的本人授权已失效或尚未登记")
    return receipt["content"], activity.for_person(state, ref["residentId"])


def export(store, token, spec, revision=None):
    from .store import Conflict

    validate(spec)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        from . import history

        history.watch(db, "document.export")
        rev, data = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        record, scope = authorise(db, json.loads(data), actor, spec)
        if spec["kind"] == "report":
            submitted = next(
                (
                    s
                    for s in record.get("submissions", [])
                    if s["version"] == spec["version"]
                ),
                None,
            )
            if submitted:
                record = submitted["snapshot"]
            elif spec["version"] != record.get("version", 1):
                raise FileNotFoundError("没有找到此报送版本")
            elif type(revision) is not int or rev != revision:
                raise Conflict("草稿已更新，请刷新并核对后导出")
            else:
                record = {k: v for k, v in record.items() if k != "submissions"}
        content = json.dumps(
            {"source": spec, "data": record},
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
        if len(content) + len(MAGIC) + 28 > MAX_PACKET:
            raise ValueError("业务包超过 16 MiB，请按报送月份拆分")
        fingerprint = sha256(content).digest()
        prior = db.execute(
            "SELECT packet FROM protected_documents WHERE content_hash=?",
            (fingerprint,),
        ).fetchone()
        if prior:
            packet = prior[0]
        else:
            nonce = secrets.token_bytes(12)
            encrypted = AESGCM(derive(store._storage_master, b"document")).encrypt(
                nonce, content, MAGIC
            )
            packet = MAGIC + nonce + encrypted
            db.execute(
                "INSERT INTO protected_documents VALUES(?,?,?)",
                (fingerprint, sha256(packet).digest(), packet),
            )
        audit(db, store, actor, "document.export", spec, scope)
        return packet


def open_package(store, token, packet):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        if not (access.has(actor, "clinical") or access.has(actor, "reports")):
            raise PermissionError("该账号没有业务文件查阅权限")
        if (
            len(packet) > MAX_PACKET
            or len(packet) < len(MAGIC) + 28
            or not packet.startswith(MAGIC)
        ):
            raise ValueError("请选择安康医养平台导出的 .akdoc 文件")
        if not db.execute(
            "SELECT 1 FROM protected_documents WHERE packet_hash=?",
            (sha256(packet).digest(),),
        ).fetchone():
            raise ValueError("文件不属于当前机构归档或完整性校验失败")
        offset = len(MAGIC)
        try:
            content = AESGCM(derive(store._storage_master, b"document")).decrypt(
                packet[offset : offset + 12], packet[offset + 12 :], MAGIC
            )
        except InvalidTag:
            raise ValueError("文件认证失败") from None
        payload = json.loads(content)
        state = json.loads(
            db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
        )
        spec = payload["source"]
        _, scope = authorise(db, state, actor, spec)
        audit(db, store, actor, "document.open", spec, scope)
        return payload


def audit(db, store, actor, action, spec, scope):
    revision = db.execute(
        "UPDATE workspace SET revision=revision+1 WHERE id=1 RETURNING revision"
    ).fetchone()[0]
    title = "民政报送" if spec["kind"] == "report" else "院外转介"
    operation = "导出" if action == "document.export" else "查阅"
    activity.write(
        db,
        revision,
        store.now().isoformat(timespec="seconds"),
        action,
        operation + title + "加密文件",
        actor,
        scope,
        {},
    )
