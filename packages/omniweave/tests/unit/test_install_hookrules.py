"""`json-hook-rules`: the command, the five spellings of ours, and convergence without collateral.

**The sharpest test is `test_an_upgrade_from_each_spelling_converges_rather_than_appends`.** 10:1693
gives the ownership parse one job: an upgrade converges an old rule instead of appending a second.
Every spelling an earlier install could have left -- the plan's four and the interpreter form this
machine can only produce (D456) -- is installed over, and each ends as exactly one rule.

The second is `test_this_machines_interpreter_needs_quoting_for_its_parentheses_too` (D457).
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks.check import resolve, split
from omniweave.hooks.envelope import EVENTS
from omniweave.install.hookrules import (
    Desired,
    converge,
    desired,
    hook_command,
    launcher,
    owned_event,
    owned_pairs,
    strip,
    tokens,
)
from omniweave.install.modes import Site, set_hooks, unset_hooks
from omniweave.install.primitives import render_json
from omniweave.install.types import HOOK_SETS

if TYPE_CHECKING:
    from conftest import PlanDocs

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
OW = ("/opt/tools/ow",)
THEIRS = {"type": "command", "command": "/usr/bin/prettier --check"}


class _Clock:
    def wall_ns(self) -> int:
        return T0

    def monotonic_ns(self) -> int:
        return 0


CLOCK = _Clock()


def _wanted(hooks: str = "steer", launch: tuple[str, ...] = OW) -> tuple[Desired, ...]:
    return desired(HOOK_SETS[hooks], launch, windows=False)  # type: ignore[index]


def _commands(document: dict[str, Any]) -> list[str]:
    return [cmd for _, cmd in owned_pairs(document)]


# ---------------------------------------------------------------------------------------------
# The command. 10:1683-1689, D456, D457.
# ---------------------------------------------------------------------------------------------


def test_the_plans_launcher_does_not_exist_on_this_machine() -> None:
    """`shutil.which("ow")` is None here: no console script is declared (D456)."""
    assert shutil.which("ow") is None or Path(str(shutil.which("ow"))).is_absolute()
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    assert "[project.scripts]" not in pyproject.read_text("utf-8")
    assert launcher(which=lambda _: None, executable=sys.executable) == (
        sys.executable,
        "-m",
        "omniweave",
    )


def test_an_absolute_ow_wins_and_a_relative_one_does_not() -> None:
    """Absolute by this platform's rule: `/usr/local/bin/ow` is drive-relative on Windows (D425)."""
    ow = str(Path(sys.executable).with_name("ow"))
    assert launcher(which=lambda _: ow, executable=sys.executable) == (ow,)
    assert launcher(which=lambda _: "ow", executable=sys.executable)[0] == sys.executable
    assert isinstance(launcher(which=lambda _: None, executable="python"), str)


def test_the_command_is_the_plans_shape(plan: PlanDocs) -> None:
    """18:2992-2996: `/usr/local/bin/ow hook session-start`, one word per event."""
    plan.require()
    printed = plan.lines("18-api-sketch.md")[2991]
    assert "/usr/local/bin/ow hook session-start" in printed
    command = hook_command(("/usr/local/bin/ow",), "SessionStart", windows=False)
    assert command == "/usr/local/bin/ow hook session-start"


def test_a_windows_path_is_forward_slashed_and_a_spaced_one_quoted() -> None:
    command = hook_command((r"C:\Program Files\Python\Scripts\ow.exe",), "PreCompact", windows=True)
    assert command == '"C:/Program Files/Python/Scripts/ow.exe" hook pre-compact'
    assert split(command)[0] == "C:/Program Files/Python/Scripts/ow.exe"


def test_this_machines_interpreter_needs_quoting_for_its_parentheses_too() -> None:
    """An unquoted `(` is a /bin/sh syntax error with or without a space beside it. D457."""
    unquoted = "C:/tools(x86)/ow.exe hook session-end"
    assert split(unquoted)[0] == "C:/tools(x86)/ow.exe"  # shlex: runnable; /bin/sh: exit 2
    assert "as syntax" in resolve(unquoted, path="").reason  # D458
    quoted = hook_command(("C:/tools(x86)/ow.exe",), "SessionEnd", windows=True)
    assert quoted == '"C:/tools(x86)/ow.exe" hook session-end'
    assert split(quoted)[0] == "C:/tools(x86)/ow.exe"
    here = launcher()
    assert isinstance(here, tuple)
    command = hook_command(here, "SessionEnd")
    expected = here[0].replace("\\", "/") if sys.platform == "win32" else here[0]
    assert split(command)[0] == expected
    assert not resolve(command, path="").reason


@pytest.mark.parametrize("head", ['C:/a"b/ow.exe', "/opt/$HOME/ow", "/opt/`x`/ow"])
def test_a_head_no_quoting_protects_is_refused(head: str) -> None:
    with pytest.raises(ValueError, match="no shell quoting protects"):
        hook_command((head,), "SessionStart", windows=False)


# ---------------------------------------------------------------------------------------------
# Ownership. 10:1690-1693.
# ---------------------------------------------------------------------------------------------

SPELLINGS = {
    "bare": "ow hook session-start",
    "absolute, forward slash": "/usr/local/bin/ow hook session-start",
    "absolute, backslash after JSON": "C:\\Python\\Scripts\\ow.exe hook session-start",
    "quoted, with spaces": '"C:/Program Files/Python/Scripts/ow.exe" hook session-start',
    "interpreter (D456)": '"E:/x y/python.exe" -m omniweave hook session-start',
}


def test_the_plan_names_four_spellings(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("10-interfaces.md")[1689:1692])
    assert "four spellings (bare name, absolute POSIX-slash, absolute back-slash" in text
    assert "-m omniweave" not in text


@pytest.mark.parametrize("name", list(SPELLINGS))
def test_each_spelling_is_ours(name: str) -> None:
    assert owned_event(SPELLINGS[name]) == "SessionStart"


def test_a_backslash_survives_the_tokenizer_and_would_not_survive_shlex() -> None:
    command = SPELLINGS["absolute, backslash after JSON"]
    assert tokens(command)[0] == "C:\\Python\\Scripts\\ow.exe"
    assert split(command)[0] == "C:PythonScriptsow.exe"


@pytest.mark.parametrize(
    ("command", "event"),
    [
        ("ow hook prompt", "UserPromptSubmit"),  # G26's alias, D432
        ("ow hook bogus", ""),  # ours, a word this release does not know
        ("python3.12 -m omniweave hook pre-tool-use", "PreToolUse"),
        ("ow serve --mcp", None),  # ours, but not a hook
        ("/usr/bin/owl hook session-start", None),
        ("node ow.js hook session-start", None),
        ("python -m other hook session-start", None),
        ("", None),
        (42, None),
    ],
)
def test_what_is_not_ours_is_not(command: object, event: str | None) -> None:
    assert owned_event(command) == event


# ---------------------------------------------------------------------------------------------
# Convergence. 10:1654, 10:1695-1698.
# ---------------------------------------------------------------------------------------------


def test_a_fresh_install_appends_one_rule_per_event_with_the_tables_matchers() -> None:
    document: dict[str, Any] = {}
    result = converge(document, _wanted())
    assert list(document["hooks"]) == list(EVENTS)
    assert result.created == ["hooks", *(f"hooks.{name}" for name in EVENTS)]
    assert document["hooks"]["PreToolUse"] == [
        {
            "matcher": "Read|Grep|Glob",
            "hooks": [{"type": "command", "command": "/opt/tools/ow hook pre-tool-use"}],
        }
    ]
    assert "matcher" not in document["hooks"]["UserPromptSubmit"][0]


@pytest.mark.parametrize("name", list(SPELLINGS))
def test_an_upgrade_from_each_spelling_converges_rather_than_appends(name: str) -> None:
    old = SPELLINGS[name]
    document = {
        "hooks": {
            "SessionStart": [{"matcher": "compact", "hooks": [{"type": "command", "command": old}]}]
        }
    }
    result = converge(document, _wanted("context"))
    rules = document["hooks"]["SessionStart"]
    assert len(rules) == 1
    assert rules[0]["hooks"] == [{"type": "command", "command": "/opt/tools/ow hook session-start"}]
    assert rules[0]["matcher"] == EVENTS["SessionStart"].matcher  # entirely ours: converged
    assert "SessionStart" in result.converged
    assert "SessionStart" in result.matchers


def test_a_shared_rule_converges_the_command_and_never_the_matcher() -> None:
    """10:1697: re-scoping a shared rule's matcher would re-scope somebody else's hook."""
    document = {
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "Edit",
                    "hooks": [THEIRS, {"type": "command", "command": "ow hook post-tool-use"}],
                }
            ]
        }
    }
    result = converge(document, _wanted())
    rule = document["hooks"]["PostToolUse"][0]
    assert rule["matcher"] == "Edit"
    assert rule["hooks"] == [
        THEIRS,
        {"type": "command", "command": "/opt/tools/ow hook post-tool-use"},
    ]
    assert "PostToolUse" not in result.matchers
    assert len(document["hooks"]["PostToolUse"]) == 1


def test_duplicates_and_unwanted_events_are_pruned_one_command_at_a_time() -> None:
    document = {
        "hooks": {
            "SessionEnd": [
                {"hooks": [{"type": "command", "command": "ow hook session-end"}]},
                {
                    "hooks": [
                        THEIRS,
                        {"type": "command", "command": "C:\\old\\ow.exe hook session-end"},
                    ]
                },
            ],
            "PreToolUse": [
                {
                    "matcher": "Read",
                    "hooks": [{"type": "command", "command": "ow hook pre-tool-use"}],
                }
            ],
        }
    }
    result = converge(document, _wanted("context"))  # context: no PreToolUse
    assert "PreToolUse" not in document["hooks"]
    assert document["hooks"]["SessionEnd"] == [
        {"hooks": [{"type": "command", "command": "/opt/tools/ow hook session-end"}]},
        {"hooks": [THEIRS]},
    ]
    assert result.pruned == ["SessionEnd", "PreToolUse"]


def test_a_file_with_nothing_of_ours_is_touched_only_by_the_append() -> None:
    """10:1654's "only if something matched": their rules come back equal, ours are appended."""
    theirs = {"hooks": {"PostToolUse": [{"matcher": "Write", "hooks": [THEIRS]}]}}
    document = copy.deepcopy(theirs)
    result = converge(document, [])
    assert document == theirs
    assert not result.matched()
    converge(document, _wanted())
    assert document["hooks"]["PostToolUse"][0] == theirs["hooks"]["PostToolUse"][0]


def test_hooks_none_removes_ours_and_nothing_else() -> None:
    document = {"hooks": {"PostToolUse": [{"hooks": [THEIRS]}]}}
    converge(document, _wanted())
    converge(document, [])
    assert document == {"hooks": {"PostToolUse": [{"hooks": [THEIRS]}]}}


def test_a_hooks_value_of_the_wrong_type_is_refused() -> None:
    assert "not an object" in converge({"hooks": []}, _wanted()).refusal


def test_strip_keeps_an_empty_event_list_the_user_had() -> None:
    document: dict[str, Any] = {"hooks": {"SessionStart": []}}
    converge(document, _wanted("context"))
    assert strip(copy.deepcopy(document), drop_emptied=False) == [*HOOK_SETS["context"]]
    kept = copy.deepcopy(document)
    strip(kept, drop_emptied=False)
    assert kept["hooks"]["SessionStart"] == []


# ---------------------------------------------------------------------------------------------
# The mode: files, rows, byte identity.
# ---------------------------------------------------------------------------------------------

SETTINGS = {
    "no hooks": '{\n  "model": "opus"\n}\n',
    "their hooks, 4 spaces, CRLF": (
        '{\r\n    "hooks": {\r\n        "PostToolUse": [\r\n            {\r\n'
        '                "matcher": "Write",\r\n                "hooks": [\r\n'
        '                    {\r\n                        "type": "command",\r\n'
        '                        "command": "/usr/bin/prettier --check"\r\n'
        "                    }\r\n                ]\r\n            }\r\n        ]\r\n    }\r\n}"
    ),
    "an empty event list of theirs": '{\n  "hooks": {\n    "SessionStart": []\n  }\n}\n',
}


def _site(home: Path) -> Site:
    return Site("claude-code", "global", home / ".claude" / "settings.json", home)


@pytest.mark.parametrize("name", list(SETTINGS))
@pytest.mark.parametrize("hooks", ["context", "steer"])
def test_install_reinstall_uninstall_is_byte_identical(
    tmp_path: Path, name: str, hooks: str
) -> None:
    site = _site(tmp_path)
    site.path.parent.mkdir()
    raw = SETTINGS[name].encode()
    site.path.write_bytes(raw)
    first = set_hooks(site, _wanted(hooks), previous=None, clock=CLOCK, pid=PID)
    assert first.record is not None
    assert first.record.events == HOOK_SETS[hooks]  # type: ignore[index]
    again = set_hooks(site, _wanted(hooks), previous=first.record, clock=CLOCK, pid=PID)
    assert again.action.action == "unchanged"
    removed = unset_hooks(site, entry=first.record, pid=PID)
    assert removed.action.action == "removed"
    assert site.path.read_bytes() == raw


def test_a_created_settings_file_and_directory_go_with_the_uninstall(tmp_path: Path) -> None:
    site = _site(tmp_path)
    row = set_hooks(site, _wanted(), previous=None, clock=CLOCK, pid=PID).record
    assert row is not None
    assert row.created_file
    assert row.created_dirs == ("~/.claude",)
    unset_hooks(site, entry=row, pid=PID)
    assert list(tmp_path.iterdir()) == []


def test_a_command_the_user_retargeted_is_kept(tmp_path: Path) -> None:
    site = _site(tmp_path)
    row = set_hooks(site, _wanted(), previous=None, clock=CLOCK, pid=PID).record
    document = json.loads(site.path.read_bytes())
    document["hooks"]["SessionEnd"][0]["hooks"][0]["command"] = "/elsewhere/ow hook session-end"
    site.path.write_bytes(render_json(document))
    kept = unset_hooks(site, entry=row, pid=PID)
    assert (kept.action.action, kept.forget) == ("kept", None)


def test_the_hosts_own_changes_beside_ours_do_not_stop_the_uninstall(tmp_path: Path) -> None:
    site = _site(tmp_path)
    row = set_hooks(site, _wanted(), previous=None, clock=CLOCK, pid=PID).record
    document = json.loads(site.path.read_bytes()) | {"model": "sonnet"}
    site.path.write_bytes(render_json(document))
    removed = unset_hooks(site, entry=row, pid=PID)
    assert removed.action.action == "removed"
    assert json.loads(site.path.read_bytes()) == {"model": "sonnet"}


def test_hooks_none_forgets_the_row_and_removes_ours(tmp_path: Path) -> None:
    site = _site(tmp_path)
    row = set_hooks(site, _wanted(), previous=None, clock=CLOCK, pid=PID).record
    none = set_hooks(site, (), previous=row, clock=CLOCK, pid=PID)
    assert (none.action.action, none.record, none.forget) == ("removed", None, row)
    assert owned_pairs(json.loads(site.path.read_bytes())) == []


def test_a_lost_row_is_re_derived_by_ownership(tmp_path: Path) -> None:
    site = _site(tmp_path)
    site.path.parent.mkdir()
    site.path.write_bytes(SETTINGS["their hooks, 4 spaces, CRLF"].encode())
    set_hooks(site, _wanted(), previous=None, clock=CLOCK, pid=PID)
    removed = unset_hooks(site, entry=None, pid=PID)
    assert removed.action.action == "removed"
    assert "re-derivation" in removed.action.note
    assert _commands(json.loads(site.path.read_bytes())) == []


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    site = _site(tmp_path)
    planned = set_hooks(site, _wanted(), previous=None, clock=CLOCK, pid=PID, dry_run=True)
    assert (planned.action.action, planned.record) == ("created", None)
    assert list(tmp_path.iterdir()) == []
