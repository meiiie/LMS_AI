"""Load Anthropic-format SKILL.md files from `library/` and inject into prompts.

Pattern: progressive disclosure (Anthropic 2026)
  Level 1 — metadata (name + description) → always loaded into system prompt.
  Level 2 — SKILL.md body → loaded when skill triggered for the query.
  Level 3 — references/ → loaded on demand by LLM (file-read tool).

This module implements Levels 1 and 2. Level 3 is reachable via the file
path field on each SkillEntry — Wiii's filesystem tools or future MCP
clients can fetch references when the SKILL body points to them.

Format reference: https://github.com/anthropics/skills (skill-creator).
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


def _strip_diacritics(text: str) -> str:
    """Lowercase + diacritic-strip text for trigger matching.

    Vietnamese SKILLs commonly write triggers with diacritics ('ở đâu',
    'chỉ cho'), but users often type without them ('o dau', 'chi cho').
    Without normalization, matching would silently fail.

    Applies:
      1. lowercase
      2. NFD decomposition + combining-mark removal (covers ừ, ậ, ố, ...)
      3. explicit ``đ → d`` / ``Đ → d`` (these are separate codepoints,
         NFD does NOT decompose them — same recipe as
         ``direct_intent._normalize_for_intent``).
    """
    if not text:
        return ""
    lowered = text.lower().replace("đ", "d").replace("Đ", "d")
    nfkd = unicodedata.normalize("NFD", lowered)
    return "".join(c for c in nfkd if unicodedata.category(c) != "Mn")

logger = logging.getLogger(__name__)

LIBRARY_DIR = Path(__file__).resolve().parent / "library"


@dataclass(frozen=True)
class SkillEntry:
    """One SKILL.md as loaded from library/."""

    name: str
    description: str
    body: str
    path: str
    triggers: tuple[str, ...] = field(default_factory=tuple)
    references: tuple[str, ...] = field(default_factory=tuple)

    def metadata_block(self) -> str:
        """Level-1 disclosure: 1-2 sentence description for system prompt."""
        # Trim long descriptions to first 600 chars for context budget.
        short = self.description.strip()
        if len(short) > 600:
            short = short[:600].rsplit(".", 1)[0] + "."
        return f"### Skill `{self.name}`\n{short}"

    def full_body(self) -> str:
        """Level-2 disclosure: the SKILL.md instructions block."""
        return f"## SKILL: {self.name}\n\n{self.body.strip()}"


def _parse_skill_md(path: Path) -> Optional[SkillEntry]:
    """Parse a single SKILL.md file. Returns None on malformed files."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.debug("[SKILL_LIB] read fail %s: %s", path, exc)
        return None

    # Frontmatter: --- ... ---
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, flags=re.DOTALL)
    if not m:
        logger.debug("[SKILL_LIB] no frontmatter: %s", path)
        return None
    frontmatter, body = m.groups()

    # name: required
    name_match = re.search(r"(?m)^name:\s*(.+?)\s*$", frontmatter)
    if not name_match:
        logger.warning("[SKILL_LIB] missing name field: %s", path)
        return None
    name = name_match.group(1).strip()

    # description: required, supports both inline and `|` block scalar
    desc = ""
    block_match = re.search(
        r"(?m)^description:\s*\|\s*\n((?:[ \t]+.*\n?)+)", frontmatter
    )
    if block_match:
        # Strip leading whitespace from each line
        lines = block_match.group(1).splitlines()
        # Find common indent
        indents = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
        common = min(indents) if indents else 0
        desc = "\n".join(l[common:] for l in lines).strip()
    else:
        inline_match = re.search(r"(?m)^description:\s*(.+?)\s*$", frontmatter)
        if inline_match:
            desc = inline_match.group(1).strip()

    if not desc:
        logger.warning("[SKILL_LIB] missing description: %s", path)
        return None

    # Trigger extraction (heuristic): look for quoted lowercase terms in
    # description (Anthropic convention: pushy descriptions list triggers).
    # Each trigger is stored in BOTH its raw lowercased form and its
    # diacritic-stripped form so queries without diacritics still match.
    raw_triggers = [
        t.strip().lower()
        for t in re.findall(r"'([^']{2,40})'", desc)
        if t.strip()
    ]
    seen: set[str] = set()
    expanded: list[str] = []
    for t in raw_triggers:
        for variant in (t, _strip_diacritics(t)):
            if variant and variant not in seen:
                seen.add(variant)
                expanded.append(variant)
    triggers = tuple(expanded)

    # References: scan references/ subfolder.
    refs_dir = path.parent / "references"
    references: tuple[str, ...] = ()
    if refs_dir.is_dir():
        references = tuple(
            sorted(str(r) for r in refs_dir.glob("*.md") if r.is_file())
        )

    return SkillEntry(
        name=name,
        description=desc,
        body=body.strip(),
        path=str(path.parent),
        triggers=triggers,
        references=references,
    )


_CACHE: list[SkillEntry] | None = None


def load_library_skills(*, force_reload: bool = False) -> list[SkillEntry]:
    """Load all SKILL.md files under `library/`. Cached after first call."""
    global _CACHE
    if _CACHE is not None and not force_reload:
        return _CACHE
    if not LIBRARY_DIR.is_dir():
        logger.debug("[SKILL_LIB] library dir missing: %s", LIBRARY_DIR)
        _CACHE = []
        return _CACHE

    skills: list[SkillEntry] = []
    for entry in sorted(LIBRARY_DIR.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.exists():
            continue
        parsed = _parse_skill_md(skill_md)
        if parsed:
            skills.append(parsed)

    logger.info("[SKILL_LIB] loaded %d skills from %s", len(skills), LIBRARY_DIR)
    _CACHE = skills
    return skills


def match_skills_for_query(query: str) -> list[SkillEntry]:
    """Return skills whose triggers appear in ``query``.

    Compares against both the lowercased query AND its diacritic-
    stripped form, so Vietnamese queries without diacritics ('o dau')
    still match diacritic-form triggers ('ở đâu').
    """
    if not query:
        return []
    q_lower = query.lower()
    q_stripped = _strip_diacritics(q_lower)
    bag = q_lower + "\n" + q_stripped
    matched: list[SkillEntry] = []
    for skill in load_library_skills():
        if any(t in bag for t in skill.triggers):
            matched.append(skill)
    return matched
