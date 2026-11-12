"""Boards with no public API: LinkedIn, JobStreet, Glassdoor, Indeed.

None of these publish a job-search API, and their terms of use prohibit
automated scraping. So this module does not fetch them. Instead:

  1. It builds the correct search URL (see search_urls.py).
  2. You, or the browser agent, open that URL in your own signed-in browser and
     read the results — pages you are entitled to see, at human pace.
  3. The agent hands the postings back as JSON records, and this module
     normalises them into the same Posting model as the API sources.

That split is deliberate. Perception stays in the browser, where a person is
present and a bot check can be respected. Everything deterministic — scoring,
dedupe, screening, tracking — stays here in Python.

Nothing in this file bypasses a CAPTCHA, a login wall or a rate limit. If a
board challenges the session, the answer is to stop.

Record schema accepted by parse_records (only `title` is required):

    {
      "title": "Security Engineer, University Graduate (2027)",
      "company": "Acme Corp",
      "location": "Singapore",
      "url": "https://...",
      "apply_url": "https://...",
      "description": "full posting text",
      "posted_at": "2026-11-10",
      "deadline": "2026-12-15",
      "employment_type": "Full Time",
      "remote": false,
      "salary_min": 5000, "salary_max": 7000,
      "salary_currency": "SGD", "salary_period": "Monthly"
    }
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Iterable

from .. import search_urls
from .base import Posting, Source, html_to_text

BROWSER_BOARDS = ("linkedin", "jobstreet", "glassdoor", "indeed", "mycareersfuture_web")


def _num(v) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return None


def _truthy(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y", "remote")


def parse_records(records: Iterable[dict], source: str) -> list[Posting]:
    """Normalise captured records into Postings, skipping unusable rows."""
    out: list[Posting] = []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            continue
        title = str(rec.get("title") or rec.get("job_title") or "").strip()
        if not title:
            continue
        desc = str(rec.get("description") or rec.get("job_description") or "")
        if "<" in desc and ">" in desc:
            desc = html_to_text(desc)
        url = str(rec.get("url") or rec.get("job_url") or rec.get("link") or "").strip()
        sid = str(rec.get("id") or rec.get("source_id") or "").strip()
        if not sid:
            # Stable enough to dedupe repeat captures of the same search.
            sid = url or f"{source}:{title}:{rec.get('company','')}:{i}"
        out.append(
            Posting(
                source=source,
                source_id=sid,
                title=title,
                company=str(rec.get("company") or rec.get("employer") or "").strip(),
                location=str(rec.get("location") or "").strip(),
                url=url,
                apply_url=str(rec.get("apply_url") or url).strip(),
                description=desc.strip(),
                posted_at=str(rec.get("posted_at") or rec.get("posted") or "")[:10],
                deadline=str(rec.get("deadline") or "")[:10],
                employment_type=str(rec.get("employment_type") or rec.get("job_type") or "").strip(),
                remote=_truthy(rec.get("remote")) or "remote" in str(rec.get("location", "")).lower(),
                salary_min=_num(rec.get("salary_min")),
                salary_max=_num(rec.get("salary_max")),
                salary_currency=str(rec.get("salary_currency") or "").strip(),
                salary_period=str(rec.get("salary_period") or "").strip(),
                extra={"captured_from": source},
            )
        )
    return out


def load_capture(path: str | Path, source: str) -> list[Posting]:
    """Read a capture file: JSON array, JSON object with `jobs`/`results`,
    JSON Lines, or CSV/TSV with a header row."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []

    suffix = p.suffix.lower()
    if suffix in (".csv", ".tsv"):
        delim = "\t" if suffix == ".tsv" else ","
        return parse_records(list(csv.DictReader(text.splitlines(), delimiter=delim)), source)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # JSON Lines
        rows = []
        for line in text.splitlines():
            line = line.strip().rstrip(",")
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if rows:
            return parse_records(rows, source)
        raise ValueError(
            f"{p} is not JSON, JSON Lines or CSV. See the record schema in "
            "sources/browser.py."
        )

    if isinstance(data, dict):
        for key in ("jobs", "results", "postings", "data", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        raise ValueError(f"{p} did not contain a list of postings")
    return parse_records(data, source)


class BrowserAssistedSource(Source):
    """A board that must be read through a real browser session."""

    automated = False

    def __init__(self, board: str, keywords: list[str] | str, **options):
        board = board.lower().replace("-", "_")
        if board not in BROWSER_BOARDS:
            raise ValueError(f"Unknown browser board {board!r}")
        self.name = board
        self.keywords = [keywords] if isinstance(keywords, str) else list(keywords)
        self.options = options

    def search_urls(self) -> list[str]:
        return [search_urls.build(self.name, kw, **self.options) for kw in self.keywords]

    def fetch(self, limit: int = 100):
        raise RuntimeError(
            f"{self.name} has no public API and its terms prohibit automated "
            f"scraping, so it cannot be fetched directly.\n"
            f"Open these in your browser, then run `ja ingest`:\n  "
            + "\n  ".join(self.search_urls())
        )
