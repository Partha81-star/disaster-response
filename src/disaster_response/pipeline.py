"""Deterministic starter pipeline. Model-backed extraction can replace the stub later."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import timedelta
from uuid import uuid4

from .models import (
    HazardType,
    Incident,
    Location,
    LocationPrecision,
    RawItem,
    VerificationStatus,
)
from .services.geocoding import Geocoder
from .services.verification import Verifier

HAZARD_TERMS: tuple[tuple[HazardType, tuple[str, ...]], ...] = (
    (HazardType.FLOOD, ("flood", "flooded", "waterlogging", "waterlogged", "inundat")),
    (HazardType.FIRE, ("fire", "burning", "smoke", "blaze")),
    (HazardType.BUILDING_COLLAPSE, ("collapse", "collapsed", "building fell")),
    (HazardType.LANDSLIDE, ("landslide", "mudslide")),
    (HazardType.ROAD_BLOCKAGE, ("blocked road", "road blocked", "underpass blocked")),
)
SEVERITY_TERMS = ("stranded", "trapped", "injured", "knee-deep", "waist-deep", "collapsed", "evacuate")


def infer_hazard(text: str) -> HazardType:
    normalized = text.casefold()
    return next((kind for kind, terms in HAZARD_TERMS if any(term in normalized for term in terms)), HazardType.OTHER)


def extract_location_text(text: str) -> str:
    """Use explicit location syntax when present; otherwise preserve an honest unknown."""
    patterns = (r"\b(?:at|near|in|around)\s+([^,.!?;]+)", r"\b(?:location)\s*:\s*([^,.!?;]+)")
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


class IncidentPipeline:
    def __init__(self, geocoder: Geocoder, verifier: Verifier) -> None:
        self.geocoder = geocoder
        self.verifier = verifier

    async def process(self, items: list[RawItem]) -> list[Incident]:
        incidents = await self._extract_and_cluster(items)
        for incident in incidents:
            incident.verification = await self.verifier.verify(incident)
            incident.urgency = self._score_urgency(incident)
        return incidents

    async def _extract_and_cluster(self, items: list[RawItem]) -> list[Incident]:
        grouped: dict[tuple[HazardType, str], list[RawItem]] = defaultdict(list)
        for item in items:
            place = extract_location_text(item.text)
            resolved = await self.geocoder.geocode(place) if place else None
            key = (infer_hazard(item.text), self._place_key(resolved.display_name if resolved else place))
            grouped[key].append(item)

        incidents: list[Incident] = []
        for (hazard, _), group in grouped.items():
            first = min(group, key=lambda item: item.reported_at)
            place = extract_location_text(first.text)
            candidate = await self.geocoder.geocode(place) if place else None
            if candidate:
                location = Location(raw_text=place, lat=candidate.lat, lon=candidate.lon,
                                    geocode_confidence=candidate.confidence, precision=candidate.precision)
            else:
                location = Location(raw_text=place, precision=LocationPrecision.UNKNOWN)
            merged_cues = sorted({term for item in group for term in SEVERITY_TERMS if term in item.text.casefold()})
            ids = [item.id for item in group]
            incident = Incident(
                cluster_id=uuid4() if len(group) > 1 else None,
                hazard_type=hazard,
                description=first.text[:240],
                location=location,
                reported_at=first.reported_at,
                received_at=max(item.received_at for item in group),
                severity_cues=merged_cues,
                sources=[item.source for item in group],
                corroboration_count=len({(item.source.type, item.source.id) for item in group}),
                raw_item_ids=ids,
            )
            incidents.append(incident)
        return incidents

    @staticmethod
    def _place_key(place: str) -> str:
        return " ".join(place.casefold().split())

    @staticmethod
    def _score_urgency(incident: Incident):
        severity = min(1.0, 0.2 + 0.18 * len(incident.severity_cues))
        exposure = min(1.0, 0.25 + (incident.people_at_risk_estimate.value or 0) / 100)
        age_hours = max(0.0, (incident.received_at - incident.reported_at).total_seconds() / 3600)
        time_sensitivity = max(0.3, 1.0 - age_hours / 24)
        confidence = incident.verification.confidence
        score = 0.35 * severity + 0.25 * exposure + 0.2 * time_sensitivity + 0.2 * confidence
        from .models import Urgency, UrgencyComponents

        return Urgency(score=round(score, 3), components=UrgencyComponents(
            severity=severity, exposure=exposure, time_sensitivity=time_sensitivity, confidence=confidence
        ))

