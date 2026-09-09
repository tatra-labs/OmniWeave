"""The schema lint, tested as a program, and `0004_runtime.sql`, tested as a transcription.

Two halves, because the two failure modes are different and neither test finds the other's.

* **`tools/gate_schema_lint.py` is INV-1's `L` enforcer** (01-principles.md:118-121) and W2.2 names
  its three clauses -- FK-target classification, no second text column, no positional Block
  reference (16-roadmap.md:415), invoked as `uv run tools/gate_schema_lint.py` by P2's exit criteria
  (16-roadmap.md:454). It is green on HEAD here, which is the same statement that shell line makes,
  and it is **shown a red for every clause** over synthetic migration trees in `tmp_path`.
  11-repo-layout.md section 6.8 is the reason the second half is not optional: a lint that has never
  been seen to fail is "a check that cannot yet fail", and the plan counts that as no enforcer at
  all.
* **`schema/migrations/0004_runtime.sql` is the runtime ledger's DDL**, assigned by
  07-store-and-retrieval.md section 3's migration table. The assertions below are the ones a
  transcription can get wrong silently: the object roster, the five deviations erratum E21
  (charter.md:8721) requires the routing block to take from the charter, and the file-level
  properties (no second pragma block, no `migration` row, ASCII).

**This file opens no database.** `sqlite3` is banned outside `omniweave_core/store/` (INV-17;
ruff's `banned-api` at `pyproject.toml:79` has a `per-file-ignores` escape for five paths and no
test root is one of them), so every assertion here is over text. G27(b) --
`tools/gate_migrations.py`, 11-repo-layout.md section 5.2 -- is the half that applies the four
files in numeric order to an empty file on `MIN_SQLITE`; it does not exist yet and its absence is
recorded in `tools/gates.toml`'s G27 row as `runner_planned`.

The gate is loaded by file path with `importlib.util`, never by `importlib.import_module` -- the API
`tools/semgrep/omniweave.yaml` bans outside `host/` -- and never by putting `tools/` on `sys.path`,
which would make the bare name `gate_schema_lint` importable for the rest of the session. That is
`packages/omniweave-core/tests/unit/test_gates_structural.py`'s pattern, and the first four tests
below are its four structural assertions applied to a fifth script it does not yet parametrise over
(its `GATES` tuple holds four names and this file owns none of them; the row it needs is reported to
the owner).

Specified in 16-roadmap.md sections 3 (W2.2) and 5 (the P2 exit line), 01-principles.md INV-1,
07-store-and-retrieval.md section 3, 05-ingest-and-routing.md sections 5.4, 6.4, 7.1 and 8.2, and
02-architecture.md section 3.3 for the stdlib-only, import-free discipline.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import sys
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

GATE = "gate_schema_lint"
"""The script this file owns, as `tools/<name>.py`."""

MIGRATION = "0004_runtime.sql"
"""The migration this file owns, under `schema/migrations/`."""


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def gate(repo_root: Path) -> ModuleType:
    """`tools/gate_schema_lint.py`, loaded under a private name.

    Registered in `sys.modules` under `_owgate_<name>` because it has to be:
    `@dataclass(frozen=True, slots=True)` re-creates the class to add `__slots__`, and resolving
    the `from __future__ import annotations` string annotations on the way through goes via
    `sys.modules[cls.__module__]`.
    """
    path = repo_root / "tools" / f"{GATE}.py"
    spec = importlib.util.spec_from_file_location(f"_owgate_{GATE}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def migration_text(repo_root: Path) -> str:
    return (repo_root / "schema" / "migrations" / MIGRATION).read_text(encoding="utf-8")


def _run(gate: ModuleType, root: Path, argv: list[str] | None = None) -> tuple[int, str]:
    """Run the gate over `root` and capture its report through the injected `TextIO`."""
    buffer = io.StringIO()
    code = gate.main([] if argv is None else argv, out=buffer, root=root)
    return code, buffer.getvalue()


def _tree(root: Path, files: dict[str, str]) -> Path:
    """Write a synthetic `schema/migrations/` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (root / name).write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return root


# The smallest tree that reproduces the two identity tables GR15 is about. Every synthetic
# violation below is this tree plus one statement, so a red names one cause and not a fixture.
L2 = """
    CREATE TABLE block (
      block_id INTEGER PRIMARY KEY,
      doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, page INTEGER NOT NULL,
      addr TEXT NOT NULL, cite TEXT NOT NULL,
      parent_id INTEGER REFERENCES block(block_id),
      text TEXT, quad BLOB
    );
    CREATE TABLE mark (
      block_id INTEGER NOT NULL REFERENCES block(block_id),
      a INTEGER NOT NULL, b INTEGER NOT NULL
    );
"""
L3 = """
    CREATE TABLE entity (entity_id INTEGER PRIMARY KEY, cite TEXT NOT NULL);
    CREATE TABLE mention (
      mention_id INTEGER PRIMARY KEY,
      entity_id INTEGER NOT NULL REFERENCES entity(entity_id),
      block_id INTEGER NOT NULL REFERENCES block(block_id)
    );
"""


@pytest.fixture
def clean(tmp_path: Path) -> Path:
    return _tree(tmp_path / "migrations", {"0001_init.sql": L2, "0002_graph.sql": L3})


# ---------------------------------------------------------------------------
# What a gate script may be made of -- test_gates_structural.py's four, applied here
# ---------------------------------------------------------------------------


def test_the_gate_imports_nothing_first_party(repo_root: Path) -> None:
    """The property that lets a gate run on a tree whose dependencies are not installed.

    02-architecture.md section 3.3: the graph is built with the stdlib `ast` module, "walking source
    rather than importing it -- which also means the gate runs on a package whose dependencies are
    not installed". A schema lint that imported `omniweave_core` to read a table roster would fail
    on exactly the broken tree it exists to diagnose.
    """
    tree = ast.parse((repo_root / "tools" / f"{GATE}.py").read_text(encoding="utf-8"))
    named: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            named.append(node.module or "")
    first_party = [
        module
        for module in named
        if module.split(".", 1)[0] == "omniweave" or module.startswith("omniweave_")
    ]
    assert first_party == [], f"tools/{GATE}.py imports {first_party}"


def test_the_gate_imports_only_the_standard_library(repo_root: Path) -> None:
    """Stdlib only, so the gate needs nothing installed but an interpreter."""
    tree = ast.parse((repo_root / "tools" / f"{GATE}.py").read_text(encoding="utf-8"))
    stdlib = frozenset(sys.stdlib_module_names) | {"__future__"}
    outside: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            outside.extend(
                alias.name for alias in node.names if alias.name.split(".", 1)[0] not in stdlib
            )
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            root = (node.module or "").split(".", 1)[0]
            if root and root not in stdlib:
                outside.append(node.module or "")
    assert outside == [], f"tools/{GATE}.py imports {outside}"


def test_the_gate_never_imports_sqlite3(repo_root: Path) -> None:
    """INV-17's outermost ring, and the reason this lint is an `L` and not an `X`.

    `import sqlite3` is banned outside `omniweave_core/store/` and `tools/` has no
    `per-file-ignores` escape (`pyproject.toml:85-89`). A static scan is what the rung
    01-principles.md:74 assigns INV-1's schema enforcer actually is.
    """
    source = (repo_root / "tools" / f"{GATE}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".", 1)[0] != "sqlite3" for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".", 1)[0] != "sqlite3"


def test_the_gate_never_calls_print(repo_root: Path) -> None:
    """T20 is enabled repo-wide, and the injected `TextIO` is what makes the report testable."""
    tree = ast.parse((repo_root / "tools" / f"{GATE}.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert calls == [], f"tools/{GATE}.py calls print at line(s) {[c.lineno for c in calls]}"


def test_the_gate_names_its_invariant_and_a_plan_locus(gate: ModuleType) -> None:
    """A red gate without a locus is an argument; with one it is a citation."""
    doc = gate.__doc__ or ""
    assert "INV-1" in doc.splitlines()[0], f"tools/{GATE}.py does not name its invariant"
    assert "02-architecture.md section 3.3" in doc
    for locus in ("16-roadmap.md:454", "16-roadmap.md:415", "charter.md:5672"):
        assert locus in doc, f"tools/{GATE}.py cites no {locus}"


def test_the_gate_refuses_arguments_rather_than_ignoring_them(
    gate: ModuleType, clean: Path
) -> None:
    """Exit 2 on an argument, so a mistyped invocation is never a silent green.

    Distinguished from exit 1: 1 is "a clause is false", 2 is "the gate did not run". CI treats
    both as failure and a human needs to know which.
    """
    code, report = _run(gate, clean, ["--all"])
    assert code == gate.EXIT_NOT_RUN
    assert "DID NOT RUN" in report


# ---------------------------------------------------------------------------
# The gate is green on HEAD
# ---------------------------------------------------------------------------


def test_the_gate_is_green_on_head(gate: ModuleType) -> None:
    """`uv run tools/gate_schema_lint.py`, P2's exit-criteria line for INV-1 (16-roadmap.md:454)."""
    buffer = io.StringIO()
    assert gate.main([], out=buffer) == gate.EXIT_CLEAN, buffer.getvalue()


def test_the_gate_classifies_every_shipped_fk_target(gate: ModuleType, repo_root: Path) -> None:
    """The classification is PRINTED on every run, because one nobody can read is unchecked.

    16-roadmap.md:454 spells this gate's job "INV-1, the FK-target classification", so the census
    is part of the report and not an internal. `UNKNOWN` empty is the assertion that matters: every
    foreign key in the shipped DDL names a table some migration creates.
    """
    schema = gate.read_schema(repo_root / "schema" / "migrations")
    census = gate.fk_target_census(schema)
    assert "UNKNOWN" not in census, census.get("UNKNOWN")
    assert census["L2"], "no L2 FK target: the parser found nothing"
    assert "block" in census["L2"]
    assert "entity" in census["L3"]
    assert "route_decision" in census["RUNTIME"]


def test_the_gate_reports_did_not_run_rather_than_green_on_an_absent_tree(
    gate: ModuleType, tmp_path: Path
) -> None:
    """An empty or missing directory is exit 2. A lint over nothing is not a lint that passed."""
    code, report = _run(gate, tmp_path / "nope")
    assert code == gate.EXIT_NOT_RUN
    assert "no such directory" in report
    empty = tmp_path / "empty"
    empty.mkdir()
    code, report = _run(gate, empty)
    assert code == gate.EXIT_NOT_RUN
    assert "no *.sql" in report


# ---------------------------------------------------------------------------
# Clause 1 -- FK-target classification
# ---------------------------------------------------------------------------


def test_clause_1_refuses_an_fk_target_no_migration_creates(gate: ModuleType, clean: Path) -> None:
    """SQLite applies this cleanly and fails on the first insert, which is why a lint must catch it.

    07-store-and-retrieval.md section 3: a foreign key's name is resolved at "the first DML on the
    child row, **not** `CREATE TABLE`", so a migration writes no rows and the typo survives to
    production. The tree is dense (`0001`, `0002`), so the finding is a failure.
    """
    (clean / "0002_graph.sql").write_text(
        L3 + "CREATE TABLE ghost (id INTEGER PRIMARY KEY,"
        " seg INTEGER REFERENCES segmnet(segment_id));\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "fk-target" in report
    assert "segmnet" in report


def test_clause_1_defers_an_unresolvable_target_on_a_tree_that_is_not_dense(
    gate: ModuleType, tmp_path: Path
) -> None:
    """A mid-build tree is not a defect, and G27(b) owns density.

    11-repo-layout.md:1243 gives `tools/gate_migrations.py` the density rule -- "asserts density and
    uniqueness, not just applicability". This gate borrows it as a discriminator only: with the
    prefixes not `1..N`, an unresolvable target is named as `deferred` and does not fail, so landing
    `0003` before `0002` never makes this lint red for a reason its author did not choose.
    """
    root = _tree(
        tmp_path / "m",
        {
            "0004_runtime.sql": "CREATE TABLE work (id INTEGER PRIMARY KEY,"
            " u TEXT REFERENCES unit(unit_uri));\n"
        },
    )
    code, report = _run(gate, root)
    assert code == gate.EXIT_CLEAN
    assert "not 1..N" in report
    assert "deferred" in report
    assert "unit" in report


def test_clause_1_refuses_an_fk_naming_a_column_the_parent_does_not_have(
    gate: ModuleType, clean: Path
) -> None:
    """A target is a `(table, column)` pair, and classifying it means resolving both."""
    (clean / "0002_graph.sql").write_text(
        L3 + "CREATE TABLE bad (id INTEGER PRIMARY KEY, e INTEGER REFERENCES entity(entty_id));\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "entty_id" in report


def test_clause_1_refuses_a_second_table_bridging_both_spaces(
    gate: ModuleType, clean: Path
) -> None:
    """GR15: `mention` is the only table referencing both a `block_id` and an `entity_id`.

    charter.md:5672 and 06-structure-extraction.md:233, and the purpose 06:235 gives -- "that is
    what makes the provenance chain in section 8 a fixed-length walk rather than a search". A
    second bridge makes it a search.
    """
    (clean / "0002_graph.sql").write_text(
        L3 + "CREATE TABLE second_bridge (\n"
        "  id INTEGER PRIMARY KEY,\n"
        "  entity_id INTEGER NOT NULL REFERENCES entity(entity_id),\n"
        "  block_id INTEGER NOT NULL REFERENCES block(block_id)\n);\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "second_bridge" in report
    assert "GR15" in report


def test_clause_1_lets_mention_bridge_and_says_which_tables_it_exempts(gate: ModuleType) -> None:
    """The exemption set is a NAMED ROSTER, so a fifth table is a decision and not a widening.

    Measured over charter.md's own L3 DDL: `edge.observed_block` (:5060),
    `claim.observed_block` (:5100) and `anchor.block_id`/`anchor.entity_id` (:5161-5162) each sit
    beside an `entity(entity_id)` reference, so GR15's statement is false of the plan's own DDL at
    three tables. Reported as a plan defect; carried here as data rather than as a widened rule.
    """
    assert "mention" in gate.GR15_BOTH_SPACES_EXEMPT
    assert set(gate.GR15_BOTH_SPACES_EXEMPT) == {"mention", "edge", "claim", "anchor"}
    for table, why in gate.GR15_BOTH_SPACES_EXEMPT.items():
        assert "charter.md:" in why, f"{table}'s exemption cites no locus"


def test_clause_1_refuses_a_name_declared_twice_across_the_set(
    gate: ModuleType, clean: Path
) -> None:
    """A name is global in `sqlite_master`, so a second `CREATE` aborts a store that ran the first.

    11-repo-layout.md section 5.2's whole subject: "some stores have applied it and some have not,
    and `migration.version` cannot distinguish them".
    """
    (clean / "0003_index.sql").write_text(
        "CREATE TABLE mark (block_id INTEGER REFERENCES block(block_id));\n", encoding="utf-8"
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "duplicate-name" in report
    assert "table mark" in report


# ---------------------------------------------------------------------------
# Clause 2 -- no second text column
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    ["cell_html", "block_markdown", "rendered_md", "source_text", "cell_bbox", "cell_quad"],
)
def test_clause_2_refuses_a_second_copy_column_on_a_table_that_reaches_a_block(
    gate: ModuleType, clean: Path, column: str
) -> None:
    """INV-1's violation list, name by name (01-principles.md:127-130).

    `source_text` is the one with a measured provenance: charter.md:5101 and :5719 reject it by
    name -- "graphrag stores `source_text`, A COPY. A copy drifts on any re-parse. We store the
    reference" -- and 06-structure-extraction.md:37 repeats it. It appears nowhere in the plan's
    DDL, which is what this clause exists to keep true.
    """
    (clean / "0003_index.sql").write_text(
        f"CREATE TABLE derived (id INTEGER PRIMARY KEY,"
        f" block_id INTEGER REFERENCES block(block_id), {column} TEXT);\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "second-copy" in report
    assert f"derived.{column}" in report


def test_clause_2_sees_a_block_two_hops_away(gate: ModuleType, clean: Path) -> None:
    """ "Reaches a Block" is the transitive closure, because a copy two hops away is still a copy.

    `grid_slot` reaches a Block through `cell` (03-document-model.md:1858, :1865), and a
    `cell_html` column there would be marker's `block.html` assignment -- INV-1's **Why** -- at one
    remove.
    """
    (clean / "0003_index.sql").write_text(
        "CREATE TABLE cell (cell_id INTEGER PRIMARY KEY,"
        " block_id INTEGER REFERENCES block(block_id));\n"
        "CREATE TABLE grid_slot (cell_id INTEGER REFERENCES cell(cell_id), cell_html TEXT);\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "grid_slot.cell_html" in report


def test_clause_2_exempts_block_itself_because_it_is_the_one_home(
    gate: ModuleType, clean: Path
) -> None:
    """`block.text` and `block.quad` are the representation, not a second copy.

    `block` reaches a Block through its own `parent_id` self-reference (03-document-model.md:2325),
    so without the exemption this clause would reject the DDL it is written to protect.
    """
    code, report = _run(gate, clean)
    assert code == gate.EXIT_CLEAN, report
    schema = gate.read_schema(clean)
    assert "block" in gate.reaches_block(schema)
    assert "text" in schema.tables["block"].column_names


def test_clause_2_refuses_an_fts_table_holding_its_own_content(
    gate: ModuleType, clean: Path
) -> None:
    """ "An FTS table declared with content of its own" is the last item on INV-1's violation list.

    01-principles.md:115: `block_fts` is an FTS5 **external-content** table "for exactly this
    reason: it indexes `block.text` rather than copying it". A `content=`-less `fts5` is a full
    second copy of every indexed column, and it is invisible in a row count.
    """
    (clean / "0003_index.sql").write_text(
        "CREATE VIRTUAL TABLE greedy_fts USING fts5(text, tokenize='unicode61');\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "greedy_fts" in report
    assert "content of its own" in report


def test_clause_2_accepts_an_external_content_fts_table(gate: ModuleType, clean: Path) -> None:
    """The shipped shape passes, which is what makes the previous test a discrimination."""
    (clean / "0003_index.sql").write_text(
        "CREATE VIRTUAL TABLE head_fts USING fts5(\n"
        "  title, content='block', content_rowid='block_id', tokenize='unicode61');\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_CLEAN, report


# ---------------------------------------------------------------------------
# Clause 3 -- no positional Block reference
# ---------------------------------------------------------------------------


def test_clause_3_refuses_an_fk_into_block_by_addr(gate: ModuleType, clean: Path) -> None:
    """INV-1: never by `addr`. `addr` is positional and generation-keyed (03:1120)."""
    (clean / "0003_index.sql").write_text(
        "CREATE TABLE by_addr (id INTEGER PRIMARY KEY, a TEXT REFERENCES block(addr));\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "positional-ref" in report
    assert "block(addr)" in report


def test_clause_3_refuses_a_composite_fk_into_block(gate: ModuleType, clean: Path) -> None:
    """INV-1's own worked violation: a `FOREIGN KEY (doc_ord, page, ord)` (01-principles.md:131)."""
    (clean / "0003_index.sql").write_text(
        "CREATE TABLE positional (\n"
        "  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, page INTEGER NOT NULL,\n"
        "  ord INTEGER NOT NULL,\n"
        "  FOREIGN KEY (doc_ord, gen, page, ord) REFERENCES block(doc_ord, gen, page, ord)\n);\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "positional-ref" in report
    assert "doc_ord" in report


def test_clause_3_refuses_a_cite_keyed_reference_to_a_block(gate: ModuleType, clean: Path) -> None:
    """`cite` is the only identifier that may enter a prompt (INV-8) and is not an FK target.

    03-document-model.md:1054's identity table gives each of the four identities one job, and
    "conflating any two is the failure this section exists to prevent" (:1049).
    """
    (clean / "0003_index.sql").write_text(
        "CREATE TABLE by_cite (id INTEGER PRIMARY KEY, c TEXT REFERENCES block(cite));\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "block(cite)" in report


@pytest.mark.parametrize("column", ["block_addr", "block_cite", "block_page", "block_ord"])
def test_clause_3_refuses_a_column_naming_a_block_by_position(
    gate: ModuleType, clean: Path, column: str
) -> None:
    """A positional reference with no FK at all is the shape an FK check alone cannot see."""
    (clean / "0003_index.sql").write_text(
        f"CREATE TABLE loose (id INTEGER PRIMARY KEY, {column} TEXT);\n", encoding="utf-8"
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert f"loose.{column}" in report


def test_clause_3_does_not_flag_a_bare_cite_column_and_the_reason_is_measured(
    gate: ModuleType, clean: Path
) -> None:
    """Four different row types own a `cite`, and only one of them is about a Block.

    `block` (charter.md:1035), `entity` (:1101), `claim` (:1208), `community` (:1320) and
    `artifact_cite` (:1444). `artifact_cite` is the one that IS about a Block, and there `cite` sits
    beside `block_id INTEGER REFERENCES block(block_id)` -- the surrogate is already the reference,
    so a lint on the bare name would reject the plan's own DDL. Clause 3's checkable reading is a
    `REFERENCES` clause plus the unambiguously qualified names above.
    """
    (clean / "0005_out.sql").write_text(
        "CREATE TABLE artifact_cite (\n"
        "  artifact_id INTEGER NOT NULL, unit TEXT NOT NULL, el TEXT NOT NULL,\n"
        "  cite TEXT NOT NULL,\n"
        "  block_id INTEGER REFERENCES block(block_id),\n"
        "  doc_gen INTEGER NOT NULL,\n"
        "  PRIMARY KEY (artifact_id, unit, el, cite)\n) WITHOUT ROWID;\n",
        encoding="utf-8",
    )
    (clean / "0003_index.sql").write_text(
        "CREATE TABLE eval_assertion (assertion_id TEXT PRIMARY KEY, addr TEXT);\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_CLEAN, report


def test_clause_3_notices_a_block_primary_key_that_is_not_the_surrogate(
    gate: ModuleType, tmp_path: Path
) -> None:
    """A column-less `REFERENCES block` resolves to `block`'s PK, so the PK is part of the clause.

    03-document-model.md:2319: `block_id` is the "DURABLE surrogate; the only FK target FOR A
    BLOCK". If the PK moved, every abbreviated foreign key in the framework would quietly re-point.
    """
    root = _tree(
        tmp_path / "m",
        {
            "0001_init.sql": "CREATE TABLE block (\n"
            "  doc_ord INTEGER NOT NULL, gen INTEGER NOT NULL, addr TEXT NOT NULL,\n"
            "  PRIMARY KEY (doc_ord, gen, addr)\n);\n"
        },
    )
    code, report = _run(gate, root)
    assert code == gate.EXIT_FAIL
    assert "block PRIMARY KEY" in report


# ---------------------------------------------------------------------------
# The parser, where a wrong answer would make a clause vacuous
# ---------------------------------------------------------------------------


def test_the_splitter_keeps_a_trigger_body_whole(gate: ModuleType, repo_root: Path) -> None:
    """A trigger body's inner `;` is not a statement terminator, and every shipped trigger has one.

    charter.md:3148 (`block_fts_ai`), :4070 (`work_no_live_delete`) and :2851
    (`route_decision_monotone`). Splitting naively on `;` would cut each in half and the second
    fragment would parse as nothing, which makes every clause silently blind to the file.
    """
    path = repo_root / "schema" / "migrations" / MIGRATION
    statements = gate.split_statements(path.read_text(encoding="utf-8"), path)
    triggers = [s for s in statements if "CREATE TRIGGER" in s.blank]
    assert len(triggers) == 2, [s.line for s in triggers]
    for statement in triggers:
        assert statement.blank.strip().endswith("END;")
        assert "RAISE(ABORT" in statement.raw


def test_the_splitter_survives_a_case_expression_in_a_view(
    gate: ModuleType, repo_root: Path
) -> None:
    """`CASE ... END` has an `END` and no `BEGIN`; `route_scoreboard` has three of them."""
    path = repo_root / "schema" / "migrations" / MIGRATION
    statements = gate.split_statements(path.read_text(encoding="utf-8"), path)
    views = [s for s in statements if "CREATE VIEW" in s.blank]
    assert len(views) == 2, [s.line for s in views]
    scoreboard = next(s for s in views if "route_scoreboard" in s.blank)
    # Five `CASE`, and every one of them balanced by an `END`: two inside the `q` CTE's
    # `SUM(CASE WHEN source='audit' ...)` pair and three in the outer SELECT (divergence,
    # escalation_divergence, state). The count is asserted so a rewrite of the view that dropped a
    # branch cannot pass this test by accident.
    assert scoreboard.blank.count("CASE") == 5
    assert scoreboard.blank.count("END") == 5
    assert "BEGIN" not in scoreboard.blank
    assert scoreboard.blank.strip().endswith(";")


def test_blanking_hides_a_semicolon_and_a_paren_inside_a_string_literal(gate: ModuleType) -> None:
    """A `;`, `(` or `,` inside a `'...'` or a `--` comment must not move the parser.

    `RAISE(ABORT,'OW-S-014 refusing to delete a live work row')` and every `CHECK (x IN ('a','b'))`
    depend on this; so does a comment containing the word `CREATE TABLE`.
    """
    sql = "CREATE TABLE t (a TEXT DEFAULT 'x;(,y');  -- CREATE TABLE ghost (id INTEGER);\n"
    blanked = gate.blank_noise(sql)
    assert len(blanked) == len(sql)
    assert ";(," not in blanked
    assert "ghost" not in blanked
    assert blanked.count("\n") == sql.count("\n")


def test_the_parser_reports_a_real_line_number(gate: ModuleType, clean: Path) -> None:
    """An offset in the blanked copy indexes the original, which is what makes a finding usable."""
    (clean / "0003_index.sql").write_text(
        "-- a header comment\n"
        "CREATE TABLE derived (\n"
        "  id INTEGER PRIMARY KEY,\n"
        "  block_id INTEGER REFERENCES block(block_id),\n"
        "  cell_html TEXT\n"
        ");\n",
        encoding="utf-8",
    )
    code, report = _run(gate, clean)
    assert code == gate.EXIT_FAIL
    assert "0003_index.sql:5" in report


# ---------------------------------------------------------------------------
# 0004_runtime.sql, as a transcription
# ---------------------------------------------------------------------------

# 07-store-and-retrieval.md section 3's 0004 row, verbatim and in its order. The twelve named
# tables plus the `route_*` glob.
RUNTIME_TABLES = (
    "unit",
    "work",
    "work_done",
    "cache_index",
    "dep",
    "cohort",
    "cohort_member",
    "budget_reservation",
    "run",
    "service_observation",
    "driver_observation",
    "driver_card_cache",
)
ROUTE_TABLES = (
    "route_decision",
    "route_unit_decision",
    "route_evidence",
    "route_signal",
    "route_spend",
    "route_quality",
    "route_threshold",
)


def test_0004_creates_the_twelve_named_tables_in_section_3s_order(
    gate: ModuleType, repo_root: Path
) -> None:
    """07-store-and-retrieval.md section 3's 0004 row is the per-file assignment, order included."""
    path = repo_root / "schema" / "migrations" / MIGRATION
    statements = gate.split_statements(path.read_text(encoding="utf-8"), path)
    created = [
        gate._unquote(match.group(2))
        for statement in statements
        if (match := gate._CREATE_TABLE.match(statement.blank)) is not None
    ]
    assert created[: len(RUNTIME_TABLES)] == list(RUNTIME_TABLES)
    for table in ROUTE_TABLES:
        assert table in created, table
    assert created.index("route_decision") > created.index("driver_card_cache")


def test_0004_creates_every_route_star_object(gate: ModuleType, repo_root: Path) -> None:
    """`route_*` is 07 section 3's glob; 05-ingest-and-routing.md:2647 says every one is here."""
    schema = gate.read_schema(repo_root / "schema" / "migrations")
    owners = {
        name: table.statement.file.name
        for name, table in schema.tables.items()
        if name.startswith("route_")
    }
    assert owners, "no route_* table found in the migration set"
    assert set(owners.values()) == {MIGRATION}, owners
    assert set(owners) == set(ROUTE_TABLES)
    assert schema.views["route_scoreboard"].file.name == MIGRATION


def test_0004_is_self_contained_so_it_needs_no_earlier_file_at_all(
    gate: ModuleType, repo_root: Path
) -> None:
    """Every `REFERENCES` in this file names a table this file creates. Measured, not assumed.

    07-store-and-retrieval.md section 3's table records 0004 as depending on 0001, and the real
    dependency runs the other way: `block.decision_id` in `0001_init.sql` is "the one forward
    foreign key in the shipped order". Two foreign keys inside this file are forward too --
    `budget_reservation.run_id` and `.decision_id` -- and all three are safe because a parent is
    resolved at the first DML on the child row, not at `CREATE TABLE`.
    """
    path = repo_root / "schema" / "migrations" / MIGRATION
    schema = gate.read_schema(path.parent)
    own = {n for n, t in schema.tables.items() if t.statement.file.name == MIGRATION}
    outward = sorted(
        {
            fk.parent_table
            for fk in schema.foreign_keys
            if fk.statement.file.name == MIGRATION and fk.parent_table not in own
        }
    )
    assert outward == [], outward
    forward = {
        fk.parent_table
        for fk in schema.foreign_keys
        if fk.child_table == "budget_reservation" and fk.parent_table != "work"
    }
    assert forward == {"run", "route_decision"}


def test_0004_takes_erratum_e21s_five_deviations_from_the_charter(migration_text: str) -> None:
    """The routing block is 05's, not charter.md:2808-2932's. charter erratum E21 (:8721).

    Five deviations, each checked: `route_decision.cost_class` and `.reason` are ADDED,
    `route_evidence.payload` is NULLABLE and gains `swept_at`, `route_scoreboard` pre-aggregates
    each one-to-many child in its own CTE, and there is deliberately NO `route_decision`
    `dispatch_key`. E21's own note says why the view is the half that matters: it "returns wrong
    numbers rather than merely fewer columns".
    """
    assert "cost_class       TEXT NOT NULL" in migration_text
    assert "    reason           TEXT," in migration_text
    assert "payload BLOB," in migration_text
    assert "payload BLOB NOT NULL" not in migration_text
    assert "swept_at INTEGER," in migration_text
    assert "CHECK ((payload IS NULL) = (swept_at IS NOT NULL))" in migration_text
    scoreboard = migration_text.split("CREATE VIEW route_scoreboard AS", 1)[1]
    assert "WITH q AS" in scoreboard
    assert "), sp AS (" in scoreboard
    assert scoreboard.count("COALESCE") >= 4
    decision = migration_text.split("CREATE TABLE route_decision (", 1)[1].split(");", 1)[0]
    assert "dispatch_key" not in decision


def test_0004_holds_the_two_triggers_the_plan_generates_and_their_codes(
    migration_text: str,
) -> None:
    """Both are triggers and not CHECKs, because SQLite prohibits a subquery in a CHECK.

    `work_no_live_delete` raises `OW-S-014` (charter.md:4072, 08-runtime.md:171) and
    `route_decision_monotone` raises `OW-R-030` (charter.md:2854, 05-ingest-and-routing.md:2709,
    01-principles.md:400). Neither code has a `codes.toml` row yet; the file says so and the rows
    are reported to that register's owner.
    """
    assert "CREATE TRIGGER work_no_live_delete BEFORE DELETE ON work" in migration_text
    assert "'OW-S-014 refusing to delete a live work row'" in migration_text
    assert "CREATE TRIGGER route_decision_monotone BEFORE INSERT ON route_decision" in (
        migration_text
    )
    assert "'OW-R-030 escalation is not monotone'" in migration_text


def test_0004_declares_no_pragma_and_writes_no_migration_row(
    gate: ModuleType, repo_root: Path, migration_text: str
) -> None:
    """Two omissions, both derived rather than forgotten, and both stated in the file's header.

    The pragma sequence is `0001_init.sql`'s and its order is load-bearing (07 section 2.1); a
    second copy would be a second home for one setting. The `migration` row is the applier's,
    because `migration` is created by `0003_index.sql` (07 section 3.8) and `0001`/`0002` therefore
    cannot insert their own -- the table does not exist when they run.

    Asserted over the STATEMENTS and not the file text: the header explains both omissions and
    therefore contains both words, so a text search would fail on the explanation.
    """
    path = repo_root / "schema" / "migrations" / MIGRATION
    for statement in gate.split_statements(path.read_text(encoding="utf-8"), path):
        upper = statement.blank.upper()
        assert "PRAGMA" not in upper, statement.line
        # `BEFORE INSERT` is a trigger's timing clause, not a write, so the assertion is on the
        # DML form. This file's two triggers are `BEFORE DELETE` and `BEFORE INSERT`.
        assert "INSERT INTO" not in upper, statement.line
    assert "NO PRAGMA BLOCK HERE" in migration_text
    assert "0003_index.sql (07 section 3.8)" in migration_text


def test_0004_records_its_three_per_file_migration_facts(migration_text: str) -> None:
    """11-repo-layout.md section 5.1: three things "a later operator needs and cannot re-derive".

    `cost_class` (`ddl`/`backfill`/`rebuild`), whether it is `resumable`, and the REQUIRED PROSE
    `unbackfilled_means` that `ow doctor` prints verbatim (07 section 3.8's `migration` DDL). With
    no row to carry them in this file, the header carries them for whoever writes the applier.
    """
    assert "cost_class = 'ddl'" in migration_text
    assert "resumable = 0" in migration_text
    assert "unbackfilled_means" in migration_text


def test_0004_carries_the_columns_the_plan_names_and_the_charter_ddl_omits(
    gate: ModuleType, repo_root: Path
) -> None:
    """`unit.trust_class` is named as a column at eight sites and declared at none.

    05-ingest-and-routing.md:110 and :172 ("The host stamps `unit.trust_class` from
    `SourceLocator.trust_class`"), :1030, :2848 (the audit sampler reads it) and :2140, which
    registers it as an evidence key with domain `{internal, untrusted_external}`, cost FREE, est 0
    and `null` = no. `charter.md:3991-4014`'s `CREATE TABLE unit` has no such column. NOT NULL with
    no DEFAULT: a default would silently pick one of the two the plan states for two different
    connector classes.
    """
    schema = gate.read_schema(repo_root / "schema" / "migrations")
    unit = schema.tables["unit"]
    assert "trust_class" in unit.column_names
    body = unit.statement.raw
    declared = "trust_class    TEXT NOT NULL CHECK (trust_class IN"
    assert declared in body
    assert "('internal','untrusted_external'))" in body
    assert "trust_class TEXT NOT NULL DEFAULT" not in body


def test_0004_lands_resolution_report_and_spend_attribution(
    gate: ModuleType, repo_root: Path, migration_text: str
) -> None:
    """Two objects 07 section 3's 0004 row does not name and no other row names either.

    `resolution_report` sits inside charter.md's own `#### Routing DDL` block (:2937), which 07
    section 3 globs as `route_*` -- and the glob loses the one name in the block that is not
    `route_`-prefixed. `spend_attribution` is 15-observability.md section 5.2's view and every one
    of its three inputs is created above it here. Both are reported to the owner; both are landed
    because the alternative is an object with no migration at all.
    """
    schema = gate.read_schema(repo_root / "schema" / "migrations")
    assert schema.tables["resolution_report"].statement.file.name == MIGRATION
    assert schema.views["spend_attribution"].file.name == MIGRATION
    assert "charter.md:2937" in migration_text
    assert "15-observability.md section 5.2" in migration_text


def test_0004_declares_dep_reverse_over_two_columns_not_three(migration_text: str) -> None:
    """The plan contradicts itself and the printed statement wins, three loci to one.

    `CREATE INDEX dep_reverse ON dep(kind, key)` at charter.md:4156 and 12-performance.md:1118, and
    "ONE query on dep_reverse(kind, key)" at 12-performance.md:1400, against
    07-store-and-retrieval.md:989's index-register Shape cell `(kind, key, digest)`. Reported.
    """
    assert "CREATE INDEX dep_reverse ON dep(kind, key);" in migration_text
    assert "dep(kind, key, digest)" not in migration_text


def test_0004_is_ascii_lf_and_ends_in_exactly_one_newline(repo_root: Path) -> None:
    """House style, and for SQL it is more than style: a non-ASCII dash is not a comment marker."""
    raw = (repo_root / "schema" / "migrations" / MIGRATION).read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    text = raw.decode("utf-8")
    assert text.isascii(), sorted({c for c in text if not c.isascii()})
    # U+2014 as an escape, not as a literal: house style writes `--`, and in SQL `--` is also the
    # comment marker, so an em-dash that slipped in would be a syntax error rather than a typo.
    assert "\u2014" not in text
