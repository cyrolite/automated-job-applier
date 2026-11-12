"""Grounded resume tailoring.

The model chooses which real bullets to surface and how to word them. Every
line it returns is checked against its source bullet; anything that fails is
replaced with the source wording rather than shipped. The document is always
truthful, in the worst case merely less polished.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ats, prompts
from .config import settings
from .jd import JobDescription
from .llm import BaseClient, get_client
from .profile import Profile
from .verify import Finding, VerificationResult, verify_bullet, verify_free_text


@dataclass
class TailoredBullet:
    source_id: str
    text: str
    repaired: bool = False     # True if generation failed verification and we fell back


@dataclass
class TailoredSection:
    parent_id: str
    label: str
    org: str = ""
    title: str = ""
    dates: str = ""
    link: str | None = None
    bullets: list[TailoredBullet] = field(default_factory=list)


@dataclass
class TailoredResume:
    headline: str = ""
    summary: str | None = None
    skills_lines: dict[str, str] = field(default_factory=dict)
    experience: list[TailoredSection] = field(default_factory=list)
    projects: list[TailoredSection] = field(default_factory=list)
    activities: list[TailoredSection] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)
    notes: str = ""
    verification: VerificationResult = field(default_factory=VerificationResult)
    report: ats.MatchReport | None = None
    # Switches the page fitter turns off to reclaim space, least valuable first.
    show_courses: bool = True
    show_languages: bool = True
    max_education_highlights: int | None = None

    @property
    def all_sections(self) -> list[TailoredSection]:
        return self.experience + self.projects + self.activities

    @property
    def bullet_count(self) -> int:
        return sum(len(s.bullets) for s in self.all_sections)

    @property
    def repaired_count(self) -> int:
        return sum(1 for s in self.all_sections for b in s.bullets if b.repaired)


def _fmt_dates(item: dict) -> str:
    """'2026-08' + '2026-11' -> 'Aug 2026 - Nov 2026'."""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    def one(v: object) -> str:
        s = str(v or "").strip()
        if not s or s.lower() == "present":
            return "Present"
        parts = s.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            idx = int(parts[1]) - 1
            if 0 <= idx < 12:
                return f"{months[idx]} {parts[0]}"
        return s

    start, end = one(item.get("start")), one(item.get("end"))
    return f"{start} - {end}" if start != end else start


def _parent_lookup(profile: Profile) -> dict[str, tuple[str, dict]]:
    out: dict[str, tuple[str, dict]] = {}
    for section in ("experience", "projects", "activities"):
        for item in profile.section(section):
            out[str(item.get("id"))] = (section, item)
    return out


def _build_section(section_name: str, item: dict, label: str) -> TailoredSection:
    if section_name == "experience":
        return TailoredSection(
            parent_id=str(item.get("id")),
            label=label,
            org=str(item.get("org", "")),
            title=str(item.get("title", "")),
            dates=_fmt_dates(item),
        )
    if section_name == "projects":
        return TailoredSection(
            parent_id=str(item.get("id")),
            label=label,
            org=str(item.get("name", "")),
            title="",
            dates=_fmt_dates(item),
            link=item.get("link"),
        )
    return TailoredSection(
        parent_id=str(item.get("id")),
        label=label,
        org=str(item.get("name", "")),
        title=str(item.get("role", "")),
        dates=_fmt_dates(item),
    )


def tailor(
    jd: JobDescription,
    profile: Profile | None = None,
    client: BaseClient | None = None,
    report: ats.MatchReport | None = None,
) -> TailoredResume:
    profile = profile or Profile.load()
    report = report or ats.match(jd, profile)
    client = client or get_client()

    system, user_tpl = prompts.load("tailor_resume")
    surface = ", ".join(m.term for m in report.surface_these) or "(none flagged)"
    gaps_list = ", ".join(m.term for m in report.by_status(ats.MISSING)) or "(none)"

    user = prompts.fill(
        user_tpl,
        jd=jd.summary_for_prompt(),
        gaps=report.to_markdown(),
        profile=profile.summary_for_prompt(),
        pages=settings.max_resume_pages,
        bullets_per_role=settings.bullets_per_role,
        surface=surface,
        gaps_list=gaps_list,
    )

    data = client.complete_json(system, user)
    return _assemble(data, profile, report, jd)


def _assemble(
    data: dict,
    profile: Profile,
    report: ats.MatchReport,
    jd: JobDescription,
) -> TailoredResume:
    corpus = profile.corpus()
    lookup = _parent_lookup(profile)
    result = TailoredResume(report=report)
    vr = result.verification

    # --- free text ---
    result.headline = str(data.get("headline") or "").strip()
    summary = data.get("summary")
    result.summary = str(summary).strip() if summary else None
    allowed = [jd.company, jd.title] + [m.term for m in report.matches]

    for label, value in (("headline", result.headline), ("summary", result.summary)):
        if not value:
            continue
        sub = verify_free_text(value, corpus, allowed, where=label)
        if sub.errors:
            # Unsupported claim in free text: drop it rather than ship it.
            vr.extend(sub)
            if label == "headline":
                result.headline = ""
            else:
                result.summary = None
        else:
            vr.extend(sub)

    # --- skills ---
    raw_skills = data.get("skills_lines") or {}
    if isinstance(raw_skills, dict):
        for group, line in raw_skills.items():
            kept = []
            for token in str(line).split(","):
                name = token.strip()
                if not name:
                    continue
                if profile.skill(name):
                    kept.append(profile.skill(name).name)  # canonical spelling
                else:
                    vr.findings.append(
                        Finding("error", f"skills/{group}", f"{name!r} is not in your skill inventory — dropped")
                    )
            if kept:
                result.skills_lines[str(group)] = ", ".join(dict.fromkeys(kept))

    # --- bullet sections ---
    for key, target in (
        ("experience", result.experience),
        ("projects", result.projects),
        ("activities", result.activities),
    ):
        for raw in data.get(key) or []:
            parent_id = str(raw.get("parent_id") or "")
            if parent_id not in lookup:
                vr.findings.append(
                    Finding("error", key, f"unknown parent_id {parent_id!r} — section dropped")
                )
                continue
            section_name, item = lookup[parent_id]
            label = profile.bullets_for(parent_id)[0].parent_label if profile.bullets_for(parent_id) else parent_id
            section = _build_section(section_name, item, label)

            for rb in raw.get("bullets") or []:
                sid = str(rb.get("source_id") or "")
                text = str(rb.get("text") or "").strip()
                src = profile.bullet(sid)
                if src is None:
                    vr.findings.append(
                        Finding("error", key, f"bullet cites unknown source_id {sid!r} — dropped")
                    )
                    continue
                if src.parent_id != parent_id:
                    vr.findings.append(
                        Finding(
                            "error",
                            sid,
                            f"bullet placed under {parent_id!r} but belongs to {src.parent_id!r} — "
                            "moved back to its real role",
                        )
                    )
                if not text:
                    section.bullets.append(TailoredBullet(sid, src.text, repaired=True))
                    continue

                sub = verify_bullet(text, src.text, src.tags, corpus)
                for f in sub.findings:
                    f.where = sid
                if sub.errors:
                    vr.extend(sub)
                    vr.findings.append(
                        Finding("warning", sid, "rewrite failed verification — used your original wording")
                    )
                    section.bullets.append(TailoredBullet(sid, src.text, repaired=True))
                else:
                    vr.extend(sub)
                    section.bullets.append(TailoredBullet(sid, text))

            if section.bullets:
                target.append(section)

    omitted = data.get("omitted") or []
    result.omitted = [str(o) for o in omitted] if isinstance(omitted, list) else [str(omitted)]
    result.notes = str(data.get("notes") or "")
    return result


# ----------------------------------------------------------------------
# No-LLM mode
# ----------------------------------------------------------------------
_SKILL_GROUPS: list[tuple[str, set[str]]] = [
    ("Security", {"security", "security-tools"}),
    ("Programming", {"programming"}),
    ("AI / Machine Learning", {"ml"}),
    ("Data & Infrastructure", {"data", "engineering", "cloud", "reliability"}),
    ("Mathematics", {"mathematics"}),
]


def tailor_deterministic(
    jd: JobDescription,
    profile: Profile | None = None,
    report: ats.MatchReport | None = None,
) -> TailoredResume:
    """Build a tailored resume with no model involved.

    Bullets keep their original wording and are re-ordered by how well they
    answer this job description. Less polished than the generated version, but
    it needs no API key and is incapable of inventing anything.
    """
    profile = profile or Profile.load()
    report = report or ats.match(jd, profile)
    result = TailoredResume(report=report)
    lookup = _parent_lookup(profile)

    rank = {bid: i for i, bid in enumerate(report.evidence_bullets)}
    big = len(rank) + 1000

    def bullet_rank(bid: str) -> int:
        return rank.get(bid, big)

    # Role ordering: most relevant first within experience, newest kept natural.
    for section_name, target in (
        ("experience", result.experience),
        ("projects", result.projects),
        ("activities", result.activities),
    ):
        items = profile.section(section_name)
        scored: list[tuple[int, dict]] = []
        for item in items:
            pid = str(item.get("id"))
            bullets = profile.bullets_for(pid)
            best = min((bullet_rank(b.id) for b in bullets), default=big)
            scored.append((best, item))

        # Experience stays chronological; projects and activities sort by relevance.
        ordered = items if section_name == "experience" else [i for _, i in sorted(scored, key=lambda t: t[0])]

        for item in ordered:
            pid = str(item.get("id"))
            bullets = sorted(profile.bullets_for(pid), key=lambda b: bullet_rank(b.id))
            if not bullets:
                continue
            keep_n = settings.bullets_per_role
            relevant = [b for b in bullets if bullet_rank(b.id) < big]
            chosen = (relevant or bullets)[:keep_n]
            # Drop a project or activity with no relevance to this role at all.
            if section_name != "experience" and not relevant:
                result.omitted.append(f"{pid}: no overlap with this job description")
                continue
            sec_name, raw_item = lookup[pid]
            label = bullets[0].parent_label
            section = _build_section(sec_name, raw_item, label)
            section.bullets = [TailoredBullet(b.id, b.text) for b in chosen]
            target.append(section)

    # Skills: JD-relevant first, then the rest, grouped.
    relevant_names = {m.skill for m in report.matches if m.skill and m.status != ats.MISSING}
    for group, tags in _SKILL_GROUPS:
        members = [s for s in profile.skills if tags & set(s.tags)]
        if not members:
            continue
        members.sort(key=lambda s: (s.name not in relevant_names, s.name))
        result.skills_lines[group] = ", ".join(s.name for s in members[:9])

    title = jd.title or "Security Engineer"
    result.headline = f"Final-year Information Security undergraduate — targeting {title}".strip()
    result.notes = (
        "Generated without a model: bullets use your original wording, re-ordered "
        "for this role. Set up a provider in .env for tighter, role-specific phrasing."
    )
    return result
