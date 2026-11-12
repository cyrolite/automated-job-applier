"""Paths and settings. Everything is resolved relative to the project root
so the tool works the same on Windows, macOS and Linux."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

# src/job_applier/config.py -> project root is three parents up.
ROOT = Path(__file__).resolve().parents[2]

load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    root: Path = ROOT
    context_dir: Path = field(default_factory=lambda: ROOT / "Context")
    profile_path: Path = field(default_factory=lambda: ROOT / "Context" / "profile.yaml")
    source_files_dir: Path = field(default_factory=lambda: ROOT / "Context" / "Files")
    prompts_dir: Path = field(default_factory=lambda: ROOT / "prompts")
    applications_dir: Path = field(default_factory=lambda: ROOT / "applications")
    data_dir: Path = field(default_factory=lambda: ROOT / "data")

    # --- LLM ---
    # provider: anthropic | ollama | none
    provider: str = field(default_factory=lambda: os.getenv("JA_PROVIDER", "anthropic"))
    model: str = field(default_factory=lambda: os.getenv("JA_MODEL", "claude-sonnet-5-5"))
    anthropic_api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )
    ollama_host: str = field(
        default_factory=lambda: os.getenv("JA_OLLAMA_HOST", "http://localhost:11434")
    )
    max_tokens: int = field(default_factory=lambda: int(os.getenv("JA_MAX_TOKENS", "8000")))

    # --- Resume shaping ---
    max_resume_pages: int = field(default_factory=lambda: int(os.getenv("JA_MAX_PAGES", "1")))
    # Bullets kept per role on a tailored resume.
    bullets_per_role: int = field(default_factory=lambda: int(os.getenv("JA_BULLETS_PER_ROLE", "3")))

    @property
    def db_path(self) -> Path:
        # Overridable because SQLite needs a filesystem that supports locking.
        # Network drives and some synced folders do not.
        override = os.getenv("JA_DB_PATH")
        return Path(override) if override else self.data_dir / "tracker.db"

    def ensure_dirs(self) -> None:
        for d in (self.applications_dir, self.data_dir, self.prompts_dir):
            d.mkdir(parents=True, exist_ok=True)

    def llm_available(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.anthropic_api_key)
        if self.provider == "ollama":
            return True
        return False


settings = Settings()
