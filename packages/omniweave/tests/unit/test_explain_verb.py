"""`ow explain`: register rows by either spelling, exit statuses, and the unknown-code refusal.

Every expectation is read from the shipped `codes.toml` through `load_register()`, so a register
edit moves the test with it: what is under test is that the verb prints the row, not what the row
says.
"""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave.surface import explain as verb
from omniweave_core.errors import load_register

if TYPE_CHECKING:
    from collections.abc import Sequence


def _run(argv: Sequence[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["explain", *argv], stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _json(argv: Sequence[str]) -> dict[str, Any]:
    code, out, err = _run([*argv, "--render", "json"])
    assert (code, err) == (0, "")
    document: dict[str, Any] = json.loads(out)
    return document


def test_a_numeric_prints_18s_block_from_the_register() -> None:
    row = load_register().by_numeric["OW-A-013"]
    code, out, err = _run(["OW-A-013"])
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0] == "OW-A-013  OW_PARSE_GAP_IN_SCOPE"
    assert lines[1] == f"  {row.meaning}"
    assert lines[3] == f"  see: {row.owner_doc}"


def test_either_spelling_in_any_case_is_the_same_row() -> None:
    """10:1438: *"accepts `OW-A-013` or `OW_PARSE_GAP_IN_SCOPE`"*."""
    by_numeric = _run(["OW-A-013"])[1]
    assert _run(["OW_PARSE_GAP_IN_SCOPE"])[1] == by_numeric
    assert _run([" ow_parse_gap_in_scope "])[1] == by_numeric


def test_render_json_is_code_rows_five_fields_with_schema_first() -> None:
    document = _json(["OW-A-017"])
    assert list(document) == ["schema", "numeric", "symbol", "meaning", "fix", "owner_doc"]
    row = load_register().by_numeric["OW-A-017"]
    assert (document["symbol"], document["meaning"]) == (row.symbol, row.meaning)


def test_a_row_the_register_leaves_empty_says_so() -> None:
    register = load_register()
    blank = next(row for row in register.rows if not row.fix)
    out = _run([blank.numeric])[1]
    assert "  fix: (not recorded in codes.toml)" in out.splitlines()


def test_every_register_row_resolves() -> None:
    for row in load_register().rows:
        assert _run([row.numeric])[0] == 0, row.numeric


def test_an_exit_status_resolves_to_its_row() -> None:
    """10:1520-1523 and 10:2769: *"`ow explain 8` resolves"*."""
    register = load_register()
    for row in register.exits:
        document = _json([str(row.code)])
        assert (document["exit"], document["slug"]) == (row.code, row.slug)
    code, out, _ = _run(["2"])
    assert code == 0
    assert out.splitlines()[0] == "exit 2  not-found"
    assert "  raised by: NotFoundError" in out.splitlines()


def test_an_unknown_code_is_2_naming_the_nearest_and_a_command_that_runs() -> None:
    """18:1205-1208 and D618: the fix names the nearest row, not a `--check` no parser takes."""
    code, out, err = _run(["OW-A-999"])
    assert (code, out) == (2, "")
    assert "OW-A-026" in err
    assert "Nearest:" in err
    fix = err.splitlines()[1]
    assert fix.startswith("  fix: ow explain OW-")
    assert "--check" not in err
    nearest = fix.split()[3]
    assert _run([nearest])[0] == 0, "the command the fix prints runs"


def test_an_unknown_exit_status_is_2() -> None:
    code, _, err = _run(["99"])
    assert code == 2
    assert "not in codes.toml's exit table" in err


def test_an_error_under_render_json_is_the_error_object_on_stdout() -> None:
    code, out, err = _run(["OW-A-999", "--render", "json"])
    assert (code, err) == (2, "")
    document = json.loads(out)
    assert (list(document), document["error"]["symbol"]) == (["schema", "error"], "OW_UNKNOWN_CODE")


@pytest.mark.parametrize(
    ("flags", "named"),
    [
        (["--quiet"], "--quiet"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
    ],
)
def test_a_parsed_flag_this_build_cannot_serve_is_refused_by_name(
    flags: list[str], named: str
) -> None:
    code, out, err = _run(["OW-A-013", *flags])
    assert (code, out) == (1, "")
    assert named in err


def test_a_parse_error_is_1_and_help_is_0() -> None:
    assert _run([])[0] == 1, "CODE is required"
    assert _run(["--help"])[0] == 0


def test_python_m_omniweave_dispatches_explain(capsys: pytest.CaptureFixture[str]) -> None:
    assert "explain" in launcher.DISPATCHED
    assert launcher.main(["explain", "OW-A-013"]) == 0
    assert capsys.readouterr().out.startswith("OW-A-013  OW_PARSE_GAP_IN_SCOPE")
