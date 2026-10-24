# Disaster Response System

A human-in-the-loop decision-support pipeline that turns noisy emergency reports into structured, geolocated incidents with evidence and triage scores. It does **not** dispatch responders autonomously.

## Current vertical slice

`Raw reports → deterministic extraction → place lookup → batch deduplication → conservative OSM context check → urgency score → persistent operator review queue`

The app includes a responsive operator dashboard with a report map, search and status filters, incident evidence details, report entry, and operator decisions. Incidents persist in a local SQLite database. The service starts without model credentials. Extraction is intentionally a simple baseline so provider-backed structured extraction can be introduced behind the same contracts. Nominatim and Overpass are live OpenStreetMap services; geocoding confidence is a heuristic and OSM context cannot prove that an emergency occurred. Reports therefore remain in `needs_review` until an operator reviews them.

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

## API

`POST /api/v1/ingest` accepts a batch of up to 100 `RawItem` records and returns deduplicated `Incident` records. `GET /api/v1/incidents` lists persistent incidents sorted by urgency; `GET /api/v1/incidents/{incident_id}` returns one record; `POST /api/v1/incidents/{incident_id}/decision` records an operator verdict and note; and `GET /api/v1/summary` returns dashboard counts. SQLite is suitable for local development; a multi-operator deployment should move to PostgreSQL/PostGIS and append-only audit records.

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
2. Persist incidents and evidence in PostGIS; add spatial/time-window clustering and a source-diversity model.
3. Add independent rainfall, gauge, road-closure, and trusted-source feeds for evidence-backed verification.
4. Add operator review, audit history, and explicit approval workflows.
5. Add a constrained vehicle routing solver only after resource, capacity, depot, and travel-time data are defined.

