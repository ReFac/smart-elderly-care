"""Resolve spoken page names into permission-checked, read-only workspace destinations."""

from dataclasses import dataclass
import re

from .. import access_policy as policy
from . import chat_web


@dataclass(frozen=True)
class Page:
    route: str
    title: str
    aliases: tuple = ()
    tab: str = ""
    grant: str = ""
    params: tuple = ()

    def link(self):
        return {
            "route": self.route,
            "title": self.title,
            **({"tab": self.tab} if self.tab else {}),
            **({"params": dict(self.params)} if self.params else {}),
        }


# The model may name a page in prose. Only this application-owned directory supplies a route or tab.
PAGES = (
    Page("overview", "运营总览", ("院务总览", "运营首页")),
    Page("residents", "入住管理", ("长辈档案", "老人档案", "档案名册", "入住名册")),
    Page(
        "residents",
        "办理老人入住",
        ("长辈入住", "老人入住", "办理入住", "登记入住", "办理入院", "分配床位"),
        "all",
        "intake",
    ),
    Page("residents", "到期续住", ("续住", "续签入住", "到期续租"), "renew", "intake"),
    Page("residents", "办理试住", ("试住入住", "开始试住"), "notAdmitted", "intake"),
    Page("residents", "试住", ("试住管理", "试住转正式", "试住记录"), "trials"),
    Page("residents", "试住回访", (), "followups"),
    Page("beds", "床位管理", ("病房管理", "床位")),
    Page("beds", "全部床位", ("床位列表", "床位名册"), "all"),
    Page("beds", "区域设置", ("护理区域", "护工职责", "照护区域", "楼栋分区"), "zones"),
    Page("beds", "楼层平面图", ("平面图", "房间工作台"), "plan"),
    Page("beds", "编辑矢量平面图", ("平面图设置", "矢量平面图", "编辑平面图"), "plan", "facility.manage", (("edit", "layout"),)),
    Page("dossier", "个人与医疗档案", ("个人档案", "医疗档案", "医疗存档", "医疗资料", "过去诊疗记录", "会诊记录")),
    Page("assessments", "能力评估", ("长辈评估", "老人评估")),
    Page("assessments", "评估记录", (), "assess"),
    Page("assessments", "等级判定", ("护理等级", "评估结果"), "grading", "care"),
    Page("assessments", "照护计划", (), "plans"),
    Page("assessments", "复评安排", (), "review"),
    Page("care", "照护服务", ("护理服务",)),
    Page("care", "健康工作台", ("健康管理", "智慧照护"), "healthDesk"),
    Page("care", "照护工单", ("护理工单",), "tasks", "care"),
    Page("care", "班次交接", ("交接班", "交班记录"), "handover", "care"),
    Page("care", "登记集体活动", ("集体活动", "登记集体用餐", "登记餐单"), "groupLife", "care"),
    Page("care", "核对活动参加名单", ("集体活动待确认", "用餐签认", "确认参加名单"), "groupLife", "care.groupConfirm"),
    Page("care", "定时工单", ("自动工单", "伙食工单", "伙食排期", "自动派工"), "scheduledWork"),
    Page("care", "健康体征", ("体征记录",), "vitals", "clinical"),
    Page("inventory", "物资仓储", ("仓库", "物资管理")),
    Page(
        "inventory",
        "库存台账",
        ("护理用具库存", "物资库存", "库存明细", "库存"),
        "stock",
    ),
    Page("inventory", "护理用具工单", ("物资工单", "补货工单"), "orders"),
    Page("inventory", "出入库流水", ("物资流水",), "moves"),
    Page("billing", "财务结算", ("费用结算", "收费管理")),
    Page("billing", "收费账单", ("收费明细", "账单明细"), "bills"),
    Page("billing", "待出月账单", ("月付账单", "待出月付账单"), "due"),
    Page("billing", "渠道对账", ("支付对账",), "orders"),
    Page("billing", "欠费提醒", ("催缴提醒",), "reminders"),
    Page("billing", "账务提醒", ("账单日提醒", "缴费提醒", "月费提醒"), "billingNotices"),
    Page("billing", "支出登记", ("费用支出",), "expenses"),
    Page("billing", "预交余额", ("预交金余额",), "deposits"),
    Page("billing", "实收流水", ("收款流水", "到账流水", "实收凭证"), "receipts"),
    Page("billing", "账单核销记录", ("预缴冲抵记录",), "payments"),
    Page("leads", "意向客户", ("来电登记", "意向客服", "咨询回访")),
    Page("leads", "接待时间表", ("来访排班", "接待排班表", "参观排班", "来访预约"), "schedule"),
    Page("shifts", "人员排班", ("员工排班", "排班表", "排班")),
    Page("reports", "统计报送", ("统计报表",)),
    Page("reports", "民政报送", (), "drafts", "reports"),
    Page("inbox", "预警与确认", ("预警与人工确认", "预警中心")),
    Page("inbox", "全员通知", ("全院通知",), "notices"),
    Page("inbox", "设备预警", ("跌倒预警",), "alerts", "alerts"),
    Page("medications", "用药管理", ("药品管理",)),
    Page("medications", "用药台账", ("用药记录",), "orders"),
    Page("medications", "用药安全筛查", ("用药冲突", "过敏核对", "重复用药"), "safety", "clinical"),
    Page("medications", "定时提醒", ("给药提醒",), "reminders"),
    Page("longCare", "长期护理保险", ("长护险经办台账", "长护险", "长护保险")),
    Page("activity", "操作日志", ("审计日志",)),
    Page("history", "最近改动", ("最近更改", "变更记录")),
    Page("integrations", "设备与接口", ("设备接入", "设备管理")),
    Page(
        "access",
        "账号与权限",
        ("账户与权限", "员工账户", "员工账号", "账号管理", "账户管理", "权限管理"),
    ),
    Page("settings", "机构设置", ("系统设置",)),
    Page("settings", "界面与 AI 套餐", ("AI 套餐", "界面设置"), "general"),
    Page("settings", "AI 用量", ("DeepSeek 用量", "模型用量", "API 用量", "Token 用量", "缓存命中率"), "deepseekUsage"),
    Page("settings", "定时巡查", ("巡查设置",), "rounds"),
    Page("settings", "试住约定", ("试住设置", "试住默认价", "试住默认天数"), "trials"),
    Page("settings", "备份与恢复", ("备份", "快照", "恢复备份"), "backups"),
    Page("settings", "平台更新", ("自动更新", "检查更新", "更新设置", "升级前备份", "软件更新", "版本更新"), "platformUpdates"),
    Page("account", "个人中心", ("我的账户", "我的账号")),
    Page("tour", "环境导览", ("院内环境", "养老院环境", "院区环境", "全景导览")),
    Page("family", "家属服务", ("长辈服务", "照护消息", "家属消息", "家属推送")),
    Page("faq", "常见问题", ("FAQ", "faq", "帮助中心", "使用指南")),
)

WAYFINDING = re.compile(
    r"入口|页面|界面|模块|菜单|页签|工作台|哪里|哪儿|在哪|何处|怎么|如何|打开|点开|前往|进入|进去|跳转|带我去|办理入住|办理试住"
)
RECOMMENDATION = re.compile(
    r"点击|点开|进入|打开|前往|跳转|切换|选择|找到|访问|查看|参看|核对|可在|可以在|请在|入口|页签|菜单|页面|界面|左侧|侧栏|侧边栏|右上角|导航栏|下方"
)
NEGATIVE = re.compile(
    r"不(?:要|用|必|能|可|允许)|请勿|无(?:法|权)|没有(?:权限|开放|入口)|未(?:开放|开通|授权)|别(?:点|打|进|跳)"
)
PREVIOUS = re.compile(
    r"(?:刚才|刚刚|上面|上次|前面|上一条|之前|对应|那[个一]?|这[个一]?|该).{0,12}(?:页|入口|模块|界面)|^(?:那|请|让我|帮我|给我|把)?(?:怎么进去|怎么进入|给个入口|给我入口|入口在哪|带我过去|直接打开)[？?！!。吧呢]*$"
)
PUBLIC = re.compile(
    r"政策|法规|条例|新闻|官方网站|官网|政府网站|公开(?:资料|信息|网站)|外网|互联网|搜索引擎|https?://",
    re.I,
)
DIRECT = re.compile(
    r"^(?:(?:请你|请|麻烦你|麻烦|帮我|给我|我要|先|现在|马上)[，,、\s]*)*"
    r"(?:打开|进入|前往|跳转到|带我去|定位到|去)\s*(?P<name>[^，,。！!？?；;\n]+?)[。！!\s]*$"
)
SENTENCE = re.compile(r"[。！？!?；;\n]+")
ROOM_NUMBER = {"单": 1, "一": 1, "双": 2, "两": 2, "二": 2, "三": 3, "四": 4,
               "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
ROOM_CAPACITY = re.compile(r"(1[0-2]|[1-9单双一两二三四五六七八九十])\s*(?:人间|人房|床房)")
ROOM_LIMIT = re.compile(r"(\d{1,3}|[一两二三四五六七八九十])\s*(?:间|个)\s*(?:[1-9单双一两二三四五六七八九十]|房)")
ROOM_EDIT = re.compile(r"(?:修改|编辑|调整|设置|改成|改为|自定义).{0,14}(?:房型|房间|人间|床位数)|房型编辑|房间设置")


def room_capacity(text):
    if ROOM_EDIT.search(text):
        return None
    capacity = ROOM_CAPACITY.search(text)
    if not capacity:
        return None
    number = capacity[1]
    limit = ROOM_LIMIT.search(text)
    count = limit[1] if limit else "6"
    return ROOM_NUMBER.get(number, int(number) if number.isdigit() else 1), min(
        30, max(1, ROOM_NUMBER.get(count, int(count) if count.isdigit() else 6))
    )


def room_shortcut(question, pages, area):
    if NEGATIVE.search(question) or not any(p.route == "beds" for p in pages):
        return None
    area = area or {}
    scope = tuple((short, area[key]) for short, key in (
        ("campus", "campusId"), ("building", "buildingId"), ("floor", "floorId"), ("room", "roomId"),
    ) if area.get(key))
    permitted_layout = any(p.route == "beds" and p.grant == "facility.manage" for p in pages)
    if permitted_layout and (ROOM_EDIT.search(question) or re.search(r"编辑房型|调整房型", question)):
        if area.get("roomId"):
            return Page("beds", "编辑房型", tab="plan", params=(*scope, ("edit", "room")))
        return Page("beds", "查找房间并编辑房型", tab="all", params=scope)
    if permitted_layout and re.search(r"矢量平面图|编辑平面图|平面图设置", question):
        return Page("beds", "编辑矢量平面图", tab="plan", params=(*scope, ("edit", "layout")))
    match = room_capacity(question)
    if match:
        beds, limit = match
        label = {1: "单人间", 2: "双人间", 3: "三人间"}.get(beds, f"{beds} 人间")
        return Page("beds", f"查看{label}", tab="all",
                    params=(*scope, ("capacity", str(beds)), ("limit", str(limit))))
    return None


def visible(user, routes):
    return tuple(
        p
        for p in PAGES
        if p.route in routes
        and (not p.grant or policy.has(user, p.grant))
        and (p.grant != "intake" or "intake" in routes)
        and (p.tab != "scheduledWork" or any(policy.has(user, grant) for grant in ("care", "clinical", "care.schedule")))
    )


def directory(pages):
    names = {p.route: p.title for p in pages if not p.tab}
    content = {title: [] for title in names.values()}
    notes = {
        ("residents", "notAdmitted"): "入住管理的「待入住」筛选（在对应长辈右侧选择「办理试住」）",
        ("residents", "trials"): "入住管理的「试住」筛选（在同一张名册查看试住记录、办理转正或离院）",
        (
            "longCare",
            "",
        ): "页面默认内容就是「长护险经办台账」，点击下方「长期护理保险」即可查看，无需再找子页面。",
        (
            "residents",
            "all",
        ): "入住管理名册（点击「办理老人入住」打开名册，再选择已有长辈档案办理）",
        (
            "settings",
            "backups",
        ): "备份与恢复（在此查看和管理本机及异地快照、备份导入与导出）",
    }
    for p in pages:
        label = notes.get((p.route, p.tab), p.title if p.tab else "")
        if label:
            content[names[p.route]].append(label)
    return content


def named(text, pages):
    text = text.replace("长者", "长辈")
    hits = []
    for page in pages:
        for label in (page.title, *page.aliases):
            start = text.find(label)
            if start >= 0:
                hits.append((start, start + len(label), page))
    # “分配床位” is the admission destination; its embedded “床位” is not a second request.
    return list(
        dict.fromkeys(
            page
            for start, end, page in sorted(hits, key=lambda hit: hit[0])
            if not any(
                a <= start and end <= b and b - a > end - start for a, b, _ in hits
            )
        )
    )


def public_topic(text):
    return bool(PUBLIC.search(text) or chat_web.requests_public_site(text))


def local_question(text):
    """Page-finding stays inside the workspace even when public search is enabled."""
    return bool(
        not public_topic(text)
        and (room_capacity(text) or ROOM_EDIT.search(text) or PREVIOUS.search(text)
             or WAYFINDING.search(text) and named(text, PAGES))
    )


def navigation_actions(actions, text, pages):
    if not actions or set(actions.values()) != {"navigate"}:
        return actions
    if public_topic(text) or PREVIOUS.search(text):
        return {}
    requested = named(text, PAGES)
    if not requested:
        return actions
    targets = {
        "intake" if p.route == "residents" and p.tab == "all" else p.route
        for p in requested
        if p in pages
    }
    return {r: kind for r, kind in actions.items() if r in targets}


def direct_destination(text, pages, actions):
    match = DIRECT.fullmatch(text.strip().replace("长者", "长辈"))
    if not match or not actions or set(actions.values()) != {"navigate"}:
        return None
    name = match["name"].strip()
    targets = [page for page in pages if page.route in actions and any(
        name in (label, label + "页面", label + "界面", label + "页签")
        for label in (page.title, *page.aliases)
    )]
    if len(targets) == 1:
        return {**targets[0].link(), "kind": "navigate"}
    return None


def resolve(question, answer, pages, previous=(), action=None, area=None):
    if public_topic(question):
        return []
    shortcut = room_shortcut(question, pages, area)
    matches = [shortcut] if shortcut else []
    for sentence in SENTENCE.split(question):
        if WAYFINDING.search(sentence) and not NEGATIVE.search(sentence):
            matches.extend(named(sentence, pages))
    if (
        not matches
        and previous
        and PREVIOUS.search(question)
        and not NEGATIVE.search(question)
    ):
        # A bare reference to previous destinations must not invent a different one.
        return list(previous)
    requested = {p.route for p in matches}
    requested_tabs = {p.route for p in matches if p.tab}
    for sentence in SENTENCE.split(answer):
        if NEGATIVE.search(sentence) or PUBLIC.search(sentence):
            continue
        if RECOMMENDATION.search(sentence):
            matches.extend(
                p
                for p in named(sentence, pages)
                if not requested
                or (p.route in requested and p.route not in requested_tabs)
            )
    if not matches and action and action.get("kind") == "navigate":
        route = action.get("route")
        target = {"intake": ("residents", "all"), "rooms": ("beds", "plan")}.get(
            route, (route, "")
        )
        matches = [p for p in pages if (p.route, p.tab) == target]
    # A specific tab already opens its parent. Show only the most useful destination once.
    with_tab = {page.route for page in matches if page.tab}
    if shortcut:
        matches = [shortcut, *(page for page in matches if page.route != "beds")]
    return list(
        dict.fromkeys(
            page for page in matches if page.tab or page.route not in with_tab
        )
    )[:4]
