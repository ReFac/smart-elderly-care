"""Institution-owned writing skills reviewed by DeerFlow before human publication.

The text employees use to describe a correction is transient. Only ordered, reviewed
evidence categories cross the publication boundary, never patient text, executable
code, a tool permission, or an instruction copied from a document.
"""

from contextlib import closing
import json
from uuid import uuid4

from ..provider import generation

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
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_reviews (
        proposal TEXT PRIMARY KEY REFERENCES agent_rule_proposals(id), receipt TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_releases (
        campus TEXT NOT NULL, topic TEXT NOT NULL, version INTEGER NOT NULL, ordering TEXT NOT NULL,
        actor TEXT NOT NULL, created TEXT NOT NULL, proposal TEXT, reason TEXT NOT NULL,
        PRIMARY KEY(campus,topic,version))""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_skill_artifacts (
        campus TEXT NOT NULL, topic TEXT NOT NULL, digest TEXT NOT NULL, document TEXT NOT NULL,
        body TEXT NOT NULL, report TEXT NOT NULL, PRIMARY KEY(campus,topic,digest))""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_experience_drafts (
        actor TEXT NOT NULL, campus TEXT NOT NULL, topic TEXT NOT NULL, version INTEGER NOT NULL,
        id TEXT NOT NULL, ordering TEXT NOT NULL, evidence TEXT NOT NULL,
        PRIMARY KEY(actor,campus,topic))""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_proposal_sources (
        proposal TEXT PRIMARY KEY REFERENCES agent_rule_proposals(id),
        baseline TEXT NOT NULL, evidence TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS agent_rule_release_skills (
        campus TEXT NOT NULL, topic TEXT NOT NULL, version INTEGER NOT NULL, digest TEXT NOT NULL,
        PRIMARY KEY(campus,topic,version),
        FOREIGN KEY(campus,topic,digest) REFERENCES agent_rule_skill_artifacts(campus,topic,digest))""")
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
        "gateway-export": "授权同步",
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
            artifact = _released_skill(db, campus_id, topic, version)
            text = artifact["body"] if artifact else _instruction(topic, order)
            result.append(f"{label} v{version}：{text}")
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


def read(store, token, campus="", topic="", proposal=""):
    with closing(store.connect()) as db:
        actor = store.actor(db, token)
        view = _view(db, actor)
        if not (campus and topic):
            if proposal:
                raise ValueError("查看检查报告需要选择院区和主题")
            return view
        _area_and_topic(db, actor, {"campusId": campus, "topic": topic})
        if proposal:
            row = db.execute("""SELECT p.author,p.decision,s.baseline,s.evidence FROM agent_rule_proposals p
                LEFT JOIN agent_rule_proposal_sources s ON s.proposal=p.id
                WHERE p.campus=? AND p.topic=? AND p.id=?""", (campus, topic, proposal)).fetchone()
            if not row or (row["author"] != actor["id"] and not _can_review(actor)):
                raise FileNotFoundError("未找到可查看的建议")
            artifact = _stored_proposal(db, campus, topic, proposal)
            return {"id": proposal, "decision": row["decision"], "baselineDocument": row["baseline"],
                    "candidateDocument": artifact["document"] if artifact else None,
                    "report": json.loads(artifact["report"]) if artifact else None,
                    "experience": json.loads(row["evidence"]) if row["evidence"] else None}
        version, order = _current(db, campus, topic)
        query = """SELECT p.id,p.author,p.created,p.ordering,p.base,p.decision,p.reviewer,p.reviewed,
            (SELECT receipt FROM agent_rule_reviews WHERE proposal=p.id) AS receipt,
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
            item["skillReview"] = json.loads(item.pop("receipt") or "null")
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


def _candidate(db, actor, operation, body, campus, topic, version):
    if operation != "preview" and (type(body.get("base")) is not int or body["base"] != version):
        from ..store import Conflict
        raise Conflict("规则已更新，请重新查看或提出建议")
    if operation != "review":
        if "experience" in body:
            if body["experience"] is not True or "order" in body or "correction" in body:
                raise ValueError("请单独选择从审核记录生成建议")
            return None
        if "order" in body or operation == "propose":
            return _order(topic, body.get("order"))
        return _suggest(topic, body.get("correction"))
    if not _can_review(actor):
        raise PermissionError("规则发布需具有本院区的规则审核权限")
    decision = body.get("decision")
    if decision in ("approve", "reject"):
        key = body.get("proposalId")
        if not isinstance(key, str):
            raise ValueError("请选择待审核的建议")
        row = db.execute("""SELECT ordering,base,decision FROM agent_rule_proposals
            WHERE id=? AND campus=? AND topic=?""", (key, campus, topic)).fetchone()
        if not row or row[2] != "pending":
            raise ValueError("此建议已处理或不存在")
        if decision == "reject":
            return []
        if row[1] != version:
            raise ValueError("建议对应的旧版已改变，请重新提出")
        return _order(topic, json.loads(row[0]))
    if decision == "rollback":
        target = body.get("restoreVersion")
        if type(target) is not int or not 0 <= target < version:
            raise ValueError("请选择更早的规则版本")
        old = db.execute("""SELECT ordering FROM agent_rule_releases
            WHERE campus=? AND topic=? AND version=?""", (campus, topic, target)).fetchone()
        if target and not old:
            raise ValueError("未找到历史版本")
        return json.loads(old[0]) if old else []
    raise ValueError("请确认审核结果")


def _experience(db, actor, campus, topic):
    query = """SELECT decision,ordering FROM agent_rule_proposals
        WHERE campus=? AND topic=? AND decision IN ('approve','reject')"""
    args = (campus, topic)
    if not _can_review(actor):
        query += " AND author=?"
        args += (actor["id"],)
    # Keep a bounded, anonymous projection. No feedback text, actor ID or resident
    # information enters the model. Identical evidence reuses its metered result.
    groups = {}
    for decision, raw in db.execute(query + " ORDER BY reviewed DESC,rowid DESC LIMIT 40", args):
        key = (decision, tuple(_order(topic, json.loads(raw))))
        groups[key] = groups.get(key, 0) + 1
    if not groups:
        raise ValueError("还没有可用于学习的已审核建议。可以先手动提出写作规则，审核后再试。")
    return [{"decision": decision, "order": order, "count": count}
            for (decision, order), count in sorted(groups.items())]


def _document(topic, order):
    label = TOPICS[topic][0]
    return (f"---\nname: careops-{topic}\ndescription: 在{label}中按审核通过的顺序呈现有据可查的观察。"
            f"\n---\n\n# {label}\n\n"
            + (_instruction(topic, order) if order else "按系统默认顺序列出已有证据。") + "\n")


def _released_skill(db, campus, topic, version):
    return db.execute("""SELECT a.* FROM agent_rule_release_skills r
        JOIN agent_rule_skill_artifacts a USING(campus,topic,digest)
        WHERE r.campus=? AND r.topic=? AND r.version=?""", (campus, topic, version)).fetchone()


def _stored_proposal(db, campus, topic, proposal):
    # Legacy proposals have ordering only, and are reviewed again before first use.
    return db.execute("""SELECT a.* FROM agent_rule_reviews r
        JOIN agent_rule_skill_artifacts a ON a.digest=json_extract(r.receipt,'$.digest')
        JOIN agent_rule_proposals p ON p.id=r.proposal AND p.campus=a.campus AND p.topic=a.topic
        WHERE r.proposal=? AND a.campus=? AND a.topic=?""", (proposal, campus, topic)).fetchone()


def _skill_review(topic, baseline, candidate):
    from . import deerflow_chat

    try:
        return deerflow_chat.capability("experience.review", {
            "name": "careops-" + topic, "baseline": baseline, "candidate": candidate,
        })
    except deerflow_chat.Unavailable as error:
        raise ValueError("DeerFlow 经验技能检查暂时不可用，请稍后重试") from error


def change(store, token, operation, body):
    fields = {
        "preview": ("campusId", "topic", "correction", "order", "experience"),
        "propose": ("campusId", "topic", "base", "order", "experienceId"),
        "review": ("campusId", "topic", "base", "decision", "proposalId", "restoreVersion"),
    }
    if operation not in fields:
        raise FileNotFoundError("未找到此规则操作")
    _body(body, fields[operation])
    decision = body.get("decision") if operation == "review" else None
    with closing(store.connect()) as db:
        actor = store.actor(db, token)
        campus, topic = _area_and_topic(db, actor, body)
        version, previous = _current(db, campus, topic)
        order = _candidate(db, actor, operation, body, campus, topic, version)
        evidence = _experience(db, actor, campus, topic) if order is None else None
        active = _released_skill(db, campus, topic, version)
        baseline = active["document"] if active else _document(topic, previous)
        stored = None
        if decision == "approve":
            stored = _stored_proposal(db, campus, topic, body["proposalId"])
        elif decision == "rollback":
            stored = _released_skill(db, campus, topic, body["restoreVersion"])
    if evidence:
        facts = {"topic": topic, "options": {key: item[0] for key, item in TOPICS[topic][3].items()},
                 "missing": {key: val[0] for key, val in MISSING.items()},
                 "current": previous, "reviews": evidence}
        def validate(result):
            return {"order": _order(topic, result.get("order") if isinstance(result, dict) else None)}
        result = generation.generate(
            store, actor["id"], ["experience", campus, topic, version, generation.fingerprint(facts)],
            "从员工已采纳、驳回的安排中提议写作顺序。所有 options 键各用一次，最后加一个 missing 键。"
            "返回 JSON 对象，仅含 order 数组。有据可支持原顺序时可保留原顺序。",
            facts, validate, feature="assistant.experience", output_tokens=120,
        )
        order = result["order"]
    candidate = stored["document"] if stored else _document(topic, order)
    artifact = None if decision == "reject" else _skill_review(topic, baseline, candidate)
    receipt = None if artifact is None else {
        "engine": artifact["engine"], "version": artifact["version"], "digest": artifact["digest"],
        "schema": artifact["report"]["schema_version"], "assurance": artifact["report"]["assurance"],
        "readiness": artifact["report"]["readiness"],
    }
    examples = _examples(topic, order, previous) if order else []
    # The venv and model never hold a database write lock. Recheck both identity
    # and candidate head before showing health-domain metadata or publishing it.
    with closing(store.connect()) as db, db:
        if operation != "preview" or evidence is not None:
            db.execute("BEGIN IMMEDIATE")
        current_actor = store.actor(db, token)
        _area_and_topic(db, current_actor, body)
        current_version, current_order = _current(db, campus, topic)
        expected = _candidate(db, current_actor, operation, body, campus, topic, current_version)
        if (current_actor["id"] != actor["id"] or (current_version, current_order) != (version, previous)
                or (expected is not None and expected != order)
                or (evidence is not None and _experience(db, current_actor, campus, topic) != evidence)):
            from ..store import Conflict
            raise Conflict("院区、审核记录或规则已更新，请重新预览")
        if operation == "preview":
            result = {"order": order, "instruction": _instruction(topic, order), "base": version,
                      "examples": examples, "skillReview": receipt}
            if evidence is not None:
                # At most one unsubmitted model suggestion per actor, campus and topic. A
                # submitted suggestion owns a copy of the anonymous evidence for later audit.
                draft_id = generation.fingerprint([actor["id"], campus, topic, version, order, evidence])
                db.execute("""INSERT OR REPLACE INTO agent_rule_experience_drafts VALUES(?,?,?,?,?,?,?)""",
                           (actor["id"], campus, topic, version, draft_id, json.dumps(order), json.dumps(evidence)))
                result["experienceId"] = draft_id
            return result
        now = store.now().isoformat(timespec="seconds")
        history.watch(db, "learning.edit")
        if artifact:
            db.execute("""INSERT OR IGNORE INTO agent_rule_skill_artifacts
                (campus,topic,digest,document,body,report) VALUES (?,?,?,?,?,?)""",
                (campus, topic, receipt["digest"], candidate, artifact["body"],
                 json.dumps(artifact["report"], ensure_ascii=False)))
        if operation == "propose":
            if order == previous:
                raise ValueError("此顺序已经生效")
            encoded = json.dumps(order)
            audited_experience = None
            if "experienceId" in body:
                if not isinstance(body["experienceId"], str):
                    raise ValueError("经验预览无效，请重试")
                saved = db.execute("""SELECT evidence FROM agent_rule_experience_drafts WHERE
                    actor=? AND campus=? AND topic=? AND version=? AND id=? AND ordering=?""",
                    (actor["id"], campus, topic, version, body["experienceId"], encoded)).fetchone()
                if not saved or json.loads(saved[0]) != json.loads(json.dumps(_experience(db, actor, campus, topic))):
                    raise ValueError("这份经验预览已变更或不属于当前账号，请重新预览")
                audited_experience = saved[0]
            existing = db.execute("""SELECT id FROM agent_rule_proposals WHERE campus=? AND topic=?
                AND ordering=? AND base=? AND author=? AND decision='pending'""",
                (campus, topic, encoded, version, actor["id"])).fetchone()
            if existing:
                return {"id": existing[0], "decision": "pending"}
            key = uuid4().hex
            db.execute("""INSERT INTO agent_rule_proposals(id,campus,topic,ordering,base,author,created)
                VALUES(?,?,?,?,?,?,?)""", (key, campus, topic, encoded, version, actor["id"], now))
            db.execute("INSERT INTO agent_rule_reviews VALUES(?,?)", (key, json.dumps(receipt)))
            db.execute("INSERT INTO agent_rule_proposal_sources VALUES(?,?,?)", (key, baseline, audited_experience))
            _audit(db, campus, topic, "propose", actor, now, version)
            return {"id": key, "decision": "pending"}
        proposal_id = body.get("proposalId") if decision != "rollback" else None
        if proposal_id:
            saved = db.execute("SELECT receipt FROM agent_rule_reviews WHERE proposal=?", (proposal_id,)).fetchone()
            if decision == "approve" and saved and json.loads(saved[0])["digest"] != receipt["digest"]:
                raise ValueError("候选技能内容已改变，请重新提出建议")
            if decision == "approve" and not saved:
                db.execute("INSERT INTO agent_rule_reviews VALUES(?,?)", (proposal_id, json.dumps(receipt)))
            db.execute("UPDATE agent_rule_proposals SET decision=?,reviewer=?,reviewed=? WHERE id=?",
                       (decision, actor["id"], now, proposal_id))
        if decision != "reject":
            version += 1
            db.execute("INSERT INTO agent_rule_releases VALUES(?,?,?,?,?,?,?,?)",
                       (campus, topic, version, json.dumps(order), actor["id"], now, proposal_id, decision))
            db.execute("INSERT INTO agent_rule_release_skills VALUES(?,?,?,?)",
                       (campus, topic, version, receipt["digest"]))
        _audit(db, campus, topic, decision, actor, now, version)
        return {"decision": decision, "version": version}
