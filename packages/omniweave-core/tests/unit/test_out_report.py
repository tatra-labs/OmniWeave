"""`omniweave_core.out`'s diagnostic and gate: the fold, the ten statuses, the digest, the report.

09-generation.md section 4.1 (the severity x provenance table), 4.2 (the `Finding`, the fold, the
JSON and the console), 4.5 (`gate_status()`, `il_digest`) and 14.3 (the second fold). Charter OUT3
to OUT7. W9.1's estimation basis gives the fold *"a fixture per severity x provenance cell"*; that
is `test_each_severity_and_provenance_cell_does_what_09_says`, twelve cases.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import omniweave_core.out.finding as finding_module
import omniweave_core.out.report as report_module
import pytest
from omniweave_core.errors import ConfigError, load_register
from omniweave_core.out import (
    Finding,
    FindingSet,
    GateStatus,
    ILFile,
    OutReport,
    Provenance,
    Severity,
    SkippedCheck,
    Truncation,
    gate_status,
    il_digest,
    render,
)
from omniweave_core.out.gate import CLEARS, clears, exit_code
from omniweave_core.out.job import UNREADABLE, read_il_files
from omniweave_core.out.report import _finding_json, parse_digest, report_path

FIX = "ow out normalize --target pptx --construct attr.fill.lowercase-hex"


def _finding(**fields: object) -> Finding:
    base: dict[str, object] = {
        "code": "OW_TARGET_FILL_NOT_UPPER_HEX",
        "severity": Severity.WARNING,
        "provenance": Provenance.INTRODUCED,
        "rule": "pptx.style.fill@1",
        "unit": "u02",
        "msg": "fill is not uppercase hex",
        "fix": FIX,
    }
    base.update(fields)
    return Finding(**base)  # type: ignore[arg-type]


def _file(name: str, data: bytes = b"x") -> ILFile:
    return ILFile(name, hashlib.sha256(data).hexdigest(), len(data))


FILES = (
    _file("il.toml", b"schema = 1"),
    _file("u01.svg", b"<svg/>"),
    _file("u02.svg", b"<svg></svg>"),
)


def _report(findings: Sequence[Finding] | FindingSet = (), **fields: object) -> OutReport:
    found = findings if isinstance(findings, FindingSet) else FindingSet(tuple(findings))
    base: dict[str, object] = {
        "stage": "final",
        "target": "pptx",
        "constructs_digest": "sha256:" + "7" * 64,
        "files": FILES,
        "units": ("u01", "u02"),
        "findings": found,
    }
    base.update(fields)
    return OutReport.build(**base)  # type: ignore[arg-type]


def _digest(report: OutReport) -> bytes:
    return parse_digest(il_digest(report.il_files))


# ---------------------------------------------------------------------------
# Finding (OUT6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fix", ["", "   "])
def test_a_finding_without_a_fix_command_is_refused(fix: str) -> None:
    with pytest.raises(ValueError, match="exact command"):
        _finding(fix=fix)


def test_a_finding_holds_at_most_three_examples_and_a_count_of_one_or_more() -> None:
    _finding(examples=("a", "b", "c"))
    with pytest.raises(ValueError, match="4 examples"):
        _finding(examples=("a", "b", "c", "d"))
    with pytest.raises(ValueError, match="below 1"):
        _finding(count=0)
    with pytest.raises(ValueError, match="never re-folded"):
        _finding(unit_examples=("u01",))


# ---------------------------------------------------------------------------
# The fold (OUT7), rulings 1-2
# ---------------------------------------------------------------------------


def test_two_hundred_lowercase_colours_on_one_slide_are_one_finding() -> None:
    colours = [_finding(examples=(f'fill="#{i:06x}"',)) for i in range(200)]
    (folded,) = FindingSet(tuple(colours)).fold().findings
    assert folded.count == 200
    assert folded.examples == ('fill="#000000"', 'fill="#000001"', 'fill="#000002"')


def test_the_fold_keeps_unit_canonical_severity_and_provenance_apart() -> None:
    base = _finding()
    apart = [
        base,
        replace(base, unit="u03"),
        replace(base, canonical="#RRGGBB"),
        replace(base, severity=Severity.ERROR),
        replace(base, provenance=Provenance.INHERITED),
    ]
    assert len(FindingSet(tuple(apart)).fold().findings) == 5
    together = [base, replace(base, msg="another wording", at="il/u02.svg:9:1")]
    (folded,) = FindingSet(tuple(together)).fold().findings
    assert folded.count == 2
    assert folded.msg == base.msg, "a folded finding keeps its first member's fields"


def test_the_fold_sums_counts_and_is_idempotent() -> None:
    findings = [
        _finding(count=3, examples=("a",)),
        _finding(count=4, examples=("a", "b")),
        _finding(unit="u01"),
    ]
    once = FindingSet(tuple(findings)).fold()
    assert sum(f.count for f in once.findings) == 8
    assert once.findings[0].examples == ("a", "b")
    assert once.fold() == once


def test_past_the_ceiling_the_set_refolds_without_the_unit_and_records_it() -> None:
    findings = [_finding(unit=f"u{n:02d}", examples=(f"e{n}",)) for n in range(1, 6)]
    findings.append(
        _finding(code="OW_TARGET_SCRIPT_FORBIDDEN", severity=Severity.ERROR, unit="u04")
    )
    refolded = FindingSet(tuple(findings)).fold(limit=3)
    assert [f.code for f in refolded.findings] == [
        "OW_TARGET_FILL_NOT_UPPER_HEX",
        "OW_TARGET_SCRIPT_FORBIDDEN",
    ]
    colour = refolded.findings[0]
    assert (colour.unit, colour.at, colour.el, colour.count) == ("", None, None, 5)
    assert colour.units_affected == 5
    assert colour.unit_examples == ("u01", "u02", "u03")
    assert refolded.truncations == (Truncation("refold", before=6, after=2),)
    assert refolded.fold(limit=1) == refolded, (
        "a re-folded set is not re-folded, nor recorded twice"
    )


# ---------------------------------------------------------------------------
# 09 section 4.1's table: twelve cells
# ---------------------------------------------------------------------------

_CELLS = [
    (Severity.ERROR, Provenance.INTRODUCED, GateStatus.FAILED, 0),
    (Severity.ERROR, Provenance.INHERITED, GateStatus.FAILED, 0),
    (Severity.ERROR, Provenance.IMPORTED, GateStatus.FAILED, 0),
    (Severity.ERROR, Provenance.FRAMEWORK, GateStatus.FAILED, 0),
    (Severity.WARNING, Provenance.INTRODUCED, GateStatus.PASSED, 1),
    (Severity.WARNING, Provenance.INHERITED, GateStatus.PASSED, 0),
    (Severity.WARNING, Provenance.IMPORTED, GateStatus.PASSED, 0),
    (Severity.WARNING, Provenance.FRAMEWORK, GateStatus.PASSED, 0),
    (Severity.INFO, Provenance.INTRODUCED, GateStatus.PASSED, 0),
    (Severity.INFO, Provenance.INHERITED, GateStatus.PASSED, 0),
    (Severity.INFO, Provenance.IMPORTED, GateStatus.PASSED, 0),
]


@pytest.mark.parametrize(("severity", "provenance", "status", "introduced"), _CELLS)
def test_each_severity_and_provenance_cell_does_what_09_says(
    severity: Severity, provenance: Provenance, status: GateStatus, introduced: int
) -> None:
    report = _report([_finding(severity=severity, provenance=provenance)])
    assert report.gate() == (status, introduced)
    assert report.counts[severity.value] == 1
    assert report.by_provenance[provenance.value] == 1


def test_the_twelfth_cell_a_framework_info_is_a_recorded_skip_and_the_gate_is_unverified() -> None:
    skip = SkippedCheck(
        rule="pptx.text.overflow@2",
        needs="measure",
        reason="uharfbuzz is not importable",
        fix="uv pip install 'omniweave-target-pptx[measure]'",
    )
    report = _report([], skipped=[skip])
    (finding,) = report.findings
    assert (finding.code, finding.severity, finding.provenance) == (
        "OW_TARGET_CHECK_SKIPPED",
        Severity.INFO,
        Provenance.FRAMEWORK,
    )
    assert finding.fix == skip.fix
    assert report.gate() == (GateStatus.UNVERIFIED, 0)
    assert exit_code(GateStatus.UNVERIFIED, report) == 64, (
        "an absent engine is exit 64 (09 section 15)"
    )


def test_a_truncation_is_a_framework_finding_and_keeps_the_gate_unverified() -> None:
    cut = FindingSet(
        (_finding(),), (Truncation("rule", before=9_000, after=5_000, rule="pptx.style.fill@1"),)
    )
    report = _report(cut)
    assert {f.code for f in report.findings} == {
        "OW_TARGET_FILL_NOT_UPPER_HEX",
        "OW_TARGET_FINDINGS_TRUNCATED",
    }
    assert report.gate() == (GateStatus.UNVERIFIED, 1)
    assert exit_code(GateStatus.UNVERIFIED, report) == 8, (
        "a truncation is the rule's defect, not an engine's"
    )
    #  D766: the fix is a command the CLI parses, the global `--render json` and not `--json`.
    [truncated] = [f for f in report.findings if f.code == "OW_TARGET_FINDINGS_TRUNCATED"]
    assert truncated.fix.endswith("--stage final --render json")


def test_summary_buckets_units_and_counts_count_findings() -> None:
    findings = [
        _finding(unit="u01", severity=Severity.ERROR, code="OW_TARGET_SCRIPT_FORBIDDEN"),
        _finding(unit="u01"),
        _finding(unit="u02"),
        _finding(unit="u02", code="OW_TARGET_ID_WITH_STYLE"),
    ]
    report = _report(findings, units=("u01", "u02", "u03"))
    assert report.summary == {"units": 3, "clean": 1, "warned": 1, "blocked": 1}
    assert report.counts == {"error": 1, "warning": 3, "info": 0}
    assert report.introduced_warning_count == 3


def test_summary_is_taken_before_the_refold_drops_the_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(finding_module, "MAX_FOLDED_FINDINGS", 1)
    findings = [
        _finding(unit="u01", severity=Severity.ERROR),
        _finding(unit="u02", code="OW_TARGET_ID_WITH_STYLE"),
    ]
    report = _report(findings)
    assert report.truncations == (Truncation("refold", before=2, after=2),)
    assert report.summary == {"units": 2, "clean": 0, "warned": 1, "blocked": 1}
    assert {f.unit for f in report.findings} == {""}


# ---------------------------------------------------------------------------
# gate_status(): ten values, one order (OUT4, OUT5)
# ---------------------------------------------------------------------------


def test_the_gate_reads_bytes_before_content() -> None:
    report = _report([_finding(severity=Severity.ERROR)])
    other = parse_digest("sha256:" + "0" * 64)
    assert gate_status(report, _digest(report)) == (GateStatus.FAILED, 0)
    assert gate_status(report, other) == (GateStatus.STALE, 0), (
        "a stale report's errors point at moved lines"
    )


def test_each_status_in_09s_order() -> None:
    clean = _report([])
    digest = _digest(clean)
    assert gate_status(None, digest) == (GateStatus.NOT_PROVIDED, 0)
    assert gate_status(OutReport.blank(unreadable=True), digest) == (GateStatus.UNREADABLE, 0)
    assert gate_status(
        OutReport.blank(schema="omniweave.out-report/2", unreadable=False), digest
    ) == (
        GateStatus.UNSUPPORTED_SCHEMA,
        0,
    )
    early = _report([_finding(severity=Severity.ERROR)], stage="early")
    assert gate_status(early, digest)[0] is GateStatus.NON_FINAL, "non-final outranks failed"
    restricted = _report(
        [], restricted=[{"cite": "d7#412"}], manual=[{"unit": "u01", "reason": "unrepresentable"}]
    )
    assert gate_status(restricted, digest)[0] is GateStatus.RESTRICTED, "restricted outranks manual"
    manual = _report([], manual=[{"unit": "u01", "reason": "unrepresentable"}])
    assert gate_status(manual, digest)[0] is GateStatus.MANUAL_REQUIRED
    skipped = SkippedCheck("r@1", "measure", "absent", "uv pip install x")
    both = _report([_finding(severity=Severity.ERROR)], skipped=[skipped])
    assert gate_status(both, digest)[0] is GateStatus.FAILED, "failed outranks unverified"
    unverified = _report([], skipped=[skipped], restricted=[{"cite": "d7#412"}])
    assert gate_status(unverified, digest)[0] is GateStatus.UNVERIFIED, (
        "unverified outranks restricted"
    )
    assert gate_status(clean, digest) == (GateStatus.PASSED, 0)


def test_the_nine_refusals_each_name_a_distinct_meaning_and_a_command() -> None:
    refusals = [s for s in GateStatus if s is not GateStatus.PASSED]
    assert set(CLEARS) == set(refusals)
    meanings = [clears(s, "pptx") for s in refusals]
    assert all(m is not None and m[1].startswith("ow out ") for m in meanings)
    assert len({m[0] for m in meanings if m is not None}) == 9
    assert clears(GateStatus.PASSED, "pptx") is None
    assert clears(GateStatus.MANUAL_REQUIRED, "docx") == (
        "a unit needs a human",
        "ow out compile --target docx --accept-manual",
    )


def test_the_exit_codes_are_09_section_15s() -> None:
    assert exit_code(GateStatus.PASSED, None) == 0
    assert exit_code(GateStatus.RESTRICTED, None) == 6
    assert exit_code(GateStatus.NOT_PROVIDED, None) == 8
    assert exit_code(GateStatus.FAILED, None) == 8
    assert exit_code(GateStatus.STALE, None) == 8


# ---------------------------------------------------------------------------
# il_digest (OUT4), rulings 8-10
# ---------------------------------------------------------------------------


def test_il_digest_is_09s_framing_over_basenames(tmp_path: Path) -> None:
    (tmp_path / "u01.svg").write_bytes(b"<svg/>")
    (tmp_path / "il.toml").write_bytes(b"")
    files = read_il_files(tmp_path)
    assert [f.name for f in files] == ["il.toml", "u01.svg"]
    assert files[0].byte_len == 0 and files[0].sha256 == hashlib.sha256(b"").hexdigest(), "ruling 9"
    framed = b"".join(
        f.name.encode() + b"\x00" + hashlib.sha256(data).hexdigest().encode() + b"\n"
        for f, data in zip(files, (b"", b"<svg/>"), strict=True)
    )
    assert il_digest(files) == "sha256:" + hashlib.sha256(framed).hexdigest()
    assert il_digest(tuple(reversed(files))) == il_digest(files)


def test_il_digest_ignores_where_the_job_lives_and_the_stamp_lock(tmp_path: Path) -> None:
    one, two = tmp_path / "a" / "il", tmp_path / "b" / "deeper" / "il"
    for root in (one, two):
        root.mkdir(parents=True)
        (root / "u01.svg").write_bytes(b"<svg/>")
    (two / ".stamp.lock").write_bytes(b"pid 1")
    (two / "assets").mkdir()
    assert il_digest(read_il_files(one)) == il_digest(read_il_files(two))
    (two / "u01.svg").write_bytes(b"<svg />")
    assert il_digest(read_il_files(one)) != il_digest(read_il_files(two)), "the gate binds to bytes"


def test_an_unreadable_file_contributes_the_literal_and_never_drops_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "u01.svg").write_bytes(b"<svg/>")
    (tmp_path / "u02.svg").write_bytes(b"<svg/>")
    real_open = Path.open

    def refuse(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "u02.svg":
            raise PermissionError(13, "Permission denied", str(self))
        return real_open(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "open", refuse)
    files = read_il_files(tmp_path)
    assert files[1] == ILFile("u02.svg", UNREADABLE, 0, "PermissionError: Permission denied")
    assert str(tmp_path) not in (files[1].error or ""), "ruling 10: no path in the report"
    without = il_digest(files[:1])
    assert il_digest(files) != without


def test_an_il_file_row_holds_its_two_iffs() -> None:
    with pytest.raises(ValueError, match="basename"):
        ILFile("il/u01.svg", "0" * 64, 1)
    with pytest.raises(ValueError, match="hex"):
        ILFile("u01.svg", "A" * 64, 1)
    with pytest.raises(ValueError, match="iff"):
        ILFile("u01.svg", UNREADABLE, 0)
    with pytest.raises(ValueError, match="iff"):
        ILFile("u01.svg", "0" * 64, 1, "an error")
    with pytest.raises(ValueError, match="byte_len"):
        ILFile("u01.svg", UNREADABLE, 3, "an error")


# ---------------------------------------------------------------------------
# The report on disk, ruling 15
# ---------------------------------------------------------------------------


def test_a_report_round_trips_through_its_file(tmp_path: Path) -> None:
    skip = SkippedCheck(
        "pptx.text.overflow@2", "measure", "absent", "uv pip install x", el="u01/e3"
    )
    report = _report(
        [
            _finding(examples=("a", "b")),
            _finding(unit="u01", severity=Severity.ERROR, at="il/u01.svg:4:2"),
        ],
        skipped=[skip],
        markers=[{"el": "u03/e17", "id": "k-1a2b3c4d", "state": "pending"}],
        portability={"external_asset_refs": ["https://x"]},
        timings={"b@1": 2, "a@1": 4},
    )
    path = report.write(tmp_path)
    assert path == tmp_path / "validation" / "final.json"
    loaded = OutReport.load(path)
    assert loaded == report
    assert loaded is not None and loaded.as_json() == report.as_json()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["gate"] == {
        "status": "failed",
        "introduced_warning_count": 1,
        "exit": 8,
        "fix": "ow out check --target pptx --stage final --render json",
    }
    assert doc["skipped_checks"] == [skip.as_json()]
    assert list(doc["rule_timings_ms"]) == ["a@1", "b@1"]
    assert not list((tmp_path / "validation").glob(".*")), "the write leaves no temporary file"


def test_each_stage_writes_its_own_file(tmp_path: Path) -> None:
    for stage in ("early", "first-unit", "unit", "final"):
        assert _report([], stage=stage).write(tmp_path).name == f"{stage}.json"
    with pytest.raises(ValueError, match="not one of"):
        report_path(tmp_path, "release")


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"\xff\xfe",
        b"[]",
        b'{"schema": 1}',
        b'{"schema": "omniweave.out-report/1"}',
    ],
)
def test_a_report_that_does_not_parse_is_unreadable_and_not_absent(
    tmp_path: Path, content: bytes
) -> None:
    path = tmp_path / "final.json"
    path.write_bytes(content)
    loaded = OutReport.load(path)
    assert loaded is not None
    assert loaded.unreadable
    assert gate_status(loaded, b"")[0] is GateStatus.UNREADABLE
    assert OutReport.load(tmp_path / "absent.json") is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("il_digest", "sha256:abc"),
        ("counts", {"error": 0}),
        ("introduced_warning_count", True),
        ("findings", [{"code": "X"}]),
        ("truncations", None),
    ],
)
def test_a_v1_report_with_a_bad_field_is_unreadable(
    tmp_path: Path, field: str, value: object
) -> None:
    doc = _report([]).as_json()
    doc[field] = value
    path = tmp_path / "final.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    loaded = OutReport.load(path)
    assert loaded is not None and loaded.unreadable


def test_another_schema_is_unsupported_and_not_unreadable(tmp_path: Path) -> None:
    path = tmp_path / "final.json"
    path.write_text(
        json.dumps({"schema": "omniweave.out-report/2", "stage": "final"}), encoding="utf-8"
    )
    loaded = OutReport.load(path)
    assert loaded is not None and not loaded.unreadable
    assert gate_status(loaded, b"")[0] is GateStatus.UNSUPPORTED_SCHEMA


# ---------------------------------------------------------------------------
# The console (OUT6), ruling 11
# ---------------------------------------------------------------------------


def test_the_console_renders_the_json_and_resolves_the_numeric() -> None:
    report = _report(
        [
            _finding(
                count=200,
                examples=('fill="#3a7bd5"', 'fill="#ffffff"'),
                canonical="#RRGGBB",
                at="il/u02.svg:19:14",
            ),
            _finding(
                code="OW_TARGET_SCRIPT_FORBIDDEN",
                severity=Severity.ERROR,
                unit="u03",
                el="u03/e17",
                construct="elem.script",
                fix="remove <script> from il/u03.svg",
            ),
        ],
        units=("u01", "u02", "u03"),
    )
    text = render(report.as_json())
    numerics = load_register().by_symbol
    lines = text.splitlines()
    assert lines[0].startswith(
        "gate: failed   (1 blocking · 1 introduced warning · 0 skipped checks · il_digest"
    )
    error_at = next(i for i, line in enumerate(lines) if line.startswith("E "))
    warning_at = next(i for i, line in enumerate(lines) if line.startswith("W "))
    assert error_at < warning_at, "errors first"
    assert (
        lines[error_at].split()[1] == numerics["OW_TARGET_SCRIPT_FORBIDDEN"].numeric == "OW-T-401"
    )
    assert "u03/e17" in lines[error_at]
    assert "  construct: elem.script   provenance: introduced" in lines
    assert "  canonical: #RRGGBB   provenance: introduced" in lines
    assert '  examples: fill="#3a7bd5" | fill="#ffffff"' in lines
    assert lines[warning_at].endswith("x200")
    assert lines[-2:] == [
        "1 blocking. Release refused: gate = failed.",
        "Clear with: ow out check --target pptx --stage final --render json      (exit 8)",
    ]
    loaded = json.loads(json.dumps(report.as_json()))
    assert render(loaded) == text, "the console is a function of the JSON alone"


def test_the_console_on_a_passed_report_and_a_refolded_finding() -> None:
    assert render(_report([]).as_json()).splitlines()[-1] == "Release permitted: gate = passed."
    refolded = replace(_finding(), unit="", units_affected=40, unit_examples=("u01", "u02", "u03"))
    doc = _report([]).as_json()
    doc["findings"] = [_finding_json(refolded)]
    assert "  units: 40 (u01, u02, u03)" in render(doc).splitlines()


def test_render_never_fails_for_want_of_the_register(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> object:
        raise ConfigError("codes.toml is unreadable", fix="git checkout codes.toml")

    monkeypatch.setattr(report_module, "load_register", broken)
    text = render(_report([_finding()]).as_json())
    assert "W OW_TARGET_FILL_NOT_UPPER_HEX" in text
