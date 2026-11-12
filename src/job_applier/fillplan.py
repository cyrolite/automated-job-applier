"""The fill plan: a machine-readable mapping from form fields to your answers.

Python cannot drive a browser, and a browser agent should not have to guess
what belongs in "Work authorization". So the work is split:

  * this module emits a precise plan — label patterns, values, field kinds,
    file paths, and per-ATS field-name hints
  * the browser agent opens the form, matches each field against the plan,
    fills it, and stops

`stop_before_submit` is always true, and `never_do` lists the actions the agent
must not take. The last click is yours. That is not a limitation to work
around: an auto-submitted application is one you never read, sent under your
name, and most boards' terms prohibit it.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import settings
from .jd import JobDescription
from .profile import Profile

# Actions the agent must never take while filling a form.
NEVER_DO = [
    "click Submit, Apply, Send Application, or any final confirmation",
    "accept terms or consent checkboxes on your behalf",
    "answer demographic, disability or veteran questions (leave them blank)",
    "enter a salary figure in a required numeric field without asking first",
    "solve or bypass a CAPTCHA or bot check",
    "create an account or set a password",
    "upload anything from outside this application folder",
]

# Field names these platforms actually use, as hints for matching.
ATS_HINTS: dict[str, dict[str, list[str]]] = {
    "greenhouse": {
        "first_name": ["job_application[first_name]", "#first_name"],
        "last_name": ["job_application[last_name]", "#last_name"],
        "email": ["job_application[email]", "#email"],
        "phone": ["job_application[phone]", "#phone"],
        "resume": ["#resume", "input[type=file][name*=resume]"],
        "cover_letter": ["#cover_letter", "input[type=file][name*=cover]"],
        "linkedin": ["job_application[urls]", "input[name*=linkedin i]"],
    },
    "lever": {
        "name": ["input[name=name]"],
        "email": ["input[name=email]"],
        "phone": ["input[name=phone]"],
        "org": ["input[name=org]"],
        "resume": ["input[name=resume]"],
        "urls_linkedin": ["input[name='urls[LinkedIn]']"],
        "urls_github": ["input[name='urls[GitHub]']"],
    },
    "ashby": {
        "name": ["input[name=_systemfield_name]"],
        "email": ["input[name=_systemfield_email]"],
        "resume": ["input[type=file]"],
    },
    "workday": {
        "note": [
            "Workday builds field ids per tenant, so match on the visible "
            "label text rather than a selector."
        ],
    },
}


@dataclass
class Field:
    """One answer, plus the labels it should be matched against."""
    key: str
    value: str
    kind: str = "text"          # text|email|tel|url|textarea|select|file|date|boolean
    match: list[str] = field(default_factory=list)
    note: str = ""
    required_guess: bool = False


def _f(key, value, kind="text", match=None, note="", required=False) -> Field:
    return Field(key=key, value=str(value or ""), kind=kind,
                 match=match or [], note=note, required_guess=required)


def detect_ats(url: str) -> str:
    """Which platform a form is on, from its URL."""
    u = (url or "").lower()
    for needle, name in (
        ("greenhouse.io", "greenhouse"),
        ("lever.co", "lever"),
        ("ashbyhq.com", "ashby"),
        ("myworkdayjobs.com", "workday"),
        ("workday.com", "workday"),
        ("smartrecruiters.com", "smartrecruiters"),
        ("taleo.net", "taleo"),
        ("successfactors", "successfactors"),
        ("mycareersfuture.gov.sg", "mycareersfuture"),
        ("linkedin.com", "linkedin"),
    ):
        if needle in u:
            return name
    return "unknown"


def build_plan(
    profile: Profile,
    jd: JobDescription,
    folder: Path | None = None,
    apply_url: str = "",
) -> dict:
    m = profile.meta
    js = profile.job_search
    fa = profile.data.get("form_answers", {}) or {}
    edu = (profile.section("education") or [{}])[0]

    name = str(m.get("name", "")).strip()
    parts = name.split()
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""

    singapore_role = "singapore" in (jd.location or "").lower()
    wa = m.get("work_authorisation", {}) or {}

    fields: list[Field] = [
        _f("first_name", first, "text", ["first name", "given name", "forename"], required=True),
        _f("last_name", last, "text", ["last name", "surname", "family name"], required=True),
        _f("full_name", name, "text", ["full name", "name"], required=True),
        _f("preferred_name", first, "text", ["preferred name", "nickname"]),
        _f("email", m.get("email"), "email", ["email", "e-mail address"], required=True),
        _f("phone", m.get("phone"), "tel", ["phone", "mobile", "contact number", "telephone"], required=True),
        _f("location", m.get("location"), "text", ["city", "location", "current location", "where are you based"]),
        _f("country", "Singapore", "select", ["country", "country of residence"]),
        _f("linkedin", m.get("linkedin"), "url", ["linkedin", "linkedin profile", "linkedin url"]),
        _f("github", m.get("github"), "url", ["github", "portfolio", "personal website", "other url"]),

        _f("university", edu.get("institution"), "text", ["school", "university", "institution", "college"]),
        _f("degree", edu.get("degree"), "text", ["degree", "qualification", "program"]),
        _f("discipline", "Information Security", "text", ["discipline", "major", "field of study", "course"]),
        _f("gpa", edu.get("gpa"), "text", ["gpa", "grade", "cap", "cgpa"]),
        _f("education_start", str(edu.get("start", ""))[:7], "date", ["education start", "start date", "from"]),
        _f("graduation", str(edu.get("end", ""))[:7], "date",
           ["graduation", "expected graduation", "end date", "completion date"], required=True),

        _f("work_authorised", "Yes" if singapore_role else "No", "boolean",
           ["authorised to work", "authorized to work", "legally entitled to work", "right to work"],
           note="Singapore citizen" if singapore_role else "would need sponsorship outside Singapore"),
        _f("needs_sponsorship", "No" if singapore_role else "Yes", "boolean",
           ["require sponsorship", "need sponsorship", "visa sponsorship", "work permit"],
           note=str(wa.get("singapore") if singapore_role else wa.get("other"))),
        _f("earliest_start", js.get("earliest_start"), "date",
           ["earliest start", "available from", "availability", "when can you start", "notice period"],
           note=str(fa.get("notice_period", ""))),
        _f("relocate", fa.get("willing_to_relocate"), "boolean", ["relocate", "willing to relocate"]),
        _f("salary_expectation", fa.get("salary_expectation"), "text",
           ["salary", "expected salary", "compensation expectation"],
           note="A free-text box can take this sentence. A required number needs your decision — ask first."),
        _f("how_heard", fa.get("how_did_you_hear"), "select",
           ["how did you hear", "source", "referral"]),
        _f("languages", ", ".join(str(x) for x in (m.get("languages") or [])), "text",
           ["languages", "language proficiency"]),
        _f("notice_period", fa.get("notice_period"), "text", ["notice period"]),
        _f("visa_status", "Singapore Citizen" if singapore_role else "Requires sponsorship", "select",
           ["visa status", "citizenship", "nationality", "residency status"]),
    ]

    documents: dict[str, str] = {}
    if folder:
        folder = Path(folder)
        for key, candidates in (
            ("resume", ("resume.pdf", "resume.docx")),
            ("cover_letter", ("cover-letter.pdf", "cover-letter.docx")),
        ):
            for fname in candidates:
                path = folder / fname
                if path.exists():
                    documents[key] = str(path)
                    break

    # Many graduate applications ask for a transcript. It lives with the
    # source documents, not in the per-application folder.
    try:
        transcripts = sorted(Path(settings.source_files_dir).glob("Transcript*.pdf"))
        if transcripts:
            documents["transcript"] = str(transcripts[-1])
    except OSError:
        pass

    if documents.get("resume"):
        fields.append(_f("resume_file", documents["resume"], "file",
                         ["resume", "cv", "upload resume", "attach resume"], required=True))
    if documents.get("cover_letter"):
        fields.append(_f("cover_letter_file", documents["cover_letter"], "file",
                         ["cover letter", "covering letter", "motivation letter"]))
    if documents.get("transcript"):
        fields.append(_f("transcript_file", documents["transcript"], "file",
                         ["transcript", "academic transcript", "academic record"]))

    ats = detect_ats(apply_url or jd.url)

    return {
        "version": 1,
        "application": {
            "company": jd.company,
            "title": jd.title,
            "location": jd.location,
            "apply_url": apply_url or jd.url,
            "ats": ats,
        },
        "documents": documents,
        "fields": [asdict(f) for f in fields if f.value],
        "ats_hints": ATS_HINTS.get(ats, {}),
        "stop_before_submit": True,
        "never_do": NEVER_DO,
        "leave_blank": [
            "demographic questions (race, gender, disability, veteran status)",
            "anything you are unsure about — flag it instead of guessing",
        ],
        "instructions": [
            f"Open {apply_url or jd.url}",
            "Match each field in `fields` by its visible label against the `match` list.",
            "Use `ats_hints` for selectors when the label is ambiguous.",
            "Upload the files in `documents`.",
            "Leave anything in `leave_blank` untouched.",
            "Do not perform anything in `never_do`.",
            "Screenshot the completed form, list anything you could not fill, and stop.",
        ],
    }


def write_plan(plan: dict, folder: Path) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "fill-plan.json"
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
