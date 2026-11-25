"""Consent-based phone enquiries from the published visitor mini program."""
from http.client import HTTPException
import json
import os
import re
from urllib.parse import quote
from urllib.request import build_opener, HTTPRedirectHandler, Request

from . import lead_intake
from .profile_fields import phone_number


def contact_link():
    link = os.environ.get("NH_WECHAT_TOUR_LINK", "")
    if (os.environ.get("NH_WECHAT_MINI_APP_ID") and os.environ.get("NH_WECHAT_MINI_APP_SECRET")
            and re.fullmatch(r"https://(?:wxaurl|wxmpurl)\.cn/[A-Za-z0-9_-]+", link)):
        return link
    return ""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post(path, payload):
    request = Request("https://api.weixin.qq.com/" + path, data=json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=5) as response:
            data = json.loads(response.read(16385))
        if not isinstance(data, dict) or data.get("errcode", 0) != 0:
            raise ValueError()
    except (ValueError, OSError, HTTPException):
        raise ValueError("微信暂时未能取得手机号，请手动填写。") from None
    return data


def receive(store, payload, peer):
    if set(payload) != {"code", "consent"} or payload.get("consent") is not True:
        raise ValueError("请先授权机构使用此手机号联系您")
    code = payload["code"]
    if not isinstance(code, str) or not re.fullmatch(r"[!-~]{1,512}", code):
        raise ValueError("请重新授权或手动填写手机号")
    app_id = os.environ.get("NH_WECHAT_MINI_APP_ID")
    secret = os.environ.get("NH_WECHAT_MINI_APP_SECRET")
    if not app_id or not secret:
        raise ValueError("微信手机号暂未开通，请手动填写。")
    store.public_submissions.check(("wechat-phone", peer))
    result = _post("cgi-bin/stable_token", {"grant_type": "client_credential", "appid": app_id,
                                            "secret": secret, "force_refresh": False})
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise ValueError("微信连接暂时不可用，请手动填写。")
    result = _post("wxa/business/getuserphonenumber?access_token=" + quote(token, safe=""), {"code": code})
    info = result.get("phone_info")
    watermark = info.get("watermark") if isinstance(info, dict) else None
    if not isinstance(watermark, dict) or watermark.get("appid") != app_id:
        raise ValueError("微信手机号未通过校验，请手动填写。")
    phone = phone_number(info.get("purePhoneNumber"), mobile=True)
    if str(info.get("countryCode")) != "86" or not phone:
        raise ValueError("请手动填写可接听回电的中国大陆手机号。")
    return lead_intake.submit(store, {"source": "consent", "consent": True, "phone": phone}, peer)
