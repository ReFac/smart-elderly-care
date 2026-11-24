"""Operate the mandatory snapshot clock and recover a cloud copy without a working database."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
from platform_core.backups import cloud
from platform_core.store import Store

ROOT = Path(__file__).resolve().parent


def run_due(db_path):
    if not db_path.is_file():
        raise ValueError("未找到机构工作库")
    store = Store(db_path)
    while store.backups.capture(wait=True):
        pass

    def sync(provider):
        while store.backups.deliver(provider):
            pass

    with ThreadPoolExecutor(max_workers=len(cloud.PROVIDERS)) as pool:
        list(pool.map(sync, cloud.PROVIDERS))
    with closing(store.connect()) as db:
        point = db.execute(
            "SELECT state FROM backup_points WHERE owner='' ORDER BY created DESC,rowid DESC LIMIT 1"
        ).fetchone()
        if not point or point[0] != "ready":
            raise ValueError("本期本机快照尚未成功")
        if not db.execute("SELECT 1 FROM backup_locations LIMIT 1").fetchone():
            print("本机完整快照已保存。当前尚无已授权的异地副本位置。")
        if db.execute("""SELECT 1 FROM backup_deliveries d JOIN backup_locations l
            ON d.provider=l.provider AND d.signature=l.signature WHERE d.state='failed' LIMIT 1""").fetchone():
            raise ValueError("本机快照已保存，另有异地副本未完成校验")


def unit_arg(path):
    string = str(path)
    if any(ord(c) < 32 for c in string):
        raise ValueError("服务路径无效")
    return (
        '"'
        + string.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("%", "%%")
        .replace("$", "$$")
        + '"'
    )


def install_timer(db_path, environment=None):
    if not db_path.is_file():
        raise ValueError("请选择现有工作库")
    config = (
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        / "systemd/user"
    )
    config.mkdir(parents=True, exist_ok=True)
    env_line = (
        "EnvironmentFile=" + unit_arg(environment.resolve()) + "\n"
        if environment
        else ""
    )
    exe = unit_arg(Path(sys.executable).absolute())
    ident = sha256(str(db_path.resolve()).encode()).hexdigest()[:12]
    name = "ankang-backup-" + ident
    spec = {
        "service": "[Unit]\nDescription=Encrypted elderly care snapshots\n[Service]\nType=oneshot\nUMask=0077\n"
        + env_line
        + "ExecStart="
        + exe
        + " "
        + unit_arg(ROOT / "manage_backups.py")
        + " --db "
        + unit_arg(db_path.resolve())
        + " run-due\n",
        "timer": "[Unit]\nDescription=Daily elderly care backup schedule\n[Timer]\nOnCalendar=*-*-* 00:00:00 Asia/Shanghai\nOnStartupSec=2min\nOnUnitInactiveSec=15min\nAccuracySec=1s\nPersistent=true\n[Install]\nWantedBy=timers.target\n",
    }
    for suffix, content in spec.items():
        file = config / (name + "." + suffix)
        if not file.exists() or file.read_text() != content:
            file.write_text(content)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", name + ".timer"], check=True
    )
    print(name + ".timer")


def main():
    p = argparse.ArgumentParser(description="医养管理平台加密快照与异地恢复")
    p.add_argument("--db", type=Path, default=ROOT / ".local/workspace.sqlite3")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("run-due", help="补做本期完整快照并重试异地队列")
    timer = sub.add_parser("install-timer", help="为当前 Linux 用户安装持续的定时任务")
    timer.add_argument("--environment-file", type=Path)
    for key in ("list-cloud", "download"):
        c = sub.add_parser(key)
        c.add_argument("provider", choices=cloud.PROVIDERS)
        if key == "download":
            c.add_argument("object")
            c.add_argument("destination", type=Path)
    args = p.parse_args()
    if args.action == "run-due":
        run_due(args.db)
    elif args.action == "install-timer":
        install_timer(args.db, args.environment_file)
    else:
        remote = cloud.locations().get(args.provider)
        if not remote:
            raise ValueError("该异地位置尚未配置授权")
        if args.action == "list-cloud":
            print(json.dumps(cloud.list_files(remote), ensure_ascii=False, indent=2))
        else:
            cloud.download(remote, args.object, args.destination)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
