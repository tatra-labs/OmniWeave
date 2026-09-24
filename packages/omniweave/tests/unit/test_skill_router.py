"""The router body: rendered, within 10:1151's 150 lines, and the same bytes in all three places.

**The sharpest test is `test_every_tool_and_verb_the_body_names_is_the_registrys`.** The router
is the one skill every session loads, and a tool name spelled by hand in it is jcodemunch's #397
(10:111) on the always-resident surface. So every `ow_*` in the body must be an `mcp_name`, and
every `ow <verb>` an Action's CLI spelling or one of the five `unregistered()` names -- which the
day their rows land stop being hand-spelled without anyone editing the body.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from omniweave.install.claude_code import ClaudeCode
from omniweave.install.engine import HostEnv
from omniweave.install.types import InstallOptions
from omniweave.skills import router
from omniweave.skills.hash import bundle_sha256
from omniweave.skills.tier import CORE, is_core
from omniweave.surface.registry import ACTIONS

REPO = Path(__file__).resolve().parents[4]
SKILLS = REPO / "skills"
HEADINGS = (
    "## When NOT to load this skill",
    "## 1. Start from artefact state",
    "## 2. Route the deliverable",
    "### Resolve common ambiguities",
    "## 3. Read the route stub before committing",
    "## 4. Install and enter",
    "## 5. Hand off and leave",
    "## Low-confidence stop rule",
)
#  10:1157-1158, in the tree's order.
STUBS = (
    "pptx", "deck", "docx", "video", "report", "extract", "review", "apply-comments", "driver",
    "ingest",
)  # fmt: skip


class _Clock:
    def wall_ns(self) -> int:
        return 1_788_257_523 * 1_000_000_000

    def monotonic_ns(self) -> int:
        return 0


def test_the_render_fits_the_budget_and_opens_with_its_frontmatter() -> None:
    text = router.render()
    assert text.count("\n") <= router.MAX_LINES
    assert text.startswith("---\nname: omniweave\ndescription: >\n")
    assert text.endswith("\n") and not text.endswith("\n\n")


def test_the_description_is_the_plans_at_the_994_characters_it_measured() -> None:
    """10:1213: *"measured at 994 characters against the 1,024 cap"*."""
    described = router.description()
    assert len(described) == 994
    assert described.startswith("Mandatory entry point for any request")
    assert described.endswith("the ow_query/ow_open MCP tools or `ow query` do that.")


def test_the_frontmatter_is_yaml_a_host_reads_as_written() -> None:
    yaml = pytest.importorskip("yaml")
    document = yaml.safe_load("\n".join(router.FRONTMATTER))
    assert document["name"] == CORE
    assert document["description"].strip() == router.description()
    keywords = [one.strip() for one in document["metadata"]["keywords"].split(",")]
    assert len(keywords) == 20
    assert keywords[0] == "pptx" and keywords[-1] == "omniweave"


def test_the_sections_are_10_1248s_six_in_order_and_the_two_most_skills_omit() -> None:
    lines = router.render().split("\n")
    at = [lines.index(heading) for heading in HEADINGS]
    assert at == sorted(at)


def test_the_tables_are_the_plans_rows() -> None:
    assert len(router.STATES) == 6
    assert router.STATES[0][0].startswith("an `.owdeck`/IL bundle exists")
    assert router.STATES[-1][0] == "nothing exists"
    assert tuple(route.name for route in router.ROUTES) == STUBS
    assert [route.skill for route in router.ROUTES][-1] == ""


def test_every_quoted_cue_is_the_descriptions_own_or_the_pptx_stubs() -> None:
    described = router.description()
    stub = ('"make a powerpoint"', '"pptx"', '"OOXML slides"', '"editable slides for finance"')
    for route in router.ROUTES:
        for cue in route.cues:
            if cue.startswith('"'):
                assert cue in described or cue in stub, (route.name, cue)


def test_every_tool_and_verb_the_body_names_is_the_registrys() -> None:
    body = router.render().split("---\n", 2)[2]
    tools = {spec.mcp_name for spec in ACTIONS.values() if spec.mcp_name}
    named = set(re.findall(r"\bow_[a-z_]+", body))
    assert named == {"ow_query", "ow_open", "ow_corpora"}
    assert named <= tools
    spelled = {"ow " + " ".join(spec.cli) for spec in ACTIONS.values()}
    planned = set(router._PLANNED.values())
    verbs = set(re.findall(r"`(ow [a-z][a-z ]*?)(?: <[a-z]+>)?`", body))
    assert len(verbs) == 8, verbs
    assert verbs <= spelled | planned, verbs - spelled - planned


def test_the_five_verbs_the_body_names_without_a_row_are_listed() -> None:
    """D487: pinned so a row landing flips it, and the body stops spelling that verb by hand."""
    assert router.unregistered() == (
        "skills.install",
        "out.targets",
        "out.check",
        "ingest",
        "route.explain",
    )


def test_the_tier_rule_is_one_name() -> None:
    assert is_core("omniweave")
    assert not is_core("omniweave-pptx")
    assert not is_core("omniweave-authoring")


# ---------------------------------------------------------------------------------------------
# 10:1371: shipped, rendered and blessed agree.
# ---------------------------------------------------------------------------------------------


def test_the_shipped_router_is_the_render_and_the_blessed_copy() -> None:
    assert router.check(SKILLS) == ()


def test_a_hand_edit_and_an_unblessed_change_are_each_named(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    shutil.copytree(SKILLS, root)
    shipped = root / router.SHIPPED
    shipped.write_bytes(shipped.read_bytes() + b"\nA hand edit.\n")
    assert router.check(root) == (
        "skills/omniweave/SKILL.md differs from the render (shipped copy)",
    )
    (root / router.EXPECTED).unlink()
    assert "skills/expected/omniweave/SKILL.md is missing (blessed copy)" in router.check(root)
    assert router.emit(root)
    assert not router.emit(root)
    router.bless(root)
    assert router.check(root) == ()


def test_the_blessed_copy_is_not_itself_a_bundle() -> None:
    """`--skills all` installs every child of `skills/` with a `SKILL.md`; `expected/` has none."""
    assert not (SKILLS / "expected" / "SKILL.md").exists()


# ---------------------------------------------------------------------------------------------
# The measurement W7.5f was waiting for: this repository's bundle now installs.
# ---------------------------------------------------------------------------------------------


def test_this_repositorys_router_bundle_installs_and_reverses(tmp_path: Path) -> None:
    (tmp_path / "home").mkdir()
    env = HostEnv(
        omniweave_home=tmp_path / "owhome",
        user_home=tmp_path / "home",
        clock=_Clock(),
        pid=4242,
        launch=("python", "-m", "omniweave"),
        windows=False,
        which=lambda _name: None,
        lock_wait_ms=0,
        skills_root=SKILLS,
    )
    host = ClaudeCode(env)
    result = host.install("global", InstallOptions(hooks="none", skills="core"))
    (skill,) = [one for one in result.actions if one.kind == "skill"]
    assert skill.action == "created", skill
    installed = tmp_path / "home" / ".agents" / "skills" / CORE
    assert bundle_sha256(installed) == bundle_sha256(SKILLS / CORE)
    assert (installed / "SKILL.md").read_bytes() == (SKILLS / router.SHIPPED).read_bytes()
    host.uninstall("global")
    assert not installed.exists()
