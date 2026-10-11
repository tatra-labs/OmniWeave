"""`omniweave.out-report/1`: `il_digest()`, `OutReport` and the one render. **D737.**

09-generation.md section 4.2 (the JSON and the console), section 4.5 (the digest, the loader) and
section 14.3 (the second fold); charter OUT3, OUT4, OUT6 and OUT7. The report is written to
`validation/<stage>.json`, one file per stage, so no diagnostic run can produce the file the release
gate reads.

## Rulings (the ledger's D737)

11. **The console renders the JSON document, and nothing else** (OUT6). `render()` takes the
    mapping `OutReport.as_json()` returns, or one read back from disk, so the two cannot disagree;
    the findings are in one order in both, `Finding.sort_key()`.
12. **The framework mints its findings from the records that move the gate.** A skipped check
    becomes one `OW_TARGET_CHECK_SKIPPED` info finding and a truncation one
    `OW_TARGET_FINDINGS_TRUNCATED`, both `FRAMEWORK`, in `OutReport.build()`. A caller cannot hand
    in a skip without its finding or a finding without its skip, so 09 section 4.1's
    `info`/`framework` cell (*"a recorded skip, the gate becomes `unverified`"*) holds by
    construction.
13. **A skipped check carries its fix in the JSON as well as in its finding**, and `el` when the
    skip is one node's (09 section 4.4's *"one skip naming the rule and the `el`"*).
14. **`summary` buckets units before the re-fold.** The re-fold drops `unit`, so the buckets are
    taken from the per-unit fold, and `counts`, `by_provenance` and `introduced_warning_count` from
    the findings as listed.
15. **A report that parses as JSON but not as `/1` is unreadable**: a missing field, a mistyped
    one, a malformed digest. A report of another `schema` keeps that value and nothing else, so it
    reaches `gate_status()` as `unsupported-schema`, not as `unreadable`.
16. **A finding no rule owns has `rule = ""`**, as it has `unit = ""` (ruling 3). The console prints
    neither.

## `nsig` (the ledger's D743)

17. **`nsig` is computed over a canonical copy**, never the parsed tree, which a rule may still be
    reading: the six normalizations rewrite and collapse.
18. **Normalization 2 is the identity.** ppt-master rewrote a file path to `asset-slot:`; OUT9 makes
    `asset-slot:<sha256>` the only asset syntax an IL holds, so there is no other spelling to fold.
19. **A clone prefix and the edited assets are arguments**, both empty by default: the prefix a
    cloned asset's ids carry and the ledger's edited digests are facts of the asset ledger, not of
    the tree. A cloned id, `url(#id)` and `href="#id"` lose the prefix; an edited slot gains
    `:edited:<sha256>`.
20. **The framing is ppt-master's `semantic_subtree_sha256`**: the tag, the attributes sorted, the
    character data, the children in order. Indentation and attribute order are not content; a tail
    is. Normalizations 4 and 5 apply below the measured element, never to it. **Amended by D746**:
    each run of character data is framed whitespace-collapsed (runs to one space, ends stripped),
    not raw, everywhere. An `OWC1` marker sits on its own line as an element's first child, so
    placing or removing one adds or drops whitespace beside the element's text; framed raw, that
    would move the very `nsig` the marker records. A whitespace-only edit is therefore no change,
    which is the price, and 09's own: `nsig` is a change detector whose failure mode is a
    reviewable edit, not an identity.
21. **The shared definitions are the direct children with an id of the root's direct `<defs>`**,
    as ppt-master's `_direct_defs`. `changed_definitions()` is computed once a unit, and
    `unchanged()` is the two-factor test: the subtree's own `nsig` AND no changed definition it
    references.
22. **`il_digest_rt` elides by selector, over the canonical copy** (09 section 11.3). An element
    selector drops the matching element, an attribute selector the attribute, and a sub-property
    selector one declaration from `style`. Which selectors is `job.elided(table)`'s to derive.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import OwError, load_register
from omniweave_core.out.carrier import Selector, parse_selector, style_declarations
from omniweave_core.out.carrier.tree import collapse
from omniweave_core.out.finding import Finding, FindingSet, Provenance, Severity, Truncation
from omniweave_core.out.gate import REPORT_SCHEMA, GateStatus, clears, exit_code, gate_status
from omniweave_core.out.job import ILFile

if TYPE_CHECKING:
    from omniweave_core.out.carrier.tree import Node

__all__ = [
    "NSIG_HEX",
    "STAGES",
    "OutReport",
    "SkippedCheck",
    "canonical_subtree",
    "changed_definitions",
    "definitions",
    "il_digest",
    "nsig",
    "parse_digest",
    "referenced_ids",
    "render",
    "report_path",
    "unchanged",
]

STAGES: Final = ("early", "first-unit", "unit", "final")
"""09 section 4.3: one report path each."""

PORTABILITY: Final = (
    "generic_only_font_stacks",
    "unresolved_brief_tokens",
    "external_asset_refs",
    "unsafe_exported_faces",
)
"""09 section 4.2's four portability lists. Not validity (section 5.3)."""

_DIGEST_PREFIX: Final = "sha256:"
_CHECK_SKIPPED: Final = "OW_TARGET_CHECK_SKIPPED"
_TRUNCATED: Final = "OW_TARGET_FINDINGS_TRUNCATED"
_EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})


def il_digest(files: Sequence[ILFile]) -> str:
    """09 section 4.5: per file sorted by basename, `name 0x00 hex(sha256(bytes)) 0x0A`."""
    digest = sha256()
    for file in sorted(files, key=lambda f: f.name):
        digest.update(file.name.encode("utf-8") + b"\x00" + file.sha256.encode("ascii") + b"\n")
    return _DIGEST_PREFIX + digest.hexdigest()


def parse_digest(text: str) -> bytes:
    """`sha256:<64 hex>` to its 32 bytes, so the gate compares bytes with bytes (09 section 4.5)."""
    if not text.startswith(_DIGEST_PREFIX):
        raise ValueError(f"{text!r} is not a sha256: digest")
    raw = bytes.fromhex(text.removeprefix(_DIGEST_PREFIX))
    if len(raw) != sha256().digest_size:
        raise ValueError(f"{text!r} is not 32 bytes")
    return raw


def report_path(job_dir: Path, stage: str) -> Path:
    """`validation/<stage>.json`, and no other name: the release gate reads exactly one file."""
    if stage not in STAGES:
        raise ValueError(f"{stage!r} is not one of {STAGES}")
    return job_dir / "validation" / f"{stage}.json"


@dataclass(frozen=True, slots=True)
class SkippedCheck:
    """A check that could not run (OUT3). Ruling 13's shape."""

    rule: str
    needs: str
    reason: str
    fix: str
    el: str | None = None

    def finding(self) -> Finding:
        """Ruling 12: the skip's own `FRAMEWORK` info finding."""
        where = f" at {self.el}" if self.el else ""
        return Finding(
            code=_CHECK_SKIPPED,
            severity=Severity.INFO,
            provenance=Provenance.FRAMEWORK,
            rule=self.rule,
            unit="",
            msg=f'rule {self.rule} needs "{self.needs}"{where}; {self.reason}',
            fix=self.fix,
            el=self.el,
        )

    def as_json(self) -> dict[str, object]:
        doc: dict[str, object] = {
            "rule": self.rule,
            "needs": self.needs,
            "reason": self.reason,
            "fix": self.fix,
        }
        if self.el is not None:
            doc["el"] = self.el
        return doc


def _truncation_finding(truncation: Truncation, target: str) -> Finding:
    """Ruling 12: a truncation's own `FRAMEWORK` info finding."""
    if truncation.kind == "rule":
        msg = (
            f"rule {truncation.rule} emitted {truncation.before} findings and the first "
            f"{truncation.after} are kept; the absence of a finding past them proves nothing"
        )
    else:
        msg = (
            f"{truncation.before} folded findings re-folded into {truncation.after} without the "
            "unit; per-unit attribution is dropped"
        )
    return Finding(
        code=_TRUNCATED,
        severity=Severity.INFO,
        provenance=Provenance.FRAMEWORK,
        rule=truncation.rule or "",
        unit="",
        msg=msg,
        fix=f"ow out check --target {target} --stage final --json",
    )


@dataclass(frozen=True, slots=True)
class OutReport:
    """One `validation/<stage>.json`, as written and as read back (09 section 4.2)."""

    schema: str
    stage: str
    target: str
    constructs_digest: str
    il_digest: bytes
    """Bytes, decoded at load, so the gate's comparison is bytes with bytes (09 section 4.5)."""
    il_files: tuple[ILFile, ...]
    summary: Mapping[str, int]
    counts: Mapping[str, int]
    by_provenance: Mapping[str, int]
    introduced_warning_count: int
    findings: tuple[Finding, ...]
    skipped_checks: tuple[SkippedCheck, ...]
    truncations: tuple[Truncation, ...]
    restricted_items: tuple[Mapping[str, Any], ...]
    manual_units: tuple[Mapping[str, Any], ...]
    markers: tuple[Mapping[str, Any], ...]
    portability: Mapping[str, tuple[str, ...]]
    rule_timings_ms: Mapping[str, int]
    unreadable: bool = False

    @classmethod
    def build(
        cls,
        *,
        stage: str,
        target: str,
        constructs_digest: str,
        files: Sequence[ILFile],
        units: Sequence[str],
        findings: FindingSet,
        skipped: Sequence[SkippedCheck] = (),
        restricted: Sequence[Mapping[str, Any]] = (),
        manual: Sequence[Mapping[str, Any]] = (),
        markers: Sequence[Mapping[str, Any]] = (),
        portability: Mapping[str, Sequence[str]] | None = None,
        timings: Mapping[str, int] | None = None,
    ) -> OutReport:
        """Fold, mint the framework's findings, count, and bind to `files`' digest."""
        report_path(Path(), stage)
        per_unit = findings.fold(limit=sys.maxsize)
        listed = findings.fold()
        framework = [s.finding() for s in skipped] + [
            _truncation_finding(t, target) for t in listed.truncations
        ]
        final = sorted(
            FindingSet((*listed.findings, *framework)).fold(limit=sys.maxsize).findings,
            key=Finding.sort_key,
        )
        return cls(
            schema=REPORT_SCHEMA,
            stage=stage,
            target=target,
            constructs_digest=constructs_digest,
            il_digest=parse_digest(il_digest(files)),
            il_files=tuple(sorted(files, key=lambda f: f.name)),
            summary=_summary(units, per_unit.findings),
            counts={s.value: sum(f.severity is s for f in final) for s in Severity},
            by_provenance={p.value: sum(f.provenance is p for f in final) for p in Provenance},
            introduced_warning_count=sum(
                f.severity is Severity.WARNING and f.provenance is Provenance.INTRODUCED
                for f in final
            ),
            findings=tuple(final),
            skipped_checks=tuple(skipped),
            truncations=listed.truncations,
            restricted_items=tuple(restricted),
            manual_units=tuple(manual),
            markers=tuple(markers),
            portability={k: tuple((portability or {}).get(k, ())) for k in PORTABILITY},
            rule_timings_ms=dict(sorted((timings or {}).items())),
        )

    @classmethod
    def blank(cls, *, schema: str = "", unreadable: bool) -> OutReport:
        """Every field zeroed: 09's unreadable report, or ruling 15's other-schema one."""
        return cls(
            schema=schema,
            stage="",
            target="",
            constructs_digest="",
            il_digest=b"",
            il_files=(),
            summary=_EMPTY,
            counts=_EMPTY,
            by_provenance=_EMPTY,
            introduced_warning_count=0,
            findings=(),
            skipped_checks=(),
            truncations=(),
            restricted_items=(),
            manual_units=(),
            markers=(),
            portability=_EMPTY,
            rule_timings_ms=_EMPTY,
            unreadable=unreadable,
        )

    @classmethod
    def load(cls, path: Path) -> OutReport | None:  # noqa: PLR0911 -- 09 4.5: three answers
        """`None` when there is no file; an unreadable report when it does not parse (09 4.5)."""
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError:
            return cls.blank(unreadable=True)
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return cls.blank(unreadable=True)
        schema = doc.get("schema") if isinstance(doc, dict) else None
        if not isinstance(schema, str):
            return cls.blank(unreadable=True)
        if schema != REPORT_SCHEMA:
            return cls.blank(schema=schema, unreadable=False)
        try:
            return _from_json(doc)
        except (KeyError, TypeError, ValueError, AttributeError):
            return cls.blank(unreadable=True)

    def gate(self) -> tuple[GateStatus, int]:
        """The gate this report decides against its own bytes: the `gate` block it carries."""
        return gate_status(self, self.il_digest)

    def as_json(self) -> dict[str, Any]:
        """09 section 4.2's document, in its key order."""
        status, introduced = self.gate()
        cleared = clears(status, self.target)
        return {
            "schema": self.schema,
            "stage": self.stage,
            "target": self.target,
            "constructs_digest": self.constructs_digest,
            "il_digest": _DIGEST_PREFIX + self.il_digest.hex(),
            "il_files": [_file_json(f) for f in self.il_files],
            "summary": dict(self.summary),
            "counts": dict(self.counts),
            "by_provenance": dict(self.by_provenance),
            "introduced_warning_count": self.introduced_warning_count,
            "findings": [_finding_json(f) for f in self.findings],
            "skipped_checks": [s.as_json() for s in self.skipped_checks],
            "truncations": [t.as_json() for t in self.truncations],
            "restricted_items": [dict(r) for r in self.restricted_items],
            "manual_units": [dict(m) for m in self.manual_units],
            "markers": [dict(m) for m in self.markers],
            "portability": {k: list(v) for k, v in self.portability.items()},
            "rule_timings_ms": dict(self.rule_timings_ms),
            "gate": {
                "status": status.value,
                "introduced_warning_count": introduced,
                "exit": exit_code(status, self),
                "fix": None if cleared is None else cleared[1],
            },
        }

    def write(self, job_dir: Path) -> Path:
        """`validation/<stage>.json`, replaced whole, so a crash leaves the previous report."""
        path = report_path(job_dir, self.stage)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_bytes(
            (json.dumps(self.as_json(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        )
        temp.replace(path)
        return path


def _summary(units: Sequence[str], findings: Sequence[Finding]) -> dict[str, int]:
    """Ruling 14: one bucket a unit, the worst severity it holds."""
    errors = {f.unit for f in findings if f.severity is Severity.ERROR}
    warnings = {f.unit for f in findings if f.severity is Severity.WARNING}
    blocked = sum(u in errors for u in units)
    warned = sum(u in warnings and u not in errors for u in units)
    return {
        "units": len(units),
        "clean": len(units) - blocked - warned,
        "warned": warned,
        "blocked": blocked,
    }


def _file_json(file: ILFile) -> dict[str, object]:
    doc: dict[str, object] = {"name": file.name, "sha256": file.sha256, "bytes": file.byte_len}
    if file.error is not None:
        doc["error"] = file.error
    return doc


def _finding_json(finding: Finding) -> dict[str, object]:
    """Exactly the dataclass's fields, in their order."""
    doc: dict[str, object] = {}
    for f in fields(finding):
        value = getattr(finding, f.name)
        doc[f.name] = list(value) if isinstance(value, tuple) else value
    return doc


def _from_json(doc: Mapping[str, Any]) -> OutReport:
    """Ruling 15: `/1` read strictly; any shape it does not have raises."""
    return OutReport(
        schema=_str(doc["schema"]),
        stage=_str(doc["stage"]),
        target=_str(doc["target"]),
        constructs_digest=_str(doc["constructs_digest"]),
        il_digest=parse_digest(_str(doc["il_digest"])),
        il_files=tuple(
            ILFile(_str(f["name"]), _str(f["sha256"]), _int(f["bytes"]), f.get("error"))
            for f in _list(doc["il_files"])
        ),
        summary=_ints(doc["summary"]),
        counts=_counts(doc["counts"]),
        by_provenance=_ints(doc["by_provenance"]),
        introduced_warning_count=_int(doc["introduced_warning_count"]),
        findings=tuple(_finding(f) for f in _list(doc["findings"])),
        skipped_checks=tuple(
            SkippedCheck(
                _str(s["rule"]), _str(s["needs"]), _str(s["reason"]), _str(s["fix"]), s.get("el")
            )
            for s in _list(doc["skipped_checks"])
        ),
        truncations=tuple(
            Truncation(t["kind"], before=_int(t["from"]), after=_int(t["to"]), rule=t.get("rule"))
            for t in _list(doc["truncations"])
        ),
        restricted_items=tuple(_dict(r) for r in _list(doc["restricted_items"])),
        manual_units=tuple(_dict(m) for m in _list(doc["manual_units"])),
        markers=tuple(_dict(m) for m in _list(doc["markers"])),
        portability={
            k: tuple(_str(v) for v in _list(vs)) for k, vs in _dict(doc["portability"]).items()
        },
        rule_timings_ms=_ints(doc["rule_timings_ms"]),
    )


def _finding(doc: Mapping[str, Any]) -> Finding:
    values = dict(_dict(doc))
    values["severity"] = Severity(values["severity"])
    values["provenance"] = Provenance(values["provenance"])
    values["examples"] = tuple(_str(e) for e in _list(values.get("examples", [])))
    values["unit_examples"] = tuple(_str(e) for e in _list(values.get("unit_examples", [])))
    return Finding(**values)


def _counts(value: object) -> dict[str, int]:
    counts = _ints(value)
    if set(counts) != {s.value for s in Severity}:
        raise ValueError(f"counts {sorted(counts)} is not error, warning and info")
    return counts


def _str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{value!r} is not a string")
    return value


def _int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{value!r} is not an integer")
    return value


def _list(value: object) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{value!r} is not a list")
    return value


def _dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{value!r} is not an object")
    return value


def _ints(value: object) -> dict[str, int]:
    return {_str(k): _int(v) for k, v in _dict(value).items()}


# ---------------------------------------------------------------------------
# The console (ruling 11)
# ---------------------------------------------------------------------------

_MARK: Final = {"error": "E", "warning": "W", "info": "I"}


def render(doc: Mapping[str, Any]) -> str:
    """09 section 4.2's console block, from the JSON document alone."""
    gate = doc["gate"]
    counts = doc["counts"]
    skipped = len(doc["skipped_checks"])
    introduced = doc["introduced_warning_count"]
    head = (
        f"gate: {gate['status']}   ({counts['error']} blocking · {introduced} introduced "
        f"warning{'' if introduced == 1 else 's'} · {skipped} skipped "
        f"check{'' if skipped == 1 else 's'} · il_digest {doc['il_digest'][:19]}…)"
    )
    lines = [head, ""]
    numerics = _numerics()
    for finding in doc["findings"]:
        lines.extend(_block(finding, numerics))
        lines.append("")
    if gate["status"] == GateStatus.PASSED.value:
        lines.append("Release permitted: gate = passed.")
    else:
        lines.append(f"{counts['error']} blocking. Release refused: gate = {gate['status']}.")
        lines.append(f"Clear with: {gate['fix']}      (exit {gate['exit']})")
    return "\n".join(lines) + "\n"


def _block(finding: Mapping[str, Any], numerics: Mapping[str, str]) -> list[str]:
    anchor = finding["el"] or finding["unit"] or "-"
    numeric = numerics.get(finding["code"], finding["code"])
    at = finding["at"] or "-"
    lines = [
        f"{_MARK[finding['severity']]} {numeric:<9} {anchor:<8} {at:<17} x{finding['count']}",
        f"  {finding['msg']}",
    ]
    detail = []
    if finding["canonical"] is not None:
        detail.append(f"canonical: {finding['canonical']}")
    elif finding["construct"] is not None:
        detail.append(f"construct: {finding['construct']}")
    detail.append(f"provenance: {finding['provenance']}")
    lines.append("  " + "   ".join(detail))
    if finding["units_affected"] is not None:
        named = ", ".join(finding["unit_examples"]) or "-"
        lines.append(f"  units: {finding['units_affected']} ({named})")
    if finding["examples"]:
        lines.append("  examples: " + " | ".join(finding["examples"]))
    lines.append(f"  fix: {finding['fix']}")
    return lines


def _numerics() -> Mapping[str, str]:
    """Symbol to `OW-T-nnn`, from `codes.toml`. A render never fails for want of the register."""
    try:
        return {symbol: row.numeric for symbol, row in load_register().by_symbol.items()}
    except OwError:
        return {}


# ---------------------------------------------------------------------------
# nsig (09 section 8.2), D743
# ---------------------------------------------------------------------------

NSIG_HEX: Final = 8
"""32 bits: a change detector, not an identity (09 section 8.2's birthday arithmetic)."""

_EL: Final = "data-ow-el"
_URL_ID: Final = re.compile(r"url\(\s*(['\"]?)#([^)'\"\s]+)\1\s*\)")
_SLOT_VALUE: Final = re.compile(r"asset-slot:([0-9a-f]{64})")
_FILTER_TARGETS: Final = frozenset({"svg|circle", "svg|image", "svg|path", "svg|rect", "svg|text"})
_NON_VISUAL: Final = frozenset({"svg|defs", "svg|desc", "svg|metadata", "svg|title"})
_EMPTY_EDITS: Final[Mapping[str, str]] = MappingProxyType({})


@dataclass(slots=True)
class _Canon:
    """A canonical copy of one element: never the parsed tree, which a rule may still read."""

    tag: str
    attrs: dict[str, str]
    content: list[_Canon | str]


def canonical_subtree(
    node: Node,
    *,
    clone_prefix: str | None = None,
    edited: Mapping[str, str] = _EMPTY_EDITS,
    elide: Sequence[str] = (),
) -> bytes:
    """09 section 8.2's six normalizations, then ppt-master's semantic framing (rulings 17-20).

    `elide` is `il_digest_rt`'s (09 section 11.3, ruling 22): the selectors whose payload the
    round-trip digest leaves out, an element, an attribute or one style declaration.
    """
    canon = _copy(node, clone_prefix, edited)
    if elide:
        _elide(canon, [parse_selector(s, node.tag.split("|", 1)[0]) for s in elide])
    _lower_filters(canon)
    _collapse(canon)
    out = bytearray()
    _frame(canon, out)
    return bytes(out)


def nsig(
    node: Node, *, clone_prefix: str | None = None, edited: Mapping[str, str] = _EMPTY_EDITS
) -> str:
    """`hex(sha256(canonical_subtree(el)))[:8]`."""
    return sha256(canonical_subtree(node, clone_prefix=clone_prefix, edited=edited)).hexdigest()[
        :NSIG_HEX
    ]


def referenced_ids(node: Node) -> frozenset[str]:
    """Every local definition id the subtree references: `url(#id)` anywhere, `href="#id"`."""
    found: set[str] = set()
    stack: list[Node | str] = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            found.update(m.group(2) for m in _URL_ID.finditer(item))
            continue
        for name, value in item.attrs().items():
            found.update(m.group(2) for m in _URL_ID.finditer(value))
            if name.rpartition(":")[2] == "href" and value.startswith("#"):
                found.add(value[1:])
        stack.extend(item.content)
    return frozenset(found)


def definitions(root: Node) -> dict[str, str]:
    """Ruling 21: each direct child of the root's direct `<defs>` that has an id, to its nsig."""
    defs = next((c for c in root.children() if c.tag == "svg|defs"), None)
    if defs is None:
        return {}
    return {child.attr("id") or "": nsig(child) for child in defs.children() if child.attr("id")}


def changed_definitions(before: Mapping[str, str], after: Mapping[str, str]) -> frozenset[str]:
    """Ids added, removed or whose nsig moved. Computed once a unit: O(definitions)."""
    return frozenset(i for i in set(before) | set(after) if before.get(i) != after.get(i))


def unchanged(node: Node, then: str, changed: frozenset[str]) -> bool:
    """The two-factor test: the subtree's own nsig AND no changed definition it references."""
    return nsig(node) == then and not (changed & referenced_ids(node))


def _copy(node: Node, prefix: str | None, edited: Mapping[str, str]) -> _Canon:
    """Normalizations 1, 2, 3 and 6, element by element."""
    attrs: dict[str, str] = {}
    for name, value in node.attrs().items():
        if name == _EL:
            continue
        attrs[name] = _value(name, value, prefix, edited)
    content: list[_Canon | str] = [
        item if isinstance(item, str) else _copy(item, prefix, edited) for item in node.content
    ]
    return _Canon(node.tag, attrs, content)


def _value(name: str, value: str, prefix: str | None, edited: Mapping[str, str]) -> str:
    if prefix:
        if name == "id" and value.startswith(prefix):
            value = value[len(prefix) :]
        value = _URL_ID.sub(lambda m: _strip_ref(m, prefix), value)
        if name.rpartition(":")[2] == "href" and value.startswith("#" + prefix):
            value = "#" + value[len(prefix) + 1 :]
    if edited:
        value = _SLOT_VALUE.sub(
            lambda m: (
                m.group(0) + (f":edited:{edited[m.group(1)]}" if m.group(1) in edited else "")
            ),
            value,
        )
    return value


def _strip_ref(match: re.Match[str], prefix: str) -> str:
    quote, ref = match.group(1), match.group(2)
    return f"url({quote}#{ref.removeprefix(prefix)}{quote})"


def _lower_filters(root: _Canon) -> None:
    """Normalization 4: a filter on a bare group with one visual child moves to the child."""
    stack = [root]
    while stack:
        item = stack.pop()
        children = [c for c in item.content if isinstance(c, _Canon)]
        stack.extend(children)
        if item.tag != "svg|g" or set(item.attrs) != {"filter"} or _has_text(item):
            continue
        visual = [c for c in children if c.tag not in _NON_VISUAL]
        if (
            len(visual) == 1
            and visual[0].tag in _FILTER_TARGETS
            and "filter" not in visual[0].attrs
        ):
            visual[0].attrs["filter"] = item.attrs.pop("filter")


def _collapse(root: _Canon) -> None:
    """Normalization 5: an attribute-free one-child `<g>` is its child; never the root."""
    stack = [root]
    while stack:
        parent = stack.pop()
        changed = True
        while changed:
            changed = False
            for index, child in enumerate(parent.content):
                if not isinstance(child, _Canon):
                    continue
                inner = [c for c in child.content if isinstance(c, _Canon)]
                if (
                    child.tag == "svg|g"
                    and not child.attrs
                    and len(inner) == 1
                    and not _has_text(child)
                ):
                    parent.content[index] = inner[0]
                    changed = True
                    break
        stack.extend(c for c in parent.content if isinstance(c, _Canon))


def _elide(root: _Canon, selectors: Sequence[Selector]) -> None:
    """Ruling 22: drop each matching element, attribute and style declaration from the copy."""
    stack = [root]
    while stack:
        item = stack.pop()
        item.content = [
            c
            for c in item.content
            if isinstance(c, str) or not any(_element(s, c) for s in selectors)
        ]
        for s in selectors:
            if s.kind == "attribute":
                item.attrs.pop(s.name, None)
            elif s.kind == "subproperty" and "style" in item.attrs:
                kept = [
                    f"{p}: {v}" for p, v in style_declarations(item.attrs["style"]) if p != s.prop
                ]
                item.attrs["style"] = "; ".join(kept)
        stack.extend(c for c in item.content if isinstance(c, _Canon))


def _element(selector: Selector, item: _Canon) -> bool:
    return (
        selector.kind == "element"
        and item.tag == selector.tag
        and (not selector.name or selector.name in item.attrs)
    )


def _has_text(item: _Canon) -> bool:
    return any(isinstance(c, str) and c.strip() for c in item.content)


def _frame(item: _Canon, out: bytearray) -> None:
    """ppt-master's `semantic_subtree_sha256` framing: tag, sorted attributes, text, children."""
    out += item.tag.encode("utf-8")
    for name, value in sorted(item.attrs.items()):
        out += b"\x00a" + name.encode("utf-8") + b"\x00" + value.encode("utf-8")
    seen_child = False
    for piece in item.content:
        if isinstance(piece, str):
            text = collapse(piece)
            if text:
                out += (b"\x00l" if seen_child else b"\x00t") + text.encode("utf-8")
        else:
            out += b"\x00c"
            _frame(piece, out)
            seen_child = True
    out += b"\x00e"
