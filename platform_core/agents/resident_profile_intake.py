"""Turn clearly labelled resident registration text into editable, scoped suggestions."""
import re

from .. import profile_fields, resident_credentials, visit_extraction


PROFILE = "长辈登记资料"
LABELS = {
    "gender": ("性别",),
    "phone": ("本人手机号", "长辈本人手机号", "本人手机", "本人联系电话", "本人电话"),
    "language": ("常用语言", "语言", "常用方言"),
    "maritalStatus": ("婚姻状况", "婚姻情况"),
    "education": ("文化程度", "学历"),
    "occupation": ("原职业", "职业"),
    "addressRegion": ("现居住址", "现住址", "现居地址"),
    "birthRegion": ("出生地", "出生地点"), "nativeRegion": ("籍贯",),
}
BY_LABEL = {label: key for key, labels in LABELS.items() for label in labels}
LABELLED = re.compile(r"^(" + "|".join(sorted(BY_LABEL, key=len, reverse=True)) + r")[ :]+(.{1,140})$")


def region(raw, *, birthplace):
    parent, codes = "CN", []
    remaining = raw.strip()
    for _ in range(3 if birthplace else 5):
        children = profile_fields.region_children(parent)
        hits = [code for code, name in children.items() if remaining.startswith(name)]
        if len(hits) != 1:
            break
        parent = hits[0]
        codes.append(parent)
        remaining = remaining[len(children[parent]):].lstrip(" /·,，")
    if len(codes) < (2 if birthplace else 3) or birthplace and remaining:
        return None
    try:
        result, _ = profile_fields.address_fields({"codes": codes, "detail": remaining}, birthplace=birthplace)
    except ValueError:
        return None
    return result


INTERNATIONAL_FIELDS = {
    "name": "name", "full name": "name", "resident name": "name", "patient name": "name",
    "date of birth": "birthDate", "dob": "birthDate", "phone": "phone", "mobile": "phone",
    "postal address": "address", "home address": "address", "place of birth": "birthplace",
    "place of origin": "nativePlace",
}


def international_suggestions(lines, fields, ambiguous):
    seen = {}
    for line in lines:
        label, sep, value = visit_extraction.clean(line["text"]).partition(":")
        key = INTERNATIONAL_FIELDS.get(label.strip().casefold())
        if not sep or not key:
            continue
        value = value.strip()
        if key == "phone":
            value = profile_fields.phone_number(value, mobile=True)
        elif key == "birthDate":
            value = visit_extraction.day(value) if visit_extraction.DATE.fullmatch(value) else ""
        elif key == "name":
            if not any(ch.isalpha() for ch in value) or any(not (ch.isalpha() or ch in " .’'-") for ch in value):
                value = ""
        if not 0 < len(value) <= (60 if key == "name" else 100) or any(ord(ch) < 32 for ch in value):
            value = ""
        options = seen.setdefault(key, {fields[key]} if fields.get(key) else set())
        options.add(value)
    for key, options in seen.items():
        if len(options) == 1 and "" not in options and key not in ambiguous:
            fields[key] = next(iter(options))
        else:
            fields.pop(key, None)
            if key not in ambiguous:
                ambiguous.append(key)


def suggestions(lines, material, *, international=False):
    fields = {k: material["fields"][k] for k in ("name", "birthDate") if k in material["fields"]}
    ambiguous = [k for k in material["ambiguous"] if k in ("name", "birthDate", "idNumber")]
    seen = {}
    for line in lines:
        match = LABELLED.fullmatch(visit_extraction.clean(line["text"]))
        if match:
            seen.setdefault(BY_LABEL[match[1]], set()).add(match[2].strip())
    choices = profile_fields.catalog("dossier-choices")
    for key, values in seen.items():
        value = next(iter(values)) if len(values) == 1 else ""
        if key == "phone":
            value = profile_fields.phone_number(value, mobile=True)
        elif key.endswith("Region"):
            value = region(value, birthplace=key != "addressRegion") if value else None
        elif key == "gender":
            value = value if value in ("女", "男") else ""
        elif value not in choices[key]:
            value = ""
        if value:
            fields[key] = value
        else:
            ambiguous.append(key)
    if international:
        international_suggestions(lines, fields, ambiguous)
    return {"fields": fields, "ambiguous": ambiguous}
