"""The P3 freeze, made checkable: an INDEX of the seven frozen surfaces, plus the pins nobody wrote.

16-roadmap.md:492-499 carries a heading and one paragraph that between them freeze seven named
surfaces at the end of week 22. `test_p2_freeze.py` is the worked example and this file follows it
deliberately rather than inventing a second shape -- an index whose two instances disagreed about
what an index is would be worse than neither.

What is frozen here is the **third-party contract**, and that is what makes it different from P2's.
P2 froze the store: a widened surface there re-mints cites in a corpus we hold. P3 freezes the five
Port protocols, `DriverIO`, the `omniweave-driver/1` framing, the `driver.toml` grammar, the twelve
suite names, `Isolation` and `FailureClass` -- every one of which a **driver we will never see** is
compiled against. 04-driver-system.md:387 states the obligation for one of them in as many words:
"`DriverIO` is frozen and **not extensible**; adding a field amends the charter." A field added to
`DriverIO` in P6 does not corrupt anything we own; it silently breaks every third-party driver
built against P3's, on their machine, with our name on the error.

## What this file is, and the mistake it deliberately does not make

It is an index and two missing pins, NOT seven new tests. `test_ports_types.py` already pins
`DriverIO`'s four fields, `Isolation`'s three members and `FailureClass`'s thirteen;
`test_host_wire.py` pins the framing down to the byte order of the length prefix; `test_card.py`
pins the unknown-key rules in both directions. Re-asserting any of that here would give one fact a
second home, which is what INV-21 forbids, and the copy would drift -- the surface would then be
pinned twice and frozen nowhere, because two disagreeing homes name no value.

So `FROZEN_SURFACES` below names, for each surface, the plan clause that freezes it and the tests
that pin it. An index has a failure mode a direct assertion does not: a row pointing at a renamed
or deleted test silently exempts a frozen surface and still reads as coverage. Section 2 is the
answer -- every named test must be a module-level `def test_*` in the file the row names, must
carry no `skip` or `xfail` decorator, must import and resolve to a callable, and its own source
must mention the surface's own identifier without that token matching half the module.

## Three differences from `test_p2_freeze.py`, each forced by the subject

1. **The pins span three distributions.** P2's surfaces were all `omniweave-core`'s, so a row was
   `module` plus `test` and `UNIT_DIR` resolved it. Four of P3's seven live in `omniweave-ports`
   and one in `omniweave-conform`, so a `Pin` carries its distribution and this module puts those
   directories on `sys.path` itself. Without that, this file passes under a full `pytest -q` --
   where pytest has already inserted every test directory -- and errors when run alone, which is
   the worst of both: green where it is cheap to run and red where it is being debugged.

2. **A decorator counts as the test's body.** P2's `_pin_body` dropped the docstring, because
   prose is not an assertion, and kept everything else. It did not consider the decorator list,
   and P3's two enum surfaces are pinned by a single `@pytest.mark.parametrize` whose table IS the
   assertion's data: `Isolation` and `FailureClass` appear nowhere in
   `test_enum_membership_is_the_charters`'s body, which reads `assert [member.value for member in
   enum_cls] == values`. A parametrise table is data and a docstring is prose, so the table counts
   and the docstring does not. The `skip`/`xfail` check in section 2 is what keeps that from
   admitting a token that appears only in a condition that can be false.

3. **A clause may begin at the end of a line.** P2 asserted `clause[:20] in lines[line - 1]`, which
   works while every clause starts at a line's beginning. Two of P3's seven do not -- the
   `driver.toml` clause begins with the last word of :494 and `FailureClass`'s with the last two of
   :498 -- so this file maps each character of the joined paragraph back to the line it came from
   and asserts the clause's FIRST character lands on the cited line. Stricter and correct on a
   wrapped clause, where the substring form would have failed a citation that was right.

## Seven, not eight, and the count is pinned rather than parsed

The freeze paragraph is seven sentences and this file says seven. An "eight" reading exists only by
splitting one of the paragraph's `X and Y` conjunctions and not the others -- the twelve suite
names from the `[quality.suites]` sub-table, say -- and applied evenly that rule gives nine,
because the `driver.toml` clause's own "hard errors ... and which are ignored" is the same
conjunction. There is no reading on which the paragraph is eight. So the count is asserted as a
literal with its citation, and `test_the_seven_clauses_are_the_plan_paragraph_whole` re-reads the
paragraph and asserts the seven clauses joined ARE it, verbatim and in order.

## What this file adds as assertions, and why only these two

* **The twelve suite names, as a VALUE.** `omniweave_core.drivers.card.QUALITY_SUITES` declares
  them and three tests assert AGREEMENT with it -- `SUITES is QUALITY_SUITES`,
  `tuple(SUITE_RUNNERS) == SUITES`, `len(card.quality.suites) == 12` -- which is exactly the shape
  `test_p2_freeze.py` found behind `SCHEMA = 1`: renaming `idempotence` to `idempotency` in
  `card.py` keeps every one of them green, because each compares the declaration against something
  derived from it. The new pin is in `test_card.py`, beside the loader that owns the tuple, and it
  is a literal list plus a plan-parity read of 04-driver-system.md section 8.2's own table.

* **`CompileV1`, the fifth Port protocol.** It is frozen at the end of P3 and it does not exist:
  04-driver-system.md:379 puts it in `omniweave_core.out.compile` rather than in
  `omniweave_ports`, and `omniweave_core.out` arrives at P5. `test_compile_v1_is_not_here` pins the
  absence; nothing pins the SHAPE the absence is holding a place for. Section 4 records it now,
  because the cheapest moment to snapshot a surface is the moment it is frozen, and it is written
  so that it gets STRONGER when P5 lands rather than needing to be rewritten then.

## The adversarial pass, and the four things it changed

Eleven defects of exactly the shapes this file exists to catch were introduced into the subject
one at a time and the suite was run against each. Ten were caught as written. The findings:

* **Three tokens were not discriminating.** `("'HELLO_ACK'", "'SHUTDOWN'")` also matched the
  direction-partition test, `("'little'",)` also matched a header-cap test that happens to build a
  length prefix on its way elsewhere, and `("degradations",)` matched three -- including the test
  about the one set whose unknown members are KEPT, which is the opposite claim to the one the row
  makes. Each row could have been repointed at its neighbour and stayed green. All three are
  sharpened, and `MAX_TESTS_SHARING_A_MENTION_SET` is 1 rather than 3 because that is what forced
  them to be found.
* **The bound itself was unpinned.** Widening it back to three was the one mutation that changed
  nothing, because no row presses on it today -- which is precisely how a slack bound gets relaxed
  for free and the next loose token lands under it.
  `test_the_discrimination_bound_is_the_literal_one` closes that.

The nine that were caught unchanged are worth listing, because a list of what an index CAN see is
the only honest summary of one: a renamed pinned test, a pinned test gutted to `assert X is not
None` with its docstring left intact, a suite renamed in the loader, a field added to `DriverIO`,
a `skipif` added to a pinned test, `FROZEN_SURFACE_COUNT` rebound to `len(FROZEN_SURFACES)`, a
clause paraphrased, a clause's citation moved by one line, and a pin row dropped from the table.

## This file is NOT a gate row, and adding one would be a defect

The plan names no G-number for the freeze. `tools/gates.toml` transcribes lists the plan owns
(11-repo-layout.md section 6.4), so inventing a row for a property the plan gates nowhere would be
inventing a claim rather than transcribing one. This is ordinary coverage of an ordinary claim; it
runs in the normal suite, in the `test` job, and needs no register entry. Do not add one.

## The obligation paragraph P2 has and P3 does not

16-roadmap.md:433-438 follows P2's freeze with "**This freeze carries a forward-compatibility
obligation nothing else in the plan does.**" P3's freeze has no such paragraph -- :500 is blank and
:501 is `#### The demo`. That absence is asserted rather than assumed, because a reader of this
file who went looking for P3's version and found none has no way to tell "there is none" from "I
missed it", and because a later erratum adding one should fail here and be read.

Specified in 16-roadmap.md section 6 (the "Frozen at the end of P3" paragraph, :492-499), with
04-driver-system.md sections 1.4, 1.5, 2, 6.2 and 8.2, 09-generation.md section 2 and
01-principles.md INV-6 as the documents the individual clauses delegate to.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path
from typing import Final, NamedTuple

import pytest

REPO: Final = Path(__file__).resolve().parents[4]
PACKAGES: Final = REPO / "packages"


def _unit_dir(distribution: str) -> Path:
    return PACKAGES / distribution / "tests" / "unit"


PINNED_DISTRIBUTIONS: Final[tuple[str, ...]] = (
    "omniweave-conform",
    "omniweave-core",
    "omniweave-ports",
)
"""The three distributions whose test trees this index reaches into, sorted.

P3's freeze is the third-party contract and the contract is not one distribution's: the Port
protocols and the three value types are `omniweave-ports`', the framing and the card grammar are
`omniweave-core`'s, and the twelve suite names are pinned from `omniweave-conform` as well as from
the loader that owns them. A row naming a fourth is either a surface that moved or a typo, and
`test_the_three_distributions_are_the_three` is which."""

for _distribution in PINNED_DISTRIBUTIONS:
    # Put the other two trees on `sys.path` here rather than relying on pytest having collected
    # them. Under a full `pytest -q` it already has; running this file alone it has not, and a
    # test that is green in bulk and errors in isolation is worst exactly when it is being read.
    _path = str(_unit_dir(_distribution))
    if _path not in sys.path:
        sys.path.append(_path)

FREEZE_DOCUMENT: Final = "16-roadmap.md"
FREEZE_HEADING: Final = "#### Frozen at the end of P3 (week 22)"
FREEZE_HEADING_LINE: Final = 492
FREEZE_FIRST_LINE: Final = 494
FREEZE_LAST_LINE: Final = 499

FROZEN_SURFACE_COUNT: Final = 7
"""Seven sentences at 16-roadmap.md:494-499. See the module docstring on why it is not eight.

It is a literal on purpose and `test_the_count_of_seven_is_a_literal_in_this_files_own_source` is
what keeps it one. A `len(FROZEN_SURFACES)` here would be an assertion whose two sides are the
same object, and the plan-text backstop below skips on a checkout without `_plan/` -- which is
every clean clone, because `_plan/` is `.gitignore`d.
"""

MAX_TESTS_SHARING_A_MENTION_SET: Final = 1
"""How many of a module's tests a row's `mentions` may match. THIS FILE'S CALL, not a plan claim.

**One, where `test_p2_freeze.py` had to settle for three.** That file's own note says why it could
not go lower -- "Lowering it to one would be the better rule and it is not reachable without
splitting tests that have no reason to split" -- and here it was reachable, so it is taken. Every
one of the twenty rows below names a token set matched by exactly one test in its module, and
three of them had to be sharpened to get there:

* `("'HELLO_ACK'", "'SHUTDOWN'")` also matched
  `test_the_two_directions_partition_the_eleven_kinds_five_and_six`, which asserts the direction
  split rather than the vocabulary. The token is now `("'SHUTDOWN', 10)")`, a pair from the
  numbered literal, which only the vocabulary test carries.
* `("'little'",)` also matched the header-cap encode test, which happens to build a length prefix
  on its way to asserting something else entirely.
* `("degradations",)` matched three, including
  `test_an_unknown_member_of_forfeits_is_kept_where_every_other_set_drops_one` -- a test about the
  one set whose unknown members are KEPT, which is the opposite claim.

The bound being one is what forced each of those to be found. It also means the failure message
for a rotted row names exactly one candidate, which is the difference between "this row could be
repointed" and "this row now points somewhere else"."""


class Pin(NamedTuple):
    """One test that pins one frozen surface, plus a token its own source must carry.

    `mentions` is what keeps a row from pointing at a test that merely exists, and two properties
    make that work: the token must appear in the named test's body or its decorators, docstring
    stripped, and the token set must be DISCRIMINATING -- it may match at most
    `MAX_TESTS_SHARING_A_MENTION_SET` of that module's tests.

    Tokens are written as `ast.unparse` renders them, which is why a string literal inside a
    `parametrize` table appears here in single quotes whatever the source file used. That is a
    real cost of matching against the AST rather than the text, and it is paid on purpose: a token
    found in a comment would otherwise count, and a comment is neither a definition site nor an
    assertion.
    """

    distribution: str
    module: str
    test: str
    mentions: tuple[str, ...]


class FrozenSurface(NamedTuple):
    """One of the seven surfaces 16-roadmap.md:494-499 freezes.

    `clause` is the plan's own sentence, verbatim, and `line` is the line its first character
    falls on. Both are re-read out of `_plan/` below, so this table cannot paraphrase the plan and
    stay green.
    """

    name: str
    clause: str
    line: int
    pins: tuple[Pin, ...]


FROZEN_SURFACES: Final[tuple[FrozenSurface, ...]] = (
    FrozenSurface(
        name="the five Port protocols at major 1",
        clause="The five Port protocols at major 1.",
        line=494,
        pins=(
            Pin(
                distribution="omniweave-ports",
                module="test_ports_protocols",
                test="test_each_port_declares_its_port_string",
                mentions=("proto.PORT", "SCHEMA_VERSION"),
            ),
            Pin(
                distribution="omniweave-ports",
                module="test_ports_protocols",
                test="test_a_port_protocol_has_exactly_its_printed_members",
                mentions=("declared == set(members)",),
            ),
            Pin(
                distribution="omniweave-ports",
                module="test_ports_types",
                test="test_compile_v1_is_not_here",
                mentions=("CompileV1",),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_p3_freeze",
                test="test_the_fifth_protocols_shape_is_recorded_at_the_moment_it_is_frozen",
                mentions=("COMPILE_V1_METHODS", "COMPILE_V1_PORT"),
            ),
        ),
    ),
    FrozenSurface(
        name="DriverIO's field set",
        clause="`DriverIO`'s field set.",
        line=494,
        pins=(
            Pin(
                distribution="omniweave-ports",
                module="test_ports_types",
                test="test_driver_io_has_exactly_four_fields",
                mentions=("'max_output_bytes'",),
            ),
            Pin(
                distribution="omniweave-ports",
                module="test_ports_types",
                test="test_driver_io_carries_no_store_cache_ledger_or_writable_root",
                mentions=("'output_root'", "'cache_root'"),
            ),
        ),
    ),
    FrozenSurface(
        name="the omniweave-driver/1 framing",
        clause="The `omniweave-driver/1` framing.",
        line=494,
        pins=(
            Pin(
                distribution="omniweave-core",
                module="test_host_wire",
                test="test_the_kind_vocabulary_is_pinned_as_a_literal_in_the_plans_own_order",
                mentions=("('SHUTDOWN', 10)", "('FATAL', 11)"),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_host_wire",
                test="test_the_three_caps_are_pinned_as_literals_as_well_as_derived",
                mentions=("1048576", "262144"),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_host_wire",
                test="test_the_prefix_is_two_little_endian_u32_lengths_in_that_order",
                mentions=("16 .to_bytes(4, 'little')",),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_host_wire",
                test="test_the_protocol_name_is_the_one_the_plan_prints",
                mentions=("PROTOCOL",),
            ),
        ),
    ),
    FrozenSurface(
        name="the driver.toml grammar and its two unknown-key rules",
        clause=(
            "The `driver.toml` grammar, including which unknown keys are hard errors (any "
            "top-level table) and which are ignored with a recorded degradation (a key inside "
            "`[capability.<port>]`, because every such key is an ordered or set-valued floor and "
            "an unrecognised one can only make a driver look less capable)."
        ),
        line=494,
        pins=(
            Pin(
                distribution="omniweave-core",
                module="test_card",
                test="test_an_unknown_top_level_table_or_key_is_a_hard_error",
                mentions=("'top level'", "'telemetry'"),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_card",
                test="test_an_unknown_key_in_capability_parse_is_ignored_with_a_recorded_degradation",
                mentions=("CARD_CAPABILITY_UNKNOWN", "'[capability.parse]'"),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_card",
                test="test_an_unknown_key_in_a_port_sibling_is_a_hard_error",
                mentions=("'[embed]'", "'quantisation'"),
            ),
        ),
    ),
    FrozenSurface(
        name="the twelve suite names and the [quality.suites] sub-table",
        clause="The twelve suite names and the `[quality.suites]` sub-table.",
        line=498,
        pins=(
            Pin(
                distribution="omniweave-core",
                module="test_card",
                test="test_the_twelve_suite_names_are_a_value_and_not_an_agreement",
                mentions=("QUALITY_SUITES == TWELVE_SUITES",),
            ),
            Pin(
                distribution="omniweave-conform",
                module="test_conform_kit",
                test="test_the_verdict_vocabulary_is_the_cards_and_not_a_second_one",
                mentions=("SUITES is QUALITY_SUITES",),
            ),
            Pin(
                distribution="omniweave-conform",
                module="test_conform_suites",
                test="test_there_is_an_implementation_for_exactly_the_twelve_suites_the_card_names",
                mentions=("SUITE_RUNNERS", "SUITES"),
            ),
        ),
    ),
    FrozenSurface(
        name="Isolation's members",
        clause="`Isolation`'s members.",
        line=498,
        pins=(
            Pin(
                distribution="omniweave-ports",
                module="test_ports_types",
                test="test_enum_membership_is_the_charters",
                mentions=("(Isolation, ['inproc', 'subproc', 'wasm'])",),
            ),
        ),
    ),
    FrozenSurface(
        name="FailureClass's thirteen members",
        clause="`FailureClass`'s thirteen members.",
        line=498,
        pins=(
            Pin(
                distribution="omniweave-ports",
                module="test_ports_types",
                test="test_enum_membership_is_the_charters",
                mentions=("'driver_crashed'", "'driver_bug'"),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_errors",
                test="test_the_fatality_table_covers_every_failure_class",
                mentions=("_failure_class_values", "FAILURE_CLASS_IS_FATAL"),
            ),
            Pin(
                distribution="omniweave-core",
                module="test_host_subproc",
                test="test_a_result_carrying_a_failure_class_outside_the_closed_set_is_a_protocol_error",
                mentions=("thirteen FailureClass",),
            ),
        ),
    ),
)

ALL_PINS: Final = tuple(pin for surface in FROZEN_SURFACES for pin in surface.pins)
PIN_IDS: Final = tuple(
    f"{pin.module}::{pin.test}::{re.sub(r'[^0-9A-Za-z]+', '-', pin.mentions[0]).strip('-')}"
    for pin in ALL_PINS
)
"""A parametrise id per row, carrying the row's first token because module::test is not unique.

`test_ports_types::test_enum_membership_is_the_charters` is the pin for `Isolation`'s members AND
for `FailureClass`'s thirteen, which is correct -- one parametrised test asserts both tables -- and
without the token the two rows stringify the same. pytest would disambiguate them itself with an
`id0`/`id1` suffix, so both would run, but the failure message would name neither surface."""

PIN_COUNT: Final = 20
"""The rows in the table above, counted once as a literal, because `ALL_PINS` is a derivation.

A parametrised test over a collection nobody sized proves whatever the collection happens to hold,
and a shrunken one reads as a greener suite. `test_p2_freeze.py` records the exact edit that found
this: adding one filter to the comprehension dropped four pins out of the audit, took the run from
81 tests to 66, and passed."""


# ---------------------------------------------------------------------------------------------
# 1. The audit: the table is the paragraph, and the paragraph is seven sentences
# ---------------------------------------------------------------------------------------------


def _paragraph_with_provenance(plan: object) -> tuple[str, tuple[int, ...]]:
    """The freeze paragraph joined, plus the plan line each of its characters came from.

    The provenance half is what lets a citation be checked for a clause that begins at the END of
    a line. Two of P3's seven do, so `test_p2_freeze.py`'s `clause[:20] in lines[line - 1]` would
    fail a row whose citation is correct. The joining space is attributed to the line it precedes,
    so a clause that starts immediately after a line break cites the line its first WORD is on.
    """
    lines = plan.lines(FREEZE_DOCUMENT)  # type: ignore[attr-defined]
    found = [n for n, line in enumerate(lines, start=1) if line.strip() == FREEZE_HEADING]
    assert found == [FREEZE_HEADING_LINE], (
        f"{FREEZE_HEADING!r} is at {found} and this module cites line {FREEZE_HEADING_LINE}; "
        f"re-cite it rather than widening the search"
    )
    pieces: list[str] = []
    owner: list[int] = []
    for number in range(FREEZE_FIRST_LINE, FREEZE_LAST_LINE + 1):
        stripped = lines[number - 1].strip()
        if pieces:
            pieces.append(" ")
            owner.append(number)
        pieces.append(stripped)
        owner.extend([number] * len(stripped))
    return "".join(pieces), tuple(owner)


def _freeze_paragraph(plan: object) -> str:
    return _paragraph_with_provenance(plan)[0]


def test_every_one_of_the_seven_frozen_surfaces_has_a_row() -> None:
    """The count is 16-roadmap.md:494-499's, pinned as a literal with its citation.

    If the plan froze eight things and this table held seven, this fails; the plan-text join below
    is what makes that hold against the plan's own words rather than against this sentence.
    """
    assert len(FROZEN_SURFACES) == FROZEN_SURFACE_COUNT
    names = [surface.name for surface in FROZEN_SURFACES]
    assert len(set(names)) == FROZEN_SURFACE_COUNT, f"a surface is named twice: {names}"
    assert all(surface.pins for surface in FROZEN_SURFACES), "a surface with no pin is unfrozen"


def _sole_binding(source: str, filename: str, name: str) -> ast.AST:
    """The ONE statement in `source` that binds `name`, or an assertion naming the others.

    Every binding form is counted and not just the annotated one at module scope, which is the
    hole `test_p2_freeze.py` records: annotating the golden as a literal and then adding a plain
    `NAME = <derivation>` further down satisfies a check that only looks for `AnnAssign`, and the
    later binding is what the tests then read.
    """
    tree = ast.parse(source, filename=filename)
    bindings: list[ast.AST] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign | ast.NamedExpr):
            targets = [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            bindings.append(node)
    assert len(bindings) == 1, (
        f"{name} is bound {len(bindings)} times in {filename} (lines "
        f"{[getattr(node, 'lineno', '?') for node in bindings]}); it is a golden, and a golden "
        f"rebound anywhere is whatever the last binding made it"
    )
    binding = bindings[0]
    assert isinstance(binding, ast.AnnAssign), f"{name} is declared with its type annotation"
    assert binding.value is not None
    return binding.value


def test_the_count_of_seven_is_a_literal_in_this_files_own_source() -> None:
    """`FROZEN_SURFACE_COUNT` is an integer literal, assigned once, and never a derivation.

    `len(FROZEN_SURFACES) == FROZEN_SURFACE_COUNT` is an assertion about a value only while the
    right-hand side is written down. Rebinding the constant to `len(FROZEN_SURFACES)` -- the shape
    a reader reaches for when adding an eighth row makes the literal fail -- turns it into a
    tautology while the test above stays green. The plan-text join is the real backstop and it is
    not enough on its own: `plan.require()` SKIPS on a checkout without `_plan/`, which is every
    clean clone, so in the environment that gates a release the literal is all that is left.
    """
    value = _sole_binding(
        Path(__file__).read_text(encoding="utf-8"), __file__, "FROZEN_SURFACE_COUNT"
    )
    assert isinstance(value, ast.Constant) and value.value == 7, (
        "FROZEN_SURFACE_COUNT is an integer literal and not an expression over FROZEN_SURFACES; "
        "a derived count pins agreement and not value, and the plan-text backstop skips without "
        "_plan/. If the plan really froze an eighth surface, write the new number down here."
    )
    assert FROZEN_SURFACE_COUNT == 7


def test_the_audit_runs_over_every_pin_in_the_table_and_over_twenty_of_them() -> None:
    """`ALL_PINS` is what the four parametrised tests below iterate, so its size is a claim.

    Both halves are needed and neither is the other. The set equality says the derivation lost
    nothing; the literal says how many there are, which is the half a filter added to the
    comprehension would otherwise satisfy by shrinking both sides at once. `PIN_IDS` is checked
    alongside because pytest collapses duplicate parameter ids, so two rows that stringify the
    same would be one test wearing two rows' names.
    """
    assert len(ALL_PINS) == PIN_COUNT
    assert set(ALL_PINS) == {pin for surface in FROZEN_SURFACES for pin in surface.pins}
    assert len(PIN_IDS) == PIN_COUNT
    assert len(set(PIN_IDS)) == PIN_COUNT, f"two rows share a parametrise id: {PIN_IDS}"


def test_the_seven_clauses_are_the_plan_paragraph_whole(plan) -> None:
    """The seven `clause` fields, joined, ARE 16-roadmap.md:494-499. Verbatim, in order.

    This is the assertion that makes the count honest without pretending to a sentence parse. It
    fails three ways and each is a real event: an eighth surface frozen by a later erratum leaves
    unmatched text at the end; a clause paraphrased in this file stops matching; and a reordered
    paragraph reorders the join.
    """
    plan.require()
    assert " ".join(surface.clause for surface in FROZEN_SURFACES) == _freeze_paragraph(plan)


def test_every_clause_begins_on_the_plan_line_its_row_cites(plan) -> None:
    """A row's `line` is a citation, and a citation nobody checks is a comment.

    The clause is located by scanning FORWARD from the previous clause's end rather than by
    `str.index` from zero, so a clause that is a prefix of another cannot be found at the wrong
    occurrence -- and so the seven offsets are forced to be in the paragraph's own order.
    """
    plan.require()
    paragraph, owner = _paragraph_with_provenance(plan)
    cursor = 0
    for surface in FROZEN_SURFACES:
        assert FREEZE_FIRST_LINE <= surface.line <= FREEZE_LAST_LINE, surface.name
        offset = paragraph.find(surface.clause, cursor)
        assert offset >= 0, (
            f"{surface.name}: the clause is not in the paragraph at or after {cursor}"
        )
        assert owner[offset] == surface.line, (
            f"{surface.name}: begins on {FREEZE_DOCUMENT}:{owner[offset]} and the row cites "
            f"{surface.line}"
        )
        cursor = offset + len(surface.clause)


def test_this_freeze_carries_no_forward_compatibility_paragraph_and_p2s_does(plan) -> None:
    """The difference this file's docstring rests on, checked rather than remembered.

    P2's freeze is followed by "**This freeze carries a forward-compatibility obligation nothing
    else in the plan does.**" (16-roadmap.md:433). P3's is followed by `#### The demo`. A reader
    who went looking for P3's version and found none cannot otherwise tell "there is none" from
    "I missed it", and an erratum that adds one should fail here and be read rather than land
    unnoticed under a heading nobody re-reads.
    """
    plan.require()
    lines = plan.lines(FREEZE_DOCUMENT)
    assert "forward-compatibility obligation" in lines[432], "P2's obligation line moved off :433"
    after = [line.strip() for line in lines[FREEZE_LAST_LINE : FREEZE_LAST_LINE + 3]]
    assert after[0] == ""
    assert after[1].startswith("#### "), f"P3's freeze is now followed by {after[1]!r}"
    assert "obligation" not in " ".join(after)


# ---------------------------------------------------------------------------------------------
# 2. Non-vacuity: every row names a test that exists, is collected, and is about the surface
# ---------------------------------------------------------------------------------------------


def _module_functions(pin: Pin) -> dict[str, ast.FunctionDef]:
    """Every module-level `def` in the pin's module, by name, parsed rather than imported.

    `ast` and not `import` for the structural half, because what has to be proved is that pytest
    will COLLECT the function: collection is a module-level `def test_*`, and a name bound at
    module level by any other means -- a nested def hoisted by a helper, an assignment, a
    decorator that returns something other than a function -- satisfies `getattr` while being
    collected as nothing.
    """
    path = _unit_dir(pin.distribution) / f"{pin.module}.py"
    assert path.is_file(), f"no such test module: {path}"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _pin_body(pin: Pin, test: str) -> str:
    """One test function's decorators and body, unparsed, with a leading docstring dropped.

    The docstring goes because it is prose and a token in prose is not an assertion --
    `test_p2_freeze.py` records the defect that rule closed, where a pinned test gutted to
    `assert Block is not None` with its docstring untouched passed every non-vacuity check.

    The decorators STAY, which is this file's departure and the module docstring argues it: a
    `@pytest.mark.parametrize` table is the assertion's data, not commentary on it. Two of P3's
    seven surfaces are pinned by one parametrised test whose body names neither enum, and pinning
    them by a token from the body would mean pinning them by nothing that distinguishes them.
    """
    node = _module_functions(pin)[test]
    body = node.body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    rendered = [ast.unparse(decorator) for decorator in node.decorator_list]
    rendered.extend(ast.unparse(statement) for statement in body)
    return "\n".join(rendered)


@pytest.mark.parametrize("pin", ALL_PINS, ids=PIN_IDS)
def test_every_pin_names_a_test_that_exists_and_is_collected(pin: Pin) -> None:
    """The index's own failure mode, closed.

    A row pointing at a deleted or renamed test would silently exempt a frozen surface while still
    reading as coverage -- the failure an index has and a direct assertion does not. Three things
    are checked and each is a way a pin rots: the file is gone, the function is gone, and the
    function is there but no longer collected or no longer runs.

    The `skip`/`xfail` clause carries extra weight here because `_pin_body` now counts decorators:
    without it, a token appearing only inside a `skipif` condition would satisfy the mentions
    check while the test it names never ran on the machine that matters.
    """
    functions = _module_functions(pin)
    assert pin.test in functions, (
        f"{pin.distribution}/{pin.module}.py declares no module-level `{pin.test}`. A frozen "
        f"surface is now pinned by nothing -- find where the assertion moved and update the row, "
        f"or restore the test."
    )
    node = functions[pin.test]
    assert node.name.startswith("test_"), f"{pin.test} is not a name pytest collects"
    for decorator in node.decorator_list:
        rendered = ast.unparse(decorator)
        assert "skip" not in rendered and "xfail" not in rendered, (
            f"{pin.module}::{pin.test} carries `{rendered}`; a conditionally skipped test is not "
            f"a pin, because the condition can be false on the machine that matters"
        )


@pytest.mark.parametrize("pin", ALL_PINS, ids=PIN_IDS)
def test_every_pin_resolves_to_a_callable_at_runtime(pin: Pin) -> None:
    """The import half. `ast` proves the shape; this proves the module actually loads.

    A test module that raises at import time is reported as a collection error and asserts
    nothing, and the parse above cannot see that. The import is free for every module the session
    has already collected, which is all of them under a full run, and works in isolation because
    of the `sys.path` block at the top of this file.
    """
    module = importlib.import_module(pin.module)
    function = getattr(module, pin.test, None)
    assert callable(function), f"{pin.module}.{pin.test} is not callable"


@pytest.mark.parametrize("pin", ALL_PINS, ids=PIN_IDS)
def test_every_pin_is_about_the_surface_its_row_claims(pin: Pin) -> None:
    """A test can be renamed into a row's slot by accident; it cannot also be ABOUT the surface.

    `ast.unparse` is used rather than the raw source text so that a token appearing only in a
    comment does not count -- a comment is not a definition site and it is not an assertion. What
    is left is still a grep and it still cannot tell an assertion from a mention of one, which is
    what the next test is for.
    """
    source = _pin_body(pin, pin.test)
    for token in pin.mentions:
        assert token in source, (
            f"{pin.module}::{pin.test} never mentions `{token}` in its body or decorators, so it "
            f"is not the pin its row in FROZEN_SURFACES claims it is"
        )


@pytest.mark.parametrize("pin", ALL_PINS, ids=PIN_IDS)
def test_every_pins_mention_set_narrows_its_module_to_a_handful(pin: Pin) -> None:
    """A row's tokens must NARROW its module. Otherwise the check above is a formality.

    `test_p2_freeze.py` is where this rule was learned: `("Block",)` matched eighteen of its
    module's forty-seven tests, so a row could be repointed at a test with nothing to say about
    the frozen surface and every non-vacuity check passed. The named test must of course be among
    the matches, which is the check above restated over the same corpus -- cheap, and it means a
    mis-set bound cannot pass by matching a neighbourhood the pin is not in.
    """
    functions = _module_functions(pin)
    matched = sorted(
        name
        for name in functions
        if name.startswith("test_") and all(token in _pin_body(pin, name) for token in pin.mentions)
    )
    assert pin.test in matched
    assert len(matched) <= MAX_TESTS_SHARING_A_MENTION_SET, (
        f"{pin.module}::{pin.test}'s tokens {pin.mentions} match {len(matched)} of that module's "
        f"tests ({matched}), so the row could be repointed at any of them and stay green. Narrow "
        f"the tokens to the identifier or the assertion fragment this pin actually turns on."
    )


def test_the_discrimination_bound_is_the_literal_one() -> None:
    """The bound is not binding today, and that is exactly why it has to be written down.

    Every one of the twenty rows names a token set matched by one test, so widening
    `MAX_TESTS_SHARING_A_MENTION_SET` back to `test_p2_freeze.py`'s three changes no outcome in
    this file -- the adversarial pass that built section 2 confirmed it: setting it to 3 left all
    240 tests green. A bound nothing currently presses on is a bound a later edit can relax for
    free, and the relaxation is invisible because nothing fails on the day it happens. The next
    loose token then lands under it and a frozen surface is pinned by a test that is not about it.

    So the widening is made to fail HERE, where the failure message can say what the number is
    for, rather than three rows later where it would say nothing at all. Raising it is a
    deliberate act: change this literal, and say in the same diff which row needed the room.
    """
    value = _sole_binding(
        Path(__file__).read_text(encoding="utf-8"), __file__, "MAX_TESTS_SHARING_A_MENTION_SET"
    )
    assert isinstance(value, ast.Constant) and value.value == 1, (
        "MAX_TESTS_SHARING_A_MENTION_SET is the literal 1. Every row in this file names a token "
        "set matched by exactly one test in its module; if a new row genuinely cannot, raise this "
        "number in the same diff that adds the row and say which row needed the room."
    )
    assert MAX_TESTS_SHARING_A_MENTION_SET == 1


def test_no_surface_is_pinned_only_from_inside_this_file() -> None:
    """This file is an index, and an index that is also a fact's sole home is neither.

    One surface carries an assertion here because the fifth Port protocol has no code to put one
    beside; it also carries three pins in `omniweave-ports`. If that stops being true the surface
    has been moved INTO the index, which is the drift this module exists to prevent.
    """
    for surface in FROZEN_SURFACES:
        elsewhere = [pin for pin in surface.pins if pin.module != "test_p3_freeze"]
        assert elsewhere, f"{surface.name} is pinned only by test_p3_freeze.py"


def test_the_three_distributions_are_the_three() -> None:
    """P3's freeze is the third-party contract, and the contract is not one distribution's.

    A fourth distribution appearing here is either a surface that moved or a typo in a row, and
    both are worth stopping on: this module puts exactly these three test trees on `sys.path`, so
    a row naming a fourth would fail with a missing-file error that says nothing about why.
    """
    assert {pin.distribution for pin in ALL_PINS} == set(PINNED_DISTRIBUTIONS)
    assert list(PINNED_DISTRIBUTIONS) == sorted(PINNED_DISTRIBUTIONS)
    for distribution in PINNED_DISTRIBUTIONS:
        assert _unit_dir(distribution).is_dir(), distribution


# ---------------------------------------------------------------------------------------------
# 3. Gap: `CompileV1`, the fifth Port protocol, frozen at the end of P3 and written at P5
# ---------------------------------------------------------------------------------------------

COMPILE_V1_PORT: Final = "compile/1"
"""09-generation.md:99. The major this clause freezes, for the protocol that does not exist yet."""

COMPILE_V1_METHODS: Final[tuple[str, ...]] = (
    "probe",
    "carrier",
    "rules",
    "measure",
    "lower",
    "postflight",
    "project",
)
"""04-driver-system.md:381-383's seven, in its order. `__init__` is deliberately not among them.

Two plan sites print this protocol and they count it differently, which is why the list is
transcribed from the one that enumerates rather than from the one that sums. 04:381-383 says "Its
seven methods are `probe`, `carrier`, `rules`, `measure`, `lower`, `postflight`, `project` -- there
is no `validate()`", which is these seven. 09-generation.md:93 says "Seven methods. `probe` and
`__init__` are the `DriverBase` shape ...; the other five are OUT's" -- but its own fence at :98-112
prints `carrier`, `rules`, `measure`, `lower`, `postflight` and `project`, which is SIX others and
makes that sentence's arithmetic 2 + 6 = 8. Reported as a plan defect rather than resolved here;
the fence and 04's enumeration agree with each other and only 09's prose disagrees with both.

This file takes 04's reading -- seven, excluding `__init__` -- and
`test_the_seven_methods_are_04_381s_own_enumeration` re-reads that line so the choice is checked
against the plan and not merely stated."""


def test_the_fifth_protocols_shape_is_recorded_at_the_moment_it_is_frozen() -> None:
    """The fifth Port protocol is frozen at the end of P3 and does not exist until P5.

    04-driver-system.md:379 puts `CompileV1` in `omniweave_core.out.compile` rather than in
    `omniweave_ports`, because "its signature mixes ports types with `Plan`, `ILBundle`,
    `AssetLedger`, `RuleSpec` and `CarrierDoc`, and a Protocol has to live in the one distribution
    holding both halves" -- and `omniweave_core.out` arrives at P5 (16-roadmap.md section 8).

    So this clause freezes a surface with no code behind it, and the freeze is still meaningful:
    `Port.COMPILE` exists today, `compile/1` is the string a card will be checked against, and the
    method set is printed in two plan documents. Recording it now is the point of an index written
    at the moment of the freeze rather than at the moment of the implementation.

    The assertion is deliberately in two halves so that it gets STRONGER at P5 instead of needing
    to be rewritten: the absence is asserted while the module is absent, and the member list is
    asserted the day it is not.
    """
    from omniweave_ports import Port  # noqa: PLC0415 -- one test needs the enum

    assert Port.COMPILE.value == "compile"
    assert f"{Port.COMPILE.value}/1" == COMPILE_V1_PORT
    assert len(COMPILE_V1_METHODS) == 7
    assert "validate" not in COMPILE_V1_METHODS, "04-driver-system.md:382: there is no validate()"
    assert "__init__" not in COMPILE_V1_METHODS, COMPILE_V1_METHODS

    try:
        compile_module = importlib.import_module("omniweave_core.out.compile")
    except ImportError:
        # P3's state. `test_ports_types.py::test_compile_v1_is_not_here` pins the other half of
        # this -- that it is not in `omniweave_ports` either -- and that is a pin on this surface.
        import omniweave_ports  # noqa: PLC0415 -- asserting an absence needs the namespace

        assert not hasattr(omniweave_ports, "CompileV1")
        return

    protocol = compile_module.CompileV1
    assert protocol.PORT == COMPILE_V1_PORT
    declared = {
        name
        for name, value in vars(protocol).items()
        if (callable(value) or isinstance(value, classmethod))
        and (not name.startswith("__") or name == "__init__")
    }
    assert declared == {*COMPILE_V1_METHODS, "__init__"}, (
        "CompileV1's member set is frozen at the end of P3 (16-roadmap.md:494) and this is the "
        "list 04-driver-system.md:381-383 and 09-generation.md:98-112 both print"
    )
    assert "validate" not in declared


def test_the_seven_methods_are_04_381s_own_enumeration(plan) -> None:
    """The golden above, re-read out of the plan. A transcription nobody checks is a guess.

    Only 04's enumeration is checked, and the docstring on `COMPILE_V1_METHODS` says why: 09's
    prose count disagrees with 09's own fence, so asserting against it would be asserting against
    a sentence this repository has already reported as wrong.
    """
    plan.require()
    # The sentence lives INSIDE a ```python fence, as a `#` comment that wraps across three
    # lines, so a plain whitespace join leaves a `#` in the middle of the enumeration. Stripping
    # a leading comment marker per line is what makes the fence readable as prose; it mangles
    # markdown headings on the way past and that is harmless here, because the needle is a
    # sentence no heading contains.
    text = " ".join(
        re.sub(r"^\s*#\s?", "", line).strip() for line in plan.lines("04-driver-system.md")
    )
    text = " ".join(text.split())
    printed = "Its seven methods are " + ", ".join(f"`{name}`" for name in COMPILE_V1_METHODS)
    assert printed in text, printed
    assert "there is no `validate()`" in text
