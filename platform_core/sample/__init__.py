"""Explicit, versioned onboarding for a fictional demonstration institution."""

from contextlib import closing
import json

from ..backups import process_lock

VERSION = 1


def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS workspace_installation(
        id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL CHECK(mode IN ('demo','empty')),
        sample_version INTEGER NOT NULL DEFAULT 0)""")


def ready(db):
    return bool(db.execute(
        "SELECT 1 FROM workspace_installation WHERE id=1 AND mode='demo' AND sample_version>=1"
    ).fetchone())


def project(db, data, user):
    if user["kind"] not in ("owner", "staff") or not ready(db):
        return
    data["demoGuide"] = True
    visible = {r["id"] for r in data.get("medicalVisits", ())}
    if visible:
        data["demoVisitIds"] = [rid for (rid,) in db.execute(
            "SELECT id FROM dossier_visit_drafts WHERE request LIKE 'demo-medical-v1-%'"
        ) if rid in visible]


def pending(store):
    with closing(store.connect()) as db:
        return bool(db.execute("SELECT 1 FROM workspace_installation WHERE id=1 AND mode='demo' AND sample_version>=0 AND sample_version<?",
                               (VERSION,)).fetchone())


def _legacy_sample(db):
    state = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
    people = {(r["id"], r["name"]) for r in state.get("residents", ())}
    stock = {(r["id"], r["name"]) for r in state.get("inventory", ())}
    return ({("r001", "沈月兰"), ("r002", "徐松年"), ("r003", "梁秋萍")} <= people and
            {("stock-1", "医用检查手套"), ("stock-2", "成人护理垫")} <= stock and
            any(m["residentId"] == "r001" and m["bedId"] == "b001" and m["kind"] == "入住"
                for m in state.get("bedMoves", ())))


def populate(store, token, *, adopt_legacy=False):
    """Resume an interrupted setup. An unmarked historical demo needs an explicit Owner upgrade."""
    from . import facility, medical, scenarios

    with process_lock(store.backups.folder, "sample-setup", wait=True) as locked:
        if not locked:
            raise RuntimeError("演示资料正在初始化，请稍后重试")
        with closing(store.connect()) as db, db:
            if store.actor(db, token)["kind"] != "owner":
                raise PermissionError("仅 Owner 可以初始化演示机构")
            record = db.execute("SELECT mode,sample_version FROM workspace_installation WHERE id=1").fetchone()
            if record is None:
                if not adopt_legacy or not _legacy_sample(db):
                    raise ValueError("资料库缺少可核验的虚构演示样本")
                db.execute("INSERT INTO workspace_installation(id,mode) VALUES(1,'demo')")
            elif record["mode"] != "demo":
                raise ValueError("这是空白机构模式创建的资料库，请另建演示库")
            elif record["sample_version"] >= VERSION:
                return False
            elif record["sample_version"] < 0:
                db.execute("UPDATE workspace_installation SET sample_version=0 WHERE id=1")

        def command(action, **payload):
            return store.execute(action, payload, store.version(token)["revision"], token, comment="载入虚构业务演示")

        facility.structure(store, token, command)
        facility.schedules(store, token, command)
        scenarios.seed_scenarios(store, token)
        medical.seed_medical(store, token)
        with closing(store.connect()) as db, db:
            db.execute("UPDATE workspace_installation SET sample_version=? WHERE id=1", (VERSION,))
        return True
