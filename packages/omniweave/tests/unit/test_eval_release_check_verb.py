"""`ow eval release-check`: the verb, its entry point, and each exit its docstring rules. D840.

The verb runs in-process through `omniweave.surface.eval.main`, against an `.oweval` written under
`tmp_path` by `omniweave_core.store.oweval` and a copy of the repository's `eval/gates.toml`. The
judging happens in `omniweave-conform`, across the `[omniweave.eval] release-check` entry point
the workspace installs; `test_conform_release.py` holds each ruling, and this file what the verb
prints and exits.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import omniweave.__main__ as launcher
import pytest
from omniweave.surface import dispatch
from omniweave.surface import eval as verb
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.store.oweval import Batch, Corpus, Metric, Run, open_oweval
from omniweave_core.store.oweval import write as store

REPO = Path(__file__).resolve().parents[4]

_MEASURED = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="pdfium",
    runtime_version="6721",
    sampling="{}",
    prompt_version="n/a",
    hardware="ow-bench-1",
    corpus="golden@2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    harness_version="0.1.0",
)
_CORPUS = Corpus(
    corpus_id="golden",
    version="2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    tier="A",
    n_docs=1,
    n_assertions=1,
    n_checked=1,
    document_redistributable=True,
    assertions_redistributable=True,
    publishable=True,
)
_PARSE = Run(
    run_id="r1",
    suite="parse",
    corpus_id="golden",
    corpus_version="2026.09",
    corpus_digest="sha256:" + "ab" * 32,
    subject="parse.pdf.pdfium",
    subject_version="0.1.0",
    producer_id=None,
    measured_on=_MEASURED,
    timing_basis="in_process",
    witness="ci",
    cassette="required",
    policy_digest=None,
    pricebook_digest=None,
    harness_version="0.1.0",
    code_fingerprint="c0ffee",
    hardware="ow-bench-1",
    started_ns=1,
    ended_ns=2,
    status="ok",
    not_measured=("handwriting",),
    confounders=("one embedder",),
)
_ABSENCE = replace(_PARSE, run_id="r2", suite="absence", subject="omniweave.absence")
_SPAN = Metric(
    run_id="r1",
    metric="span_exact_rate",
    value=1.0,
    n=40,
    ci_lo=0.91,
    ci_hi=1.0,
    method="exact",
    truth_kind="rendered",
    state="ok",
)
_DETECT = replace(_SPAN, run_id="r2", metric="degradation_detection")
_OFF = "span_exact_rate@__macro__ in parse/parse.pdf.pdfium run r1"
_GATE_FIX = "fix the regression; a hard budget moves only by a reviewed eval/gates.toml diff"


def _eval_dir(root: Path, *metrics: Metric, runs: tuple[Run, ...] = (_PARSE, _ABSENCE)) -> None:
    (root / "eval").mkdir(parents=True, exist_ok=True)
    (root / "eval" / "gates.toml").write_bytes((REPO / "eval" / "gates.toml").read_bytes())
    connection = open_oweval(root / "eval" / "omniweave.oweval")
    try:
        store(
            connection,
            Batch(corpora=(_CORPUS,), runs=runs, metrics=metrics or (_SPAN, _DETECT)),
        )
    finally:
        connection.close()


def _run(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["eval", "release-check", *argv], cwd=cwd, env={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


# --- the verdict -------------------------------------------------------------------------------


def test_a_clean_store_exits_0_with_one_line(tmp_path: Path) -> None:
    _eval_dir(tmp_path)
    assert _run(tmp_path) == (
        0,
        "ow eval release-check: ok; 2 latest run(s), 0 superseded, 2 hard gate(s)\n",
        "",
    )


def test_a_finding_exits_1_printing_it_and_its_fix(tmp_path: Path) -> None:
    _eval_dir(tmp_path, replace(_SPAN, value=0.98), _DETECT)
    code, out, err = _run(tmp_path)
    assert (code, err) == (1, "")
    assert out.splitlines() == [
        f"  gate        {_OFF}: 0.98 is not the hard budget 1.0",
        f"              fix: {_GATE_FIX}",
        "ow eval release-check: refused, 1 finding(s); 2 latest run(s), 0 superseded,"
        " 2 hard gate(s)",
    ]


def test_strict_refuses_the_suites_nothing_ran(tmp_path: Path) -> None:
    _eval_dir(tmp_path)
    code, out, _ = _run(tmp_path, "--strict")
    assert code == 1
    lines = out.splitlines()
    assert [line.split()[1] for line in lines[:-1:2]] == [
        "extract:",
        "retrieve:",
        "roundtrip:",
        "portability:",
        "perf:",
    ]
    assert lines[-1].endswith("finding(s); 2 latest run(s), 0 superseded, 2 hard gate(s), --strict")


def test_the_paths_are_options_relative_to_the_working_directory(tmp_path: Path) -> None:
    _eval_dir(tmp_path, runs=(_PARSE, _ABSENCE, replace(_PARSE, run_id="r0", started_ns=0)))
    (tmp_path / "eval" / "omniweave.oweval").rename(tmp_path / "nightly.oweval")
    (tmp_path / "eval" / "gates.toml").rename(tmp_path / "metrics.toml")
    code, out, _ = _run(tmp_path, "--oweval", "nightly.oweval", "--gates", "metrics.toml")
    assert (code, out) == (
        0,
        "ow eval release-check: ok; 2 latest run(s), 1 superseded, 2 hard gate(s)\n",
    )


def test_render_json_prints_one_object(tmp_path: Path) -> None:
    _eval_dir(tmp_path, replace(_SPAN, value=0.5), _DETECT)
    code, out, _ = _run(tmp_path, "--render", "json")
    assert code == 1
    assert json.loads(out) == {
        "ok": False,
        "strict": False,
        "runs": 2,
        "superseded": 0,
        "gates": 2,
        "findings": [
            {
                "kind": "gate",
                "names": _OFF,
                "why": "0.5 is not the hard budget 1.0",
                "fix": _GATE_FIX,
            }
        ],
    }
    code, out, _ = _run(tmp_path, "--render", "json", "--strict")
    assert json.loads(out)["strict"] is True


# --- the refusals ------------------------------------------------------------------------------


def test_a_missing_oweval_is_not_found_and_never_created(tmp_path: Path) -> None:
    code, out, err = _run(tmp_path)
    assert (code, out) == (2, "")
    assert "no .oweval at" in err
    assert "fix: run the eval suites to write one, or pass --oweval PATH" in err
    assert not (tmp_path / "eval").exists()


def test_a_missing_register_is_not_found(tmp_path: Path) -> None:
    _eval_dir(tmp_path)
    (tmp_path / "eval" / "gates.toml").unlink()
    code, out, err = _run(tmp_path)
    assert (code, out) == (2, "")
    assert "no metric register at" in err
    assert "fix: pass --gates PATH naming the eval/gates.toml register" in err


def test_a_register_the_check_cannot_read_exits_1_with_its_quality_code(tmp_path: Path) -> None:
    _eval_dir(tmp_path)
    (tmp_path / "eval" / "gates.toml").write_bytes(
        b'[[gate]]\nmetric = "m"\nsuite = "parse"\nslice = "*"\nkind = "hard"\n'
        b'class = "blocking"\nbudget = "one"\n'
    )
    code, out, err = _run(tmp_path)
    assert (code, out) == (1, "")
    assert "OW_QUALITY" in err
    assert "hard [[gate]] #1 has no numeric budget" in err


@pytest.mark.parametrize("mode", ["jsonl", "rows"])
def test_a_render_mode_with_no_writer_is_refused_by_name(tmp_path: Path, mode: str) -> None:
    _eval_dir(tmp_path)
    code, _, err = _run(tmp_path, "--render", mode)
    assert code == 1
    assert f"--render {mode} is parsed and not served by ow eval release-check" in err


def test_without_omniweave_conform_the_verb_is_ow_a_027(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _eval_dir(tmp_path)
    monkeypatch.setattr(dispatch, "_installed", lambda *_: [])
    code, _, err = _run(tmp_path)
    assert code == 64
    assert err.startswith("ow: OW-A-027: ")
    assert "ow eval release-check needs omniweave-conform, which is not installed" in err


_GOOD: dict[str, object] = {"ok": True, "runs": 0, "superseded": 0, "gates": 0, "findings": []}


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {**_GOOD, "ok": "yes"},
        {**_GOOD, "runs": "0"},
        {**_GOOD, "superseded": None},
        {**_GOOD, "gates": 1.0},
        {**_GOOD, "findings": ()},
        {**_GOOD, "findings": ["gate"]},
        {**_GOOD, "findings": [{"kind": "gate", "names": "n", "why": "w"}]},
        {**_GOOD, "findings": [{"kind": "gate", "names": "n", "why": "w", "fix": 1}]},
    ],
)
def test_a_malformed_entry_point_reply_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: dict[str, object]
) -> None:
    _eval_dir(tmp_path)
    monkeypatch.setattr(verb, "eval_entry", lambda _name: lambda **_: reply)
    code, _, err = _run(tmp_path)
    assert code == 70
    assert "release-check entry point returned no ok, runs, superseded, gates and findings" in err


def test_a_well_formed_reply_is_read_field_by_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _eval_dir(tmp_path)
    finding = {"kind": "perf", "names": "B in run r", "why": "status stale", "fix": "rerun"}
    reply: dict[str, Any] = {"ok": False, "runs": 3, "superseded": 4, "gates": 5}
    monkeypatch.setattr(
        verb, "eval_entry", lambda _name: lambda **_: {**reply, "findings": [finding]}
    )
    assert _run(tmp_path) == (
        1,
        "  perf        B in run r: status stale\n"
        "              fix: rerun\n"
        "ow eval release-check: refused, 1 finding(s); 3 latest run(s), 4 superseded,"
        " 5 hard gate(s)\n",
        "",
    )


def test_the_entry_point_is_handed_absolute_paths_and_the_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _eval_dir(tmp_path)
    seen: dict[str, object] = {}

    def entry(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return _GOOD

    monkeypatch.setattr(verb, "eval_entry", lambda name: entry if name == "release-check" else None)
    assert _run(tmp_path, "--strict")[0] == 0
    assert seen == {
        "oweval": str(tmp_path / "eval" / "omniweave.oweval"),
        "gates": str(tmp_path / "eval" / "gates.toml"),
        "strict": True,
    }


def test_the_launcher_routes_release_check_to_the_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert launcher.main(["eval", "release-check", "--oweval", "nowhere.oweval"]) == 2
    assert "no .oweval at" in capsys.readouterr().err


def test_the_workspace_installs_the_release_check_entry_point() -> None:
    from omniweave_conform.entry import release_check  # noqa: PLC0415

    assert dispatch.eval_entry("release-check") is release_check
