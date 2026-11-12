"""Making the resume actually fit the page count you asked for.

`JA_MAX_PAGES` used to be a request passed to the model and nothing more, so a
one-page setting happily produced two pages. This measures the rendered PDF and
trims the least valuable content until it fits.

Trimming only ever *removes* content, so a fitted resume stays as truthful as
the one it came from. What goes first is what a reader values least:

    summary -> activities -> extra projects -> thin bullets on old roles
    -> courses and languages -> the least relevant role

Everything removed is reported, so you can see the cost of one page and
override it with JA_MAX_PAGES=2 if the trade is not worth it.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import render
from .profile import Profile
from .tailor import TailoredResume

# Roughly how many rendered lines fit on one page at the resume's geometry.
# Only used when no PDF can be produced, and reported as an estimate.
LINES_PER_PAGE = 52
CHARS_PER_LINE = 118


def count_pages(pdf_path: Path) -> int | None:
    """Exact page count of a rendered PDF, or None if it cannot be read."""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return None
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf_path)).pages)
    except Exception:
        pass
    try:  # poppler, if it happens to be installed
        out = subprocess.run(
            ["pdfinfo", str(pdf_path)], capture_output=True, text=True, timeout=30
        ).stdout
        for line in out.splitlines():
            if line.lower().startswith("pages:"):
                return int(line.split(":", 1)[1].strip())
    except Exception:
        pass
    return None


def estimate_pages(tailored: TailoredResume, profile: Profile) -> float:
    """Fallback estimate from text volume, for machines with no PDF converter."""
    text = render.render_resume_text(tailored, profile)
    lines = 0
    for raw in text.splitlines():
        lines += max(1, -(-len(raw) // CHARS_PER_LINE))  # ceiling division
    return round(lines / LINES_PER_PAGE, 2)


# ----------------------------------------------------------------------
def _rank(tailored: TailoredResume) -> dict[str, int]:
    """How well each bullet answers this job description. Lower is better."""
    order = tailored.report.evidence_bullets if tailored.report else []
    rank = {bid: i for i, bid in enumerate(order)}
    return rank


def _section_score(section, rank: dict[str, int]) -> int:
    return min((rank.get(b.source_id, 10_000) for b in section.bullets), default=10_000)


def _droppability(index: int, section, rank: dict[str, int]) -> tuple[int, int]:
    """Higher means safer to cut: least relevant first, then oldest."""
    return (_section_score(section, rank), index)


def _worst(sections, rank):
    return max(
        enumerate(sections), key=lambda pair: _droppability(pair[0], pair[1], rank)
    )[1]


# The two most recent roles carry the most weight with a reader, so they keep at
# least this many bullets until there is genuinely nothing else to give up.
PROTECTED_ROLES = 2
PROTECTED_BULLETS = 2


def trim_once(tailored: TailoredResume) -> str | None:
    """Remove the single least valuable thing left. Returns what went, or None
    when there is nothing safe left to cut.

    The order matters more than the mechanism. Dropping a whole irrelevant role
    costs a reader nothing; thinning the most recent one costs a lot. So whole
    low-relevance roles go before bullets are shaved off strong ones.
    """
    rank = _rank(tailored)

    if tailored.summary:
        tailored.summary = None
        return "the summary paragraph"

    # Activities are the first thing a reader skims past.
    if len(tailored.activities) > 1:
        gone = _worst(tailored.activities, rank)
        tailored.activities.remove(gone)
        return f"activity: {gone.org}"

    if len(tailored.projects) > 2:
        gone = _worst(tailored.projects, rank)
        tailored.projects.remove(gone)
        return f"project: {gone.org}"

    # A whole unrelated role costs less than a bullet off a relevant one.
    if len(tailored.experience) > 4:
        gone = _worst(tailored.experience, rank)
        tailored.experience.remove(gone)
        return f"role: {gone.org} (least relevant to this posting)"

    # Thin the least relevant role that can spare a bullet, protecting the two
    # most recent ones.
    def thinnable(protect: bool):
        out = []
        for i, sec in enumerate(tailored.experience):
            floor = PROTECTED_BULLETS if (protect and i < PROTECTED_ROLES) else 1
            if len(sec.bullets) > floor:
                out.append((i, sec))
        return out

    for protect in (True, False):
        candidates = thinnable(protect)
        if not candidates:
            continue
        i, target = max(candidates, key=lambda pair: _droppability(pair[0], pair[1], rank))
        worst = max(target.bullets, key=lambda b: rank.get(b.source_id, 10_000))
        target.bullets.remove(worst)
        return f"a bullet from {target.org}"

    if tailored.show_courses:
        tailored.show_courses = False
        return "the additional courses line"

    if tailored.max_education_highlights is None:
        tailored.max_education_highlights = 1
        return "the second coursework line"

    if tailored.show_languages:
        tailored.show_languages = False
        return "the languages line"

    if len(tailored.activities) == 1:
        gone = tailored.activities.pop()
        return f"activity: {gone.org}"

    if len(tailored.projects) > 1:
        gone = _worst(tailored.projects, rank)
        tailored.projects.remove(gone)
        return f"project: {gone.org}"

    if len(tailored.experience) > 3:
        gone = _worst(tailored.experience, rank)
        tailored.experience.remove(gone)
        return f"role: {gone.org}"

    return None


@dataclass
class FitResult:
    docx: Path
    pdf: Path | None = None
    pages: int | None = None
    estimated: bool = False
    fitted: bool = True
    target: int = 1
    trimmed: list[str] = field(default_factory=list)

    def message(self) -> str:
        where = "estimated at" if self.estimated else ""
        pages = f"{self.pages} page(s)" if self.pages is not None else "unknown length"
        head = f"Resume is {where} {pages}".replace("  ", " ")
        if self.trimmed:
            head += f", after trimming {len(self.trimmed)} item(s) to reach {self.target}"
        if not self.fitted:
            head += (
                f" — still over the {self.target}-page target. Nothing else was safe "
                "to cut; set JA_MAX_PAGES=2 if that is the better trade."
            )
        return head


def render_fitted(
    tailored: TailoredResume,
    profile: Profile,
    path: Path,
    max_pages: int = 1,
    want_pdf: bool = True,
    max_attempts: int = 14,
) -> FitResult:
    """Render the resume, trimming until it fits `max_pages`.

    If no PDF converter is available the length is estimated instead, and the
    result says so rather than implying a measurement that did not happen.
    """
    path = Path(path)
    docx = render.render_resume_docx(tailored, profile, path)
    pdf = render.to_pdf(docx) if want_pdf else None
    pages = count_pages(pdf) if pdf else None

    estimated = pages is None
    if estimated:
        pages = max(1, int(estimate_pages(tailored, profile) + 0.5))

    trimmed: list[str] = []
    attempts = 0
    while pages is not None and pages > max_pages and attempts < max_attempts:
        what = trim_once(tailored)
        if what is None:
            break
        trimmed.append(what)
        attempts += 1

        docx = render.render_resume_docx(tailored, profile, path)
        if estimated:
            pages = max(1, int(estimate_pages(tailored, profile) + 0.5))
        else:
            pdf = render.to_pdf(docx)
            measured = count_pages(pdf) if pdf else None
            pages = measured if measured is not None else pages

    return FitResult(
        docx=docx,
        pdf=pdf,
        pages=pages,
        estimated=estimated,
        fitted=pages is not None and pages <= max_pages,
        target=max_pages,
        trimmed=trimmed,
    )
