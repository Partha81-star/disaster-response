"""Configurable RSS/Atom polling; every accepted entry goes through the incident pipeline."""

from __future__ import annotations

import asyncio
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from re import sub

import httpx

from .models import RawItem, Source, SourceType
from .pipeline import infer_hazard
from .models import HazardType

log = logging.getLogger(__name__)


def parse_feed(xml: str, feed_url: str) -> list[RawItem]:
    root = ET.fromstring(xml)
    entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    reports = []
    for entry in entries[:30]:
        def value(*names: str) -> str:
            for name in names:
                node = entry.find(name)
                if node is not None and node.text:
                    return node.text.strip()
            return ""
        title = value("title", "{http://www.w3.org/2005/Atom}title")
        description = value("description", "summary", "{http://www.w3.org/2005/Atom}summary")
        description = sub(r"<[^>]+>", " ", unescape(description))
        identifier = value("guid", "link", "{http://www.w3.org/2005/Atom}id") or title
        if title and identifier:
            reports.append(RawItem(text=f"{title}. {description}"[:2000],
                                   source=Source(type=SourceType.NEWS, id=f"{feed_url}|{identifier}", name=feed_url),
                                   reported_at=datetime.now(timezone.utc)))
    return reports


async def poll_feeds(pipeline, store, hub, stop: asyncio.Event) -> None:
    urls = [url.strip() for url in os.getenv("RSS_FEEDS", "").split(",") if url.strip()]
    if not urls:
        return
    keywords = [word.strip().casefold() for word in os.getenv("FEED_KEYWORDS", "").split(",") if word.strip()]
    if not keywords:
        log.warning("RSS_FEEDS is set but FEED_KEYWORDS is empty; feed ingestion is disabled")
        return
    interval = max(30, int(os.getenv("FEED_POLL_SECONDS", "120")))
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": "disaster-response-system/0.2"}) as client:
        while not stop.is_set():
            for url in urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    entries = parse_feed(response.text, url)
                    fresh = [entry for entry in entries
                             if infer_hazard(entry.text) != HazardType.OTHER
                             and any(word in entry.text.casefold() for word in keywords)
                             and not store.has_source(entry.source.type.value, entry.source.id)]
                    for entry in fresh:
                        incidents = await pipeline.process([entry])
                        store.save_many(incidents)
                        hub.publish()
                except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
                    log.warning("Feed poll failed for %s: %s", url, exc)
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
