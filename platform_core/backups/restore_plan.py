"""Describe and apply an authenticated business restore inside the live transaction."""

import json

# Live identity, grants, payer callbacks, AI quotas and audit have their own authority.
# Live originals may only be extended. These tables support replacement of mutable records.
MUTABLE = {
    "staff_paydays": "员工工资日",
    "facility_buildings": "楼栋",
    "facility_campuses": "分院",
    "facility_building_campus": "楼栋归属",
    "facility_floors": "楼层",
    "facility_rooms": "房间",
    "facility_beds": "房间床位",
    "facility_plans": "楼层平面图",
    "facility_scenes": "导览场景",
    "facility_media": "导览资源",
    "dossier_profiles": "长者档案资料",
    "dossier_relatives": "亲属档案资料",
    "rounds_modes": "长者巡查生成设置",
    "rounds_policy": "机构巡查排程设置",
}
ORIGINALS = {
    "resident_health_notes": "长者健康简介和个人谈话记录",
    "daily_life_events": "集体活动登记",
    "daily_life_invitees": "活动候选名单",
    "daily_life_signatures": "活动签认凭证",
    "daily_life_attendance": "个人活动与进食记录",
    "dossier_visit_records": "已签认就诊病例",
    "dossier_visit_originals": "就诊附件原件",
    "staff_contract_originals": "劳动合同原件",
    "staff_contract_versions": "员工合同留存版本",
    "dossier_documents": "医疗原件",
    "dossier_document_reviews": "文书签认",
    "storage_assets": "环境与历史原件",
    "protected_documents": "签发的加密文书",
    "rounds_observations": "已核对咳嗽时段观测",
    "rounds_reports": "已生成的长者巡查简报",
}
# A point-in-time restore cannot retract external actions, recorded clinical observations or cash.
PROTECTED = {
    "leadContacts": "意向客户与回访意愿",
    "leadEvents": "来电、回访与接待记录",
    "visitBookings": "已确认的接待排期与变更",
    "trialFollowups": "试住回访及报告",
    "longCareEvents": "长护险办理凭证",
    "payments": "收款凭证",
    "bills": "账单",
    "paymentOrders": "支付订单",
    "channelReceipts": "渠道回执",
    "deposits": "预存余额",
    "depositEntries": "预存流水",
    "expenses": "支出流水",
    "transactions": "库存流水",
    "reports": "报送记录",
    "referrals": "转介与授权",
    "medications": "给药记录",
    "vitals": "生命体征",
    "handovers": "交班签收",
    "archives": "医疗归档",
    "assessments": "评估记录",
    "qualityChecks": "质检记录",
    "supplyOrders": "已发布的物资工单",
    "staffNotices": "已发布的全员通知",
}
LABELS = {
    **PROTECTED,
    "visitSchedulePolicies": "院区并行接待席位",
    "beds": "床位",
    "residents": "长者",
    "inquiries": "入住咨询",
    "plans": "照护计划",
    "tasks": "护理工单",
    "bedMoves": "床位变动",
    "followups": "随访",
    "drugRules": "用药规则",
    "inventory": "库存",
    "shifts": "排班",
    "careTimelineSettings": "老人和房间时间线设置",
    "suggestions": "工作建议",
    "leaves": "请假外出",
}


RECEPTION_COLLECTIONS = ("leadContacts", "leadEvents", "visitBookings", "visitSchedulePolicies")


def with_reception_collections(state):
    # Snapshots taken before the reception desk opened represent empty reception ledgers.
    for key in RECEPTION_COLLECTIONS:
        state.setdefault(key, [])
    return state


def attach(db, path, store):
    from .. import secure_storage

    key = secure_storage.derive(store._storage_master, b"database")
    db.execute(
        "ATTACH DATABASE ? AS incoming KEY ?", (str(path), "x'" + key.hex() + "'")
    )


def absent(db, table, target, *, compare_values=True):
    # Resolve each source record by indexed primary key; large original BLOBs never enter
    # a sorted EXCEPT table, a JSON audit payload, or the application response.
    columns = list(db.execute(f'PRAGMA main.table_info("{table}")'))
    pks = [r[1] for r in columns if r[5]]
    if not pks:
        raise ValueError("业务表缺少主键")
    names = pks + ([r[1] for r in columns if not r[5]] if compare_values else [])
    comparisons = " AND ".join(f't."{name}" IS s."{name}"' for name in names)
    return f'NOT EXISTS(SELECT 1 FROM {target}."{table}" t WHERE {comparisons})'


def difference_count(db, table, origin, target):
    return db.execute(
        f'SELECT count(*) FROM {origin}."{table}" s WHERE ' + absent(db, table, target)
    ).fetchone()[0]


def completed(rows):
    return {
        x["id"]: x for x in rows if x.get("completedAt") or x.get("status") == "已完成"
    }


OPTIONAL_TABLES = {
    "resident_health_notes",
    "daily_life_events",
    "daily_life_invitees",
    "daily_life_signatures",
    "daily_life_attendance",
    "dossier_visit_records",
    "dossier_visit_originals",
    "staff_paydays",
    "staff_contract_originals",
    "staff_contract_versions",
    "rounds_modes",
    "rounds_policy",
    "rounds_observations",
    "rounds_reports",
}


def supported_tables(db, group):
    # Snapshots from before rounding was introduced have no representation of
    # these records. Preserve the live records and configuration during import.
    present = {
        r[0]
        for r in db.execute(
            "SELECT name FROM incoming.sqlite_master WHERE type='table'"
        )
    }
    return {k: v for k, v in group.items() if k not in OPTIONAL_TABLES or k in present}


def describe(db):
    def field(schema, query):
        return db.execute(query.format(s=schema)).fetchone()[0]

    if field("main", "SELECT id FROM {s}.facility_site") != field(
        "incoming", "SELECT id FROM {s}.facility_site"
    ):
        raise ValueError("备份所属机构与本机构不一致")
    source = with_reception_collections(json.loads(field("incoming", "SELECT data FROM {s}.workspace WHERE id=1")))
    live = json.loads(field("main", "SELECT data FROM {s}.workspace WHERE id=1"))
    changes = []
    blockers = []
    expired_ids = {r[0] for r in db.execute("SELECT resident FROM archive_expirations")}
    if any(
        r["id"] in expired_ids and r.get("status") != "归档到期"
        for r in source.get("residents", ())
    ):
        blockers.append("快照包含已满 365 天并清理的日常档案")
    sealed = {r["id"] for r in live.get("residents", ()) if r.get("status") == "已退住"}
    if any(
        r["id"] in sealed and r.get("status") != "已退住"
        for r in source.get("residents", ())
    ):
        blockers.append("已退住的只读档案不可恢复为待入住或在住")
    if source.keys() != live.keys():
        blockers.append("业务集合版本不同")
    for key in sorted(live.keys() | source.keys()):
        current = live.get(key, [])
        wanted = source.get(key, [])
        if current == wanted:
            continue
        if not isinstance(current, list) or not isinstance(wanted, list):
            blockers.append("业务数据格式不同")
            continue
        name = LABELS.get(key, key)
        changes.append(
            {"label": name, "current": len(current), "incoming": len(wanted)}
        )
        if key in PROTECTED:
            blockers.append(name)
        if key == "tasks":
            if completed(current) != completed(wanted):
                blockers.append("已完成护理工单")
        if key == "residents" and {r["id"] for r in current} - {
            r["id"] for r in wanted
        }:
            blockers.append("当前已建档长者在选定时间点缺失")

    live_campuses = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT campus_id FROM accounts WHERE campus_id IS NOT NULL AND campus_id<>''"
        )
    }
    next_campuses = {
        r[0] for r in db.execute("SELECT id FROM incoming.facility_campuses")
    }
    if not live_campuses <= next_campuses:
        blockers.append("当前员工授权的分院在选定时间点缺失")

    for table, label in supported_tables(db, {**MUTABLE, **ORIGINALS}).items():
        removed = difference_count(db, table, "main", "incoming")
        added = difference_count(db, table, "incoming", "main")
        if not (removed or added):
            continue
        changes.append(
            {
                "label": label,
                "current": field("main", f'SELECT count(*) FROM {{s}}."{table}"'),
                "incoming": field("incoming", f'SELECT count(*) FROM {{s}}."{table}"'),
            }
        )
        if removed and table in ORIGINALS:
            blockers.append(label)

    # Rewinding a task or assignment while a recorded external event refers to it could replay it.
    for table, label in (
        ("gateway_voice", "语音确认"),
        ("gateway_alert", "设备预警"),
        ("dossier_ocr_jobs", "识别任务"),
    ):
        if difference_count(db, table, "main", "incoming") or difference_count(
            db, table, "incoming", "main"
        ):
            blockers.append(label)
    missing_staff = db.execute(
        "SELECT count(*) FROM incoming.accounts s WHERE kind='staff' AND NOT EXISTS(SELECT 1 FROM accounts a WHERE a.id=s.id)"
    ).fetchone()[0]
    if missing_staff:
        blockers.append("快照含当前机构未授权的员工账号")
    return {
        "sourceRevision": field(
            "incoming", "SELECT revision FROM {s}.workspace WHERE id=1"
        ),
        "currentRevision": field(
            "main", "SELECT revision FROM {s}.workspace WHERE id=1"
        ),
        "residents": len(source["residents"]),
        "staff": field(
            "incoming", "SELECT count(*) FROM {s}.accounts WHERE kind='staff'"
        ),
        "documents": field("incoming", "SELECT count(*) FROM {s}.dossier_documents"),
        "changes": changes,
        "blockers": blockers,
    }


def apply(db):
    # Child references are checked after all related tables have been restored.
    db.execute("PRAGMA defer_foreign_keys=ON")
    mutable = supported_tables(db, MUTABLE)
    for name in reversed(mutable):
        db.execute(
            f'DELETE FROM main."{name}" AS s WHERE ' + absent(db, name, "incoming")
        )
    for name in mutable:
        db.execute(
            f'INSERT INTO main."{name}" SELECT s.* FROM incoming."{name}" AS s WHERE '
            + absent(db, name, "main", compare_values=False)
        )
    for name in supported_tables(db, ORIGINALS):
        db.execute(
            f'INSERT INTO main."{name}" SELECT s.* FROM incoming."{name}" AS s WHERE '
            + absent(db, name, "main", compare_values=False)
        )
    raw = db.execute("SELECT data FROM incoming.workspace WHERE id=1").fetchone()[0]
    state = json.loads(raw)
    if any(key not in state for key in RECEPTION_COLLECTIONS):
        raw = json.dumps(with_reception_collections(state), ensure_ascii=False, separators=(",", ":"))
    db.execute("UPDATE workspace SET data=? WHERE id=1", (raw,))
    if db.execute("PRAGMA main.foreign_key_check").fetchone():
        raise ValueError("恢复数据与当前授权机构的关联记录不一致")
