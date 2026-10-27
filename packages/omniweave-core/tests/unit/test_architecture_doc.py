"""`docs/ARCHITECTURE.md` is held to the code, clause by clause. **D986.**

11-repo-layout.md section 8.6 adds G27 clause (d) by adopting graphify's mechanism, and records
what drift cost there: *"It had drifted to document six functions that do not exist ... Anyone
following it wrote code that raised, or -- worse for `extract()` -- code that ran and silently
produced non-canonical ids."* The adopted rule is that the test **parses the document rather than
restating it**, so a row added to the table is checked without anyone editing this file.

## What this covers, and what it does not

Section 8.6 gives the clause five parts over `docs/ARCHITECTURE.md` **and** `docs/plan/*.md`:
d0 the walk found something, d1 symbols import, d2 registers resolve, d3 links resolve, d4 the
count ratchets. **This file is the ARCHITECTURE.md half**: d0, d1 and d2's checkable shapes over
one document, with the floor stated for that document rather than for the whole set.

D991 committed the plan documents, so `tools/gate_docs.py` can now walk both sets and the
520-symbol floor in `tools/gates.toml` is meetable; writing it is the next cell. This file does
not become redundant then -- it keeps the one document a contributor actually reads honest at the
test tier, where a failure names the symbol rather than a gate step, and its own floor stays
asserted because a regex that matched nothing would make every assertion below it vacuous, which
is exactly the failure clause d0 exists to prevent.

## Rulings

1. **A symbol is a dotted name under one of the three roots**, matched by `_SYMBOL` -- the shape
   section 8.6's d1 row prints -- and a bare root with no dotted tail is not a symbol: d0 owns the
   roots, and there is nothing to import-check about `omniweave_core` alone.
2. **Resolution is import-then-getattr, longest module prefix first.** `omniweave_core.model.doc`
   is a module and `omniweave_core.model.doc.Doc` is an attribute of one, and the document names
   both shapes; trying the longest prefix first is what lets one regex cover them.
3. **A command, a gate id and a register path are checked against their own register**, never
   against a list in this file: `ACTIONS` for `ow <group> <verb>`, `tools/gates.toml` for `G<n>`,
   and the filesystem for a `tools/*.toml` or `eval/*.toml` path. A hand-kept copy here would be
   one more thing to drift.
4. **Every distribution has a row.** The table is checked against
   `glob("packages/*/pyproject.toml")`, so adding a distribution without documenting it fails, and
   so does documenting one that does not exist.

Specified in 11-repo-layout.md sections 8.6 and 1.2, and G27 clause (d) in section 6.4.
"""

from __future__ import annotations

import importlib
import re
import tomllib
from pathlib import Path
from typing import Final

import pytest

REPO: Final = Path(__file__).resolve().parents[4]
DOC: Final = REPO / "docs" / "ARCHITECTURE.md"
REGISTER: Final = REPO / "tools" / "gates.toml"
ROOTS: Final = ("omniweave_core", "omniweave_ports", "omniweave")
SYMBOL_FLOOR: Final = 25
"""Ruling 1 and clause d0: the floor for THIS document. `tools/gates.toml`'s 520 is the floor for
the nineteen plan documents plus this one, and it cannot be met until they are committed."""

_SYMBOL: Final = re.compile(r"`(omniweave(?:_[a-z]+)*(?:\.[a-z_]+)+(?:\.[A-Za-z_]\w*)?)`")
_VERB: Final = re.compile(r"`ow ([a-z]+)(?: ([a-z][a-z-]*))?`")
_GATE: Final = re.compile(r"`(G\d+)`")
_REGISTER_PATH: Final = re.compile(r"`((?:tools|eval)/[a-z_]+\.toml|codes\.toml)`")
_TABLE_ROW: Final = re.compile(r"^\| `(omniweave[a-z-]*)` \| `([a-z_]+)` \|", re.MULTILINE)


def _text() -> str:
    return DOC.read_text(encoding="utf-8")


def _symbols() -> list[str]:
    return sorted(set(_SYMBOL.findall(_text())))


def _resolve(dotted: str) -> str:
    """Ruling 2: the longest importable prefix, then `getattr` for the rest."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for attr in parts[cut:]:
            if not hasattr(target, attr):
                return f"no attribute {attr!r}"
            target = getattr(target, attr)
        return ""
    return "no such module"


def test_the_document_exists_and_says_what_it_is_for() -> None:
    assert DOC.is_file(), "11-repo-layout.md section 8.6: docs/ARCHITECTURE.md is a named file"
    text = _text()
    assert "test_architecture_doc.py" in text, (
        "graphify's rule is that the document says its table is checked; a document that does not "
        "say so gets read as prose and drifts"
    )


def test_the_walk_found_something() -> None:
    """Clause d0, the one most adopters drop: a regex that matches nothing passes everything."""
    found = _symbols()
    assert len(found) >= SYMBOL_FLOOR, f"{len(found)} symbol(s) matched, floor is {SYMBOL_FLOOR}"
    roots = {one.split(".")[0] for one in found}
    assert set(ROOTS) <= roots, f"missing root(s): {sorted(set(ROOTS) - roots)}"


@pytest.mark.parametrize("dotted", _symbols())
def test_every_symbol_the_document_names_imports(dotted: str) -> None:
    """Clause d1. The failure message is the symbol, because that is what has to be fixed."""
    why = _resolve(dotted)
    assert not why, f"{dotted}: {why}"


def test_every_command_the_document_names_is_in_the_action_registry() -> None:
    """Clause d2 for `ow <group> <verb>`: INV-20 makes the registry the one source of the surface,
    so a command this document invents is a command no surface has."""
    actions = importlib.import_module("omniweave.surface.registry").ACTIONS
    names = set(actions)
    groups = {name.split(".")[0] for name in names}
    unknown = []
    for group, verb in _VERB.findall(_text()):
        if verb:
            #  The CLI spells a verb with hyphens and the registry with underscores
            #  (`ow eval release-check` is `eval.release_check`).
            if f"{group}.{verb.replace('-', '_')}" not in names:
                unknown.append(f"ow {group} {verb}")
        elif group not in names and group not in groups:
            unknown.append(f"ow {group}")
    assert unknown == [], unknown


def test_every_gate_the_document_names_is_in_the_register() -> None:
    """Clause d2 for `G<n>`: the series' cardinality lives in tools/gates.toml, so a cited row
    either exists there or is a number this document made up."""
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    rows = {str(row["id"]) for row in register["gate"]}
    cited = set(_GATE.findall(_text()))
    assert cited, "the document cites no gate; section 5 is supposed to name the load-bearing ones"
    assert cited <= rows, sorted(cited - rows)


def test_every_register_path_the_document_names_is_a_file() -> None:
    """Clause d2 and d3: a register this document points at has to be there to point at."""
    missing = [one for one in set(_REGISTER_PATH.findall(_text())) if not (REPO / one).is_file()]
    assert missing == []


def test_every_distribution_has_exactly_one_row_and_no_row_invents_one() -> None:
    """Ruling 4: the table is checked against the workspace, in both directions."""
    documented = dict(_TABLE_ROW.findall(_text()))
    workspace = {
        tomllib.loads(path.read_text(encoding="utf-8"))["project"]["name"]
        for path in sorted((REPO / "packages").glob("*/pyproject.toml"))
    }
    assert set(documented) == workspace, {
        "undocumented": sorted(workspace - set(documented)),
        "invented": sorted(set(documented) - workspace),
    }
    for dist, package in documented.items():
        assert package == dist.replace("-", "_"), f"{dist}'s import package is {package}"
        assert importlib.import_module(package), package


def test_every_documented_import_package_is_the_one_the_dist_installs() -> None:
    """The row's second column is the thing a reader types after `import`, so it is checked by
    importing it -- which is also what proves the workspace is synced before the suite trusts the
    rest of this file."""
    for _dist, package in _TABLE_ROW.findall(_text()):
        module = importlib.import_module(package)
        assert module.__name__ == package
