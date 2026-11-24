"""随首次启动日期生成虚构院区与照护记录。"""

from .clinical import (
    add_medication,
    give_medication,
    handover,
    review_medication,
    vital,
)
from .plans import assess
from .records import LEVELS, iso_date, offset_date
from .residency import make_card_code


WARD_NAMES = ("颐养一区", "颐养二区", "护理三区")


STAFF = ("林晓", "陈悦", "周宁", "吴桐")


COLLECTIONS = (
    "beds",
    "residents",
    "inquiries",
    "assessments",
    "plans",
    "tasks",
    "medications",
    "vitals",
    "handovers",
    "leaves",
    "qualityChecks",
    "bedMoves",
    "archives",
)


def seed(today: str) -> dict:
    """生成相对营业日的虚构演示记录；固定样本 ID 方便跨业务引用。"""
    today = iso_date(today, "业务日期")
    state = {name: [] for name in COLLECTIONS}
    names = (
        "沈月兰",
        "徐松年",
        "梁秋萍",
        "许敬安",
        "温桂香",
        "苏承远",
        "姜慧芳",
        "顾明哲",
        "宋雅琴",
        "吴泽民",
        "徐雪芬",
        "方瑞华",
        "江映秋",
        "程建中",
        "余月华",
        "李书远",
        "叶素清",
        "冯玉芬",
        "郑和宜",
    )
    occupied = (8, 6, 5)
    for ward_num, ward in enumerate(WARD_NAMES):
        for slot in range(8):
            index = ward_num * 8 + slot + 1
            bed = {
                "id": f"b{index:03}",
                "label": f"{ward_num + 1}0{slot // 2 + 1}-{slot % 2 + 1:02}",
                "ward": ward,
                "dailyRate": (60, 70, 80)[ward_num],
                "residentId": "",
                "status": "空闲",
            }
            state["beds"].append(bed)
            if slot >= occupied[ward_num]:
                continue
            n = len(state["residents"])
            resident_id = f"r{n + 1:03}"
            level = LEVELS[(ward_num + slot // 4) % len(LEVELS)]
            entered = offset_date(today, -60 - 3 * n)
            resident = {
                "id": resident_id,
                "name": names[n],
                "age": 72 + n % 17,
                "gender": "女" if n % 2 == 0 else "男",
                "level": level,
                "status": "在住",
                "contact": f"家属{n + 1:02}（演示）",
                "bedId": bed["id"],
                "risk": "步行需陪护" if n % 4 == 0 else "",
                "allergies": "青霉素" if n % 5 == 0 else "",
                "admittedAt": entered,
                "endDate": offset_date(today, 14 + n * 4),
                "dischargedAt": "",
                "summary": f"{ward}在住长者，日常照护由{STAFF[n % 4]}跟进。",
                "inquiryId": "",
            }
            state["residents"].append(resident)
            bed.update(status="已入住", residentId=resident_id)
            state["bedMoves"].append(
                {
                    "id": f"bm{n + 1:03}",
                    "residentId": resident_id,
                    "kind": "入住",
                    "date": entered,
                    "beforeBedId": "",
                    "bedId": bed["id"],
                    "cardCode": make_card_code(len(state["bedMoves"]) + 1),
                }
            )
    routines = (
        ("晨间生活照护", "生活照料", "07:30"),
        ("体征巡测", "健康观察", "08:00"),
        ("床旁巡访", "日常照护", "09:00"),
        ("午餐陪护", "膳食照护", "11:30"),
        ("午间巡视", "日常照护", "13:00"),
        ("活动陪伴", "活动支持", "15:00"),
        ("晚间巡房", "日常照护", "19:30"),
        ("交班前巡访", "日常照护", "20:00"),
    )
    for offset in range(7, -1, -1):
        day = offset_date(today, -offset)
        count = (18, 22, 19, 24, 20, 21, 23, 24)[7 - offset]
        for i in range(count):
            title, kind, clock = routines[i * 8 // count]
            resident = state["residents"][(i + offset) % len(names)]
            # 当班仅完成首批；近几日保留少量逾期工单，便于工作台追踪。
            done = i < (count - offset % 3 if offset else 10)
            task = {
                "id": f"t{offset}_{i + 1:02}",
                "residentId": resident["id"],
                "title": title,
                "assignee": STAFF[i % 4],
                "kind": kind,
                "time": clock,
                "date": day,
                "status": "已完成" if done else "待执行",
                "note": "已按交班安排执行。" if done else "",
            }
            if done:
                task.update(operator=task["assignee"], completedAt=day)
            state["tasks"].append(task)
    for i, name in enumerate(("杜文英", "许庭安", "钟玉珍")):
        state["inquiries"].append(
            {
                "id": f"i{i + 1:03}",
                "name": name,
                "contact": "家属（演示）",
                "date": offset_date(today, -i),
                "status": "待跟进",
                "note": ("计划本周探访", "咨询空闲床位", "预约入住评估")[i],
            }
        )
    for i in range(3):
        resident = state["residents"][i]
        assess(
            state,
            {
                "residentId": resident["id"],
                "level": LEVELS[i],
                "assignee": STAFF[i],
                "note": (
                    "按本人生活习惯安排起居协助。",
                    "活动前确认陪护安排。",
                    "请责任人员复核既有照护要求。",
                )[i],
            },
            today,
        )
        add_medication(
            state,
            {
                "residentId": resident["id"],
                "name": ("青霉素类样例药 A", "样例药 B", "样例药 C")[i],
                "assignee": STAFF[i],
                "instruction": "按演示医嘱核对，记录执行情况。",
            },
            today,
        )
        medication = state["medications"][-1]
        if i:
            review_medication(
                state, {"medicationId": medication["id"], "reviewer": STAFF[0]}, today
            )
        if i == 2:
            give_medication(
                state, {"medicationId": medication["id"], "operator": STAFF[2]}, today
            )
    for i in range(4):
        vital(
            state,
            {
                "residentId": state["residents"][i]["id"],
                "metric": "体温",
                "value": ("37.9", "36.5", "36.6", "36.7")[i],
                "unit": "℃",
                "abnormal": i == 0,
                "note": "值班人员已标记，等待复测。" if i == 0 else "",
                "operator": STAFF[i],
            },
            today,
        )
    handover(state, {"assignee": STAFF[0], "note": "接班后关注待复核记录。"}, today)
    return state
