"""The OUT framework: CompileV1, constructs, rules, gate, opc, receipt. LAZY.
09-generation.md; 02-architecture.md section 2 row 29.

D737 builds the diagnostic and the gate: `finding` (`Severity`, `Provenance`, `Finding`, the fold),
`gate` (the ten `GateStatus`es, `gate_status()`), `job` (`ILFile`) and `report` (`il_digest()`,
`OutReport`, the one render). D738 builds `carrier`: the two stdlib carriers, `svg_carrier()` and
`html_carrier()`, the types a rule is written against, the selector grammar and the splice.
D739 builds `constructs`: `ConstructTable.load()`, the contract as data, asserted as it loads.
D740 builds `brief`: the locked `Brief` and `parse_brief()`. D741 builds `plan`: `OutUnit`, `Plan`,
the seven `UnitOutcome`s, `ManualReason` and the total `classify_and_assert()`. D742 builds
`rules`: `RuleSpec`, `RuleCtx`, `DocIndex`, `Box`, `TextMeasure` and the two-pass `run_pack()`.
D743 adds `nsig()`, the canonical subtree digest, and the definition dependency to `report`.
"""

from omniweave_core.out.brief import Brief, Prohibition, baseline_rows, parse_brief
from omniweave_core.out.carrier import (
    CarrierDoc,
    CarrierNode,
    CarrierParseError,
    ParseError,
    Splice,
    parse_selector,
)
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.carrier.xml import svg_carrier
from omniweave_core.out.constructs import Construct, ConstructTable, Disposition, RoundTrip
from omniweave_core.out.finding import Finding, FindingSet, Provenance, Severity, Truncation
from omniweave_core.out.gate import GateStatus, gate_status
from omniweave_core.out.job import ILFile
from omniweave_core.out.plan import (
    Classified,
    ManualReason,
    OutUnit,
    Plan,
    UnitOutcome,
    classify_and_assert,
)
from omniweave_core.out.report import (
    OutReport,
    SkippedCheck,
    changed_definitions,
    definitions,
    il_digest,
    nsig,
    referenced_ids,
    render,
    unchanged,
)
from omniweave_core.out.rules import (
    Box,
    DocIndex,
    PackRun,
    RuleCtx,
    RuleSpec,
    TextMeasure,
    run_pack,
)

__all__ = [
    "Box",
    "Brief",
    "CarrierDoc",
    "CarrierNode",
    "CarrierParseError",
    "Classified",
    "Construct",
    "ConstructTable",
    "Disposition",
    "DocIndex",
    "Finding",
    "FindingSet",
    "GateStatus",
    "ILFile",
    "ManualReason",
    "OutReport",
    "OutUnit",
    "PackRun",
    "ParseError",
    "Plan",
    "Prohibition",
    "Provenance",
    "RoundTrip",
    "RuleCtx",
    "RuleSpec",
    "Severity",
    "SkippedCheck",
    "Splice",
    "TextMeasure",
    "Truncation",
    "UnitOutcome",
    "baseline_rows",
    "changed_definitions",
    "classify_and_assert",
    "definitions",
    "gate_status",
    "html_carrier",
    "il_digest",
    "nsig",
    "parse_brief",
    "parse_selector",
    "referenced_ids",
    "render",
    "run_pack",
    "svg_carrier",
    "unchanged",
]
