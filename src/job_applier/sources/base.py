"""The common posting model every source normalises into."""
from __future__ import annotations

import html as _html
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Iterator

from ..jd import JobDescription

_BLOCK_CLOSE = re.compile(
    r"(?i)</(p|div|li|ul|ol|h[1-6]|tr|table|section|article|blockquote)>"
)
_LIST_OPEN = re.compile(r"(?i)<li[^>]*>")
_BR = re.compile(r"(?i)<br\s*/?>")
_DROP = re.compile(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>")
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


def html_to_text(raw: str) -> str:
    """Turn a job description's HTML into readable plain text.

    Structure is preserved where it matters, because the JD parser uses
    headings and bullets to tell a requirement from a nice-to-have.
    """
    if not raw:
        return ""
    if "<" not in raw:
        return raw.strip()
    s = _DROP.sub(" ", raw)
    s = _BR.sub("\n", s)
    s = _LIST_OPEN.sub("\n- ", s)
    s = _BLOCK_CLOSE.sub("\n", s)
    s = _TAG.sub(" ", s)
    s = _html.unescape(s)
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in s.splitlines()]
    out = "\n".join(ln for ln in lines if ln)
    return _BLANKS.sub("\n\n", out).strip()


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


@dataclass
class Posting:
    source: str                     # "greenhouse", "mycareersfuture", ...
    source_id: str
    title: str
    company: str = ""
    location: str = ""
    url: str = ""
    apply_url: str = ""
    description: str = ""           # plain text
    posted_at: str = ""             # ISO date, best effort
    deadline: str = ""
    employment_type: str = ""
    remote: bool = False
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = ""
    salary_period: str = ""
    min_years_experience: int | None = None
    extra: dict = field(default_factory=dict)

    # ---------- identity ----------
    @property
    def dedupe_key(self) -> str:
        """The same role posted to three boards should collapse to one entry.

        Keyed on company plus title plus the first locality token, not on URL,
        because every board mints its own URL for the same job.
        """
        loc = _norm(self.location).split(" ")
        locality = loc[0] if loc and loc[0] else ""
        return f"{_norm(self.company)}|{_norm(self.title)}|{locality}"

    def slug(self) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", f"{self.company}-{self.title}".lower())
        return (base.strip("-") or "posting")[:70]

    # ---------- conversion ----------
    def to_jd(self) -> JobDescription:
        return JobDescription.from_text(
            self.description or self.title,
            title=self.title,
            company=self.company,
            location=self.location,
            url=self.url or self.apply_url,
        )

    def as_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        bits = [self.title]
        if self.company:
            bits.append(self.company)
        if self.location:
            bits.append(self.location)
        return " — ".join(bits)


class Source:
    """A place postings come from.

    Subclasses implement fetch(). Anything that raises net.Blocked is reported
    and skipped rather than retried, because a refusal is an answer.
    """

    name = "source"
    # False for sources that need the user's own browser session.
    automated = True

    def fetch(self, limit: int = 100) -> Iterable[Posting]:  # pragma: no cover
        raise NotImplementedError

    def __iter__(self) -> Iterator[Posting]:
        return iter(self.fetch())
