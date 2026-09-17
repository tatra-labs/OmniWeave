"""The public Python API and the report types every entry point returns. 11:249; 18 section 1.4.

18:149: *"`import omniweave` re-exports the whole surface; `omniweave.sdk` is the module"*, and
9.1's `Corpus`, `query()`, `open()` and the rest are this package's. None of them exists yet -- they
call `omniweave_core.retrieve.retrieve()` and `omniweave_core.answer.render()`, which SV19 makes the
single implementation under all three surfaces, through a dispatcher that is W7.2's.

What is here is `reports.py`, and it arrived with W7.1 rather than with the API around it because
`ActionSpec.out` is a `type` (10:137) and two of the four listed Actions declare an `outputSchema`.
`omniweave_core/store/card.py` already names this module as the reflection source: its
`CorpusCardRow` docstring says `corpora-out-v1.json` is reflected from `omniweave.sdk:CorpusCard`
and not from the stored row. So the alternative to shipping it here was an `out` pointing at
nothing.

**W7.1b adds three more and no fourth.** `DoctorReport`, `DoctorFinding` and `CodeRow` are the
`out` types of the `doctor` and `explain` Actions, and they are here because 18 section 1.4 prints
them field for field exactly as it prints `CorpusCard` and `AddReport` -- a report type this
document specifies is this package's whether or not the entry point that returns it exists. The
other thirteen `full`-profile Actions have no such specification, and `registry.py`'s
`_unrostered_full()` names each one rather than this module guessing a shape.

`_generated.pyi` is 11:249's other half and is `T-GENERATED`: 10:211 generates it from `inp`, `out`
and `name`, and G25 byte-diffs it. Nothing in this package may be hand-written into that file.
"""

from __future__ import annotations

from omniweave.sdk.reports import (
    AddCompleted,
    AddPending,
    AddReport,
    CodeRow,
    CorporaReport,
    CorpusCard,
    DoctorFinding,
    DoctorReport,
    Gap,
)

__all__ = [
    "AddCompleted",
    "AddPending",
    "AddReport",
    "CodeRow",
    "CorporaReport",
    "CorpusCard",
    "DoctorFinding",
    "DoctorReport",
    "Gap",
]
