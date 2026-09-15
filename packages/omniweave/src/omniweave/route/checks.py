"""The six `ow route lint` checks that read the INSTALLATION rather than the policy.

`lint.py` holds the checks that are functions of `(policy, registry)` alone. These six are not, and
05:1800 draws the line for its own reasons -- `G27(a3)` runs eight of the fourteen over
documentation fences and excludes exactly these five plus one, *"because each reads something a
documentation fence has no standing to carry -- `retrieval.toml`, an enabled driver's card, the
shipped `[drivers] enabled`, or a `[budget.*]` block."* So the split is not a file-size convenience:
it is the same line the gate draws, and putting the two groups in one module would make the gate's
exclusion list a fact about a comment rather than about an import.

| # | check | code | what it reads |
|---|---|---|---|
| 3 | `sum(channel_ms) + hydration_reserve_ms <= query_ms` | `OW-P-003` | `[retrieval.budget]` |
| 6 | every `driver` and `[[pin]]` target is in `[drivers] enabled` | `OW-P-006` | configuration |
| 9 | no `on_unknown = "match"` on a rule whose driver is `billed_api` | `OW-P-012` | a card |
| 11 | a rule's `unit.format` tokens are in its driver's served token set | `OW-P-015` | a card |
| 13 | `[budget.*] micros >= reserved_micros` at `PAGE`/`REGEN` | `OW-P-021` | a card, a book |
| 14 | no `expect_unavailable = true` on a driver that IS enabled | `OW-P-024` | configuration |

## Sound and incomplete, for the second time and a different reason

F30's incompleteness in `lint.py` is about an open string domain; here it is about an absent card. A
driver a rule names but the machine has not installed has no `[cost.model]` to read and no served
token set to compare against, so checks 9, 11 and 13 return `Undecided` on it rather than a verdict.
That is the same discipline (17:890 -- *"the linter reports only the complete cases and says so"*)
applied to a different gap, and the gap is structural rather than temporary: an operator who has not
installed `omniweave-vision` genuinely cannot be told whether `parse.page.olmocr`'s cost class is
`billed_api`, and a linter that guessed would be answering a question about a file it has not read.

**Check 6 is the one whose absence is an ERROR anyway**, and the asymmetry is the plan's. A driver
rule names and the operator has not enabled is a decidable fact about configuration -- `[drivers]
enabled` is a list, not a lookup -- so check 6 fires where 9, 11 and 13 defer. The
`expect_unavailable = true` exemption turns it into a **warning**, and check 14 stops that from
becoming permanent: 05:1002 -- *"`ow route lint` check 14 makes the declaration self-retiring:
`expect_unavailable = true` on a rule whose driver **is** enabled is an error, so the day an
open-tier driver ships, the line that excused its absence fails the build instead of rotting into a
permanent excuse."*

## Check 13's number is the one section 10 prints

05:1976 names the comparison in a comment on `RouteDecision.reserved_micros`: *"what `ow route lint`
check 13 compares `micros_per_part` against."* `reserved_micros` is not a card field -- it is
`est_spend` with its output-proportional dimensions scaled by `tokens_out_p95_multiple` and then
priced (05:2461) -- so this check needs a `PriceBook` as well as a card, and returns `Undecided`
without one. On section 10's pricebook and olmocr's card the number is **2,732**, against a shipped
`[budget.per_unit] micros_per_part` of 3,000 and a `[budget.per_part] micros` of 6,000.

05:1789 records that this check exists because the default had the defect: *"a per-unit cap that
grows more slowly than the reservation denies parts the operator can afford, and it is the shipped
default that had this defect."*

Specified in 05-ingest-and-routing.md section 4.5; scheduled by 16-roadmap.md:607.
"""

from __future__ import annotations

from collections.abc import Mapping  # runtime: `channel_budget` narrows with isinstance
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_ports.types import CostClass

from omniweave.route.lint import Finding, Undecided
from omniweave.route.rung import Rung

if TYPE_CHECKING:
    from omniweave_core.drivers.card import DriverCard

    from omniweave.route.policy import RoutePolicy, Rule
    from omniweave.route.spend import PriceBook

__all__ = [
    "CARD_CHECKS",
    "CHANNEL_KEYS",
    "CODES",
    "ESCALATING_RUNGS",
    "Installation",
    "budget_below_reservation",
    "channel_budget",
    "driver_not_enabled",
    "match_on_billed_api",
    "reserved_micros",
    "run_all",
    "tokens_off_card",
    "unavailable_but_enabled",
]

CODES: Final[Mapping[int, str]] = MappingProxyType(
    {3: "OW-P-003", 6: "OW-P-006", 9: "OW-P-012", 11: "OW-P-015", 13: "OW-P-021", 14: "OW-P-024"}
)
"""Check number to numeric, for the six. The same pairing 05:1774-1789's table prints."""

CARD_CHECKS: Final[tuple[int, int, int]] = (9, 11, 13)
"""The three that return `Undecided` for a driver whose card is not installed."""

ESCALATING_RUNGS: Final[frozenset[Rung]] = frozenset({Rung.PAGE, Rung.REGEN})
"""Check 13's subject: 05:1786's *"for every enabled driver a `PAGE`- or `REGEN`-rung rule can
select"*.

Selected AT those rungs, which is a rule whose own `rung` is one of them OR whose `escalate_to`
is -- `decode.no-text-layer` sits at `DECODE` and names `parse.page.olmocr` with
`escalate_to = "PAGE"`, and it is the rule that actually causes the 2,732-micro reservation. A
check reading only `rule.rung` would find no PAGE-rung driver in the shipped policy at all."""

CHANNEL_KEYS: Final[tuple[str, str, str]] = (
    "retrieval.budget.channel_ms",
    "retrieval.budget.hydration_reserve_ms",
    "retrieval.budget.query_ms",
)
"""Check 3's three configuration keys, in the order its inequality reads them. 07 section 4.4."""

_UNDECIDED_NO_CARD: Final[str] = "driver-card-not-installed"
_UNDECIDED_NO_BOOK: Final[str] = "no-pricebook"
_UNDECIDED_NO_COST_MODEL: Final[str] = "card-declares-no-cost-model"

_P95_DIMS: Final[tuple[str, str]] = ("tokens_out", "gpu_ms")
"""The output-proportional dimensions `reserved_micros` scales. 05:2478:

*"**The p95 multiple applies to `gpu_ms` as well as `tokens_out`.** On a decode-bound VLM, GPU time
is proportional to output tokens, so reserving the mean `gpu_ms` against a p95 `tokens_out` reserves
a number that cannot occur. `tokens_in`, `calls` and `bytes_egress` are reserved at their declared
values."*"""


# --------------------------------------------------------------------------------------------
# 1. What the six read.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Installation:
    """The operator's machine, reduced to what these six checks read and nothing else.

    A record rather than four parameters, because `lint()` takes it as one optional argument and
    "run the six" has to be one decision rather than four. Every field defaults to empty, and an
    empty field narrows the run rather than failing it -- `Report.not_run` then says which check was
    skipped and why, which is the same contract `lint.py` already holds to for its registry.

    **Not `omniweave_core.drivers.catalog.Catalog`.** That type is the resolver's: it carries trust
    decisions, validity keys and a catalog digest, and it is built by walking entry points. This one
    is four lookups a caller may assemble from a test fixture, a `tools/` script or a real catalog,
    and a linter that could only run against a live installation could not be tested against a
    policy at all.
    """

    enabled: frozenset[str] = frozenset()
    """`omniweave.toml [drivers] enabled`. `SHIPPED_DRIVERS` is the default install's thirteen."""

    cards: Mapping[str, DriverCard] = field(default_factory=dict)
    """`driver_id -> card`, for the drivers whose distribution is installed. A driver in `enabled`
    with no card here is an install that has not finished, not a lint failure: check 6 passes it and
    checks 9, 11 and 13 return `Undecided`."""

    book: PriceBook | None = None
    """`.omniweave/pricebook.toml`. Check 13 alone reads it, and without it check 13 cannot run:
    `reserved_micros` is micros and a card declares physical units."""

    retrieval: Mapping[str, object] = field(default_factory=dict)
    """The flattened `[retrieval.budget]` block, keyed as `CHANNEL_KEYS` spells it."""

    def card(self, driver: str) -> DriverCard | None:
        return self.cards.get(driver)


def _drivers_of(policy: RoutePolicy) -> tuple[tuple[Rule, str], ...]:
    """Every `(rule, driver_id)` the policy names, in file order. Modifier rules name none."""
    return tuple((rule, rule.then.driver) for rule in policy.rules if rule.then.driver)


# --------------------------------------------------------------------------------------------
# 2. Checks 6 and 14 -- configuration, and the exemption that retires itself.
# --------------------------------------------------------------------------------------------


def driver_not_enabled(policy: RoutePolicy, installation: Installation) -> tuple[Finding, ...]:
    """Check 6, `OW-P-006`: every `then.driver` and every `[[pin]]` target is enabled.

    **A warning and not an error for a rule declaring `expect_unavailable = true`.** The flag has
    three mechanical effects and 05:1001 is the second: *"`ow route lint` check 6 reports the rule
    as a warning rather than an error."* The first is `ow doctor`'s exit-1 condition downgrading,
    *"so a fresh install exits 0 with the absence stated rather than failing on a driver the
    operator was never asked to consent to (INV-5)"*; the third is check 14. 05:1005 names the one
    shipped rule in that state: *"One rule in the shipped policy carries it -- `fields.extract`."*

    A `[[pin]]` gets no such exemption and the asymmetry is right: a rule naming an absent driver is
    a path that is never taken, while a pin naming one is an operator's instruction that cannot be
    carried out, and 05:2817 makes a pin's `reason` and `expires` mandatory precisely because
    somebody is expected to be watching it.
    """
    enabled = installation.enabled
    findings = [
        Finding(
            code="OW-P-006",
            check=6,
            rule_id=rule.id,
            severity="warning" if rule.expect_unavailable else "error",
            message=f"names driver {driver!r}, which is not in [drivers] enabled"
            + (
                "; the rule declares expect_unavailable = true, so this is a warning and check 14 "
                "retires it the day the driver ships (05:1002)"
                if rule.expect_unavailable
                else ". Discovery is not consent: a driver nobody enabled cannot run (INV-5)"
            ),
        )
        for rule, driver in _drivers_of(policy)
        if driver not in enabled
    ]
    findings += [
        Finding(
            code="OW-P-006",
            check=6,
            rule_id=f"pin:{pin.unit}",
            message=f"pins {pin.driver!r}, which is not in [drivers] enabled. A pin is an "
            "instruction, not a path, so it has no expect_unavailable exemption",
        )
        for pin in policy.pins
        if pin.driver not in enabled
    ]
    return tuple(findings)


def unavailable_but_enabled(policy: RoutePolicy, installation: Installation) -> tuple[Finding, ...]:
    """Check 14, `OW-P-024`: `expect_unavailable = true` on a driver that IS enabled.

    The exemption's expiry date, expressed as a check rather than as a date. 05:1002: *"`ow route
    lint` check 14 makes the declaration self-retiring: `expect_unavailable = true` on a rule whose
    driver **is** enabled is an error, so the day an open-tier driver ships, the line that excused
    its absence fails the build instead of rotting into a permanent excuse."*

    An error and not a warning, because by the time it fires the thing it was excusing has arrived:
    a stale `expect_unavailable` suppresses check 6 on a driver that could now be checked, which is
    a lint that has been switched off by a line nobody re-read.
    """
    return tuple(
        Finding(
            code="OW-P-024",
            check=14,
            rule_id=rule.id,
            message=f"declares expect_unavailable = true and {driver!r} IS in [drivers] enabled. "
            "The declaration is an exemption from check 6 and must retire the day the driver "
            "ships (05:1002)",
        )
        for rule, driver in _drivers_of(policy)
        if rule.expect_unavailable and driver in installation.enabled
    )


# --------------------------------------------------------------------------------------------
# 3. Checks 9, 11 and 13 -- a card, or an `Undecided`.
# --------------------------------------------------------------------------------------------


def match_on_billed_api(
    policy: RoutePolicy, installation: Installation
) -> tuple[tuple[Finding, ...], tuple[Undecided, ...]]:
    """Check 9, `OW-P-012`: no `on_unknown = "match"` on a rule whose driver is `billed_api`.

    05:1129 states it and states what it buys: check 9 *"rejects `match` on a rule whose
    `then.driver` declares `class = "billed_api"`, which is what makes 'an unavailable signal can
    never spend money' mechanical."* An unavailable signal is a provider that did not answer; a
    rule that fires anyway on a hosted driver turns a missing measurement into a bill.

    `local_compute` and `free` pass, and the shipped policy depends on that. 05:2438 closes a
    paragraph about `gate.watcher-may-not-bill`'s clamp with the consequence: it *"is what makes
    `ow route lint` check 9 satisfiable by the shipped policy"* -- `decode.part-text-unusable` and
    `decode.broken-font-encoding` both declare `match` and both name `parse.page.olmocr`.
    """
    findings: list[Finding] = []
    undecided: list[Undecided] = []
    for rule, driver in _drivers_of(policy):
        if rule.on_unknown != "match":
            continue
        card = installation.card(driver)
        if card is None or card.cost_model is None:
            undecided.append(_no_card(rule.id, driver, 9, card))
            continue
        if card.cost_model.cost_class is CostClass.BILLED_API:
            findings.append(
                Finding(
                    code="OW-P-012",
                    check=9,
                    rule_id=rule.id,
                    message=f"declares on_unknown = 'match' and names {driver!r}, whose "
                    "[cost.model] class is billed_api. An unavailable signal would then spend "
                    "money, which is exactly what this check makes impossible (05:1129)",
                )
            )
    return tuple(findings), tuple(undecided)


def tokens_off_card(
    policy: RoutePolicy, installation: Installation
) -> tuple[tuple[Finding, ...], tuple[Undecided, ...]]:
    """Check 11, `OW-P-015`: a rule's `unit.format` tokens are in its driver's served token set.

    05:1784 gives the served set as `{format_token_for(m) for m in [capability] formats}` unioned
    with the card's own `format_tokens` tokens, and says why the comparison is token-to-token:
    *"Compared token-to-token: `[capability] formats` holds media types and a rule holds tokens, so
    the card's token-side projection is the only comparable of the right type."*

    **The card's own `[parse] format_tokens` IS that projection**, and reading it is the only way to
    get it: `format_token_for` is a function of `route/detect.py`'s vocabulary, which 05 section 2.2
    has not shipped, and a media type has no token without it. A card whose `[capability] formats`
    names a media type its `format_tokens` does not pair is `OW-D-024`'s failure and the card
    loader's (05:2166) -- not this check's, so an unpaired media type is not reported here.

    05:3190 is the shipped case: `decode.office-native` names twelve tokens and the rule's own
    comment says *"lint check 11 asserts that list is exactly anydoc's declared `[capability]`
    formats, so this rule cannot name a format the driver refuses -- which is what routing `html`
    or `md` here would have done."*
    """
    findings: list[Finding] = []
    undecided: list[Undecided] = []
    for rule, driver in _drivers_of(policy):
        named = _format_literals(rule)
        if not named:
            continue
        card = installation.card(driver)
        if card is None or card.parse is None:
            undecided.append(_no_card(rule.id, driver, 11, card))
            continue
        served = frozenset(pair.token for pair in card.parse.format_tokens)
        refused = sorted(named - served)
        if refused:
            findings.append(
                Finding(
                    code="OW-P-015",
                    check=11,
                    rule_id=rule.id,
                    message=f"routes {', '.join(refused)} to {driver!r}, whose served token set "
                    f"({len(served)} token(s)) does not contain "
                    f"{'them' if len(refused) > 1 else 'it'}. The driver would refuse the unit",
                )
            )
    return tuple(findings), tuple(undecided)


def _format_literals(rule: Rule) -> frozenset[str]:
    """Every `unit.format` literal in one rule's `when`, as a set. Check 11's left-hand side."""
    named: set[str] = set()
    for clause in rule.when.clauses:
        for key, test in clause.tests:
            if key != "unit.format" or test.op == "exists":
                continue
            values = test.value if isinstance(test.value, tuple) else (test.value,)
            named.update(one for one in values if isinstance(one, str))
    return frozenset(named)


def reserved_micros(card: DriverCard, book: PriceBook) -> int:
    """`est_spend` scaled on its output-proportional dimensions, then priced. 05:2461.

    *"`reserved_micros` = `est_spend` with its OUTPUT-PROPORTIONAL dimensions x
    `tokens_out_p95_multiple`, priced <- THE p95 CEILING."* The scaling is applied to the VECTOR and
    then priced, which is the order the plan prints and which `Spend.scaled()` implements; the two
    coincide only because every rate in a `PriceBook` is linear in its unit.

    `per_session` is **not** included, and 05:2472 is why: when a card declares a `service`, *"the
    `per_session` term is **omitted entirely**, because the model load belongs to the service --
    paid once per run, recorded on the run manifest, visible in the `service_attaches` counter."* A
    per-part reservation that carried it would reserve the model load once per part, which on a
    188-page document is 188 model loads nobody will pay for.
    """
    from omniweave.route.spend import DIMS, Spend  # noqa: PLC0415 -- spend imports none of this

    model = card.cost_model
    if model is None:
        message = f"{card.identity.id} declares no [cost.model]"
        raise ValueError(message)
    est = Spend()
    for dim, value in model.per_part.items():
        if dim in DIMS:
            est = replace(est, **{dim: int(value)})
    return est.scaled(model.tokens_out_p95_multiple, _P95_DIMS).micros(book)


def budget_below_reservation(
    policy: RoutePolicy, installation: Installation
) -> tuple[tuple[Finding, ...], tuple[Undecided, ...]]:
    """Check 13, `OW-P-021`: both per-part caps clear the reservation for every escalating driver.

    05:1789: *"for every enabled driver a `PAGE`- or `REGEN`-rung rule can select,
    `[budget.per_unit] micros_per_part >= card.reserved_micros` and `[budget.per_part] micros >=
    card.reserved_micros` -- a per-unit cap that grows more slowly than the reservation denies parts
    the operator can afford, and it is the shipped default that had this defect."*

    **Both caps and not one**, because they bind differently: `micros_per_part` is the slope of the
    per-unit ceiling (`clamp(base + per_part x part_count, 0, max)`, 05:1745) and `[budget.per_part]
    micros` is the ceiling on a single part. A document can be denied by either, and a check on one
    of them passes a policy that denies every part on the other.

    Section 10.1 is the arithmetic a reader can check: olmocr reserves 2,732 micros per part against
    a shipped `micros_per_part` of 3,000 and a `[budget.per_part] micros` of 6,000.

    **No book means this check did not run, not that every driver is undecided.** Without a
    `PriceBook` there is nothing to compare for ANY driver, so it belongs in `Report.not_run`
    ("I did not look") rather than producing one `Undecided` per driver ("I looked and could not
    tell"). With a book, a driver whose card is absent is the second case and gets one.
    """
    book = installation.book
    if book is None:
        return (), ()
    findings: list[Finding] = []
    undecided: list[Undecided] = []
    caps = _caps(policy)
    for driver in _escalating_drivers(policy):
        card = installation.card(driver)
        if card is None or card.cost_model is None:
            undecided.append(_no_card(driver, driver, 13, card, against="[budget.*]"))
            continue
        needed = reserved_micros(card, book)
        findings += [
            Finding(
                code="OW-P-021",
                check=13,
                rule_id=driver,
                message=f"reserves {needed:,} micros per part and [{block}] {knob} is {cap:,}. "
                "A cap below the reservation denies parts the operator can afford (05:1789)",
            )
            for block, knob, cap in caps
            if cap < needed
        ]
    return tuple(findings), tuple(undecided)


def _caps(policy: RoutePolicy) -> tuple[tuple[str, str, int], ...]:
    """The two caps check 13 compares, as `(block, knob, value)`. An absent cap is not compared.

    Absent rather than zero: `[budget.per_unit]` may legitimately declare no `micros_per_part` --
    05:1745's formula degenerates to a flat `micros_base` -- and reading a missing knob as `0` would
    report every escalating driver as over budget on a policy that simply does not cap per part.
    """
    per_unit = policy.budgets.get("per_unit", {})
    per_part = policy.budgets.get("per_part", {})
    found: list[tuple[str, str, int]] = []
    for block, table, knob in (
        ("budget.per_unit", per_unit, "micros_per_part"),
        ("budget.per_part", per_part, "micros"),
    ):
        value = table.get(knob)
        if isinstance(value, int) and not isinstance(value, bool):
            found.append((block, knob, value))
    return tuple(found)


def _escalating_drivers(policy: RoutePolicy) -> tuple[str, ...]:
    """Every driver a `PAGE`- or `REGEN`-rung rule can select, sorted and deduplicated.

    "Can select" is `rule.rung` in the pair **or** `then.escalate_to` in it. The shipped policy has
    no rule whose own `rung` is `PAGE` and whose `then` names a driver -- the driver arrives through
    `decode.no-text-layer`'s `escalate_to = "PAGE"` -- so a check reading only `rule.rung` would
    find nothing to compare and report a pass it had not earned.
    """
    return tuple(
        sorted(
            {
                rule.then.driver
                for rule in policy.rules
                if rule.then.driver
                and (rule.rung in ESCALATING_RUNGS or rule.then.escalate_to in ESCALATING_RUNGS)
            }
        )
    )


def _no_card(
    rule_id: str, driver: str, check: int, card: DriverCard | None, *, against: str = ""
) -> Undecided:
    """One `Undecided` shape for the three card checks, naming which half of the card is absent.

    `key` is always the DRIVER, because that is what an operator installs to make the undecidable
    go away: `reason` says which of the two absences it was and `key` says which distribution
    closes it. `against` defaults to the driver and check 13 overrides it, because check 13's
    subject is a driver against a budget block rather than a rule against a driver.
    """
    reason = _UNDECIDED_NO_COST_MODEL if card is not None else _UNDECIDED_NO_CARD
    return Undecided(
        rule_id=rule_id,
        against=against or driver,
        where=f"check {check}",
        reason=reason,
        key=driver,
    )


# --------------------------------------------------------------------------------------------
# 4. Check 3 -- the retrieval surface's, linted here because the grammar is shared.
# --------------------------------------------------------------------------------------------


def channel_budget(installation: Installation) -> tuple[tuple[Finding, ...], tuple[Undecided, ...]]:
    """Check 3, `OW-P-003`: `sum(channel_ms) + hydration_reserve_ms <= query_ms`.

    The one check in the fourteen that is about no `[[rule]]` at all. 05:1776 hands it to the other
    document -- *"the `retrieval` surface's check, specified in 07 section 4.4, which owns
    `hydration_reserve_ms`"* -- and it is linted here because D4 gives both surfaces one grammar and
    one linter: `surface = "route"` and `surface = "retrieval"` share the policy file's shape, so a
    single `ow route lint` is what an operator runs.

    **`<=` and not `<`, and the shipped default is exactly on the boundary.** 07:1114 states the
    refusal from the other side -- check 3 *"refuses a set for which `sum(channel_ms) +
    hydration_reserve_ms > query_ms`"* -- and the declared defaults are `15 + 25 + 50 + 40 + 80 =
    210, + 40 reserved = 250 against query_ms = 250`, which the plan's own comment writes out. A
    strict `<` would fail the shipped configuration, so the boundary is not a detail here.

    The reserve is a TERM and not an implicit gap, and 07:1115 says why: *"the gap is the part a
    reader silently spends: a `channel_ms` edit summing to 249 passes an arithmetic that only
    compares against `query_ms`, and hydration then runs past the gate on every query."*

    Returns `Undecided` rather than a pass when the block is absent: a retrieval budget nobody
    declared is a default nobody has read, and reporting it as checked would be the overclaim F30
    objects to.
    """
    channels = installation.retrieval.get(CHANNEL_KEYS[0])
    reserve = installation.retrieval.get(CHANNEL_KEYS[1])
    query = installation.retrieval.get(CHANNEL_KEYS[2])
    if not isinstance(channels, Mapping) or not isinstance(reserve, int):
        return (), (_no_budget(),)
    if not isinstance(query, int):
        return (), (_no_budget(),)
    total = sum(value for value in channels.values() if isinstance(value, int)) + reserve
    if total <= query:
        return (), ()
    return (
        Finding(
            code="OW-P-003",
            check=3,
            rule_id="[retrieval.budget]",
            message=f"sum(channel_ms) + hydration_reserve_ms = {total} ms, above query_ms = "
            f"{query} ms. Every channel would have to be cut short or the reserve overrun, and "
            "the Answer would be degraded by arithmetic nobody chose",
        ),
    ), ()


def _no_budget() -> Undecided:
    """No `[retrieval.budget]` was supplied. Not a pass, for check 3's docstring's reason."""
    return Undecided(
        rule_id="[retrieval.budget]",
        against="query_ms",
        where="check 3",
        reason="retrieval-budget-not-supplied",
        key=", ".join(CHANNEL_KEYS),
    )


# --------------------------------------------------------------------------------------------
# 5. The six, run together.
# --------------------------------------------------------------------------------------------


def run_all(
    policy: RoutePolicy, installation: Installation
) -> tuple[tuple[Finding, ...], tuple[Undecided, ...]]:
    """Every check in this module, findings then undecidables. `lint()`'s one call into here.

    Ordered by check number rather than by cost, because the output is read by a human against
    05:1774's table and a reader scanning for "check 11" should not have to know which of these
    opens a file.

    **A check `not_run()` reports as skipped is not run**, and the two agreeing is the whole
    contract: an `Installation` with no `enabled` set would otherwise have check 6 report every
    driver-naming rule as an error while `Report.not_run` said check 6 never ran. One of those two
    sentences has to be false, and the true one is that a lint with no configuration has nothing to
    resolve against.
    """
    skipped = not_run(installation)
    findings: list[Finding] = []
    undecided: list[Undecided] = []
    for number, produce in (
        (3, lambda: channel_budget(installation)),
        (6, lambda: (driver_not_enabled(policy, installation), ())),
        (9, lambda: match_on_billed_api(policy, installation)),
        (11, lambda: tokens_off_card(policy, installation)),
        (13, lambda: budget_below_reservation(policy, installation)),
        (14, lambda: (unavailable_but_enabled(policy, installation), ())),
    ):
        if number in skipped:
            continue
        produced = produce()
        findings.extend(produced[0])
        undecided.extend(produced[1])
    return tuple(findings), tuple(undecided)


def not_run(installation: Installation) -> dict[int, str]:
    """Which of the six this `Installation` could not run, and why. `Report.not_run`'s input.

    A check is "not run" when the input it reads is absent for EVERY subject, and `Undecided` when
    it is absent for some: check 9 over a policy naming two drivers, one of whose cards is
    installed, ran -- it just could not decide half of it. The distinction is the one F30 asks for,
    one level up: "I did not look" and "I looked and could not tell" are different sentences.
    """
    absent: dict[int, str] = {}
    if not installation.retrieval:
        absent[3] = (
            "OW-P-003 reads [retrieval.budget] channel_ms, hydration_reserve_ms and query_ms, "
            "and none was supplied"
        )
    if not installation.enabled:
        for number in (6, 14):
            absent[number] = (
                f"{CODES[number]} resolves against omniweave.toml [drivers] enabled, "
                "and none was supplied"
            )
    if not installation.cards:
        for number in CARD_CHECKS:
            absent[number] = f"{CODES[number]} reads a driver card and none is installed"
    elif installation.book is None:
        absent[13] = "OW-P-021 needs a PriceBook to turn a card's units into micros, and none"
    return absent
