"""Per-account access to the bound resident's portal records."""

from .care.records import append_record, text_field

SCOPES = {
    "careSchedule": "查阅照护工单进度",
    "medication": "查阅已复核医嘱及给药记录",
    "medicationReport": "本人填写及更正体检用药自报",
    "personalHealth": "查看本人的生活简报、时间线与健康简介",
    "billingNotices": "查看已绑定长者的缴费提醒",
}


def scopes(payload, kind, previous=(), *, portal_self=False):
    if "portalScopes" not in payload:
        return list(previous)
    value = payload["portalScopes"]
    if (
        kind != "family"
        or not isinstance(value, list)
        or not all(isinstance(v, str) and v in SCOPES for v in value)
    ):
        raise ValueError("请选择绑定长者账号可查阅的服务范围")
    if "medicationReport" in value and not portal_self:
        raise ValueError("体检用药自报仅可授予已核验的长者本人账号")
    if "personalHealth" in value and not portal_self:
        raise ValueError("个人生活与健康档案仅可授予已核验的长者本人账号")
    return sorted(set(value))


def require_personal_health(user, rid):
    if (
        user.get("kind") != "family"
        or not user.get("portalSelf")
        or not rid
        or user.get("residentId") != rid
        or "personalHealth" not in user.get("portalScopes", ())
    ):
        raise PermissionError("此账号未获本人生活与健康档案的查阅授权")


PAGE_SIZE = 30
VIEWS = {
    "careSchedule": ("tasks", ("id", "date", "time", "title", "status", "completedAt", "menu")),
    "medication": (
        "medications",
        (
            "name",
            "instruction",
            "reviewedAt",
            "scheduledAt",
            "status",
            "executedAt",
            "executedTime",
        ),
    ),
}


def history(state, user, scope, offset=0):
    if (
        user["kind"] != "family"
        or scope not in user["portalScopes"]
        or scope not in VIEWS
    ):
        raise PermissionError("该账号未获此项查阅授权")
    if type(offset) is not int or offset < 0:
        raise ValueError("页码无效")
    collection, fields = VIEWS[scope]
    rows = [r for r in state[collection] if r["residentId"] == user["residentId"]]
    if scope == "medication":
        rows = [
            r
            for r in rows
            if r["status"] in ("待执行", "已执行")
            or (r["status"] == "已取消" and r.get("reviewedAt"))
        ]
    else:
        rows = [r for r in rows if r["status"] in ("待执行", "已完成", "已取消")]
    rows.sort(
        key=lambda r: (
            r.get("executedAt") or r.get("completedAt") or r["date"],
            r["date"],
            r.get("time", ""),
            r["id"],
        ),
        reverse=True,
    )
    page = [
        {k: r[k] for k in fields if k in r} for r in rows[offset : offset + PAGE_SIZE]
    ]
    if scope == "careSchedule":
        ratings = {
            r["taskId"]: r["rating"]
            for r in state["qualityChecks"]
            if r.get("accountId") == user["id"]
        }
        for task in page:
            if task["id"] in ratings:
                task["rating"] = ratings[task["id"]]
    return {"rows": page, "offset": offset, "total": len(rows)}


def project(data, state, user):
    totals = {}
    for scope, target in (
        ("careSchedule", "portalTasks"),
        ("medication", "portalMedication"),
    ):
        if scope in user["portalScopes"]:
            first = history(state, user, scope)
            data[target] = first["rows"]
            totals[scope] = first["total"]
    if totals:
        data["portalTotals"] = totals


def feedback(state, user, payload, day):
    task = next(
        (
            t
            for t in state["tasks"]
            if t["id"] == payload.get("taskId")
            and t["residentId"] == user["residentId"]
        ),
        None,
    )
    if not task or task["status"] != "已完成":
        raise PermissionError("仅可评价已完成的本人绑定服务")
    if any(
        r.get("accountId") == user["id"] and r["taskId"] == task["id"]
        for r in state["qualityChecks"]
    ):
        raise ValueError("此账号已评价该次服务")
    rating = payload.get("rating")
    if type(rating) is not int or not 1 <= rating <= 5:
        raise ValueError("请选择 1 至 5 分")
    note = text_field(payload.get("note"), "评价意见", limit=500)
    append_record(
        state,
        "qualityChecks",
        taskId=task["id"],
        residentId=task["residentId"],
        accountId=user["id"],
        reviewer=user["displayName"],
        date=day,
        note=note,
        rating=rating,
        source="长者本人评价" if user["portalSelf"] else "家属评价",
    )
    return f"评价「{task['title']}」服务，满意度 {rating} 分"
