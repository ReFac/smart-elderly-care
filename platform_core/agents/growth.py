"""Institution-owned presentation skills shared by Pi and DeerFlow.

The text employees use to describe a correction is transient. Only ordered, reviewed
evidence categories cross the publication boundary, never patient text, executable
code, a tool permission, or an instruction copied from a document.
"""

from contextlib import closing
import json
from uuid import uuid4

from .. import access_policy as policy, activity, facility, history

# Each clause stays attributable to a known source. A rule changes the way an
# authorised draft is presented; it cannot create a fact or expand a data query.
TOPICS = {
    "meals": (
        "用餐简报",
        "care",
        ("chat", "daily-life"),
        {
            "intake": (
                "实际摄入",
                "只在有个人进食观察时写明吃了什么、吃了多少。",
                ("摄入", "实际吃", "吃了", "吃过", "进食"),
            ),
            "attendance": (
                "出席记录",
                "签到只说明参加了这顿饭。",
                ("签到", "到场", "参加", "出席"),
            ),
            "menu": (
                "当日菜单",
                "餐单仅说明供应了哪些菜品。",
                ("餐单", "菜单", "供应"),
            ),
        },
    ),
    "handover": (
        "护理交班",
        "care",
        ("chat", "daily-life"),
        {
            "pending": (
                "待签认事项",
                "仅列台账中仍待签认的事项。",
                ("待签", "待办", "未完成", "未签"),
            ),
            "done": ("已完成事项", "已签认的工作可列入完成事项。", ("完成", "已签")),
            "source": (
                "记录来源",
                "列出有权查看的来源和记录日期。",
                ("来源", "依据", "日期"),
            ),
        },
    ),
    "visit": (
        "就诊资料核对",
        "medical",
        ("chat", "medical-documents"),
        {
            "visit": (
                "就诊日期",
                "就诊日期取自原件中明确标为就诊的日期。",
                ("就诊日期", "就医日期"),
            ),
            "issued": (
                "签发日期",
                "原件签发或打印日期单独标注。",
                ("签发", "打印", "出具"),
            ),
            "source": (
                "文书出处",
                "列明核对过的文书及其页码。",
                ("文书", "来源", "页码", "出处"),
            ),
        },
    ),
    "observations": (
        "健康变化简报",
        "clinical",
        ("chat", "health-review"),
        {
            "change": (
                "已核实变化",
                "仅列有观察记录支持的变化。",
                ("变化", "变化趋势"),
            ),
            "time": ("观察时间", "区分记录日期与事件实际发生时间。", ("日期", "时间")),
            "source": (
                "观察依据",
                "保留本次观察的凭证出处。",
                ("凭证", "出处", "依据", "来源"),
            ),
        },
    ),
}


def init(db):
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_proposals (
        id TEXT PRIMARY KEY, campus TEXT NOT NULL, topic TEXT NOT NULL, ordering TEXT NOT NULL,
        base INTEGER NOT NULL, author TEXT NOT NULL, created TEXT NOT NULL,
        decision TEXT NOT NULL DEFAULT 'pending', reviewer TEXT, reviewed TEXT)""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS agent_rule_pending
        ON agent_rule_proposals(campus,topic,ordering,base,author) WHERE decision='pending'""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_releases (
        campus TEXT NOT NULL, topic TEXT NOT NULL, version INTEGER NOT NULL, ordering TEXT NOT NULL,
        actor TEXT NOT NULL, created TEXT NOT NULL, proposal TEXT, reason TEXT NOT NULL,
        PRIMARY KEY(campus,topic,version))""")
    db.execute(
        """CREATE INDEX IF NOT EXISTS agent_rule_inbox ON agent_rule_proposals(campus,decision,created DESC)"""
    )


def _audit(db, campus, topic, operation, actor, now, version):
    revision = db.execute("SELECT revision+1 FROM workspace WHERE id=1").fetchone()[0]
    db.execute("UPDATE workspace SET revision=? WHERE id=1", (revision,))
    label = {
        "propose": "提出",
        "approve": "发布",
        "reject": "驳回",
        "rollback": "恢复",
    }[operation]
    activity.write(
        db,
        revision,
        now,
        "learning." + operation,
        f"{label}{TOPICS[topic][0]}规则（v{version}）",
        actor,
        {"campusId": campus},
        {},
    )


def _campuses(db, actor):
    if (
        not actor
        or actor.get("kind") not in ("staff", "owner")
        or not policy.has(actor, "assistants")
    ):
        return {}
    acl = facility._access(db, actor, environment=True)
    limits = actor.get("facilityScope") or {}
    if any(key in limits for key in ("roomIds", "floorIds", "buildingIds")):
        where, args = facility._restrictions(acl)
        query = (
            "SELECT DISTINCT b.campusId,b.campusName FROM "
            + facility.ROOM_TABLE
            + where
        )
        return dict(db.execute(query, args))
    return {
        key: name
        for key, name in db.execute("SELECT id,name FROM facility_campuses")
        if acl.campuses is None or key in acl.campuses
    }


def _can_review(actor):
    return policy.has(actor, "assistants.reviewRules") and not any(
        k in (actor.get("facilityScope") or {})
        for k in ("roomIds", "buildingIds", "floorIds")
    )


def _can_use(actor, topic):
    return policy.has(actor, TOPICS[topic][1]) and (
        topic != "observations" or policy.has(actor, "medical")
    )


def _current(db, campus, topic):
    row = db.execute(
        """SELECT version,ordering FROM agent_rule_releases WHERE campus=? AND topic=?
        ORDER BY version DESC LIMIT 1""",
        (campus, topic),
    ).fetchone()
    return (row[0], json.loads(row[1])) if row else (0, [])


MISSING = {
    "missing-skip": ("略去缺少依据的项目", "没有该项证据时略过，已记录事实照常保留。"),
    "missing-note": ("列明待核对项", "缺少依据时明确提示该项待核对，不作事实推断。"),
}


def _instruction(topic, order):
    clauses = TOPICS[topic][3]
    sections = [key for key in order if key in clauses]
    return (
        "依次呈现"
        + "、".join(clauses[k][0] for k in sections)
        + "。"
        + "".join(clauses[k][1] for k in sections)
        + MISSING[order[-1]][1]
    )


def guidance(db, actor, channel, *, campus_id="", bed_id=""):
    """Return current skills only for the authorised campus, domain and audience.

    Background resident specialists must pass a bed resolved from a verified
    stay. An unspecified staff scope can resolve only when exactly one campus
    is accessible. The caller still rechecks all underlying business evidence.
    """
    if bed_id:
        row = db.execute(
            "SELECT b.campusId FROM "
            + facility.ROOM_TABLE
            + " JOIN facility_beds beds ON beds.roomId=r.id WHERE beds.bedId=?",
            (bed_id,),
        ).fetchone()
        if not row or (campus_id and campus_id != row[0]):
            return ""
        campus_id = row[0]
    if actor is None:
        if not bed_id or channel not in ("daily-life", "health-review"):
            return ""
    else:
        allowed = _campuses(db, actor)
        if not campus_id and len(allowed) == 1:
            campus_id = next(iter(allowed))
        if campus_id not in allowed:
            return ""
    result = []
    for topic, (label, _, channels, _) in TOPICS.items():
        if channel not in channels or (actor and not _can_use(actor, topic)):
            continue
        version, order = _current(db, campus_id, topic)
        if order:
            result.append(f"{label} v{version}：{_instruction(topic, order)}")
    return "\n".join(result)


def _area_and_topic(db, actor, body):
    campus, topic = body.get("campusId"), body.get("topic")
    if not isinstance(campus, str) or campus not in _campuses(db, actor):
        raise PermissionError("请选择当前账号有权使用的院区")
    if not isinstance(topic, str) or topic not in TOPICS or not _can_use(actor, topic):
        raise PermissionError("当前岗位未获准维护该类工作方法")
    return campus, topic


def _order(topic, value):
    keys = TOPICS[topic][3]
    if (
        not isinstance(value, list)
        or len(value) != len(keys) + 1
        or not all(isinstance(v, str) for v in value)
        or set(value[:-1]) != set(keys)
        or value[-1] not in MISSING
    ):
        raise ValueError("请逐项核对规则的顺序")
    return value


def _suggest(topic, correction):
    if not isinstance(correction, str) or not 1 <= len(correction.strip()) <= 1200:
        raise ValueError("请输入本次要改进的写作方法")
    positions = {}
    for key, (_, _, terms) in TOPICS[topic][3].items():
        matches = [correction.index(term) for term in terms if term in correction]
        if matches:
            positions[key] = min(matches)
    if not positions:
        raise ValueError("暂未识别对应的证据类别，请说明想先呈现哪一项，或直接调整顺序")
    missing = (
        "missing-note"
        if any(term in correction for term in ("待核对", "请核对", "注明缺", "标明缺"))
        else "missing-skip"
    )
    return [
        *sorted(TOPICS[topic][3], key=lambda k: positions.get(k, len(correction) + 1)),
        missing,
    ]


EXAMPLES = {
    "meals": {
        "intake": "实际喝了半碗粥",
        "attendance": "早餐已签到",
        "menu": "餐单列有鸡蛋",
    },
    "handover": {
        "pending": "晚间巡视待签认",
        "done": "早餐协助已签认",
        "source": "当日护理台账",
    },
    "visit": {
        "visit": "就诊日期为五月八日",
        "issued": "打印日期为五月九日",
        "source": "就诊单第一页",
    },
    "observations": {
        "change": "已复核一条体温变化",
        "time": "本次观察在早班",
        "source": "已签认的观察记录",
    },
}


def _examples(topic, order, previous):
    """Replay two fictional inputs against the ordered template; no LLM or resident data."""
    facts = EXAMPLES[topic]
    result = []
    for name, available in (
        ("完整记录", facts),
        ("仅有一项记录", {list(facts)[-1]: list(facts.values())[-1]}),
    ):

        def render(recipe):
            values = [available[k] for k in recipe if k in available]
            if "missing-note" in recipe:
                values += [
                    TOPICS[topic][3][k][0] + "待核对"
                    for k in recipe
                    if k in facts and k not in available
                ]
            return values

        before, after = render(previous or facts), render(order)
        if any(after.count(value) != 1 for value in available.values()) or any(
            value in after for key, value in facts.items() if key not in available
        ):
            raise ValueError("规则回放未能保留原始证据")
        result.append({"case": name, "before": before, "after": after})
    return result


def _body(body, fields):
    if not isinstance(body, dict) or not set(body) <= set(fields):
        raise ValueError("规则操作参数无效")


def _view(db, actor):
    campuses = _campuses(db, actor)
    if not campuses:
        raise PermissionError("当前账号无可用院区")
    review = _can_review(actor)
    topics = [
        {
            "id": k,
            "label": v[0],
            "parts": [{"id": key, "label": val[0]} for key, val in v[3].items()],
        }
        for k, v in TOPICS.items()
        if _can_use(actor, k)
    ]
    return {
        "canReview": review,
        "campuses": [{"id": k, "name": v} for k, v in campuses.items()],
        "topics": topics,
        "missing": [{"id": k, "label": v[0]} for k, v in MISSING.items()],
    }


def read(store, token, campus="", topic=""):
    with closing(store.connect()) as db:
        actor = store.actor(db, token)
        view = _view(db, actor)
        if not (campus and topic):
            return view
        _area_and_topic(db, actor, {"campusId": campus, "topic": topic})
        version, order = _current(db, campus, topic)
        query = """SELECT p.id,p.author,p.created,p.ordering,p.base,p.decision,p.reviewer,p.reviewed,
            (SELECT ordering FROM agent_rule_releases r WHERE r.campus=p.campus AND r.topic=p.topic AND r.version=p.base) AS previous
            FROM agent_rule_proposals p WHERE campus=? AND topic=?"""
        args = [campus, topic]
        if not view["canReview"]:
            query += " AND author=?"
            args.append(actor["id"])
        rows = db.execute(
            query
            + " ORDER BY (decision='pending') DESC,created DESC,rowid DESC LIMIT 100",
            args,
        )
        changes = []
        for row in rows:
            item = dict(row)
            item["order"] = json.loads(item.pop("ordering"))
            item["instruction"] = _instruction(topic, item["order"])
            item["examples"] = _examples(
                topic, item["order"], json.loads(item.pop("previous") or "[]")
            )
            changes.append(item)
        releases = [
            dict(row)
            for row in db.execute(
                """SELECT version,actor,created,reason,proposal,ordering
                   FROM agent_rule_releases WHERE campus=? AND topic=? ORDER BY version DESC LIMIT 100""",
                (campus, topic),
            )
        ]
        for row in releases:
            values = json.loads(row.pop("ordering"))
            row["instruction"] = _instruction(topic, values) if values else ""
        return {
            **view,
            "version": version,
            "order": order,
            "proposals": changes,
            "releases": releases,
        }


def change(store, token, operation, body):
    fields = {
        "preview": ("campusId", "topic", "correction", "order"),
        "propose": ("campusId", "topic", "base", "order"),
        "review": (
            "campusId",
            "topic",
            "base",
            "decision",
            "proposalId",
            "restoreVersion",
        ),
    }
    if operation not in fields:
        raise FileNotFoundError("未找到此规则操作")
    _body(body, fields[operation])
    with closing(store.connect()) as db, db:
        if operation != "preview":
            db.execute("BEGIN IMMEDIATE")
        actor = store.actor(db, token)
        campus, topic = _area_and_topic(db, actor, body)
        version, previous = _current(db, campus, topic)
        if operation == "preview":
            order = (
                _order(topic, body["order"])
                if "order" in body
                else _suggest(topic, body.get("correction"))
            )
            return {
                "order": order,
                "instruction": _instruction(topic, order),
                "base": version,
                "examples": _examples(topic, order, previous),
            }
        if type(body.get("base")) is not int or body["base"] != version:
            from ..store import Conflict

            raise Conflict("规则已更新，请重新查看或提出建议")
        history.watch(db, "learning.edit")
        now = store.now().isoformat(timespec="seconds")
        if operation == "propose":
            order = _order(topic, body.get("order"))
            encoded = json.dumps(order)
            if order == previous:
                raise ValueError("此顺序已经生效")
            # Replayed inside the same transaction as the proposal. Raw correction,
            # conversation and clinical text are never written to this ledger.
            _examples(topic, order, previous)
            existing = db.execute(
                """SELECT id FROM agent_rule_proposals WHERE campus=? AND topic=?
                AND ordering=? AND base=? AND author=? AND decision='pending'""",
                (campus, topic, encoded, version, actor["id"]),
            ).fetchone()
            if existing:
                return {"id": existing[0], "decision": "pending"}
            key = uuid4().hex
            db.execute(
                """INSERT INTO agent_rule_proposals(id,campus,topic,ordering,base,author,created)
                VALUES(?,?,?,?,?,?,?)""",
                (key, campus, topic, encoded, version, actor["id"], now),
            )
            _audit(db, campus, topic, "propose", actor, now, version)
            return {"id": key, "decision": "pending"}
        if not _can_review(actor):
            raise PermissionError("规则发布需具有本院区的规则审核权限")
        decision = body.get("decision")
        proposal_id = None
        if decision in ("approve", "reject"):
            proposal_id = body.get("proposalId")
            if not isinstance(proposal_id, str):
                raise ValueError("请选择待审核的建议")
            row = db.execute(
                """SELECT ordering,base,decision FROM agent_rule_proposals
                WHERE id=? AND campus=? AND topic=?""",
                (proposal_id, campus, topic),
            ).fetchone()
            if not row or row[2] != "pending":
                raise ValueError("此建议已处理或不存在")
            if decision == "approve" and row[1] != version:
                raise ValueError("建议对应的旧版已改变，请重新提出")
            db.execute(
                "UPDATE agent_rule_proposals SET decision=?,reviewer=?,reviewed=? WHERE id=?",
                (decision, actor["id"], now, proposal_id),
            )
            if decision == "reject":
                _audit(db, campus, topic, decision, actor, now, version)
                return {"decision": decision, "version": version}
            order = _order(topic, json.loads(row[0]))
            _examples(topic, order, previous)
        elif decision == "rollback":
            target = body.get("restoreVersion")
            if type(target) is not int or not 0 <= target < version:
                raise ValueError("请选择更早的规则版本")
            old = db.execute(
                """SELECT ordering FROM agent_rule_releases
                WHERE campus=? AND topic=? AND version=?""",
                (campus, topic, target),
            ).fetchone()
            if target and not old:
                raise ValueError("未找到历史版本")
            order = json.loads(old[0]) if old else []
        else:
            raise ValueError("请确认审核结果")
        db.execute(
            "INSERT INTO agent_rule_releases VALUES(?,?,?,?,?,?,?,?)",
            (
                campus,
                topic,
                version + 1,
                json.dumps(order),
                actor["id"],
                now,
                proposal_id,
                decision,
            ),
        )
        _audit(db, campus, topic, decision, actor, now, version + 1)
        return {"decision": decision, "version": version + 1}
