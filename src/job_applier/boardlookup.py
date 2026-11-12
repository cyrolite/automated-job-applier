"""Finding which job board a company runs on.

`sources.yaml` is only as good as the company tokens in it, and finding those
by hand means opening a careers page, following a redirect and reading a slug
out of the URL. This guesses the slug from the company name and asks each
public board API whether it exists.

One request per candidate, through the shared polite fetcher, so a lookup costs
a handful of rate-limited calls and nothing is hammered.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import settings
from .net import Blocked, NotFound, fetcher

PROBES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json&limit=1",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}

# Legal and descriptive suffixes that never appear in a board slug.
_NOISE = re.compile(
    r"(?i)\b(pte|pty|ltd|limited|llc|inc|incorporated|corp|corporation|co|company|"
    r"private|pvt|plc|gmbh|bv|nv|ag|sa|srl|holdings|group|technologies|technology|"
    r"tech|international|asia|pacific|singapore|sg|global|worldwide|solutions|"
    r"services|systems|labs|the)\b"
)


def candidate_tokens(company: str, limit: int = 4) -> list[str]:
    """Plausible board slugs for a company name, most likely first."""
    name = (company or "").strip()
    if not name:
        return []

    def slug(text: str, joiner: str = "") -> str:
        cleaned = re.sub(r"[^a-z0-9\s-]", " ", text.lower())
        parts = [p for p in re.split(r"[\s-]+", cleaned) if p]
        return joiner.join(parts)

    stripped = _NOISE.sub(" ", name)
    out: list[str] = []
    for text in (stripped, name):
        for joiner in ("", "-"):
            token = slug(text, joiner)
            if token and token not in out:
                out.append(token)
    # A single leading word is a common slug ("shopee" for "Shopee Singapore").
    first = slug(stripped).split()
    head = re.split(r"[\s-]+", _NOISE.sub(" ", name).strip().lower())
    head = [h for h in head if h]
    if head:
        token = re.sub(r"[^a-z0-9]", "", head[0])
        if token and token not in out:
            out.append(token)
    return out[:limit]


@dataclass
class Hit:
    ats: str
    token: str
    jobs: int
    company: str = ""

    @property
    def yaml_entry(self) -> str:
        return (
            f"  - ats: {self.ats}\n"
            f"    token: {self.token}\n"
            f"    company: {self.company}\n"
        )


def _count(ats: str, payload) -> int | None:
    """Job count from a board response, or None if this is not a real board."""
    if ats == "lever":
        return len(payload) if isinstance(payload, list) else None
    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        return len(payload["jobs"])
    return None


def find_boards(
    company: str, max_candidates: int = 3, only: str | None = None
) -> tuple[list[Hit], list[str]]:
    """Probe the public board APIs. Returns (hits, notes)."""
    tokens = candidate_tokens(company, limit=max_candidates)
    if not tokens:
        return [], ["no usable token could be derived from that name"]

    boards = {only: PROBES[only]} if only in PROBES else PROBES
    hits: list[Hit] = []
    notes: list[str] = []
    seen: set[tuple[str, str]] = set()

    for ats, template in boards.items():
        for token in tokens:
            if (ats, token) in seen:
                continue
            seen.add((ats, token))
            url = template.format(token=token)
            try:
                payload = fetcher.get_json(url)
            except NotFound:
                continue          # this company does not run a board here
            except Blocked:
                continue          # the platform declined; nothing to work around
            except Exception as e:
                notes.append(f"{ats}/{token}: {type(e).__name__}")
                continue
            count = _count(ats, payload)
            if count is None:
                continue
            name = company
            if ats == "greenhouse" and isinstance(payload, dict):
                jobs = payload.get("jobs") or []
                if jobs and isinstance(jobs[0], dict):
                    name = jobs[0].get("company_name") or company
            hits.append(Hit(ats=ats, token=token, jobs=count, company=name))
            break                 # one token per platform is enough

    hits.sort(key=lambda h: -h.jobs)
    return hits, notes


# ----------------------------------------------------------------------
def add_to_config(hit: Hit, path: Path | None = None) -> bool:
    """Insert a board into sources.yaml, leaving every comment intact.

    The entry goes directly under `company_boards:` rather than at the end of
    the block, because the block ends in commented examples that are worth
    keeping where they are.
    """
    path = Path(path or (settings.context_dir / "sources.yaml"))
    text = path.read_text(encoding="utf-8")

    if re.search(rf"^\s*token:\s*{re.escape(hit.token)}\s*$", text, re.MULTILINE):
        return False              # already configured

    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if re.match(r"^company_boards:\s*$", line):
            lines.insert(i + 1, hit.yaml_entry)
            path.write_text("".join(lines), encoding="utf-8")
            return True
    # No such key: append the whole block.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"\ncompany_boards:\n{hit.yaml_entry}")
    return True
