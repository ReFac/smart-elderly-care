"""Host operator entry points for offline migration, recovery, and encrypted originals."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sys

from platform_core import secure_storage as vault, storage_assets
from platform_core.store import Store


def seal_legacy_bootstrap(db, path):
    from platform_core.access import _digest
    import hmac
    import stat

    old = path.parent / ".owner-password"
    if not old.exists():
        return "absent"
    fd = os.open(
        old, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    )
    with os.fdopen(fd, "rb") as secret:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or (
            os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077)
        ):
            raise ValueError("旧首次凭据文件权限不符，已保留原件")
        password = secret.read(1024).decode().strip()
        row = db.execute(
            "SELECT salt,password_hash FROM accounts WHERE kind='owner'"
        ).fetchone()
        if not row or not hmac.compare_digest(
            _digest(password, row["salt"]), row["password_hash"]
        ):
            return "unmatched_existing_file"
        with db:
            db.execute(
                "INSERT OR REPLACE INTO storage_bootstrap VALUES(1,?)", (password,)
            )
        if not os.path.samestat(info, old.lstat()):
            raise ValueError("旧凭据文件已变化")
        old.unlink()
        vault.sync_dir(old.parent)
        return "sealed"


def main():
    parser = argparse.ArgumentParser(description="机构加密存储与恢复")
    parser.add_argument(
        "--db", required=True, type=Path, help="工作库路径；恢复时为全新的目标路径"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("migrate", help="停止旧服务后，把原工作库转换为加密存储")
    commands.add_parser("verify", help="完整核验加密页面和业务库结构")
    commands.add_parser(
        "owner-password", help="在本机终端查看尚未更改的系统首次生成凭据"
    )
    snap = commands.add_parser("snapshot", help="创建完整的加密时间点快照")
    snap.add_argument("file", type=Path)
    restore = commands.add_parser("restore", help="从加密快照恢复到新路径")
    restore.add_argument("file", type=Path)
    restore.add_argument("--recovery-key-file", required=True, type=Path)
    wrap = commands.add_parser("wrap-key", help="用交互口令封装离线恢复材料")
    wrap.add_argument("file", type=Path, help="新建的离线恢复材料路径")
    unwrap = commands.add_parser("unwrap-key", help="从离线材料恢复独立密钥文件")
    unwrap.add_argument("file", type=Path)
    unwrap.add_argument("--key-out", required=True, type=Path)
    for command in ("import-file", "export-file", "import-tour"):
        part = commands.add_parser(command)
        part.add_argument("name", help="院内保存的相对名称")
        part.add_argument("file", type=Path, help="导入源文件或全新的导出路径")
    args = parser.parse_args()
    dbpath = args.db.absolute()
    if args.command in ("wrap-key", "unwrap-key"):
        from getpass import getpass

        if not sys.stdin.isatty():
            raise ValueError("请在本机交互终端输入恢复口令")
        password = getpass("离线恢复口令：")
        if args.command == "wrap-key":
            if password != getpass("再次输入恢复口令："):
                raise ValueError("两次口令不一致")
            result = vault.wrap_recovery_key(
                vault.key_location(dbpath), args.file, password
            )
        else:
            result = vault.unwrap_recovery_key(args.file, args.key_out, password)
    elif args.command == "restore":
        result = vault.restore_snapshot(args.file, dbpath, args.recovery_key_file)
    else:
        if not dbpath.is_file():
            raise FileNotFoundError("未找到工作库")
        if args.command == "migrate":
            vault.migrate_database(dbpath)
        store = Store(dbpath)
        if args.command == "snapshot":
            result = vault.create_snapshot(store, args.file)
        else:
            with closing(store.connect()) as db:
                if args.command == "migrate":
                    result = {
                        **vault.verify(db),
                        "initialPassword": seal_legacy_bootstrap(db, dbpath),
                    }
                elif args.command == "verify":
                    result = vault.verify(db)
                elif args.command == "owner-password":
                    if not sys.stdout.isatty():
                        raise ValueError("请直接在本机交互终端查看首次凭据")
                    row = db.execute(
                        "SELECT password FROM storage_bootstrap WHERE id=1"
                    ).fetchone()
                    if not row:
                        raise ValueError("已更改首次密码或初始化时已由部署方指定")
                    print(row[0])
                    return
                else:
                    with db:
                        if args.command == "export-file":
                            db.execute("BEGIN")
                            result = storage_assets.export_asset(
                                db, "archive", args.name, args.file
                            )
                        else:
                            db.execute("BEGIN IMMEDIATE")
                            result = storage_assets.import_asset(
                                db,
                                "tour" if args.command == "import-tour" else "archive",
                                args.name,
                                args.file,
                            )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, vault.cipherdb.Error) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
