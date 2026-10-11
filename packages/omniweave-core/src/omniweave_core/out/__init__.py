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
D744 adds `ILBundle` to `job`: `il.toml`, the roster check, and both digests over one parse.
D745 builds `marker`: the `OWC1` grammar, `scan()`, `resolve()`, `apply_reverse()`,
`assert_clean()`. D746 adds `place()` and `Insertion`, and frames `nsig`'s text collapsed.
D747 builds `opc`: the only ZIP-for-write, `part_digest()` and section 5.3's package checks.
D748 builds `receipt`: `CheckValue`, `Receipt`, `ArtefactDeterminism` and the report status.
D749 builds `compile` (`CompileV1`, `check()`) and `ledger` (`AssetLedger`, `slot()`).
D752 builds `retain`: the IL bundle frozen into CAS (`retain.freeze()`) and fetched back
verified (`retain.fetch()`). Both stay module-qualified: a bare `fetch` says nothing here.
D753 adds the ledger's JobDir half to `ledger` (`AssetLicence`, `ledger_digest()`, the
`assets/index.json` reader and writer). The store-backed class is `store.ledger`'s.
D754 builds `cites`: `CiteResolver`, `CitedBlock`, the refusing `NO_CITES` and `verbatim()`,
09 section 10's predicate. `RuleCtx.cites` is one, and the store-backed resolver is
`store.cites`'s.
D756 builds `manual`: `ManualRegion`, `manual_regions()`, `ManualEvidence` and
`EvidenceRegion`, so an `ow:manual` region reaches the gate, the classifier and the seal.
D757 builds `roundtrip`: `r1` ... `r7` as predicates and `applicable()`, imported
module-qualified by the conformance suite.
D760 builds `card`: `CompileCard`, `[compile]` read strictly, and `targets()`, the rows
`ow out targets` prints.
D762 builds `agentdoc`: `load_table()` finds a target's table beside its card and imports none of
its code, and `select()`, `groups()` and `agent_doc()` produce what `ow out constructs` prints.
It is imported module-qualified, as `roundtrip` is.
D763 adds `Job` and `JobDeterminism` to `job`: `job.json`, schema `omniweave.out-job/1`, closed
at every level, which closes 09 Q11. `schema/job-v1.json` is generated from it.
D764 adds `scaffold()` and `job_path()` to `job`: one JobDir, written whole.
D767 builds `stamp`: `data-ow-el` minted once on every citable, text-bearing element, under
`il/.stamp.lock`, all units or none. It is imported module-qualified.
"""

from omniweave_core.out.brief import Brief, Prohibition, baseline_rows, parse_brief
from omniweave_core.out.card import CompileCard, TargetRow, targets
from omniweave_core.out.carrier import (
    CarrierDoc,
    CarrierNode,
    CarrierParseError,
    Insertion,
    ParseError,
    Splice,
    parse_selector,
)
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.carrier.xml import svg_carrier
from omniweave_core.out.cites import NO_CITES, CitedBlock, CiteResolver, verbatim
from omniweave_core.out.compile import CheckResult, CompileV1, check
from omniweave_core.out.constructs import Construct, ConstructTable, Disposition, RoundTrip
from omniweave_core.out.finding import Finding, FindingSet, Provenance, Severity, Truncation
from omniweave_core.out.gate import GateStatus, gate_status
from omniweave_core.out.job import ILBundle, ILFile
from omniweave_core.out.ledger import (
    AssetLedger,
    AssetLicence,
    AssetSource,
    LedgerRow,
    ledger_digest,
    slot,
)
from omniweave_core.out.manual import (
    EvidenceRegion,
    ManualEvidence,
    ManualRegion,
    manual_regions,
)
from omniweave_core.out.marker import (
    Marker,
    MarkerEdit,
    Payload,
    apply_reverse,
    assert_clean,
    place,
    resolve,
    scan,
)
from omniweave_core.out.opc import check_package, part_digest, write_opc
from omniweave_core.out.plan import (
    Classified,
    ManualReason,
    OutUnit,
    Plan,
    UnitOutcome,
    classify_and_assert,
)
from omniweave_core.out.receipt import (
    ArtefactDeterminism,
    CheckValue,
    Receipt,
    console_line,
    report_status,
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
from omniweave_core.out.retain import Retained
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
    "NO_CITES",
    "ArtefactDeterminism",
    "AssetLedger",
    "AssetLicence",
    "AssetSource",
    "Box",
    "Brief",
    "CarrierDoc",
    "CarrierNode",
    "CarrierParseError",
    "CheckResult",
    "CheckValue",
    "CiteResolver",
    "CitedBlock",
    "Classified",
    "CompileCard",
    "CompileV1",
    "Construct",
    "ConstructTable",
    "Disposition",
    "DocIndex",
    "EvidenceRegion",
    "Finding",
    "FindingSet",
    "GateStatus",
    "ILBundle",
    "ILFile",
    "Insertion",
    "LedgerRow",
    "ManualEvidence",
    "ManualReason",
    "ManualRegion",
    "Marker",
    "MarkerEdit",
    "OutReport",
    "OutUnit",
    "PackRun",
    "ParseError",
    "Payload",
    "Plan",
    "Prohibition",
    "Provenance",
    "Receipt",
    "Retained",
    "RoundTrip",
    "RuleCtx",
    "RuleSpec",
    "Severity",
    "SkippedCheck",
    "Splice",
    "TargetRow",
    "TextMeasure",
    "Truncation",
    "UnitOutcome",
    "apply_reverse",
    "assert_clean",
    "baseline_rows",
    "changed_definitions",
    "check",
    "check_package",
    "classify_and_assert",
    "console_line",
    "definitions",
    "gate_status",
    "html_carrier",
    "il_digest",
    "ledger_digest",
    "manual_regions",
    "nsig",
    "parse_brief",
    "parse_selector",
    "part_digest",
    "place",
    "referenced_ids",
    "render",
    "report_status",
    "resolve",
    "run_pack",
    "scan",
    "slot",
    "svg_carrier",
    "targets",
    "unchanged",
    "verbatim",
    "write_opc",
]
