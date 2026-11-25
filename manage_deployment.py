"""Initialize an empty institution and check its local deployment before starting the service."""
import argparse
from contextlib import closing
from getpass import getpass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from platform_core import deployment_language, secure_storage, updates
from platform_core.backups import process_lock
from platform_core.store import Store


def validate_origin(value):
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username is not None
            or url.password is not None or url.path not in ("", "/") or url.query or url.fragment):
        raise ValueError("请提供用于机构反向代理的 HTTPS 根地址")
    return value.rstrip("/")


def initialize(path, profile, language=None):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with process_lock(updates.update_directory(path), "running-server") as locked:
        if not locked or path.exists() or path.is_symlink():
            raise ValueError("该机构库已存在或正在使用，请改用 check")
        password = os.environ.get("NH_OWNER_PASSWORD")
        if not password:
            password = getpass("首次 Owner 密码 / Initial Owner password: ")
            if password != getpass("再次输入 / Repeat password: "):
                raise ValueError("两次密码不同")
        if not 14 <= len(password) <= 128:
            raise ValueError("正式部署初始密码应为 14 至 128 个字符")
        os.environ["NH_INSTITUTION_PROFILE"] = profile
        if language:
            os.environ["NH_DEPLOYMENT_LANGUAGE"] = language
        institution = Store(path, initial_data="empty", initial_owner_password=password)
    return {"initialized": True, "account": "owner", "profile": profile, "language": institution.deployment_language}


def check(path, profile, origin, *, full=False, language=None):
    public = validate_origin(origin)
    if not path.is_file() or path.is_symlink():
        raise ValueError("未找到有效机构库")
    key = secure_storage.read_key(secure_storage.key_location(path))
    with closing(secure_storage.open_database(path, key)) as db:
        db.execute("PRAGMA query_only=ON")
        if full:
            secure_storage.verify(db)
        mode = db.execute("SELECT mode FROM workspace_installation WHERE id=1").fetchone()
        if not mode or mode[0] != "empty":
            raise ValueError("正式环境须使用正式机构库")
        installed_language = db.execute("SELECT language FROM deployment_language WHERE id=1").fetchone()[0]
        if language and language != installed_language:
            raise ValueError("Configured language does not match this institution")
        owned = db.execute("SELECT count(*) FROM accounts WHERE kind='owner' AND enabled=1").fetchone()[0]
        if not owned:
            raise ValueError("请先启用机构 Owner")
        persisted = db.execute("SELECT 1 FROM clinical_archive_policy WHERE id=1").fetchone()
        if bool(persisted) != (profile == "licensed-medical"):
            raise ValueError("启动配置与机构库中的病案保全设置不一致")
        protected = db.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND lower(name) IN ('audit_no_update','audit_no_delete')").fetchone()[0]
        if protected != 2:
            raise ValueError("机构库需要先完成追加式审计台账迁移")
    return {"encryptedDatabase":"integrity-verified" if full else "opened", "installation":"empty-initialized", "profile":profile,
            "language":installed_language, "activeOwners":owned, "appendOnlyAuditTriggers":protected, "configuredOrigin":public}


def review(path, category, after, limit):
    """Local records-officer console. Access to the institution database and key is required."""
    if not path.is_file() or path.is_symlink() or after < 0 or not 1 <= limit <= 100:
        raise ValueError("Enter a valid institution, cursor and page size (1–100)")
    key = secure_storage.read_key(secure_storage.key_location(path))
    with closing(secure_storage.open_database(path, key)) as db:
        db.execute("PRAGMA query_only=ON")
        if category == "reads":
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='clinical_reads'").fetchone():
                raise ValueError("Clinical access receipts require a licensed-medical installation")
            query = "SELECT seq,at,actor,role,resource,status,peer FROM clinical_reads WHERE seq>? ORDER BY seq LIMIT ?"
        else:
            query = "SELECT rowid AS seq,resident,due_on FROM clinical_archive_reviews WHERE rowid>? ORDER BY rowid LIMIT ?"
        rows = [dict(row) for row in db.execute(query,(after,limit))]
        return {"entries": rows, "after": rows[-1]["seq"] if rows else after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init","check","review"])
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--profile", choices=["residential","licensed-medical"], default="licensed-medical")
    parser.add_argument("--public-origin", default=os.environ.get("NH_PUBLIC_ORIGIN"))
    parser.add_argument("--language", choices=tuple(deployment_language.locales()), default=os.environ.get("NH_DEPLOYMENT_LANGUAGE"), help="Set the institution language at initialization")
    parser.add_argument("--full", action="store_true", help="Check every encrypted database page")
    parser.add_argument("--category", choices=["retention","reads"], default="retention")
    parser.add_argument("--after", type=int, default=0)
    parser.add_argument("--limit", type=int, default=25)
    opt = parser.parse_args()
    try:
        if opt.action == "init":
            result = initialize(opt.db.absolute(), opt.profile, opt.language)
        elif opt.action == "review":
            result = review(opt.db.absolute(), opt.category, opt.after, opt.limit)
        elif not opt.public_origin:
            raise ValueError("请设置 --public-origin 或 NH_PUBLIC_ORIGIN")
        else:
            result = check(opt.db.absolute(), opt.profile, opt.public_origin, full=opt.full, language=opt.language)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, RuntimeError) as err:
        parser.exit(1, str(err) + "\n")


if __name__ == "__main__":
    main()
