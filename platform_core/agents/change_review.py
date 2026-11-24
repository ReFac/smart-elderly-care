"""Local, transactional review tools. No prompts, profile text or credentials leave the host."""

import json
from decimal import Decimal

DOMAINS = {
    "care.register": "档案与床位",
    "care.admit": "档案与床位",
    "care.transfer": "档案与床位",
    "care.discharge": "原件归档",
    "dossier.profile": "档案填写",
    "dossier.relative": "档案填写",
    "ltci.record": "长护险",
    "ops.bill": "费用核算",
    "ops.pay": "收款核销",
    "ops.deposit": "收款核销",
    "ops.paymentOrder": "收款核销",
    "ops.importReceipt": "收款核销",
    "access.create": "账号授权",
    "access.update": "账号授权",
    "access.status": "账号授权",
}


def category(action):
    if action.startswith("backup."):
        return "备份"
    if action.startswith(("account.", "access.")) and any(
        k in action.lower() for k in ("password", "contact", "recovery", "challenge")
    ):
        return "账号凭据"
    return DOMAINS.get(action)


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS history_agent_checks (
        revision INTEGER PRIMARY KEY REFERENCES history_commits(revision) ON DELETE CASCADE,
        domain TEXT NOT NULL, result TEXT NOT NULL)""")


def person_meta(db, rid):
    return db.execute(
        """SELECT json_extract(value,'$.status'),json_extract(value,'$.bedId')
        FROM workspace,json_each(workspace.data,'$.residents') WHERE json_extract(value,'$.id')=?""",
        (rid,),
    ).fetchone()


def inspect(db, revision, action, actor, rid):
    domain = category(action)
    if not domain:
        return
    checks = ["已关联经办身份和本次业务版本"]
    # Archived care files are sealed without passing their contents into an agent.
    meta = person_meta(db, rid) if rid else None
    if domain == "原件归档" or (
        meta and meta[0] in ("已退住", "归档", "已归档", "归档到期")
    ):
        return
    if domain == "档案与床位":
        if not meta:
            raise ValueError("审核 Agent 未能关联长者档案")
        occupied = [
            r[0]
            for r in db.execute(
                """SELECT json_extract(value,'$.id') FROM workspace,
            json_each(workspace.data,'$.beds') WHERE json_extract(value,'$.residentId')=?""",
                (rid,),
            )
        ]
        if (meta[0] == "在住" and occupied != [meta[1]]) or (
            meta[0] == "未入住" and (occupied or meta[1])
        ):
            raise ValueError("审核 Agent 检出档案与床位占用不一致")
        checks.append("已核对档案入住状态与唯一床位占用")
    elif domain == "费用核算":
        (payload,) = db.execute(
            "SELECT json_extract(data,'$.bills[0]') FROM workspace WHERE id=1"
        ).fetchone()
        bill = json.loads(payload)
        lines = bill.get("lineItems", [])
        if (
            bill["residentId"] != rid
            or not lines
            or any(
                Decimal(str(line["quantity"]))
                * Decimal(str(line["unitPrice"]))
                * (-1 if line["code"] == "reduction" else 1)
                != Decimal(str(line["amount"]))
                for line in lines
            )
            or sum(Decimal(str(i["amount"])) for i in lines)
            != Decimal(str(bill["amount"]))
            or Decimal(str(bill["paid"])) + Decimal(str(bill["balance"]))
            != Decimal(str(bill["amount"]))
        ):
            raise ValueError("审核 Agent 检出收费明细、应收或余额不一致")
        checks.append("已逐项核对分项合计、实收与待缴余额")
    elif domain == "收款核销":
        if not meta:
            raise ValueError("收款凭证缺少对应长者档案")
        bills = {}

        def owned(collection):
            # Only the resident under review is projected from the institution ledger.
            return (
                json.loads(r[0])
                for r in db.execute(
                    "SELECT value FROM workspace,json_each(data,?) WHERE json_extract(value,'$.residentId')=?",
                    ("$." + collection, rid),
                )
            )

        def money(row, key):
            return Decimal(str(row[key]))

        for bill in owned("bills"):
            if (
                money(bill, "paid") < 0
                or money(bill, "balance") < 0
                or money(bill, "paid") + money(bill, "balance") != money(bill, "amount")
            ):
                raise ValueError("收款后实收和余额与原账单不符")
            bills[bill["id"]] = bill
        if any(money(a, "amount") < 0 for a in owned("deposits")):
            raise ValueError("预交账户结余异常")
        if action in ("ops.paymentOrder", "ops.importReceipt"):
            for row in owned("paymentOrders"):
                if row["billId"] not in bills or money(row, "amount") <= 0:
                    raise ValueError("收款订单的归属或金额异常")
        if action == "ops.importReceipt":
            for row in owned("channelReceipts"):
                if row["billId"] not in bills or money(row, "billAmount") + money(
                    row, "depositAmount"
                ) != money(row, "amount"):
                    raise ValueError("到账凭证的账单核销与转预交金额不符")
        checks.append("已核对长者账单余额、预交结余及本次渠道凭证关系")
    elif domain == "长护险":
        from ..long_care import ALLOWED, STAGES

        # The local checker reads event labels, dates and the presence of the official
        # reference, but does not interpret a clinical assessment or copy its contents.
        events = db.execute(
            """SELECT json_extract(value,'$.event'), json_extract(value,'$.status'),
            json_extract(value,'$.date'),length(json_extract(value,'$.reference'))
            FROM workspace,json_each(data,'$.longCareEvents')
            WHERE json_extract(value,'$.residentId')=? ORDER BY CAST(key AS INTEGER) DESC LIMIT 2""",
            (rid,),
        ).fetchall()
        if not meta or not events:
            raise ValueError("长护险经办记录缺少关联档案")
        event, status, day, referenced = events[0]
        previous = events[1] if len(events) == 2 else None
        if (
            event not in ALLOWED.get(previous[1] if previous else "", ())
            or STAGES.get(event) != status
            or not referenced
            or (previous and previous[2] > day)
        ):
            raise ValueError("长护险阶段、经办日期或文书编号未通过复核")
        checks.append("已按前一办理阶段核对流转顺序、日期及文书依据")
    elif action == "dossier.profile":
        from ..profile_fields import region_children

        row = db.execute(
            """SELECT json_extract(basic,'$.birthRegion.codes'),json_extract(basic,'$.addressRegion.codes'),
            json_type(household,'$.fundingSources'),json_extract(household,'$.pensionBand'),
            json_extract(household,'$.pensionAmount') FROM dossier_profiles WHERE resident_id=?""",
            (rid,),
        ).fetchone()
        if not meta or not row:
            raise ValueError("缺少已关联的个人档案资料")
        for raw in (row[0], row[1]):
            parent = "CN"
            for code in json.loads(raw) if raw else ():
                if code not in region_children(parent):
                    raise ValueError("档案的地址区划层级不一致")
                parent = code
        if row[2] not in (None, "array") or (
            row[3] == "精确金额" and row[4] in (None, "")
        ):
            raise ValueError("请核对费用来源选项和养老金金额")
        checks.append("已复核登记的区划层级及经济字段格式")
    elif domain == "备份":
        if (
            action
            in ("backup.create", "backup.apply", "backup.import", "backup.export")
            and actor.get("kind") != "owner"
        ):
            raise PermissionError("备份办理身份未通过机构审核")
        checks.append("已核对快照操作类别与经办身份")
    elif domain == "账号授权":
        owners = db.execute(
            "SELECT count(*) FROM accounts WHERE kind='owner' AND enabled=1"
        ).fetchone()[0]
        if owners != 1:
            raise ValueError("机构须保留一个可用的总管理员账号")
        checks.append("已核对账号操作后的总管理员可用性")
    elif domain == "账号凭据":
        invalid = db.execute("""SELECT count(*) FROM accounts WHERE length(password_hash)<>32 OR
            length(salt)<16 OR typeof(password_hash)<>'blob' OR typeof(salt)<>'blob'""").fetchone()[
            0
        ]
        if invalid:
            raise ValueError("账号凭据摘要的存储格式异常")
        checks.append("已核对盐和口令摘要的存储格式")
    else:
        if not meta:
            # Self-service relative updates may refer to the signed-in portal account.
            if action != "dossier.relative" or actor.get("kind") != "family":
                raise ValueError("审核 Agent 未能关联业务档案")
        checks.append("已核对经办记录与长者档案的关联")
    db.execute(
        "INSERT INTO history_agent_checks VALUES(?,?,?)",
        (revision, domain, json.dumps(checks, ensure_ascii=False)),
    )


def result(db, revision):
    row = db.execute(
        "SELECT domain,result FROM history_agent_checks WHERE revision=?", (revision,)
    ).fetchone()
    return (
        {"provider": "local", "domain": row[0], "checks": json.loads(row[1])}
        if row
        else None
    )
