"""Document the clinician's completed risk instrument without inferring a score or treatment."""

from .records import iso_date, text_field

TOPICS = ("跌倒/坠床", "压疮", "噎食/误吸", "走失", "其他")
LEVELS = ("低风险", "中风险", "高风险", "待专业复核")


def _score(value):
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 10000:
        raise ValueError("量表分值须为 0 至 10000 的整数，未评分请留空")
    return value


def record(value, today):
    if not isinstance(value, dict) or set(value) != {
        "topic",
        "instrument",
        "level",
        "score",
        "maximum",
        "factors",
        "immediate",
        "follow",
        "routine",
        "avoid",
        "nextReview",
    }:
        raise ValueError("请核对专项报告字段")
    if value["topic"] not in TOPICS or value["level"] not in LEVELS:
        raise ValueError("请选择专项及经评估人员确认的等级")
    total, maximum = _score(value["score"]), _score(value["maximum"])
    if maximum is not None and (maximum == 0 or total is None or total > maximum):
        raise ValueError("请核对原量表总分与满分")
    factors = value["factors"]
    if not isinstance(factors, list) or len(factors) > 30:
        raise ValueError("最多可登记 30 项分值因素")
    entries = []
    for item in factors:
        if not isinstance(item, dict) or set(item) != {"group", "finding", "points"}:
            raise ValueError("请逐项填写评估因素")
        entries.append(
            {
                "group": text_field(item["group"], "评估维度", required=True, limit=60),
                "finding": text_field(
                    item["finding"], "观察与依据", required=True, limit=200
                ),
                "points": _score(item["points"]),
            }
        )
    next_date = (
        iso_date(value["nextReview"], "下次评估日期") if value["nextReview"] else ""
    )
    if next_date and next_date < today:
        raise ValueError("下次专项评估日期不可早于登记日")
    return {
        "topic": value["topic"],
        "level": value["level"],
        "factors": entries,
        "score": total,
        "maximum": maximum,
        "instrument": text_field(
            value["instrument"], "原量表或评估依据", required=True, limit=150
        ),
        "nextReview": next_date,
        **{
            k: text_field(value[k], "专业人员意见", limit=800)
            for k in ("immediate", "follow", "routine", "avoid")
        },
    }
