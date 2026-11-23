from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.agents.orchestrator import AgentOrchestrator
from app.config import get_settings
from app.hooks.human_review import list_reviews, resolve_review
from app.models.schemas import (
    FeedbackRequest,
    FusionRequest,
    HealthAutoRequest,
    MeetingRequest,
    SensorEvent,
    TypelessCommand,
    VoiceCareRequest,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("nh.agent")

orch: AgentOrchestrator | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global orch
    orch = AgentOrchestrator()
    logger.info("Agent runtime ready tools=%s", orch.harness.list_tools())
    yield


app = FastAPI(title="智能养老 Agent Runtime", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _o() -> AgentOrchestrator:
    if orch is None:
        raise HTTPException(503, "agent not ready")
    return orch


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/v1/manifest")
def manifest() -> dict[str, Any]:
    return _o().manifest()


@app.get("/v1/mcp/tools")
def mcp_tools() -> dict[str, Any]:
    return _o().manifest()["mcp"]


@app.post("/v1/sensors/ingest")
def ingest_sensor(event: SensorEvent) -> dict[str, Any]:
    o = _o()
    return o.harness.call_tool(
        "sensor.ingest_event",
        {
            "source": event.source.value,
            "bed_id": event.bed_id,
            "elder_id": event.elder_id,
            "event_type": event.event_type,
            "confidence": event.confidence,
            "payload": event.payload,
            "ts": event.ts.isoformat() + "Z",
        },
    )


@app.post("/v1/fusion/decide")
def fusion_decide(req: FusionRequest) -> dict[str, Any]:
    return _o().fusion.run(req).model_dump()


@app.post("/v1/care/voice")
async def care_voice(req: VoiceCareRequest) -> dict[str, Any]:
    return (await _o().care.run(req)).model_dump()


@app.post("/v1/meeting/summarize")
async def meeting_summarize(req: MeetingRequest) -> dict[str, Any]:
    return (await _o().meeting.run(req)).model_dump()


@app.post("/v1/alerts/feedback")
def alert_feedback(req: FeedbackRequest) -> dict[str, Any]:
    return _o().feedback.run(req)


@app.post("/v1/routing/push")
def routing_push(payload: dict[str, Any]) -> dict[str, Any]:
    return _o().routing.route(
        payload.get("risk_level", "review"),
        payload.get("title", "告警"),
        payload["bed_id"],
        payload.get("elder_id"),
        payload.get("message", ""),
    )


@app.post("/v1/memory/bed/bind")
def bed_bind(payload: dict[str, Any]) -> dict[str, Any]:
    return _o().memory.bind_elder(payload["bed_id"], payload["elder_id"], payload.get("traits"))


@app.get("/v1/memory/bed/{bed_id}")
def bed_memory(bed_id: str) -> dict[str, Any]:
    return _o().memory.load(bed_id)


@app.post("/v1/health/auto")
def health_auto(req: HealthAutoRequest) -> dict[str, Any]:
    return _o().health.run(req)


@app.post("/v1/typeless")
async def typeless(cmd: TypelessCommand) -> dict[str, Any]:
    return await _o().typeless.run(cmd)


@app.get("/v1/audit")
def audit_list(limit: int = 30) -> list[dict[str, Any]]:
    return _o().harness.audit.list_recent(limit)


@app.get("/v1/reviews")
def reviews(status: str | None = "pending") -> list[dict[str, Any]]:
    return list_reviews(status)


@app.post("/v1/reviews/{review_id}/resolve")
def review_resolve(review_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return resolve_review(review_id, payload.get("decision", "approved"), payload.get("note"))
    except KeyError as exc:
        raise HTTPException(404, "review not found") from exc


@app.get("/v1/policy")
def get_policy() -> dict[str, Any]:
    return _o().harness.policy.data


def run() -> None:
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.agent_host, port=settings.agent_port, reload=False)


if __name__ == "__main__":
    run()
