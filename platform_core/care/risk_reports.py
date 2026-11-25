"""Document the clinician's completed risk instrument without inferring a score or treatment."""

from contextlib import closing

from .. import access
from .records import iso_date, text_field

TOPICS = ("跌倒/坠床", "压疮", "噎食/误吸", "走失", "其他")
LEVELS = ("低风险", "中风险", "高风险", "待专业复核")


def example(store, token):
    """An isolated training record. No query or write against any resident's chart."""
    from .demo import sample_risk_report

    with closing(store.connect()) as db:
        actor = store.actor(db, token)
        access.require(actor, "clinical")
        if actor["kind"] not in ("owner", "staff"):
            raise PermissionError("报告示例供机构照护人员查阅")
    person = {"id": "training-person", "name": "沈月兰", "status": "在住", "sex": "女", "level": "自理"}
    fixture = {"residents": [person], "followups": []}
    sample_risk_report(fixture, store.now().date().isoformat(), person["id"])
    report = fixture["followups"][0]
    report["id"] = "示例-01"
    return {"resident": person, "report": report}


def _score(value):
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 10000:
        raise ValueError("量表分值须为 0 至 10000 的整数，未评分请留空")
    return value


REQUIRED = {"topic", "instrument", "level", "score", "maximum", "factors", "immediate", "follow",
            "routine", "avoid", "nextReview"}
OPTIONAL = {"bands", "dimensions", "tags", "bedside", "preventionSteps", "reviewer", "reviewNote"}


def _rows(value, label, count):
    if not isinstance(value, list) or len(value) > count:
        raise ValueError(f"{label}最多可登记 {count} 项")
    return value


def _fields(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"请核对{label}字段")


def _text_list(value, label, limit):
    return [text_field(item, label, required=True, limit=limit) for item in _rows(value, label, 12)]


def _bands(value):
    bands = []
    for row in _rows(value, "原量表分级区间", 3):
        _fields(row, ("level", "min", "max"), "原量表分级区间")
        low, high = _score(row["min"]), _score(row["max"])
        if row["level"] not in LEVELS[:3] or low is None or (high is not None and high < low):
            raise ValueError("请核对风险分级及原量表区间的起止分值")
        if any(row["level"] == entry["level"] for entry in bands):
            raise ValueError("同一风险等级只能登记一个区间")
        bands.append({"level": row["level"], "min": low, "max": high})
    ordered = sorted(bands, key=lambda entry: entry["min"])
    for previous, following in zip(ordered, ordered[1:]):
        if previous["max"] is None or previous["max"] >= following["min"]:
            raise ValueError("原量表的风险区间不能重叠")
    return bands


def _dimensions(value):
    entries = []
    groups = set()
    for item in _rows(value, "分项得分", 30):
        _fields(item, ("group", "score", "maximum"), "分项得分")
        group = text_field(item["group"], "维度名称", required=True, limit=60)
        score, maximum = _score(item["score"]), _score(item["maximum"])
        if group in groups or not maximum or score is None or score > maximum:
            raise ValueError("请核对分项名称、得分和满分，每项仅登记一次")
        groups.add(group)
        entries.append({"group": group, "score": score, "maximum": maximum})
    return entries


def _extensions(value):
    extra = {}
    if "bands" in value:
        extra["bands"] = _bands(value["bands"])
    if "dimensions" in value:
        extra["dimensions"] = _dimensions(value["dimensions"])
    if "tags" in value:
        extra["tags"] = _text_list(value["tags"], "关注标签", 40)
    if "bedside" in value:
        bedside = value["bedside"]
        _fields(bedside, ("recommended", "avoid"), "床旁防护")
        extra["bedside"] = {key: _text_list(bedside[key], "床旁防护事项", 160) for key in ("recommended", "avoid")}
    if "preventionSteps" in value:
        steps = []
        for step in _rows(value["preventionSteps"], "重点预案步骤", 3):
            _fields(step, ("title", "detail"), "重点预案")
            steps.append({"title": text_field(step["title"], "预案步骤", required=True, limit=60),
                          "detail": text_field(step["detail"], "执行说明", required=True, limit=400)})
        extra["preventionSteps"] = steps
    if "reviewer" in value:
        extra["reviewer"] = text_field(value["reviewer"], "复评负责人", limit=80)
    if "reviewNote" in value:
        extra["reviewNote"] = text_field(value["reviewNote"], "复评备注", limit=800)
    return extra


def record(value, today):
    if not isinstance(value, dict) or not REQUIRED <= value.keys() <= REQUIRED | OPTIONAL:
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
        **_extensions(value),
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
