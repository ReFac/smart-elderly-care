"""运营域命令注册表。"""

from .assistants import generate_suggestion, review_suggestion
from .billing import CARE_RATES, deposit, generate_bill, pay
from .demo import seed
from .payment_terms import configure as configure_payment_fees
from .settlements import create_order, expense, import_receipt, remind
from .reports import generate_report, submit_report, report_receipt
from .resources import add_item, assign_shift, edit_item, record_stock


__all__ = ["CARE_RATES", "apply", "seed"]

ACTIONS = {
    "ops.addItem": add_item,
    "ops.editStockItem": edit_item,
    "ops.stock": record_stock,
    "ops.shift": assign_shift,
    "ops.bill": generate_bill,
    "ops.deposit": deposit,
    "ops.pay": pay,
    "ops.paymentFees": configure_payment_fees,
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
