# Disaster Response System

A human-in-the-loop decision-support pipeline that turns noisy emergency reports into structured, geolocated incidents with evidence and triage scores. It does **not** dispatch responders autonomously.

## Current vertical slice

`Raw reports → deterministic extraction → place lookup → batch deduplication → conservative OSM context check → urgency score → persistent operator review queue`

The app includes a responsive operator dashboard with a report map, search and status filters, incident evidence details, report entry, and operator decisions. Incidents persist in SQLite. Browser clients receive server-sent updates as soon as reports or decisions arrive. A configurable RSS/Atom collector can poll relevant feeds and submit entries through the same pipeline. Extraction remains a deterministic baseline. Nominatim and Overpass provide location context, but do not prove an emergency occurred; reports remain in `needs_review` until an operator reviews them.

## Run locally

Requires Python 3.11 or newer.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
disaster-response
```

Open `http://127.0.0.1:8000` for the dashboard or `http://127.0.0.1:8000/docs` for the API. Set a descriptive `GEOCODER_USER_AGENT` in `.env` before making geocoding requests. Respect Nominatim and Overpass usage policies; use a local or hosted provider for sustained ingestion.

The `disaster-response` CLI loads `.env` from the current directory when present.

## Deploy with Docker Compose

Set `OPERATOR_TOKEN` to a long random value in your shell or a local `.env` file. Then run:

```powershell
docker compose up --build -d
```

The dashboard runs on port 8000 and asks for the operator token. SQLite data is stored in the `incident_data` volume. Deploy **one app replica**: in-process server-sent events and the RSS collector are single-instance components. Put an HTTPS reverse proxy in front, set `COOKIE_SECURE=true`, and keep the token and volume backed up. Docker was not available in the development environment, so the container build has not been exercised here.

Set `RSS_FEEDS` to a comma-separated list of RSS/Atom URLs and `FEED_KEYWORDS` to city or locality names. Only entries containing a recognized hazard and a configured locality keyword are ingested. `FEED_POLL_SECONDS` defaults to 120. Feed availability and update frequency depend on the sources; this collector does not read emergency calls, private social networks, or sensors.

## API

`POST /api/v1/ingest` accepts a batch of up to 100 `RawItem` records and returns deduplicated `Incident` records. `GET /api/v1/incidents` lists persistent incidents sorted by urgency; `GET /api/v1/incidents/{incident_id}` returns one record; `POST /api/v1/incidents/{incident_id}/decision` records an operator verdict and note; `GET /api/v1/incidents/{incident_id}/history` returns its decision history; `GET /api/v1/events` streams change notifications; and `GET /api/v1/summary` returns dashboard counts. In production, all `/api/v1/*` endpoints except session and config require the operator cookie. SQLite is suitable for a single-instance deployment; a multi-replica deployment needs PostgreSQL/PostGIS and shared events.

Example request:

```json
{
  "items": [
    {
      "text": "Flooded underpass near Pimpri station; several vehicles stranded",
      "source": {"type": "news", "id": "local-outlet-42", "name": "Local News", "credibility_prior": 0.7}
    }
  ]
}
```

## Design and safety

- Pydantic contracts are shared across pipeline stages; unresolved locations retain null coordinates and `unknown` precision.
- Infrastructure matches are evidence context only. Lack of an OSM feature does not mean an incident is false.
- The verifier routes reports to human review because OSM context alone cannot confirm that an event occurred. Operator decisions require a note.
- Urgency is a transparent baseline formula, not a dispatch command. Accepting a report does not dispatch resources.
- Deduplication currently merges matching hazard and normalized place text in one request batch. Production clustering should use spatial distance, time windows, and source diversity.

## Next milestones

1. Replace keyword extraction with a schema-constrained model adapter and add labeled extraction/geocoding evaluation.
2. Move to PostGIS for multiple replicas; add spatial/time-window clustering and a source-diversity model.
3. Add independent rainfall, gauge, road-closure, and trusted-source feeds for evidence-backed verification.
4. Add operator review, audit history, and explicit approval workflows.
5. Add a constrained vehicle routing solver only after resource, capacity, depot, and travel-time data are defined.

