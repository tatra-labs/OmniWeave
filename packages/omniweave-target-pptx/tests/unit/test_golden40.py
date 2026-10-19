"""V10-10's 40-unit golden OUT fixture: `fixtures/gen/gen_golden40.py`'s forty-slide deck. D881.

The generator is loaded by file path, as the other `fixtures/gen/` tests load theirs. The deck is
generated into `tmp_path`, pinned through `fixtures/gen/EXPECTED.sha256`, and held to the pptx
gate in this process. Its five-way compile is `omniweave-conform`'s conform tier, since that
spawns children.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omniweave_core.out.compile import check
from omniweave_core.out.gate import GateStatus
from omniweave_target_pptx.driver import PptxCompiler, table

REPO = Path(__file__).resolve().parents[4]
PINS = REPO / "fixtures" / "gen" / "EXPECTED.sha256"
FONTS = REPO / "fixtures" / "out" / "golden" / "pptx" / "fonts"


def _load() -> ModuleType:
    path = REPO / "fixtures" / "gen" / "gen_golden40.py"
    spec = importlib.util.spec_from_file_location("_owgen_golden40", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN = _load()


def test_the_pin_is_the_digest_of_a_freshly_generated_deck(tmp_path: Path) -> None:
    """13-quality.md:588: a change to the deck is *"a one-line visible diff"*."""
    line = next(
        row
        for row in PINS.read_text("utf-8").splitlines()
        if not row.startswith("#") and row.endswith("golden40/pptx.manifest")
    )
    pinned, _, path = line.partition("  ")
    assert path == "fixtures/generated/out/golden40/pptx.manifest"
    manifest = GEN.write(tmp_path / "pptx")
    assert manifest == tmp_path / "pptx.manifest"
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == pinned
    assert b"\r" not in manifest.read_bytes()


def test_the_deck_is_generated_with_no_clock_and_no_randomness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`fixtures/gen/README.md`'s regime: the clocks and the RNG raise, and the bytes repeat."""

    def refuse(*_a: object, **_k: object) -> None:
        msg = "a generator may not read a clock or draw a random number"
        raise AssertionError(msg)

    for target in ("time.time", "time.time_ns", "random.random", "random.seed", "uuid.uuid4"):
        monkeypatch.setattr(target, refuse)
    first = GEN.write(tmp_path / "a" / "pptx").read_bytes()
    second = GEN.write(tmp_path / "b" / "pptx").read_bytes()
    assert first == second


def test_forty_units_seven_layouts_and_a_cite_per_quote_slide(tmp_path: Path) -> None:
    out = tmp_path / "pptx"
    GEN.write(out)
    units = sorted(p.name for p in (out / "il").glob("u*.svg"))
    assert units == [f"u{n:02d}.svg" for n in range(1, 41)]
    layouts = [GEN.layout_of(n) for n in range(1, 41)]
    assert set(layouts) == {"cover", *GEN.LAYOUTS}
    cites = json.loads((out / "cites.json").read_text(encoding="utf-8"))
    assert sorted(cites) == sorted(
        GEN.cite_of(n) for n in range(1, 41) if layouts[n - 1] == "quote"
    )
    for slide in range(1, 41):
        if layouts[slide - 1] == "quote":
            body = (out / "il" / f"u{slide:02d}.svg").read_text(encoding="utf-8")
            assert f">{cites[GEN.cite_of(slide)]['text']}</text>" in body
    assert (out / "assets" / "chart.png").read_bytes() == (
        REPO / "fixtures" / "out" / "golden" / "pptx" / "assets" / "chart.png"
    ).read_bytes()


def test_the_deck_passes_the_pptx_gate_as_a_release(tmp_path: Path) -> None:
    """No slide carries a manual region, so the gate passes and the compile is a release."""
    from omniweave_conform.suites.target.suite import _FixtureCites  # noqa: PLC0415

    out = tmp_path / "pptx"
    GEN.write(out)
    job = tmp_path / "job"
    (job / "il").mkdir(parents=True)
    for unit in (out / "il").iterdir():
        (job / "il" / unit.name).write_bytes(unit.read_bytes())
    result = check(
        job,
        PptxCompiler(font_dir=str(FONTS)),
        target="pptx",
        constructs=table(),
        stage="final",
        cites=_FixtureCites(out / "cites.json"),
    )
    assert (result.status, result.report.findings) == (GateStatus.PASSED, ())
    assert result.report.summary["units"] == 40
