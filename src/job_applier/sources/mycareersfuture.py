"""MyCareersFuture — Singapore's national jobs portal (Workforce Singapore).

Public, keyless search API, verified against live data:
    GET https://api.mycareersfuture.gov.sg/v2/jobs
        ?search=<keywords>&limit=<=100&page=<n>&sortBy=new_posting_date

Response: {"results": [...], "total": int, "countWithoutFilters": int, "_links": {...}}

Each result carries structured fields the other boards do not: a skills list,
position levels, a salary band in SGD, minimum years of experience, and an
expiry date that doubles as a real application deadline.

The structured skills are appended to the description text, because the matcher
reads text — this is the one source that hands over a clean skills taxonomy and
it would be wasteful to drop it.
"""
from __future__ import annotations

import urllib.parse
from typing import Iterable

from ..net import fetcher
from .base import Posting, Source, html_to_text

BASE = "https://api.mycareersfuture.gov.sg/v2/jobs"
PAGE_SIZE = 100
PUBLIC_JOB_URL = "https://www.mycareersfuture.gov.sg/job/{uuid}"


class MyCareersFutureSource(Source):
    name = "mycareersfuture"

    def __init__(
        self,
        keywords: list[str] | str | None = None,
        max_per_keyword: int = 100,
        sort_by: str = "new_posting_date",
        min_salary: int = 0,
    ):
        if isinstance(keywords, str):
            keywords = [keywords]
        self.keywords = keywords or [""]
        self.max_per_keyword = max_per_keyword
        self.sort_by = sort_by
        self.min_salary = min_salary

    # ---------- helpers ----------
    @staticmethod
    def _location(job: dict) -> str:
        addr = job.get("address") or {}
        if addr.get("isOverseas"):
            country = addr.get("overseasCountry") or "Overseas"
            return str(country)
        districts = addr.get("districts") or []
        if districts:
            names = [str((d or {}).get("location", "")) for d in districts]
            names = [n for n in names if n]
            if names:
                return f"Singapore ({'; '.join(names[:2])})"
        return "Singapore"

    @staticmethod
    def _description(job: dict) -> str:
        parts = [html_to_text(job.get("description") or "")]

        skills = [
            str((s or {}).get("skill", "")).strip()
            for s in (job.get("skills") or [])
        ]
        skills = [s for s in skills if s]
        if skills:
            # Presented as a requirements block so the JD parser weights them
            # as requirements rather than loose prose.
            parts.append("Skills and experience:\n" + "\n".join(f"- {s}" for s in skills))

        levels = [
            str((p or {}).get("position", "")).strip()
            for p in (job.get("positionLevels") or [])
        ]
        levels = [l for l in levels if l]
        if levels:
            parts.append("Position level: " + ", ".join(levels))

        years = job.get("minimumYearsExperience")
        if isinstance(years, (int, float)) and years > 0:
            parts.append(f"Requires {int(years)} years experience.")

        other = job.get("otherRequirements")
        if other:
            parts.append(html_to_text(str(other)))
        return "\n\n".join(p for p in parts if p).strip()

    @classmethod
    def _to_posting(cls, job: dict) -> Posting | None:
        meta = job.get("metadata") or {}
        status = (job.get("status") or {}).get("jobStatus", "")
        if status and status.lower() != "open":
            return None

        posted = job.get("postedCompany") or {}
        hiring = job.get("hiringCompany") or {}
        company = (hiring.get("name") or posted.get("name") or "").strip()
        if meta.get("isHideEmployerName") and not hiring.get("name"):
            company = company or "(employer name withheld)"

        salary = job.get("salary") or {}
        hidden = bool(meta.get("isHideSalary"))
        uuid = str(job.get("uuid") or "")

        emp = [
            str((e or {}).get("employmentType", "")).strip()
            for e in (job.get("employmentTypes") or [])
        ]

        years = job.get("minimumYearsExperience")
        return Posting(
            source=cls.name,
            source_id=str(meta.get("jobPostId") or uuid),
            title=(job.get("title") or "").strip(),
            company=company,
            location=cls._location(job),
            url=meta.get("jobDetailsUrl") or PUBLIC_JOB_URL.format(uuid=uuid),
            apply_url=meta.get("jobDetailsUrl") or PUBLIC_JOB_URL.format(uuid=uuid),
            description=cls._description(job),
            posted_at=str(meta.get("newPostingDate") or meta.get("originalPostingDate") or "")[:10],
            deadline=str(meta.get("expiryDate") or "")[:10],
            employment_type=", ".join(e for e in emp if e),
            remote=False,
            salary_min=None if hidden else salary.get("minimum"),
            salary_max=None if hidden else salary.get("maximum"),
            salary_currency="" if hidden else "SGD",
            salary_period=(salary.get("type") or {}).get("salaryType", "") if not hidden else "",
            min_years_experience=int(years) if isinstance(years, (int, float)) else None,
            extra={
                "uen": posted.get("uen"),
                "categories": [
                    (c or {}).get("category") for c in (job.get("categories") or [])
                ],
                "position_levels": [
                    (p or {}).get("position") for p in (job.get("positionLevels") or [])
                ],
                "vacancies": job.get("numberOfVacancies"),
                "salary_hidden": hidden,
            },
        )

    # ---------- fetch ----------
    def fetch(self, limit: int = 300) -> Iterable[Posting]:
        seen: set[str] = set()
        emitted = 0
        for keyword in self.keywords:
            if emitted >= limit:
                return
            for page in range(0, (self.max_per_keyword // PAGE_SIZE) + 1):
                params = {
                    "limit": min(PAGE_SIZE, self.max_per_keyword),
                    "page": page,
                    "sortBy": self.sort_by,
                }
                if keyword:
                    params["search"] = keyword
                if self.min_salary:
                    params["salary"] = self.min_salary
                url = f"{BASE}?{urllib.parse.urlencode(params)}"
                data = fetcher.get_json(url)
                results = (data or {}).get("results") or []
                if not results:
                    break
                for job in results:
                    posting = self._to_posting(job)
                    if posting is None or not posting.title:
                        continue
                    if posting.source_id in seen:
                        continue
                    seen.add(posting.source_id)
                    yield posting
                    emitted += 1
                    if emitted >= limit:
                        return
                if len(results) < params["limit"]:
                    break
