"""A deck through `ow out`: checked with its `font_dir`, compiled, and read back. D806.

`[drivers."compile.pptx.native".config] font_dir` names the faces `measure.py` shapes with. Until
D806 the card declared a list, which the config layer refuses (a driver's configuration is flat
scalars), so no deck could pass `ow out check` and nothing reached `compile` or `back`. Each test
writes its face with `fontkit` into the project, names it in `omniweave.toml`, and drives the
verbs as `test_out_back_verb.py` drives docx's.
"""

from __future__ import annotations

import dataclasses
import io
import json
import sqlite3  # noqa: TID251 -- the assertions read the rows the loop wrote.
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fontkit import tiny_font, write_font  # type: ignore[import-not-found]  # tests/fontkit.py
from omniweave.surface import out as verb
from omniweave.surface.out import _need_fixes  # pyright: ignore[reportPrivateUsage]
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.model.enums import enum_val_rows
from omniweave_core.out.brief import BRIEF_SCHEMA
from omniweave_core.out.card import CompileCard
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite
from omniweave_target_pptx.driver import CARD

BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n## forbidden\n"
)
SLIDE = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u01/e1">'
    '<g data-ow-el="u01/e2"><text data-ow-el="u01/e3" x="60" y="100" font-family="Probe Sans" '
    'font-size="28">Revenue <tspan data-ow-el="u01/e4" font-weight="bold">rose</tspan></text>'
    '<rect data-ow-el="u01/e5" x="60" y="200" width="200" height="100" fill="#1F4E79"/></g>'
    "</svg>"
)


def _project(tmp_path: Path, *, font_dir: bool) -> Path:
    fonts = tmp_path / "fonts"
    write_font(fonts, "probe.ttf", tiny_font("Probe Sans"))
    config = (
        f'\n[drivers."compile.pptx.native".config]\nfont_dir = "{fonts.as_posix()}"\n'
        if font_dir
        else ""
    )
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n' + config, encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    (tmp_path / "brief.md").write_text(BRIEF, encoding="utf-8")
    return tmp_path


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    env = {
        "OMNIWEAVE_HOME": str(cwd / "owhome"),
        "HOME": str(cwd / "home"),
        "USERPROFILE": str(cwd / "home"),
    }
    code = verb.main(["out", *argv], cwd=cwd, env=env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _ok(argv: Sequence[str], cwd: Path) -> str:
    code, out, err = _run(argv, cwd)
    assert (code, err) == (0, ""), out + err
    return out


def _authored(project: Path) -> Path:
    """`deck@1` scaffolded, its one slide written; returns its JobDir."""
    out = _ok(
        ["scaffold", "pptx", "--brief", "brief.md", "--slug", "deck", "--render", "json"], project
    )
    job = Path(json.loads(out)["job_dir"])
    (job / "il" / "u01.svg").write_text(SLIDE, encoding="utf-8", newline="")
    il = job / "il" / "il.toml"
    il.write_text(
        il.read_text(encoding="utf-8") + '\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.svg"\n',
        encoding="utf-8",
    )
    return job


def _store_rows(project: Path, sql: str) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        return connection.execute(sql).fetchall()
    finally:
        connection.close()


def test_without_a_font_dir_the_deck_is_unverified(tmp_path: Path) -> None:
    project = _project(tmp_path, font_dir=False)
    job = _authored(project)
    code, out, _ = _run(
        ["check", "--stage", "final", "--job", str(job), "--render", "json"], project
    )
    assert code == 64
    report = json.loads(out)
    assert report["gate"]["status"] == "unverified"
    fix = (
        'ow config set drivers."compile.pptx.native".config.font_dir <value>   '
        "# what uharfbuzz measures with; then check again"
    )
    assert [(s["needs"], s["fix"]) for s in report["skipped_checks"]] == [("measure", fix)]
    assert {f["fix"] for f in report["findings"]} == {fix}, "D807: the skip names the setting"


def test_with_its_font_dir_the_deck_passes_the_gate(tmp_path: Path) -> None:
    project = _project(tmp_path, font_dir=True)
    job = _authored(project)
    out = _ok(["check", "--stage", "final", "--job", str(job), "--render", "json"], project)
    assert json.loads(out)["gate"]["status"] == "passed"


def test_a_deck_is_compiled_and_read_back_once_its_addresses_mapped(tmp_path: Path) -> None:
    """D806: the loop D788 closed for docx, through parse.pptx.native in an S4 worker."""
    project = _project(tmp_path, font_dir=True)
    job = _authored(project)
    _ok(["check", "--stage", "final", "--job", str(job)], project)
    _ok(["compile", "--job", str(job)], project)
    document = json.loads(_ok(["back", "deck", "--render", "json"], project))
    doc_ord = document["read_back_doc_ord"]
    assert isinstance(doc_ord, int)
    assert (document["read_back"], document["els"], document["loop_open"]) == (
        "parse.pptx.native",
        5,
        "",
    )
    kinds = {name: ordinal for domain, ordinal, name in enum_val_rows() if domain == "kind"}
    assert _store_rows(
        project,
        "SELECT e.el, b.kind, b.text, b.origin_driver FROM artifact_el e"
        " JOIN block b ON b.block_id = e.block_id ORDER BY e.el",
    ) == [
        ("u01/e1", kinds["section"], "Revenue rose", "parse.pptx.native"),
        ("u01/e2", kinds["container"], "Revenue rose", "parse.pptx.native"),
        ("u01/e3", kinds["paragraph"], "Revenue rose", "parse.pptx.native"),
        ("u01/e4", kinds["paragraph"], "rose", "parse.pptx.native"),
        ("u01/e5", kinds["diagram"], None, "parse.pptx.native"),
    ]
    assert _store_rows(project, "SELECT page_kind FROM page") == [
        (next(o for d, o, n in enum_val_rows() if (d, n) == ("page_kind", "slide")),)
    ]


def test_a_corpus_holding_its_own_deck_reports_its_generated_share(tmp_path: Path) -> None:
    """V10-17 (07 section 6.7), D857: the store holds the deck it compiled, read back as
    `roundtrip` blocks. Asked about it, the read-back is the evidence and `generated_share` says
    so; denying `roundtrip`, nothing generated answers and the share is 0.0."""
    from omniweave_core.model.enums import Method  # noqa: PLC0415
    from omniweave_core.retrieve import retrieve  # noqa: PLC0415
    from omniweave_core.retrieve.types import Query, RetrievalPolicy  # noqa: PLC0415
    from omniweave_core.store import reader as rd  # noqa: PLC0415
    from omniweave_core.store.types import Filters  # noqa: PLC0415

    project = _project(tmp_path, font_dir=True)
    job = _authored(project)
    _ok(["check", "--stage", "final", "--job", str(job)], project)
    _ok(["compile", "--job", str(job)], project)
    _ok(["back", "deck"], project)
    store = project / ".omniweave" / "index.owstore"

    def ask(filters: Filters) -> Any:
        connection = store_sqlite.connect_readonly(store)
        try:  # D887: closed here, not left to the collector
            return retrieve(
                rd.SqliteReader(connection, now_ns=1),
                Query(text="Revenue rose", filters=filters),
                RetrievalPolicy(),
                monotonic_ns=lambda: 0,
            )
        finally:
            connection.close()

    open_ = ask(Filters())
    assert open_.hits, "the read-back answers"
    assert open_.verdict.generated_share == 1.0
    denied = ask(Filters(deny_methods=frozenset({Method.ROUNDTRIP})))
    assert denied.hits == ()
    assert denied.verdict.generated_share == 0.0


def _slide(n: int, words: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u0{n}/e1">'
        f'<text data-ow-el="u0{n}/e2" x="60" y="100" font-family="Probe Sans" font-size="28">'
        f"{words}</text></svg>"
    )


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {info.filename: zf.read(info) for info in zf.infolist()}


def test_an_edited_slide_is_rebuilt_and_its_neighbour_copied_byte_for_byte(tmp_path: Path) -> None:
    """D809, P9's demo: one slide's IL edited by hand and recompiled. The untouched slide is
    `passthrough`, its part its parent's, and the row names the generation it edits."""
    project = _project(tmp_path, font_dir=True)
    two = BRIEF.replace(
        "- u01: { anchor: cover }\n", "- u01: { anchor: cover }\n- u02: { anchor: body }\n"
    )
    (project / "two.md").write_text(two, encoding="utf-8")
    out = _ok(
        ["scaffold", "pptx", "--brief", "two.md", "--slug", "deck", "--render", "json"], project
    )
    job = Path(json.loads(out)["job_dir"])
    for n, words in ((1, "Revenue"), (2, "Margins")):
        (job / "il" / f"u0{n}.svg").write_text(_slide(n, words), encoding="utf-8", newline="")
    il = job / "il" / "il.toml"
    il.write_text(
        il.read_text(encoding="utf-8")
        + '\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.svg"\n'
        + '\n[[unit]]\nid = "u02"\nord = 2\nfile = "u02.svg"\n',
        encoding="utf-8",
    )
    _ok(["check", "--stage", "final", "--job", str(job)], project)
    _ok(["compile", "--job", str(job)], project)
    edit = Path(json.loads(_ok(["back", "deck", "--render", "json"], project))["job_dir"])
    plan = json.loads((edit / "job.json").read_text(encoding="utf-8"))["plan"]
    assert plan["parent_gen"] == 1
    assert [u["source_part"] for u in plan["units"]] == [
        "ppt/slides/slide1.xml",
        "ppt/slides/slide2.xml",
    ]
    (edit / "il" / "u02.svg").write_text(_slide(2, "Margins held"), encoding="utf-8", newline="")
    _ok(["check", "--stage", "final", "--job", str(edit)], project)
    _ok(["compile", "--job", str(edit)], project)
    assert _store_rows(
        project,
        "SELECT a.artifact_gen, a.parent_artifact_gen, u.unit, u.outcome FROM artifact_unit u"
        " JOIN artifact a USING(artifact_id) ORDER BY 1, 3",
    ) == [
        (1, None, "u01", "native"),
        (1, None, "u02", "native"),
        (2, 1, "u01", "passthrough"),
        (2, 1, "u02", "rebuilt"),
    ]
    out_root = project / ".omniweave" / "out"
    first = _members(out_root / "deck@1" / "deck.pptx")
    second = _members(out_root / "deck@2" / "deck.pptx")
    assert first["ppt/slides/slide1.xml"] == second["ppt/slides/slide1.xml"]
    assert first["ppt/slides/slide2.xml"] != second["ppt/slides/slide2.xml"]


def test_a_skipped_measurement_names_the_settings_the_card_declares() -> None:
    """D807 (surface ruling 27): the fix sets the card's `[config]` keys, or is left alone."""
    driver = load_card(CARD.read_bytes(), origin="driver_path", source=str(CARD))
    assert isinstance(driver, DriverCard)
    card = CompileCard.of(driver)
    [fix] = _need_fixes(driver, card).values()
    assert fix.startswith('ow config set drivers."compile.pptx.native".config.font_dir <value>')
    both = dataclasses.replace(
        driver.config, properties={"font_dir": {"type": "string"}, "hinting": {"type": "string"}}
    )
    [fix] = _need_fixes(dataclasses.replace(driver, config=both), card).values()
    assert ".config.{font_dir|hinting} <value>" in fix
    bare = dataclasses.replace(driver, config=dataclasses.replace(driver.config, properties={}))
    assert _need_fixes(bare, card) == {}, "no setting to name: the framework's fix stands"
    assert _need_fixes(driver, dataclasses.replace(card, measure="none")) == {}
