"""INV-1's `L` enforcer: the schema lint over the migration set, in three clauses.

`uv run tools/gate_schema_lint.py` is 16-roadmap.md section 5's P2 exit-criteria line, spelled
there as "INV-1, the FK-target classification" (16-roadmap.md:454). W2.2 names the three clauses
this file implements -- "the schema lint (FK-target classification, no second text column, no
positional Block reference)" (16-roadmap.md:415) -- and each has its own specifying site:

* **FK-target classification.** INV-1, 01-principles.md:118-121: *"a schema lint classifies every
  FK target and rejects both a second text column and a positional reference to a Block (`GR15`
  restricts the both-layers case to `mention`)"*. `GR15` itself is charter.md:5672 and
  06-structure-extraction.md:233: *"`mention` is the only table in the framework referencing both a
  `block_id` and an `entity_id`, enforced by a schema lint classifying every FK target as L2 or L3
  and failing on any table but `mention` holding both"*. 00-vision.md:202 states the same rule from
  the vision side.
* **No second text column.** INV-1's statement -- *"No layer stores a second copy of a Block's
  text, structure or geometry"* -- and its **A violation looks like** paragraph, which is the
  operative one because it is the only site that enumerates shapes: *"A new column named `*_html`,
  `*_text`, `*_md` or `*_bbox` on a table that already reaches a Block; ...; an FTS table declared
  with content of its own"* (01-principles.md:127-130). 01-principles.md:1200 is the same rule as a
  rejection-list row: *"stores a second copy of a Block's text, structure or geometry | the schema
  lint's FK classification, and the new columns' names"*.
* **No positional Block reference.** INV-1's statement again -- *"no table references a Block by
  anything other than `block_id` -- never by `addr`, `cite`, `(doc_ord, gen, page, ord)` or any
  other position"* -- against 03-document-model.md's three declarations of what `block_id` is:
  `:272` (*"The only FK target for a Block"*), `:1054` (the identity table's job column, the same
  words) and `:2319`, the `block` DDL's own comment, *"DURABLE surrogate; the only FK target FOR A
  BLOCK"*.

**Why this is an `L` and not an `X`.** 01-principles.md:74 defines the `L` rung as *"a static scan
rejects the source"*, and lists a schema lint beside semgrep and `ow route lint`. This gate reads
the `.sql` text and never opens a database: `sqlite3` is banned outside `omniweave_core/store/`
(INV-17, 07-store-and-retrieval.md section 10.1), and the ban has no `per-file-ignores` escape for
`tools/`. G27(b) -- `tools/gate_migrations.py`, 11-repo-layout.md section 5.2 -- is the half that
applies the files to an empty database on `MIN_SQLITE`; this half asserts what applying them
successfully would not notice, because every violation below is valid SQL.

**Stdlib only, and it imports nothing first-party.** The same discipline `tools/gate_layers.py`,
`tools/gate_core_pure.py` and `tools/gate_tombstones.py` hold to, for the reason
02-architecture.md section 3.3 gives: the graph is built by *"walking source rather than importing
it -- which also means the gate runs on a package whose dependencies are not installed"*. A schema
lint that imported `omniweave_core` to read a table roster would fail on exactly the broken tree it
exists to diagnose, and it would then be asserting a property of *this* process rather than of the
DDL on disk.

The layer classification is DERIVED, not transcribed
----------------------------------------------------
A table's layer is **the migration file that creates it**. 16-roadmap.md:291 -- *"Migrations are
numbered by layer, not by date"* -- and 07-store-and-retrieval.md section 3's table are the same
statement: `0001_init.sql` is L2, `0002_graph.sql` is L3, `0003_index.sql` is L4, `0004_runtime.sql`
is the runtime ledger and `0005_out.sql` is OUT. So the roster this gate classifies against is read
off the files it is already parsing, and there is no second copy of the table list for a new table
to be missing from -- which is INV-1's own argument applied to the gate.

A migration numbered outside 1-5 is labelled `EXT<n>` rather than failed: 11-repo-layout.md section
5.1 makes the migration set append-only and a later `0006_*.sql` is expected. `EXT<n>` is a layer
like any other for `GR15`'s purposes -- it is neither L2 nor L3, so it can never be half of a
both-layers pair, and adding a file cannot make this gate go red for a reason its author did not
choose.

What the gate does when the tree is incomplete
----------------------------------------------
An FK naming a table no file creates is a real defect -- SQLite resolves a foreign key's parent at
*the first DML on the child row*, not at `CREATE TABLE` (07-store-and-retrieval.md section 3), so
the store applies cleanly and fails on the first insert. But it is indistinguishable, from here,
from a tree that is simply mid-build. The discriminator is G27(b)'s own density rule
(11-repo-layout.md:1243, *"asserts density and uniqueness, not just applicability"*): when the
numeric prefixes on disk are exactly `1..N`, an unresolvable FK target is a **failure**; when they
are not, it is reported as **deferred** and named, and the gate does not fail on it. Every other
clause runs either way, because they are all statements about one file.

Two shapes this gate deliberately does NOT flag, both measured rather than assumed
----------------------------------------------------------------------------------
1. **A bare `cite` or `addr` column.** INV-1's statement names `cite` and `addr` as forbidden ways
   to reference a Block, and a lint on the bare names would reject the plan's own DDL: `cite` is a
   column on `block` (charter.md:1035), `entity` (:1101), `claim` (:1208), `community` (:1320) and
   `artifact_cite` (:1444), and only the last of those is about a Block -- where it sits *beside*
   `block_id INTEGER REFERENCES block(block_id)`, so the Block reference is already the surrogate
   and `cite` is the shipped citation text. `eval_assertion.addr` (:1542) is an assertion's
   address, not a Block's. The checkable reading of "references a Block" is a `REFERENCES` clause,
   which is clause 3a, plus the unambiguously-qualified column names of clause 3b.
2. **`block.text` and `block.quad`.** `block` is the single home for a Block's text and geometry,
   so it is exempt from clause 2 by construction. Measured over every ```sql block in `_plan/` and
   `_plan/_notes/charter.md`: the only column names matching clause 2's markers are `block.text`
   and `block.quad`. `source_text` -- the shape charter.md:5101 and :5719 reject by name
   (*"graphrag stores `source_text`, A COPY. A copy drifts on any re-parse"*) -- appears only in
   prose, which is what clause 2 exists to keep true.

Exit codes
----------
`0` the three clauses hold. `1` a clause is false. `2` the gate did not run (an argument, or
the migration directory is absent or holds no `.sql` file). `1` and `2` are distinguished because CI
treats both as failure and a human needs to know which.

Specified in 16-roadmap.md sections 4 and 5 (the P2 exit line, :454) and section 3 (W2.2, :415);
01-principles.md INV-1 and its rejection-list row :1200; 00-vision.md:202;
06-structure-extraction.md:233; charter.md GR15 :5672; 07-store-and-retrieval.md section 3 for the
file-to-layer correspondence; 02-architecture.md section 3.3 for the stdlib-only, import-free
discipline every `tools/` gate holds to.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence
    from typing import TextIO

REPO = Path(__file__).resolve().parent.parent
# The DDL is `omniweave-core` PACKAGE DATA, not a repo-root directory: 11-repo-layout.md:1186 has it
# "packaged with `omniweave-core` as package data, read through `importlib.resources` at use time",
# :205's tree diagram draws it under `omniweave_core/store/`, and :793 spells the path in full.
# Root `schema/` is a different artefact -- :346, "GENERATED from Python, committed, byte-diff
# gated (G6)" -- and hand-written DDL is not generated. The move, and the sdist defect that a
# build-time copy from the root introduced, are `_plan/_notes/build-defects.md` D12.
MIGRATIONS = (
    REPO
    / "packages"
    / "omniweave-core"
    / "src"
    / "omniweave_core"
    / "store"
    / "schema"
    / "migrations"
)

EXIT_CLEAN = 0
EXIT_FAIL = 1
EXIT_NOT_RUN = 2

# 07-store-and-retrieval.md section 3's migration table, read as the file-to-layer correspondence
# 16-roadmap.md:291 states in one sentence. The KEY is the four-digit numeric prefix.
LAYER_BY_MIGRATION: Mapping[int, str] = {
    1: "L2",
    2: "L3",
    3: "L4",
    4: "RUNTIME",
    5: "OUT",
}

# GR15, and the one place this gate departs from an enforcer the plan sketches, because the sketch
# rejects the plan's own DDL. MEASURED, 2026-09-07, over charter.md's L3 block:
#
#   * The enforcer cell at charter.md:5672 and 06-structure-extraction.md:233 says "classifies
#     every FK target as L2 or L3 and fails on any table but `mention` holding both". Applied
#     literally to the DDL the charter itself prints, that fails EIGHT tables -- `segment`
#     (segmenter_id + synopsis_of), `segment_block`, `derive_run` (producer_id + pass_id), `edge`,
#     `claim`, `anchor`, `quarantine` and L4's `block_link` (relation -> relation_vocab is L3 while
#     src_block is L2). None of those is a defect; every one is printed law.
#   * GR15's own STATEMENT is narrower and is the normative half: "`mention` is the only table in
#     the framework referencing both a `block_id` and an `entity_id`" (charter.md:5672,
#     06-structure-extraction.md:233, and `mention`'s own DDL comment at charter.md:5030, "THE
#     BRIDGE: the only table referencing both spaces (GR15)").
#   * That statement is ALSO false of the charter's own DDL, at three tables, and it is a defect
#     rather than a reading: `edge.observed_block` sits beside `src_entity`/`dst_entity`
#     (charter.md:5052-5062), `claim.observed_block` beside `subject_entity`/`object_entity`
#     (:5089-5101), and `anchor.block_id` beside `anchor.entity_id` (:5161-5162). Reported to the
#     plan's owner; until it is ruled, the three are carried as an exemption ROSTER rather than
#     silently widened away, so a FIFTH table growing the pair is still a decision somebody has to
#     make in a pull request.
#
# The spelling implemented is the statement's -- an FK to `block` AND an FK to `entity` -- because
# it is the one that both documents print as GR15 and the one whose purpose they give
# (06-structure-extraction.md:235: "That is what makes the provenance chain in section 8 a
# fixed-length walk rather than a search").
GR15_ENTITY = "entity"
GR15_BOTH_SPACES_EXEMPT: Mapping[str, str] = {
    "mention": "THE BRIDGE, and the only one GR15 sanctions (charter.md:5030)",
    "edge": "observed_block: WHERE THE RELATIONSHIP WAS OBSERVED (charter.md:5060)",
    "claim": "observed_block: the reference graphrag stored as a copy (charter.md:5100)",
    "anchor": "block_id defines, entity_id is the resolved target (charter.md:5161)",
}

# The one home for a Block's text, structure and geometry (03-document-model.md:2318). Exempt from
# clause 2 by construction: `block.text` IS the representation INV-1 forbids a second copy of.
BLOCK = "block"
BLOCK_SURROGATE = "block_id"

# INV-1's "A violation looks like" enumeration (01-principles.md:127-130), as exact names and as
# suffixes. `md` and `markdown` are the two spellings 01-principles.md:190's semgrep rule bans on a
# model class ("an `html`, `markdown` or `md` field"); the geometry half is `*_bbox` from the same
# sentence, plus the three spellings `block`'s own geometry column could have taken.
TEXT_MARKERS = ("text", "html", "markdown", "md")
GEOMETRY_MARKERS = ("bbox", "quad", "polygon", "geometry")
SECOND_COPY_MARKERS = TEXT_MARKERS + GEOMETRY_MARKERS

# Clause 3b. Only names that unambiguously identify a BLOCK by something other than its surrogate;
# see the module docstring for why bare `cite` and `addr` are not here.
POSITIONAL_BLOCK_COLUMNS = (
    "block_addr",
    "block_cite",
    "block_page",
    "block_ord",
    "block_doc_ord",
    "block_gen",
)

# The positional components INV-1 names: "never by `addr`, `cite`, `(doc_ord, gen, page, ord)` or
# any other position". Used only to make a composite-FK finding readable.
POSITIONAL_COMPONENTS = ("doc_ord", "gen", "page", "ord", "addr", "cite")

_NAME = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][A-Za-z0-9_$]*)'
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")

_CREATE_TABLE = re.compile(
    rf"^\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:({_NAME})\s*\.\s*)?({_NAME})",
    re.I,
)
_CREATE_VIRTUAL = re.compile(
    rf"^\s*CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:({_NAME})\s*\.\s*)?({_NAME})\s+USING\s+({_NAME})",
    re.I,
)
_CREATE_INDEX = re.compile(
    rf"^\s*CREATE\s+(UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:({_NAME})\s*\.\s*)?({_NAME})\s+ON\s+({_NAME})",
    re.I,
)
_CREATE_VIEW = re.compile(
    rf"^\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:({_NAME})\s*\.\s*)?({_NAME})",
    re.I,
)
_CREATE_TRIGGER = re.compile(
    rf"^\s*CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"(?:({_NAME})\s*\.\s*)?({_NAME})\b",
    re.I,
)
_TRIGGER_ON = re.compile(rf"\bON\s+({_NAME})", re.I)

# A column-level REFERENCES, and a table-level FOREIGN KEY. The parent column list is optional in
# both: omitting it makes SQLite resolve the parent's PRIMARY KEY, which clause 3a checks.
_REFERENCES = re.compile(rf"\bREFERENCES\s+(?:{_NAME}\s*\.\s*)?({_NAME})\s*(\(([^()]*)\))?", re.I)
_FOREIGN_KEY = re.compile(r"\bFOREIGN\s+KEY\s*\(([^()]*)\)\s*", re.I)

_TABLE_CONSTRAINT_HEAD = re.compile(
    r"^\s*(CONSTRAINT\b|PRIMARY\s+KEY\b|UNIQUE\s*\(|CHECK\s*\(|FOREIGN\s+KEY\b)", re.I
)
_PK_TABLE = re.compile(r"^\s*PRIMARY\s+KEY\s*\(([^()]*)\)", re.I)
_PK_COLUMN = re.compile(r"\bPRIMARY\s+KEY\b", re.I)
_FTS_CONTENT = re.compile(r"\bcontent\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|(\S+))", re.I)


# The statement splitter's depth words. `BEGIN` opens a trigger body and `CASE` opens an
# expression; both are closed by `END`, so one counter serves both (see `split_statements`).
DEPTH_OPENS = frozenset({"BEGIN", "CASE"})
DEPTH_CLOSE = "END"
QUOTE_PAIR = 2  # the shortest quoted identifier is two delimiters around something


def _unquote(name: str) -> str:
    """Strip SQLite's four identifier quotings and fold case: its names are ASCII-insensitive."""
    text = name.strip()
    if len(text) >= QUOTE_PAIR and text[0] in '"`[' and text[-1] in '"`]':
        text = text[1:-1]
    return text.lower()


def blank_noise(sql: str) -> str:
    """Return `sql` with comments and string-literal bodies replaced by spaces, offsets preserved.

    Parsing a blanked copy rather than a stripped one is what lets a finding name a real line: the
    blanked text and the original are the same length, so an offset found in one indexes the other.
    It also removes the only characters that could fool a depth counter -- a `(`, `)`, `,` or `;`
    inside a `'...'` literal or a `--` comment. The quote and comment DELIMITERS are kept so a
    tokenizer still sees a token boundary where one exists.
    """
    out = list(sql)
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "-" and sql.startswith("--", i):
            j = sql.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif ch == "/" and sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                out[k] = "\n" if sql[k] == "\n" else " "
            i = j
        elif ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            for k in range(i + 1, min(j, n)):
                out[k] = "\n" if sql[k] == "\n" else " "
            i = min(j + 1, n)
        else:
            i += 1
    return "".join(out)


@dataclass(frozen=True, slots=True)
class Statement:
    """One top-level SQL statement, with the offsets that let a finding cite a line."""

    file: Path
    line: int
    raw: str
    blank: str

    def line_of(self, offset: int) -> int:
        """The 1-based line in `file` of `offset` within this statement."""
        return self.line + self.blank[:offset].count("\n")


def split_statements(sql: str, path: Path) -> list[Statement]:
    """Split on top-level `;`, keeping a `CREATE TRIGGER` body and a `CASE ... END` whole.

    A trigger body is `BEGIN <stmt>; ... END;` and its inner semicolons are not statement
    terminators -- every trigger in the shipped DDL has one (charter.md:3148, :4070, :2851). A view
    can carry an unbalanced-looking `END` too, because `CASE ... END` is an expression:
    `route_scoreboard` has three. Counting `BEGIN` and `CASE` up and `END` down handles both with
    one counter, and never goes negative in valid SQL.
    """
    blank = blank_noise(sql)
    statements: list[Statement] = []
    depth = 0
    start = 0
    line = 1
    i, n = 0, len(blank)
    while i < n:
        ch = blank[i]
        if ch == "\n":
            i += 1
            continue
        word = _WORD.match(blank, i)
        if word is not None:
            token = word.group(0).upper()
            if token in DEPTH_OPENS:
                depth += 1
            elif token == DEPTH_CLOSE:
                depth = max(0, depth - 1)
            i = word.end()
            continue
        if ch == ";" and depth == 0:
            chunk = blank[start : i + 1]
            if chunk.strip():
                statements.append(
                    Statement(file=path, line=line, raw=sql[start : i + 1], blank=chunk)
                )
            line += blank[start : i + 1].count("\n")
            start = i + 1
        i += 1
    tail = blank[start:]
    if tail.strip():
        statements.append(Statement(file=path, line=line, raw=sql[start:], blank=tail))
    return statements


def _body_span(blank: str) -> tuple[int, int] | None:
    """Offsets of the outermost parenthesised body, or None when there is none."""
    open_at = blank.find("(")
    if open_at < 0:
        return None
    depth = 0
    for i in range(open_at, len(blank)):
        if blank[i] == "(":
            depth += 1
        elif blank[i] == ")":
            depth -= 1
            if depth == 0:
                return open_at + 1, i
    return None


def _split_items(blank: str, lo: int, hi: int) -> Iterator[tuple[int, int]]:
    """Offsets of the top-level comma-separated items of a table body."""
    depth = 0
    start = lo
    for i in range(lo, hi):
        ch = blank[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            yield start, i
            start = i + 1
    yield start, hi


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    offset: int


@dataclass(frozen=True, slots=True)
class ForeignKey:
    child_table: str
    child_columns: tuple[str, ...]
    parent_table: str
    parent_columns: tuple[str, ...]
    offset: int
    statement: Statement

    @property
    def where(self) -> str:
        return f"{self.statement.file.name}:{self.statement.line_of(self.offset)}"


@dataclass(slots=True)
class Table:
    name: str
    statement: Statement
    columns: list[Column] = field(default_factory=list)
    primary_key: tuple[str, ...] = ()
    virtual_module: str | None = None
    virtual_args: str = ""

    @property
    def column_names(self) -> frozenset[str]:
        return frozenset(c.name for c in self.columns)


@dataclass(slots=True)
class Schema:
    """Every object the migration files on disk declare, plus where each came from."""

    tables: dict[str, Table] = field(default_factory=dict)
    layer_of: dict[str, str] = field(default_factory=dict)
    foreign_keys: list[ForeignKey] = field(default_factory=list)
    indexes: dict[str, tuple[str, bool, Statement]] = field(default_factory=dict)
    views: dict[str, Statement] = field(default_factory=dict)
    triggers: dict[str, tuple[str, Statement]] = field(default_factory=dict)
    duplicates: list[str] = field(default_factory=list)
    dense: bool = True
    files: tuple[Path, ...] = ()


def _parse_table(statement: Statement, name: str, *, virtual: str | None = None) -> Table:
    table = Table(name=name, statement=statement, virtual_module=virtual)
    span = _body_span(statement.blank)
    if span is None:
        return table
    lo, hi = span
    if virtual is not None:
        # A virtual table's arguments are module-defined and are NOT column definitions: fts5 takes
        # `content=`, `tokenize=`, `prefix=` and bare column names in one list. Kept whole so
        # clause 2b can read the options.
        table.virtual_args = statement.raw[lo:hi]
        return table
    pk_columns: list[str] = []
    for item_lo, item_hi in _split_items(statement.blank, lo, hi):
        item = statement.blank[item_lo:item_hi]
        if not item.strip():
            continue
        if _TABLE_CONSTRAINT_HEAD.match(item):
            pk = _PK_TABLE.match(item)
            if pk is not None:
                pk_columns = [_unquote(part) for part in pk.group(1).split(",") if part.strip()]
            continue
        word = _WORD.search(item)
        if word is None:
            continue
        column = Column(name=_unquote(word.group(0)), offset=item_lo + word.start())
        table.columns.append(column)
        if _PK_COLUMN.search(item) and not pk_columns:
            pk_columns = [column.name]
    table.primary_key = tuple(pk_columns)
    return table


def _parse_foreign_keys(statement: Statement, table: Table) -> list[ForeignKey]:
    """Every FK the statement declares, column-level and table-level alike."""
    found: list[ForeignKey] = []
    span = _body_span(statement.blank)
    if span is None or table.virtual_module is not None:
        return found
    lo, hi = span
    for item_lo, item_hi in _split_items(statement.blank, lo, hi):
        item = statement.blank[item_lo:item_hi]
        if not item.strip():
            continue
        table_level = _FOREIGN_KEY.search(item)
        child: tuple[str, ...]
        if table_level is not None:
            child = tuple(
                _unquote(part) for part in table_level.group(1).split(",") if part.strip()
            )
        else:
            word = _WORD.search(item)
            if word is None or _TABLE_CONSTRAINT_HEAD.match(item):
                continue
            child = (_unquote(word.group(0)),)
        for reference in _REFERENCES.finditer(item):
            parent_columns = (
                tuple(
                    _unquote(part) for part in (reference.group(3) or "").split(",") if part.strip()
                )
                if reference.group(2)
                else ()
            )
            found.append(
                ForeignKey(
                    child_table=table.name,
                    child_columns=child,
                    parent_table=_unquote(reference.group(1)),
                    parent_columns=parent_columns,
                    offset=item_lo + reference.start(),
                    statement=statement,
                )
            )
    return found


def migration_files(root: Path) -> list[Path]:
    return sorted(root.glob("*.sql"), key=lambda p: p.name)


def read_schema(root: Path) -> Schema:
    """Parse every `*.sql` in `root`, classifying each object by the file that declares it."""
    schema = Schema(files=tuple(migration_files(root)))
    numbers: list[int] = []
    for path in schema.files:
        prefix = re.match(r"^(\d+)", path.name)
        number = int(prefix.group(1)) if prefix else -1
        if number >= 0:
            numbers.append(number)
        layer = LAYER_BY_MIGRATION.get(number, f"EXT{number}" if number >= 0 else "UNNUMBERED")
        for statement in split_statements(path.read_text(encoding="utf-8"), path):
            head = statement.blank
            virtual = _CREATE_VIRTUAL.match(head)
            plain = None if virtual else _CREATE_TABLE.match(head)
            index = _CREATE_INDEX.match(head)
            view = _CREATE_VIEW.match(head)
            trigger = _CREATE_TRIGGER.match(head)
            if virtual is not None or plain is not None:
                match = virtual if virtual is not None else plain
                assert match is not None  # noqa: S101 -- narrowing for the type checker
                name = _unquote(match.group(2))
                module = _unquote(virtual.group(3)) if virtual is not None else None
                table = _parse_table(statement, name, virtual=module)
                if name in schema.tables:
                    schema.duplicates.append(f"table {name}")
                schema.tables[name] = table
                schema.layer_of[name] = layer
                schema.foreign_keys.extend(_parse_foreign_keys(statement, table))
            elif index is not None:
                name = _unquote(index.group(3))
                if name in schema.indexes:
                    schema.duplicates.append(f"index {name}")
                schema.indexes[name] = (_unquote(index.group(4)), bool(index.group(1)), statement)
            elif view is not None:
                name = _unquote(view.group(2))
                if name in schema.views:
                    schema.duplicates.append(f"view {name}")
                schema.views[name] = statement
                schema.layer_of[name] = layer
            elif trigger is not None:
                name = _unquote(trigger.group(2))
                on = _TRIGGER_ON.search(statement.blank[trigger.end() :])
                if name in schema.triggers:
                    schema.duplicates.append(f"trigger {name}")
                schema.triggers[name] = (_unquote(on.group(1)) if on else "", statement)
    numbers.sort()
    schema.dense = bool(numbers) and numbers == list(range(1, len(numbers) + 1))
    return schema


def reaches_block(schema: Schema) -> frozenset[str]:
    """Tables with a foreign-key path to `block`, which is what INV-1's "reaches a Block" names.

    Transitive rather than direct, because the invariant is about a *second copy* and a copy two
    hops away is still a copy: `grid_slot` reaches a Block through `cell`, and a `cell_html` column
    would be exactly marker's `block.html` assignment (INV-1's Why) at one remove.
    """
    edges: dict[str, set[str]] = {}
    for fk in schema.foreign_keys:
        edges.setdefault(fk.child_table, set()).add(fk.parent_table)
    seen: set[str] = set()
    for start in edges:
        stack = [start]
        walked: set[str] = set()
        while stack:
            node = stack.pop()
            if node in walked:
                continue
            walked.add(node)
            stack.extend(edges.get(node, ()))
        if BLOCK in walked:
            seen.add(start)
    return frozenset(seen)


@dataclass(frozen=True, slots=True)
class Finding:
    clause: str
    subject: str
    where: str
    detail: str


def _marks_second_copy(column: str) -> str | None:
    for marker in SECOND_COPY_MARKERS:
        if column == marker or column.endswith("_" + marker):
            return marker
    return None


def clause_fk_targets(schema: Schema) -> tuple[list[Finding], list[str]]:
    """Clause 1 -- classify every FK target, and hold GR15's both-spaces case to its roster."""
    findings: list[Finding] = []
    deferred: list[str] = []
    spaces: dict[str, dict[str, list[str]]] = {}
    for fk in schema.foreign_keys:
        parent = schema.tables.get(fk.parent_table)
        if parent is None:
            note = (
                f"{fk.child_table}.{'+'.join(fk.child_columns)} -> {fk.parent_table} "
                f"({fk.where}): no migration file on disk creates {fk.parent_table}"
            )
            if schema.dense:
                findings.append(
                    Finding(
                        clause="fk-target",
                        subject=f"{fk.child_table} -> {fk.parent_table}",
                        where=fk.where,
                        detail=(
                            f"the FK target {fk.parent_table} is created by no migration, so it "
                            f"has no layer and cannot be classified. SQLite resolves a parent at "
                            f"the first DML on the child row, not at CREATE TABLE "
                            f"(07-store-and-retrieval.md section 3), so this applies cleanly and "
                            f"fails on the first insert."
                        ),
                    )
                )
            else:
                deferred.append(note)
            continue
        if fk.parent_columns and not set(fk.parent_columns) <= parent.column_names:
            missing = sorted(set(fk.parent_columns) - parent.column_names)
            findings.append(
                Finding(
                    clause="fk-target",
                    subject=f"{fk.child_table} -> {fk.parent_table}({','.join(fk.parent_columns)})",
                    where=fk.where,
                    detail=f"{fk.parent_table} declares no column {missing}",
                )
            )
            continue
        if fk.parent_table in (BLOCK, GR15_ENTITY):
            spaces.setdefault(fk.child_table, {}).setdefault(fk.parent_table, []).append(
                f"{'+'.join(fk.child_columns)} -> {fk.parent_table}"
            )
    for child, by_space in sorted(spaces.items()):
        if len(by_space) > 1 and child not in GR15_BOTH_SPACES_EXEMPT:
            detail = "; ".join(
                f"{space}: {', '.join(sorted(refs))}" for space, refs in sorted(by_space.items())
            )
            findings.append(
                Finding(
                    clause="fk-target",
                    subject=child,
                    where=f"{schema.tables[child].statement.file.name}"
                    f":{schema.tables[child].statement.line}",
                    detail=(
                        f"holds a foreign key into BOTH spaces -- {detail}. GR15: `mention` is "
                        f"the only table in the framework referencing both a block_id and an "
                        f"entity_id (charter.md:5672, 06-structure-extraction.md:233), which is "
                        f"what makes the provenance chain a fixed-length walk rather than a "
                        f"search. The three tables the charter's own DDL adds to that set are "
                        f"carried as a named roster in this file; a fourth is a decision, not a "
                        f"widening."
                    ),
                )
            )
    return findings, deferred


def clause_second_text_column(schema: Schema) -> list[Finding]:
    """Clause 2 -- no second copy of a Block's text, structure or geometry."""
    findings: list[Finding] = []
    reaching = reaches_block(schema)
    for name, table in sorted(schema.tables.items()):
        if name == BLOCK:
            continue
        if name in reaching:
            for column in table.columns:
                marker = _marks_second_copy(column.name)
                if marker is None:
                    continue
                findings.append(
                    Finding(
                        clause="second-copy",
                        subject=f"{name}.{column.name}",
                        where=f"{table.statement.file.name}"
                        f":{table.statement.line_of(column.offset)}",
                        detail=(
                            f"a `{marker}` column on a table that reaches a Block. INV-1: no layer "
                            f"stores a second copy of a Block's text, structure or geometry. "
                            f"Render it from the Blocks instead."
                        ),
                    )
                )
        if table.virtual_module is not None and table.virtual_module.startswith("fts"):
            content = _FTS_CONTENT.search(table.virtual_args)
            value = ""
            if content is not None:
                value = content.group(1) or content.group(2) or content.group(3) or ""
            if content is None or not value.strip():
                findings.append(
                    Finding(
                        clause="second-copy",
                        subject=name,
                        where=f"{table.statement.file.name}:{table.statement.line}",
                        detail=(
                            "an FTS table declared with content of its own. INV-1's violation list "
                            "names it, and `block_fts` is an external-content table for exactly "
                            "this reason: it indexes `block.text` rather than copying it "
                            "(01-principles.md:115, :130)."
                        ),
                    )
                )
    return findings


def clause_positional_block_reference(schema: Schema) -> list[Finding]:
    """Clause 3 -- `block_id` is the only FK target for a Block, and the only way to name one."""
    findings: list[Finding] = []
    block = schema.tables.get(BLOCK)
    if block is not None and block.primary_key not in {(BLOCK_SURROGATE,), ()}:
        findings.append(
            Finding(
                clause="positional-ref",
                subject=f"{BLOCK} PRIMARY KEY",
                where=f"{block.statement.file.name}:{block.statement.line}",
                detail=(
                    f"the primary key is {list(block.primary_key)}, so an FK written "
                    f"`REFERENCES block` with no column list would resolve to it rather than to "
                    f"`block_id`. 03-document-model.md:2319: block_id is the DURABLE surrogate and "
                    f"the only FK target FOR A BLOCK."
                ),
            )
        )
    for fk in schema.foreign_keys:
        if fk.parent_table != BLOCK:
            continue
        if fk.parent_columns and tuple(fk.parent_columns) != (BLOCK_SURROGATE,):
            positional = [c for c in fk.parent_columns if c in POSITIONAL_COMPONENTS]
            findings.append(
                Finding(
                    clause="positional-ref",
                    subject=f"{fk.child_table} -> block({','.join(fk.parent_columns)})",
                    where=fk.where,
                    detail=(
                        f"a Block is referenced by "
                        f"{'a position, ' + str(positional) + ', ' if positional else ''}"
                        f"not by block_id. INV-1: no table references a Block by anything other "
                        f"than `block_id` -- never by `addr`, `cite`, `(doc_ord, gen, page, ord)` "
                        f"or any other position (01-principles.md:105)."
                    ),
                )
            )
    for name, table in sorted(schema.tables.items()):
        if name == BLOCK:
            continue
        for column in table.columns:
            if column.name not in POSITIONAL_BLOCK_COLUMNS:
                continue
            findings.append(
                Finding(
                    clause="positional-ref",
                    subject=f"{name}.{column.name}",
                    where=f"{table.statement.file.name}:{table.statement.line_of(column.offset)}",
                    detail=(
                        f"names a Block by `{column.name.removeprefix('block_')}` instead of by "
                        f"the surrogate. `addr` is positional and generation-keyed "
                        f"(03-document-model.md:1120) and `cite` is a prompt token (INV-8); "
                        f"neither is an FK target for a Block."
                    ),
                )
            )
    return findings


def fk_target_census(schema: Schema) -> dict[str, list[str]]:
    """Every distinct FK target, grouped by the layer of the file that creates it.

    This IS the classification 16-roadmap.md:454 names -- printed on every run, green or red,
    because a classification nobody can read is a classification nobody can check. `UNKNOWN` holds
    the targets no migration on disk creates; clause 1 decides whether that is a failure.
    """
    census: dict[str, set[str]] = {}
    for fk in schema.foreign_keys:
        layer = schema.layer_of.get(fk.parent_table, "UNKNOWN")
        census.setdefault(layer, set()).add(fk.parent_table)
    return {layer: sorted(names) for layer, names in sorted(census.items())}


def audit(root: Path) -> tuple[Schema, list[Finding], list[str]]:
    schema = read_schema(root)
    fk_findings, deferred = clause_fk_targets(schema)
    findings = [
        *fk_findings,
        *clause_second_text_column(schema),
        *clause_positional_block_reference(schema),
    ]
    for duplicate in schema.duplicates:
        findings.append(
            Finding(
                clause="duplicate-name",
                subject=duplicate,
                where=root.name,
                detail=(
                    "declared twice across the migration set. A name is global in sqlite_master, "
                    "so the second CREATE aborts every store that applied the first "
                    "(11-repo-layout.md section 5.2)."
                ),
            )
        )
    return schema, findings, deferred


def _emit(out: TextIO, message: str = "") -> None:
    """The only write. T20 is enabled repo-wide, so a gate reports through an injected `TextIO`."""
    out.write(message + "\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    out: TextIO | None = None,
    root: Path | None = None,
) -> int:
    """Run the three clauses over `root` (default `MIGRATIONS`) and report."""
    writer = sys.stdout if out is None else out
    arguments: Iterable[str] = sys.argv[1:] if argv is None else argv
    extra = list(arguments)
    if extra:
        _emit(writer, f"schema-lint DID NOT RUN  unexpected argument(s): {extra}")
        _emit(writer, "usage: uv run tools/gate_schema_lint.py   (no arguments)")
        return EXIT_NOT_RUN
    where = MIGRATIONS if root is None else root
    if not where.is_dir():
        _emit(writer, f"schema-lint DID NOT RUN  no such directory: {where}")
        return EXIT_NOT_RUN
    files = migration_files(where)
    if not files:
        _emit(writer, f"schema-lint DID NOT RUN  no *.sql in {where}")
        return EXIT_NOT_RUN

    schema, findings, deferred = audit(where)
    _emit(writer, f"schema-lint  {len(files)} migration(s) in {where}")
    for path in files:
        prefix = re.match(r"^(\d+)", path.name)
        number = int(prefix.group(1)) if prefix else -1
        layer = LAYER_BY_MIGRATION.get(number, f"EXT{number}" if number >= 0 else "UNNUMBERED")
        owned = sorted(n for n, lay in schema.layer_of.items() if lay == layer)
        _emit(writer, f"  {path.name:<22} {layer:<9} {len(owned)} table(s)/view(s)")
    _emit(
        writer,
        f"  objects     {len(schema.tables)} tables, {len(schema.indexes)} indexes, "
        f"{len(schema.views)} views, {len(schema.triggers)} triggers",
    )
    _emit(
        writer,
        f"  edges       {len(schema.foreign_keys)} foreign key(s), "
        f"{len(reaches_block(schema))} table(s) reaching a Block",
    )
    for layer, targets in fk_target_census(schema).items():
        _emit(writer, f"  fk targets  {layer:<9} {', '.join(targets)}")
    if not schema.dense:
        _emit(
            writer,
            "  NOTE        the numeric prefixes are not 1..N, so an unresolvable FK target is "
            "reported as deferred rather than failed (G27b owns density).",
        )
    for note in deferred:
        _emit(writer, f"  deferred    {note}")
    _emit(writer)

    if findings:
        for finding in findings:
            _emit(writer, f"FAIL  {finding.clause:<14} {finding.subject}   {finding.where}")
            _emit(writer, f"      {finding.detail}")
        _emit(
            writer,
            f"\nschema-lint FAIL  {len(findings)} finding(s) over {len(schema.tables)} table(s).",
        )
        return EXIT_FAIL
    _emit(
        writer,
        "schema-lint ok  every FK target classified, GR15 holds, no second text column, "
        "no positional Block reference.",
    )
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
