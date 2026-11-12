"""Load and index the master profile.

The profile is the only place facts live. Every bullet carries a stable id
so generated output can be traced back to a source claim and verified.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .config import settings


@dataclass
class Bullet:
    id: str
    text: str
    tags: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    # Where this bullet came from, for rendering.
    section: str = ""       # experience | projects | activities | education
    parent_id: str = ""
    parent_label: str = ""  # "TikTok Private Limited — Cybersecurity Engineer Intern"


@dataclass
class Skill:
    name: str
    level: str = "working"
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def all_names(self) -> list[str]:
        return [self.name] + list(self.aliases)


class Profile:
    def __init__(self, data: dict[str, Any]):
        self.data = data
        self.bullets: dict[str, Bullet] = {}
        self.skills: list[Skill] = []
        self._index()

    # ---------- loading ----------
    @classmethod
    def load(cls, path: Path | None = None) -> "Profile":
        path = Path(path or settings.profile_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Master profile not found at {path}. "
                "This file is the source of truth; create it before tailoring."
            )
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        return cls(data)

    def _index(self) -> None:
        d = self.data

        def label_for(section: str, item: dict) -> str:
            if section == "experience":
                return f"{item.get('org','')} — {item.get('title','')}"
            if section == "projects":
                return item.get("name", "")
            if section == "activities":
                role = item.get("role", "")
                return f"{item.get('name','')}{', ' + role if role else ''}"
            return item.get("institution", item.get("name", ""))

        for section in ("experience", "projects", "activities", "education"):
            for item in d.get(section) or []:
                parent_id = item.get("id", "")
                label = label_for(section, item)
                key = "highlights" if section == "education" else "bullets"
                for b in item.get(key) or []:
                    bullet = Bullet(
                        id=b["id"],
                        text=b["text"],
                        tags=list(b.get("tags") or []),
                        metrics=list(b.get("metrics") or []),
                        section=section,
                        parent_id=parent_id,
                        parent_label=label,
                    )
                    self.bullets[bullet.id] = bullet

        for s in d.get("skills") or []:
            self.skills.append(
                Skill(
                    name=s["name"],
                    level=s.get("level", "working"),
                    aliases=list(s.get("aliases") or []),
                    tags=list(s.get("tags") or []),
                    evidence=list(s.get("evidence") or []),
                )
            )

    # ---------- accessors ----------
    @property
    def meta(self) -> dict:
        return self.data.get("meta", {})

    @property
    def job_search(self) -> dict:
        return self.data.get("job_search", {})

    def section(self, name: str) -> list[dict]:
        return self.data.get(name) or []

    def bullet(self, bid: str) -> Bullet | None:
        return self.bullets.get(bid)

    def bullets_for(self, parent_id: str) -> list[Bullet]:
        return [b for b in self.bullets.values() if b.parent_id == parent_id]

    def skill(self, name: str) -> Skill | None:
        low = name.lower().strip()
        for s in self.skills:
            if low in [n.lower() for n in s.all_names]:
                return s
        return None

    def all_tags(self) -> set[str]:
        tags: set[str] = set()
        for b in self.bullets.values():
            tags.update(b.tags)
        for s in self.skills:
            tags.update(s.tags)
        return tags

    def corpus(self) -> str:
        """All profile text, for coverage checks."""
        parts: list[str] = []
        for b in self.bullets.values():
            parts.append(b.text)
            parts.extend(b.tags)
        for s in self.skills:
            parts.extend(s.all_names)
            parts.extend(s.tags)
        for item in self.section("certifications_courses"):
            parts.append(str(item))
        for e in self.section("education"):
            parts.append(str(e.get("degree", "")))
            parts.append(str(e.get("second_major", "")))
        return "\n".join(parts)

    def summary_for_prompt(self) -> str:
        """Compact, id-annotated view of every available fact.
        This is what the model is allowed to draw from — nothing else."""
        lines: list[str] = []
        m = self.meta
        lines.append(f"CANDIDATE: {m.get('name')} | {m.get('location')} | {m.get('email')}")
        js = self.job_search
        lines.append(
            f"SEEKING: {', '.join(js.get('targets', []))} | "
            f"graduation {js.get('graduation')} | earliest start {js.get('earliest_start')}"
        )
        lines.append("")
        for e in self.section("education"):
            lines.append(
                f"EDUCATION [{e.get('id')}]: {e.get('degree')}, {e.get('institution')} "
                f"({e.get('start')} to {e.get('end')}), GPA {e.get('gpa')}, "
                f"second major {e.get('second_major')}"
            )
            for h in e.get("highlights") or []:
                lines.append(f"  - [{h['id']}] {h['text']}")
        lines.append("")
        lines.append("EXPERIENCE:")
        for x in self.section("experience"):
            lines.append(
                f"  [{x.get('id')}] {x.get('org')} — {x.get('title')} "
                f"({x.get('start')} to {x.get('end')})"
            )
            for b in x.get("bullets") or []:
                lines.append(f"    - [{b['id']}] {b['text']}")
        lines.append("")
        lines.append("PROJECTS:")
        for p in self.section("projects"):
            lines.append(f"  [{p.get('id')}] {p.get('name')} ({p.get('start')} to {p.get('end')})")
            for b in p.get("bullets") or []:
                lines.append(f"    - [{b['id']}] {b['text']}")
        lines.append("")
        lines.append("ACTIVITIES / LEADERSHIP:")
        for a in self.section("activities"):
            lines.append(f"  [{a.get('id')}] {a.get('name')} — {a.get('role')}")
            for b in a.get("bullets") or []:
                lines.append(f"    - [{b['id']}] {b['text']}")
        lines.append("")
        lines.append("SKILLS (name | self-assessed level | aliases):")
        for s in self.skills:
            al = f" | aliases: {', '.join(s.aliases)}" if s.aliases else ""
            lines.append(f"  - {s.name} | {s.level}{al}")
        lines.append("")
        lines.append("COURSES: " + "; ".join(str(c) for c in self.section("certifications_courses")))
        return "\n".join(lines)
