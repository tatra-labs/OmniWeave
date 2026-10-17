"""`ow eval run`: the verb, its entry point, its refusals, and what `release-check` reads. D868.

The verb runs in-process through `omniweave.surface.eval.main`, from the repository root, because
the register's `card` and `fixtures` paths are relative to the working directory. The `.oweval`
goes under `tmp_path`, named by an absolute `--oweval`. The measuring happens in
`omniweave-conform`, across the `[omniweave.eval] run` entry point; `test_conform_eval_run.py`
holds each of its rulings, and this file what the verb prints, refuses and exits.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from omniweave.surface import eval as verb

REPO = Path(__file__).resolve().parents[4]
PDFIUM = "parse.pdf.pdfium"


def _eval(*argv: str, cwd: Path = REPO) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["eval", *argv], cwd=cwd, env={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_run_writes_the_store_and_prints_a_line_per_subject(tmp_path: Path) -> None:
    store = tmp_path / "new.oweval"
    code, out, err = _eval("run", "--subject", PDFIUM, "--oweval", str(store))
    assert (code, err) == (0, "")
    first, last = out.splitlines()
    assert first.split()[:4] == [PDFIUM, "pdf/born_digital", "span_exact_rate", "1.0000"]
    assert first.endswith("parsed, 3 refused")
    assert last == f"ow eval run --suite parse: 1 run(s) written to {store}"
    assert store.is_file()


def test_render_json_prints_one_object(tmp_path: Path) -> None:
    store = tmp_path / "x.oweval"
    code, out, _ = _eval(
        "run", "--suite", "parse", "--subject", PDFIUM, "--oweval", str(store), "--render", "json"
    )
    assert code == 0
    done = json.loads(out)
    assert (done["suite"], done["oweval"]) == ("parse", str(store))
    [row] = done["runs"]
    assert (row["subject"], row["slice"], row["metric"], row["value"]) == (
        PDFIUM,
        "pdf/born_digital",
        "span_exact_rate",
        1.0,
    )
    assert row["corpus"] == "packages/omniweave-pdf/fixtures"
    assert len(row["run_id"]) == 32


def test_release_check_then_wants_only_the_absence_gate(tmp_path: Path) -> None:
    store = tmp_path / "x.oweval"
    assert _eval("run", "--oweval", str(store))[0] == 0
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert out.splitlines() == [
        "  unmeasured  hard gate degradation_detection@*: no absence run measured it",
        "              fix: run the gate's suite: ow eval run --suite absence",
        "ow eval release-check: refused, 1 finding(s); 2 latest run(s), 0 superseded,"
        " 2 hard gate(s)",
    ]


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--suite", "absence"], "--suite absence is not measured in this build"),
        (["--suite", "bogus"], "--suite 'bogus' is not one of parse, extract"),
        (["--witness", "me"], "--witness 'me' is not one of ci, self, third_party"),
        (["--cassette", "on"], "--cassette 'on' is not one of off, allow, required"),
        (["--corpus", "golden@2026.09"], "--corpus is parsed and not served by ow eval run"),
        (["--validate-judge"], "--validate-judge is parsed and not served by ow eval run"),
        (["--emit", "x.json"], "--emit is parsed and not served by ow eval run"),
        (["--render", "jsonl"], "--render jsonl is parsed and not served by ow eval run"),
    ],
)
def test_what_is_not_served_is_refused_by_name_before_anything_runs(
    tmp_path: Path, argv: list[str], says: str
) -> None:
    store = tmp_path / "x.oweval"
    code, _, err = _eval("run", *argv, "--oweval", str(store))
    assert code == 1
    assert says in err
    assert not store.exists()


def test_a_missing_register_exits_2(tmp_path: Path) -> None:
    code, _, err = _eval("run", "--oweval", "x.oweval", cwd=tmp_path)
    assert code == 2
    assert "no metric register at" in err
    assert not (tmp_path / "x.oweval").exists()


def test_a_subject_the_register_lacks_is_a_refusal_exit_1(tmp_path: Path) -> None:
    code, _, err = _eval("run", "--subject", "parse.nothing", "--oweval", str(tmp_path / "x"))
    assert code == 1
    assert "no [[subject]] in the metric register is driver 'parse.nothing'" in err
