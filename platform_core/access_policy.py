"""Server-side grants for the single-institution workspace and its read models."""

PERMISSIONS = {
    "residents": "查阅长者基本档案",
    "intake": "接待、入住和床位管理",
    "care": "评估、照护和工单执行",
    "clinical": "体征、异常、医嘱和用药复核",
    "medical": "查阅医疗文档原件",
    "medical.write": "登记医疗照片与概括",
    "relatives": "查看授权亲属资料",
    "inventory": "库存与领用",
    "finance": "财务、收款与结算",
    "shifts": "工作排班",
    "reports": "报送及经营视图",
    "assistants": "运行 Agent 协作、生成与审核建议",
    "gateway.simulate": "登记模拟设备事件",
    "alerts": "护士复核预警并记录处置",
    "voice": "发起语音变更申请",
    "voice.confirm": "确认或退回语音变更",
    "audit": "查阅已授权业务的操作日志",
}
PRESETS = {
    "院长": [
        "residents",
        "intake",
        "care",
        "inventory",
        "finance",
        "shifts",
        "reports",
        "assistants",
        "gateway.simulate",
        "audit",
    ],
    "护士": [
        "assistants",
        "residents",
        "care",
        "clinical",
        "medical",
        "medical.write",
        "alerts",
        "voice",
        "voice.confirm",
    ],
    "护工": ["residents", "care", "voice", "voice.confirm"],
    "财务": ["finance", "reports"],
    "自定义": [],
}
# Empty grants is still a valid employee account.
ROUTE_GRANTS = {
    "overview": (),
    "assistants": ("assistants",),
    "intake": ("intake",),
    "residents": ("residents", "intake", "care", "clinical"),
    "assessments": ("care",),
    "care": ("care", "clinical"),
    "medications": ("clinical",),
    "beds": ("intake", "care"),
    "rooms": ("intake", "care", "clinical", "residents"),
    "tour": (),
    "inventory": ("inventory",),
    "billing": ("finance",),
    "shifts": ("shifts",),
    "reports": ("reports", "audit"),
    "activity": ("audit",),
    "dossier": ("residents", "intake", "medical", "relatives"),
    "inbox": ("gateway.simulate", "alerts", "voice", "voice.confirm"),
    "integrations": ("gateway.simulate", "alerts", "voice", "voice.confirm"),
}
ACTION_GRANTS = {
    "care.inquire": "intake",
    "care.admit": "intake",
    "care.transfer": "intake",
    "care.renew": "intake",
    "care.discharge": "intake",
    "care.leave": "intake",
    "care.assess": "care",
    "care.approvePlan": "care",
    "care.addTask": "care",
    "care.completeTask": "care",
    "care.quality": "care",
    "care.handover": "care",
    "care.addMedication": "clinical",
    "care.giveMedication": "clinical",
    "care.reviewMedication": "clinical",
    "care.vital": "clinical",
    "care.resolveVital": "clinical",
    "care.archive": "clinical",
    "ops.stock": "inventory",
    "ops.addItem": "inventory",
    "ops.shift": "shifts",
    "ops.bill": "finance",
    "ops.deposit": "finance",
    "ops.pay": "finance",
    "ops.report": "reports",
    "dossier.profile": "intake",
    "dossier.document": "medical.write",
    "agent.start": "assistants",
    "agent.publish": "assistants",
    "agent.cancel": "assistants",
    "gw.ingest": "gateway.simulate",
    "gw.review": "alerts",
    "gw.propose": "voice",
    "gw.confirm": "voice.confirm",
    "gw.dismiss": "voice.confirm",
}
SUGGESTION_GRANTS = {"日常照护": "care", "物资管控": "inventory", "运营分析": "finance"}
COLLECTION_GRANTS = {
    "inquiries": "intake",
    "assessments": "care",
    "plans": "care",
    "tasks": "care",
    "qualityChecks": "care",
    "handovers": "care",
    "medications": "clinical",
    "vitals": "clinical",
    "inventory": "inventory",
    "transactions": "inventory",
    "shifts": "shifts",
    "bills": "finance",
    "deposits": "finance",
    "depositEntries": "finance",
    "payments": "finance",
    "reports": "reports",
}
FACILITY_COMMANDS = (
    "facility.addBuilding",
    "facility.addFloor",
    "facility.addRoom",
    "facility.addBeds",
    "facility.linkBed",
    "facility.setLayout",
    "facility.setScene",
    "facility.withdrawScene",
)
DEFAULT_UI = {
    "brandName": "安康医养平台",
    "institutionName": "安康家园",
    "theme": "forest",
    "hiddenRoutes": [],
}


def has(user, permission):
    return bool(user) and (
        user["kind"] == "owner" or permission in user.get("permissions", ())
    )


def require(user, permission):
    if not has(user, permission):
        raise PermissionError("此账号没有当前操作权限")


def resolve_routes(user):
    if user["kind"] == "family":
        return ["family", "tour"]
    routes = [
        route
        for route, grants in ROUTE_GRANTS.items()
        if not grants or any(has(user, g) for g in grants)
    ]
    if user["kind"] == "owner":
        routes.extend(["access", "settings"])
    return routes


def authorize(user, action, payload, state):
    """Fail closed. Permissions for proposals/reviews include the affected business area."""
    if not user:
        raise PermissionError("请先登录")
    if not isinstance(action, str) or not isinstance(payload, dict):
        raise ValueError("业务操作格式无效")
    if action in FACILITY_COMMANDS:
        if user["kind"] != "owner":
            raise PermissionError("仅机构总管理员可以维护院区")
        return
    if action.startswith("access."):
        if user["kind"] != "owner":
            raise PermissionError("仅总管理员可管理账号与系统设置")
        return
    if action == "dossier.relative":
        if user["kind"] not in ("owner", "family"):
            raise PermissionError("本人或总管理员可维护亲属资料")
        return
    if action in ("ops.suggest", "ops.review"):
        require(user, "assistants")
        category = payload.get("category")
        if action == "ops.review":
            record = next(
                (
                    s
                    for s in state.get("suggestions", ())
                    if s["id"] == payload.get("id")
                ),
                None,
            )
            category = record["category"] if record else None
        grant = SUGGESTION_GRANTS.get(category) if isinstance(category, str) else None
        if not grant:
            raise ValueError("建议类别或编号无效")
        require(user, grant)
        return
    permission = ACTION_GRANTS.get(action)
    if not permission:
        raise ValueError("未登记的业务操作")
    require(user, permission)
    if action in ("gw.propose", "gw.confirm", "gw.dismiss"):
        require(user, "care")


def allowed_actions(user):
    actions = [
        action for action, permission in ACTION_GRANTS.items() if has(user, permission)
    ]
    if not has(user, "care"):
        actions = [
            a for a in actions if a not in ("gw.propose", "gw.confirm", "gw.dismiss")
        ]
    if has(user, "assistants") and any(
        has(user, g) for g in SUGGESTION_GRANTS.values()
    ):
        actions += ["ops.suggest", "ops.review"]
    if user["kind"] in ("owner", "family"):
        actions.append("dossier.relative")
    if user["kind"] == "owner":
        actions += [
            *FACILITY_COMMANDS,
            "access.create",
            "access.update",
            "access.password",
            "access.settings",
        ]
    return sorted(actions)


def can_view_audit(user, action, *, agent_initiator=None, agent_grants=()):
    if not has(user, "audit"):
        return False
    if user["kind"] == "owner":
        return True
    if action.startswith("agent."):
        return (
            action in ACTION_GRANTS
            and user["id"] == agent_initiator
            and has(user, "assistants")
            and bool(agent_grants)
            and all(grant in PERMISSIONS and has(user, grant) for grant in agent_grants)
        )
    if action in ("ops.suggest", "ops.review"):
        # Old rows have no stored category, and may describe any of the source domains.
        return all(has(user, p) for p in ("assistants", *SUGGESTION_GRANTS.values()))
    if action in ("gw.propose", "gw.confirm", "gw.dismiss") and not has(user, "care"):
        return False
    return has(user, ACTION_GRANTS[action]) if action in ACTION_GRANTS else False


def select_fields(row, names):
    return {key: row[key] for key in names if key in row}


def visible_data(state, user):
    # Unknown module keys are never copied automatically to a restricted account.
    # Downstream dossier/gateway projectors append their own authorized read models.
    if user["kind"] == "owner":
        return dict(state)
    data = {
        key: []
        for key in (
            *COLLECTION_GRANTS,
            "residents",
            "beds",
            "suggestions",
            "archives",
            "bedMoves",
            "leaves",
        )
    }
    if user["kind"] == "family":
        data["residents"] = [
            select_fields(r, ("id", "name"))
            for r in state["residents"]
            if r["id"] == user["residentId"]
        ]
        return data
    for key, grant in COLLECTION_GRANTS.items():
        if has(user, grant):
            data[key] = state.get(key, [])

    def any_grant(*grants):
        return any(has(user, g) for g in grants)

    if any_grant(
        "care",
        "intake",
        "clinical",
        "residents",
        "medical",
        "relatives",
        "finance",
        "gateway.simulate",
        "alerts",
        "voice",
        "voice.confirm",
        "shifts",
    ):
        basic = ["id", "name", "status", "bedId"]
        if any_grant("care", "clinical", "intake", "residents"):
            basic.extend(
                ["age", "gender", "admittedAt", "endDate", "dischargedAt", "level"]
            )
        if any_grant("intake", "relatives"):
            basic.append("contact")
        if any_grant("clinical", "medical"):
            basic.extend(["risk", "allergies", "summary"])
        data["residents"] = [select_fields(r, basic) for r in state["residents"]]
        bed_fields = ["id", "label", "ward", "status", "residentId"]
        if any_grant("finance", "intake"):
            bed_fields.append("dailyRate")
        data["beds"] = [select_fields(b, bed_fields) for b in state["beds"]]
    if any_grant("intake", "care"):
        data["bedMoves"] = state.get("bedMoves", [])
    if any_grant("clinical", "medical"):
        data["archives"] = state.get("archives", [])
    if any_grant("intake", "finance"):
        data["leaves"] = (
            state.get("leaves", [])
            if has(user, "intake")
            else [
                select_fields(row, ("id", "residentId", "date", "startDate", "endDate"))
                for row in state.get("leaves", [])
            ]
        )
    if has(user, "assistants"):
        data["suggestions"] = [
            s
            for s in state.get("suggestions", [])
            if s["category"] in SUGGESTION_GRANTS
            and has(user, SUGGESTION_GRANTS[s["category"]])
        ]
    return data
