"""G26's deterministic half, in real children: the witness and the hook path's module count.

**It spawns, so it is T3** (13 section 2.7). The wall clock is not asserted: the gate script
itself (`uv run tools/gate_hook_latency.py`) is where the budgets and the band run, and a timing
asserted inside a loaded test run would be a flake by construction.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.conform

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL = REPO_ROOT / "tools" / "gate_hook_latency.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("gate_hook_latency_t3", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


g = _load()


def _project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(g.PROJECT_TOML, encoding="utf-8")  # type: ignore[attr-defined]
    return tmp_path


def test_the_prompt_reaches_its_handler_and_the_control_does_not(tmp_path: Path) -> None:
    """D432: the witness discriminates, so a gate over `ow hook prompt` times the handler."""
    ok, counters = g.witness(_project(tmp_path))  # type: ignore[attr-defined]
    assert ok, counters
    assert all(one.startswith("ow-hook-ups-") for one in counters["prompt"])


def test_the_hook_path_module_count_is_this_os_baseline(tmp_path: Path) -> None:
    """The hard assertion, where it is deterministic: the same count as the recorded baseline,
    and no module the baseline does not name. A new eager import on the hook path fails here."""
    path = g.baseline_path()  # type: ignore[attr-defined]
    if not path.is_file():
        pytest.skip(f"no G26 baseline for this OS: {path.name}")
    baseline = json.loads(path.read_text(encoding="utf-8"))
    modules = g.hook_modules(_project(tmp_path))  # type: ignore[attr-defined]
    assert sorted(set(modules) - set(baseline["modules"])) == []
    assert len(modules) <= baseline["module_count"]
