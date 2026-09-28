"""`ow --version`, `ow --help` and `ow` alone: the three answers `__main__` gives before a root.

V01-3 times the first two (11:680), and G10 measures them through the console script W7.8l
declares (D619). What these tests pin is what each prints and exits, in-process; the timing is
G10's, and the script itself is `conform/test_console_script_process.py`'s.
"""

from __future__ import annotations

import omniweave.__main__ as launcher
import pytest
from omniweave_core.contract import CONTRACT, RELEASE, SCHEMA_STRING


def test_version_prints_release_contract_and_schema_on_one_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """11:704: *"`ow --version` prints `RELEASE`, `CONTRACT` and `SCHEMA` on one line"*."""
    assert launcher.main(["--version"]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"omniweave {RELEASE}  contract {CONTRACT}  schema {SCHEMA_STRING}\n"
    assert captured.err == ""
    major, minor = SCHEMA_STRING.split(".")
    assert major.isdigit() and minor.isdigit(), "11:704: SCHEMA as <major>.<minor>"


@pytest.mark.parametrize("word", ["--help", "-h"])
def test_help_is_the_generated_trees_help_and_exit_0(
    word: str, capsys: pytest.CaptureFixture[str]
) -> None:
    from omniweave.cli import COMMANDS  # noqa: PLC0415

    assert launcher.main([word]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: ow ")
    roots = {command.words[0] for command in COMMANDS}
    assert all(f" {root} " in out or f"{{{root}," in out or f",{root}," in out for root in roots)


def test_no_command_is_usage_naming_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert launcher.main([]) == 1
    captured = capsys.readouterr()
    assert (captured.out, "ow --help" in captured.err) == ("", True)


@pytest.mark.parametrize(
    "argv",
    [
        ["--render", "json", "explain", "OW-A-013"],
        ["--render=json", "explain", "OW-A-013"],
        ["--no-color", "--render", "json", "explain", "OW-A-013"],
        ["explain", "--render", "json", "OW-A-013"],
    ],
)
def test_a_global_flag_before_the_root_reaches_it(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """D624, closing D619 item 4: 18:887's *"before or after the verb, on every command"*."""
    assert launcher.main(argv) == 0
    assert capsys.readouterr().out.startswith('{"schema": 1, "numeric": "OW-A-013"')


def test_the_root_gets_the_command_line_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing is re-ordered: the root parses the same argv the tree just did."""
    seen: list[list[str]] = []
    monkeypatch.setattr(launcher, "_explain", lambda args: seen.append(args) or 0)
    assert launcher.main(["-q", "--corpus", "x", "explain", "OW-A-013"]) == 0
    assert seen == [["-q", "--corpus", "x", "explain", "OW-A-013"]]


def test_a_flag_before_the_root_that_the_root_refuses_is_refused_by_the_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The flag reaches `explain`, which refuses `--quiet` by name, as it does written after."""
    for argv in (["-q", "explain", "OW-A-013"], ["explain", "OW-A-013", "-q"]):
        assert launcher.main(argv) == 1
        assert "--quiet" in capsys.readouterr().err


@pytest.mark.parametrize(
    "argv",
    [["--frobnicate", "query", "x"], ["--corpus", "x", "ingest", "a"], ["--corpus"]],
)
def test_before_the_root_what_the_tree_cannot_parse_is_usage(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    """An unknown flag, a root the tree hides (`ingest` parses its own argv), a missing value."""
    assert launcher.main(argv) == 1
    assert "ow: error:" in capsys.readouterr().err


def test_a_flag_after_the_root_still_reaches_it(capsys: pytest.CaptureFixture[str]) -> None:
    assert launcher.main(["explain", "OW-A-013", "--render", "json"]) == 0
    assert capsys.readouterr().out.startswith('{"schema": 1, "numeric": "OW-A-013"')


def test_ow_and_omniweave_are_declared_as_one_entry_point_and_no_other() -> None:
    """18:874: *"`ow` and `omniweave` are the same console script; there is no other alias."*"""
    import tomllib  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["scripts"]
    assert scripts == {"ow": "omniweave.__main__:main", "omniweave": "omniweave.__main__:main"}
