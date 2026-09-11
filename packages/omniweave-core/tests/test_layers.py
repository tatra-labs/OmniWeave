"""G4 — the layer gate: the module graph obeys `tools/layers.toml`.

A row in `tools/layers.toml` is the **complete allowed set of first-party import roots**
for that package, transitively closed. `omniweave_serve = ["omniweave_core",
"omniweave_ports"]` therefore means that `import omniweave` anywhere under
`omniweave_serve/` is a gate failure — inside a function body and inside an
`if TYPE_CHECKING:` block included (02-architecture.md section 3.2).

The graph is built with `ast`, never with a regex and never by importing. A regex reads
an import out of a docstring, misses one indented into a function and cannot tell a
relative import from an absolute one; importing needs the dependencies installed, which
is precisely the condition a layer violation makes impossible. Walking source is also
what keeps the dev dependency group exactly as charter D1 prints it: there is no
`import-linter` and no `grimp`, because introducing one would put a package's own import
graph between HEAD and the gate that proves HEAD's import graph (02-architecture.md
section 3.3, "Extends the charter").

Enforced in CI by `tools/gate_layers.py`, which W1.7/W1.9 own. This is the same walk in
the test tree. The half a walk cannot do — re-deriving each row from that distribution's
entry points, so no author picks their own row — is below, marked `xfail(strict=True)`
until P3 declares the first `[project.entry-points."omniweave.drivers"]` table.
"""

from __future__ import annotations

import re
import tomllib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the fixtures deliver these; the names are here for the annotations
    from collections.abc import Iterable
    from pathlib import Path

    from conftest import Distribution, ImportSite, PlanDocs, SourceIndex

# The two sites that print the file. 02-architecture.md section 3.2 says "verbatim from
# charter section 3.3", which is a claim a test can settle rather than a reader.
LAYERS_FENCE_SITES: tuple[str, ...] = ("02-architecture.md", "_notes/charter.md")

# 11-repo-layout.md section 1.5: the entry-point *value* is a colon-free dotted package
# path. The card's own `entrypoint` key is `module:attr` and is the one place a colon is
# legal; G4 asserts the shape directly because hatchling, unlike setuptools, writes
# `entry_points.txt` from the table without validating the value at all.
ENTRY_POINT_VALUE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")

DRIVER_ENTRY_POINT_GROUP = "omniweave.drivers"

# Rules 3 and 4 of 02-architecture.md section 3.2, keyed by the Port a driver declares.
ROW_FOR_COMPILE: tuple[str, ...] = ("omniweave_core", "omniweave_ports")
ROW_FOR_EVERYTHING_ELSE: tuple[str, ...] = ("omniweave_ports",)


def _offending_imports(
    own_root: str, allowed: frozenset[str], sites: Iterable[ImportSite]
) -> list[str]:
    """Every import in `sites` naming a first-party root outside `allowed`.

    A package may always import itself; `allowed` is the row. Anything that is not an
    `omniweave*` root is somebody else's gate — D1's purity is `test_purity.py`'s.
    """
    offences: list[str] = []
    for site in sites:
        root = site.module.split(".", 1)[0]
        if not (root == "omniweave" or root.startswith("omniweave_")):
            continue
        if root == own_root or root in allowed:
            continue
        offences.append(str(site))
    return offences


def _driver_entry_points(dist: Distribution) -> dict[str, str]:
    """That distribution's `[project.entry-points."omniweave.drivers"]` table."""
    project = dist.pyproject().get("project")
    if not isinstance(project, dict):
        return {}
    groups = project.get("entry-points")
    if not isinstance(groups, dict):
        return {}
    table = groups.get(DRIVER_ENTRY_POINT_GROUP)
    if not isinstance(table, dict):
        return {}
    return {str(key): str(value) for key, value in table.items()}


def _row_from_entry_points(entry_points: dict[str, str]) -> tuple[str, ...]:
    """Rule 3 / rule 4, derived from the declared driver ids.

    A driver id is `<port>.<family>.<impl>` (04-driver-system.md section 4.1), so the
    Port is the first segment. `tools/gate_layers.py` reads the same fact out of each
    named package's `driver.toml` **without importing it**; the two must agree, and a
    card whose `port` contradicts its entry-point key is that gate's finding, not this
    one's.
    """
    ports = {key.split(".", 1)[0] for key in entry_points}
    return ROW_FOR_COMPILE if "compile" in ports else ROW_FOR_EVERYTHING_ELSE


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


def test_layers_toml_is_verbatim_the_charters_import_dag(
    sources: SourceIndex, plan: PlanDocs
) -> None:
    """`tools/layers.toml` equals the fence both plan documents print.

    02-architecture.md section 3.2 introduces its block as "verbatim from charter
    section 3.3". Three copies of one graph is two chances to edit the wrong one, and
    the copy CI reads is the file — so the file is the subject and the documents are
    the assertion.
    """
    plan.require()
    declared = {key: list(value) for key, value in sources.layers().items()}
    for document in LAYERS_FENCE_SITES:
        printed = [
            fence
            for fence in plan.toml_fences(document)
            if fence and all(str(key).startswith("omniweave") for key in fence)
        ]
        assert len(printed) == 1, f"_plan/{document} prints {len(printed)} layer fences"
        assert printed[0] == declared, f"tools/layers.toml disagrees with _plan/{document}"


def test_every_workspace_member_has_exactly_one_row(sources: SourceIndex) -> None:
    """Fourteen distributions, fourteen rows, and the mapping is name-with-underscores.

    Read off `packages/*/pyproject.toml` rather than a list, so a fifteenth distribution
    fails here on the day it is added rather than on the day someone notices.
    """
    rows = sources.layers()
    members = {dist.layer_key for dist in sources.distributions()}
    assert sorted(rows) == sorted(members)


def test_the_ports_row_is_empty_and_it_is_the_only_empty_row(sources: SourceIndex) -> None:
    """Rule 1. `omniweave-ports` depends on nothing, so a `trust_class` field on a ports
    dataclass would be unspellable (04-driver-system.md sections 1.3 and 5.1)."""
    rows = sources.layers()
    assert rows["omniweave_ports"] == ()
    assert [key for key, value in rows.items() if value == ()] == ["omniweave_ports"]


def test_every_import_root_a_row_names_is_a_real_distribution(sources: SourceIndex) -> None:
    """A row naming a package that does not exist is a row nothing can violate."""
    rows = sources.layers()
    for package, row in sorted(rows.items()):
        assert package not in row, f"{package} lists itself"
        unknown = sorted(set(row) - set(rows))
        assert unknown == [], f"{package} may import undeclared {unknown}"


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------


def test_no_module_imports_above_its_layer(sources: SourceIndex) -> None:
    """G4's first clause, over every `packages/*/src/**/*.py` in the workspace.

    Every `Import` and `ImportFrom` at module, class and function scope, `TYPE_CHECKING`
    blocks included — a layer violation is a fact about the source, and `TYPE_CHECKING`
    hiding one would let a driver name a framework type it may not depend on.
    """
    rows = sources.layers()
    offences: list[str] = []
    for dist in sources.distributions():
        allowed = frozenset(rows[dist.layer_key])
        for root in dist.import_roots:
            for path in sources.files(dist.src / root):
                offences.extend(_offending_imports(root, allowed, sources.imports(path)))
    assert offences == [], "imports above their layer:\n" + "\n".join(offences)


def test_the_walk_detects_a_violation_it_is_shown(sources: SourceIndex, tmp_path: Path) -> None:
    """The negative control, and 02-architecture.md section 3.3's own worked example.

    A gate that has never seen a red is a gate nobody has tested. The two violations
    that document prints are `import omniweave_core.model` under `omniweave-pdf` (a
    parse driver may not hold a `DocSink`) and `from omniweave.run.supervisor import
    run` under `omniweave-serve` (which never runs the Supervisor); both are reproduced
    here against the rows those distributions actually carry.
    """
    rows = sources.layers()
    offender = tmp_path / "driver.py"
    offender.write_text(
        "import omniweave_core.model\n"
        "from omniweave.run.supervisor import run\n"
        "import omniweave_ports\n"
        "import json\n",
        encoding="utf-8",
    )
    sites = sources.imports(offender)

    as_pdf = _offending_imports("omniweave_pdf", frozenset(rows["omniweave_pdf"]), sites)
    assert len(as_pdf) == 2, as_pdf
    assert "omniweave_core.model" in as_pdf[0]

    as_serve = _offending_imports("omniweave_serve", frozenset(rows["omniweave_serve"]), sites)
    assert len(as_serve) == 1, as_serve
    assert "omniweave.run.supervisor" in as_serve[0]


def test_no_source_file_uses_a_relative_import(sources: SourceIndex) -> None:
    """`ban-relative-imports = "all"` (11-repo-layout.md section 8.1's ruff block).

    The layer gate needs it: `from . import store` carries no first-party root to map,
    so a tree that mixes the two spellings has a hole in exactly the place a violation
    would hide. Ruff enforces it on a changed file; this enforces it on the tree.
    """
    offences: list[str] = []
    for dist in sources.distributions():
        for root in dist.import_roots:
            for path in sources.files(dist.src / root):
                offences.extend(str(site) for site in sources.imports(path) if site.level > 0)
    assert offences == [], "relative imports:\n" + "\n".join(offences)


def test_core_may_import_only_ports_and_ports_may_import_nothing(sources: SourceIndex) -> None:
    """Rules 1 and 2, restated as the two rows this distribution is responsible for.

    Stated separately from the walk because these two are the rows P1 freezes: the other
    twelve are derived from entry points that do not exist yet, and these two are not
    derived from anything — they are the charter (02-architecture.md section 3.2).
    """
    rows = sources.layers()
    assert rows["omniweave_core"] == ("omniweave_ports",)
    assert rows["omniweave_ports"] == ()


# ---------------------------------------------------------------------------
# The half a source walk cannot do: no author picks their own row
# ---------------------------------------------------------------------------


def test_every_row_is_re_derived_from_that_distributions_entry_points(
    sources: SourceIndex,
) -> None:
    """G4's second clause: rows 3 and 4 read off the entry points, never chosen.

    "NO AUTHOR PICKS THEIR OWN ROW" is the property that makes the layer graph
    self-derived, and it is the reason adding `omniweave_core` to a parse driver's row
    This was a strict xfail until W3.5 -- "the day a driver distribution declares a card,
    this starts passing and the hand-written rows stop being trusted". That day is
    `omniweave-pdf` declaring `parse.pdf.pdfium`, and the marker came off with it. The rows
    are now derived for every distribution that declares one and hand-written only for the
    ones that do not yet.
    """
    rows = sources.layers()
    declaring = [dist for dist in sources.distributions() if _driver_entry_points(dist)]
    assert declaring, "no distribution declares a driver entry point"
    for dist in declaring:
        expected = _row_from_entry_points(_driver_entry_points(dist))
        assert rows[dist.layer_key] == expected, f"{dist.name}'s row is not its derived row"


def test_every_entry_point_value_is_a_colon_free_dotted_package_that_exists(
    sources: SourceIndex,
) -> None:
    """Two grammars that look alike and are not.

    hatchling writes `entry_points.txt` from the table without validating the value's
    shape at all, so a malformed first-party value would ship and fail on a user's
    machine as a discovery-time refusal. G4 asserts the shape while it is already
    reading the table (11-repo-layout.md section 1.5). Strict-xfailed until W3.5 gave it a
    value to check.
    """
    checked = 0
    for dist in sources.distributions():
        for driver_id, value in sorted(_driver_entry_points(dist).items()):
            assert ":" not in value, f"{dist.name}: {driver_id} -> {value} is module:attr"
            assert "/" not in value, f"{dist.name}: {driver_id} -> {value} is a path"
            assert ENTRY_POINT_VALUE.match(value), f"{dist.name}: {driver_id} -> {value}"
            assert (dist.src / value.replace(".", "/")).is_dir() or (
                dist.src / (value.replace(".", "/") + ".py")
            ).is_file(), f"{dist.name}: {value} names no package in src/"
            checked += 1
    assert checked, "no entry-point value to check"


def test_the_derivation_rules_agree_with_the_plans_worked_shapes(sources: SourceIndex) -> None:
    """The derivation function itself, checked against the rows the plan already fixes.

    `omniweave-pdf` is 11-repo-layout.md section 1.5's worked non-`compile` shape and
    `omniweave-target-pptx` is 02-architecture.md section 3.2's worked `compile` one. So
    the rule can be checked today even though no card declares it today, which is what
    made the two tests above strict xfails for as long as the data was missing rather than
    the code -- and W3.5 supplied the data, so they run.
    """
    rows = sources.layers()
    assert _row_from_entry_points({"parse.pdf.pdfium": "omniweave_pdf"}) == ROW_FOR_EVERYTHING_ELSE
    assert rows["omniweave_pdf"] == ROW_FOR_EVERYTHING_ELSE
    assert _row_from_entry_points({"compile.pptx.oxml": "omniweave_target_pptx"}) == ROW_FOR_COMPILE
    assert rows["omniweave_target_pptx"] == ROW_FOR_COMPILE
    assert _row_from_entry_points({"parse.a.b": "x", "compile.c.d": "y"}) == ROW_FOR_COMPILE, (
        "one compile driver carries the whole distribution to rule 4"
    )


def test_layers_toml_parses_with_one_key_per_physical_line(sources: SourceIndex) -> None:
    """G27 clause (a2) applied to the one declaration file this gate reads.

    Every non-comment, non-blank line is exactly one `key = [...]` row. A row split
    across lines is legal TOML, parses identically, and defeats the line-oriented diff
    that makes a layers change reviewable.
    """
    text = (sources.repo_root / "tools" / "layers.toml").read_text(encoding="utf-8")
    rows = [
        line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(rows) == len(sources.layers())
    for line in rows:
        key, _, value = line.partition("=")
        assert key.strip() in sources.layers()
        assert tomllib.loads(f"x = {value.strip()}")["x"] == list(sources.layers()[key.strip()])
