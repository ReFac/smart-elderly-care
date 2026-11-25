"""Authenticated connectivity check for the institution's hosted DeepSeek service."""

from contextlib import closing
from .chat import Unavailable
from .. import provider


def _authorize(store, token):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        store.actor(db, token)
        plan = provider.latest(db)
        day = store.now().date().isoformat()
        if not provider.active(plan, day):
            raise Unavailable("机构的云端 AI 套餐尚未开通或已经到期")
        return plan["id"]


def probe(store, token):
    from ..provider import web_search

    plan = _authorize(store, token)
    try:
        key = provider.read_key()
    except (OSError, ValueError):
        raise Unavailable("机构的 DeepSeek 服务尚未配置，请联系管理员") from None

    if not store.network_probes.acquire(blocking=False):
        raise Unavailable("连接检测正在进行，请稍后重试")
    try:
        result = web_search.probe(key)
    except web_search.WebSearchError as error:
        raise Unavailable(str(error)) from None
    finally:
        store.network_probes.release()
    if _authorize(store, token) != plan:
        raise Unavailable("机构套餐已更新，请重新检测")
    return {**result, "checkedAt": store.now().isoformat(timespec="seconds")}
