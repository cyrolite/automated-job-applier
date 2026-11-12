"""Grounding verification.

A fabricated resume bullet is a career risk, so nothing reaches a document
without passing these checks. Every generated line is compared against the
profile bullet it claims to come from.

What gets caught:
  * inflated or invented numbers        ("10,000 packets" -> "100,000 packets")
  * technologies not in the source      (adding Kubernetes to a role that had none)
  * misattribution                      (a real skill moved to the wrong employer)
  * invented acronyms, tools, companies

Findings are either `error` (blocked) or `warning` (shown, you decide).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .lexicon import ALL_TERMS

# ----------------------------------------------------------------------
_NUM = re.compile(
    r"(?<![\w.])~?\s*(\d[\d,]*(?:\.\d+)?)\s*(%|k\b|m\b|bn\b|b\b|\+)?", re.IGNORECASE
)
_ACRONYM = re.compile(r"\b([A-Z][A-Z0-9&/]{1,9})\b")
# CamelCase / mixed-case product names: LangGraph, ChromaDB, XGBoost, PostgreSQL.
_MIXEDCASE = re.compile(r"\b([A-Z][a-z0-9]*[A-Z][A-Za-z0-9+#.]*)\b")

# Acronyms that are ordinary resume vocabulary, not claims about tooling.
_BENIGN_ACRONYMS = {
    "A", "I", "AI", "IT", "OK", "US", "UK", "EU", "QA", "ID", "KPI", "ROI",
    "CV", "PDF", "FAQ", "AM", "PM", "CEO", "CTO", "HR", "R&D", "AND", "OR",
    "THE", "TO", "IN", "OF", "FOR", "ON", "AT", "BY", "AS", "AN", "AI/ML",
}


@dataclass
class Finding:
    level: str      # error | warning
    where: str      # bullet id, or section name
    detail: str

    def __str__(self) -> str:
        return f"[{self.level.upper()}] {self.where}: {self.detail}"


@dataclass
class VerificationResult:
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def extend(self, other: "VerificationResult") -> None:
        self.findings.extend(other.findings)

    def to_markdown(self) -> str:
        if not self.findings:
            return "## Grounding check\n\nPassed. Every claim traces back to the master profile.\n"
        L = ["## Grounding check", ""]
        if self.errors:
            L.append(f"**{len(self.errors)} blocked claim(s)** — rewritten to the source wording:")
            L += [f"- {f.where}: {f.detail}" for f in self.errors]
            L.append("")
        if self.warnings:
            L.append(f"**{len(self.warnings)} thing(s) to eyeball:**")
            L += [f"- {f.where}: {f.detail}" for f in self.warnings]
            L.append("")
        return "\n".join(L)


# ----------------------------------------------------------------------
def _normalise_numbers(text: str) -> set[str]:
    """Numbers as comparable canonical strings. 250,000 / 250000 / 250k all match."""
    out: set[str] = set()
    for m in _NUM.finditer(text):
        digits = m.group(1).replace(",", "")
        suffix = (m.group(2) or "").lower().strip()
        try:
            val = float(digits)
        except ValueError:
            continue
        if suffix == "k":
            val *= 1_000
        elif suffix == "m":
            val *= 1_000_000
        elif suffix in ("b", "bn"):
            val *= 1_000_000_000
        if suffix == "%":
            out.add(f"{val:g}%")
        else:
            out.add(f"{val:g}")
    return out


def _tech_terms(text: str) -> set[str]:
    low = text.lower()
    return {t for t in ALL_TERMS if _term_present(t, low)}


def _term_present(term: str, low_text: str) -> bool:
    if term not in low_text:
        return False
    esc = re.escape(term).replace(r"\ ", r"[\s\-]+")
    return re.search(rf"(?<![A-Za-z0-9]){esc}(?![A-Za-z0-9])", low_text) is not None


def _proper_tokens(text: str) -> set[str]:
    """Acronyms and mixed-case product names — the shapes fabrication takes."""
    out: set[str] = set()
    for m in _ACRONYM.finditer(text):
        tok = m.group(1)
        if tok.upper() not in _BENIGN_ACRONYMS and len(tok) >= 2:
            out.add(tok)
    for m in _MIXEDCASE.finditer(text):
        out.add(m.group(1))
    return out


# ----------------------------------------------------------------------
def verify_bullet(
    rewritten: str,
    source_text: str,
    source_tags: list[str] | None = None,
    corpus: str = "",
) -> VerificationResult:
    """Check one rewritten bullet against the profile bullet it came from."""
    res = VerificationResult()
    where = "bullet"
    src_low = source_text.lower()
    tag_blob = " ".join(source_tags or []).lower().replace("-", " ")
    src_plus_tags = f"{src_low} {tag_blob}"
    corpus_low = corpus.lower()

    # 1. Numbers must come from the source bullet.
    src_nums = _normalise_numbers(source_text)
    for num in _normalise_numbers(rewritten):
        if num in src_nums:
            continue
        # A year already in the profile is fine (dates, graduation).
        if re.fullmatch(r"20\d\d", num) and num in corpus_low:
            continue
        res.findings.append(
            Finding(
                "error",
                where,
                f"number {num!r} is not in the source bullet "
                f"(source has: {', '.join(sorted(src_nums)) or 'none'})",
            )
        )

    # 2. Technologies must belong to this bullet, not merely to the profile.
    reported: set[str] = set()
    src_terms = _tech_terms(src_plus_tags)
    for term in _tech_terms(rewritten):
        reported.add(term.lower())
        if term in src_terms:
            continue
        if _term_present(term, corpus_low):
            res.findings.append(
                Finding(
                    "warning",
                    where,
                    f"{term!r} is real for you but not part of this bullet — "
                    "check it is not attributed to the wrong role",
                )
            )
        else:
            res.findings.append(
                Finding("error", where, f"{term!r} does not appear anywhere in your profile")
            )

    # 3. Acronyms and product names must be traceable.
    src_tokens = {t.lower() for t in _proper_tokens(source_text)}
    for tok in _proper_tokens(rewritten):
        low = tok.lower()
        if low in reported:          # already judged as a technology above
            continue
        if low in src_tokens or _term_present(low, src_plus_tags):
            continue
        if _term_present(low, corpus_low) or low in corpus_low:
            res.findings.append(
                Finding("warning", where, f"{tok!r} is in your profile but not in this bullet")
            )
        else:
            res.findings.append(
                Finding("error", where, f"{tok!r} is not traceable to your profile")
            )

    # 4. Keep bullets readable on one or two lines.
    words = len(rewritten.split())
    if words > 45:
        res.findings.append(Finding("warning", where, f"long bullet ({words} words) — consider trimming"))
    return res


def verify_free_text(
    text: str,
    corpus: str,
    allowed_terms: list[str] | None = None,
    where: str = "text",
) -> VerificationResult:
    """Looser check for a summary or cover letter, where the company name and
    the role's own vocabulary are legitimately new."""
    res = VerificationResult()
    allowed_blob = " ".join(allowed_terms or []).lower()
    corpus_low = corpus.lower()

    def known(token: str) -> bool:
        low = token.lower()
        return (
            _term_present(low, corpus_low)
            or low in corpus_low
            or _term_present(low, allowed_blob)
            or low in allowed_blob
        )

    for num in _normalise_numbers(text):
        if num in _normalise_numbers(corpus) or re.fullmatch(r"20\d\d", num):
            continue
        res.findings.append(
            Finding("error", where, f"number {num!r} does not appear in your profile")
        )

    for term in _tech_terms(text):
        if not known(term):
            res.findings.append(
                Finding("error", where, f"{term!r} is claimed but is not in your profile")
            )

    for tok in _proper_tokens(text):
        if not known(tok):
            res.findings.append(
                Finding("warning", where, f"{tok!r} is not in your profile — confirm it is the company or role name")
            )
    return res
