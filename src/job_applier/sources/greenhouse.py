"""Greenhouse job boards.

Public, keyless board API:
    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true

Verified shape: {"jobs": [{id, internal_job_id, title, absolute_url,
location: {name}, updated_at, first_published, requisition_id, company_name,
metadata: [...], application_deadline, content}]}.

`content` arrives HTML-escaped, so it is unescaped before being flattened.
"""
from __future__ import annotations

import html
from typing import Iterable

from ..net import fetcher
from .base import Posting, Source, html_to_text

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


class GreenhouseSource(Source):
    name = "greenhouse"

    def __init__(self, token: str, company: str = ""):
        self.token = token
        self.company = company or token.replace("-", " ").title()

    def fetch(self, limit: int = 500) -> Iterable[Posting]:
        data = fetcher.get_json(API.format(token=self.token))
        for job in (data or {}).get("jobs", [])[:limit]:
            yield self._to_posting(job)

    def _to_posting(self, job: dict) -> Posting:
            content = job.get("content") or ""
            if "&lt;" in content:          # double-escaped HTML
                content = html.unescape(content)
            loc = (job.get("location") or {}).get("name", "")
            meta = {
                str(m.get("name")): m.get("value")
                for m in (job.get("metadata") or [])
                if m.get("name")
            }
            return Posting(
                source=self.name,
                source_id=str(job.get("id") or job.get("internal_job_id") or ""),
                title=(job.get("title") or "").strip(),
                company=job.get("company_name") or self.company,
                location=loc,
                url=job.get("absolute_url") or "",
                apply_url=job.get("absolute_url") or "",
                description=html_to_text(content),
                posted_at=(job.get("first_published") or "")[:10],
                deadline=(job.get("application_deadline") or "" or "")[:10],
                remote="remote" in f"{loc} {meta.get('Location Type','')}".lower(),
                extra={"requisition_id": job.get("requisition_id"), "metadata": meta},
            )
