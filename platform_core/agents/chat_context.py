"""Collect only facts the current speaker can read, for the selected period and place."""

from collections import Counter
from datetime import timedelta
import hashlib
import json

from .. import access, access_policy as policy, campus_access, facility, history
from . import chat_navigation, region, revenue, ward_brief


ROUTES = {
    "overview": "运营总览",
    "intake": "老人入住",
    "residents": "入住管理",
    "leads": "意向客户",
    "beds": "床位管理及平面图",
    "dossier": "个人与医疗档案",
    "assessments": "能力评估",
    "care": "照护工单",
    "inventory": "物资仓储",
    "billing": "财务结算",
    "shifts": "人员排班",
    "reports": "统计报送",
    "inbox": "预警与确认",
    "medications": "用药管理",
    "longCare": "长期护理保险",
    "activity": "操作日志",
    "history": "最近改动",
    "integrations": "设备与接口",
    "access": "账号与权限",
    "settings": "机构设置",
    "account": "个人中心",
    "tour": "环境导览",
    "family": "家属服务",
    "faq": "常见问题",
}


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def scope(store, db, token, selection):
    actor = store.actor(db, token)
    visual = json.loads(
        db.execute("SELECT visual FROM institution_settings WHERE id=1").fetchone()[0]
    )
    routes = {
        k: v
        for k, v in ROUTES.items()
        if k in actor["routes"] and k not in visual["hiddenRoutes"]
    }
    if "residents" not in routes:
        routes.pop("intake", None)
    state = json.loads(
        db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0]
    )
    if selection is not None and not isinstance(selection, dict):
        raise ValueError("聊天区域格式无效")
    selection = region.selection(selection) if selection else {}
    chosen = (
        facility.scope(db, state, actor, **selection, agent=True) if selection else None
    )
    assigned = (
        campus_access.allowed_beds(db, actor, include_rooms=True)
        if actor.get("facilityScope")
        else None
    )
    area = {
        "policy": actor.get("facilityScope", {}),
        "selection": selection or {},
        "beds": sorted(assigned) if assigned is not None else None,
        "people": sorted(campus_access.resident_ids(state, assigned, actor))
        if assigned is not None
        else None,
        "roomIds": chosen["roomIds"] if chosen else None,
        "residentIds": chosen["residentIds"] if chosen else None,
    }
    signature = [
        actor["id"],
        actor["kind"],
        actor["role"],
        sorted(actor["permissions"]),
        actor["residentId"],
        sorted(actor.get("portalScopes", ())),
        actor.get("familyServices", False),
        routes,
        area,
    ]
    return (
        actor,
        hashlib.sha256(compact(signature).encode()).hexdigest(),
        routes,
        state,
        chosen,
    )


def institution_access(actor):
    return actor["kind"] in ("owner", "staff") and policy.has(actor, "assistants")


def notice_access(actor):
    return policy.has(actor, "notices.publish") and not actor.get("facilityScope")


def history_counts(store, db, actor, chosen, start, end):
    reader = history.Reader(store, db, actor)
    counts = Counter()
    people = set(chosen["residentIds"]) if chosen else None
    rooms = set(chosen["roomIds"]) if chosen else None
    sql = history.SELECT + " WHERE unixepoch(a.at) BETWEEN ? AND ?"
    for row in db.execute(sql, (int(start.timestamp()), int(end.timestamp()))):
        if not reader.visible(row):
            continue
        linked = set(json.loads(row["people"] or "[]"))
        if row["residentId"]:
            linked.add(row["residentId"])
        if linked & reader.archived_ids:
            continue
        if chosen:
            related_rooms = set(json.loads(row["rooms"] or "[]"))
            if not (linked or related_rooms) or not (
                linked <= people and related_rooms <= rooms
            ):
                continue
        counts[row["action"]] += 1
    return dict(sorted(counts.items()))


def evidence(store, db, actor, state, chosen, hours, topics):
    if not institution_access(actor):
        return {"说明": "当前仅提供本人可见界面的使用帮助，没有提供院务记录。"}
    data = access.project(db, state, actor, store.facility_policy)
    now = store.now()
    since = now - timedelta(hours=hours)
    area = chosen["label"] if chosen else "当前账号授权范围"
    facts = {
        "统计起点": since.isoformat(timespec="minutes"),
        "统计截止": now.isoformat(timespec="minutes"),
        "范围": area,
        "精确时间窗内已登记改动（操作代号及次数）": history_counts(
            store, db, actor, chosen, since, now
        ),
    }
    current = {r["id"] for r in data["residents"] if r.get("status") == "在住"}
    if chosen:
        current &= set(chosen["residentIds"])
    if any(policy.has(actor, g) for g in ("intake", "care", "residents", "clinical")):
        beds = [b for b in data["beds"] if not chosen or b["id"] in chosen["bedIds"]]
        facts["当前床位"] = {
            "在住人数": len(current),
            "床位数": len(beds),
            "空床数": sum(not bool(b.get("residentId")) for b in beds),
        }
    room_filter = chat_navigation.room_capacity(topics)
    if room_filter and "beds" in actor["routes"] and any(
        policy.has(actor, grant) for grant in (*facility.READ_GRANTS, facility.MANAGE_GRANT)
    ):
        count, limit = room_filter
        scoped = {key: chosen[key] for key in ("campusId", "buildingId", "floorId", "roomId")} if chosen else {}
        matches = facility.rooms(db, state, actor, bedCount=count, limit=min(limit, 12), **scoped)
        facts["实查房型"] = {
            "每间启用床位数": count,
            "匹配房间数": matches["total"],
            "房号": [{k: r[k] for k in ("number", "buildingName", "floorLabel", "occupiedCount")}
                   for r in matches["rooms"]],
        }
    if policy.has(actor, "care"):
        today = now.date().isoformat()
        tasks = [t for t in data["tasks"] if t["residentId"] in current]
        facts["照护工单"] = {
            "今日计划按当前状态": dict(
                Counter(t["status"] for t in tasks if t["date"] == today)
            ),
            "以往日期仍待执行": sum(
                t["date"] < today and t["status"] == "待执行" for t in tasks
            ),
        }
    if policy.has(actor, "inventory") and not chosen and not actor.get("facilityScope"):
        items = sorted(
            data["inventory"], key=lambda i: (i["quantity"] >= i["minimum"], i["name"])
        )
        facts["物资"] = {
            "品项总数": len(items),
            "低于下限品项数": sum(i["quantity"] < i["minimum"] for i in items),
            "品项明细（最多120项，低库存优先）": [
                {
                    "名称": i["name"],
                    "单位": i["unit"],
                    "现存": i["quantity"],
                    "下限": i["minimum"],
                }
                for i in items[:120]
            ],
        }
        if any(t in topics for t in ("经销", "供应", "供货", "履约", "供应商")):
            facts["经销员或供应商绩效资料"] = (
                "当前没有此类台账，不能据库存推断供应商表现。"
            )
    today = now.date().isoformat()
    if policy.has(actor, "health.overview"):
        residents = campus_access.projection(db, state, actor)["residents"] if actor.get("facilityScope") else state["residents"]
        current_health = {p["id"] for p in residents if p.get("status") == "在住"}
        if chosen:
            current_health &= set(chosen["residentIds"])
    else:
        current_health = current
    health = ward_brief.health(db, actor, state, current_health, chosen, today)
    if health is not None:
        facts["今日已登记健康情况"] = health
    if policy.has(actor, "finance"):
        summary = revenue.overview(data, today, set(chosen["residentIds"]) if chosen else None)
        facts["到账与欠款（元）"] = {
            "日期": today, "本月至今流水（含预缴）": summary["monthGross"],
            "今日新增实收（含预缴）": summary["todayGross"], "今日扣费后净入账": summary["todayNet"] if summary["todayNet"] is not None else "历史凭证手续费待核对",
            "截至今日待缴余额": summary["outstanding"],
        }
        bills = [b for b in data["bills"] if b.get("residentId") in current]
        facts["在住账单当前状态（按账单笔数统计）"] = dict(
            Counter(b["status"] for b in bills)
        )
    if (
        not chosen
        and policy.manages_accounts(actor)
        and any(
            t in topics
            for t in (
                "账号",
                "帐号",
                "账户",
                "帐户",
                "用户",
                "登录",
                "激活",
                "启用",
                "停用",
                "员工",
                "人员",
                "角色",
                "权限",
            )
        )
    ):
        accounts = data["accounts"]
        facts["账号概况"] = {
            "可见账号": len(accounts),
            "启用": sum(a["enabled"] for a in accounts),
            "停用": sum(not a["enabled"] for a in accounts),
            "待激活": sum(a["activationPending"] for a in accounts),
            "角色分布": dict(Counter(a["role"] for a in accounts)),
        }
    return facts
