"""Hops 5-9 over real files: evidence, `evaluate()`, `resolve()`, the decision, `admit()`, the plan.

Every run is the real `ow ingest` composition over a real store, the real catalog (the installed
first-party drivers, found through D128's editable-install locator), the shipped route policy and
the installed signal registry. The OPC packages are built here from their structure.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the assertions read the store the run wrote.
import zipfile
from pathlib import Path

import pytest
from omniweave.route.evidence import build_registry, builtin_specs
from omniweave.run import ingest as ingest_module
from omniweave.run.dispatch import Batch
from omniweave.run.ingest import ingest
from omniweave.run.routing import resolve_policy, unit_evidence
from omniweave_core.config import Config, load
from omniweave_core.work import WorkRow

from omniweave import plan

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


def test_a_pdf_whose_deciding_signal_nobody_computes_is_not_refused(tmp_path: Path) -> None:
    """D579. `decode.pdf-text-layer` defers on `decode.char_count`; nothing computes it, and a
    later rule -- `decode.no-rule-matched` -- would refuse every PDF as `unsupported_format`."""
    store, config = _project(tmp_path)
    report = _run(tmp_path, store, config)
    assert _unit(store, "report.pdf") == ("identified",)
    reasons = list(report.routed.unrouted)  # type: ignore[attr-defined]
    assert any(reason.startswith("deferred (decode.pdf-text-layer") for reason in reasons)
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
