"""`RouteDecision`, `Modifiers` and `RouteHints` -- what one `evaluate()` call takes and returns.

05-ingest-and-routing.md section 4.6 prints all three: `RouteDecision` at :1907-1990 with the file
header `# omniweave/route/decision.py`, `Modifiers` at :1993-2016, `RouteHints` at :2018-2033.
16-roadmap.md:604 schedules them with W5.2, because `evaluate()`'s signature is what makes INV-14
checkable and a signature needs its types.

**Three types and three different reasons for their shape.**

`RouteDecision` is a RECORD OF INPUTS. Its first eight fields are *"EXACTLY the eight columns of
`route_decision_identity`"* (05:1913) and every one is an input -- *"nothing about WHEN the decision
was made appears here"*. That is what makes `decision_id()` derived rather than minted, which is
what makes the insert idempotent under concurrency: two `ow ingest` processes computing the same
decision converge on one row (05 section 4.3 property 6).

`Modifiers` is NOT first-match-wins, and it is the whole reason `then` keys split in two. 05:1996:
*"Every matching modifier rule contributes; the combination is per key, and each key's monoid is the
one section 4.2's table states ... which is what lets one part take four GATE modifiers at once, the
case a single ordered list cannot deliver."* The four are `gate.watcher-may-not-bill`,
`gate.agent-triggered-may-not-bill`, `gate.form-admits-fields` and `gate.schema-admits-fields`, and
a single first-match list delivers one of them.

`RouteHints` is DEFINED BY A FIELD IT DOES NOT HAVE. 05:2030: *"IT HAS NO budget, egress OR licence
FIELD, AND THEREFORE CANNOT WIDEN ANYTHING. `--allow-cost` is CLI-only for exactly this reason, and
the absence IS the mechanism: there is nothing to validate at the MCP boundary because there is no
field to send."* A test asserts each absent field by name, because an absence is what a later
contributor adds without noticing.

## Four things the table carries that `RouteDecision` deliberately does not

05:1984, each with its own reason and none of them "not implemented yet": `audit_selected`, because
the sampler needs `unit_uri`, which is not in the identity and which `evaluate()` must never see
(RT2); `grant_id`, which `admit()` step 3 issues; `admission`, which is `admit()`'s own verdict; and
`decided_at`, which exists for humans and retention only. One whole family is absent for a different
reason again -- `render`, `max_cost_class`, `skip_rungs`, `deny_lanes` and the admitted lane set are
**modifiers**, and the modifier set is a pure function of `(policy_digest, evidence)`, both already
in the identity, so `ow route explain` recomputes it exactly from the stored read set.

## The `Rung` in the digest is its NAME, and that is not a detail

`sha256_canonical` refuses anything that is not JSON, and an `IntEnum` would serialise as its
ordinal. The ordinal is append-only in SQL and the NAME is what `route_decision.rung` stores
(05:1216), so digesting the integer would make `decision_id` change if the ladder ever gained a
member below `ENRICH` -- renumbering every historical decision on a change the plan explicitly
allows the stored column to survive.

Core plus this package's `rung` and `spend`. No store, no clock, no IO, no policy: this module is
importable by `eval.py`, which semgrep holds to purity.

Tier T-PUBLIC: 18-api-sketch.md:843.

Specified in 05-ingest-and-routing.md section 4.6 (:1907-2033) and 16-roadmap.md:604.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.canonical import sha256_canonical
from omniweave_ports.types import CostClass

from omniweave.route.rung import Rung
from omniweave.route.spend import Spend

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_core.observe.degradation import Degradation

__all__ = [
    "DECISION_PREFIX",
    "IDENTITY_FIELDS",
    "OUTCOMES",
    "Modifiers",
    "Outcome",
    "RouteDecision",
    "RouteHints",
]

Outcome = Literal["ok", "ok_partial", "refuse", "skip"]
"""The four settling outcomes. 05:1967.

`not_eligible` is NOT here and its absence is the type carrying section 4.2's split: it is a
MODIFIER -- *"it excludes **blocks** from the rung without touching the part"* (05:1054) -- so it
lands in `Modifiers.not_eligible` as a set of block ids and never in this field. A five-member
literal would let a first-match action rule settle a part by excluding some of its blocks, which is
exactly the confusion `REPAIR`-on-PDF depends on not happening.
"""

OUTCOMES: Final[frozenset[str]] = frozenset({"ok", "ok_partial", "refuse", "skip"})
"""`Outcome`'s members as data, for the loader, which validates a string out of TOML."""

DECISION_PREFIX: Final[str] = "dec_"
"""05:1988: `'dec_' || sha256_canonical(<the eight identity fields>)[:24]`."""

_DIGEST_CHARS: Final[int] = 24
"""The hex prefix length. 05:1988's `[:24]` -- 96 bits, which is the same truncation `dispatch_key`
takes at `[:16]` and `run_id` at its own width, and it is chosen there and here for the same
reason: the id is a join key inside one store, not a global identifier."""

IDENTITY_FIELDS: Final[tuple[str, ...]] = (
    "content_sha256",
    "unit_part",
    "lane",
    "rung",
    "policy_digest",
    "pricebook_digest",
    "hints_digest",
    "read_set_digest",
)
"""05:1913's *"EXACTLY the eight columns of `route_decision_identity`"*, in the plan's order.

Named as data rather than spelled inline in `decision_id()` because three things read the same
tuple: the digest, the `ON CONFLICT` target of section 4.3 property 6's insert, and a test that
asserts no ninth field crept into the identity. The order is load-bearing -- `sha256_canonical`
digests a list, so a reordering is a different id for the same decision.
"""


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """What one `(part, lane, rung)` decided, before anything ran. 05:1909-1990, field for field.

    Frozen, because it is written to an append-only, immutable table (05:1165) and because
    `decision_id()` is derived: a mutable identity field would let a caller change the id of a row
    already inserted.

    `matched = False` is the common case and carries no other content: 05:1946 makes it *"no action
    rule matched at this `(rung, lane, phase)`; the loop in section 4.3 continues and writes no
    row."* Every other field is then at its default and `decision_id()` is still well defined,
    which is what lets the loop treat the return value uniformly instead of unpacking an optional.
    """

    # -- identity: EXACTLY the eight columns of `route_decision_identity` (05:1913). Every one an
    #    INPUT; nothing about WHEN the decision was made appears here. --
    content_sha256: str = ""
    """Keyed on CONTENT, not `unit_uri`: *"the same PDF in three folders is one decision and one
    parse"* (05:1915). It is also what keeps `unit_uri` out of `evaluate()`'s reach (RT2)."""

    unit_part: str = ""
    """`''` for a unit-grain decision. *"`''` folds NULL, because NULLs are distinct in a UNIQUE
    index"* (05:1917) -- so the empty string is the one spelling and the UNIQUE index works."""

    lane: str = "text"
    """A `LANES` member. In the key, *"so a part's `text` and `table` decisions are separate rows
    that age out and re-price apart"* (05:1919)."""

    rung: Rung = Rung.GATE
    policy_digest: str = ""

    pricebook_digest: str = ""
    """Filled by `price()`. *"A price change makes a NEW decision row rather than silently
    rewriting history"* (05:1921)."""

    hints_digest: str = ""
    """Over `RouteHints`, *"plus the CLI-only `--allow-cost` and `--max-rung` values"* (05:1924).
    Those two are not `RouteHints` fields and must not become them -- section 7.3 -- so the digest
    is computed by the caller that has them and arrives here as a string."""

    read_set_digest: str = ""

    # -- what the winning rule said. `evaluate()` fills all of these. --
    matched: bool = False
    rule_id: str = ""

    rule_origin: str = ""
    """`'project:.omniweave/policy.d/10-route.toml:41'`. A column and not a log line because
    `ow route explain` and 15 section 6.2's escalation report both print it (05:1949)."""

    driver: str = ""
    """`''` == no driver ran, *"the same convention `Spend.provider` uses for local. A `GATE`
    refusal writes a row with `driver = ''`"* (05:1952)."""

    driver_by: Literal["cheapest_admissible"] | None = None
    escalate_to: Rung | None = None
    terminal: bool = False
    outcome: Outcome | None = None
    failure_class: str | None = None
    sequence_max_parts: int | None = None

    cause: str | None = None
    """Rendered from the clause that fired when the rule declares `cause_from = "when"`:
    `'garble.score=0.71>=0.50'`. A GENERATED string, *"so 'why it escalated' is a `GROUP BY` and not
    a log grep"* (05:1974)."""

    reason: str | None = None
    slice_key: str = ""
    pinned: bool = False
    flagged_blocks: tuple[int, ...] = ()
    degradations: tuple[Degradation, ...] = ()
    """A SET, not a flag: *"a part can be budget-degraded AND signal-degraded, and both survive into
    the run manifest and the serve envelope"* (05:1981). `Degradation` is 15-observability.md's type
    and 05:1983 says this document *"mints no second one"* -- so it is imported, not redefined."""

    # -- filled by `price()` (section 6.3), between `evaluate()` and the row write. --
    cost_class: CostClass = CostClass.FREE
    """The driver's declared `[cost.model] class`, FROZEN AT DECISION TIME: it is the `cost_class`
    label on `ow_spend_micros_total` and the `class` column of `ow cost --by driver`, and *"reading
    it from the live catalog would re-label history after a card upgrade"* (05:1985)."""

    est_spend: Spend = field(default_factory=Spend)
    est_micros: int = 0
    """`est_spend.micros(book)`. *"`Spend.micros` is still the only place money appears (INV-15);
    this field is its result, not a second pricer"* (05:1989)."""

    reserved_micros: int = 0
    """The p95 CEILING: the output-proportional dimensions multiplied by `tokens_out_p95_multiple`,
    then priced. What `admit()` holds, and what `ow route lint` check 13 compares
    `micros_per_part` against."""

    def identity(self) -> tuple[tuple[str, str], ...]:
        """The eight identity fields as `(name, value)` pairs, in `IDENTITY_FIELDS` order.

        `rung` renders as its NAME. An `IntEnum` digests as its ordinal, the ordinal is append-only
        in SQL, and `route_decision.rung` stores the name -- so digesting the integer would change
        every historical `decision_id` if the ladder ever gained a member, on a change the stored
        column is designed to survive.
        """
        return tuple(
            (name, self.rung.name if name == "rung" else str(getattr(self, name)))
            for name in IDENTITY_FIELDS
        )

    def decision_id(self) -> str:
        """`'dec_' || sha256_canonical(<the eight identity fields>)[:24]`. 05:1988.

        DERIVED, *"which is what makes the insert idempotent under concurrency: two `ow ingest`
        processes computing the same decision converge on one row"*. Recomputed on every call
        rather than cached on the instance: a cached id on a frozen record is a second source for
        one fact, and `__slots__` would have to grow a mutable cell to hold it.
        """
        return (
            DECISION_PREFIX + sha256_canonical([[k, v] for k, v in self.identity()])[:_DIGEST_CHARS]
        )


@dataclass(frozen=True, slots=True)
class Modifiers:
    """Every matching modifier rule contributes, by a per-key monoid. 05:1995-2016.

    Not first-match-wins. 05:1018 gives the case: the shipped `GATE` block *"contains four rules
    that must **all** take effect on one part -- two cost clamps, a lane admission for forms and a
    lane admission for a supplied schema -- which a single first-match-wins list cannot deliver."*

    The monoids are section 4.2's table, one per key, and `merge()` below is the only place they
    are written down. Each default is that monoid's IDENTITY element, which is why
    `max_cost_class` defaults to `BILLED_API` -- the weakest clamp, so that merging a rule that
    sets nothing leaves the clamp alone.
    """

    max_cost_class: CostClass = CostClass.BILLED_API
    """MINIMUM over contributors. *"A clamp: it can only lower"* (05:2001), and `BILLED_API` is the
    identity of `min` over `COST_CLASS_ORDER` rather than a claim that billing is allowed."""

    admit_lanes: frozenset[str] = frozenset()
    deny_lanes: frozenset[str] = frozenset()
    """Set UNION, *"applied AFTER every `admit_lanes`, so a denial always wins"* (05:2003). The two
    are kept as separate fields rather than pre-subtracted because the rung loop unions
    `admit_lanes` into a set that already holds lanes admitted at earlier rungs, and a denial has to
    reach those too."""

    render: Literal["structure", "glyph"] | None = None
    """The MORE EXPENSIVE profile wins (05:2005). `glyph` is 1384 px on the short edge against
    `structure`'s 692 (section 4.4's `[render.*]` blocks), so the order is fixed by the shipped
    configuration and not by the name."""

    skip_rungs: frozenset[Rung] = frozenset()
    flag_blocks: bool = False

    not_eligible: frozenset[int] = frozenset()
    """Set UNION of excluded BLOCK ids -- *"the modifier form of `outcome`: it excludes BLOCKS from
    the rung without touching the part, which is how `REPAIR` is made structurally unavailable on
    PDF"* (05:2009). An empty set from a rule that fired is not the same as a rule that did not
    fire, which is what `rule_ids` records."""

    rule_ids: tuple[str, ...] = ()
    """Every modifier rule that contributed, IN FILE ORDER. `ow route explain` prints them, and it
    is the only evidence that a modifier with an empty contribution fired at all."""

    def merge(self, other: Modifiers) -> Modifiers:
        """Combine two modifier sets by section 4.2's per-key monoids. Associative, not commutative.

        Not commutative in exactly one place: `rule_ids` concatenates, because file order is what
        `ow route explain` prints and a set would lose it. Every other key is a lattice operation
        and commutes, which is what lets the caller fold in any order it likes as long as it visits
        rules in file order.

        `render` takes the more expensive profile, which is `glyph`; `max_cost_class` takes the
        minimum under `COST_CLASS_ORDER`, which is `FREE < LOCAL_COMPUTE < BILLED_API`.
        """
        return Modifiers(
            max_cost_class=min(
                self.max_cost_class, other.max_cost_class, key=_COST_ORDER.__getitem__
            ),
            admit_lanes=self.admit_lanes | other.admit_lanes,
            deny_lanes=self.deny_lanes | other.deny_lanes,
            render="glyph"
            if "glyph" in (self.render, other.render)
            else self.render or other.render,
            skip_rungs=self.skip_rungs | other.skip_rungs,
            flag_blocks=self.flag_blocks or other.flag_blocks,
            not_eligible=self.not_eligible | other.not_eligible,
            rule_ids=self.rule_ids + other.rule_ids,
        )

    def lanes(self, admitted: frozenset[str]) -> frozenset[str]:
        """Apply this set to a lane set. `admit` first, `deny` after, so a denial always wins.

        05:2003 states the order and 05:1043 states the reason it is an order at all:
        *"`deny_lanes` is applied after every `lane`, so a denial always wins."* A caller that
        unioned and subtracted in the other order would let `gate.form-admits-fields` re-admit a
        lane section 2.3's weak-format-basis rule had just denied.
        """
        return (admitted | self.admit_lanes) - self.deny_lanes


_COST_ORDER: Final[Mapping[CostClass, int]] = {
    CostClass.FREE: 0,
    CostClass.LOCAL_COMPUTE: 1,
    CostClass.BILLED_API: 2,
}
"""`min()`'s key for the `max_cost_class` clamp.

`omniweave_core.drivers.resolve.COST_CLASS_ORDER` is the same ordering and is NOT imported here:
that module reaches a `Catalog`, and `eval.py` -- which imports this one -- is the module semgrep
holds to purity. A three-entry dict is a cheaper price than a purity exemption, and a test asserts
the two agree so the duplication cannot drift.
"""


@dataclass(frozen=True, slots=True)
class RouteHints:
    """The `request` merge layer. It RESTRICTS and never widens. 05:2019-2033.

    *"Which is what makes it safe to accept from an agent over MCP or the SDK."* Five fields, and
    the type's content is as much what is absent as what is present -- there is no `budget`, no
    `egress` and no `licence` field, so there is nothing for an MCP boundary to validate.

    Every field defaults to `None`, and `None` means *"the request said nothing"* rather than
    *"the request said no limit"*: a `max_rung` of `None` leaves the policy's ladder alone, and a
    `max_rung` of `Rung.DECODE` caps it. The distinction matters because the merge is a
    restriction -- there is no value of any field that can raise a ceiling.
    """

    lane: str | None = None
    max_rung: Rung | None = None
    """*"A part that would have escalated past it records `Degradation(kind="rung_ceiling")`"*
    (05:2024). The ceiling is applied by the rung loop, not by `evaluate()`: a pure function cannot
    mint a `Degradation` that names a part it is not allowed to know the uri of."""

    prefer_capability: str | None = None
    deadline_ms: int | None = None

    schema: Mapping[str, object] | None = None
    """*"`request.schema_present` IS its presence, and it is what admits the `fields` lane"*
    (05:2030). The schema's CONTENT never reaches `evaluate()` -- the evidence key is a boolean --
    so a rule cannot branch on a JSON Schema an agent supplied."""
