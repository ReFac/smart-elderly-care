"""Institutional merchant rates, in basis points, versioned on each receipt."""

from decimal import Decimal, ROUND_HALF_UP

from .records import CENT, text_field, whole_number

RATE_CHANNELS = ("微信支付", "支付宝", "银联刷卡", "银行转账")
OFFLINE_CHANNELS = ("现金", "银行转账", "微信支付", "支付宝")
CASH_METHODS = frozenset(("线下登记", "线下刷卡登记", "微信支付", "支付宝", "银联刷卡"))


def configure(state, payload, today):
    rates = payload.get("rates")
    if not isinstance(rates, dict) or set(rates) != set(RATE_CHANNELS):
        raise ValueError("请完整设置各渠道的手续费率")
    values = {k: whole_number(rates[k], k + "费率", zero=True) for k in RATE_CHANNELS}
    if any(rate > 10000 for rate in values.values()):
        raise ValueError("手续费率须在 0% 至 100% 之间")
    state["paymentFeeSettings"] = [dict(id="institution", rates=values, date=today)]
    return "已更新机构承担的收款手续费率"


def rate_for(state, channel):
    settings = state.get("paymentFeeSettings") or [{}]
    return settings[0].get("rates", {}).get(channel, 0)


def fee(amount, rate):
    return (amount * Decimal(rate) / 10000).quantize(CENT, rounding=ROUND_HALF_UP)


def accounting(amount, fee_amount, rate):
    return dict(
        feeRateBps=rate,
        feeAmount=float(fee_amount),
        netAmount=float(amount - fee_amount),
    )


def offline(payload):
    method = payload.get("method", "线下登记")
    channel = payload.get("channel", "银联刷卡" if method == "线下刷卡登记" else "现金")
    if not (
        (method == "线下登记" and channel in OFFLINE_CHANNELS)
        or (method == "线下刷卡登记" and channel == "银联刷卡")
    ):
        raise ValueError("请选择对应的线下登记方式和实际支付渠道")
    return method, channel


def manual_reference(state, payload, *, bill_id, resident_id, amount, method, channel):
    """Match retries from one form; never accept its reference for different terms."""
    if "paymentRef" not in payload:
        return "", False
    ref = text_field(payload, "paymentRef", "收款登记编号", 80)
    for rows in (state["depositEntries"], state["payments"]):
        for prior in rows:
            if prior.get("paymentRef") == ref:
                if (
                    prior.get("originBillId", ""),
                    prior["residentId"],
                    prior["grossAmount"],
                    prior["method"],
                    prior["channel"],
                ) != (bill_id, resident_id, float(amount), method, channel):
                    raise ValueError("收款登记编号已用于其他凭证")
                if channel in ("微信支付", "支付宝") and any(
                    payload.get(key) != prior.get(stored)
                    for key, stored in (
                        ("merchantOrder", "merchantOrder"),
                        ("transactionId", "transactionId"),
                        ("paidDate", "date"),
                    )
                ):
                    raise ValueError("收款登记编号对应的交易信息不同")
                return ref, True
    return ref, False
