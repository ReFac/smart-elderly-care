"""Fuzzy lookup over public facility names. Queries stay on the institution host."""

from collections import namedtuple
from contextlib import closing
import csv
from functools import lru_cache
import gzip
from pathlib import Path
import re
from unicodedata import normalize

from . import access

CATALOG = Path(__file__).with_name("catalog_data") / "hospitals.tsv.gz"
REGION_WORDS = ("河南省", "河南", "郑州市", "郑州", "平顶山市", "平顶山", "汝州市", "汝州")
ALIASES = {
    "郑州大学第一附属医院": ("郑大一附院", "郑大一附"),
    "郑州大学第二附属医院": ("郑大二附院",),
    "河南省人民医院": ("河南省医", "省人民医院"),
    "汝州市第一人民医院": ("汝州一院", "汝州一人医", "汝州一医院"),
    "平顶山市第一人民医院": ("平顶山一院", "平顶山一人医"),
    "平顶山市第二人民医院": ("平顶山二院", "平顶山二人医"),
    "中国医学科学院北京协和医院": ("北京协和", "北京协和医院"),
    "复旦大学附属华山医院": ("华山医院", "上海华山医院"),
    "四川大学华西医院": ("华西医院", "四川华西"),
}
LOCALITY_OVERRIDES = {"郑州大学第一附属医院": "河南省郑州市"}
Hospital = namedtuple("Hospital", "name province locality priority tokens region")


def compact(text):
    return re.sub(r"[^\w\u3400-\u9fff]", "", normalize("NFKC", text).casefold())


@lru_cache(maxsize=1)
def entries():
    result = []
    with gzip.open(CATALOG, "rt", encoding="utf-8", newline="") as stream:
        for name, province, locality, source in csv.reader(stream, delimiter="\t"):
            if locality == province:
                locality = LOCALITY_OVERRIDES.get(name, locality)
            main = compact(name)
            names = (main, *(compact(value) for value in ALIASES.get(name, ())))
            priority = (province == "河南省") + 2 * any(
                city in locality for city in ("郑州市", "平顶山市")
            ) + 3 * ("汝州市" in locality)
            result.append(Hospital(name, province, locality, int(source) + priority, names, compact(locality)))
    return result


def in_order(needle, value):
    letters = iter(value)
    return all(letter in letters for letter in needle)


def rank(query, term, row):
    if query in row.tokens:
        return 0
    if any(query in value for value in row.tokens):
        return 1
    if term != query and any(term in value for value in row.tokens):
        return 2
    if query in row.region:
        return 3
    if len(query) >= 2 and any(in_order(query, value) for value in row.tokens):
        return 4
    if term != query and len(term) >= 2 and any(in_order(term, value) for value in row.tokens):
        return 5
    return None


def lookup(query, limit=12):
    if not isinstance(query, str) or len(query) > 80:
        raise ValueError("医院名称最多 80 字")
    query = compact(query)
    if not query:
        return []
    region = next((word for word in sorted(REGION_WORDS, key=len, reverse=True) if word in query), "")
    term = query.replace(region, "", 1) or query
    ranked = []
    for row in entries():
        if region and region not in row.region and region not in row.tokens[0]:
            continue
        score = rank(query, term, row)
        if score is not None:
            ranked.append((score, -row.priority, len(row.name), row))
    ranked.sort()
    result = []
    seen = set()
    for _, _, _, row in ranked:
        # The same facility can appear in several historical publication years.
        key = row.tokens[0], row.province
        if key in seen:
            continue
        seen.add(key)
        result.append({"name": row.name, "locality": row.locality})
        if len(result) == limit:
            break
    return result


def search(store, token, query):
    with closing(store.connect()) as db:
        actor = store.actor(db, token)
        if actor["kind"] not in ("owner", "staff"):
            raise PermissionError("仅档案经办人可使用医院名录")
        for permission in ("medical", "medical.write", "clinical"):
            access.require(actor, permission)
    return {"options": lookup(query)}
