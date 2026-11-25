"""Expose existing timed workflows without generating a second copy of their work."""

from datetime import datetime, timedelta

from . import access_policy as access, campus_access, daily_life
from .backups import PERIOD, slot_for
from .care.residency import TRIAL_PENDING
from .operations import contract_renewal
from .operations.billing_cycles import pending_periods
from .rounds.records import policy as rounds_policy


def overview(db, state, user, now):
    scoped = campus_access.projection(db, state, user)
    day = now.date().isoformat()
    routes = set(user.get("routes", access.resolve_routes(user)))
    owner = user["kind"] == "owner"
    items = []

    def add(
        id,
        title,
        status,
        description,
        route,
        tab,
        *,
        count=None,
        next_at=None,
        kind="work",
    ):
        items.append(
            dict(
                id=id,
                title=title,
                status=status,
                description=description,
                route=route if route in routes else "",
                tab=tab,
                count=count,
                nextAt=next_at,
                kind=kind,
            )
        )

    if access.has(user, "care") or access.has(user, "clinical"):
        policy = rounds_policy(db)
        ids = {r["id"] for r in scoped["residents"]}
        jobs = sum(r[0] in ids for r in db.execute("SELECT resident FROM rounds_jobs"))
        add(
            "health-rounds",
            "日常起居助理巡查与提醒",
            "已启用" if policy["enabled"] else "已暂停",
            f"每 {policy['intervalMinutes']} 分钟检查，{policy['notifyAt']} 起处理当日提醒与获授权家属的推送。"
            "按长辈已设定的自动生成方式执行。",
            "settings" if owner else "inbox",
            "rounds",
            count=jobs,
            next_at=policy["nextRunAt"],
        )
        if access.has(user, "medical") and access.has(user, "clinical"):
            health = db.execute("SELECT enabled,interval_min,next_at FROM rounds_health_policy WHERE singleton=1").fetchone()
            health_jobs = sum(row[0] in ids for row in db.execute("SELECT resident FROM rounds_health_jobs"))
            add("health-review", "健康复核助理", "已启用" if health[0] else "已暂停",
                f"每 {health[1]} 分钟逐人核对健康资料，在个人档案中保留带出处的草稿。",
                "settings" if owner else "residents", "rounds" if owner else "",
                count=health_jobs, next_at=health[2] if health[0] else None)
    if access.has(user, "care"):
        tasks = [
            row
            for row in scoped["tasks"]
            if row.get("planId") and row["status"] == "待执行"
        ]
        add(
            "approved-plans",
            "照护计划派工与复评",
            "按计划",
            "护理计划获批准时自动派发照护任务，并登记下一次复评提醒。",
            "care",
            "tasks",
            count=len(tasks),
            next_at=min(
                (r["date"] + "T" + r["time"] for r in tasks if r["date"] >= day),
                default=None,
            ),
        )
    if access.has(user, "care.groupConfirm"):
        add(
            "group-activity-signoff",
            "集体活动到时签认",
            "按活动结束时间",
            "已登记的集体活动结束后进入签认待办，工作人员核对实际参加者。",
            "care",
            "groupLife",
            count=daily_life.pending_count(db, state, user, now),
        )
    if access.has(user, "clinical"):
        followups = [
            r
            for r in scoped["followups"]
            if r.get("status") == "待随访" and r.get("dueDate")
        ]
        add(
            "clinical-followups",
            "筛查后的预约随访",
            "按预约",
            "随访按经办人约定日期显示到期提醒，完成后保留随访结论。",
            "care",
            "followups",
            count=sum(r["dueDate"] <= day for r in followups),
            next_at=min(
                (r["dueDate"] for r in followups if r["dueDate"] >= day), default=None
            ),
        )
        medications = [
            r
            for r in scoped["medications"]
            if r.get("status") == "待执行" and r.get("scheduledAt")
        ]
        add(
            "medication-due",
            "到时用药提醒",
            "按已复核医嘱",
            "在已复核医嘱的计划时间显示待给药提醒，由有权人员登记执行。",
            "medications",
            "reminders",
            count=sum(
                r["scheduledAt"] <= now.strftime("%Y-%m-%dT%H:%M") for r in medications
            ),
            next_at=min(
                (
                    r["scheduledAt"]
                    for r in medications
                    if r["scheduledAt"] > now.strftime("%Y-%m-%dT%H:%M")
                ),
                default=None,
            ),
        )
    if access.has(user, "intake"):
        people = scoped["residents"]
        used = contract_renewal.security_used_today(scoped, day)
        renewals = [
            reminder
            for p in people
            if (reminder := contract_renewal.reminder_for(p, day, used.get(p["id"])))
        ]
        add(
            "contract-renewal",
            "入住合同到期续住",
            "按押金及合同约定提醒",
            "设置了押金的长辈在合同到期或押金冲抵时提醒。其他固定期限合同提前 30 天列入续住待办。",
            "residents",
            "renew",
            count=len(renewals),
            next_at=min((row["at"] for row in renewals if row["at"] >= day), default=None),
        )
        add(
            "trial-decision",
            "试住到期与入住确认",
            "每日检查",
            "到期释放床位，未确认入住结果时生成待确认提醒。",
            "residents",
            "trials",
            count=sum(
                r["status"] == TRIAL_PENDING and r.get("trialReleasedOn", day) < day
                for r in people
            ),
            next_at=min(
                (
                    (
                        datetime.fromisoformat(r["trialEndsAt"]).date()
                        + timedelta(days=1)
                    ).isoformat()
                    for r in people
                    if r.get("stayType") == "trial"
                    and r.get("trialEndsAt", "") >= day
                    and r["status"] == "在住"
                ),
                default=None,
            ),
        )
        followups = [
            r
            for r in state.get("trialFollowups", ())
            if r["residentId"] in {p["id"] for p in people} and r["status"] == "待回访"
        ]
        add(
            "trial-followup",
            "未入住回访",
            "按待办日期",
            "登记未正式入住时派给经办人，按约定日跟进并留存报告。",
            "residents",
            "trials",
            count=len(followups),
            next_at=min(
                (r["dueDate"] for r in followups if r["dueDate"] >= day), default=None
            ),
        )
    if access.has(user, "finance"):
        add(
            "monthly-billing",
            "月付账单到期提醒",
            "按长辈账单日",
            "根据月付账单日列出待出账期，财务核算确认后生成账单。",
            "billing",
            "due",
            count=len(pending_periods(scoped, day)),
        )
        add(
            "overdue-billing",
            "服务期结束后的欠费提醒",
            "按账单服务期",
            "列出服务期已结束且仍有欠款的账单，财务人员可核对后登记催缴。",
            "billing",
            "reminders",
            count=sum(
                b["balance"] > 0 and bool(b.get("endDate")) and b["endDate"] < day
                for b in scoped["bills"]
            ),
        )
    if owner:
        add(
            "encrypted-backup",
            "加密快照",
            "已启用",
            "按备份策略创建数据库时间点并保留加密副本。",
            "settings",
            "backups",
            kind="maintenance",
            next_at=datetime.fromtimestamp(
                slot_for(int(now.timestamp())) + PERIOD, now.tzinfo
            ).isoformat(timespec="minutes"),
        )
        add(
            "archive-retention",
            "归档保管到期",
            "每日检查",
            "核对长辈及意向客户已归档记录的保管期限。",
            "activity",
            "",
            kind="maintenance",
        )
    return items
