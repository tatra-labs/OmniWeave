"""Q-G8's static half tested as a program: `tools/gate_measured_on.py`. D831.

The row rule is `omniweave_conform.scoreboard.unmeasured()`'s and `test_conform_scoreboard.py`
holds it to `MeasuredOn`. This file holds the program to its docstring: an absent tree passes
and says so, an unmeasured row exits 1 with its file, position, metric, slice and reason, and a
file that is not a list of rows exits 2.

Loaded by file path under a private name and at module scope, as `test_gate_metric_rot.py` loads
its gate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_measured_on.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_measured_on", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()

MEASURED = {
    "weights": "n/a",
    "weights_revision": "n/a",
    "runtime": "pdfium",
    "runtime_version": "6721",
    "sampling": "{}",
    "prompt_version": "n/a",
    "hardware": "ow-bench-1",
    "corpus": "golden@2026.09",
    "corpus_digest": "sha256:" + "ab" * 32,
    "harness_version": "0.1.0",
}


def _row(metric: str, **measured: Any) -> dict[str, Any]:
    return {"metric": metric, "slice_key": "__macro__", "measured_on": {**MEASURED, **measured}}


def _results(tmp_path: Path, files: dict[str, Any]) -> list[str]:
    root = tmp_path / "results"
    for rel, rows in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((rows if isinstance(rows, str) else json.dumps(rows)).encode())
    return ["--results", str(root)]


def test_the_repository_passes() -> None:
    assert GATE.main([]) == GATE.EXIT_CLEAN


def test_an_absent_tree_passes_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert GATE.main(["--results", str(tmp_path / "none")]) == GATE.EXIT_CLEAN
    assert "Q-G8 ok  nothing published: no *.json under" in capsys.readouterr().out


def test_every_row_measured_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    argv = _results(tmp_path, {"parse/a.json": [_row("m"), _row("n")], "parse/b.json": [_row("m")]})
    assert GATE.main(argv) == GATE.EXIT_CLEAN
    assert capsys.readouterr().out.splitlines() == [
        "Q-G8  2 file(s), 3 row(s)",
        "Q-G8 ok  0 unmeasured row(s)",
    ]


def test_an_unmeasured_row_fails_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bare = {"metric": "doc_acc", "slice_key": "office/*", "measured_on": {}}
    files = {
        "parse/a.json": [_row("order_acc"), _row("field_acc", weights_revision="main")],
        "parse/b.json": [bare],
    }
    assert GATE.main(_results(tmp_path, files)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Q-G8  2 file(s), 3 row(s)"
    assert out[1].startswith(
        "  parse/a.json row 2 (field_acc@__macro__): MeasuredOn.weights_revision must be an exact"
    )
    assert out[2].startswith("  parse/b.json row 1 (doc_acc@office/*): measured_on has missing [")
    assert out[3:] == [
        "  fix: re-export with ow eval publish; a committed row is never edited by hand",
        "Q-G8 FAIL  2 unmeasured row(s)",
    ]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("[{", "parse/a.json: not JSON ("),
        ("{}", "parse/a.json: not a list of rows"),
        ("[1]", "parse/a.json: not a list of rows"),
    ],
)
def test_a_file_that_is_not_rows_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, match: str
) -> None:
    assert GATE.main(_results(tmp_path, {"parse/a.json": text})) == GATE.EXIT_NOT_RUN
    out = capsys.readouterr().out
    assert out.startswith("Q-G8 DID NOT RUN  ")
    assert match in out


def test_a_bad_argument_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--no-such-flag"]) == GATE.EXIT_NOT_RUN
    capsys.readouterr()


# ---------------------------------------------------------------------------
# --prose: V10-5's other half. D981.
# ---------------------------------------------------------------------------

REGISTER = """schema = "omniweave.published-numbers/1"

[[limit]]
path = "CHANGELOG.md"
text = "1 GiB"
source = "cards/office.toml"
key = "isolation.memory_mb"
value = 1024
reason = "the shipped ceiling"
"""


def _tree(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _prose(root: Path) -> list[str]:
    return ["--prose", "--root", str(root)]


def _perf_row(measured_on: dict[str, Any] | None = None) -> dict[str, Any]:
    """One results row, whose `measured_on` is complete unless a short one is passed."""
    return {
        "metric": "warm_p50_ms",
        "slice_key": "__macro__",
        "measured_on": dict(MEASURED if measured_on is None else measured_on),
    }


def test_the_committed_tree_backs_every_figure_it_publishes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real register against the real prose. This is the row V10-5 runs."""
    assert GATE.main(["--prose"]) == GATE.EXIT_CLEAN
    out = capsys.readouterr().out
    assert "V10-5 prose ok" in out
    assert "0 unbacked figure(s)" in out


def test_a_configured_limit_passes_when_its_key_still_holds_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(
        tmp_path,
        {
            "CHANGELOG.md": "- the office worker reaches its 1 GiB memory limit\n",
            "cards/office.toml": "[isolation]\nmemory_mb = 1024\n",
            "eval/published_numbers.toml": REGISTER,
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_CLEAN
    assert "1 figure(s) published" in capsys.readouterr().out


def test_a_limit_that_drifted_from_its_card_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole point of naming the key: prose and card cannot part company quietly."""
    _tree(
        tmp_path,
        {
            "CHANGELOG.md": "- the office worker reaches its 1 GiB memory limit\n",
            "cards/office.toml": "[isolation]\nmemory_mb = 2048\n",
            "eval/published_numbers.toml": REGISTER,
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out
    assert "isolation.memory_mb is 2048, and this row says 1024" in out


def test_a_figure_nothing_registers_fails_with_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """D978's defect, caught by a gate this time."""
    _tree(
        tmp_path,
        {
            "CHANGELOG.md": "- notes\n- warm query p50 is 95 ms on a developer machine\n",
            "eval/published_numbers.toml": 'schema = "omniweave.published-numbers/1"\n',
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out
    assert "CHANGELOG.md:2 publishes 'p50' with nothing behind it" in out
    assert "CHANGELOG.md:2 publishes '95 ms' with nothing behind it" in out
    assert "fix: state what backs it in eval/published_numbers.toml" in out


@pytest.mark.parametrize(
    "line",
    [
        "- 13 questions, below the minimum sample",
        "- release 1.0 ships fourteen wheels",
        "- `max_xml_nodes` closes a 1073741824-column sheet",
        "- reviewed on 2026-10-23",
    ],
)
def test_a_count_a_version_and_a_date_are_not_figures(tmp_path: Path, line: str) -> None:
    """A gate that flagged every integer is a gate a reviewer learns to skip."""
    _tree(
        tmp_path,
        {
            "CHANGELOG.md": line + "\n",
            "eval/published_numbers.toml": 'schema = "omniweave.published-numbers/1"\n',
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_CLEAN


def test_a_measured_figure_needs_a_complete_measured_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    register = (
        'schema = "omniweave.published-numbers/1"\n\n'
        "[[measured]]\n"
        'path = "CHANGELOG.md"\n'
        'text = "95 ms"\n'
        'results = "eval/results/perf.json"\n'
        "row = 1\n"
        'reason = "the nightly"\n'
    )
    short = dict(MEASURED)
    del short["weights"]

    _tree(
        tmp_path,
        {
            "CHANGELOG.md": "- warm query p50 is 95 ms\n",
            "eval/published_numbers.toml": register,
            "eval/results/perf.json": json.dumps([_perf_row(short)]),
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_FAIL
    out = capsys.readouterr().out
    assert "eval/results/perf.json row 1:" in out
    assert "p50" in out


def test_a_measured_figure_passes_on_a_complete_row(tmp_path: Path) -> None:
    register = (
        'schema = "omniweave.published-numbers/1"\n\n'
        "[[measured]]\n"
        'path = "CHANGELOG.md"\n'
        'text = "95 ms"\n'
        'results = "eval/results/perf.json"\n'
        "row = 1\n"
        'reason = "the nightly"\n'
        "\n[[measured]]\n"
        'path = "CHANGELOG.md"\n'
        'text = "p50"\n'
        'results = "eval/results/perf.json"\n'
        "row = 1\n"
        'reason = "the same row"\n'
    )
    _tree(
        tmp_path,
        {
            "CHANGELOG.md": "- warm query p50 is 95 ms\n",
            "eval/published_numbers.toml": register,
            "eval/results/perf.json": json.dumps([_perf_row()]),
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_CLEAN


def test_a_row_the_prose_does_not_carry_is_pruned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(
        tmp_path,
        {
            "CHANGELOG.md": "- nothing numeric here\n",
            "cards/office.toml": "[isolation]\nmemory_mb = 1024\n",
            "eval/published_numbers.toml": REGISTER,
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_FAIL
    assert "is published nowhere -- prune the row" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("register", "match"),
    [
        (None, "published_numbers.toml"),
        ('schema = "omniweave.published-numbers/2"\n', "schema is"),
        ("schema = [\n", "not TOML"),
        ('schema = "omniweave.published-numbers/1"\nlimit = [1]\n', "is not a table"),
    ],
)
def test_a_register_that_cannot_be_read_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], register: str | None, match: str
) -> None:
    """An absent register is not a pass: prose exists the moment someone writes a figure."""
    files = {"CHANGELOG.md": "- 1 GiB\n"}
    if register is not None:
        files["eval/published_numbers.toml"] = register
    _tree(tmp_path, files)
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_NOT_RUN
    out = capsys.readouterr().out
    assert out.startswith("V10-5 prose DID NOT RUN  ")
    assert match in out


def test_no_published_prose_at_all_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(tmp_path, {"eval/published_numbers.toml": 'schema = "omniweave.published-numbers/1"\n'})
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_NOT_RUN
    assert "is there to read" in capsys.readouterr().out


def test_docs_markdown_is_published_prose_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _tree(
        tmp_path,
        {
            "docs/AGENTS.md": "- the cache holds 100 MiB\n",
            "eval/published_numbers.toml": 'schema = "omniweave.published-numbers/1"\n',
        },
    )
    assert GATE.main(_prose(tmp_path)) == GATE.EXIT_FAIL
    assert "docs/AGENTS.md:1 publishes '100 MiB'" in capsys.readouterr().out
