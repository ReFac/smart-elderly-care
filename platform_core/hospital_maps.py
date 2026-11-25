"""Explicit hospital-name searches via edition-specific map services."""
from http.client import HTTPException, HTTPSConnection
import json
import os
import re
from urllib.parse import urlencode, urlsplit


MAX_RESPONSE = 128 * 1024


def public_keyword(value):
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= 80:
        raise ValueError("Enter a hospital name or city (2–80 characters).")
    value = value.strip()
    if re.search(r"\d{7}|[\r\n\t@:/\\<>?=&%#]|身份证|手机号|床号|病历号|patient\s*(id|number)", value, re.I):
        raise ValueError("请仅输入医院名称或城市 / Enter only the hospital name or city.")
    return value


def _fetch(host, path, *, body=None, headers=None):
    connection = HTTPSConnection(host, timeout=5)
    try:
        connection.request("POST" if body is not None else "GET", path, body=body, headers=headers or {})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("Directory unavailable")
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("Directory response is too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("Unexpected directory response")
        return result
    finally:
        connection.close()


def _small(value, limit):
    return value.strip()[:limit] if isinstance(value, str) else ""


def _google(query, key, language):
    payload = _fetch("places.googleapis.com", "/v1/places:searchText",
                     body=json.dumps({"textQuery":query, "includedType":"hospital", "strictTypeFiltering":True,
                                      "languageCode":language, "pageSize":8}).encode(),
                     headers={"Content-Type":"application/json", "X-Goog-Api-Key":key,
                              "X-Goog-FieldMask":"places.id,places.displayName,places.formattedAddress,places.attributions"})
    rows = []
    for place in payload.get("places", [])[:8]:
        name = _small((place.get("displayName") or {}).get("text"), 180)
        if not name:
            continue
        credits = []
        for credit in (place.get("attributions") or [])[:8]:
            label = _small(credit.get("provider"), 180)
            uri = _small(credit.get("providerUri"), 1024)
            if label:
                credits.append({"name":label, "url":uri if urlsplit(uri).scheme == "https" else ""})
        rows.append({"name":name, "locality":_small(place.get("formattedAddress"), 240),
                     "placeId":_small(place.get("id"), 160), "credits":credits})
    return rows


def _amap(query, key):
    params = urlencode({"key":key, "keywords":query, "types":"090100|090200", "page_size":"8"})
    data = _fetch("restapi.amap.com", "/v5/place/text?" + params)
    if data.get("status") != "1":
        raise ValueError("Directory unavailable")
    rows = []
    for poi in data.get("pois", [])[:8]:
        name = _small(poi.get("name"), 180)
        if name:
            locality = "".join(_small(poi.get(k), 80) for k in ("pname", "cityname", "adname"))
            rows.append({"name":name, "locality":locality, "credits":[]})
    return rows


def search(edition, language, query):
    query = public_keyword(query)
    google = edition == "international"
    provider = "google" if google else "amap"
    key = os.environ.get("NH_GOOGLE_PLACES_KEY" if google else "NH_AMAP_WEB_KEY")
    result = {"provider":provider, "status":"not-configured", "options":[]}
    if key:
        try:
            result["options"] = _google(query, key, language) if google else _amap(query, key)
            result["status"] = "ok"
        except (OSError, HTTPException, ValueError, TypeError, KeyError, AttributeError):
            result["status"] = "unavailable"
    return result
