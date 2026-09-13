"""`probe()`: one indexed query per Batch, the outstanding list, and a clause for every miss.

`08:1789-1800` gives three properties a naive `get(key)` loop does not have, and each is asserted
here against the returned record rather than against an intention:

1. *"One indexed query per Batch"* -- `CacheProbe.queries` counts the `IN` chunks, so a 256-unit
   batch reports 1 and a 2,000-unit one reports 3.
2. *"`outstanding` is what gets dispatched"* -- `hits` and `outstanding` partition the units, which
   `CacheProbe.__post_init__` refuses to let drift (08:2110's property 3).
3. *"Every miss carries its clause"* -- all six read-policy verdicts are reachable through the batch
   path, one test each.

The clause tests run through `probe()` rather than through `read_verdict()` directly: `read_verdict`
already has its own tests, and what is unproven until now is that the batch path *reaches* each
clause with the right facts -- `blob_ok` and `nonempty` are caller-supplied, and a probe that
evaluated them against the wrong entry would pass a policy test and fail a corpus.

## The tests that are defect reports

`test_the_namespace_a_row_belongs_to_is_not_derivable_from_the_row` shows `cache_ns()`'s five inputs
against `cache_index`'s columns: two of the five are on no column. **D171.**

`test_a_probe_cannot_reach_an_index_through_the_arguments_the_plan_prints` reads `RunContext`'s
fields and shows none of them is a cache, a blob store or an Operator. **D172.**
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import omniweave_core.store.sqlite as ow
import pytest
from omniweave_core.cache import (
    CACHE_INDEX_COLUMNS,
    DEFAULT_CACHE_RECIPE,
    IN_CHUNK,
    BatchIndex,
    CacheEntry,
    CacheHit,
    CacheLayer,
    CacheProbe,
    CacheVerdict,
    cache_ns,
    chunked,
    probe,
    same_namespace,
)
from omniweave_core.operator import RunContext
from omniweave_core.store import migrate
from omniweave_core.store.cache import SqliteCacheIndex, select_many_sql
from omniweave_ports.types import UnitRef

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Iterator, Mapping, Sequence
    from pathlib import Path

    from conftest import PlanDocs


REF = "cas://ab/cd/" + "ab" * 32


def _unit(n: int = 0, part: str = "") -> UnitRef:
    return UnitRef(
        uri=f"c:/x/{n}.pdf", part=part, content_sha256="9f" * 32, byte_len=10, media_type=""
    )


def _key(n: int = 0) -> str:
    return f"{n:064d}"


def _entry(n: int = 0, **extra: Any) -> CacheEntry:
    fields: dict[str, Any] = {
        "cache_key": _key(n),
        "layer": CacheLayer.CALL,
        "cost_class": "free",
        "ref": REF,
        "bytes": 100,
        "unit_uri": f"c:/x/{n}.pdf",
        "unit_part": "",
        "driver": "parse.pdf.pdfium",
        "driver_schema_v": 1,
        "config_digest": "cfg",
        "origin_operator": "parse.pdf",
        "spend_json": '{"wall_ms":12}',
        "micros": 7,
    }
    fields.update(extra)
    return CacheEntry(**fields)


class _Index:
    """A `BatchIndex` that records what it was asked, so property 1 is observable."""

    def __init__(self, rows: Sequence[CacheEntry] = ()) -> None:
        self.rows = {entry.cache_key: entry for entry in rows}
        self.calls: list[tuple[str, ...]] = []

    def get_many(self, keys: Sequence[str]) -> Mapping[str, CacheEntry]:
        self.calls.append(tuple(keys))
        return {key: self.rows[key] for key in keys if key in self.rows}


# ---------------------------------------------------------------------------------------------
# 1. Property 1: one indexed query per Batch
# ---------------------------------------------------------------------------------------------


def test_a_full_batch_is_one_query_and_not_one_per_unit() -> None:
    """08:1791: *"At `batch = 256` that is one statement instead of 256."*"""
    units = [_unit(n) for n in range(256)]
    keys = [_key(n) for n in range(256)]
    index = _Index()
    result = probe(units, keys, index=index, layer=CacheLayer.CALL)
    assert result.queries == 1
    assert len(index.calls) == 1
    assert len(index.calls[0]) == 256


def test_the_in_list_is_chunked_at_the_variable_number_floor() -> None:
    """08:1793: *"chunked at 900 to stay under SQLite's `SQLITE_MAX_VARIABLE_NUMBER` floor."*"""
    assert IN_CHUNK == 900
    units = [_unit(n) for n in range(2000)]
    keys = [_key(n) for n in range(2000)]
    result = probe(units, keys, index=_Index(), layer=CacheLayer.CALL)
    assert result.queries == 3


def test_chunked_preserves_order_and_refuses_a_zero_width() -> None:
    assert list(chunked(("a", "b", "c"), 2)) == [("a", "b"), ("c",)]
    assert list(chunked((), 2)) == []
    with pytest.raises(ValueError, match="at least one key"):
        list(chunked(("a",), 0))


def test_a_repeated_key_is_asked_for_once() -> None:
    """Two parts of one unit that hash alike cost one lookup, not two."""
    index = _Index()
    probe([_unit(1), _unit(1, "p2")], [_key(1), _key(1)], index=index, layer=CacheLayer.CALL)
    assert index.calls == [(_key(1),)]


def test_an_empty_batch_issues_no_query_at_all() -> None:
    index = _Index()
    result = probe([], [], index=index, layer=CacheLayer.CALL)
    assert index.calls == []
    assert (result.queries, result.hits, result.outstanding) == (0, (), ())


# ---------------------------------------------------------------------------------------------
# 2. Property 2: hits and outstanding partition the batch
# ---------------------------------------------------------------------------------------------


def test_hits_and_outstanding_sum_to_units() -> None:
    """08:2110's property 3, which `__post_init__` refuses to let drift."""
    units = [_unit(n) for n in range(4)]
    keys = [_key(n) for n in range(4)]
    index = _Index([_entry(1, unit_uri="c:/x/1.pdf"), _entry(3, unit_uri="c:/x/3.pdf")])
    result = probe(units, keys, index=index, layer=CacheLayer.CALL)
    assert len(result.hits) == 2
    assert len(result.outstanding) == 2
    assert len(result.hits) + len(result.outstanding) == len(units)
    assert [unit.uri for unit in result.outstanding] == ["c:/x/0.pdf", "c:/x/2.pdf"]


def test_outstanding_keeps_the_probed_order() -> None:
    """08:1778: *"EXACTLY what must be computed. Order preserved."*"""
    units = [_unit(n) for n in range(6)]
    keys = [_key(n) for n in range(6)]
    index = _Index([_entry(4, unit_uri="c:/x/4.pdf")])
    result = probe(units, keys, index=index, layer=CacheLayer.CALL)
    assert [unit.uri for unit in result.outstanding] == [f"c:/x/{n}.pdf" for n in (0, 1, 2, 3, 5)]


def test_a_hit_records_the_position_it_answered() -> None:
    """A caller widening a narrowed batch reads positions, not identities."""
    units = [_unit(n) for n in range(3)]
    keys = [_key(n) for n in range(3)]
    result = probe(
        units, keys, index=_Index([_entry(2, unit_uri="c:/x/2.pdf")]), layer=CacheLayer.CALL
    )
    assert [hit.index for hit in result.hits] == [2]
    assert result.hits[0].unit.uri == "c:/x/2.pdf"


def test_a_probe_that_lost_a_unit_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="sum to units"):
        CacheProbe(
            hits=(),
            outstanding=(),
            verdicts={("c:/x/a", ""): CacheVerdict.MISS},
            legacy=0,
            would_have_been_micros=0,
        )


def test_a_probe_whose_counts_disagree_with_its_hits_is_refused() -> None:
    hit = CacheHit(
        index=0,
        key=_key(1),
        unit=_unit(1),
        verdict=CacheVerdict.HIT,
        ref=REF,
        bytes=1,
        spend_json="{}",
        micros=5,
    )
    with pytest.raises(ValueError, match="hit_legacy"):
        CacheProbe(
            hits=(hit,),
            outstanding=(),
            verdicts={("c:/x/1.pdf", ""): CacheVerdict.HIT},
            legacy=1,
            would_have_been_micros=5,
        )
    with pytest.raises(ValueError, match="sum over hits"):
        CacheProbe(
            hits=(hit,),
            outstanding=(),
            verdicts={("c:/x/1.pdf", ""): CacheVerdict.HIT},
            legacy=0,
            would_have_been_micros=99,
        )


def test_a_cache_hit_refuses_to_record_a_miss() -> None:
    with pytest.raises(ValueError, match="records a hit"):
        CacheHit(
            index=0,
            key=_key(1),
            unit=_unit(1),
            verdict=CacheVerdict.MISS_CORRUPT,
            ref=REF,
            bytes=1,
            spend_json="{}",
            micros=0,
        )


# ---------------------------------------------------------------------------------------------
# 3. Property 3: every miss carries its clause -- all six, through the batch path
# ---------------------------------------------------------------------------------------------


def _one(entry: CacheEntry | None = None, **kwargs: Any) -> CacheVerdict:
    index = _Index(() if entry is None else (entry,))
    result = probe([_unit(1)], [_key(1)], index=index, layer=CacheLayer.CALL, **kwargs)
    return result.verdicts[("c:/x/1.pdf", "")]


def test_clause_1_no_entry_is_a_plain_miss() -> None:
    assert _one(None) is CacheVerdict.MISS


def test_clause_2_a_blob_that_does_not_parse_is_corrupt() -> None:
    """Counted into `manifest.cache.corrupt_entries` and overwritten on the next success."""
    assert _one(_entry(1, unit_uri="c:/x/1.pdf"), blob_ok=lambda _e: False) is (
        CacheVerdict.MISS_CORRUPT
    )


def test_clause_3_a_partial_entry_needs_the_callers_permission() -> None:
    partial = _entry(1, unit_uri="c:/x/1.pdf", partial=True)
    assert _one(partial) is CacheVerdict.MISS_PARTIAL
    assert _one(partial, allow_partial=True) is CacheVerdict.HIT


def test_clause_4_an_empty_artefact_is_not_a_hit() -> None:
    """08:245: *"There is no empty success"*, on the read path."""
    assert _one(_entry(1, unit_uri="c:/x/1.pdf"), nonempty=lambda _e: False) is (
        CacheVerdict.MISS_EMPTY
    )


def test_clause_5_a_recorded_unit_that_is_not_the_one_asked_for_is_a_bug_report() -> None:
    """*"a key collision or a poisoned write"* -- the one clause that is not a miss."""
    assert _one(_entry(1, unit_uri="c:/x/OTHER.pdf")) is CacheVerdict.MISS_UNIT_MISMATCH


def test_clause_6_an_older_namespace_is_a_legacy_hit_only_when_allowed() -> None:
    """*"dropping pre-fingerprinting entries would re-bill a whole corpus."*"""
    entry = _entry(1, unit_uri="c:/x/1.pdf")
    assert _one(entry, in_namespace=lambda _e: False) is CacheVerdict.MISS
    assert _one(entry, in_namespace=lambda _e: False, allow_legacy=True) is (
        CacheVerdict.HIT_LEGACY
    )


def test_a_row_in_another_layer_is_a_collision_and_never_a_hit() -> None:
    """The key matched; the row is not the one this operator asked for. Clause 5, one level up."""
    assert _one(_entry(1, unit_uri="c:/x/1.pdf", layer=CacheLayer.RENDER)) is (
        CacheVerdict.MISS_UNIT_MISMATCH
    )


def test_the_miss_shapes_are_counted_and_the_zeros_are_absent() -> None:
    """08:1453: the five distinct miss shapes, so *"is the cache working"* is a query."""
    units = [_unit(n) for n in range(3)]
    keys = [_key(n) for n in range(3)]
    rows = [_entry(0, unit_uri="c:/x/WRONG.pdf"), _entry(1, unit_uri="c:/x/1.pdf", partial=True)]
    result = probe(units, keys, index=_Index(rows), layer=CacheLayer.CALL)
    assert result.misses == {
        CacheVerdict.MISS_UNIT_MISMATCH: 1,
        CacheVerdict.MISS_PARTIAL: 1,
        CacheVerdict.MISS: 1,
    }
    assert CacheVerdict.MISS_CORRUPT not in result.misses


def test_the_legacy_count_is_the_mixed_vintage_warning() -> None:
    units = [_unit(n) for n in range(2)]
    keys = [_key(n) for n in range(2)]
    rows = [_entry(0, unit_uri="c:/x/0.pdf"), _entry(1, unit_uri="c:/x/1.pdf")]
    result = probe(
        units,
        keys,
        index=_Index(rows),
        layer=CacheLayer.CALL,
        in_namespace=lambda entry: entry.cache_key == _key(0),
        allow_legacy=True,
    )
    assert result.legacy == 1
    assert {hit.verdict for hit in result.hits} == {CacheVerdict.HIT, CacheVerdict.HIT_LEGACY}


# ---------------------------------------------------------------------------------------------
# 4. Re-pricing, and the honest default
# ---------------------------------------------------------------------------------------------


def test_a_hit_is_re_priced_at_the_current_book() -> None:
    """08:1307: *"the only source of `cost.would_have_been_micros_if_uncached`."*"""
    result = probe(
        [_unit(1)],
        [_key(1)],
        index=_Index([_entry(1, unit_uri="c:/x/1.pdf", micros=7)]),
        layer=CacheLayer.CALL,
        reprice=lambda spend_json: 100 if spend_json == '{"wall_ms":12}' else 0,
    )
    assert result.hits[0].micros == 100
    assert result.would_have_been_micros == 100


def test_without_a_pricebook_the_price_at_creation_stands() -> None:
    """Zero would make the savings read as nothing on exactly the runs that saved the most."""
    result = probe(
        [_unit(1)],
        [_key(1)],
        index=_Index([_entry(1, unit_uri="c:/x/1.pdf", micros=7)]),
        layer=CacheLayer.CALL,
    )
    assert result.would_have_been_micros == 7


def test_the_replayed_spend_crosses_as_json_with_no_currency() -> None:
    """INV-15: `spend_json` carries no currency, and the re-pricer is what adds one."""
    result = probe(
        [_unit(1)],
        [_key(1)],
        index=_Index([_entry(1, unit_uri="c:/x/1.pdf")]),
        layer=CacheLayer.CALL,
    )
    assert result.hits[0].spend_json == '{"wall_ms":12}'
    assert "micros" not in result.hits[0].spend_json


# ---------------------------------------------------------------------------------------------
# 5. Ordering, parallelism and the two refusals
# ---------------------------------------------------------------------------------------------


def test_the_mapping_re_projects_onto_the_batchs_own_order() -> None:
    units = [_unit(n) for n in range(3)]
    keys = [_key(n) for n in range(3)]
    result = probe(
        units, keys, index=_Index([_entry(1, unit_uri="c:/x/1.pdf")]), layer=CacheLayer.CALL
    )
    assert result.ordered(units) == (CacheVerdict.MISS, CacheVerdict.HIT, CacheVerdict.MISS)
    assert result.ordered(list(reversed(units)))[0] is CacheVerdict.MISS


def test_keys_and_units_must_be_parallel() -> None:
    with pytest.raises(ValueError, match="parallel"):
        probe([_unit(0), _unit(1)], [_key(0)], index=_Index(), layer=CacheLayer.CALL)


def test_a_caller_with_no_blob_store_gets_hits_rather_than_silence() -> None:
    """The two clause-answerers default to `True` because both clauses are refusals."""
    result = probe(
        [_unit(1)],
        [_key(1)],
        index=_Index([_entry(1, unit_uri="c:/x/1.pdf")]),
        layer=CacheLayer.CALL,
    )
    assert result.verdicts[("c:/x/1.pdf", "")] is CacheVerdict.HIT


# ---------------------------------------------------------------------------------------------
# 6. The batch read against a real store
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def index(tmp_path: Path) -> Iterator[SqliteCacheIndex]:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        migrate.apply_pending(connection, now_ns=1_700_000_000_000_000_000)
    finally:
        connection.close()

    class _Clock:
        def monotonic_ns(self) -> int:
            return 1

        def wall_ns(self) -> int:
            return 1_700_000_000_000_000_000

    with ow.StoreThread(lambda: ow.connect(path)) as thread:
        yield SqliteCacheIndex(thread, clock=_Clock())


def test_get_many_returns_the_rows_that_exist_and_omits_the_rest(
    index: SqliteCacheIndex,
) -> None:
    allowed = frozenset({("c:/x/1.pdf", ""), ("c:/x/2.pdf", "")})
    written = index.put(
        [_entry(1, unit_uri="c:/x/1.pdf"), _entry(2, unit_uri="c:/x/2.pdf")],
        allowed_units=allowed,
    )
    assert written == 2
    found = index.get_many([_key(1), _key(2), _key(3)])
    assert set(found) == {_key(1), _key(2)}
    assert found[_key(1)].unit_uri == "c:/x/1.pdf"


def test_get_many_over_nothing_takes_no_transaction(index: SqliteCacheIndex) -> None:
    assert index.get_many([]) == {}


def test_a_real_probe_against_a_real_index_is_one_statement(index: SqliteCacheIndex) -> None:
    """The whole point, end to end: rows in, one query, hits and outstanding out."""
    entries = [_entry(n, unit_uri=f"c:/x/{n}.pdf") for n in range(5)]
    index.put(entries, allowed_units=frozenset((e.unit_uri, e.unit_part) for e in entries))
    units = [_unit(n) for n in range(8)]
    keys = [_key(n) for n in range(8)]
    result = probe(units, keys, index=index, layer=CacheLayer.CALL)
    assert result.queries == 1
    assert len(result.hits) == 5
    assert [unit.uri for unit in result.outstanding] == [f"c:/x/{n}.pdf" for n in (5, 6, 7)]
    assert result.would_have_been_micros == 35


def test_the_sqlite_index_satisfies_the_batch_protocol(index: SqliteCacheIndex) -> None:
    """Structurally, like `Store`/`SqliteStore`: `runtime_checkable` is deliberately off, so the
    conformance is asserted by *using* it rather than by an `isinstance` the Protocol refuses."""
    checked: BatchIndex = index
    assert probe([_unit(1)], [_key(1)], index=checked, layer=CacheLayer.CALL).queries == 1


def test_the_generated_statement_binds_every_key_and_interpolates_only_the_count() -> None:
    sql = select_many_sql(3)
    assert sql.count("?") == 3
    assert "IN (?, ?, ?)" in sql
    for column in CACHE_INDEX_COLUMNS:
        assert column in sql
    with pytest.raises(ValueError, match="at least one key"):
        select_many_sql(0)


def test_a_probe_wider_than_one_chunk_still_reads_one_consistent_index(
    index: SqliteCacheIndex,
) -> None:
    """Six chunks in one `Unit`, so a concurrent sweep cannot split a batch across two states."""
    entries = [_entry(n, unit_uri=f"c:/x/{n}.pdf") for n in range(1200)]
    index.put(entries, allowed_units=frozenset((e.unit_uri, e.unit_part) for e in entries))
    units = [_unit(n) for n in range(1200)]
    keys = [_key(n) for n in range(1200)]
    result = probe(units, keys, index=index, layer=CacheLayer.CALL)
    assert result.queries == 2
    assert len(result.hits) == 1200


# ---------------------------------------------------------------------------------------------
# 7. The two defect reports
# ---------------------------------------------------------------------------------------------


def test_the_namespace_a_row_belongs_to_is_not_derivable_from_the_row() -> None:
    """`cache_ns()` takes five inputs; `cache_index` carries three of them. **D171.**"""
    assert cache_ns(
        "free", operator="parse.pdf", op_version=1, code_fingerprint="fp", config_digest="cfg"
    )
    columns = set(CACHE_INDEX_COLUMNS)
    assert {"cost_class", "origin_operator", "config_digest"} <= columns
    assert "op_version" not in columns
    assert "code_fingerprint" not in columns
    # What the index IS built on, and therefore what `same_namespace` compares.
    assert {"driver", "driver_schema_v", "recipe"} <= columns


def test_the_namespace_test_that_ships_is_the_index_tuple() -> None:
    entry = _entry(1)
    assert same_namespace(entry, driver="parse.pdf.pdfium", driver_schema_v=1, recipe=entry.recipe)
    assert not same_namespace(entry, driver="parse.pdf.pdfium", driver_schema_v=2, recipe=1)
    assert not same_namespace(
        entry, driver="parse.other", driver_schema_v=1, recipe=DEFAULT_CACHE_RECIPE
    )


def test_the_partial_index_the_plan_calls_the_enforcement_is_on_those_three(
    migrations: Path,
) -> None:
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    assert (
        "CREATE INDEX cache_ns   ON cache_index(driver, driver_schema_v, recipe) "
        "WHERE cost_class='free'" in ddl
    )


def test_a_probe_cannot_reach_an_index_through_the_arguments_the_plan_prints() -> None:
    """08:1783's `(units, ident, card, ctx)` reaches no cache, no blobs and no Operator. D172."""
    fields = {field.name for field in dataclasses.fields(RunContext)}
    for absent in ("cache", "blobs", "store", "operator", "index"):
        assert absent not in fields
    assert {"roots", "clock", "cancel", "admission", "services", "budget", "events"} <= fields


def test_the_hit_verdict_pair_agrees_with_the_middlewares(plan: PlanDocs) -> None:
    """Two homes for one pair, checked rather than trusted -- `_CACHE_KEY_HEX_LEN`'s arrangement."""
    plan.require()
    from omniweave_core.cache import _HIT_VERDICTS  # noqa: PLC0415 -- the private under test.

    assert frozenset({CacheVerdict.HIT, CacheVerdict.HIT_LEGACY}) == _HIT_VERDICTS
    rows = plan.grep(r"`CacheVerdict` is `hit \| miss", documents=("08-runtime.md",))
    assert rows, "08:1440 prints the seven members"
    lines = plan.lines("08-runtime.md")
    printed = " ".join(lines[rows[0].line - 1 : rows[0].line + 1])
    members = {
        name.strip(" `")
        for name in printed.split("is", 1)[1].split(".", 1)[0].replace("`", " ").split("|")
    }
    assert {verdict.value for verdict in CacheVerdict} == {m for m in members if m}
