"""运营域命令注册表。"""

from .assistants import generate_suggestion, review_suggestion
from .billing import CARE_RATES, deposit, generate_bill, pay
from .demo import seed
from .settlements import create_order, expense, import_receipt, remind
from .reports import generate_report, submit_report, report_receipt
from .resources import add_item, assign_shift, record_stock


__all__ = ["CARE_RATES", "apply", "seed"]

ACTIONS = {
    "ops.addItem": add_item,
    "ops.stock": record_stock,
    "ops.shift": assign_shift,
    "ops.bill": generate_bill,
    "ops.deposit": deposit,
    "ops.pay": pay,
    "ops.paymentOrder": create_order,
    "ops.importReceipt": import_receipt,
    "ops.remindBill": remind,
    "ops.expense": expense,
    "ops.submitReport": submit_report,
    "ops.reportReceipt": report_receipt,
    "ops.report": generate_report,
    "ops.suggest": generate_suggestion,
    "ops.review": review_suggestion,
}


def apply(state, action, payload, today):
    return ACTIONS[action](state, payload, today)
