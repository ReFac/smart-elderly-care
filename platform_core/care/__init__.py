"""护理域命令注册表。"""

from .clinical import (
    add_medication,
    give_medication,
    handover,
    resolve_vital,
    publish_drug_rule,
    retire_drug_rule,
    review_medication,
    vital,
)
from .demo import seed
from .pathways import (
    screen,
    schedule_followup,
    finish_followup,
    refer,
    receive_referral,
    referral_consent,
    export_referral,
)
from . import plan_items, scales
from .plans import add_task, approve_plan, assess, complete_task, quality
from .records import LEVELS, iso_date
from .receiving import receive as receive_medication
from .residency import (
    admit,
    confirm_stay,
    end_trial,
    archive,
    discharge,
    date_archive,
    file_archive,
    inquire,
    leave,
    register,
    renew,
    transfer,
)


__all__ = ["LEVELS", "apply", "seed", "scales"]

_ACTIONS = {
    "care.screen": screen,
    "care.scheduleFollowup": schedule_followup,
    "care.finishFollowup": finish_followup,
    "care.refer": refer,
    "care.receiveReferral": receive_referral,
    "care.referralConsent": referral_consent,
    "care.exportReferral": export_referral,
    "care.publishDrugRule": publish_drug_rule,
    "care.retireDrugRule": retire_drug_rule,
    "care.inquire": inquire,
    "care.register": register,
    "care.fileArchive": file_archive,
    "care.dateArchive": date_archive,
    "care.admit": admit,
    "care.confirmStay": confirm_stay,
    "care.endTrial": end_trial,
    "care.transfer": transfer,
    "care.discharge": discharge,
    "care.renew": renew,
    "care.assess": assess,
    "care.approvePlan": approve_plan,
    "care.revisePlan": plan_items.revise,
    "care.addTask": add_task,
    "care.completeTask": complete_task,
    "care.addMedication": add_medication,
    "care.receiveMedication": receive_medication,
    "care.reviewMedication": review_medication,
    "care.giveMedication": give_medication,
    "care.vital": vital,
    "care.resolveVital": resolve_vital,
    "care.handover": handover,
    "care.leave": leave,
    "care.archive": archive,
    "care.quality": quality,
}


def apply(state, action, payload, today):
    """在调用方事务的工作副本上应用一个动作，返回审计标题。"""
    handler = _ACTIONS[action]
    if not isinstance(payload, dict):
        raise ValueError("操作参数须为对象。")
    return handler(state, payload, iso_date(today, "业务日期"))
