"""`ow out normalize`: each `normalize` row's normalizer, applied through the splice. **D768.**

09 section 4.3's table: `ow out normalize` reads "`validation/<stage>.json` plus the IL" and writes
"the `normalizer` of each `normalize`-disposition finding, applied through `CarrierDoc.splice()`".
It is idempotent, "asserted per normalizer (section 3.4 assertion 2)", and exits 0, or 70 "on a
normalizer or reparse failure, having written nothing". Both writers "recompute `il_digest` before
doing anything and refuse on a mismatch with the report they were given". A normalize on a clean
bundle "writes nothing and says so".

## Rulings

1. **Where a value is normalized is read from the IL, never from the report.** A finding is folded,
   with a count and at most three examples (09 section 4.2), so the report cannot list every
   occurrence. The report decides which rows run: every `normalize` row its findings name. The
   current IL decides where: every node the row's selector matches in the unit.
2. **A report is optional, and when given it must describe these bytes.** With `stage`, the report
   at `validation/<stage>.json` must exist and its `il_digest` must be the bundle's
   (`OW_TARGET_NORMALIZE_STALE`, `OW-T-523`), and only the rows its findings name run. Without a
   stage, every `normalize` row of the table runs. That is safe for the same reason as ruling 1:
   nothing reads an offset the report recorded.
3. **`construct` and `unit` narrow the run.** A `construct` that is not a `normalize` row is
   `OW_CONSTRUCT_UNKNOWN`, because it names no normalizer.
4. **An attribute selector's value is rewritten in place.** The attribute is found inside the
   element's start tag, quoted, and its value is replaced with the normalizer's output, escaped for
   its quote. An element selector names no value to normalize, and a style sub-property's
   splice is not built. Both are `OW_TARGET_NORMALIZE_REFUSED` (`OW-T-524`), as is an attribute
   written without quotes.
5. **Every normalizer is held to idempotence on every value it changes.** `f(f(x)) == f(x)` fails
   as `OW_TARGET_NORMALIZE_REFUSED`, because a normalize that does not settle would never reach a
   clean report.
6. **All units or none, as `stamp` writes** (D767 ruling 4). Every unit is spliced and reparsed
   before any file is written, and each file is replaced through a dot-file sibling.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Never

from omniweave_core.errors import NotFoundError, TargetError
from omniweave_core.out.carrier import CarrierParseError, ParseError, Splice, parse_selector
from omniweave_core.out.carrier.tree import Doc, Node
from omniweave_core.out.constructs import Disposition
from omniweave_core.out.job import ILBundle, read_il_files
from omniweave_core.out.report import OutReport, il_digest, parse_digest, report_path

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.out.carrier import CarrierDoc
    from omniweave_core.out.constructs import Construct, ConstructTable
    from omniweave_core.out.plan import OutUnit

__all__ = ["Normalized", "normalize"]

_FIX: Final = "ow out check --stage early"


@dataclass(frozen=True, slots=True)
class Normalized:
    """What a normalize changed: per unit, per row, how many values. Nothing is a success."""

    changed: Mapping[str, Mapping[str, int]]
    written: tuple[str, ...]
    """The `il/` basenames whose bytes changed, in roster order."""


def normalize(
    job_dir: Path,
    *,
    carrier: Callable[[str, str], CarrierDoc],
    constructs: ConstructTable,
    normalizers: Mapping[str, Callable[[str], str]],
    stage: str | None = None,
    construct: str | None = None,
    unit: str | None = None,
) -> Normalized:
    """Rulings 1-6 over `<job_dir>/il/`."""
    il = job_dir / "il"
    rows = _rows(constructs, _named(job_dir, il, stage), construct)
    bundle = ILBundle.load(il, carrier=carrier, constructs=constructs)
    planned: list[tuple[OutUnit, str, dict[str, int]]] = []
    for one in bundle.units:
        if unit is not None and one.id != unit:
            continue
        try:
            doc = carrier(one.il_path, bundle.text(one.il_path))
        except CarrierParseError as exc:
            _refused(f"{one.il_path} does not read ({exc.error.at}: {exc.error.msg})", one)
        edits, counts = _edits(doc, one, rows, normalizers, constructs.carrier)
        if not edits:
            continue
        written = doc.splice(edits)
        if isinstance(written, ParseError):
            _refused(f"{one.il_path} does not reparse ({written.at}: {written.msg})", one)
        planned.append((one, written, counts))
    for one, written, _ in planned:
        path = il / one.il_path.removeprefix("il/")
        staged = path.with_name(f".{path.name}.normalize")
        staged.write_bytes(written.encode("utf-8"))
        staged.replace(path)
    return Normalized(
        changed=MappingProxyType(
            {one.id: MappingProxyType(dict(counts)) for one, _, counts in planned}
        ),
        written=tuple(one.il_path.removeprefix("il/") for one, _, _ in planned),
    )


def _named(job_dir: Path, il: Path, stage: str | None) -> frozenset[str] | None:
    """Ruling 2: the rows a current report names, or `None` when no stage was given."""
    if stage is None:
        return None
    report = OutReport.load(report_path(job_dir, stage))
    if report is None or report.unreadable:
        raise TargetError(
            f"there is no readable validation/{stage}.json to normalize from",
            symbol="OW_TARGET_NORMALIZE_STALE",
            fix=f"ow out check --stage {stage}",
        )
    if report.il_digest != parse_digest(il_digest(read_il_files(il))):
        raise TargetError(
            f"validation/{stage}.json describes other bytes: its il_digest is not the bundle's",
            symbol="OW_TARGET_NORMALIZE_STALE",
            fix=f"ow out check --stage {stage}",
        )
    return frozenset(f.construct for f in report.findings if f.construct)


def _rows(
    constructs: ConstructTable, named: frozenset[str] | None, construct: str | None
) -> tuple[Construct, ...]:
    """Rulings 2-3: the `normalize` rows this run applies, in table order."""
    rows = tuple(r for r in constructs.rows if r.disposition is Disposition.NORMALIZE)
    if construct is not None:
        if construct not in {r.id for r in rows}:
            raise NotFoundError(
                f"{construct!r} is not a normalize row of {constructs.il}; those are "
                f"{', '.join(r.id for r in rows) or 'none'}",
                symbol="OW_CONSTRUCT_UNKNOWN",
                fix=f"ow out constructs <target> --construct {construct}",
            )
        rows = tuple(r for r in rows if r.id == construct)
    if named is not None:
        rows = tuple(r for r in rows if r.id in named)
    return rows


def _edits(
    doc: CarrierDoc,
    unit: OutUnit,
    rows: tuple[Construct, ...],
    normalizers: Mapping[str, Callable[[str], str]],
    carrier: str,
) -> tuple[list[Splice], dict[str, int]]:
    """Rulings 4-5: one value splice per changed attribute, and the count per row."""
    if not isinstance(doc, Doc):
        raise TypeError(f"{doc!r} is not a carrier document this normalize can splice")
    data = doc.source().encode("utf-8")
    edits: list[Splice] = []
    counts: dict[str, int] = {}
    for row in rows:
        selector = parse_selector(row.selector, carrier)
        if selector.kind != "attribute":
            _refused(
                f"{row.id} selects {row.selector!r}, a {selector.kind}, and normalize rewrites an "
                "attribute's value only",
                unit,
            )
        fn = normalizers.get(row.normalizer or "")
        if fn is None:
            _refused(f"{row.id} names normalizer {row.normalizer!r}, which is not loaded", unit)
        for node in (one for one in doc.nodes() if selector.matches(one)):
            old = node.attr(selector.name) or ""
            new = fn(old)
            if new == old:
                continue
            if fn(new) != new:
                _refused(
                    f"{row.normalizer}({new!r}) is not {new!r}: the normalizer is not idempotent",
                    unit,
                )
            start, end, quote = _value(data, node, selector.name, unit)
            edits.append(Splice(start, end, _escaped(new, quote)))
            counts[row.id] = counts.get(row.id, 0) + 1
    return edits, counts


def _value(data: bytes, node: Node, name: str, unit: OutUnit) -> tuple[int, int, str]:
    """Ruling 4: the byte range of `name`'s quoted value inside `node`'s start tag."""
    tag = data[node.start : node.start_end]
    pattern = re.compile(
        rb"(?<![\w:.-])" + re.escape(name.encode("utf-8")) + rb"\s*=\s*(\"[^\"]*\"|'[^']*')"
    )
    match = pattern.search(tag)
    if match is None:
        _refused(f"{node.at}: {name} is not a quoted attribute of its start tag", unit)
    start, end = match.span(1)
    return node.start + start + 1, node.start + end - 1, chr(tag[start])


def _escaped(value: str, quote: str) -> str:
    out = value.replace("&", "&amp;").replace("<", "&lt;")
    return out.replace('"', "&quot;") if quote == '"' else out.replace("'", "&#39;")


def _refused(msg: str, unit: OutUnit) -> Never:
    raise TargetError(
        f"{unit.il_path}: {msg}; nothing was written",
        symbol="OW_TARGET_NORMALIZE_REFUSED",
        fix=_FIX,
    )
