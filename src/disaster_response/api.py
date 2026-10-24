"""FastAPI entry point for ingestion and incident review."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .models import Incident, RawItem
from .pipeline import IncidentPipeline
from .services.geocoding import NominatimGeocoder
from .services.verification import OSMVerifier, OverpassInfrastructureLookup

app = FastAPI(title="Disaster Response System", version="0.1.0",
              description="Human-in-the-loop emergency report triage. No autonomous dispatch.")
pipeline = IncidentPipeline(NominatimGeocoder(), OSMVerifier(OverpassInfrastructureLookup()))
incidents: dict[str, Incident] = {}


class IngestRequest(BaseModel):
    items: list[RawItem] = Field(min_length=1, max_length=100)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "disaster-response-system"}


@app.post("/api/v1/ingest", response_model=list[Incident])
async def ingest(request: IngestRequest) -> list[Incident]:
    try:
        results = await pipeline.process(request.items)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Pipeline provider error: {type(exc).__name__}") from exc
    for incident in results:
        incidents[str(incident.incident_id)] = incident
    return results


@app.get("/api/v1/incidents", response_model=list[Incident])
async def list_incidents() -> list[Incident]:
    return sorted(incidents.values(), key=lambda incident: incident.urgency.score, reverse=True)


@app.get("/api/v1/incidents/{incident_id}", response_model=Incident)
async def get_incident(incident_id: str) -> Incident:
    if incident_id not in incidents:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incidents[incident_id]

