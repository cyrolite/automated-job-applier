"""Nudges derived from the tracker.

Nothing is sent anywhere. This reads the tracker and tells you what has gone
quiet or is about to close, which is the part of a job search that actually
gets dropped.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from .tracker import Application, Tracker

# How long a status may sit untouched before it is worth a nudge.
STALE_AFTER = {
    "applied": 14,
    "screening": 7,
    "interview": 7,
    "drafted": 3,
}

ACTION = {
    "deadline": "closes soon — finish and submit",
    "deadline_discovered": "closes soon and you have not drafted it yet",
    "stale_applied": "no reply since you applied — worth a polite follow-up",
    "stale_screening": "screening has gone quiet — check in",
    "stale_interview": "no word since the interview — check in",
    "stale_drafted": "drafted but never submitted",
    "expired": "the deadline has passed",
}


@dataclass
class Nudge:
    app: Application
    kind: str
    detail: str
    urgency: int          # lower sorts first

    @property
    def line(self) -> str:
        who = f"{self.app.company or '?'} — {self.app.title or '?'}"
        return f"{who}  [{self.app.status}]  {self.detail}"


def _days_since(stamp: str | None) -> int | None:
    if not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp).date()
    except ValueError:
        return None
    return (date.today() - then).days


def nudges(tracker: Tracker | None = None, deadline_window: int = 7) -> list[Nudge]:
    tracker = tracker or Tracker()
    out: list[Nudge] = []

    for app in tracker.list(limit=500):
        if app.status in ("rejected", "withdrawn", "offer"):
            continue

        days_left = app.days_to_deadline

        if days_left is not None and days_left < 0 and app.status in ("discovered", "drafted"):
            out.append(Nudge(app, "expired", ACTION["expired"], 0))
            continue

        if days_left is not None and 0 <= days_left <= deadline_window:
            if app.status == "discovered":
                out.append(Nudge(app, "deadline_discovered",
                                 f"{ACTION['deadline_discovered']} ({days_left}d left)", 1))
            elif app.status == "drafted":
                out.append(Nudge(app, "deadline",
                                 f"{ACTION['deadline']} ({days_left}d left)", 1))
            continue

        limit = STALE_AFTER.get(app.status)
        if limit is None:
            continue
        idle = _days_since(app.applied_at if app.status == "applied" else app.updated_at)
        if idle is not None and idle >= limit:
            kind = f"stale_{app.status}"
            out.append(Nudge(app, kind, f"{ACTION.get(kind, 'needs attention')} ({idle}d)", 2))

    out.sort(key=lambda n: (n.urgency, n.app.deadline or "9999-12-31"))
    return out


def report(tracker: Tracker | None = None, deadline_window: int = 7) -> str:
    items = nudges(tracker, deadline_window)
    if not items:
        return "Nothing needs chasing. Everything is either in flight or closed."
    lines = [f"{len(items)} thing(s) need attention:", ""]
    lines += [f"  {n.line}" for n in items]
    return "\n".join(lines)
