"""The OUT framework: CompileV1, constructs, rules, gate, opc, receipt. LAZY.
09-generation.md; 02-architecture.md section 2 row 29.

D737 builds the diagnostic and the gate: `finding` (`Severity`, `Provenance`, `Finding`, the fold),
`gate` (the ten `GateStatus`es, `gate_status()`), `job` (`ILFile`) and `report` (`il_digest()`,
`OutReport`, the one render). D738 builds `carrier`: the two stdlib carriers, `svg_carrier()` and
`html_carrier()`, the types a rule is written against, the selector grammar and the splice.
D739 builds `constructs`: `ConstructTable.load()`, the contract as data, asserted as it loads.
"""

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
from omniweave_core.out.report import OutReport, SkippedCheck, il_digest, render

__all__ = [
    "CarrierDoc",
    "CarrierNode",
    "CarrierParseError",
    "Construct",
    "ConstructTable",
    "Disposition",
    "Finding",
    "FindingSet",
    "GateStatus",
    "ILFile",
    "OutReport",
    "ParseError",
    "Provenance",
    "RoundTrip",
    "Severity",
    "SkippedCheck",
    "Splice",
    "Truncation",
    "gate_status",
    "html_carrier",
    "il_digest",
    "parse_selector",
    "render",
    "svg_carrier",
]
