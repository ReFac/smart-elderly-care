"""A2A 1.0 read-only institution service using the official SDK's wire types."""

from contextlib import closing
import json
import re
from uuid import uuid4

from .. import access, campus_access
from . import chat_context


SDK_MESSAGE = "The A2A service requires requirements-a2a.txt"
ENGLISH_NAMES = {"bed-availability": "Bed availability", "today-care-work": "Today’s care workload"}
SKILLS = {
    "bed-availability": ("床位概况", "Count vacant and occupied beds visible to the caller.", "beds"),
    "today-care-work": ("今日照护工单", "Count today's care work by status in the caller's scope.", "care"),
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS a2a_tasks (
        id TEXT PRIMARY KEY, site TEXT NOT NULL, actor TEXT NOT NULL, message_id TEXT NOT NULL,
        scope TEXT NOT NULL, command TEXT NOT NULL, artifact TEXT NOT NULL,
        UNIQUE (site, actor, message_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS a2a_requests (
        site TEXT NOT NULL, actor TEXT NOT NULL, rpc_id TEXT NOT NULL,
        task TEXT NOT NULL REFERENCES a2a_tasks(id),
        PRIMARY KEY (site, actor, rpc_id))""")


def agent_card(origin, edition="china"):
    from a2a.types import a2a_pb2 as wire
    from google.protobuf.json_format import MessageToDict

    card = wire.AgentCard(
        name="Elder Care Operations", version="1.0.0",
        description="Read-only aggregates within the signed-in staff member's institution and assignment.",
        default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        supported_interfaces=[wire.AgentInterface(url=origin + "/api/a2a", protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=wire.AgentCapabilities(),
    )
    card.security_schemes["workspaceSession"].api_key_security_scheme.CopyFrom(
        wire.APIKeySecurityScheme(name="nh_session", location="cookie", description="Authenticated workspace session")
    )
    card.security_requirements.add().schemes["workspaceSession"].SetInParent()
    for command, (name, description, _) in SKILLS.items():
        if edition == "international":
            name = ENGLISH_NAMES[command]
        card.skills.add(id=command, name=name, description=description, tags=["operations"], examples=[command, name])
    return MessageToDict(card)


def _validate_keys(value, allowed):
    from a2a.utils.errors import InvalidParamsError

    if not isinstance(value, dict) or not value.keys() <= allowed:
        raise InvalidParamsError("Unexpected parameters for this skill")


def _key(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[a-zA-Z0-9._:-]{1,128}", value))


def _command(params):
    from a2a.types import a2a_pb2 as wire
    from a2a.utils.errors import ContentTypeNotSupportedError, InvalidParamsError, UnsupportedOperationError
    from google.protobuf.json_format import ParseDict, ParseError

    _validate_keys(params, {"message", "configuration"})
    message = params.get("message")
    _validate_keys(message, {"messageId", "role", "parts"})
    configuration = params.get("configuration", {})
    _validate_keys(configuration, {"acceptedOutputModes", "historyLength", "returnImmediately"})
    try:
        parsed = ParseDict(params, wire.SendMessageRequest())
    except (ParseError, TypeError, ValueError):
        raise InvalidParamsError("Invalid SendMessage request") from None
    if not _key(parsed.message.message_id) or parsed.message.role != wire.ROLE_USER:
        raise InvalidParamsError("A user message with a stable messageId is required")
    if len(parsed.message.parts) != 1 or set(message["parts"][0]) - {"text", "mediaType"}:
        raise ContentTypeNotSupportedError("Send one text/plain command from the Agent Card")
    part = parsed.message.parts[0]
    modes = parsed.configuration.accepted_output_modes
    if part.media_type not in ("", "text/plain") or (modes and "text/plain" not in modes):
        raise ContentTypeNotSupportedError()
    if not 0 <= parsed.configuration.history_length <= 100:
        raise InvalidParamsError("Invalid historyLength")
    text = part.text.strip()
    for command, (name, _, _) in SKILLS.items():
        if text in (command, name, ENGLISH_NAMES[command]):
            return parsed.message.message_id, command
    raise UnsupportedOperationError("Select a read-only operation listed in the Agent Card")


def _allowed(actor, routes, command):
    if SKILLS[command][2] not in routes:
        return False
    if command == "today-care-work":
        return access.has(actor, "care")
    return any(access.has(actor, grant) for grant in ("intake", "residents", "care", "clinical"))


def _report(store, db, state, actor, command):
    projected = access.visible_data(campus_access.projection(db, state, actor), actor)
    if command == "bed-availability":
        beds = projected["beds"]
        vacant = sum(b["status"] == "空闲" and not b.get("residentId") for b in beds)
        occupied = sum(bool(b.get("residentId")) for b in beds)
        if store.deployment_edition == "international":
            return f"{len(beds)} visible beds, {vacant} vacant and {occupied} occupied."
        return f"当前授权范围共 {len(beds)} 张床位，其中空闲 {vacant} 张，已占用 {occupied} 张。"
    today = store.now().date().isoformat()
    counts = {}
    for task in projected["tasks"]:
        if task["date"] == today:
            counts[task["status"]] = counts.get(task["status"], 0) + 1
    if store.deployment_edition == "international":
        statuses = {"待执行": "pending", "待接单": "unassigned", "处理中": "in progress", "待复核": "in review",
                    "已完成": "completed", "已驳回": "rejected", "已取消": "cancelled"}
        items = ", ".join(f"{statuses.get(status, status)} {n}" for status, n in sorted(counts.items()))
        return f"{today}: {sum(counts.values())} care tasks in scope" + (f" ({items})." if items else ".")
    totals = "，".join(f"{status} {n} 项" for status, n in sorted(counts.items()))
    return f"{today} 当前授权范围内有 {sum(counts.values())} 项照护工单" + (f"，{totals}。" if totals else "。")


def _send(store, db, rpc_id, params, actor, site, scope, routes, state):
    from a2a.types import a2a_pb2 as wire
    from a2a.utils.errors import InvalidParamsError, TaskNotFoundError
    from google.protobuf.json_format import MessageToDict

    message_id, command = _command(params)
    if not _allowed(actor, routes, command):
        raise PermissionError("当前账号没有此项院务查询权限")
    identity = (site, actor["id"])
    request_key = json.dumps(rpc_id, ensure_ascii=True)
    prior = db.execute("SELECT task FROM a2a_requests WHERE site=? AND actor=? AND rpc_id=?",
                       (*identity, request_key)).fetchone()
    row = db.execute("SELECT * FROM a2a_tasks WHERE site=? AND actor=? AND message_id=?",
                     (*identity, message_id)).fetchone()
    if prior and (not row or prior["task"] != row["id"]):
        raise InvalidParamsError("This request id was already used with another message")
    if row:
        if row["scope"] != scope:
            raise TaskNotFoundError()
        if row["command"] != command:
            raise InvalidParamsError("This message id was already used with another operation")
        task = json.loads(row["artifact"])
    else:
        task_id = uuid4().hex
        result = wire.Task(id=task_id, context_id=uuid4().hex)
        result.status.state = wire.TASK_STATE_COMPLETED
        result.status.timestamp.FromDatetime(store.now())
        artifact_name = ENGLISH_NAMES[command] if store.deployment_edition == "international" else SKILLS[command][0]
        artifact = result.artifacts.add(artifact_id=uuid4().hex, name=artifact_name)
        artifact.parts.add(text=_report(store, db, state, actor, command), media_type="text/plain")
        task = MessageToDict(result)
        db.execute("INSERT INTO a2a_tasks VALUES (?,?,?,?,?,?,?)",
                   (task_id, *identity, message_id, scope, command, json.dumps(task, ensure_ascii=False)))
    if not prior:
        db.execute("INSERT INTO a2a_requests VALUES (?,?,?,?)", (*identity, request_key, task["id"]))
    return {"task": task}


def dispatch(store, token, request, version=None):
    from a2a.utils import errors
    from a2a.utils.error_handlers import build_error_details

    rpc_id = request.get("id")
    try:
        if (request.get("jsonrpc") != "2.0" or set(request) - {"jsonrpc", "id", "method", "params"}
                or not (_key(rpc_id) or type(rpc_id) is int and abs(rpc_id) < 2**53)):
            rpc_id = None
            raise errors.InvalidRequestError()
        if version not in (None, "1.0"):
            raise errors.VersionNotSupportedError()
        method = request.get("method")
        params = request.get("params")
        with closing(store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE" if method == "SendMessage" else "BEGIN")
            actor, scope, routes, state, _ = chat_context.scope(store, db, token, None)
            if not chat_context.institution_access(actor) or "assistants" not in routes:
                raise PermissionError("请使用具有助理权限的机构员工账号")
            site = db.execute("SELECT id FROM facility_site WHERE singleton=1").fetchone()[0]
            if method == "SendMessage":
                result = _send(store, db, rpc_id, params, actor, site, scope, routes, state)
            elif method in ("GetTask", "CancelTask"):
                _validate_keys(params, {"id", "historyLength"} if method == "GetTask" else {"id"})
                depth = params.get("historyLength", 0)
                if not _key(params.get("id")) or type(depth) is not int or not 0 <= depth <= 100:
                    raise errors.InvalidParamsError()
                row = db.execute("SELECT * FROM a2a_tasks WHERE site=? AND actor=? AND id=? AND scope=?",
                                 (site, actor["id"], params["id"], scope)).fetchone()
                if not row or not _allowed(actor, routes, row["command"]):
                    raise errors.TaskNotFoundError()
                if method == "CancelTask":
                    raise errors.TaskNotCancelableError()
                result = json.loads(row["artifact"])
            else:
                raise errors.MethodNotFoundError()
        return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
    except errors.A2AError as exc:
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {
            "code": errors.JSON_RPC_ERROR_CODE_MAP[type(exc)], "message": str(exc),
            "data": build_error_details(exc),
        }}


def http(handler, discovery=False):
    try:
        if discovery:
            origin = handler.public_origin or ("http://" + handler.headers["Host"])
            body = agent_card(origin, handler.store.deployment_edition)
        else:
            try:
                request = handler.read_json(8192)
            except ValueError:
                return handler.send_json(400, {"jsonrpc": "2.0", "id": None, "error": {
                    "code": -32700, "message": "A JSON-RPC object of at most 8192 bytes is required",
                }})
            body = dispatch(handler.store, handler.token(), request, handler.headers.get("A2A-Version"))
    except ModuleNotFoundError as exc:
        if exc.name.split(".")[0] not in {"a2a", "google"}:
            raise
        return handler.send_json(503, {"error": SDK_MESSAGE})
    return handler.send_json(200, body)
