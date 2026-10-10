"""The OUT framework: CompileV1, constructs, rules, gate, opc, receipt. LAZY.
09-generation.md; 02-architecture.md section 2 row 29.

D737 builds the diagnostic and the gate: `finding` (`Severity`, `Provenance`, `Finding`, the fold),
`gate` (the ten `GateStatus`es, `gate_status()`), `job` (`ILFile`) and `report` (`il_digest()`,
`OutReport`, the one render).
"""

from omniweave_core.out.finding import Finding, FindingSet, Provenance, Severity, Truncation
from omniweave_core.out.gate import GateStatus, gate_status
from omniweave_core.out.job import ILFile
from omniweave_core.out.report import OutReport, SkippedCheck, il_digest, render

__all__ = [
    "Finding",
    "FindingSet",
    "GateStatus",
    "ILFile",
    "OutReport",
    "Provenance",
    "Severity",
    "SkippedCheck",
    "Truncation",
    "gate_status",
    "il_digest",
    "render",
]
