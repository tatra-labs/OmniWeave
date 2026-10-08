"""GR8's harness run small through the real `ow add`, and once with its deletion off. **D678.**

The full gate (60 documents, 20 steps) is `uv run tools/gate_incremental_graph.py`; T3 runs the same
harness over a corpus small enough for a test, with every kind the gate can run. The counterfactual
is what makes the first test mean something: with the explicit retirement skipped -- the file gone,
nothing told the store -- the two sides must differ, so the comparison is shown to see deletions.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.conform

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL = REPO_ROOT / "tools" / "gate_incremental_graph.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("gate_incremental_graph_t3", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


g = _load()


def test_a_small_corpus_through_every_runnable_kind_converges(tmp_path: Path) -> None:
    report = g.run(tmp_path, documents=7, mix={"add": 2, "edit": 3, "delete": 2})
    assert report.failure == ""
    assert report.differences == {}
    assert report.exit_code() == g.EXIT_CLEAN
    assert len(report.steps) == 7
    assert report.sizes["entities"] > 0, "the projection compared something"
    assert report.sizes["anchors"] > 0
    assert report.sizes["unresolved"] > 0


def test_a_deletion_the_store_was_not_told_of_is_a_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(g, "retire_document", lambda *_args: None)
    report = g.run(tmp_path, documents=3, mix={"delete": 1})
    assert report.failure == ""
    assert report.exit_code() == g.EXIT_FAIL
    assert {"entities", "anchors"} <= set(report.differences)
    for only_incremental, only_full in report.differences.values():
        assert only_incremental, "the incremental side kept what the deleted file held"
        assert not only_full
