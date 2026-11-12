"""Job description intake and sectioning.

Accepts raw text, a file, or a URL and produces a JobDescription whose lines
are tagged by section, so a keyword found under "Requirements" can outweigh
one found under "Nice to have".
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .lexicon import (
    PREFERRED_HEADERS,
    REQUIREMENT_HEADERS,
    RESPONSIBILITY_HEADERS,
)

_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•●▪·‣⁃]|\d+[.)])\s*")
_WS = re.compile(r"[ \t]+")


def _clean(line: str) -> str:
    line = _BULLET_PREFIX.sub("", line)
    return _WS.sub(" ", line).strip()


def _is_header(line: str) -> bool:
    """A short line that introduces a block, with or without a colon."""
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if s.endswith(":"):
        return True
    words = s.split()
    if len(words) <= 8 and (s.isupper() or s.istitle()):
        return True
    return False


def _classify_header(line: str) -> str | None:
    low = line.lower()
    for h in PREFERRED_HEADERS:          # check preferred first: "preferred qualifications"
        if h in low:
            return "preferred"
    for h in REQUIREMENT_HEADERS:
        if h in low:
            return "requirement"
    for h in RESPONSIBILITY_HEADERS:
        if h in low:
            return "responsibility"
    return None


@dataclass
class JDLine:
    text: str
    section: str = "other"   # requirement | preferred | responsibility | other


@dataclass
class JobDescription:
    raw: str
    title: str = ""
    company: str = ""
    location: str = ""
    url: str = ""
    lines: list[JDLine] = field(default_factory=list)

    # ---------- intake ----------
    @classmethod
    def from_text(
        cls,
        text: str,
        title: str = "",
        company: str = "",
        location: str = "",
        url: str = "",
    ) -> "JobDescription":
        jd = cls(raw=text, title=title, company=company, location=location, url=url)
        jd._section_lines()
        jd._infer_missing_fields()
        return jd

    @classmethod
    def from_file(cls, path: str | Path, **kw) -> "JobDescription":
        p = Path(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        # A .json sidecar lets you record title/company/url alongside the text.
        if p.suffix.lower() == ".json":
            data = json.loads(text)
            return cls.from_text(
                data.get("description", data.get("text", "")),
                title=data.get("title", ""),
                company=data.get("company", ""),
                location=data.get("location", ""),
                url=data.get("url", ""),
            )
        return cls.from_text(text, **kw)

    # ---------- internals ----------
    def _section_lines(self) -> None:
        current = "other"
        for raw_line in self.raw.splitlines():
            if not raw_line.strip():
                continue
            if _is_header(raw_line):
                found = _classify_header(raw_line)
                if found:
                    current = found
                    continue
                # An unrecognised header ends the previous block.
                current = "other"
                # Keep it: headers often name the role or a skill group.
                self.lines.append(JDLine(text=_clean(raw_line), section=current))
                continue
            cleaned = _clean(raw_line)
            if cleaned:
                self.lines.append(JDLine(text=cleaned, section=current))

    def _infer_missing_fields(self) -> None:
        """Best-effort guesses from the first few lines, only to save typing.
        Anything passed in explicitly always wins."""
        head = [l.text for l in self.lines[:6]]
        if not self.title and head:
            self.title = head[0][:120]
        if not self.company:
            for line in head:
                m = re.search(r"\bat\s+([A-Z][\w&.,'\- ]{2,40})", line)
                if m:
                    self.company = m.group(1).strip(" .,")
                    break

    # ---------- accessors ----------
    def text_of(self, section: str) -> str:
        return "\n".join(l.text for l in self.lines if l.section == section)

    @property
    def full_text(self) -> str:
        return "\n".join(l.text for l in self.lines)

    def slug(self) -> str:
        base = f"{self.company}-{self.title}".lower()
        base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
        return (base or "application")[:70]

    def summary_for_prompt(self, limit: int = 7000) -> str:
        parts = [
            f"ROLE: {self.title or '(not given)'}",
            f"COMPANY: {self.company or '(not given)'}",
            f"LOCATION: {self.location or '(not given)'}",
            "",
        ]
        for label, name in (
            ("REQUIREMENTS", "requirement"),
            ("RESPONSIBILITIES", "responsibility"),
            ("PREFERRED / NICE TO HAVE", "preferred"),
            ("OTHER CONTEXT", "other"),
        ):
            body = self.text_of(name)
            if body.strip():
                parts.append(f"--- {label} ---")
                parts.append(body)
                parts.append("")
        out = "\n".join(parts)
        return out[:limit]
