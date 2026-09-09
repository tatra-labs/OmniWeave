"""`0002_graph.sql` and `0003_index.sql`, asserted as artefacts rather than trusted as prose.

Specified in 07-store-and-retrieval.md section 3 (the per-file object assignment, the three-way
forward-reference rule, and sections 3.2 through 3.8, which are normative for every L4 statement),
with charter.md:4830-5250 ("The owgraph DDL") as L3's DDL home, 06-structure-extraction.md sections
1.3-1.6 for the census and the vocabularies, 11-repo-layout.md sections 5.1 and 5.2 for the
migration mechanism, and 16-roadmap.md section 3.3 for the phase column.

**THE ORDER IS LOAD-BEARING AND THE PLAN SAYS WHY.** 11-repo-layout.md:1188: "`0002_graph.sql`
precedes `0003_index.sql` because L4 indexes and foreign keys reference L3 tables, and the reverse
ordering was a real defect -- an index on a table a later file creates aborts the migration and
**neither file applies**." So `0003` may name `0002`'s objects and `0002` may never name `0003`'s,
and that asymmetry is asserted here in both directions: once as "no object this file creates an
index or trigger on is created later", and once as "`0002` alone stands on `0001` alone".

**WHY THIS FILE DOES NOT APPLY THE MIGRATIONS TO A DATABASE.** It cannot: `sqlite3` is banned
outside `omniweave_core/store/` (INV-17, 01-principles.md:483 -- "`G24` bans `conn.commit()`,
`BEGIN` and `import sqlite3` outside `omniweave_core/store/`"), and the ban is enforced here by
ruff `TID251`, whose `per-file-ignores` roster (11-repo-layout.md:2187-2194, mirrored verbatim in
`pyproject.toml`) contains no entry for a test tree or for `tools/`. Applying the files is G27(b)'s
job and G27(b)'s runner is `tools/gate_migrations.py` (`tools/gates.toml`, `runner_planned`), which
is not written yet and needs that roster row when it is. What this file asserts instead is the
*name-resolution* property the recorded failure was about -- which object each file creates and
which objects each statement names -- statement by statement, over the file bytes, with no
database. The two halves are complementary and neither is a substitute: an apply run proves the
DDL is valid SQL, and this proves the object assignment is 07 section 3's.

The assertions here are deliberately over the FILE and not over `sqlite_master`, because
`sqlite_master` cannot distinguish "created by `0002`" from "created by `0003`" once both have
applied, and the per-file assignment is the whole subject.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest
from conftest import MIGRATIONS_DIR as MIGRATIONS

GRAPH = MIGRATIONS / "0002_graph.sql"
INDEX = MIGRATIONS / "0003_index.sql"

# ---------------------------------------------------------------------------------------------
# The rosters, transcribed with their loci. These are the plan's own lists and not a re-derivation
# from the files -- a test that reads its expectation out of its subject asserts nothing.
# ---------------------------------------------------------------------------------------------

# 07-store-and-retrieval.md:237, the `0001_init.sql` row of section 3's table, verbatim. Needed
# because a BACKWARD reference from 0002 or 0003 into L2 must resolve somewhere, and 0001 is
# another cluster's file: this is the declared contract, not an observation of its bytes.
L2_OBJECTS: frozenset[str] = frozenset(
    {
        "meta",
        "enum_val",
        "doc",
        "page",
        "producer",
        "block",
        "block_history",
        "rel",
        "mark",
        "table_meta",
        "cell",
        "grid_slot",
        "part",
        "asset",
        "block_asset",
        "page_render",
        "diag",
        "block_fts",
    }
)

# 07-store-and-retrieval.md:238, the `0002_graph.sql` row of section 3's table, verbatim.
# charter.md:4834, verbatim and in its order: "enum_val gains the CLOSED domains: 'lane',
# 'akind', 'alias_kind', 'claim_status', 'taint', 'precision'." Six, and exactly these six --
# `0001_init.sql` owns L2's nine and no third file seeds any.
L3_ENUM_DOMAINS: frozenset[str] = frozenset(
    {"lane", "akind", "alias_kind", "claim_status", "taint", "precision"}
)

L3_TABLES: frozenset[str] = frozenset(
    {
        "segmenter",
        "segment",
        "segment_block",
        "derive_pass",
        "derive_run",
        "derive_cover",
        "entity",
        "entity_alias",
        "mention",
        "edge",
        "edge_evidence",
        "claim",
        "entity_merge",
        "entity_band",
        "anchor",
        "relation_vocab",
        "etype_vocab",
        "quarantine",
        "graph_history",
        "community",
        "community_member",
        "community_report",
        "graph_observation",
    }
)

# 07-store-and-retrieval.md:240 and :241, the `0004_runtime.sql` and `0005_out.sql` rows. Every
# name here is a FORWARD reference from this cluster's point of view, which is legal for a foreign
# key and fatal for an index or a trigger.
LATER_OBJECTS: frozenset[str] = frozenset(
    {
        # 0004_runtime.sql
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
        "route_decision",
        "route_unit_decision",
        "route_evidence",
        "route_signal",
        "route_spend",
        "route_quality",
        "route_threshold",
        "resolution_report",
        # 0005_out.sql
        "artifact",
        "artifact_unit",
        "artifact_asset",
        "artifact_cite",
        "artifact_el",
    }
)

# The L4 tables 07 section 3 prints in sections 3.5 through 3.8, in the order it prints them.
# `head_fts` and `block_tri` are the two VIRTUAL tables and are listed separately below, because
# fts5 also materialises shadow tables and a count over `CREATE TABLE` alone must not include them.
L4_TABLES: frozenset[str] = frozenset(
    {
        "ref_site",  # section 3.5
        "ref_attempt",  # section 3.5
        "block_sec",  # section 3.6
        "block_link",  # section 3.6
        "embed_space",  # section 3.7
        "ingest_scope",  # section 3.8
        "index_state",  # section 3.8
        "stat",  # section 3.8
        "migration",  # section 3.8
    }
)

# 07 section 3.13's register, the rows whose `Owner` column reads 0002 or 0003. Section 3.13 is not
# an exhaustive index list -- it is the corpus-wide register of the indexes the QUERY PATH depends
# on -- so this is a subset assertion in one direction only.
REGISTER_0002: frozenset[str] = frozenset(
    {"anchor_corpus", "anchor_name", "segment_block_seg", "mention_block"}
)
REGISTER_0003: frozenset[str] = frozenset(
    {
        "segment_digest_ix",
        "segment_doc",
        "segment_restricted",
        "block_sec_path",
        "block_link_identity",
        "block_link_out",
        "block_link_in",
        "block_link_bound",
        "block_link_restricted",
        "ref_site_block",
        "ref_site_name",
    }
)


# ---------------------------------------------------------------------------------------------
# A statement reader. Comments and string literals are removed first, because both can contain a
# `;`, a `(`, or the word BEGIN, and every classification below is a keyword match.
# ---------------------------------------------------------------------------------------------


class Stmt(NamedTuple):
    """One DDL statement: the SQL with comments stripped, plus what it creates and names."""

    sql: str
    verb: str  # 'table' | 'virtual table' | 'index' | 'unique index' | 'view' | 'trigger'
    name: str  # the object created
    on: str  # for an index / trigger, the table it is created ON; else ''


def _decomment(sql: str) -> str:
    """Drop every `--` comment, leaving string literals intact.

    A comment marker inside a quoted string is not a comment (`'--'` never occurs in these two
    files, but a reader that assumed so would be wrong the first time it did), and a quote inside
    a comment is not a string, which is the case that actually bites: `-- don't` would otherwise
    swallow the rest of the file.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        if sql[i] == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":  # a doubled quote escapes itself
                        j += 2
                        continue
                    break
                j += 1
            out.append(sql[i : j + 1])
            i = j + 1
        elif sql.startswith("--", i):
            j = sql.find("\n", i)
            if j == -1:
                break
            out.append("\n")
            i = j
        else:
            out.append(sql[i])
            i += 1
    return "".join(out)


def _split(sql: str) -> list[str]:
    """Split on `;`, except inside a `CREATE TRIGGER ... BEGIN ... END;` body.

    A trigger body holds its own statement terminators, so a naive split cuts a trigger into
    fragments and every keyword match downstream reads the fragments instead of the trigger. None
    of the shipped triggers nests a `BEGIN`, so one flag is enough; a nested one would need a
    counter and would also be a statement no reviewer should accept.
    """
    stmts: list[str] = []
    buf: list[str] = []
    in_body = False
    for piece in re.split(r"(\bBEGIN\b|\bEND\b|;)", sql, flags=re.IGNORECASE):
        buf.append(piece)
        upper = piece.upper()
        if upper == "BEGIN" and re.match(r"\s*CREATE\s+TRIGGER\b", "".join(buf), re.IGNORECASE):
            in_body = True
        elif upper == "END" and in_body:
            in_body = False
        elif piece == ";" and not in_body:
            text = "".join(buf).strip()
            if text.rstrip(";").strip():
                stmts.append(text)
            buf = []
    assert not "".join(buf).strip(), f"trailing text after the last `;`: {''.join(buf)!r}"
    return stmts


_CREATE = re.compile(
    r"""^\s*CREATE\s+
        (?P<verb>VIRTUAL\s+TABLE|UNIQUE\s+INDEX|TABLE|INDEX|VIEW|TRIGGER)\s+
        (?P<name>[a-z_][a-z0-9_]*)""",
    re.IGNORECASE | re.VERBOSE,
)
_ON = re.compile(r"\bON\s+(?P<table>[a-z_][a-z0-9_]*)\s*[(\s]", re.IGNORECASE)
_TRIGGER_ON = re.compile(
    r"\bAFTER\s+(?:INSERT|UPDATE|DELETE)(?:\s+OF\s+[a-z0-9_,\s]+)?\s+ON\s+"
    r"(?P<table>[a-z_][a-z0-9_]*)",
    re.IGNORECASE,
)


_ENUM_SEED = re.compile(r"\s*INSERT\s+INTO\s+enum_val\b", re.IGNORECASE)
"""The ONE non-CREATE statement these files may carry: 0002's six closed domains (charter.md:4834).

Skipped here rather than allowed a `verb`, because a `Stmt` is a created OBJECT throughout this
module -- every roster assertion, the forward-reference walk and the both-files-disjoint check all
read `name` as "the object this statement creates", and a seed statement creates nothing. It is
matched narrowly on the table name so that an `INSERT INTO segment` still trips the assertion
below, which is the property 16-roadmap.md:466 ("the tables exist and are empty") actually needs.
`test_every_statement_is_a_create_and_no_rows_are_written` is where the seeds are checked.
"""


def _parse_text(text: str, label: str) -> tuple[Stmt, ...]:
    out: list[Stmt] = []
    for raw in _split(_decomment(text)):
        if _ENUM_SEED.match(raw):
            continue
        m = _CREATE.match(raw)
        assert m is not None, f"{label}: not a CREATE statement: {raw[:80]!r}"
        verb = " ".join(m.group("verb").lower().split())
        name = m.group("name")
        on = ""
        if verb in {"index", "unique index"}:
            hit = _ON.search(raw[m.end() :])
            assert hit is not None, f"{label}: no ON target in {name}"
            on = hit.group("table")
        elif verb == "trigger":
            hit = _TRIGGER_ON.search(raw)
            assert hit is not None, f"{label}: no ON target in trigger {name}"
            on = hit.group("table")
        out.append(Stmt(sql=raw, verb=verb, name=name, on=on))
    return tuple(out)


def _parse(path: Path) -> tuple[Stmt, ...]:
    return _parse_text(path.read_text(encoding="utf-8"), path.name)


@pytest.fixture(scope="module")
def graph() -> tuple[Stmt, ...]:
    return _parse(GRAPH)


@pytest.fixture(scope="module")
def index() -> tuple[Stmt, ...]:
    return _parse(INDEX)


def _named(stmts: tuple[Stmt, ...], *verbs: str) -> frozenset[str]:
    return frozenset(s.name for s in stmts if s.verb in verbs)


def _fk_targets(stmt: Stmt) -> frozenset[str]:
    return frozenset(re.findall(r"\bREFERENCES\s+([a-z_][a-z0-9_]*)", stmt.sql, re.IGNORECASE))


def _content_target(stmt: Stmt) -> str:
    """The `content='<table>'` an external-content fts5 table resolves its columns against.

    07 section 3.3: an external-content table with a column the content table does not have
    raises `no such column` at CREATE time, so this target is resolved exactly as eagerly as an
    index's and belongs in the same backward-reference check.
    """
    hit = re.search(r"content\s*=\s*'([a-z_][a-z0-9_]*)'", stmt.sql, re.IGNORECASE)
    return hit.group(1) if hit else ""


# ---------------------------------------------------------------------------------------------
# 1. the artefacts themselves
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", [GRAPH, INDEX], ids=["0002_graph", "0003_index"])
def test_the_file_exists_under_the_shipped_name(path: Path) -> None:
    """`NNNN_<slug>.sql`, four digits, in `schema/migrations/` (11-repo-layout.md section 5.1).

    Packaged with `omniweave-core` as package data and read through `importlib.resources` at use
    time, which is why the name and the directory are part of the contract and not a convention.
    """
    assert path.is_file(), f"{path} is missing"
    assert re.fullmatch(r"\d{4}_[a-z][a-z0-9_]*\.sql", path.name)


@pytest.mark.parametrize("path", [GRAPH, INDEX], ids=["0002_graph", "0003_index"])
def test_encoding_is_ascii_lf_and_one_trailing_newline(path: Path) -> None:
    """ASCII in SQL, LF, UTF-8, exactly one trailing newline.

    `.gitattributes` declares `*.sql text eol=lf` and `schema/** text eol=lf`, so a CRLF here is a
    byte-diff failure on the Windows cells of the nine-cell matrix rather than a cosmetic one.
    """
    raw = path.read_bytes()
    assert b"\r" not in raw, f"{path.name}: CR byte present"
    raw.decode("ascii")  # raises on any non-ASCII, which is the assertion
    assert raw.endswith(b"\n"), f"{path.name}: no trailing newline"
    assert not raw.endswith(b"\n\n"), f"{path.name}: more than one trailing newline"


@pytest.mark.parametrize("path", [GRAPH, INDEX], ids=["0002_graph", "0003_index"])
def test_no_line_exceeds_one_hundred_columns(path: Path) -> None:
    """Line length 100, the same ceiling `[tool.ruff] line-length` sets for Python."""
    over = [
        (n, len(line))
        for n, line in enumerate(path.read_text(encoding="ascii").split("\n"), start=1)
        if len(line) > 100
    ]
    assert over == [], f"{path.name}: lines over 100 columns: {over}"


@pytest.mark.parametrize("path", [GRAPH, INDEX], ids=["0002_graph", "0003_index"])
def test_the_file_opens_with_a_header_naming_its_plan_section(path: Path) -> None:
    """House style: every file opens with a header naming the plan section it implements."""
    head = path.read_text(encoding="ascii").split("\n", 8)
    assert head[0].startswith(f"-- {path.name}"), head[0]
    joined = "\n".join(head)
    assert "07-store-and-retrieval.md section 3" in joined
    assert "11-repo-layout.md:1188" in joined


@pytest.mark.parametrize("path", [GRAPH, INDEX], ids=["0002_graph", "0003_index"])
def test_no_if_not_exists_anywhere(path: Path) -> None:
    """07 section 3.3: "the shipped DDL uses no `IF NOT EXISTS`".

    That is what makes a duplicated object name an ABORT rather than a silent no-op, and the abort
    is the mechanism G27(b) relies on to catch a name collision between two migration files.

    Asserted over the DECOMMENTED body: both headers quote the clause, and a test that scanned the
    raw bytes would forbid the file from explaining why the clause exists.
    """
    body = _decomment(path.read_text(encoding="ascii"))
    assert not re.search(r"IF\s+NOT\s+EXISTS", body, re.IGNORECASE)


@pytest.mark.parametrize("path", [GRAPH, INDEX], ids=["0002_graph", "0003_index"])
def test_the_transaction_belongs_to_the_runner_not_the_file(path: Path) -> None:
    """No `BEGIN`/`COMMIT`/`ROLLBACK` outside a trigger body, and no `PRAGMA`.

    11-repo-layout.md section 5.1: migrations are "applied forward-only in numeric order, one
    transaction each" -- the runner owns the transaction, so a file that opens its own cannot be
    rolled back with the `migration` row that records it. The pragmas are per connection and per
    file-create (07 section 2.1's CONN_PRAGMAS / INIT_PRAGMAS / CREATE_PRAGMAS), never per
    migration, and `busy_timeout` must be first for reasons a migration file cannot honour.
    """
    body = _decomment(path.read_text(encoding="ascii"))
    for stmt in _split(body):
        if not re.match(r"\s*CREATE\s+TRIGGER\b", stmt, re.IGNORECASE):
            assert not re.search(r"\bBEGIN\b", stmt, re.IGNORECASE), stmt[:80]
    assert not re.search(r"\b(COMMIT|ROLLBACK|PRAGMA)\b", body, re.IGNORECASE)


@pytest.mark.parametrize("path", [GRAPH, INDEX], ids=["0002_graph", "0003_index"])
def test_every_statement_is_a_create_and_no_rows_are_written(path: Path) -> None:
    """These tables are created EMPTY, and "empty" means no rows -- not a blank file.

    16-roadmap.md section 3.3 ("P2 creates them **empty**; P8 fills them") and 16-roadmap.md:466
    ("No `segment` rows and no L3 rows: the tables exist and are empty"). Three populations are
    therefore deliberately absent and each has a different owner:

    * `etype_vocab`'s fifteen builtin rows and `relation_vocab`'s thirteen
      (06-structure-extraction.md section 1.6) -- P8's;
    `enum_val`'s six L3 domains ARE seeded here and are the exception this test allows. That was
    once the other way round, and the citation that settled it is charter.md:4834, which describes
    THIS FILE and says outright: "enum_val gains the CLOSED domains: 'lane', 'akind', 'alias_kind',
    'claim_status', 'taint', 'precision'." Settled law assigns the six domains to 0002.

    The contrary argument -- that 03-document-model.md section 15.3 gives the write to the
    migration STEP ("regenerates `enum_val` from the Python enums"), so a literal INSERT would be a
    second writer -- is right about the MECHANISM and does not reach the OUTCOME. Section 15.3
    fixes where the truth lives; charter.md:4834 fixes which file the domains belong to. Abstaining
    left `enum_val` holding NINE of the fifteen closed domains after all four migrations, which no
    reading permits and which nothing detected, because `0001_init.sql` seeds L2's nine literally
    and every test compared only what was present against what was expected to be present.
    test_enum_val_parity.py is the assertion that now closes both directions.
    * `index_state`'s `schema` row and this file's own `migration` row -- also the runner's, and
      G27(b) checks the first at the END of the run (11-repo-layout.md:1196-1200).

    Every statement being a `CREATE` is most of the property, and the rest is that no DML hides
    inside one. `ON DELETE CASCADE` and `ON DELETE SET NULL` are referential ACTIONS and not
    statements, so the scan is for the statement forms and not for the bare keywords.
    """
    for stmt in _parse(path):
        assert stmt.verb in {"table", "virtual table", "index", "unique index", "view", "trigger"}
    dml = re.compile(r"\b(INSERT\s+INTO|REPLACE\s+INTO|DELETE\s+FROM|UPDATE\s+\w+\s+SET)\b", re.I)
    # `enum_val` is the ONE table these two files may write, and only 0002 may: charter.md:4834
    # assigns it six closed domains. Scoped to that table by name so that a write to any other --
    # an `etype_vocab` row, a `segment` row, a `meta` row -- still fails. The parity of those rows
    # against the Python enums is test_enum_val_parity.py's, not this test's.
    seed = re.compile(r"\bINSERT\s+INTO\s+enum_val\b", re.IGNORECASE)
    for stmt in _split(_decomment(path.read_text(encoding="ascii"))):
        # An fts5 sync trigger's BODY is INSERTs by construction and writes no row at DDL time; the
        # `'delete'` command row is how an external-content table is told to drop a posting.
        if re.match(r"\s*CREATE\s+TRIGGER\b", stmt, re.IGNORECASE):
            continue
        if seed.search(stmt):
            assert path is GRAPH, f"only 0002 seeds enum_val (charter.md:4834), not {path.name}"
            # ...and it may write NOTHING BUT the six domains that file is assigned.
            written = set(re.findall(r"\('([a-z_]+)',\s*\d+,", stmt))
            assert written <= L3_ENUM_DOMAINS, f"0002 seeded {sorted(written - L3_ENUM_DOMAINS)}"
            continue
        assert not dml.search(stmt), stmt[:80]


# ---------------------------------------------------------------------------------------------
# 2. the per-file object assignment is 07 section 3's
# ---------------------------------------------------------------------------------------------


def test_0002_creates_exactly_section_3s_twenty_three_l3_tables(graph: tuple[Stmt, ...]) -> None:
    """The `0002_graph.sql` row of 07 section 3's table, neither short nor long."""
    assert _named(graph, "table") == L3_TABLES
    assert len(L3_TABLES) == 23


def test_0002_creates_its_thirty_two_indexes_and_seven_of_them_are_unique(
    graph: tuple[Stmt, ...],
) -> None:
    """The count is stated so a dropped index is a failure and not a diff nobody reads.

    Seven UNIQUE: `derive_run_identity`, `entity_cite`, `edge_identity`, `claim_identity`,
    `claim_cite`, `entity_merge_pair` and `community_cite`. Four of the seven are ST10 identities
    with `IFNULL` sentinels or a partial predicate, which is why they are standalone indexes.
    """
    assert len(_named(graph, "index", "unique index")) == 32
    assert _named(graph, "unique index") == {
        "derive_run_identity",
        "entity_cite",
        "edge_identity",
        "claim_identity",
        "claim_cite",
        "entity_merge_pair",
        "community_cite",
    }


def test_0002_creates_the_two_views_over_its_own_tables(graph: tuple[Stmt, ...]) -> None:
    """`community_report_fresh` (charter.md:5237) and `ow_entity_head`.

    `ow_entity_head` EXTENDS THE CHARTER: 06-structure-extraction.md section 1.5 declares it and is
    its only home. 07 section 3's file table lists only tables, so the file is a choice; it lands
    here because its base table does, exactly as `ow_block_head` follows `block` in
    `0001_init.sql`, and because 07 section 3.2's own argument for `ow_segment_head` is that a view
    belongs beside the objects it reads. Either way the reference is backward.
    """
    assert _named(graph, "view") == {"community_report_fresh", "ow_entity_head"}


def test_0003_creates_exactly_the_l4_tables_section_3_prints(index: tuple[Stmt, ...]) -> None:
    """Nine ordinary tables plus the two fts5 virtual tables, and nothing else.

    The `vec` and `events` sidecars (sections 3.9 and 3.10) are separate database FILES and their
    objects carry the owner "events" in section 3.13's register, so they are not here; `asset`,
    `part` and `page_render` (section 3.11) are `0001_init.sql`'s and the five `cache_index`
    objects (section 3.12) are `0004_runtime.sql`'s. Section 3 discusses all of them without
    owning their DDL.
    """
    assert _named(index, "table") == L4_TABLES
    assert _named(index, "virtual table") == {"head_fts", "block_tri"}


def test_0003_creates_the_eleven_indexes_section_3_13_gives_it(index: tuple[Stmt, ...]) -> None:
    """Section 3.13's register rows whose owner is 0003, exactly, plus no twelfth.

    Section 3.13 is not an exhaustive index list for the store, but for THIS file it happens to be
    complete: every index 07 section 3 prints in sections 3.2 through 3.8 has a register row.
    """
    assert _named(index, "index", "unique index") == REGISTER_0003
    assert _named(index, "unique index") == {"block_link_identity"}


def test_0003_creates_three_views_and_six_triggers(index: tuple[Stmt, ...]) -> None:
    """`ow_segment_head`, `ref_unresolved`, `ow_ref_resolved`; two fts5 trigger sets of three."""
    assert _named(index, "view") == {"ow_segment_head", "ref_unresolved", "ow_ref_resolved"}
    assert _named(index, "trigger") == {
        "head_fts_ai",
        "head_fts_ad",
        "head_fts_au",
        "block_tri_ai",
        "block_tri_ad",
        "block_tri_au",
    }


def test_the_register_rows_owned_by_0002_are_all_present(graph: tuple[Stmt, ...]) -> None:
    """A subset assertion: section 3.13 lists only the query path's indexes, so 0002 has more."""
    assert _named(graph, "index", "unique index") >= REGISTER_0002


def test_no_object_name_is_declared_in_both_files(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """One namespace for everything in `sqlite_master`, tables and triggers alike.

    07 section 3.3 prices the collision: "printing `block_fts_ai` a second time in
    `0003_index.sql` would abort G27(b) ... and by the same forward-reference rule that governs
    the migration order above, **neither file would apply**."
    """
    assert not ({s.name for s in graph} & {s.name for s in index})


def test_0003_does_not_redeclare_0001s_block_fts_triggers_or_ow_block_head(
    index: tuple[Stmt, ...],
) -> None:
    """The specific collision 07 section 3.3 names, asserted by name.

    charter.md:3148-3160 re-prints `block_fts_ai`/`_ad`/`_au` inside its L4 fence and
    charter.md:3310 re-prints `ow_block_head`; both ship in `0001_init.sql`
    (03-document-model.md section 13.1), and 07 section 3.3 is the later, normative site that
    forbids the repetition.
    """
    forbidden = {"block_fts_ai", "block_fts_ad", "block_fts_au", "ow_block_head", "block_fts"}
    assert not (forbidden & {s.name for s in index})


# ---------------------------------------------------------------------------------------------
# 3. the order, in both directions -- the assertion this file exists for
# ---------------------------------------------------------------------------------------------


def _created_by_file(graph: tuple[Stmt, ...], index: tuple[Stmt, ...]) -> dict[str, int]:
    """Object name -> the migration number that creates it, over 0001 declared plus 0002-0003."""
    where = dict.fromkeys(L2_OBJECTS, 1)
    where["ow_block_head"] = 1  # 03 section 13.1's DDL block, beside `block`
    for stmt in graph:
        where[stmt.name] = 2
    for stmt in index:
        where[stmt.name] = 3
    return where


@pytest.mark.parametrize("number", [2, 3], ids=["0002_graph", "0003_index"])
def test_every_eagerly_resolved_reference_is_backward(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...], number: int
) -> None:
    """An index, a trigger and an external-content fts5 table resolve their table AT CREATE TIME.

    07 section 3's three-way rule, and the branch that aborts: "an **index** | `CREATE INDEX` |
    **aborts**, and takes G27b's whole run with it. This is the failure above, and it is why L3
    precedes L4." A trigger's `ON` target and an external-content table's `content=` target resolve
    just as eagerly, so all three are checked together.
    """
    where = _created_by_file(graph, index)
    stmts = graph if number == 2 else index
    for stmt in stmts:
        targets = {stmt.on} if stmt.on else set()
        if stmt.verb == "virtual table":
            targets.add(_content_target(stmt))
        for target in targets - {""}:
            assert target in where, f"{stmt.name} names unknown object {target!r}"
            assert where[target] <= number, (
                f"0{number:03d}: {stmt.verb} {stmt.name} is created ON {target}, "
                f"which 0{where[target]:03d} creates -- an index or trigger resolves its table at "
                f"CREATE time, so this aborts the migration and NEITHER FILE APPLIES "
                f"(11-repo-layout.md:1188)"
            )


def test_0002_names_no_object_that_0003_creates(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """The recorded defect, stated as its own assertion because it is the one that happened.

    "Under the earlier numbering, `0002` created an index on `segment`, a table `0003` had not
    created yet, so `no such table: main.segment` aborted the migration and **neither file
    applied**" (07 section 3, 11-repo-layout.md:1188). This is a whole-text scan and not only an
    `ON`-target scan: a foreign key to a 0003 table would survive `CREATE TABLE` and then fail at
    the first row, which is worse, not better.
    """
    later = {s.name for s in index}
    body = _decomment(GRAPH.read_text(encoding="ascii"))
    words = set(re.findall(r"[a-z_][a-z0-9_]*", body))
    # The scan is not vacuous: it sees this file's own object names, so a miss is a real miss.
    assert {s.name for s in graph} <= words
    for word in words:
        assert word not in later, f"0002_graph.sql names {word!r}, which 0003_index.sql creates"


def test_0002_alone_stands_on_0001_alone(graph: tuple[Stmt, ...]) -> None:
    """Applying 0001 then 0002 and stopping must leave nothing unresolved but the forward FK.

    This is the second direction the brief for this cluster requires, and it is not implied by the
    previous test: 0002 could avoid every 0003 name and still lean on 0004's.
    """
    own = {s.name for s in graph}
    for stmt in graph:
        if stmt.on:
            assert stmt.on in own | L2_OBJECTS, f"{stmt.name} is ON unresolvable {stmt.on!r}"
        for target in _fk_targets(stmt):
            assert target in own | L2_OBJECTS | LATER_OBJECTS, (
                f"{stmt.name} references unknown table {target!r}"
            )


def test_the_forward_foreign_keys_in_this_cluster_are_exactly_one(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """A foreign key MAY point forward; SQLite resolves the parent at the first DML, not at DDL.

    07 section 3: "a **foreign key** | the first DML on the child row, **not** `CREATE TABLE` |
    survives -- SQLite performs no DDL-time parent lookup, and a migration writes no rows." The
    one in this cluster is `derive_run.decision_id -> route_decision` (charter.md:4950).

    NOTE FOR THE PLAN'S OWNER, and this test is where it is pinned: 07-store-and-retrieval.md:249
    says "**The one forward foreign key in the shipped order is `block.decision_id ->
    route_decision`**". Counted from DEFINITION SITES rather than mentions, `REFERENCES
    route_decision` appears at eight sites in `charter.md` and two of them are forward:
    `block.decision_id` at charter.md:1062 (in `0001_init.sql`) and `derive_run.decision_id` at
    charter.md:4950 (here). The other six -- charter.md:2833, :2864, :2884, :2899, :4029 and
    :4185 -- are all inside `0004_runtime.sql` and so are same-file. The RULE is unaffected and
    the exception 07 takes is still correct; the count is one short.
    """
    forward = {
        (stmt.name, target)
        for stmt in (*graph, *index)
        for target in _fk_targets(stmt)
        if target in LATER_OBJECTS
    }
    assert forward == {("derive_run", "route_decision")}


def test_no_index_or_trigger_in_this_cluster_points_forward_at_all(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """The complement of the previous test: the surviving branch is FK-only, never eager."""
    for stmt in (*graph, *index):
        if stmt.verb in {"index", "unique index", "trigger"}:
            assert stmt.on not in LATER_OBJECTS, f"{stmt.name} is ON a later file's {stmt.on}"


def test_index_state_is_created_by_0003_which_is_why_g27b_asserts_at_the_end(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """11-repo-layout.md:1196-1200, and the mistake those lines describe, not repeated here.

    "G27(b) then asserts, **at the end of the run and not after `0001_init.sql`**, that
    `index_state` and `meta` are each in exactly one home. ... The anchor is the end of the run
    because `index_state` is created by `0003_index.sql` -- an assertion written against
    `0001_init.sql` is unrunnable, since the table does not yet exist."

    So this asserts the *premise* of that anchoring rather than the assertion itself: `index_state`
    is in 0003 and in neither of the two earlier rosters, and `meta` is 0001's and is not
    re-declared here. Whether `index_state.schema` equals `f"{SCHEMA}.{SCHEMA_MINOR}"` is a
    statement about a store AFTER the whole sequence has run and one `migration`-writing runner has
    written it, and no assertion in this file may be written as though a migration file put it
    there.
    """
    assert "index_state" in _named(index, "table")
    assert "index_state" not in L2_OBJECTS
    assert "index_state" not in _named(graph, "table")
    assert "meta" in L2_OBJECTS
    assert "meta" not in {s.name for s in (*graph, *index)}
    assert not re.search(
        r"\bmeta\b", _decomment(INDEX.read_text(encoding="ascii")), re.IGNORECASE
    ), "0003 must not write `meta`; ADR-9 puts `schema` in `index_state` and nowhere else"


# ---------------------------------------------------------------------------------------------
# 4. the vocabularies, against the one site that applies the ordinal rule
# ---------------------------------------------------------------------------------------------


def _check_list(stmts: tuple[Stmt, ...], table: str, column: str) -> tuple[str, ...]:
    """The literals of a `CHECK(<column> IN (...))` on `table`, in the order they are written."""
    sql = next(s.sql for s in stmts if s.verb == "table" and s.name == table)
    hit = re.search(
        rf"CHECK\s*\(\s*{column}\s+IN\s*\((?P<items>[^)]*)\)", sql, re.IGNORECASE | re.DOTALL
    )
    assert hit is not None, f"no CHECK ... IN on {table}.{column}"
    return tuple(re.findall(r"'([^']*)'", hit.group("items")))


def _enum_val_rows() -> tuple[tuple[str, int, str], ...]:
    """`omniweave_core.model.enums.enum_val_rows()`, imported INSIDE the call and not at module
    scope.

    `model` is one of the nine LAZY subpackages (11-repo-layout.md section 1.3), and
    `test_config.py::test_importing_config_loads_none_of_the_nine_lazy_subpackages` asserts that
    none of them appears in `sys.modules`. Its instrument is the SHARED `sys.modules` of one pytest
    session, not a fresh interpreter, so any module-level import anywhere in the tree fails it --
    which that test's own comment already records for `drivers`: "Listing it here made this
    assertion fail the moment any sibling test module imported `omniweave_core.drivers.card`".
    Pytest imports every test module at COLLECTION, so a module-scope import here would run before
    that test does. Deferring it into the call means this file contributes nothing to `sys.modules`
    unless a test that actually needs an ordinal runs, and those sort after `test_config.py`.
    `tests/test_g17.py` asserts the same property in a SUBPROCESS, which is the instrument that
    cannot be polluted, and it is unaffected either way.
    """
    from omniweave_core.model.enums import enum_val_rows  # noqa: PLC0415

    return enum_val_rows()


def _domain(domain: str) -> tuple[str, ...]:
    """The member names of one `enum_val` domain, in ordinal order, from the ONE derivation.

    Read from `enum_val_rows()` rather than transcribed: that function is the single site that
    applies 03 section 2.1's ordinal rule, and a literal here that happened to agree today is
    exactly the second truth "CI asserts parity in both directions" (charter.md:939) forbids.
    """
    return tuple(name for dom, _ord, name in _enum_val_rows() if dom == domain)


@pytest.mark.parametrize(
    ("table", "column", "domain"),
    [
        ("entity_alias", "alias_kind", "alias_kind"),
        ("claim", "status", "claim_status"),
        ("claim", "t_precision", "precision"),
    ],
)
def test_a_check_vocabulary_equals_its_enum_val_domain_in_order(
    graph: tuple[Stmt, ...], table: str, column: str, domain: str
) -> None:
    """Three of the six domains 0002 brings into use are also CHECK lists, and they must agree.

    charter.md:4834 says this file is where `enum_val` "gains the CLOSED domains: 'lane', 'akind',
    'alias_kind', 'claim_status', 'taint', 'precision'". Three of the six are enforceable in the
    schema and are enforced: `entity_alias.alias_kind`, `claim.status` and `claim.t_precision`. The
    other three are not, for three different reasons -- `taint` is a BITMASK and every subset of it
    is legal; `akind` is `TEXT NOT NULL` with no CHECK in either charter.md:5156 or 07 section 3.5,
    deliberately, because `anchor` and `ref_site` are in different migration files and two CHECK
    lists would be two truths; and `lane` reaches `derive_pass.lanes` as a JSON ARRAY, which a
    scalar `IN` list cannot constrain.

    Order is asserted, not just membership: `enum_val.ord` for a `StrEnum` IS declaration order
    and IS the stored value, so a CHECK list in a different order is a document that reads as
    agreeing while the ordinals it implies are wrong.
    """
    assert _check_list(graph, table, column) == _domain(domain)


def test_claim_status_is_the_enum_val_domain_and_derive_run_status_is_not(
    graph: tuple[Stmt, ...],
) -> None:
    """Two closed vocabularies are spelled `status` and only one is an `enum_val` domain.

    `claim.status` is the `claim_status` domain (charter.md:942 lists the domain name, not the
    column name). `derive_run.status` (charter.md:4956) is `ok|partial|empty|failed|quarantined`
    and is deliberately NOT a domain at all -- which is why the domain carries the table in its
    name. The two lists must differ, or a later reader will "unify" them.
    """
    claim_status = _check_list(graph, "claim", "status")
    run_status = _check_list(graph, "derive_run", "status")
    assert claim_status == _domain("claim_status")
    assert run_status == ("ok", "partial", "empty", "failed", "quarantined")
    assert set(claim_status).isdisjoint(run_status)


def test_the_five_closed_domains_this_layer_adds_are_stored_as_names_and_taint_as_a_mask(
    graph: tuple[Stmt, ...],
) -> None:
    """The storage shape of a domain, which decides what a row means.

    Of the six domains charter.md:4834 adds here, five are stored as the LOWER-CASE MEMBER NAME in
    a `TEXT` column -- `lane`, `akind`, `alias_kind`, `claim_status`, `precision` -- and `taint` is
    an `INTEGER` BITMASK. Both are consistent with `enum_val` being the name-to-ord registry: an
    ord addresses one member, and neither a TEXT join partner (`route_decision.lane` and
    `work.lane` in 0004 are TEXT) nor a subset of bits is one member. The ten domains 0001 carries
    are the integer-coded ones, `taint` joining them here.

    `taint`'s ordinals are the ONE set that is not dense from 0: the ord is the member's own BIT
    (none 0, untrusted_source 1, sentinel 2, hidden_text 4, offscreen 8, single_witness_xdoc 16),
    because `taint & TAINT_UNTRUSTED_SOURCE` is the shipped predicate. Anyone generating rows for
    it must not use `ROW_NUMBER()`.
    """
    text_columns = {
        ("derive_cover", "lane"),
        ("graph_observation", "lane"),
        ("anchor", "akind"),
        ("entity_alias", "alias_kind"),
        ("claim", "status"),
        ("claim", "t_precision"),
        ("derive_pass", "lanes"),
    }
    for table, column in text_columns:
        sql = next(s.sql for s in graph if s.verb == "table" and s.name == table)
        assert re.search(rf"\b{column}\s+TEXT\b", sql), f"{table}.{column} is not TEXT"
    for table in ("entity", "entity_alias", "mention", "edge", "claim", "community"):
        sql = next(s.sql for s in graph if s.verb == "table" and s.name == table)
        assert re.search(r"\btaint\s+INTEGER\b", sql), f"{table}.taint is not INTEGER"
        assert re.search(r"\btrust\s+INTEGER\b", sql), f"{table}.trust is not INTEGER"
    taint_ords = [o for dom, o, _n in _enum_val_rows() if dom == "taint"]
    assert taint_ords == [0, 1, 2, 4, 8, 16]


# ---------------------------------------------------------------------------------------------
# 5. the joins and identities the plan says failed silently without them
# ---------------------------------------------------------------------------------------------


def test_akind_is_one_column_name_and_one_vocabulary_on_both_sides(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """`anchor.akind` (definitions) and `ref_site.akind` (occurrences), joined BY EQUALITY.

    charter.md:4820: "`anchor` said `citation_key` where `ref_site` said `citekey`" -- so "EVERY
    citation-key reference was permanently unresolved, permanently visible in `ref_unresolved`,
    permanently absent from `ow_ref_resolved`, with nothing anywhere reporting it". The guard is
    that the column NAME and the vocabulary are one, across two files, and the join is on both
    `name_norm` and `akind`.
    """
    anchor = next(s.sql for s in graph if s.name == "anchor")
    ref_site = next(s.sql for s in index if s.name == "ref_site")
    for sql, table in ((anchor, "anchor"), (ref_site, "ref_site")):
        assert re.search(r"\bakind\s+TEXT\s+NOT\s+NULL\b", sql), f"{table}.akind"
        assert re.search(r"\bname_norm\s+TEXT\s+NOT\s+NULL\b", sql), f"{table}.name_norm"
        assert "citation_key" not in sql
    assert len(_domain("akind")) == 14
    for view in ("ref_unresolved", "ow_ref_resolved"):
        sql = next(s.sql for s in index if s.name == view)
        assert re.search(r"n\.akind\s*=\s*s\.akind", sql), view
        assert re.search(r"n\.name_norm\s*=\s*s\.name_norm", sql), view


@pytest.mark.parametrize("view", ["ref_unresolved", "ow_ref_resolved"])
def test_both_reference_views_carry_the_two_predicates_that_failed_silently(
    index: tuple[Stmt, ...], view: str
) -> None:
    """`n.gen = dd.gen` and the scope clause, in both views (07 section 3.5).

    Without the first, a RETIRED generation's anchor still satisfies the anti-join, so a reference
    "resolves" against text that is no longer the head. Without the second, a `scope='document'`
    anchor in document A resolves a `ref_site` in document B -- "Figure 3" in one contract binding
    "Figure 3" in another, the single most common false merge in a document corpus.
    `ref_unresolved` is a `canonical_projection()` member, so a full build and an incremental build
    agreed on the same wrong answer and gate G19 could never see it.
    """
    sql = next(s.sql for s in index if s.name == view)
    assert re.search(r"n\.gen\s*=\s*dd\.gen", sql), f"{view} lost the head-generation predicate"
    assert re.search(
        r"n\.scope\s*=\s*'corpus'\s+OR\s+n\.doc_ord\s*=\s*s\.doc_ord", sql, re.IGNORECASE
    ), f"{view} lost the scope predicate"


def test_the_span_columns_are_ts_a_and_ts_b_and_never_a_and_b(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """The terminology lock: a `TextSpan` is `ts_a`/`ts_b`, an `OriginSpan` is `os_a`/`os_b`.

    07 section 3.5 states the convention and the reason it is not cosmetic: a `TextSpan` is
    half-open `[ts_a, ts_b)` in CHARACTERS of `block.text`, while an `OriginSpan`'s `os_a` is an
    OFFSET and `os_b` is a LENGTH, and a semgrep rule rejects `os_a:os_b` slicing. charter.md:3182
    and :3211 still print `a`/`b` for `ref_site` and `ref_attempt`; 07 section 3.5 renames them
    and is the normative site for L4.
    """
    for stmts, table in ((index, "ref_site"), (index, "ref_attempt"), (graph, "mention")):
        sql = next(s.sql for s in stmts if s.name == table)
        assert re.search(r"\bts_a\s+INTEGER\b", sql), f"{table}.ts_a"
        assert not re.search(r"^\s*a\s+INTEGER\b", sql, re.MULTILINE), f"{table} has a bare `a`"
        assert not re.search(r"^\s*b\s+INTEGER\b", sql, re.MULTILINE), f"{table} has a bare `b`"
    # The rename reaches the KEYS too, which is where a half-done rename would still compile:
    # `ref_site`'s primary key and `ref_attempt`'s both carry the span's start.
    for table in ("ref_site", "ref_attempt"):
        sql = next(s.sql for s in index if s.name == table)
        key = re.search(r"PRIMARY\s+KEY\s*\(([^)]*)\)", sql, re.IGNORECASE)
        assert key is not None and "ts_a" in key.group(1), f"{table} primary key lost ts_a"


def test_every_ifnull_identity_is_a_standalone_unique_index(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """ST10, and it is not a review rule: the inline form fails `CREATE TABLE`.

    "SQLite prohibits an expression in a table-level constraint, so the inline form does not merely
    fail review, it fails `CREATE TABLE`" (07 section 3.6, verified on 3.45.1). Without the
    sentinels there is nothing to conflict on and `INSERT OR IGNORE` degenerates to a plain
    `INSERT` -- codegraph #1034, byte-identical duplicates that inflated counts and flowed into
    callers. The installing migration must GROUP BY the identical expression, sentinels included.
    """
    for stmt in (*graph, *index):
        if stmt.verb == "table":
            for match in re.finditer(
                r"(UNIQUE|PRIMARY\s+KEY)\s*\(([^)]*)\)", stmt.sql, re.IGNORECASE
            ):
                assert "IFNULL" not in match.group(2).upper(), (
                    f"{stmt.name}: an IFNULL sentinel inside an inline "
                    f"{match.group(1)} fails CREATE TABLE (ST10)"
                )
    with_sentinels = {
        stmt.name for stmt in (*graph, *index) if "IFNULL" in stmt.sql.upper() and stmt.on
    }
    assert with_sentinels == {
        "derive_run_identity",
        "edge_identity",
        "claim_identity",
        "block_link_identity",
    }
    for name in with_sentinels:
        stmt = next(s for s in (*graph, *index) if s.name == name)
        assert stmt.verb == "unique index", f"{name} must be a UNIQUE index"


def test_four_tables_reference_both_spaces_and_gr15_says_one(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """A CONFIRMED plan defect, measured from definition sites and pinned rather than reproduced.

    THE CLAIM. 06-structure-extraction.md:232-234: "`mention` is **the only table in the framework
    referencing both a `block_id` and an `entity_id`** (GR15), enforced by a schema lint
    classifying every FK target as L2 or L3 and **failing on any table but `mention` holding
    both**." Restated at 06:2487, glossary.md:777, 01-principles.md:121 ("GR15 restricts the
    both-layers case to `mention`") and 17-risks.md R-T20 ("GR15 keeps `mention` the only table
    referencing both spaces, so there is exactly one place to check").

    THE MEASUREMENT. Counted over `REFERENCES` clauses in the DDL this cluster ships, which is
    charter.md:4982-5170 transcribed, FOUR tables hold both:
      mention  entity (NOT NULL) + block (NOT NULL) + segment      charter.md:5030-5035
      edge     entity (NOT NULL, twice) + block (NOT NULL)          charter.md:5054-5060
      claim    entity (NOT NULL) + block (NOT NULL)                 charter.md:5091-5106
      anchor   entity (nullable, ON DELETE SET NULL) + block         charter.md:5162-5164
    No narrower reading rescues the claim: "both NOT NULL" still admits `edge` and `claim`, and
    "both NOT NULL plus a mandatory span" still admits `claim`, whose `ts_a`/`ts_b` are NOT NULL.

    WHY IT MATTERS RATHER THAN BEING PEDANTRY. The lint as described would fail on three tables of
    the charter's own settled-law DDL, so it cannot be written as stated. And R-T20's mitigation
    for "a span written in one coordinate system and read in another" rests on there being "exactly
    one place to check" -- but `edge.ts_a`/`ts_b` and `claim.ts_a`/`ts_b` are also offsets into
    `block.text` produced by `ground()`, so the audit surface is three tables, not one.

    This test asserts the measurement. If GR15 is amended to name the real set, or the DDL is
    changed, exactly one of the two sides moves and this test says which.
    """
    both = {
        stmt.name
        for stmt in (*graph, *index)
        if stmt.verb == "table" and {"block", "entity"} <= _fk_targets(stmt)
    }
    assert both == {"mention", "edge", "claim", "anchor"}
    # `mention` IS the only one of the four whose entity reference is its subject rather than its
    # provenance, which is the property section 8's fixed-length provenance walk actually uses.
    mention = next(s.sql for s in graph if s.name == "mention")
    assert re.search(r"\bentity_id\s+INTEGER\s+NOT\s+NULL\s+REFERENCES\s+entity\b", mention)
    # `block_link.via_entity` is the near miss, and carrying no FK is what keeps it out of the set.
    block_link = next(s.sql for s in index if s.name == "block_link")
    assert re.search(r"\bvia_entity\s+INTEGER\s*,", block_link), "via_entity must carry no FK"
    assert "entity" not in _fk_targets(next(s for s in index if s.name == "block_link"))


def test_mention_block_is_the_charters_shape_and_the_register_row_disagrees(
    graph: tuple[Stmt, ...],
) -> None:
    """One index name, two printed shapes, and the DDL home wins.

    charter.md:5047 is `CREATE INDEX mention_block ON mention(block_id, ts_a);`. 07 section 3.13's
    register row prints it as "`(block_id)` partial `state = 0`", which is a different index. The
    charter's is implemented: it is the DDL home, and `ts_a` in the key makes span-ordered
    hydration inside one block a covering range scan. The register's own consumer -- section 7.4's
    `SELECT COUNT(*) FROM mention WHERE block_id = ? AND state = 0` -- is served by the left
    prefix, so nothing is lost. NOTE FOR THE PLAN'S OWNER: one of the two rows should change.
    """
    stmt = next(s for s in graph if s.name == "mention_block")
    assert stmt.on == "mention"
    assert re.search(r"\(\s*block_id\s*,\s*ts_a\s*\)", stmt.sql)
    assert "WHERE" not in stmt.sql.upper()


# ---------------------------------------------------------------------------------------------
# 6. lexical: `head_fts`'s options are a retrieval decision, and the conditional trigram set
# ---------------------------------------------------------------------------------------------


def test_head_fts_indexes_block_label_with_the_required_option_set(index: tuple[Stmt, ...]) -> None:
    """The column is `label`, and `detail`/`columnsize` are 07 section 3.3's, not schema taste.

    ADR-1 decision 7 renamed `block.title` to `label` so that `Kind.TITLE` keeps the word, and an
    external-content fts5 table resolves its column names against `content='block'` -- so
    `head_fts(title ...)` raises `no such column: title` when this file applies, which takes
    G27(b)'s whole run with it. charter.md:3161 still prints `title`; 03 section 13.1's DDL is the
    one home for the name. `detail='full'` supplies the instance offsets `ChannelResult.spans`
    carries and `columnsize=1` the per-row length `bm25()` normalises by; a persistent `rank` is
    never set, because it would put part of the scorer outside `SCORER_VERSION`.
    """
    sql = next(s.sql for s in index if s.name == "head_fts")
    assert re.search(r"fts5\(\s*label\s*,", sql), "the fts5 column must be `label`"
    assert "title" not in sql
    assert _content_target(next(s for s in index if s.name == "head_fts")) == "block"
    assert "content_rowid='block_id'" in sql
    assert "tokenize='unicode61 remove_diacritics 2'" in sql
    assert "detail='full'" in sql
    assert "columnsize=1" in sql
    assert "prefix" not in sql
    assert not re.search(r"\brank\b", sql, re.IGNORECASE)


@pytest.mark.parametrize("prefix", ["head_fts", "block_tri"])
def test_each_fts_trigger_set_carries_both_guards_and_the_delete_carries_old(
    index: tuple[Stmt, ...], prefix: str
) -> None:
    """Skip `state <> 0`, skip a NULL column, and make the `'delete'` row carry the OLD value.

    07 section 3.3: "an external-content table stores no text of its own, so a `'delete'` whose
    text differs from what was indexed corrupts the index silently." Every trigger is named
    explicitly, because `sqlite_master` has one namespace for all of them and "the same three
    triggers" is not a legal instruction -- `CREATE TRIGGER` is not idempotent.
    """
    column = "label" if prefix == "head_fts" else "text"
    for suffix in ("ai", "ad", "au"):
        sql = next(s.sql for s in index if s.name == f"{prefix}_{suffix}")
        assert re.search(r"\bstate\s*=\s*0\b", sql), f"{prefix}_{suffix} lost the state guard"
        assert f"{column} IS NOT NULL" in sql, f"{prefix}_{suffix} lost the NULL guard"
    delete = next(s.sql for s in index if s.name == f"{prefix}_ad")
    assert f"OLD.{column}" in delete and "'delete'" in delete
    update = next(s.sql for s in index if s.name == f"{prefix}_au")
    assert f"OLD.{column}" in update and f"NEW.{column}" in update


def test_the_trigram_set_is_the_only_optional_region_and_holds_exactly_four_statements(
    index: tuple[Stmt, ...],
) -> None:
    """A static SQL file cannot branch on `[retrieval] trigram`, so the region is delimited.

    07 section 3.4: "When `[retrieval] trigram = true`, `0003_index.sql` **additionally** creates"
    the virtual table "plus three triggers named `block_tri_ai` / `block_tri_ad` / `block_tri_au`
    ... They ship in this same file as `head_fts`'s set, so no name collides with 0001's ... The
    set is registered in `tools/indexes.toml` as conditional". The marker grammar is
    `-- @ow:optional-begin <name>` / `-- @ow:optional-end <name>`; the runner applies statements
    outside a region always and inside one only when that region's condition holds. G27(b) applies
    the whole file, which is the desired reading: it proves the conditional DDL is valid without
    deciding whether a given store wants it.
    """
    text = INDEX.read_text(encoding="ascii")
    begins = re.findall(r"^-- @ow:optional-begin (\S+)", text, re.MULTILINE)
    ends = re.findall(r"^-- @ow:optional-end (\S+)", text, re.MULTILINE)
    assert begins == ends == ["trigram"], (begins, ends)
    start = text.index("-- @ow:optional-begin trigram")
    stop = text.index("-- @ow:optional-end trigram")
    assert start < stop
    # Parsed as its own statement stream rather than matched by substring: `stat` is a substring of
    # "statements" and `head_fts` appears in the region's prose, so a name test over the raw text
    # would report objects the region does not contain.
    inside = {s.name for s in _parse_text(text[start:stop], "the trigram region")}
    assert inside == {"block_tri", "block_tri_ai", "block_tri_ad", "block_tri_au"}
    outside = _parse_text(text[:start] + text[stop:], "0003 outside the trigram region")
    assert not (inside & {s.name for s in outside}), "the set must be wholly inside the region"
    assert {s.name for s in outside} | inside == {s.name for s in index}


def test_block_tri_uses_the_bare_trigram_tokenizer_because_min_sqlite_is_3_42(
    index: tuple[Stmt, ...],
) -> None:
    """A MEASURED plan defect, pinned so the departure cannot be silently reverted.

    07 section 3.4 prints `tokenize='trigram remove_diacritics 1'`. The fts5 TRIGRAM tokenizer
    gained a `remove_diacritics` option only in SQLite 3.45.0; before that its only option is
    `case_sensitive`, and the constructor raises. Measured on 3.43.1 in this workspace:
    `trigram` and `trigram case_sensitive 0` construct, `trigram remove_diacritics 1` raises
    `error in tokenizer constructor`.

    `MIN_SQLITE = (3, 42, 0)` is stated at five sites (02-architecture.md section 2 row 7 and
    section 6 row 6, 07 section 2.1, charter.md:430, charter.md:8518), is already a shipped
    constant in `omniweave_core.limits`, and is G27(b)'s own flag; 07 section 2.1 justifies the
    floor exhaustively as "three features deep", so a fourth feature at 3.45 would have been
    named. The printed option string is therefore the defective side, and it also asks for
    `remove_diacritics 1` -- the value 07 section 3.3's own option table rejects for `unicode61`
    because "version `1` mishandles multi-codepoint diacritic sequences".
    """
    sql = next(s.sql for s in index if s.name == "block_tri")
    assert "tokenize='trigram'" in sql
    assert "remove_diacritics" not in sql
    assert _content_target(next(s for s in index if s.name == "block_tri")) == "block"


# ---------------------------------------------------------------------------------------------
# 7. the tags, and the statements that are load-bearing at a specific version
# ---------------------------------------------------------------------------------------------


def test_every_l4_object_carries_a_sor_or_der_tag(index: tuple[Stmt, ...]) -> None:
    """07 section 3.1: "it is why every table below carries a tag".

    The tag is not documentation: "A `[DER]` object may be dropped and re-created by a minor
    migration; an `[SOR]` object may not. That is the whole operational meaning of the legend."
    `0002_graph.sql` carries none because charter.md's L3 fence prints none, so this is asserted
    for the file whose specifying section defines the legend.
    """
    text = INDEX.read_text(encoding="ascii")
    for stmt in index:
        if stmt.verb in {"index", "unique index", "trigger"}:
            continue  # section 3.1's legend is over tables and views; every index is [DER]
        head = text[text.index(stmt.sql.split("\n", 1)[0]) :][:400]
        assert "[SOR]" in head or "[DER]" in head, f"{stmt.name} carries no tag"


def test_graph_observation_is_the_one_strict_table_and_the_floor_covers_it(
    graph: tuple[Stmt, ...],
) -> None:
    """`STRICT` needs SQLite 3.37 and `MIN_SQLITE` is (3, 42, 0), so the floor covers it.

    07 section 2.1: the floor "is three features deep: STRICT tables need 3.37.0, `unixepoch()`
    needs 3.38.0, `unixepoch('subsec')` needs 3.42.0". charter.md:4115 records the counter-example
    the floor exists to prevent: "an engineer targeting a documented 3.35 floor fails on the FIRST
    `CREATE TABLE ... STRICT`". `migration` in 0003 is the other STRICT table in this cluster.
    """
    strict = {s.name for s in graph if re.search(r"\)\s*STRICT\s*;?\s*$", s.sql, re.IGNORECASE)}
    assert strict == {"graph_observation"}


def test_migration_is_strict_and_declares_the_three_things_an_operator_cannot_re_derive(
    index: tuple[Stmt, ...],
) -> None:
    """`cost_class`, `resumable` and `unbackfilled_means`, the last as REQUIRED PROSE.

    11-repo-layout.md:1218 and 07 section 3.8: `ow doctor` prints `unbackfilled_means` VERBATIM,
    because "a half-backfilled column is a correctness question an operator must be able to answer
    without reading the migration". `version INTEGER PRIMARY KEY` is half of why G27(b) asserts
    density and uniqueness of the numeric prefixes BEFORE applying anything: two branches each
    adding a `0004` would both insert version 4, and a GAP raises nothing at all
    (11-repo-layout.md section 5.2).
    """
    sql = next(s.sql for s in index if s.name == "migration")
    assert re.search(r"\)\s*STRICT\s*;", sql, re.IGNORECASE)
    assert re.search(r"\bversion\s+INTEGER\s+PRIMARY\s+KEY\b", sql, re.IGNORECASE)
    assert _check_list(index, "migration", "cost_class") == ("ddl", "backfill", "rebuild")
    assert re.search(r"\bresumable\s+INTEGER\s+NOT\s+NULL\b", sql, re.IGNORECASE)
    assert re.search(r"\bunbackfilled_means\s+TEXT\s+NOT\s+NULL\b", sql, re.IGNORECASE)


def test_the_segment_is_defined_once_and_0003_adds_no_second_chunking(
    graph: tuple[Stmt, ...], index: tuple[Stmt, ...]
) -> None:
    """INV-1's schema half, over the one object both layers touch.

    07 section 3.2: "L4 **adds no second representation of anything** (INV-1). It reads `block`,
    `segment` and `anchor` and adds indexes and occurrence tables over them." So `segment`,
    `segmenter` and `segment_block` are 0002's, and everything 0003 does to them is an index or a
    view.
    """
    assert {"segment", "segmenter", "segment_block"} <= _named(graph, "table")
    touching = [s for s in index if s.on in {"segment", "segmenter", "segment_block"}]
    assert {s.name for s in touching} == {"segment_digest_ix", "segment_doc", "segment_restricted"}
    for stmt in touching:
        assert stmt.verb == "index"
    head = next(s.sql for s in index if s.name == "ow_segment_head")
    assert re.search(r"s\.gen\s*=\s*d\.gen\s+AND\s+s\.state\s*=\s*0", head, re.IGNORECASE)
