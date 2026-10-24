"""Small SQLite store for local operator review and restart-safe incidents."""

from __future__ import annotations

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
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS incidents (id TEXT PRIMARY KEY, status TEXT NOT NULL, urgency REAL NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS source_ids (source_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, actor TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

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
                for source in incident.sources:
                    db.execute("INSERT OR IGNORE INTO source_ids(source_id,incident_id) VALUES(?,?)", (f"{source.type}:{source.id}", str(incident.incident_id)))

    def has_source(self, source_type: str, source_id: str) -> bool:
        with self._lock, self._connect() as db:
            return db.execute("SELECT 1 FROM source_ids WHERE source_id=?", (f"{source_type}:{source_id}",)).fetchone() is not None

    def list(self) -> list[Incident]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT payload FROM incidents ORDER BY urgency DESC, updated_at DESC").fetchall()
        return [Incident.model_validate_json(row["payload"]) for row in rows]

    def get(self, incident_id: str) -> Incident | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM incidents WHERE id=?", (incident_id,)).fetchone()
        return Incident.model_validate_json(row["payload"]) if row else None

    def update(self, incident: Incident, actor: str = "operator", note: str = "") -> None:
        with self._lock, self._connect() as db:
            cursor = db.execute("UPDATE incidents SET status=?, urgency=?, payload=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (incident.verification.status.value, incident.urgency.score,
                                 incident.model_dump_json(), str(incident.incident_id)))
            if cursor.rowcount == 0:
                raise KeyError(str(incident.incident_id))
            db.execute("INSERT INTO audit(incident_id,actor,status,note) VALUES(?,?,?,?)",
                       (str(incident.incident_id), actor, incident.verification.status.value, note))

    def history(self, incident_id: str) -> list[dict]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT actor,status,note,created_at FROM audit WHERE incident_id=? ORDER BY id DESC", (incident_id,)).fetchall()
        return [dict(row) for row in rows]

