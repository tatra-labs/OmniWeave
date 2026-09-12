"""`parse.office.anydoc` under a byte-level fuzzer. One of 14-security.md:477's format handlers.

Twelve readers behind one FFI call, and the only fuzzed parser in the collection on the other side
of it: anydoc ships twelve cargo-fuzz targets (`csv doc docx epub numfmt odf pdf ppt rtf xls xlsb
xlsx`, 04-driver-system.md:2091) and is "the **only** fuzzed parser among the 22 repositories"
(14-security.md:479). This target is the Python half of that -- not a second opinion on the Rust
readers, which `cargo +nightly fuzz` already covers far better, but an assertion about the
**boundary**: that whatever the Rust side does with a malformed input, what crosses back into
Python is a typed `DriverError` from the closed `FailureClass` and never a bare `ValueError`, an
`IndexError` out of the marshal, or a `pyo3_runtime.PanicException`.

That boundary is the one R-E5 is about. `firecrawl-anydoc` is the framework's only compiled
dependency, it sits on the default install path, and it is the driver the host grants
`Isolation.INPROC` -- 02-architecture.md:1061: "Interpreter-state corruption is unrecoverable here
by construction, which is the fifth reason `inproc` is gated to a fuzz-green first-party driver."
*Fuzz-green* is a condition DR9 states and something has to measure it. This and the `fuzz`
conformance suite are the two things that do.

## The corpus

Three mirrored corpora (`xls`, `xlsb`, `xlsx`) plus this driver's own sixteen fixtures. The
mirrored three are the spreadsheets `vendor/anydoc/fuzz/seeds/` ships; `numfmt` is mirrored and has
no reader here, for the reason `fuzz/seeds/MIRROR.toml` records. The fixtures cover the other nine
formats -- docx, pptx, ppt, doc, rtf, odt, ods, odp, epub, csv -- which the seeds do not reach at
all, and that is why the corpus is both.

Specified in 14-security.md:477-481 and section 2.9, 04-driver-system.md section 8.2, and
02-architecture.md section 7.5's S1 row.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import main
from _parse import parse_target

TARGET = parse_target(
    "office",
    card=Path("packages/omniweave-office/src/omniweave_office/driver.toml"),
    fixtures=Path("packages/omniweave-office/fixtures"),
    seeds=("xls", "xlsb", "xlsx"),
)

__all__ = ["TARGET"]

if __name__ == "__main__":
    raise SystemExit(main(TARGET))
