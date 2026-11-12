"""Lever job boards.

Public, keyless postings API:
    GET https://api.lever.co/v0/postings/{company}?mode=json

Verified shape: a top-level array. Each posting carries descriptionPlain,
descriptionBodyPlain, additionalPlain, a `lists` array of
{text: heading, content: HTML}, categories {commitment, location, team,
allLocations}, country, workplaceType, hostedUrl, applyUrl, createdAt (epoch ms).

The `lists` sections are where requirements live, so they are reassembled with
their headings intact — the JD parser needs them to tell a must-have from a
nice-to-have.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ..net import fetcher
from .base import Posting, Source, html_to_text

API = "https://api.lever.co/v0/postings/{company}?mode=json"


class LeverSource(Source):
    name = "lever"

    def __init__(self, token: str, company: str = ""):
        self.token = token
        self.company = company or token.replace("-", " ").title()

    @staticmethod
    def _description(job: dict) -> str:
        parts: list[str] = []
        head = job.get("descriptionPlain") or html_to_text(job.get("description") or "")
        if head:
            parts.append(head)
        for section in job.get("lists") or []:
            heading = (section.get("text") or "").strip()
            body = html_to_text(section.get("content") or "")
            if heading:
                parts.append(f"{heading}:")
            if body:
                parts.append(body)
        extra = job.get("additionalPlain") or ""
        if extra:
            parts.append(extra)
        return "\n\n".join(p for p in parts if p).strip()

    def fetch(self, limit: int = 500) -> Iterable[Posting]:
        data = fetcher.get_json(API.format(company=self.token))
        for job in (data or [])[:limit]:
            yield self._to_posting(job)

    def _to_posting(self, job: dict) -> Posting:
            cats = job.get("categories") or {}
            created = job.get("createdAt")
            posted = ""
            if isinstance(created, (int, float)):
                posted = datetime.fromtimestamp(
                    created / 1000, tz=timezone.utc
                ).date().isoformat()
            workplace = (job.get("workplaceType") or "").lower()
            loc = cats.get("location") or ""
            return Posting(
                source=self.name,
                source_id=str(job.get("id") or ""),
                title=(job.get("text") or "").strip(),
                company=self.company,
                location=loc,
                url=job.get("hostedUrl") or "",
                apply_url=job.get("applyUrl") or job.get("hostedUrl") or "",
                description=self._description(job),
                posted_at=posted,
                employment_type=cats.get("commitment") or "",
                remote=workplace == "remote" or "remote" in loc.lower(),
                extra={
                    "team": cats.get("team"),
                    "all_locations": cats.get("allLocations"),
                    "country": job.get("country"),
                    "workplace_type": job.get("workplaceType"),
                },
            )
