"""The tier nobody may declare, the ack a single mutated byte voids, and the Grant that cannot
exist without a `dpa_ref`.

`omniweave_core/drivers/licence.py` is W3.3 (16-roadmap.md:483). Three properties decide whether
it is worth anything, and the obvious test -- "`compute_tier` returns `open` for these facts" --
is none of them:

* **The tier is COMPUTED and never DECLARED** (04-driver-system.md:712, :1838; 02:1194). So the
  load-bearing tests are that a card DECLARING a tier is refused in all three places it could be
  written, that the token appears in no card-grammar constant, and that a recorded tier
  disagreeing with the facts is a non-zero exit with the difference PRINTED. The tier ladder is
  then tested at every boundary -- ten `restricted` producers one at a time, the two allocated
  restriction bits that deliberately do NOT raise the tier, `requires_credential` as
  `commercial`'s only route (Q12, 04:2804-2810), a seeded digest as `forbidden`, and the
  `max(code, weights)` rule in both directions.
* **An acknowledgement is void when the text changes** (02:1166, 04:1890-1893, DR16). The
  required test is 04:1913's: mutate the licence file and assert `LICENCE_ACK_STALE` with the hash
  diff printed. Every digest in this file is a PINNED LITERAL, computed once and written down. A
  test that recomputed `licence_sha256(MUTATED)` and asserted the verdict named it would pin
  agreement between two calls of one function and would pass just as happily if the ack were
  bound to nothing at all.
* **A `Grant` without a `dpa_ref` must be UNCONSTRUCTABLE** (AP-4, 01:1091). AP-4's verdict is
  "the mechanism exists, the audit finds it, and it has never once run", so it is not enough that
  a validator rejects one: the field must have no default, the blank must raise, and
  `dataclasses.replace()` must not be able to strip it. All three are asserted, plus that the
  reference reaches the run manifest, which is where 01:1091 requires it to be printed.

Two more things this file does on purpose. The shipped six tombstones are run through
`compute_tier()` and each must compute `forbidden`, which is 04 section 10.4's `tier` column
re-derived from the plan's own markdown rather than copied here -- the roster and the computation
are then two independent sources that have to agree. And the tier lattice is asserted against
04:1856's printed ordering string, because `LicenceTier` is a `StrEnum` and a plain `max()` over
two of its members returns the ALPHABETICALLY larger one: `max(OPEN, FORBIDDEN)` is `"open"`, the
single worst wrong answer available here, and that trap is asserted as a live property of the
enum rather than remembered as a comment.

Section 8 is different in kind and is labelled so. Sections 1-7 were written from the plan;
section 8 was written from a MUTATION PASS over `licence.py` -- each of its tests was proved red
under a named, reverted mutation and green without it, and the mutation is named in its docstring.
Fourteen mutations survived sections 1-7 untouched, so fourteen defects of that shape could have
shipped: a `LICENCE_ACK_STALE` refusal with the digest-divergence pointer removed, a second
denylist beside the tombstones, a `seeds` argument given the AP-4 default the module docstring
warns against, `clause_refs` dropped from a refusal 04:1973 requires them in, an `ack_version`
that admitted `true`, and nine more. Two of the fourteen were live bugs in `licence.py` rather
than untested behaviour and were fixed in that file, each said so in the test that pins it.

The lesson worth carrying forward is that the shapes were mostly not missing tests. They were
tests whose PROSE claimed more than their assertions: "two guards" where only one was reachable,
"differ on exactly one of these rows" where a one-sided `max` fails two, and three indices read
off a verdict whose status the test never looked at.

Specified in 04-driver-system.md sections 7.1, 7.3, 7.5 and 10.4, 01-principles.md INV-5, DR15,
DR16 and AP-4, 02-architecture.md rows 13 and :1166 and :1194, 14-security.md sections 5.2 and
9.7, 16-roadmap.md:483, and 00-vision.md:404.
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import datetime as dt
import inspect
import io
import re
import tokenize
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import pytest
from omniweave_core.drivers import licence as licence_module
from omniweave_core.drivers.card import (
    TOP_LEVEL_KEYS,
    TOP_LEVEL_TABLES,
    DriverCard,
    LicenceFacts,
    Tombstone,
    load_card,
)
from omniweave_core.drivers.licence import (
    ACK_ROW_KEYS,
    ACK_ROW_REQUIRED,
    ACK_STALE_CODE,
    COPYLEFT_NETWORK,
    COPYLEFT_STRONG,
    GRANT_MANIFEST_FIELDS,
    TIER_ORDER,
    Ack,
    AckSet,
    AckStatus,
    AckVerdict,
    AckWhich,
    Grant,
    LicenceSeeds,
    check_ack,
    compute_tier,
    licence_sha256,
    load_acks,
    require_computed_tier,
    restriction_bits,
    restrictions_of,
    seeds_from_tombstones,
    stored_tier_mismatch,
    tier_from_card,
    tier_rank,
    tier_reasons,
)
from omniweave_core.errors import ConfigError, DriverHostError
from omniweave_ports.types import LicenceTier, Restriction

if TYPE_CHECKING:
    from conftest import Interpreter, PlanDocs

TOMBSTONES = (
    Path(__file__).resolve().parents[2] / "src" / "omniweave_core" / "drivers" / "tombstones"
)
"""The shipped refusal set, reached from this file rather than from the module under test, so the
two agree by measurement rather than by construction."""

MINIMAL = """card_schema = 1

[driver]
id = "parse.notebook.ipynb"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "pkg.driver:Cls"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""
"""The smallest card that loads, so a negative test asserts one thing. `[licence.code]` is
required at load (04-driver-system.md section 2.1), and there is no `tier` key anywhere in it
because there is no legal place to write one."""

# --------------------------------------------------------------------------------------------
# The licence-text fixture and its PINNED digests. Computed once, written down, never recomputed
# by a test: 04:1913's mutated-licence assertion is about STALENESS, and a test that derived the
# expected digest from the mutated bytes would assert that sha256 is a function.
# --------------------------------------------------------------------------------------------

LICENCE_TEXT = b"OMNIWEAVE TEST LICENCE 1.0\n\nYou may use this software internally.\n"
LICENCE_DIGEST = "sha256:eb38f56a151697856213321abf653098800380fd7146ad17a8c823439cbf076b"

RELICENSED_TEXT = LICENCE_TEXT.replace(b"1.0", b"1.1")
RELICENSED_DIGEST = "sha256:ebc6182a5025650037eaf38701887b3a55022f646ec2d8a96317510841fdd4ab"
RELICENSED_FIRST_DIFFERENCE = 9
"""Both digests begin `sha256:eb`, so the index is not decoration: an operator comparing two
hashes by eye stops once the prefix matches, which is exactly the case a one-character version
bump produces."""

RECASED_TEXT = LICENCE_TEXT.replace(b"internally", b"Internally")
RECASED_DIGEST = "sha256:3ab554fdd622cddfaae5eb17acbb00f487bbcbb42fb2db3ca013fb977c67ba73"

WHITESPACE_TEXT = LICENCE_TEXT[:-1] + b" \n"
WHITESPACE_DIGEST = "sha256:dc4423297b555e7b47b9e479c4d7ef99a2c6203ecae188a35e81f6de37fa1ae1"
"""One trailing space. The digest moves, which is the point of hashing the RAW BYTES: a
normalising digest would make a whitespace-only relicence invisible."""

DATALAB_SEED = "unresolved:md5=e1f69b64dee2f1641a9b1ab12adf24d6"
"""The one seed marker, surya and lift share, transcribed from the shipped tombstone cards and
04-driver-system.md section 10.4 ("`md5sum marker/MODEL_LICENSE surya/MODEL_LICENSE
lift/MODEL_LICENSE` returns one digest three times"). It is an explicitly UNRESOLVED seed because
the file is not in this repository and never will be (11-repo-layout.md section 9.2 layer 1)."""

PYMUPDF_LICENCE_DIGEST = "sha256:37a680133bd09342f934afb8dd2c7d9e1b624da5f35e3a38adb103e37c055ed1"
"""The digest the plan's own worked ack row is bound to (04:1902, and again at 14:1614). Two
documents write the same value, which is why it can be a literal here."""

PLAN_ACK_FILE = f'''ack_version = 1

[[ack]]
driver = "parse.pdf.pymupdf"
licence_sha256 = "{PYMUPDF_LICENCE_DIGEST}"
which = "code"
tier = "restricted"
restrictions = ["copyleft_network"]
acknowledged_by = "legal@example.com"
acknowledged_at = "2026-08-30T09:12:00Z"
note = "AGPL-3.0 accepted for internal-only deployment; ticket LEGAL-4471."
'''
"""04-driver-system.md:1897-1908, transcribed. The plan's worked row is the fixture, so the
grammar this module accepts is the grammar the plan prints and not a superset of it."""


def facts(**overrides: object) -> LicenceFacts:
    """`[licence.*]` facts, defaulting to the permissive shape 04:931-947's worked card writes."""
    base: dict[str, object] = {"spdx": "Apache-2.0", "redistribution": "allowed"}
    base.update(overrides)
    return LicenceFacts(**base)  # type: ignore[arg-type]


def card(text: str) -> DriverCard:
    """Load a driver card, insisting it is one."""
    loaded = load_card(text.encode("utf-8"), origin="entry_point", source="driver.toml")
    assert isinstance(loaded, DriverCard)
    return loaded


def refusal(text: str) -> DriverHostError:
    """Load `text` expecting a card refusal, and hand the error back to be read."""
    with pytest.raises(DriverHostError) as caught:
        load_card(text.encode("utf-8"), origin="entry_point", source="driver.toml")
    return caught.value


def shipped_tombstones() -> tuple[Tombstone, ...]:
    """The six shipped refusal cards, through the real `load_card()`."""
    loaded = []
    for path in sorted(TOMBSTONES.glob("*.toml")):
        stone = load_card(path.read_bytes(), origin="tombstone", source=str(path))
        assert isinstance(stone, Tombstone)
        loaded.append(stone)
    return tuple(loaded)


NO_SEEDS = LicenceSeeds()
"""An explicitly empty refusal set. Every tier test that is not about the seed set passes this,
which is the point of `seeds` having no default: the absence of a refusal set is written down."""


# --------------------------------------------------------------------------------------------
# 1. The tier is computed and never declared (04:712, 04:1838, 02:1194, DR15).
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("where", "text"),
    [
        ("top level", MINIMAL.replace("card_schema = 1", 'card_schema = 1\ntier = "open"')),
        ("[licence]", MINIMAL + '\n[licence]\ntier = "open"\n'),
        (
            "[licence.code]",
            MINIMAL.replace('spdx = "Apache-2.0"', 'spdx = "Apache-2.0"\ntier = "open"'),
        ),
    ],
)
def test_a_card_that_declares_its_own_licence_tier_is_refused(where: str, text: str) -> None:
    """04:712: the tier is "*computed*, never on the card". 04:1838: "an author cannot mislabel".

    All three spellings, because refusing one and admitting another would leave the mislabel a
    formatting question. The receipt for why this matters is 01:205-209: marker, surya and lift
    ship a permissive top-level `LICENSE` over OpenRAIL-M weights, so a card that could say
    `tier = "open"` would be believed by everything downstream.
    """
    error = refusal(text)
    assert error.code() == "OW_CARD_INVALID", where
    assert "tier" in str(error), where


def test_the_token_tier_appears_in_no_card_grammar_constant() -> None:
    """The refusal above is not a special case: there is nowhere legal to write it.

    Asserted over the grammar's own closed sets rather than over a card, so a future table or key
    that admitted `tier` fails here even if no fixture card happens to write one.
    """
    assert "tier" not in TOP_LEVEL_KEYS
    assert "tier" not in TOP_LEVEL_TABLES
    assert "tier" not in {field.name for field in dataclasses.fields(LicenceFacts)}


def test_a_recorded_tier_that_disagrees_with_the_facts_exits_non_zero_with_the_difference() -> None:
    """04:1839 and 04:1975-1976: `ow drivers check` exits non-zero, and exit 1 is the code.

    The exit is the exception class and not an argument: `ConfigError.EXIT` is 1, which
    10-interfaces.md section 9.3 makes the whole of the mapping. The message must carry the
    DIFFERENCE -- both tiers and the clause that produced the computed one -- because "forbidden"
    alone sends the operator to re-read a licence somebody already read for them.
    """
    reasons = tier_reasons(facts(competitor_bar=True), seeds=NO_SEEDS)
    with pytest.raises(ConfigError) as caught:
        require_computed_tier(
            driver="parse.page.thirdparty",
            stored="open",
            computed=LicenceTier.RESTRICTED,
            source="omniweave.lock",
            reasons=reasons,
        )
    error = caught.value
    assert error.EXIT == 1
    message = str(error)
    assert "'open'" in message
    assert "'restricted'" in message
    assert "omniweave.lock" in message
    assert "competitor_bar -> restricted" in message
    assert error.fix == "ow drivers check --posture"


def test_a_recorded_tier_that_agrees_is_not_a_finding() -> None:
    """The witness mechanism has to be silent when the witness is right, or nobody will keep it."""
    assert (
        stored_tier_mismatch(
            driver="parse.notebook.ipynb",
            stored="open",
            computed=LicenceTier.OPEN,
            source="omniweave.lock",
        )
        is None
    )


def test_a_recorded_tier_spelled_nonsense_is_a_mismatch_and_not_an_exception() -> None:
    """`tier = "permissive"` is the mislabel DR15 exists to catch, arriving as a typo.

    Refusing to compare an unknown spelling would turn a caught mislabel into an unread parse
    error, so the comparison is over the string and the computed tier is named beside it.
    """
    found = stored_tier_mismatch(
        driver="parse.pdf.pymupdf",
        stored="permissive",
        computed=LicenceTier.RESTRICTED,
        source="omniweave.acks.toml",
    )
    assert found is not None
    assert "'permissive'" in found.message
    assert "'restricted'" in found.message


# --------------------------------------------------------------------------------------------
# 2. Every tier boundary (04:1844-1859).
# --------------------------------------------------------------------------------------------


def test_the_tier_lattice_is_the_plans_printed_ordering(plan: PlanDocs) -> None:
    """04:1856: "the ordering `open < restricted < commercial < forbidden`".

    Re-derived from the document because the ordering is a licence judgement, not a convenience:
    `commercial` above `restricted` says a credential nobody purchased is a harder obstacle than
    copyleft an operator may knowingly accept (04:2029-2036).
    """
    plan.require()
    hits = plan.grep(
        r"open < restricted < commercial < forbidden", documents=["04-driver-system.md"]
    )
    assert hits, "04-driver-system.md no longer prints the tier ordering"
    printed = tuple(re.split(r"\s*<\s*", hits[0].text.split("`")[1]))
    assert printed == ("open", "restricted", "commercial", "forbidden")
    assert tuple(tier.value for tier in TIER_ORDER) == printed


def test_a_plain_max_over_the_tier_enum_returns_the_wrong_answer() -> None:
    """The trap `tier_rank()` exists for, asserted as a live property rather than remembered.

    `LicenceTier` is a `StrEnum`, so `max()` compares strings and `max(OPEN, FORBIDDEN)` is
    `"open"` -- the permissive tier for a forbidden card, which is the single worst wrong answer
    this module could give. `compute_tier` must not agree with it.
    """
    assert max(LicenceTier.OPEN, LicenceTier.FORBIDDEN) == "open"
    assert tier_rank(LicenceTier.OPEN) < tier_rank(LicenceTier.FORBIDDEN)
    seeds = LicenceSeeds(digests=frozenset({DATALAB_SEED}))
    assert compute_tier(facts(), facts(licence_sha256=DATALAB_SEED), seeds=seeds) == "forbidden"


def test_the_worked_cards_facts_compute_open() -> None:
    """04:931-947's `[licence.code]`, key for key: Apache-2.0, everything false, zero or empty.

    `open` is the fall-through and has no producer of its own, so this is the assertion that the
    ladder does not fire on a permissive card. Pinned as the literal string, not as
    `LicenceTier.OPEN`, so a renamed member value fails here.
    """
    worked = LicenceFacts(
        spdx="Apache-2.0",
        licence_sha256="sha256:c693279643b8cd5d248172d9c22cb7cf4ed163a3c98c8a3f69c2717edd3eacb7",
        licence_url="https://github.com/example/omniweave-driver-ipynb/blob/v0.1.0/LICENSE",
        notice_path="NOTICE",
        redistribution="allowed",
        output_share_alike=False,
        competitor_bar=False,
        requires_credential=False,
        revenue_gate_usd=0,
        mau_gate=0,
        territory_excluded=(),
        field_of_use_excluded=(),
        attribution_per_output=False,
        no_model_training=False,
        remote_kill_switch=False,
        clause_refs=(),
    )
    assert compute_tier(worked, seeds=NO_SEEDS) == "open"
    assert restriction_bits(worked) == 0


@pytest.mark.parametrize(
    ("producer", "override", "bit"),
    [
        ("competitor_bar", {"competitor_bar": True}, 2),
        ("output_share_alike", {"output_share_alike": True}, 1),
        ("territory_excluded", {"territory_excluded": ("EU",)}, 4),
        ("field_of_use_excluded", {"field_of_use_excluded": ("insurance",)}, 8),
        ("revenue_gate_usd", {"revenue_gate_usd": 5_000_000}, 16),
        ("mau_gate", {"mau_gate": 100_000_000}, 32),
        ("remote_kill_switch", {"remote_kill_switch": True}, 512),
        ("redistribution", {"redistribution": "restricted"}, 64),
        ("spdx in COPYLEFT_NETWORK", {"spdx": "AGPL-3.0-or-later"}, 1024),
        ("spdx in COPYLEFT_STRONG", {"spdx": "GPL-3.0-only"}, 2048),
    ],
)
def test_each_of_the_ten_restricted_producers_raises_the_tier_alone(
    producer: str, override: dict[str, object], bit: int
) -> None:
    """04:1847-1850 lists ten producers of `restricted`. One at a time, so each is load-bearing.

    The bit is pinned as a literal integer too, because `restriction_bits` is stamped onto every
    row a driver produces (INV-16) and a shifted bit would silently reinterpret every stored
    value. `1 << Restriction.X.value` would have pinned agreement with the enum instead.
    """
    table = facts(**override)
    assert compute_tier(table, seeds=NO_SEEDS) == "restricted", producer
    assert restriction_bits(table) == bit, producer


@pytest.mark.parametrize(
    ("fact_name", "bit"),
    [("attribution_per_output", 256), ("no_model_training", 128)],
)
def test_the_two_bits_that_deliberately_do_not_raise_the_tier(fact_name: str, bit: int) -> None:
    """04:1869-1870 allocates twelve bits; 04:1847-1850's `restricted` rule reads ten facts.

    So a driver whose only licence fact is "attribution required per output" computes `open`,
    needs no acknowledgement, and STILL stamps a bit onto every block, segment and artefact it
    produces (04:1873-1876). That asymmetry is the plan's arithmetic and it is asserted rather
    than smoothed: a reader who assumed `restricted == (bits != 0)` would be wrong, and the
    posture report prints both facts as consequences of the enabled set (04:1957-1961).
    """
    table = facts(**{fact_name: True})
    assert compute_tier(table, seeds=NO_SEEDS) == "open"
    assert restriction_bits(table) == bit


def test_requires_credential_is_commercials_only_route() -> None:
    """Q12 (04:2804-2810): `commercial` had no producer until E10 made `requires_credential` a
    `[licence.code]` fact, and release 1 ships no commercial driver -- so 04:2809 asks for exactly
    this, "one synthetic `commercial` card in the licence unit tests, which is cheap and should
    land with `compute_tier`".

    E10's reasoning is why the fact lives on the licence table and not in config (04:1861-1865):
    "this licence requires a purchased credential" is a fact about the same text `licence_sha256`
    covers, and putting it anywhere else would give `compute_tier` an input outside the hash the
    ack is bound to. The corollary asserted here is that it carries no restriction bit: a
    thirteenth code is a migration on a hot table (04:1869).
    """
    table = facts(requires_credential=True)
    assert compute_tier(table, seeds=NO_SEEDS) == "commercial"
    assert restriction_bits(table) == 0


def test_commercial_outranks_restricted_and_forbidden_outranks_both() -> None:
    """The ladder is ordered, so a card with two producers reports the higher one.

    Each expectation is a literal, so this cannot pass by both sides computing the same thing.
    """
    seeds = LicenceSeeds(digests=frozenset({DATALAB_SEED}))
    assert compute_tier(facts(requires_credential=True, competitor_bar=True), seeds=seeds) == (
        "commercial"
    )
    assert (
        compute_tier(facts(requires_credential=True, licence_sha256=DATALAB_SEED), seeds=seeds)
        == "forbidden"
    )


@pytest.mark.parametrize(
    ("code_override", "weights_override", "expected"),
    [
        ({}, {}, "open"),
        ({}, {"competitor_bar": True}, "restricted"),
        ({"competitor_bar": True}, {}, "restricted"),
        ({"competitor_bar": True}, {"requires_credential": True}, "commercial"),
        ({"requires_credential": True}, {"competitor_bar": True}, "commercial"),
    ],
)
def test_the_weakest_link_governs_across_code_and_weights(
    code_override: dict[str, object], weights_override: dict[str, object], expected: str
) -> None:
    """04:1855: the tier of a card with `[licence.weights]` is `max(tier(code), tier(weights))`.

    Both directions, because a one-sided implementation -- one that simply returns the weights
    tier whenever `[licence.weights]` is present, or the code tier whenever it is not -- fails two
    of these five rows, and one that returns the code tier unconditionally fails two others. Which
    two was measured, not supposed: an earlier draft of this docstring claimed "exactly one" and
    was wrong. 14:1345 is the same rule from the weights side: "a weights licence is a first-class
    register row with its own SPDX entry and its own tier contribution".
    """
    assert (
        compute_tier(facts(**code_override), facts(**weights_override), seeds=NO_SEEDS) == expected
    )


def test_absent_weights_are_not_an_empty_table() -> None:
    """04:1856-1857: `[licence.weights]` is omitted entirely when a driver ships no weights.

    So `None` and a default-constructed `LicenceFacts` must reach the same tier here for a
    permissive card -- and the distinction that matters is enforced by `card.py`, which refuses
    the empty table outright. This asserts `compute_tier` tolerates the absence rather than
    treating `None` as a missing argument.
    """
    assert compute_tier(facts(), None, seeds=NO_SEEDS) == "open"
    assert compute_tier(facts(), seeds=NO_SEEDS) == "open"


# --------------------------------------------------------------------------------------------
# 3. The shipped tombstones ARE the known-bad seed set (04:2016-2024, section 10.4).
# --------------------------------------------------------------------------------------------


def test_the_seed_set_built_from_the_shipped_tombstones() -> None:
    """04:2022: "a `frozenset[str]` of at most a few dozen digests, built once with the tombstones".

    Four distinct digests over six cards, because marker, surya and lift share ONE
    `MODEL_LICENSE` file -- which is the property that makes the set hash-keyed rather than
    id-keyed in the first place. Pinned as literals: a set derived from the cards and compared
    against the cards would agree with itself whatever the cards said.
    """
    seeds = seeds_from_tombstones(shipped_tombstones())
    assert seeds.digests == frozenset(
        {
            DATALAB_SEED,
            "unresolved:HunyuanOCR/License.txt",
            "unresolved:jcodemunch-mcp/LICENSE",
            "unresolved:omniparse/LICENSE",
        }
    )
    assert seeds.ids == frozenset(
        {
            "derive.code.jcodemunch",
            "parse.doc.omniparse",
            "parse.fields.lift",
            "parse.page.hunyuan",
            "parse.page.marker",
            "parse.page.surya",
        }
    )


def test_every_shipped_tombstone_computes_forbidden(plan: PlanDocs) -> None:
    """04 section 10.4's `tier` column, re-derived from the plan and computed from the cards.

    Two independent sources: the markdown table says `forbidden` for each of the six, and
    `compute_tier()` over the cards' own facts says `forbidden` for each of the six. Copying the
    column into this file as a literal would have made the assertion a restatement.
    """
    plan.require()
    rows = [
        line
        for line in plan.lines("04-driver-system.md")
        if line.startswith("| `parse.") or line.startswith("| `derive.")
    ]
    table = {
        cells[1].strip().strip("`"): cells[3].strip()
        for cells in (row.split("|") for row in rows)
        if len(cells) > 4 and cells[3].strip() in {"forbidden", "restricted", "commercial", "open"}
    }
    stones = shipped_tombstones()
    assert len(stones) == 6
    seeds = seeds_from_tombstones(stones)
    for stone in stones:
        expected = table[stone.id]
        assert expected == "forbidden", stone.id
        computed = compute_tier(
            stone.licence_code or LicenceFacts(), stone.licence_weights, seeds=seeds
        )
        assert computed == expected, stone.id


def test_the_seed_set_survives_a_rename() -> None:
    """04:2018: hash-keyed, so "a third party wrapping the same weights under a different driver
    id computes `forbidden` too".

    The third-party card here declares a brand-new id and NO restriction facts at all -- the
    weights licence hash is the only thing wrong with it. Removing the hash and changing nothing
    else computes `open`, which is what proves the seed did the work rather than some other fact
    on the fixture.
    """
    seeds = LicenceSeeds(digests=frozenset({DATALAB_SEED}))
    wrapped = facts(spdx="Apache-2.0", licence_sha256=DATALAB_SEED)
    assert compute_tier(facts(), wrapped, seeds=seeds) == "forbidden"
    assert compute_tier(facts(), facts(spdx="Apache-2.0"), seeds=seeds) == "open"


def test_a_seeded_code_licence_is_as_forbidden_as_a_seeded_weights_licence() -> None:
    """04:2016 says `[licence.code].licence_sha256` **or** `[licence.weights].licence_sha256`.

    Two of the six shipped tombstones ship no weights at all -- `parse.doc.omniparse` and
    `derive.code.jcodemunch` -- so a weights-only reading would have dropped a third of the
    refusal set while looking correct.
    """
    seeds = LicenceSeeds(digests=frozenset({"unresolved:omniparse/LICENSE"}))
    assert compute_tier(facts(licence_sha256="unresolved:omniparse/LICENSE"), seeds=seeds) == (
        "forbidden"
    )


def test_a_card_with_no_licence_digest_is_never_matched_by_an_empty_seed() -> None:
    """The hazard `tools/gate_tombstones.py`'s `SEED_RE` exists for, from the lookup side.

    `LicenceFacts.licence_sha256` defaults to `""` and four of the six shipped tombstones write a
    `[licence.code]` table with no digest in it, so a single `""` reaching the seed set would turn
    the narrowest check in this module into a blanket `forbidden` for every card that omits its
    own digest.

    This test reaches only ONE of the module's two guards -- the BUILDER's. `LicenceSeeds` strips
    the empty digest in `__post_init__`, so a `LicenceSeeds(digests=frozenset({""}))` never holds
    one and `seeded()`'s own guard is never asked. An earlier docstring here claimed both guards
    were covered; deleting the lookup guard left this file green. The second guard is
    `test_the_lookup_refuses_an_empty_digest_even_when_the_stored_set_holds_one` below, which has
    to bypass `__post_init__` to put the question.
    """
    hostile = LicenceSeeds(digests=frozenset({""}))
    assert compute_tier(facts(), seeds=hostile) == "open"
    assert not hostile.seeded(facts())

    stone = load_card(
        (TOMBSTONES / "parse.page.surya.toml").read_bytes(),
        origin="tombstone",
        source="parse.page.surya.toml",
    )
    assert isinstance(stone, Tombstone)
    assert stone.licence_code is not None
    assert stone.licence_code.licence_sha256 == ""
    assert "" not in seeds_from_tombstones((stone,)).digests


def test_a_hand_built_seed_set_normalises_its_own_digests() -> None:
    """The lookup normalises its input, so the STORED side has to normalise too.

    `seeds_from_tombstones()` is not the only way a `LicenceSeeds` comes into being -- a
    `Policy` assembled from a lockfile and a posture report both build one -- and a stored
    `SHA256:AB...` that the lookup could never match would be a refusal silently absent, which
    is AP-4's shape and the exact failure a seed set exists to prevent. The empty string is
    dropped on the same pass, for the reason the test above states.
    """
    hand_built = LicenceSeeds(digests=frozenset({LICENCE_DIGEST.upper(), "", "   "}))
    assert hand_built.digests == frozenset({LICENCE_DIGEST})
    assert hand_built.seeded(facts(licence_sha256=LICENCE_DIGEST))
    assert compute_tier(facts(licence_sha256=LICENCE_DIGEST), seeds=hand_built) == "forbidden"


def test_a_digest_matches_case_insensitively_but_an_unresolved_path_does_not() -> None:
    """A sha256's hex has one canonical casing; an `unresolved:` marker names a PATH.

    `unresolved:omniparse/LICENSE` and `unresolved:omniparse/license` are two different files on a
    case-sensitive filesystem, so lower-casing every seed would quietly widen the refusal set.
    Normalising only the `sha256:` form is the narrow rule, and this is both halves of it.
    """
    seeds = LicenceSeeds(digests=frozenset({LICENCE_DIGEST, "unresolved:omniparse/LICENSE"}))
    assert seeds.seeded(facts(licence_sha256=LICENCE_DIGEST.upper()))
    assert not seeds.seeded(facts(licence_sha256="unresolved:omniparse/license"))


def test_a_third_party_card_under_a_vetoed_id_is_forbidden_whatever_its_facts_say() -> None:
    """The id half of 04:1844, which `compute_tier`'s two printed parameters cannot express.

    A tombstoned id normally never becomes a `DriverCard` -- `load_card()` branches on
    `[tombstone]` first -- so this arm exists for the case 04:2018 names: somebody else's card,
    under a vetoed id, carrying licence facts of their own choosing. `compute_tier` over the same
    facts says `open`, which is exactly why the id check cannot live inside it.
    """
    impostor = card(MINIMAL.replace("parse.notebook.ipynb", "parse.page.marker"))
    seeds = seeds_from_tombstones(shipped_tombstones())
    assert tier_from_card(impostor, seeds=seeds) == "forbidden"
    assert compute_tier(impostor.licence_code, impostor.licence_weights, seeds=seeds) == "open"
    assert "parse.page.marker is itself a shipped tombstone" in "\n".join(
        tier_reasons(impostor.licence_code, seeds=seeds, driver=impostor.identity.id)
    )


# --------------------------------------------------------------------------------------------
# 4. The restriction bits (04:1867-1886).
# --------------------------------------------------------------------------------------------


def test_the_fact_to_bit_map_special_cases_four_of_the_twelve_codes() -> None:
    """04:1871-1875 claims "the fact and its bit differ by casing and nothing else", and
    `card.py`'s `LicenceFacts` docstring repeats it. It is false for four of the twelve.

    Eight bits do have a casing-identical fact. `REVENUE_GATE` is a rename of `revenue_gate_usd`;
    `NO_REDISTRIBUTION` is derived from a string comparison; `COPYLEFT_NETWORK` and
    `COPYLEFT_STRONG` are derived from SPDX-set membership. This test states the true count so a
    future `getattr(facts, member.name.lower())` refactor -- the code that made the claim look
    true -- fails here instead of raising `AttributeError` on four members.
    """
    fields = {field.name for field in dataclasses.fields(LicenceFacts)}
    casing_identical = {bit for bit in Restriction if bit.name.lower() in fields}
    assert len(tuple(Restriction)) == 12
    assert len(casing_identical) == 8
    assert {bit.name for bit in set(Restriction) - casing_identical} == {
        "REVENUE_GATE",
        "NO_REDISTRIBUTION",
        "COPYLEFT_NETWORK",
        "COPYLEFT_STRONG",
    }


def test_agpl_is_the_network_bit_and_gpl_is_the_strong_one() -> None:
    """14:1620-1621: "AGPL's section 13 is the *network* clause ... using the wrong bit would let
    an artefact carrying it pass a policy that filters the other".

    The consequence is 10:2343-2349's: `ow serve --http` refuses at listener start on
    `copyleft_network` while the same driver is accepted for a local run. One merged COPYLEFT bit
    would have made that refusal impossible to express.
    """
    assert restrictions_of(facts(spdx="AGPL-3.0-or-later")) == {Restriction.COPYLEFT_NETWORK}
    assert restrictions_of(facts(spdx="GPL-3.0-only")) == {Restriction.COPYLEFT_STRONG}
    assert "AGPL-3.0-or-later" in COPYLEFT_NETWORK
    assert "AGPL-3.0-or-later" not in COPYLEFT_STRONG
    assert not COPYLEFT_NETWORK & COPYLEFT_STRONG


def test_lgpl_is_in_neither_copyleft_set_and_therefore_computes_open() -> None:
    """A reported departure, asserted so it cannot become an accident.

    14:1478 denies LGPL as a DEPENDENCY of omniweave, which is `tools/licences.toml`'s
    build-time mechanism with a different owner (14:1650: "three files, three jobs, no overlap").
    No plan line puts LGPL in either `COPYLEFT_NETWORK` or `COPYLEFT_STRONG`, and calling weak
    copyleft "strong" here would be this module inventing a licence reading. So an LGPL driver
    computes `open` unless another fact bites, and that is written down rather than discovered.
    """
    assert compute_tier(facts(spdx="LGPL-3.0-or-later"), seeds=NO_SEEDS) == "open"
    assert "LGPL-3.0-or-later" not in COPYLEFT_NETWORK | COPYLEFT_STRONG


def test_an_spdx_expression_matches_neither_copyleft_set() -> None:
    """04:1850 writes `spdx in COPYLEFT_NETWORK`: membership over the whole string.

    `"MIT OR AGPL-3.0-or-later"` therefore computes `open`. The hole is real and it is reported;
    what this test pins is that the behaviour is the plan's literal reading rather than a partial
    expression parser somebody added without a specification.
    """
    assert compute_tier(facts(spdx="MIT OR AGPL-3.0-or-later"), seeds=NO_SEEDS) == "open"


def test_a_zero_revenue_gate_is_not_a_restriction() -> None:
    """Why the Datalab cards write `revenue_gate_usd = 0` (04:2039-2044, 01:205-209).

    Clause 2(c) has NO revenue threshold -- 2(a) and 2(b) are the clauses with the $5,000,000
    carve-out, and they are a different clause. Recording 5000000 on those cards would record the
    wrong clause, so the tier has to come from `competitor_bar`, and a zero gate must contribute
    nothing at all.
    """
    assert restrictions_of(facts(revenue_gate_usd=0)) == frozenset()
    assert compute_tier(facts(revenue_gate_usd=0), seeds=NO_SEEDS) == "open"
    assert restrictions_of(facts(competitor_bar=True, revenue_gate_usd=0)) == {
        Restriction.COMPETITOR_BAR
    }


# --------------------------------------------------------------------------------------------
# 5. The acknowledgement file (04:1888-1919, DR16).
# --------------------------------------------------------------------------------------------


def test_the_plans_worked_ack_row_loads_as_written(plan: PlanDocs) -> None:
    """04:1897-1908, transcribed. The plan's row is the fixture, so this grammar is not a superset.

    The digest is checked against the document too, because 04:1902 and 14:1614 print the same
    value in two places and a fixture that drifted from both would still pass every other test in
    this file.
    """
    acks = load_acks(PLAN_ACK_FILE.encode("utf-8"), source="omniweave.acks.toml")
    row = acks.get("parse.pdf.pymupdf", AckWhich.CODE)
    assert row is not None
    assert row.licence_sha256 == PYMUPDF_LICENCE_DIGEST
    assert row.which == "code"
    assert row.tier == "restricted"
    assert row.restrictions == ("copyleft_network",)
    assert row.acknowledged_by == "legal@example.com"
    assert row.acknowledged_at == "2026-08-30T09:12:00Z"
    plan.require()
    assert plan.grep(re.escape(PYMUPDF_LICENCE_DIGEST), documents=["04-driver-system.md"])


def test_licence_sha256_is_over_the_raw_bytes_of_the_text() -> None:
    """The digest an ack is bound to, pinned against three mutations of one fixture.

    Over bytes and not over meaning: the whitespace row is the one that matters, because a
    normalising digest would make a relicence that only moved whitespace invisible, and an ack
    bound to it would survive a text it was never given for.
    """
    assert licence_sha256(LICENCE_TEXT) == LICENCE_DIGEST
    assert licence_sha256(RELICENSED_TEXT) == RELICENSED_DIGEST
    assert licence_sha256(RECASED_TEXT) == RECASED_DIGEST
    assert licence_sha256(WHITESPACE_TEXT) == WHITESPACE_DIGEST
    assert len({LICENCE_DIGEST, RELICENSED_DIGEST, RECASED_DIGEST, WHITESPACE_DIGEST}) == 4


def test_a_mutated_licence_yields_licence_ack_stale_with_the_hash_diff_printed() -> None:
    """04:1913's REQUIRED test, and 00:404's, and DR16's (01:211).

    The ack is bound to `LICENCE_DIGEST`. The installed text is `RELICENSED_TEXT`, one character
    different, and both digests here are pinned literals -- if this test computed the expected
    digest from the mutated bytes it would be asserting that sha256 is a function, and would pass
    just as happily against an ack bound to nothing.

    The message must print the DIFF and not merely the verdict: both digests in full, because a
    truncated hash in a refusal is a hash nobody can check, and the index where they diverge,
    because these two share the prefix `sha256:eb`.
    """
    acks = AckSet(
        rows={
            ("parse.pdf.pymupdf", AckWhich.CODE): Ack(
                driver="parse.pdf.pymupdf",
                licence_sha256=LICENCE_DIGEST,
                which=AckWhich.CODE,
                tier="restricted",
                acknowledged_by="legal@example.com",
                acknowledged_at="2026-08-30T09:12:00Z",
            )
        }
    )
    verdict = check_ack(
        driver="parse.pdf.pymupdf",
        which=AckWhich.CODE,
        tier=LicenceTier.RESTRICTED,
        installed=RELICENSED_DIGEST,
        acks=acks,
    )
    assert verdict.status == "stale"
    assert not verdict.valid
    assert verdict.first_difference == RELICENSED_FIRST_DIFFERENCE
    message = verdict.message
    assert message.startswith("LICENCE_ACK_STALE ")
    assert ACK_STALE_CODE == "LICENCE_ACK_STALE"
    assert LICENCE_DIGEST in message
    assert RELICENSED_DIGEST in message
    assert f"index {RELICENSED_FIRST_DIFFERENCE}" in message
    assert "ow drivers ack parse.pdf.pymupdf" in message

    unchanged = check_ack(
        driver="parse.pdf.pymupdf",
        which=AckWhich.CODE,
        tier=LicenceTier.RESTRICTED,
        installed=LICENCE_DIGEST,
        acks=acks,
    )
    assert unchanged.status == "ok"
    assert unchanged.valid


def test_the_hash_diff_index_points_at_the_first_differing_character() -> None:
    """Three mutations of one text, three pinned indices, and one identical pair.

    The recased and whitespace mutations both diverge at index 7 -- the first character after
    `sha256:` -- and the version bump diverges at 9. Pinned, because an index computed from the
    two digests inside the test would agree with the property under test by construction.

    The status is asserted beside every index. Without that, this test reads three indices off a
    verdict whose status it never looks at, and stays green with the staleness comparison in
    `check_ack` deleted outright -- which was measured, not supposed.
    """
    acks = AckSet(
        rows={
            ("d", AckWhich.CODE): Ack(
                driver="d",
                licence_sha256=LICENCE_DIGEST,
                which=AckWhich.CODE,
                tier="restricted",
                acknowledged_by="legal@example.com",
                acknowledged_at="2026-08-30T09:12:00Z",
            )
        }
    )

    def verdict_for(installed: str) -> AckVerdict:
        return check_ack(
            driver="d",
            which=AckWhich.CODE,
            tier=LicenceTier.RESTRICTED,
            installed=installed,
            acks=acks,
        )

    for digest, index in ((RELICENSED_DIGEST, 9), (RECASED_DIGEST, 7), (WHITESPACE_DIGEST, 7)):
        found = verdict_for(digest)
        assert found.status == "stale", digest
        assert found.first_difference == index, digest
        assert f"index {index}" in found.message, digest
    same = verdict_for(LICENCE_DIGEST)
    assert same.status == "ok"
    assert same.first_difference == -1


def test_an_ack_covers_one_licensed_artefact_and_not_the_other() -> None:
    """04:1903: "one row per licensed artefact".

    The Datalab trap is exactly a permissive code licence over restrictive weights (01:205-209),
    so an operator who accepted the code licence has NOT accepted the weights licence. A
    code-side row must therefore leave the weights side unacknowledged.
    """
    acks = load_acks(PLAN_ACK_FILE.encode("utf-8"), source="omniweave.acks.toml")
    weights_side = check_ack(
        driver="parse.pdf.pymupdf",
        which=AckWhich.WEIGHTS,
        tier=LicenceTier.RESTRICTED,
        installed=PYMUPDF_LICENCE_DIGEST,
        acks=acks,
    )
    assert weights_side.status == "missing"
    assert not weights_side.valid
    assert "LICENCE_ACK_MISSING" in weights_side.message


def test_a_restricted_driver_on_a_fresh_install_is_refused_for_want_of_an_ack() -> None:
    """04:1915-1916: refused twice over on a fresh install, "once by the tier allowlist and once
    by the missing ack".

    The allowlist half is the caller's -- `[licence] allow_tiers = ["open"]` is a selector this
    module deliberately does not read. This is the other half, and it is asserted against an EMPTY
    ack set with a consequence attached, because an assertion that an empty set is empty proves
    nothing on its own.
    """
    empty = load_acks(b"ack_version = 1\n", source="omniweave.acks.toml")
    assert len(empty.rows) == 0
    verdict = check_ack(
        driver="parse.pdf.pymupdf",
        which=AckWhich.CODE,
        tier=LicenceTier.RESTRICTED,
        installed=PYMUPDF_LICENCE_DIGEST,
        acks=empty,
    )
    assert verdict.status == "missing"
    assert not verdict.valid


@pytest.mark.parametrize(
    ("tier", "status"),
    [
        (LicenceTier.OPEN, "not_required"),
        (LicenceTier.COMMERCIAL, "not_required"),
        (LicenceTier.FORBIDDEN, "not_required"),
        (LicenceTier.RESTRICTED, "missing"),
    ],
)
def test_only_a_restricted_tier_requires_an_acknowledgement(tier: LicenceTier, status: str) -> None:
    """04:1890 binds the ack requirement to `restricted` and to nothing else.

    `forbidden` reports `not_required` rather than `missing` because there is no ack that would
    help: 04:2033, "there is no configuration in which omniweave may run it". Reporting a
    forbidden driver as merely unacknowledged would suggest a form to fill in.
    """
    verdict = check_ack(
        driver="parse.pdf.pymupdf",
        which=AckWhich.CODE,
        tier=tier,
        installed=PYMUPDF_LICENCE_DIGEST,
        acks=AckSet(),
    )
    assert verdict.status == status


def test_two_rows_for_one_driver_and_artefact_is_a_hard_error_at_load() -> None:
    """04:1914: "an ack is a decision, and two decisions is none".

    Two rows differing only in `acknowledged_by` is the realistic shape -- two people each
    recording their own approval -- and it is refused, because nothing downstream could choose
    between them and a silent last-wins would make the file unreviewable.
    """
    doubled = PLAN_ACK_FILE + PLAN_ACK_FILE.split("ack_version = 1\n", 1)[1].replace(
        "legal@example.com", "counsel@example.com"
    )
    with pytest.raises(ConfigError) as caught:
        load_acks(doubled.encode("utf-8"), source="omniweave.acks.toml")
    assert "two [[ack]] rows" in str(caught.value)
    assert caught.value.EXIT == 1


def test_the_same_driver_may_acknowledge_both_of_its_licences() -> None:
    """The uniqueness key is the PAIR, so a code row and a weights row coexist.

    Without this, a driver shipping licensed weights under licensed code could not be
    acknowledged at all -- which is the only shape 04:1903's "one row per licensed artefact"
    exists to allow.
    """
    both = PLAN_ACK_FILE + PLAN_ACK_FILE.split("ack_version = 1\n", 1)[1].replace(
        'which = "code"', 'which = "weights"'
    )
    acks = load_acks(both.encode("utf-8"), source="omniweave.acks.toml")
    assert len(acks.rows) == 2
    assert acks.get("parse.pdf.pymupdf", AckWhich.WEIGHTS) is not None


def test_the_ack_grammar_has_no_expires_key() -> None:
    """14:1645-1648: "There is deliberately no `expires` field."

    An ack is void when the licence text changes and at no other time; an expiry "would make a
    legal decision lapse silently on a Tuesday". So the key is refused rather than ignored, and
    the refusal says why -- an operator who wrote one was reaching for a review cadence, which
    `ow drivers check --posture` provides by printing `acknowledged_at`.
    """
    assert "expires" not in ACK_ROW_KEYS
    with pytest.raises(ConfigError) as caught:
        load_acks(
            (PLAN_ACK_FILE + 'expires = "2027-01-01"\n').encode("utf-8"),
            source="omniweave.acks.toml",
        )
    assert "expires" in str(caught.value)


@pytest.mark.parametrize(
    ("what", "text"),
    [
        ("a newer grammar", "ack_version = 2\n"),
        ("no version at all", "[[ack]]\ndriver = 'x'\n"),
        ("an unknown top-level key", "ack_version = 1\nacks = []\n"),
        ("a single-bracket table", "ack_version = 1\n[ack]\ndriver = 'x'\n"),
        (
            "a missing required key",
            'ack_version = 1\n[[ack]]\ndriver = "x"\nwhich = "code"\n',
        ),
        (
            "an unknown which",
            PLAN_ACK_FILE.replace('which = "code"', 'which = "model"'),
        ),
        (
            "a restriction outside the vocabulary",
            PLAN_ACK_FILE.replace('["copyleft_network"]', '["copyleft_ish"]'),
        ),
        (
            "an empty acknowledged_by",
            PLAN_ACK_FILE.replace('acknowledged_by = "legal@example.com"', 'acknowledged_by = ""'),
        ),
    ],
)
def test_a_malformed_acknowledgement_file_is_refused_at_load(what: str, text: str) -> None:
    """Every one of these is a consent record that could be MISREAD rather than not read.

    A file from a newer grammar, a row whose `which` names an artefact this build does not know,
    a restriction spelled `copyleft_ish` -- each would leave a decision partly understood, and a
    decision partly understood is worse than a file that will not load. 04:1975 makes an
    unreadable configuration exit 1, which is `ConfigError`.
    """
    with pytest.raises(ConfigError) as caught:
        load_acks(text.encode("utf-8"), source="omniweave.acks.toml")
    assert caught.value.EXIT == 1, what


def test_an_ack_rows_tier_is_a_witness_and_not_an_authority() -> None:
    """04:1904 puts a `tier` key in the ack row, and DR15 says no file may declare a tier.

    Both are true because the row's tier is the tier as computed on the day the decision was
    made: a witness, compared and never trusted. This is DR15's mislabel arriving through the
    consent file instead of through the card, and 04:1975-1976 makes it exit 1.
    """
    acks = load_acks(
        PLAN_ACK_FILE.replace('tier = "restricted"', 'tier = "open"').encode("utf-8"),
        source="omniweave.acks.toml",
    )
    row = acks.get("parse.pdf.pymupdf", AckWhich.CODE)
    assert row is not None
    assert row.tier == "open"
    with pytest.raises(ConfigError) as caught:
        require_computed_tier(
            driver=row.driver,
            stored=row.tier,
            computed=LicenceTier.RESTRICTED,
            source="omniweave.acks.toml",
        )
    assert caught.value.EXIT == 1
    assert "omniweave.acks.toml" in str(caught.value)


# --------------------------------------------------------------------------------------------
# 6. The Grant (AP-4, 01:1091; 14:806-807; 14:890).
# --------------------------------------------------------------------------------------------

GRANT = {
    "grant_id": "grant-2026-011",
    "dpa_ref": "DPA-2026-014 clause 7",
    "approver": "legal@example.com",
    "expires": "2027-01-01T00:00:00Z",
    "scope": "corpus:contracts-2026",
}


def test_a_grant_without_a_dpa_ref_cannot_be_constructed() -> None:
    """AP-4 (01:1091): "the mechanism exists, the audit finds it, and it has never once run".

    Three ways one could fail to name an agreement and be let through anyway: omit the argument,
    pass an empty string, pass whitespace. A required field policed by a validator that some code
    path skips is precisely AP-4's shape, so the argument is positionally required by the type
    itself and the blank forms raise from `__post_init__` -- which `dataclasses.replace()` also
    runs, so a Grant cannot be edited into an invalid one either.
    """
    with pytest.raises(TypeError):
        Grant(  # type: ignore[call-arg]
            grant_id=GRANT["grant_id"],
            approver=GRANT["approver"],
            expires=GRANT["expires"],
            scope=GRANT["scope"],
        )
    for blank in ("", "   ", "\t\n"):
        with pytest.raises(ValueError, match="dpa_ref is required"):
            Grant(**{**GRANT, "dpa_ref": blank})
    valid = Grant(**GRANT)
    with pytest.raises(ValueError, match="dpa_ref is required"):
        dataclasses.replace(valid, dpa_ref="")


def test_the_dpa_ref_field_carries_no_default_of_any_kind() -> None:
    """The structural half of the assertion above, and the half a refactor breaks silently.

    `Grant(dpa_ref="")` raising is a runtime check; `dpa_ref: str = ""` appearing in the type
    would keep that check and still let every caller omit the field. So the absence of a default
    and of a `default_factory` is asserted on the field itself.
    """
    field = {f.name: f for f in dataclasses.fields(Grant)}["dpa_ref"]
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING


def test_every_grant_prints_its_dpa_ref_in_the_run_manifest() -> None:
    """01:1091 requires the `dpa_ref` "printed in every affected run manifest"; 14:890 lists
    "`Grant` ids and `dpa_ref`s" among a run manifest's contents.

    The key list is pinned as a literal tuple rather than read from `GRANT_MANIFEST_FIELDS`: a
    manifest's columns are a published contract, and a test that imported the constant it is
    checking would pass through any rename of it. The two are then asserted to agree with the
    type's own fields, so a field added to `Grant` and forgotten here is a finding.
    """
    row = Grant(**GRANT).manifest_row()
    assert tuple(row) == ("grant_id", "dpa_ref", "approver", "expires", "scope")
    assert row["dpa_ref"] == "DPA-2026-014 clause 7"
    assert tuple(field.name for field in dataclasses.fields(Grant)) == GRANT_MANIFEST_FIELDS


def test_a_dpa_ref_is_otherwise_unvalidated_on_purpose() -> None:
    """14:806-807: "validating it would imply omniweave can tell whether your data-processing
    agreement covers this, which it cannot. Naming it forces someone to write down which
    agreement they are relying on."

    So an unhelpful-but-present reference is accepted, and that is the design rather than a gap:
    the audit reads the manifest, and the manifest now names something a human chose to write.
    """
    assert Grant(**{**GRANT, "dpa_ref": "see wiki"}).manifest_row()["dpa_ref"] == "see wiki"


@pytest.mark.parametrize("field_name", ["grant_id", "approver", "expires", "scope"])
def test_a_grant_names_its_id_approver_expiry_and_scope(field_name: str) -> None:
    """The glossary's Grant "carrying a required (deliberately unvalidated) `dpa_ref`, an expiry
    and an approver", scoped to a corpus, plus 05:2820's `route_decision.grant_id`.

    A grant with an empty approver is a decision nobody made, so each is refused for the same
    reason `dpa_ref` is -- the field exists to make someone write something down.
    """
    with pytest.raises(ValueError, match=f"names its {field_name}"):
        Grant(**{**GRANT, field_name: ""})


def test_a_grant_expiry_must_carry_a_timezone_and_the_clock_is_a_parameter() -> None:
    """A naive expiry names a different instant on every machine the grant covers, and a site
    grant covers a fleet. And `is_active` takes `now`, because a value type that read the wall
    clock would make every test of it a test of the day it ran.
    """
    with pytest.raises(ValueError, match="timezone offset"):
        Grant(**{**GRANT, "expires": "2027-01-01T00:00:00"})
    with pytest.raises(ValueError, match=r"not a valid|Invalid isoformat"):
        Grant(**{**GRANT, "expires": "next Tuesday"})
    grant = Grant(**GRANT)
    assert grant.is_active(dt.datetime(2026, 12, 31, tzinfo=dt.UTC))
    assert not grant.is_active(dt.datetime(2027, 1, 2, tzinfo=dt.UTC))
    with pytest.raises(ValueError, match="clocks are parameters"):
        grant.is_active(dt.datetime(2026, 12, 31))  # noqa: DTZ001 -- the naive value IS the case


# --------------------------------------------------------------------------------------------
# 7. Purity and the lazy surface.
# --------------------------------------------------------------------------------------------


def test_a_bare_import_of_omniweave_core_does_not_load_the_licence_module(
    interpreter: Interpreter,
) -> None:
    """G17 is about the nine lazy names, and this module is not one of them -- but it imports
    `drivers.card`, which is large, and `import omniweave_core` pays for every module it touches
    (G23, G26's 250 ms warm hook budget).

    A fresh interpreter is the only witness: once a pytest session has imported half the tree for
    its own reasons, `sys.modules` can no longer answer the question.
    """
    loaded = interpreter.modules_added_by("import omniweave_core")
    assert "omniweave_core.drivers.licence" not in loaded
    assert "omniweave_core.drivers.card" not in loaded


# --------------------------------------------------------------------------------------------
# 8. What the mutation pass found. Every test below was proved RED under a named mutation of
#    `licence.py` and GREEN with that mutation reverted; the mutation is named in each
#    docstring, because "this test would have caught X" is a claim like any other.
# --------------------------------------------------------------------------------------------

LICENCE_MODULE_CONTAINERS = (
    "ACK_ROW_KEYS",
    "ACK_ROW_REQUIRED",
    "ACK_VERSIONS_SUPPORTED",
    "COPYLEFT_NETWORK",
    "COPYLEFT_STRONG",
    "GRANT_MANIFEST_FIELDS",
    "TIER_ORDER",
    "_BITS_OUTSIDE_THE_TIER",
    "_BIT_FROM_FACT",
)
"""Every module-level collection `licence.py` is allowed to hold, pinned as literals.

16-roadmap.md:483 is the whole reason this list is closed: "the separate denylist and
`weights_licence_md5` are struck, so this is one mechanism rather than two that can disagree", and
04:2019-2020 says the seed set "absorbs D4's two separate licence-denylist mechanisms, both of
which are struck". A denylist is a collection. So a NEW module-level collection here is either a
transcription of something the plan owns -- in which case it belongs in this tuple with the plan
line beside it -- or it is the second mechanism the plan struck.

Nine names, and none of them is a refusal set except by way of the `seeds` ARGUMENT: two SPDX sets
that raise the tier to `restricted` and never to `forbidden`, the tier ladder, the fact-to-bit map
and its two-member exception, and four ack/manifest grammars."""

TIER_OF_GLOBALS = ("LicenceTier", "_BITS_OUTSIDE_THE_TIER", "restrictions_of")
"""Every module-level name the BODY of `tier_of()` may read.

`seeds` is absent because it is a PARAMETER, and that is the property under test: the `forbidden`
arm of 04:1844's ladder consults the set it was handed and nothing the module keeps for itself. A
second denylist has to be reachable from here to have any effect, so pinning this tuple is what
makes "one mechanism rather than two" (16:483) a checkable claim rather than a comment."""


def _function_globals(name: str) -> tuple[str, ...]:
    """The non-builtin module-level names the BODY of `licence.py`'s `name` reads.

    Over the parsed source rather than `__code__.co_names`, because `co_names` also carries
    attribute names (`FORBIDDEN`, `seeded`) and would drown the signal. Only `fn.body` is walked,
    so the annotations in the signature -- which name types this module imports and must -- are
    out of scope. Parameters and locals are subtracted, because a parameter is exactly what a
    refusal set is supposed to be.
    """
    tree = ast.parse(Path(licence_module.__file__).read_text(encoding="utf-8"))
    found = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )
    bound = {arg.arg for arg in (*found.args.args, *found.args.kwonlyargs)}
    read: set[str] = set()
    for statement in found.body:
        for node in ast.walk(statement):
            if isinstance(node, ast.Name):
                (read if isinstance(node.ctx, ast.Load) else bound).add(node.id)
    return tuple(sorted(read - bound - set(dir(builtins))))


def test_the_seed_set_is_the_only_refusal_mechanism_in_the_module() -> None:
    """16-roadmap.md:483 and 04:2019-2020: ONE mechanism, not two that can disagree.

    Three ways a second denylist could arrive, all closed here. It could be a new module-level
    collection, so the collections are pinned by name. It could be consulted from the ladder, so
    the module-level names `tier_of()`'s body reads are pinned. Or it could be the one the plan
    struck by name -- `weights_licence_md5` -- so the token `md5` is required absent from the
    module's CODE, with comments and string literals stripped: the module docstring legitimately
    prints the Datalab `MODEL_LICENSE`'s md5 as a receipt (01:205-209), and a mention is not a
    definition site.

    MUTATION MEASURED: adding a `LICENCE_DENYLIST_SPDX` frozenset, a `WEIGHTS_LICENCE_MD5_DENY`
    frozenset and a `_second_denylist_hit()` consulted from `tier_of`'s `forbidden` arm left every
    other test in this file green -- including the case where the second mechanism supersedes the
    first and returns the right answer for the wrong reason. A driver could have been refused by a
    list nobody voted for, and 04:2016's authoritative seed set silently bypassed.
    """
    containers = tuple(
        sorted(
            name
            for name, value in vars(licence_module).items()
            if not name.startswith("__")
            and not isinstance(value, type)
            and isinstance(value, frozenset | set | tuple | list | dict | MappingProxyType)
        )
    )
    assert containers == LICENCE_MODULE_CONTAINERS
    assert _function_globals("tier_of") == TIER_OF_GLOBALS

    source = Path(licence_module.__file__).read_text(encoding="utf-8")
    code = [
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type in (tokenize.NAME, tokenize.OP, tokenize.NUMBER)
    ]
    assert len(code) > 1000, "the module tokenised to almost nothing; the check below is empty"
    assert not [token for token in code if "md5" in token.lower()]
    assert "e1f69b64dee2f1641a9b1ab12adf24d6" in source, (
        "the Datalab md5 is the receipt the module docstring carries; if it is gone, the md5 "
        "assertion above has stopped being a narrow claim about code"
    )


def test_no_licence_fact_computes_forbidden_without_a_seed_that_says_so() -> None:
    """The behavioural half of "one mechanism": `forbidden` has exactly ONE producer.

    04:1844-1845 gives the `forbidden` rule two arms and both are keyed on the shipped tombstones
    -- an id in the set, or a `licence_sha256` matching one. So with `LicenceSeeds()` handed in,
    NOTHING a `[licence.*]` table can say may reach `forbidden`, and that is asserted over the
    complete lattice of the six boolean facts rather than over a list of examples: an example list
    proves a rule is wide enough and never that it is narrow enough. Every other restricting fact
    is held at its worst value throughout, so each of the 64 rows carries between six and nine of
    04:1847-1850's ten `restricted` producers -- `copyleft_strong` is the one that cannot fire,
    because the fixed `spdx` is the network-copyleft spelling.

    The Datalab digest is then fed in with an EMPTY seed set, because that is the exact card a
    built-in denylist would refuse for the wrong reason. It must compute `open`: the digest is
    forbidden BY THE SEED SET (04:2016) and by nothing the module remembers on its own, which is
    what makes 04:2018's rename survival a property of the catalog rather than of this file.
    """
    booleans = (
        "output_share_alike",
        "competitor_bar",
        "requires_credential",
        "attribution_per_output",
        "no_model_training",
        "remote_kill_switch",
    )
    seen: set[str] = set()
    for mask in range(1 << len(booleans)):
        table = facts(
            **{name: bool(mask & (1 << index)) for index, name in enumerate(booleans)},
            spdx="AGPL-3.0-or-later",
            redistribution="restricted",
            territory_excluded=("EU",),
            field_of_use_excluded=("insurance",),
            revenue_gate_usd=5_000_000,
            mau_gate=100_000_000,
        )
        computed = compute_tier(table, table, seeds=LicenceSeeds())
        assert computed != "forbidden", f"mask {mask:06b} reached forbidden with no seed"
        seen.add(str(computed))
    assert seen == {"restricted", "commercial"}, seen

    assert compute_tier(facts(licence_sha256=DATALAB_SEED), seeds=LicenceSeeds()) == "open"
    assert compute_tier(facts(), facts(licence_sha256=DATALAB_SEED), seeds=LicenceSeeds()) == (
        "open"
    )


def test_the_seeds_argument_carries_no_default_of_any_kind() -> None:
    """`compute_tier`'s module docstring calls a default of "no seeds" AP-4's shape exactly.

    AP-4 (01:1091) is "the mechanism exists, the audit finds it, and it has never once run", and a
    `seeds: LicenceSeeds = LicenceSeeds()` default is that failure precisely: a caller who forgot
    the argument gets a `forbidden` check that can never fire, and no reviewer sees a call site
    that says so. `Grant.dpa_ref` has exactly this assertion in section 6; the three functions that
    take a seed set had none.

    MUTATION MEASURED: giving `tier_of`, `compute_tier` and `tier_from_card` that default left this
    file green, because every existing call site passes `seeds` explicitly -- which is the point.
    Keyword-only is asserted beside it, because a positional third parameter could be filled by
    accident from a `weights`-shaped value.
    """
    for name in ("tier_of", "compute_tier", "tier_from_card"):
        signature = inspect.signature(getattr(licence_module, name))
        seeds = signature.parameters["seeds"]
        assert seeds.default is inspect.Parameter.empty, name
        assert seeds.kind is inspect.Parameter.KEYWORD_ONLY, name


def test_the_lookup_refuses_an_empty_digest_even_when_the_stored_set_holds_one() -> None:
    """The SECOND of the module's two guards against a blanket `forbidden`, put directly.

    `LicenceSeeds.__post_init__` strips the empty digest, so the guard inside `seeded()` cannot be
    reached through the constructor -- which is why
    `test_a_card_with_no_licence_digest_is_never_matched_by_an_empty_seed` proves the BUILDER's
    guard twice and not this one.

    MUTATION MEASURED: deleting `or not facts.licence_sha256` from `seeded()` left this file green.
    So the set is forced past `__post_init__` with `object.__setattr__`, which is the state a
    future refactor of the builder would leave behind, and the question is put to the LOOKUP: a
    card with no digest of its own is not a member, and a card with one still is. Both halves,
    because a `seeded()` that returned `False` unconditionally would satisfy the first alone.
    """
    forced = LicenceSeeds(digests=frozenset({LICENCE_DIGEST}))
    object.__setattr__(forced, "digests", frozenset({"", LICENCE_DIGEST}))
    assert "" in forced.digests

    assert not forced.seeded(facts())
    assert compute_tier(facts(), seeds=forced) == "open"
    assert forced.seeded(facts(licence_sha256=LICENCE_DIGEST))
    assert compute_tier(facts(licence_sha256=LICENCE_DIGEST), seeds=forced) == "forbidden"


def test_a_truncated_acknowledged_digest_still_reports_where_the_two_diverge() -> None:
    """`first_difference`'s third branch: one digest is a PREFIX of the other.

    A hand-edited `omniweave.acks.toml` carrying a digest somebody pasted short is the realistic
    case, and it is the one where the two strings never disagree character by character.

    MUTATION MEASURED: replacing that branch with `return -1` left this file green -- and `-1` is
    the value the OK path uses for "they do not differ", printed inside a `LICENCE_ACK_STALE`
    refusal. The operator would be told the two texts are identical in the very message saying
    their consent is void.

    Both orders, because `min(len(a), len(b))` and `len(a)` are the same number in one of them.
    The index is a pinned literal: `sha256:` is 7 characters, the digest is 71, and a truncation
    to 11 diverges at 11 from either side.
    """
    short = LICENCE_DIGEST[:11]
    assert len(LICENCE_DIGEST) == 71
    assert LICENCE_DIGEST.startswith(short)

    truncated_ack = AckVerdict(
        status=AckStatus.STALE,
        driver="d",
        which=AckWhich.CODE,
        acknowledged=short,
        installed=LICENCE_DIGEST,
    )
    assert truncated_ack.first_difference == 11
    assert "index 11" in truncated_ack.message

    truncated_install = AckVerdict(
        status=AckStatus.STALE,
        driver="d",
        which=AckWhich.CODE,
        acknowledged=LICENCE_DIGEST,
        installed=short,
    )
    assert truncated_install.first_difference == 11
    assert "index 11" in truncated_install.message


def _one_row_ack_set(acknowledged: str) -> AckSet:
    """An `AckSet` holding one `code` row for driver `d`, bound to `acknowledged`."""
    return AckSet(
        rows={
            ("d", AckWhich.CODE): Ack(
                driver="d",
                licence_sha256=acknowledged,
                which=AckWhich.CODE,
                tier="restricted",
                acknowledged_by="legal@example.com",
                acknowledged_at="2026-08-30T09:12:00Z",
            )
        }
    )


@pytest.mark.parametrize(
    ("acknowledged", "installed", "status"),
    [
        (LICENCE_DIGEST.upper(), LICENCE_DIGEST, "ok"),
        (LICENCE_DIGEST, LICENCE_DIGEST.upper(), "ok"),
        ("unresolved:omniparse/LICENSE", "unresolved:omniparse/LICENSE", "ok"),
        ("unresolved:omniparse/LICENSE", "unresolved:omniparse/license", "stale"),
    ],
)
def test_an_ack_digest_folds_case_only_when_it_is_a_sha256(
    acknowledged: str, installed: str, status: str
) -> None:
    """`check_ack` normalises the way `LicenceSeeds` does, and the NARROWNESS is the point.

    A sha256's hex has one canonical casing, so an operator whose tooling wrote `SHA256:EB38...`
    has acknowledged the installed text and must not be told their consent is void. An
    `unresolved:` marker names a PATH -- `unresolved:omniparse/LICENSE` and
    `unresolved:omniparse/license` are two different files on a case-sensitive filesystem -- so
    folding case there would treat consent given for one text as consent for another.

    MUTATION MEASURED: neither direction was asserted through `check_ack` before. Replacing its
    two `_normalise_digest` calls with a blanket `.lower()` on both sides left this file green, and
    so did replacing them with a raw `!=`. Only `LicenceSeeds.seeded()` had the equivalent test,
    and consent is not the same mechanism as refusal.
    """
    verdict = check_ack(
        driver="d",
        which=AckWhich.CODE,
        tier=LicenceTier.RESTRICTED,
        installed=installed,
        acks=_one_row_ack_set(acknowledged),
    )
    assert verdict.status == status


def test_the_ack_row_grammar_is_the_eight_keys_the_plan_prints_and_no_others() -> None:
    """04-driver-system.md:1901-1908 prints eight keys in the worked `[[ack]]` row.

    Both tuples pinned as literals, in the plan's printed order. `ACK_ROW_KEYS` was previously
    pinned only against the absence of `expires` (14:1645), which is one key out of the infinity a
    closed grammar excludes.

    MUTATION MEASURED: adding `review_after` and `superseded_by` to `ACK_ROW_KEYS` left this file
    green. "A key nobody validates is a key nobody reads" is the module's own reason the set is
    closed, and an invented key in a file counsel signs is a sentence counsel did not read.
    """
    assert ACK_ROW_REQUIRED == (
        "driver",
        "licence_sha256",
        "which",
        "tier",
        "acknowledged_by",
        "acknowledged_at",
    )
    assert ACK_ROW_KEYS == (
        "driver",
        "licence_sha256",
        "which",
        "tier",
        "acknowledged_by",
        "acknowledged_at",
        "restrictions",
        "note",
    )


@pytest.mark.parametrize(
    "omitted",
    ["driver", "licence_sha256", "which", "tier", "acknowledged_by", "acknowledged_at"],
)
def test_an_ack_row_missing_any_single_required_key_is_exit_one_and_not_a_crash(
    omitted: str,
) -> None:
    """One key at a time, so each membership of `ACK_ROW_REQUIRED` is load-bearing.

    The existing malformed-file table has one row for this, and it omits FOUR keys at once --
    `licence_sha256`, `tier`, `acknowledged_by` and `acknowledged_at` -- so the `missing` list is
    populated whatever else `ACK_ROW_REQUIRED` holds, and no single membership of that tuple is
    load-bearing in it.

    MUTATION MEASURED: dropping `acknowledged_at` from `ACK_ROW_REQUIRED` while leaving it a legal
    key left this file green -- and a row omitting it then reached `str(table["acknowledged_at"])`
    and raised `KeyError`. 04:1975 makes an unreadable configuration exit 1; a `KeyError` out of a
    consent-file parser is a traceback in place of a refusal, and `ConfigError.EXIT` never runs.

    So the assertion is `ConfigError` AND that the message names the key, neither of which a
    `KeyError` can satisfy.
    """
    original = PLAN_ACK_FILE.splitlines(keepends=True)
    kept = [line for line in original if not line.startswith(f"{omitted} = ")]
    assert len(kept) == len(original) - 1, omitted
    with pytest.raises(ConfigError) as caught:
        load_acks("".join(kept).encode("utf-8"), source="omniweave.acks.toml")
    assert caught.value.EXIT == 1, omitted
    assert omitted in str(caught.value), omitted


def test_a_note_that_is_not_a_string_is_refused_rather_than_coerced() -> None:
    """`note` is prose, and prose that arrived as a number is a row somebody generated wrongly.

    Coercing it with `str()` would put `1699` into the file counsel reads and lose the fact that
    nothing was written. MUTATION MEASURED: replacing `_ack_note`'s type check with `str(value)`
    left this file green -- it was the one `[[ack]]` value whose validation had no test at all.
    """
    with pytest.raises(ConfigError) as caught:
        load_acks(
            PLAN_ACK_FILE.replace(
                'note = "AGPL-3.0 accepted for internal-only deployment; ticket LEGAL-4471."',
                "note = 1699",
            ).encode("utf-8"),
            source="omniweave.acks.toml",
        )
    assert "note must be a string" in str(caught.value)
    assert caught.value.EXIT == 1


def test_the_loaded_ack_set_reports_the_version_the_file_declared() -> None:
    """`load_acks` is the only constructor of `AckSet`, so its `ack_version` is the FILE's.

    MUTATION MEASURED: `load_acks` returned a hardcoded `ack_version=1`, and changing that literal
    to `99` left this file green -- `AckSet.ack_version` was a field no code path could be wrong
    about and no test read, which is the definition of a value that proves nothing.

    `ACK_VERSIONS_SUPPORTED` is `{1}` today, so the only loadable version is 1 and the runtime
    assertion here is about provenance rather than about a second grammar. That is exactly when it
    is worth writing: the day an `ack_version = 2` is admitted, a `load_acks` that forwards the
    parsed version reports 2 and one that returns a literal reports 1, and only one of those is
    the file the operator wrote. The source assertion is what makes the claim checkable while
    `ACK_VERSIONS_SUPPORTED` still has one member.

    The four rejected spellings are the second finding this test records, and it was a live bug
    rather than a latent one. Python makes `True in frozenset({1})` and `1.0 in frozenset({1})`
    both true, so `ack_version = true` LOADED, as version 1, out of the one file whose whole
    reason for existing is that "a boolean in the main config cannot be void" (02:1166). Membership
    in a `frozenset[int]` is not a type check, and a consent file's grammar version is the last
    place to discover that.
    """
    acks = load_acks(PLAN_ACK_FILE.encode("utf-8"), source="omniweave.acks.toml")
    assert acks.ack_version == 1
    assert sorted(licence_module.ACK_VERSIONS_SUPPORTED) == [1]
    source = Path(licence_module.__file__).read_text(encoding="utf-8")
    assert "ack_version=1)" not in source, (
        "load_acks must forward the version it PARSED; a literal at the return makes "
        "AckSet.ack_version a value no test and no caller can be wrong about"
    )

    for written in ("true", "false", "1.0", "'1'"):
        with pytest.raises(ConfigError) as caught:
            load_acks(f"ack_version = {written}\n".encode(), source="omniweave.acks.toml")
        assert "ack_version is" in str(caught.value), written
        assert caught.value.EXIT == 1, written


def test_a_missing_ack_refusal_prints_the_installed_digest_it_found_no_row_for() -> None:
    """`LICENCE_ACK_MISSING`'s message, which had no assertion beyond the code word.

    An operator about to run `ow drivers ack <driver>` has to know WHICH text they are accepting,
    and the refusal is where that digest is printed. 04:1973 requires a refusal to name "the
    driver, the clause refs and the exact command that would resolve it", and a consent prompt for
    an unnamed text is what INV-5 exists to prevent.

    MUTATION MEASURED: deleting the `installed` line from this branch left this file green; the
    existing test asserts only that `"LICENCE_ACK_MISSING"` appears somewhere in the string.
    """
    verdict = check_ack(
        driver="parse.pdf.pymupdf",
        which=AckWhich.CODE,
        tier=LicenceTier.RESTRICTED,
        installed=PYMUPDF_LICENCE_DIGEST,
        acks=AckSet(),
    )
    message = verdict.message
    assert message.startswith("LICENCE_ACK_MISSING ")
    assert PYMUPDF_LICENCE_DIGEST in message
    assert "ow drivers ack parse.pdf.pymupdf" in message


def test_a_refusal_names_the_clause_refs_the_card_recorded() -> None:
    """04:1973: the message names "the driver, the clause refs and the exact command".

    `clause_refs` is the reason that card field exists -- `parse.page.surya` records
    `Attachment A 2(c) at MODEL_LICENSE:58`, and a refusal printing `forbidden` alone sends the
    operator to read a licence somebody already paid to have read (04:1839, DR16).

    MUTATION MEASURED: deleting the `clause {ref}` lines from `tier_reasons()` left this file
    green. Nothing anywhere asserted that the field the plan requires in a refusal reaches one.

    Asserted through `require_computed_tier` as well as through the tuple, because the clause has
    to survive the trip into the exit-1 message and not merely exist in a return value.
    """
    table = facts(
        competitor_bar=True,
        clause_refs=("Attachment A 2(c) at MODEL_LICENSE:58", "LICENSE:1"),
    )
    reasons = tier_reasons(table, seeds=NO_SEEDS)
    assert "[licence.code] clause Attachment A 2(c) at MODEL_LICENSE:58" in reasons
    assert "[licence.code] clause LICENSE:1" in reasons

    with pytest.raises(ConfigError) as caught:
        require_computed_tier(
            driver="parse.page.thirdparty",
            stored="open",
            computed=LicenceTier.RESTRICTED,
            source="omniweave.lock",
            reasons=reasons,
        )
    assert "Attachment A 2(c) at MODEL_LICENSE:58" in str(caught.value)


def test_a_bit_that_does_not_raise_the_tier_says_so_in_the_reasons() -> None:
    """The two readings of the twelve codes disagree, and a refusal must not hide which is which.

    04:1869-1870 allocates twelve bits and 04:1847-1850's `restricted` rule reads ten facts, so
    `attribution_per_output` stamps a bit onto every row the driver produces (INV-16) and computes
    `open`. A reason line reading `attribution_per_output -> restricted` beside a computed `open`
    is a refusal that contradicts itself.

    MUTATION MEASURED: labelling the `_BITS_OUTSIDE_THE_TIER` clauses `-> restricted` like the
    other ten left this file green. `tier_reasons()` had exactly two call sites in the whole file
    -- the recorded-tier mismatch and the vetoed-id impostor -- and neither reached this branch.

    The suffix is asserted ABSENT for these two and PRESENT for a tenth producer in the same call,
    because a clause list that named nothing at all would satisfy the first half alone.
    """
    table = facts(attribution_per_output=True, no_model_training=True, competitor_bar=True)
    assert compute_tier(table, seeds=NO_SEEDS) == "restricted"
    reasons = tier_reasons(table, seeds=NO_SEEDS)
    assert "[licence.code] competitor_bar -> restricted" in reasons
    for outside in ("attribution_per_output", "no_model_training"):
        assert f"[licence.code] {outside} -> restricted" not in reasons
        assert (
            f"[licence.code] {outside} -> a restriction bit that does not raise the tier"
        ) in reasons

    alone = facts(attribution_per_output=True)
    assert compute_tier(alone, seeds=NO_SEEDS) == "open"
    assert not [line for line in tier_reasons(alone, seeds=NO_SEEDS) if "-> restricted" in line]


def test_a_grant_is_not_active_at_the_instant_it_expires() -> None:
    """`now < expires`, and the boundary is the only value at which `<` and `<=` differ.

    A `Grant` is a site-layer authorisation for egress (AP-4, 14:806-807), so this boundary
    decides one hosted call that either had a live authorisation or did not.

    MUTATION MEASURED: `now <= self.expires_at()` left this file green. The existing test asserts
    a day either side of the expiry, which both spellings satisfy.

    The instant is pinned as a literal `datetime`, not read back from `Grant.expires_at()`: a host
    that recomputed the expiry from the subject would be asserting agreement between two readings
    of one string rather than what the subject claimed.
    """
    grant = Grant(**GRANT)
    assert grant.expires == "2027-01-01T00:00:00Z"
    expiry = dt.datetime(2027, 1, 1, 0, 0, 0, tzinfo=dt.UTC)
    assert not grant.is_active(expiry)
    assert grant.is_active(expiry - dt.timedelta(microseconds=1))
    assert not grant.is_active(expiry + dt.timedelta(microseconds=1))
