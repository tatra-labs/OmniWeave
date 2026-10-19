"""The `licence` suite reads its spellings from `tools/licences.toml`'s `[normalise]`. D879.

The kit kept an `ALIASES` table in code beside G3's `[normalise]`, and the two drifted:
`uharfbuzz` declares `Apache License 2.0`, which G3 reads as `Apache-2.0` and the kit refused,
failing `compile.pptx.native`'s reader on a licence the policy permits. These tests hold the kit
to the one table, read the way G3 reads it.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from omniweave_conform import Subject
from omniweave_conform.suites import licence, run_suite

REPO = Path(__file__).resolve().parents[4]
TEMPLATE = REPO / "packages/omniweave-conform/src/omniweave_conform/template"
PPTX_BACK = REPO / "packages/omniweave-target-pptx/src/omniweave_target_pptx/back/driver.toml"


def _normalise() -> dict[str, tuple[str, ...]]:
    table = tomllib.loads((REPO / "tools" / "licences.toml").read_text(encoding="utf-8"))
    return {k.strip().lower(): tuple(v) for k, v in table["normalise"].items()}


def test_the_kit_reads_g3s_table_and_keeps_none_of_its_own(tmp_path: Path) -> None:
    subject = Subject.of(TEMPLATE / "driver.toml", workdir=tmp_path)
    policy = licence._policy(subject)
    assert dict(policy.normalise) == _normalise()
    assert policy.source.endswith("licences.toml")
    assert not hasattr(licence, "ALIASES")


def test_a_whole_field_row_is_its_candidates_and_a_term_is_looked_up_alone() -> None:
    table = _normalise()
    terms = licence._terms
    assert terms("Apache License 2.0", table) == ["Apache-2.0"]
    assert terms("BSD-3-Clause, Apache-2.0, dependency licenses", table) == [
        "BSD-3-Clause",
        "Apache-2.0",
    ]
    assert terms("PSFL OR MIT License", table) == ["PSF-2.0", "MIT"]
    assert terms("BSD License", table) == ["BSD-2-Clause", "BSD-3-Clause"]
    assert terms("MIT-CMU", table) == ["MIT-CMU"]
    assert terms("A, B", {"a, b": ("X",)}) == ["X"], "a whole row wins over its terms"


def test_the_two_spellings_only_the_kit_had_now_live_in_the_table() -> None:
    table = _normalise()
    assert (table["apache-2"], table["the unlicense"]) == (("Apache-2.0",), ("Unlicense",))


def test_the_pptx_readers_resolved_graph_fails_on_pillow_alone(tmp_path: Path) -> None:
    """`uharfbuzz` clears; `Pillow`'s MIT-CMU is G3's open policy question (ledger D9)."""
    result = run_suite("licence", Subject.of(PPTX_BACK, workdir=tmp_path))
    [resolved] = [a for a in result.assertions if a.locus == "scan:resolved"]
    assert not resolved.ok
    assert resolved.actual == "Pillow (MIT-CMU)"
