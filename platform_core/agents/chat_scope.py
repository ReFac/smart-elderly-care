"""Deterministic subject rules for an institution's assistant and public searches."""

import re
from unicodedata import normalize


REFUSAL = "这个问题超出了院务范围。你想了解院里的哪件事？"
NO_TOPIC = "这句话没有提取到可独立检索的养老或医疗主题。请用不含个人资料的问题再问一次。"

PUBLIC_SUBJECTS = {
    "insurance": r"长护险|长护保险|长期照护保险|长期护理(?:保险|险)|医保|医疗保障|医疗险|社保.{0,5}待遇|"
                 r"long.term care insurance|health insurance|medicaid|medicare",
    "eldercare": r"养老|医养|护养|疗养院|护理|照护|失能|失智|老年|老龄|长[辈者]|高龄|老人|安宁疗护|"
                 r"eldercare|elderly|geriatr\w*|older adults|senior care|nursing|caregivers?|care homes?|"
                 r"long.term care|assisted living|dementia care|palliative care|hospice",
    "health": r"疾病|医疗|医学|医院|卫生健康|疾控|感染|并发症|体征|临床|康复|药物|用药|疫苗|"
              r"就医|就诊|诊疗|病情|预防接种|健康评估|健康指南|急救|心肺复苏|血压|血糖|发热|发烧|呛咳|噎住|"
              r"心梗|心绞痛|心律失常|卒中|脑梗|中风|骨折|褥疮|压疮|压伤|跌倒|吞咽困难|尿路感染|"
              r"高血压|糖尿病|慢阻肺|哮喘|痛风|肺炎|骨质疏松|阿尔茨海默|帕金森|抑郁症|肿瘤|癌症|"
              r"贫血|便秘|失眠|脱水|眩晕|关节炎|白内障|青光眼|骨关节疾病|"
              r"[一-龥]{1,12}(?:综合征|病症|病变|性疾病|肝炎|肾病|传染病|息肉|增生|功能衰竭)|"
              r"hospital|medical|healthcare|diseases?|illness|symptoms?|diagnosi[ss]|clinical|first aid|"
              r"diabet\w*|dementia|alzheimer\w*|stroke|hypertension|pneumonia|parkinson\w*|"
              r"osteoporosis|rehabilitation|vaccin\w*|medication|infection|pressure ulcer",
}
PUBLIC_SUBJECTS = {
    name: re.compile(r"(?<![a-z])(?:" + words + r")(?![a-z])", re.I)
    for name, words in PUBLIC_SUBJECTS.items()
}
UNRELATED = re.compile(
    r"装机|攒机|游戏本|游戏电脑|(?:电脑|台式机|笔记本|cpu|gpu|显卡).{0,10}(?:配置|推荐|排行|性价比|买|评测)|"
    r"(?:配置|推荐|买).{0,6}(?:电脑|台式机|笔记本|cpu|gpu|显卡)|"
    r"游戏攻略|电竞|股票(?:推荐|行情|走势)|选股|彩票|博彩|抽奖攻略|八卦|偶像(?:新闻|绯闻)|"
    r"旅游攻略|出游攻略|手机.{0,8}(?:配置|推荐|性价比)|购物推荐|购物折扣|小说推荐|影视推荐|"
    r"(?:淘宝|京东|拼多多|购物).{0,12}(?:账号|账户|登录|支付|优惠)|任务管理软件|普通天气|天气预报|"
    r"今天.{0,8}天气.{0,6}怎么样|(?:附近|周边).{0,14}(?:奶茶|烧烤|餐厅|餐馆|甜品店|咖啡店)|"
    r"\b(?:gaming pc|gaming laptop|pc build|computer specs|"
    r"(?:cpu|gpu) recommendation|stock picks?|celebrity gossip|video game walkthrough)\b",
    re.I,
)
ELDERCARE_PRACTICE = re.compile(
    r"养老(?:政策|服务|补贴|照护|护理|标准|模式|待遇|产业|行业|管理)|医养结合|疗养|护理|照护|健康|"
    r"起居|失能|失智|认知|身体|运动|活动|营养|膳食|饮食|早餐|餐食|睡眠|入住|探访|机构选型|机构名单|选择|"
    r"管理|运营|申办|备案|筹建|开办|建设|法规|政策|标准|消防|服务质量|人员配比|设施|维护|"
    r"维保|防护|护理员|培训|交班|监控|门禁|设备|收费|合规|验收|照明|巡检|报修|巡查|排查|"
    r"nursing|care|assist\w* living|geriatr\w*|staffing|regulations?|"
    r"certification|autonomy|falls?|nutritio\w*|facilit\w* maintenance",
    re.I,
)
INSTITUTION = re.compile(
    r"院务|院区|院内|院里|院门|我院|本院|分院|院方|护工|护理员|病房|床位|房型|楼层平面图|"
    r"退住|试住|续住|排班|班次|交班|探访|来访登记|入住办理|办理入住|巡查|体检|"
    r"配餐|餐单|餐费|行政简报|工单|医疗档案|长[辈者]档案|病历|物资|库存|仓库|仓储|供应商|经销员|"
    r"欠款|账单|营收|收款|缴费|流水|财务|机构设置|系统设置|工作区备份|机构的?数据备份|全员通知|"
    r"家属服务|员工|重复用药|医疗|疾病|用药|服药|喂药|给药|吃药|医嘱|台账|运营总览|环境导览|"
    r"看我上次聊天|新对话|历史对话|复盘对话|对话记忆|这个界面|本页|工作台|本平台|医养平台|"
    r"填(?:一下|好|写|报)|登记表|上传(?:文件|资料|图片|照片)|这(?:份|张)(?:材料|资料|表|文件|照片)|"
    r"平台(?:备份|恢复|更新|权限|登录|巡查|用量|帮助|联网)|健康助理|"
    r"\b(?:inventory|handover|staffing|care plan|care work|ward|admission|resident|receipts?|bills?|staff|visits?|bed occupancy|"
    r"bed management|deployment console|deployment settings|scheduled care tasks|recurring care tasks|stock ledger|patient care)\b",
    re.I,
)
SHORT_WORKSPACE = re.compile(
    r"^(?:今天|今日|最近|查一下|看看|查|问|我的?|本院的?|本系统的?|打开|查看|请)?\s*"
    r"(?:账号|账户|权限申请|登录|平台备份|备份|照护|护理|房间|这个房间|这个页面|营业情况|营运|"
    r"待办|通知|全员通知|导览|帮助中心|常见问答|常见问题|faq)"
    r"(?:的?(?:情况怎么样|情况|有哪些|怎么样|如何|入口|怎么使用|在哪里|是什么意思|是什么|有没有|信息|设置|"
    r"最新状态|进度))?[？?！!。吧呢呀]*$",
    re.I,
)
GREETINGS = re.compile(
    r"^(?:你好(?:呀|啊|吗)?|您好|嗨|哈喽|谢谢(?:你)?|辛苦了|再见|不客气|你是谁|"
    r"你(?:能|可以)(?:帮我)?做什么|hello|hi|thank you|thanks|goodbye)[，,。！？!?\s]*$",
    re.I,
)
NEXT_STEPS = re.compile(r"^(?:接下来|现在)(?:还有|有)(?:什么|哪些)(?:需要|应该)(?:看|处理|查看|办)的[？?！!。吗呢]*$")
FOLLOW_UP = re.compile(
    r"^(?:那|那么|他们|她们|这些|这些人|其中|上面|刚才|之前)?"
    r"(?:继续|还有|还有谁|还有什么|还有哪些|再说一次|再看一眼|能展开|说详细点|详细一点|"
    r"为什么|怎么做|怎么处理|怎么办|有哪些变化|有变化|是哪些|是哪几项|有几个|"
    r"多少人|多少钱|过去\s*(?:24|48|一|两|二|四十八)\s*(?:小时|h|天))[呢吗呀吧？?。！!]*$",
    re.I,
)

_TODAY = r"(?:今天|今日|现在|目前|这会儿)"
_HOME = r"(?:(?:我们|咱们|咱)?(?:这个|这家)?(?:养老院|疗养院|机构|院里|院内|院区)|我院|本院|全院|咱院)"
_OVERVIEW_SUBJECT = rf"(?:{_TODAY}(?:的?{_HOME})?|{_HOME}(?:的?{_TODAY})?)"
_STATUS = r"(?:怎么样|怎样|咋样|如何|还好[吗么]|有(?:什么|哪些)(?:事儿?|变化|情况))"
_OPERATIONS = r"(?:整体|总体)?(?:运营|经营|运行|院务)?"
OVERVIEW = re.compile(
    r"(?:你好|您好)?(?:请问|想问一下|问一下|我想了解一下|帮我看看|帮我看一下|给我说说|说说|看看|汇报一下)?"
    + _OVERVIEW_SUBJECT
    + rf"的?{_OPERATIONS}(?:(?:情况|状况|状态)?{_STATUS}|情况|状况|概况|简报|总结|报告)"
    + r"(?:了|啦)?(?:吗|么|呢|啊|呀|吧)?"
)


def overview_question(text):
    query = re.sub(r"[\s，、。！？,?.!]", "", normalized(text))
    return OVERVIEW.fullmatch(query) is not None


def normalized(text):
    return normalize("NFKC", text).strip().casefold()


def public_subjects(text):
    if UNRELATED.search(text):
        return set()
    subjects = {name for name, expression in PUBLIC_SUBJECTS.items() if expression.search(text)}
    if "eldercare" in subjects and not ELDERCARE_PRACTICE.search(text):
        subjects.discard("eldercare")
    return subjects


def obvious_unrelated(text):
    return bool(UNRELATED.search(normalized(text)))


def conversation_subject(text, previous=""):
    text = normalized(text)
    if obvious_unrelated(text):
        return False
    if (overview_question(text) or public_subjects(text) or INSTITUTION.search(text) or SHORT_WORKSPACE.fullmatch(text)
            or GREETINGS.fullmatch(text) or NEXT_STEPS.fullmatch(text)):
        return True
    previous = normalized(previous)
    return bool(FOLLOW_UP.fullmatch(text) and not obvious_unrelated(previous)
                and (overview_question(previous) or public_subjects(previous)
                     or INSTITUTION.search(previous) or SHORT_WORKSPACE.fullmatch(previous)))
