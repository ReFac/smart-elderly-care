"""运营域命令注册表。"""

from .assistants import generate_suggestion, review_suggestion
from .billing import CARE_RATES, deposit, generate_bill, pay
from .demo import seed
from .reports import generate_report
from .resources import assign_shift, record_stock


__all__ = ["CARE_RATES", "apply", "seed"]

ACTIONS = {
    "ops.stock": record_stock,
    "ops.shift": assign_shift,
    "ops.bill": generate_bill,
    "ops.deposit": deposit,
    "ops.pay": pay,
    "ops.report": generate_report,
    "ops.suggest": generate_suggestion,
    "ops.review": review_suggestion,
}


def apply(state, action, payload, today):
    return ACTIONS[action](state, payload, today)
