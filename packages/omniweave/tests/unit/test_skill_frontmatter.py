"""10:1239-1243's `tests/test_skill_frontmatter.py`, for every shipped skill.

For each: `len(description) <= 1024`, `name` equals the directory name, `metadata.keywords` present
and comma-separated, and -- for an on-demand skill -- a description whose last sentence is the
generated prerequisite. The frontmatter is read by the small reader below rather than a YAML
library: none is a declared dependency, and the subset a skill uses (plain keys, one folded block,
one quoted scalar across lines) is small enough to read exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave.skills import router
from omniweave.skills.tier import is_core

SKILLS = Path(__file__).resolve().parents[4] / "skills"
PREREQUISITE = "Requires the omniweave router skill and an indexed corpus (ow_corpora to check)."
DESCRIPTION_MAX_CHARS = 1024


def _frontmatter(text: str) -> dict[str, str]:
    """`key -> value` for the block between the two `---` lines; nested keys as `parent.child`."""
    lines = text.split("\n")
    assert lines[0] == "---", "a skill opens with its frontmatter"
    block = lines[1 : lines.index("---", 1)]
    found: dict[str, str] = {}
    parent, key, parts, folded = "", "", [], False

    def close() -> None:
        if key:
            value = " ".join(parts).strip()
            found[key] = value[1:-1] if value.startswith('"') and value.endswith('"') else value

    for line in block:
        indent = len(line) - len(line.lstrip(" "))
        head, sep, rest = line.strip().partition(":")
        starts_key = sep and " " not in head and (indent == 0 or (parent and indent == 2))
        if starts_key and not (folded and indent > 0 and not parent):
            close()
            if indent == 0 and not rest.strip():
                parent, key, parts, folded = head, "", [], False
                continue
            if indent == 0:
                parent = ""
            key = f"{parent}.{head}" if parent and indent == 2 else head
            folded = rest.strip() == ">"
            parts = [] if folded else [rest.strip()]
            continue
        parts.append(line.strip())
    close()
    return found


def _skills() -> list[Path]:
    return sorted(one for one in SKILLS.iterdir() if (one / "SKILL.md").is_file())


def test_the_reader_reads_the_router_as_yaml_would() -> None:
    found = _frontmatter(router.render())
    assert found["name"] == "omniweave"
    assert found["description"] == router.description()
    assert found["metadata.keywords"].startswith("pptx, powerpoint, deck")


def test_at_least_the_core_skill_ships() -> None:
    assert [one.name for one in _skills()][:1] == ["omniweave"]


@pytest.mark.parametrize("skill", _skills(), ids=lambda one: one.name)
def test_every_shipped_skills_frontmatter(skill: Path) -> None:
    found = _frontmatter((skill / "SKILL.md").read_text("utf-8"))
    assert found["name"] == skill.name
    assert 0 < len(found["description"]) <= DESCRIPTION_MAX_CHARS
    keywords = [one.strip() for one in found["metadata.keywords"].split(",")]
    assert len(keywords) > 1
    assert all(keywords)
    if not is_core(skill.name):
        assert found["description"].endswith(PREREQUISITE)
