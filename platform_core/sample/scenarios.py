"""Populate business ledgers in an explicitly selected demonstration institution."""

from secrets import token_urlsafe
from datetime import timedelta

from platform_core import facility, visit_schedule
from platform_core.operations import billing_lifecycle


class _Scenarios:
    def __init__(self, store, token):
        self.store = store
        self.token = token
        self.now = store.now()
        self.today = self.now.date().isoformat()
        self.count = 0
        self.refresh()

    def refresh(self):
        response = self.store.snapshot(self.token)
        self.data = response["data"]
        self.revision = response["revision"]

    def command(self, action, **payload):
        self.store.execute(action, payload, self.revision, self.token, comment="载入虚构业务演示")
        self.count += 1
        self.refresh()

    def find(self, collection, **fields):
        return next((r for r in self.data.get(collection, [])
                     if all(r.get(k) == v for k, v in fields.items())), None)

    def day(self, days):
        return (self.now.date() + timedelta(days=days)).isoformat()


def _reception(s):
    campus = facility.HOME_CAMPUS
    # North American 555-01xx numbers are reserved for fictional use and are never contacted.
    for name, phone, scenario in (
        ("程女士（演示）", "+12025550141", "callback"),
        ("宋先生（演示）", "+12025550142", "visit"),
        ("叶女士（演示）", "+12025550143", "archive"),
    ):
        lead = s.find("leadContacts", campusId=campus, phone=phone)
        if not lead:
            s.command("leads.register", campusId=campus, phone=phone, name=name,
                      channel="walkin" if scenario == "archive" else "incoming",
                      note="现场了解公共活动室。" if scenario == "archive" else "来电咨询房型与短期试住。",
                      occurredAt=s.now.isoformat(timespec="seconds"))
            lead = s.find("leadContacts", campusId=campus, phone=phone)
        if lead["name"] != name or lead["status"] == "已归档" or lead["callbackStopped"]:
            continue
        lid = lead["id"]
        if scenario == "archive":
            if not s.find("leadEvents", leadId=lid, kind="接待反馈"):
                s.command("leads.feedback", leadId=lid, feedback="已参观样板间，希望与家人商量后自行联络。",
                          occurredAt=s.now.isoformat(timespec="seconds"))
            s.command("leads.archive", leadId=lid, feedback="本次参观已完成，按访客意愿结案。")
            continue
        if lead["callbackExempt"]:
            continue
        if not s.find("leadEvents", leadId=lid, kind="回访"):
            s.command("leads.call", leadId=lid, direction="outgoing",
                      outcome="有参观意向" if scenario == "visit" else "继续联系",
                      feedback="已向访客介绍参观流程，电话核对了下次接待时间。" if scenario == "visit" else
                               "已介绍试住费用，约定再次回电。",
                      occurredAt=s.now.isoformat(timespec="seconds"))
        if not s.find("visitBookings", leadId=lid, kind=scenario):
            # Leave existing bookings and capacity intact if an older demo already uses these slots.
            for offset in range(1, 8):
                day = s.day(offset)
                schedule = visit_schedule.day_view(s.data, campus, day, s.now)
                slot = next((r for r in schedule["slots"] if r["bookable"] and
                             "09:00" <= r["start"] < "17:00"), None)
                if slot:
                    s.command("leads.book", leadId=lid, kind=scenario, date=day, start=slot["start"],
                              end=slot["end"], phoneConfirmed=True, feedback="演示电话确认记录")
                    break


def _stays(s):
    for name, age, gender, purpose in (
        ("邵清兰（演示）", 77, "女", "new"),
        ("葛怀春（演示）", 81, "男", "discharge"),
        ("夏月华（演示）", 74, "女", "trial"),
        ("江玉珊（演示）", 83, "女", "monthly"),
    ):
        resident = s.find("residents", name=name)
        if not resident:
            s.command("care.register", name=name, campusId=facility.HOME_CAMPUS, age=age, gender=gender)
            resident = s.find("residents", name=name)
        if purpose == "new":
            continue
        rid = resident["id"]
        if resident["status"] == "未入住" and not s.find("bedMoves", residentId=rid, kind="入住"):
            bed = next((b for b in s.data["beds"] if b["status"] == "空闲" and
                        s.data["bedDirectory"].get(b["id"], {}).get("campusId") == facility.HOME_CAMPUS), None)
            if not bed:
                continue
            if purpose == "trial":
                s.command("care.admit", residentId=rid, bedId=bed["id"], stayType="trial",
                          trialDays=3, trialPrice=240, paymentMode="offline",
                          offlinePayment={"amount": 240, "method": "线下登记", "channel": "现金"})
            else:
                s.command("care.admit", residentId=rid, bedId=bed["id"],
                          paymentMode="temporary", depositMonths=0)
            resident = s.find("residents", id=rid)
        if purpose == "discharge" and resident["status"] == "在住":
            s.command("care.discharge", residentId=rid, note="演示家庭已完成接回，登记退住并释放床位。")
        if purpose == "monthly" and resident["status"] == "在住" and not s.find("accounts", username="demo-family-jiang"):
            s.command("access.create", kind="family", username="demo-family-jiang", residentId=rid,
                      displayName="江女士（演示家属）", portalScopes=["billingNotices"],
                      password=token_urlsafe(32))


def _care(s):
    person = s.find("residents", id="r001", name="沈月兰", status="在住")
    if not person or not person.get("bedId"):
        return
    rid = person["id"]
    receipt_id = "96da204f-fea1-4e4b-b706-05bcbb5f8e2b"
    if not s.find("medicationReceipts", requestId=receipt_id):
        s.command("care.receiveMedication", residentId=rid, requestId=receipt_id,
                  name="培训药品样盒（演示）", specification="空包装，仅供交接演练", quantity=2,
                  unit="盒", source="家属交付", sender="演示家属", lot="DEMO-RX-01", expiry=s.day(180))
    if not s.find("longCareEvents", residentId=rid):
        s.command("ltci.record", residentId=rid, event="登记参保", date=s.today,
                  region={"codes": ["41", "4104", "410482"]}, insuranceType="城乡居民",
                  reference="演示参保-001", note="虚构经办材料")
    if not s.find("leaves", residentId=rid):
        start = max(person["admittedAt"], min(s.today, person.get("endDate") or s.today))
        if start <= s.today:
            s.command("care.leave", residentId=rid, startDate=start, endDate=start, reason="家属陪同短时外出（演示）")
    event_id = "demo-radar-room-01"
    if not any(o["eventId"] == event_id for r in s.data["gatewayAlerts"] for o in r["observations"]):
        s.command("gw.ingest", source="radar", signal="possible_fall", bedId=person["bedId"],
                  eventId=event_id, evidenceRef="DEMO-RADAR-01", observation="模拟雷达测试信号，待值班人员到场核实。")

    username = "demo-shift-nurse"
    receiver = s.find("accounts", username=username)
    if not receiver:
        s.command("access.create", kind="staff", role="护士", username=username, displayName="杜青（演示护士）",
                  campusId=facility.HOME_CAMPUS, password=token_urlsafe(32))
        receiver = s.find("accounts", username=username)
    if receiver and receiver["enabled"] and not s.find("handovers", assigneeId=receiver["id"], residentId=rid):
        s.command("care.handover", residentId=rid, assigneeId=receiver["id"],
                  note="请接班时核对床旁呼叫铃与家属交来的演示药盒，并登记核对结果。")
    item = s.find("inventory", id="stock-2", name="成人护理垫")
    title = "核对床旁护理垫并登记领用（演示）"
    if item and not s.find("tasks", residentId=rid, title=title):
        s.command("care.addTask", residentId=rid, title=title, kind="物资领用", assignee=receiver["displayName"],
                  date=s.today, time="15:00", note="按床旁实际需要核对物资，经护理用品台账办理领用。")
    if item and not s.find("transactions", note=title) and item["quantity"] > 0:
        s.command("ops.stock", itemId=item["id"], type="出库", quantity=1, note=title)


def _finance(s):
    if not s.find("expenses", voucher="DEMO-ENERGY-001"):
        s.command("ops.expense", category="设施", voucher="DEMO-ENERGY-001", amount=386.50,
                  date=s.today, payee="示范园区服务站（虚构）", note="活动室照明维护")
    ref = "DEMO-PAYMENT-001"
    if not s.find("payments", paymentRef=ref):
        bill = next((b for b in s.data["bills"] if b["residentId"] == "r002" and b["balance"] > 0), None)
        if bill and s.find("residents", id="r002", name="徐松年"):
            s.command("ops.pay", billId=bill["id"], amount=min(bill["balance"], 200),
                      paymentRef=ref, method="线下登记", channel="银行转账")
    # The same in-app reminders are visible to family accounts with a matching resident and grant.
    billing_lifecycle.tick(s.store)


def seed_scenarios(store, token):
    """Fill missing fictional scenarios using the institution's normal audited commands."""
    s = _Scenarios(store, token)
    if s.data["user"]["kind"] != "owner":
        raise PermissionError("请使用演示机构的 Owner 载入业务演示")
    _reception(s)
    _stays(s)
    _care(s)
    _finance(s)
    return s.count
