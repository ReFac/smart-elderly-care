"""Resolve a requested area on the host and retain its room boundaries with the run."""

import json

from .. import facility

FIELDS = ("buildingId", "floorId", "roomId")
POLICY = ("buildingIds", "floorIds", "roomIds")
EMPTY_STATE = {"beds": [], "residents": []}


def selection(value):
    if not isinstance(value, dict) or set(value) - set(FIELDS):
        raise ValueError("区域只能指定楼栋、楼层或房间")
    selected = {}
    for key in FIELDS:
        item = value.get(key, "")
        if not isinstance(item, str) or len(item) > 100 or item != item.strip():
            raise ValueError("区域编号无效")
        if item:
            selected[key] = item
    if not selected:
        raise ValueError("请选择一个具体区域")
    return selected


def within(db, user, selected):
    policy = user.get("facilityScope", {})
    if not isinstance(policy, dict) or set(policy) - {"institutionId", *POLICY}:
        raise PermissionError("区域授权格式无效")
    if "institutionId" in policy:
        site = db.execute("SELECT id FROM facility_site WHERE singleton=1").fetchone()
        if not site or policy["institutionId"] != site[0]:
            raise PermissionError("机构范围不匹配")
    if any(key in policy for key in POLICY) and not selected:
        raise PermissionError("当前岗位必须选择获授权的楼栋、楼层或房间")


def resolve(db, state, user, selected):
    within(db, user, selected)
    if selected is None:
        return None
    return facility.scope(db, state, user, **selected)


def save(db, run_id, resolved):
    historical = {
        k: resolved[k] for k in ("institutionId", *FIELDS, "label", "roomIds")
    }
    db.execute(
        "INSERT INTO agent_regions VALUES(?,?)",
        (run_id, json.dumps(historical, ensure_ascii=False)),
    )


def visible(db, user, saved):
    """An employee newly limited to a room cannot reopen the old whole-floor report."""
    if not user.get("facilityScope") and isinstance(
        user.get("facilityScope", {}), dict
    ):
        return True
    try:
        within(db, user, saved)
        if not saved:
            return True
        current = facility.scope(db, EMPTY_STATE, user, **{k: saved[k] for k in FIELDS})
        return saved["institutionId"] == current["institutionId"] and set(
            saved["roomIds"]
        ) <= set(current["roomIds"])
    except (ValueError, PermissionError, FileNotFoundError, KeyError):
        return False
