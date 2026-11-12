"""Discovery: many sources in, one ranked queue out.

The pipeline is deliberately boring and deterministic:

    fetch  ->  merge duplicates  ->  screen seniority  ->  score against the
    profile  ->  drop blockers and weak fits  ->  rank  ->  write to tracker

Nothing here calls a model. The same postings always produce the same queue,
and every rejection carries a reason you can read back.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ats
from .filters import Screen, screen as screen_posting
from .net import Blocked
from .profile import Profile
from .sources.base import Posting, Source
from .tracker import Tracker

# When the same role appears on several boards, keep the entry from the source
# closest to the employer: a company ATS link applies directly, an aggregator
# link often bounces through a redirect or expires.
SOURCE_PRIORITY = {
    "greenhouse": 0,
    "lever": 0,
    "ashby": 0,
    "mycareersfuture": 1,
    "linkedin": 2,
    "jobstreet": 2,
    "indeed": 3,
    "glassdoor": 3,
}


def _priority(p: Posting) -> int:
    return SOURCE_PRIORITY.get(p.source, 5)


@dataclass
class Candidate:
    posting: Posting
    report: ats.MatchReport
    screen: Screen
    also_on: list[str] = field(default_factory=list)

    @property
    def required_score(self) -> float:
        return self.report.required_score

    @property
    def score(self) -> float:
        return self.report.score

    @property
    def blockers(self) -> list:
        return self.report.blockers


@dataclass
class DiscoveryResult:
    candidates: list[Candidate] = field(default_factory=list)
    rejected: list[tuple[Posting, str]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)
    fetched: int = 0
    unique: int = 0

    def summary(self) -> str:
        lines = [
            f"fetched {self.fetched} postings, {self.unique} unique after merging, "
            f"{len(self.candidates)} worth applying to"
        ]
        if self.rejected:
            lines.append(f"{len(self.rejected)} screened out")
        for name, err in self.errors:
            lines.append(f"source {name} failed: {err}")
        return "\n".join(lines)


# ----------------------------------------------------------------------
def merge_duplicates(postings: list[Posting]) -> list[tuple[Posting, list[str]]]:
    """Collapse the same role across boards into one entry.

    The surviving posting takes the best description found anywhere and the
    most direct apply link, so merging adds information rather than losing it.
    """
    groups: dict[str, list[Posting]] = {}
    for p in postings:
        groups.setdefault(p.dedupe_key, []).append(p)

    merged: list[tuple[Posting, list[str]]] = []
    for group in groups.values():
        group.sort(key=lambda p: (_priority(p), -len(p.description or "")))
        best = group[0]

        # Take the richest description available for this role.
        richest = max(group, key=lambda p: len(p.description or ""))
        if len(richest.description or "") > len(best.description or ""):
            best.description = richest.description

        # Fill blanks from siblings rather than discarding what they knew.
        for other in group[1:]:
            for attr in (
                "location", "deadline", "posted_at", "employment_type",
                "salary_min", "salary_max", "salary_currency", "salary_period",
                "min_years_experience", "apply_url",
            ):
                if not getattr(best, attr, None) and getattr(other, attr, None):
                    setattr(best, attr, getattr(other, attr))

        also_on = sorted({p.source for p in group[1:]})
        merged.append((best, also_on))
    return merged


def discover(
    sources: list[Source],
    profile: Profile | None = None,
    *,
    max_years: int = 2,
    min_required_score: float = 45.0,
    per_source_limit: int = 300,
    keep_blocked: bool = False,
) -> DiscoveryResult:
    profile = profile or Profile.load()
    result = DiscoveryResult()

    raw: list[Posting] = []
    for source in sources:
        if not getattr(source, "automated", True):
            continue   # browser-assisted boards come in through `ingest`
        try:
            got = list(source.fetch(limit=per_source_limit))
            raw.extend(got)
            result.fetched += len(got)
        except Blocked as e:
            result.errors.append((source.name, str(e)))
        except Exception as e:  # a bad token should not kill the whole run
            result.errors.append((source.name, f"{type(e).__name__}: {e}"))

    return score_postings(
        raw,
        profile,
        result=result,
        max_years=max_years,
        min_required_score=min_required_score,
        keep_blocked=keep_blocked,
    )


def score_postings(
    postings: list[Posting],
    profile: Profile | None = None,
    *,
    result: DiscoveryResult | None = None,
    max_years: int = 2,
    min_required_score: float = 45.0,
    keep_blocked: bool = False,
) -> DiscoveryResult:
    """Screen, score and rank postings. Used by both discovery and ingest."""
    profile = profile or Profile.load()
    result = result or DiscoveryResult(fetched=len(postings))

    merged = merge_duplicates(postings)
    result.unique = len(merged)

    for posting, also_on in merged:
        verdict = screen_posting(posting, max_years=max_years)
        if not verdict.suitable:
            result.rejected.append((posting, verdict.reasons[0] if verdict.reasons else "screened out"))
            continue

        report = ats.match(posting.to_jd(), profile)

        hard = [h for h in report.hard_requirements if h.verdict == "blocker"]
        if hard and not keep_blocked:
            result.rejected.append((posting, f"blocker — {hard[0].detail}"))
            continue

        if report.required_score < min_required_score:
            result.rejected.append(
                (posting, f"must-have coverage {report.required_score}% below {min_required_score:g}%")
            )
            continue

        result.candidates.append(Candidate(posting, report, verdict, also_on))

    # Best fit first; among equals, the soonest deadline.
    result.candidates.sort(
        key=lambda c: (-c.required_score, c.posting.deadline or "9999-12-31")
    )
    return result


# ----------------------------------------------------------------------
def record(result: DiscoveryResult, tracker: Tracker | None = None) -> int:
    """Write discovered roles into the tracker without disturbing anything
    you have already drafted or applied to."""
    tracker = tracker or Tracker()
    written = 0
    for c in result.candidates:
        p = c.posting
        slug = p.slug()
        existing = tracker.get(slug)
        if existing and existing.status not in ("discovered",):
            continue   # already in flight; leave it alone
        note = f"found on {p.source}"
        if c.also_on:
            note += f" (also on {', '.join(c.also_on)})"
        tracker.upsert(
            slug,
            company=p.company,
            title=p.title,
            location=p.location,
            url=p.url or p.apply_url,
            status="discovered",
            fit_score=c.score,
            required_score=c.required_score,
            deadline=p.deadline or None,
            notes=note,
        )
        # Keep the description we already paid to fetch, so `apply --from-queue`
        # can build the documents without asking for the text again.
        try:
            tracker.save_posting(slug, p.source, p.as_dict())
        except Exception:
            pass
        written += 1
    return written
