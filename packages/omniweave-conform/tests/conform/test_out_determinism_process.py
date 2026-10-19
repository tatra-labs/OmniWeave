"""OUT13 for real: the pptx golden compiled here and in three fresh processes. D878.

`out_determinism.run()` spawns `python -m omniweave_conform.out_determinism` once per
`PYTHONHASHSEED`, so this lives in the conform tier (Q-G25).
"""

from __future__ import annotations

import tomllib
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
