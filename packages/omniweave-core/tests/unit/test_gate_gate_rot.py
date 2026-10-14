"""Q-G17 tested as a program: `tools/gate_gate_rot.py`'s rows, its clock and its exit codes. D830.

Two halves. The shipped registers pass at a fixed date and at the wall clock. The second is the
forcing function the gate exists for: the day a row falls due, this file goes red with the rest
of the build, exactly as `test_tombstones.py::test_the_gate_is_green_on_head` does. Every other
test builds its own tree under `tmp_path` and passes `--today`, so its result does not depend on
the day it runs.

The gate is loaded by file path under a private name, as `test_gate_budgets.py` loads its gate.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_gate_rot.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_gate_rot", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
NOW = "2026-10-14"
"""A fixed 'today' for every test but the wall-clock one."""

EVAL_GATES = """\
[[gate]]
metric = "span_exact_rate"
owner = "quality"
review_by = "2026-12-10"

[[gate]]
metric = "degradation_detection"
owner = "quality"
review_by = "2026-12-28"
"""
COUNTERS = """\
[gate]
owner = "team"
review_by = "2027-06-01"

[[counter]]
id = "blocks_written"
class = "exact"
"""
QUARANTINE = """\
[gate]
owner = "quality"
review_by = "2027-06-01"

[[quarantined]]
test_id = "tests/unit/test_x.py::test_y"
since = "2026-09-02"
expires = "2026-11-01"
owner = "quality"
reason = "one run in forty"
"""
"""13:282-296's shape (D836): a `[gate]` table, and rows whose clock is `expires`."""
TOOLS_GATES = """\
[[gate]]
id = "G1"
owner = "release"
review_by = "2026-12-03"

[[gate.clause]]
name = "a clause carries no date of its own"

[[job_assertion]]
name = "ci-ok.skips_declared"
owner = "release"
review_by = "2026-12-03"
"""


def _sidecar(provenance: str, extra: str = "") -> str:
    return f'[fixture]\nsha256 = "00"\nprovenance = "{provenance}"\n{extra}'


def _tree(root: Path, **override: str | None) -> Path:
    """A whole tree of registers and sidecars; `override` replaces or (with None) drops one."""
    files: dict[str, str | None] = {
        "eval/gates.toml": EVAL_GATES,
        "eval/counters.toml": COUNTERS,
        "eval/quarantine.toml": QUARANTINE,
        "tools/gates.toml": TOOLS_GATES,
        "fixtures/scan.pdf.meta.toml": _sidecar(
            "public_domain", 'owner = "licence"\nreview_by = "2027-09-01"\n'
        ),
        "packages/omniweave-office/fixtures/memo.doc.meta.toml": _sidecar("generated"),
    }
    files.update(
        {key.replace("__", "/").replace("_toml", ".toml"): v for key, v in override.items()}
    )
    for rel, text in files.items():
        if text is None:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    return root


def _run(root: Path, capsys: pytest.CaptureFixture[str], today: str = NOW) -> tuple[int, str]:
    code = GATE.main(["--root", str(root), "--today", today])
    return code, capsys.readouterr().out


# --- the shipped registers -------------------------------------------------------------------


def test_the_repository_passes_at_a_fixed_date(capsys: pytest.CaptureFixture[str]) -> None:
    code = GATE.main(["--today", NOW])
    out = capsys.readouterr().out
    assert code == GATE.EXIT_CLEAN, out
    assert "  eval/quarantine.toml   absent\n" in out


def test_the_repository_passes_today() -> None:
    """At the wall clock. This goes red the day a shipped row falls due, by design."""
    assert GATE.main([]) == GATE.EXIT_CLEAN


# --- rulings 1-3: the rows -------------------------------------------------------------------


def test_every_register_and_external_sidecar_is_a_row(tmp_path: Path) -> None:
    scan = GATE.rows(_tree(tmp_path))
    assert [(row.register, row.label) for row in scan.rows] == [
        ("eval/gates.toml", "gate span_exact_rate"),
        ("eval/gates.toml", "gate degradation_detection"),
        ("eval/counters.toml", "[gate]"),
        ("eval/quarantine.toml", "[gate]"),
        ("eval/quarantine.toml", "quarantined tests/unit/test_x.py::test_y"),
        ("tools/gates.toml", "gate G1"),
        ("tools/gates.toml", "job_assertion ci-ok.skips_declared"),
        ("fixtures/scan.pdf.meta.toml", "fixture"),
    ]
    assert scan.absent == ()
    assert scan.sidecars == 2


def test_an_absent_register_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _run(_tree(tmp_path, eval__quarantine_toml=None, tools__gates_toml=None), capsys)
    assert code == GATE.EXIT_CLEAN
    assert "  eval/quarantine.toml   absent\n" in out
    assert "  tools/gates.toml       absent\n" in out


def test_a_row_with_no_label_is_numbered(tmp_path: Path) -> None:
    root = _tree(tmp_path, eval__gates_toml='[[gate]]\nowner = "q"\nreview_by = "2027-01-01"\n')
    assert GATE.rows(root).rows[0].label == "gate #1"


def test_an_external_sidecar_needs_a_clock_and_a_generated_one_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)
    (root / "fixtures" / "photo.png.meta.toml").write_bytes(_sidecar("cc_by").encode())
    (root / "fixtures" / "own.md.meta.toml").write_bytes(_sidecar("authored").encode())
    code, out = _run(root, capsys)
    assert code == GATE.EXIT_FAIL
    assert "  fixtures/photo.png.meta.toml  fixture: no owner" in out
    assert "  fixtures/photo.png.meta.toml  fixture: review_by None is not a YYYY-MM-DD" in out
    assert "own.md" not in out
    assert "  fixture sidecars       4 read, 2 with an external provenance" in out


def test_a_written_index_does_not_stop_the_sidecars_being_read(tmp_path: Path) -> None:
    """Ruling 3: the index is derived, so its rows are still read from the sidecars."""
    root = _tree(tmp_path)
    (root / "fixtures" / "index.toml").write_bytes(b"[[fixture]]\n")
    assert [row.label for row in GATE.rows(root).rows].count("fixture") == 1


# --- rulings 4 and 5: the clock --------------------------------------------------------------


def test_a_row_fails_on_its_date_and_not_the_day_before(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)
    assert _run(root, capsys, "2026-10-31")[0] == GATE.EXIT_CLEAN
    code, out = _run(root, capsys, "2026-11-01")
    assert code == GATE.EXIT_FAIL
    assert out.splitlines()[-2:] == [
        "  eval/quarantine.toml  quarantined tests/unit/test_x.py::test_y: expires 2026-11-01 "
        "is not after 2026-11-01; return the test to its tier, or delete the row with the "
        "reason (13:296)",
        "Q-G17 FAIL  1 finding(s)",
    ]


def test_the_report_names_each_registers_next_due_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(_tree(tmp_path), capsys)
    assert code == GATE.EXIT_CLEAN
    assert out.splitlines() == [
        f"Q-G17  as of {NOW}",
        "  eval/gates.toml        2 row(s), next due 2026-12-10 (57 days)",
        "  eval/counters.toml     1 row(s), next due 2027-06-01 (230 days)",
        "  eval/quarantine.toml   2 row(s), next due 2026-11-01 (18 days)",
        "  tools/gates.toml       2 row(s), next due 2026-12-03 (50 days)",
        "  fixture sidecars       2 read, 1 with an external provenance, next due 2027-09-01 "
        "(322 days)",
        "Q-G17 ok  0 finding(s)",
    ]


@pytest.mark.parametrize(
    ("row", "finding"),
    [
        ('owner = "q"\n', "review_by None is not a YYYY-MM-DD date"),
        ('owner = "q"\nreview_by = "2027-1-1"\n', "review_by '2027-1-1' is not"),
        ('owner = "q"\nreview_by = "20270101"\n', "review_by '20270101' is not"),
        ('owner = "q"\nreview_by = "2027-02-30"\n', "review_by '2027-02-30' is not"),
        ('owner = "q"\nreview_by = 20270101\n', "review_by 20270101 is not"),
        ('review_by = "2027-01-01"\n', "no owner; name the role that reviews it"),
        ('owner = "  "\nreview_by = "2027-01-01"\n', "no owner"),
        ('owner = 7\nreview_by = "2027-01-01"\n', "no owner"),
    ],
)
def test_a_row_without_an_owner_or_a_readable_date_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], row: str, finding: str
) -> None:
    root = _tree(tmp_path, eval__gates_toml=f'[[gate]]\nmetric = "m"\n{row}')
    code, out = _run(root, capsys)
    assert code == GATE.EXIT_FAIL
    assert f"  eval/gates.toml  gate m: {finding}" in out


def test_a_toml_date_is_a_date(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(tmp_path, eval__gates_toml='[[gate]]\nowner = "q"\nreview_by = 2027-01-01\n')
    assert _run(root, capsys)[0] == GATE.EXIT_CLEAN


def test_a_toml_datetime_is_not_a_date(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _tree(
        tmp_path, eval__gates_toml='[[gate]]\nowner = "q"\nreview_by = 2027-01-01T00:00:00\n'
    )
    assert _run(root, capsys)[0] == GATE.EXIT_FAIL


def test_counters_without_their_gate_table_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(_tree(tmp_path, eval__counters_toml='[[counter]]\nid = "x"\n'), capsys)
    assert code == GATE.EXIT_FAIL
    assert "  eval/counters.toml  [gate]: no owner" in out


# --- did not run -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"eval__gates_toml": "[[gate]\n"}, "Q-G17 DID NOT RUN"),
        ({"eval__gates_toml": 'gate = "x"\n'}, "eval/gates.toml: `gate` is not an array of tables"),
        ({"tools__gates_toml": "job_assertion = 1\n"}, "`job_assertion` is not an array"),
        (
            {"eval__counters_toml": '[[gate]]\nowner = "q"\n'},
            "counters.toml: `gate` is not a table",
        ),
    ],
)
def test_a_register_that_cannot_be_read_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], override: dict[str, str], match: str
) -> None:
    code, out = _run(_tree(tmp_path, **override), capsys)
    assert code == GATE.EXIT_NOT_RUN
    assert match in out


def test_an_unreadable_sidecar_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _tree(tmp_path)
    (root / "fixtures" / "bad.meta.toml").write_bytes(b"[fixture\n")
    assert _run(root, capsys)[0] == GATE.EXIT_NOT_RUN


@pytest.mark.parametrize("argv", [["--today", "2026-13-01"], ["--no-such-flag"]])
def test_a_bad_argument_did_not_run(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(argv) == GATE.EXIT_NOT_RUN
    capsys.readouterr()


def test_the_wall_clock_is_utc() -> None:
    assert GATE.today() == dt.datetime.now(tz=dt.UTC).date()
