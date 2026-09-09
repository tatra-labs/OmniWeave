"""`model/records.py` -- the L2 records, asserted against the shipped DDL and against SQLite.

Specified by 03-document-model.md section 2.8 (:390-435) and section 9 (:1795-1804). The module
under test is W2.1's last remainder (16-roadmap.md section 3.3).

**The test that earns the file is `test_every_field_of_a_record_lands_in_a_column`.** These
records exist to become rows, so a field with no column and a NOT NULL column with no field are
both fatal, and both are invisible to any test that reads the record alone. The correspondence is
asserted in BOTH directions, per record, off `PRAGMA table_info` on a database the shipped
migrations actually built -- never off a transcription of the DDL, because a transcription is the
thing that goes stale. `ROW_SHAPES` below is the map, and its three allowance lists are the whole
editorial content of this file: a column may be absent from a record only if the sink mints it,
only if it carries the document scope the record is written inside, or only if the DDL gives it a
DEFAULT.

**Why `import sqlite3` is here at all.** INV-17 bans it outside `omniweave_core/store/`, and this
file needs it for the reason `test_migration_0001.py` and `test_store_integration.py` need it: the
obligation being tested is *"these values can be written into those columns and read back equal"*,
and nothing short of a real INSERT tests it. A field-to-column check that only compared names
would pass against a `BLOB` field bound to a `TEXT` column, against a `CHECK` the record violates,
and against a foreign key that does not resolve -- and the round-trip tests below fail on all
three. The semgrep half of the ban (`tools/semgrep/omniweave.yaml`) scopes every rule to
`packages/*/src/**` and so already exempts a test; ruff's half carries no `per-file-ignores` row
for tests, so the `noqa` is the narrowest available form of the exemption: one line, one file,
with the reason attached.

`_plan/` is `.gitignore`d, so every test that reads a plan document calls `plan.require()` first
and skips when the design tree is absent (see `tests/conftest.py`).
"""

from __future__ import annotations

import dataclasses
import json
import re
import sqlite3  # noqa: TID251 -- see the module docstring: the records are asserted as ROWS.
from typing import TYPE_CHECKING, Any, Literal, get_args, get_type_hints

import pytest
from omniweave_core import model as model_surface
from omniweave_core.errors import ModelError, load_register
from omniweave_core.model import block as block_module
from omniweave_core.model import records
from omniweave_core.model.block import Capabilities
from omniweave_core.model.enums import ENUM_DOMAINS, Method, PageKind, Quote, RelKind, Trust
from omniweave_core.model.enums import enum_val_rows as _enum_val_rows
from omniweave_core.model.records import (
    DOC_STATUSES,
    QUAD_ORIGINS,
    SEVERITIES,
    AssetDraft,
    AssetRef,
    Diag,
    DocKey,
    DocRecord,
    PageRecord,
    Producer,
    Rel,
)
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path


NOW_NS = 1_757_400_000_000_000_000
"""A fixed wall clock. `time.time()` is banned in library code and `apply_pending` takes the
clock as an argument, so a test that read the ambient clock would assert against a value the
production path cannot produce."""


# ---------------------------------------------------------------------------------------------
# The map from record to row, and the three reasons a column may have no field.
# ---------------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RowShape:
    """One record, the table it becomes, and every allowance, each with its reason.

    `renames` exists because two records spell a column differently on purpose: `Rel.src`/`dst`
    are 03:440's field names against `src_id`/`dst_id`, and `Diag.block` is 03:1801's against
    `block_id`. Both are one-line facts and both would otherwise read as missing columns.
    """

    record: type
    table: str
    renames: dict[str, str] = dataclasses.field(default_factory=dict)
    minted: frozenset[str] = frozenset()
    scope: frozenset[str] = frozenset()


ROW_SHAPES: tuple[RowShape, ...] = (
    RowShape(record=Producer, table="producer", minted=frozenset({"producer_id"})),
    RowShape(record=DocRecord, table="doc"),
    RowShape(
        record=PageRecord,
        table="page",
        # `page.producer_id` is NOT NULL with no default and `PageRecord` has no such field:
        # the runner stamps provenance and the driver never does, exactly as `BlockDraft`
        # carries no `producer_id` either. Reported, because 03:559's `begin_page(page)` takes
        # the record and nothing else.
        minted=frozenset({"producer_id"}),
        scope=frozenset({"doc_ord", "gen"}),
    ),
    RowShape(
        record=AssetDraft,
        table="asset",
        # `store_ref` is the `cas://` locator only the CAS writer can produce, and `asset_id`
        # is the surrogate -- 03 section 2.10's `add_asset` row says it "writes `store_ref`".
        minted=frozenset({"asset_id", "store_ref"}),
        scope=frozenset({"doc_ord"}),
    ),
    RowShape(record=AssetRef, table="asset", scope=frozenset({"doc_ord"})),
    RowShape(
        record=Rel,
        table="rel",
        renames={"src": "src_id", "dst": "dst_id"},
        scope=frozenset({"doc_ord", "gen"}),
    ),
    RowShape(
        record=Diag,
        table="diag",
        renames={"block": "block_id"},
        scope=frozenset({"doc_ord", "gen"}),
    ),
)
"""Every record in `records.py`, mapped to its table. Asserted exhaustive by
`test_every_record_in_the_module_has_a_row_shape`, so a record added later cannot skip the
field-to-column check by not appearing here."""

SHAPES_BY_NAME = {shape.record.__name__: shape for shape in ROW_SHAPES}


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A real `.owstore` with all four shipped migrations applied, closed and re-openable."""
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        applied = migrate.apply_pending(connection, now_ns=NOW_NS)
        assert len(applied) == 4, f"expected four migrations, applied {len(applied)}"
    finally:
        connection.close()
    return path


@dataclasses.dataclass(frozen=True)
class Column:
    """One `PRAGMA table_info` row, reduced to the three facts this file asks about."""

    name: str
    not_null: bool
    has_default: bool


def columns_of(connection: sqlite3.Connection, table: str) -> dict[str, Column]:
    """The table's columns, from the database rather than from a copy of the DDL."""
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    assert rows, f"{table} does not exist in the migrated store"
    return {
        row[1]: Column(name=row[1], not_null=bool(row[3]), has_default=row[4] is not None)
        for row in rows
    }


# ---------------------------------------------------------------------------------------------
# 1. The correspondence that earns the file: fields against columns, both directions.
# ---------------------------------------------------------------------------------------------


def test_every_record_in_the_module_has_a_row_shape() -> None:
    """A record added to `records.py` cannot dodge the field-to-column check.

    Enumerated off `records.__all__` and not off a hand-kept list, so a new record is either
    mapped to a table here or it fails this test on the day it lands.
    """
    declared = {
        name
        for name in records.__all__
        if dataclasses.is_dataclass(getattr(records, name))
        and isinstance(getattr(records, name), type)
    }
    assert declared == set(SHAPES_BY_NAME), (
        "every dataclass in records.__all__ needs a ROW_SHAPES entry; "
        f"unmapped: {sorted(declared - set(SHAPES_BY_NAME))}"
    )


@pytest.mark.parametrize("shape", ROW_SHAPES, ids=lambda s: s.record.__name__)
def test_every_field_of_a_record_lands_in_a_column(shape: RowShape, store: Path) -> None:
    """A record whose fields the store cannot persist is worse than no record.

    Read off `PRAGMA table_info` on a migrated database, so the assertion is against the DDL
    SQLite parsed and not against a transcription of it.
    """
    connection = sqlite3.connect(store)
    try:
        columns = columns_of(connection, shape.table)
    finally:
        connection.close()
    for field in dataclasses.fields(shape.record):
        column = shape.renames.get(field.name, field.name)
        assert column in columns, (
            f"{shape.record.__name__}.{field.name} has no column {column!r} on "
            f"{shape.table}; the store cannot persist it"
        )


@pytest.mark.parametrize("shape", ROW_SHAPES, ids=lambda s: s.record.__name__)
def test_every_required_column_has_a_field_or_a_named_reason(shape: RowShape, store: Path) -> None:
    """The reverse direction: a NOT NULL column with no default needs a field or an allowance.

    The three allowances are the only ones -- `minted` (a surrogate or a locator only the sink
    can produce), `scope` (`doc_ord`/`gen`, the document the record is written inside) and a
    DDL DEFAULT. Anything else absent means a row the record cannot fill.
    """
    connection = sqlite3.connect(store)
    try:
        columns = columns_of(connection, shape.table)
    finally:
        connection.close()
    covered = {
        shape.renames.get(field.name, field.name) for field in dataclasses.fields(shape.record)
    }
    for column in columns.values():
        if column.name in covered or column.has_default:
            continue
        if column.name in shape.minted or column.name in shape.scope:
            continue
        # An `INTEGER PRIMARY KEY` is a rowid alias: SQLite reports `notnull = 0` and fills it.
        if not column.not_null:
            continue
        pytest.fail(
            f"{shape.table}.{column.name} is NOT NULL with no DEFAULT and no "
            f"{shape.record.__name__} field, and is not listed as minted or scope"
        )


def test_the_records_cover_every_l2_row_the_plan_prints() -> None:
    """The seven names 03 section 2.8 and section 9 owe, minus the one homed elsewhere.

    `Frame` is 03:444's and is deliberately absent: it already exists at
    `archive/frames.py:94`, and INV-21 gives one name one home. Asserted so the absence stays a
    decision rather than becoming an oversight.
    """
    assert set(SHAPES_BY_NAME) == {
        "Producer",
        "DocRecord",
        "PageRecord",
        "AssetDraft",
        "AssetRef",
        "Rel",
        "Diag",
    }
    assert not hasattr(records, "Frame"), "Frame is archive/frames.py's -- INV-21"
    assert not hasattr(records, "CellDraft"), "CellDraft is 03 section 2.6's, i.e. block.py's"


# ---------------------------------------------------------------------------------------------
# 2. Frozen, slotted, and the two mapping defaults.
# ---------------------------------------------------------------------------------------------


def a_producer() -> Producer:
    return Producer(operator="parse.pdf", op_version=1, code_fingerprint="ow128:abc")


def a_doc_record(**over: Any) -> DocRecord:
    """One valid `DocRecord`, with the fields a test varies overridable.

    A helper rather than a fixture because several tests need two records that differ in one
    field, and `dataclasses.replace` on a frozen record re-runs `__post_init__`, which is the
    validation half of what is being tested.
    """
    caps = Capabilities(
        spatial="block_bbox",
        origin_span="exact",
        text_span=True,
        marks=True,
        reading_order="char_stream",
        sections="typed_levels",
        tables="cells_with_spans",
        math=frozenset({"latex"}),
        assets="bytes",
        asset_origin=True,
        notes="linked",
        confidence="page",
        furniture="separated",
        round_trip="structure",
    )
    values: dict[str, Any] = {
        "doc_ord": 7,
        "doc_key": DocKey(bytes(range(16))),
        "gen": 1,
        "source_sha256": bytes(range(32)),
        "normalizer": "canonical/1",
        "uri": "file:///corpus/report.pdf",
        "media_type": "application/pdf",
        "format": "pdf",
        "format_evidence": {"magic": "%PDF-1.7"},
        "source_bytes": 4096,
        "status": "ok",
        "page_count": 3,
        "model_version": "1.1",
        "declared": caps,
        "achieved": caps,
        "confidence": {"parse": 0.94, "ocr": None},
        "timings_ms": {"parse": 812},
    }
    values.update(over)
    return DocRecord(**values)


def a_page_record(**over: Any) -> PageRecord:
    values: dict[str, Any] = {
        "page": 0,
        "page_kind": PageKind.PAGE,
        "label": "iv",
        "w_mpt": 612_000,
        "h_mpt": 792_000,
        "rotation": 0,
        "quad_origin": "topleft",
        "method": Method.TEXT_LAYER,
        "status": "ok",
        "parse_score": 0.91,
    }
    values.update(over)
    return PageRecord(**values)


def a_diag(**over: Any) -> Diag:
    values: dict[str, Any] = {
        "code": "OW_TABLE_SPAN_CLAMPED",
        "severity": "warning",
        "component": "parse.pdf",
        "message": "a row span exceeded the budget; run ow doc verify d7#1",
    }
    values.update(over)
    return Diag(**values)


def an_asset_draft() -> AssetDraft:
    return AssetDraft(
        media_type="image/png",
        sha256=bytes(range(32)),
        byte_len=1024,
        origin_part="word/media/image1.png",
        width=640,
        height=480,
        licence="CC-BY-4.0",
        licence_url="https://creativecommons.org/licenses/by/4.0/",
        spdx="CC-BY-4.0",
        source_url="https://example.invalid/i.png",
        retrieved_at_ns=NOW_NS,
    )


ALL_INSTANCES = {
    "Producer": a_producer,
    "DocRecord": a_doc_record,
    "PageRecord": a_page_record,
    "AssetDraft": an_asset_draft,
    "AssetRef": lambda: AssetRef(
        asset_id=1,
        media_type="image/png",
        sha256=bytes(range(32)),
        byte_len=1024,
        width=640,
        height=480,
        store_ref="cas://00/01/" + bytes(range(32)).hex(),
        restriction_bits=0,
    ),
    "Rel": lambda: Rel(
        src=1,
        dst=2,
        kind=RelKind.CAPTION_OF,
        producer_id=1,
        trust=Trust.INFERRED,
        score=None,
        score_kind=None,
        origin_operator="parse.pdf",
    ),
    "Diag": a_diag,
}


@pytest.mark.parametrize("name", sorted(ALL_INSTANCES))
def test_every_record_is_frozen_and_slotted(name: str) -> None:
    """Assignment raises and there is no instance `__dict__`.

    Asserted over the whole module by name rather than per class, so a record cannot arrive
    mutable or dict-carrying by omission -- the same discipline `test_model_block.py` applies.
    """
    instance = ALL_INSTANCES[name]()
    first = dataclasses.fields(instance)[0].name
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(instance, first, getattr(instance, first))
    assert not hasattr(instance, "__dict__"), f"{name} is slots=True, so it has no __dict__"
    assert type(instance).__dataclass_params__.frozen is True
    assert "__slots__" in type(instance).__dict__


def test_the_mappingproxy_defaults_are_shared_but_immutable() -> None:
    """03:412's and 03:424's `MappingProxyType({})` default is not a shared MUTABLE.

    The two halves matter separately. Shared: two records built without `x` hold the same object,
    which is what makes the printed default legal at all. Immutable: mutating it raises
    `TypeError` rather than reaching the other instance -- so the classic mutable-default bug is
    unreachable, and the proof is that a *different* instance is unchanged afterwards.
    """
    first, second = a_doc_record(), a_doc_record()
    assert first.x is second.x, "the printed default is one shared MappingProxyType"
    with pytest.raises(TypeError):
        first.x["x.vendor.note"] = 1  # type: ignore[index]
    assert dict(second.x) == {}, "a different instance's default is untouched"
    assert dict(first.x) == {}

    pages = a_page_record(), a_page_record()
    assert pages[0].stats is pages[1].stats
    with pytest.raises(TypeError):
        pages[0].stats["n"] = 1  # type: ignore[index]
    assert dict(pages[1].stats) == {}


def test_the_diag_detail_default_is_a_fresh_dict_per_instance() -> None:
    """03:1803 uses `field(default_factory=dict)` where section 2.8 uses `MappingProxyType({})`.

    The asymmetry is the plan's, transcribed rather than smoothed, and it is safe for the OTHER
    reason: a factory allocates per instance, so mutating one `detail` cannot reach another.
    Both halves of the asymmetry are therefore proved, not assumed.
    """
    first, second = a_diag(), a_diag()
    assert first.detail is not second.detail, "a default_factory allocates per instance"
    first.detail["clamped_to"] = 4  # type: ignore[index]
    assert second.detail == {}, "mutating one Diag.detail must not reach another"


# ---------------------------------------------------------------------------------------------
# 3. The three CHECK-backed vocabularies: the constant, the annotation and the database agree.
# ---------------------------------------------------------------------------------------------


def check_members(connection: sqlite3.Connection, table: str, column: str) -> tuple[str, ...]:
    """The membership of `column`'s inline `CHECK(... IN (...))`, read out of the shipped DDL.

    Read from `sqlite_master.sql` -- the text SQLite itself stored -- and not from the migration
    file, so a migration that stopped being applied could not make this pass. The pattern
    demands the column name immediately before `IN`, so a CHECK on a different column cannot
    satisfy it.
    """
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    assert row is not None, f"{table} is not in sqlite_master"
    sql = re.sub(r"--[^\n]*", "", row[0])  # a comment is not a definition site
    match = re.search(rf"CHECK\(\s*{column}\s+IN\s*\(([^)]*)\)\s*\)", sql)
    assert match is not None, f"{table}.{column} carries no inline CHECK(... IN ...)"
    return tuple(part.strip().strip("'") for part in match.group(1).split(","))


@pytest.mark.parametrize(
    ("constant", "record", "field", "table", "column"),
    [
        (DOC_STATUSES, DocRecord, "status", "doc", "status"),
        (QUAD_ORIGINS, PageRecord, "quad_origin", "page", "quad_origin"),
        (SEVERITIES, Diag, "severity", "diag", "severity"),
    ],
    ids=["doc.status", "page.quad_origin", "diag.severity"],
)
def test_the_constant_the_literal_annotation_and_the_check_all_agree(
    *,
    constant: tuple[str, ...],
    record: type,
    field: str,
    table: str,
    column: str,
    store: Path,
) -> None:
    """Three transcriptions of one closed vocabulary, held equal in one place.

    The module declares a tuple because a `Literal` is not enforced at runtime; the annotation is
    what a type checker reads; the CHECK is what the database enforces. Any two agreeing while
    the third drifts is exactly the failure this asserts away.
    """
    hints = get_type_hints(record)
    annotation = hints[field]
    args = get_args(annotation)
    if type(None) in args:  # `quad_origin` is `Literal[...] | None`
        literal = next(arg for arg in args if arg is not type(None))
        args = get_args(literal)
    assert args == constant, f"{record.__name__}.{field}'s Literal is not {constant}"

    connection = sqlite3.connect(store)
    try:
        assert check_members(connection, table, column) == constant
    finally:
        connection.close()


@pytest.mark.parametrize("status", DOC_STATUSES)
def test_doc_status_accepts_each_of_its_four_values(status: str) -> None:
    assert a_doc_record(status=status).status == status


def test_doc_status_refuses_a_fifth_value_and_names_the_allowed_set() -> None:
    """`doc.status`'s CHECK, refused in Python so the traceback names the driver, not the store.

    Without this the failure is an `sqlite3.IntegrityError` raised inside `StoreThread`, five
    frames from the code that built the record and carrying no allowed set.
    """
    with pytest.raises(ModelError) as caught:
        a_doc_record(status="quarantined")
    message = str(caught.value)
    assert "quarantined" in message
    for allowed in DOC_STATUSES:
        assert repr(allowed) in message
    assert caught.value.fix, "OwError refuses an empty fix"


@pytest.mark.parametrize("severity", SEVERITIES)
def test_diag_severity_accepts_each_of_its_three_values(severity: str) -> None:
    assert a_diag(severity=severity).severity == severity


def test_diag_severity_refuses_a_fourth_value() -> None:
    with pytest.raises(ModelError, match=r"Diag\.severity"):
        a_diag(severity="critical")


@pytest.mark.parametrize("origin", QUAD_ORIGINS)
def test_page_quad_origin_accepts_each_of_its_two_values(origin: str) -> None:
    assert a_page_record(quad_origin=origin).quad_origin == origin


def test_page_quad_origin_accepts_null_and_refuses_a_third_spelling() -> None:
    """NULL is a value: "the driver declared no coordinate frame", not "unset"."""
    assert a_page_record(quad_origin=None).quad_origin is None
    with pytest.raises(ModelError, match="quad_origin"):
        a_page_record(quad_origin="bottom-left")


def test_page_status_is_a_bare_string_and_is_not_policed() -> None:
    """03:418 prints `status: str`, and `page.status` carries a DEFAULT and no CHECK.

    The asymmetry with `doc.status` is the plan's, so it is asserted rather than corrected: a
    later reader who "fixes" it by adding a Literal breaks this test and reads why.
    """
    assert get_type_hints(PageRecord)["status"] is str
    assert a_page_record(status="degraded").status == "degraded"


# ---------------------------------------------------------------------------------------------
# 4. `Diag.code` is the symbol, never the numeric.
# ---------------------------------------------------------------------------------------------


def test_diag_code_accepts_a_codes_toml_symbol() -> None:
    assert a_diag(code="OW_RESOURCE_LIMIT").code == "OW_RESOURCE_LIMIT"


def test_diag_code_refuses_a_numeric_and_the_message_names_codes_toml() -> None:
    """03:1807: callers branch on the SYMBOL and the CLI prints the numeric.

    `code TEXT NOT NULL` would accept `OW-M-014` silently, and `CREATE INDEX diag_code` would
    then index a spelling no caller branches on -- which is the index the absence contract's
    `parse_gap_in_scope` gate joins against (03:1809-1811). So the refusal has to be here.
    """
    with pytest.raises(ModelError) as caught:
        a_diag(code="OW-M-014")
    message = str(caught.value)
    assert "codes.toml" in message, "the message must name the register"
    assert "OW-M-014" in message
    assert "SYMBOL" in message


@pytest.mark.parametrize("bad", ["", "ow_lower_case", "TABLE_SPAN_CLAMPED", "OW_", "42"])
def test_diag_code_refuses_anything_that_is_not_symbol_shaped(bad: str) -> None:
    """`errors.SYMBOL_RE` is the register's own shape, imported rather than retyped."""
    with pytest.raises(ModelError, match=r"codes\.toml symbol"):
        a_diag(code=bad)


def test_every_symbol_in_the_shipped_register_is_accepted_as_a_diag_code() -> None:
    """The refusal must not be stricter than `codes.toml` itself.

    A shape check that rejected a real symbol would be worse than no check: it would refuse a
    diagnostic the framework is required to record. Derived from the register, so it cannot
    disagree with it.
    """
    register = load_register()
    assert register.by_symbol, "codes.toml declares no rows"
    for symbol in register.by_symbol:
        assert a_diag(code=symbol).code == symbol


# ---------------------------------------------------------------------------------------------
# 5. `DocRecord.x` -- 03:302's extension-key grammar.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["x.ow.unknown", "x.ow.cite", "x.vendor.note", "x.a1_b.c2_d"])
def test_doc_record_x_accepts_a_well_formed_extension_key(key: str) -> None:
    record = a_doc_record(x={key: 1})
    assert record.x[key] == 1
    assert dict(record.x) == {key: 1}


@pytest.mark.parametrize(
    "key",
    ["ow.unknown", "x.ow", "x.OW.unknown", "x.ow.unknown.deeper", "x..y", "note", "x.ow-v.n"],
)
def test_doc_record_x_refuses_a_key_outside_the_grammar(key: str) -> None:
    """03:302 fixes the grammar INCLUDING the leading `x.` segment.

    `doc.x` appears on no `DocSink` method's enforcement list (03 section 2.10's table), so
    unlike `block.x` there is no later gate: a malformed key here is durable. The prefix is part
    of the stored key, which is why `archive/owdoc.py:663` writes `x["x.ow.cite"]` in full.
    """
    with pytest.raises(ModelError, match=r"x\.<vendor>\.<name>"):
        a_doc_record(x={key: 1})


def test_doc_record_x_defaults_to_empty_and_is_not_policed_when_absent() -> None:
    assert dict(a_doc_record().x) == {}


# ---------------------------------------------------------------------------------------------
# 6. `DocKey` -- the fourth identity, and why it is a NewType.
# ---------------------------------------------------------------------------------------------


def test_dockey_is_a_newtype_over_bytes_and_is_declared_exactly_once() -> None:
    """03:162's fourth identity, homed with its only consumer.

    `block.py:90-93` declines it in a comment on the ground that a `Block` never carries it, so
    the assertion is that it exists here and NOT there -- one name, one home (INV-21).
    """
    assert DocKey.__supertype__ is bytes
    assert not hasattr(block_module, "DocKey"), "block.py:90 declines DocKey on purpose"
    assert DocKey(b"0123456789abcdef") == b"0123456789abcdef"


# ---------------------------------------------------------------------------------------------
# 7. The round trip: every record written into its table and read back equal.
# ---------------------------------------------------------------------------------------------

_ORDINALS = {(domain, name): ordinal for domain, ordinal, name in _enum_val_rows()}
"""`(domain, member name) -> the stored integer`, from `enum_val_rows()`, the single site that
applies 03 section 2.1's ordinal rule. Never recomputed here: an independent second derivation
is how the two drift."""


def ordinal(member: Any) -> int:
    """The integer the DDL's `INTEGER` enum column holds for this member."""
    domain = next(name for name, kind in ENUM_DOMAINS.items() if kind is type(member))
    return _ORDINALS[(domain, member.name.lower())]


def caps_json(caps: Capabilities) -> str:
    """`doc.declared` / `doc.achieved` as the DDL's `TEXT ... (JSON)`.

    `frozenset` has no JSON form, so the two set-valued fields are sorted into lists -- which is
    also what makes the column byte-stable across runs.
    """
    payload = {
        f.name: sorted(getattr(caps, f.name))
        if isinstance(getattr(caps, f.name), frozenset)
        else getattr(caps, f.name)
        for f in dataclasses.fields(caps)
    }
    return json.dumps(payload, sort_keys=True)


def test_a_producer_round_trips_through_the_producer_table(store: Path) -> None:
    """The reproduction tuple, written and read back field for field."""
    producer = a_producer()
    connection = sqlite3.connect(store)
    try:
        # S608: the column list is `dataclasses.fields(...)`'s output, so the interpolated
        # text is the RECORD's own field names and nothing reaches it from outside this
        # file. Interpolating them is the point: a hand-typed column list would pass while
        # the record grew a field, which is the exact drift this test exists to catch.
        names = [f.name for f in dataclasses.fields(producer)]
        connection.execute(
            f"INSERT INTO producer (producer_id, {', '.join(names)}) "  # noqa: S608
            f"VALUES (1, {', '.join('?' for _ in names)})",
            [getattr(producer, name) for name in names],
        )
        connection.commit()
        row = connection.execute(
            f"SELECT {', '.join(names)} FROM producer WHERE producer_id = 1"  # noqa: S608
        ).fetchone()
    finally:
        connection.close()
    assert Producer(*row) == producer


def insert_doc(connection: sqlite3.Connection, record: DocRecord) -> None:
    """One `doc` row from a `DocRecord`, every field bound, `next_cite_n` left to its DEFAULT."""
    connection.execute(
        """INSERT INTO doc (doc_ord, doc_key, source_sha256, normalizer, uri, media_type,
                            format, format_evidence, source_bytes, gen, status, page_count,
                            model_version, declared, achieved, confidence, timings_ms, x)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            record.doc_ord,
            record.doc_key,
            record.source_sha256,
            record.normalizer,
            record.uri,
            record.media_type,
            record.format,
            json.dumps(dict(record.format_evidence), sort_keys=True),
            record.source_bytes,
            record.gen,
            record.status,
            record.page_count,
            record.model_version,
            caps_json(record.declared),
            caps_json(record.achieved),
            json.dumps(dict(record.confidence), sort_keys=True),
            json.dumps(dict(record.timings_ms), sort_keys=True),
            json.dumps(dict(record.x), sort_keys=True),
        ),
    )


def test_a_doc_record_round_trips_through_the_doc_table(store: Path) -> None:
    """Nineteen columns, eighteen fields, and `next_cite_n` filled by the DDL's DEFAULT.

    The read-back compares the scalar fields directly and the four JSON columns as decoded
    objects, because the columns are `TEXT` and the fields are `Mapping`s -- the encoding is the
    store's business and the equality being asserted is of values.
    """
    record = a_doc_record(x={"x.ow.unknown": {"brand_new": 1}})
    connection = sqlite3.connect(store)
    try:
        insert_doc(connection, record)
        connection.commit()
        row = connection.execute(
            """SELECT doc_ord, doc_key, source_sha256, normalizer, uri, media_type, format,
                      format_evidence, source_bytes, gen, next_cite_n, status, page_count,
                      model_version, declared, achieved, confidence, timings_ms, x
               FROM doc WHERE doc_ord = ?""",
            (record.doc_ord,),
        ).fetchone()
    finally:
        connection.close()
    assert row[:7] == (
        record.doc_ord,
        record.doc_key,
        record.source_sha256,
        record.normalizer,
        record.uri,
        record.media_type,
        record.format,
    )
    assert json.loads(row[7]) == dict(record.format_evidence)
    assert row[8:14] == (
        record.source_bytes,
        record.gen,
        1,  # next_cite_n's DEFAULT -- the cite counter is the sink's, never the record's
        record.status,
        record.page_count,
        record.model_version,
    )
    assert json.loads(row[14]) == json.loads(caps_json(record.declared))
    assert json.loads(row[15]) == json.loads(caps_json(record.achieved))
    assert json.loads(row[16]) == dict(record.confidence)
    assert json.loads(row[17]) == dict(record.timings_ms)
    assert json.loads(row[18]) == dict(record.x)


def test_the_doc_status_check_is_live_in_the_shipped_store(store: Path) -> None:
    """The Python refusal is a better error, not a replacement for the constraint.

    Written by bypassing the record, because that is the only way to reach the CHECK: if this
    ever stops raising, the DDL lost the constraint and `DocRecord.__post_init__` became the only
    thing standing between a driver and a bad row.
    """
    record = a_doc_record()
    connection = sqlite3.connect(store)
    try:
        object.__setattr__(record, "status", "quarantined")
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            insert_doc(connection, record)
    finally:
        connection.close()


def test_a_page_record_round_trips_through_the_page_table(store: Path) -> None:
    """`page_kind` and `method` go in as their `enum_val` ordinals, and come back as them.

    `doc_ord`, `gen` and `producer_id` are supplied here the way `DocSink.begin_page` has to
    supply them, which is the point of the test as much as the round trip is: the record alone
    cannot fill the row.
    """
    doc = a_doc_record()
    page = a_page_record(stats={"lines": 42})
    connection = sqlite3.connect(store)
    try:
        producer = a_producer()
        connection.execute(
            "INSERT INTO producer (producer_id, operator, op_version, code_fingerprint, "
            "options_digest) VALUES (1, ?, ?, ?, ?)",
            (producer.operator, producer.op_version, producer.code_fingerprint, b""),
        )
        insert_doc(connection, doc)
        connection.execute(
            """INSERT INTO page (doc_ord, gen, page, page_kind, label, w_mpt, h_mpt, rotation,
                                 quad_origin, method, status, ocr_error_score, parse_score,
                                 layout_score, table_score, ocr_score, producer_id, stats)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                doc.doc_ord,
                doc.gen,
                page.page,
                ordinal(page.page_kind),
                page.label,
                page.w_mpt,
                page.h_mpt,
                page.rotation,
                page.quad_origin,
                ordinal(page.method),
                page.status,
                page.ocr_error_score,
                page.parse_score,
                page.layout_score,
                page.table_score,
                page.ocr_score,
                1,
                json.dumps(dict(page.stats), sort_keys=True),
            ),
        )
        connection.commit()
        row = connection.execute(
            """SELECT page, page_kind, label, w_mpt, h_mpt, rotation, quad_origin, method,
                      status, ocr_error_score, parse_score, layout_score, table_score,
                      ocr_score, stats
               FROM page WHERE doc_ord = ? AND gen = ? AND page = ?""",
            (doc.doc_ord, doc.gen, page.page),
        ).fetchone()
    finally:
        connection.close()
    assert (
        PageRecord(
            page=row[0],
            page_kind=PageKind(next(k for k in PageKind if ordinal(k) == row[1])),
            label=row[2],
            w_mpt=row[3],
            h_mpt=row[4],
            rotation=row[5],
            quad_origin=row[6],
            method=Method(next(m for m in Method if ordinal(m) == row[7])),
            status=row[8],
            ocr_error_score=row[9],
            parse_score=row[10],
            layout_score=row[11],
            table_score=row[12],
            ocr_score=row[13],
            stats=json.loads(row[14]),
        )
        == page
    )


def test_an_asset_draft_round_trips_and_comes_back_as_an_asset_ref(store: Path) -> None:
    """The draft goes in; the ref is what a reader gets out. 03:426-436.

    Both halves in one test on purpose: `AssetDraft` and `AssetRef` are two projections of ONE
    row, so the only assertion that proves either is right is that the draft's fields survive
    and the ref's three extra columns come back with them.
    """
    doc = a_doc_record()
    draft = an_asset_draft()
    store_ref = (
        "cas://"
        + draft.sha256.hex()[:2]
        + "/"
        + draft.sha256.hex()[2:4]
        + "/"
        + (draft.sha256.hex())
    )
    connection = sqlite3.connect(store)
    try:
        insert_doc(connection, doc)
        # S608: the column list is `dataclasses.fields(...)`'s output, so the interpolated
        # text is the RECORD's own field names and nothing reaches it from outside this
        # file. Interpolating them is the point: a hand-typed column list would pass while
        # the record grew a field, which is the exact drift this test exists to catch.
        names = [f.name for f in dataclasses.fields(draft)]
        connection.execute(
            f"INSERT INTO asset (asset_id, doc_ord, store_ref, {', '.join(names)}) "  # noqa: S608
            f"VALUES (1, ?, ?, {', '.join('?' for _ in names)})",
            [doc.doc_ord, store_ref, *(getattr(draft, name) for name in names)],
        )
        connection.commit()
        back = connection.execute(
            f"SELECT {', '.join(names)} FROM asset WHERE asset_id = 1"  # noqa: S608
        ).fetchone()
        ref_row = connection.execute(
            "SELECT asset_id, media_type, sha256, byte_len, width, height, store_ref, "
            "restriction_bits FROM asset WHERE asset_id = 1"
        ).fetchone()
    finally:
        connection.close()
    assert AssetDraft(**dict(zip(names, back, strict=True))) == draft
    assert AssetRef(*ref_row) == AssetRef(
        asset_id=1,
        media_type=draft.media_type,
        sha256=draft.sha256,
        byte_len=draft.byte_len,
        width=draft.width,
        height=draft.height,
        store_ref=store_ref,
        restriction_bits=0,  # the DDL's DEFAULT; INV-16 stamps it at add_asset
    )


def test_a_diag_round_trips_through_the_diag_table(store: Path) -> None:
    """`fatal` is `INTEGER NOT NULL` with no DEFAULT, so the field's `False` is what fills it."""
    doc = a_doc_record()
    diag = a_diag(page=3000, part="word/document.xml", detail={"clamped_to": 4}, fatal=True)
    connection = sqlite3.connect(store)
    try:
        insert_doc(connection, doc)
        connection.execute(
            """INSERT INTO diag (doc_ord, gen, page, block_id, part, code, severity, component,
                                 message, detail, fatal)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                doc.doc_ord,
                doc.gen,
                diag.page,
                diag.block,
                diag.part,
                diag.code,
                diag.severity,
                diag.component,
                diag.message,
                json.dumps(dict(diag.detail), sort_keys=True),
                int(diag.fatal),
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT code, severity, component, message, page, block_id, part, detail, fatal "
            "FROM diag WHERE doc_ord = ?",
            (doc.doc_ord,),
        ).fetchone()
    finally:
        connection.close()
    assert (
        Diag(
            code=row[0],
            severity=row[1],
            component=row[2],
            message=row[3],
            page=row[4],
            block=row[5],
            part=row[6],
            detail=json.loads(row[7]),
            fatal=bool(row[8]),
        )
        == diag
    )


def test_a_rel_round_trips_through_the_rel_table(store: Path) -> None:
    """`src`/`dst` are 03:440's field names against `src_id`/`dst_id`, both FKs to `block`.

    Two real `block` rows are minted first, because `rel`'s foreign keys resolve: a test that
    inserted bare integers would pass against a schema whose FKs had been dropped.
    """
    doc = a_doc_record()
    page = a_page_record()
    rel = Rel(
        src=1,
        dst=2,
        kind=RelKind.CAPTION_OF,
        producer_id=1,
        trust=Trust.INFERRED,
        score=0.8,
        score_kind="model_logprob",
        origin_operator="parse.pdf",
    )
    connection = sqlite3.connect(store)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO producer (producer_id, operator, op_version, code_fingerprint, "
            "options_digest) VALUES (1, 'parse.pdf', 1, 'ow128:abc', ?)",
            (b"",),
        )
        insert_doc(connection, doc)
        connection.execute(
            "INSERT INTO page (doc_ord, gen, page, page_kind, method, producer_id) "
            "VALUES (?,?,?,?,?,1)",
            (doc.doc_ord, doc.gen, page.page, ordinal(page.page_kind), ordinal(page.method)),
        )
        for block_id, addr in ((1, "p0/0"), (2, "p0/1")):
            connection.execute(
                """INSERT INTO block (block_id, doc_ord, gen, page, addr, cite, ord, kind,
                                      layer, content_digest, os_kind, producer_id, method,
                                      trust, quote, origin_operator, origin_driver,
                                      driver_schema_v)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,'parse.pdf','parse.pdf.pdfium',1)""",
                (
                    block_id,
                    doc.doc_ord,
                    doc.gen,
                    page.page,
                    addr,
                    f"d{doc.doc_ord}#{block_id}",
                    block_id - 1,
                    _kind_ordinal("paragraph"),
                    _layer_ordinal("body"),
                    b"\x00" * 16,
                    _os_kind_ordinal("none"),
                    ordinal(page.method),
                    int(Trust.EXTRACTED),
                    _quote_ordinal(),
                ),
            )
        connection.execute(
            """INSERT INTO rel (doc_ord, gen, src_id, dst_id, kind, producer_id, trust, score,
                                score_kind, origin_operator)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                doc.doc_ord,
                doc.gen,
                rel.src,
                rel.dst,
                ordinal(rel.kind),
                rel.producer_id,
                int(rel.trust),
                rel.score,
                rel.score_kind,
                rel.origin_operator,
            ),
        )
        connection.commit()
        row = connection.execute(
            "SELECT src_id, dst_id, kind, producer_id, trust, score, score_kind, "
            "origin_operator FROM rel WHERE doc_ord = ?",
            (doc.doc_ord,),
        ).fetchone()
    finally:
        connection.close()
    assert (
        Rel(
            src=row[0],
            dst=row[1],
            kind=RelKind(next(k for k in RelKind if ordinal(k) == row[2])),
            producer_id=row[3],
            trust=Trust(row[4]),
            score=row[5],
            score_kind=row[6],
            origin_operator=row[7],
        )
        == rel
    )


def _kind_ordinal(name: str) -> int:
    return _ORDINALS[("kind", name)]


def _layer_ordinal(name: str) -> int:
    return _ORDINALS[("layer", name)]


def _os_kind_ordinal(name: str) -> int:
    return _ORDINALS[("origin_span_kind", name)]


def _quote_ordinal() -> int:
    return int(Quote.NORMALIZED)


# ---------------------------------------------------------------------------------------------
# 8. The re-export surface.
# ---------------------------------------------------------------------------------------------


def test_every_name_is_on_the_flat_model_surface() -> None:
    """02-architecture.md:248 puts the re-export surface on `omniweave_core.model`.

    A consumer writes `from omniweave_core.model import DocRecord`, so every public name here
    has to be bound and listed there -- checked in both directions against `records.__all__`.
    """
    for name in records.__all__:
        assert name in model_surface.__all__, f"{name} is not on the flat model surface"
        assert getattr(model_surface, name) is getattr(records, name)
    assert model_surface.__all__ == sorted(
        model_surface.__all__,
        key=lambda n: (0 if n.replace("_", "").isupper() else (1 if n[0].isupper() else 2), n),
    ), "model.__all__ is kept sorted"


def test_the_module_declares_only_what_the_plan_names() -> None:
    """A register is a transcription: nothing in `__all__` that the plan did not order.

    The seven records of 03 section 2.8 and section 9 (minus `Frame`), `DocKey` from 03:162, and
    the three CHECK vocabularies -- each of which exists only because a `Literal` is not
    enforced at runtime and the module needs the membership as data.
    """
    assert set(records.__all__) == {
        "DOC_STATUSES",
        "QUAD_ORIGINS",
        "SEVERITIES",
        "AssetDraft",
        "AssetRef",
        "Diag",
        "DocKey",
        "DocRecord",
        "PageRecord",
        "Producer",
        "Rel",
    }


def test_the_record_annotations_all_resolve_at_runtime() -> None:
    """`get_type_hints` must not raise: `ow schema emit` and `schemagen` both go through it.

    `block.py` records the trap this guards -- a `Mapping` imported only under
    `if TYPE_CHECKING:` makes the call raise `NameError`, and every runtime walk of this
    module's annotations dies with it.
    """
    for shape in ROW_SHAPES:
        hints = get_type_hints(shape.record)
        assert set(hints) == {f.name for f in dataclasses.fields(shape.record)}
    assert get_type_hints(DocRecord)["declared"] is Capabilities
    assert get_args(get_type_hints(Diag)["severity"]) == SEVERITIES
    assert get_type_hints(DocRecord)["status"] == Literal[DOC_STATUSES]
