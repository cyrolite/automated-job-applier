"""Screening postings for new-graduate suitability.

Needed because no board filters this reliably. LinkedIn treats its experience
parameter as a hint, and a MyCareersFuture keyword search for "security
engineer" happily returns heads of department. So seniority is judged from the
posting itself.

Every decision carries a reason, so an exclusion can be argued with rather
than silently trusted.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .sources.base import Posting

# Title words that rule a role out for someone still graduating.
_SENIOR_TITLE = re.compile(
    r"(?i)\b(senior|snr|sr\.?|staff|principal|lead|leader|head\s+of|director|"
    r"vp|vice\s+president|chief|cto|ciso|architect|manager|supervisor|"
    r"specialist\s+iv|expert|distinguished|fellow)\b"
)
# Roman/arabic level markers: "Engineer III", "Analyst 3".
_LEVEL_MARKER = re.compile(r"(?i)\b(engineer|analyst|developer|consultant)\s+(iii|iv|v|3|4|5)\b")

# Title words that actively signal the right level.
_JUNIOR_TITLE = re.compile(
    r"(?i)\b(graduate|grad|fresh|freshers?|entry[\s-]?level|junior|jnr|jr\.?|"
    r"intern|internship|trainee|associate|apprentice|campus|"
    r"university|undergraduate|management\s+trainee|rotational)\b"
)

_YEARS = re.compile(
    r"(?i)(?:minimum\s+(?:of\s+)?|at\s+least\s+|)(\d{1,2})\s*\+?\s*"
    r"(?:to\s*\d{1,2}\s*)?year?s?(?:\s+of)?\s+(?:relevant\s+|proven\s+|hands[\s-]on\s+)?"
    r"(?:work\s+|professional\s+|industry\s+)?experience"
)
# "under 2 years", "less than 3 years" is a new-grad signal, not a barrier.
_YEARS_CEILING = re.compile(
    r"(?i)\b(?:under|less\s+than|no\s+more\s+than|up\s+to|fewer\s+than|within)\s+(\d{1,2})\s*\+?\s*years?"
)


@dataclass
class Screen:
    suitable: bool = True
    seniority: str = "unknown"      # entry | mid | senior | unknown
    years_required: int | None = None
    reasons: list[str] = field(default_factory=list)

    def reject(self, seniority: str, reason: str) -> "Screen":
        self.suitable = False
        self.seniority = seniority
        self.reasons.append(reason)
        return self


def required_years(text: str) -> int | None:
    """Smallest stated years-of-experience requirement, ignoring ceilings.

    'under 2 years of full-time work experience' is an upper bound on a
    new-grad posting, so it must not be read as a two-year requirement.
    """
    if not text:
        return None
    ceilings = {m.start() for m in _YEARS_CEILING.finditer(text)}
    found: list[int] = []
    for m in _YEARS.finditer(text):
        # Skip a match that sits inside a "under N years" phrase.
        if any(abs(m.start() - c) < 40 for c in ceilings):
            continue
        try:
            found.append(int(m.group(1)))
        except ValueError:
            continue
    return min(found) if found else None


def screen(posting: Posting, max_years: int = 2) -> Screen:
    """Judge whether a posting is realistic for a 2027 graduate."""
    s = Screen()
    title = posting.title or ""
    body = posting.description or ""

    junior_title = bool(_JUNIOR_TITLE.search(title))

    # --- title seniority ---
    if _SENIOR_TITLE.search(title) and not junior_title:
        word = _SENIOR_TITLE.search(title).group(0)
        return s.reject("senior", f"title says {word!r}")
    if _LEVEL_MARKER.search(title) and not junior_title:
        return s.reject("mid", f"title is a level-3-or-above role: {_LEVEL_MARKER.search(title).group(0)!r}")

    # --- stated experience ---
    years = posting.min_years_experience
    if years is None:
        years = required_years(body)
    s.years_required = years
    if years is not None and years > max_years:
        # An explicit graduate title outranks boilerplate in the body.
        if junior_title:
            s.reasons.append(
                f"body asks for {years} years but the title is a graduate role — kept, worth a look"
            )
        else:
            return s.reject("mid" if years <= 5 else "senior", f"asks for {years} years of experience")

    # --- positive signals ---
    if junior_title:
        s.seniority = "entry"
        s.reasons.append(f"title signals an entry-level role: {_JUNIOR_TITLE.search(title).group(0)!r}")
    elif _JUNIOR_TITLE.search(body[:1500]):
        s.seniority = "entry"
        s.reasons.append("description mentions graduate or entry-level hiring")
    elif years is not None and years <= max_years:
        s.seniority = "entry"
        s.reasons.append(f"asks for only {years} years")

    if _YEARS_CEILING.search(body):
        s.seniority = "entry"
        s.reasons.append("posting caps experience, so it targets recent graduates")

    return s
