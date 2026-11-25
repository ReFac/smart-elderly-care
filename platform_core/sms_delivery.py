"""Host-configured SMS gateway for account and visitor verification."""

from functools import partial
import json
import os
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import Request

from .operational_secrets import valid_key
from .provider import connection


def _deliver(endpoint, secret, purpose, field, phone, content):
    req = Request(
        endpoint,
        data=json.dumps({"phone": phone, "purpose": purpose, field: content}).encode(),
        headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with connection.open_request(req, timeout=8) as response:
            if not 200 <= response.status < 300:
                raise OSError("短信渠道未接受请求")
    except HTTPError as error:
        error.close()
        raise OSError("短信渠道未接受请求") from None


def configured():
    endpoint = os.environ.get("NH_IDENTITY_SMS_ENDPOINT", "").strip()
    secret = os.environ.get("NH_IDENTITY_SMS_TOKEN", "").strip()
    if not endpoint and not secret:
        return {}, {}
    try:
        connection.endpoint(endpoint)
        if urlsplit(endpoint).scheme != "https" or not valid_key(secret):
            raise ValueError
    except ValueError:
        raise ValueError("短信网关须配置 HTTPS 地址及服务端密钥") from None
    return (
        {"sms": partial(_deliver, endpoint, secret, "verification", "code")},
        {"sms": partial(_deliver, endpoint, secret, "password-reset", "url")},
    )
