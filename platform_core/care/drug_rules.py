"""Institution-validated medication pairs, with source and version kept on each review."""

import unicodedata
from .records import append_record, lookup, required_field


def canonical(name):
    return unicodedata.normalize("NFKC", name).strip().casefold()


def matching(state, resident_id, name, exclude_id):
    key = canonical(name)
    others = {
        canonical(m["name"])
        for m in state["medications"]
        if m["residentId"] == resident_id
        and m["id"] != exclude_id
        and m["status"] in ("待执行", "待复核")
    }
    return [
        r
        for r in state.get("drugRules", ())
        if r["status"] == "生效"
        and (
            canonical(r["drugA"]) == key
            and canonical(r["drugB"]) in others
            or canonical(r["drugB"]) == key
            and canonical(r["drugA"]) in others
        )
    ]


def publish(state, p, today):
    a = required_field(p, "drugA", "药品一")
    b = required_field(p, "drugB", "药品二")
    pair = {canonical(a), canonical(b)}
    if len(pair) != 2:
        raise ValueError("配伍规则需要两个不同药品。")
    version = required_field(p, "version", "核准版本")
    for r in state.get("drugRules", ()):
        if {canonical(r["drugA"]), canonical(r["drugB"])} == pair:
            if r["status"] == "生效" or r["version"] == version:
                raise ValueError(
                    "药品组合已有生效规则或重复版本；更新时请停用旧版并登记新版。"
                )
    data = dict(
        drugA=a,
        drugB=b,
        version=version,
        source=required_field(p, "source", "核准资料与编号"),
        message=required_field(p, "message", "人工核准的提醒内容"),
        reviewer=required_field(p, "operator", "发布人"),
        date=today,
        status="生效",
    )
    state.setdefault("drugRules", [])
    append_record(state, "drugRules", **data)
    return "已发布带依据与版本的配伍规则"


def retire(state, p, today):
    state.setdefault("drugRules", [])
    rule = lookup(state, "drugRules", p.get("ruleId"))
    if rule["status"] != "生效":
        raise ValueError("该版本已停用。")
    rule.update(
        reason=required_field(p, "reason", "停用原因"),
        retiredBy=required_field(p, "operator", "停用人"),
        retiredAt=today,
        status="已停用",
    )
    return "已停用此版本的配伍规则"
