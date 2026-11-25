"""Monthly service periods and pending issue dates for confirmed admissions."""

from calendar import monthrange
from collections import defaultdict
from datetime import timedelta

from .records import month_bounds, parse_day


def monthly_start(resident):
    if resident.get("stayType") == "trial":
        return None
    if resident.get("formalizedAt"):
        # Checkout day begins the first night outside the prepaid trial package.
        return max(resident["formalizedAt"], resident.get("trialEndsAt") or "")
    return resident.get("admittedAt")


def bill_day(resident):
    # Contracts made under the original calendar-month policy have no selected day.
    selected = resident.get("billingDay", 1)
    if type(selected) is not int or not 1 <= selected <= 31:
        raise ValueError("约定账单日须为 1 至 31 日")
    return selected


def anchor(first, day):
    return first.replace(day=min(day, monthrange(first.year, first.month)[1]))


def next_anchor(current, day):
    here = anchor(current, day)
    if current < here:
        return here
    next_month = anchor(current, 31) + timedelta(days=1)
    return anchor(next_month, day)


def period(resident, start):
    day = bill_day(resident)
    end = next_anchor(start, day) - timedelta(days=1)
    if resident.get("dischargedAt"):
        end = min(end, parse_day(resident["dischargedAt"]))
    return {
        "residentId": resident["id"],
        "month": start.isoformat()[:7],
        "billingDate": start.isoformat(),
        "billingDay": day,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
    }


def selected_period(resident, payload, today):
    first, last = month_bounds(payload.get("month"), today)
    start = monthly_start(resident)
    if not start:
        raise ValueError(
            "试住期间只收一次试住费，转正后开始月付"
            if resident.get("stayType") == "trial"
            else "该档案没有可计费的入住记录"
        )
    arrival = parse_day(start)
    discharge = resident.get("dischargedAt")
    if resident["status"] == "已退住" and not discharge:
        raise ValueError("退住档案缺少退住日期")
    specific = payload.get("billingDate")
    dates = sorted({arrival, anchor(first, bill_day(resident))})
    dates = [
        d
        for d in dates
        if max(first, arrival) <= d <= last
        and (not discharge or d.isoformat() <= discharge)
    ]
    if specific is not None:
        chosen = parse_day(specific)
        if chosen not in dates:
            raise ValueError("请选择本账期实际的账单日")
    else:
        available = [d for d in dates if d.isoformat() <= today]
        if len(available) > 1:
            raise ValueError(
                "本月有两期，请选择具体账单日："
                + "、".join(d.isoformat() for d in available)
            )
        if not dates:
            raise ValueError("该长辈在此账期没有入住记录")
        chosen = available[0] if available else dates[0]
    if chosen.isoformat() > today:
        raise ValueError(f"尚未到本期账单日 {chosen.isoformat()}")
    return period(resident, chosen)


def billed(bills, candidate):
    for b in bills:
        if b.get("kind") in ("trial", "security"):
            continue
        if b.get("billingDate") == candidate["billingDate"]:
            return True
        if not b.get("billingDate") and b.get("month") == candidate["month"]:
            return True
        # A restored or older invoice may only provide its charged service dates.
        if (
            b.get("startDate")
            and b.get("endDate")
            and b["startDate"] <= candidate["endDate"]
            and candidate["startDate"] <= b["endDate"]
        ):
            return True
    return False


def pending_periods(data, today):
    """First reached, unissued period per scoped resident; reading never posts money."""
    by_resident = defaultdict(list)
    for b in data["bills"]:
        by_resident[b["residentId"]].append(b)
    result = []
    for resident in data["residents"]:
        first = monthly_start(resident)
        if not first or resident.get("billingDay") is None:
            continue
        start = parse_day(first)
        stop = min(today, resident.get("dischargedAt") or today)
        issued = by_resident[resident["id"]]
        while start.isoformat() <= stop:
            candidate = period(resident, start)
            if not billed(issued, candidate):
                result.append(candidate)
                break
            start = next_anchor(start, candidate["billingDay"])
    return sorted(result, key=lambda r: (r["billingDate"], r["residentId"]))
