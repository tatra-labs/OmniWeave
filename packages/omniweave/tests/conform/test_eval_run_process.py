"""`ow eval run`, then `ow eval release-check`, as a user types them. D869.

16-roadmap.md section 13's demo is `ow eval release-check` exiting 0. This is that pair end to end
over the repository's own register: the parse suite over both `[[subject]]` drivers, and the
absence suite's deterministic half, every built Injector damaged, read, fixed and read again,
through real `ow add` children. It spawns workers, so it is the conform tier's by Q-G25's rule.
`--strict` still refuses, naming the five suites nothing runs; that is asserted too, so the day a
suite lands the count moves here.
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


def test_a_full_run_passes_release_check_and_strict_names_the_unrun_suites(
    tmp_path: Path,
) -> None:
    store = tmp_path / "release.oweval"
    code, shown = _ow("eval", "run", "--oweval", str(store), "--render", "json")
    assert code == 0, shown[-4000:]
    done = json.loads(shown)
    assert done["suites"] == ["parse", "absence"]
    by_subject = {row["subject"]: row for row in done["runs"]}
    assert by_subject["parse.pdf.pdfium"]["value"] == 1.0
    assert by_subject["parse.office.anydoc"]["value"] is None
    absence = by_subject["omniweave"]
    assert (absence["metric"], absence["value"]) == ("degradation_detection", 1.0)
    assert absence["n"] == absence["parsed"] == sum(1 for _ in INJECTORS) * 2
    code, shown = _ow("eval", "release-check", "--oweval", str(store))
    assert (code, shown) == (
        0,
        "ow eval release-check: ok; 3 latest run(s), 0 superseded, 2 hard gate(s)\n",
    )
    code, shown = _ow("eval", "release-check", "--oweval", str(store), "--strict")
    assert code == 1
    assert [line.split()[1] for line in shown.splitlines()[:-1:2]] == [
        "extract:",
        "retrieve:",
        "roundtrip:",
        "portability:",
        "perf:",
    ]
