"""FastAPI entry point for ingestion and incident review."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .models import Incident, RawItem, VerificationStatus
from .pipeline import IncidentPipeline
from .services.geocoding import NominatimGeocoder
from .services.verification import OSMVerifier, OverpassInfrastructureLookup
from .store import IncidentStore

app = FastAPI(title="Disaster Response System", version="0.1.0",
              description="Human-in-the-loop emergency report triage. No autonomous dispatch.")
pipeline = IncidentPipeline(NominatimGeocoder(), OSMVerifier(OverpassInfrastructureLookup()))
store = IncidentStore()


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
    store.update(incident)
    return incident


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

