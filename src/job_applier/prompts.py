"""Prompt loading. Templates live in prompts/ as markdown with a '# System'
and a '# User' section, so they can be edited without touching code."""
from __future__ import annotations

import re
from pathlib import Path

from .config import settings

_SPLIT = re.compile(r"^#\s*(System|User)\s*$", re.MULTILINE | re.IGNORECASE)


def load(name: str) -> tuple[str, str]:
    """Return (system, user_template) for prompts/<name>.md."""
    path = Path(settings.prompts_dir) / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    text = path.read_text(encoding="utf-8")
    parts = _SPLIT.split(text)
    # parts = ['', 'System', <system body>, 'User', <user body>]
    sections: dict[str, str] = {}
    for i in range(1, len(parts) - 1, 2):
        sections[parts[i].lower()] = parts[i + 1].strip()
    if "system" not in sections or "user" not in sections:
        raise ValueError(f"{path} must contain '# System' and '# User' sections")
    return sections["system"], sections["user"]


def fill(template: str, **values: object) -> str:
    """Substitute {key} placeholders only for the keys given.

    str.format is unusable here because the templates contain JSON braces.
    """
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    return out
