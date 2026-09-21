"""The two declaration files P1 seeds are well-formed and internally consistent.

`codes.toml` is the single append-only error register (G13) whose reader is
`omniweave_core.errors` (02-architecture.md section 2 row 6), and `tools/layers.toml` is the
import DAG whose first two rules are statements about this distribution (section 3.2 rules 1
and 2). Both are therefore checked from here rather than from a workspace-level test tree that
`[tool.pytest.ini_options] testpaths` does not reach.

None of this replaces the gates: `tools/gate_layers.py` (G4) re-derives every layers row from
entry points, and `ow explain --check` closes the half of `codes-unique` an adjacency rule
cannot see (18-api-sketch.md section 9 item 7). These are the declaration-shape assertions that
hold before either exists.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]

# The ten area letters of 02-architecture.md section 7.2, which are exactly the ten OwError
# subclasses. ResourceLimit is cross-area and allocates no letter of its own.
AREA_LETTERS = frozenset("CMDRSGTAPQ")

NUMERIC = re.compile(r"^OW-[A-Z]-\d{3}$")
SYMBOL = re.compile(r"^OW_[A-Z0-9_]{3,}$")


def _codes() -> dict[str, object]:
    return tomllib.loads((REPO / "codes.toml").read_text(encoding="utf-8"))


def _layers() -> dict[str, list[str]]:
    return tomllib.loads((REPO / "tools" / "layers.toml").read_text(encoding="utf-8"))


def test_codes_register_declares_the_ten_areas() -> None:
    assert set(_codes()["area"]) == set(AREA_LETTERS)


def test_every_code_row_is_well_formed() -> None:
    for row in _codes()["code"]:
        assert NUMERIC.match(row["numeric"]), row
        assert SYMBOL.match(row["symbol"]), row
        assert row["numeric"][3] in AREA_LETTERS, row
        assert row["sites"], f"{row['numeric']} cites no plan definition site"


def test_the_exit_table_is_well_formed_and_in_numeric_order() -> None:
    """18-api-sketch.md section 2.3's twelve rows, beside the `OW-*` register because
    18-api-sketch.md:996 puts them there. This is the declaration-SHAPE half; `test_errors.py`
    holds the rows to `omniweave_core.errors.EXIT_CODES` and to the classes they name."""
    rows = _codes()["exit"]
    codes = [row["code"] for row in rows]
    assert codes == sorted(codes), "a reader scans this table by number"
    assert len(set(codes)) == len(codes)
    for row in rows:
        assert isinstance(row["code"], int), row
        assert row["slug"] and row["meaning"], row
        assert row.get("classes") or row.get("note"), f"exit {row['code']} says nothing it is"


def test_codes_unique_holds_in_both_directions() -> None:
    """A numeric bound to two symbols, or a symbol bound to two numerics, is the same build
    failure seen from the other end. Reading has already failed twice on exactly this
    (18-api-sketch.md section 9 item 7), which is why it is a test and not an eyeball."""
    rows = _codes()["code"]
    numerics = [row["numeric"] for row in rows]
    symbols = [row["symbol"] for row in rows]
    assert len(set(numerics)) == len(numerics)
    assert len(set(symbols)) == len(symbols)


def test_the_layer_graph_has_one_row_per_distribution() -> None:
    """The number fourteen is a literal in 11-repo-layout.md section 1.2, in charter section
    3.2 and in docs/ARCHITECTURE.md; section 1.10 resolves it against the package count so the
    literal cannot drift silently."""
    dists = sorted(p.parent.name for p in (REPO / "packages").glob("*/pyproject.toml"))
    assert len(dists) == 14
    assert sorted(_layers()) == sorted(name.replace("-", "_") for name in dists)


def test_every_layer_row_names_only_declared_packages_and_never_itself() -> None:
    rows = _layers()
    for package, row in rows.items():
        assert package not in row, f"{package} lists itself"
        unknown = sorted(set(row) - set(rows))
        assert unknown == [], f"{package} may import undeclared {unknown}"


def test_the_layer_graph_is_acyclic_and_transitively_closed() -> None:
    """A row is the COMPLETE allowed set of first-party import roots, transitively closed
    (02-architecture.md section 3.2). Closure is what makes membership a single lookup for
    tools/gate_layers.py rather than a graph walk per import site."""
    rows = _layers()
    for package, row in rows.items():
        for dependency in row:
            assert package not in rows[dependency], f"cycle: {package} <-> {dependency}"
            missing = sorted(set(rows[dependency]) - set(row))
            assert missing == [], f"{package} is not closed over {dependency}: {missing}"
