"""Nominatim geocoding adapter with a safe no-location fallback."""

from __future__ import annotations

import os
from typing import Protocol

import httpx

from ..models import GeocodeCandidate, LocationPrecision


class Geocoder(Protocol):
    async def geocode(self, text: str) -> GeocodeCandidate | None: ...


def _precision(address_type: str, category: str) -> LocationPrecision:
    if address_type in {"house", "building", "amenity", "road"}:
        return LocationPrecision.STREET if address_type == "road" else LocationPrecision.POINT
    if address_type in {"suburb", "neighbourhood", "quarter", "city_district"}:
        return LocationPrecision.NEIGHBORHOOD
    if address_type in {"city", "county", "state", "administrative"} or category == "boundary":
        return LocationPrecision.DISTRICT
    return LocationPrecision.UNKNOWN


class NominatimGeocoder:
    def __init__(self, base_url: str | None = None, user_agent: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")).rstrip("/")
        self.user_agent = user_agent or os.getenv("GEOCODER_USER_AGENT", "disaster-response-system/0.1")

    async def geocode(self, text: str) -> GeocodeCandidate | None:
        query = text.strip()
        if len(query) < 2:
            return None
        try:
            async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": self.user_agent}) as client:
                response = await client.get(f"{self.base_url}/search", params={"q": query, "format": "jsonv2", "limit": 3, "addressdetails": 1})
                response.raise_for_status()
                results = response.json()
        except httpx.HTTPError:
            # Preserve the report; the incident will carry an unresolved location and enter review.
            return None
        if not results:
            return None
        best = results[0]
        importance = float(best.get("importance", 0.0))
        # Nominatim has no calibrated confidence: this is deliberately labeled a heuristic.
        confidence = max(0.1, min(0.85, 0.35 + importance))
        precision = _precision(best.get("addresstype", ""), best.get("category", ""))
        return GeocodeCandidate(display_name=best.get("display_name", query), lat=float(best["lat"]),
                                lon=float(best["lon"]), confidence=confidence, precision=precision)


class NoopGeocoder:
    async def geocode(self, text: str) -> GeocodeCandidate | None:
        return None

