"""Ashby job boards.

Public, keyless posting API:
    GET https://api.ashbyhq.com/posting-api/job-board/{org}

Verified shape: {"jobs": [{id, title, department, team, employmentType,
location, secondaryLocations: [{location, address}], publishedAt, isListed,
isRemote, workplaceType, address, jobUrl, applyUrl, descriptionHtml,
descriptionPlain}]}.

Titles sometimes arrive with leading whitespace, so they are stripped.
"""
from __future__ import annotations

from typing import Iterable

from ..net import fetcher
from .base import Posting, Source, html_to_text

API = "https://api.ashbyhq.com/posting-api/job-board/{org}"


class AshbySource(Source):
    name = "ashby"

    def __init__(self, token: str, company: str = ""):
        self.token = token
        self.company = company or token.replace("-", " ").title()

    def fetch(self, limit: int = 500) -> Iterable[Posting]:
        data = fetcher.get_json(API.format(org=self.token))
        for job in (data or {}).get("jobs", [])[:limit]:
            posting = self._to_posting(job)
            if posting is not None:
                yield posting

    def _to_posting(self, job: dict) -> Posting | None:
            if job.get("isListed") is False:
                return None
            secondary = [
                (s or {}).get("location", "")
                for s in (job.get("secondaryLocations") or [])
            ]
            locations = [job.get("location") or ""] + [s for s in secondary if s]
            desc = job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml") or "")
            return Posting(
                source=self.name,
                source_id=str(job.get("id") or ""),
                title=(job.get("title") or "").strip(),
                company=self.company,
                location=" | ".join(dict.fromkeys(l for l in locations if l)),
                url=job.get("jobUrl") or "",
                apply_url=job.get("applyUrl") or job.get("jobUrl") or "",
                description=desc,
                posted_at=(job.get("publishedAt") or "")[:10],
                employment_type=job.get("employmentType") or "",
                remote=bool(job.get("isRemote")),
                extra={
                    "department": job.get("department"),
                    "team": job.get("team"),
                    "workplace_type": job.get("workplaceType"),
                },
            )
