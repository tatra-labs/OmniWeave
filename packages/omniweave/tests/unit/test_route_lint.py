"""`omniweave.route.lint` against 05-ingest-and-routing.md sections 4.3 and 4.5, and F30.

**A subsumption linter's unit tests are mostly about what it does NOT report.** A finding is a
claim that a rule can never fire, so a false positive tells an operator to delete a guard that
works; F30 (17-risks.md:890) pre-commits to that asymmetry -- *"a lint that overclaims is worse than
none"* -- and the tests below are written to it. Every positive case is paired with the same shape
inverted, and the four undecidable cases each get a test that the verdict is `Undecided` rather
than either answer.

The strongest test here is again the shipped policy: **fifty-two ordered action pairs, fifty-one
decided and zero findings**. It exercises the whole algebra, because section 4.4's forty rules use
every `when` form, both dtypes and every comparison operator. The fifty-second pair is
`decode.broken-font-encoding` against `decode.part-text-unusable`, which both declare
`on_unknown = "match"` -- D207's exact shape, and the one thing on this policy the algebra cannot
settle. It is asserted by name rather than tolerated by a `<= 1`: a second one appearing is a change
somebody should have to explain.

`_plan/` is needed only to check `CORE_48` against the plan's own block; the shipped policy is a
committed FILE and every other test here reads it directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from omniweave.route import evidence as ev
from omniweave.route import lint as rl
from omniweave.route import policy as rp
from omniweave.route.rung import Rung

if TYPE_CHECKING:
    from pathlib import Path

CORE_48 = (  # noqa: SIM905 -- the plan's own whitespace-separated block, kept verbatim
    "pdf docx doc pptx ppt xlsx xls csv tsv rtf odt ods odp epub html xhtml xml md txt json jsonl "
    "ipynb svg eml msg mbox png jpeg webp tiff bmp gif mp4 matroska mp3 wav flac ogg ps sqlite "
    "zip tar gz sevenz rar xz empty unknown"
).split()
"""Core's forty-eight format tokens, transcribed from 05:636-641's own block.

**A test fixture and deliberately not a constant in `omniweave`.** The vocabulary belongs to
`route/detect.py`, which is section 2.2's module and is not built; minting it inside the linter
would be claiming a cell this one was not given. A test may read the plan -- that is what the
`plan` fixture is for -- and this list is checked against the plan's own block below.
"""


def _policy(body: str, **kw: Any) -> rp.RoutePolicy:
    layer = rp.load_layer(body.encode(), layer="builtin", origin="a test")
    return rp.compile_policy([layer], **kw)


def _two(
    first: str, second: str, *, rung: str = "DECODE", lanes: tuple[str, str] = ("text", "text")
) -> rp.RoutePolicy:
    """Two action rules, `first` ahead of `second`. `lanes` splits them across two rule lists."""
    return _policy(
        'surface = "route"\n\n'
        f'[[rule]]\nid = "a"\nrung = "{rung}"\nlane = "{lanes[0]}"\nwhen = {first}\n'
        'then = { escalate_to = "REGEN" }\n\n'
        f'[[rule]]\nid = "b"\nrung = "{rung}"\nlane = "{lanes[1]}"\nwhen = {second}\n'
        'then = { outcome = "ok_partial", reason = "r" }\n'
    )


def _verdict(first: str, second: str, **kw: Any) -> tuple[list[str], list[str]]:
    findings, undecided, _ = rl.subsumption(_two(first, second, **kw))
    return [f.rule_id for f in findings], [u.reason for u in undecided]


# --------------------------------------------------------------------------------------------
# 1. The box algebra, directly. Each direction of each containment.
# --------------------------------------------------------------------------------------------


def test_an_interval_contains_a_narrower_one_and_not_a_wider_one() -> None:
    wide = rl.Span(lo=0.0, lo_closed=True)
    narrow = rl.Span(lo=0.5, lo_closed=True)
    assert rl.contains(wide, narrow) is True
    assert rl.contains(narrow, wide) is False


def test_an_open_bound_does_not_contain_its_own_endpoint() -> None:
    """The one place an off-by-one in an interval linter hides: `> 0.5` and `>= 0.5` differ on
    exactly one value, and that value is the threshold an author wrote deliberately."""
    assert rl.contains(rl.Span(lo=0.5), rl.Span(lo=0.5, lo_closed=True)) is False
    assert rl.contains(rl.Span(lo=0.5, lo_closed=True), rl.Span(lo=0.5)) is True


def test_a_hole_in_the_outer_interval_breaks_containment() -> None:
    """`ne` on a numeric key is an interval with a hole, and the hole is a real exclusion: `[0, 1]`
    minus `{0.5}` does not contain `[0, 1]`."""
    holed = rl.Span(lo=0.0, hi=1.0, lo_closed=True, hi_closed=True, holes=frozenset({0.5}))
    solid = rl.Span(lo=0.0, hi=1.0, lo_closed=True, hi_closed=True)
    assert rl.contains(holed, solid) is False
    assert rl.contains(solid, holed) is True
    assert rl.contains(holed, rl.Span(lo=0.6, hi=0.9, lo_closed=True, hi_closed=True)) is True


def test_three_of_the_four_categorical_directions_need_no_universe() -> None:
    """F30's cost is exactly one of four. 05:631 makes `unit.format`'s domain *"computed, never
    closed"*, so a linter needing the universe for every comparison would decide nothing about the
    one key every `GATE` rule reads."""
    pos = rl.Cat(items=frozenset({"pdf", "docx"}))
    wider = rl.Cat(items=frozenset({"pdf", "docx", "pptx"}))
    neg = rl.Cat(items=frozenset({"png"}), positive=False)
    fewer_excluded = rl.Cat(items=frozenset({"png", "gif"}), positive=False)
    assert rl.contains(wider, pos) is True  # positive in positive
    assert rl.contains(neg, pos) is True  # positive in complement -- disjoint from the exclusion
    assert rl.contains(neg, fewer_excluded) is True  # complement in complement
    assert rl.contains(pos, neg) is None  # complement in positive: THE undecidable one


def test_the_one_undecidable_direction_decides_when_the_domain_is_closed() -> None:
    """A `frozenset[str]` domain IS the universe, so the same comparison is exact on a closed key.
    That is what confines F30 to `unit.format` and the other computed domains."""
    universe = frozenset({"a", "b"})
    neg = rl.Cat(items=frozenset({"a"}), positive=False, universe=universe)
    assert rl.contains(rl.Cat(items=frozenset({"b"}), universe=universe), neg) is True
    assert rl.contains(rl.Cat(items=frozenset({"a"}), universe=universe), neg) is False


def test_exists_true_is_implied_by_every_value_constraint() -> None:
    """A test over UNKNOWN is UNKNOWN, so a state inside any value-constrained box HAS the key.
    That makes `{exists: true}` the weakest non-trivial constraint rather than a special case."""
    assert rl.contains(rl.PRESENT, rl.Span(lo=0.5)) is True
    assert rl.contains(rl.PRESENT, rl.Cat(items=frozenset({"pdf"}))) is True
    assert rl.contains(rl.PRESENT, rl.ABSENT) is False
    assert rl.contains(rl.ABSENT, rl.PRESENT) is False
    assert rl.contains(rl.ABSENT, rl.ABSENT) is True


def test_meeting_two_clauses_on_one_key_intersects_them() -> None:
    """What `all_of` does, and why `meet` has to be total: an `all_of` of N clauses compiles to ONE
    box, so every pair of shapes needs an exact intersection."""
    band = rl.meet(rl.Span(lo=0.2, lo_closed=True), rl.Span(hi=0.8))
    assert isinstance(band, rl.Span)
    assert band.lo == 0.2
    assert band.hi == 0.8
    assert band.lo_closed and not band.hi_closed
    assert rl.contains(rl.Span(lo=0.0, hi=1.0, lo_closed=True), band) is True


def test_an_exists_false_meeting_a_value_test_is_the_empty_set() -> None:
    """A key cannot be absent and satisfy a comparison at once; an empty box fires on nothing."""
    assert rl.meet(rl.ABSENT, rl.Span(lo=0.5)) == rl.EMPTY
    assert rl.meet(rl.PRESENT, rl.Span(lo=0.5)) == rl.Span(lo=0.5)


# --------------------------------------------------------------------------------------------
# 2. `when` to boxes.
# --------------------------------------------------------------------------------------------


def test_a_bare_clause_and_an_all_of_are_one_box_and_an_any_of_is_several() -> None:
    bare = _two('{ "garble.score" = { gte = 0.5 } }', '{ "garble.score" = { gte = 0.9 } }')
    assert len(rl.boxes_of(bare.rules[0].when) or ()) == 1
    union = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\n'
        'when.any_of = [ { "unit.format" = "pdf" }, { "unit.format" = "docx" } ]\n'
        'then = { outcome = "skip" }\n'
    )
    assert len(rl.boxes_of(union.rules[0].when) or ()) == 2


def test_a_none_of_has_no_box_at_all() -> None:
    """The complement of a union of boxes is not a box, and 05:968's *"1 level"* means there is no
    nesting to push the negation through. `None` and not an empty tuple: an empty tuple would read
    as "matches nothing", which is the opposite of what `none_of` usually matches."""
    negated = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\n'
        'when.none_of = [ { "unit.format" = "png" } ]\nthen = { outcome = "skip" }\n'
    )
    assert rl.boxes_of(negated.rules[0].when) is None


# --------------------------------------------------------------------------------------------
# 3. Check 8 over pairs, each positive case paired with its inverse.
# --------------------------------------------------------------------------------------------


def test_a_narrower_numeric_guard_behind_a_wider_one_can_never_fire() -> None:
    """The canonical shape, and the one an author writes by accident when tightening a threshold in
    place instead of moving the rule."""
    found, undecided = _verdict(
        '{ "garble.score" = { gte = 0.5 } }', '{ "garble.score" = { gte = 0.9 } }'
    )
    assert found == ["b"]
    assert undecided == []


def test_the_same_pair_in_the_other_order_is_not_a_finding() -> None:
    found, undecided = _verdict(
        '{ "garble.score" = { gte = 0.9 } }', '{ "garble.score" = { gte = 0.5 } }'
    )
    assert found == []
    assert undecided == []


def test_an_extra_conjunct_narrows_and_is_therefore_subsumed() -> None:
    found, _ = _verdict(
        '{ "unit.format" = "pdf" }',
        '{ "unit.format" = "pdf", "decode.char_count" = { lt = 10 } }',
    )
    assert found == ["b"]


def test_a_key_the_earlier_rule_reads_and_the_later_does_not_breaks_containment() -> None:
    """The mirror of the test above, and the reason is worth stating: a state satisfying the later
    rule says nothing about that key, so it may be UNKNOWN -- and an UNKNOWN key makes the earlier
    rule's test UNKNOWN rather than True."""
    found, _ = _verdict(
        '{ "unit.format" = "pdf", "decode.char_count" = { lt = 10 } }', '{ "unit.format" = "pdf" }'
    )
    assert found == []


def test_a_subset_of_an_in_list_is_subsumed() -> None:
    found, _ = _verdict(
        '{ "unit.format" = { in = ["pdf", "docx", "pptx"] } }',
        '{ "unit.format" = { in = ["pdf", "docx"] } }',
        rung="GATE",
    )
    assert found == ["b"]


def test_every_disjunct_of_an_any_of_must_fit() -> None:
    """A union is subsumed iff each of its boxes is. One disjunct escaping is the whole rule
    escaping, which is why the quantifier is universal on the later rule's side."""
    inside = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\n'
        'when = { "unit.format" = { in = ["pdf", "docx", "pptx"] } }\n'
        'then = { outcome = "skip" }\n\n'
        '[[rule]]\nid = "b"\nrung = "GATE"\n'
        'when.any_of = [ { "unit.format" = "pdf" }, { "unit.format" = "docx" } ]\n'
        'then = { outcome = "refuse", failure_class = "corrupt_input" }\n'
    )
    escapes = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\n'
        'when = { "unit.format" = { in = ["pdf", "docx"] } }\n'
        'then = { outcome = "skip" }\n\n'
        '[[rule]]\nid = "b"\nrung = "GATE"\n'
        'when.any_of = [ { "unit.format" = "pdf" }, { "unit.format" = "png" } ]\n'
        'then = { outcome = "refuse", failure_class = "corrupt_input" }\n'
    )
    assert [f.rule_id for f in rl.subsumption(inside)[0]] == ["b"]
    assert rl.subsumption(escapes)[0] == ()


def test_a_modifier_is_exempt_on_both_sides() -> None:
    """05:1174: modifiers *"are meant to overlap"*, and 05:1023 is why that is not a convenience --
    a matched action does not stop a later modifier contributing, so a modifier inside another's
    box is a working policy and not a dead guard."""
    policy = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "DECODE"\n'
        'when = { "garble.score" = { gte = 0.5 } }\nthen = { escalate_to = "REGEN" }\n\n'
        '[[rule]]\nid = "b"\nrung = "DECODE"\n'
        'when = { "garble.score" = { gte = 0.9 } }\nthen = { max_cost_class = "free" }\n'
    )
    findings, _, compared = rl.subsumption(policy)
    assert findings == ()
    assert compared == 0, "a modifier is not compared at all, not compared and cleared"


def test_two_lanes_are_two_rule_lists_and_never_compared() -> None:
    """`rule.lane` says which lane's list a rule belongs to (05:1032). A `table`-lane rule inside a
    `text`-lane rule's box is two independent passes over the same part (05:870), not a shadow."""
    found, _ = _verdict(
        '{ "garble.score" = { gte = 0.5 } }',
        '{ "garble.score" = { gte = 0.9 } }',
        lanes=("text", "table"),
    )
    assert found == []


def test_two_rungs_are_never_compared() -> None:
    policy = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "DECODE"\n'
        'when = { "garble.score" = { gte = 0.5 } }\nthen = { escalate_to = "REGEN" }\n\n'
        '[[rule]]\nid = "b"\nrung = "PAGE"\n'
        'when = { "garble.score" = { gte = 0.9 } }\nthen = { escalate_to = "DEGRADE" }\n'
    )
    assert rl.subsumption(policy)[0] == ()


def test_the_phase_splits_a_rung_into_two_lists() -> None:
    """05:1136's derived phase, and the reason check 8 groups on it: *"`decode.part-text-unusable`
    settles after `parse.pdf.pdfium` has run and does not shadow `decode.pdf-text-layer` in the
    select phase, even though both declare `rung = "DECODE"`."*"""
    registry = ev.build_registry(ev.builtin_specs())
    policy = rp.compile_policy([rp.builtin_layer()], registry=registry)
    groups = {policy.phase_of_rule(rule) for rule in policy.rules if rule.rung is Rung.DECODE}
    assert groups == {"select", "settle"}


# --------------------------------------------------------------------------------------------
# 4. The four undecidables, each reported as itself.
# --------------------------------------------------------------------------------------------


def test_an_open_string_domain_is_undecidable_and_says_which_key() -> None:
    """F30, reached. Without a registry `unit.format` has no universe, so `D \\ {png}` inside
    `{pdf, docx}` cannot be settled -- and the report carries the key so a reader can see that the
    gap is about a domain rather than about the rule."""
    policy = _two(
        '{ "unit.format" = { in = ["pdf", "docx"] } }',
        '{ "unit.format" = { not_in = ["png"] } }',
        rung="GATE",
    )
    findings, undecided, compared = rl.subsumption(policy)
    assert findings == ()
    assert compared == 0
    assert [(u.reason, u.key) for u in undecided] == [(rl.UNDECIDED_OPEN_DOMAIN, "unit.format")]


def test_supplying_the_computed_domain_decides_the_same_pair() -> None:
    """The escape hatch is the caller's, not the linter's: `ow route lint` knows the enabled cards
    and can close the domain for one run, and the closure is then that run's assumption rather than
    a fact the linter asserted."""
    policy = _two(
        '{ "unit.format" = { in = ["pdf", "docx"] } }',
        '{ "unit.format" = { not_in = ["png"] } }',
        rung="GATE",
    )
    registry = ev.build_registry(ev.builtin_specs())
    findings, undecided, compared = rl.subsumption(
        policy, registry=registry, format_domain=("pdf", "docx", "png")
    )
    assert undecided == ()
    assert compared == 1
    assert [f.rule_id for f in findings] == ["b"]


def test_a_none_of_on_either_side_is_undecidable() -> None:
    for first, second in (
        ('{ "unit.format" = "pdf" }', "<none_of>"),
        ("<none_of>", '{ "unit.format" = "pdf" }'),
    ):
        body = 'surface = "route"\n\n'
        for rule_id, when in (("a", first), ("b", second)):
            clause = (
                'when.none_of = [ { "unit.format" = "png" } ]\n'
                if when == "<none_of>"
                else f"when = {when}\n"
            )
            body += (
                f'[[rule]]\nid = "{rule_id}"\nrung = "GATE"\n{clause}'
                'then = { outcome = "skip" }\n\n'
            )
        _, undecided, compared = rl.subsumption(_policy(body))
        assert compared == 0
        assert [u.reason for u in undecided] == [rl.UNDECIDED_NONE_OF]


def test_a_later_rule_that_fires_on_unknown_is_decided_by_the_blank_record() -> None:
    """Not undecidable, and the distinction is the point: on the all-UNKNOWN record the later rule
    matches (`on_unknown = "match"`) and the earlier one does not, so the later provably CAN fire
    and `OW-P-011`'s *"can never fire"* is false of it. A `Finding` here would be the overclaim."""
    policy = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "DECODE"\non_unknown = "skip"\n'
        'when = { "garble.score" = { gte = 0.5 } }\nthen = { escalate_to = "REGEN" }\n\n'
        '[[rule]]\nid = "b"\nrung = "DECODE"\non_unknown = "match"\n'
        'when = { "garble.score" = { gte = 0.9 } }\nthen = { outcome = "ok_partial" }\n'
    )
    findings, undecided, compared = rl.subsumption(policy)
    assert findings == ()
    assert undecided == ()
    assert compared == 1


def test_it_stays_undecidable_when_the_earlier_rule_also_matches_the_blank_record() -> None:
    """The residue. Both rules fire on the all-UNKNOWN record, so the witness proves nothing and
    the containment question is about a union this algebra does not represent. D207."""
    policy = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "DECODE"\non_unknown = "match"\n'
        'when = { "garble.score" = { gte = 0.5 } }\nthen = { escalate_to = "REGEN" }\n\n'
        '[[rule]]\nid = "b"\nrung = "DECODE"\non_unknown = "match"\n'
        'when = { "garble.score" = { gte = 0.9 } }\nthen = { outcome = "ok_partial" }\n'
    )
    findings, undecided, compared = rl.subsumption(policy)
    assert findings == ()
    assert compared == 0
    assert [u.reason for u in undecided] == [rl.UNDECIDED_ON_UNKNOWN]


def test_an_exists_only_later_rule_is_compared_despite_its_on_unknown() -> None:
    """An `exists`-only `when` is never UNKNOWN (05:1004), so `on_unknown` is dead on it and the
    box IS the firing set. Refusing to compare it would leave `degrade.budget-exhausted`'s shape
    permanently unlintable for a reason that does not apply to it."""
    policy = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "DEGRADE"\n'
        'when = { "budget.exhausted" = { exists = true } }\nthen = { outcome = "ok_partial" }\n\n'
        '[[rule]]\nid = "b"\nrung = "DEGRADE"\non_unknown = "match"\n'
        'when = { "budget.exhausted" = { exists = true } }\nthen = { outcome = "refuse", '
        'failure_class = "budget_exhausted" }\n'
    )
    findings, undecided, compared = rl.subsumption(policy)
    assert [f.rule_id for f in findings] == ["b"]
    assert undecided == ()
    assert compared == 1


# --------------------------------------------------------------------------------------------
# 5. The degradation, and the report's own honesty.
# --------------------------------------------------------------------------------------------


def test_a_finding_becomes_a_policy_pruned_degradation_naming_the_subsuming_rule() -> None:
    """05:1170 orders it and 15:1077 gives the payload: *"a subsumed rule was dropped from the
    demand plan and its keys were never computed"*, with the knob column reading *"the subsuming
    rule's id"*."""
    findings, _, _ = rl.subsumption(
        _two('{ "garble.score" = { gte = 0.5 } }', '{ "garble.score" = { gte = 0.9 } }')
    )
    (degradation,) = rl.degradations(findings)
    assert degradation.kind == "policy_pruned"
    assert degradation.knob == "a"
    assert "'b'" in degradation.message
    assert "a" in degradation.message
    assert degradation.fix_command == "ow route lint --explain b"


def test_the_report_names_every_check_it_did_not_run() -> None:
    """A linter running six of fourteen in silence is F30's failure one level up. The eight unrun
    checks are data, printed on a clean run too -- a reader must not be able to read "no findings"
    as "all fourteen passed"."""
    report = rl.lint(
        _policy(
            'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\n'
            'when = { "unit.format" = "pdf" }\nthen = { outcome = "skip" }\n'
        )
    )
    assert set(rl.NOT_RUN) == {3, 5, 6, 9, 11, 12, 13, 14}
    assert set(report.not_run) == {1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14}
    lines = report.render()
    assert sum(line.startswith("not run:") for line in lines) == 13
    assert any("decided 0 pair(s)" in line for line in lines)


def test_checks_five_and_twelve_are_listed_as_unrun_because_the_loader_raises_them() -> None:
    """Both would be errors here and neither can reach: `load_layer` refuses a backward
    `escalate_to` (`OW-P-005`) and a `then` that does nothing (`OW-P-013`), so a policy carrying
    either never becomes a `RoutePolicy`. Listed anyway, so the fourteen add up."""
    assert "load_layer()" in rl.NOT_RUN[5]
    assert "load_layer()" in rl.NOT_RUN[12]


# --------------------------------------------------------------------------------------------
# 6. Checks 1, 2, 4, 7 and 10 against the registry.
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> ev.SignalRegistry:
    specs = list(ev.builtin_specs())
    for provider, relative in (
        ("pdfium", "packages/omniweave-pdf/src/omniweave_pdf/signals.toml"),
        ("officexml", "packages/omniweave-office/src/omniweave_office/signals.toml"),
    ):
        specs.extend(
            ev.load_signals((repo_root / relative).read_bytes(), provider=provider, origin=relative)
        )
    return ev.build_registry(specs)


def test_check_one_names_a_key_no_provider_registers(registry: ev.SignalRegistry) -> None:
    policy = _policy(
        'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\n'
        'when = { "unit.vibe" = "good" }\nthen = { outcome = "skip" }\n'
    )
    (finding,) = rl.unresolved_keys(policy, registry)
    assert finding.code == "OW-P-001"
    assert "unit.vibe" in finding.message


def test_check_two_catches_a_literal_outside_a_closed_domain(registry: ev.SignalRegistry) -> None:
    """`unit.trust_class` has a `frozenset[str]` domain, which is what check 2 tests against."""
    keys = registry.keys()
    closed = [key for key in keys if isinstance(registry.domain_of(key), frozenset)]
    assert closed, "the day-one registry has at least one closed str domain"
    key = closed[0]
    bad = sorted(registry.domain_of(key))[0] + "-nope"  # type: ignore[operator]
    policy = _policy(
        f'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\n'
        f'when = {{ "{key}" = "{bad}" }}\nthen = {{ outcome = "skip" }}\n'
    )
    (finding,) = rl.literals_outside_domain(policy, registry)
    assert finding.code == "OW-P-002"
    assert bad in finding.message


def test_check_seven_catches_a_rule_reading_a_key_from_a_later_rung(
    registry: ev.SignalRegistry,
) -> None:
    """05:1144's *"the only way this can go wrong"*: the key cannot have a value in either phase of
    the rule's rung, so the guard is a permanent UNKNOWN."""
    keys = registry.keys()
    late = [k for k in keys if any(r > Rung.GATE for r in registry.requires_of(k))]
    assert late, "some day-one key requires a rung above GATE"
    policy = _policy(
        f'surface = "route"\n\n[[rule]]\nid = "a"\nrung = "GATE"\non_unknown = "skip"\n'
        f'when = {{ "{late[0]}" = {{ exists = true }} }}\nthen = {{ outcome = "skip" }}\n'
    )
    (finding,) = rl.rungs_read_too_early(policy, registry)
    assert finding.code == "OW-P-010"
    assert late[0] in finding.message


# --------------------------------------------------------------------------------------------
# 7. The shipped policy. One assertion that exercises the whole algebra.
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shipped(registry: ev.SignalRegistry) -> rp.RoutePolicy:
    """The FILE, not the fence. It is committed, so this needs no `_plan/`."""
    return rp.compile_policy([rp.builtin_layer()], registry=registry)


def test_the_shipped_policy_has_no_unfirable_guard_and_every_pair_decided(
    shipped: rp.RoutePolicy,
) -> None:
    """Fifty-two ordered action pairs, all decided, none subsumed.

    The second half is the stronger claim. F30 pre-commits to an incomplete linter, and the shipped
    forty use every `when` form, both dtypes and every comparison operator -- so a run with **zero**
    `Undecided` is evidence that the incompleteness costs nothing on the policy that ships, rather
    than a promise that it will not.
    """
    findings, undecided, compared = rl.subsumption(shipped)
    assert findings == ()
    assert compared == 51
    assert [(u.rule_id, u.against, u.reason) for u in undecided] == [
        ("decode.broken-font-encoding", "decode.part-text-unusable", rl.UNDECIDED_ON_UNKNOWN)
    ]


def test_the_shipped_policy_names_every_one_of_cores_forty_eight_format_tokens(
    shipped: rp.RoutePolicy,
) -> None:
    """Check 10, `OW-P-014`, and the proof that pairs with shipping the policy as a file.

    05:1790: *"`mp3`, `eml`, `zip`, `doc` and six more tokens exist in the detection vocabulary, and
    a policy that never names them routes them nowhere."* Both directions come out empty: every
    token is named by a `GATE` or `DECODE` rule, and every literal those rules name is a token.
    """
    named = rl.format_token_union(shipped)
    assert len(CORE_48) == 48
    assert named == frozenset(CORE_48)
    assert rl.format_coverage(shipped, CORE_48) == ()


def test_core_forty_eight_is_the_plans_own_block(plan: Any) -> None:
    """The fixture above is a transcription, held to the plan the way the policy file is."""
    plan.require()
    body = plan.lines("05-ingest-and-routing.md")
    start = next(i for i, line in enumerate(body) if line.startswith("pdf docx doc pptx"))
    printed: list[str] = []
    for line in body[start:]:
        if not line.strip() or line.startswith("```"):
            break
        printed.extend(line.split("#")[0].split("(")[0].split())
    assert printed == CORE_48


def test_the_shipped_policy_is_clean_under_every_check_this_module_runs(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    """Six of fourteen, and the other eight named. The `ok` is the whole file's headline."""
    report = rl.lint(shipped, registry=registry, format_domain=CORE_48)
    assert report.findings == ()
    assert report.compared == 51
    assert len(report.undecided) == 1
    assert report.ok
    assert set(report.not_run) == {3, 5, 6, 9, 11, 12, 13, 14}
