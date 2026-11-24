"""Provision deployment credentials without including them in an institution database."""

import argparse
from contextlib import closing
from getpass import getpass
import hmac
from pathlib import Path
import sys

from platform_core import operational_secrets as secrets, secure_storage


def main():
    parser = argparse.ArgumentParser(description="平台独立运维密库")
    parser.add_argument("--vault", type=Path, default=secrets.vault_path())
    commands = parser.add_subparsers(dest="command", required=True)
    part = commands.add_parser("import-file", help="加密封存指定的运维文件")
    part.add_argument("name")
    part.add_argument("source", type=Path)
    part.add_argument(
        "--remove-source", action="store_true", help="逐字节核验后移除旧原件"
    )
    part.add_argument("--replace", action="store_true", help="明确替换同编号当前凭据")
    commands.add_parser("set-deepseek", help="通过本机交互终端安全录入供应商凭据")
    verify = commands.add_parser("verify", help="检查加密页面、运维库和指定记录")
    verify.add_argument("name")
    wrap = commands.add_parser(
        "wrap-key", help="为运维主密钥输出受恢复口令保护的离线材料"
    )
    wrap.add_argument("file", type=Path)
    unwrap = commands.add_parser("unwrap-key", help="在新路径恢复平台运维主密钥")
    unwrap.add_argument("file", type=Path)
    unwrap.add_argument("--key-out", type=Path, required=True)
    args = parser.parse_args()
    if args.command in ("wrap-key", "unwrap-key"):
        if not sys.stdin.isatty():
            raise ValueError("请通过本机交互终端输入恢复口令")
        password = getpass("运维密库离线恢复口令：")
        if args.command == "wrap-key":
            if password != getpass("再次输入恢复口令："):
                raise ValueError("输入不一致")
            secure_storage.wrap_recovery_key(
                secrets.key_file(args.vault), args.file, password
            )
        else:
            secure_storage.unwrap_recovery_key(args.file, args.key_out, password)
    elif args.command == "import-file":
        secrets.import_file(
            args.vault, args.name, args.source, args.remove_source, args.replace
        )
    elif args.command == "set-deepseek":
        if not sys.stdin.isatty():
            raise ValueError("请在本机交互终端输入凭据")
        value = getpass("请输入平台 DeepSeek 凭据：").strip()
        if not hmac.compare_digest(
            value.encode(), getpass("再次输入凭据：").strip().encode()
        ):
            raise ValueError("输入不一致")
        secrets.save(args.vault, "deepseek", value.encode(), replace=True)
    else:
        with closing(secrets.connect(args.vault)) as db:
            if (
                db.execute("PRAGMA cipher_integrity_check").fetchone() is not None
                or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            ):
                raise ValueError("运维密库完整性校验失败")
        secrets.read_value(args.vault, args.name)
    print("运维记录已核验。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, secure_storage.cipherdb.Error) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
