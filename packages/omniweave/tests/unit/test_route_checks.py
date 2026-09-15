"""`omniweave.route.checks` and `omniweave.route.explain` against 05-ingest-and-routing.md §4.5.

The six checks here read the operator's installation, so every test builds one: a `frozenset` of
enabled driver ids, the workspace's real `driver.toml` cards, a `PriceBook` and the declared
`[retrieval.budget]`. **The cards are real** -- `omniweave-office`'s and `omniweave-pdf`'s, loaded
by the same `load_card()` a running framework uses -- because check 11's whole content is a
comparison against a card's `format_tokens`, and a synthetic card would be comparing this file
against itself.

Three measured results on the shipped policy, each asserted by name rather than by count:

* **check 6 reports exactly one warning and no error** -- `fields.extract`, which 05:1005 names:
  *"One rule in the shipped policy carries it -- `fields.extract`"*;
* **check 11 comes out EXACT on `decode.office-native`** -- the twelve tokens the rule names are
  the twelve `parse.office.anydoc` serves, both directions empty, which is what 05:3190's own rule
  comment claims;
* **check 13 reproduces section 10's 2,732** from olmocr's printed `[cost.model]` and §6.2's
  pricebook, against a shipped `micros_per_part` of 3,000.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from omniweave.route import checks as rc
from omniweave.route import demand as rd
from omniweave.route import evidence as ev
from omniweave.route import explain as rx
from omniweave.route import lint as rl
from omniweave.route import policy as rp
from omniweave.route.rung import Rung
from omniweave.route.spend import PriceBook
from omniweave_core.config import SHIPPED_DRIVERS
from omniweave_core.drivers.card import DriverCard, load_card

if TYPE_CHECKING:
    from pathlib import Path

CARDS = (
    "packages/omniweave-office/src/omniweave_office/driver.toml",
    "packages/omniweave-pdf/src/omniweave_pdf/driver.toml",
    "packages/omniweave-vision/src/omniweave_vision/driver.toml",
)
"""THREE since W5.6. The third is what turned six of this file's assertions from *"undecidable
because `parse.page.olmocr` has no card"* into verdicts."""

OLMOCR_CARD = "packages/omniweave-vision/src/omniweave_vision/driver.toml"

SIGNALS = (
    ("pdfium", "packages/omniweave-pdf/src/omniweave_pdf/signals.toml"),
    ("officexml", "packages/omniweave-office/src/omniweave_office/signals.toml"),
)

BUDGET = {
    "retrieval.budget.query_ms": 250,
    "retrieval.budget.hydration_reserve_ms": 40,
    "retrieval.budget.channel_ms": {
        "identity": 15,
        "exact": 25,
        "lexical": 50,
        "structural": 40,
        "semantic": 80,
    },
}
"""07:1108's own fence, and its own comment does the arithmetic: *"15 + 25 + 50 + 40 + 80 = 210,
+ 40 reserved = 250 against query_ms = 250"*. Exactly on the boundary, which is why check 3's
inequality is non-strict."""


@pytest.fixture(scope="module")
def registry(repo_root: Path) -> ev.SignalRegistry:
    specs = list(ev.builtin_specs())
    for provider, relative in SIGNALS:
        specs.extend(
            ev.load_signals((repo_root / relative).read_bytes(), provider=provider, origin=relative)
        )
    return ev.build_registry(specs)


@pytest.fixture(scope="module")
def shipped(registry: ev.SignalRegistry) -> rp.RoutePolicy:
    return rp.compile_policy([rp.builtin_layer()], registry=registry)


@pytest.fixture(scope="module")
def cards(repo_root: Path) -> dict[str, DriverCard]:
    loaded: dict[str, DriverCard] = {}
    for relative in CARDS:
        card = load_card((repo_root / relative).read_bytes(), origin="entry_point", source=relative)
        loaded[card.identity.id] = card  # type: ignore[union-attr] -- a card, never a tombstone
    return loaded


@pytest.fixture(scope="module")
def book() -> PriceBook:
    """Section 10's pricebook: *"`gpu_ms_micros = 0.3556`, `cpu_ms_micros = 0.00928`,
    `wall_ms_micros = 0.0`"* (05:3081)."""
    return PriceBook(
        version=1,
        currency="USD",
        effective_from="2026-01-01",
        rates={
            "local": {
                "gpu_ms": Decimal("0.3556"),
                "cpu_ms": Decimal("0.00928"),
                "wall_ms": Decimal("0"),
            }
        },
    )


@pytest.fixture(scope="module")
def installed(cards: dict[str, DriverCard]) -> rc.Installation:
    return rc.Installation(enabled=frozenset(SHIPPED_DRIVERS), cards=cards, retrieval=dict(BUDGET))


def _card(body: str, source: str) -> DriverCard:
    """`load_card` returns `DriverCard | Tombstone`; every fixture here is the first."""
    loaded = load_card(body.encode(), origin="entry_point", source=source)
    assert isinstance(loaded, DriverCard)
    return loaded


def _without_olmocr(installed: rc.Installation) -> rc.Installation:
    """The installation as it was BEFORE W5.6. Six of this file's assertions were about this
    state, and they are kept as assertions about an operator who has not installed
    `omniweave-vision` -- which 05:3055 makes a supported condition with a named degradation, not
    a transitional one."""
    return rc.Installation(
        enabled=installed.enabled,
        cards={k: v for k, v in installed.cards.items() if k != "parse.page.olmocr"},
        book=installed.book,
        retrieval=installed.retrieval,
    )


# --------------------------------------------------------------------------------------------
# 1. Checks 6 and 14 -- the exemption and its expiry.
# --------------------------------------------------------------------------------------------


def test_the_shipped_policy_has_exactly_one_check_six_warning_and_no_error(
    shipped: rp.RoutePolicy, installed: rc.Installation
) -> None:
    """05:1005: *"One rule in the shipped policy carries it -- `fields.extract`."*

    A warning because it declares `expect_unavailable = true`, which 05:1001 makes the second of the
    flag's three mechanical effects. Asserted by rule id, because "one warning" would still pass if
    the one were a different rule.
    """
    findings = rc.driver_not_enabled(shipped, installed)
    assert [(f.rule_id, f.severity) for f in findings] == [("fields.extract", "warning")]
    assert "parse.fields.lift" in findings[0].message


def test_a_rule_naming_an_absent_driver_without_the_flag_is_an_error(
    shipped: rp.RoutePolicy, cards: dict[str, DriverCard]
) -> None:
    """The other side of the same check. `[drivers] enabled` reduced to nothing enables nothing,
    so every driver-naming rule fails -- and `fields.extract` stays a warning, because the
    exemption is the rule's and not the configuration's."""
    findings = rc.driver_not_enabled(shipped, rc.Installation(cards=cards))
    severities = {f.severity for f in findings}
    assert severities == {"error", "warning"}
    warned = [f.rule_id for f in findings if f.severity == "warning"]
    assert warned == ["fields.extract"]
    assert len(findings) == len({rule.id for rule in shipped.rules if rule.then.driver})


def test_a_pin_gets_no_exemption(registry: ev.SignalRegistry) -> None:
    """A rule naming an absent driver is a path never taken; a pin naming one is an instruction
    that cannot be carried out, and 05:2817 makes a pin's `reason` and `expires` mandatory
    precisely because somebody is expected to be watching it."""
    body = (
        'surface = "route"\nschema = "omniweave.policy/1"\n\n'
        "[[pin]]\nunit = 'u1'\ndriver = 'parse.nope'\nreason = 'ticket 9'\n"
        "expires = '2099-01-01'\n"
    )
    policy = rp.compile_policy(
        [rp.load_layer(body.encode(), layer="site", origin="a test")], registry=registry
    )
    findings = rc.driver_not_enabled(policy, rc.Installation(enabled=frozenset({"parse.a"})))
    assert [(f.rule_id, f.severity) for f in findings] == [("pin:u1", "error")]
    assert "no expect_unavailable exemption" in findings[0].message


def test_check_fourteen_fires_the_day_the_driver_ships(
    shipped: rp.RoutePolicy, installed: rc.Installation
) -> None:
    """05:1002: *"the day an open-tier driver ships, the line that excused its absence fails the
    build instead of rotting into a permanent excuse."* On the shipped `[drivers] enabled` this is
    silent; add `parse.fields.lift` and it fires on the one rule that declared the exemption."""
    assert rc.unavailable_but_enabled(shipped, installed) == ()
    shipping = rc.Installation(enabled=installed.enabled | {"parse.fields.lift"})
    fired = rc.unavailable_but_enabled(shipped, shipping)
    assert [f.rule_id for f in fired] == ["fields.extract"]
    assert fired[0].code == "OW-P-024"
    assert rc.driver_not_enabled(shipped, shipping) == ()


# --------------------------------------------------------------------------------------------
# 2. Checks 9 and 11 -- a card, or an Undecided.
# --------------------------------------------------------------------------------------------


def test_check_nine_is_undecidable_for_a_driver_whose_card_is_not_installed(
    shipped: rp.RoutePolicy, installed: rc.Installation
) -> None:
    """`decode.part-text-unusable` and `decode.broken-font-encoding` declare `on_unknown = "match"`
    and both name `parse.page.olmocr`. On an installation without `omniweave-vision` the check has
    two subjects and can settle neither -- which is a sentence, not a pass, and 05:3055 makes that
    installation a supported one rather than a transitional one."""
    findings, undecided = rc.match_on_billed_api(shipped, _without_olmocr(installed))
    assert findings == ()
    assert [u.rule_id for u in undecided] == [
        "decode.part-text-unusable",
        "decode.broken-font-encoding",
    ]
    assert {u.reason for u in undecided} == {"driver-card-not-installed"}
    assert {u.key for u in undecided} == {"parse.page.olmocr"}


def test_check_nine_passes_on_local_compute_and_fires_on_billed_api(
    shipped: rp.RoutePolicy, installed: rc.Installation, repo_root: Path
) -> None:
    """olmocr declares `local_compute`, which 05:2438 says *"is what makes `ow route lint` check 9
    satisfiable by the shipped policy."* Install that card and the two rules pass; move the card's
    class to `billed_api` and both fire, which is the check earning its place.

    Since W5.6 the passing half needs no fixture at all: the shipped card declares
    `local_compute`, so `installed` already carries it."""
    findings, undecided = rc.match_on_billed_api(shipped, installed)
    assert findings == ()
    assert undecided == ()

    billed = _card(
        (repo_root / OLMOCR_CARD)
        .read_text(encoding="utf-8")
        .replace('"local_compute"', '"billed_api"'),
        "a test",
    )
    hostile = rc.Installation(
        enabled=installed.enabled, cards={**installed.cards, "parse.page.olmocr": billed}
    )
    fired, _ = rc.match_on_billed_api(shipped, hostile)
    assert [f.rule_id for f in fired] == [
        "decode.part-text-unusable",
        "decode.broken-font-encoding",
    ]
    assert all(f.code == "OW-P-012" for f in fired)


def test_check_eleven_is_exact_on_the_office_rule(
    shipped: rp.RoutePolicy, installed: rc.Installation, cards: dict[str, DriverCard]
) -> None:
    """05:3190's claim, measured: *"lint check 11 asserts that list is exactly anydoc's declared
    `[capability]` formats, so this rule cannot name a format the driver refuses -- which is what
    routing `html` or `md` here would have done."*

    Both directions are empty, which is stronger than the check itself (which is containment) and
    is the fact the rule's comment claims.
    """
    rule = next(r for r in shipped.rules if r.id == "decode.office-native")
    named = rc._format_literals(rule)
    served = frozenset(
        pair.token
        for pair in cards["parse.office.anydoc"].parse.format_tokens  # type: ignore[union-attr]
    )
    assert len(named) == 12
    assert named == served

    findings, undecided = rc.tokens_off_card(shipped, installed)
    assert findings == ()
    assert "decode.office-native" not in {u.rule_id for u in undecided}


def test_check_eleven_fires_on_a_token_the_driver_refuses(
    registry: ev.SignalRegistry, cards: dict[str, DriverCard]
) -> None:
    """`html` routed to anydoc -- 05:3190's own counter-example, which the shipped rule avoids."""
    body = (
        'surface = "route"\nschema = "omniweave.policy/1"\n\n'
        '[[rule]]\nid = "decode.wrong"\nrung = "DECODE"\n'
        'when = { "unit.format" = { in = ["docx", "html"] } }\n'
        'then = { driver = "parse.office.anydoc" }\n'
    )
    policy = rp.compile_policy(
        [rp.load_layer(body.encode(), layer="site", origin="a test")], registry=registry
    )
    findings, _ = rc.tokens_off_card(
        policy, rc.Installation(enabled=frozenset({"parse.office.anydoc"}), cards=cards)
    )
    assert [f.rule_id for f in findings] == ["decode.wrong"]
    assert "html" in findings[0].message
    assert "docx" not in findings[0].message


# --------------------------------------------------------------------------------------------
# 3. Check 13 -- section 10's arithmetic.
# --------------------------------------------------------------------------------------------


def test_reserved_micros_reproduces_section_tens_two_thousand_seven_hundred_and_thirty_two(
    installed: rc.Installation, book: PriceBook
) -> None:
    """05:3085: *"`reserved_micros` = 2400 x 3.2 x 0.3556 + 1.11 = 2730.8 + 1.11 = **2732**"*.

    The p95 multiple scales `gpu_ms` as well as `tokens_out` (05:3167), and `tokens_out` prices to
    zero because section 6.2's book declares no rate for it -- which is `PriceBook.undeclared()`'s
    subject and not this check's.
    """
    assert rc.reserved_micros(installed.cards["parse.page.olmocr"], book) == 2732


def test_check_thirteen_passes_on_the_shipped_caps_and_fires_on_a_lowered_one(
    shipped: rp.RoutePolicy, installed: rc.Installation, book: PriceBook
) -> None:
    """The shipped `[budget.per_unit] micros_per_part = 3000` and `[budget.per_part] micros = 6000`
    both clear 2,732. 05:1789 says the check exists because they once did not: *"it is the shipped
    default that had this defect."*"""
    with_book = rc.Installation(enabled=installed.enabled, cards=installed.cards, book=book)
    findings, undecided = rc.budget_below_reservation(shipped, with_book)
    assert findings == ()
    assert [u.key for u in undecided] == ["parse.fields.lift"]

    lowered = rp.compile_policy(
        [
            rp.builtin_layer(),
            rp.load_layer(
                b'surface = "route"\n[budget.per_unit]\nmicros_per_part = 2000\n',
                layer="project",
                origin="a test",
            ),
        ]
    )
    fired, _ = rc.budget_below_reservation(lowered, with_book)
    assert [(f.rule_id, f.check) for f in fired] == [("parse.page.olmocr", 13)]
    assert "2,732" in fired[0].message
    assert "2,000" in fired[0].message


def test_no_pricebook_is_not_run_rather_than_undecided_for_every_driver(
    shipped: rp.RoutePolicy, installed: rc.Installation
) -> None:
    """ "I did not look" and "I looked and could not tell" are different sentences, and only the
    second is an `Undecided`. Without a book there is nothing to compare for any driver."""
    findings, undecided = rc.budget_below_reservation(shipped, installed)
    assert findings == ()
    assert undecided == ()
    assert 13 in rc.not_run(installed)


def test_the_escalating_driver_set_follows_escalate_to_and_not_only_the_rung(
    shipped: rp.RoutePolicy,
) -> None:
    """05:1789's *"every enabled driver a `PAGE`- or `REGEN`-rung rule can select"*. The shipped
    policy reaches `parse.page.olmocr` through `decode.no-text-layer`'s `escalate_to = "PAGE"` from
    a `DECODE`-rung rule, so a check reading only `rule.rung` would report a pass it had not
    earned. `parse.pdf.pdfium` is here because the three `degrade.*` rules sit at `REGEN`."""
    selected = rc._escalating_drivers(shipped)
    assert selected == ("parse.fields.lift", "parse.page.olmocr", "parse.pdf.pdfium")
    assert not any(
        rule.rung is Rung.PAGE and rule.then.driver == "parse.page.olmocr" and rule.then.escalate_to
        for rule in shipped.rules
    )


# --------------------------------------------------------------------------------------------
# 4. Check 3 -- the boundary the shipped default sits exactly on.
# --------------------------------------------------------------------------------------------


def test_the_shipped_retrieval_budget_sits_exactly_on_the_boundary() -> None:
    """07:1108's own comment: *"15 + 25 + 50 + 40 + 80 = 210, + 40 reserved = 250 against
    query_ms = 250"*. A strict `<` would fail the shipped configuration, so the non-strict
    inequality is not a detail."""
    findings, undecided = rc.channel_budget(rc.Installation(retrieval=dict(BUDGET)))
    assert findings == ()
    assert undecided == ()
    channels = BUDGET["retrieval.budget.channel_ms"]
    assert isinstance(channels, dict)
    assert sum(channels.values()) + 40 == 250


def test_one_millisecond_over_is_a_finding() -> None:
    over = {**BUDGET, "retrieval.budget.query_ms": 249}
    findings, _ = rc.channel_budget(rc.Installation(retrieval=over))
    assert [f.code for f in findings] == ["OW-P-003"]
    assert "250 ms, above query_ms = 249" in findings[0].message


def test_an_absent_budget_is_undecided_and_not_a_pass() -> None:
    """A retrieval budget nobody declared is a default nobody has read."""
    findings, undecided = rc.channel_budget(rc.Installation())
    assert findings == ()
    assert [u.reason for u in undecided] == ["retrieval-budget-not-supplied"]


# --------------------------------------------------------------------------------------------
# 5. `lint()` with an installation: twelve of fourteen.
# --------------------------------------------------------------------------------------------


def test_the_shipped_policy_is_clean_under_twelve_of_the_fourteen(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry, installed: rc.Installation
) -> None:
    """No error, one warning, and the four that did not run each say why.

    Checks 5 and 12 are structural absentees -- `load_layer()` raises `OW-P-005` and `OW-P-013`, so
    a policy carrying either never reaches this function. Check 10 needs the computed format domain
    and check 13 needs a `PriceBook`; neither ships here.
    """
    report = rl.lint(shipped, registry=registry, installation=installed)
    assert report.ok
    assert [f.severity for f in report.findings] == ["warning"]
    assert sorted(report.not_run) == [5, 10, 12, 13]
    assert len(rl.NOT_RUN) == 8


def test_an_installation_narrows_the_run_rather_than_failing_it(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    """An empty `Installation` runs none of the six and says so, key by key."""
    report = rl.lint(shipped, registry=registry, installation=rc.Installation())
    assert sorted(report.not_run) == [3, 5, 6, 9, 10, 11, 12, 13, 14]
    assert report.ok


def test_every_one_of_the_six_reaches_report_not_run_when_its_input_is_absent() -> None:
    """`checks.not_run()`'s contract: a check whose input is absent for EVERY subject."""
    absent = rc.not_run(rc.Installation())
    assert sorted(absent) == sorted(rc.CODES)
    assert all(rc.CODES[number] in why for number, why in absent.items())


# --------------------------------------------------------------------------------------------
# 6. `--explain`, and the one thing 05:2224 says it is for.
# --------------------------------------------------------------------------------------------


def test_explain_prints_the_five_facts_none_of_which_is_in_the_rule_text(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    """05:1811's list: the derived phase, action-or-modifier, each key's cost class, nullability
    and resolved provider, and the demand-plan group."""
    demand = rd.compile_demand(shipped, registry=registry)
    one = rx.explain_rule(shipped, "decode.part-text-unusable", registry=registry, demand=demand)
    assert one.phase == "settle"
    assert one.kind == "action"
    assert one.plan_label == "DECODE/text/settle"
    reading = {read.key: read for read in one.reads}
    assert [read.key for read in one.reads] == list(
        next(r for r in shipped.rules if r.id == "decode.part-text-unusable").when.keys
    )
    assert reading["ink.coverage"].group == 1
    assert reading["garble.score"].group == 0
    assert reading["ink.coverage"].cost_class is not reading["garble.score"].cost_class


def test_explain_shows_that_block_type_has_no_pdf_row(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    """05:2224, verbatim: *"`ow route lint --explain` prints the provider resolved per format,
    which is how a reviewer sees at a glance that `block.type` has no PDF row."*"""
    one = rx.explain_rule(
        shipped, "decode.admit-table-lane", registry=registry, formats=("pdf", "docx")
    )
    reading = {read.key: read for read in one.reads}
    assert reading["block.type"].unserved == ("pdf",)
    assert reading["geometry.ruled_regions"].unserved == ("docx",)
    assert "UNSERVED on pdf" in reading["block.type"].render()


def test_explain_without_a_demand_map_says_so_rather_than_guessing_a_group(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    one = rx.explain_rule(shipped, "decode.pdf-text-layer", registry=registry)
    assert one.plan_label == "(not compiled)"
    assert {read.group for read in one.reads} == {-1}
    assert "no group" in one.render()[1]


def test_explain_refuses_an_id_the_policy_does_not_carry(
    shipped: rp.RoutePolicy, registry: ev.SignalRegistry
) -> None:
    with pytest.raises(KeyError, match="is not a rule in this policy"):
        rx.explain_rule(shipped, "decode.nope", registry=registry)


def test_the_builtin_layers_origin_carries_one_layer_prefix_and_a_path(
    shipped: rp.RoutePolicy,
) -> None:
    """05:2682's shape: `'project:.omniweave/policy.d/route.toml:41'` -- layer, path, position.

    `builtin_layer()` passed `builtin:<name>` and `_rule()` prefixes the layer itself, so every
    `rule_origin` read `builtin:builtin:00-builtin-route.toml:15`. The trailing number is a BLOCK
    INDEX and not a line, because `origin` is inside `policy_digest` and a line would re-decide the
    whole corpus on a whitespace edit (D218).
    """
    origin = shipped.rules[0].origin
    assert origin.startswith("builtin:omniweave/route/policies/00-builtin-route.toml:")
    assert origin.count("builtin:") == 1
    assert [rule.origin.rsplit(":", 1)[1] for rule in shipped.rules] == [
        str(index) for index in range(len(shipped.rules))
    ]
