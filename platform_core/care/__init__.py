"""护理域命令注册表。"""

from .clinical import (
    add_medication,
    give_medication,
    handover,
    resolve_vital,
    review_medication,
    vital,
)
from .demo import seed
from .plans import add_task, approve_plan, assess, complete_task, quality
from .records import LEVELS, iso_date
from .residency import admit, archive, discharge, inquire, leave, renew, transfer


__all__ = ["LEVELS", "apply", "seed"]

_ACTIONS = {
    "care.inquire": inquire,
    "care.admit": admit,
    "care.transfer": transfer,
    "care.discharge": discharge,
    "care.renew": renew,
    "care.assess": assess,
    "care.approvePlan": approve_plan,
    "care.addTask": add_task,
    "care.completeTask": complete_task,
    "care.addMedication": add_medication,
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
