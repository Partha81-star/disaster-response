"""Shared, validated data contracts for the incident pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HazardType(StrEnum):
    FLOOD = "flood"
    FIRE = "fire"
    BUILDING_COLLAPSE = "building_collapse"
    LANDSLIDE = "landslide"
    ROAD_BLOCKAGE = "road_blockage"
    OTHER = "other"


class LocationPrecision(StrEnum):
    POINT = "point"
    STREET = "street"
    NEIGHBORHOOD = "neighborhood"
    DISTRICT = "district"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"


class SourceType(StrEnum):
    TWEET = "tweet"
    NEWS = "news"
    SENSOR = "sensor"
    IMAGE = "image"
    CALL = "call"
    OTHER = "other"


class EvidenceResult(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    NEUTRAL = "neutral"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Location(Contract):
    raw_text: str = ""
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    geocode_confidence: float = Field(default=0.0, ge=0, le=1)
    precision: LocationPrecision = LocationPrecision.UNKNOWN

    @model_validator(mode="after")
    def coordinates_are_a_pair(self) -> "Location":
        if (self.lat is None) != (self.lon is None):
            raise ValueError("latitude and longitude must both be set or both be empty")
        return self


class PeopleAtRisk(Contract):
    value: int | None = Field(default=None, ge=0)
    basis: str = "unknown"


class Source(Contract):
    type: SourceType = SourceType.OTHER
    id: str
    name: str | None = None
    credibility_prior: float = Field(default=0.5, ge=0, le=1)
    media_uri: str | None = None


class Evidence(Contract):
    chunk_id: str
    claim_checked: str
    result: EvidenceResult
    detail: str = ""


class Verification(Contract):
    status: VerificationStatus = VerificationStatus.PENDING
    confidence: float = Field(default=0.0, ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    reasoning: str = "Awaiting verification."


class UrgencyComponents(Contract):
    severity: float = Field(default=0, ge=0, le=1)
    exposure: float = Field(default=0, ge=0, le=1)
    time_sensitivity: float = Field(default=0, ge=0, le=1)
    confidence: float = Field(default=0, ge=0, le=1)


class Urgency(Contract):
    score: float = Field(default=0, ge=0, le=1)
    components: UrgencyComponents = Field(default_factory=UrgencyComponents)


class RawItem(Contract):
    id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    source: Source
    reported_at: datetime = Field(default_factory=utc_now)
    received_at: datetime = Field(default_factory=utc_now)
    media_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Incident(Contract):
    incident_id: UUID = Field(default_factory=uuid4)
    cluster_id: UUID | None = None
    hazard_type: HazardType = HazardType.OTHER
    description: str
    location: Location = Field(default_factory=Location)
    reported_at: datetime = Field(default_factory=utc_now)
    received_at: datetime = Field(default_factory=utc_now)
    severity_cues: list[str] = Field(default_factory=list)
    people_at_risk_estimate: PeopleAtRisk = Field(default_factory=PeopleAtRisk)
    sources: list[Source] = Field(default_factory=list)
    corroboration_count: int = Field(default=1, ge=1)
    verification: Verification = Field(default_factory=Verification)
    urgency: Urgency = Field(default_factory=Urgency)
    raw_item_ids: list[str] = Field(default_factory=list)


class GeocodeCandidate(Contract):
    display_name: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    confidence: float = Field(ge=0, le=1)
    precision: LocationPrecision = LocationPrecision.UNKNOWN


class InfrastructureFeature(Contract):
    feature_id: str
    kind: str
    name: str | None = None
    lat: float
    lon: float
    distance_m: float
    tags: dict[str, str] = Field(default_factory=dict)


class VerificationResult(Contract):
    status: VerificationStatus
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence] = Field(default_factory=list)
    reasoning: str

