"""Authorized cash receipts for one explicit reporting window, computed locally."""

import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from ..operations.assistants import cite_records


def reporting_window(goal, day):
    today = date.fromisoformat(day)
    token_pattern = (
        r"(?<![0-9])(?:[0-9]{4}年[0-9]{1,2}月(?:[0-9]{1,2}[日号])?|"
        r"[0-9]{4}-[0-9]{1,2}(?:-[0-9]{1,2})?|[0-9]{4}年|[0-9]{1,2}月)(?![0-9])"
        r"|上个月|上月|本月|这个月|这月|今年|本年|去年|上年|今天|今日|昨天|昨日"
    )
    tokens = re.findall(token_pattern, goal)
    rest = re.sub(token_pattern, "", goal)
    if len(tokens) > 1 or re.search(
        r"季度|周|星期|过去|最近|近[一二三四五六七八九十0-9]|[年月日天号]|上旬|中旬|下旬",
        rest,
    ):
        raise ValueError("请指定一个日期、自然月或年度查询")
    token = tokens[0] if tokens else "本月"
    numbers = [int(n) for n in re.findall(r"[0-9]+", token)]
    try:
        if len(numbers) == 3:
            first = last = date(*numbers)
        elif (
            len(numbers) == 1
            and token.endswith("年")
            or token in {"今年", "本年", "去年", "上年"}
        ):
            year = (
                numbers[0] if numbers else today.year - int(token in {"去年", "上年"})
            )
            first, last = date(year, 1, 1), date(year, 12, 31)
        elif token in {"今天", "今日", "昨天", "昨日"}:
            first = last = today - timedelta(days=int(token in {"昨天", "昨日"}))
        else:
            month_day = today.replace(day=1)
            if token in {"上月", "上个月"}:
                month_day -= timedelta(days=1)
            year, month = (
                numbers
                if len(numbers) == 2
                else (month_day.year, numbers[0] if numbers else month_day.month)
            )
            first, last = (
                date(year, month, 1),
                date(year, month, monthrange(year, month)[1]),
            )
    except (ValueError, OverflowError):
        raise ValueError("查询日期无效") from None
    if first > today:
        raise ValueError("尚未到达所选账期")
    return first.isoformat(), min(today, last).isoformat()


def receipts(records, goal, day):
    begin, end = reporting_window(goal, day)
    evidence = []
    total = Decimal(0)
    for key, label in (("depositEntries", "预交入款"), ("payments", "账单直接实收")):
        rows = sorted(
            (
                r
                for r in records[key]
                if begin <= r["date"] <= end
                and (
                    key == "depositEntries"
                    or r.get("method") in ("线下登记", "微信支付", "支付宝")
                )
            ),
            key=lambda r: r["date"],
            reverse=True,
        )
        subtotal = sum((Decimal(str(r["amount"])) for r in rows), Decimal(0))
        total += subtotal
        evidence.append(
            cite_records(key, label, rows[:10], f"{len(rows)} 笔，合计 ¥{subtotal:.2f}")
        )
    title = f"实收合计 ¥{total:.2f}"
    note = (
        f"{begin} 至 {end}，实收按到账日合计预交入款与直接收款，预交余额冲抵只计一次。"
    )
    if "bills" in records:
        issued = sorted(
            (r for r in records["bills"] if begin <= r.get("date", "") <= end),
            key=lambda r: r["date"],
            reverse=True,
        )
        billed = sum((Decimal(str(r["amount"])) for r in issued), Decimal(0))
        evidence.append(
            cite_records(
                "bills",
                "期间开单应收",
                issued[:10],
                f"{len(issued)} 张，合计 ¥{billed:.2f}",
            )
        )
        title = f"开单应收 ¥{billed:.2f} · 实收 ¥{total:.2f}"
        note += "开单应收按账单创建日期统计全单金额，预交款包含在实际现金收入中。"
    return "", title, note + "每类最多列出 10 笔凭证。", evidence
