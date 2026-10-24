"""Small SQLite store for local operator review and restart-safe incidents."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from threading import RLock

from .models import Incident


class IncidentStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or os.getenv("DATABASE_PATH", "data/incidents.sqlite3"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, status TEXT NOT NULL, urgency REAL NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def save_many(self, incidents: list[Incident]) -> None:
        with self._lock, self._connect() as db:
            for incident in incidents:
                db.execute("INSERT INTO incidents(id,status,urgency,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, urgency=excluded.urgency, payload=excluded.payload, updated_at=CURRENT_TIMESTAMP",
                           (str(incident.incident_id), incident.verification.status.value, incident.urgency.score,
                            incident.model_dump_json()))

    def list(self) -> list[Incident]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT payload FROM incidents ORDER BY urgency DESC, updated_at DESC").fetchall()
        return [Incident.model_validate_json(row["payload"]) for row in rows]

    def get(self, incident_id: str) -> Incident | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return Incident.model_validate_json(row["payload"]) if row else None

    def update(self, incident: Incident) -> None:
        with self._lock, self._connect() as db:
            cursor = db.execute("UPDATE incidents SET status=?, urgency=?, payload=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (incident.verification.status.value, incident.urgency.score,
                                 incident.model_dump_json(), str(incident.incident_id)))
            if cursor.rowcount == 0:
                raise KeyError(str(incident.incident_id))

