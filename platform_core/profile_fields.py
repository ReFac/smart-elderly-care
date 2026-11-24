"""Offline code hierarchy and structured, independently permissioned dossier fields."""

from decimal import Decimal
from functools import cache
import json
from pathlib import Path
import re
import unicodedata

ASSETS = Path(__file__).resolve().parents[1] / "web" / "assets"


def phone_number(raw, *, mobile=False):
    """Canonical contact key for resident files, explicit visits and callback matching."""
    if not isinstance(raw, str) or len(raw) > 40:
        return ""
    value = re.sub(r"[\s()-]", "", unicodedata.normalize("NFKC", raw))
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("+86"):
        value = value[3:]
        if not value.startswith(("0", "1")):
            value = "0" + value
    if re.fullmatch(r"1[3-9][0-9]{9}", value):
        return value
    if not mobile and re.fullmatch(r"0[1-9][0-9]{8,10}", value):
        return value
    return value if re.fullmatch(r"\+[1-9][0-9]{7,14}", value) else ""


@cache
def catalog(name):
    return json.loads((ASSETS / (name + ".json")).read_text(encoding="utf-8"))


def enumeration(p, key, choices, old=""):
    value = p.get(key, "")
    if not isinstance(value, str) or (value and value != old and value not in choices):
        raise ValueError("请选择目录内的有效选项")
    return value


def amount_fields(p, band_key, amount_key):
    options = catalog("dossier-choices")
    band = enumeration(p, band_key, options["amountBands"])
    amount = p.get(amount_key, "")
    if band == "精确金额":
        if not isinstance(amount, str) or not re.fullmatch(
            r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?", amount
        ):
            raise ValueError("请填写精确金额，最多保留两位小数")
        amount = format(Decimal(amount), ".2f")
    elif amount not in ("", None):
        raise ValueError("金额区间和精确金额请择一登记")
    return {band_key: band, amount_key: amount or ""}


def region_children(parent):
    if (
        len(parent) == 9
        and parent.isdecimal()
        and parent.startswith("41")
        and not parent.startswith("4104")
    ):
        return catalog("henan-villages/" + parent[:4]).get(parent, {})
    return catalog("address-regions").get(parent, {})


def address_fields(value, *, birthplace=False):
    if not isinstance(value, dict) or set(value) - {"codes", "detail", "unlisted"}:
        raise ValueError("请按行政区划逐级选择")
    codes = value.get("codes")
    detail = value.get("detail", "")
    missing = value.get("unlisted", "")
    if (
        not isinstance(missing, str)
        or len(missing) > 100
        or any(ord(c) < 32 for c in missing)
    ):
        raise ValueError("请核对未收录的区划名称")
    missing = missing.strip()
    if "unlisted" in value and not missing:
        raise ValueError("请填写未收录地区的实际名称")
    if (
        not isinstance(codes, list)
        or not isinstance(detail, str)
        or len(detail) > 120
        or any(ord(c) < 32 for c in detail)
    ):
        raise ValueError("请核对地址与门牌")
    detail = detail.strip()
    if not codes and not detail and not missing:
        return {"codes": [], "detail": ""}, ""
    minimum = 1 if missing else (2 if birthplace else 3)
    if not minimum <= len(codes) <= (3 if birthplace else 5) - bool(missing) or (
        birthplace and detail
    ):
        raise ValueError("出生地或籍贯请选择省市，联系地址请选择至区县")
    parent = "CN"
    labels = []
    for code in codes:
        children = region_children(parent)
        if not isinstance(code, str) or code not in children:
            raise ValueError("区划层级不匹配，请重新选择")
        label = children[code]
        if label not in (
            "市辖区",
            "县",
            "省直辖县级行政区划",
            "自治区直辖县级行政区划",
        ) and (not labels or label != labels[-1]):
            labels.append(label)
        parent = code
    if missing and (
        not region_children(parent) or missing in region_children(parent).values()
    ):
        raise ValueError("请核对区划层级；已有地名请直接选择")
    return {
        "codes": list(codes),
        "detail": detail,
        **({"unlisted": missing} if missing else {}),
    }, " · ".join(
        [*labels, *([missing] if missing else []), *([detail] if detail else [])]
    )


def addresses(target, p, pairs):
    for key, printed, birth in pairs:
        if key in p:
            target[key], target[printed] = address_fields(p[key], birthplace=birth)
        elif printed in p and key in target:
            # Legacy callers can send unstructured text. Do not show stale structured selections.
            _, previous = address_fields(target[key], birthplace=birth)
            if p[printed] != previous:
                target.pop(key)


def update_profile(basic, household, p, user):
    from . import access

    options = catalog("dossier-choices")
    for key in ("language", "education", "maritalStatus", "occupation"):
        if key in p:
            basic[key] = enumeration(p, key, options[key], basic.get(key, ""))
    addresses(
        basic,
        p,
        (
            ("birthRegion", "birthplace", True),
            ("nativeRegion", "nativePlace", True),
            ("addressRegion", "address", False),
        ),
    )
    if set(p) & {"fundingSources", "pensionBand", "pensionAmount", "livingArrangement"}:
        access.require(user, "relatives")
        if "fundingSources" in p:
            sources = p["fundingSources"]
            if (
                not isinstance(sources, list)
                or len(sources) > len(options["fundingSources"])
                or any(s not in options["fundingSources"] for s in sources)
            ):
                raise ValueError("请选择有效费用来源")
            if "待核实" in sources and len(sources) > 1:
                raise ValueError("已选具体来源时请取消「待核实」")
            household["fundingSources"] = [
                x for x in options["fundingSources"] if x in sources
            ]
        if "pensionBand" in p or "pensionAmount" in p:
            band = p.get("pensionBand", household.get("pensionBand", ""))
            amount = p.get(
                "pensionAmount",
                household.get("pensionAmount", "") if band == "精确金额" else "",
            )
            household.update(
                amount_fields(
                    {"pensionBand": band, "pensionAmount": amount},
                    "pensionBand",
                    "pensionAmount",
                )
            )
        if "livingArrangement" in p:
            household["livingArrangement"] = enumeration(
                p,
                "livingArrangement",
                options["livingArrangement"],
                household.get("livingArrangement", ""),
            )
