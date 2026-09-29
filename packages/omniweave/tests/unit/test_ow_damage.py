"""`tools/ow_damage.py`'s parts that need no fixture: 13:1306's admission, and the fixture table.

The suite end to end, which builds stores and runs `ow`, is the conform tier's
(`tests/conform/test_damage_suite.py`). Admission is tested here against the real registry,
because 13:1306 is about that registry: *"refuses anything whose verb is not a known Action or
whose parameters are not that Action's"*.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omniweave.__main__ import DISPATCHED
from omniweave.surface import registry
from omniweave_conform.damage import INJECTORS

REPO = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    """`tools/ow_damage.py`, loaded by path and never put on `sys.path`."""
    path = REPO / "tools" / "ow_damage.py"
    spec = importlib.util.spec_from_file_location("_owtool_damage", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_fix_gate_9_writes_is_admitted(tool: ModuleType) -> None:
    assert tool.admit(("ow", "add", "c:/corpus/tax summary.docx")) is None


def test_a_word_that_is_no_root_is_refused(tool: ModuleType) -> None:
    refusal = tool.admit(("ow", "frobnicate", "x"))
    assert refusal is not None
    assert "no-such-root" in refusal


def test_a_spelling_the_plan_records_as_absent_is_refused(tool: ModuleType) -> None:
    """`CLI_ABSENT` is the plan's own *"there is no `ow export`"*: known, and not an Action."""
    words = next(iter(registry.CLI_ABSENT))
    refusal = tool.admit(("ow", *words))
    assert refusal is not None
    assert "absent" in refusal


def test_a_rostered_verb_this_build_does_not_run_is_refused(tool: ModuleType) -> None:
    root, verbs = next(
        (root, verbs)
        for root, verbs in registry.CLI_ROSTER.items()
        if verbs and root not in DISPATCHED
    )
    refusal = tool.admit(("ow", root, verbs[0]))
    assert refusal is not None
    assert "does not run" in refusal


def test_a_parameter_the_action_does_not_take_is_refused(tool: ModuleType) -> None:
    refusal = tool.admit(("ow", "add", "x.pdf", "--frobnicate"))
    assert refusal is not None
    assert "not the Action's" in refusal


def test_a_shell_operator_split_into_words_is_refused_as_a_parameter(tool: ModuleType) -> None:
    """No shell runs the fix, so `; rm -rf x` is three more words, and `-rf` is no flag of
    `ow add`."""
    assert tool.admit(("ow", "add", "a.pdf;", "rm", "-rf", "x")) is not None


def test_every_built_injector_has_a_fixture_it_applies_to(tool: ModuleType) -> None:
    """A built Injector with no fixture would be a row of the population nothing measures."""
    assert set(tool.FIXTURES) == set(INJECTORS)
    for name, fixtures in tool.FIXTURES.items():
        assert fixtures, name
        for fixture in fixtures:
            assert fixture.target in fixture.paths
            assert Path(fixture.target).suffix in INJECTORS[name].applies_to


def test_the_fixture_documents_are_the_reference_corpus_s_own(tool: ModuleType) -> None:
    """The fixtures are `fixtures/gen/gen_reference_corpora.py`'s files, byte for byte."""
    for fixtures in tool.FIXTURES.values():
        for fixture in fixtures:
            documents = tool._documents(fixture)
            assert sorted(documents) == sorted(fixture.paths)


def test_a_register_with_no_row_is_exit_two(tool: ModuleType, tmp_path: Path) -> None:
    register = tmp_path / "gates.toml"
    register.write_text("[[gate]]\nmetric = 'span_exact_rate'\n", encoding="utf-8")
    assert tool.main(["--deterministic-half", "--register", str(register)]) == 2


def test_an_injector_that_is_not_built_is_exit_two_and_names_what_is_owed(
    tool: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tool.main(["--injector", "chaos"]) == 2
    out = capsys.readouterr().out
    assert "not built" in out
    assert "chaos" in out
