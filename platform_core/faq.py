"""Public operation guides shared by the FAQ page and the health assistant."""

from dataclasses import dataclass
import re
from unicodedata import normalize


@dataclass(frozen=True)
class Entry:
    id: str
    category: str
    question: str
    answer: str
    keywords: tuple[str, ...]

    def public(self):
        return {"id": self.id, "category": self.category, "question": self.question,
                "answer": self.answer, "keywords": list(self.keywords)}


ENTRIES = (
    Entry("visit-booking", "来访与家属", "如何预约参观养老院？",
          "打开访客首页的「来访预约」，填写联系方式和意向时段。接待人员会致电核实，并以电话确认的时间安排来访。也可以先打开「环境导览」查看机构环境。",
          ("预约参观", "预约来访", "来访预约", "参观养老院", "参观机构", "看养老院", "环境导览", "roomtour")),
    Entry("family-portal", "来访与家属", "家属在哪里查看长者的照护记录？",
          "由机构核实亲属关系并开通家属账号。登录后从「家属服务」查看获授权的照护记录、通知或缴费提醒。看不到某项记录时，可请接待人员核实当前账号的授权。",
          ("家属服务", "家属账号", "家属查看", "家属看", "亲属关系", "家属通知", "家属推送")),
    Entry("account-recovery", "来访与家属", "忘记登录密码怎么办？",
          "在登录页进入「首次设置 / 找回密码」，使用已绑定的邮箱或手机接收验证码。联系方式无法使用时，请联系负责账号管理的人员处理。",
          ("忘记密码", "找回密码", "重置密码", "首次设置", "登录密码", "验证码")),
    Entry("resident-admission", "入住与账务", "怎样办理长者入住？",
          "先在「入住管理」建立长者档案，再从入住登记选择该长者办理入住。核对床位、入住日期和费用明细后，按入住表单办理缴费或依机构授权登记欠费临时入住。",
          ("办理长者入住", "办理老人入住", "办理入住", "入住流程", "分配床位", "长者入住", "老人入住")),
    Entry("trial-stay", "入住与账务", "试住和转正式入住怎么操作？",
          "在「入住管理」点击「办理试住」，选择长者和床位，核对日期与费用。入住状态可筛选为「试住」，直接在该长者的记录确认正式入住或取消入住；后续在同页的「试住回访」填写报告。",
          ("试住管理", "试住流程", "办理试住", "试住期满", "试住", "转正式", "试住回访")),
    Entry("monthly-invoice", "入住与账务", "月度账单在哪里看，账单日怎么确定？",
          "在长者的入住资料中可打开费用明细，账单也可在「财务结算」核对。月付以入住日期为默认账单日，以办理时保存的账单日和费用约定为准。",
          ("账单在哪里", "账单在哪", "月度账单", "月付账单", "查看账单", "费用明细", "账单日", "收费明细")),
    Entry("care-handover", "日常照护", "护工怎样登记和签收交班？",
          "在「照护服务 → 班次交接」选择接班账号和交班范围，填写未完成事项并提交。接班人可从顶部待处理事项打开交班，核对后签收。",
          ("登记交班", "交班怎么", "班次交接", "交接班", "签收交班", "签收交接")),
    Entry("medical-archive", "日常照护", "就诊资料和医疗文书应该放在哪里？",
          "进入长者详细档案的「医疗资料」，选择已有就诊记录或新建就诊记录。核对就诊日期、机构和资料后归档。补充的医疗文书直接附到对应病例下。",
          ("就诊资料", "就诊记录", "医疗文书", "医疗资料", "存病历", "扫描病历", "病历归档", "上传病历")),
    Entry("medication-record", "日常照护", "如何核对并记录一次服药？",
          "从「用药管理」核对经复核的医嘱、长者及当前餐次。确认本人实际服药情况后逐人签认。出现漏服、拒服或其他例外时，按机构流程记录实际情况并通知负责人员。",
          ("服药确认", "确认服药", "核对服药", "登记服药", "用药签认", "给药记录", "记录服药")),
    Entry("long-term-care", "机构运营", "长期护理保险业务在平台哪里办理？",
          "有权限的经办人可进入「长期护理保险」维护经办台账，关联长者并登记受理、评估材料及办理进度。参保条件、支付标准和申请材料以所在地医保部门当期发布为准。",
          ("长护险台账", "长护险在哪里", "长护险入口", "长护险经办", "长护险业务", "长期护理保险业务")),
    Entry("bed-filters", "机构运营", "怎样在床位管理按楼栋或楼层筛选？",
          "在「床位管理 → 全部床位」选择楼栋、楼层和床位状态，也可切换楼层平面图。可以请健康助理打开床位管理并筛选具体楼栋。",
          ("筛选床位", "床位筛选", "床位管理", "楼栋筛选", "楼层筛选", "按楼栋", "床位平面图")),
    Entry("access-request", "机构运营", "护工怎么申请临时编辑档案的权限？",
          "从长者详细档案或「个人中心 → 权限申请」选定长者和审批人并填写理由。审批人核对后使用登记实名和当前密码签署。批准后，申请人可在 24 小时内对该长者的登记资料保存一次有效修改。",
          ("权限申请", "申请编辑权限", "临时权限", "申请权限", "权限审批", "审批权限", "实名审批", "档案编辑权限", "编辑长者档案", "编辑老人档案")),
    Entry("encrypted-backup", "机构运营", "机构如何查看加密备份和恢复记录？",
          "有备份权限的经办人可在「机构设置 → 备份与恢复」查看最近快照、异地副本和恢复记录。在恢复前，先核对快照时间点和系统列出的差异。",
          ("备份在哪里", "在哪里备份", "备份与恢复", "备份恢复", "恢复快照", "加密备份", "备份记录", "备份")),
    Entry("assistant-voice", "平台使用", "怎样给健康助理发语音并听取朗读？",
          "打开健康助理，按住「按住说话」录音，松开后自动转写。按需开启语音转写后自动发送。朗读仅用于按住说话的语音提问，播放时可从声纹小窗暂停、继续或退出。",
          ("按住说话", "助手朗读", "助理朗读", "语音朗读", "语音转写", "朗读怎么", "朗读", "怎么发语音")),
    Entry("assistant-context", "平台使用", "健康助理可以查什么？",
          "健康助理可回答养老照护、机构运营和平台使用问题，按账号授权核对业务资料，也可以调出常见问题。联网查找限养老行业、养老机构维护及面向长者的健康主题。对话使用最近五轮问答作为上下文。",
          ("助理可以查", "助理能做", "助理会什么", "健康助理可以", "联网范围", "对话记忆", "上下文", "记住几轮")),
)
BY_ID = {entry.id: entry for entry in ENTRIES}

FAQ = re.compile(r"(?<![a-z])faq(?![a-z])|常见问题|帮助中心|使用指南", re.I)
HOW_TO = re.compile(r"怎么|如何|哪[里儿]|在哪|怎么办|流程|步骤|能不能|是否|指南|教程")
OPEN = re.compile(r"打开|进入|跳转|带我去|调出|点开|前往")
PASSIVE = re.compile(r"不要|不用|别|禁止|请勿|例如|比如|假如|如果")
PUBLIC = re.compile(r"联网|上网|搜索引擎|查(?:网|最新)|公开|政府|官网|政策|医保局|法规|法律|条例|https?://", re.I)
LIVE = re.compile(r"今天|今日|昨天|昨日|这几天|过去\s*\d|最近的|最新的|目前|本周|本月")


def read():
    return {"items": [entry.public() for entry in ENTRIES]}


def key(value):
    return "".join(normalize("NFKC", value).casefold().split())


def matches(question):
    text = key(question).strip("？?。！!")
    ranked = []
    for entry in ENTRIES:
        phrases = (entry.question.rstrip("？"), *entry.keywords)
        strength = max((len(term) for phrase in phrases if (term := key(phrase)) in text), default=0)
        if strength:
            ranked.append((strength, entry))
    return [entry for _, entry in sorted(ranked, key=lambda hit: -hit[0])[:3]]


def intent(question, previous_question=""):
    question = normalize("NFKC", question)
    explicit = bool(FAQ.search(question))
    op = explicit and bool(OPEN.search(question)) and not (HOW_TO.search(question) or PASSIVE.search(question))
    if not explicit and (PUBLIC.search(question) or LIVE.search(question)):
        return None
    if not explicit and not HOW_TO.search(question) and not any(question == entry.question for entry in ENTRIES):
        return None
    items = matches(question)
    if not items and HOW_TO.search(question) and FAQ.search(previous_question):
        items = matches(previous_question)
    if not items and not explicit:
        return None
    if not items:
        return {"mode": "list", "items": [], "open": op, "explicit": explicit}
    return {"mode": "answer", "items": items, "open": op, "explicit": explicit}


def links(ids):
    return [
        {"route": "faq", "title": BY_ID[ident].question, "params": {"item": ident}}
        for ident in ids if ident in BY_ID
    ] or [{"route": "faq", "title": "常见问题"}]
