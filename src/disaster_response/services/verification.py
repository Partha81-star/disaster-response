"""Evidence-based verifier. OSM infrastructure matches are support, not proof of an event."""

from __future__ import annotations

import math
import os
from typing import Protocol

import httpx

from ..models import Evidence, Incident, InfrastructureFeature, Verification, VerificationStatus


class Verifier(Protocol):
    async def verify(self, incident: Incident) -> Verification: ...


class InfrastructureLookup(Protocol):
    async def nearby(self, lat: float, lon: float, radius_m: int = 500) -> list[InfrastructureFeature]: ...


class OverpassInfrastructureLookup:
    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint or os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")

    async def nearby(self, lat: float, lon: float, radius_m: int = 500) -> list[InfrastructureFeature]:
        query = f"[out:json][timeout:15];(node(around:{radius_m},{lat},{lon})[bridge];way(around:{radius_m},{lat},{lon})[bridge];node(around:{radius_m},{lat},{lon})[amenity~\"hospital|fire_station|shelter\"];way(around:{radius_m},{lat},{lon})[amenity~\"hospital|fire_station|shelter\"];);out center tags;"
        async with httpx.AsyncClient(timeout=20.0, headers={"User-Agent": "disaster-response-system/0.1"}) as client:
            response = await client.post(self.endpoint, data={"data": query})
            response.raise_for_status()
            elements = response.json().get("elements", [])
        features = []
        for element in elements:
            tags = element.get("tags", {})
            center = element.get("center", element)
            feature_lat, feature_lon = float(center["lat"]), float(center["lon"])
            distance = _haversine_m(lat, lon, feature_lat, feature_lon)
            features.append(InfrastructureFeature(
                feature_id=f"osm:{element.get('type')}:{element.get('id')}",
                kind=tags.get("amenity", "bridge"), name=tags.get("name"), lat=feature_lat,
                lon=feature_lon, distance_m=round(distance, 1), tags={str(k): str(v) for k, v in tags.items()},
            ))
        return features


class OSMVerifier:
    """Conservative baseline; missing evidence routes reports to human review."""

    def __init__(self, infrastructure: InfrastructureLookup) -> None:
        self.infrastructure = infrastructure

    async def verify(self, incident: Incident) -> Verification:
        if incident.location.lat is None or incident.location.lon is None:
            return Verification(status=VerificationStatus.NEEDS_REVIEW, confidence=0.2,
                                reasoning="Location could not be resolved; ground checks were not run.")
        try:
            features = await self.infrastructure.nearby(incident.location.lat, incident.location.lon)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return Verification(status=VerificationStatus.NEEDS_REVIEW, confidence=0.25,
                                reasoning=f"Ground-data lookup failed ({type(exc).__name__}); human review required.")
        evidence = [Evidence(chunk_id=f.feature_id, claim_checked=f"Nearby infrastructure: {f.kind}",
                             result="supports", detail=f"{f.name or f.kind}, {f.distance_m:.0f} m away")
                    for f in features[:5]]
        if incident.hazard_type.value == "road_blockage" and features:
            return Verification(status=VerificationStatus.NEEDS_REVIEW, confidence=0.42, evidence=evidence,
                                reasoning="Nearby infrastructure was found, but OSM presence cannot verify a road blockage.")
        return Verification(status=VerificationStatus.NEEDS_REVIEW, confidence=0.3, evidence=evidence,
                            reasoning="OSM context alone cannot establish whether this event occurred; seek independent reports or sensor evidence.")


class ReviewOnlyVerifier:
    async def verify(self, incident: Incident) -> Verification:
        return Verification(status=VerificationStatus.NEEDS_REVIEW, confidence=0.1,
                            reasoning="Verification provider is not configured; manual review required.")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

