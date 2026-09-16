"""`omniweave_core.retrieve.plan` -- the four rules, the five worked plans, and the two deadlines.

The policy these tests plan against is **read out of `_plan/`**, not retyped: `07 §6.2` prints the
four `[[rule]]` blocks in one TOML fence, `G27(a)` already `tomllib.load`s every such fence, and a
retyped copy is a copy that drifts. `_shipped()` below is the whole of the adaptation -- a `[rule.
then]` into a `Rule` -- and a plan edit that renames a channel or moves a threshold fails here
rather than in a reviewer's head.

The five worked plans of 07:1829-1968 are the fixtures. They are illustrations by the document's own
statement at 07:1834 -- *"These five are illustrations. The contract is §6.7 (the `Verdict`
record) and §6.8 (the fifteen gates)"* -- so what is asserted
from them is only what the planner produces: which rule matched, which Channels are in the plan, in
what order, with which budgets, and which gates survive. The ceiling arithmetic printed beside them
is `ceiling()`'s and is W6.3's.
"""

from __future__ import annotations

import dataclasses
import tomllib
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_core.errors import UsageError
from omniweave_core.limits import PREFILTER_MAX
from omniweave_core.model.enums import Method
from omniweave_core.retrieve import plan as pl
from omniweave_core.retrieve.types import (
    ABSENCE_GATES,
    CHANNELS,
    SCORER_VERSION,
    Query,
    QueryBudget,
    RetrievalPolicy,
    Rule,
)
from omniweave_core.store.types import Expand, Filters, IndexCaps, Narrowing

if TYPE_CHECKING:
    from conftest import PlanDocs

DOC = "07-store-and-retrieval.md"


def _caps(*, vectors: bool = False, stale: bool = False) -> IndexCaps:
    """The `handbook` corpus of 07:1831: 17 documents, 41,822 live blocks, 1,390 segments."""
    channels = frozenset(
        {"identity", "exact", "lexical", "structural"} | ({"semantic"} if vectors else set())
    )
    return IndexCaps(
        schema="1.0",
        scorer_version=SCORER_VERSION,
        channels=channels,
        has_head_fts=True,
        has_trigram=False,
        fts_state="ok",
        space_id=7 if vectors else None,
        vec_backend="brute" if vectors else None,
        vec_ceiling=250_000 if vectors else 0,
        vec_pushdown=False,
        live_blocks=41_822,
        live_segments=1_390 if vectors else 0,
        docs=17,
        stat_age_ns=90_000_000_000_000 if stale else 1_000_000_000,
        shard_ord=0,
        federated=False,
        caps_digest=f"sha256:handbook-{vectors}-{stale}",
    )


def _rule(raw: dict[str, Any]) -> Rule:
    """One `[[rule]]` block of 07:1712-1756 as a `Rule`. The `then` half is the retrieval one."""
    then = raw.get("then", {})
    return Rule(
        rule_id=raw["id"],
        when=raw.get("when", {}),
        channels=tuple(then.get("channels", CHANNELS)),
        weights=then.get("weights", {}),
        short_circuit=then.get("short_circuit", ""),
        gates=tuple(then.get("gates", ())),
        on_unknown=raw.get("on_unknown", "skip"),
    )


def _shipped(plan_docs: PlanDocs) -> RetrievalPolicy:
    """`.omniweave/policy.d/10-builtin-retrieval.toml`, read from the fence that prints it."""
    for body in plan_docs.fences(DOC, "toml"):
        raw = tomllib.loads(body)
        if raw.get("surface") == "retrieval":
            return RetrievalPolicy(
                rules=tuple(_rule(block) for block in raw["rule"]),
                thresholds=raw.get("thresholds", {}),
                policy_name=raw["policy_name"],
                policy_digest="sha256:builtin-balanced",
            )
    pytest.fail(f"{DOC} prints no `surface = 'retrieval'` TOML fence")


@pytest.fixture
def policy(plan: PlanDocs) -> RetrievalPolicy:
    plan.require()
    pl.clear_memo()
    return _shipped(plan)


# ---------------------------------------------------------------------------
# The shipped policy, as the document prints it
# ---------------------------------------------------------------------------


def test_the_fence_carries_four_rules_and_the_last_one_matches_everything(
    policy: RetrievalPolicy,
) -> None:
    """07:1751's `default` has an empty `[rule.when]`, which is what makes selection total."""
    assert [rule.rule_id for rule in policy.rules] == [
        "cite-shortcircuit",
        "structural-only",
        "thematic",
        "default",
    ]
    assert policy.rules[-1].when == {}
    assert policy.rules[-1].channels == CHANNELS


def test_the_threshold_substitution_already_happened_in_the_fence(policy: RetrievalPolicy) -> None:
    """`@thresholds.identity_certain` is a COMPILE-TIME substitution (07:1766), so a compiled rule
    holds the number. The fence is the uncompiled form and this test records which half it is."""
    assert policy.thresholds == {"low_confidence": 0.35, "identity_certain": 50}
    assert "@thresholds" in policy.rules[0].short_circuit


# ---------------------------------------------------------------------------
# The five worked plans of 07:1829
# ---------------------------------------------------------------------------


def test_plan_1_the_ordinary_mixed_query_runs_all_five_in_the_canonical_order(
    policy: RetrievalPolicy,
) -> None:
    """07:1841: `identity(15) exact(25) lexical(50) structural(40) semantic(80)`.

    `semantic` is IN the plan on a store with no vectors: the Channel reports `OFF(vectors)` at
    runtime and its weight is exempt from the ceiling there, but the plan selected it and a plan
    that dropped it would report `not_in_plan` instead -- a different disclosure."""
    made = pl.plan(Query(text="parental leave notice period"), _caps(), policy)
    assert made.rule_id == "default"
    assert made.channel_names == CHANNELS
    assert [spec.budget_ms for spec in made.channels] == [15, 25, 50, 40, 80]
    assert made.budget_ms == 210


def test_plan_2_a_cite_lookup_takes_two_channels_and_a_short_circuit(
    policy: RetrievalPolicy,
) -> None:
    """07:1862-1865: identity and exact only, `short_circuit` fires after Channel 1."""
    made = pl.plan(Query(refs=("d7#412",), mode="cite", k=1), _caps(), policy)
    assert made.rule_id == "cite-shortcircuit"
    assert made.channel_names == ("identity", "exact")
    assert made.short_circuit is not None
    assert [spec.weight for spec in made.channels] == [2.0, 1.2]


def test_plan_3_structural_only_removes_one_gate_and_keeps_the_other_fourteen(
    policy: RetrievalPolicy,
) -> None:
    """07:1902: *"`similarity_only` is REMOVED from this plan's gate set ... because the semantic
    Channel did not run"*. The other fourteen keep their precedence order."""
    made = pl.plan(
        Query(
            mode="explore",
            filters=Filters(sec_path_prefix="/0003/0007"),
            expand=Expand(relations=frozenset({"refers_to", "cites"}), max_hops=2),
        ),
        _caps(),
        policy,
    )
    assert made.rule_id == "structural-only"
    assert made.channel_names == ("identity", "exact", "structural")
    assert made.gates == ABSENCE_GATES[:-1]
    assert "similarity_only" not in made.gates


def test_plan_4_the_thematic_query_needs_vectors_and_runs_semantic_before_structural(
    policy: RetrievalPolicy,
) -> None:
    """07:1913 prints the channel line -- *"channels : lexical(50) semantic(80)
    structural(40)"* -- with identity and exact not in the plan. The order is the rule's own, and
    07:1704 is why the planner does not re-sort it."""
    text = "what does this corpus say about supply-chain concentration risk"
    made = pl.plan(Query(text=text), _caps(vectors=True), policy)
    assert made.rule_id == "thematic"
    assert made.channel_names == ("lexical", "semantic", "structural")
    assert made.channels[1].weight == 1.2


def test_the_thematic_rule_does_not_match_a_store_with_no_vectors(
    policy: RetrievalPolicy,
) -> None:
    """`caps.has_vectors` is one of its three clauses, so the shipped default catches it instead --
    and the same query gets five Channels rather than three."""
    text = "what does this corpus say about supply-chain concentration risk"
    made = pl.plan(Query(text=text), _caps(), policy)
    assert made.rule_id == "default"
    assert made.channel_names == CHANNELS


def test_plan_5_prove_absent_keeps_every_channel_and_disables_the_short_circuit(
    policy: RetrievalPolicy,
) -> None:
    """07:1826: *"an absence claim is licensed by all Channels having looked"*."""
    made = pl.plan(
        Query(text="is liability capped at twelve months of fees", mode="prove_absent"),
        _caps(),
        policy,
    )
    assert made.channel_names == CHANNELS
    assert made.short_circuit is None
    assert made.gates == ABSENCE_GATES


def test_prove_absent_disables_a_short_circuit_the_rule_declared(
    policy: RetrievalPolicy,
) -> None:
    """The mode beats the rule, which is the only ordering that makes an absence claim honest."""
    cited = Query(refs=("d7#412",), mode="cite")
    absent = Query(refs=("d7#412",), mode="prove_absent")
    assert pl.plan(cited, _caps(), policy).short_circuit is not None
    assert pl.plan(absent, _caps(), policy).short_circuit is None


# ---------------------------------------------------------------------------
# Decision 3 -- the over-fetch factor
# ---------------------------------------------------------------------------


def test_lexical_always_over_fetches_five_times_and_nothing_else_does(
    policy: RetrievalPolicy,
) -> None:
    """07:1780: *"`LEX_OVERFETCH = 5` for the lexical Channel, always, before re-rank."*"""
    made = pl.plan(Query(text="parental leave notice period", k=20), _caps(), policy)
    by_name = {spec.name: spec for spec in made.channels}
    assert by_name["lexical"].overfetch == pl.LEX_OVERFETCH
    assert by_name["lexical"].limit == 100
    assert {by_name[name].overfetch for name in ("identity", "exact", "structural")} == {1}


def test_a_stale_stat_forces_the_semantic_channel_to_the_maximum_clamp(
    policy: RetrievalPolicy,
) -> None:
    """07:728: *"the over-fetch factor is the maximum clamp, 64, and this is recorded on the
    Verdict"*. The clamp itself needs the narrowing's `n`, which is a filter VALUE and therefore
    outside the memo key."""
    text = "what does this corpus say about supply-chain concentration risk"
    fresh = pl.plan(Query(text=text), _caps(vectors=True), policy)
    stale = pl.plan(Query(text=text), _caps(vectors=True, stale=True), policy)
    assert {spec.name: spec.overfetch for spec in fresh.channels}["semantic"] == 1
    assert {spec.name: spec.overfetch for spec in stale.channels}["semantic"] == pl.STALE_OVERFETCH
    assert stale.plan_digest != fresh.plan_digest


# ---------------------------------------------------------------------------
# Decision 4 -- the two deadlines, at the only point a plan can set them
# ---------------------------------------------------------------------------


def test_the_shipped_budgets_fit_under_query_ms_with_the_hydration_reserve(
    policy: RetrievalPolicy,
) -> None:
    """`15 + 25 + 50 + 40 + 80 = 210`, `+ 40` reserved, against `query_ms = 250` -- exactly equal,
    which is why 07:1803 calls the query deadline *"a safety net rather than the norm"*."""
    budget = QueryBudget()
    assert sum(budget.channel_ms.values()) == 210
    assert budget.schedulable_ms == 210
    assert pl.plan(Query(text="anything at all"), _caps(), policy).budget_ms == 210


def test_a_budget_whose_channels_outspend_the_query_deadline_is_refused() -> None:
    """Every query under it would end at the query deadline with Channels reporting
    `OFF(query_deadline)` -- the disclosure that is NOT a failure, arriving on every query."""
    budget = QueryBudget(channel_ms=dict.fromkeys(CHANNELS, 60))
    policy = RetrievalPolicy(rules=(), budget=budget)
    with pytest.raises(UsageError) as caught:
        pl.plan(Query(text="x"), _caps(), policy)
    assert "OFF(query_deadline)" in str(caught.value)
    assert caught.value.fix


def test_a_channel_with_no_budget_of_its_own_is_refused() -> None:
    """Case one of the split is the only one that forces `degraded`, and a Channel with no
    `budget_ms` can only ever reach case two."""
    budget = QueryBudget(channel_ms={"identity": 15})
    policy = RetrievalPolicy(
        rules=(Rule(rule_id="two", channels=("identity", "exact")),), budget=budget
    )
    with pytest.raises(UsageError) as caught:
        pl.plan(Query(), _caps(), policy)
    assert "channel_ms" in str(caught.value)


def test_the_querys_own_budget_wins_over_the_policys(policy: RetrievalPolicy) -> None:
    """07:2343 makes `Query.budget = None` mean *"the retrieval policy's default budget"*, and
    D238 records that the printed `RetrievalPolicy` has no budget for it to mean."""
    generous = QueryBudget(
        query_ms=1_000, channel_ms=dict(QueryBudget().channel_ms) | {"exact": 90}
    )
    made = pl.plan(Query(text="parental leave", budget=generous), _caps(), policy)
    assert {spec.name: spec.budget_ms for spec in made.channels}["exact"] == 90


# ---------------------------------------------------------------------------
# The run order, and the one constraint on a hand-authored list
# ---------------------------------------------------------------------------


def test_structural_may_not_precede_lexical_in_a_hand_authored_list() -> None:
    """07:1707. `structural`'s fallback seed is lexical's re-ranked top-N, which does not exist at
    that point -- and `ow route lint` catching it first does not make the planner's check
    redundant, for the reason RT8 gives for the rung trigger."""
    policy = RetrievalPolicy(rules=(Rule(rule_id="backwards", channels=("structural", "lexical")),))
    with pytest.raises(UsageError) as caught:
        pl.plan(Query(), _caps(), policy)
    assert "structural before lexical" in str(caught.value)


def test_structural_before_lexical_is_fine_when_there_is_no_lexical_channel() -> None:
    """The `structural-only` plan: seeded from `identity` and `exact` or from `tmp_narrow`."""
    policy = RetrievalPolicy(rules=(Rule(rule_id="only", channels=("structural", "identity")),))
    assert pl.plan(Query(), _caps(), policy).channel_names == ("structural", "identity")


def test_an_unknown_channel_name_is_refused() -> None:
    policy = RetrievalPolicy(rules=(Rule(rule_id="typo", channels=("lexcial",)),))
    with pytest.raises(UsageError) as caught:
        pl.plan(Query(), _caps(), policy)
    assert "lexcial" in str(caught.value)


def test_a_rule_that_selects_no_channel_is_refused() -> None:
    """A plan that runs nothing returns a zero no gate can distinguish from an absence."""
    policy = RetrievalPolicy(rules=(Rule(rule_id="none", channels=()),))
    with pytest.raises(UsageError):
        pl.plan(Query(), _caps(), policy)


def test_a_channel_named_twice_is_refused() -> None:
    policy = RetrievalPolicy(rules=(Rule(rule_id="dup", channels=("exact", "exact")),))
    with pytest.raises(UsageError):
        pl.plan(Query(), _caps(), policy)


# ---------------------------------------------------------------------------
# Selection, and the grammar this module does not own
# ---------------------------------------------------------------------------


def test_the_four_evidence_keys_are_total() -> None:
    """No clause is ever UNKNOWN here, which is why `on_unknown` never decides anything."""
    for query in (Query(), Query(text="a b c", refs=("x",), mode="cite")):
        assert tuple(pl.evidence(query, _caps())) == pl.EVIDENCE_KEYS


def test_a_clause_outside_the_shipped_forms_is_refused_rather_than_approximated() -> None:
    """D235: the rest of D4's comparison set is `omniweave.route.policy`'s and core may not import
    it, so an `in` clause is a refusal here and never a silently different channel set."""
    policy = RetrievalPolicy(
        rules=(Rule(rule_id="member", when={"query.mode": {"in": ("find", "cite")}}),)
    )
    with pytest.raises(UsageError) as caught:
        pl.plan(Query(), _caps(), policy)
    assert "D235" in str(caught.value)


def test_a_two_operator_clause_is_refused() -> None:
    policy = RetrievalPolicy(
        rules=(Rule(rule_id="both", when={"query.text_terms": {"gte": 1, "lte": 9}}),)
    )
    with pytest.raises(UsageError):
        pl.plan(Query(text="one two"), _caps(), policy)


def test_an_ordered_comparison_against_a_non_number_is_refused() -> None:
    policy = RetrievalPolicy(rules=(Rule(rule_id="odd", when={"query.mode": {"gte": 4}}),))
    with pytest.raises(UsageError):
        pl.plan(Query(), _caps(), policy)


def test_defer_is_refused_because_the_query_path_has_nothing_to_defer_to() -> None:
    """The routing loop promotes a `CostClass` group; the query path has no `DemandPlan`."""
    rule = Rule(rule_id="deferring", when={"nope.missing": 1}, on_unknown="defer")
    with pytest.raises(UsageError) as caught:
        pl.select(RetrievalPolicy(rules=(rule,)), pl.evidence(Query(), _caps()))
    assert "DemandPlan" in str(caught.value)


def test_an_unknown_key_under_skip_simply_does_not_match() -> None:
    rule = Rule(rule_id="skipping", when={"nope.missing": 1}, channels=("identity",))
    made = pl.plan(Query(), _caps(), RetrievalPolicy(rules=(rule,)))
    assert made.rule_id == "builtin:default"
    assert made.channel_names == CHANNELS


def test_a_policy_with_no_rules_plans_all_five() -> None:
    """The fall-through is a real `Rule` so that every plan names the rule that built it."""
    made = pl.plan(Query(), _caps(), RetrievalPolicy())
    assert made.rule_id == "builtin:default"


# ---------------------------------------------------------------------------
# The gate modifier, whose grammar the plan prints once and defines nowhere
# ---------------------------------------------------------------------------


def test_a_gate_modifier_outside_the_two_parsed_forms_is_refused() -> None:
    """D237. A token this function ignored would leave a gate in a plan its author removed."""
    for token in ("similarity_only:off", "+similarity_only", "+no_such_gate:off", "-x:off"):
        policy = RetrievalPolicy(rules=(Rule(rule_id="mod", gates=(token,)),))
        with pytest.raises(UsageError):
            pl.plan(Query(), _caps(), policy)


def test_turning_a_gate_back_on_restores_it_at_its_own_precedence() -> None:
    """Order is precedence (07:2170), so a re-added gate may not land at the end of the tuple."""
    policy = RetrievalPolicy(
        rules=(Rule(rule_id="mod", gates=("+timed_out:off", "+timed_out:on")),)
    )
    assert pl.plan(Query(), _caps(), policy).gates == ABSENCE_GATES


# ---------------------------------------------------------------------------
# Memoisation and the digest
# ---------------------------------------------------------------------------


def test_two_queries_of_the_same_shape_share_a_plan_digest(policy: RetrievalPolicy) -> None:
    """07:1546, and it is what lets the query scoreboard slice by plan at all."""
    first = pl.plan(Query(text="parental leave notice period"), _caps(), policy)
    second = pl.plan(Query(text="a wholly different four words"), _caps(), policy)
    assert first.plan_digest == second.plan_digest
    assert first.channels == second.channels


def test_the_filters_are_on_the_plan_but_not_in_the_digest(policy: RetrievalPolicy) -> None:
    """The memo carries the filter FIELD set; the values ride on the returned plan."""
    one = pl.plan(Query(text="x y z w", filters=Filters(uri_prefix="a/")), _caps(), policy)
    two = pl.plan(Query(text="x y z w", filters=Filters(uri_prefix="b/")), _caps(), policy)
    assert one.plan_digest == two.plan_digest
    assert one.filters != two.filters
    assert one.filters.uri_prefix == "a/"


def test_a_different_filter_field_set_is_a_different_plan(policy: RetrievalPolicy) -> None:
    bare = pl.plan(Query(text="x y z w"), _caps(), policy)
    scoped = pl.plan(Query(text="x y z w", filters=Filters(uri_prefix="a/")), _caps(), policy)
    assert bare.plan_digest != scoped.plan_digest


def test_a_different_k_is_a_different_plan(policy: RetrievalPolicy) -> None:
    """D234. On 07:1541's printed key these two share a cache entry, and the second gets the
    first's `limit` on every Channel."""
    small = pl.plan(Query(text="parental leave notice period", k=5), _caps(), policy)
    large = pl.plan(Query(text="parental leave notice period", k=200), _caps(), policy)
    assert small.plan_digest != large.plan_digest
    assert {spec.name: spec.limit for spec in small.channels}["lexical"] == 25
    assert {spec.name: spec.limit for spec in large.channels}["lexical"] == 1_000


def test_the_memo_key_names_eleven_fields_and_the_document_prints_five() -> None:
    printed = ("mode", "channels", "filter_fields", "policy_digest", "caps_digest")
    assert set(printed) <= set(pl.MEMO_FIELDS)
    assert len(pl.MEMO_FIELDS) == 11


def test_the_memo_is_bounded_and_clearing_it_changes_no_answer(policy: RetrievalPolicy) -> None:
    """A cache of a pure function may be dropped at any time without changing a result."""
    query = Query(text="parental leave notice period")
    cached = pl.plan(query, _caps(), policy)
    pl.clear_memo()
    assert pl.plan(query, _caps(), policy) == cached


def test_every_plan_carries_the_one_scorer_version(policy: RetrievalPolicy) -> None:
    """07:1382's *"ONE constant"*, and a run that cannot name its scorer cannot be compared."""
    assert pl.plan(Query(), _caps(), policy).scorer_version == SCORER_VERSION


def test_the_plan_carries_the_policy_digest_it_was_built_from(policy: RetrievalPolicy) -> None:
    assert pl.plan(Query(), _caps(), policy).policy_digest == policy.policy_digest


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------


def test_the_module_imports_no_clock_no_rng_and_no_environment() -> None:
    """The `tools/gate_pure_eval.py` half is unwritten (P5's exit criterion); this is the import
    half, which a test can make without semgrep. 01:422 names this file beside `route/eval.py`."""
    source = (pl.__file__ or "").replace("\\", "/")
    text = __import__("pathlib").Path(source).read_text(encoding="utf-8")
    for banned in ("import time", "import random", "os.environ", "import os", "open("):
        assert f"\n{banned}" not in text


def test_planning_twice_returns_equal_plans_in_either_order(policy: RetrievalPolicy) -> None:
    """RT1's shape for this surface: evaluate the fixtures twice in shuffled order, assert
    identity. The planner has no state a call can leave behind except the memo."""
    queries = [
        Query(text="parental leave notice period"),
        Query(refs=("d7#412",), mode="cite"),
        Query(mode="explore", filters=Filters(sec_path_prefix="/0003/0007")),
        Query(text="is liability capped at twelve months of fees", mode="prove_absent"),
    ]
    forward = [pl.plan(query, _caps(), policy) for query in queries]
    pl.clear_memo()
    backward = [pl.plan(query, _caps(), policy) for query in reversed(queries)]
    assert forward == list(reversed(backward))


# ---------------------------------------------------------------------------
# W6.4 -- decision 3's bind-time half, and the one field a caller may not set
# ---------------------------------------------------------------------------

THEMATIC = "what does this corpus say about supply-chain concentration risk"


def _set(n: int) -> Narrowing:
    """An exact narrowing of `n` blocks -- `Narrowing.n` is EXACT when `kind == "set"` (07:1581)."""
    return Narrowing(kind="set", table="tmp_narrow", n=n)


def test_the_clamp_divides_the_corpus_by_the_narrowed_set() -> None:
    """07:1671's `clamp(1/selectivity, 1, 64)`, over worked plan (1)'s own narrowing.

    07:1841 narrows the 41,822-block handbook to *"n=38,104"*, a selectivity of 0.911, so the
    factor is 2 -- a query that filters almost nothing over-fetches almost nothing. A tenth of the
    corpus is a factor of 10 -- 41,822 over 4,183, rounded UP, which is the number the
    post-filter has to survive.
    """
    assert pl.overfetch_clamp(_set(38_104), _caps()) == 2
    assert pl.overfetch_clamp(_set(4_183), _caps()) == 10


def test_a_narrowing_that_kept_the_corpus_needs_no_over_fetch() -> None:
    """Selectivity 1.0. The clamp's floor is 1 and it is reached, not approached."""
    assert pl.overfetch_clamp(_set(41_822), _caps()) == 1


def test_the_clamp_stops_at_the_maximum_it_is_named_for() -> None:
    """`STALE_OVERFETCH = 64` is the ceiling of the same clamp, not a second number."""
    assert pl.overfetch_clamp(_set(1), _caps()) == pl.STALE_OVERFETCH


def test_a_stale_stat_takes_the_maximum_before_anything_is_divided() -> None:
    """07:729: *"age > STAT_MAX_AGE_NS or a key is missing"* takes the maximum clamp.

    The narrowing here would otherwise yield 1, so the assertion is that staleness OVERRIDES the
    measurement rather than bounding it -- 07:722's *"staleness fails expensive"*, because a wrong
    over-fetch factor is a silent recall loss.
    """
    assert pl.overfetch_clamp(_set(41_822), _caps(stale=True)) == pl.STALE_OVERFETCH


def test_a_live_blocks_count_of_zero_is_the_missing_key() -> None:
    """`stat` is that count's only writer (07:722), so a zero is absence and not a small corpus."""
    empty_stat = dataclasses.replace(_caps(), live_blocks=0)
    assert pl.overfetch_clamp(_set(10), empty_stat) == pl.STALE_OVERFETCH


def test_an_empty_narrowing_has_nothing_to_over_fetch() -> None:
    """A proven-empty candidate set short-circuits every Channel, so the factor is the floor."""
    assert pl.overfetch_clamp(Narrowing(kind="empty", table=None, n=0), _caps()) == 1


def test_above_the_cap_the_capped_count_over_estimates_the_factor() -> None:
    """The probe stopped at `PREFILTER_MAX + 1`, so the division is by a count that is too SMALL.

    A ten-million-block corpus whose narrowed set the probe could not enumerate yields 50. If the
    true set were five million the honest factor would be 2, so this over-fetches by 25x -- which
    is the direction to be wrong in: 07:1782-1783 calls an under-fetch *"silent recall loss that
    presents as absence"*, and an over-fetch costs the backend a longer list.
    """
    big = dataclasses.replace(_caps(), live_blocks=10_000_000)
    proof = Narrowing(kind="all", table=None, n=PREFILTER_MAX + 1)
    assert pl.overfetch_clamp(proof, big) == 50
    assert pl.overfetch_clamp(proof, big) > pl.overfetch_clamp(_set(5_000_000), big)


def test_the_bind_moves_the_semantic_spec_and_leaves_the_other_four(
    policy: RetrievalPolicy,
) -> None:
    """07:1781 gives the selectivity clamp to the semantic Channel by name.

    `LEX_OVERFETCH = 5` is *"always"* (07:1780) and must not move with the narrowing; the three
    exact Channels fetch what they rank.
    """
    made = pl.plan(Query(text=THEMATIC, k=20), _caps(vectors=True), policy)
    bound = pl.bind_overfetch(made, _set(4_183), _caps(vectors=True))
    before = {spec.name: spec.overfetch for spec in made.channels}
    after = {spec.name: spec.overfetch for spec in bound.channels}
    assert before["semantic"] == 1
    assert after["semantic"] == 10
    assert {name: value for name, value in after.items() if name != "semantic"} == {
        name: value for name, value in before.items() if name != "semantic"
    }


def test_the_bind_does_not_move_the_plan_digest(policy: RetrievalPolicy) -> None:
    """07:1545: the digest is *"computed over the unbound specs"*, and the factor is a filter VALUE.

    A digest that moved here would slice the scoreboard by narrowed-set size rather than by query
    shape, which is the one thing `plan_digest` exists to make sliceable.
    """
    made = pl.plan(Query(text=THEMATIC), _caps(vectors=True), policy)
    wide = pl.bind_overfetch(made, _set(41_822), _caps(vectors=True))
    narrow = pl.bind_overfetch(made, _set(1_000), _caps(vectors=True))
    assert wide.plan_digest == narrow.plan_digest == made.plan_digest
    assert {spec.name: spec.overfetch for spec in wide.channels}["semantic"] == 1
    assert {spec.name: spec.overfetch for spec in narrow.channels}["semantic"] == 42


def test_the_bound_limit_is_k_times_the_factor(policy: RetrievalPolicy) -> None:
    """07:3297's `limit = k x overfetch`. A factor with no depth is a number nobody spends."""
    made = pl.plan(Query(text=THEMATIC, k=20), _caps(vectors=True), policy)
    bound = pl.bind_overfetch(made, _set(4_183), _caps(vectors=True))
    semantic = next(spec for spec in bound.channels if spec.name == "semantic")
    assert semantic.limit == 20 * 10
    assert bound.pack.k == 20


def test_a_caller_set_restriction_mask_is_refused(policy: RetrievalPolicy) -> None:
    """07:1576: `deny_restriction_bits` is *"set by POLICY, never by the caller (DR17)"*.

    14:101 makes it boundary B6. No shipped policy shape carries the value -- `RetrievalPolicy` is
    four fields and a `Rule`'s `then` half is channels, weights, a short-circuit and gate
    modifiers -- so a non-zero mask here came from the caller, which is the source the boundary
    excludes. D261.
    """
    with pytest.raises(UsageError, match="only policy may set it"):
        pl.plan(Query(filters=Filters(deny_restriction_bits=0b10)), _caps(), policy)


def test_the_deny_methods_twin_is_the_callers_to_set(policy: RetrievalPolicy) -> None:
    """07:1640: *"Unlike `deny_restriction_bits` (DR17: policy only), `deny_methods` is a
    caller-expressible intent."* V10-17's shipped spelling plans like any other query, and the
    filters reach the plan unchanged."""
    filters = Filters(deny_methods=frozenset({Method.ROUNDTRIP}))
    made = pl.plan(Query(text="parental leave", filters=filters), _caps(), policy)
    assert made.filters is filters
    assert made.filters.deny_restriction_bits == 0
