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
import re
from pathlib import Path

import pytest
from omniweave.surface import admit as admission
from omniweave.surface import eval as verb
from omniweave_conform import absence as absence_harness
from omniweave_conform import portability as cell_harness
from omniweave_conform import removal as removal_harness
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
    monkeypatch.setattr(removal_harness, "run_suite", lambda *_a, **_k: _removal())
    return handed


def _removal() -> removal_harness.Removal:
    """The removal half, faked at the repository's counts (D933): 13 answerable questions and 17
    genuinely absent, none answered `absent`."""
    return removal_harness.Removal(
        asked=tuple(
            removal_harness.Asked(removal_harness.Question(f"t{i}", "c", "q?", population), state)
            for population, n in ((removal_harness.ANSWERABLE, 13), (removal_harness.REMOVED, 17))
            for i, state in enumerate(["low_confidence"] * n)
        ),
        shared=(),
        documents={"c/a.docx": b"one", "c-removed/a.docx": b"two"},
    )


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


def _fake_cells(monkeypatch: pytest.MonkeyPatch) -> None:
    """The portability harness, faked: one identical shape, and each target's frozen parts."""
    frozen = cell_harness.read_parts(REPO)
    monkeypatch.setattr(cell_harness, "shapes", lambda _root: ({"a.shape": "1"}, {"a.shape": "1"}))
    monkeypatch.setattr(
        cell_harness,
        "parts",
        lambda target: (
            f"compile.{target.target}.native",
            "0.1.0",
            "f" * 64,
            frozen[target.target],
        ),
    )


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


LABELS_FIX = (
    '              fix: verify its labels: write checked = "verified" on each .assertions.toml '
    "row you confirm against its document, 30 or more a slice, then ow eval run --suite parse"
)
DRAFTED = [
    "  metric      order_acc@__macro__ in parse/parse.office.anydoc run <id>: UNKNOWN; 15 "
    "unverified assertion(s) ran and were not scored (13:1022)",
    LABELS_FIX,
    "  metric      order_acc@__macro__ in parse/parse.pdf.pdfium run <id>: UNKNOWN; 60 "
    "unverified assertion(s) ran and were not scored (13:1022)",
    LABELS_FIX,
    "  metric      table_rel_acc@__macro__ in parse/parse.office.anydoc run <id>: UNKNOWN; 10 "
    "unverified assertion(s) ran and were not scored (13:1022)",
    LABELS_FIX,
]
"""D913: the drafted labels' three rates, each refused and naming the verification as its fix."""
UNDER_MIN = [
    "  metric      false_confident_zero@removal in absence/omniweave run <id>: UNKNOWN; 0 of 13 "
    "answerable question(s) answered absent, under min_slice_n = 30 (13:1088)",
    "              fix: measure 30 or more a slice: add questions to the suite's corpus, then ow "
    "eval run --suite absence",
]
"""D933: the removal half's ceiling over 13 answerable questions, naming more as its fix."""


def _masked(out: str) -> list[str]:
    return [re.sub(r" run [0-9a-f]{32}", " run <id>", line) for line in out.splitlines()]


def test_release_check_after_parse_alone_wants_the_other_four_gates(tmp_path: Path) -> None:
    store = tmp_path / "x.oweval"
    assert _eval("run", "--suite", "parse", "--oweval", str(store))[0] == 0
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert _masked(out) == [
        *DRAFTED,
        "  unmeasured  hard gate degradation_detection@*: no absence run measured it",
        "              fix: run the gate's suite: ow eval run --suite absence",
        "  unmeasured  hard gate citability_violations@*: no retrieve run measured it",
        "              fix: run the gate's suite: ow eval run --suite retrieve",
        "  unmeasured  hard gate address_survival@*: no roundtrip run measured it",
        "              fix: run the gate's suite: ow eval run --suite roundtrip",
        "  unmeasured  hard gate cell_identity@*: no portability run measured it",
        "              fix: run the gate's suite: ow eval run --suite portability",
        "ow eval release-check: refused, 7 finding(s); 2 latest run(s), 0 superseded,"
        " 5 hard gate(s)",
    ]


def test_every_built_suite_by_default_and_release_check_refuses_only_the_drafted_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handed = _fake_suite(monkeypatch, True, True)
    _fake_cites(monkeypatch)
    _fake_roundtrip(monkeypatch)
    _fake_cells(monkeypatch)
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
    assert lines[3].split() == [
        "omniweave",
        "removal",
        "false_confident_zero",
        "unknown",
        "over",
        "13;",
        "0",
        "of",
        "13",
        "answerable",
        "question(s)",
        "answered",
        "absent",
    ]
    assert lines[4].split()[:5] == [
        "omniweave",
        "born_digital",
        "citability_violations",
        "0",
        "over",
    ]
    assert lines[4].endswith("2 answer(s); 4 of 4 cite(s) resolve")
    assert lines[5].endswith("address_survival 1.0000 over 1; 1 of 1 element(s) survive")
    assert lines[5].split()[:2] == ["compile.docx.native", "docx"]
    assert lines[6].split()[:2] == ["compile.pptx.native", "pptx"]
    assert lines[7].split()[:3] == ["omniweave", "shape", "cell_identity"]
    assert lines[7].endswith("1.0000 over 1; 1 of 1 identical to the frozen values")
    assert [line.split()[1] for line in lines[8:10]] == ["docx", "pptx"]
    assert lines[10].startswith(
        "ow eval run --suite parse,absence,retrieve,roundtrip,portability: 10 run(s) written to "
    )
    assert handed == [admission.admit]
    code, out, err = _eval("release-check", "--oweval", str(store))
    assert (code, err) == (1, "")
    assert _masked(out) == [
        *UNDER_MIN,
        *DRAFTED,
        "ow eval release-check: refused, 4 finding(s); 10 latest run(s), 0 superseded,"
        " 5 hard gate(s)",
    ], "D913: every hard gate holds; the unverified labels' rates refuse, and D933's ceiling"


def test_deterministic_half_runs_the_damage_half_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D933: `--deterministic-half` is 16:690's paired-damage half, and leaves the removal half."""
    _fake_suite(monkeypatch, True)

    def never(*_a: object, **_k: object) -> removal_harness.Removal:
        raise AssertionError("--deterministic-half runs no removal half")

    monkeypatch.setattr(removal_harness, "run_suite", never)
    store = tmp_path / "x.oweval"
    code, out, _ = _eval(
        "run", "--suite", "absence", "--deterministic-half", "--oweval", str(store)
    )
    assert code == 0
    first, last = out.splitlines()
    assert first.split()[1:3] == ["deterministic_half", "degradation_detection"]
    assert last == f"ow eval run --suite absence: 1 run(s) written to {store}"


def test_a_failed_element_is_printed_and_release_check_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D902: R2 is the hard `address_survival` row, so one lost address refuses a release."""
    _fake_roundtrip(monkeypatch, survive=False)
    store = tmp_path / "x.oweval"
    code, out, _ = _eval("run", "--suite", "roundtrip", "--oweval", str(store))
    assert code == 0
    assert out.splitlines()[0].endswith(
        "address_survival 0.0000 over 1; 0 of 1 element(s) survive; failed: u01/e1 (kind: it)"
    )
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert "address_survival@docx in roundtrip/compile.docx.native run" in out
    assert "0.0 is not the hard budget 1.0" in out


def test_a_shape_that_moved_on_this_cell_is_printed_and_release_check_refuses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D903: portability is the hard `cell_identity` row, so one moved shape refuses a release."""
    _fake_cells(monkeypatch)
    monkeypatch.setattr(cell_harness, "shapes", lambda _root: ({"a.shape": "1"}, {"a.shape": "2"}))
    store = tmp_path / "x.oweval"
    code, out, _ = _eval("run", "--suite", "portability", "--oweval", str(store))
    assert code == 0
    assert out.splitlines()[0].endswith(
        "cell_identity 0.0000 over 1; 0 of 1 identical to the frozen values;"
        " differ: a.shape: differs"
    )
    code, out, _ = _eval("release-check", "--oweval", str(store))
    assert code == 1
    assert "cell_identity@shape in portability/omniweave run" in out
    assert "0.0 is not the hard budget 1.0" in out


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
        (
            ["--suite", "parse", "--deterministic-half"],
            "--deterministic-half keeps the absence suite",
        ),
        (["--deterministic-half"], "--deterministic-half keeps the absence suite"),
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


@pytest.mark.parametrize("suite", ["extract", "perf"])
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
