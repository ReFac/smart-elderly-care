"""Identified household members, independent of logins and sharing consent."""

import re
from uuid import uuid4

KINDS = {"配偶", "子女", "其他"}
ROLES = ("推荐联系人", "常用联系人", "紧急联系人")


def update(household, change, today):
    from .dossier import calendar_day, text

    if not isinstance(change, dict):
        raise ValueError("请填写家庭成员资料")
    members = list(household.get("familyMembers", []))
    member_id = text(change, "id", 64)
    old = next((item for item in members if item["id"] == member_id), None)
    if member_id and not old:
        raise ValueError("家庭成员已变动，请刷新")
    if change.get("remove") is True:
        if not old:
            raise ValueError("请选择要移除的家庭成员")
        household["familyMembers"] = [m for m in members if m["id"] != member_id]
        return
    kind = text(change, "kind", 10, True)
    roles = change.get("roles", [])
    if (
        kind not in KINDS
        or not isinstance(roles, list)
        or any(v not in ROLES for v in roles)
    ):
        raise ValueError("请核对成员类别与联系人用途")
    if kind == "配偶" and any(
        m["kind"] == kind and m["id"] != member_id for m in members
    ):
        raise ValueError("已登记配偶，请编辑现有资料")
    phone = text(change, "phone", 40, required=bool(roles))
    if phone and (
        not re.fullmatch(r"\+?[0-9 ()-]+", phone)
        or not 5 <= sum(c.isdigit() for c in phone) <= 18
    ):
        raise ValueError("请核对联系电话")
    verified = text(change, "verifiedOn", 10)
    if verified:
        calendar_day(verified, "电话接通核实日期", today)
        if not phone:
            raise ValueError("请先填写已通过人工通话核实的电话号码")
    member = {
        "id": member_id or uuid4().hex,
        "kind": kind,
        "name": text(change, "name", 60, True),
        "relationship": text(change, "relationship", 50),
        "phone": phone,
        "address": text(change, "address", 300),
        "note": text(change, "note", 300),
        "roles": [r for r in ROLES if r in roles],
        "verifiedOn": verified,
    }
    if old:
        members[members.index(old)] = member
    else:
        members.append(member)
    household["familyMembers"] = members
