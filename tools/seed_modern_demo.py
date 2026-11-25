"""Create a complete demonstration or enrich an existing demonstration in place."""

from contextlib import closing
import argparse
from contextlib import closing
from getpass import getpass
import os
from pathlib import Path

from platform_core import secure_storage
from platform_core.sample import populate
from platform_core.store import Store


def main():
    parser = argparse.ArgumentParser(description="建立或补充医养平台虚构演示场景")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--enrich-existing-demo", action="store_true", help="保留已有演示数据，补齐业务场景")
    args = parser.parse_args()
    if args.db.exists() != args.enrich_existing_demo:
        parser.error("新建演示库请选择新文件，补充既有演示库需指定 --enrich-existing-demo")
    if args.enrich_existing_demo:
        if not args.db.is_file() or not args.db.stat().st_size:
            parser.error("请选择已初始化的机构资料库")
        key = secure_storage.read_key(secure_storage.key_location(args.db))
        with closing(secure_storage.open_database(args.db, key)) as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workspace'").fetchone() or not db.execute(
                    "SELECT 1 FROM workspace WHERE id=1").fetchone():
                parser.error("文件中未找到已初始化的机构工作区")
    password = os.environ.get("NH_OWNER_PASSWORD") or getpass("演示库 Owner 密码：")
    store = Store(args.db, initial_data="demo", initial_owner_password=password)
    with closing(store.connect()) as db:
        username = db.execute("SELECT username FROM accounts WHERE kind='owner'").fetchone()[0]
    token, _ = store.login(username, password)
    try:
        populate(store, token, adopt_legacy=args.enrich_existing_demo)
    finally:
        store.logout(token)
    print(f"演示库已就绪：{args.db}")


if __name__ == "__main__":
    main()
