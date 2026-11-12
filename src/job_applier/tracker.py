"""Application tracker backed by SQLite.

One row per application, plus an event log so you can see what happened and
when. Local file, no service, no account.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from .config import settings

STATUSES = [
    "discovered",
    "drafted",
    "applied",
    "screening",
    "interview",
    "offer",
    "rejected",
    "withdrawn",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT UNIQUE NOT NULL,
    company         TEXT NOT NULL DEFAULT '',
    title           TEXT NOT NULL DEFAULT '',
    location        TEXT NOT NULL DEFAULT '',
    url             TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'discovered',
    fit_score       REAL,
    required_score  REAL,
    folder          TEXT NOT NULL DEFAULT '',
    deadline        TEXT,
    applied_at      TEXT,
    notes           TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id  INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    ts              TEXT NOT NULL,
    kind            TEXT NOT NULL,
    detail          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_app ON events(application_id);
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);

-- Discovery already downloaded the full job description. Keeping it here is
-- what lets `apply --from-queue` skip the manual copy-paste entirely.
CREATE TABLE IF NOT EXISTS postings (
    slug         TEXT PRIMARY KEY,
    source       TEXT NOT NULL DEFAULT '',
    payload      TEXT NOT NULL,
    captured_at  TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Application:
    id: int
    slug: str
    company: str
    title: str
    location: str
    url: str
    status: str
    fit_score: float | None
    required_score: float | None
    folder: str
    deadline: str | None
    applied_at: str | None
    notes: str
    created_at: str
    updated_at: str

    @property
    def days_to_deadline(self) -> int | None:
        if not self.deadline:
            return None
        try:
            d = date.fromisoformat(self.deadline[:10])
        except ValueError:
            return None
        return (d - date.today()).days


class Tracker:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or settings.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------- writes ----------
    def upsert(
        self,
        slug: str,
        *,
        company: str = "",
        title: str = "",
        location: str = "",
        url: str = "",
        status: str | None = None,
        fit_score: float | None = None,
        required_score: float | None = None,
        folder: str = "",
        deadline: str | None = None,
        notes: str | None = None,
    ) -> int:
        with self._conn() as c:
            row = c.execute("SELECT id FROM applications WHERE slug = ?", (slug,)).fetchone()
            if row:
                app_id = int(row["id"])
                fields: dict[str, object] = {
                    "company": company, "title": title, "location": location,
                    "url": url, "folder": folder,
                }
                sets = {k: v for k, v in fields.items() if v}
                if status:
                    sets["status"] = status
                if fit_score is not None:
                    sets["fit_score"] = fit_score
                if required_score is not None:
                    sets["required_score"] = required_score
                if deadline is not None:
                    sets["deadline"] = deadline
                if notes is not None:
                    sets["notes"] = notes
                sets["updated_at"] = _now()
                clause = ", ".join(f"{k} = ?" for k in sets)
                c.execute(
                    f"UPDATE applications SET {clause} WHERE id = ?",
                    (*sets.values(), app_id),
                )
                return app_id

            ts = _now()
            cur = c.execute(
                """INSERT INTO applications
                   (slug, company, title, location, url, status, fit_score,
                    required_score, folder, deadline, notes, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (slug, company, title, location, url, status or "discovered",
                 fit_score, required_score, folder, deadline, notes or "", ts, ts),
            )
            return int(cur.lastrowid)

    def set_status(self, slug: str, status: str, detail: str = "") -> None:
        if status not in STATUSES:
            raise ValueError(f"Unknown status {status!r}. Use one of: {', '.join(STATUSES)}")
        with self._conn() as c:
            row = c.execute("SELECT id FROM applications WHERE slug = ?", (slug,)).fetchone()
            if not row:
                raise KeyError(f"No application with slug {slug!r}")
            app_id = int(row["id"])
            applied_at = _now() if status == "applied" else None
            if applied_at:
                c.execute(
                    "UPDATE applications SET status=?, applied_at=COALESCE(applied_at,?), updated_at=? WHERE id=?",
                    (status, applied_at, _now(), app_id),
                )
            else:
                c.execute(
                    "UPDATE applications SET status=?, updated_at=? WHERE id=?",
                    (status, _now(), app_id),
                )
            c.execute(
                "INSERT INTO events (application_id, ts, kind, detail) VALUES (?,?,?,?)",
                (app_id, _now(), f"status:{status}", detail),
            )

    def save_posting(self, slug: str, source: str, payload: dict) -> None:
        """Store the posting a role was discovered from, verbatim."""
        import json

        with self._conn() as c:
            c.execute(
                """INSERT INTO postings (slug, source, payload, captured_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(slug) DO UPDATE SET
                     source=excluded.source,
                     payload=excluded.payload,
                     captured_at=excluded.captured_at""",
                (slug, source, json.dumps(payload, ensure_ascii=False), _now()),
            )

    def get_posting(self, slug: str) -> dict | None:
        import json

        with self._conn() as c:
            row = c.execute(
                "SELECT payload FROM postings WHERE slug = ?", (slug,)
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            return None

    def log(self, slug: str, kind: str, detail: str = "") -> None:
        with self._conn() as c:
            row = c.execute("SELECT id FROM applications WHERE slug = ?", (slug,)).fetchone()
            if not row:
                return
            c.execute(
                "INSERT INTO events (application_id, ts, kind, detail) VALUES (?,?,?,?)",
                (int(row["id"]), _now(), kind, detail),
            )

    # ---------- reads ----------
    def get(self, slug: str) -> Application | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM applications WHERE slug = ?", (slug,)).fetchone()
        return Application(**dict(row)) if row else None

    def list(self, status: str | None = None, limit: int = 200) -> list[Application]:
        q = "SELECT * FROM applications"
        params: tuple = ()
        if status:
            q += " WHERE status = ?"
            params = (status,)
        q += " ORDER BY (deadline IS NULL), deadline ASC, updated_at DESC LIMIT ?"
        with self._conn() as c:
            rows = c.execute(q, (*params, limit)).fetchall()
        return [Application(**dict(r)) for r in rows]

    def events(self, slug: str) -> list[sqlite3.Row]:
        with self._conn() as c:
            return c.execute(
                """SELECT e.* FROM events e JOIN applications a ON a.id = e.application_id
                   WHERE a.slug = ? ORDER BY e.ts DESC""",
                (slug,),
            ).fetchall()

    def counts(self) -> dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) n FROM applications GROUP BY status"
            ).fetchall()
        return {r["status"]: int(r["n"]) for r in rows}

    def due_soon(self, days: int = 7) -> list[Application]:
        out = []
        for a in self.list():
            d = a.days_to_deadline
            if d is not None and 0 <= d <= days and a.status in ("discovered", "drafted"):
                out.append(a)
        return out
