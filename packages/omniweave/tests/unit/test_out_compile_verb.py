"""`ow out compile [--accept-manual] [--job DIR]`: a gated JobDir lowered in an S4 worker, sealed.

Each test scaffolds an owtext JobDir through `ow out scaffold`, authors a unit with no citation (so
the seal's `artifact_cite` rows name no block an empty store lacks), checks it at `final`, and
compiles it. The worker is a real child process on the named-pipe arm; the tests that refuse
before lowering run anywhere. `run.out_compile`'s own rulings are `test_run_out_compile.py`'s.
"""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_core.errors import TargetError
from omniweave_core.out.brief import BRIEF_SCHEMA
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent
GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "out" / "golden" / "owtext" / "il"
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n"
    "- u02: { anchor: content }\n## forbidden\n"
)
U01 = (
    '<section data-ow-el="u01/e1">\n'
    '  <p data-ow-el="u01/e2" class="lead" id="intro">Revenue rose 12% in Q3.</p>\n'
    "</section>\n"
)
ROW = '\n[[unit]]\nid = "{unit}"\nord = {ord}\nfile = "{unit}.html"\n'
TEXT = "== u01 ==\nRevenue rose 12% in Q3.\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    (tmp_path / "brief.md").write_text(BRIEF.replace("- u02: { anchor: content }\n", ""))
    return tmp_path


def _env(home: Path) -> dict[str, str]:
    return {
        "OMNIWEAVE_HOME": str(home / "owhome"),
        "HOME": str(home / "home"),
        "USERPROFILE": str(home / "home"),
        "OMNIWEAVE_DRIVER_PATH": str(SUITES),
    }


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", *argv], cwd=cwd, env=_env(cwd), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _job(project: Path, *, manual: bool = False) -> Path:
    """A scaffolded JobDir with a cite-free `u01` authored, and the golden `u02` when `manual`."""
    if manual:
        (project / "brief.md").write_text(BRIEF, encoding="utf-8")
    code, out, err = _run(
        ["scaffold", "owtext", "--brief", "brief.md", "--slug", "q3", "--render", "json"], project
    )
    assert (code, err) == (0, "")
    job = Path(json.loads(out)["job_dir"])
    (job / "il" / "u01.html").write_text(U01, encoding="utf-8", newline="")
    rows = ROW.format(unit="u01", ord=1)
    if manual:
        shutil.copyfile(GOLDEN / "u02.html", job / "il" / "u02.html")
        rows += ROW.format(unit="u02", ord=2)
    il = job / "il" / "il.toml"
    il.write_text(il.read_text(encoding="utf-8") + rows, encoding="utf-8")
    return job


def _checked(project: Path, *, manual: bool = False) -> Path:
    job = _job(project, manual=manual)
    code, _out, err = _run(["check", "--stage", "final", "--job", str(job)], project)
    assert (code, err) == (8 if manual else 0, "")
    return job


def _compile(project: Path, job: Path, *argv: str) -> tuple[int, dict[str, Any]]:
    code, out, err = _run(["compile", "--job", str(job), "--render", "json", *argv], project)
    assert err == "", err
    document: dict[str, Any] = json.loads(out)
    return code, document


# ---------------------------------------------------------------------------------------------
# Rulings 16, 17, 19 and 20: lowered in a worker, sealed, placed
# ---------------------------------------------------------------------------------------------


def test_a_passed_gate_is_lowered_in_a_worker_sealed_and_placed(project: Path) -> None:
    job = _checked(project)
    code, out, err = _run(["compile", "--job", str(job)], project)
    assert (code, err) == (0, "")
    lines = out.splitlines()
    assert lines[0].startswith("[POSTFLIGHT] slug=q3 gen=1 status=passed gate=passed units=1")
    placed = project / ".omniweave" / "out" / "q3@1" / "q3.txt"
    assert lines[-1] == f"sealed q3@1 (release) at {placed}"
    assert placed.read_bytes() == TEXT.encode()
    code, listed, err = _run(["list", "--corpus", "handbook", "--render", "json"], project)
    assert (code, err) == (0, "")
    [row] = json.loads(listed)
    assert (row["slug"], row["artifact_gen"], row["gate_status"]) == ("q3", 1, "passed")


def test_the_json_report_and_a_second_compile_that_is_the_lookup(project: Path) -> None:
    job = _checked(project)
    code, first = _compile(project, job)
    assert code == 0
    assert (first["status"], first["delivery"], first["hit"], first["restricted"]) == (
        "passed",
        "release",
        False,
        [],
    )
    assert first["sha256"].startswith("sha256:")
    assert first["postflight"].startswith("[POSTFLIGHT]")
    code, second = _compile(project, job)
    assert code == 0
    assert second["hit"] is True
    assert (second["path"], second["sha256"]) == (first["path"], first["sha256"])
    assert second["postflight"] is None, "a lookup hit lowers nothing and writes no receipt"
    code, out, err = _run(["compile", "--job", str(job)], project)
    assert (code, err) == (0, "")
    assert out.splitlines() == ["lookup hit: q3@1 is an earlier compile's bytes, placed again"]


def test_the_store_holds_one_producer_row_for_the_card(project: Path) -> None:
    job = _checked(project)
    _compile(project, job)
    _compile(project, job)
    connection = store_sqlite.connect(project / ".omniweave" / "index.owstore")
    try:
        rows = connection.execute(
            "SELECT op_version, code_fingerprint FROM producer"
            " WHERE operator = 'compile.text.owtext'"
        ).fetchall()
    finally:
        connection.close()
    assert rows == [(1, "")]


# ---------------------------------------------------------------------------------------------
# Rulings 17, 18 and 20: closed gates, nothing lowered
# ---------------------------------------------------------------------------------------------


def test_no_final_report_is_not_provided_and_lowers_nothing(project: Path) -> None:
    job = _job(project)
    code, out, err = _run(["compile", "--job", str(job)], project)
    assert (code, err) == (8, "")
    assert out.splitlines() == [
        "gate not-provided: nothing was lowered (exit 8)",
        "re-check: ow out check --stage final",
    ]
    assert not (project / ".omniweave" / "out").exists()


def _docx(project: Path) -> Path:
    """A scaffolded docx JobDir with one owflow/1 unit authored and checked at `final`."""
    code, out, err = _run(
        ["scaffold", "docx", "--brief", "brief.md", "--slug", "memo", "--render", "json"], project
    )
    assert (code, err) == (0, "")
    job = Path(json.loads(out)["job_dir"])
    (job / "il" / "u01.html").write_text(
        '<section><h1>Memo</h1><p>Revenue rose.<a data-ow-note="n1"></a></p>'
        '<aside data-ow-footnote="n1"><p>Audited.</p></aside></section>',
        encoding="utf-8",
        newline="",
    )
    il = job / "il" / "il.toml"
    il.write_text(il.read_text(encoding="utf-8") + ROW.format(unit="u01", ord=1), "utf-8")
    code, _out, err = _run(["check", "--stage", "final", "--job", str(job)], project)
    assert (code, err) == (0, "")
    return job


def test_an_unimplemented_target_is_refused_before_its_gate(project: Path) -> None:
    """Ruling 24 (D781): a JobDir naming video, whose card says it cannot lower."""
    job = _docx(project)
    document = json.loads((job / "job.json").read_bytes())
    document["plan"]["target"] = "video"
    (job / "job.json").write_text(json.dumps(document), encoding="utf-8")
    code, out, err = _run(["compile", "--job", str(job)], project)
    assert (code, out) == (TargetError.EXIT, "")
    assert err.startswith(
        "ow: OW-T-514: compile.video.native cannot compile: [compile] implemented"
    )
    assert "fix: ow out check --target video --stage final" in err
    assert not (project / ".omniweave" / "out").exists()


def test_a_docx_job_compiles_in_a_worker_and_seals(project: Path) -> None:
    """D783: owflow/1 through the S4 worker, sealed, placed, and a Word package with its note."""
    job = _docx(project)
    code, out, err = _run(["compile", "--job", str(job)], project)
    assert (code, err) == (0, "")
    placed = project / ".omniweave" / "out" / "memo@1" / "memo.docx"
    assert out.splitlines()[-1] == f"sealed memo@1 (release) at {placed}"
    with zipfile.ZipFile(placed) as zf:
        names = set(zf.namelist())
        document = zf.read("word/document.xml").decode()
    assert {"word/document.xml", "word/footnotes.xml", "customXml/omniweave-provenance.json"} <= (
        names
    )
    assert "Revenue rose." in document
    assert "<w:footnoteReference" in document
    code, listed, err = _run(["list", "--corpus", "handbook", "--render", "json"], project)
    assert (code, err) == (0, "")
    [row] = json.loads(listed)
    assert (row["slug"], row["target"]) == ("memo", "docx")


def test_il_edited_after_the_check_is_stale(project: Path) -> None:
    job = _checked(project)
    (job / "il" / "u01.html").write_text(U01.replace("12%", "13%"), encoding="utf-8")
    code, document = _compile(project, job)
    assert (code, document["status"], document["path"]) == (8, "stale", None)


def test_a_manual_gate_is_closed_until_accept_manual_asks_for_its_draft(project: Path) -> None:
    job = _checked(project, manual=True)
    code, out, err = _run(["compile", "--job", str(job)], project)
    assert (code, err) == (8, "")
    assert out.splitlines()[-1] == "a draft: ow out compile --accept-manual"
    code, document = _compile(project, job, "--accept-manual")
    assert code == 0
    assert (document["status"], document["delivery"]) == ("manual-required", "draft")
    assert Path(document["path"]).read_bytes() == (TEXT + "== u02 ==\nMargins held.\n").encode()


def test_a_restricted_compile_names_each_barred_source() -> None:
    """Ruling 20's text form for exit 6. A run's barred mask is 0 until 14 gives a policy one
    (D770), so the lines are read off a report rather than a store."""
    from omniweave.sdk.reports import CompileReport, RestrictedItem  # noqa: PLC0415

    built = CompileReport(
        target="owtext",
        slug="q3",
        delivery="release",
        status="restricted",
        exit=6,
        restricted=(RestrictedItem("asset", 7, 8, None), RestrictedItem("cite", 9, 8, "d7#1")),
    )
    assert verb._compile_lines(built) == [
        "gate restricted: nothing was lowered (exit 6)",
        "  barred asset 7: restriction bits 8",
        "  barred cite d7#1: restriction bits 8",
        "re-check: ow out check --stage final",
    ]


def test_accept_manual_on_a_passed_gate_is_a_usage_error(project: Path) -> None:
    job = _checked(project)
    code, out, err = _run(["compile", "--job", str(job), "--accept-manual"], project)
    assert (code, out) == (1, "")
    assert "a draft is --accept-manual's answer" in err
    assert "ow out compile --target owtext" in err


# ---------------------------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--corpus", "handbook"], "--corpus is not served by ow out compile"),
        (["--quiet"], "--quiet is parsed and not served by ow out compile"),
        (["--render", "jsonl"], "--render jsonl is parsed and not served by ow out compile"),
    ],
)
def test_usage_is_refused_by_name(argv: list[str], named: str, project: Path) -> None:
    job = _job(project)
    code, out, err = _run(["compile", "--job", str(job), *argv], project)
    assert (code, out) == (1, "")
    assert named in err


def test_the_console_script_routes_compile(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    job = _job(project)
    monkeypatch.chdir(job)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    code = launcher.main(["out", "compile", "--render", "json"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (8, "")
    assert json.loads(captured.out)["status"] == "not-provided"


# ---------------------------------------------------------------------------------------------
# D779: `[licence] deny_restrictions` is the restriction aggregate's barred mask
# ---------------------------------------------------------------------------------------------

U01_CITED = (
    '<section data-ow-el="u01/e1">\n'
    '  <p data-ow-el="u01/e2" data-ow-cite="d7#1" class="lead">Revenue rose 12% in Q3.</p>\n'
    "</section>\n"
)


def _cited_block(project: Path, bits: int) -> None:
    """Document 7 with one page and one block, `d7#1`, carrying `bits`."""
    from omniweave_core.model.enums import enum_val_rows  # noqa: PLC0415

    ordinal = {(domain, name): n for domain, n, name in enum_val_rows()}
    connection = store_sqlite.connect(project / ".omniweave" / "index.owstore")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint,"
            " options_digest) VALUES (1, 'parse.pdf', 1, 'f', x'00')"
        )
        connection.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
            " format_evidence, source_bytes, status, model_version, declared, achieved)"
            " VALUES (7, ?, ?, 'file:///c/contract.pdf', 'application/pdf', 'pdf', '{}', 10,"
            " 'ok', '1.1', '{}', '{}')",
            (b"\x07" * 16, b"\x00" * 32),
        )
        connection.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id)"
            " VALUES (7, 1, 1, ?, ?, 1)",
            (ordinal["page_kind", "page"], ordinal["method", "native_xml"]),
        )
        connection.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text,"
            " content_digest, os_kind, producer_id, method, trust, quote, origin_operator,"
            " origin_driver, driver_schema_v, restriction_bits)"
            " VALUES (101, 7, 1, 1, 'p1/101', 'd7#1', 1, ?, ?, 'Revenue rose 12% in Q3.',"
            " x'00', ?, 1, ?, 2, 0, 'parse.pdf', 'parse.pdf.text', 1, ?)",
            (
                ordinal["kind", "paragraph"],
                ordinal["layer", "body"],
                ordinal["origin_span_kind", "none"],
                ordinal["method", "native_xml"],
                bits,
            ),
        )
        connection.execute("COMMIT")
    finally:
        connection.close()


def _cited_job(project: Path) -> Path:
    job = _job(project)
    (job / "il" / "u01.html").write_text(U01_CITED, encoding="utf-8", newline="")
    code, _out, err = _run(["check", "--stage", "final", "--job", str(job)], project)
    assert (code, err) == (0, ""), err
    return job


def test_a_cite_the_policy_bars_is_restricted_and_nothing_is_lowered(project: Path) -> None:
    """INV-16's compile-side refusal, through the verbs: a block carrying a barred bit is cited,
    the gate passed, and the compile refuses before `lower()` with exit 6 naming the cite."""
    from omniweave_ports import Restriction  # noqa: PLC0415

    _cited_block(project, Restriction.OUTPUT_SHARE_ALIKE.bit | Restriction.MAU_GATE.bit)
    toml = project / "omniweave.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8")
        + '\n[licence]\ndeny_restrictions = ["output_share_alike"]\n',
        encoding="utf-8",
    )
    job = _cited_job(project)
    code, out, err = _run(["compile", "--job", str(job)], project)
    assert (code, err) == (6, "")
    bits = Restriction.OUTPUT_SHARE_ALIKE.bit | Restriction.MAU_GATE.bit
    assert out.splitlines() == [
        "gate restricted: nothing was lowered (exit 6)",
        f"  barred cite d7#1: restriction bits {bits}",
        "re-check: ow out check --stage final",
    ]
    code, document = _compile(project, job)
    assert (code, document["status"], document["path"]) == (6, "restricted", None)
    assert document["restricted"] == [{"what": "cite", "id": 101, "bits": bits, "cite": "d7#1"}]
    assert not (project / ".omniweave" / "out").exists()


def test_a_cite_the_policy_does_not_bar_compiles(project: Path) -> None:
    from omniweave_ports import Restriction  # noqa: PLC0415

    _cited_block(project, Restriction.MAU_GATE.bit)
    toml = project / "omniweave.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8")
        + '\n[licence]\ndeny_restrictions = ["output_share_alike"]\n',
        encoding="utf-8",
    )
    job = _cited_job(project)
    code, document = _compile(project, job)
    assert (code, document["status"], document["restricted"]) == (0, "passed", [])
