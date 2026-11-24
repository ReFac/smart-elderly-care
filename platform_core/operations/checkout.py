"""Signed merchant pre-orders, scoped cashier access and short-lived QR code caching."""

from base64 import b64encode
from contextlib import closing
from decimal import Decimal
from http.client import HTTPSConnection, HTTPException
from importlib.util import find_spec
import json
import os
from pathlib import Path
import re
from secrets import token_hex
from urllib.parse import urlencode, urlsplit

from .. import access, activity, campus_access
from .channels import material, setting, verify_signature, verify_wechat_message
from .records import lookup

CONFIG = {
    "微信支付": (
        "WXPAY_APP_ID",
        "WXPAY_MERCHANT_ID",
        "WXPAY_PUBLIC_KEY_ID",
        "WXPAY_PUBLIC_KEY_FILE",
        "WXPAY_V3_KEY_FILE",
        "WXPAY_CERT_SERIAL",
        "WXPAY_PRIVATE_KEY_FILE",
    ),
    "支付宝": (
        "ALIPAY_APP_ID",
        "ALIPAY_SELLER_ID",
        "ALIPAY_PUBLIC_KEY_FILE",
        "ALIPAY_PRIVATE_KEY_FILE",
    ),
}
PUBLIC_ORIGIN = "PAYMENT_PUBLIC_ORIGIN"
LEASE_SECONDS = 45
CACHE_SECONDS = 6900


def notify_origin():
    origin = setting(PUBLIC_ORIGIN).rstrip("/")
    parts = urlsplit(origin)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.path
        or parts.query
        or parts.fragment
    ):
        raise ValueError("请配置机构收款回调的 HTTPS 根域名")
    return origin


def enabled_channels():
    if not (find_spec("cryptography") and find_spec("qrcode")):
        return []
    try:
        notify_origin()
    except ValueError:
        return []

    def ready(key):
        val = os.environ.get("NH_" + key, "")
        return bool(val) and (
            not key.endswith("_FILE")
            or (Path(val).is_file() and os.access(val, os.R_OK))
        )

    return [
        name for name, settings in CONFIG.items() if all(ready(k) for k in settings)
    ]


def compact(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def sign(key, data):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    priv = serialization.load_pem_private_key(material(key), password=None)
    if not isinstance(priv, rsa.RSAPrivateKey) or priv.key_size < 2048:
        raise ValueError("商户签名私钥格式无效")
    return b64encode(priv.sign(data, padding.PKCS1v15(), hashes.SHA256())).decode(
        "ascii"
    )


def send(host, path, payload, headers):
    with closing(HTTPSConnection(host, timeout=8)) as client:
        try:
            client.request("POST", path, body=payload, headers=headers)
            with client.getresponse() as response:
                body = response.read(65537)
                if response.status != 200 or len(body) > 65536:
                    raise ValueError("收款渠道未签发付款码，请核对商户订单及签约配置")
                return response.headers, body
        except (OSError, HTTPException):
            raise ValueError("收款渠道暂时无法连接，请稍后重试同一订单") from None


def wx_native(order, now):
    path = "/v3/pay/transactions/native"
    merchant = setting("WXPAY_MERCHANT_ID")
    serial = setting("WXPAY_CERT_SERIAL")
    if not re.fullmatch(r"[0-9A-Za-z]+", merchant) or not re.fullmatch(
        r"[0-9A-Fa-f]+", serial
    ):
        raise ValueError("微信商户号或证书序列号格式错误")
    payload = compact(
        dict(
            appid=setting("WXPAY_APP_ID"),
            mchid=merchant,
            out_trade_no=order["id"],
            description="养老机构服务费",
            notify_url=notify_origin() + "/api/payments/notify/wechat",
            amount=dict(total=int(Decimal(str(order["amount"])) * 100), currency="CNY"),
        )
    ).encode()
    stamp, nonce = str(int(now.timestamp())), token_hex(16)
    signed = sign(
        "WXPAY_PRIVATE_KEY_FILE",
        f"POST\n{path}\n{stamp}\n{nonce}\n".encode() + payload + b"\n",
    )
    auth = f'WECHATPAY2-SHA256-RSA2048 mchid="{merchant}",nonce_str="{nonce}",timestamp="{stamp}",serial_no="{serial}",signature="{signed}"'
    headers, raw = send(
        "api.mch.weixin.qq.com",
        path,
        payload,
        {
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Ankang-Merchant/1.0",
            "Wechatpay-Serial": setting("WXPAY_PUBLIC_KEY_ID"),
        },
    )
    verify_wechat_message(headers, raw, now)
    return json.loads(raw)["code_url"]


def signed_object(raw, name):
    # Preserve the gateway's exact JSON member representation, including escaped characters.
    text = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    pos = 0

    def whitespace():
        nonlocal pos
        while pos < len(text) and text[pos] in " \t\r\n":
            pos += 1

    def take(char):
        nonlocal pos
        whitespace()
        if text[pos : pos + 1] != char:
            raise ValueError("支付宝应答格式无效")
        pos += 1

    take("{")
    values = {}
    encoded = None
    while True:
        whitespace()
        key, pos = decoder.raw_decode(text, pos)
        if not isinstance(key, str) or key in values:
            raise ValueError("支付宝应答字段重复或无效")
        take(":")
        whitespace()
        begin = pos
        values[key], pos = decoder.raw_decode(text, pos)
        if key == name:
            encoded = text[begin:pos].encode()
        whitespace()
        if text[pos : pos + 1] == "}":
            take("}")
            break
        take(",")
    if text[pos:].strip() or not encoded:
        raise ValueError("支付宝预下单应答无效")
    verify_signature("ALIPAY_PUBLIC_KEY_FILE", encoded, values["sign"])
    return values[name]


def ali_precreate(order, now):
    params = dict(
        app_id=setting("ALIPAY_APP_ID"),
        method="alipay.trade.precreate",
        format="JSON",
        charset="utf-8",
        sign_type="RSA2",
        timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
        version="1.0",
        notify_url=notify_origin() + "/api/payments/notify/alipay",
        biz_content=compact(
            dict(
                out_trade_no=order["id"],
                total_amount=f"{order['amount']:.2f}",
                subject="养老机构服务费",
                qr_code_timeout_express="2h",
                seller_id=setting("ALIPAY_SELLER_ID"),
            )
        ),
    )
    message = "&".join(f"{k}={params[k]}" for k in sorted(params))
    params["sign"] = sign("ALIPAY_PRIVATE_KEY_FILE", message.encode())
    _, raw = send(
        "openapi.alipay.com",
        "/gateway.do?charset=utf-8",
        urlencode(params).encode(),
        {
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
            "Accept": "application/json",
        },
    )
    result = signed_object(raw, "alipay_trade_precreate_response")
    if result["code"] != "10000" or result["out_trade_no"] != order["id"]:
        raise ValueError("支付宝未确认这笔商户订单")
    return result["qr_code"]


def precreate(order, now):
    try:
        url = (
            wx_native(order, now)
            if order["channel"] == "微信支付"
            else ali_precreate(order, now)
        )
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "weixin"
            if order["channel"] == "微信支付"
            else (parsed.scheme == "https" and parsed.hostname == "qr.alipay.com")
        )
        if (
            not valid
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or len(url) > 1024
        ):
            raise ValueError("收款渠道返回的付款码格式无效")
        return url
    except (KeyError, UnicodeError, TypeError, AttributeError):
        raise ValueError("收款渠道的签名应答缺少必要字段") from None


def qr(order, url, expires):
    import qrcode

    code = qrcode.QRCode(border=4)
    code.add_data(url)
    code.make(fit=True)
    return dict(
        orderId=order["id"],
        amount=order["amount"],
        channel=order["channel"],
        expiresAt=expires,
        checkoutUrl=url,
        matrix=["".join("1" if b else "0" for b in row) for row in code.get_matrix()],
    )


def authorized_order(store, db, token, oid):
    actor = store.actor(db, token)
    access.require(actor, "finance")
    data = json.loads(db.execute("SELECT data FROM workspace WHERE id=1").fetchone()[0])
    order = lookup(data, "paymentOrders", oid, "商户订单")
    campus_access.require_resident(db, actor, order["residentId"], data)
    return actor, data, order


def payable(order, bill):
    if order["status"] != "待支付" or bill["balance"] <= 0:
        return False
    return (
        order["amount"] <= bill["balance"]
        or order.get("balanceAtIssue") == bill["balance"]
    )


def cached_payment_link(db, state, order, now):
    if not payable(order, lookup(state, "bills", order["billId"], "账单")):
        return {}
    if not db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkout_codes'"
    ).fetchone():
        return {}
    row = db.execute(
        "SELECT url,until FROM checkout_codes WHERE id=? AND url<>'' AND until>?",
        (order["id"], int(now.timestamp())),
    ).fetchone()
    if not row or order["channel"] not in enabled_channels():
        return {}
    return dict(
        channel=order["channel"], checkoutUrl=row["url"], expiresAt=row["until"]
    )


def open_code(store, token, oid):
    now = store.now()
    ts = int(now.timestamp())
    lease = token_hex(16)
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        _, data, order = authorized_order(store, db, token, oid)
        if order["channel"] not in enabled_channels():
            raise ValueError("本机构尚未启用此渠道的商户收款码")
        bill = lookup(data, "bills", order["billId"], "账单")
        if not payable(order, bill):
            raise ValueError("订单已到账或应收余额已变，请核对收费账单")
        db.execute(
            """CREATE TABLE IF NOT EXISTS checkout_codes (id TEXT PRIMARY KEY, lease TEXT NOT NULL, until INTEGER NOT NULL, url TEXT NOT NULL)"""
        )
        cached = db.execute(
            "SELECT url,until FROM checkout_codes WHERE id=?", (oid,)
        ).fetchone()
        if cached and cached["until"] > ts:
            if not cached["url"]:
                raise ValueError("该订单正在向渠道申请付款码，请稍后打开")
            return qr(order, cached["url"], cached["until"])
        db.execute(
            "INSERT OR REPLACE INTO checkout_codes VALUES (?,?,?,?)",
            (oid, lease, ts + LEASE_SECONDS, ""),
        )
    try:
        url = precreate(order, now)
        with closing(store.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            actor, data, order = authorized_order(store, db, token, oid)
            bill = lookup(data, "bills", order["billId"], "账单")
            if not payable(order, bill):
                raise ValueError("订单状态已更新，请刷新账单")
            if not db.execute(
                "UPDATE checkout_codes SET url=?,until=? WHERE id=? AND lease=?",
                (url, ts + CACHE_SECONDS, oid, lease),
            ).rowcount:
                raise ValueError("订单付款码已更新，请重新打开")
            revision = db.execute(
                "UPDATE workspace SET revision=revision+1 WHERE id=1 RETURNING revision"
            ).fetchone()[0]
            activity.write(
                db,
                revision,
                now.isoformat(timespec="seconds"),
                "ops.paymentOrder",
                f"为 {oid} 申请{order['channel']}收款码",
                actor,
                activity.for_person(data, order["residentId"]),
                {},
            )
            return qr(order, url, ts + CACHE_SECONDS)
    except Exception:
        with closing(store.connect()) as db, db:
            db.execute(
                "DELETE FROM checkout_codes WHERE id=? AND lease=? AND url=''",
                (oid, lease),
            )
        raise
