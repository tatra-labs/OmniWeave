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
the one suite nothing runs -- `perf`, since D987 made `extract` not applicable rather than
unmeasured -- and that is asserted too, so the day a suite lands the count moves here.
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


def _step_six(shown: str) -> None:
    """Checklist step 6's output, asserted apart so its test stays inside ruff's statement limit.

    Everything printed is a DISCLOSURE: D1023's eighteen thin slices and D1017's declared unknown.
    Nothing refuses, and nothing asks for a signature any more.
    """
    lines = shown.splitlines()
    assert lines[-1] == (
        "ow eval release-check: ok; 10 latest run(s), 0 superseded, 5 hard gate(s)"
    ), lines[-1]
    kinds = [line.split()[0] for line in lines[:-1:2]]
    assert set(kinds) == {"under-min-slice", "declared-unknown"}, kinds
    assert kinds.count("under-min-slice") == 18, kinds
    assert kinds.count("declared-unknown") == 1, kinds
    #  The declared unknown keeps the detail the run computed, and its own ruling as the fix.
    (declared,) = [line for line in lines if line.startswith("  declared-unknown")]
    assert "false_confident_zero@removal" in declared
    assert "0 of 13 answerable question(s) answered absent, under min_slice_n = 30" in declared
    assert "deferred past v1.0" in lines[lines.index(declared) + 1]
    #  And every thin row names its population against the floor, so a reader can see the gap.
    thin = [line for line in lines if line.startswith("  under-min-slice")]
    assert all("of 30 (13:406), and the macro computed" in line for line in thin), thin
    assert {line.split("@")[0].split()[-1] for line in thin} == {
        "structure_f1",
        "table_rel_acc",
    }, "order_acc has no thin slice: D1021 put every office order verdict on the coarse key"
    #  Nothing asks for a signature any more, which is the whole of what changed.
    assert 'fix: verify its labels: write checked = "verified"' not in shown
    assert 'fix: verify its structure reference: write checked = "verified"' not in shown


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
    #  **CHECKLIST STEP 6, END TO END IN A CHILD PROCESS.** The reviewer verified all 178
    #  assertion labels and all 33 structure references on 2026-10-30, so every rate computed and
    #  met its floor and this exits 0. It asserted `code == 1` until then, and that expectation is
    #  what CI caught when the unit tier did not: T3 runs under `-m conform` and a `-m "not
    #  conform"` run never reaches it.
    #
    #  What is printed is DISCLOSURES and nothing else:
    #    * D1023's eighteen thin slices -- the per-extension keys that cannot reach
    #      `min_slice_n`, each with its `n`, reported because 13:406 will not let a thin slice drop
    #      silently out of the macro mean and refusing nothing because that macro computed;
    #    * D1017's `false_confident_zero`, 0 of 13 answerable questions against a floor of 30,
    #      which no signature or rerun can move.
    assert code == 0, shown
    _step_six(shown)
    code, shown = _ow("eval", "release-check", "--oweval", str(store), "--strict")
    assert code == 1
    #  D987: `--strict` still asks for an `extract` run, and that is the point rather than an
    #  oversight. Not applicable is a DISCLOSURE and a disclosure is a row -- 16:942's "skip is
    #  not a state" -- so a store with no extract row is a store that has not said so yet.
    assert [line.split()[1] for line in shown.splitlines()[:-1:2]][-2:] == ["extract:", "perf:"]
    assert "  suite       extract: no run at all" in shown
    #  And once the row exists it is a disclosure rather than a refusal: `extract` leaves the
    #  findings entirely and `perf` is the only suite still owed.
    code, shown = _ow("eval", "run", "--suite", "extract", "--oweval", str(store))
    assert code == 0, shown
    code, shown = _ow("eval", "release-check", "--oweval", str(store), "--strict")
    assert code == 1, shown
    assert "  not-applicable  extract/omniweave run " in shown
    assert "not applicable at this release" in shown
    assert [line.split()[1] for line in shown.splitlines()[:-1:2]][-1:] == ["perf:"]
