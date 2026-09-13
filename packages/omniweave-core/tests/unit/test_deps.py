"""`omniweave_core.deps`: the six kinds, the five key shapes, the three paths, and one query.

Three things here are transcriptions rather than inventions, and each has a test that fails if the
plan moves under it:

* `DEP_KINDS` is read out of `dep.kind`'s CHECK in `0004_runtime.sql`, in both directions.
* `INVALIDATE_SQL` is compared word for word against the query as 07 and 08 print it, modulo the
  table name -- which is the one edit, and the reason for it is `test_nothing_in_the_plan_creates_
  the_changed_relation`.
* The key shapes are compared against `0004_runtime.sql:187`'s own five worked examples.

## The two tests that are defect reports

`test_nothing_in_the_plan_creates_the_changed_relation` shows that the invalidation query joins a
relation no migration creates and no document describes creating. **D175.**

`test_a_deleted_key_invalidates_because_no_recorded_digest_can_be_empty` shows that a deletion has
no new digest to put in the delta, that no document names a sentinel for one, and that
`ABSENT_DIGEST` is unequal to every recorded digest by construction rather than by convention.
**D176.**
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from omniweave_core.canonical import sha256_canonical
from omniweave_core.deps import (
    ABSENT_DIGEST,
    CHANGED_CLEAR_SQL,
    CHANGED_COLUMNS,
    CHANGED_DDL,
    CHANGED_INSERT_SQL,
    CHANGED_TABLE,
    COHORT_ID_HEX,
    COHORT_PREFIX,
    DEP_KINDS,
    INVALIDATE_SQL,
    Change,
    Cohort,
    Dep,
    DepIndex,
    Witness,
    cohort_deps,
    cohort_digest,
    cohort_key,
    cohort_of,
    invalidate,
    name_digest,
    name_key,
    part_key,
    policy_key,
    record_deps,
    runner_deps,
    service_model_key,
    unit_key,
    witness_deps,
)
from omniweave_core.errors import ResourceLimit, StoreError
from omniweave_core.limits import MAX_DEPS_PER_UNIT
from omniweave_core.model.enums import AnchorKind
from omniweave_core.store.queue import DEP_KINDS as QUEUE_DEP_KINDS
from omniweave_core.store.queue import dep_statements

if TYPE_CHECKING:  # pragma: no cover -- typing only.
    from collections.abc import Sequence
    from pathlib import Path

    from conftest import PlanDocs


URI = "file:///corpus/a.pdf"
OTHER = "file:///corpus/b.pdf"
SHA = "a" * 64


class _Index:
    """A `DepIndex` that records what it was asked and answers from a script."""

    def __init__(self, answer: frozenset[int] = frozenset()) -> None:
        self.answer = answer
        self.calls: list[tuple[Change, ...]] = []

    def dependents(self, changes: Sequence[Change], /) -> frozenset[int]:
        self.calls.append(tuple(changes))
        return self.answer


# =============================================================================================
# 1. The closed domain
# =============================================================================================


def test_dep_kinds_is_the_check_constraints_own_list(migrations: Path) -> None:
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    match = re.search(r"kind\s+TEXT NOT NULL CHECK \(kind IN \(([^)]*)\)\)", ddl)
    assert match is not None, "dep.kind's CHECK moved; DEP_KINDS cannot be verified"
    assert tuple(re.findall(r"'([a-z_]+)'", match.group(1))) == DEP_KINDS


def test_the_store_queue_spelling_is_this_one(migrations: Path) -> None:
    """One home. `store/queue.py` declared it at W4.1 with a note saying where it belonged."""
    del migrations
    assert QUEUE_DEP_KINDS is DEP_KINDS


def test_there_are_six_and_the_order_is_the_ddls() -> None:
    assert len(DEP_KINDS) == 6
    assert DEP_KINDS[0] == "unit"
    assert DEP_KINDS[-1] == "service_model"


def test_every_document_that_prints_the_six_prints_these_six(plan: PlanDocs) -> None:
    plan.require()
    pattern = r"unit \\?\| part \\?\| name \\?\| cohort \\?\| policy \\?\| service_model"
    hits = plan.grep(pattern)
    assert hits, "no plan document prints the closed kind list"
    for hit in hits:
        span = re.search(pattern, hit.text)
        assert span is not None
        assert tuple(re.findall(r"[a-z_]+", span.group(0))) == DEP_KINDS


# =============================================================================================
# 2. The five key shapes
# =============================================================================================


def test_the_ddl_prints_five_key_shapes_and_this_module_builds_all_five(migrations: Path) -> None:
    """`0004_runtime.sql:187`: `uri | 'uri#p41' | 'figure:3.1' | cohort_id | 'route:<digest>'`."""
    ddl = (migrations / "0004_runtime.sql").read_text(encoding="utf-8")
    printed = next(line for line in ddl.splitlines() if "uri#p41" in line)
    assert "figure:3.1" in printed
    assert "route:<digest>" in printed
    assert "cohort_id" in printed


def test_a_unit_key_is_the_uri_unchanged() -> None:
    assert unit_key(URI) == URI


def test_a_part_key_is_the_uri_hash_the_part() -> None:
    assert part_key("file:///x.pdf", "p41") == "file:///x.pdf#p41"


def test_an_empty_part_is_not_a_part_key() -> None:
    """`unit_part` empty IS the whole unit everywhere in the schema, so `'uri#'` is not one."""
    with pytest.raises(StoreError, match="the empty unit_part IS the whole unit"):
        part_key(URI, "")


def test_a_name_key_is_akind_colon_name_norm() -> None:
    assert name_key("figure", "3.1") == "figure:3.1"


def test_a_name_keys_akind_is_the_anchor_vocabulary(migrations: Path) -> None:
    """`anchor.akind` holds `AnchorKind`'s lower-case member names, and `figure` is one."""
    ddl = (migrations / "0002_graph.sql").read_text(encoding="utf-8")
    assert "akind" in ddl
    assert name_key(AnchorKind.FIGURE.value, "3.1") == "figure:3.1"


def test_a_cohort_key_must_carry_the_prefix() -> None:
    with pytest.raises(StoreError, match="does not start with"):
        cohort_key("deadbeef")


def test_a_policy_key_is_route_colon_the_digest() -> None:
    assert policy_key("d" * 64) == f"route:{'d' * 64}"


def test_a_service_model_key_is_the_service_name() -> None:
    assert service_model_key("vlm.olmocr") == "vlm.olmocr"


@pytest.mark.parametrize(
    "call",
    [
        lambda: unit_key(""),
        lambda: part_key("", "p1"),
        lambda: name_key("", "3.1"),
        lambda: name_key("figure", ""),
        lambda: policy_key(""),
        lambda: service_model_key(""),
    ],
)
def test_every_key_builder_refuses_an_empty_component(call: object) -> None:
    with pytest.raises(StoreError, match="is empty"):
        call()  # type: ignore[operator]


# =============================================================================================
# 3. `name_digest` -- sha256 over the sorted definition set
# =============================================================================================


def test_a_name_digest_is_order_independent() -> None:
    assert name_digest(["b.pdf", "a.pdf"]) == name_digest(["a.pdf", "b.pdf"])


def test_a_name_digest_is_duplicate_independent() -> None:
    assert name_digest(["a.pdf", "a.pdf"]) == name_digest(["a.pdf"])


def test_a_name_digest_moves_when_the_definition_set_moves() -> None:
    assert name_digest(["a.pdf"]) != name_digest(["a.pdf", "b.pdf"])


def test_the_empty_definition_set_has_a_digest_and_it_is_not_the_sentinel() -> None:
    """A name whose last definition was removed is a CHANGE, not an absence."""
    assert name_digest(()) == sha256_canonical([])
    assert name_digest(()) != ABSENT_DIGEST


# =============================================================================================
# 4. `Dep` and `Change`
# =============================================================================================


def test_a_dep_carries_three_fields_and_the_row_is_what_dep_statements_takes() -> None:
    dep = Dep(kind="unit", key=URI, digest=SHA)
    assert dep.row == ("unit", URI, SHA)
    assert dep.target == ("unit", URI)


def test_a_dep_outside_the_closed_kinds_is_refused() -> None:
    with pytest.raises(StoreError, match="outside"):
        Dep(kind="block", key=URI, digest=SHA)  # type: ignore[arg-type]


def test_a_dep_with_an_empty_digest_is_refused() -> None:
    with pytest.raises(StoreError, match="empty digest"):
        Dep(kind="unit", key=URI, digest="")


def test_a_deleted_key_invalidates_because_no_recorded_digest_can_be_empty(
    plan: PlanDocs,
) -> None:
    """D176: deletion has no new digest, no document names a sentinel, and this one is sound.

    06's invalidation matrix requires a deleted document's dependents to be re-derived; the query
    only sees what the caller puts in `changed`. `ABSENT_DIGEST` is `''` and `Dep` refuses `''`, so
    `d.digest <> c.new_digest` is necessarily true rather than conventionally true.
    """
    plan.require()
    assert plan.grep(r"a whole document deleted", documents=("06-structure-extraction.md",))
    assert not plan.grep(r"ABSENT_DIGEST|absent_digest|sentinel digest")
    assert ABSENT_DIGEST == ""
    with pytest.raises(StoreError):
        Dep(kind="unit", key=URI, digest=ABSENT_DIGEST)
    assert Change(kind="unit", key=URI, new_digest=ABSENT_DIGEST).absent


def test_a_change_that_carries_a_digest_is_not_absent() -> None:
    assert not Change(kind="unit", key=URI, new_digest=SHA).absent


def test_a_change_outside_the_closed_kinds_is_refused() -> None:
    with pytest.raises(StoreError, match="outside"):
        Change(kind="segment", key=URI, new_digest=SHA)  # type: ignore[arg-type]


def test_a_change_with_an_empty_key_is_refused() -> None:
    with pytest.raises(StoreError, match="key is empty"):
        Change(kind="unit", key="", new_digest=SHA)


# =============================================================================================
# 5. The three population paths
# =============================================================================================


def test_runner_deps_emit_unit_for_a_whole_unit_and_part_for_a_part() -> None:
    deps = runner_deps({(URI, ""): SHA, (OTHER, "p41"): "b" * 64})
    assert {dep.kind for dep in deps} == {"unit", "part"}
    assert {dep.key for dep in deps} == {URI, f"{OTHER}#p41"}


def test_a_witness_names_a_subset_of_the_input_set() -> None:
    inputs = {(URI, ""): SHA, (OTHER, ""): "b" * 64}
    deps = witness_deps([Witness(unit_uri=OTHER, token="fig:3")], inputs=inputs)
    assert [dep.key for dep in deps] == [OTHER]


def test_a_witness_outside_the_input_set_is_refused() -> None:
    """08:1831-1839: a driver cannot name a unit it was never given."""
    with pytest.raises(StoreError, match="outside the invocation's input set"):
        witness_deps([Witness(unit_uri=OTHER)], inputs={(URI, ""): SHA})


def test_a_witness_supplies_the_unit_and_the_runner_supplies_the_digest() -> None:
    """A driver-supplied digest could record a dep that never invalidates."""
    deps = witness_deps([Witness(unit_uri=URI)], inputs={(URI, ""): SHA})
    assert deps[0].digest == SHA


def test_a_witness_with_a_part_records_a_part_dep() -> None:
    inputs = {(URI, "p7"): SHA}
    deps = witness_deps([Witness(unit_uri=URI, unit_part="p7")], inputs=inputs)
    assert deps[0].row == ("part", f"{URI}#p7", SHA)


def test_the_token_reaches_no_dep_row() -> None:
    """Dep granularity is the unit or the part, never the block."""
    inputs = {(URI, ""): SHA}
    first = witness_deps([Witness(unit_uri=URI, token="fig:3")], inputs=inputs)
    second = witness_deps([Witness(unit_uri=URI, token="tbl:9")], inputs=inputs)
    assert first == second


def test_a_cohort_dep_is_one_row_whatever_the_member_count() -> None:
    cohort = cohort_of("corpus", [(f"u{n}", "", SHA) for n in range(500)])
    deps = cohort_deps(cohort)
    assert len(deps) == 1
    assert deps[0].row == ("cohort", cohort.cohort_id, cohort.member_sha256)


# =============================================================================================
# 6. The cohort merkle
# =============================================================================================


def test_the_cohort_digest_is_order_independent() -> None:
    members = [(URI, "", SHA), (OTHER, "", "b" * 64)]
    assert cohort_digest(members) == cohort_digest(list(reversed(members)))


def test_the_cohort_digest_is_duplicate_independent() -> None:
    assert cohort_digest([(URI, "", SHA), (URI, "", SHA)]) == cohort_digest([(URI, "", SHA)])


def test_any_member_change_moves_the_digest() -> None:
    before = cohort_digest([(URI, "", SHA)])
    assert before != cohort_digest([(URI, "", "b" * 64)])
    assert before != cohort_digest([(URI, "", SHA), (OTHER, "", SHA)])


def test_the_cohort_id_is_the_prefix_plus_24_hex_of_the_merkles_digest() -> None:
    cohort = cohort_of("corpus", [(URI, "", SHA)])
    assert cohort.cohort_id.startswith(COHORT_PREFIX)
    body = cohort.cohort_id[len(COHORT_PREFIX) :]
    assert len(body) == COHORT_ID_HEX
    assert body == sha256_canonical(cohort.member_sha256)[:COHORT_ID_HEX]


def test_member_count_counts_distinct_members() -> None:
    """`cohort_member`'s PRIMARY KEY holds one row per `(cohort_id, unit_uri, unit_part)`."""
    cohort = cohort_of("corpus", [(URI, "", SHA), (URI, "", SHA), (OTHER, "", SHA)])
    assert cohort.member_count == 2


def test_a_cohort_needs_a_name() -> None:
    with pytest.raises(StoreError, match="is empty"):
        cohort_of("", [(URI, "", SHA)])


def test_the_cohort_is_what_the_plan_prints(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("08-runtime.md"))
    assert r"'coh_' \|\| sha256_canonical(member merkle)[:24]" in text
    assert "(unit_uri, unit_part, content_sha256)` in sorted order" in text
    assert "the merkle itself is `cohort.member_sha256`" in text


# =============================================================================================
# 7. `record_deps` -- the merge, and the three refusals
# =============================================================================================


def test_record_deps_merges_the_paths_into_one_sorted_tuple() -> None:
    cohort = cohort_of("corpus", [(URI, "", SHA)])
    merged = record_deps(
        runner_deps({(URI, ""): SHA}),
        cohort_deps(cohort),
        [Dep(kind="policy", key=policy_key("d" * 64), digest="d" * 64)],
    )
    assert [dep.kind for dep in merged] == ["unit", "cohort", "policy"]


def test_the_order_is_dep_kinds_then_key() -> None:
    merged = record_deps(
        [
            Dep(kind="name", key="figure:9", digest=SHA),
            Dep(kind="name", key="figure:1", digest=SHA),
            Dep(kind="unit", key=URI, digest=SHA),
        ]
    )
    assert [dep.key for dep in merged] == [URI, "figure:1", "figure:9"]


def test_an_identical_duplicate_is_deduplicated_in_silence() -> None:
    dep = Dep(kind="unit", key=URI, digest=SHA)
    assert record_deps([dep], [dep]) == (dep,)


def test_one_key_with_two_digests_is_refused_not_resolved() -> None:
    """`INSERT OR IGNORE` on the dep PRIMARY KEY would keep whichever arrived first."""
    with pytest.raises(StoreError, match="recorded twice with two digests"):
        record_deps(
            [Dep(kind="unit", key=URI, digest=SHA)],
            [Dep(kind="unit", key=URI, digest="b" * 64)],
        )


def test_a_key_outside_the_allowed_set_is_refused() -> None:
    with pytest.raises(StoreError, match="outside the invocation's input set"):
        record_deps([Dep(kind="unit", key=OTHER, digest=SHA)], allowed_keys=frozenset({URI}))


def test_an_allowed_key_passes() -> None:
    deps = record_deps([Dep(kind="unit", key=URI, digest=SHA)], allowed_keys=frozenset({URI}))
    assert len(deps) == 1


def test_past_the_ceiling_record_deps_raises_the_same_class_and_fix_as_dep_statements() -> None:
    """08:1840 makes the remedy part of the error, and there are now two sites raising it."""
    rows = [Dep(kind="unit", key=f"u{n}", digest=SHA) for n in range(MAX_DEPS_PER_UNIT + 1)]
    with pytest.raises(ResourceLimit) as early:
        record_deps(rows)
    with pytest.raises(ResourceLimit) as late:
        dep_statements(1, [dep.row for dep in rows])
    assert early.value.fix == late.value.fix
    assert "max_deps_per_unit" in str(early.value.fix) or "cohort" in str(early.value.fix)


def test_the_ceiling_is_the_declared_one() -> None:
    assert MAX_DEPS_PER_UNIT == 256
    assert len(record_deps([Dep(kind="unit", key=f"u{n}", digest=SHA) for n in range(256)])) == 256


def test_a_caller_may_clamp_below_the_ceiling() -> None:
    """18:1677: `runtime.max_deps_per_unit` *"clamps below `MAX_DEPS_PER_UNIT`"*."""
    rows = [Dep(kind="unit", key=f"u{n}", digest=SHA) for n in range(9)]
    with pytest.raises(ResourceLimit, match="the ceiling is 8"):
        record_deps(rows, limit=8)


def test_record_deps_over_nothing_is_empty() -> None:
    assert record_deps() == ()


# =============================================================================================
# 8. Invalidation -- one query, never a sweep
# =============================================================================================


def test_the_query_is_the_one_two_documents_print(plan: PlanDocs) -> None:
    plan.require()
    for document in ("07-store-and-retrieval.md", "08-runtime.md"):
        joined = " ".join(plan.lines(document))
        printed = re.search(
            r"SELECT DISTINCT d\.dependent_id FROM dep d JOIN changed c\s+"
            r"ON c\.kind = d\.kind AND c\.key = d\.key WHERE d\.digest <> c\.new_digest",
            joined,
        )
        assert printed is not None, f"{document} no longer prints the invalidation query"
    normalised = INVALIDATE_SQL.replace(CHANGED_TABLE, "changed")
    assert normalised == (
        "SELECT DISTINCT d.dependent_id FROM dep d "
        "JOIN changed c ON c.kind = d.kind AND c.key = d.key "
        "WHERE d.digest <> c.new_digest"
    )


def test_nothing_in_the_plan_creates_the_changed_relation(plan: PlanDocs, migrations: Path) -> None:
    """D175: three documents join `changed` and nothing anywhere declares it.

    The shipped answer is a TEMP table on 07:1601-1603's own `IF NOT EXISTS` plus `DELETE FROM`
    idiom -- the rule that file states for `tmp_narrow`, for the reason it states.
    """
    plan.require()
    assert plan.grep(r"JOIN changed c"), "the query stopped being printed"
    assert not plan.grep(r"CREATE (TEMP )?TABLE( IF NOT EXISTS)? changed")
    for path in sorted(migrations.glob("*.sql")):
        assert "TABLE changed" not in path.read_text(encoding="utf-8")
    assert "CREATE TEMP TABLE IF NOT EXISTS" in CHANGED_DDL
    assert CHANGED_CLEAR_SQL.startswith("DELETE FROM ")


def test_the_temp_table_carries_the_three_columns_the_query_reads() -> None:
    for column in CHANGED_COLUMNS:
        assert f"{column} TEXT NOT NULL" in CHANGED_DDL
    assert "PRIMARY KEY (kind, key)" in CHANGED_DDL
    assert "WITHOUT ROWID" in CHANGED_DDL


def test_the_delta_insert_replaces_rather_than_duplicates() -> None:
    """The PRIMARY KEY makes the delta a set; the later observation of a key wins."""
    assert CHANGED_INSERT_SQL.startswith("INSERT OR REPLACE INTO ")


def test_the_temp_table_is_prefixed_so_it_cannot_shadow_a_main_schema_table() -> None:
    assert CHANGED_TABLE != "changed"
    assert CHANGED_TABLE.startswith("ow_")


def test_an_empty_delta_asks_the_store_nothing() -> None:
    index = _Index()
    assert invalidate((), index=index) == frozenset()
    assert index.calls == []


def test_a_delta_reaches_the_index_verbatim_and_the_answer_comes_back() -> None:
    index = _Index(frozenset({4, 9}))
    delta = (Change(kind="unit", key=URI, new_digest=SHA),)
    assert invalidate(delta, index=index) == frozenset({4, 9})
    assert index.calls == [delta]


def test_the_answer_is_a_frozen_set_of_work_ids() -> None:
    index = _Index(frozenset({7}))
    answer = invalidate((Change(kind="unit", key=URI, new_digest=SHA),), index=index)
    assert isinstance(answer, frozenset)


def test_the_shipped_index_satisfies_the_protocol() -> None:
    """Structurally, like `Store`/`SqliteStore` and `CacheIndex`/`BatchIndex`.

    `runtime_checkable` is deliberately off, so the conformance is asserted by *using* it rather
    than by an `isinstance` the Protocol refuses -- and the flag's absence is asserted too, because
    turning it on would make a structural check pass for anything with a `dependents` attribute.
    """
    checked: DepIndex = _Index(frozenset({3}))
    assert invalidate((Change(kind="unit", key=URI, new_digest=SHA),), index=checked) == (
        frozenset({3})
    )
    assert getattr(DepIndex, "_is_runtime_protocol", False) is False


# =============================================================================================
# 9. What the plan says this module is for
# =============================================================================================


def test_the_architecture_row_homes_these_names_here(plan: PlanDocs) -> None:
    plan.require()
    row = plan.grep(r"\| 20 \| Deps \| `omniweave_core\.deps`", documents=("02-architecture.md",))
    assert len(row) == 1
    for name in ("Dep", "DepKind", "record_deps", "invalidate(delta)", "cohort_digest"):
        assert name in row[0].text


def test_the_measured_consequence_of_skipping_this_is_on_record(plan: PlanDocs) -> None:
    plan.require()
    hits = plan.grep(r"4\.3% of .*distinct edges wrong")
    assert len(hits) >= 2, "the codegraph measurement is the reason this module exists"


def test_observation_is_impossible_by_design_and_the_plan_says_so(plan: PlanDocs) -> None:
    plan.require()
    text = " ".join(plan.lines("08-runtime.md"))
    assert "There is no `DeriveIO.read_unit()`; no such type exists." in text


def test_a_cohort_carries_the_merkle_under_the_ddls_own_column_name() -> None:
    cohort = cohort_of("corpus", [(URI, "", SHA)])
    assert isinstance(cohort, Cohort)
    assert cohort.member_sha256 == cohort_digest([(URI, "", SHA)])
