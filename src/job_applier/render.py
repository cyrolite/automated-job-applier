"""Document rendering.

ATS-safe by construction: one column, no tables, no text boxes, no images, no
header/footer content, standard section names, real bullet characters with a
hanging indent, and contact details in the body where every parser looks.

Outputs
  .docx  the file to upload
  .txt   plain text, for pasting into web application forms
  .md    quick read / diff
  .pdf   converted from the .docx when Word or LibreOffice is available
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT  # noqa: F401  (kept for future use)
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.shared import Inches, Pt, RGBColor

from .cover_letter import CoverLetter
from .jd import JobDescription
from .profile import Profile
from .tailor import TailoredResume, _fmt_dates

BODY_FONT = "Calibri"
RIGHT_TAB = Inches(7.3)
INK = RGBColor(0x00, 0x00, 0x00)


# ----------------------------------------------------------------------
# docx helpers
# ----------------------------------------------------------------------
def _new_document(margin: float = 0.6) -> Document:
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(margin)
        section.bottom_margin = Inches(margin)
        section.left_margin = Inches(margin)
        section.right_margin = Inches(margin)
    style = doc.styles["Normal"]
    style.font.name = BODY_FONT
    style.font.size = Pt(10)
    style.font.color.rgb = INK
    pf = style.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1.0
    return doc


def _para(doc: Document, text: str = "", *, size: int = 10, bold: bool = False,
          italic: bool = False, align=None, space_after: int = 0,
          space_before: int = 0) -> object:
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.space_before = Pt(space_before)
    if text:
        run = p.add_run(text)
        run.bold = bold
        run.italic = italic
        run.font.size = Pt(size)
        run.font.name = BODY_FONT
    return p


def _section_heading(doc: Document, title: str) -> None:
    p = _para(doc, title.upper(), size=10.5, bold=True, space_before=8, space_after=2)
    # A bottom rule, drawn as a paragraph border — no table involved.
    pPr = p._p.get_or_add_pPr()
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), "6")
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "808080")
    borders.append(bottom)
    pPr.append(borders)


def _row(doc: Document, left: str, right: str = "", *, bold_left: bool = True,
         italic_left: bool = False, size: int = 10, space_before: int = 3) -> None:
    """A line with text on the left and a date on the right, via a tab stop.
    Parsers read this as one plain paragraph, which is the point."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(0)
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.tab_stops.add_tab_stop(RIGHT_TAB, WD_TAB_ALIGNMENT.RIGHT)
    run = p.add_run(left)
    run.bold = bold_left
    run.italic = italic_left
    run.font.size = Pt(size)
    run.font.name = BODY_FONT
    if right:
        tail = p.add_run("\t" + right)
        tail.font.size = Pt(size)
        tail.font.name = BODY_FONT
        tail.italic = True


def _bullet(doc: Document, text: str, size: int = 10) -> None:
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.left_indent = Inches(0.18)
    pf.first_line_indent = Inches(-0.18)
    pf.space_after = Pt(1)
    pf.space_before = Pt(0)
    run = p.add_run("•  " + text)
    run.font.size = Pt(size)
    run.font.name = BODY_FONT


# ----------------------------------------------------------------------
# Resume
# ----------------------------------------------------------------------
def _contact_line(profile: Profile) -> str:
    m = profile.meta
    bits = [m.get("phone"), m.get("email"), m.get("linkedin"), m.get("github")]
    return "  |  ".join(str(b) for b in bits if b)


def render_resume_docx(tailored: TailoredResume, profile: Profile, path: Path) -> Path:
    doc = _new_document()
    m = profile.meta

    _para(doc, str(m.get("name", "")).upper(), size=16, bold=True,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=1)
    _para(doc, _contact_line(profile), size=8.5,
          align=WD_ALIGN_PARAGRAPH.CENTER, space_after=1)
    if tailored.headline:
        _para(doc, tailored.headline, size=9.5, italic=True,
              align=WD_ALIGN_PARAGRAPH.CENTER, space_after=2)

    if tailored.summary:
        _section_heading(doc, "Summary")
        _para(doc, tailored.summary, size=10, space_after=1)

    # --- Education ---
    _section_heading(doc, "Education")
    for e in profile.section("education"):
        _row(doc, str(e.get("institution", "")), _fmt_dates(e), space_before=2)
        degree = str(e.get("degree", ""))
        if e.get("second_major"):
            degree += f"  |  Second Major in {e['second_major']}"
        _para(doc, degree, size=10, italic=True, space_after=1)
        facts = []
        if e.get("gpa"):
            facts.append(f"GPA: {e['gpa']}")
        if e.get("standing"):
            facts.append(str(e["standing"]))
        if facts:
            _bullet(doc, "  |  ".join(facts))
        highlights = e.get("highlights") or []
        if tailored.max_education_highlights is not None:
            highlights = highlights[: tailored.max_education_highlights]
        for h in highlights:
            _bullet(doc, str(h.get("text", "")))

    # --- Skills ---
    if tailored.skills_lines:
        _section_heading(doc, "Skills")
        for group, line in tailored.skills_lines.items():
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(1)
            g = p.add_run(f"{group}: ")
            g.bold = True
            g.font.size = Pt(10)
            g.font.name = BODY_FONT
            v = p.add_run(line)
            v.font.size = Pt(10)
            v.font.name = BODY_FONT

    # --- Experience / Projects / Activities ---
    for heading, sections in (
        ("Experience", tailored.experience),
        ("Projects", tailored.projects),
        ("Leadership & Activities", tailored.activities),
    ):
        if not sections:
            continue
        _section_heading(doc, heading)
        for s in sections:
            left = f"{s.org}, {s.title}" if s.title else s.org
            _row(doc, left, s.dates)
            if s.link:
                _para(doc, str(s.link), size=9, italic=True, space_after=0)
            for b in s.bullets:
                _bullet(doc, b.text)

    # --- Courses / languages ---
    courses = profile.section("certifications_courses") if tailored.show_courses else []
    if courses:
        _section_heading(doc, "Additional Courses")
        _para(doc, "  |  ".join(str(c) for c in courses), size=9.5)

    langs = (profile.meta.get("languages") or []) if tailored.show_languages else []
    if langs:
        _section_heading(doc, "Additional Information")
        _para(doc, "Languages: " + ", ".join(str(l) for l in langs), size=9.5)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


def render_resume_text(tailored: TailoredResume, profile: Profile) -> str:
    """Plain text for pasting into application forms."""
    m = profile.meta
    L: list[str] = [str(m.get("name", "")).upper(), _contact_line(profile).replace("  |  ", " | ")]
    if tailored.headline:
        L.append(tailored.headline)
    if tailored.summary:
        L += ["", "SUMMARY", tailored.summary]

    L += ["", "EDUCATION"]
    for e in profile.section("education"):
        L.append(f"{e.get('institution','')} ({_fmt_dates(e)})")
        deg = str(e.get("degree", ""))
        if e.get("second_major"):
            deg += f" | Second Major in {e['second_major']}"
        L.append(deg)
        if e.get("gpa"):
            L.append(f"GPA: {e['gpa']}")
        for h in e.get("highlights") or []:
            L.append(f"- {h.get('text','')}")

    if tailored.skills_lines:
        L += ["", "SKILLS"]
        for g, line in tailored.skills_lines.items():
            L.append(f"{g}: {line}")

    for heading, sections in (
        ("EXPERIENCE", tailored.experience),
        ("PROJECTS", tailored.projects),
        ("LEADERSHIP & ACTIVITIES", tailored.activities),
    ):
        if not sections:
            continue
        L += ["", heading]
        for s in sections:
            left = f"{s.org}, {s.title}" if s.title else s.org
            L.append(f"{left} ({s.dates})")
            if s.link:
                L.append(str(s.link))
            for b in s.bullets:
                L.append(f"- {b.text}")

    courses = profile.section("certifications_courses")
    if courses:
        L += ["", "ADDITIONAL COURSES"] + [f"- {c}" for c in courses]
    langs = profile.meta.get("languages") or []
    if langs:
        L += ["", "LANGUAGES: " + ", ".join(str(x) for x in langs)]
    return "\n".join(L) + "\n"


def render_resume_markdown(tailored: TailoredResume, profile: Profile) -> str:
    m = profile.meta
    L = [f"# {m.get('name','')}", "", _contact_line(profile), ""]
    if tailored.headline:
        L += [f"*{tailored.headline}*", ""]
    if tailored.summary:
        L += ["## Summary", "", tailored.summary, ""]
    L += ["## Education", ""]
    for e in profile.section("education"):
        L.append(f"**{e.get('institution','')}** — {_fmt_dates(e)}  ")
        L.append(f"{e.get('degree','')}" + (f" | Second Major in {e['second_major']}" if e.get("second_major") else ""))
        if e.get("gpa"):
            L.append(f"- GPA: {e['gpa']}")
        for h in e.get("highlights") or []:
            L.append(f"- {h.get('text','')}")
        L.append("")
    if tailored.skills_lines:
        L += ["## Skills", ""]
        for g, line in tailored.skills_lines.items():
            L.append(f"- **{g}:** {line}")
        L.append("")
    for heading, sections in (
        ("Experience", tailored.experience),
        ("Projects", tailored.projects),
        ("Leadership & Activities", tailored.activities),
    ):
        if not sections:
            continue
        L += [f"## {heading}", ""]
        for s in sections:
            left = f"{s.org}, {s.title}" if s.title else s.org
            L.append(f"**{left}** — {s.dates}  ")
            for b in s.bullets:
                flag = "  _(original wording)_" if b.repaired else ""
                L.append(f"- {b.text}{flag}")
            L.append("")
    return "\n".join(L)


# ----------------------------------------------------------------------
# Cover letter
# ----------------------------------------------------------------------
def render_cover_letter_docx(
    letter: CoverLetter, profile: Profile, jd: JobDescription, path: Path
) -> Path:
    doc = _new_document(margin=1.0)
    m = profile.meta

    _para(doc, str(m.get("name", "")), size=13, bold=True, space_after=1)
    _para(doc, _contact_line(profile), size=9, space_after=10)

    if jd.company:
        _para(doc, jd.company, size=10, bold=True, space_after=0)
    if jd.title:
        _para(doc, f"Re: {jd.title}", size=10, space_after=10)

    _para(doc, letter.greeting, size=10.5, space_after=8)
    for para in letter.paragraphs:
        p = _para(doc, para, size=10.5, space_after=8)
        p.paragraph_format.line_spacing = 1.15
    _para(doc, letter.closing, size=10.5, space_before=4, space_after=2)
    _para(doc, letter.signature, size=10.5)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    return path


# ----------------------------------------------------------------------
# PDF conversion
# ----------------------------------------------------------------------
def to_pdf(docx_path: Path) -> Path | None:
    """Convert a .docx to .pdf using whatever is on the machine.

    Windows with Word installed -> docx2pdf (best fidelity).
    Otherwise LibreOffice, if present. Returns None if neither is available;
    the .docx is still perfectly submittable.
    """
    docx_path = Path(docx_path)
    out_pdf = docx_path.with_suffix(".pdf")

    if sys.platform.startswith("win"):
        try:
            from docx2pdf import convert  # type: ignore

            convert(str(docx_path), str(out_pdf))
            if out_pdf.exists():
                return out_pdf
        except Exception:
            pass

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            subprocess.run(
                [soffice, "--headless", "--convert-to", "pdf",
                 "--outdir", str(docx_path.parent), str(docx_path)],
                check=True, capture_output=True, timeout=180,
            )
            if out_pdf.exists():
                _tidy(docx_path.parent)
                return out_pdf
        except Exception:
            pass
    return None


def _tidy(folder: Path) -> None:
    """LibreOffice leaves lock and temp files behind. Remove them so the
    application folder holds only the documents."""
    for pattern in (".~lock.*#", "*.tmp"):
        for junk in folder.glob(pattern):
            try:
                junk.unlink()
            except OSError:
                pass
