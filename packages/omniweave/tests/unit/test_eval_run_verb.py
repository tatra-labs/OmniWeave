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
from omniweave.surface import admit as admission
from omniweave.surface import eval as verb
from omniweave_conform import absence as absence_harness
from omniweave_conform import retrieval as cite_harness
from omniweave_conform import roundtrip as r2_harness
from omniweave_conform.damage import Assessment, Clause

REPO = Path(__file__).resolve().parents[4]
PDFIUM = "parse.pdf.pdfium"


def _fake_suite(monkeypatch: pytest.MonkeyPatch, *oks: bool) -> list[object]:
    """The absence harness, faked: a unit test spawns no `ow` (Q-G25). Returns its `admit`s."""
    handed: list[object] = []

    def fake(_chosen: object, **kw: object) -> absence_harness.Suite:
        handed.append(kw["admit"])
        return absence_harness.Suite(
            assessments=tuple(
                Assessment(f"inj{index}", "corpus/doc.pdf", (Clause("degraded", ok, "why"),))
                for index, ok in enumerate(oks)
            ),
            documents={"corpus/doc.pdf": b"%PDF-"},
        )

    monkeypatch.setattr(absence_harness, "run_suite", fake)
    return handed


def _fake_cites(monkeypatch: pytest.MonkeyPatch, *unsound: str) -> None:
    """The retrieve harness, faked: two Answers of two cites, the first's `unsound` failing."""
    checked = cite_harness.Checked(
        asked=(
            cite_harness.Asked("t0", ("d1#1", unsound[0] if unsound else "d1#2"), unsound),
            cite_harness.Asked("t1", ("d1#3", "d1#4"), ()),
        ),
        documents={"data_room/a.xlsx": b"x"},
        skipped=6,
    )
    monkeypatch.setattr(cite_harness, "run_suite", lambda *_a, **_k: checked)


def _fake_roundtrip(monkeypatch: pytest.MonkeyPatch, *, survive: bool = True) -> None:
    """The roundtrip harness, faked: each target one addressed element, surviving or not."""

    def judge(target: r2_harness.Target) -> r2_harness.Judged:
        return r2_harness.Judged(
            target=target,
            driver=f"compile.{target.target}.native",
            version="0.1.0",
            gate="manual-required",
            elements=(
                r2_harness.Element("u01/e1", "heading", survive, "" if survive else "kind: it"),
            ),
            unknown=None,
            il_units=(),
            fingerprint="f" * 64,
        )

    monkeypatch.setattr(r2_harness, "judge", judge)


def _eval(*argv: str, cwd: Path = REPO) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["eval", *argv], cwd=cwd, env={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_run_writes_the_store_and_prints_a_line_per_subject(tmp_path: Path) -> None:
    store = tmp_path / "new.oweval"
    code, out, err = _eval("run", "--suite", "parse", "--subject", PDFIUM, "--oweval", str(store))
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
    assert (done["suites"], done["oweval"]) == (["parse"], str(store))
    [row] = done["runs"]
    assert (row["suite"], row["subject"], row["slice"], row["metric"], row["value"]) == (
        "parse",
        PDFIUM,
        "pdf/born_digital",
        "span_exact_rate",
        1.0,
    )
    assert row["corpus"] == "packages/omniweave-pdf/fixtures"
    assert len(row["run_id"]) == 32


def test_release_check_after_parse_alone_wants_the_other_two_gates(tmp_path: Path) -> None:
    store = tmp_path / "x.oweval"
    assert _eval("run", "--suite", "parse", "--oweval", str(store))[0] == 0
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert out.splitlines() == [
        "  unmeasured  hard gate degradation_detection@*: no absence run measured it",
        "              fix: run the gate's suite: ow eval run --suite absence",
        "  unmeasured  hard gate citability_violations@*: no retrieve run measured it",
        "              fix: run the gate's suite: ow eval run --suite retrieve",
        "ow eval release-check: refused, 2 finding(s); 2 latest run(s), 0 superseded,"
        " 3 hard gate(s)",
    ]


def test_every_built_suite_by_default_and_release_check_then_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handed = _fake_suite(monkeypatch, True, True)
    _fake_cites(monkeypatch)
    _fake_roundtrip(monkeypatch)
    store = tmp_path / "x.oweval"
    code, out, _ = _eval("run", "--oweval", str(store))
    assert code == 0
    lines = out.splitlines()
    assert lines[2].split() == [
        "omniweave",
        "deterministic_half",
        "degradation_detection",
        "1.0000",
        "over",
        "2;",
        "2",
        "of",
        "2",
        "pair(s)",
        "passed",
    ]
    assert lines[3].split()[:5] == [
        "omniweave",
        "born_digital",
        "citability_violations",
        "0",
        "over",
    ]
    assert lines[3].endswith("2 answer(s); 4 of 4 cite(s) resolve")
    assert lines[4].endswith("r2 1.0000 over 1; 1 of 1 element(s) survive")
    assert lines[4].split()[:2] == ["compile.docx.native", "docx"]
    assert lines[5].split()[:2] == ["compile.pptx.native", "pptx"]
    assert lines[6].startswith(
        "ow eval run --suite parse,absence,retrieve,roundtrip: 6 run(s) written to "
    )
    assert handed == [admission.admit]
    assert _eval("release-check", "--oweval", str(store)) == (
        0,
        "ow eval release-check: ok; 6 latest run(s), 0 superseded, 3 hard gate(s)\n",
        "",
    )


def test_a_failed_element_is_printed_and_does_not_refuse_a_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D871 ruling 16: 13 names no metric for R2, so a failed verdict is no gate."""
    _fake_roundtrip(monkeypatch, survive=False)
    store = tmp_path / "x.oweval"
    code, out, _ = _eval("run", "--suite", "roundtrip", "--oweval", str(store))
    assert code == 0
    assert out.splitlines()[0].endswith(
        "r2 0.0000 over 1; 0 of 1 element(s) survive; failed: u01/e1 (kind: it)"
    )
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert "hard gate span_exact_rate@*: no parse run measured it" in out
    assert "u01/e1" not in out


def test_an_unresolved_cite_is_printed_and_release_check_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_cites(monkeypatch, "d1#9")
    store = tmp_path / "x.oweval"
    code, out, _ = _eval("run", "--suite", "retrieve", "--oweval", str(store))
    assert code == 0
    assert out.splitlines()[0].endswith(
        "citability_violations 1 over 2 answer(s); 3 of 4 cite(s) resolve; unresolved: t0: d1#9"
    )
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert "1.0 is not the hard budget 0.0" in out


def test_a_failed_pair_is_printed_and_release_check_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_suite(monkeypatch, True, False)
    store = tmp_path / "x.oweval"
    code, out, _ = _eval(
        "run", "--suite", "absence", "--deterministic-half", "--oweval", str(store)
    )
    assert code == 0
    assert out.splitlines()[0].endswith(
        "0.5000 over 2; 1 of 2 pair(s) passed; failed: inj1 x corpus/doc.pdf"
    )
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert "0.5 is not the hard budget 1.0" in out


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (["--suite", "parse", "--deterministic-half"], "--deterministic-half names the half"),
        (["--deterministic-half"], "--deterministic-half names the half"),
        (["--suite", "absence", "--subject", PDFIUM], "--subject names a parse driver"),
        (["--subject", PDFIUM], "--subject names a parse driver"),
        (["--suite", "retrieve", "--subject", PDFIUM], "the retrieve suite's subjects"),
        (["--suite", "roundtrip", "--subject", PDFIUM], "the roundtrip suite's subjects"),
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
    code, _, err = _eval(
        "run", "--suite", "parse", "--subject", "parse.nothing", "--oweval", str(tmp_path / "x")
    )
    assert code == 1
    assert "no [[subject]] in the metric register is driver 'parse.nothing'" in err


@pytest.mark.parametrize("suite", ["extract", "portability", "perf"])
def test_an_unmeasurable_suite_is_one_unknown_run_and_release_check_refuses_it(
    tmp_path: Path, suite: str
) -> None:
    """D872: 16:942, *"every suite must be able to report `unknown`"*."""
    store = tmp_path / "x.oweval"
    code, out, _ = _eval("run", "--suite", suite, "--oweval", str(store))
    assert code == 0
    first, last = out.splitlines()
    assert first.split()[:4] == ["omniweave", "none", suite, "unknown:"]
    assert last == f"ow eval run --suite {suite}: 1 run(s) written to {store}"
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert f"  run         {suite}/omniweave run " in out
    assert f"fix: fix what stopped the run, then ow eval run --suite {suite}\n" in out
