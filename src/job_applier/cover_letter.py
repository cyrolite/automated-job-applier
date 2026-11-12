"""Cover letter generation, grounded in the same way as the resume.

Free text is checked more loosely than resume bullets: the company name and the
role's own vocabulary are legitimately new. Invented numbers and technologies
are still blocked.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import ats, prompts
from .jd import JobDescription
from .llm import BaseClient, get_client
from .profile import Profile
from .verify import Finding, VerificationResult, verify_free_text


@dataclass
class CoverLetter:
    greeting: str = "Dear Hiring Manager,"
    paragraphs: list[str] = field(default_factory=list)
    closing: str = "Sincerely,"
    signature: str = ""
    notes: str = ""
    verification: VerificationResult = field(default_factory=VerificationResult)

    @property
    def word_count(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)

    def to_text(self) -> str:
        parts = [self.greeting, ""]
        for p in self.paragraphs:
            parts += [p, ""]
        parts += [self.closing, self.signature]
        return "\n".join(parts).strip() + "\n"


def write(
    jd: JobDescription,
    profile: Profile | None = None,
    client: BaseClient | None = None,
    report: ats.MatchReport | None = None,
) -> CoverLetter:
    profile = profile or Profile.load()
    report = report or ats.match(jd, profile)
    client = client or get_client()

    system, user_tpl = prompts.load("cover_letter")
    js = profile.job_search
    gaps_list = (
        ", ".join(m.term for m in report.by_status(ats.MISSING) if m.required) or "(none)"
    )
    user = prompts.fill(
        user_tpl,
        jd=jd.summary_for_prompt(),
        gaps=report.to_markdown(),
        profile=profile.summary_for_prompt(),
        start_date=js.get("earliest_start", ""),
        graduation=js.get("graduation", ""),
        gaps_list=gaps_list,
    )

    data = client.complete_json(system, user)

    letter = CoverLetter(
        greeting=str(data.get("greeting") or "Dear Hiring Manager,").strip(),
        closing=str(data.get("closing") or "Sincerely,").strip(),
        signature=str(profile.meta.get("name", "")),
        notes=str(data.get("notes") or ""),
    )

    corpus = profile.corpus()
    allowed = [jd.company, jd.title, jd.location] + [m.term for m in report.matches]

    raw_paras = data.get("paragraphs") or []
    if isinstance(raw_paras, str):
        raw_paras = [raw_paras]

    for i, para in enumerate(raw_paras, start=1):
        text = str(para).strip()
        if not text:
            continue
        sub = verify_free_text(text, corpus, allowed, where=f"paragraph {i}")
        letter.verification.extend(sub)
        if sub.errors:
            letter.verification.findings.append(
                Finding("warning", f"paragraph {i}", "kept, but the flagged claims above need your review before sending")
            )
        letter.paragraphs.append(text)

    if not letter.paragraphs:
        letter.verification.findings.append(
            Finding("error", "letter", "the model returned no usable paragraphs")
        )
    return letter
