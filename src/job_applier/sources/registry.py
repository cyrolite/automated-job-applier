"""Builds sources from Context/sources.yaml."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import settings
from .ashby import AshbySource
from .base import Source
from .browser import BrowserAssistedSource
from .greenhouse import GreenhouseSource
from .lever import LeverSource
from .mycareersfuture import MyCareersFutureSource

ATS_CLASSES = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
}

DEFAULT_PATH = "sources.yaml"


@dataclass
class SourceConfig:
    search_terms: list[str] = field(default_factory=list)
    screening: dict = field(default_factory=dict)
    mycareersfuture: dict = field(default_factory=dict)
    company_boards: list[dict] = field(default_factory=list)
    browser_boards: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None = None) -> "SourceConfig":
        path = Path(path or (settings.context_dir / DEFAULT_PATH))
        if not path.exists():
            raise FileNotFoundError(
                f"No source configuration at {path}. "
                "Copy the template from the repository or run `ja init`."
            )
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(
            search_terms=list(data.get("search_terms") or []),
            screening=dict(data.get("screening") or {}),
            mycareersfuture=dict(data.get("mycareersfuture") or {}),
            company_boards=list(data.get("company_boards") or []),
            browser_boards=dict(data.get("browser_boards") or {}),
        )

    # ---------- derived settings ----------
    @property
    def max_years(self) -> int:
        return int(self.screening.get("max_years_experience", 2))

    @property
    def min_required_score(self) -> float:
        return float(self.screening.get("min_required_score", 45))

    @property
    def max_per_source(self) -> int:
        return int(self.screening.get("max_per_source", 300))

    # ---------- source construction ----------
    def api_sources(self) -> list[Source]:
        out: list[Source] = []
        mcf = self.mycareersfuture
        if mcf.get("enabled", True):
            out.append(
                MyCareersFutureSource(
                    keywords=self.search_terms or [""],
                    max_per_keyword=int(mcf.get("max_per_keyword", 100)),
                    sort_by=str(mcf.get("sort_by", "new_posting_date")),
                    min_salary=int(mcf.get("min_salary", 0) or 0),
                )
            )
        for board in self.company_boards:
            ats = str(board.get("ats", "")).lower()
            token = str(board.get("token", "")).strip()
            if not token:
                continue
            cls = ATS_CLASSES.get(ats)
            if cls is None:
                continue
            out.append(cls(token=token, company=str(board.get("company", "") or "")))
        return out

    def browser_sources(self) -> list[BrowserAssistedSource]:
        out: list[BrowserAssistedSource] = []
        for board, opts in (self.browser_boards or {}).items():
            opts = dict(opts or {})
            if not opts.pop("enabled", False):
                continue
            try:
                out.append(
                    BrowserAssistedSource(board, self.search_terms or [""], **opts)
                )
            except ValueError:
                continue
        return out

    def unsupported_ats(self) -> list[str]:
        """Configured boards whose platform has no adapter, so the user is told
        rather than left wondering why a company produced nothing."""
        bad = []
        for board in self.company_boards:
            ats = str(board.get("ats", "")).lower()
            if ats and ats not in ATS_CLASSES:
                bad.append(f"{board.get('company') or board.get('token')} ({ats})")
        return bad
