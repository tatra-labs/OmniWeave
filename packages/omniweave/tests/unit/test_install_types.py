"""`omniweave.install.types`: the protocol as the plan writes it, and the types it never defines.

**The sharpest test is `test_hooks_none_and_hooks_None_are_different_requests`.** 10:1427's
`--hooks none` and 10:1657's `hooks=None` are one keystroke apart and mean *write no hooks* and
*do not look at hooks*; the type is what keeps them apart. D447.
"""

from __future__ import annotations

import dataclasses
import inspect
import re
from typing import TYPE_CHECKING, get_args

import pytest
from omniweave.hooks.envelope import EVENTS
from omniweave.install import types as module
from omniweave.install.types import (
    ACTIONS,
    HOOK_SETS,
    KINDS,
    LOCATIONS,
    MODES,
    TARGET_IDS,
    AgentTarget,
    DetectionResult,
    FileAction,
    InstallOptions,
    WriteResult,
)

if TYPE_CHECKING:
    from conftest import PlanDocs

INTERFACES = "10-interfaces.md"
SKETCH = "18-api-sketch.md"


def _line(plan: PlanDocs, document: str, number: int) -> str:
    return plan.lines(document)[number - 1]


def test_the_seven_target_ids_are_10_1632_in_its_order(plan: PlanDocs) -> None:
    plan.require()
    line = _line(plan, INTERFACES, 1632)
    assert line.startswith("TargetId = Literal[")
    assert tuple(re.findall(r'"([a-z-]+)"', line)) == TARGET_IDS


def test_the_two_locations_are_10_1633(plan: PlanDocs) -> None:
    plan.require()
    assert _line(plan, INTERFACES, 1633) == 'Location = Literal["global", "local"]'
    assert LOCATIONS == ("global", "local")


def test_the_six_file_actions_are_10_1645(plan: PlanDocs) -> None:
    plan.require()
    line = _line(plan, INTERFACES, 1645)
    listed = re.search(r"\{([^}]*)\}", line)
    assert listed is not None
    assert tuple(part.strip() for part in listed.group(1).split(",")) == ACTIONS


def test_kinds_and_modes_are_the_table_at_10_1665_and_the_receipt_rows(plan: PlanDocs) -> None:
    """The table's rows in order, and every `kind`/`mode` a 10:1702 receipt row spells."""
    plan.require()
    rows = plan.lines(INTERFACES)[1666:1671]
    modes = tuple(re.search(r"\| `([a-z-]+)`", row).group(1) for row in rows)  # type: ignore[union-attr]
    assert modes == MODES
    receipt = "\n".join(plan.lines(INTERFACES)[1701:1727])
    assert set(re.findall(r'"kind":"([a-z]+)"', receipt)) == set(KINDS)
    assert set(re.findall(r'"mode":"([a-z-]+)"', receipt)) == set(MODES)


def test_the_protocol_has_10_1636s_attributes_and_1637_1642s_methods(plan: PlanDocs) -> None:
    plan.require()
    block = "\n".join(plan.lines(INTERFACES)[1634:1642])
    methods = tuple(re.findall(r"def (\w+)\(", block))
    assert methods == (
        "supports_location",
        "detect",
        "install",
        "uninstall",
        "print_config",
        "describe_paths",
    )
    for name in methods:
        assert callable(getattr(AgentTarget, name))
    assert set(AgentTarget.__annotations__) == {"id", "display_name", "docs_url"}


# ---------------------------------------------------------------------------------------------
# D447: `--hooks none|context|steer` and `hooks=None`.
# ---------------------------------------------------------------------------------------------


def test_hooks_none_and_hooks_None_are_different_requests(plan: PlanDocs) -> None:  # noqa: N802
    plan.require()
    assert "--hooks none|context|steer" in _line(plan, INTERFACES, 1427).replace("\\", "")
    assert "allow_cli=False, hooks=None" in _line(plan, INTERFACES, 1657)
    refresh = InstallOptions(hooks=None, skills="core")
    nothing = InstallOptions(hooks="none", skills="core")
    assert refresh != nothing
    assert refresh.hooks is None
    assert HOOK_SETS[nothing.hooks] == ()  # type: ignore[index]


def test_context_is_the_five_events_18s_dry_run_lists(plan: PlanDocs) -> None:
    """18:2977-2978 is the only place the difference shows: no `PreToolUse`."""
    plan.require()
    listed = " ".join(plan.lines(SKETCH)[2976:2978])
    assert "--hooks context" in _line(plan, SKETCH, 2973)
    shown = tuple(name for name in EVENTS if re.search(rf"\b{name}\b", listed))
    assert shown == HOOK_SETS["context"]
    assert "PreToolUse" not in HOOK_SETS["context"]


def test_steer_is_all_six_as_10_1720s_receipt_row_lists_them(plan: PlanDocs) -> None:
    plan.require()
    row = " ".join(plan.lines(INTERFACES)[1719:1721])
    assert tuple(re.findall(r'"([A-Za-z]+)"', row.split('"events":', 1)[1])) == HOOK_SETS["steer"]
    assert set(HOOK_SETS["steer"]) - set(HOOK_SETS["context"]) == {"PreToolUse"}


def test_the_hook_sets_are_exactly_the_three_flag_values() -> None:
    assert tuple(HOOK_SETS) == get_args(module.HookSet)


def test_hooks_and_skills_have_no_default_and_allow_cli_is_off(plan: PlanDocs) -> None:
    """10:1681 gives `--allow-cli` its default and nothing gives the other two one."""
    plan.require()
    assert "**off by default**" in _line(plan, INTERFACES, 1681)
    with pytest.raises(TypeError):
        InstallOptions()  # type: ignore[call-arg]
    fields = {field.name: field for field in dataclasses.fields(InstallOptions)}
    assert fields["hooks"].default is dataclasses.MISSING
    assert fields["skills"].default is dataclasses.MISSING
    assert fields["allow_cli"].default is False


# ---------------------------------------------------------------------------------------------
# The result types.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("actions", "changed"),
    [
        ((), False),
        (("unchanged", "not-found", "kept"), False),
        (("unchanged", "created"), True),
        (("updated",), True),
        (("kept", "removed"), True),
    ],
)
def test_changed_is_whether_anything_was_written_or_removed(
    actions: tuple[str, ...], changed: bool
) -> None:
    result = WriteResult(
        "claude-code",
        "global",
        tuple(FileAction(path=f"p{i}", action=a) for i, a in enumerate(actions)),  # type: ignore[arg-type]
    )
    assert result.changed() is changed


def test_every_changing_action_is_one_of_the_six() -> None:
    source = inspect.getsource(WriteResult.changed)
    assert set(re.findall(r'"([a-z-]+)"', source)) <= set(ACTIONS)


def test_the_result_types_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DetectionResult(installed=True, already_configured=False).installed = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        FileAction("p", "created").action = "kept"  # type: ignore[misc]
