"""Owner-controlled downloads from a pinned, signed institution release feed."""

from base64 import b64decode
from contextlib import closing
from datetime import datetime
from hashlib import sha256
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from zoneinfo import ZoneInfo

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from . import history, secure_storage
from .backups import audit, process_lock, require_owner


MAX_ARCHIVE = 256 * 1024 * 1024
CHUNK = 128 * 1024
MAX_MANIFEST = 16 * 1024
BASE_VERSION = "0.2.0"
LOCAL = ZoneInfo("Asia/Shanghai")
SERVICE = {"id": "platform-operator", "username": "platform-operator", "displayName": "平台更新服务", "role": "system"}
ACTION = "update.settings"


class UpdateError(ValueError):
    """An update, configuration or verification step did not complete."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        raise UpdateError("更新源重定向不受支持，请核对下载域名")


def parse_version(version):
    if not isinstance(version, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,5})(?:\.(?:0|[1-9][0-9]{0,5})){2}", version):
        raise UpdateError("更新版本号无效")
    return tuple(int(part) for part in version.split("."))


def installed_version():
    version = os.environ.get("NH_RELEASE_VERSION", BASE_VERSION)
    parse_version(version)
    return version


def strict_json(raw):
    def unique_pairs(pairs):
        obj = dict(pairs)
        if len(obj) != len(pairs):
            raise UpdateError("更新记录包含重复字段")
        return obj

    try:
        return json.loads(raw, object_pairs_hook=unique_pairs)
    except (TypeError, UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise UpdateError("更新记录的 JSON 格式无效") from error


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def atomic_json(path, value):
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=path.parent) as folder:
        tmp = Path(folder) / "record"
        with secure_storage.private_file(tmp) as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        secure_storage.sync_dir(path.parent)


def read_json(path):
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_MANIFEST + 1)
    except FileNotFoundError:
        return None
    if len(raw) > MAX_MANIFEST:
        raise UpdateError("更新记录超过大小限制")
    return strict_json(raw)


def normalized_origin(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise UpdateError("请为更新服务配置无凭据的 HTTPS 地址")
    return parsed.hostname, parsed.port or 443


class ReleaseSource:
    def __init__(self, url=None, keyfile=None, *, transport=None):
        self.url = url if url is not None else os.environ.get("NH_UPDATE_MANIFEST_URL", "")
        self.keyfile = keyfile if keyfile is not None else os.environ.get("NH_UPDATE_PUBLIC_KEY_FILE", "")
        self.transport = transport or build_opener(ProxyHandler({}), NoRedirect()).open

    @property
    def configured(self):
        return bool(self.url and self.keyfile)

    def verify(self, envelope):
        if not self.configured:
            raise UpdateError("机构更新源与发布公钥尚未配置")
        origin = normalized_origin(self.url)
        if not isinstance(envelope, dict) or envelope.keys() != {"release", "signature"}:
            raise UpdateError("更新清单格式无效")
        release = envelope["release"]
        if not isinstance(release, dict) or release.keys() != {
            "product", "format", "version", "artifact", "size", "sha256", "notes",
        }:
            raise UpdateError("更新清单字段无效")
        if release["product"] != "ankang-platform" or type(release["format"]) is not int or release["format"] != 1:
            raise UpdateError("更新包不适用于本平台")
        parse_version(release["version"])
        if (
            not isinstance(release["artifact"], str)
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,120}\.zip", release["artifact"])
            or type(release["size"]) is not int
            or not 1 <= release["size"] <= MAX_ARCHIVE
            or not isinstance(release["sha256"], str)
            or not re.fullmatch("[a-f0-9]{64}", release["sha256"])
            or not isinstance(release["notes"], str)
            or len(release["notes"]) > 1400
            or not isinstance(envelope["signature"], str)
            or len(envelope["signature"]) != 88
        ):
            raise UpdateError("更新包的文件、摘要或发布说明无效")
        if normalized_origin(urljoin(self.url, release["artifact"])) != origin:
            raise UpdateError("更新包必须来自配置的同一发布源")
        try:
            with Path(self.keyfile).open("rb") as stream:
                public_key = load_pem_public_key(stream.read(8192))
            if not isinstance(public_key, Ed25519PublicKey):
                raise UpdateError("发布公钥须为 Ed25519")
            public_key.verify(b64decode(envelope["signature"], validate=True), canonical(release))
        except InvalidSignature:
            raise UpdateError("更新清单签名验证失败") from None
        except (OSError, ValueError) as error:
            raise UpdateError("发布公钥或签名格式无效") from error
        return release

    def request(self, url, *, timeout):
        if not self.configured:
            raise UpdateError("机构更新源与发布公钥尚未配置")
        normalized_origin(url)
        try:
            return self.transport(Request(url, headers={"User-Agent": "ElderlyCare-Platform-Updates"}), timeout=timeout)
        except (URLError, OSError) as error:
            raise UpdateError("访问机构更新源失败，请核对网络与发布配置") from error

    def discover(self):
        try:
            with self.request(self.url, timeout=8) as response:
                raw = response.read(MAX_MANIFEST + 1)
        except (OSError, HTTPException) as error:
            raise UpdateError("未能完整读取更新清单") from error
        if len(raw) > MAX_MANIFEST:
            raise UpdateError("更新清单超过大小限制")
        envelope = strict_json(raw)
        self.verify(envelope)
        return envelope

    def download(self, envelope, destination):
        release = self.verify(envelope)
        deadline = time.monotonic() + 180
        size, digest = 0, sha256()
        with tempfile.TemporaryDirectory(prefix=".download-", dir=destination.parent) as folder:
            tmp = Path(folder) / "archive"
            with (
                self.request(urljoin(self.url, release["artifact"]), timeout=15) as response,
                secure_storage.private_file(tmp) as out,
            ):
                try:
                    while chunk := response.read(CHUNK):
                        size += len(chunk)
                        if size > release["size"] or time.monotonic() > deadline:
                            raise UpdateError("更新包大小或下载耗时超过限制")
                        digest.update(chunk)
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                except (OSError, HTTPException) as error:
                    raise UpdateError("更新包未完整下载，或本机写入失败") from error
            if size != release["size"] or digest.hexdigest() != release["sha256"]:
                raise UpdateError("下载包的文件长度或摘要校验失败")
            os.replace(tmp, destination)
            secure_storage.sync_dir(destination.parent)


def update_directory(database):
    folder = database.with_name(database.name + ".updates")
    folder.mkdir(mode=0o700, exist_ok=True)
    if folder.is_symlink() or not folder.is_dir():
        raise UpdateError("本机更新目录无效")
    return folder


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS update_policy(
        id INTEGER PRIMARY KEY CHECK(id=1), automatic INTEGER NOT NULL, hour INTEGER NOT NULL)""")
    db.execute("INSERT OR IGNORE INTO update_policy VALUES(1,0,2)")


def policy(db):
    row = db.execute("SELECT automatic,hour FROM update_policy WHERE id=1").fetchone()
    return {"automatic": bool(row["automatic"]), "hour": row["hour"]}


class UpdateService:
    def __init__(self, store, source=None, *, version=None, managed=None):
        self.store = store
        self.source = source or ReleaseSource()
        self.version = version or installed_version()
        self.managed = (os.environ.get("NH_UPDATE_MANAGED") == "1") if managed is None else managed
        self.folder = update_directory(store.path)
        self.offer = self.folder / "offer.json"
        self.staged = self.folder / "staged.json"
        self.pending = self.folder / "pending.json"
        self.outcome = self.folder / "outcome.json"
        self.auto = self.folder / "auto.json"

    def archive(self, version):
        parse_version(version)
        return self.folder / ("application-" + version + ".zip")

    def authorized(self, token):
        with closing(self.store.connect()) as db:
            return require_owner(self.store, db, token)

    def status(self, token):
        with closing(self.store.connect()) as db:
            require_owner(self.store, db, token)
            settings = policy(db)
        offer = read_json(self.offer)
        staged = read_json(self.staged)
        pending = read_json(self.pending)
        available = offer["release"] if offer else {}
        if available and parse_version(available["version"]) <= parse_version(self.version):
            available = {}
        return {
            "installedVersion": self.version,
            "configured": self.source.configured,
            "managed": self.managed,
            "settings": settings,
            "available": {key: available[key] for key in ("version", "size", "notes")} if available else None,
            "stagedVersion": staged["release"]["version"] if staged else None,
            "pendingVersion": pending["version"] if pending else None,
            "outcome": read_json(self.outcome),
        }

    def configure(self, token, fields):
        if (
            set(fields) != {"automatic", "hour"}
            or type(fields["automatic"]) is not bool
            or type(fields["hour"]) is not int
            or not 0 <= fields["hour"] <= 23
        ):
            raise UpdateError("请选择有效的自动更新时间")
        if fields["automatic"] and not (self.source.configured and self.managed):
            raise UpdateError("配置签名更新源并使用托管启动器后可启用自动更新")
        with closing(self.store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            actor = require_owner(self.store, db, token)
            if policy(db) != fields:
                history.watch(db, ACTION)
                db.execute("UPDATE update_policy SET automatic=?,hour=? WHERE id=1", (int(fields["automatic"]), fields["hour"]))
                description = f"设置每日 {fields['hour']:02d}:00 检查并安装更新" if fields["automatic"] else "关闭自动更新"
                audit(db, self.store, actor, ACTION, description)
        return self.status(token)

    def _check(self):
        envelope = self.source.discover()
        atomic_json(self.offer, envelope)
        return envelope["release"]["version"]

    def check(self, token):
        self.authorized(token)
        with process_lock(self.folder, "release-download") as locked:
            if not locked:
                raise UpdateError("更新服务正在处理，请稍后再试")
            self._check()
        return self.status(token)

    def _offer(self, version):
        parse_version(version)
        if parse_version(version) <= parse_version(self.version):
            raise UpdateError("只可下载较新的正式版本")
        envelope = read_json(self.offer)
        if not envelope:
            raise UpdateError("请先检查可用的更新")
        release = self.source.verify(envelope)
        if release["version"] != version:
            raise UpdateError("更新清单已有变动，请重新检查")
        return envelope

    def _download(self, version):
        if self.pending.exists():
            raise UpdateError("更新安装正在准备，请稍候")
        envelope = self._offer(version)
        before = read_json(self.staged)
        self.source.download(envelope, self.archive(version))
        atomic_json(self.staged, envelope)
        if before and before["release"]["version"] != version:
            self.archive(before["release"]["version"]).unlink(missing_ok=True)

    def download(self, token, version):
        self.authorized(token)
        with process_lock(self.folder, "release-download") as locked:
            if not locked:
                raise UpdateError("更新服务正在处理，请稍后再试")
            self._download(version)
        return self.status(token)

    def _queue(self, version, actor):
        if not self.managed:
            raise UpdateError("请改用机构更新托管启动器后安装")
        parse_version(version)
        if parse_version(version) <= parse_version(self.version):
            raise UpdateError("只可安装较新的正式版本")
        envelope = read_json(self.staged)
        if not envelope or self.source.verify(envelope)["version"] != version or not self.archive(version).is_file():
            raise UpdateError("请先下载并校验此版本")
        pending = read_json(self.pending)
        if pending:
            if pending["version"] != version:
                raise UpdateError("其他版本正在等待安装")
            return
        atomic_json(self.pending, {"version": version, "actor": actor["id"], "requested": int(time.time())})

    def queue(self, token, version):
        actor = self.authorized(token)
        with process_lock(self.folder, "release-download") as locked:
            if not locked:
                raise UpdateError("更新服务正在处理，请稍后再试")
            self._queue(version, actor)
        return self.status(token)

    def automatic(self, now=None):
        if not (self.managed and self.source.configured):
            return
        moment = (now or datetime.now(LOCAL)).astimezone(LOCAL)
        today = moment.date().isoformat()
        with closing(self.store.connect()) as db:
            settings = policy(db)
        if not settings["automatic"] or moment.hour != settings["hour"]:
            return
        with process_lock(self.folder, "release-download") as locked:
            if not locked or self.pending.exists() or read_json(self.auto) == {"day": today}:
                return
            atomic_json(self.auto, {"day": today})
            try:
                version = self._check()
                if parse_version(version) > parse_version(self.version):
                    self._download(version)
                    self._queue(version, SERVICE)
            except (OSError, UpdateError) as error:
                message = str(error) if isinstance(error, UpdateError) else "无法写入本机更新目录"
                atomic_json(self.outcome, {"state": "failed", "message": message, "at": int(time.time())})
