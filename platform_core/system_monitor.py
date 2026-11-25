"""Read-only institution operations telemetry. Session identifiers stay on the server."""
from collections import OrderedDict
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time


class Presence:
    def __init__(self):
        self._active = OrderedDict()
        self._lock = threading.Lock()

    def touch(self, digest):
        now = int(time.time())
        with self._lock:
            self._active[digest] = now
            self._active.move_to_end(digest)
            while self._active and (len(self._active) > 4096 or next(iter(self._active.values())) < now - 300):
                self._active.popitem(last=False)

    def recent(self):
        cutoff = int(time.time()) - 300
        with self._lock:
            return {key: at for key, at in self._active.items() if at >= cutoff}


def _caches():
    from . import drug_catalog, hospital_catalog, profile_fields
    namespaces = (
        ("hospital_catalog", "全国医院检索目录", hospital_catalog.entries),
        ("drug_names", "药名标准化索引", drug_catalog._key),
        ("profile_choices", "档案选项目录", profile_fields.catalog),
    )
    rows = []
    for name, label, function in namespaces:
        stat = function.cache_info()
        rows.append(dict(name=name, label=label, entries=stat.currsize, limit=stat.maxsize,
                         hits=stat.hits, misses=stat.misses))
    return rows


def _timestamp(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")


def inspect(store, token, view, http_server):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        actor = store.actor(db, token)
        if actor["kind"] != "owner" or "settings" not in actor["routes"]:
            raise PermissionError("仅 Owner 可查看机构运行监控")
        stamp = store.now().isoformat(timespec="seconds")
        if view == "onlineUsers":
            beats = store.presence.recent()
            accounts = {}
            for key, uid, login, name, role in db.execute(
                """SELECT s.token_hash,a.id,a.username,a.display_name,a.role FROM sessions s
                   JOIN accounts a ON a.id=s.account_id WHERE a.enabled=1 AND s.expires>?
                   AND s.token_hash IN (SELECT value FROM json_each(?))""",
                (int(time.time()), json.dumps(list(beats))),
            ):
                row = accounts.setdefault(uid,dict(login=login,name=name,role=role,sessions=0,lastSeen=0))
                row["sessions"] += 1
                row["lastSeen"] = max(row["lastSeen"],beats[key])
            rows = sorted(accounts.values(),key=lambda row: row["lastSeen"],reverse=True)
            for row in rows:
                row["lastSeen"] = _timestamp(row["lastSeen"])
        elif view == "timers":
            threads = {t.name for t in threading.enumerate() if t.is_alive()}
            rows = [{"name":label,"worker":worker,"active":worker in threads}
                    for worker,label in (("scheduled-work","定时工单派发"),("resident-rounds","长辈定时巡查"),
                                         ("snapshots","本机时间快照"),("platform-updates","平台自动更新检查"))]
            rules = db.execute("SELECT count(*) FROM scheduled_work_rules").fetchone()[0]
            recent = [dict(day=d,time=t,title=n,count=c,status=s) for d,t,n,c,s in db.execute(
                "SELECT day,time,title,count,status FROM scheduled_work_runs ORDER BY releasedAt DESC LIMIT 100")]
            return {"sampledAt":stamp,"rows":rows,"ruleCount":rules,"runs":recent}
        elif view == "dataMonitor":
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            pages = db.execute("PRAGMA page_count").fetchone()[0]
            free = db.execute("PRAGMA freelist_count").fetchone()[0]
            revision = db.execute("SELECT revision FROM workspace WHERE id=1").fetchone()[0]
            accounts = db.execute("SELECT count(*) FROM accounts").fetchone()[0]
            backups = db.execute("SELECT count(*) FROM backup_points").fetchone()[0]
            rows = [["业务数据版本",revision,"最近一次成功提交的版本号"],["账号总数",accounts,"机构账号目录"],
                    ["备份时间点",backups,"已登记的时间点，状态见备份与恢复"],
                    ["数据库页数",pages,"每页 " + str(page_size) + " 字节"],
                    ["可重用页数",free,"已分配且可复用的数据库页"]]
        elif view == "serviceMonitor":
            rows = [["HTTP 服务","运行中","当前请求已到达机构服务"],
                    ["存储服务","已连接","已完成本次只读数据库事务"],
                    ["服务线程",threading.active_count(),"本进程当前存活线程"]]
            if hasattr(http_server,"usage"):
                stat = http_server.usage()
                rows.extend([["在途连接",stat["active"],"连接并发上限 " + str(stat["limit"])],
                             ["连接并发峰值",stat["peak"],"本次进程启动以来"],
                             ["过载拒绝",stat["rejected"],"连接槽已满的请求数"]])
            try:
                rss = next(line.split()[1] for line in Path("/proc/self/status").read_text().splitlines() if line.startswith("VmRSS:"))
                rows.append(["进程常驻内存",f"{int(rss)/1024:.1f} MiB","Linux 进程当前 RSS"])
            except (OSError, StopIteration, ValueError):
                pass
            if hasattr(os,"getloadavg"):
                rows.append(["系统负载"," / ".join(f"{n:.2f}" for n in os.getloadavg()),"主机最近 1、5、15 分钟"])
        elif view in ("cacheMonitor","cacheList"):
            rows = _caches()
        else:
            raise ValueError("未知监控视图")
        return {"sampledAt":stamp,"rows":rows}
