"""`compile_artifact()` end to end: the call order's second half, from the gate to the seal.

09-generation.md section 2 (the call order), section 5.1 (preflight), section 5.4 (the
lookup-before-build), section 7.3 (the restriction aggregate), section 10 (the citation ledger)
and D750-D754's pieces, joined. The target is a small text `CompileV1` written here. The store,
the CAS, the ledger, the cite resolver and the JobDir are all real.
"""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the seal wrote.
import tomllib
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO, ClassVar

import pytest
from omniweave.run.out_compile import CompileHost, compile_artifact
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import TargetError, UsageError
from omniweave_core.model.doc import Doc
from omniweave_core.model.enums import Quote, enum_val_rows
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.compile import check
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILBundle
from omniweave_core.out.ledger import AssetLedger, AssetLicence, slot
from omniweave_core.out.marker import Payload, format_marker
from omniweave_core.out.plan import Plan, UnitOutcome
from omniweave_core.out.receipt import ArtefactDeterminism, Receipt
from omniweave_core.out.rules import RuleSpec, TextMeasure
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.artifact import SqliteArtifactStore
from omniweave_core.store.cites import SqliteCiteResolver
from omniweave_core.store.ledger import SqliteAssetLedger
from omniweave_ports import (
    ArtifactRef,
    DriverIO,
    DriverResult,
    ProbeEnv,
    ProbeStatus,
    ProbeVerdict,
    Scalar,
)

NOW_NS = 1_700_000_000_000_000_000
ORD = {(domain, name): ordinal for domain, ordinal, name in enum_val_rows()}
LOGO = b"\x89PNG logo"
LOGO_SHA = hashlib.sha256(LOGO).hexdigest()
BARRED = 1 << 3
CARD = "sha256:" + "4" * 64

TABLE = """\
schema = "omniweave.out-constructs/1"
carrier = "html"
il = "owtext/1"
version = 1
unknown_construct = "forbidden"

[[construct]]
id = "attr.ow-cite"
selector = "@data-ow-cite"
disposition = "native"
round_trip = "exact"
canonical = "cite tokens"
maps_to = "lower.cites:sidecar"
code = "OW_TARGET_CITE_MALFORMED"
since = "0.1.0"

[[construct]]
id = "attr.ow-el"
selector = "@data-ow-el"
disposition = "native"
round_trip = "exact"
canonical = "u<NN>e<NN>"
maps_to = "lower.ids:passthrough"
code = "OW_TARGET_EL_DUPLICATE"
since = "0.1.0"

[[construct]]
id = "elem.ow-manual"
selector = "html|div[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
since = "0.1.0"
"""
CONSTRUCTS = ConstructTable.parse(tomllib.loads(TABLE), {}, source="constructs.toml")
BRIEF = parse_brief(
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n## forbidden\n",
    baseline=(),
)
IL_TOML = (
    'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "sha256:'
    + "7" * 64
    + '"\n\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n\n'
    '[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n'
)
U01 = (
    '<section data-ow-el="u01/e1"><p data-ow-el="u01/e2" data-ow-cite="d7#1" '
    'data-ow-cite-kind="quote" data-ow-cite-span="0:7">Revenue</p></section>'
)
U02 = (
    '<section data-ow-el="u02/e1"><p data-ow-el="u02/e2" data-ow-cite="d7#2">Margins</p>'
    f"<p>{slot(LOGO_SHA)}</p></section>"
)
HOST = CompileHost(
    compile_driver="compile.text.owtext",
    media_type="text/plain",
    suffix=".txt",
    producer_id=1,
    restriction_bits=1 << 9,
    barred_mask=BARRED,
)


class _Clock:
    def monotonic_ns(self) -> int:  # pragma: no cover -- the seal reads wall time only.
        return 0

    def wall_ns(self) -> int:
        return NOW_NS


class _Text:
    """A `CompileV1` whose artefact is its units' bytes, concatenated in roster order."""

    PORT: ClassVar[str] = "compile/1"
    SCHEMA_VERSION: ClassVar[int] = 1

    def __init__(self, **config: Scalar) -> None:
        self.config = config
        self.lowered = 0
        self.lie: dict[str, Any] = {}

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:  # noqa: ARG003 -- the protocol's shape.
        return ProbeVerdict(status=ProbeStatus.OK, detail="stdlib only")

    def carrier(self, path: str, text: str) -> CarrierDoc:
        return html_carrier(path, text, strict=False)

    def rules(self) -> Mapping[str, Sequence[RuleSpec]]:
        return {}

    def measure(self) -> TextMeasure | None:
        return None

    def lower(
        self,
        plan: Plan,
        il: ILBundle,
        ledger: AssetLedger,
        io: DriverIO,
    ) -> DriverResult:
        del ledger  # the protocol's shape; this target reads no ledger
        self.lowered += 1
        body = b"".join(il.data(u.il_path) for u in plan.units)
        return DriverResult(outcome="ok", produced=(ArtifactRef.of("artifact", body, io),))

    def postflight(self, artifact: str, plan: Plan) -> Receipt:
        data = Path(artifact).read_bytes()
        units = {
            u.id: UnitOutcome.MANUAL_REQUIRED if u.manual_reason else UnitOutcome.NATIVE
            for u in plan.units
        }
        fields: dict[str, Any] = {
            "schema": "omniweave.out-receipt/1",
            "target": plan.target,
            "slug": plan.slug,
            "artifact_gen": plan.artifact_gen,
            "output": {
                "path": artifact,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            },
            "part_digest": hashlib.sha256(b"part:" + data).hexdigest(),
            "determinism": (ArtefactDeterminism.PART,),
            "gate_status": plan.gate_status,
            "delivery": plan.delivery,
            "checks": (),
            "units": units,
            "counts": dict(Counter(units.values())),
            "portability": {},
            "normalizations": (),
            "degradations": (),
            "skipped_checks": (),
            "truncations": (),
        }
        fields.update(self.lie)
        return Receipt(**fields)

    def project(self, doc: Doc, io: DriverIO) -> ILBundle:
        raise NotImplementedError


@dataclass
class _Source:
    data: bytes
    doc_ord: int = 7
    media_type: str = "image/png"
    content_length: int | None = None
    claimed_sha256: str | None = None
    licence: AssetLicence | None = None

    def open(self) -> BinaryIO:
        return io.BytesIO(self.data)


def _seed(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, options_digest)"
        " VALUES (1, 'compile.text.owtext', 1, 'f', x'00')"
    )
    connection.execute(
        "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
        " format_evidence, source_bytes, status, model_version, declared, achieved)"
        " VALUES (7, ?, ?, 'file:///c/contract.pdf', 'application/pdf', 'pdf', '{}', 10, 'ok',"
        " '1.1', '{}', '{}')",
        (b"\x07" * 16, b"\x00" * 32),
    )
    connection.execute(
        "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id)"
        " VALUES (7, 1, 0, ?, ?, 1)",
        (ORD["page_kind", "page"], ORD["method", "native_xml"]),
    )
    for block_id, cite, quote, bits, text in (
        (101, "d7#1", Quote.VERBATIM, 0, "Revenue rose 12% in Q3."),
        (102, "d7#2", Quote.NORMALIZED, 0, "Margins held."),
        (103, "d7#3", Quote.VERBATIM, BARRED, "A restricted figure."),
    ):
        connection.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text,"
            " content_digest, os_kind, producer_id, method, trust, quote, origin_operator,"
            " origin_driver, driver_schema_v, restriction_bits)"
            " VALUES (?, 7, 1, 0, ?, ?, ?, ?, ?, ?, x'00', ?, 1, ?, 2, ?, 'parse.pdf',"
            " 'parse.pdf.text', 1, ?)",
            (
                block_id,
                f"p0/{block_id}",
                cite,
                block_id,
                ORD["kind", "paragraph"],
                ORD["layer", "body"],
                text,
                ORD["origin_span_kind", "none"],
                ORD["method", "native_xml"],
                int(quote),
                bits,
            ),
        )
    connection.execute(
        "INSERT INTO asset(asset_id, doc_ord, media_type, sha256, byte_len, store_ref)"
        " VALUES (201, 7, 'image/png', ?, ?, ?)",
        (bytes.fromhex(LOGO_SHA), len(LOGO), f"cas://{LOGO_SHA[:2]}/{LOGO_SHA[2:4]}/{LOGO_SHA}"),
    )


@dataclass
class World:
    job: Path
    out: Path
    owstore: Path
    blobs: BlobStore
    kit: MemoryBlobStore
    tmp: Path
    artifacts: SqliteArtifactStore
    ledger: SqliteAssetLedger
    cites: SqliteCiteResolver

    def write_il(self, **files: str) -> None:
        il = self.job / "il"
        il.mkdir(parents=True, exist_ok=True)
        for name, text in {"il.toml": IL_TOML, "u01.html": U01, "u02.html": U02, **files}.items():
            (il / name).write_text(text, encoding="utf-8", newline="")

    def checked(self, target: _Text) -> ILBundle:
        result = check(self.job, target, target="owtext", constructs=CONSTRUCTS, stage="final")
        assert result.status is GateStatus.PASSED, result.status
        return ILBundle.load(self.job / "il", carrier=target.carrier, constructs=CONSTRUCTS)

    def plan(self, bundle: ILBundle, **fields: Any) -> Plan:
        base: dict[str, Any] = {
            "schema": "omniweave.out-plan/1",
            "target": "owtext",
            "slug": "q3",
            "artifact_gen": 1,
            "delivery": "release",
            "units": bundle.units,
            "unit_count": len(bundle.units),
            "brief": BRIEF,
            "corpus": "acme",
            "cites": {},
            "gate_status": GateStatus.PASSED,
            "il_digest": bundle.il_digest,
            "constructs_digest": CONSTRUCTS.digest(),
            "ledger_digest": self.ledger.digest(),
            "brief_digest": BRIEF.digest(),
            "card_sha256": CARD,
        }
        base.update(fields)
        return Plan(**base)

    def compile(self, target: _Text, plan: Plan, **kw: Any) -> Any:
        return compile_artifact(
            self.job,
            target,
            plan,
            host=kw.pop("host", HOST),
            constructs=CONSTRUCTS,
            ledger=self.ledger,
            cites=self.cites,
            artifacts=self.artifacts,
            blobs=self.blobs,
            io=make_io(self.kit, self.tmp / f"io{target.lowered}"),
            output_root=self.out,
            **kw,
        )

    def rows(self, sql: str) -> list[tuple[Any, ...]]:
        connection = sqlite3.connect(self.owstore)
        try:
            return connection.execute(sql).fetchall()
        finally:
            connection.close()


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    owstore = tmp_path / "index.owstore"
    connection = ow.connect(owstore)
    try:
        assert len(migrate.apply_pending(connection, now_ns=NOW_NS)) == 5
        connection.execute("BEGIN IMMEDIATE")
        _seed(connection)
        connection.execute("COMMIT")
    finally:
        connection.close()
    (tmp_path / "cas").mkdir()
    blobs = BlobStore(tmp_path / "cas")
    thread = ow.StoreThread(lambda: ow.connect(owstore)).start()
    job = tmp_path / "job"
    ledger = SqliteAssetLedger(thread, blobs, job_dir=job)
    try:
        built = World(
            job=job,
            out=tmp_path / "output",
            owstore=owstore,
            blobs=blobs,
            kit=MemoryBlobStore(tmp_path / "kit"),
            tmp=tmp_path,
            artifacts=SqliteArtifactStore(thread, clock=_Clock()),
            ledger=ledger,
            cites=SqliteCiteResolver(thread, corpus="acme"),
        )
        built.write_il()
        ledger.freeze(_Source(LOGO), role="image", unit="u02")
        yield built
    finally:
        thread.close()


# ---------------------------------------------------------------------------
# The whole order
# ---------------------------------------------------------------------------


def test_a_passed_gate_compiles_seals_and_places_the_artefact(world: World) -> None:
    target = _Text()
    bundle = world.checked(target)
    done = world.compile(target, world.plan(bundle))
    assert (done.status, done.exit, target.lowered) == (GateStatus.PASSED, 0, 1)
    assert done.sealed is not None and not done.sealed.hit
    row = done.sealed.row
    body = (U01 + U02).encode()
    assert row.path == "q3@1/q3.txt"
    assert done.path == world.out / "q3@1" / "q3.txt"
    assert done.path.read_bytes() == body
    assert row.sha256 == "sha256:" + hashlib.sha256(body).hexdigest()
    assert row.part_digest == "sha256:" + hashlib.sha256(b"part:" + body).hexdigest()
    assert row.il_store_ref == world.blobs.ref(bundle.il_digest.removeprefix("sha256:"))
    assert row.ledger_digest == world.ledger.digest()
    assert row.gate_status is GateStatus.PASSED
    assert row.restriction_bits == 1 << 9
    receipt = (world.job / "out" / "receipt.json").read_bytes()
    assert row.receipt_sha256 == "sha256:" + hashlib.sha256(receipt).hexdigest()
    assert json.loads(receipt)["slug"] == "q3"
    final = (world.job / "validation" / "final.json").read_bytes()
    assert row.report_sha256 == "sha256:" + hashlib.sha256(final).hexdigest()
    assert world.rows("SELECT unit, outcome, il_path, nsig IS NOT NULL FROM artifact_unit") == [
        ("u01", "native", "il/u01.html", 1),
        ("u02", "native", "il/u02.html", 1),
    ]
    assert world.rows("SELECT asset_id, units FROM artifact_asset") == [(201, '["u02"]')]
    assert world.rows(
        "SELECT unit, el, cite, block_id, doc_gen, kind, span_a, span_b, verbatim"
        " FROM artifact_cite"
    ) == [
        ("u01", "u01/e2", "d7#1", 101, 1, "quote", 0, 7, 1),
        ("u02", "u02/e2", "d7#2", 102, 1, "derived", None, None, 0),
    ]


def test_an_identical_compile_is_the_lookup_and_lowers_nothing(world: World) -> None:
    """OUT12: the second compile is the first one's row, and its bytes are placed again."""
    target = _Text()
    plan = world.plan(world.checked(target))
    first = world.compile(target, plan)
    first.path.unlink()
    again = world.compile(target, plan)
    assert target.lowered == 1
    assert again.sealed.hit and again.sealed.row == first.sealed.row
    assert again.path.read_bytes() == (U01 + U02).encode()
    assert world.rows("SELECT count(*) FROM artifact") == [(1,)]


# ---------------------------------------------------------------------------
# The gate, and the Plan's inputs
# ---------------------------------------------------------------------------


def test_no_final_report_is_not_provided_and_nothing_is_lowered(world: World) -> None:
    target = _Text()
    bundle = ILBundle.load(world.job / "il", carrier=target.carrier, constructs=CONSTRUCTS)
    done = world.compile(target, world.plan(bundle))
    assert (done.status, done.exit, target.lowered, done.sealed) == (
        GateStatus.NOT_PROVIDED,
        8,
        0,
        None,
    )
    assert not world.out.exists()


def test_il_edited_after_the_check_is_stale(world: World) -> None:
    target = _Text()
    plan = world.plan(world.checked(target))
    world.write_il(**{"u01.html": U01.replace("Revenue</p>", "Revenue!</p>")})
    done = world.compile(target, plan)
    assert (done.status, target.lowered) == (GateStatus.STALE, 0)


@pytest.mark.parametrize("field", ["il_digest", "constructs_digest", "ledger_digest"])
def test_a_plan_made_against_other_inputs_is_stale(world: World, field: str) -> None:
    target = _Text()
    plan = world.plan(world.checked(target), **{field: "sha256:" + "9" * 64})
    done = world.compile(target, plan)
    assert (done.status, done.exit, target.lowered) == (GateStatus.STALE, 8, 0)


def test_a_draft_of_a_passed_gate_is_a_usage_error(world: World) -> None:
    target = _Text()
    plan = world.plan(world.checked(target), delivery="draft")
    with pytest.raises(UsageError, match="this gate passed"):
        world.compile(target, plan)


# ---------------------------------------------------------------------------
# Markers, preflight and the aggregate: all before lower()
# ---------------------------------------------------------------------------


def test_an_unresolved_marker_stops_the_compile(world: World) -> None:
    """OUT16: the check passes with a pending note in it; the compile does not."""
    target = _Text()
    doc = html_carrier("il/u01.html", U01, strict=True)
    line = format_marker(
        doc, "u01/e2", "00000000", "2026-09-03T11:04:00Z", Payload(note="x", sev="ask", by="agent")
    )
    world.write_il(**{"u01.html": U01.replace("</section>", f"\n{line}\n</section>")})
    plan = world.plan(world.checked(target))
    with pytest.raises(TargetError) as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_MARKER_UNRESOLVED"
    assert target.lowered == 0


def test_a_plan_roster_the_bundle_does_not_hold_is_refused(world: World) -> None:
    target = _Text()
    bundle = world.checked(target)
    swapped = tuple(replace(u, ord=3 - u.ord) for u in reversed(bundle.units))
    plan = world.plan(bundle, units=swapped)
    with pytest.raises(TargetError, match="roster") as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_ROSTER_MISMATCH"


def test_an_unfrozen_slot_is_preflight_two(world: World) -> None:
    target = _Text()
    other = "a" * 64
    world.write_il(**{"u02.html": U02.replace(LOGO_SHA, other)})
    plan = world.plan(world.checked(target))
    with pytest.raises(TargetError, match=other) as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_ASSET_UNFROZEN"
    assert target.lowered == 0


def test_an_unresolved_cite_is_refused_before_lower(world: World) -> None:
    target = _Text()
    world.write_il(**{"u02.html": U02.replace("d7#2", "d7#99")})
    plan = world.plan(world.checked(target))
    with pytest.raises(TargetError, match="d7#99") as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_CITE_UNRESOLVED"
    assert caught.value.fix == "ow open d7#99"
    assert target.lowered == 0


def test_a_barred_cite_is_restricted_exit_six_and_nothing_is_written(world: World) -> None:
    """Aggregate #2: the store governs bytes at compile time, naming what it bars."""
    target = _Text()
    world.write_il(**{"u02.html": U02.replace("d7#2", "d7#3")})
    plan = world.plan(world.checked(target))
    done = world.compile(target, plan)
    assert (done.status, done.exit, target.lowered) == (GateStatus.RESTRICTED, 6, 0)
    assert [(r.what, r.id, r.cite) for r in done.restricted] == [("cite", 103, "d7#3")]
    assert world.rows("SELECT count(*) FROM artifact") == [(0,)]
    allowed = world.compile(target, plan, host=replace(HOST, barred_mask=0))
    assert allowed.status is GateStatus.PASSED


# ---------------------------------------------------------------------------
# lower() and postflight(): the receipt must describe the compile
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("lie", "said"),
    [
        ({"slug": "other"}, "slug"),
        ({"artifact_gen": 2}, "artifact_gen"),
        ({"output": {"path": "x", "bytes": 1, "sha256": "0" * 64}}, "output.bytes"),
    ],
)
def test_a_receipt_that_misdescribes_the_compile_is_refused(
    world: World, lie: dict[str, Any], said: str
) -> None:
    target = _Text()
    target.lie = lie
    plan = world.plan(world.checked(target))
    with pytest.raises(TargetError, match=said) as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_PACKAGE_CORRUPT"
    assert world.rows("SELECT count(*) FROM artifact") == [(0,)]
    assert not world.out.exists()


def test_a_receipt_outcome_the_classifier_disagrees_with_is_refused(world: World) -> None:
    target = _Text()
    target.lie = {
        "units": {"u01": UnitOutcome.NATIVE, "u02": UnitOutcome.REBUILT},
        "counts": {UnitOutcome.NATIVE: 1, UnitOutcome.REBUILT: 1},
    }
    plan = world.plan(world.checked(target))
    with pytest.raises(TargetError, match="classifier") as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_UNIT_UNCLASSIFIED"


class _NoArtefact(_Text):
    def lower(
        self,
        plan: Plan,
        il: ILBundle,
        ledger: AssetLedger,
        io: DriverIO,
    ) -> DriverResult:
        del plan, il, ledger, io  # the protocol's shape; this target produces nothing
        self.lowered += 1
        return DriverResult(outcome="ok", produced=())


class _TwoArtefacts(_Text):
    def lower(self, plan: Plan, il: ILBundle, ledger: AssetLedger, io: DriverIO) -> DriverResult:
        one = super().lower(plan, il, ledger, io).produced[0]
        return DriverResult(outcome="ok", produced=(one, one))


@pytest.mark.parametrize(("target", "count"), [(_NoArtefact(), 0), (_TwoArtefacts(), 2)])
def test_lower_returns_exactly_one_artefact(world: World, target: _Text, count: int) -> None:
    plan = world.plan(world.checked(target))
    with pytest.raises(TargetError, match=f"{count} artifact refs") as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_PACKAGE_CORRUPT"


# ---------------------------------------------------------------------------
# Ruling 7: the cite rows, as the IL states them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("u01", "said"),
    [
        (U01.replace(' data-ow-el="u01/e2"', ""), "carries no data-ow-el"),
        (U01.replace('"quote"', '"rumour"'), "data-ow-cite-kind 'rumour'"),
        (U01.replace('"0:7"', '"7:7"'), "is not a:b with a < b"),
        (U01.replace('"0:7"', '"zero:7"'), "is not a:b with a < b"),
    ],
)
def test_a_citation_the_il_cannot_state_is_refused(world: World, u01: str, said: str) -> None:
    target = _Text()
    world.write_il(**{"u01.html": u01})
    plan = world.plan(world.checked(target))
    with pytest.raises(TargetError, match=said) as caught:
        world.compile(target, plan)
    assert caught.value.code() == "OW_TARGET_IL_MALFORMED"


def test_a_quote_the_store_disproves_is_a_quote_but_not_verbatim(world: World) -> None:
    """The kind is the author's; `verbatim` is only ever the predicate's."""
    target = _Text()
    world.write_il(**{"u01.html": U01.replace('"0:7"', '"0:8"')})
    plan = world.plan(world.checked(target))
    world.compile(target, plan)
    assert world.rows(
        "SELECT kind, span_a, span_b, verbatim FROM artifact_cite WHERE unit='u01'"
    ) == [("quote", 0, 8, 0)]


# ---------------------------------------------------------------------------
# D756: a manual region, and the Plan's units rebuilt from the bundle
# ---------------------------------------------------------------------------

MANUAL_U02 = U02.replace(
    "</section>", '<div data-ow-el="u02/e9" data-ow-manual="unverifiable_data">?</div></section>'
)


def _manual(world: World, target: _Text) -> ILBundle:
    world.write_il(**{"u02.html": MANUAL_U02})
    result = check(world.job, target, target="owtext", constructs=CONSTRUCTS, stage="final")
    assert result.status is GateStatus.MANUAL_REQUIRED
    return ILBundle.load(world.job / "il", carrier=target.carrier, constructs=CONSTRUCTS)


def test_a_release_of_a_manual_unit_is_a_closed_gate(world: World) -> None:
    target = _Text()
    plan = world.plan(_manual(world, target))
    done = world.compile(target, plan)
    assert (done.status, done.exit, target.lowered) == (GateStatus.MANUAL_REQUIRED, 8, 0)


def test_a_draft_of_a_manual_unit_seals_its_reason(world: World) -> None:
    """09 section 9: the draft is a second row with a different delivery, never a pass."""
    target = _Text()
    bundle = _manual(world, target)
    plan = world.plan(
        bundle,
        units=tuple(replace(u, manual_reason=None) for u in bundle.units),
        delivery="draft",
        gate_status=GateStatus.MANUAL_REQUIRED,
    )
    done = world.compile(target, plan)
    assert done.sealed is not None
    assert (done.sealed.row.delivery, done.sealed.row.gate_status) == (
        "draft",
        GateStatus.MANUAL_REQUIRED,
    )
    assert world.rows("SELECT unit, outcome, reason FROM artifact_unit") == [
        ("u01", "native", None),
        ("u02", "manual_required", "unverifiable_data"),
    ]


def test_the_plans_units_are_rebuilt_from_the_bundle(world: World) -> None:
    """09 section 3.7 note 4: a Plan with no nsig, or a stale one, seals the bundle's."""
    target = _Text()
    bundle = world.checked(target)
    blind = tuple(replace(u, nsig=None) for u in bundle.units)
    done = world.compile(target, world.plan(bundle, units=blind))
    assert done.sealed is not None
    assert [r.nsig for r in world.artifacts.units(done.sealed.row.artifact_id)] == [
        u.nsig for u in bundle.units
    ]
