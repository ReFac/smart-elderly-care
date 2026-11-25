"""Owner deployment drafts and authenticated edge-gateway heartbeats.

Each institution has a separate encrypted operations database outside its business
backups. The process reads approved runtime settings once per service start.
"""

from contextlib import closing
from hashlib import sha256
from hmac import compare_digest
import json
import os
from pathlib import Path
import re
import socket
from threading import RLock
from time import time

from . import deployment_language, operational_secrets, provider, updates
from .provider import completions, connection, deepseek
from .store import Conflict

LOCK = RLock()
DEVICE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}")
MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]{0,179}")
BASE = {"deepseek": deepseek.ENDPOINT, **completions.CHAT_ENDPOINTS}
GATEWAY_TYPES = ("HTTP", "MQTT 网桥", "Modbus 网桥")
MODES = ("next-start", "manual")


def operator():
    return os.environ.get("NH_DEPLOYMENT_MODE") == "operator"


def path_for(database):
    path = Path(database)
    return path.with_name("." + path.name + ".deployment.sqlite3")


def allowed_endpoints():
    endpoints = {name: [url] for name, url in BASE.items()}
    # Only an operator outside the web application can establish new destinations.
    raw = os.environ.get("NH_DEPLOY_CHAT_ENDPOINTS", "").strip()
    if raw:
        for url in raw.split(","):
            url = connection.endpoint(url.strip())
            if url not in endpoints["openai"]:
                endpoints["openai"].append(url)
    return endpoints


def connection_defaults():
    kind = completions.provider_name()
    return {
        "provider": kind,
        "model": provider.model_name(),
        "endpoint": completions.chat_endpoint(kind),
        "host": "127.0.0.1",
        "port": 8765,
    }


def read_state(db):
    row = db.execute("SELECT data FROM secrets WHERE name='settings'").fetchone()
    return (
        json.loads(row[0])
        if row
        else {"revision": 0, "active": None, "draft": None, "policy": "manual"}
    )


def save_state(db, state):
    db.execute(
        "INSERT OR REPLACE INTO secrets VALUES('settings',?)",
        (json.dumps(state).encode(),),
    )


def saved_state(database):
    path = path_for(database)
    if not path.exists():
        return {"revision": 0, "active": None, "draft": None, "policy": "manual"}
    with closing(operational_secrets.connect(path)) as db:
        return read_state(db)


def public_config(config):
    if config is None:
        return None
    return {k: v for k, v in config.items() if k not in ("key",)}


def selected_config(database):
    if not operator():
        return None
    state = saved_state(database)
    if state["draft"] and state["policy"] == "next-start":
        return state["draft"]
    return state["active"]


def bind_allowed(host, origin):
    return host == "127.0.0.1" or (
        host == "0.0.0.0"
        and origin
        and os.environ.get("NH_DEPLOY_ALLOW_NETWORK_BIND") == "1"
    )


def start_options(database, explicit_port, origin):
    config = selected_config(database) or {}
    if config and explicit_port is not None and explicit_port != config["port"]:
        # A recovery port overrides a bad draft without activating it partially.
        config = saved_state(database)["active"] or {}
    host = config.get("host", "127.0.0.1")
    if not bind_allowed(host, origin):
        raise ValueError(
            "部署监听需要配置机构 HTTPS 域名及受信反向代理，或使用回环地址"
        )
    return (
        host,
        explicit_port if explicit_port is not None else config.get("port", 8765),
        config,
    )


def activate(database, config, port):
    # The listener is already bound; a failed bind never consumes a staged draft.
    if not config:
        return
    if config["endpoint"] not in allowed_endpoints()[config["provider"]]:
        raise ValueError("待应用的模型端点已不在部署许可名单中")
    completions.deployed = dict(config)
    with LOCK, closing(operational_secrets.connect(path_for(database))) as db, db:
        db.execute("BEGIN IMMEDIATE")
        state = read_state(db)
        if (
            state["draft"] == config
            and state["policy"] == "next-start"
            and config["port"] == port
        ):
            state.update(active=config, draft=None, revision=state["revision"] + 1)
            save_state(db, state)
            audit(db, "系统", "服务重启，已应用部署配置")


def audit(db, actor, message):
    db.execute(
        "CREATE TABLE IF NOT EXISTS changes(at INTEGER NOT NULL, actor TEXT NOT NULL, message TEXT NOT NULL)"
    )
    db.execute("INSERT INTO changes VALUES(?,?,?)", (int(time()), actor, message))


def owner(store, conn, token):
    user = store.actor(conn, token)
    if user["kind"] != "owner":
        raise PermissionError("仅 Owner 可以管理部署")
    return user


def inspect(store, token, server):
    with closing(store.connect()) as business:
        user = owner(store, business, token)
        plan = provider.status(business, user)
    mode = operator()
    state = (
        saved_state(store.path)
        if mode
        else {"revision": 0, "draft": None, "policy": "manual"}
    )
    devices, changes = [], []
    path = path_for(store.path)
    if path.exists():
        with closing(operational_secrets.connect(path)) as db:
            tables = {
                r[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if "devices" in tables:
                devices = [
                    dict(
                        id=i,
                        label=n,
                        transport=t,
                        enabled=bool(e),
                        lastSeen=h,
                        status="已停用"
                        if not e
                        else "等待首报"
                        if not h
                        else "近期收到心跳"
                        if time() - h <= 180
                        else "心跳超时",
                    )
                    for i, n, t, e, h in db.execute(
                        "SELECT id,label,transport,enabled,lastSeen FROM devices ORDER BY id"
                    )
                ]
            if "changes" in tables:
                changes = [
                    dict(at=t, actor=a, message=m)
                    for t, a, m in db.execute(
                        "SELECT at,actor,message FROM changes ORDER BY rowid DESC LIMIT 20"
                    )
                ]
    connection_info = connection_defaults()
    connection_info.update(host=server.server_address[0], port=server.server_port)
    return {
        "mode": "operator" if mode else "managed",
        "profile": "licensed-medical" if store.clinical_archive_protection else "residential",
        "locale": deployment_language.public(store.deployment_language),
        "language": store.deployment_language,
        "running": connection_info
        if mode
        else {
            "provider": connection_info["provider"],
            "model": connection_info["model"],
        },
        "version": updates.installed_version(),
        "credentialConfigured": provider.model_configured(),
        "publicOrigin": getattr(server, "deployment_origin", None) if mode else None,
        "portPinned": bool(getattr(server, "deployment_port_pinned", False))
        if mode
        else False,
        "networkBind": bool(
            bind_allowed("0.0.0.0", getattr(server, "deployment_origin", None))
        )
        if mode
        else False,
        "allowedEndpoints": allowed_endpoints() if mode else {},
        "revision": state["revision"],
        "draft": public_config(state["draft"]),
        "policy": state["policy"],
        "plan": {
            "name": plan.get("planName"),
            "status": plan["state"],
            "unlimited": plan.get("unlimited", False),
        },
        "gatewayTypes": GATEWAY_TYPES,
        "devices": devices,
        "recent": changes,
    }


def configure(store, token, data, server):
    with closing(store.connect()) as business:
        user = owner(store, business, token)
        if not operator():
            raise PermissionError("此机构使用平台托管套餐，部署参数由平台运营方管理")
        op = data.get("action")
        expected = (
            {"action", "revision", "config", "policy", "key"}
            if op == "save"
            else {"action", "revision"}
        )
        if (
            set(data) != expected
            or op not in ("save", "arm", "discard")
            or type(data["revision"]) is not int
        ):
            raise ValueError("部署操作或字段无效")
        path = path_for(store.path)
        with LOCK, closing(operational_secrets.connect(path, create=True)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = read_state(db)
            if state["revision"] != data["revision"]:
                raise Conflict("部署设置已被修改，请刷新后重新核对")
            if op == "save":
                cfg = data["config"]
                if not isinstance(cfg, dict) or set(cfg) != {
                    "provider",
                    "model",
                    "endpoint",
                    "host",
                    "port",
                }:
                    raise ValueError("部署设置字段不完整")
                kind, model, endpoint = cfg["provider"], cfg["model"], cfg["endpoint"]
                if (
                    kind not in BASE
                    or endpoint not in allowed_endpoints()[kind]
                    or not isinstance(model, str)
                    or not MODEL.fullmatch(model)
                ):
                    raise ValueError("请选择已登记的服务商端点并填写模型编号")
                if kind == "deepseek" and model != provider.DEFAULT_MODEL:
                    raise ValueError("DeepSeek 请使用机构套餐指定的模型")
                if (
                    not bind_allowed(
                        cfg["host"], getattr(server, "deployment_origin", None)
                    )
                    or type(cfg["port"]) is not int
                    or not 1 <= cfg["port"] <= 65535
                ):
                    raise ValueError("监听地址或端口不在允许范围")
                if (
                    getattr(server, "deployment_port_pinned", False)
                    and cfg["port"] != server.server_port
                ):
                    raise ValueError(
                        "启动命令已固定端口。请由运维去掉 --port 后再设置端口"
                    )
                if (cfg["host"], cfg["port"]) != server.server_address and cfg[
                    "port"
                ] != server.server_port:
                    try:
                        with socket.socket() as probe:
                            probe.bind((cfg["host"], cfg["port"]))
                    except OSError:
                        raise ValueError(
                            "目标端口当前无法绑定，请选择空闲端口"
                        ) from None
                key, policy = data["key"], data["policy"]
                if (
                    not isinstance(key, str)
                    or key
                    and not operational_secrets.valid_key(key)
                    or policy not in MODES
                ):
                    raise ValueError("凭据格式或应用策略无效")
                if not key:
                    key = next(
                        (
                            c.get("key", "")
                            for c in (state["draft"], state["active"])
                            if c
                            and (c["provider"], c["endpoint"]) == (kind, endpoint)
                            and c.get("key")
                        ),
                        "",
                    )
                if endpoint != BASE[kind] and not key:
                    raise ValueError("自建端点须提供专用凭据")
                state.update(draft={**cfg, "key": key}, policy=policy)
            elif not state["draft"]:
                raise ValueError("当前没有待应用配置")
            elif op == "arm":
                state["policy"] = "next-start"
            else:
                state.update(draft=None, policy="manual")
            state["revision"] += 1
            save_state(db, state)
            audit(
                db,
                user["displayName"],
                {
                    "save": "保存部署配置",
                    "arm": "批准下次启动应用",
                    "discard": "撤回待应用配置",
                }[op],
            )
    return inspect(store, token, server)


def device_settings(store, token, data, server):
    with closing(store.connect()) as business:
        user = owner(store, business, token)
        if set(data) != {"id", "label", "transport", "enabled", "secret"}:
            raise ValueError("设备连接字段无效")
        identifier, label, secret = data["id"], data["label"], data["secret"]
        if (
            not isinstance(identifier, str)
            or not DEVICE.fullmatch(identifier)
            or not isinstance(label, str)
            or not 1 <= len(label.strip()) <= 60
        ):
            raise ValueError("请填写有效网关编号和名称")
        if (
            data["transport"] not in GATEWAY_TYPES
            or type(data["enabled"]) is not bool
            or not isinstance(secret, str)
        ):
            raise ValueError("请选择网桥类型和启用状态")
        if secret and not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", secret):
            raise ValueError("网关令牌须为 32 至 128 位随机字母、数字、短横线或下划线")
        with (
            LOCK,
            closing(
                operational_secrets.connect(path_for(store.path), create=True)
            ) as db,
            db,
        ):
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,label TEXT NOT NULL,transport TEXT NOT NULL,
                          enabled INTEGER NOT NULL, digest BLOB NOT NULL,lastSeen INTEGER NOT NULL DEFAULT 0)""")
            existing = db.execute(
                "SELECT digest FROM devices WHERE id=?", (identifier,)
            ).fetchone()
            if not existing and (
                not secret
                or db.execute("SELECT count(*) FROM devices").fetchone()[0] >= 256
            ):
                raise ValueError("请为新网关设置专用令牌，每机构最多登记 256 个网关")
            digest = sha256(secret.encode()).digest() if secret else existing[0]
            db.execute(
                """INSERT INTO devices(id,label,transport,enabled,digest) VALUES(?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET label=excluded.label,transport=excluded.transport,enabled=excluded.enabled,
                        lastSeen=CASE WHEN devices.digest!=excluded.digest OR devices.enabled!=excluded.enabled THEN 0 ELSE devices.lastSeen END,
                        digest=excluded.digest""",
                (
                    identifier,
                    label.strip(),
                    data["transport"],
                    int(data["enabled"]),
                    digest,
                ),
            )
            audit(db, user["displayName"], "更新设备网关 " + identifier)
    return inspect(store, token, server)


def heartbeat(database, identifier, authorization):
    denied = PermissionError("网关认证未通过")
    if not DEVICE.fullmatch(identifier) or not re.fullmatch(
        r"Bearer [A-Za-z0-9_-]{32,128}", authorization or ""
    ):
        raise denied
    path = path_for(database)
    if not path.exists():
        raise denied
    with closing(operational_secrets.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='devices'"
        ).fetchone():
            raise denied
        row = db.execute(
            "SELECT enabled,digest,lastSeen FROM devices WHERE id=?", (identifier,)
        ).fetchone()
        if (
            not row
            or not row[0]
            or not compare_digest(sha256(authorization[7:].encode()).digest(), row[1])
        ):
            raise denied
        stamp = int(time())
        if stamp - row[2] >= 15:
            db.execute("UPDATE devices SET lastSeen=? WHERE id=?", (stamp, identifier))
    return {"accepted": True, "receivedAt": stamp}
