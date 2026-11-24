"""Server-side grants for the single-institution workspace and its read models."""

PERMISSIONS = {
    "residents": "查阅长者基本档案",
    "intake": "意向客户、接待、入住和床位管理",
    "care": "评估、照护和工单执行",
    "clinical": "体征、异常、医嘱和用药复核",
    "clinical.rules": "维护经专业核准的用药核查规则",
    "medical": "查阅医疗文档原件",
    "medical.write": "登记医疗照片与概括",
    "relatives": "查看授权亲属资料",
    "family.share": "代录长者对每日巡查简报的分享意愿",
    "inventory": "库存与领用",
    "finance": "财务、收款与结算",
    "longCare": "长护险参保、评估和待遇经办",
    "shifts": "工作排班",
    "notices.publish": "向全体员工发布通知",
    "reports": "报送及经营视图",
    "assistants": "向 AI 助理询问已授权的业务",
    "gateway.simulate": "登记模拟设备事件",
    "alerts": "护士复核预警并记录处置",
    "voice": "向 AI 助理语音提问、发起语音变更申请",
    "voice.confirm": "确认或退回语音变更",
    "audit": "查阅已授权业务的操作日志",
    "staff.manage": "在本人业务权限内管理员工账号",
}
PRESETS = {
    "院长": [
        "residents",
        "intake",
        "care",
        "inventory",
        "finance",
        "shifts",
        "notices.publish",
        "voice",
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
    "history": (),
    "assistants": ("assistants",),
    "intake": ("intake",),
    "leads": ("intake",),
    "residents": ("residents", "intake", "care", "clinical"),
    "assessments": ("care",),
    "care": ("care", "clinical"),
    "medications": ("clinical",),
    "beds": ("intake", "care", "clinical", "residents"),
    "rooms": ("intake", "care", "clinical", "residents"),
    "tour": (),
    "inventory": ("inventory",),
    "billing": ("finance",),
    "longCare": ("longCare",),
    "shifts": ("shifts",),
    "reports": ("reports", "audit"),
    "activity": ("audit",),
    "dossier": ("residents", "intake", "medical", "relatives"),
    "inbox": (
        "notices.publish",
        "gateway.simulate",
        "alerts",
        "voice",
        "voice.confirm",
        "care",
        "clinical",
    ),
    "integrations": ("gateway.simulate", "alerts", "voice", "voice.confirm"),
}
ACTION_GRANTS = {
    "leads.register": "intake",
    "leads.call": "intake",
    "leads.feedback": "intake",
    "leads.archive": "intake",
    "leads.book": "intake",
    "leads.cancel": "intake",
    "leads.capacity": "intake",
    "care.reassignTrialFollowup": "intake",
    "care.inquire": "intake",
    "care.register": "intake",
    "care.fileArchive": "intake",
    "care.dateArchive": "intake",
    "care.admit": "intake",
    "care.confirmStay": "intake",
    "care.endTrial": "intake",
    "care.transfer": "intake",
    "care.renew": "intake",
    "care.discharge": "intake",
    "care.leave": "intake",
    "care.assess": "care",
    "care.approvePlan": "care",
    "care.addTask": "care",
    "care.timelineSettings": "care",
    "care.completeTask": "care",
    "care.quality": "care",
    "care.handover": "care",
    "care.acceptHandover": "care",
    "care.withdrawHandover": "care",
    "care.addMedication": "clinical",
    "care.giveMedication": "clinical",
    "care.reviewMedication": "clinical",
    "care.vital": "clinical",
    "care.resolveVital": "clinical",
    "care.archive": "clinical",
    "care.screen": "clinical",
    "care.scheduleFollowup": "clinical",
    "care.finishFollowup": "clinical",
    "care.refer": "clinical",
    "care.receiveReferral": "clinical",
    "care.referralConsent": "clinical",
    "care.exportReferral": "clinical",
    "care.publishDrugRule": "clinical.rules",
    "care.retireDrugRule": "clinical.rules",
    "ltci.record": "longCare",
    "ops.supplyOrder": "inventory",
    "ops.publishNotice": "notices.publish",
    "ops.stock": "inventory",
    "ops.addItem": "inventory",
    "ops.shift": "shifts",
    "ops.bill": "finance",
    "ops.deposit": "finance",
    "ops.pay": "finance",
    "ops.importReceipt": "finance",
    "ops.paymentOrder": "finance",
    "ops.remindBill": "finance",
    "ops.expense": "finance",
    "ops.importExpenses": "finance",
    "ops.submitReport": "reports",
    "ops.reportReceipt": "reports",
    "ops.report": "reports",
    "dossier.profile": "intake",
    "dossier.document": "medical.write",
    "dossier.ocr": "medical.write",
    "dossier.reviewDocument": "medical.write",
    "dossier.signSummary": "medical",
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
    "followups": "clinical",
    "referrals": "clinical",
    "drugRules": "clinical",
    "vitals": "clinical",
    "inventory": "inventory",
    "transactions": "inventory",
    "shifts": "shifts",
    "bills": "finance",
    "longCareEvents": "longCare",
    "deposits": "finance",
    "depositEntries": "finance",
    "payments": "finance",
    "paymentOrders": "finance",
    "channelReceipts": "finance",
    "expenses": "finance",
    "reports": "reports",
}
FACILITY_COMMANDS = (
    "facility.addCampus",
    "facility.updateCampus",
    "facility.renameBuilding",
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
    from . import campus_access

    if (
        user
        and campus_access.bound(user)
        and permission in campus_access.INSTITUTION_GRANTS
    ):
        return False
    return bool(user) and (
        user["kind"] == "owner" or permission in user.get("permissions", ())
    )


def require(user, permission):
    if not has(user, permission):
        raise PermissionError("此账号没有当前操作权限")


STAFF_ACCOUNT_ACTIONS = ("access.create", "access.update", "access.staffContract", "access.staffPayday")


def can_record_scale(user):
    return has(user, "care") and (has(user, "clinical") or has(user, "medical"))


def manages_accounts(user):
    return user["kind"] in ("staff", "owner") and has(user, "staff.manage")


def has_agent_domain(user):
    return has(user, "assistants") and any(
        has(user, grant) for grant in SUGGESTION_GRANTS.values()
    )


def resolve_routes(user):
    if user["kind"] == "family":
        return ["family", "tour", "account"]
    routes = [
        route
        for route, grants in ROUTE_GRANTS.items()
        if not grants or any(has(user, g) for g in grants)
    ]
    if "assistants" in routes and not has_agent_domain(user):
        routes.remove("assistants")
    if "inbox" in routes and not (
        has(user, "care")
        or has(user, "clinical")
        or has(user, "alerts")
        or has(user, "gateway.simulate")
        or has(user, "notices.publish")
    ):
        routes.remove("inbox")
    if manages_accounts(user):
        routes.append("access")
    if user["kind"] == "owner":
        routes.append("settings")
    return [*routes, "account"]


def authorize(user, action, payload, state):
    """Fail closed. Permissions for proposals/reviews include the affected business area."""
    if not user:
        raise PermissionError("请先登录")
    if not isinstance(action, str) or not isinstance(payload, dict):
        raise ValueError("业务操作格式无效")
    if action == "ops.finishSupplyOrder":
        if user["kind"] not in ("owner", "staff"):
            raise PermissionError("仅在岗员工可以办理")
        return
    if action == "account.changePassword":
        return
    if action == "care.finishTrialFollowup":
        if user["kind"] in ("owner", "staff") and "residents" in user["routes"]:
            return
        raise PermissionError("此账号没有试住回访权限")
    if action == "family.consent":
        if user["kind"] == "family" and user.get("portalSelf"):
            return
        require(user, "relatives")
        require(user, "family.share")
        return
    if action in ("family.subscribe", "family.read"):
        if user["kind"] != "family" or user.get("portalSelf"):
            raise PermissionError("仅限亲属本人管理订阅和收件箱")
        return
    if action == "portal.feedback":
        if user["kind"] != "family" or "careSchedule" not in user.get(
            "portalScopes", ()
        ):
            raise PermissionError("此账号没有服务评价授权")
        return
    if action in FACILITY_COMMANDS:
        if user["kind"] != "owner":
            raise PermissionError("仅机构总管理员可以维护院区")
        return
    if action == "access.password":
        raise PermissionError("密码须由账号本人通过验证码设置")
    if action.startswith("access."):
        if action in STAFF_ACCOUNT_ACTIONS and manages_accounts(user):
            return
        if user["kind"] != "owner":
            raise PermissionError("此账号没有对应的管理权限")
        return
    if action == "dossier.relative":
        if user["kind"] not in ("owner", "family") or user.get("portalSelf"):
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
    if action == "leads.capacity":
        require(user, "staff.manage")
    if action == "care.assess" and "scale" in payload and not can_record_scale(user):
        raise PermissionError("标准量表原表录入需要照护及临床或医疗档案权限")
    if action == "dossier.reviewDocument":
        require(user, "clinical")
        require(user, "medical")
    if action == "dossier.signSummary":
        require(user, "clinical")
    if permission == "clinical.rules":
        require(user, "clinical")
    if action in (
        "agent.start",
        "agent.publish",
        "agent.cancel",
    ) and not has_agent_domain(user):
        raise PermissionError("智能协作需要另行授予照护、物资或财务权限")
    if action in ("gw.propose", "gw.confirm", "gw.dismiss"):
        require(user, "care")


def allowed_actions(user):
    actions = [
        action for action, permission in ACTION_GRANTS.items() if has(user, permission)
    ]
    from .operations.dispatch import unrestricted

    if not has(user, "staff.manage"):
        actions = [a for a in actions if a != "leads.capacity"]

    if not unrestricted(user):
        actions = [a for a in actions if a not in ("ops.publishNotice", "ops.supplyOrder", "ops.importExpenses")]
    if user["kind"] in ("owner", "staff"):
        actions.append("ops.finishSupplyOrder")
    actions.append("account.changePassword")
    if user["kind"] in ("owner", "staff") and "residents" in resolve_routes(user):
        actions.append("care.finishTrialFollowup")
    if user["kind"] == "family":
        actions.extend(
            ["family.consent"]
            if user.get("portalSelf")
            else ["family.subscribe", "family.read"]
        )
    elif has(user, "relatives") and has(user, "family.share"):
        actions.append("family.consent")
    if user["kind"] == "family" and "careSchedule" in user.get("portalScopes", ()):
        actions.append("portal.feedback")
    if not (has(user, "clinical") and has(user, "medical")):
        actions = [
            a
            for a in actions
            if a not in ("dossier.reviewDocument", "dossier.signSummary")
        ]
    if not has(user, "clinical"):
        actions = [a for a in actions if ACTION_GRANTS.get(a) != "clinical.rules"]
    if not has(user, "care"):
        actions = [
            a for a in actions if a not in ("gw.propose", "gw.confirm", "gw.dismiss")
        ]
    if has_agent_domain(user):
        actions += ["ops.suggest", "ops.review"]
    else:
        actions = [action for action in actions if not action.startswith("agent.")]
    if user["kind"] in ("owner", "family") and not user.get("portalSelf"):
        actions.append("dossier.relative")
    if manages_accounts(user):
        actions.extend(STAFF_ACCOUNT_ACTIONS)
    if user["kind"] == "owner":
        actions += [
            *FACILITY_COMMANDS,
            "access.settings",
            "access.mediaSettings",
            "access.trialSettings",
        ]
    from . import campus_access

    if campus_access.bound(user):
        actions = [a for a in actions if a not in ("ops.expense", "ops.suggest")]
    return sorted(actions)


def can_view_audit(user, action, *, agent_initiator=None, agent_grants=()):
    if not has(user, "audit"):
        return False
    if user["kind"] == "owner":
        return True
    if action == "leads.public":
        return has(user, "intake")
    if action == "family.consent":
        return has(user, "relatives") and has(user, "family.share")
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

    if data["assessments"] and not can_record_scale(user):
        # General care needs the scores and final level. Diagnoses and source paperwork
        # remain with personnel authorized to read the professional assessment.
        visible_scores = (
            "version",
            "name",
            "assessedOn",
            "scores",
            "subtotals",
            "total",
            "grade",
            "gradeName",
        )
        data["assessments"] = [
            {**r, "scale": select_fields(r["scale"], visible_scores)}
            if r.get("scale")
            else r
            for r in data["assessments"]
        ]

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
        "longCare",
        "gateway.simulate",
        "alerts",
        "shifts",
    ):
        basic = ["id", "name", "status", "bedId"]
        if any_grant("care", "clinical", "intake", "residents"):
            basic.extend(
                [
                    "age",
                    "gender",
                    "admittedAt",
                    "endDate",
                    "stayType",
                    "formalizedAt",
                    "trialDays",
                    "trialEndsAt",
                    "dischargedAt",
                    "archiveUntil",
                    "registeredAt",
                    "registeredCampusId",
                    "level",
                ]
            )
        if any_grant("intake", "relatives"):
            basic.append("contact")
        if any_grant("intake", "finance"):
            basic.extend(["admittedAt", "dischargedAt", "billingDay", "stayType", "formalizedAt", "trialEndsAt", "trialPrice", "trialDays"])
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
