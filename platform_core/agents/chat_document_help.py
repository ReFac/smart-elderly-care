"""Recognize requests to draft resident registration details from a supplied original."""
import re

from .. import access_policy as policy


RESIDENT = re.compile(r"长辈|长者|老人|老年人|住民|住户|入住人员")
PROFILE = re.compile(r"个人(?:信息|资料)|基本(?:信息|资料)|登记(?:信息|资料|表)|档案|身份证|户口(?:本|簿)")
DRAFT = re.compile(r"填|录入|补充|完善|更新|整理|登记|识别|读取|上传|传一|发一|导入")
FILE = re.compile(r"图片|照片|拍照|相片|扫描件|截图|文件|证件|身份证|PDF|表格|工作簿|Excel|xlsx?", re.I)
FOLLOW_UP = re.compile(r"^(?:那|可以|可不可以|能|我|用|发|传|再|给|这|只|还有|要|一|两|几|多|单|拍|支持|是|好|想|直接|[0-9])")


def _resident_request(text):
    if re.search(r"\b(?:resident|patient)\b", text, re.I) and re.search(r"profile|personal (?:details|information)|ID card", text, re.I) and re.search(r"fill|upload|complete|photo|image|scan", text, re.I):
        return True
    return bool(RESIDENT.search(text) and PROFILE.search(text) and (DRAFT.search(text) or FILE.search(text)))


def intent(text, previous_question=""):
    if not isinstance(text, str) or not text.strip():
        return False
    if _resident_request(text):
        return True
    return bool(previous_question and _resident_request(previous_question) and
                len(text) < 70 and FILE.search(text) and FOLLOW_UP.search(text.strip()) and
                not re.search(r"简历|员工|工单|报销|发票|药品|别的|不想|不用", text))


def reply(user, routes):
    if (user["kind"] not in ("owner", "staff") or not policy.has(user, "assistants") or
            "dossier.profile" not in policy.allowed_actions(user) or
            not ({"dossier", "residents"} & set(routes))):
        return "补充长辈个人资料需要档案编辑权限。请联系有权限的同事，或从该长辈的登记资料中申请编辑权限。", None
    return ("可以，一张清晰的照片就可以，也支持多张图片、PDF 和 Excel 表格。"
            "请点「上传长辈资料」，核对文件和所属长辈后，我会把能确认的字段预填到登记资料。最后由你核对并保存。",
            {"kind": "uploadResidentProfile", "title": "上传长辈资料"})
