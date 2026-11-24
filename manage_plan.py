"""Platform operator commands for the separately purchased Agent service entitlement."""

import argparse
from contextlib import closing
import json
from pathlib import Path
from platform_core import secure_storage
import sys

from platform_core import activity, provider
from platform_core.provider import media, search_usage


def main():
    parser = argparse.ArgumentParser(description="安康医养平台 · 平台运营方套餐管理")
    parser.add_argument(
        "--db", type=Path, required=True, help="该机构的现有工作区数据库"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    grant = commands.add_parser("grant", help="核实付款后发放或调整本期额度")
    grant.add_argument("--name", required=True)
    grant.add_argument("--ocr-pages", type=int, help="本期识别照片页数")
    grant.add_argument("--asr-seconds", type=int, help="本期语音识别秒数")
    grant.add_argument("--tokens", required=True, type=int)
    grant.add_argument(
        "--expires", required=True, help="到期日 YYYY-MM-DD（上海时区，含当日）"
    )
    commands.add_parser("status", help="查看套餐与用量")
    commands.add_parser("disable", help="停止接受新的付费规划")
    commands.add_parser("unsettled", help="查看待结算或结果未明的记录")
    reconcile = commands.add_parser(
        "reconcile", help="按供应商账单输入一笔请求的实际总用量，含迟到的回执"
    )
    reconcile.add_argument("--actor", required=True)
    reconcile.add_argument("--request", required=True)
    reconcile.add_argument("--tokens", type=int, required=True)
    commands.add_parser("media-unsettled", help="列出待核对的媒体用量")
    rec_media = commands.add_parser(
        "media-reconcile", help="按 DeepSeek 账单核实单笔页数或秒数"
    )
    rec_media.add_argument("--call", required=True)
    rec_media.add_argument("--units", type=int, required=True)
    commands.add_parser("search-unsettled", help="查看待核对的公开搜索请求")
    rec_search = commands.add_parser(
        "search-reconcile", help="按供应商账单核对单笔搜索"
    )
    rec_search.add_argument("--actor", required=True)
    rec_search.add_argument("--request", required=True)
    rec_search.add_argument("--calls", type=int, choices=(0, 1), required=True)
    args = parser.parse_args()
    try:
        with (
            closing(
                secure_storage.open_database(
                    args.db,
                    secure_storage.read_key(secure_storage.key_location(args.db)),
                )
            ) as db,
            db,
        ):
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            if not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace'"
            ).fetchone():
                raise ValueError("请选择实际机构工作区数据库")
            provider.init(db)
            from platform_core import history

            history.watch(db, "platform.plan")
            change = None
            if args.command == "search-reconcile":
                search_usage.reconcile(
                    db, args.actor, args.request, args.calls, provider.local_time()
                )
                change = f"核对公开搜索用量 {args.calls} 次"
            elif args.command == "grant":
                provider.grant(db, args.name, args.tokens, args.expires)
                for kind, limit in (("ocr", args.ocr_pages), ("asr", args.asr_seconds)):
                    if limit is not None:
                        media.grant(db, provider.latest(db)["id"], kind, limit)
                change = f"调整套餐 {args.name}，本期额度 {args.tokens} token，有效至 {args.expires}"
                if args.ocr_pages is not None:
                    change += f"，文书识别 {args.ocr_pages} 页"
                if args.asr_seconds is not None:
                    change += f"，语音转写 {args.asr_seconds} 秒"
            elif args.command == "media-reconcile":
                media.reconcile(db, args.call, args.units, provider.local_time())
                change = f"媒体识别用量对账 {args.call}，结算 {args.units} 单位"
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
            if args.command == "search-unsettled":
                result = search_usage.unsettled(db)
            elif args.command == "media-unsettled":
                result = [
                    dict(r)
                    for r in db.execute(
                        "SELECT id,kind,actor,at,reserved,state FROM media_usage WHERE state IN ('pending','uncertain') ORDER BY at"
                    )
                ]
            elif args.command == "unsettled":
                result = provider.unsettled(db)
            else:
                result = provider.status(
                    db,
                    {"id": "platform-operator", "kind": "owner"},
                    provider.local_time(),
                )
            print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, secure_storage.cipherdb.Error, OSError) as err:
        print(str(err), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
