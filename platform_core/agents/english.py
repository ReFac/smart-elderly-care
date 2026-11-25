"""International-edition commands and localized summaries from authorized ledger facts."""
from dataclasses import replace
import re
from unicodedata import normalize

from .. import deployment_language
from . import chat_forms


def writing(language):
    name = deployment_language.locales()[language]["name"]
    return (f"Use the institution language {name} ({language}) for all user-facing prose, including answers "
            "and document guidance. Preserve names, recorded amounts, dates and units. "
            "Keep tool names, JSON keys, identifiers and source documents unchanged. "
            "Only offer actions the signed-in user can access. A button opens a draft for staff review.")


FORM_TITLES = dict(zip(
    ("staffAdd","residentAdd","admission","trial","shiftAdd","inventoryAdd","stockIn","stockOut",
     "vitalAdd","medicationAdd","medicationCheck","billAdd","depositAdd","expenseAdd","leadAdd",
     "longCareAdd","scheduleAdd","reportAdd","visitManual"),
    ("Add an employee","Create a resident record","Admit a resident","Start a trial stay","Schedule a shift",
     "Add an inventory item","Receive stock","Issue stock","Record vital signs","Record a medication plan",
     "Review medication administration","Prepare a bill","Record a prepayment","Record an expense",
     "Register a prospect","Record long-term care insurance","Create a recurring care task",
     "Prepare a reporting draft","Record a medical visit"), strict=True))
ALIASES = {
    "residentAdd": ("create a resident profile","add a resident","new resident","register a resident","create a resident"),
    "admission": ("admit resident","start admission"),
    "trial": ("arrange a trial stay",), "staffAdd": ("add a staff member","create an employee account",),
}
REFUSAL = "I can help with this care facility, resident care and related health or policy questions."


def form(text):
    command = re.sub(r"^(?:please |help me |i want to )+", "", text.strip().lower()).rstrip(".!")
    return next((f for f in chat_forms.FORMS if command in (FORM_TITLES[f.key].lower(), *ALIASES.get(f.key, ()))), None)


# Each key is an existing workspace Page, whose own route, tab and grants remain authoritative.
PAGE_NAMES = {
    "床位管理": ("Bed management", "beds", "bed board", "room management"),
    "全部床位": ("Bed list", "all beds"),
    "楼层平面图": ("Floor plan", "floor plans"),
    "区域设置": ("Care areas", "area settings"),
    "入住管理": ("Admissions", "admission management", "resident list"),
    "个人与医疗档案": ("Resident records", "medical records", "resident profiles"),
    "试住": ("Trial stays", "trial stay management"),
    "意向客户": ("Prospective residents", "leads", "prospects"),
    "接待时间表": ("Visit schedule", "visitor appointments", "reception calendar"),
    "能力评估": ("Resident assessments", "care assessments"),
    "专项风险档案": ("Risk assessments", "risk reports"),
    "照护计划": ("Care plans",),
    "照护工单": ("Care tasks", "care work orders"),
    "定时工单": ("Scheduled care tasks", "recurring care tasks", "scheduled work orders"),
    "班次交接": ("Shift handovers", "handover log"),
    "人员排班": ("Staff scheduling", "staff roster", "staff shifts"),
    "健康体征": ("Vital signs", "vital sign records"),
    "用药管理": ("Medication management", "medications"),
    "用药台账": ("Medication records",),
    "物资仓储": ("Inventory", "inventory management", "warehouse"),
    "库存台账": ("Stock ledger", "inventory ledger"),
    "出入库流水": ("Stock movements", "inventory transactions"),
    "财务结算": ("Billing", "finance"),
    "收费账单": ("Bills", "billing statements"),
    "待收费": ("Unpaid bills", "outstanding bills"),
    "实收流水": ("Receipts", "payment receipts"),
    "统计报送": ("Reports",),
    "预警与确认": ("Alerts and confirmations", "alert center", "alert centre"),
    "设备预警": ("Device alerts",),
    "运营看板": ("Operations dashboard", "management dashboard"),
    "运营总览": ("Operations overview", "facility overview"),
    "账号与权限": ("Accounts and permissions", "accounts", "account management"),
    "部署控制台": ("Deployment console", "deployment settings"),
    "机构设置": ("Facility settings", "system settings"),
    "AI 用量": ("AI usage", "model usage"),
    "备份与恢复": ("Backup and restore", "backups"),
    "平台更新": ("Platform updates", "software updates"),
    "设备与接口": ("Devices and integrations", "device management"),
    "定时任务": ("System timers", "scheduler status"),
    "操作日志": ("Audit log", "audit logs"),
    "最近改动": ("Recent changes", "change history"),
    "个人中心": ("My account", "personal settings"),
    "家属服务": ("Family services", "family portal"),
    "环境导览": ("Room tour", "roomtour", "virtual tour"),
    "常见问题": ("FAQ", "frequently asked questions", "help center", "help centre"),
}
PAGE_ALIASES = {alias.casefold(): key for key, aliases in PAGE_NAMES.items() for alias in aliases}
OPEN_PAGE = re.compile(
    r"(?:(?:please|help me) )*(?:open|show(?: me)?|view|go to|take me to|navigate to|bring up) "
    r"(?:the )?([a-z][a-z &-]{0,68}?)(?: (?:page|screen|tab))?(?:,? please)?[.!]?"
)


def navigation_page(text):
    phrase = " ".join(normalize("NFKC",text).casefold().split())
    # "Can you open the page?" asks the assistant to navigate; "Can I open ...?"
    # asks about the speaker's capabilities and remains ordinary conversation.
    if polite := re.fullmatch(r"(?:can|could|would) you (.+?)[?]?", phrase):
        phrase = polite[1]
    match = OPEN_PAGE.fullmatch(phrase)
    return PAGE_ALIASES.get(match[1]) if match else None


def destination(target, pages):
    page = next((p for p in pages if p.title == target), None)
    if page:
        return replace(page,title=PAGE_NAMES[target][0])
    return None


def topic(text, language="en"):
    def normalize(value):
        return value.casefold().strip().strip("¿¡?.! ").replace("’", "'")

    for prompt, category in (("How are things today?", "operations"), ("How are the residents today?", "health"),
                             ("What are today's receipts?", "finance")):
        if normalize(text) == normalize(deployment_language.message(language, prompt)):
            return category
    value = text.lower().strip().rstrip("?.!")
    if re.fullmatch(r"(?:how (?:are (?:we|things)|is (?:the (?:care home|facility|home)|it)) (?:doing|going)(?: today)?|how(?:'s| is) (?:today|the (?:care home|facility)(?: today)?)|today.s (?:overview|update)|daily (?:brief|summary)|how are things today)", value):
        return "operations"
    if re.fullmatch(r"(?:how are (?:our |the )?residents(?: doing)?(?: today)?|(?:today.s )?resident health(?: today)?)", value):
        return "health"
    if re.fullmatch(r"(?:what (?:is|are) )?(?:today.s |this month.s )?(?:receipts|revenue|cash flow|outstanding bills)(?: today)?", value):
        return "finance"
    return ""


def briefing(kind, facts, language="en"):
    lines = []

    def add(message, **values):
        lines.append(deployment_language.message(language, message).format(**values))

    beds = facts.get("当前床位")
    if kind == "operations" and beds:
        add("Residents in care: {residents}. Beds available: {beds}.", residents=beds["在住人数"], beds=beds["空床数"])
    tasks = facts.get("照护工单")
    if kind == "operations" and tasks:
        counts = tasks["今日计划按当前状态"]
        add("Today's care tasks: {completed} completed, {pending} pending. Earlier tasks overdue: {overdue}.",
            completed=counts.get("已完成", 0), pending=counts.get("待执行", 0), overdue=tasks["以往日期仍待执行"])
    health = facts.get("今日已登记健康情况")
    if kind in ("health", "operations") and health:
        covered = health.get("已记录体征人数")
        if covered is not None:
            add("Vital signs recorded today for {covered} of {residents} residents. New abnormal observations: {abnormal}.",
                covered=covered, residents=health["在住人数"], abnormal=health.get("新增异常体征记录", 0))
        if health.get("尚未核实的设备提示"):
            add("Device alerts awaiting verification: {alerts}.", alerts=health["尚未核实的设备提示"])
        if health.get("现场核实设备异常"):
            add("Device alerts confirmed by staff: {alerts}.", alerts=health["现场核实设备异常"])
        if health.get("咳嗽增多提示人数"):
            add("Residents flagged for increased coughing: {residents}.", residents=health["咳嗽增多提示人数"])
    cash = facts.get("到账与欠款（元）")
    if kind in ("finance", "operations") and cash:
        add("Today's receipts after verified refunds (before fees): CNY {today}. "
            "Month to date including prepayments: CNY {month}. Outstanding bills: CNY {due}.",
            today=f"{cash['今日新增实收（含预缴）']:,.2f}", month=f"{cash['本月至今流水（含预缴）']:,.2f}", due=f"{cash['截至今日待缴余额']:,.2f}")
    if not lines:
        add("There are no figures available for this summary within your access scope.")
    return lines
