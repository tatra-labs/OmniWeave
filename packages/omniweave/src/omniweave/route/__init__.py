"""The router: evidence, the pure `evaluate()`, `admit()`, and the one place money appears.

02-architecture.md section 2 row 35 gives this package `Rung` (7, closed, ordered), `LANES` (open),
`Spend`, `PriceBook`, the `SignalSpec` registry, `Evidence` with its read log, `evaluate()` (pure),
`admit()`, `RouteHints`, `Degradation`, the policy loader, the subsumption linter and the isotonic
threshold fitter. 11-repo-layout.md:250 lists the files: `evidence.py`, `eval.py` (PURE),
`admit.py`, `spend.py` and the policy loader.

**`spend.py` came first and the rest is P5's.** 16-roadmap.md:545 schedules `PriceBook` and
`Spend.micros(book)` with W4.5, beside the durable ledger they price for, because a budget declared
in `micros` cannot be checked against a driver that reports seven physical units until something
converts one to the other.

**W5.1 added `evidence.py` and `rung.py`.** `Evidence`, `SignalSpec` and the registry are W5.1's
own (16-roadmap.md:603); `rung.py` is W5.4's first half, landed early and for the same reason
`spend.py` was -- `SignalSpec.requires` is `tuple[Rung, ...]` and the day-one registry names
`DECODE`, `PAGE`, `REPAIR` and `REGEN` in that column, so the registry cannot be read without the
ordinal type. W5.4 still owns the `BEFORE INSERT` trigger, the compiler-parity gate and the three
exact counters.

**W5.2 adds `decision.py`, `policy.py` and `eval.py`** (16-roadmap.md:604): the three types
`evaluate()` touches, the grammar and six-layer loader that 11-repo-layout.md:250 calls *"the policy
loader"*, and the pure `evaluate()` itself. W5.2's other half -- the interval-box subsumption linter
(`OW-P-011`), the isotonic threshold fitter and the shipped forty-rule `builtin` layer of section
4.4 -- is not here: all three are analyses over a compiled policy or data it reads, and none is
needed to compile one. `admit.py`, `estimate.py` and `detect.py` are W5.3 and W5.5.

`omniweave.route` may import `omniweave_core`; `omniweave_core` may not import this, which is why
`omniweave_core.operator.SpendVector` exists as a structural stand-in for `Spend` and why
`StepMetrics.spend` is typed against it (D139).
"""

from __future__ import annotations

from omniweave.route.decision import Modifiers, RouteDecision, RouteHints
from omniweave.route.eval import evaluate
from omniweave.route.evidence import Evidence, SignalRegistry, SignalSpec
from omniweave.route.policy import RoutePolicy, Rule, compile_policy, load_layer
from omniweave.route.rung import LANES, PARSE_LANES, Rung
from omniweave.route.spend import PriceBook, Spend

__all__ = [
    "LANES",
    "PARSE_LANES",
    "Evidence",
    "Modifiers",
    "PriceBook",
    "RouteDecision",
    "RouteHints",
    "RoutePolicy",
    "Rule",
    "Rung",
    "SignalRegistry",
    "SignalSpec",
    "Spend",
    "compile_policy",
    "evaluate",
    "load_layer",
]
