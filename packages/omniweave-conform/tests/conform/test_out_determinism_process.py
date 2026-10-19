"""OUT13 for real: the pptx golden compiled here and in three fresh processes. D878.

`out_determinism.run()` spawns `python -m omniweave_conform.out_determinism` once per
`PYTHONHASHSEED`, so this lives in the conform tier (Q-G25).
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from omniweave_conform.out_determinism import SEEDS, compile_fresh, run
from omniweave_conform.roundtrip import targets
from omniweave_core.errors import QualityError

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]
REGISTER = REPO / "eval" / "gates.toml"


def test_the_pptx_golden_compiles_to_one_part_digest_five_ways(tmp_path: Path) -> None:
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    [target] = [t for t in targets(register, REPO) if t.target == "pptx"]
    judged = run(target, root=REPO, register=REGISTER, workdir=tmp_path)
    assert judged.held, judged.failures
    assert [c.label for c in judged.compiles] == [
        "in-process a",
        "in-process b",
        *(f"PYTHONHASHSEED={seed}" for seed in SEEDS),
    ]
    assert judged.agree("part_digest") == 5
    assert len(judged.compiles[2].members) == len(judged.compiles[0].members) > 1


def test_a_child_that_cannot_compile_is_a_quality_error_not_a_disagreement(
    tmp_path: Path,
) -> None:
    with pytest.raises(QualityError, match="exited 1"):
        compile_fresh("no-such-target", root=REPO, register=REGISTER, workdir=tmp_path, seed="0")


def test_the_forty_unit_golden_compiles_to_one_part_digest_five_ways(tmp_path: Path) -> None:
    """V10-10's *"40-unit golden"* (D881), generated here and compiled as the two-unit one is."""
    spec = importlib.util.spec_from_file_location(
        "_owgen_golden40_process", REPO / "fixtures" / "gen" / "gen_golden40.py"
    )
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen
    spec.loader.exec_module(gen)
    deck = tmp_path / "deck" / "pptx"
    gen.write(deck)
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    [target] = [t for t in targets(register, REPO) if t.target == "pptx"]
    judged = run(replace(target, golden=deck), root=REPO, register=REGISTER, workdir=tmp_path / "w")
    assert judged.held, judged.failures
    assert judged.agree("part_digest") == 5
    assert judged.agree("byte_digest") == 5
    assert len(judged.compiles[0].members) > 100
