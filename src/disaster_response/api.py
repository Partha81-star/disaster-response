"""FastAPI entry point for ingestion and incident review."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .models import Incident, RawItem, VerificationStatus
from .feeds import poll_feeds
from .pipeline import IncidentPipeline
from .realtime import EventHub
from .services.geocoding import NominatimGeocoder
from .services.verification import OSMVerifier, OverpassInfrastructureLookup
from .store import IncidentStore

pipeline = IncidentPipeline(NominatimGeocoder(), OSMVerifier(OverpassInfrastructureLookup()))
store = IncidentStore()
hub = EventHub()
operator_token = os.getenv("OPERATOR_TOKEN", "")
session_signature = hmac.new(operator_token.encode(), b"operator-session-v1", hashlib.sha256).hexdigest() if operator_token else ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("APP_ENV") == "production" and not operator_token:
        raise RuntimeError("OPERATOR_TOKEN is required in production")
    stop = asyncio.Event()
    task = asyncio.create_task(poll_feeds(pipeline, store, hub, stop))
    yield
    stop.set()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Disaster Response System", version="0.2.0", lifespan=lifespan,
              description="Human-in-the-loop emergency report triage. No autonomous dispatch.")


@app.middleware("http")
async def protect_api(request: Request, call_next):
    if request.url.path.startswith("/api/v1/") and request.url.path not in {"/api/v1/session", "/api/v1/config"}:
        if operator_token and not secrets.compare_digest(request.cookies.get("operator_session", ""), session_signature):
            return Response(status_code=401, content="Operator sign-in required")
    return await call_next(request)


class IngestRequest(BaseModel):
    items: list[RawItem] = Field(min_length=1, max_length=100)


class ReviewDecision(BaseModel):
    status: VerificationStatus
    note: str = Field(min_length=3, max_length=1000)

    @field_validator("status")
    @classmethod
    def only_operator_verdicts(cls, value: VerificationStatus) -> VerificationStatus:
        if value not in {VerificationStatus.ACCEPTED, VerificationStatus.REJECTED, VerificationStatus.NEEDS_REVIEW}:
            raise ValueError("Choose accepted, rejected, or needs_review")
        return value


class SessionRequest(BaseModel):
    token: str


@app.get("/api/v1/config")
async def config() -> dict[str, bool]:
    return {"auth_required": bool(operator_token),
            "feed_enabled": bool(os.getenv("RSS_FEEDS", "").strip() and os.getenv("FEED_KEYWORDS", "").strip())}


@app.post("/api/v1/session")
async def create_session(credentials: SessionRequest, response: Response) -> dict[str, str]:
    if not operator_token or not secrets.compare_digest(credentials.token, operator_token):
        raise HTTPException(status_code=401, detail="Invalid operator token")
    response.set_cookie("operator_session", session_signature, httponly=True, samesite="strict",
                        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", max_age=86400)
    return {"status": "signed_in"}


@app.get("/api/v1/events")
async def events(request: Request):
    async def stream():
        queue = hub.subscribe()
        try:
            yield "event: connected\ndata: ready\n\n"
            while not await request.is_disconnected():
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"event: {event}\ndata: refresh\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            hub.unsubscribe(queue)
    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "disaster-response-system"}


@app.post("/api/v1/ingest", response_model=list[Incident])
async def ingest(request: IngestRequest) -> list[Incident]:
    try:
        results = await pipeline.process(request.items)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Pipeline provider error: {type(exc).__name__}") from exc
    store.save_many(results)
    hub.publish()
    return results


@app.get("/api/v1/incidents", response_model=list[Incident])
async def list_incidents() -> list[Incident]:
    return store.list()


@app.get("/api/v1/incidents/{incident_id}", response_model=Incident)
async def get_incident(incident_id: str) -> Incident:
    incident = store.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@app.post("/api/v1/incidents/{incident_id}/decision", response_model=Incident)
async def decide_incident(incident_id: str, decision: ReviewDecision) -> Incident:
    incident = store.get(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    incident.verification.status = decision.status
    incident.verification.reasoning = f"Operator decision: {decision.note.strip()}"
    store.update(incident, note=decision.note.strip())
    hub.publish()
    return incident


@app.get("/api/v1/incidents/{incident_id}/history")
async def incident_history(incident_id: str) -> list[dict]:
    if store.get(incident_id) is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return store.history(incident_id)


@app.get("/api/v1/summary")
async def summary() -> dict[str, int | float]:
    records = store.list()
    return {
        "total": len(records),
        "needs_review": sum(item.verification.status == VerificationStatus.NEEDS_REVIEW for item in records),
        "accepted": sum(item.verification.status == VerificationStatus.ACCEPTED for item in records),
        "rejected": sum(item.verification.status == VerificationStatus.REJECTED for item in records),
        "high_priority": sum(item.urgency.score >= 0.7 for item in records),
    }


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="dashboard")

