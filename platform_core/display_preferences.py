"""Own-account display preferences. Local device overrides stay in the browser."""

import json
from contextlib import closing

OPTIONS = {
    "mode": ("light", "dark", "system"),
    "family": ("system", "sans", "serif"),
    "density": ("comfortable", "compact"),
    "motion": ("system", "reduced"),
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS account_display_preferences (
        account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
        version INTEGER NOT NULL, settings TEXT NOT NULL)""")


def read(db, actor):
    row = db.execute("SELECT version,settings FROM account_display_preferences WHERE account_id=?",
                     (actor["id"],)).fetchone()
    return {"version": row[0], "values": json.loads(row[1])} if row else {"version": 0, "values": None}


def settings(store, token, body=None):
    from .store import Conflict

    with closing(store.connect()) as db, db:
        if body is not None:
            db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        current = read(db, actor)
        if body is None:
            return {**current, "accountId": actor["id"]}
        if (not isinstance(body, dict) or set(body) != {"version", "values", "expectedAccount"}
                or type(body["version"]) is not int or body["version"] < 0):
            raise ValueError("显示设置版本无效")
        if body["expectedAccount"] != actor["id"]:
            raise Conflict("登录账号已切换，请重新打开个人中心")
        values = body["values"]
        if (not isinstance(values, dict) or set(values) != {*OPTIONS, "level"}
                or type(values["level"]) is not int or not 1 <= values["level"] <= 10
                or any(values[key] not in options for key, options in OPTIONS.items())):
            raise ValueError("请选择有效的主题、字号、字体、界面密度和动效")
        if values == current["values"]:
            return current
        if body["version"] != current["version"]:
            raise Conflict("另一台设备已更新显示设置，请重新载入后再保存")
        version = current["version"] + 1
        db.execute("""INSERT INTO account_display_preferences(account_id,version,settings) VALUES(?,?,?)
                      ON CONFLICT(account_id) DO UPDATE SET version=excluded.version,settings=excluded.settings""",
                   (actor["id"], version, json.dumps(values, separators=(",", ":"))))
        return {"version": version, "values": values}
