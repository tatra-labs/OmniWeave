"""`omniweave.plan`: the single `INSERT` that creates a routed `work` row. 02-architecture.md
row 36 (02:260).

02:260: *"the single `INSERT` that creates a routed `work` row, carrying `driver`, `decision_id`,
the denormalised `dispatch_key` and the recorded `cache_key` together -- so two rows share one
`INVOKE` iff they share that key, and I1's idempotence check has a key to compare"*. Its row in 02
section 4.1's trace is hop 9 (02:479): *"one `INSERT` per part: `operator='parse.pdf'`,
`op_version=<int>`, `unit_part='p1'..'p42'`, `status='pending'`, `driver='parse.pdf.pdfium'`,
`decision_id`, `dispatch_key = sha256(driver_id||config_digest||isolation)[:16]`,
`cost_class='free'`, and `cache_key` from the **free** recipe of section 8.3"*.

**02:452-461's ordering constraint is why this is a module and not a line in the router.**
`work.decision_id REFERENCES route_decision(decision_id)`, and three CHECKs chain `operator LIKE
'op.%'` to `decision_id`, `driver` and `dispatch_key` all being NULL together. So a routed row is
written whole or not at all, in the transaction that wrote its decision: *"There is no window in
which a routed work row is half-populated, and there is no `UPDATE work SET driver = ...` anywhere
in the codebase."* `plan_statements()` returns the row and the unit's move to `planned`, and the
caller commits them with the decision.

**The operator is the driver's port family.** 02:479 writes `operator='parse.pdf'` for
`parse.pdf.pdfium`: the driver id without its implementation segment. `op_version` is the card's
`schema_version`, which the card calls *"THE ONLY DRIVER VERSION IN A CACHE KEY"* and which
`cache.cache_key()` already reads for a driver row, so the row and its key name one version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.cache import cache_key
from omniweave_core.errors import RouteError
from omniweave_core.model.records import Producer

from omniweave.run.dispatch import dispatch_key

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_core.drivers.card import DriverCard
    from omniweave_core.drivers.resolve import Candidate
    from omniweave_core.operator import RunContext
    from omniweave_ports.types import UnitRef

__all__ = [
    "PLANNED_SQL",
    "PLAN_INSERT_SQL",
    "PLAN_PRIORITY",
    "Planned",
    "operator_of",
    "plan_row",
]

PLAN_PRIORITY: Final[int] = 200
"""A parse row's claim priority, below `op.identify`'s 300 (`expand.OP_IDENTIFY_PRIORITY`): 08
section 1.7 has the expander's own rows claimed first so the queue fills before it drains."""

PLAN_INSERT_SQL: Final[str] = """
INSERT INTO work(unit_uri, unit_part, operator, op_version, cache_key, cost_class, status, priority,
                 driver, decision_id, dispatch_key)
VALUES(:unit_uri, :unit_part, :operator, :op_version, :cache_key, :cost_class, 'pending', :priority,
       :driver, :decision_id, :dispatch_key)
ON CONFLICT(unit_uri, unit_part, operator, op_version) DO NOTHING
"""
"""Hop 9. `ON CONFLICT ... DO NOTHING` on `work_identity` for `expand.IDENTIFY_INSERT_SQL`'s
reason: a resumed run re-routes a unit that already has its row, and a second `pending` row for one
`(unit, part, operator, op_version)` would be claimed twice."""

PLANNED_SQL: Final[str] = """
UPDATE unit SET state = 'planned' WHERE unit_uri = :unit_uri AND state = 'identified'
"""
"""05:401's `identified -> planned`, in the transaction that wrote the row that plans it."""


@dataclass(frozen=True, slots=True)
class Planned:
    """One routed row's parameters, before the caller's transaction runs them."""

    params: Mapping[str, object]

    def statements(self) -> tuple[tuple[str, Mapping[str, object]], ...]:
        """The row, then the unit's move to `planned`. Commit both or neither (02:452-461)."""
        return (
            (PLAN_INSERT_SQL, self.params),
            (PLANNED_SQL, {"unit_uri": self.params["unit_uri"]}),
        )


def operator_of(driver_id: str) -> str:
    """`parse.pdf.pdfium` -> `parse.pdf`: 02:479's operator, the driver's port family."""
    head, sep, _tail = driver_id.rpartition(".")
    if not sep or "." not in head:
        raise RouteError(
            f"{driver_id!r} is not '<port>.<family>.<implementation>'; no operator can be derived",
            fix="name the driver as its card's [driver] id does",
        )
    return head


def plan_row(
    unit: UnitRef,
    *,
    card: DriverCard,
    candidate: Candidate,
    decision_id: str,
    ctx: RunContext,
    salt: str,
) -> Planned:
    """Hop 9's one row for one part: the decision's driver, keyed and batched as 02:479 prints."""
    operator = operator_of(card.identity.id)
    producer = Producer(
        operator=operator,
        op_version=card.identity.schema_version,
        code_fingerprint="",
        options_digest=bytes.fromhex(candidate.config_digest),
    )
    cost = card.cost_model.cost_class if card.cost_model is not None else "free"
    return Planned(
        params={
            "unit_uri": unit.uri,
            "unit_part": unit.part,
            "operator": operator,
            "op_version": card.identity.schema_version,
            "cache_key": cache_key(unit, producer, card, ctx, salt=salt),
            "cost_class": str(cost),
            "priority": PLAN_PRIORITY,
            "driver": card.identity.id,
            "decision_id": decision_id,
            "dispatch_key": dispatch_key(
                card.identity.id, candidate.config_digest, str(candidate.isolation_granted)
            ),
        }
    )
