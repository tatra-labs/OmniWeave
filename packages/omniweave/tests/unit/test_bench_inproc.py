"""`ow bench inproc` (D656): F2's measurement, run small, and the report it prints.

The full bench is two minutes of children and a 20-minute `ow add` over `fixtures/office-200`; the
tests here run one real child per path over two documents and render the report from a result
built by hand, so the K-9 line and the worker's ceiling line are both exercised without either.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from typing import Final

import pytest
from omniweave.run import inproc as bi

REPO: Final = Path(__file__).resolve().parents[4]


def _tool() -> object:
    spec = importlib.util.spec_from_file_location("ow_bench_tool", REPO / "tools" / "ow_bench.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _two_documents(dest: Path) -> Path:
    """Two of office-200's own documents, written by its generator: a docx and an xlsx."""
    spec = importlib.util.spec_from_file_location(
        "omniweave_gen_office200_bench", REPO / "fixtures" / "gen" / "gen_office200.py"
    )
    assert spec is not None
    assert spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen
    spec.loader.exec_module(gen)
    dest.mkdir(parents=True)
    (dest / "a.docx").write_bytes(gen.docx(gen._Stream("t:a"), 2))
    (dest / "b.xlsx").write_bytes(gen.xlsx(gen._Stream("t:b"), 30))
    return dest


def test_both_paths_run_in_their_own_child_and_report_every_field(tmp_path: Path) -> None:
    corpus = _two_documents(tmp_path / "corpus")
    result = bi.inproc(corpus, workspace=tmp_path / "work", threads=(1,), worker=False)
    assert result.documents == 2
    assert result.worker is None
    assert [(p.mode, p.threads) for p in result.points] == [("rust", 1), ("document", 1)]
    for point in result.points:
        assert point.documents == 2
        assert point.refused == 0
        assert point.wall_s > 0
        assert point.peak_rss is not None
        assert point.peak_rss > 0
        #  The floor is the probe's own, with nothing running here; under a loaded test run
        #  the OS preempts the probe and the floor rises, so only its range is asserted.
        assert 0.0 <= point.gil_idle <= 1.0
        assert 0.0 <= point.gil_held <= 1.0


def test_an_empty_corpus_is_refused_with_the_command_that_writes_it(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"gen_office200.py"):
        bi.inproc(tmp_path, workspace=tmp_path / "work", worker=False)


def _point(mode: str, threads: int, held: float) -> bi.InprocPoint:
    return bi.InprocPoint(
        mode=mode,
        threads=threads,
        documents=200,
        refused=0,
        wall_s=8.0,
        peak_rss=800 * 2**20,
        peak_rss_source="test",
        gil_held=held,
        gil_idle=0.01,
    )


def test_the_report_names_k9_and_the_worker_against_its_ceiling() -> None:
    """K-9's 30% line is read against the marshal's held share above the floor, and the worker
    line says OVER and names the clause when the peak passes value + tolerance."""
    tool = _tool()
    result = bi.InprocResult(
        corpus=Path("office-200"),
        documents=200,
        corpus_bytes=14 * 2**20,
        points=(_point("rust", 1, 0.02), _point("document", 1, 0.34), _point("document", 4, 0.47)),
        worker=bi.WorkerPeak(peak_rss=2_000_000_000, rows=200, done=189, seconds=1170.0),
    )
    out = io.StringIO()
    tool.report_inproc(result, out)  # type: ignore[attr-defined]
    text = out.getvalue()
    assert "K-9" in text
    assert "47%" in text
    assert "over 30% above the floor at threads [1, 4]" in text
    assert "rss.office200_peak_bytes" in text
    assert "189/200" in text
    assert "OVER: FORK-TRIGGER.md clause 2" in text
    assert "11 rows did not settle" in text
