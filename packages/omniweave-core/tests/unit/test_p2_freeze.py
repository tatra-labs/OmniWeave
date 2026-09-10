"""The P2 freeze, made checkable: an INDEX of the frozen surfaces, plus the pins nobody wrote.

16-roadmap.md:426-431 carries a heading and one paragraph that between them freeze eight named
surfaces at the end of week 16, and the paragraph under them (:433-438) says why this freeze is
unlike every other line in the plan: *"This freeze carries a forward-compatibility obligation
nothing else in the plan does."* v0.1 ships a store at `SCHEMA = 1` and v1.0 ships the same
`SCHEMA`; every L3 and runtime table P4 and P8 fill is created empty in P2; the upgrade is
additive DDL plus passes, never a re-parse -- and *"a column that forces a re-parse of an existing
corpus is a defect, not a migration, because it re-mints cites."*

Before this file, nothing in the tree said any of that. The assertions existed, scattered across
six modules; the FREEZE did not. A reader in P5 holding a patch that adds a field to `Block` had
no way to learn that the field set was frozen three phases earlier, and the cheapest moment to
snapshot a surface is the moment it is frozen.

## What this file is, and the mistake it deliberately does not make

It is an index and four missing pins, NOT eight new tests. `test_store_protocols.py` already pins
the four store protocols completely -- 33 methods counted rather than transcribed, names and
signatures read out of the plan's own fences -- and `test_archive_owdoc.py` already pins
`container_version`, `digest_recipe` and `FRAME_TARGET_BLOCKS`. Re-asserting any of that here
would give one fact a second home, which is exactly what INV-21 forbids, and the copy would
drift: the surface would then be pinned twice and frozen nowhere, because two disagreeing homes
name no value.

So `FROZEN_SURFACES` below names, for each surface, the plan clause that freezes it and the tests
that pin it, and `tests/unit/test_core_eager_surface.py`'s `FILLED_HOMES` is the shape being
followed -- including the part that matters most. An index has a failure mode a direct assertion
does not: a row pointing at a test that was renamed or deleted silently exempts a frozen surface
and still reads as coverage. `test_the_filled_homes_are_really_filled` is the answer there and the
three parametrised tests in section 2 are the answer here -- every named test must be a
module-level `def test_*` in the file the row names, must carry no `skip` or `xfail` decorator,
must import and resolve to a callable, and its own source must mention the surface's own
identifier. A row cannot go stale quietly; it can only be edited on purpose.

## Eight, not nine, and the count is pinned rather than parsed

The freeze paragraph is eight sentences and this file says eight. A "nine" reading exists only by
splitting one of the paragraph's `X and Y` conjunctions and not the others -- `SCHEMA = 1` from
the system-of-record read contract, say -- and applied evenly that rule gives eleven, because
`container_version` and the `.owdoc` member layout is also two and so is the `cite` grammar and
`doc.next_cite_n` minting. There is no reading on which the paragraph is nine. So the count is
asserted as a literal with its citation, and `test_the_eight_clauses_are_the_plan_paragraph_whole`
re-reads the paragraph and asserts the eight clauses joined ARE it, verbatim and in order --
which catches a ninth surface frozen by a later erratum, and catches a clause paraphrased here,
without either of them depending on a sentence splitter.

## What this file adds as assertions, and why only these four

Four surfaces had no pin worth the name. Each gap assertion is placed in the file where that fact
already lives if it has one, then indexed from here:

* **`SCHEMA = 1`.** Its value is not missing -- `omniweave_core/contract.py:95` declares
  `SCHEMA: int = 1` as ADR-9's sole code home, and `test_contract.py` pins the literal. What was
  missing was the DISK side: `test_store_migrate.py`'s `index_state` test compared the stored
  stamp against `contract.SCHEMA_STRING`, which pins agreement and not value, so a renumbered
  constant stayed green. The new pin is in `test_store_migrate.py`, beside the test whose
  docstring says why it is not the one to change. The read-contract half of the same clause --
  03:2474's fifteen `[SOR]` tables -- had no pin at all, and it is in section 3 below, because it
  has no other home: the DDL tags each statement in a COMMENT, and `store/verify.py` states in as
  many words that scanning only the `[SOR]` set is not implementable from inside the store.
* **`Block`'s field set.** Pinned against the plan's fence and against the DDL in both directions,
  which are relations rather than a list. `test_model_block.py`'s `FROZEN_FIELD_SET` is the new
  golden and its docstring is the argument for it. The wire side is a DIFFERENT list of a
  different length, already pinned in `test_archive_owdoc.py`, and section 4 reconciles the two.
* **the `addr` grammar.** Its three rules are pinned by example in `test_store_doc.py` and its
  parse by `archive/owdoc.py`'s `parent_addr`. The GRAMMAR -- 03:1088-1092's five productions
  and
  the two bounds at 03:1131 -- was nowhere, so it is section 5.
* **the `cite` grammar.** Minting from `doc.next_cite_n` is pinned in `test_store_doc.py` and the
  gap behaviour in `test_model_rebind.py`. The two productions of 03:1141-1142 were nowhere, and
  the shipped `_CITE_GRAMMAR` is looser than they are on purpose; section 6 says in which
  direction and why.

## This file is NOT a gate row, and adding one would be a defect

The plan names no G-number for the freeze. `tools/gates.toml` transcribes lists the plan owns
(11-repo-layout.md section 6.4), so inventing a row for a property the plan gates nowhere would be
inventing a claim rather than transcribing one -- the same error whichever way it is motivated.
This is ordinary test coverage of an ordinary claim the plan makes; it runs in the normal suite,
in the `test` job, and it needs no register entry. Do not add one.

## Seven things in this file could not fail, and the fixes are named where they sit

An adversarial pass broke the subject and watched, and seven of this file's claims stayed green
under a defect of exactly the shape they were written to catch. Each is closed below and each
fix is annotated at its own test rather than here, but the shapes are worth naming together
because five of the six are the same shape: an assertion whose two sides cannot disagree.

* `mentions` was matched against `ast.unparse(node)`, docstring INCLUDED. Replacing a pinned
  test's body with `assert Block is not None` and leaving its docstring alone left all three
  non-vacuity tests green. The token is now matched against the body with the docstring
  stripped -- `_pin_body`.
* `mentions` was not required to be DISCRIMINATING. `("Block",)` was satisfied by eighteen of
  test_model_block.py's tests and `("cite",)` by ten of test_model_rebind.py's, so a row could
  be repointed at an unrelated test and stay green. Every token set now names at most
  `MAX_TESTS_SHARING_A_MENTION_SET` tests in its module, which is what forced the sharper
  tokens the rows now carry.
* `ALL_PINS` was derived and un-counted. Adding `if pin.module != "test_p2_freeze"` to its
  comprehension dropped four pins out of the audit and the run went from 81 tests to 66, all
  green: a parametrised assertion over a collection nobody sized. `PIN_COUNT` sizes it.
* `FROZEN_SURFACE_COUNT` was a literal, and nothing stopped it becoming
  `len(FROZEN_SURFACES)`. It survives as a tautology, and the plan-text backstop
  `plan.require()`s -- `_plan/` is `.gitignore`d, so on a clean clone the four plan-reading
  tests SKIP and the count would then be pinned by nothing at all.
  `test_the_count_of_eight_is_a_literal_in_this_files_own_source` reads this file's own AST.
* `ADDR_GRAMMAR` and `CITE_GRAMMAR` are transcriptions with no parity check, unlike
  `SOR_TABLES`, which has one. Widening the corpus class to `{0,63}` and admitting `dot` as a
  root broke nothing. Section 5 and 6 now each carry a plan-parity test AND an intrinsic
  boundary test, because parity alone skips on a clean clone.
* The `Block`-against-the-wire reconciliation was arithmetic over three lengths and nothing
  else, so the two ROLES were interchangeable: swapping `WIRE_KEYS_WITH_NO_FIELD` with
  `WIRE_KEYS_CARRYING_TWO_FIELDS` cancelled, and naming `addr`, `cite` and `page` -- three
  fields that do travel -- as the three that do not left it green. Worse, the old numbers were
  wrong in both directions: `producer_id` and `parent` never reach the wire, `pd` carries no
  field of its own and `pa` carries a repeat of `addr`, so the true equation is 32 - 5 = 27 and
  not 32 - 3 = 29. The mapping is now READ OFF `archive/owdoc.py` and every term of it is a
  named set asserted against the subject.

* The by-example lists were UNSIZED, so the two grammar tests were `for` loops over whatever
  the tuples happened to hold. Emptying `ADDR_EXAMPLES`, `NOT_ADDRESSES`, `CITE_EXAMPLES` and
  `NOT_CITES` -- the entire by-example content of sections 5 and 6 -- left this file green over
  108 tests. Each list is now sized with the count its own docstring already states.

One more finding is a defect in the tree rather than in this file and is reported rather than
fixed here: `store/doc.py` mints the root address from a FOURTH literal `doc` that
`test_the_root_addr_is_the_literal_doc_in_every_home_that_spells_it` did not read, so its name
was a promise it did not keep. It reads it now, off that module's AST.

Specified in 16-roadmap.md section 5 (the "Frozen at the end of P2" paragraph, :426-438), with
03-document-model.md sections 6.2, 6.3, 13.1 and 15.1, 07-store-and-retrieval.md section 3.1 and
ADR-9 as the documents the individual clauses delegate to.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import re
from collections import Counter
from pathlib import Path
from typing import Final, NamedTuple

import pytest
from conftest import MIGRATIONS_DIR
from omniweave_core.archive import owdoc as owdoc_module
from omniweave_core.archive.owdoc import ROOT_ADDR, WIRE_KEYS, parent_addr
from omniweave_core.limits import MAX_BLOCK_DEPTH
from omniweave_core.model.block import Block
from omniweave_core.store import doc as doc_module
from omniweave_core.store import graph as graph_module
from omniweave_core.store import portable as portable_module
from omniweave_core.store import verify as verify_module
from omniweave_core.store.doc import _MAX_ADDR_CHARS
from omniweave_core.store.migrate import apply_pending
from omniweave_core.store.sqlite import connect

UNIT_DIR: Final = Path(__file__).resolve().parent
"""This directory. Every pinned test lives here, which is what makes a row resolvable by name."""

FREEZE_DOCUMENT: Final = "16-roadmap.md"
FREEZE_HEADING: Final = "#### Frozen at the end of P2 (week 16)"
FREEZE_HEADING_LINE: Final = 426
FREEZE_FIRST_LINE: Final = 428
FREEZE_LAST_LINE: Final = 431

FROZEN_SURFACE_COUNT: Final = 8
"""Eight sentences at 16-roadmap.md:428-431. See the module docstring on why it is not nine.

It is a literal on purpose and `test_the_count_of_eight_is_a_literal_in_this_files_own_source`
is what keeps it one. A `len(FROZEN_SURFACES)` here would be an assertion whose two sides are
the same object, and the plan-text backstop below skips on a checkout without `_plan/`.
"""

MAX_TESTS_SHARING_A_MENTION_SET: Final = 3
"""How many of a module's tests a row's `mentions` may match. THIS FILE'S CALL, not a plan
claim.

The plan says nothing about how an index proves its rows point somewhere. The number is set at
three because three of the rows below legitimately share a token with two siblings that pin the
same surface -- `ADDR_GRAMMAR` and `CITE_GRAMMAR` each appear in three tests of this module,
and all three of each are about that grammar -- while every token that was too loose to be a
pin at all matched four or more: `("addr",)` matched four, `("SCHEMA",)` five,
`("MANIFEST_MEMBER",)` seven, `("frames.json",)` eight, `("PROTOCOLS",)` nine, `("cite",)` ten
and `("Block",)` eighteen. Lowering it to one would be the better rule and it is not reachable
without splitting tests that have no reason to split.
"""

NOW_NS: Final = 1_700_000_000_000_000_000
"""A fixed clock for the one migrated store this module builds. Determinism, not convenience."""


# ---------------------------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------------------------


class Pin(NamedTuple):
    """One test that pins one frozen surface, plus a token its own source must carry.

    `mentions` is what keeps a row from pointing at a test that merely exists. Two properties
    make that work and the original version of this class had only the first: the token must
    appear in the named test's BODY, docstring stripped, and the token set must be
    DISCRIMINATING -- it may match at most `MAX_TESTS_SHARING_A_MENTION_SET` of that module's
    tests. Without the second, `("Block",)` matched eighteen of test_model_block.py's tests and a
    row repointed at any of them stayed green; without the first, gutting a pinned test to
    `assert Block is not None` and leaving its docstring alone stayed green too.

    A token is preferably the identifier the assertion turns on -- `FRAME_TARGET_BLOCKS`,
    `next_cite_n`, `FROZEN_FIELD_SET`. Where that identifier is too common to discriminate, the
    token is a fragment of the assertion itself (`contract.SCHEMA == 1`) or, failing that, a
    helper the test calls. The earlier version of this docstring ruled helper names out because a
    helper can be renamed without the subject moving; that trade is now taken the other way round
    on purpose, because a renamed helper fails LOUDLY and is repaired by editing one row, while a
    token too loose to discriminate fails SILENTLY and leaves a frozen surface pinned by an
    unrelated test. A loud false alarm beats a quiet true negative.
    """

    module: str
    test: str
    mentions: tuple[str, ...]


class FrozenSurface(NamedTuple):
    """One of the eight surfaces 16-roadmap.md:428-431 freezes.

    `clause` is the plan's own sentence, verbatim, and `line` is the line it begins on. Both are
    re-read out of `_plan/` below, so this table cannot paraphrase the plan and stay green.
    """

    name: str
    clause: str
    line: int
    pins: tuple[Pin, ...]


# Clause 5 carries a literal em dash (U+2014) because the plan prints one and the comparison
# below is verbatim. It is NOT one of the characters RUF001/RUF002 treat as confusable, so no
# per-file exemption is needed here -- `ruff check` passes on it as written. Anything replacing
# it with `--`, which is this tree's prose convention elsewhere, breaks the paragraph match.
FROZEN_SURFACES: Final[tuple[FrozenSurface, ...]] = (
    FrozenSurface(
        name="SCHEMA = 1 and the system-of-record read contract",
        clause="`SCHEMA = 1` and the system-of-record read contract.",
        line=428,
        pins=(
            Pin(
                module="test_contract",
                test="test_schema_is_1_and_schema_minor_is_0__03_document_model_md_section_15_1",
                mentions=("contract.SCHEMA == 1", "contract.SCHEMA_MINOR == 0"),
            ),
            Pin(
                module="test_store_migrate",
                test="test_a_migrated_store_reports_schema_major_one_and_that_is_the_frozen_value",
                mentions=("index_state", "major == '1'"),
            ),
            Pin(
                module="test_p2_freeze",
                test="test_the_read_contract_is_03_2474s_own_fifteen_sor_tables",
                mentions=("SOR_TABLES", "DER_OBJECTS"),
            ),
        ),
    ),
    FrozenSurface(
        name="digest_recipe = 1",
        clause="`digest_recipe = 1`.",
        line=428,
        pins=(
            Pin(
                module="test_archive_owdoc",
                test="test_the_release_one_version_stamps_are_the_plans_own_numbers",
                mentions=("DIGEST_RECIPE",),
            ),
        ),
    ),
    FrozenSurface(
        name="container_version and the .owdoc member layout",
        clause="`container_version` and the `.owdoc` member layout.",
        line=428,
        pins=(
            Pin(
                module="test_archive_owdoc",
                test="test_the_release_one_version_stamps_are_the_plans_own_numbers",
                mentions=("CONTAINER_VERSION",),
            ),
            Pin(
                module="test_archive_owdoc",
                test="test_every_member_is_deflated_and_no_member_carries_a_zst_suffix",
                mentions=("ZIP_DEFLATED",),
            ),
            Pin(
                module="test_archive_owdoc",
                test="test_the_manifest_carries_the_seventeen_printed_keys_plus_gen",
                mentions=("MANIFEST_MEMBER", "container_version"),
            ),
        ),
    ),
    FrozenSurface(
        name="Block's field set",
        clause="`Block`'s field set.",
        line=429,
        pins=(
            Pin(
                module="test_model_block",
                test="test_the_frozen_field_set_is_these_thirty_two_names_in_this_order__16_429",
                mentions=("FROZEN_FIELD_SET",),
            ),
            Pin(
                module="test_model_block",
                test="test_block_declares_the_plans_fields_in_the_plans_order",
                mentions=("Block", "_fence_class"),
            ),
            Pin(
                module="test_p2_freeze",
                test="test_the_field_set_and_the_wire_keys_are_two_lists_and_not_one",
                mentions=("WIRE_KEYS",),
            ),
        ),
    ),
    FrozenSurface(
        name="the four store protocols",
        clause=(
            "The four store protocols — `Store` is never widened, and neither is any of the "
            "other three."
        ),
        line=429,
        pins=(
            Pin(
                module="test_store_protocols",
                test="test_the_four_protocols_declare_exactly_thirty_three_methods",
                mentions=("PROTOCOLS", "33"),
            ),
            Pin(
                module="test_store_protocols",
                test="test_the_method_names_are_the_plans_own_in_the_plans_own_order",
                mentions=("PROTOCOLS", "declared == expected"),
            ),
            Pin(
                module="test_store_protocols",
                test="test_every_signature_is_the_plans_printed_signature",
                mentions=("PROTOCOLS", "_shape_from_code"),
            ),
        ),
    ),
    FrozenSurface(
        name="the addr grammar",
        clause="The `addr` grammar.",
        line=430,
        pins=(
            Pin(
                module="test_p2_freeze",
                test="test_the_addr_grammar_is_03_1088s_five_productions",
                mentions=("ADDR_GRAMMAR", "NOT_ADDRESSES"),
            ),
            Pin(
                module="test_p2_freeze",
                test="test_the_addr_is_bounded_by_sixty_four_steps_and_five_hundred_twelve_chars",
                mentions=("MAX_BLOCK_DEPTH",),
            ),
            Pin(
                module="test_store_doc",
                test=(
                    "test_the_addresses_are_section_6_2s_three_rules_"
                    "including_a_cell_across_a_page_break"
                ),
                mentions=("addr", "r0c0"),
            ),
            Pin(
                module="test_archive_owdoc",
                test="test_the_parent_addr_is_derived_from_the_child_addr",
                mentions=("parent_addr",),
            ),
        ),
    ),
    FrozenSurface(
        name="the cite grammar and doc.next_cite_n minting",
        clause="The `cite` grammar and `doc.next_cite_n` minting.",
        line=430,
        pins=(
            Pin(
                module="test_p2_freeze",
                test="test_the_cite_grammar_is_03_1141s_two_productions",
                mentions=("CITE_GRAMMAR", "NOT_CITES"),
            ),
            Pin(
                module="test_store_doc",
                test="test_cite_is_minted_from_doc_next_cite_n_and_the_counter_is_persisted",
                mentions=("next_cite_n",),
            ),
            Pin(
                module="test_model_rebind",
                test="test_the_worked_example_discards_the_staged_cites_of_every_carried_row",
                mentions=("cite", "d7#17"),
            ),
        ),
    ),
    FrozenSurface(
        name="Frame as a block-count-bounded run",
        clause="`Frame` as a block-count-bounded run.",
        line=431,
        pins=(
            Pin(
                module="test_archive_owdoc",
                test="test_the_frame_target_is_eight_thousand_one_hundred_and_ninety_two",
                mentions=("FRAME_TARGET_BLOCKS",),
            ),
            Pin(
                module="test_archive_owdoc",
                test="test_a_multiframe_archive_writes_one_member_per_frame",
                mentions=("frames.json", "blocks/000003.ndjson"),
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

`test_archive_owdoc::test_the_release_one_version_stamps_are_the_plans_own_numbers` is the pin for
`digest_recipe = 1` AND for `container_version`, which is correct -- it asserts both stamps -- and
it means two rows stringify the same without the token. pytest then disambiguates them itself with
an `id0`/`id1` suffix, so both ran, but the failure message named neither surface. The token is the
half that says which claim the row is making.
"""

PIN_COUNT: Final = 22
"""The rows in the table above, counted once as a literal, because `ALL_PINS` is a derivation.

A parametrised test over a collection nobody sized proves whatever the collection happens to
hold, and a shrunken one reads as a greener suite: adding `if pin.module != "test_p2_freeze"` to
`ALL_PINS` above -- a plausible "do not audit ourselves" refactor -- dropped four pins out of the
audit, took the run from 81 tests to 66 and passed. This number is what makes that edit fail.
Adding a pin means editing it, which is a one-line cost paid once per pin and is the point.
"""


# ---------------------------------------------------------------------------------------------
# 1. The audit: the table is the paragraph, and the paragraph is eight sentences
# ---------------------------------------------------------------------------------------------


def _freeze_paragraph(plan) -> str:
    """16-roadmap.md's freeze paragraph, joined into one string with single spaces.

    Located by its HEADING rather than by slicing at the cited line numbers, so a plan edit that
    moves the paragraph fails saying where the heading now is, instead of silently reading four
    unrelated lines and calling them the freeze.
    """
    lines = plan.lines(FREEZE_DOCUMENT)
    found = [n for n, line in enumerate(lines, start=1) if line.strip() == FREEZE_HEADING]
    assert found == [FREEZE_HEADING_LINE], (
        f"{FREEZE_HEADING!r} is at {found} and this module cites line {FREEZE_HEADING_LINE}; "
        f"re-cite it rather than widening the search"
    )
    body = lines[FREEZE_FIRST_LINE - 1 : FREEZE_LAST_LINE]
    return " ".join(line.strip() for line in body)


def test_every_one_of_the_eight_frozen_surfaces_has_a_row() -> None:
    """The count is 16-roadmap.md:428-431's, pinned as a literal with its citation.

    If the plan froze nine things and this table held eight, this fails; the next test is what
    makes that hold against the plan's own text rather than against this sentence.
    """
    assert len(FROZEN_SURFACES) == FROZEN_SURFACE_COUNT
    names = [surface.name for surface in FROZEN_SURFACES]
    assert len(set(names)) == FROZEN_SURFACE_COUNT, f"a surface is named twice: {names}"
    assert all(surface.pins for surface in FROZEN_SURFACES), "a surface with no pin is unfrozen"


def _sole_binding(source: str, filename: str, name: str) -> ast.AST:
    """The ONE statement in `source` that binds `name`, or an assertion naming the others.

    Every binding form is counted and not just the annotated one at module scope, which is the
    hole the first version of this had: annotating the golden as a literal and then adding a plain
    `NAME = <derivation>` line further down satisfied a check that only looked for `AnnAssign`,
    and the module-level rebinding is what the tests then read. `ast.walk` rather than
    `tree.body`, for the same reason one level out -- a `global NAME` inside a function reaches
    the same value.
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


def test_the_count_of_eight_is_a_literal_in_this_files_own_source() -> None:
    """`FROZEN_SURFACE_COUNT` is an integer literal, assigned once, and never a derivation.

    Rule 5's corollary, applied to this module: `len(FROZEN_SURFACES) == FROZEN_SURFACE_COUNT` is
    an assertion about a value only while the right-hand side is written down. Rebinding the
    constant to `len(FROZEN_SURFACES)` -- which is the shape a reader reaches for when adding a
    ninth row makes the literal fail -- turns it into a tautology, and the test above stays green
    while asserting nothing. The plan-text join is the real backstop and it is not enough on its
    own: `plan.require()` SKIPS on a checkout without `_plan/`, which is every clean clone, so in
    the environment that gates a release the literal is the only assertion left standing.

    So this reads the module's own source and insists the golden is spelled out. It is the one
    test here that is about this file rather than about the plan, and that is deliberate: an index
    that cannot vouch for its own count is a comment.
    """
    value = _sole_binding(
        Path(__file__).read_text(encoding="utf-8"), __file__, "FROZEN_SURFACE_COUNT"
    )
    assert isinstance(value, ast.Constant) and value.value == 8, (
        "FROZEN_SURFACE_COUNT is an integer literal and not an expression over FROZEN_SURFACES; "
        "a derived count pins agreement and not value, and the plan-text backstop skips without "
        "_plan/. If the plan really froze a ninth surface, write the new number down here."
    )
    assert FROZEN_SURFACE_COUNT == 8


def test_the_audit_runs_over_every_pin_in_the_table_and_over_twenty_two_of_them() -> None:
    """`ALL_PINS` is what the three parametrised tests below iterate, so its size is a claim.

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


def test_the_eight_clauses_are_the_plan_paragraph_whole(plan) -> None:
    """The eight `clause` fields, joined, ARE 16-roadmap.md:428-431. Verbatim, in order.

    This is the assertion that makes the count honest without pretending to a sentence parse. It
    fails three ways and each is a real event: a ninth surface frozen by a later erratum leaves
    unmatched text at the end; a clause paraphrased in this file stops matching; and a reordered
    paragraph reorders the join.
    """
    plan.require()
    assert " ".join(surface.clause for surface in FROZEN_SURFACES) == _freeze_paragraph(plan)


def test_every_clause_begins_on_the_plan_line_its_row_cites(plan) -> None:
    """A row's `line` is a citation, and a citation nobody checks is a comment."""
    plan.require()
    lines = plan.lines(FREEZE_DOCUMENT)
    for surface in FROZEN_SURFACES:
        assert FREEZE_FIRST_LINE <= surface.line <= FREEZE_LAST_LINE, surface.name
        head = surface.clause[:20]
        assert head in lines[surface.line - 1], (
            f"{surface.name}: the clause does not begin on {FREEZE_DOCUMENT}:{surface.line}"
        )


def test_the_freeze_carries_the_obligation_paragraph_this_file_is_built_around(plan) -> None:
    """16-roadmap.md:433-438. The reason an index is worth having at all, quoted and checked.

    Without this, the module docstring's central claim -- that the re-parse sentence is what makes
    a widened surface a defect rather than a migration -- is prose in a test file citing a line
    nobody re-reads. The second needle spans a line break in the source document, which is why it
    is matched against the joined text rather than against a single line.
    """
    plan.require()
    text = " ".join(plan.text(FREEZE_DOCUMENT).split())
    assert "This freeze carries a forward-compatibility obligation nothing else in the plan" in text
    assert "a column that forces a re-parse of an existing corpus is a defect, not a" in text


# ---------------------------------------------------------------------------------------------
# 2. Non-vacuity: every row names a test that exists, is collected, and is about the surface
# ---------------------------------------------------------------------------------------------


def _module_functions(module: str) -> dict[str, ast.FunctionDef]:
    """Every module-level `def` in `unit/<module>.py`, by name, parsed rather than imported.

    `ast` and not `import` for the structural half, because what has to be proved is that pytest
    will COLLECT the function: collection is a module-level `def test_*`, and a name bound at
    module level by any other means -- a nested def hoisted by a helper, an assignment, a
    decorator that returns something other than a function -- satisfies `getattr` while being
    collected as nothing.
    """
    path = UNIT_DIR / f"{module}.py"
    assert path.is_file(), f"no such test module: {path}"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def _pin_body(module: str, test: str) -> str:
    """One test function's body, unparsed, with a leading docstring dropped.

    The docstring is dropped because it is prose and a token in prose is not an assertion. The
    original version of the mentions check unparsed the whole function, docstring included, and a
    pinned test whose body was replaced by `assert Block is not None` -- docstring untouched --
    passed every non-vacuity test in this section. That is the cheapest way a pin rots and it was
    the one shape this section could not see.
    """
    body = _module_functions(module)[test].body
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(statement) for statement in body)


@pytest.mark.parametrize("pin", ALL_PINS, ids=PIN_IDS)
def test_every_pin_names_a_test_that_exists_and_is_collected(pin: Pin) -> None:
    """The index's own failure mode, closed.

    A row pointing at a deleted or renamed test would silently exempt a frozen surface while
    still reading as coverage -- the failure an index has and a direct assertion does not. Three
    things are checked here and each is a way a pin rots: the file is gone, the function is gone,
    and the function is there but no longer collected or no longer runs.

    The `skip`/`xfail` clause is why no row points at
    `test_archive_owdoc.py::test_unzip_l_lists_the_members_of_the_archive`, which would otherwise
    be the natural pin for the `.owdoc` member layout: it is `skipif`-guarded on `unzip` being on
    PATH, and a pin whose condition can be false on the machine that matters is not a pin. The
    `ZIP_DEFLATED` row covers the same surface unconditionally.
    """
    functions = _module_functions(pin.module)
    assert pin.test in functions, (
        f"{pin.module}.py declares no module-level `{pin.test}`. A frozen surface is now pinned "
        f"by nothing -- find where the assertion moved and update the row, or restore the test."
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
    has already collected, which is all of them under a full run.
    """
    module = importlib.import_module(pin.module)
    function = getattr(module, pin.test, None)
    assert callable(function), f"{pin.module}.{pin.test} is not callable"


@pytest.mark.parametrize("pin", ALL_PINS, ids=PIN_IDS)
def test_every_pin_is_about_the_surface_its_row_claims(pin: Pin) -> None:
    """A test can be renamed into a row's slot by accident; it cannot also be ABOUT the surface.

    `ast.unparse` of the body is used rather than the raw source text so that a token which
    appears only in a comment does not count -- a comment is not a definition site, and it is not
    an assertion either. The DOCSTRING does not count for the same reason, and it used to: see
    `_pin_body`, where that defect is written up. What is left is still a grep and it still cannot
    tell an assertion from a mention of one, which is what the next test is for.
    """
    source = _pin_body(pin.module, pin.test)
    for token in pin.mentions:
        assert token in source, (
            f"{pin.module}::{pin.test} never mentions `{token}` in its body, so it is not the pin "
            f"its row in FROZEN_SURFACES claims it is"
        )


@pytest.mark.parametrize("pin", ALL_PINS, ids=PIN_IDS)
def test_every_pins_mention_set_narrows_its_module_to_a_handful(pin: Pin) -> None:
    """A row's tokens must NARROW its module. Otherwise the check above is a formality.

    This is the finding that made the rest of section 2 worth re-examining. `("Block",)` was
    matched by eighteen of test_model_block.py's forty-seven tests, so the `Block`-field-order row
    could be repointed at `test_blockdraft_is_slotted_even_though_it_is_mutable` -- a test with
    nothing whatever to say about the frozen field set -- and every test in this section passed.
    `("cite",)` matched ten, `("PROTOCOLS",)` nine, `("frames.json",)` eight,
    `("MANIFEST_MEMBER",)` seven, `("SCHEMA",)` five and `("addr",)` four.

    So the bound is what forces a token to be specific, and the rows above now carry a fragment of
    the assertion itself where no identifier was narrow enough. The named test must of course be
    among the matches, which is the check above restated over the same corpus -- cheap, and it
    means a mis-set bound cannot pass by matching a neighbourhood the pin is not in.
    """
    functions = _module_functions(pin.module)
    matched = sorted(
        name
        for name in functions
        if name.startswith("test_")
        and all(token in _pin_body(pin.module, name) for token in pin.mentions)
    )
    assert pin.test in matched
    assert len(matched) <= MAX_TESTS_SHARING_A_MENTION_SET, (
        f"{pin.module}::{pin.test}'s tokens {pin.mentions} match {len(matched)} of that module's "
        f"tests ({matched}), so the row could be repointed at any of them and stay green. Narrow "
        f"the tokens to the identifier or the assertion fragment this pin actually turns on."
    )


def test_no_surface_is_pinned_only_from_inside_this_file() -> None:
    """This file is an index, and an index that is also a fact's sole home is neither.

    Four surfaces carry an assertion here because they carried none anywhere; each of those four
    also has a pin in the module where the surface's other facts live. If that stops being true
    the surface has been moved INTO the index, which is the drift this module exists to prevent.
    """
    for surface in FROZEN_SURFACES:
        elsewhere = [pin for pin in surface.pins if pin.module != "test_p2_freeze"]
        assert elsewhere, f"{surface.name} is pinned only by test_p2_freeze.py"


# ---------------------------------------------------------------------------------------------
# 3. Gap: the system-of-record read contract -- 03:2474's fifteen `[SOR]` tables
# ---------------------------------------------------------------------------------------------

SOR_TABLES: Final[tuple[str, ...]] = (
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
    "part",
    "asset",
    "block_asset",
    "diag",
)
"""03:2474-2476, transcribed. *"At a `SCHEMA` major, these are `[SOR]` -- a public read contract."*

This is the second half of the freeze's first clause and it had no home in the tree. The DDL tags
each statement `[SOR]` or `[DER]` in a COMMENT and `test_migration_0002_0003.py` asserts that
every statement carries one of the two tags -- but a comment is not a definition site, and a tag
being present says nothing about which set a table is in. `omniweave_core.store.verify` holds no
transcription either, and says why in as many words: its single-homedness check scans every table
it finds because *"scanning only the `[SOR]` set is not implementable"* (verify.py:1021).
"""

DER_OBJECTS: Final[tuple[str, ...]] = (
    "grid_slot",
    "block_fts",
    "page_render",
    "ow_block_head",
    "block_sec",
)
"""03:2476-2478's `[DER]` list, minus "L4's indexes", which the plan does not name individually.

*"These are `[DER]` and explicitly outside it, rebuildable by `ow store rebuild <object>`."* They
are here as the NEGATIVE half: a read contract is a boundary, and a boundary asserted only from
the inside is satisfied by a store in which everything is `[SOR]`.
"""


def _objects_in_a_migrated_store(tmp_path: Path) -> dict[str, str]:
    """`{name: type}` for every table and view the four shipped migrations create."""
    connection = connect(tmp_path / "index.owstore")
    try:
        apply_pending(connection, now_ns=NOW_NS, corpus_id="p2-freeze")
        rows = connection.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    finally:
        connection.close()
    return {str(name): str(kind) for name, kind in rows}


def test_the_read_contract_is_03_2474s_own_fifteen_sor_tables(tmp_path: Path) -> None:
    """16-roadmap.md:428 freezes the read contract; 03:2474 is the list, and it is fifteen.

    Asserted against a store the shipped migrations actually built, so an `[SOR]` table the DDL
    never creates fails here rather than at the first customer upgrade. The `[DER]` five are
    asserted present AND outside the contract, because 03:2476 makes that the operational
    difference: a `[DER]` object may be dropped and rebuilt by a migration and an `[SOR]` object
    may not.
    """
    assert len(SOR_TABLES) == 15
    assert len(set(SOR_TABLES)) == 15
    assert not set(SOR_TABLES) & set(DER_OBJECTS), "a name cannot be both [SOR] and [DER]"
    objects = _objects_in_a_migrated_store(tmp_path)
    missing = [name for name in SOR_TABLES if objects.get(name) != "table"]
    assert missing == [], f"the read contract names objects the migrations do not create: {missing}"
    absent = [name for name in DER_OBJECTS if name not in objects]
    assert absent == [], f"03:2476's [DER] objects are not in the store: {absent}"


def test_the_sor_and_der_lists_are_the_plans_own_names(plan) -> None:
    """Read back out of 03:2474-2478, so neither transcription above can drift silently.

    Without this the two tuples are a second home for a list the plan owns. With it they are a
    transcription with a parity check, which is `test_enum_val_parity.py`'s pattern: two
    enforcers, one truth, and the parity is what stops the enforcer becoming a second truth.
    """
    plan.require()
    lines = plan.lines("03-document-model.md")
    start = next(n for n, line in enumerate(lines) if line.startswith("**The read contract.**"))
    paragraph = " ".join(line.strip() for line in lines[start : start + 5])
    sor_half, marker, der_half = paragraph.partition("These are `[DER]`")
    assert marker, "03's read-contract paragraph no longer separates the two sets"
    for name in SOR_TABLES:
        assert f"`{name}`" in sor_half, f"{name} is not in 03:2474-2476's [SOR] sentence"
    for name in DER_OBJECTS:
        assert f"`{name}`" in der_half, f"{name} is not in 03:2476-2478's [DER] sentence"


# ---------------------------------------------------------------------------------------------
# 4. Gap: `Block`'s field set against the wire keys -- two lists, and why
# ---------------------------------------------------------------------------------------------

WIRE_WRITERS: Final = ("block_record", "mark_records")
"""The two functions in `archive/owdoc.py` that build a block's wire record.

`block_record` writes the block members and `mark_records` writes the `m` key, which lives in its
own frame-aligned member (03:659) rather than inline. Between them they are the only place a
`Block` field becomes a wire value, which is what makes the mapping below a derivation off the
subject rather than a fourth transcription of a list the plan already owns twice.
"""

FIELDS_OFF_THE_WIRE: Final = ("doc_ord", "gen", "id", "parent", "producer_id")
"""The five `Block` fields no wire key reads, and every one of them is a store-local identity.

`id` is the `block_id` and 03:645 is explicit that *"there is no `block_id` here"* -- the archive
addresses blocks by `addr`, which is what lets an import mint fresh ids. `parent` is a `block_id`
too: `pa` carries the PARENT'S ADDR, re-derived from this block's own `addr` by `parent_addr`, so
the field's value never travels and an import resolves `pa` to a freshly minted id. `producer_id`
is the same shape one level out -- `pd` holds an INDEX into `manifest.producers[]` and
`archive/owdoc.py:414-416` says so in as many words, *"an INDEX and not a `producer_id`, for the
same reason the archive holds no `block_id`."* `doc_ord` and `gen` are constant across an archive:
it holds one document at one generation and `manifest.json` carries `doc_key` and `gen` once
(03:2486), so a per-block copy would be one fact repeated once per block.

**This list said three names before this wave and the three were wrong twice over.** It omitted
`parent` and `producer_id`, and the test below checked only that the three named were *among*
`Block`'s fields -- so renaming them to `addr`, `cite` and `page`, three fields that plainly do
travel, left it green. The list is now compared as a SET against what the wire writers do not
read.
"""

WIRE_KEYS_WITH_NO_FIELD: Final = ("dc", "pd", "pl")
"""The three keys whose value is not read off any `Block` field.

`dc` is `decision_id` and `pl` is `payload`: the two `block` columns 03:311 keeps OFF `Block` on
purpose. Both are read through a join -- `Doc.payload(id)` and the runtime's `route_decision` --
and neither is on the hot path of a render. They are on the wire because the archive is a lossless
projection of the store and they are columns; they are not fields because materialising a JSON
object per block would put a `json.loads` on every row of a 600k-block scan. `pd` is the
`manifest.producers[]` index, explained in `FIELDS_OFF_THE_WIRE`.

`pa` is deliberately NOT here. It reads `block.addr`, so it carries a field -- one another key
already carries, which is `WIRE_KEYS_REPEATING_ANOTHERS_FIELD`'s term and not this one. The
distinction is the whole reason the two sides balance: a key that carries nothing and a key that
carries a repeat pull the arithmetic in opposite directions.
"""

WIRE_KEYS_CARRYING_TWO_FIELDS: Final = ("od", "sc")
"""`sc` is `[score, score_kind]` and `od` is `[origin_driver, driver_schema_v]` (03:658-662).

Each pair is both-or-neither on the table -- `score` and `score_kind` are nullable together under
a CHECK -- so one JSON array per pair is the encoding that cannot represent the illegal half.
"""

WIRE_KEYS_REPEATING_ANOTHERS_FIELD: Final = ("i", "pa")
"""The two keys that read `addr`: `i` is the block's own and `pa` is its parent's, derived from it.

This is the term the old arithmetic did not have, and without it the two sides do not balance:
twenty-eight field-to-key attributions over twenty-seven distinct fields, because `addr` is
attributed twice. Naming it is what lets the reconciliation below be an equality rather than a
coincidence -- and it is why `parent` is in `FIELDS_OFF_THE_WIRE` even though the archive plainly
knows each block's parent. What travels is the parent's ADDRESS, computed from the child's;
`block.parent`, a `block_id`, is read by nothing on the write path.
"""


def _block_attrs(
    node: ast.AST, fields: frozenset[str], aliases: dict[str, frozenset[str]]
) -> frozenset[str]:
    """Every `Block` field read anywhere under `node`, following one level of local alias."""
    found: set[str] = set()
    for inner in ast.walk(node):
        if (
            isinstance(inner, ast.Attribute)
            and isinstance(inner.value, ast.Name)
            and inner.value.id == "block"
            and inner.attr in fields
        ):
            found.add(inner.attr)
        elif isinstance(inner, ast.Name) and inner.id in aliases:
            found |= aliases[inner.id]
    return frozenset(found)


def _wire_key_fields() -> dict[str, frozenset[str]]:
    """`{wire key: the `Block` fields its value is read from}`, off `archive/owdoc.py`'s AST.

    The one wrinkle is `os`, whose value is computed into a local above the record literal
    (`origin = _ORIGIN_ENCODERS[type(block.origin)](block.origin)`), so a read of the dict values
    alone attributes it to nothing. One pass collects locals assigned from a `block` attribute and
    the second resolves them, which is why `_block_attrs` takes an alias map. A second level of
    indirection would need a third pass and there is none in the subject; if one appears, that key
    reports zero fields and `WIRE_KEYS_WITH_NO_FIELD` fails, which is the right direction to fail
    in.
    """
    fields = frozenset(field.name for field in dataclasses.fields(Block))
    tree = ast.parse(Path(owdoc_module.__file__ or "").read_text(encoding="utf-8"))
    per: dict[str, set[str]] = {key: set() for key in WIRE_KEYS}
    writers = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in WIRE_WRITERS
    ]
    assert [node.name for node in writers] == sorted(WIRE_WRITERS), (
        f"archive/owdoc.py no longer declares {WIRE_WRITERS} at module scope; the wire record is "
        f"built somewhere else now and this derivation is reading the wrong functions"
    )
    for writer in writers:
        aliases: dict[str, frozenset[str]] = {}
        for node in ast.walk(writer):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                attrs = _block_attrs(node.value, fields, {})
                if attrs:
                    aliases[node.targets[0].id] = attrs
        for node in ast.walk(writer):
            if not isinstance(node, ast.Dict):
                continue
            for key_node, value in zip(node.keys, node.values, strict=True):
                if isinstance(key_node, ast.Constant) and key_node.value in per:
                    per[key_node.value] |= _block_attrs(value, fields, aliases)
    return {key: frozenset(value) for key, value in per.items()}


def test_the_field_set_and_the_wire_keys_are_two_lists_and_not_one() -> None:
    """Thirty-two fields, twenty-nine keys, and the difference accounted for by NAME.

    16-roadmap.md:429 freezes `Block`'s field set and 03:687 freezes the twenty-nine keys of
    `model_version = "1.1"` (erratum `E52`, superseding the charter's twenty-two). They are two
    lists of two lengths, and a reader who takes them for one list will add a field and expect a
    key, or retire a key and expect a field. Neither list is transcribed here: the fields come off
    `Block`, the keys off `archive/owdoc.py`'s `WIRE_KEYS`, and the MAPPING between them off the
    two functions that write the record.

    **What this test used to be, and why that could not fail.** It was arithmetic over three
    lengths -- `32 - 3 == 29 - 2 + 2` -- with subset checks that only asked whether the names
    existed. So the two roles were interchangeable: swapping `WIRE_KEYS_WITH_NO_FIELD` with
    `WIRE_KEYS_CARRYING_TWO_FIELDS` cancelled in the arithmetic and passed, and naming `addr`,
    `cite` and `page` as the fields that never travel passed too. Both numbers were also wrong:
    `parent` and `producer_id` never reach the wire either, and `pa` and `pd` carry no field of
    their own, so the true reconciliation is

        32 fields - 5 that never travel                      = 27 that do
        29 keys - 3 carrying no field + 2 carrying two        = 28 field-to-key attributions
        28 attributions - 1 repeat of `addr` (`i` and `pa`)   = 27 distinct fields carried

    and every term on both lines is now a named set asserted against the subject.
    """
    fields = frozenset(field.name for field in dataclasses.fields(Block))
    assert len(fields) == 32
    assert len(WIRE_KEYS) == 29

    carried = _wire_key_fields()
    counts = Counter(name for names in carried.values() for name in names)

    # Five anchors, so a derivation that silently stops reading the subject fails HERE, naming
    # the key it misread, rather than reporting a plausible-looking set of roles below. `os` is
    # the one that matters: it is the only key whose field is reached through a local, so it is
    # the canary for `_wire_key_fields`'s alias pass.
    assert carried["i"] == frozenset({"addr"})
    assert carried["pa"] == frozenset({"addr"}), "`pa` is the PARENT's addr, derived from `addr`"
    assert carried["lb"] == frozenset({"label"})
    assert carried["m"] == frozenset({"marks"}), "`m` is written by mark_records, not block_record"
    assert carried["os"] == frozenset({"origin"}), (
        "`os` reads `block.origin` through a local (`origin = _ORIGIN_ENCODERS[...](...)`), so an "
        "empty set here means the alias pass in `_wire_key_fields` no longer resolves it and "
        "every role set below is wrong rather than merely different"
    )
    assert sorted(key for key, names in carried.items() if not names) == list(
        WIRE_KEYS_WITH_NO_FIELD
    )
    assert len(WIRE_KEYS_WITH_NO_FIELD) == 3
    assert sorted(key for key, names in carried.items() if len(names) == 2) == list(
        WIRE_KEYS_CARRYING_TWO_FIELDS
    )
    assert [key for key, names in carried.items() if len(names) > 2] == [], (
        "no wire key carries three `Block` fields; 03:658-662's two pairs are the only pairs"
    )
    assert sorted(
        key for key, names in carried.items() if any(counts[name] > 1 for name in names)
    ) == list(WIRE_KEYS_REPEATING_ANOTHERS_FIELD)
    assert sorted(fields - set(counts)) == list(FIELDS_OFF_THE_WIRE)

    attributions = sum(len(names) for names in carried.values())
    assert attributions == 28
    assert (
        len(WIRE_KEYS) - len(WIRE_KEYS_WITH_NO_FIELD) + len(WIRE_KEYS_CARRYING_TWO_FIELDS)
        == attributions
    )
    assert len(counts) == 27
    assert len(fields) - len(FIELDS_OFF_THE_WIRE) == len(counts) == 27, (
        f"{len(fields) - len(FIELDS_OFF_THE_WIRE)} Block fields travel but the wire keys carry "
        f"{len(counts)}; one of the two frozen lists moved and the sets above say which"
    )
    assert set(fields) != set(WIRE_KEYS), "the field set and the key set are not one list"


# ---------------------------------------------------------------------------------------------
# 5. Gap: the `addr` grammar -- 03:1088-1092's five productions and its two bounds
# ---------------------------------------------------------------------------------------------

ADDR_GRAMMAR: Final = re.compile(r"\Adoc\Z|\Ap[0-9]+(?:/(?:[0-9]+|r[0-9]+c[0-9]+))+\Z")
"""03:1088-1092's five productions, assembled into one anchored pattern.

`ADDR_PRODUCTIONS` below is the fence itself, transcribed, and read back out of the plan by
`test_the_two_grammars_are_the_plans_own_printed_productions`. An earlier version of this
docstring printed the fence here as prose and called it four productions; the fence declares
five -- `addr`, `page`, `step`, `ord` and `cell_ref` -- and 03's `cite` fence, whose two
productions this module counts as two, includes its own head. Counted the same way, this one is
five.

There is no such regex in the shipped code, and that is correct rather than an omission: an `addr`
is MINTED, never parsed from input. `store/doc.py:_address` builds a child's address from its
parent's, which is how rule 2's page anchor falls out without a lookup, and the one reader that
walks an address (`archive/owdoc.py:parent_addr`) needs only the last `/`. So the grammar's
checkable form lives here, in a test, and the assertions below run it over the plan's own worked
examples and over the strings a reader would guess are legal.
"""

ADDR_PRODUCTION_LINES: Final = (1088, 1092)
ADDR_PRODUCTIONS: Final[tuple[str, ...]] = (
    'addr      := "doc" | "p" page "/" step ( "/" step )*',
    "page       := DIGIT+",
    "step       := ord | cell_ref",
    "ord        := DIGIT+",
    'cell_ref   := "r" DIGIT+ "c" DIGIT+',
)
"""03:1088-1092, transcribed line for line, with each line's trailing `--` comment dropped.

Why a transcription is here at all, when `ADDR_GRAMMAR` above already is one: a regex is a
transcription nobody can diff against the plan by eye, and this module had no parity check for
either grammar -- unlike `SOR_TABLES`, which has one. Widening the corpus class of `CITE_GRAMMAR`
from `{0,31}` to `{0,63}`, and admitting `dot` beside `doc` as an `addr` root, each broke nothing.
These lines are what a parity test can compare, and the two boundary tests below are what holds
when the parity test skips, which it does on every checkout without `_plan/`.
"""

ADDR_EXAMPLES: Final = ("doc", "p14/3", "p14/3/1", "p14/3/r2c5", "p14/3/r2c5/0")
"""03:1112-1114, verbatim. `doc` is the root; the other four are the example spine it prints."""

NOT_ADDRESSES: Final = (
    "",
    "doc/0",
    "p14",
    "14/3",
    "P14/3",
    "p14/3/r2",
    "p14/3/c5",
    "p14/-1",
    "p14/3/",
    "/p14/3",
    "p14//3",
    "p14/3/r2c5#0",
    "d1#1",
)
"""Strings a reader could take for an address. Each is refused for a reason the grammar states.

`doc/0` is the one worth naming. Rule 3 makes the FIRST step a page-root ordinal, so the root's
children are `p<page>/<n>` and never `doc/<n>`; a grammar that accepted it would make the root's
address a prefix of its children's, which is the document-global numbering 03:1113-1116 rejects --
*"re-parsing page 12 of a 5,000-page document would renumber pages 13 through 4,999."*
"""


def _fence_productions(plan, first: int, last: int) -> tuple[str, ...]:
    """`_plan/03`'s lines `first`..`last`, each with its trailing `--` commentary dropped.

    The fence delimiters are asserted rather than searched for, because a fence that moved is a
    re-citation and not something to recover from silently: if `` ``` `` is not immediately above
    `first` and immediately below `last`, the cited range is no longer the printed grammar.
    """
    lines = plan.lines("03-document-model.md")
    assert lines[first - 2].strip() == "```", f"03:{first - 1} no longer opens a fence"
    assert lines[last].strip() == "```", f"03:{last + 1} no longer closes a fence"
    return tuple(line.split(" --")[0].rstrip() for line in lines[first - 1 : last])


def test_the_two_grammars_are_the_plans_own_printed_productions(plan) -> None:
    """`ADDR_PRODUCTIONS` and `CITE_PRODUCTIONS` are 03's two fences, verbatim and in order.

    This is the parity check neither grammar had. `SOR_TABLES` has had one since it was written --
    `test_the_sor_and_der_lists_are_the_plans_own_names` -- and without the same for these two,
    both regexes were transcriptions of a document nothing re-read: widening the corpus class to
    `{0,63}` and admitting `dot` as a root each passed every test in sections 5 and 6.

    It cannot be the whole answer, because it skips without `_plan/`. The two boundary tests that
    follow each grammar are the half that runs on a clean clone, and between them they pin the
    same two characters this test pins the whole line of.
    """
    plan.require()
    assert _fence_productions(plan, *ADDR_PRODUCTION_LINES) == ADDR_PRODUCTIONS
    assert _fence_productions(plan, *CITE_PRODUCTION_LINES) == CITE_PRODUCTIONS


def test_the_only_bare_word_addr_is_doc_and_the_only_page_prefix_is_p() -> None:
    """The half of the grammar the example lists do not reach, pinned without the plan.

    `ADDR_GRAMMAR`'s first alternative is a three-character literal and its second begins with a
    one-character one, and neither `ADDR_EXAMPLES` nor `NOT_ADDRESSES` says so: relaxing the root
    to `do[ct]` and the prefix to `q?p` left every test in this section green, because a positive
    list only ever proves the pattern is wide enough and a negative list proves nothing about the
    shapes it does not contain. These are those shapes.

    `docs` is the one worth naming. 03:1096 makes the root's addr a literal, so a reader who
    pluralises it -- in a fixture, a migration, a hand-written `.owdoc` -- is writing an address
    that is not one, and an `addr` is never parsed at runtime to tell them so.
    """
    for near_root in ("do", "dot", "docs", "doc0", "Doc", "root", "d"):
        assert not ADDR_GRAMMAR.match(near_root), f"{near_root!r} is not the root addr (03:1088)"
    assert ADDR_GRAMMAR.match("doc")
    for near_prefix in ("q14/3", "qp14/3", "pp14/3", "page14/3", "14/3"):
        assert not ADDR_GRAMMAR.match(near_prefix), f"{near_prefix!r} has no `p` page anchor"
    assert ADDR_GRAMMAR.match("p14/3")


def test_the_addr_grammar_is_03_1088s_five_productions() -> None:
    """The plan's five worked examples are legal and thirteen near-misses are not.

    The negative list is the half that carries the grammar: a pattern that accepted everything
    would pass the positive half, and `doc/0` and `p14/3/r2` are the two shapes a reader
    actually guesses wrong.

    Both lists are SIZED first, with the numbers their own docstrings already state. A `for` loop
    over an empty tuple passes and proves nothing, and emptying these three tuples -- the whole
    by-example content of sections 5 and 6 -- left this file green over 108 tests. The counts are
    not new claims: five is what 03:1112-1114 prints and thirteen is what `NOT_ADDRESSES` says it
    holds.
    """
    assert len(ADDR_EXAMPLES) == 5, "03:1112-1114 prints five addresses"
    assert len(NOT_ADDRESSES) == 13, "the negative list is thirteen near-misses"
    for addr in ADDR_EXAMPLES:
        assert ADDR_GRAMMAR.match(addr), f"03:1112 prints {addr!r} as an address"
    for text in NOT_ADDRESSES:
        assert not ADDR_GRAMMAR.match(text), f"{text!r} is not an addr under 03:1088-1092"


def _addr_literals_in(module: object) -> frozenset[str]:
    """Every `Addr("...")` string literal in `module`'s source, read off its AST.

    `store/doc.py` mints the root address as `Addr("doc")` inline (`:1536`) rather than from a
    named constant, so it is a FOURTH home for the frozen literal and the only one of the four
    that decides what a real store writes to the `block` table. The test below claimed "every home
    that spells it" and read three; changing that fourth site alone left it green.

    An AST read rather than a store write, deliberately, and it is worth being precise about what
    that buys. It proves the literal at the mint site is the frozen one; it does not prove the
    mint site is reached, which is `test_store_doc.py`'s
    `test_the_addresses_are_section_6_2s_three_rules_including_a_cell_across_a_page_break` and
    already a pin on this surface. A set equality rather than a membership test is what makes a
    SECOND bare-word literal appearing in that module fail here too.
    """
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Addr"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }
    return frozenset(found)


def test_the_root_addr_is_the_literal_doc_in_every_home_that_spells_it() -> None:
    """Rule 1: *"The `document` root's addr is the literal `doc`."* 03:1096.

    The literal is asserted first and the four homes are then asserted equal to IT rather than to
    each other, which is the difference between pinning a value and pinning agreement. That a
    frozen one-word production HAS four homes is a finding this wave reports rather than something
    this test can fix: `archive/owdoc.py:345` exports `ROOT_ADDR` publicly, `store/verify.py:198`
    and `store/portable.py:363` each declare a private `_ROOT_ADDR`, and `store/doc.py:1536` --
    the one that mints it -- spells it inline. See `_addr_literals_in` on the fourth.
    """
    assert str(ROOT_ADDR) == "doc"
    assert verify_module._ROOT_ADDR == "doc"
    assert portable_module._ROOT_ADDR == "doc"
    assert _addr_literals_in(doc_module) == {"doc"}
    assert ADDR_GRAMMAR.match(str(ROOT_ADDR))
    assert parent_addr(str(ROOT_ADDR)) is None, "the root has no parent (03:1096)"


def test_walking_a_plan_example_to_the_root_stays_inside_the_grammar() -> None:
    """Every prefix of a legal addr is a legal addr, which is what makes `parent_addr` total.

    03:1105's rule 3 builds an address by appending steps, so the containment spine of
    `p14/3/r2c5/0` is `p14/3/r2c5`, `p14/3`, `doc` -- four addresses, all in the grammar, ending
    at the root. A grammar admitting a step shape only at depth one would break this walk, and a
    `parent_addr` that returned `None` early would silently reparent a subtree on import.
    """
    walked = ["p14/3/r2c5/0"]
    while (parent := parent_addr(walked[-1])) is not None:
        walked.append(str(parent))
    assert walked == ["p14/3/r2c5/0", "p14/3/r2c5", "p14/3", "doc"]
    for addr in walked:
        assert ADDR_GRAMMAR.match(addr), addr


def test_the_addr_is_bounded_by_sixty_four_steps_and_five_hundred_twelve_chars() -> None:
    """03:1131-1134: *"`addr` is bounded. `MAX_BLOCK_DEPTH = 64` steps and `length(addr) <= 512`."*

    The bounds are part of the frozen grammar because they are what stops a hostile document with
    50,000 nested `div`s producing a 50,000-deep spine and a 250 KB address. Each is read at its
    own home -- the depth from `limits.py`, the length from the CHECK in the shipped DDL -- and
    `store/doc.py`'s private mirror is asserted against the CHECK its own error message names,
    which is the assertion that fails if one of the two is edited alone.
    """
    assert MAX_BLOCK_DEPTH == 64
    assert _MAX_ADDR_CHARS == 512
    ddl = (MIGRATIONS_DIR / "0001_init.sql").read_text(encoding="utf-8")
    assert "CHECK (length(addr) <= 512)" in ddl, (
        "0001_init.sql no longer bounds `addr` at 512 chars; 03:1131 makes the bound part of the "
        "grammar 16-roadmap.md:430 freezes"
    )


# ---------------------------------------------------------------------------------------------
# 6. Gap: the `cite` grammar -- 03:1141-1142's two productions
# ---------------------------------------------------------------------------------------------

CITE_GRAMMAR: Final = re.compile(r"\A(?:[a-z0-9][a-z0-9_-]{0,31}:)?d[0-9]+#[0-9]+\Z")
"""03:1141-1142's two productions, assembled into one anchored pattern.

    cite   := [ corpus ":" ] "d" doc_ord "#" n
    corpus := [a-z0-9][a-z0-9_-]{0,31}

`{0,31}` after a leading character is a corpus of at most THIRTY-TWO characters, which is the
boundary `test_the_corpus_segment_is_bounded_at_thirty_two_characters` pins from both sides. It is
pinned there rather than only in `CITE_PRODUCTIONS` because a transcription with a parity check
still has no parity on a checkout without `_plan/`.

`store/graph.py:239`'s `_CITE_GRAMMAR` is the shipped parser and it is deliberately LOOSER in the
corpus position -- `(?:[^:]*:)?` -- because its job is to pull a `doc_ord` out of a key so a cite
lookup is an index seek on `block_cite (doc_ord, cite)` rather than a scan. Validating the corpus
segment there would be validating it in the wrong place: 03:1144 says a corpus *"must name an
entry in `omniweave.toml [corpora]`"*, which is a config lookup and not a character class. So the
relation asserted below is containment rather than equality, in the direction a real break shows
up in.
"""

CITE_PRODUCTION_LINES: Final = (1141, 1142)
CITE_PRODUCTIONS: Final[tuple[str, ...]] = (
    'cite   := [ corpus ":" ] "d" doc_ord "#" n',
    "corpus := [a-z0-9][a-z0-9_-]{0,31}",
)
"""03:1141-1142, transcribed line for line, with the trailing `--` comment dropped.

See `ADDR_PRODUCTIONS` for why both fences are transcribed as text beside the two regexes.
"""

CITE_EXAMPLES: Final = ("d1#1", "d1#2", "d2#1", "d325001#987654321", "corpus-a:d1#7", "c0:d1#1")
"""Five forms the plan admits plus the qualified form of 03:1141's optional `corpus` prefix."""

NOT_CITES: Final = (
    "",
    "d1",
    "1#1",
    "D1#1",
    "d1#",
    "#1",
    "d1#1#2",
    "d-1#1",
    "d1#-1",
    "Corpus:d1#1",
    "-corpus:d1#1",
    "p14/3",
)
"""Twelve refusals. `p14/3` is last on purpose: an `addr` is never a `cite` (INV-8)."""


def test_the_cite_grammar_is_03_1141s_two_productions() -> None:
    """Six legal forms, twelve refusals, and the corpus production's own character class.

    `Corpus:d1#1` and `-corpus:d1#1` are the two that matter: the corpus segment is lower-case
    and may not lead with a hyphen, which is part of what makes a cite safe in a CLI argument, a
    log line and a prompt.

    Sized first, for the reason `test_the_addr_grammar_is_03_1088s_five_productions` gives.
    """
    assert len(CITE_EXAMPLES) == 6, "six legal forms, as this test's own name says"
    assert len(NOT_CITES) == 12, "twelve refusals, as `NOT_CITES` says it holds"
    for cite in CITE_EXAMPLES:
        assert CITE_GRAMMAR.match(cite), f"{cite!r} is a cite under 03:1141-1142"
    for text in NOT_CITES:
        assert not CITE_GRAMMAR.match(text), f"{text!r} is not a cite under 03:1141-1142"


def test_the_corpus_segment_is_bounded_at_thirty_two_characters() -> None:
    """`corpus := [a-z0-9][a-z0-9_-]{0,31}` -- a lead character plus thirty-one, so thirty-two.

    Both sides of the boundary, and the character class, pinned without the plan. `NOT_CITES`
    above carries no over-long corpus and no corpus with an illegal interior character, so
    widening the class to `[a-z0-9_.-]{0,63}` -- a plausible "hostnames have dots" edit --
    passed every test in this section. The bound is not decoration: 03:1144 makes a corpus name an
    entry in `omniweave.toml [corpora]`, and a cite is meant to be safe in a CLI argument, a log
    line and a prompt, which is a promise about its length as much as its alphabet.
    """
    assert CITE_GRAMMAR.match("a" * 32 + ":d1#1"), "a thirty-two character corpus is legal"
    assert not CITE_GRAMMAR.match("a" * 33 + ":d1#1"), "thirty-three is one over 03:1142's bound"
    assert CITE_GRAMMAR.match("a_b-c9:d1#1"), "underscore, hyphen and digit are in the class"
    for illegal in ("a.b:d1#1", "a b:d1#1", "a/b:d1#1", "a+b:d1#1", "_ab:d1#1", "9-a:d1#1"):
        legal = illegal.startswith("9")
        assert bool(CITE_GRAMMAR.match(illegal)) is legal, f"{illegal!r} against 03:1142's class"


def test_the_shipped_parser_resolves_every_cite_the_plans_grammar_admits() -> None:
    """Containment in the direction a break would show up in, with the looseness declared.

    A cite the plan admits and the shipped parser cannot match is a durable name that resolves to
    nothing, which is the one failure `cite` exists to prevent -- 03:1150, *"One cite names at
    most one row, for the life of the corpus."* The converse is not asserted: the parser's corpus
    position is wider on purpose, for the reason `CITE_GRAMMAR`'s docstring gives.
    """
    assert len(CITE_EXAMPLES) == 6, "an empty corpus of examples proves no containment at all"
    for cite in CITE_EXAMPLES:
        match = graph_module._CITE_GRAMMAR.match(cite)
        assert match is not None, f"the shipped parser cannot read {cite!r}"
        assert int(match.group("doc_ord")) > 0
        assert int(match.group("n")) > 0


def test_the_unqualified_form_is_what_a_row_holds_and_both_forms_resolve() -> None:
    """03:1167-1170: *"the column holds the unqualified form and that both forms resolve."*

    Corpus qualification is a per-surface presentation decision that belongs to
    10-interfaces.md, so the model's obligation is exactly two properties: the stored form carries
    no corpus, and stripping a corpus off a qualified form yields the stored form with the same
    `doc_ord` and the same `n`.
    """
    qualified = "corpus-a:d1#7"
    unqualified = qualified.split(":", 1)[1]
    assert unqualified == "d1#7"
    assert CITE_GRAMMAR.match(unqualified)
    assert CITE_GRAMMAR.match(qualified)
    for form in (qualified, unqualified):
        match = graph_module._CITE_GRAMMAR.match(form)
        assert match is not None
        assert (match.group("doc_ord"), match.group("n")) == ("1", "7")
