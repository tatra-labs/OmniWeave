"""`omniweave_core.contract` — the contract stamp.

Every assertion names the plan locus that sets the value it checks, in the test's own name, because
a constant test that does not cite its warrant is a test of what the code happens to say.
"""

from __future__ import annotations

import ast
import sys
from importlib.metadata import version as dist_version
from pathlib import Path

import pytest
from omniweave_core import contract

SOURCE = Path(contract.__file__)


def _public_names(mod: object) -> set[str]:
    """Names a `from ... import *` would take. `annotations` is the `__future__` flag, and
    an `@`-prefixed name is pytest's assertion-rewriting machinery, not a public symbol."""
    return {
        n for n in vars(mod) if n.isidentifier() and not n.startswith("_") and n != "annotations"
    }


# ---------------------------------------------------------------------------
# The four constants, each against the document that prints it
# ---------------------------------------------------------------------------


def test_contract_is_1__16_roadmap_md_section_1_p1_ends_at_contract_1() -> None:
    """`P1 ends at CONTRACT = 1 and card_schema = 1` — 16-roadmap.md section 1."""
    assert contract.CONTRACT == 1
    assert isinstance(contract.CONTRACT, int)


def test_contracts_supported_is_a_frozenset_of_int__02_architecture_md_section_2_row_2() -> None:
    """Row 2 prints `CONTRACTS_SUPPORTED: frozenset[int]`; ADR-9 decision 1 repeats the type."""
    assert isinstance(contract.CONTRACTS_SUPPORTED, frozenset)
    assert frozenset({1}) == contract.CONTRACTS_SUPPORTED
    assert all(isinstance(m, int) for m in contract.CONTRACTS_SUPPORTED)


def test_contracts_supported_contains_contract__04_driver_system_md_section_5_3() -> None:
    """`activate()` checks a card's declared contract against this set, so a build that cannot
    accept its own ABI could never activate a first-party driver."""
    assert contract.CONTRACT in contract.CONTRACTS_SUPPORTED


def test_schema_is_1_and_schema_minor_is_0__03_document_model_md_section_15_1() -> None:
    """`At release 1: SCHEMA = 1, SCHEMA_MINOR = 0, model_version = "1.1"` — section 15.1."""
    assert contract.SCHEMA == 1
    assert contract.SCHEMA_MINOR == 0
    assert isinstance(contract.SCHEMA, int)
    assert isinstance(contract.SCHEMA_MINOR, int)


def test_release_is_the_installed_distribution_version__11_repo_layout_md_section_4_2() -> None:
    """Section 4.2's forty version-bearing sites put `RELEASE` in `[project] version` and nowhere in
    `omniweave_core`, so this module reads the declaration rather than repeating it."""
    assert dist_version("omniweave-core") == contract.RELEASE
    assert contract.RELEASE == "0.1.0"


# ---------------------------------------------------------------------------
# The one formatting site
# ---------------------------------------------------------------------------


def test_schema_string_is_the_pair__adr_0009_schema_single_home_md_decision_2() -> None:
    """`the pair is formatted as f"{SCHEMA}.{SCHEMA_MINOR}" at exactly one site, in contract`."""
    assert f"{contract.SCHEMA}.{contract.SCHEMA_MINOR}" == contract.SCHEMA_STRING
    assert contract.SCHEMA_STRING == "1.0"


def test_no_other_module_source_formats_the_pair__adr_0009_decision_2_exactly_one_site() -> None:
    """The f-string appears in exactly one `omniweave_core` source file: this one."""
    root = SOURCE.parent
    formatting = [
        path
        for path in root.rglob("*.py")
        if "{SCHEMA}.{SCHEMA_MINOR}" in path.read_text(encoding="utf-8")
    ]
    assert formatting == [SOURCE]


# ---------------------------------------------------------------------------
# The rulings this module has to honour
# ---------------------------------------------------------------------------


def test_no_schemas_supported__adr_0009_rejected_alternative_three() -> None:
    """`SCHEMAS_SUPPORTED: frozenset[int]` is rejected on the record: section 3.1's four-row
    table is already a total function of the four version components, so a supported-set would
    only restate it."""
    assert not hasattr(contract, "SCHEMAS_SUPPORTED")


def test_module_exports_exactly_the_stamp__02_architecture_md_section_2_row_2() -> None:
    """Row 2: four module constants, plus `RELEASE` (18-api-sketch.md section 1.1) and the one
    formatted form. Nothing else is public, because this is the module a third party pins."""
    assert contract.__all__ == sorted(contract.__all__)
    assert set(contract.__all__) == {
        "CONTRACT",
        "CONTRACTS_SUPPORTED",
        "RELEASE",
        "SCHEMA",
        "SCHEMA_MINOR",
        "SCHEMA_STRING",
    }
    public = _public_names(contract)
    assert public - set(contract.__all__) == set()


def test_it_holds_no_ceiling__02_architecture_md_section_2_rows_2_and_7() -> None:
    """Row 2 holds stamps; row 7 holds ceilings. The split is the whole of ADR-9."""
    assert [n for n in contract.__all__ if n.startswith(("MAX_", "MIN_"))] == []


@pytest.mark.parametrize("name", sorted(contract.__all__))
def test_every_exported_constant_carries_a_docstring_naming_its_document(name: str) -> None:
    """A reader must be able to get from the constant to its warrant. PEP 258 attribute docstrings
    are not introspectable, so this reads them out of the source instead."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    body = tree.body
    doc = None
    for i, node in enumerate(body[:-1]):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        if target != name:
            continue
        nxt = body[i + 1]
        if isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant):
            doc = nxt.value.value
    assert isinstance(doc, str), f"{name} has no attribute docstring"
    assert ".md" in doc or "ADR-9" in doc or "adr/" in doc, f"{name}'s docstring cites no document"


# ---------------------------------------------------------------------------
# D1 — zero third-party runtime dependencies
# ---------------------------------------------------------------------------


def test_imports_nothing_outside_the_standard_library__charter_d1_and_gate_g1() -> None:
    """`omniweave_core` has zero third-party runtime dependencies: stdlib only."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots
    assert roots <= sys.stdlib_module_names, roots - sys.stdlib_module_names


# ---------------------------------------------------------------------------------------------
# `RELEASE` from the dist-info directory's name (W7.8m, D620)
# ---------------------------------------------------------------------------------------------


def test_the_fast_read_and_importlib_metadata_agree_on_this_install() -> None:
    """The directory name and `METADATA` are one fact; if they ever differ, this is where."""
    assert contract._release_from_dist_info() == dist_version("omniweave-core")


def test_the_fast_read_takes_the_version_from_the_directory_name(tmp_path: Path) -> None:
    """Case-insensitive, as Windows is; another distribution whose name merely starts the same
    (`omniweave_core_extra`) is not a match; an unreadable path entry is skipped."""
    (tmp_path / "OmniWeave_Core-2.3.4.dist-info").mkdir()
    (tmp_path / "omniweave_core_extra-9.dist-info").mkdir()
    assert contract._release_from_dist_info([str(tmp_path)]) == "2.3.4"
    skipped = [str(tmp_path / "missing"), str(tmp_path)]
    assert contract._release_from_dist_info(skipped) == "2.3.4"


def test_the_first_path_entry_holding_one_decides(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    (first / "omniweave_core-1.0.0.dist-info").mkdir(parents=True)
    (second / "omniweave_core-2.0.0.dist-info").mkdir(parents=True)
    assert contract._release_from_dist_info([str(first), str(second)]) == "1.0.0"
    assert contract._release_from_dist_info([str(second), str(first)]) == "2.0.0"


def test_two_in_one_entry_or_none_at_all_fall_back(tmp_path: Path) -> None:
    (tmp_path / "omniweave_core-1.0.0.dist-info").mkdir()
    (tmp_path / "omniweave_core-1.1.0.dist-info").mkdir()
    assert contract._release_from_dist_info([str(tmp_path)]) is None
    assert contract._release_from_dist_info([str(tmp_path / "nothing-here")]) is None
    assert contract._release_from_dist_info([]) is None


def test_importing_the_contract_does_not_import_importlib_metadata() -> None:
    """D620: `ow --version` has 150 ms for the whole process, and this import was ~70 of them."""
    tree = ast.parse(Path(contract.__file__).read_text(encoding="utf-8"))
    top = [node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)]
    modules = {
        alias.name for node in top if isinstance(node, ast.Import) for alias in node.names
    } | {node.module for node in top if isinstance(node, ast.ImportFrom) and node.module}
    assert not {name for name in modules if name.startswith("importlib")}, modules


def test_release_takes_the_fast_reads_answer_and_falls_back_without_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fast read is consulted first; `importlib.metadata` answers only when it does not."""
    monkeypatch.setattr(contract, "_release_from_dist_info", lambda: "7.7.7")
    assert contract._release() == "7.7.7"
    monkeypatch.setattr(contract, "_release_from_dist_info", lambda: None)
    assert contract._release() == dist_version("omniweave-core")
