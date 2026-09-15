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
loader"*, and the pure `evaluate()` itself.

**W5.2's other half adds `lint.py`, `fit.py` and `policies/`** -- the interval-box subsumption
linter (`OW-P-011`), the isotonic threshold fitter, and section 4.4's forty rules as the file
05:1267 names. All three are analyses over a compiled policy or the data one reads, which is why
none of them is in `policy.py`; and the policy ships beside the linter because a policy and the
proof that it names every format token (check 10, `OW-P-014`) are one reviewable unit. That leaves
02-architecture.md:259's row 35 complete except for `admit()`.

**W5.3 adds `admit.py`** (16-roadmap.md:605): *"the only channel by which budget reaches a routing
decision (INV-14)"*. Steps 1-3 of 05:2519's admission ladder plus the `budget.exhausted` write-back;
steps 4-6 are `omniweave_core.budget.admit()`'s and are not restated. `estimate.py` and `detect.py`
are still W5.5's.

**`lint()` and `fit()` are deliberately NOT re-exported, and the omission is mechanical.** Each
shares its name with the module that defines it, so binding the function here would shadow the
module: after `from omniweave.route.lint import lint`, the name `omniweave.route.lint` is the
function, and `from omniweave.route import lint as rl` then hands a caller something with no
`Span` on it. The verbs 02-architecture.md:259 actually names -- *"the subsumption linter and the
isotonic threshold fitter"* -- are `subsumption()` and `isotonic()`, and both are here; the two
entry points that wrap them are one import away at `omniweave.route.lint.lint` and
`omniweave.route.fit.fit`.

`omniweave.route` may import `omniweave_core`; `omniweave_core` may not import this, which is why
`omniweave_core.operator.SpendVector` exists as a structural stand-in for `Spend` and why
`StepMetrics.spend` is typed against it (D139).
"""

from __future__ import annotations

from omniweave.route.admit import AdmissionRequest, write_exhausted
from omniweave.route.decision import Modifiers, RouteDecision, RouteHints
from omniweave.route.eval import evaluate
from omniweave.route.evidence import Evidence, SignalRegistry, SignalSpec
from omniweave.route.fit import Observation, Proposal, isotonic, render_diff
from omniweave.route.lint import Finding, Report, Undecided, degradations, subsumption
from omniweave.route.policy import (
    BUILTIN_POLICY,
    RoutePolicy,
    Rule,
    builtin_layer,
    compile_policy,
    load_layer,
)
from omniweave.route.rung import LANES, PARSE_LANES, Rung
from omniweave.route.spend import PriceBook, Spend

__all__ = [
    "BUILTIN_POLICY",
    "LANES",
    "PARSE_LANES",
    "AdmissionRequest",
    "Evidence",
    "Finding",
    "Modifiers",
    "Observation",
    "PriceBook",
    "Proposal",
    "Report",
    "RouteDecision",
    "RouteHints",
    "RoutePolicy",
    "Rule",
    "Rung",
    "SignalRegistry",
    "SignalSpec",
    "Spend",
    "Undecided",
    "builtin_layer",
    "compile_policy",
    "degradations",
    "evaluate",
    "isotonic",
    "load_layer",
    "render_diff",
    "subsumption",
    "write_exhausted",
]
