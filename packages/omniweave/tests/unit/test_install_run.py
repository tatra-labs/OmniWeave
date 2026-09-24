"""`ow install` and `ow uninstall` from argv, in-process: the parser, the refusals, the cycle.

**The sharpest test is `test_the_plans_own_example_is_refused_with_both_flags_named`.** 10:2453
prints `ow install --target auto` as the wiring command, and the plan gives `--hooks` and
`--skills` no default (D447), so that exact argv is refused -- with both flags named -- rather than
choosing what an unqualified install does to a user's host. D471.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave.install import run

if TYPE_CHECKING:
    from collections.abc import Sequence


def _env(tmp: Path) -> dict[str, str]:
    (tmp / "home").mkdir(exist_ok=True)
    return {
        "HOME": str(tmp / "home"),
        "USERPROFILE": str(tmp / "home"),
        "OMNIWEAVE_HOME": str(tmp / "owhome"),
    }


def _run(
    argv: Sequence[str], tmp: Path, *, stdin: str = "", env: dict[str, str] | None = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    (tmp / "proj").mkdir(exist_ok=True)
    code = run.main(
        argv,
        env=_env(tmp) if env is None else env,
        cwd=tmp / "proj",
        stdin=io.StringIO(stdin),
        stdout=out,
        stderr=err,
    )
    return code, out.getvalue(), err.getvalue()


def _tree(root: Path) -> dict[str, bytes | None]:
    if not root.exists():
        return {}
    return {
        one.relative_to(root).as_posix(): (one.read_bytes() if one.is_file() else None)
        for one in sorted(root.rglob("*"))
    }


INSTALL = ["install", "--target", "claude-code", "--location", "global", "--hooks", "context"]
#  Named, not `auto`: `auto` is every host found, and PATH is this machine's (D479).
CHECK = ["install", "--check", "--target", "claude-code"]


def test_the_plans_own_example_is_refused_with_both_flags_named(tmp_path: Path) -> None:
    """D471: 10:2453's `ow install --target auto`."""
    code, out, _ = _run(["install", "--target", "auto"], tmp_path)
    assert code == 1
    assert out.startswith("ow: --hooks and --skills have no default (the plan gives none, D447)")
    assert _tree(tmp_path / "home") == {}


def test_one_missing_flag_is_named_alone(tmp_path: Path) -> None:
    code, out, _ = _run([*INSTALL], tmp_path)
    assert code == 1
    assert out.startswith("ow: --skills has no default")


def test_a_choice_the_generator_could_not_publish_is_checked_here(tmp_path: Path) -> None:
    """A human-only row has no MCP input schema, so the parser has no `choices` to enforce."""
    code, out, _ = _run(["install", "--hooks", "sometimes", "--skills", "core"], tmp_path)
    assert (code, out) == (1, "ow: --hooks must be one of none, context, steer; got 'sometimes'\n")
    code, out, _ = _run([*INSTALL, "--skills", "core", "--location", "both"], tmp_path)
    assert (code, out) == (1, "ow: --location must be one of global, local; got 'both'\n")


def test_an_unknown_flag_exits_1_not_argparses_2(tmp_path: Path) -> None:
    """10:1484: usage is 1, and 2 is *"not found"* (10:1485)."""
    code, _, err = _run(["install", "--bogus"], tmp_path)
    assert code == 1
    assert "unrecognized arguments: --bogus" in err


def test_help_is_exit_0_on_the_stream_it_was_given(tmp_path: Path) -> None:
    code, out, _ = _run(["install", "--help"], tmp_path)
    assert code == 0
    assert "--allow-cli" in out


def test_no_home_is_a_usage_error_naming_both_variables(tmp_path: Path) -> None:
    code, _, err = _run([*INSTALL, "--skills", "none"], tmp_path, env={})
    assert code == 1
    assert "neither HOME nor USERPROFILE is set" in err


def test_no_terminal_means_no_question_and_no_write(tmp_path: Path) -> None:
    code, out, _ = _run(["uninstall", "--yes"], tmp_path)
    assert (code, out) == (1, "ow: --location is required: global or local (there is no terminal "
                              "to ask on)\n")  # fmt: skip
    code, out, _ = _run([*INSTALL, "--skills", "none"], tmp_path)
    assert code == 1
    assert out.rstrip().endswith("nothing written (pass --yes to write without asking)")
    assert _tree(tmp_path / "home") == {}


def test_a_terminal_is_asked_the_location_and_the_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """10:1754: the location first, with the directories it will sweep; then the plan's yes."""
    monkeypatch.setattr(run, "_is_terminal", lambda _stream: True)
    argv = ["install", "--target", "claude-code", "--hooks", "context", "--skills", "none"]
    code, out, _ = _run(argv, tmp_path, stdin="global\ny\n")
    assert code == 0
    assert out.startswith("Uninstall from which location?\n  global: ~/.claude.json")
    assert "Write this plan? [y/N]" in out
    assert (tmp_path / "home" / ".claude.json").is_file()


def test_the_whole_cycle_from_argv_leaves_the_home_as_it_was(tmp_path: Path) -> None:
    before = _tree(tmp_path / "home")
    assert _run(CHECK, tmp_path)[0] == 9
    code, out, _ = _run([*INSTALL, "--skills", "none", "--yes"], tmp_path)
    assert code == 0
    assert "wrote 4 entries" in out
    code, out, _ = _run(CHECK, tmp_path)
    assert code == 0
    assert out.startswith("claude-code global   configured    mcp ok")
    code, _, _ = _run(["uninstall", "--location", "global", "--yes"], tmp_path)
    assert code == 0
    assert _run(CHECK, tmp_path)[0] == 9
    assert _tree(tmp_path / "home") == before


def test_print_config_from_argv_writes_nothing(tmp_path: Path) -> None:
    code, out, _ = _run(["install", "--print-config", "claude-code"], tmp_path)
    assert code == 0
    assert out.startswith("# ~/.claude.json  json-key  mcpServers.omniweave\n")
    assert _tree(tmp_path / "home") == {}
    assert not (tmp_path / "owhome").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="the NUL device is Windows's")
def test_the_null_device_is_not_a_terminal_though_isatty_says_it_is() -> None:
    """D472, measured: `isatty()` is True for `NUL`; `GetConsoleMode` is not."""
    with Path(os.devnull).open(encoding="utf-8") as null:
        assert null.isatty()
        assert not run._is_terminal(null)


def test_a_stream_with_no_descriptor_is_not_a_terminal() -> None:
    assert not run._is_terminal(io.StringIO())


# ---------------------------------------------------------------------------------------------
# `ow skills install | remove` (W7.6b), from argv.
# ---------------------------------------------------------------------------------------------


def test_ow_skills_install_and_remove_from_argv(tmp_path: Path) -> None:
    """The router's section 4, `ow skills install <name>` (10:1261), run as an agent runs it."""
    code, out, _ = _run(["skills", "install", "omniweave"], tmp_path)
    assert code == 1
    assert "`ow install --skills core`" in out
    (tmp_path / "home" / ".agents" / "skills").mkdir(parents=True)
    code, out, _ = _run(["skills", "install", "omniweave", "omniweave"], tmp_path)
    assert code == 0, out
    assert out.rstrip().endswith(" created")
    assert _run(["skills", "install", "omniweave-pptx"], tmp_path)[0] == 2
    code, out, _ = _run(["skills", "remove", "omniweave"], tmp_path)
    assert code == 1
    assert "not confirmed; nothing removed" in out
    code, out, _ = _run(["skills", "remove", "omniweave", "--yes"], tmp_path)
    assert code == 0, out
    assert _tree(tmp_path / "home") == {".agents": None, ".agents/skills": None}
    assert not (tmp_path / "owhome" / "skills-lock.json").exists()


def test_ow_skills_install_needs_a_name(tmp_path: Path) -> None:
    assert _run(["skills", "install"], tmp_path)[0] == 1
