"""A user-initiated live drug name search with ATC-coded candidate filtering."""

from http.client import HTTPException
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .agents.chat_web import privacy_allows

API = "https://www.wikidata.org/w/api.php"
PUBLIC_SEARCH = "https://pharm.ncmi.cn/pharm/fullText/search.do?"
SOURCE = "Wikidata 开放药名资料"
MAX_BYTES = 2 * 1024 * 1024


def public_term(db, state, text):
    # No room/bed, contact details, chart text, or known directory names accompany a query.
    if (
        not isinstance(text, str)
        or not 2 <= len(text) <= 45
        or not re.fullmatch(r"[\u3400-\u9fffA-Za-zα-ω0-9Ⅰ-Ⅹ·（）()/ -]+", text)
    ):
        return False
    return not re.search(
        r"\d{4}|住址|服用|早晚|每天|早晨|房间|护工|护士|老人|患者|病人|姓名|毫克|用量",
        text,
    ) and privacy_allows(db, state, text)


def _api(**params):
    request = Request(
        API + "?" + urlencode({"format": "json", **params}),
        headers={
            "User-Agent": "ElderlyCare/1.0 (https://github.com/ReFac/smart-elderly-care)",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=6) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("来源返回内容过大")
    result = json.loads(data)
    if not isinstance(result, dict) or "error" in result:
        raise ValueError("来源未返回有效结果")
    return result


def _atc(entity):
    for claim in entity.get("claims", {}).get("P267", []):
        if claim.get("rank") != "deprecated":
            value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(value, str) and re.fullmatch(
                "[A-Z][0-9]{2}[A-Z]{2}[0-9]{2}", value
            ):
                return value
    return ""


def search(query):
    result = {
        "status": "live",
        "matches": [],
        "source": SOURCE,
        "publicUrl": PUBLIC_SEARCH + urlencode({"keyWord": query}),
    }
    try:
        response = _api(
            action="wbsearchentities",
            search=query,
            language="zh",
            uselang="zh-cn",
            limit=5,
        )
        records = [
            (item["id"], item["label"])
            for item in response["search"]
            if re.fullmatch("Q[0-9]+", item.get("id", ""))
            and isinstance(item.get("label"), str)
            and 1 < len(item["label"]) <= 60
        ]
        if records:
            entities = _api(
                action="wbgetentities",
                ids="|".join(key for key, _ in records),
                props="claims",
            )["entities"]
            for key, name in records:
                code = _atc(entities.get(key, {}))
                if code:
                    result["matches"].append(
                        {
                            "name": name,
                            "match": "ATC " + code,
                            "url": "https://www.wikidata.org/wiki/" + key,
                        }
                    )
    except (OSError, ValueError, HTTPException, KeyError, TypeError, AttributeError):
        result["status"] = "unavailable"
        result["matches"] = []
    return result
