"""The router: evidence, the pure `evaluate()`, `admit()`, and the one place money appears.

02-architecture.md section 2 row 35 gives this package `Rung` (7, closed, ordered), `LANES` (open),
`Spend`, `PriceBook`, the `SignalSpec` registry, `Evidence` with its read log, `evaluate()` (pure),
`admit()`, `RouteHints`, `Degradation`, the policy loader, the subsumption linter and the isotonic
threshold fitter. 11-repo-layout.md:250 lists the files: `evidence.py`, `eval.py` (PURE),
`admit.py`, `spend.py` and the policy loader.

**`spend.py` is here and the rest is P5's.** 16-roadmap.md:545 schedules `PriceBook` and
`Spend.micros(book)` with W4.5, beside the durable ledger they price for, because a budget declared
in `micros` cannot be checked against a driver that reports seven physical units until something
converts one to the other. W5.1 through W5.5 fill in the rest of this package.

`omniweave.route` may import `omniweave_core`; `omniweave_core` may not import this, which is why
`omniweave_core.operator.SpendVector` exists as a structural stand-in for `Spend` and why
`StepMetrics.spend` is typed against it (D139).
"""

from __future__ import annotations

from omniweave.route.spend import PriceBook, Spend

__all__ = ["PriceBook", "Spend"]
