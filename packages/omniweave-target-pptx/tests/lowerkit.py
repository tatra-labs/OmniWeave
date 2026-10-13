"""What the owsvg/1 lowering tests share: a JobDir, a compile, and the package read back. D796.

`lowered(tmp_path, *units)` builds a JobDir in `tmp_path` (`job.json`, `il/`, `assets/index.json`),
lowers it with `PptxCompiler` over a `FrozenLedger` of its `assets`, and returns the package's
bytes and
members. The rest read a shape's DrawingML: `outline()` its elements and attributes in order,
`box()` and `turn()` its frame, and `line_of()` its `a:ln`. D795 wrote these in
`test_pptx_lower.py`; D796's path tests share them. D800: `assets` freezes pictures into the
ledger, each at `slot(sha256)`, and `png()` makes one.
"""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pptx
from lxml import etree  # type: ignore[attr-defined] -- lxml ships no stubs
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILBundle, Job, JobDeterminism
from omniweave_core.out.ledger import FrozenLedger, LedgerRow, ledger_digest, slot, write_index
from omniweave_core.out.plan import Plan
from omniweave_core.out.receipt import Receipt
from omniweave_ports import ArtifactKind
from omniweave_target_pptx.driver import PptxCompiler, table

TABLE = table()
CLOCK_NS = 1_700_000_000_123_456_789
TRACEPARENT = "00-" + "1" * 32 + "-" + "2" * 16 + "-01"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
BRIEF = parse_brief(
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n## forbidden\n",
    baseline=(),
)
RECT = '<rect width="1" height="1"/>'
INK = 'stroke="#000000"'


def u(n: float) -> int:
    """`n` user units in EMU."""
    return round(n * 9525)


def slide(body: str, *, box: str = "0 0 1280 720") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{box}">{body}</svg>'


@dataclass(frozen=True, slots=True)
class Lowered:
    data: bytes
    members: Mapping[str, bytes]
    plan: Plan
    path: Path

    def xml(self, name: str) -> Any:
        return etree.fromstring(self.members[name])

    def tree(self, n: int = 1) -> Any:
        """Slide `n`'s `p:spTree`."""
        return self.xml(f"ppt/slides/slide{n}.xml").find(f"{P}cSld/{P}spTree")

    def shapes(self, n: int = 1) -> list[Any]:
        """Slide `n`'s top-level shapes, groups and pictures."""
        return [c for c in self.tree(n) if c.tag in (f"{P}sp", f"{P}grpSp", f"{P}pic")]

    def first(self) -> Any:
        """The first `p:sp` on slide 1, at any depth."""
        return next(self.tree().iter(f"{P}sp"))

    def deck(self) -> Any:
        return pptx.Presentation(io.BytesIO(self.data))

    def receipt(self) -> Receipt:
        return PptxCompiler().postflight(str(self.path), self.plan)


def png(width: int, height: int) -> bytes:
    """A `width` by `height` RGB PNG, every pixel one colour."""
    raw = b"".join(b"\x00" + b"\x10\x20\x30" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + crc

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def picture_slot(blob: bytes) -> str:
    """The slot `assets=[blob]` freezes `blob` at."""
    return slot(hashlib.sha256(blob).hexdigest())


def job_dir(
    tmp_path: Path,
    units: Sequence[str],
    *,
    plan_units: Sequence[str] | None = None,
    assets: Sequence[bytes] = (),
) -> tuple[Path, Plan, FrozenLedger, MemoryBlobStore]:
    job = tmp_path / "job"
    il = job / "il"
    il.mkdir(parents=True)
    rows = "".join(
        f'\n[[unit]]\nid = "u{n:02d}"\nord = {n}\nfile = "u{n:02d}.svg"\n'
        for n in range(1, len(units) + 1)
    )
    (il / "il.toml").write_text(
        f'schema = "omniweave.out-il/1"\nil = "owsvg/1"\nconstructs_digest = "{TABLE.digest()}"\n'
        + rows,
        encoding="utf-8",
    )
    for n, text in enumerate(units, 1):
        (il / f"u{n:02d}.svg").write_text(text, encoding="utf-8", newline="")
    store = MemoryBlobStore(tmp_path / "cas")
    frozen = [
        LedgerRow(n, (sha := store.add(blob)), slot(sha), "image", "u01")
        for n, blob in enumerate(assets, 1)
    ]
    write_index(job, frozen)
    bundle = ILBundle.load(il, carrier=PptxCompiler().carrier, constructs=TABLE)
    roster = bundle.units
    if plan_units is not None:
        roster = tuple(u for u in bundle.units if u.id in plan_units)
    plan = Plan(
        schema="omniweave.out-plan/1",
        target="pptx",
        slug="deck",
        artifact_gen=1,
        delivery="release",
        units=roster,
        unit_count=len(roster),
        brief=BRIEF,
        corpus="acme",
        cites={},
        gate_status=GateStatus.PASSED,
        il_digest=bundle.il_digest,
        constructs_digest=TABLE.digest(),
        ledger_digest=ledger_digest(frozen),
        brief_digest=BRIEF.digest(),
        card_sha256="sha256:" + "4" * 64,
    )
    Job("omniweave.out-job/1", plan, TRACEPARENT, JobDeterminism(CLOCK_NS)).write(job)
    return job, plan, FrozenLedger(frozen, store), store


def lowered(tmp_path: Path, *units: str, **kwargs: Any) -> Lowered:
    job, plan, ledger, store = job_dir(tmp_path, units, **kwargs)
    compiler = PptxCompiler()
    bundle = ILBundle.load(job / "il", carrier=compiler.carrier, constructs=TABLE)
    result = compiler.lower(plan, bundle, ledger, make_io(store, tmp_path / "io"))
    [ref] = result.produced
    assert ref.kind == ArtifactKind.ARTIFACT
    data = ref.inline if ref.inline is not None else store.open(ref.blob or "").read()
    path = tmp_path / "deck.pptx"
    path.write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        members = {info.filename: zf.read(info) for info in zf.infolist()}
    return Lowered(data, members, plan, path)


def outline(element: Any) -> list[str]:
    """`element` and everything under it, in order: each local name and its attributes."""
    return [
        " ".join([etree.QName(e).localname, *(f"{k}={v}" for k, v in e.attrib.items())])
        for e in element.iter()
        if isinstance(e.tag, str)
    ]


def frame(shape: Any) -> Any:
    """A shape's, a picture's or a group's `a:xfrm`."""
    own = f"{P}grpSpPr" if shape.tag == f"{P}grpSp" else f"{P}spPr"
    return shape.find(f"{own}/{A}xfrm")


def box(shape: Any) -> tuple[int, int, int, int]:
    made = frame(shape)
    off, ext = made.find(f"{A}off"), made.find(f"{A}ext")
    return (int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy")))


def turn(shape: Any) -> tuple[str | None, str | None, str | None]:
    made = frame(shape)
    return (made.get("rot"), made.get("flipH"), made.get("flipV"))


def line_of(shape: Any) -> Any:
    return shape.find(f"{P}spPr/{A}ln")
