"""Record professional observations against GB/T 42195-2022, tables 2–6."""

from .records import iso_date, required_field, text_field

VERSION = "GB/T 42195-2022"
GROUPS = {
    "自理能力": {
        "进食": 4,
        "修饰": 4,
        "洗澡": 4,
        "穿脱上衣": 4,
        "穿脱裤子和鞋袜": 4,
        "小便控制": 4,
        "大便控制": 4,
        "如厕": 4,
    },
    "基础运动能力": {"床上体位转移": 4, "床椅转移": 4, "平地行走": 4, "上下楼梯": 3},
    "精神状态": {
        "时间定向": 4,
        "空间定向": 4,
        "人物定向": 4,
        "记忆": 4,
        "理解能力": 4,
        "表达能力": 4,
        "攻击行为": 1,
        "抑郁症状": 1,
        "意识水平": 2,
    },
    "感知觉与社会参与": {
        "视力": 2,
        "听力": 2,
        "执行日常事务": 4,
        "使用交通工具外出": 3,
        "社会交往能力": 4,
    },
}
CATALOG = {
    "name": "老年人能力评估规范",
    "version": VERSION,
    "sourceUrl": "https://www.zhuhai.gov.cn/smzj/attachment/0/385/385975/3719486.pdf",
    "groups": GROUPS,
    "adjustments": [
        "无",
        "已确诊痴呆（F00–F03）",
        "精神科专科医生已诊断其他精神和行为障碍（F04–F99）",
        "近30天两次及以上照护风险事件",
        "昏迷",
    ],
}
LEVEL_NAMES = ("能力完好", "轻度失能", "中度失能", "重度失能", "完全失能")


def score_scale(raw, method, today):
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        raise ValueError("量表版本无效，请重新打开评估表。")
    if method not in ("线上采集", "纸质量表录入"):
        raise ValueError("请选择有效的量表采集方式。")
    scores = raw.get("scores")
    maxima = {
        name: maximum for group in GROUPS.values() for name, maximum in group.items()
    }
    if not isinstance(scores, dict) or scores.keys() != maxima.keys():
        raise ValueError("请完整录入本版本全部26项评分。")
    if any(
        type(scores[name]) is not int or not 0 <= scores[name] <= maximum
        for name, maximum in maxima.items()
    ):
        raise ValueError("分项评分超出该项量表范围。")
    adjustment = raw.get("adjustment")
    if adjustment not in CATALOG["adjustments"]:
        raise ValueError("请核对等级调整依据。")
    if adjustment == "昏迷" and scores["意识水平"] != 0:
        raise ValueError("昏迷与所填意识水平分数不一致。")
    reason = text_field(
        raw.get("basis"), "等级调整的记录依据", required=adjustment != "无"
    )
    assessed = iso_date(raw.get("assessedOn"), "实际评估日期")
    if assessed > today:
        raise ValueError("实际评估日期不能晚于今天。")
    evaluators = [
        required_field(raw, k, label)
        for k, label in (
            ("assessor", "评估人员一（含医护背景）"),
            ("coAssessor", "评估人员二"),
        )
    ]
    if evaluators[0] == evaluators[1]:
        raise ValueError("请分别登记两位评估人员的姓名或工号。")
    ref = text_field(
        raw.get("reference"),
        "纸质量表编号",
        required=method == "纸质量表录入",
        limit=150,
    )
    subtotals = {
        group: sum(scores[name] for name in items) for group, items in GROUPS.items()
    }
    total = sum(subtotals.values())
    initial = sum(total < threshold for threshold in (90, 66, 46, 30))
    final = 4 if adjustment == "昏迷" else min(4, initial + (adjustment != "无"))
    return dict(
        version=VERSION,
        name=CATALOG["name"],
        assessedOn=assessed,
        source=method,
        sourceUrl=CATALOG["sourceUrl"],
        scores=dict(scores),
        subtotals=subtotals,
        total=total,
        initialGrade=initial,
        grade=final,
        gradeName=LEVEL_NAMES[final],
        adjustment=adjustment,
        basis=reason,
        assessors=evaluators,
        reference=ref,
    )
