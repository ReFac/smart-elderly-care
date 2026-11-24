"""Compare employee assignments at their actual building, floor or room granularity."""

from contextlib import contextmanager


def boundary(db, user, resolver):
    if user["kind"] == "owner" or (resolver is None and not user.get("facilityScope")):
        return None
    site = db.execute("SELECT id FROM facility_site WHERE singleton=1").fetchone()[0]
    # A floor includes future rooms. Comparing just the currently occupied rooms
    # would let a room-bound manager reset a whole-floor employee's password.
    locations = {
        "buildingIds": {
            b: (b,) for (b,) in db.execute("SELECT id FROM facility_buildings")
        },
        "floorIds": {
            f: (b, f)
            for f, b in db.execute("SELECT id,buildingId FROM facility_floors")
        },
        "roomIds": {
            r: (b, f, r)
            for r, f, b in db.execute(
                "SELECT r.id,f.id,f.buildingId FROM facility_rooms r JOIN facility_floors f ON r.floorId=f.id"
            )
        },
    }

    def branches(policy):
        if (
            not isinstance(policy, dict)
            or set(policy) - {"institutionId", *locations}
            or policy.get("institutionId", site) != site
        ):
            raise PermissionError("机构或区域授权无效")
        result = {()}
        for key, paths in locations.items():
            if key not in policy:
                continue
            ids = policy[key]
            if not isinstance(ids, (list, tuple)) or any(
                not isinstance(i, str) or i not in paths for i in ids
            ):
                raise PermissionError("无法核实账号的区域授权")
            result = {
                paths[i]
                for i in ids
                if any(paths[i][: len(parent)] == parent for parent in result)
            }
        return result

    manager = branches(user.get("facilityScope", {}))

    def contains(account):
        try:
            candidate = branches(resolver(db, account) if resolver else {})
        except PermissionError:
            return False
        return all(
            any(path[: len(parent)] == parent for parent in manager)
            for path in candidate
        )

    return contains


@contextmanager
def verify_change(db, check, read_target):
    """A policy provider can use the new, persisted account to look up its assignment."""
    if check is None:
        yield
        return
    db.execute("SAVEPOINT staff_scope_change")
    try:
        yield
        if not check(read_target()):
            raise PermissionError("该员工的区域超出本人可管理的范围")
    except BaseException:
        db.execute("ROLLBACK TO staff_scope_change")
        raise
    finally:
        db.execute("RELEASE staff_scope_change")
