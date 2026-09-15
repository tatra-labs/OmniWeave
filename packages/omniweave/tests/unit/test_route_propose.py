"""`omniweave.route.propose` -- the bindings, the passes, and the diff a human commits.

The sharpest test in this file is `test_the_photo_page_population_moves_the_threshold_down`. Section
10.3 works one threshold move through as its example, twice, and both times names the wrong
direction (D223); the fit over the population the section itself describes is the check, and it
disagrees with the word the plan uses.

Everything else is the two halves of the loop: which `[thresholds]` entries a fit can move at all,
and whether a diff emitted by `render_diff()` can be read back and applied to the file it names
without losing the marker comments that say where each number came from.
"""

from __future__ import annotations

import pytest
from omniweave.route import fit as rf
from omniweave.route import ledger as rlg
from omniweave.route import policy as rp
from omniweave.route import propose as rpz
from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import RouteError

SLICE = "pdf/workiva/true/en"
"""05:3162's own slice."""

MEASURED_ON = MeasuredOn(
    weights="n/a",
    weights_revision="n/a",
    runtime="n/a",
    runtime_version="n/a",
    sampling="n/a",
    prompt_version="n/a",
    hardware="n/a",
    corpus="fixtures/route/mixed-40",
    corpus_digest="c" * 16,
    harness_version="0.0.0",
)
"""Seven `"n/a"`s, which is 04 section 2.6's own instruction for a pure-code path, and three real
fields: a PAVA fit over stored rows has no weights, no runtime and no prompt."""

DIVERGENCE_MICROS = 10_000.0
"""What one whole unit of avoided divergence is worth, in micros. D209: no `PriceBook` row prices
one, so every caller states it and this test is a caller."""


def _policy() -> rp.RoutePolicy:
    return rp.compile_policy([rp.builtin_layer()], registry=None)


def _slice(
    state: str, slice_key: str = SLICE, rule_id: str = "decode.part-text-unusable"
) -> rlg.Rollup:
    return rlg.Rollup(
        slice_key=slice_key,
        rule_id=rule_id,
        driver="parse.page.olmocr",
        decisions_n=6_000,
        audited_n=30,
        divergence=0.38,
        escalation_divergence=0.06,
        complaints=0,
        micros=12_012,
        state=state,
    )


def _population() -> rlg.Log:
    """Section 10.3's part 177, forty times over, against ten genuinely unusable scans.

    05:2316: *"a page that is one large photograph with a caption -- the photo's ink is not
    explained by the text layer, coverage collapses, and the part escalates to a `PAGE` call that
    re-reads the caption it already had"*. 05:3160 gives that part `agree.decode_vs_page = 0.94`, so
    its divergence is 0.06 and the 858 micros bought 0.06 of a unit. A real scan diverges far more.
    """
    rows = [
        rf.Observation(
            signal=0.10 + index * 0.001, divergence=0.06, micros=858, decision_id=f"photo{index}"
        )
        for index in range(40)
    ]
    rows.extend(
        rf.Observation(
            signal=0.01 + index * 0.001, divergence=0.70, micros=858, decision_id=f"scan{index}"
        )
        for index in range(10)
    )
    return rlg.Log(observations=tuple(rows))


# --------------------------------------------------------------------------------------------
# 1. The bindings: the one place a threshold, its signal and its direction are one record.
# --------------------------------------------------------------------------------------------


def test_the_shipped_policy_binds_fourteen_thresholds_to_a_signal_and_a_direction() -> None:
    """Sixteen `[thresholds]` entries, fourteen of them read by an ORDERED operator in some rule."""
    found = rpz.bindings(_policy())
    assert len(found) == 14
    assert {one.direction for one in found} == set(rf.DIRECTIONS)


def test_ink_coverage_min_escalates_below_and_garble_escalate_above() -> None:
    """05:1525's two clauses, side by side: `ink.coverage lt` and `garble.score gte` are the two
    directions, and a fit that took the same direction for both would move one of them backwards."""
    by_name = {one.name: one for one in rpz.bindings(_policy())}
    assert (by_name["ink_coverage_min"].signal, by_name["ink_coverage_min"].direction) == (
        "ink.coverage",
        "below",
    )
    assert (by_name["garble_escalate"].signal, by_name["garble_escalate"].direction) == (
        "garble.score",
        "above",
    )


def test_two_thresholds_are_declared_and_read_by_no_rule() -> None:
    """`garble_min_chars` and `math_char_frac` are consumed INSIDE a signal computation rather than
    by a `when` clause -- 05:2282 (*"Below `@thresholds.garble_min_chars = 50` characters the
    verdict is not trusted at all and the signal returns `None`"*) and 05:2248 (`math_chars /
    len(text) > 0.02` per block). `@thresholds.<name>` is a compile-time substitution into a RULE,
    so neither reaches its reader, and `route_signal`'s key does not carry either. D222."""
    assert rpz.unfittable(_policy()) == (
        ("garble_min_chars", "declared and read by no rule"),
        ("math_char_frac", "declared and read by no rule"),
    )


# --------------------------------------------------------------------------------------------
# 2. The pass, and the direction section 10.3 names wrongly.
# --------------------------------------------------------------------------------------------


def test_the_photo_page_population_moves_the_threshold_down() -> None:
    """D223. 05:2321 and 05:3161 both call the evidence below what `ow route propose` reads to RAISE
    `ink_coverage_min`, and raising it is what escalates MORE.

    The rule is `ink.coverage < @thresholds.ink_coverage_min` (05:1525), so the escalating set is
    `{coverage < t}` and it GROWS as `t` rises. The evidence the section describes -- high
    `agree.decode_vs_page` on escalated parts, low `escalation_divergence` for the slice -- is
    evidence that the escalations are buying nothing, which argues for escalating less. The fit
    agrees: the argmax lands inside the scanned cluster, below the shipped 0.25.
    """
    binding = {one.name: one for one in rpz.bindings(_policy())}["ink_coverage_min"]
    assert binding.current == 0.25
    proposal = rf.fit(
        _population().observations,
        name=binding.name,
        current=binding.current,
        slice_key=SLICE,
        measured_on=MEASURED_ON,
        divergence_micros=DIVERGENCE_MICROS,
        direction="below",
        state="REGRESSED",
    )
    assert proposal is not None
    assert proposal.proposed < binding.current
    assert proposal.proposed <= 0.02
    assert proposal.gain > 0


def test_a_slice_at_unknown_yields_no_proposal_and_is_not_even_read() -> None:
    """05:2995's refusal, and it short-circuits BEFORE `observe`: reading a decision log to build
    observations nobody may publish is work done to reach a conclusion already reached."""
    reads: list[tuple[str, str]] = []

    def observe(slice_key: str, signal: str) -> rlg.Log:
        reads.append((slice_key, signal))
        return _population()

    outcomes = rpz.propose(
        _policy(),
        [_slice("UNKNOWN")],
        observe=observe,
        measured_on=MEASURED_ON,
        divergence_micros=DIVERGENCE_MICROS,
    )
    assert reads == []
    assert all(one.proposal is None for one in outcomes)
    assert "UNKNOWN" in outcomes[0].refusal


def test_every_pass_is_reported_even_when_it_proposes_nothing() -> None:
    """Fourteen bindings against one slice is fourteen passes, and a report that printed only the
    one proposal would read as a corpus with one threshold in it."""
    outcomes = rpz.propose(
        _policy(),
        [_slice("REGRESSED")],
        observe=lambda _key, signal: _population() if signal == "ink.coverage" else rlg.Log(),
        measured_on=MEASURED_ON,
        divergence_micros=DIVERGENCE_MICROS,
    )
    assert len(outcomes) == 14
    proposed = [one for one in outcomes if one.proposal is not None]
    assert [one.binding.name for one in proposed] == ["ink_coverage_min"]
    assert all(one.refusal for one in outcomes if one.proposal is None)


def test_the_refusal_names_which_of_the_fitters_three_it_was() -> None:
    """`fit()` returns `Proposal | None`, which is the right type for a fitter and the wrong one for
    a report, so the three remaining cases are separated from the log it was handed."""
    flat = rlg.Log(
        observations=tuple(
            rf.Observation(signal=0.11, divergence=0.06, micros=858, decision_id=str(index))
            for index in range(40)
        )
    )
    outcomes = rpz.propose(
        _policy(),
        [_slice("OK")],
        observe=lambda _key, _signal: flat,
        measured_on=MEASURED_ON,
        divergence_micros=DIVERGENCE_MICROS,
    )
    assert "one distinct value" in outcomes[0].refusal
    thin = rlg.Log(observations=flat.observations[:3], swept=9)
    outcomes = rpz.propose(
        _policy(),
        [_slice("OK")],
        observe=lambda _key, _signal: thin,
        measured_on=MEASURED_ON,
        divergence_micros=DIVERGENCE_MICROS,
    )
    assert "n = 3 is below min_n = 30" in outcomes[0].refusal
    assert "9 dropped for a swept payload" in outcomes[0].render()


def test_one_slice_is_fitted_once_even_though_the_view_rolls_up_per_rule() -> None:
    """`route_scoreboard` is per `(slice_key, rule_id, driver)`, so one slice appears once per rule
    that decided in it. A fit is per slice; running one per rollup row would emit one proposal per
    rule over one population."""
    rows = [_slice("OK", rule_id="decode.part-text-unusable"), _slice("OK", rule_id="gate.empty")]
    outcomes = rpz.propose(
        _policy(),
        rows,
        observe=lambda _key, _signal: _population(),
        measured_on=MEASURED_ON,
        divergence_micros=DIVERGENCE_MICROS,
    )
    assert len({one.slice_key for one in outcomes}) == 1
    assert len(outcomes) == 14


def test_the_worst_state_across_a_slices_rollup_rows_wins() -> None:
    """A slice with any rollup row still short of `min_audit_n` has a population part of which
    cannot speak, so `UNKNOWN` beats `REGRESSED` beats `OK`."""
    rows = [_slice("OK", rule_id="a"), _slice("UNKNOWN", rule_id="b")]
    outcomes = rpz.propose(
        _policy(),
        rows,
        observe=lambda _key, _signal: _population(),
        measured_on=MEASURED_ON,
        divergence_micros=DIVERGENCE_MICROS,
    )
    assert all(one.state == "UNKNOWN" for one in outcomes)


# --------------------------------------------------------------------------------------------
# 3. The diff, out and back.
# --------------------------------------------------------------------------------------------


def _proposal(name: str, current: float, proposed: float) -> rf.Proposal:
    return rf.Proposal(
        name=name,
        slice_key=SLICE,
        current=current,
        proposed=proposed,
        direction="below",
        n=40,
        ci95=(0.05, 0.07),
        measured_on=MEASURED_ON,
        objective=61_420.0,
        objective_now=51_100.0,
    )


def test_a_rendered_diff_reads_back_as_the_change_it_rendered() -> None:
    """The round trip is the guard: `render_diff()` and `parse_diff()` are one format, and a test
    that asserted the text of each separately would let the two drift apart on a shared reading."""
    diff = rf.render_diff(
        [_proposal("ink_coverage_min", 0.25, 0.02)],
        path=".omniweave/policy.d/route.toml",
        current={"ink_coverage_min": 0.25},
    )
    patch = rpz.parse_diff(diff)
    assert patch.path == ".omniweave/policy.d/route.toml"
    assert patch.changes == (rpz.Change(name="ink_coverage_min", old=0.25, new=0.02),)
    assert any("isotonic_pava_1d" in comment for comment in patch.comments)


def test_a_comment_only_hunk_parses_to_no_change() -> None:
    """Two slices that fitted one threshold to two values emit the numbers as comments and no `+`
    line (D208), so a promote of that diff applies nothing rather than picking a side."""
    diff = rf.render_diff(
        [_proposal("ink_coverage_min", 0.25, 0.02), _proposal("ink_coverage_min", 0.25, 0.09)],
        path="p.toml",
        current={"ink_coverage_min": 0.25},
    )
    patch = rpz.parse_diff(diff)
    assert patch.changes == ()
    assert any("proposes nothing" in comment for comment in patch.comments)


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["--- a/p.toml", "+++ b/p.toml", "+x = 1"], "no removed line"),
        (["--- a/p.toml", "+++ b/p.toml", "-x = 1"], "no added line"),
        (["--- a/p.toml", "+++ b/p.toml", "-x = 1", "-y = 2"], "two removed lines"),
        (["--- a/p.toml", "+++ b/p.toml", "-x = 1", "+y = 2"], "a rename"),
        (["--- a/p.toml", "+++ b/p.toml", "-x = high", "+x = 2"], "not `<name> = <number>`"),
        (["+++ b/p.toml", "-x = 1", "+x = 2"], "names no file"),
        (["--- a/p.toml", "@@ -1 +1 @@"], "not a line `ow route propose` emits"),
    ],
)
def test_the_parser_declines_every_shape_it_did_not_produce(lines: list[str], message: str) -> None:
    """This parser's whole job is to be the thing that cannot silently misread the artefact a human
    approved."""
    with pytest.raises(RouteError, match=message.replace("`", "`")):
        rpz.parse_diff(lines)


TOML = (
    "[thresholds]                         # the learnable numbers.\n"
    "garble_escalate = 0.50\n"
    "ink_coverage_min = 0.25              # marker layout_coverage_threshold (line.py:35-39)\n"
    "blank_page_tiles = 4\n"
)
"""The shipped block's shape: aligned, with the marker comments that say where each number came
from. Both of those survive a promote, which is why this is a rewriter and not `git apply`."""


def test_applying_a_change_keeps_the_marker_comment_and_the_alignment() -> None:
    """The provenance of a number is the reason the block is reviewable, and a patch that replaced
    the `-` line with the `+` line would delete it on every threshold it touched."""
    patch = rpz.Patch(path="p.toml", changes=(rpz.Change("ink_coverage_min", 0.25, 0.02),))
    after = rpz.apply_patch(TOML, patch)
    assert "ink_coverage_min = 0.02              # marker layout_coverage_threshold" in after
    assert "garble_escalate = 0.50" in after
    assert after.count("\n") == TOML.count("\n")


def test_the_new_value_keeps_the_shape_the_file_used() -> None:
    """`0.25` -> `0.10`, not `0.1`; and `4` -> `6`, not `6.0`. A promote that reformatted the one
    line it touched would read as a formatting change on top of a value change."""
    after = rpz.apply_patch(
        TOML,
        rpz.Patch(
            path="p.toml",
            changes=(
                rpz.Change("ink_coverage_min", 0.25, 0.1),
                rpz.Change("blank_page_tiles", 4, 6),
            ),
        ),
    )
    assert "ink_coverage_min = 0.10 " in after
    assert "blank_page_tiles = 6\n" in after


def test_a_file_that_moved_since_the_review_is_refused() -> None:
    """*"applies a REVIEWED diff"* (05:2996). A `-` value that is not what the file holds means
    somebody edited the threshold between the propose and the promote."""
    patch = rpz.Patch(path="p.toml", changes=(rpz.Change("ink_coverage_min", 0.30, 0.02),))
    with pytest.raises(RouteError, match="moved between the propose and the promote"):
        rpz.apply_patch(TOML, patch)


def test_a_threshold_the_file_does_not_declare_is_refused() -> None:
    """`ow route propose` proposes a move and never introduces a threshold."""
    patch = rpz.Patch(path="p.toml", changes=(rpz.Change("nope", 0.1, 0.2),))
    with pytest.raises(RouteError, match="declares no nope"):
        rpz.apply_patch(TOML, patch)


def test_a_threshold_declared_twice_is_refused() -> None:
    doubled = TOML + "ink_coverage_min = 0.25\n"
    patch = rpz.Patch(path="p.toml", changes=(rpz.Change("ink_coverage_min", 0.25, 0.02),))
    with pytest.raises(RouteError, match="declared twice"):
        rpz.apply_patch(doubled, patch)


def test_a_patch_with_no_change_returns_the_text_unchanged() -> None:
    assert rpz.apply_patch(TOML, rpz.Patch(path="p.toml")) == TOML


def test_route_promote_is_the_human_only_action_ten_interfaces_names() -> None:
    """10-interfaces.md:143. `HUMAN_ONLY` means `mcp_name is None` and an empty `listed_in` (rule 4
    at 10:188); the registry that enforces that is P7's, and this is the name it points at."""
    assert rpz.HUMAN_ONLY_ACTION == "route.promote"
