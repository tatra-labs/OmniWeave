"""Artefact 4: `omniweave/sdk/_generated.pyi`. 10 section 2.3 row 4; 18 section 1; 02:212.

Two properties carry this file, and the first is the one that makes a stub safe to generate at all.

**The stub declares exactly what the package exports** -- not a symbol more, which would make
`omniweave.sdk.corpus("handbook")` type-check against a package that has no `corpus`, and not a
symbol less, which would hide a shipped promise from the byte diff that 02:212 makes the proof of
every `T-PUBLIC` tier. Both directions are asserted here and `_stub_failures()` raises on one of
them at import.

**`SDK_HOMES` is the plan's own signatures, and two of seven match their `inp`.** 10:211 says this
artefact is generated from *"`inp`, `out`, `name`"*; the tests below pin each difference as a
number and a name, so D324's claim is checkable rather than remembered.
"""

from __future__ import annotations

import ast
import json
import subprocess  # noqa: TID251 -- an import set is observable only from a fresh interpreter.
import sys
from dataclasses import fields
from pathlib import Path

import omniweave.gen.sdk_stub as sdk_stub_module
import omniweave.sdk as sdk_package
import pytest
from omniweave.gen.emit import REPO_ROOT
from omniweave.gen.sdk_stub import (
    HANDLE_PARAM,
    SDK_HOMES,
    SOURCES,
    _mismatches,
    agreeing,
    exported,
    owed,
    render,
)
from omniweave.surface import ACTIONS

STUB = REPO_ROOT / "packages" / "omniweave" / "src" / "omniweave" / "sdk" / "_generated.pyi"

PRINTED_SIGNATURES = {
    "query": "Corpus.query",
    "open": "Corpus.open",
    "add": "Corpus.add",
    "corpora": "corpora",
    "corpus.coverage": "Corpus.coverage",
    "doctor": "doctor",
    "explain": "explain",
}
"""18 section 1's spellings, transcribed a second time so `SDK_HOMES` is compared against the
document rather than against itself."""


def _stub_tree() -> ast.Module:
    return ast.parse(render().decode("utf-8"))


def _declared() -> list[str]:
    """Every name the stub re-exports, read back out of the emitted source."""
    return [
        alias.asname or alias.name
        for node in _stub_tree().body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]


# ---------------------------------------------------------------------------------------------
# The rule that makes a generated stub safe: it declares the package and nothing else
# ---------------------------------------------------------------------------------------------


def test_the_stub_declares_exactly_what_the_package_exports() -> None:
    """Over-declaring is LEANN's `llms.txt` -- two tools against a four-tool server -- and G25 is
    named after it (00:851). Under-declaring hides a shipped promise from the byte diff 02:212
    makes the proof of the `T-PUBLIC` tier."""
    assert _declared() == list(exported())
    assert exported() == tuple(sorted(sdk_package.__all__))


def test_every_declared_name_is_actually_bound_by_the_package() -> None:
    """`__all__` is a claim; `hasattr` is the fact. `_stub_failures()` raises on a disagreement."""
    for symbol in exported():
        assert hasattr(sdk_package, symbol), symbol


def test_a_name_in_all_that_the_package_does_not_bind_fails_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Pretend:
        __all__ = ["Invented"]  # noqa: RUF012 -- a stand-in module object, not a real registry

    monkeypatch.setattr(sdk_stub_module, "_sdk", Pretend)
    failures = sdk_stub_module._stub_failures()
    assert any("Invented" in line and "not bound" in line for line in failures)


def test_the_stub_lists_its_names_in_one_sorted_order() -> None:
    """10:225's sort, and the reason it matters for a stub: `__all__`'s order is what a reader
    diffs, so an unsorted one would reorder on every insertion."""
    names = exported()
    assert list(names) == sorted(names)
    tree = _stub_tree()
    exports = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__all__"
    )
    assert isinstance(exports.value, ast.List)
    listed = [element.value for element in exports.value.elts if isinstance(element, ast.Constant)]
    assert listed == list(names)


def test_every_import_uses_the_explicit_re_export_form() -> None:
    """PEP 484: in a stub a plain `import X` does not re-export, so a type checker refuses a caller
    that touches it. `X as X` is what makes the name part of `omniweave.sdk`'s public surface."""
    for node in _stub_tree().body:
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.asname == alias.name, f"{alias.name} is imported without `as`"


def test_the_stub_imports_from_the_module_the_package_imports_from() -> None:
    """`Gap` is DEFINED in `omniweave_core.store.card` and reaches the SDK through
    `omniweave.sdk.reports`. A stub naming the definition site would publish a second route to the
    same name and disagree with the package about where its surface comes from."""
    sources = {
        node.module
        for node in _stub_tree().body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert sources == set(SOURCES)
    assert sdk_package.Gap.__module__ == "omniweave_core.store.card"
    assert sources == {"omniweave.sdk.reports"}


def test_four_of_the_declared_names_are_a_landed_actions_out_type() -> None:
    """The `out` half of 10:211's source column, asserted: the stub is not merely a copy of
    `reports.py`, it is where an Action's result type becomes a public promise."""
    outs = {spec.out.__name__ for spec in ACTIONS.values()}
    assert outs & set(exported()) == {"AddReport", "CodeRow", "CorporaReport", "DoctorReport"}


# ---------------------------------------------------------------------------------------------
# What the plan prints and the package does not export
# ---------------------------------------------------------------------------------------------


def test_the_five_printed_entry_points_are_owed_and_named() -> None:
    """18 section 1.1's four module-level names and section 1.2's class. Every one waits on
    02:719's ordered sequence, which D323 records as scheduled by no work item."""
    assert owed() == ("Corpus", "corpora", "corpus", "doctor", "explain")
    for name in owed():
        assert not hasattr(sdk_package, name), name


def test_the_stub_does_not_mention_a_symbol_it_is_owed() -> None:
    text = render().decode("utf-8")
    for node in _stub_tree().body:
        if isinstance(node, ast.ImportFrom):
            assert not {alias.name for alias in node.names} & set(owed())
    assert "def corpus" not in text
    assert "class Corpus" not in text


# ---------------------------------------------------------------------------------------------
# `SDK_HOMES`, and the seven signatures 10:211 says come from `inp`
# ---------------------------------------------------------------------------------------------


def test_sdk_homes_covers_every_action_whose_spelling_the_plan_prints() -> None:
    assert set(SDK_HOMES) == set(PRINTED_SIGNATURES)
    for name, printed in PRINTED_SIGNATURES.items():
        home = SDK_HOMES[name]
        assert f"{home.holder}.{home.symbol}" if home.holder else home.symbol
        assert printed.endswith(home.symbol)
        assert printed.startswith("Corpus.") == (home.holder == "Corpus")


def test_the_actions_with_no_sdk_entry_point_are_the_document_pair_and_the_install_verbs() -> None:
    """18:500 routes the document model through `Corpus.doc(ref) -> Doc`, whose accessors 03
    section 13.5 owns. So `doc.grid` and `doc.diff` are a boundary, not a gap.

    `install` and `uninstall` are a gap. 10:32-33 gives every Action an SDK method and the plan
    prints no signature for either, so there is nothing to transcribe into `SDK_HOMES` (D470). The
    two `ow skills` verbs are the same gap."""
    missing = sorted(name for name, spec in ACTIONS.items() if spec.cli and name not in SDK_HOMES)
    assert missing == [
        "doc.diff", "doc.grid", "hooks.check", "install", "skills.check", "skills.hash",
        "skills.install", "skills.ls", "skills.remove", "skills.update", "skills.verify",
        "uninstall",
    ]  # fmt: skip


def test_exactly_two_signatures_are_their_input_types_field_list() -> None:
    """D324. 10:211 says the stub is generated from `inp`, `out` and `name`; it is true of two."""
    assert agreeing() == ("doctor", "explain")
    assert len(_mismatches()) == len(SDK_HOMES) - len(agreeing()) == 5


@pytest.mark.parametrize("name", ["doctor", "explain"])
def test_an_agreeing_signature_really_is_the_field_list(name: str) -> None:
    home = SDK_HOMES[name]
    declared = tuple(field.name for field in fields(ACTIONS[name].inp))
    assert home.parameters == declared


def test_the_handle_supplies_corpus_and_is_not_counted_as_a_difference() -> None:
    """18:261 makes `Corpus` a lazy handle carrying `name`, so `QueryIn.corpus` missing from
    `Corpus.query` is the design. Subtracted before comparing, or every row would be a finding."""
    assert HANDLE_PARAM == "corpus"
    for name, home in SDK_HOMES.items():
        if home.holder != "Corpus":
            continue
        assert HANDLE_PARAM in {field.name for field in fields(ACTIONS[name].inp)}, name
        assert HANDLE_PARAM not in home.parameters, name


def test_the_query_difference_is_a_rename_plus_seven_parameters() -> None:
    line = next(entry for entry in _mismatches() if entry.startswith("query ->"))
    assert "QueryIn declares query" in line
    assert "the SDK takes expand, filters, k, max_blocks, mode, refs, text" in line


def test_coverage_is_the_one_difference_that_narrows_rather_than_widens() -> None:
    """`CoverageIn` declares `scope` and 18:464's `Corpus.coverage()` takes no arguments, so the
    SDK cannot ask the question the Action declares. Every other difference adds."""
    line = next(entry for entry in _mismatches() if entry.startswith("corpus.coverage ->"))
    assert "CoverageIn declares scope" in line
    assert "the SDK takes" not in line
    assert SDK_HOMES["corpus.coverage"].parameters == ()


def test_corpora_is_a_different_operation_under_one_name() -> None:
    line = next(entry for entry in _mismatches() if entry.startswith("corpora ->"))
    assert "CorporaIn declares corpus, detail" in line
    assert "the SDK takes config, names" in line


@pytest.mark.parametrize("name", ["open", "add"])
def test_the_cli_only_flags_reappear_as_sdk_parameters(name: str) -> None:
    """The same widening the CLI showed at D321, in a third surface: `--raw`, `--want-impact`,
    `--schema`, `--allow-cost`, `--allow-egress` and `--wait` are SDK parameters too, and none is
    a declared `inp` field. Three surfaces agree with each other and none agrees with `inp`."""
    line = next(entry for entry in _mismatches() if entry.startswith(f"{name} ->"))
    assert "the SDK takes" in line
    assert "declares" not in line, "these two widen only"


# ---------------------------------------------------------------------------------------------
# The bytes, and the purity behind them
# ---------------------------------------------------------------------------------------------


def test_the_committed_stub_is_byte_for_byte_what_the_generator_produces() -> None:
    assert STUB.read_bytes().replace(b"\r\n", b"\n") == render()


def test_the_stub_is_utf8_with_no_bom_and_one_trailing_newline() -> None:
    raw = render()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.endswith(b"]\n")
    assert not raw.endswith(b"\n\n")
    assert b"\r" not in raw
    raw.decode("utf-8")


def test_the_stub_parses_as_python_and_declares_no_runtime_code() -> None:
    """A stub is declarations. Anything else in it would be code a type checker reads and nothing
    runs -- which is how a `.pyi` drifts from the module it types."""
    body = _stub_tree().body
    allowed = (ast.Expr, ast.ImportFrom, ast.Assign, ast.AnnAssign)
    for node in body:
        assert isinstance(node, allowed), ast.dump(node)[:80]


def test_the_docstring_carries_the_action_table_it_was_generated_from() -> None:
    text = render().decode("utf-8")
    for name, spec in ACTIONS.items():
        assert f"{name:<17} {spec.inp.__name__:<19} {spec.out.__name__}" in text


def test_rendering_twice_gives_the_same_bytes() -> None:
    assert render() == render()


def test_the_generator_reads_no_clock_no_environment_and_no_path() -> None:
    """10:224's ban, over the module that renders artefact 4."""
    source = Path(sdk_stub_module.__file__).read_text(encoding="utf-8")
    banned = {"time", "random", "secrets", "os", "datetime", "pathlib"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            assert not {alias.name.split(".")[0] for alias in node.names} & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module


def _modules_loaded_by(statement: str) -> set[str]:
    code = f"{statement}\nimport json as _j, sys as _s\nprint(_j.dumps(sorted(_s.modules)))"
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return set(json.loads(proc.stdout.strip().splitlines()[-1]))


def test_importing_the_sdk_opens_no_path_to_a_socket() -> None:
    """The stub's own import block is what a type checker walks and what `import omniweave.sdk`
    costs at runtime. D298's charge, on the package this artefact types."""
    loaded = _modules_loaded_by("import omniweave.sdk")
    assert "omniweave.route" not in loaded
    assert loaded.isdisjoint({"_socket", "socket", "email"})
