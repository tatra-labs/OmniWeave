"""`parse.pdf.pdfium` under a byte-level fuzzer. The second of 14-security.md:477's handlers.

The PDF path is where a crash is most likely and least dangerous, and both halves of that are
deliberate. 14-security.md:469 fixes the isolation: "`[drivers] isolation_floor = "subproc"`, and
`parse.pdf.pdfium` is **not** in `[drivers] inproc`" -- DR9's five conditions plus an id in
`[drivers] inproc` admit `omniweave-office` only. So "a segfault becomes one `driver_crashed` row
plus a batch retry at `batch = 1` to localise the poison unit; three crashes in 60 s quarantine the
driver for the run."

That is the whole reason 04-driver-system.md:2082's asymmetry -- **a crash is allowed, a hang is
not** -- can be lived with here. What this target is actually hunting is the other half: an untyped
escape, which no host can attribute, and a hang, which holds a worker and everything queued behind
it. A pdfium call that never returns costs the run's wall clock; a pdfium call that dies costs one
unit.

## Why the corpus is this driver's own fixtures and nothing mirrored

`vendor/anydoc/fuzz/` ships a `pdf.rs` target and **no** `pdf` seed directory --
`vendor/anydoc/fuzz/seeds/` holds `numfmt`, `xls`, `xlsb` and `xlsx` only. So there is nothing to
mirror onto this path, and `fuzz/seeds/MIRROR.toml`'s `[readers]` table says so rather than leaving
a reader to infer it from an absence. The seven fixtures in `packages/omniweave-pdf/fixtures/` are
the starting corpus, and they are a good one for this purpose: they already include the abuse cases
(`truncated.pdf`, `not_a_pdf.bin`, `no_text_layer.pdf`) the driver is specified to refuse, so the
mutator starts from inputs that are already near the boundary.

`fixtures/generated/gen_5000p.pdf` is deliberately not here. 13-quality.md:586 gitignores that tree
and a 29 MB input mutated seven ways is 200 MB of work per replay, on a budget 16-roadmap.md:520
runs on every pull request.

Specified in 14-security.md:468-481, 04-driver-system.md section 8.2, and 02-architecture.md
section 5.6's S4 row.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import main
from _parse import parse_target

TARGET = parse_target(
    "pdf",
    card=Path("packages/omniweave-pdf/src/omniweave_pdf/driver.toml"),
    fixtures=Path("packages/omniweave-pdf/fixtures"),
)

__all__ = ["TARGET"]

if __name__ == "__main__":
    raise SystemExit(main(TARGET))
