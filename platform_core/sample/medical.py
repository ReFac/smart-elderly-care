"""Populate the three fictional residents' visit histories in an explicitly selected demo."""

import base64
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from platform_core import medical_visits


@dataclass(frozen=True)
class Encounter:
    key: str
    resident: str
    name: str
    day: str
    department: str
    reason: str
    diagnosis: str
    tests: str
    orders: str
    follow_up: str
    report: str
    category: str


FACILITY = "明川医养门诊部（虚构）"
REPORTS = Path(__file__).with_name("demo_reports")
ENCOUNTERS = (
    Encounter("bp-intake", "r001", "沈月兰", "2026-09-03", "老年医学科",
              "携既往血压记录就诊，核对近两周测量情况。", "既往高血压，本次为慢病随访。",
              "核对晨晚记录，部分日期缺少测量时间。", "按既有随访安排记录测量时间与当日感受。",
              "下次门诊携带完整血压记录表。", "慢病门诊随访记录", "就诊记录"),
    Encounter("bp-followup", "r001", "沈月兰", "2026-09-24", "老年医学科",
              "按上次预约复诊，带来补记的晨晚血压表。", "高血压随访，已补齐近期测量记录。",
              "复核两次门诊之间的测量日期与记录完整性。", "本次门诊记录未记载处方变更。",
              "机构经办人将测量表补充归档到本次复诊。", "复诊记录", "就诊记录"),
    Encounter("glucose-review", "r002", "徐松年", "2026-09-16", "内分泌科",
              "因既往2型糖尿病到门诊定期复查。", "2型糖尿病，本次为常规复查。",
              "虚构检验结果：糖化血红蛋白 7.1%。", "已核对检验单与既往病史，未新增用药记录。",
              "随下次门诊携带检验报告与日常记录。", "糖化血红蛋白检验报告", "检查报告"),
    Encounter("knee-review", "r003", "梁秋萍", "2026-09-18", "骨科",
              "因行走时膝部不适就诊，携影像检查报告归院。", "门诊病历记载膝骨关节炎。",
              "右膝正侧位片报告记载退行性改变。", "门诊记录已交由护理人员核对归档。",
              "下次随诊核对活动情况。", "右膝影像检查报告", "检查报告"),
)


def _encoded(key):
    return base64.b64encode((REPORTS / (key + ".pdf")).read_bytes()).decode("ascii")


def seed_medical(store, token):
    """Return the number of newly signed visits and supplemental documents."""
    with closing(store.connect()) as db:
        if store.actor(db, token)["kind"] != "owner":
            raise PermissionError("请使用演示库 Owner 账号载入演示病例")
    residents = {row["id"]: row for row in store.snapshot(token)["data"]["residents"]}
    inserted = 0
    for case in ENCOUNTERS:
        person = residents.get(case.resident)
        if not person or person["name"] != case.name or person["status"] != "在住":
            continue
        if case.day > store.now().date().isoformat():
            continue
        request = "demo-medical-v1-" + case.key
        with closing(store.connect()) as db:
            signed = db.execute(
                """SELECT r.id FROM dossier_visit_records r JOIN dossier_visit_drafts d ON r.id=d.id
                   WHERE d.request=? AND r.resident_id=?""", (request, case.resident),
            ).fetchone()
        if signed:
            visit_id = signed[0]
        else:
            draft = medical_visits.preview(store, token, case.resident, {
                "requestId": request, "mode": "manual", "revision": store.version(token)["revision"],
                "fields": {
                    "eventDate": case.day, "facility": FACILITY, "department": case.department,
                    "reason": case.reason, "diagnosis": case.diagnosis, "tests": case.tests,
                    "orders": case.orders, "followUp": case.follow_up,
                },
                "attachments": [{
                    "filename": f"{case.name}-{case.report}.pdf", "category": case.category,
                    "mime": "application/pdf", "imageBase64": _encoded(case.key),
                }],
            })
            visit_id = draft["draftId"]
            store.execute("dossier.confirmVisit", {
                "residentId": case.resident, "draftId": visit_id, "confirmed": True,
                "fields": draft["fields"],
            }, draft["revision"], token)
            inserted += 1
        if case.key == "bp-followup":
            request += "-measurements"
            with closing(store.connect()) as db:
                attached = db.execute(
                    """SELECT 1 FROM dossier_documents d JOIN dossier_visit_documents vd
                       ON d.id=vd.document_id WHERE d.request_id=? AND vd.visit_id=?""",
                    (request, visit_id),
                ).fetchone()
            if not attached:
                store.execute("dossier.document", {
                    "residentId": case.resident, "visitId": visit_id, "requestId": request,
                    "eventDate": case.day, "category": "其他医疗文书", "source": FACILITY,
                    "description": "复诊补充材料：9 月 21 至 23 日晨间血压记录，共三次。",
                    "mime": "application/pdf", "imageBase64": _encoded("bp-measurements"),
                }, store.version(token)["revision"], token)
                inserted += 1
    return inserted
