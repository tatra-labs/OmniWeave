"""`ow bench query` end to end over a two-page store: built by `ow add`, merged, timed. D915.

`Corpus.add` spawns the PDF driver's worker, so the conform tier (Q-G25).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave.run import bench

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]


def test_a_small_store_is_built_merged_and_every_query_timed_warm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_HOME", str(tmp_path / "owhome"))
    result: object = bench.query(REPO, tmp_path / "project", pages=2, runs=1)
    assert result.pages == 2  # type: ignore[attr-defined]
    assert result.merged is True  # type: ignore[attr-defined]
    assert 0 < result.blocks < 200  # type: ignore[attr-defined]
    assert result.narrowing_all is False  # type: ignore[attr-defined]
    total = result.total  # type: ignore[attr-defined]
    assert total.n == 40
    assert 0 < total.p50 <= total.p99
    assert {series.name for series in result.by_kind} == {  # type: ignore[attr-defined]
        "heading",
        "phrase",
        "cell",
        "words",
        "absent",
    }
    assert (tmp_path / "project" / ".omniweave" / "docs.owstore").is_file()
