"""The answer sheet for application forms.

Most of an online application is the same twelve fields typed again. This
writes them out once per role, with the role-specific answers filled in, so
filling a Workday or Greenhouse form is copy-and-paste rather than recall.
"""
from __future__ import annotations

from .cover_letter import CoverLetter
from .jd import JobDescription
from .profile import Profile
from .tailor import TailoredResume


def build(
    jd: JobDescription,
    profile: Profile,
    tailored: TailoredResume,
    letter: CoverLetter | None = None,
    resume_text: str = "",
) -> str:
    m = profile.meta
    js = profile.job_search
    fa = profile.data.get("form_answers", {}) or {}
    edu = (profile.section("education") or [{}])[0]

    L: list[str] = []
    L.append(f"# Form answers — {jd.company or 'company'} / {jd.title or 'role'}")
    L.append("")
    L.append("Copy-paste sheet for the online application. Nothing here is generated;")
    L.append("these are your real details plus the role-specific answers.")
    L.append("")

    L.append("## Identity")
    L.append("")
    rows = [
        ("Full name", m.get("name", "")),
        ("Email", m.get("email", "")),
        ("Phone", m.get("phone", "")),
        ("Location", m.get("location", "")),
        ("LinkedIn", m.get("linkedin", "")),
        ("GitHub / portfolio", m.get("github", "")),
    ]
    for k, v in rows:
        L.append(f"- **{k}:** {v}")
    L.append("")

    L.append("## Education")
    L.append("")
    for k, v in [
        ("University", edu.get("institution", "")),
        ("Degree", edu.get("degree", "")),
        ("Second major", edu.get("second_major", "")),
        ("Start", edu.get("start", "")),
        ("Expected graduation", edu.get("end", "")),
        ("GPA", edu.get("gpa", "")),
    ]:
        if v:
            L.append(f"- **{k}:** {v}")
    L.append("")

    L.append("## Eligibility and logistics")
    L.append("")
    wa = m.get("work_authorisation", {}) or {}
    loc = (jd.location or "").lower()
    if "singapore" in loc:
        L.append(f"- **Work authorisation:** {wa.get('singapore', '')}")
        L.append("- **Require sponsorship:** No")
    else:
        L.append(f"- **Work authorisation (this role):** {wa.get('other', '')}")
        L.append("- **Require sponsorship:** Yes — confirm the company sponsors before applying")
    L.append(f"- **Earliest start date:** {js.get('earliest_start', '')}")
    L.append(f"- **Notice period:** {fa.get('notice_period', '')}")
    L.append(f"- **Willing to relocate:** {fa.get('willing_to_relocate', '')}")
    L.append(f"- **Salary expectation:** {fa.get('salary_expectation', '')}")
    L.append(f"- **How did you hear about us:** {fa.get('how_did_you_hear', '')}")
    L.append(f"- **Languages:** {', '.join(str(x) for x in (m.get('languages') or []))}")
    L.append("")

    if letter and letter.paragraphs:
        L.append("## \"Why this role / company\" — short form")
        L.append("")
        L.append("Many forms want 100-300 words instead of a letter. Use the opening")
        L.append("paragraph of the cover letter:")
        L.append("")
        L.append("> " + letter.paragraphs[0].replace("\n", "\n> "))
        L.append("")

    report = tailored.report
    if report:
        L.append("## If asked about a skill you do not have")
        L.append("")
        missing = [mm.term for mm in report.by_status("missing")]
        if missing:
            L.append("These appear in the posting but not in your profile. Answer honestly —")
            L.append("say what you have done that is adjacent, not that you have the skill:")
            L.append("")
            for term in missing:
                L.append(f"- {term}")
        else:
            L.append("Nothing in this posting falls outside your profile.")
        L.append("")

    if resume_text:
        L.append("## Resume as plain text")
        L.append("")
        L.append("For forms with a \"paste your resume\" box:")
        L.append("")
        L.append("```")
        L.append(resume_text.rstrip())
        L.append("```")
        L.append("")

    return "\n".join(L)
