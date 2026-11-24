"""Read posted bank/electricity exports. An invoice alone is evidence, not payment."""

import csv
from io import StringIO
import re
from xml.etree import ElementTree

from .records import currency_amount, parse_day
from .settlements import EXPENSES

HEADERS = {
    "date": (
        "交易日期",
        "记账日期",
        "记帐日期",
        "入账日期",
        "缴费日期",
        "付款日期",
        "支付日期",
    ),
    "payee": (
        "对方户名",
        "对方账户名称",
        "对方账号名称",
        "收款单位",
        "收款户名",
        "收款方",
        "收款对象",
    ),
    "amount": ("实付金额", "缴费金额", "交易金额", "发生额", "金额"),
    "debit": ("借方发生额", "借方发生额(支取)", "借方金额", "支出金额"),
    "credit": ("贷方发生额", "贷方发生额(收入)", "贷方金额", "收入金额"),
    "direction": ("收支方向", "借贷标志", "借贷方向", "收支类型"),
    "transactionId": (
        "银行流水号",
        "交易流水号",
        "交易序号",
        "凭证流水号",
        "流水号",
        "银行回单号",
        "缴费流水号",
    ),
    "invoiceNo": ("发票号码", "数电票号码", "发票号", "票据号码"),
    "status": ("交易状态", "缴费状态", "支付状态", "付款状态"),
    "category": ("支出分类", "支出类别"),
    "note": ("摘要", "用途", "事由", "备注"),
    "currency": ("币种", "货币"),
}
PAID = {
    "已缴费",
    "已支付",
    "已付款",
    "成功",
    "交易成功",
    "支付成功",
    "已入账",
    "已记账",
    "已转账",
    "缴费成功",
}
UNPAID = {
    "欠费",
    "未结清",
    "应缴",
    "待付款",
    "已退费",
    "退款成功",
    "未支付",
    "未付款",
    "未缴费",
    "待缴费",
    "待支付",
    "已撤销",
    "冲正",
    "已冲正",
    "失败",
    "交易失败",
    "已退款",
    "退款",
    "撤销",
}
OUT = {"支出", "借", "借方", "付款", "转出", "付", "D", "DEBIT"}
IN = {"收入", "贷", "贷方", "收款", "转入", "收", "C", "CREDIT"}
MAX_ROWS = 1000


def read_text(raw):
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            result = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\0" not in result:
            return result
    raise ValueError("请选择 UTF-8 或 GB18030 编码的账单")


def header_name(value):
    return value.strip().replace("（", "(").replace("）", ")").removesuffix("(元)")


def amount(value):
    if not re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", value):
        raise ValueError("金额格式或正负方向待核对")
    return currency_amount(value.replace(",", ""), "金额")


def day(value):
    date = value.split(" ")[0].replace("/", "-")
    if re.fullmatch(r"\d{8}", date):
        date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    return parse_day(date).isoformat()


def row_data(fields, number, source, today):
    def pick(key):
        return fields.get(key, "")

    invoice, txn = pick("invoiceNo"), pick("transactionId")
    row = dict(
        rowNumber=number,
        invoiceNo=invoice,
        transactionId=txn,
        voucher=txn or invoice,
        date=pick("date"),
        payee=pick("payee"),
        amount=None,
        category=pick("category") or ("设施" if source == "electricity" else "其他"),
        note=pick("note")
        or ("电费缴费" if source == "electricity" else "银行对账单支出"),
        status="review",
        reason="",
    )
    try:
        if any(
            any(ord(c) < 32 or ord(c) == 127 for c in value)
            for value in fields.values()
        ):
            raise ValueError("字段含换行或控制符，请核对原始记录")
        if pick("currency").upper() not in {"", "人民币", "人民币元", "CNY", "RMB"}:
            raise ValueError("此记录币种需单独核对")
        if pick("status") in UNPAID:
            return {**row, "status": "excluded", "reason": "未实付或已撤销"}
        direction = pick("direction").upper()
        if direction and direction not in (OUT | IN):
            raise ValueError("收支方向需复核")
        if any(
            term in row["note"]
            for term in ("内部转账", "内部划转", "账户划转", "冲正", "冲销", "红冲")
        ):
            raise ValueError("内部划转或冲正记录须核对实际费用")
        debit, credit = pick("debit"), pick("credit")
        if debit or credit:
            outflow, inflow = amount(debit or "0"), amount(credit or "0")
            if (
                (outflow and inflow)
                or (direction in IN and outflow)
                or (direction in OUT and inflow)
            ):
                raise ValueError("借贷方向与发生额不一致")
            if inflow:
                return {
                    **row,
                    "amount": float(inflow),
                    "status": "excluded",
                    "reason": "贷方收入",
                }
            if not outflow:
                raise ValueError("缺少借方发生额")
            if pick("amount") and amount(pick("amount")) != outflow:
                raise ValueError("交易金额与借方发生额不一致")
            value = outflow
        else:
            value = amount(pick("amount"))
            if direction in IN:
                return {
                    **row,
                    "amount": float(value),
                    "status": "excluded",
                    "reason": "贷方收入",
                }
            if source == "bank" and direction not in OUT:
                raise ValueError("缺少明确的支出方向")
        row["amount"] = float(value)
        if source == "electricity" or "status" in fields:
            if pick("status") not in PAID:
                raise ValueError("缺少已实付凭据")
        if not value:
            raise ValueError("金额须大于零")
        row["date"] = day(pick("date"))
        if row["date"] > today:
            raise ValueError("交易日期在未来")
        if not row["payee"] or not row["voucher"] or (source == "bank" and not txn):
            raise ValueError("缺少收款单位或可复核的唯一凭证号")
        if (
            max(len(txn), len(invoice)) > 100
            or len(row["payee"]) > 80
            or len(row["note"]) > 160
        ):
            raise ValueError("凭证号、收款单位或摘要过长")
        if row["category"] not in EXPENSES:
            raise ValueError("支出分类需核对")
    except ValueError as e:
        row["reason"] = str(e)
        return row
    return {**row, "status": "ready", "reason": "可登记实付支出"}


def bank_or_power_csv(raw, source, today):
    text = read_text(raw)
    reader = csv.reader(
        StringIO(text, newline=""),
        delimiter="\t" if "\t" in text.partition("\n")[0] else ",",
        strict=True,
    )
    result = []
    try:
        headers = [header_name(x) for x in next(reader, [])]
        fields = {
            index: key
            for key, aliases in HEADERS.items()
            for index, val in enumerate(headers)
            if val in aliases
        }
        if not fields or not {"date", "payee"}.issubset(fields.values()):
            raise ValueError("账单至少需含日期和收款单位，请参照模板")
        if len(fields) != len(set(fields.values())):
            raise ValueError("检测到含义重复的列，请整理成单组对账字段")
        for i, values in enumerate(reader, 2):
            if not any(v.strip() for v in values):
                continue
            if len(result) >= MAX_ROWS:
                raise ValueError(f"单次最多预览 {MAX_ROWS} 笔")
            if len(values) != len(headers):
                raise ValueError(f"第 {i} 行列数与表头不一致")
            fields_at_row = {name: values[k].strip() for k, name in fields.items()}
            result.append(row_data(fields_at_row, i, source, today))
    except csv.Error:
        raise ValueError("CSV 格式无效，请检查引号和分隔符") from None
    if not result:
        raise ValueError("文件没有可预览的账单行")
    return result


def power_invoice(raw):
    # Only extract evidence. A tax invoice has no guaranteed bank settlement date.
    text = read_text(raw)
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("仅支持不含文档类型定义的发票 XML")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise ValueError("发票 XML 格式错误") from None

    def scalar(*names):
        values = {
            e.text.strip()
            for e in root.iter()
            if e.tag.rsplit("}", 1)[-1] in names and e.text and e.text.strip()
        }
        return values.pop() if len(values) == 1 else ""

    invoice = scalar("InvoiceNumber", "EInvoiceNumber", "EIid")
    seller = scalar("SellerName", "SellerInformationName", "SellerIdentificationName")
    total = scalar(
        "TotalTax-includedAmount",
        "TotalTaxIncludedAmount",
        "TotalAmWithoutTaxAndTaxAm",
        "TotalAmountWithTax",
        "TotalTax-includedAm",
    )
    if not invoice:
        raise ValueError("未能识别发票唯一号码，请使用电费缴费明细 CSV")
    try:
        value = float(amount(total))
    except ValueError:
        value = None
    return [
        dict(
            rowNumber=1,
            status="review",
            reason="发票尚需关联实付凭据",
            invoiceOnly=True,
            invoiceNo=invoice,
            transactionId="",
            voucher=invoice,
            date="",
            payee=seller,
            amount=value,
            category="设施",
            note="电费电子发票",
        )
    ]
