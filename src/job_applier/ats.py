"""Deterministic JD <-> profile matching.

No model involved, so this runs with no API key and gives the same answer
every time. It produces the gap report that matters most:

  COVERED  — you have it, with evidence in the profile
  WEAK     — you have some exposure but thin evidence; claim carefully
  MISSING  — not in your profile at all; do not claim it

The point is not a vanity score. It is to tell you which real strengths to
surface, and which gaps are genuine so you stay honest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .jd import JobDescription
from .lexicon import ALL_TERMS, GENERIC_TERMS, SECTION_WEIGHTS, TERM_DOMAIN
from .profile import Profile, Skill

COVERED, WEAK, MISSING = "covered", "weak", "missing"

# How much a bullet gains per subject area it shares with the posting. Small
# enough that a direct keyword hit still dominates, large enough to separate
# bullets that would otherwise tie.
TAG_AFFINITY = 0.2

_STRONG_LEVELS = {"expert", "proficient"}


def _boundary(term: str) -> re.Pattern[str]:
    """Word-boundary regex tolerant of +, #, /, . and spacing in tech terms."""
    esc = re.escape(term)
    esc = esc.replace(r"\ ", r"[\s\-]+")      # "rest api" matches "rest-api"
    lead = r"(?<![A-Za-z0-9])"
    trail = r"(?![A-Za-z0-9])" if not term[-1].isalnum() else r"(?![A-Za-z0-9+#])"
    return re.compile(lead + esc + trail, re.IGNORECASE)


@dataclass
class Match:
    term: str
    status: str                       # covered | weak | missing
    weight: float = 0.0               # importance from JD sections
    sections: set[str] = field(default_factory=set)
    soft: bool = False                # generic phrasing: not evidence-checkable
    skill: str | None = None          # canonical profile skill name
    level: str | None = None
    evidence: list[str] = field(default_factory=list)   # bullet ids
    jd_snippets: list[str] = field(default_factory=list)

    @property
    def required(self) -> bool:
        return "requirement" in self.sections


@dataclass
class HardRequirement:
    kind: str          # years | degree | clearance | visa | grad_year | language
    detail: str
    verdict: str       # ok | check | blocker


@dataclass
class MatchReport:
    jd: JobDescription
    matches: list[Match]
    hard_requirements: list[HardRequirement]
    # Requirement lines where the vocabulary recognised nothing at all. These
    # are the matcher's blind spots, and they are reported rather than hidden:
    # a score computed only over terms it understood would be misleading.
    unmatched: list[str] = field(default_factory=list)
    # bullet id -> which profile section it came from, for ranking.
    _bullet_section: dict[str, str] = field(default_factory=dict)
    # bullet id -> its tags, for domain affinity.
    _bullet_tags: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # canonical skill name -> its tags.
    _skill_tags: dict[str, tuple[str, ...]] = field(default_factory=dict)

    # ---------- scoring ----------
    @property
    def score(self) -> float:
        """Weighted keyword coverage, 0-100. WEAK counts half."""
        total = sum(m.weight for m in self.matches)
        if total == 0:
            return 0.0
        got = sum(
            m.weight * (1.0 if m.status == COVERED else 0.5 if m.status == WEAK else 0.0)
            for m in self.matches
        )
        return round(100 * got / total, 1)

    @property
    def required_score(self) -> float:
        """Coverage of must-have requirements only — the number that matters."""
        req = [m for m in self.matches if m.required]
        total = sum(m.weight for m in req)
        if total == 0:
            return self.score
        got = sum(
            m.weight * (1.0 if m.status == COVERED else 0.5 if m.status == WEAK else 0.0)
            for m in req
        )
        return round(100 * got / total, 1)

    @property
    def domain_tags(self) -> set[str]:
        """The subject areas this posting is about, from the skills it names.

        Keyword hits alone rank a Java address-book project above an AI
        security project on a security posting, because both merely say
        "Java". Knowing the posting is a security posting fixes that.
        """
        tags: set[str] = set()
        for m in self.matches:
            # Every matched term counts, including ones the candidate lacks:
            # a posting demanding smart contracts is about blockchain whether
            # or not he has touched it.
            tags.update(TERM_DOMAIN.get(m.term.lower(), ()))
            if m.skill:
                tags.update(self._skill_tags.get(m.skill, ()))
        return tags

    def by_status(self, status: str, include_soft: bool = True) -> list[Match]:
        items = [m for m in self.matches if m.status == status]
        if status == MISSING or not include_soft:
            # Generic phrasing you did not list is not a gap worth flagging.
            items = [m for m in items if not m.soft]
        return sorted(items, key=lambda m: (-m.weight, m.term))

    @property
    def surface_these(self) -> list[Match]:
        """Covered skills the JD asks for — these must appear on the resume."""
        return [m for m in self.by_status(COVERED) if m.weight >= 0.5]

    @property
    def evidence_bullets(self) -> list[str]:
        """Profile bullet ids backing the JD's asks, best first.

        Ranked by how much JD weight a bullet carries, then by how many
        distinct requirements it speaks to, then by section so paid work
        outranks coursework. The last key keeps the order stable.
        """
        weight: dict[str, float] = {}
        hits: dict[str, int] = {}
        for m in self.matches:
            if m.status == MISSING:
                continue
            for bid in m.evidence:
                weight[bid] = weight.get(bid, 0.0) + m.weight
                hits[bid] = hits.get(bid, 0) + 1

        # Credit a bullet for working in the posting's subject area, not just
        # for sharing a keyword with it.
        domain = self.domain_tags
        if domain:
            for bid in weight:
                shared = domain & set(self._bullet_tags.get(bid, ()))
                weight[bid] += TAG_AFFINITY * len(shared)

        section_rank = {"experience": 0, "projects": 1, "activities": 2, "education": 3}

        def sort_key(bid: str) -> tuple:
            b = self._bullet_section.get(bid, "education")
            return (-weight[bid], -hits[bid], section_rank.get(b, 9), bid)

        return sorted(weight, key=sort_key)

    @property
    def blockers(self) -> list[HardRequirement]:
        return [h for h in self.hard_requirements if h.verdict == "blocker"]

    # ---------- rendering ----------
    def to_markdown(self) -> str:
        jd = self.jd
        L: list[str] = []
        L.append(f"# Fit report — {jd.title or 'Untitled role'}")
        if jd.company:
            L.append(f"**Company:** {jd.company}")
        if jd.location:
            L.append(f"**Location:** {jd.location}")
        if jd.url:
            L.append(f"**Posting:** {jd.url}")
        L.append("")
        L.append(f"**Must-have coverage: {self.required_score}%**  ·  overall keyword coverage {self.score}%")
        if self.unmatched:
            L.append("")
            L.append(
                f"> The score covers only what the matcher recognised. "
                f"{len(self.unmatched)} requirement line(s) used vocabulary it does not know — "
                "read those yourself, below."
            )
        L.append("")

        if self.hard_requirements:
            L.append("## Hard requirements")
            icon = {"ok": "OK", "check": "CHECK", "blocker": "BLOCKER"}
            for h in self.hard_requirements:
                L.append(f"- **[{icon[h.verdict]}]** {h.kind}: {h.detail}")
            L.append("")

        cov = self.by_status(COVERED)
        if cov:
            L.append("## Surface these — you have real evidence")
            for m in cov:
                ev = f"  _(evidence: {', '.join(m.evidence)})_" if m.evidence else ""
                req = " **[required]**" if m.required else ""
                L.append(f"- {m.term}{req}{ev}")
            L.append("")

        weak = self.by_status(WEAK)
        if weak:
            L.append("## Claim carefully — thin evidence")
            for m in weak:
                req = " **[required]**" if m.required else ""
                lvl = f" (self-assessed: {m.level})" if m.level else ""
                L.append(f"- {m.term}{req}{lvl}")
            L.append("")

        miss = self.by_status(MISSING)
        if miss:
            L.append("## Genuine gaps — do not claim these")
            for m in miss:
                req = " **[required]**" if m.required else ""
                L.append(f"- {m.term}{req}")
            L.append("")
            req_missing = [m.term for m in miss if m.required]
            if req_missing:
                L.append(
                    "> Required and missing: "
                    + ", ".join(req_missing)
                    + ". Address these in the cover letter as adjacent experience, "
                      "or treat the role as a stretch."
                )
                L.append("")

        if self.unmatched:
            L.append("## Requirements the matcher could not read")
            L.append("")
            L.append("Judge these by hand. They are not counted in the score either way:")
            for line in self.unmatched:
                L.append(f"- {line}")
            L.append("")

        if self.evidence_bullets:
            L.append("## Profile bullets ranked for this role")
            for bid in self.evidence_bullets[:15]:
                L.append(f"- `{bid}`")
            L.append("")
        return "\n".join(L)


# ----------------------------------------------------------------------
# Hard requirement detection
# ----------------------------------------------------------------------
_YEARS = re.compile(
    r"(\d+)\s*\+?\s*(?:to\s*\d+\s*)?years?[\s\w]{0,25}?experience", re.IGNORECASE
)
_DEGREE = re.compile(
    r"\b(bachelor|b\.?s\.?c?\.?|master|m\.?s\.?c?\.?|phd|doctorate|degree)\b", re.IGNORECASE
)
_CLEARANCE = re.compile(
    r"\b(security clearance|ts/sci|top secret|public trust|clearance required)\b",
    re.IGNORECASE,
)
_VISA = re.compile(
    r"\b(work authoris?z?ation|right to work|visa sponsorship|no sponsorship|"
    r"citizen(?:ship)? required|permanent resident|work permit)\b",
    re.IGNORECASE,
)
_GRAD = re.compile(r"\b(?:graduat\w+|class of|batch of)\D{0,20}(20\d{2})", re.IGNORECASE)


def _hard_requirements(jd: JobDescription, profile: Profile) -> list[HardRequirement]:
    text = jd.full_text
    out: list[HardRequirement] = []

    # Years of experience — a new grad clears 0-2, should check 3+.
    years = [int(m.group(1)) for m in _YEARS.finditer(text)]
    if years:
        y = min(years)
        verdict = "ok" if y <= 2 else ("check" if y <= 4 else "blocker")
        out.append(
            HardRequirement(
                "years",
                f"asks for {y}+ years of experience (you have internship experience only)",
                verdict,
            )
        )

    # Degree level.
    if _DEGREE.search(text):
        low = text.lower()
        if re.search(r"\b(phd|doctorate)\b", low):
            out.append(HardRequirement("degree", "PhD mentioned — confirm whether required", "check"))
        elif re.search(r"\b(master|m\.?s\.?c?\.?)\b", low) and "bachelor" not in low:
            out.append(HardRequirement("degree", "Master's mentioned without Bachelor's alternative", "check"))
        else:
            deg = profile.section("education")[0].get("degree", "your degree")
            out.append(HardRequirement("degree", f"Bachelor's level — met by {deg}", "ok"))

    # Clearance.
    if _CLEARANCE.search(text):
        out.append(
            HardRequirement("clearance", "security clearance mentioned — likely a blocker as a non-national", "blocker")
        )

    # Work authorisation.
    if _VISA.search(text):
        loc = (jd.location or "").lower()
        if "singapore" in loc or "singapore" in text.lower()[:400]:
            out.append(HardRequirement("visa", "Singapore role — you are a citizen, no sponsorship needed", "ok"))
        else:
            out.append(
                HardRequirement("visa", "work authorisation mentioned for a non-Singapore role — confirm sponsorship", "check")
            )

    # Graduation year window.
    grad_years = {int(m.group(1)) for m in _GRAD.finditer(text)}
    if grad_years:
        mine = int(str(profile.job_search.get("graduation", "2027"))[:4])
        if mine in grad_years:
            out.append(HardRequirement("grad_year", f"targets {sorted(grad_years)} — you graduate {mine}", "ok"))
        else:
            out.append(
                HardRequirement("grad_year", f"targets {sorted(grad_years)} but you graduate {mine}", "blocker")
            )
    return out


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------
def build_vocabulary(profile: Profile) -> tuple[list[str], dict[str, Skill]]:
    """Every term worth looking for, plus a map from term to profile skill."""
    term_to_skill: dict[str, Skill] = {}
    terms: set[str] = set(ALL_TERMS)
    for s in profile.skills:
        for name in s.all_names:
            key = name.lower().strip()
            terms.add(key)
            term_to_skill[key] = s
    # Let lexicon terms resolve to a skill by name or alias too.
    for t in list(terms):
        if t in term_to_skill:
            continue
        hit = profile.skill(t)
        if hit:
            term_to_skill[t] = hit
    return sorted(terms, key=len, reverse=True), term_to_skill


def _bullets_mentioning(profile: Profile, names: list[str], limit: int = 4) -> list[str]:
    """Profile bullet ids whose text actually demonstrates one of these terms.
    Evidence beats a self-assessed level, so this is checked first."""
    hits: list[str] = []
    pats = [_boundary(n) for n in names if n]
    for b in profile.bullets.values():
        if any(p.search(b.text) for p in pats):
            hits.append(b.id)
            if len(hits) >= limit:
                break
    return hits


def match(jd: JobDescription, profile: Profile) -> MatchReport:
    terms, term_to_skill = build_vocabulary(profile)
    corpus = profile.corpus().lower()

    found: dict[str, Match] = {}
    unmatched: list[str] = []

    for line in jd.lines:
        weight = SECTION_WEIGHTS.get(line.section, 0.5)
        consumed: list[tuple[int, int]] = []
        hits_this_line = 0
        low = line.text.lower()
        for term in terms:                      # longest first
            if term not in low:
                continue
            pat = _boundary(term)
            m = pat.search(line.text)
            if not m:
                continue
            span = m.span()
            if any(span[0] < e and s < span[1] for s, e in consumed):
                continue                        # inside a longer term already matched
            consumed.append(span)
            hits_this_line += 1

            skill = term_to_skill.get(term)
            canonical = skill.name if skill else term

            entry = found.get(canonical)
            if entry is None:
                if skill:
                    evidence = list(skill.evidence) or _bullets_mentioning(
                        profile, skill.all_names
                    )
                    strong = skill.level in _STRONG_LEVELS
                    status = COVERED if (evidence or strong) else WEAK
                    if skill.level == "exposure" and not evidence:
                        status = WEAK
                    entry = Match(
                        term=canonical,
                        status=status,
                        skill=skill.name,
                        level=skill.level,
                        evidence=evidence,
                    )
                else:
                    # Not a named skill. Is it demonstrated in a real bullet?
                    evidence = _bullets_mentioning(profile, [term])
                    if evidence:
                        status = COVERED
                    elif _boundary(term).search(corpus):
                        status = WEAK
                    else:
                        status = MISSING
                    entry = Match(term=canonical, status=status, evidence=evidence)
                found[canonical] = entry

            term_weight = weight
            if term in GENERIC_TERMS:
                entry.soft = True
                term_weight = weight * 0.25
            entry.weight = max(entry.weight, term_weight)
            entry.sections.add(line.section)
            if len(entry.jd_snippets) < 3:
                entry.jd_snippets.append(line.text[:160])

        # A substantive requirement line that matched nothing is a blind spot.
        if (
            hits_this_line == 0
            and line.section in ("requirement", "preferred", "responsibility")
            and len(line.text.split()) >= 4
        ):
            unmatched.append(line.text)

    return MatchReport(
        jd=jd,
        matches=_merge_plurals(found),
        hard_requirements=_hard_requirements(jd, profile),
        unmatched=unmatched,
        _bullet_section={b.id: b.section for b in profile.bullets.values()},
        _bullet_tags={b.id: tuple(b.tags) for b in profile.bullets.values()},
        _skill_tags={sk.name: tuple(sk.tags) for sk in profile.skills},
    )


def _merge_plurals(found: dict[str, Match]) -> list[Match]:
    """'smart contract' and 'smart contracts' are one requirement, not two."""
    out: dict[str, Match] = {}
    for term in sorted(found, key=len):            # singular first
        entry = found[term]
        key = term.lower().rstrip("s")
        kept = out.get(key)
        if kept is None:
            out[key] = entry
            continue
        kept.weight = max(kept.weight, entry.weight)
        kept.sections |= entry.sections
        for bid in entry.evidence:
            if bid not in kept.evidence:
                kept.evidence.append(bid)
        if entry.status == COVERED:
            kept.status = COVERED
    return list(out.values())
