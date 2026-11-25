"""Read labelled registration fields from original text and validate staff-reviewed values."""

import re

from . import dossier, visit_extraction

CATEGORIES = {"身份证正面": "idFront", "身份证反面": "idBack", "户口本": "household", "发票": "invoice"}
LABELS = {
    "name": ("姓名", "患者姓名", "个人姓名"), "birthDate": ("出生日期", "出生"),
    "idNumber": ("公民身份号码", "居民身份证号码", "身份证号码", "身份证号"),
    "authority": ("签发机关",), "validity": ("有效期限", "有效期"),
    "invoiceDate": ("开票日期",),
}
KINDS = {
    "idFront": ("name", "birthDate", "idNumber"), "idBack": ("authority", "validity"),
    "household": ("name", "birthDate", "idNumber"), "invoice": ("invoiceDate",),
}
LIMITS = {"name": 60, "authority": 80, "validity": 60}
NUMBER = re.compile(r"(?<![0-9])(?:[0-9][ \t-]*){17}[0-9Xx](?![0-9])")
ALL_LABELS = {label for aliases in LABELS.values() for label in aliases} | {"性别", "民族", "住址", "出生地", "出生地点"}
MARKER = re.compile("|".join(sorted(ALL_LABELS, key=len, reverse=True)))


def reviewed(kind, fields, person):
    if not isinstance(fields, dict) or fields.keys() - set(KINDS[kind]):
        raise ValueError("请核对该材料允许填写的证件字段")
    result = {}
    for key, value in fields.items():
        if not isinstance(value, str) or len(value) > 120 or any(ord(ch) < 32 for ch in value):
            raise ValueError("证件字段格式无效")
        value = value.strip()
        if not value:
            continue
        if key == "name" and person != value:
            raise ValueError("证件姓名与所选长辈不符，请核实归属")
        if key == "idNumber":
            value = value.upper()
            dossier.check_identity(value)
        if key in ("birthDate", "invoiceDate") and visit_extraction.day(value) != value:
            raise ValueError("请按年月日核对日期")
        if len(value) > LIMITS.get(key, 60):
            raise ValueError("证件字段过长")
        result[key] = value
    number = result.get("idNumber")
    if number and result.get("birthDate") and result["birthDate"].replace("-", "") != number[6:14]:
        raise ValueError("出生日期与证件号码不符，请核对原件")
    return result


def suggestions(lines):
    seen = {}
    for i, line in enumerate(lines):
        text = visit_extraction.clean(line["text"])
        parts = list(MARKER.finditer(text))
        if parts and text[:parts[0].start()].strip(" |:，,"):
            continue
        for index, match in enumerate(parts):
            label = match[0]
            key = next((key for key, aliases in LABELS.items() if label in aliases), None)
            if not key:
                continue
            end = parts[index + 1].start() if index + 1 < len(parts) else len(text)
            value = text[match.end():end].strip(' :')
            if not value and len(parts) == 1 and i + 1 < len(lines) and lines[i + 1]["page"] == line["page"]:
                following = visit_extraction.clean(lines[i + 1]["text"])
                value = following if not MARKER.search(following) else ""
            if key in ("birthDate", "invoiceDate"):
                value = visit_extraction.day(value) if visit_extraction.DATE.fullmatch(value) else ""
            elif key == "idNumber":
                value = re.sub(r"[ \t-]", "", value).upper()
                try:
                    dossier.check_identity(value)
                except ValueError:
                    value = ""
            elif key == "name" and not re.fullmatch(r"[a-zA-Z\u3400-\u9fff·• -]{2,60}", value):
                value = ""
            seen.setdefault(key, set()).add(value if len(value) <= LIMITS.get(key, 60) else "")
    fields = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1 and "" not in v}
    conflicts = [k for k in seen if k not in fields]
    if "idNumber" in fields and "birthDate" in fields and fields["idNumber"][6:14] != fields["birthDate"].replace("-", ""):
        conflicts += ["birthDate", "idNumber"]
        del fields["birthDate"], fields["idNumber"]
    return {"fields": fields, "ambiguous": conflicts}
