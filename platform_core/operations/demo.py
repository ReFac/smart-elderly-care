"""从护理域演示数据构造相互关联的运营单据。"""

from datetime import timedelta

from ..bootstrap import OPERATIONS_COLLECTIONS
from .assistants import generate_suggestion
from .billing import CARE_RATES, deposit, generate_bill
from .records import parse_day
from .reports import generate_report
from .resources import assign_shift, record_stock


def seed(today: str, state: dict) -> dict:
    state.update({key: [] for key in OPERATIONS_COLLECTIONS})
    for index, (name, unit, quantity, minimum) in enumerate(
        (
            ("医用检查手套", "盒", 36, 15),
            ("成人护理垫", "包", 8, 12),
            ("免洗手消毒液", "瓶", 18, 8),
            ("一次性口罩", "盒", 24, 10),
            ("床品套件", "套", 16, 6),
        )
    ):
        item_id = f"stock-{index + 1}"
        state["inventory"].append(
            dict(id=item_id, name=name, unit=unit, quantity=0, minimum=minimum)
        )
        # 两个相邻自然周的虚构流水使趋势、补货及大额领用都能复核。
        uses = [(12, 2), (10, 2), (8, 1), (5, 2), (2, 3), (0, 8 if index == 1 else 2)]
        opening = quantity + sum(qty for _, qty in uses)
        start = parse_day(today) - timedelta(days=14)
        record_stock(
            state,
            dict(itemId=item_id, type="入库", quantity=opening, note="演示期初入库"),
            start.isoformat(),
        )
        for offset, used in uses:
            when = (parse_day(today) - timedelta(days=offset)).isoformat()
            record_stock(
                state,
                dict(itemId=item_id, type="出库", quantity=used, note="照护区日常领用"),
                when,
            )
    scheduled = dict.fromkeys(
        t["assignee"] for t in state.get("tasks", []) if t.get("assignee")
    )
    staff_names = list(dict.fromkeys([*scheduled, "林晓", "陈悦", "周宁"]))
    for index, period in enumerate(("早班", "中班", "夜班")):
        assign_shift(
            state,
            dict(
                staff=staff_names[index],
                period=period,
                date=today,
            ),
            today,
        )
    residents = [
        r
        for r in state["residents"]
        if r.get("status") == "在住"
        and r.get("admittedAt")
        and r["admittedAt"] <= today
    ]
    for index, resident in enumerate(residents[:3]):
        draft = dict(residentId=resident["id"], month=today[:7])
        if index == 2:
            # 此份演示合同有护理日价例外，留给财务人员核对。
            draft["careFee"] = CARE_RATES.get(resident["level"], 45) + 8
        generate_bill(state, draft, today)
    if len(residents) >= 3:
        prior_end = parse_day(today).replace(day=1) - timedelta(days=1)
        candidate = residents[1]
        if candidate["admittedAt"] <= prior_end.isoformat():
            generate_bill(
                state,
                dict(residentId=candidate["id"], month=prior_end.strftime("%Y-%m")),
                today,
            )
    if residents:
        deposit(state, dict(residentId=residents[0]["id"], amount=300), today)
        generate_suggestion(
            state, dict(category="日常照护", residentId=residents[0]["id"]), today
        )
    generate_suggestion(state, dict(category="物资管控"), today)
    generate_suggestion(state, dict(category="运营分析"), today)
    generate_report(state, dict(month=today[:7]), today)
    return state
