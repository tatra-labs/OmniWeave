"""`ow eval publish`: the verb, its entry point, and each exit its docstring rules. D833.

The verb runs in-process through `omniweave.surface.eval.main`, against an `.oweval` written
under `tmp_path` by `omniweave_core.store.oweval`. The work happens in `omniweave-conform`, across
the `[omniweave.eval] publish` entry point that the workspace installs. The refusals when that
entry point is missing are tested by handing `eval_entry()` rows, as the serve tests do.
"""

from __future__ import annotations

import io
import json
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave.surface import dispatch
from omniweave.surface import eval as verb
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import CapabilityMissing, ConfigError
from omniweave_core.store.oweval import Batch, Corpus, Metric, Run, open_oweval
from omniweave_core.store.oweval import write as store

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

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
_RUN = Run(
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
    fairness={},
)
_METRIC = Metric(
    run_id="r1",
    metric="order_acc",
    value=0.9,
    n=40,
    ci_lo=0.77,
    ci_hi=0.96,
    method="closed_form",
    truth_kind="rendered",
    state="ok",
)
FILE = "parse/parse.pdf.pdfium.json"


def _oweval(root: Path, *metrics: Metric) -> None:
    (root / "eval").mkdir(parents=True, exist_ok=True)
    connection = open_oweval(root / "eval" / "omniweave.oweval")
    try:
        store(connection, Batch(corpora=(_CORPUS,), runs=(_RUN,), metrics=metrics or (_METRIC,)))
    finally:
        connection.close()


def _run(cwd: Path, *argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["eval", "publish", *argv], cwd=cwd, env={}, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


# --- publish ---------------------------------------------------------------------------------


def test_publish_writes_the_tree_and_a_second_run_finds_it_matching(tmp_path: Path) -> None:
    _oweval(tmp_path)
    code, out, err = _run(tmp_path)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        f"  wrote  {FILE}",
        "published eval/results: 1 file(s), 1 row(s), 1 file(s) changed",
    ]
    rows = json.loads((tmp_path / "eval" / "results" / FILE).read_bytes())
    assert [(r["metric"], r["run_id"]) for r in rows] == [("order_acc", "r1")]
    assert _run(tmp_path) == (0, "eval/results matches the .oweval: 1 file(s), 1 row(s)\n", "")


def test_publish_removes_a_file_no_export_names(tmp_path: Path) -> None:
    _oweval(tmp_path)
    stray = tmp_path / "eval" / "results" / "parse" / "retired.json"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"[]\n")
    code, out, _ = _run(tmp_path)
    assert code == 0
    assert "  wrote  parse/retired.json" in out.splitlines()
    assert not stray.exists()
    assert (tmp_path / "eval" / "results" / FILE).is_file()


def test_check_names_what_differs_and_writes_nothing(tmp_path: Path) -> None:
    _oweval(tmp_path)
    assert _run(tmp_path, "--check") == (
        1,
        f"  differs  {FILE}\now eval publish --check: 1 file(s) differ; run ow eval publish\n",
        "",
    )
    assert not (tmp_path / "eval" / "results").exists()
    _run(tmp_path)
    assert _run(tmp_path, "--check")[0] == 0
    target = tmp_path / "eval" / "results" / FILE
    target.write_bytes(target.read_bytes().replace(b"0.9", b"0.91"))
    code, out, _ = _run(tmp_path, "--check")
    assert code == 1
    assert f"  differs  {FILE}" in out
    assert b"0.91" in target.read_bytes()


def test_the_paths_are_options_relative_to_the_working_directory(tmp_path: Path) -> None:
    _oweval(tmp_path)
    (tmp_path / "eval" / "omniweave.oweval").rename(tmp_path / "nightly.oweval")
    code, out, _ = _run(tmp_path, "--oweval", "nightly.oweval", "--results", "board")
    assert code == 0
    assert out.endswith("published board: 1 file(s), 1 row(s), 1 file(s) changed\n")
    assert (tmp_path / "board" / FILE).is_file()


def test_render_json_prints_one_object(tmp_path: Path) -> None:
    _oweval(tmp_path)
    code, out, _ = _run(tmp_path, "--render", "json")
    assert code == 0
    assert json.loads(out) == {"files": [FILE], "rows": 1, "changed": [FILE], "written": True}
    assert json.loads(_run(tmp_path, "--render", "json", "--check")[1])["written"] is False


# --- the refusals ----------------------------------------------------------------------------


def test_a_missing_oweval_is_not_found_and_never_created(tmp_path: Path) -> None:
    code, out, err = _run(tmp_path)
    assert (code, out) == (2, "")
    assert "no .oweval at" in err
    assert "fix: run the eval suites to write one, or pass --oweval PATH" in err
    assert not (tmp_path / "eval").exists()


def test_a_refused_publication_exits_1_with_its_quality_code(tmp_path: Path) -> None:
    """Ruling 3: Q-G21 refuses `field_acc` without `doc_acc`, and the exit is 1, not 70."""
    _oweval(tmp_path, replace(_METRIC, metric="field_acc"))
    code, out, err = _run(tmp_path)
    assert (code, out) == (1, "")
    assert "OW_QUALITY" in err
    assert "Q-G21:" in err
    assert not (tmp_path / "eval" / "results").exists()
    code, out, _ = _run(tmp_path, "--render", "json")
    assert code == 1
    error = json.loads(out)["error"]
    assert error["code"] == "OW_QUALITY"
    assert error["message"].startswith("Q-G21: parse/parse.pdf.pdfium.json: field_acc@")


@pytest.mark.parametrize("mode", ["jsonl", "rows"])
def test_a_render_mode_with_no_writer_is_refused_by_name(tmp_path: Path, mode: str) -> None:
    _oweval(tmp_path)
    code, _, err = _run(tmp_path, "--render", mode)
    assert code == 1
    assert f"--render {mode} is parsed and not served by ow eval publish" in err
    assert not (tmp_path / "eval" / "results").exists()


def test_quiet_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    code, _, err = _run(tmp_path, "--quiet")
    assert code == 1
    assert "--quiet is parsed and not served by ow eval" in err


def test_without_omniweave_conform_the_verb_is_ow_a_027(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 5 and 10:286: the code, exit 64, and the install command."""
    _oweval(tmp_path)
    monkeypatch.setattr(dispatch, "_installed", lambda *_: [])
    code, _, err = _run(tmp_path)
    assert code == 64
    assert err.startswith("ow: OW-A-027: ")
    assert "ow eval publish needs omniweave-conform, which is not installed" in err
    assert "fix: pip install omniweave-conform" in err


@pytest.mark.parametrize(
    "reply",
    [
        {"files": "x"},
        {"files": [], "changed": [], "rows": 0},
        {"files": [], "changed": [], "rows": 0, "written": "yes"},
        {"files": [], "changed": [], "rows": "0", "written": False},
    ],
)
def test_a_malformed_entry_point_reply_is_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: dict[str, object]
) -> None:
    _oweval(tmp_path)
    monkeypatch.setattr(verb, "eval_entry", lambda _name: lambda **_: reply)
    code, _, err = _run(tmp_path)
    assert code == 70
    assert "returned no files, changed, rows and written" in err


def test_the_launcher_routes_eval_to_the_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert launcher.main(["eval", "publish", "--oweval", "nowhere.oweval"]) == 2
    assert "no .oweval at" in capsys.readouterr().err


# --- eval_entry() ----------------------------------------------------------------------------


class _Entry:
    def __init__(self, name: str, value: str, loaded: Any) -> None:
        self.name = name
        self.value = value
        self._loaded = loaded

    def load(self) -> Any:
        return self._loaded


def _publish(**_: object) -> dict[str, object]:
    return {}


def test_eval_entry_loads_the_verb_it_is_named_for() -> None:
    rows: Sequence[Any] = [_Entry("check", "m:check", print), _Entry("publish", "m:p", _publish)]
    assert dispatch.eval_entry("publish", rows) is _publish


def test_eval_entry_refusals_name_the_group_and_the_fix() -> None:
    with pytest.raises(CapabilityMissing) as missing:
        dispatch.eval_entry("publish", [])
    assert missing.value.code() == "OW_EVAL_NOT_INSTALLED"
    assert missing.value.missing == ("omniweave-conform",)
    assert "no [omniweave.eval] publish entry point" in str(missing.value)
    two = [_Entry("publish", "a:p", _publish), _Entry("publish", "b:p", _publish)]
    with pytest.raises(ConfigError, match=r"declared 2 times \(a:p, b:p\)"):
        dispatch.eval_entry("publish", two)
    with pytest.raises(ConfigError, match="is not callable"):
        dispatch.eval_entry("publish", [_Entry("publish", "m:x", 7)])


def test_the_workspace_installs_the_publish_entry_point() -> None:
    from omniweave_conform.entry import publish  # noqa: PLC0415

    assert dispatch.eval_entry("publish") is publish
