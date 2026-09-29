"""Hops 5-9 over real files: evidence, `evaluate()`, `resolve()`, the decision, `admit()`, the plan.

Every run is the real `ow ingest` composition over a real store, the real catalog (the installed
first-party drivers, found through D128's editable-install locator), the shipped route policy and
the installed signal registry. The OPC packages are built here from their structure.
"""

from __future__ import annotations

import hashlib
import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import zipfile
from importlib.metadata import distributions
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from omniweave.route.demand import compile_demand
from omniweave.route.evidence import build_registry, builtin_specs, installed_specs
from omniweave.route.policy import builtin_layer, compile_policy, load_layer
from omniweave.run import ingest as ingest_module
from omniweave.run import routing
from omniweave.run.dispatch import Batch
from omniweave.run.ingest import ingest
from omniweave.run.routing import resolve_policy, unit_evidence
from omniweave_core.clock import SystemClock
from omniweave_core.config import Config, load
from omniweave_core.host.signals import SignalAnswer
from omniweave_core.store.sqlite import StoreThread, Unit, connect
from omniweave_core.work import WorkRow
from omniweave_ports.types import CostClass

from omniweave import plan

if TYPE_CHECKING:
    from collections.abc import Iterator

HANDBOOK = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
OPT_IN = "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
"""The three `[drivers]` opt-ins a checkout needs before any first-party driver resolves (D576)."""
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            f'<Override PartName="/word/document.xml" ContentType="{DOCX}.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="r" Type="{REL}" Target="word/document.xml"/></Relationships>',
        )
        archive.writestr("word/document.xml", "<w:document/>")
    return path


def _project(tmp_path: Path, *, drivers: str = OPT_IN) -> tuple[Path, Config]:
    (tmp_path / "omniweave.toml").write_text(HANDBOOK + drivers, encoding="utf-8")
    docs = tmp_path / "docs"
    _docx(docs / "memo.docx")
    (docs / "notes.txt").write_text("plain words\n", encoding="utf-8")
    (docs / "empty.txt").write_bytes(b"")
    (docs / "report.pdf").write_bytes(b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n")
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    return tmp_path / ".omniweave" / "index.owstore", config


def _run(tmp_path: Path, store: Path, config: Config, *, paths: bool = True) -> object:
    return ingest(
        store,
        config=config,
        source_root=tmp_path,
        output_root=tmp_path / ".omniweave" / "out",
        cache_root=tmp_path / ".omniweave" / "cache",
        argv=["ingest"],
        paths=(tmp_path / "docs",) if paths else (),
        sweep_ms=20,
    )


def _rows(store: Path, sql: str) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(store)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _unit(store: Path, suffix: str, columns: str = "state") -> tuple[object, ...]:
    (row,) = _rows(store, f"SELECT {columns} FROM unit WHERE unit_uri LIKE '%{suffix}'")  # noqa: S608
    return row


# ---------------------------------------------------------------------------------------------
# the planned path: a DOCX reaches a routed `parse.office` row
# ---------------------------------------------------------------------------------------------


def test_an_office_document_is_decided_admitted_planned_and_then_parsed(
    tmp_path: Path,
) -> None:
    """02:475-479, hops 5-9: the decision row BEFORE anything runs (05:1103), then 02:479's row --
    which hops 10-17 now take to a terminal status in the same run. This DOCX is a bare
    `<w:document/>` with no WordprocessingML namespace: it routes and plans exactly as a real one
    does -- detection reads the package, not the body -- and anydoc then refuses the body as
    `CORRUPT_INPUT`, which fails the unit with no `doc` row (05:405)."""
    store, config = _project(tmp_path)
    report = _run(tmp_path, store, config)
    assert report.routed is not None  # type: ignore[attr-defined]
    assert dict(report.routed.planned) == {"parse.office.anydoc": 1}  # type: ignore[attr-defined]
    assert _unit(store, "memo.docx", "state, acq_failure_class") == ("failed", "corrupt_input")
    ((operator, version, driver, status, cost, key, decision, priority, part),) = _rows(
        store,
        "SELECT operator, op_version, driver, status, cost_class, dispatch_key, decision_id, "
        "priority, unit_part FROM work WHERE operator <> 'op.identify'",
    )
    assert (operator, version, driver, status, cost, part) == (
        "parse.office",
        1,
        "parse.office.anydoc",
        "failed_permanent",
        "free",
        "",
    )
    assert len(str(key)) == 16
    assert priority == plan.PLAN_PRIORITY
    decided = _rows(
        store,
        "SELECT rule_id, driver, rung, admission, lane, pricebook_digest FROM route_decision "  # noqa: S608
        f"WHERE decision_id = '{decision}'",
    )
    assert decided == [("decode.office-native", "parse.office.anydoc", 1, "admitted", "text", "")]
    assert _rows(store, "SELECT count(*) FROM route_unit_decision") == [(2,)], "docx + empty"
    ((evidence,),) = _rows(store, "SELECT count(*) FROM route_evidence")
    assert int(str(evidence)) >= 1


def test_a_second_run_decides_the_same_and_plans_nothing_twice(tmp_path: Path) -> None:
    """05:1175-1177: two runs that compute one decision converge on one row."""
    store, config = _project(tmp_path)
    _run(tmp_path, store, config)
    before = _rows(store, "SELECT decision_id FROM route_decision ORDER BY 1")
    _run(tmp_path, store, config, paths=False)
    assert _rows(store, "SELECT decision_id FROM route_decision ORDER BY 1") == before
    assert _rows(store, "SELECT count(*) FROM work WHERE operator = 'parse.office'") == [(1,)]
    ((_reports, hits),) = _rows(store, "SELECT count(*), max(hits) FROM resolution_report")
    assert int(str(hits)) >= 1


# ---------------------------------------------------------------------------------------------
# what is refused, and what is honestly not routed
# ---------------------------------------------------------------------------------------------


def test_a_gate_refusal_writes_a_driverless_decision_and_fails_the_unit(tmp_path: Path) -> None:
    """05:1180: *"A `GATE` refusal writes a row with `driver = ''`"*; 05:405's terminal `failed`."""
    store, config = _project(tmp_path)
    report = _run(tmp_path, store, config)
    assert dict(report.routed.refused) == {"gate.empty": 1}  # type: ignore[attr-defined]
    assert _unit(store, "empty.txt", "state, acq_failure_class") == ("failed", "corrupt_input")
    assert _rows(store, "SELECT driver, rung FROM route_decision WHERE rule_id = 'gate.empty'") == [
        ("", 0)
    ]


def test_a_refused_unit_stays_refused_across_runs(tmp_path: Path) -> None:
    """D580. Acquisition retried every `failed` unit, re-read the refused file, cleared its class
    and left it `acquired` -- where nothing identifies or routes it again."""
    store, config = _project(tmp_path)
    _run(tmp_path, store, config)
    _run(tmp_path, store, config, paths=False)
    assert _unit(store, "empty.txt", "state, acq_failure_class") == ("failed", "corrupt_input")


def test_a_pdf_whose_deciding_signal_pdfium_cannot_compute_is_not_refused(tmp_path: Path) -> None:
    """D579, kept by D628. `decode.pdf-text-layer` defers on `decode.char_count`, and this run's
    real pdfium child cannot open the stub `report.pdf`. A later rule -- `decode.no-rule-matched`
    -- would refuse it as `unsupported_format`; it stays `identified`, and the report says why."""
    store, config = _project(tmp_path)
    report = _run(tmp_path, store, config)
    assert _unit(store, "report.pdf") == ("identified",)
    reasons = list(report.routed.unrouted)  # type: ignore[attr-defined]
    held = [reason for reason in reasons if reason.startswith("deferred (decode.pdf-text-layer")]
    assert len(held) == 1, reasons
    assert "decode.char_count: omniweave_pdf.signals: PdfiumError" in held[0]
    assert report.routed.children == {"pdfium": 3}  # type: ignore[attr-defined]
    assert not _rows(store, "SELECT 1 FROM route_decision WHERE rule_id = 'decode.no-rule-matched'")


def test_a_rule_naming_a_driver_no_package_provides_plans_nothing(tmp_path: Path) -> None:
    """`decode.text-native` names `parse.text.builtin`, which `[drivers] enabled` lists and no
    distribution ships: the unit stays `identified` and the report names the driver."""
    store, config = _project(tmp_path)
    report = _run(tmp_path, store, config)
    assert _unit(store, "notes.txt") == ("identified",)
    assert report.routed.unrouted["parse.text.builtin: not installed"] == 1  # type: ignore[attr-defined]


def test_by_the_shipped_driver_defaults_nothing_on_a_checkout_resolves(tmp_path: Path) -> None:
    """D576: no attestation (`ow conform` writes it), no `omniweave.lock` writer, and an `inproc`
    driver whose editable install cannot be pinned. Reported per driver, never waived."""
    store, config = _project(tmp_path, drivers="")
    report = _run(tmp_path, store, config)
    assert not report.routed.planned  # type: ignore[attr-defined]
    assert report.routed.unrouted["parse.office.anydoc: unattested"] == 1  # type: ignore[attr-defined]
    assert _unit(store, "memo.docx") == ("identified",)


def test_the_report_names_what_was_planned_and_what_stopped_it(tmp_path: Path) -> None:
    store, config = _project(tmp_path)
    lines = _run(tmp_path, store, config).lines()  # type: ignore[attr-defined]
    assert any(line.startswith("  route     1 planned (parse.office.anydoc 1)") for line in lines)
    assert "  parse     1 failed (corrupt_input 1)" in lines
    assert all(line.isascii() for line in lines)


def test_a_row_no_executor_serves_is_refused_by_name() -> None:
    """D578, narrowed by W7.3z: `parse.*` rows have an executor now, and a row of any other family
    -- `derive.*`, `embed.*` -- is still refused by name, so the Supervisor's crash path holds it
    for the reaper rather than failing it for a driver that never ran."""
    executors = ingest_module._Executors.__new__(ingest_module._Executors)
    row = WorkRow(
        id=1, unit_uri="u", unit_part="", operator="derive.segment", op_version=1,
        cache_key="k" * 64, decision_id="d", sequence_id=None, driver="derive.segment.spine",
        cost_class="free", dispatch_key="0" * 16, service=None, staged_gen=None,
        status="claimed", failure_class=None, failure_message=None, retry_after=None,
        attempts_total=1, attempts_today=1, last_attempt_at=None, stale_since=None,
        claimed_by="w", claimed_gen=1, lease_expires=0, cost_micros=0, queued_ms=0, ran_ms=0,
        peak_rss_bytes=0, priority=200,
    )  # fmt: skip
    with pytest.raises(ingest_module.NoExecutorError, match=r"derive\.segment"):
        executors(Batch(invoke_id="i", rows=(row,)))


# ---------------------------------------------------------------------------------------------
# the parts: evidence, the resolve policy, the plan's operator
# ---------------------------------------------------------------------------------------------


def test_the_free_group_is_the_roster_and_two_keys_are_honestly_unknown() -> None:
    """05 section 5.1's FREE keys the roster holds; `unit.corrupt` and a PDF's `unit.encrypted` are
    UNAVAILABLE with a reason, because nothing checked them."""
    registry = build_registry(builtin_specs())
    derived = '{"format_evidence":{"chosen":{"basis":"magic"}}}'
    row = ("c:/x/a.pdf", "a" * 64, 10, 1, "pdf", "application/pdf", "internal", derived)
    ev = unit_evidence(row, registry=registry, trigger="cli")
    assert ev.read("unit.format") == "pdf"
    assert ev.read("unit.format_basis") == "magic"
    assert (ev.read("unit.bytes"), ev.read("unit.part_count")) == (10, 1)
    assert (ev.read("trigger.kind"), ev.read("unit.schema_requested")) == ("cli", False)
    assert ev.read("unit.corrupt") is None
    assert ev.read("unit.encrypted") is None
    docx = ("c:/x/a.docx", "a" * 64, 10, 1, "docx", DOCX, "internal", derived)
    assert unit_evidence(docx, registry=registry, trigger="cli").read("unit.encrypted") is False


def test_the_resolve_policy_is_the_drivers_block_with_this_host(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(HANDBOOK + OPT_IN, encoding="utf-8")
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "h")})
    policy = resolve_policy(config)
    assert (policy.allow_unattested, policy.require_lock, policy.inproc_ids) == (
        True,
        False,
        frozenset(),
    )
    assert policy.host_env is not None


def test_the_operator_is_the_driver_s_port_family() -> None:
    """02:479: `operator='parse.pdf'` for `parse.pdf.pdfium`."""
    assert plan.operator_of("parse.pdf.pdfium") == "parse.pdf"
    assert plan.operator_of("parse.office.anydoc") == "parse.office"
    with pytest.raises(Exception, match="no operator can be derived"):
        plan.operator_of("anydoc")


def test_the_executor_refusal_names_the_row_it_cannot_run() -> None:
    error = ingest_module.NoExecutorError("parse.office", "parse.office.anydoc")
    assert "parse.office" in str(error)
    assert "hops 10-17" in str(error)


# ---------------------------------------------------------------------------------------------
# the signal groups: 05:1096-1100's loop, with a recording computer (D628)
# ---------------------------------------------------------------------------------------------

PDFIUM = {"pdfium": "omniweave_pdf"}
CLAMP_TO_FREE = b"""surface = "route"
[[rule]]
id = "gate.test-free-only"
rung = "GATE"
when = { "unit.format" = "pdf" }
then = { max_cost_class = "free" }
"""
PDF_ROW = ("c:/x/a.pdf", "a" * 64, 10, 1, "pdf", "application/pdf", "internal", "{}")


class _Computer:
    """`routing.Compute`, answering from a table and recording every child it would have started."""

    def __init__(self, values: dict[str, Any], unavailable: dict[str, str] | None = None) -> None:
        self.values, self.unavailable = values, unavailable or {}
        self.asked: list[tuple[str, tuple[str, ...]]] = []

    def __call__(self, package: str, source: str, digest: str, keys: tuple[str, ...]) -> Any:
        del source, digest
        self.asked.append((package, keys))
        return SignalAnswer(
            values={k: v for k, v in self.values.items() if k in keys},
            unavailable={
                k: self.unavailable.get(k, f"{package}.signals does not compute {k}")
                for k in keys
                if k not in self.values
            },
        )


@pytest.fixture
def signals(tmp_path: Path) -> Iterator[StoreThread]:
    """A migrated store for the router's `route_signal` reads and writes, and nothing else."""
    store = tmp_path / "signals.owstore"
    ingest_module._create(store, now_ns=0)
    with StoreThread(lambda: connect(store)) as thread:
        yield thread


def _router(
    thread: StoreThread,
    computer: _Computer,
    *,
    layers: tuple[bytes, ...] = (),
    shipped: bool = True,
) -> Any:
    registry = build_registry((*builtin_specs(), *installed_specs(distributions()).specs))
    extra = [load_layer(raw, layer="project", origin="test") for raw in layers]
    policy = compile_policy([*([builtin_layer()] if shipped else []), *extra], registry=registry)
    return routing._Router(
        thread=thread,
        ctx=SimpleNamespace(trigger="cli", clock=SystemClock()),  # type: ignore[arg-type]
        policy=policy,
        registry=registry,
        catalog=None,  # type: ignore[arg-type]
        resolving=None,  # type: ignore[arg-type]
        source_root="",
        now_ms=0,
        demand=compile_demand(policy, registry=registry),
        computers=PDFIUM,
        compute=computer,
    )


def _decide(router: Any, row: tuple[object, ...] = PDF_ROW) -> tuple[Any, Any]:
    ev = unit_evidence(row, registry=router.registry, trigger="cli", computers=router.computers)
    return router.decide(ev, row), ev


def test_a_clean_pdf_computes_two_free_groups_and_never_the_local_one(signals: StoreThread) -> None:
    """05:3110 and INV-13: `decode.pdf-text-layer` matches on the FREE group, no earlier rule
    defers, so `ink.tiles` is never asked for and no raster is rendered."""
    computer = _Computer({"unit.part_count": 3, "corpus.is_form": False, "decode.char_count": 900})
    decision, ev = _decide(_router(signals, computer))
    assert (decision.rule_id, decision.driver) == ("decode.pdf-text-layer", "parse.pdf.pdfium")
    assert computer.asked == [
        ("omniweave_pdf", ("corpus.is_form", "unit.part_count")),
        ("omniweave_pdf", ("decode.char_count",)),
    ]
    assert not ev.computed("ink.tiles")
    assert ("decode.char_count", "1.0.0", 900) in ev.read_set()


def test_a_pdf_page_count_is_the_computer_answer_and_not_the_roster_one(
    signals: StoreThread,
) -> None:
    """05:2199 and 05:2222: the key resolves to `pdfium` for a PDF, so the roster's `1` is not put
    under `builtin`'s version first."""
    computer = _Computer({"unit.part_count": 12_000, "corpus.is_form": False})
    decision, ev = _decide(_router(signals, computer))
    assert decision.rule_id == "gate.too-many-parts"
    assert ev.read("unit.part_count") == 12_000


def test_a_scanned_pdf_promotes_the_local_group_and_is_held_on_ink_tiles(
    signals: StoreThread,
) -> None:
    """`decode.blank-part-escape` defers on `ink.tiles`, which nothing computes: the LOCAL group is
    asked for, answers nothing, and the unit is held rather than settled on the later rule."""
    computer = _Computer({"unit.part_count": 1, "corpus.is_form": False, "decode.char_count": 0})
    router = _router(signals, computer)
    decision, _ev = _decide(router)
    assert decision.rule_id == "decode.no-text-layer"
    assert computer.asked[-1] == ("omniweave_pdf", ("ink.tiles",))
    router.route(PDF_ROW)
    assert dict(router.tally.unrouted) == {
        "deferred (decode.blank-part-escape): ink.tiles: omniweave_pdf.signals does not compute "
        "ink.tiles": 1
    }


def test_a_pdf_pdfium_could_not_read_is_held_and_never_refused_as_unsupported(
    signals: StoreThread,
) -> None:
    """D579, kept: once its groups ran, `decode.pdf-text-layer` is still UNKNOWN, and a settle on
    `decode.no-rule-matched` would refuse the unit for good as `unsupported_format`."""
    why = "omniweave_pdf.signals: PdfiumError: Failed to load document"
    keys = ("unit.part_count", "corpus.is_form", "decode.char_count")
    router = _router(signals, _Computer({}, dict.fromkeys(keys, why)))
    decision, _ev = _decide(router)
    assert decision.rule_id == "decode.no-rule-matched"
    router.route(PDF_ROW)
    assert not router.tally.refused
    (reason,) = router.tally.unrouted
    assert reason.startswith("deferred (decode.pdf-text-layer, decode.blank-part-escape")
    assert reason.endswith(f"decode.char_count: {why}")


def test_a_value_of_the_wrong_dtype_is_unavailable_not_compared(signals: StoreThread) -> None:
    computer = _Computer({"unit.part_count": 1, "corpus.is_form": False, "decode.char_count": "9"})
    _decision, ev = _decide(_router(signals, computer))
    assert ev.read("decode.char_count") is None
    assert ev.unavailable_reason("decode.char_count") == "the provider answered str, not int"


def test_the_gate_clamp_keeps_the_local_group_uncomputed(signals: StoreThread) -> None:
    """05:1117: *"still under the `GATE` clamp"*. A scanned page under a `free` clamp never asks
    for `ink.tiles`, and is held on the key it could not compute."""
    computer = _Computer({"unit.part_count": 1, "corpus.is_form": False, "decode.char_count": 0})
    router = _router(signals, computer, layers=(CLAMP_TO_FREE,))
    _decision, ev = _decide(router)
    assert all(keys != ("ink.tiles",) for _package, keys in computer.asked)
    assert not ev.computed("ink.tiles")
    router.route(PDF_ROW)
    (reason,) = router.tally.unrouted
    assert reason == "deferred (decode.blank-part-escape): ink.tiles: not computed"


def test_an_office_unit_starts_no_child_and_reads_as_it_did_before_there_was_one(
    signals: StoreThread,
) -> None:
    """`officexml` ships no computer: its keys are put UNAVAILABLE with an empty version, which is
    `read_set()`'s own spelling for a key nobody computed."""
    computer = _Computer({})
    docx = ("c:/x/a.docx", "a" * 64, 10, 1, "docx", DOCX, "internal", "{}")
    decision, ev = _decide(_router(signals, computer), docx)
    assert decision.rule_id == "decode.office-native"
    assert computer.asked == []
    assert ev.unavailable_reason("corpus.is_form") == "the officexml provider ships no computer"
    unknown = [(key, version) for key, version, value in ev.read_set() if value is None]
    assert unknown
    assert all(version == "" for _key, version in unknown), unknown


NO_CATCH_ALL = (
    CLAMP_TO_FREE
    + b"""
[[rule]]
id = "decode.test-blank"
rung = "DECODE"
on_unknown = "defer"
when = { "ink.tiles" = { lte = 4 } }
then = { outcome = "ok", terminal = true, reason = "blank-part" }
"""
)


def test_a_group_above_the_clamp_is_not_computed_when_nothing_matched_below_it(
    signals: StoreThread,
) -> None:
    """`next_group()`'s rule, on the path the shipped policy never takes: its
    `decode.no-rule-matched` always matches on the FREE group, so there `deferrals_pending()` is
    what the clamp stops. With no catch-all, nothing matches and the loop reaches the LOCAL group,
    which a `free` clamp forbids."""
    computer = _Computer({"unit.part_count": 1, "corpus.is_form": False})
    decision, ev = _decide(_router(signals, computer, layers=(NO_CATCH_ALL,), shipped=False))
    assert decision is None
    assert not ev.computed("ink.tiles")
    assert computer.asked == []


# ---------------------------------------------------------------------------------------------
# route_signal: 05 section 5.4's cache, read before the child and written after it (D632)
# ---------------------------------------------------------------------------------------------

CLEAN = {"unit.part_count": 3, "corpus.is_form": False, "decode.char_count": 900}
SIGNAL_ROWS = (
    "SELECT signal_key, signal_version, value, unavailable_reason, compute_ms, computed_at "
    "FROM route_signal ORDER BY signal_key"
)


def _signal_rows(thread: StoreThread) -> list[tuple[object, ...]]:
    return cast(
        "list[tuple[object, ...]]",
        thread.run(
            Unit(
                name="test.read",
                run=lambda c: c.execute(SIGNAL_ROWS).fetchall(),  # type: ignore[attr-defined]
                cost_class="free",
                wait_ms=1000,
            )
        ),
    )


def _execute(thread: StoreThread, sql: str) -> None:
    thread.run(
        Unit(
            name="test.write",
            run=lambda c: c.execute(sql),  # type: ignore[attr-defined]
            cost_class="free",
            wait_ms=1000,
        )
    )


def test_a_second_run_over_the_same_content_starts_no_child_and_decides_the_same(
    signals: StoreThread,
) -> None:
    """05:1097's *"route_signal cache first"*: a clean PDF's two FREE groups are two children the
    first time and none the second, and the read set -- the decision's identity -- is unchanged."""
    first_computer, again_computer = _Computer(CLEAN), _Computer(CLEAN)
    first, first_ev = _decide(_router(signals, first_computer))
    router = _router(signals, again_computer)
    again, again_ev = _decide(router)
    assert len(first_computer.asked) == 2
    assert again_computer.asked == []
    assert (again.rule_id, again.driver) == (first.rule_id, first.driver)
    assert again_ev.read_set_digest() == first_ev.read_set_digest()
    assert dict(router.tally.cached) == {"pdfium": 3}
    assert not router.tally.children


def test_each_computed_key_is_one_row_under_its_provider_version(signals: StoreThread) -> None:
    router = _router(signals, _Computer(CLEAN))
    router.now_ms = 1_234
    _decide(router)
    rows = _signal_rows(signals)
    assert [(key, version) for key, version, *_ in rows] == [
        ("corpus.is_form", "1.0.0"),
        ("decode.char_count", "1.0.0"),
        ("unit.part_count", "1.0.0"),
    ]
    assert [value for _k, _v, value, *_ in rows] == [b"false", b"900", b"3"]
    assert all(reason is None for *_, reason, _ms, _at in rows)
    assert all(isinstance(ms, int) and ms >= 0 for *_, ms, _at in rows)
    assert {at for *_, at in rows} == {1_234}


def test_a_kept_reason_is_cached_so_a_held_unit_is_not_recomputed(signals: StoreThread) -> None:
    """05:2352: *"we tried and could not" is a cacheable fact*. The scanned PDF is held on
    `ink.tiles`, which pdfium's computer does not compute; the next run holds it again, for the same
    reason, without asking the child for anything."""
    scan = {"unit.part_count": 1, "corpus.is_form": False, "decode.char_count": 0}
    first = _router(signals, _Computer(scan))
    first.route(PDF_ROW)
    computer = _Computer(scan)
    again = _router(signals, computer)
    again.route(PDF_ROW)
    assert computer.asked == []
    assert dict(again.tally.unrouted) == dict(first.tally.unrouted)
    (reason,) = [row[3] for row in _signal_rows(signals) if row[0] == "ink.tiles"]
    assert reason == "omniweave_pdf.signals does not compute ink.tiles"


def test_a_refused_request_is_not_cached_and_is_asked_again(signals: StoreThread) -> None:
    """A timeout, a crash, changed bytes or a raising provider is not a function of the content,
    so the next run asks again, as it did before the cache existed."""

    class _Refusing(_Computer):
        def __call__(self, package: str, source: str, digest: str, keys: tuple[str, ...]) -> Any:
            super().__call__(package, source, digest, keys)
            return SignalAnswer.refused(keys, "the pdfium provider did not answer in 120 s")

    _decide(_router(signals, _Refusing({})))
    assert _signal_rows(signals) == []
    computer = _Computer(CLEAN)
    _decide(_router(signals, computer))
    assert len(computer.asked) == 2


def test_another_version_or_other_content_is_a_miss(signals: StoreThread) -> None:
    _decide(_router(signals, _Computer(CLEAN)))
    _execute(signals, "UPDATE route_signal SET signal_version = '0.9.0'")
    computer = _Computer(CLEAN)
    _decide(_router(signals, computer))
    assert len(computer.asked) == 2
    other = ("c:/x/b.pdf", "b" * 64, *PDF_ROW[2:])
    computer = _Computer(CLEAN)
    _decide(_router(signals, computer), other)
    assert len(computer.asked) == 2


def test_only_the_keys_the_cache_lacks_go_to_the_child(signals: StoreThread) -> None:
    _decide(_router(signals, _Computer(CLEAN)))
    _execute(signals, "DELETE FROM route_signal WHERE signal_key = 'unit.part_count'")
    computer = _Computer(CLEAN)
    decision, ev = _decide(_router(signals, computer))
    assert computer.asked == [("omniweave_pdf", ("unit.part_count",))]
    assert decision.rule_id == "decode.pdf-text-layer"
    assert ev.read("corpus.is_form") is False


def test_a_cached_value_comes_back_as_the_type_it_was_given(signals: StoreThread) -> None:
    """`1.0` stays a `float` and `True` a `bool`, or the read set would name another value."""
    router = _router(signals, _Computer({}))
    versions = {"a.float": "1", "a.bool": "1", "a.str": "1", "a.int": "1"}
    answered = SignalAnswer(
        values={"a.float": 1.0, "a.bool": True, "a.str": "x", "a.int": 7}, unavailable={}
    )
    router._remember("c" * 64, versions, tuple(versions), answered, 3)
    kept = router._cached("c" * 64, versions)
    assert kept.values == answered.values
    assert [type(value) for value in kept.values.values()] == [float, bool, str, int]


def test_the_report_names_the_cached_signals(signals: StoreThread) -> None:
    scan = {"unit.part_count": 1, "corpus.is_form": False, "decode.char_count": 0}
    _router(signals, _Computer(scan)).route(PDF_ROW)
    router = _router(signals, _Computer(scan))
    router.route(PDF_ROW)
    assert "  route     4 signals cached (pdfium 4)" in router.tally.lines()


def test_a_run_that_read_nothing_from_the_cache_reports_no_cache_line(
    signals: StoreThread,
) -> None:
    scan = {"unit.part_count": 1, "corpus.is_form": False, "decode.char_count": 0}
    router = _router(signals, _Computer(scan))
    router.route(PDF_ROW)
    assert not router.tally.cached
    assert not any("signals cached" in line for line in router.tally.lines())


def test_the_real_child_is_started_once_for_a_scan_held_twice(
    signals: StoreThread, tmp_path: Path
) -> None:
    """Through `host.signals`' own child: `no_text_layer.pdf` is held on `ink.tiles` both times,
    and the second routing reads every one of its four keys back rather than starting a child."""
    pdf = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures" / "no_text_layer.pdf"
    raw = pdf.read_bytes()
    row = (
        str(pdf),
        hashlib.sha256(raw).hexdigest(),
        len(raw),
        1,
        "pdf",
        "application/pdf",
        "internal",
        "{}",
    )
    ctx = SimpleNamespace(roots=SimpleNamespace(cache=tmp_path / "cache"), run_id="r1")
    real = routing._child_compute(ctx)  # type: ignore[arg-type]
    first = _router(signals, cast("_Computer", real))
    first.route(row)
    again = _router(signals, cast("_Computer", real))
    again.route(row)
    assert sum(first.tally.children.values()) == 3
    assert not again.tally.children
    assert dict(again.tally.cached) == {"pdfium": 4}
    assert dict(again.tally.unrouted) == dict(first.tally.unrouted)
    ((reason, _count),) = again.tally.unrouted.items()
    assert reason.startswith("deferred (decode.blank-part-escape): ink.tiles:")


# ---------------------------------------------------------------------------------------------
# --ignore-evidence-cache: recompute what route_signal holds, never a billed key (D633)
# ---------------------------------------------------------------------------------------------


class _Billed:
    """The registry, with one key moved to `billed_api`, as a billed provider's key would be."""

    def __init__(self, registry: Any, key: str) -> None:
        self._registry, self._key = registry, key

    def cost_class_of(self, key: str) -> Any:
        return CostClass.BILLED_API if key == self._key else self._registry.cost_class_of(key)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._registry, name)


def test_the_flag_recomputes_every_cached_key_and_writes_over_its_row(
    signals: StoreThread,
) -> None:
    """05:2822: *"re-computes `route_signal` rows"*. Both FREE groups go to the child again, and
    each row is the second run's: `computed_at` is its `now_ms`."""
    _decide(_router(signals, _Computer(CLEAN)))
    computer = _Computer({**CLEAN, "decode.char_count": 901})
    router = _router(signals, computer)
    router.ignore_evidence_cache = True
    router.now_ms = 9_999
    _decision, ev = _decide(router)
    assert len(computer.asked) == 2
    assert not router.tally.cached
    assert ev.read("decode.char_count") == 901
    assert {row[5] for row in _signal_rows(signals)} == {9_999}
    assert [row[2] for row in _signal_rows(signals) if row[0] == "decode.char_count"] == [b"901"]


def test_without_the_flag_the_same_router_reads_the_cache(signals: StoreThread) -> None:
    _decide(_router(signals, _Computer(CLEAN)))
    router = _router(signals, _Computer(CLEAN))
    assert router.ignore_evidence_cache is False
    _decide(router)
    assert dict(router.tally.cached) == {"pdfium": 3}


def test_the_flag_never_recomputes_a_billed_key(signals: StoreThread) -> None:
    """18:988-990: re-running billed work is `--allow-rebill`'s, which prints what it discards."""
    _decide(_router(signals, _Computer(CLEAN)))
    computer = _Computer(CLEAN)
    router = _router(signals, computer)
    router.registry = _Billed(router.registry, "decode.char_count")
    router.ignore_evidence_cache = True
    _decide(router)
    assert computer.asked == [("omniweave_pdf", ("corpus.is_form", "unit.part_count"))]
    assert dict(router.tally.cached) == {"pdfium": 1}


def test_only_free_and_local_compute_are_recomputable() -> None:
    assert {CostClass.FREE, CostClass.LOCAL_COMPUTE} == routing.RECOMPUTABLE


def test_a_held_scan_rerouted_by_ingest_reads_the_cache_unless_told_not_to(
    tmp_path: Path,
) -> None:
    """Through `ingest()` and the real signal child: `no_text_layer.pdf` is held on `ink.tiles`, so
    every run re-routes it. The second reads its four keys back; the third, under the flag, starts
    the children again."""
    (tmp_path / "omniweave.toml").write_text(HANDBOOK + OPT_IN, encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    fixture = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures"
    (docs / "scan.pdf").write_bytes((fixture / "no_text_layer.pdf").read_bytes())
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "owhome")})
    store = tmp_path / ".omniweave" / "index.owstore"

    def lines(**flags: bool) -> list[str]:
        report = ingest(
            store,
            config=config,
            source_root=tmp_path,
            output_root=tmp_path / ".omniweave" / "out",
            cache_root=tmp_path / ".omniweave" / "cache",
            argv=["ingest"],
            paths=(docs,),
            sweep_ms=20,
            **flags,
        )
        return [line for line in report.lines() if "signal" in line]

    first, second, third = lines(), lines(), lines(ignore_evidence_cache=True)
    assert any("signal children" in line for line in first)
    assert not any("signals cached" in line for line in first)
    assert any("4 signals cached (pdfium 4)" in line for line in second)
    assert not any("signal children" in line for line in second)
    assert any("signal children" in line for line in third)
    assert not any("signals cached" in line for line in third)
