"""Resolve direct operation requests to existing manual workspace forms."""

from dataclasses import dataclass
import re

from .. import access_policy as policy
from . import chat_navigation


@dataclass(frozen=True)
class ManualForm:
    key: str
    route: str
    tab: str
    title: str
    command: str
    aliases: tuple[str, ...] = ()

    def action(self):
        return {"kind": "openForm", "form": self.key, "route": self.route, "tab": self.tab, "title": self.title}


FORMS = (
    ManualForm("staffAdd", "access", "", "新增员工", "access.create", ("添加员工", "新建员工账号", "创建员工账号", "新建员工", "新员工建档", "添加新员工", "添加护理人员")),
    ManualForm("residentAdd", "residents", "notAdmitted", "新建长辈档案", "care.register",
               ("长辈建档", "登记新长辈", "新增长辈档案", "创建长辈档案", "建立长辈档案",
                "新建老人档案", "创建老人档案", "建立老人档案")),
    ManualForm("admission", "residents", "notAdmitted", "办理入住", "care.admit", ("办理长辈入住", "办理老人入住", "登记正式入住", "办理正式入住")),
    ManualForm("trial", "residents", "notAdmitted", "办理试住", "care.admit", ("开始试住", "登记试住")),
    ManualForm("shiftAdd", "shifts", "", "安排班次", "ops.shift", ("新增排班", "新建排班", "安排排班", "登记排班")),
    ManualForm("inventoryAdd", "inventory", "stock", "建立物资品目", "ops.addItem", ("新增物资", "添加物资", "新建物资品目")),
    ManualForm("stockIn", "inventory", "stock", "登记入库", "ops.stock", ("办理入库", "物资入库", "录入入库")),
    ManualForm("stockOut", "inventory", "stock", "登记出库", "ops.stock", ("办理出库", "物资出库", "登记领用")),
    ManualForm("vitalAdd", "care", "vitals", "录入健康体征", "care.vital", ("登记体征", "录入体征", "录入血压", "登记血压", "登记体温", "录入体温", "上报体征")),
    ManualForm("medicationAdd", "medications", "orders", "登记用药计划", "care.addMedication", ("录入用药计划", "录入医嘱", "登记医嘱", "新增用药")),
    ManualForm("medicationCheck", "care", "medRounds", "床旁服药核对", "care.confirmMedRound", ("服药核对", "核对服药", "核对给药")),
    ManualForm("billAdd", "billing", "due", "核算账单", "ops.bill", ("生成账单", "核算月度账单", "核算月付账单", "开具账单")),
    ManualForm("depositAdd", "billing", "deposits", "登记预缴金", "ops.deposit", ("录入预缴金", "登记预交金", "登记预缴", "收取预缴金")),
    ManualForm("expenseAdd", "billing", "expenses", "登记支出", "ops.expense", ("登记已发生支出", "录入支出", "登记费用支出")),
    ManualForm("leadAdd", "leads", "contacts", "手工登记客户", "leads.register", ("登记客户", "登记来电", "登记到访", "登记意向客户")),
    ManualForm("longCareAdd", "longCare", "", "登记长护险办理", "ltci.record", ("录入长护险", "登记长护险", "登记长期护理保险")),
    ManualForm("scheduleAdd", "care", "scheduledWork", "新建定时计划", "care.saveSchedule", ("新建定时工单", "创建定时工单", "新增定时工单", "新增定时计划", "创建定时计划")),
    ManualForm("reportAdd", "reports", "drafts", "生成民政报送草稿", "ops.report", ("生成报送草稿", "新建民政报送草稿", "创建民政报送草稿")),
    ManualForm("visitManual", "dossier", "", "手动录入病例", "dossier.confirmVisit", ("手写病例", "手动登记病例", "手动录入病历", "手工录入病历")),
)

COMMAND = re.compile(
    r"^(?:(?:请你|请|麻烦你|麻烦|帮我|给我|我要|我想|先|现在|接下来|马上)[，,、\s]*)*"
    r"(?:打开|带我去|进入|定位|去|新建|新增|添加|创建|建立|办理|登记|手工登记|安排|核对|录入|上报|核算|生成|开具|收取|开始|手动录入|手动登记|手写)"
)
QUESTION = re.compile(r"[？?]|怎么|如何|哪里|哪儿|在哪|请问|能否|可以.{0,8}吗|吗[。！!\s]*$|如果|假如|例如|比如")


def intent(text):
    text = text.strip().replace("长者", "长辈")
    if len(text) > 150 or not COMMAND.match(text) or QUESTION.search(text) or chat_navigation.NEGATIVE.search(text) or chat_navigation.public_topic(text):
        return None
    matches = [form for form in FORMS if any(word in text for word in (form.title, *form.aliases))]
    return matches[0] if len(matches) == 1 else None


def available(form, user, routes):
    return user["kind"] in ("staff", "owner") and form.route in routes and form.command in policy.allowed_actions(user)
