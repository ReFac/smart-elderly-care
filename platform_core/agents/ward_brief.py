"""Produce shareable ward counts from records the current speaker may see."""

import json

from .. import access_policy, campus_access
from . import chat_scope, resident_status


def health(db, actor, state, current, chosen, today):
    totals = access_policy.has(actor, "health.overview")
    clinical = totals or access_policy.has(actor, "clinical")
    alerts = totals or access_policy.has(actor, "alerts")
    if not (clinical or alerts):
        return None
    vitals = [
        v
        for v in state["vitals"]
        if v.get("date") == today and v.get("residentId") in current
    ]
    pending = confirmed = cough = 0
    if alerts:
        beds = (
            set(chosen["bedIds"])
            if chosen
            else campus_access.allowed_beds(db, actor, include_rooms=True)
        )
        for bed, status, hint, person, candidates in db.execute(
            """SELECT bed_id,status,resident_hint,resident_id,candidates FROM gateway_alert
               WHERE id=episode AND date(observed_at,'+8 hours')=?""",
            (today,),
        ):
            if beds is not None and bed not in beds:
                continue
            linked = {x for x in (hint, person) if x}
            if linked - current or (
                not linked and not (current & set(json.loads(candidates)))
            ):
                continue
            pending += status in ("待复核", "无法核实")
            confirmed += status == "已核实"
    if clinical:
        for row in db.execute(
            "SELECT resident,signals FROM rounds_staff_inbox WHERE day=?", (today,)
        ):
            if row[0] in current and "cough" in json.loads(row[1]):
                cough += 1
    return {
        "日期": today,
        "在住人数": len(current),
        **(
            {
                "已记录体征人数": len({v["residentId"] for v in vitals}),
                "新增异常体征记录": sum(bool(v.get("abnormal")) for v in vitals),
                "咳嗽增多提示人数": cough,
            }
            if clinical
            else {}
        ),
        **(
            {"现场核实设备异常": confirmed, "尚未核实的设备提示": pending}
            if alerts
            else {}
        ),
    }


def topic(text):
    """Recognize standalone daily status questions; leave analysis and named people to chat."""
    import re

    if chat_scope.overview_question(text):
        return "operations"
    query = re.sub(r"[\s，、。！？,?.!]", "", text)
    if resident_status.question(text) is not None:
        return "health"
    if re.search(
        r"流水|营收|实收|新增款|欠款|待缴|今日的财|今天的财|财务", query
    ) and re.fullmatch(
        r"(?:请问|看一下|看看|我想了解|养老院|院里|院内|我们|这个月|本月|今天|今日|目前|截至|的|和|"
        r"财务|财|流水|营收|实收|新增款|待欠款|欠款|待缴|净入账|收入|收款|情况|有多少|多少|如何|怎么样|呢|呀|啊)+",
        query,
    ):
        return "finance"
    return ""


def phrases(kind, facts):
    if kind == "operations":
        return operations_phrases(facts)
    if kind == "finance":
        cash = facts.get("到账与欠款（元）")
        if cash is None:
            return ["当前账号没有这一范围的财务查阅权限。"]

        def money(key):
            return f"{cash[key]:,.2f} 元"

        net = cash["今日扣费后净入账"]
        if cash.get("本月已核实退款"):
            received = cash["今日新增实收（含预缴）"] + cash["今日已核实退款"]
            return [
                f"今天新收到 {received:,.2f} 元，已退 {money('今日已核实退款')}。",
                f"本月扣除已退的 {money('本月已核实退款')} 后，收款余额为 {money('本月至今流水（含预缴）')}，含预缴款。",
                f"截至目前，账单待缴余额为 {money('截至今日待缴余额')}。",
            ]
        return [
            f"本月至今共收到 {money('本月至今流水（含预缴）')}，其中包括预缴款。",
            f"今天新收到 {money('今日新增实收（含预缴）')}。"
            + (
                f"扣除机构承担的手续费，净入账 {net:,.2f} 元。"
                if isinstance(net, (int, float))
                else "有历史凭证的手续费待核对，今日净入账尚未确定。"
            ),
            f"截至目前，账单待缴余额为 {money('截至今日待缴余额')}。",
        ]
    health = facts.get("今日已登记健康情况")
    if health is None:
        return ["当前账号无法查阅这个范围的健康汇总。"]
    people = health["在住人数"]
    if not people:
        return ["当前授权范围内没有在住老人。"]
    changes = health_changes(health)
    if "已记录体征人数" in health:
        count = health["已记录体征人数"]
        changes.append(
            f"在住 {people} 人，今天已有 {count} 人登记体征。"
            if count
            else f"在住 {people} 人，今天还没有体征登记。"
        )
    else:
        changes.append("当前汇总仅涵盖获授权查看的设备提示。")
    return changes


def health_changes(health):
    changes = []
    for field, template in (
        ("新增异常体征记录", "今天登记了 {} 条异常体征记录。"),
        ("现场核实设备异常", "今天有 {} 起设备异常已由工作人员到场核实。"),
        ("咳嗽增多提示人数", "有 {} 位老人的巡查记录提示咳嗽比平时多。"),
        ("尚未核实的设备提示", "还有 {} 起设备提示，现场情况尚未核实。"),
    ):
        if health.get(field):
            changes.append(template.format(health[field]))
    if not changes:
        changes.append(
            "截至目前，今日已登记的记录中未见新增健康异常。"
            if "已记录体征人数" in health
            else "今天的设备提示中没有已核实的异常或待核实事项。"
        )
    return changes


def operations_phrases(facts):
    lines = []
    beds = facts.get("当前床位")
    if beds is not None:
        occupancy = f"目前在住 {beds['在住人数']} 人，有 {beds['空床数']} 张空床可安排。"
        if beds.get("今日新入住登记数"):
            occupancy += f"今天有 {beds['今日新入住登记数']} 笔新入住登记。"
        lines.append(occupancy)

    tasks = facts.get("照护工单")
    if tasks is not None:
        counts = tasks["今日计划按当前状态"]
        done, pending = counts.get("已完成", 0), counts.get("待执行", 0)
        care = (
            f"在住长辈今天安排了 {done + pending} 项照护，已完成 {done} 项，还有 {pending} 项待执行。"
            if done or pending
            else "在住长辈今天暂无已排定的照护工单。"
        )
        if tasks["以往日期仍待执行"]:
            care += f"此前还有 {tasks['以往日期仍待执行']} 项照护逾期未完成，需要跟进。"
        lines.append(care)

    health = facts.get("今日已登记健康情况")
    if health and health["在住人数"]:
        covered = health.get("已记录体征人数")
        coverage = ""
        if covered is not None:
            coverage = f"今天已有 {covered} 位长辈登记体征。" if covered else "今天还没有体征登记。"
        lines.append(coverage + "".join(health_changes(health)))

    cash = facts.get("到账与欠款（元）")
    if cash is not None:
        if cash.get("本月已核实退款"):
            lines.append("".join(phrases("finance", facts)))
        else:
            lines.append(
                f"今天新收到 {cash['今日新增实收（含预缴）']:,.2f} 元，本月累计实收 "
                f"{cash['本月至今流水（含预缴）']:,.2f} 元（含预缴）。当前账单还有 "
                f"{cash['截至今日待缴余额']:,.2f} 元待缴。"
            )
    inventory = facts.get("物资")
    if inventory and (inventory["低于下限品项数"] or not lines):
        lines.append(
            f"库存中有 {inventory['低于下限品项数']} 种物资低于补货下限，需要核对。"
            if inventory["低于下限品项数"]
            else f"当前登记了 {inventory['品项总数']} 种物资，库存均未低于补货下限。"
        )
    return lines or ["当前账号可查看的资料中，没有可汇总的院内运营记录。"]
