"""Owner-only usage report over confirmed charges and outstanding reservations."""

from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta
import json
import re

from . import ZONE, local_time, task_usage


FEATURES = {
    "assistant.chat": "健康助理 · 对话",
    "assistant.faq": "健康助理 · 常见问题",
    "assistant.toolAnswer": "健康助理 · 核对资料后回答",
    "assistant.scheduledMeal": "健康助理 · 伙食工单确认入口",
    "assistant.medication": "健康助理 · 服药确认入口",
    "assistant.finance": "健康助理 · 经营快报",
    "assistant.operations": "健康助理 · 今日院务简报",
    "assistant.health": "健康助理 · 健康快报",
    "assistant.webAnswer": "健康助理 · 联网回答",
    "assistant.webTopic": "健康助理 · 联网选词",
    "assistant.webSearch": "健康助理 · 公开搜索",
    "assistant.voiceAsr": "健康助理 · 语音转写",
    "assistant.readAloud": "健康助理 · 朗读合成",
    "medication.voiceParse": "床旁服药 · 口述解析",
    "care.scheduledMealVoiceParse": "伙食工单 · 口述解析",
    "care.roundPriorities": "照护巡查 · 事项优先级",
    "care.roundNarrative": "照护巡查 · 生活简报",
    "care.healthReview": "健康复核 · 在住长辈资料",
    "care.taskAsr": "照护工单 · 语音转写",
    "dossier.documentOcr": "医疗档案 · OCR",
    "assistant.documentOcr": "健康助理 · 文件识别",
    "assistant.documentClassify": "健康助理 · 文件分类",
    "access.resumeOcr": "员工简历 · OCR",
    "dossier.visitOcr": "就诊资料 · OCR",
    "dossier.visitExtraction": "就诊资料 · 病例整理",
    "dossier.healthIntroduction": "长辈档案 · 健康简介",
    "dossier.summary": "长辈档案 · 健康摘要",
    "inventory.similarity": "物资品目 · 查重核对",
    "agent.routing": "智能协作 · 任务分派",
    "agent.voiceAsr": "智能协作 · 语音转写",
    "agent.specialist.care": "智能协作 · 照护说明",
    "agent.specialist.finance": "智能协作 · 财务说明",
    "agent.specialist.inventory": "智能协作 · 物资说明",
    "workflow.changeReview": "最近改动 · 云端复核",
    "legacy.generation": "历史内容生成 · 未细分",
    "legacy.ocr": "历史 OCR · 未细分",
    "legacy.asr": "历史语音转写 · 未细分",
    "other": "其他 · 未分类",
}

AUTOMATED_ACTORS = {
    "rounds-agent": "机构自动任务 · 照护巡查",
    "daily-life": "机构自动任务 · 日常起居助理",
    "health-review": "机构自动任务 · 健康复核助理",
    "change-review": "机构自动任务 · 改动复核",
    "dossier-summary": "历史服务账号 · 档案摘要",
}

PAGE_SIZE = 50
MAX_RANGE = 366
UNITS = {
    "tokens": "tokens",
    "pages": "ocrPages",
    "seconds": "asrSeconds",
    "characters": "ttsCharacters",
    "calls": "searchCalls",
}
TOKEN_FIELDS = ("inputTokens", "cacheHitTokens", "cacheMissTokens", "outputTokens")


def _parameters(query, now):
    if not isinstance(query, dict) or set(query) - {
        "start",
        "end",
        "actorId",
        "feature",
        "taskId",
        "page",
    }:
        raise ValueError("用量筛选参数无效")
    today = local_time(now).date()
    try:
        end = date.fromisoformat(query["end"]) if "end" in query else today
        start = (
            date.fromisoformat(query["start"])
            if "start" in query
            else end.replace(day=1)
        )
    except (TypeError, ValueError):
        raise ValueError("请选择有效的起止日期") from None
    if any(
        key in query and query[key] != value.isoformat()
        for key, value in (("start", start), ("end", end))
    ):
        raise ValueError("日期格式须为 YYYY-MM-DD")
    if end > today or not 0 <= (end - start).days < MAX_RANGE:
        raise ValueError("请选择截至今天且不超过 366 天的日期范围")
    actor, feature, page = (
        query.get("actorId", ""),
        query.get("feature", ""),
        query.get("page", "1"),
    )
    if not isinstance(actor, str) or not re.fullmatch(
        r"[A-Za-z0-9_:.\-]{0,120}", actor
    ):
        raise ValueError("员工编号无效")
    if not isinstance(feature, str) or feature and feature not in FEATURES:
        raise ValueError("请选择有效功能")
    if not isinstance(page, str) or not re.fullmatch(r"[1-9][0-9]{0,7}", page):
        raise ValueError("页码无效")
    task_id = query.get("taskId", "")
    if not isinstance(task_id, str) or task_id and not task_usage.TASK_ID.fullmatch(task_id):
        raise ValueError("任务编号无效")
    return start, end, actor, feature, int(page), task_id


def _time_window(start, end):
    return tuple(
        int(datetime.combine(day, time.min, tzinfo=ZONE).timestamp())
        for day in (start, end + timedelta(days=1))
    )


LEDGER = """
WITH
token AS (
    SELECT COALESCE(NULLIF(u.attributedActor,''),u.actor) AS actorId,
      CASE
        WHEN u.feature IS NOT NULL THEN u.feature
        WHEN u.request LIKE 'chat/%' THEN CASE WHEN t.web_sources IS NULL
          THEN 'assistant.chat' ELSE 'assistant.webAnswer' END
        WHEN u.request LIKE 'rounds/%' THEN 'care.roundPriorities'
        WHEN u.request LIKE 'generation/%' THEN CASE u.actor
          WHEN 'rounds-agent' THEN 'care.roundNarrative'
          WHEN 'change-review' THEN 'workflow.changeReview'
          WHEN 'dossier-summary' THEN 'dossier.summary'
          ELSE 'legacy.generation' END
        ELSE 'agent.routing'
      END AS feature,
      u.createdAt AS at, u.request AS ordinal,
      CASE WHEN l.actor IS NOT NULL AND l.verified IS NULL THEN 'review'
        WHEN u.status IN ('pending','uncertain') THEN u.status
        WHEN u.reason='reconciled' OR l.verified IS NOT NULL THEN 'settled'
        WHEN u.status='ok' THEN 'complete' ELSE 'failed' END AS status,
      'tokens' AS unit, u.charged + COALESCE(l.verified-l.original,0) AS amount,
      CASE WHEN u.status IN ('pending','uncertain') THEN u.allowance
        WHEN l.verified IS NULL AND l.reported>l.original THEN l.reported-l.original ELSE 0 END AS reserved,
      u.providerTokens, u.inputTokens, u.cachedInputTokens AS cacheHitTokens,
      u.uncachedInputTokens AS cacheMissTokens, u.outputTokens, 'tokens' AS meter, u.actor AS billingActor
    FROM api_usage u
    LEFT JOIN api_late_usage l ON l.actor=u.actor AND l.request=u.request
    LEFT JOIN assistant_turns t ON t.actor=u.actor AND t.request=substr(u.request,6) AND u.feature IS NULL AND u.request LIKE 'chat/%'
    WHERE u.createdAt >= :start AND u.createdAt < :end
),
media AS (
    SELECT actor AS actorId,
      COALESCE(feature,CASE
        WHEN kind='tts' THEN 'assistant.readAloud'
        WHEN kind='ocr' THEN 'legacy.ocr'
        WHEN kind='asr' AND reference LIKE 'chat-voice:%' THEN 'assistant.voiceAsr'
        WHEN kind='asr' AND reference LIKE 'agent:%' THEN 'agent.voiceAsr'
        WHEN kind='asr' AND reference<>'' THEN 'care.taskAsr'
        WHEN kind='asr' THEN 'legacy.asr' ELSE 'other' END) AS feature,
      at, id AS ordinal,
      CASE WHEN state IN ('pending','uncertain') THEN state
        WHEN state='complete' THEN 'complete'
        WHEN state='reconciled' THEN 'settled' ELSE 'failed' END AS status,
      CASE kind WHEN 'ocr' THEN 'pages'
        WHEN 'asr' THEN 'seconds' WHEN 'tts' THEN 'characters' END AS unit,
      charged AS amount, CASE WHEN state IN ('pending','uncertain') THEN reserved ELSE 0 END AS reserved,
      NULL AS providerTokens, NULL AS inputTokens, NULL AS cacheHitTokens,
      NULL AS cacheMissTokens, NULL AS outputTokens, 'media' AS meter, actor AS billingActor
    FROM media_usage INDEXED BY media_usage_by_time
    WHERE kind IN ('ocr','asr','tts') AND at >= :start AND at < :end
),
search AS (
    SELECT actor AS actorId, 'assistant.webSearch' AS feature, createdAt AS at, request AS ordinal,
       CASE WHEN needsReview THEN 'review'
         WHEN verified IS NOT NULL THEN 'settled'
         WHEN status='ok' THEN 'complete'
         WHEN status='closed' THEN 'failed' ELSE status END AS status,
       'calls' AS unit, coalesce(verified,status='ok') AS amount,
       CASE WHEN verified IS NULL AND status IN ('pending','uncertain') THEN 1 ELSE 0 END AS reserved,
       NULL AS providerTokens, NULL AS inputTokens, NULL AS cacheHitTokens,
       NULL AS cacheMissTokens, NULL AS outputTokens, 'search' AS meter, actor AS billingActor
    FROM api_search_usage WHERE createdAt >= :start AND createdAt < :end
),
all_calls AS (SELECT * FROM token UNION ALL SELECT * FROM media UNION ALL SELECT * FROM search)
SELECT c.*, t.taskId, t.runtime FROM all_calls c
LEFT JOIN agent_task_usage t ON t.meter=c.meter AND t.actor=c.billingActor AND t.receipt=c.ordinal
WHERE :taskId='' OR t.taskId=:taskId
ORDER BY at DESC, actorId, unit, ordinal
"""


def _read_ledger(db, start, end, task_id):
    lower, upper = _time_window(start, end)
    return db.execute(LEDGER, {"start": lower, "end": upper, "taskId": task_id})


def _summary():
    return {
        "calls": 0,
        "pendingCalls": 0,
        **dict.fromkeys(UNITS.values(), 0),
        "reservedTokens": 0,
        **dict.fromkeys(TOKEN_FIELDS, None),
        "unclassifiedTokenCalls": 0,
        "unclassifiedCacheCalls": 0,
    }


def _token_fields(row):
    recorded = row["unit"] == "tokens" and row["providerTokens"] == row["amount"]
    return {key: row[key] if recorded else None for key in TOKEN_FIELDS}


def _add(summary, row, chunks):
    summary["calls"] += 1
    summary["pendingCalls"] += row["status"] in ("pending", "uncertain", "review")
    summary[UNITS[row["unit"]]] += row["amount"]
    if row["unit"] == "tokens":
        summary["reservedTokens"] += row["reserved"]
        if row["amount"] > 0:
            summary["unclassifiedTokenCalls"] += (
                chunks["inputTokens"] is None or chunks["outputTokens"] is None
            )
            summary["unclassifiedCacheCalls"] += (
                chunks["cacheHitTokens"] is None or chunks["cacheMissTokens"] is None
            )
        for key, value in chunks.items():
            if value is not None:
                summary[key] = (summary[key] or 0) + value


def _directory(db):
    accounts = list(
        db.execute(
            "SELECT id,display_name,username,kind,role,staff_duties FROM accounts"
        )
    )
    duplicates = Counter(r["display_name"] for r in accounts)
    result = {}
    for row in accounts:
        label = row["display_name"]
        if row["kind"] == "staff":
            duties = json.loads(row["staff_duties"])
            position = (
                "、".join(duties) if row["role"] == "自定义" and duties else row["role"]
            )
            label += f"（{position}）"
        if duplicates[row["display_name"]] > 1:
            label += f" · {row['username']}"
        result[row["id"]] = {"id": row["id"], "label": label, "kind": row["kind"]}
    return result


def _actor(actor_id, directory):
    if actor_id in directory:
        return directory[actor_id]
    if actor_id in AUTOMATED_ACTORS:
        return {"id": actor_id, "label": AUTOMATED_ACTORS[actor_id], "kind": "system"}
    return {
        "id": actor_id,
        "label": f"历史账号（{actor_id[-8:]}）",
        "kind": "historical",
    }


def _groups(groups, labels):
    return [
        {"id": key, "label": labels[key], **summary} for key, summary in groups.items()
    ]


def _report(db, start, end, actor, feature, page, task_id):
    directory = _directory(db)
    people = {
        uid: option
        for uid, option in directory.items()
        if option["kind"] in ("owner", "staff")
    }
    if actor:
        people.setdefault(actor, _actor(actor, directory))
    total, items = _summary(), []
    by_feature, by_actor, by_day = (defaultdict(_summary) for _ in range(3))
    offset = (page - 1) * PAGE_SIZE
    for row in _read_ledger(db, start, end, task_id):
        uid = row["actorId"]
        if uid not in people:
            people[uid] = _actor(uid, directory)
        fid = row["feature"] if row["feature"] in FEATURES else "other"
        if (actor and uid != actor) or (feature and fid != feature):
            continue
        at = datetime.fromtimestamp(row["at"], ZONE)
        day = at.date().isoformat()
        chunks = _token_fields(row)
        if offset <= total["calls"] < offset + PAGE_SIZE:
            items.append(
                dict(
                    at=at.isoformat(timespec="seconds"),
                    actorId=uid,
                    actorLabel=people[uid]["label"],
                    feature=fid,
                    featureLabel=FEATURES[fid],
                    runtime=row["runtime"],
                    taskId=row["taskId"],
                    status=row["status"],
                    unit=row["unit"],
                    amount=row["amount"],
                    reserved=row["reserved"],
                    **chunks,
                )
            )
        for summary in (
            total,
            by_feature[fid],
            by_actor[uid],
            by_day[day],
        ):
            _add(summary, row, chunks)
    return {
        "range": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timeZone": ZONE.key,
        },
        "features": [{"id": key, "label": label} for key, label in FEATURES.items()],
        "actors": sorted(people.values(), key=lambda item: (item["label"], item["id"])),
        "summary": total,
        "byFeature": _groups(by_feature, FEATURES),
        "byActor": _groups(by_actor, {uid: p["label"] for uid, p in people.items()}),
        "byDay": _groups(by_day, {day: day for day in by_day}),
        "records": {
            "items": items,
            "total": total["calls"],
            "page": page,
            "pageSize": PAGE_SIZE,
        },
    }


def read(store, token, query):
    with closing(store.connect()) as db, db:
        db.execute("BEGIN")
        if store.actor(db, token)["kind"] != "owner":
            raise PermissionError("仅 Owner 可查看机构和员工的 AI 用量")
        return _report(db, *_parameters(query, store.now()))
