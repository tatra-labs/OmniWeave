"""GR8's harness without a run: the corpus, the script and the verdict. **D678.**

The run itself spawns `ow add` and is T3's (`tests/conform/test_gr8_converges_small.py`).
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL = REPO_ROOT / "tools" / "gate_incremental_graph.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("gate_incremental_graph_t1", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


g = _load()


def test_the_numbers_are_06_section_10_4s() -> None:
    """*"60 documents, 20 shuffled steps including 3 edits, 2 deletions and 1 driver-version
    re-parse"* (06:2405). The other fourteen are additions (ruling 1)."""
    assert (g.DOCUMENTS, g.STEPS) == (60, 20)
    assert dict(g.MIX) == {"edit": 3, "delete": 2, "driver_version": 1, "add": 14}
    assert sum(g.MIX.values()) == g.STEPS
    assert g.INITIAL == 46


def test_the_script_is_the_mix_shuffled_and_every_target_is_present() -> None:
    names = tuple(g.corpus())
    assert len(names) == g.DOCUMENTS
    initial, steps = g.script(names)
    assert len(initial) == g.INITIAL
    assert Counter(step.kind for step in steps) == Counter(g.MIX)
    unshuffled = [kind for kind, count in g.MIX.items() for _ in range(count)]
    assert [step.kind for step in steps] != unshuffled, "shuffled"
    present = set(initial)
    for step in steps:
        if step.kind == "add":
            assert step.name not in present
            present.add(step.name)
        elif step.kind in {"edit", "delete"}:
            assert step.name in present, f"{step.render()} names a file that is not there"
            if step.kind == "edit":
                assert step.name.endswith(".md"), "an edit is a text change"
            if step.kind == "delete":
                present.remove(step.name)
        else:
            assert step.name == ""
    assert len(present) == g.DOCUMENTS - g.MIX["delete"]


def test_the_corpus_and_the_script_are_functions_of_the_seed() -> None:
    assert g.corpus() == g.corpus()
    assert g.script(tuple(g.corpus())) == g.script(tuple(g.corpus()))
    assert g.corpus(seed=9) != g.corpus()


def test_the_corpus_shares_its_defined_terms_across_documents() -> None:
    """A term defined in one document and used in another is what makes a deletion move another
    document's graph; a corpus without one would let the deletion path go untested."""
    texts = [body.decode("utf-8") for name, body in g.corpus().items() if name.endswith(".md")]
    defined: Counter[str] = Counter()
    for text in texts:
        defined.update({term for term in g._TERMS if f'"{term}" ' in text})
    assert any(count > 1 for count in defined.values())
    assert len(texts) == g.DOCUMENTS - len(g.OFFICE)
    assert all("Section" in text for text in texts)


def test_the_office_fixtures_are_in_the_initial_roster() -> None:
    """Ruling 2 (D679): the driver step re-parses what `PARSE_DRIVER` parsed, so those documents
    must be there when it runs, wherever the shuffle puts it."""
    names = tuple(g.corpus())
    initial, _steps = g.script(names)
    assert set(g.OFFICE) <= set(initial)
    assert all((g.FIXTURES / name).is_file() for name in g.OFFICE)


def test_each_edit_changes_the_text_it_is_given() -> None:
    text = next(body.decode("utf-8") for name, body in g.corpus().items() if name.endswith(".md"))
    for edit in g._EDITS:
        assert edit(text) != text


@pytest.mark.parametrize(
    ("differences", "absent", "failure", "code"),
    [
        ({}, [], "", 0),
        ({}, ["driver_version"], "", 2),
        ({}, [], "ow add exited 1", 2),
        ({"entities": ([1], [])}, ["driver_version"], "", 1),
    ],
    ids=["clean", "a-step-not-run", "an-add-failed", "a-difference-wins"],
)
def test_the_exit_code(differences: Any, absent: Any, failure: str, code: int) -> None:
    """A difference is a failure whatever else happened; an absent step is never a pass."""
    report = g.Report(differences=differences, absent=[g.Step(k) for k in absent], failure=failure)
    assert report.exit_code() == code


def test_every_step_kind_runs_now() -> None:
    """D679 gave the driver-version step its mechanism, so nothing is absent."""
    assert dict(g.ABSENT) == {}


def test_the_bump_moves_the_parse_drivers_config_off_its_default() -> None:
    """Ruling 4: the step moves the parse driver's key through its config. A value equal to
    the card's default would move nothing and the step would re-parse nothing."""
    from omniweave_core.discovery import catalog  # noqa: PLC0415

    card = catalog().cards[g.PARSE_DRIVER]
    default = card.config.effective({})
    assert f'[drivers."{g.PARSE_DRIVER}".config]' in g.BUMP
    assert "max_asset_bytes = 33554431" in g.BUMP
    assert default["max_asset_bytes"] != 33554431
