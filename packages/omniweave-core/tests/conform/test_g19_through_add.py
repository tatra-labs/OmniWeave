"""G19 through `ow add`, small: every mutation kind on four documents, both stores real. **D908.**

`tools/incremental_add.py` builds the incremental project through a script and a full rebuild of
the step's roster, each with real `python -m omniweave add` children, and the gate's
`_diff_checkpoint` compares their exports. The PR path runs 60/8 and the nightly 300/40; this is
the same builder on a corpus a test can afford, so a change that breaks it fails here first. It
spawns children, so the conform tier (Q-G25).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]
MIX = {"edit": 1, "touch": 1, "rename": 1, "delete": 1, "add": 1, "driver_version": 1}


def _load(name: str) -> ModuleType:
    path = REPO / "tools" / name
    spec = importlib.util.spec_from_file_location(f"ow_test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_mutation_kind_through_add_agrees_with_a_full_rebuild(tmp_path: Path) -> None:
    gate, builder = _load("gate_incremental.py"), _load("incremental_add.py")
    corpus = builder.fixture()
    script = corpus.script_for(4, MIX, "omniweave/test_g19_through_add/1")
    assert {m.kind for m in script} == set(MIX)
    [built] = builder.build(tmp_path, (len(script),), documents=4, mutations=script, corpus=corpus)
    checkpoint = gate.Checkpoint(built.step, built.incremental, built.full, built.roots)
    divergences, _provenance, archives, _records = gate._diff_checkpoint(checkpoint)
    assert divergences == []
    assert archives == len(corpus.corpus_for(4, script, len(script)))
