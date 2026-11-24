"""Platform operator commands for the separately purchased Agent service entitlement."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

from platform_core import activity, provider


def main():
    parser = argparse.ArgumentParser(description="安康医养平台 · 平台运营方套餐管理")
    parser.add_argument(
        "--db", type=Path, required=True, help="该机构的现有工作区数据库"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser("grant", help="核实付款后发放或调整本期额度")
    grant.add_argument("--name", required=True)
    grant.add_argument("--tokens", required=True, type=int)
    grant.add_argument(
        "--expires", required=True, help="到期日 YYYY-MM-DD（上海时区，含当日）"
    )
    commands.add_parser("status", help="查看套餐与用量")
    commands.add_parser("disable", help="停止接受新的付费规划")
    commands.add_parser("unsettled", help="查看待结算或结果未明的记录")
    reconcile = commands.add_parser(
        "reconcile", help="按供应商对账结果结算一笔不明用量"
    )
    reconcile.add_argument("--actor", required=True)
    reconcile.add_argument("--request", required=True)
    reconcile.add_argument("--tokens", type=int, required=True)
    args = parser.parse_args()
    try:
        with (
            closing(
                sqlite3.connect(
                    args.db.resolve().as_uri() + "?mode=rw", uri=True, timeout=8
                )
            ) as db,
            db,
        ):
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace'"
            ).fetchone():
                raise ValueError("请选择实际机构工作区数据库")
            provider.init(db)
            change = None
            if args.command == "grant":
                provider.grant(db, args.name, args.tokens, args.expires)
                change = f"调整套餐 {args.name}，本期额度 {args.tokens} token，有效至 {args.expires}"
            elif args.command == "disable":
                provider.disable(db)
                change = "停用云端规划套餐"
            elif args.command == "reconcile":
                provider.reconcile(db, args.actor, args.request, args.tokens)
                change = f"完成单笔云端用量对账，结算 {args.tokens} token"
            if change:
                activity.init(db)
                db.execute("UPDATE workspace SET revision=revision+1 WHERE id=1")
                revision = db.execute(
                    "SELECT revision FROM workspace WHERE id=1"
                ).fetchone()[0]
                operator = {
                    "id": "platform-operator",
                    "username": "platform-operator",
                    "displayName": "平台运营方",
                }
                activity.write(
                    db,
                    revision,
                    provider.local_time().isoformat(timespec="seconds"),
                    "platform.plan." + args.command,
                    change,
                    operator,
                    {},
                    {},
                )
            if args.command == "unsettled":
                entries = db.execute("""SELECT planId,actor,request,model,status,allowance,createdAt FROM api_usage
                    WHERE status IN ('pending','uncertain') ORDER BY createdAt""")
                result = [dict(r) for r in entries]
            else:
                result = provider.status(
                    db,
                    {"id": "platform-operator", "kind": "owner"},
                    provider.local_time(),
                )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, sqlite3.Error, OSError) as err:
        print(str(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
