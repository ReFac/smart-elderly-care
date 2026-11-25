"""Merchant-configured payment notifications. Verify before opening any write transaction."""

import base64
from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from .. import activity
from .settlements import settle


def setting(name):
    value = os.environ.get("NH_" + name)
    if not value:
        raise ValueError("此机构尚未配置该收款渠道")
    return value


def material(name):
    try:
        with Path(setting(name)).open("rb") as stream:
            data = stream.read(16385)
    except OSError:
        raise ValueError("渠道验签材料不可用") from None
    if not data or len(data) > 16384:
        raise ValueError("渠道验签材料格式无效")
    return data


def verify_signature(name, signed, signature):
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = serialization.load_pem_public_key(material(name))
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise ValueError("渠道公钥须为 RSA 2048 位或以上")
    try:
        key.verify(
            base64.b64decode(signature, validate=True),
            signed,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (InvalidSignature, ValueError, TypeError):
        raise PermissionError("渠道通知验签失败") from None


def verify_wechat_message(headers, raw, now):
    key_id = setting("WXPAY_PUBLIC_KEY_ID")
    if (
        key_id != headers.get("Wechatpay-Serial")
        or headers.get("Wechatpay-Signature-Type", "WECHATPAY2-SHA256-RSA2048")
        != "WECHATPAY2-SHA256-RSA2048"
    ):
        raise PermissionError("微信支付通知的公钥标识或签名类型不匹配")
    stamp = headers.get("Wechatpay-Timestamp", "")
    nonce = headers.get("Wechatpay-Nonce", "")
    if (
        not stamp.isascii()
        or not stamp.isdecimal()
        or len(stamp) > 12
        or abs(int(stamp) - now.timestamp()) > 300
        or not nonce
        or len(nonce) > 128
    ):
        raise PermissionError("微信支付通知时间或随机值无效")
    verify_signature(
        "WXPAY_PUBLIC_KEY_FILE",
        (stamp + "\n" + nonce + "\n").encode() + raw + b"\n",
        headers.get("Wechatpay-Signature", ""),
    )


def wechat_event(headers, raw, now, allowed_events):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    verify_wechat_message(headers, raw, now)
    event = json.loads(raw)
    if (
        event["event_type"] not in allowed_events
        or event["resource"]["algorithm"] != "AEAD_AES_256_GCM"
    ):
        raise ValueError("渠道通知事件类型或加密算法不匹配")
    resource = event["resource"]
    secret = material("WXPAY_V3_KEY_FILE").rstrip(b"\r\n")
    if len(secret) != 32:
        raise ValueError("微信支付 APIv3 密钥长度不正确")
    try:
        order = json.loads(
            AESGCM(secret).decrypt(
                resource["nonce"].encode(),
                base64.b64decode(resource["ciphertext"], validate=True),
                resource.get("associated_data", "").encode(),
            )
        )
    except InvalidTag:
        raise PermissionError("微信支付通知解密校验失败") from None
    return event, order


def wechat(headers, raw, now):
    event, order = wechat_event(headers, raw, now, {"TRANSACTION.SUCCESS"})
    if (
        order["appid"] != setting("WXPAY_APP_ID")
        or order["mchid"] != setting("WXPAY_MERCHANT_ID")
        or order["trade_state"] != "SUCCESS"
    ):
        raise PermissionError("微信支付商户或交易状态不匹配")
    amount = order["amount"]
    cents = amount["total"]
    if type(cents) is not int or cents <= 0 or amount.get("currency", "CNY") != "CNY":
        raise ValueError("微信支付订单金额或币种不正确")
    when = datetime.fromisoformat(order["success_time"])
    if when.tzinfo is None:
        raise ValueError("缺少支付时间时区")
    return dict(
        channel="微信支付",
        merchantOrder=order["out_trade_no"],
        transactionId=order["transaction_id"],
        amount=f"{cents // 100}.{cents % 100:02d}",
        paidDate=when.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(),
        source=event["id"],
    )


def alipay(raw):
    items = parse_qsl(
        raw.decode("utf-8"),
        keep_blank_values=True,
        strict_parsing=True,
        max_num_fields=128,
        errors="strict",
    )
    params = dict(items)
    if (
        len(items) != len(params)
        or params.get("sign_type") != "RSA2"
        or params.get("charset", "utf-8").lower() != "utf-8"
    ):
        raise ValueError("支付宝通知参数重复或签名类型、字符集无效")
    signing = "&".join(
        f"{k}={params[k]}"
        for k in sorted(params)
        if k not in ("sign", "sign_type") and params[k]
    )
    verify_signature("ALIPAY_PUBLIC_KEY_FILE", signing.encode(), params["sign"])
    if (
        params["app_id"] != setting("ALIPAY_APP_ID")
        or params["seller_id"] != setting("ALIPAY_SELLER_ID")
        or params["trade_status"] not in ("TRADE_SUCCESS", "TRADE_FINISHED")
    ):
        raise PermissionError("支付宝商户或交易状态不匹配")
    if params.get("trans_currency", "CNY") != "CNY":
        raise ValueError("暂仅受理人民币交易")
    when = datetime.strptime(params["gmt_payment"], "%Y-%m-%d %H:%M:%S")
    return dict(
        channel="支付宝",
        merchantOrder=params["out_trade_no"],
        transactionId=params["trade_no"],
        amount=params["total_amount"],
        paidDate=when.date().isoformat(),
        source=params["notify_id"],
    )


def receive(store, channel, headers, raw_body):
    now = store.now()
    if not raw_body or len(raw_body) > 65536 or channel not in ("wechat", "alipay"):
        raise ValueError("渠道通知无效")
    try:
        fields = (
            wechat(headers, raw_body, now) if channel == "wechat" else alipay(raw_body)
        )
    except ImportError:
        raise ValueError("此机构需安装渠道验签组件 cryptography") from None
    except (KeyError, UnicodeError, TypeError, AttributeError):
        raise ValueError("渠道通知缺少有效的交易字段") from None
    record_verified(store, channel, fields, now, "渠道签名通知")


def record_verified(store, channel, fields, now, verification):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        from .. import history

        history.watch(db, "ops.importReceipt")
        revision, encoded = db.execute(
            "SELECT revision,data FROM workspace WHERE id=1"
        ).fetchone()
        state = json.loads(encoded)
        receipt, added = settle(
            state, fields, now.date().isoformat(), verification=verification
        )
        if added:
            revision += 1
            db.execute(
                "UPDATE workspace SET revision=?,data=? WHERE id=1",
                (
                    revision,
                    json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            actor = dict(
                id="channel-" + channel,
                username="channel-" + channel,
                displayName=receipt["channel"] + "通知",
            )
            activity.write(
                db,
                revision,
                now.isoformat(timespec="seconds"),
                "ops.importReceipt",
                f"{receipt['channel']}签名通知核销 ¥{receipt['amount']:.2f}，凭证 {receipt['id']}",
                actor,
                activity.for_person(state, receipt["residentId"]),
                {},
            )
        return receipt["id"]
