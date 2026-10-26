"""`ow eval run`, then `ow eval release-check`, as a user types them. D869.

16-roadmap.md section 13's demo is `ow eval release-check` exiting 0. This is that pair end to end
over the repository's own register: the parse suite over both `[[subject]]` drivers, the absence
suite's two halves, every built Injector damaged, read, fixed and read again and every
catalogue question asked of its corpus with its answer removed (D933), and the
retrieve suite's self-verifying half (D870), every catalogue question asked and every cite
resolved, and the roundtrip suite (D871), each target's golden compiled, read back and held to
law R2 as the hard `address_survival` row (D902), and the portability suite (D903), the Tier-A
shapes and each target's parts held to their frozen values, all through real `ow add` children.
It spawns workers, so it is the conform tier's by Q-G25's rule. `--strict` still refuses, naming
the two suites nothing runs; that is asserted too, so the day a suite lands the count moves here.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from omniweave_conform.damage import INJECTORS
from omniweave_core.host.subproc import run_captured

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]
TIMEOUT_S = 900


def _ow(*argv: str) -> tuple[int, str]:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    done = run_captured(
        (sys.executable, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(REPO),
        env=keep,
        timeout_s=TIMEOUT_S,
    )
    shown = (done.stdout + done.stderr).decode("utf-8", "replace").replace("\r\n", "\n")
    return (-1 if done.returncode is None else done.returncode), shown


def test_a_full_run_holds_every_hard_gate_and_refuses_only_the_unverified_labels(
    tmp_path: Path,
) -> None:
    store = tmp_path / "release.oweval"
    code, shown = _ow("eval", "run", "--oweval", str(store), "--render", "json")
    assert code == 0, shown[-4000:]
    done = json.loads(shown)
    assert done["suites"] == ["parse", "absence", "retrieve", "roundtrip", "portability"]
    by_run = {(row["suite"], row["subject"]): row for row in done["runs"]}
    by_slice = {(row["suite"], row["slice"]): row for row in done["runs"]}
    assert by_run["parse", "parse.pdf.pdfium"]["value"] == 1.0
    assert by_run["parse", "parse.office.anydoc"]["value"] is None
    absence = by_slice["absence", "deterministic_half"]
    assert (absence["metric"], absence["value"]) == ("degradation_detection", 1.0)
    assert absence["n"] == absence["parsed"] == sum(1 for _ in INJECTORS) * 2
    removal = by_slice["absence", "removal"]
    #  D933: no answerable catalogue question is answered `absent`, and 13 is under
    #  min_slice_n, so the ceiling is unknown.
    assert (removal["metric"], removal["value"], removal["refused"]) == (
        "false_confident_zero",
        None,
        [],
    )
    assert removal["n"] == removal["parsed"] == 13
    assert removal["corpus"] == "absence_corpus/quick"
    retrieve = by_run["retrieve", "omniweave"]
    assert (retrieve["metric"], retrieve["value"], retrieve["refused"]) == (
        "citability_violations",
        0.0,
        [],
    )
    assert retrieve["n"] > 0
    assert retrieve["parsed"] > 0
    for target in ("docx", "pptx"):
        survived = by_run["roundtrip", f"compile.{target}.native"]
        assert (survived["metric"], survived["value"], survived["refused"]) == (
            "address_survival",
            1.0,
            [],
        )
        assert survived["n"] == survived["parsed"] > 0
    for subject, slice_key in (
        ("omniweave", "shape"),
        ("compile.docx.native", "docx"),
        ("compile.pptx.native", "pptx"),
    ):
        same = by_run["portability", subject]
        assert (same["metric"], same["slice"], same["value"], same["refused"]) == (
            "cell_identity",
            slice_key,
            1.0,
            [],
        )
        assert same["n"] == same["parsed"] > 0
    code, shown = _ow("eval", "release-check", "--oweval", str(store))
    #  D913: every hard gate holds. The drafted labels' rates are unknown until a reviewer
    #  verifies them, and each refusal names that as its fix. D933: false_confident_zero is
    #  unknown over 13 answerable questions, and its refusal names more questions as the fix.
    #  D982 added `structure_f1` over the office fixtures' drafted `structure.jsonl` references:
    #  unknown for the same reason, one signature short, and its fix names those rows and not the
    #  assertions file's, because a reference is signed per document in its own file.
    assert code == 1
    refused = [line.split()[1] for line in shown.splitlines()[:-1:2]]
    assert refused == [
        "false_confident_zero@removal",
        "order_acc@__macro__",
        "order_acc@__macro__",
        "structure_f1@__macro__",
        "table_rel_acc@__macro__",
    ], shown
    assert shown.count('fix: verify its labels: write checked = "verified"') == 3
    assert shown.count('fix: verify its structure reference: write checked = "verified"') == 1
    assert shown.splitlines()[-1] == (
        "ow eval release-check: refused, 5 finding(s); 10 latest run(s), 0 superseded, "
        "5 hard gate(s)"
    )
    code, shown = _ow("eval", "release-check", "--oweval", str(store), "--strict")
    assert code == 1
    assert [line.split()[1] for line in shown.splitlines()[:-1:2]][-2:] == [
        "extract:",
        "perf:",
    ]
