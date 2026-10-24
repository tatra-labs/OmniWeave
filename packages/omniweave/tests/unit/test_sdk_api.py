"""`omniweave.corpus()`, `Corpus.query()`, `Corpus.open()` and `explain()`. D858.

Each method composes the core calls the CLI verb composes, so the strongest test here is that the
SDK and `ow query --render json` give the same answer to the same question over one store. The
store is migrated by the shipped migrations and seeded with SQL, as `test_retrieve_execute.py`
seeds one.
"""

from __future__ import annotations

import inspect
import io
import json
import sqlite3  # noqa: TID251 -- the fixture seeds a REAL store, as test_retrieve_execute's do.
from typing import TYPE_CHECKING

import pytest
from omniweave.gen.sdk_stub import SDK_HOMES, owed
from omniweave.sdk import api
from omniweave.surface import query as query_verb
from omniweave.surface.query import answer_json
from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.model.enums import Method
from omniweave_core.store import migrate
from omniweave_core.store.types import Filters

import omniweave
from omniweave import sdk

if TYPE_CHECKING:
    from pathlib import Path

NOW_NS = 1_757_400_000_000_000_000
DIGEST = b"\x00" * 16
TEXTS = {
    1: "Termination",
    2: "Either party may terminate this agreement with thirty days notice.",
    3: "Fees are payable monthly in arrears.",
}


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    return int(row[0])


def _seed(store: Path, *, method: str = "native", restriction_bits: int = 0) -> None:
    conn = sqlite3.connect(store)
    try:
        migrate.apply_pending(conn, now_ns=NOW_NS)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('op.parse', 1, 'fp', X'00')"
        )
        producer = int(conn.execute("SELECT producer_id FROM producer").fetchone()[0])
        conn.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
            "                format_evidence, source_bytes, gen, status, model_version, declared, "
            "                achieved) "
            "VALUES(1, ?, ?, 'file:///corpus/contract.pdf', 'application/pdf', 'pdf', '{}', 1, 1,"
            "       'ok', '1.1', '{}', '{}')",
            (b"\x01" * 16, DIGEST),
        )
        conn.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
            "VALUES(1, 1, 1, ?, ?, ?)",
            (_code(conn, "page_kind", "page"), _code(conn, "method", "native"), producer),
        )
        for block_id, text in TEXTS.items():
            kind = "heading" if block_id == 1 else "paragraph"
            conn.execute(
                "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, "
                "                  label, text, content_digest, os_kind, producer_id, method, "
                "                  trust, quote, origin_operator, origin_driver, driver_schema_v, "
                "                  restriction_bits, state) "
                "VALUES(?, 1, 1, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, 4, 'op.parse', 'drv', 1,"
                "       ?, 0)",
                (
                    block_id,
                    f"p1/{block_id}",
                    f"d1#{block_id}",
                    block_id,
                    _code(conn, "kind", kind),
                    _code(conn, "layer", "body"),
                    text if block_id == 1 else None,
                    text,
                    DIGEST,
                    _code(conn, "origin_span_kind", "none"),
                    producer,
                    _code(conn, "method", method if block_id == 3 else "native"),
                    restriction_bits if block_id == 3 else 0,
                ),
            )
        conn.execute(
            "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, "
            "                         complete) VALUES('corpus', 1, 1, 0, ?, 1)",
            (NOW_NS,),
        )
        conn.execute("COMMIT")
    finally:
        conn.close()


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    _seed(tmp_path / ".omniweave" / "index.owstore")
    return tmp_path


def _env(home: Path) -> dict[str, str]:
    return {"OMNIWEAVE_HOME": str(home / "owhome"), "HOME": str(home), "USERPROFILE": str(home)}


def _corpus(project: Path, name: str | None = "handbook") -> api.Corpus:
    return omniweave.corpus(name, cwd=project, env=_env(project))


# --- the signatures are 18 section 1's (ruling 1) -------------------------------------------


@pytest.mark.parametrize(
    ("action", "member"),
    [
        ("query", api.Corpus.query),
        ("open", api.Corpus.open),
        ("explain", api.explain),
        ("corpus.coverage", api.Corpus.coverage),
        ("corpora", api.corpora),
        ("doctor", api.doctor),
    ],
)
def test_each_method_takes_exactly_the_parameters_18_prints(action: str, member: object) -> None:
    printed = SDK_HOMES[action].parameters
    taken = tuple(name for name in inspect.signature(member).parameters if name != "self")  # type: ignore[arg-type]
    assert taken == printed


def test_all_five_entry_points_land() -> None:
    assert {"Corpus", "corpus", "corpora", "doctor", "explain"} <= set(sdk.__all__)
    assert owed() == ()


def test_the_top_level_package_is_an_alias_for_the_sdk() -> None:
    """18:149: `omniweave.corpus(...)` works, and nothing the SDK does not export is invented."""
    assert omniweave.corpus is api.corpus
    assert omniweave.explain is api.explain
    assert omniweave.Corpus is api.Corpus
    with pytest.raises(AttributeError, match="no attribute 'invented'"):
        _ = omniweave.invented  # type: ignore[attr-defined]
    assert hasattr(sdk, "api"), "a submodule of the SDK"
    assert not hasattr(omniweave, "api"), "is not an SDK export, so not the package's alias"


# --- explain --------------------------------------------------------------------------------


def test_explain_takes_either_spelling_and_returns_both() -> None:
    by_numeric = omniweave.explain("OW-R-030")
    by_symbol = omniweave.explain("OW_ROUTE_ESCALATION_NOT_MONOTONE")
    assert by_numeric == by_symbol
    assert (by_numeric.numeric, by_numeric.symbol) == (
        "OW-R-030",
        "OW_ROUTE_ESCALATION_NOT_MONOTONE",
    )


def test_explain_of_an_unknown_code_is_not_found() -> None:
    with pytest.raises(NotFoundError):
        omniweave.explain("OW-Z-999")


# --- corpus() --------------------------------------------------------------------------------


def test_a_corpus_carries_its_name_generation_and_schema(project: Path) -> None:
    from omniweave_core.contract import SCHEMA  # noqa: PLC0415

    handle = _corpus(project)
    assert (handle.name, handle.schema) == ("handbook", SCHEMA)
    assert handle.generation >= 0
    assert _corpus(project, None).name == "handbook", "None is the default corpus"


def test_an_undeclared_corpus_is_not_found(project: Path) -> None:
    with pytest.raises(NotFoundError, match="contracts"):
        _corpus(project, "contracts")


def test_a_corpus_whose_store_is_missing_is_not_found(project: Path) -> None:
    (project / ".omniweave" / "index.owstore").unlink()
    with pytest.raises(NotFoundError):
        _corpus(project)


def test_without_a_cwd_the_entry_point_reads_the_process_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 3: the one ambient read, through `sdk._ambient`, and only when none is given."""
    from omniweave.sdk import _ambient  # noqa: PLC0415

    monkeypatch.setattr(_ambient, "process_cwd", lambda: project)
    assert omniweave.corpus("handbook", env=_env(project)).name == "handbook"


# --- query and open: one implementation with the CLI ---------------------------------------


def _cli(project: Path, *argv: str) -> dict[str, object]:
    out, err = io.StringIO(), io.StringIO()
    code = query_verb.main(
        ["query", *argv, "--render", "json"], cwd=project, env=_env(project), stdout=out, stderr=err
    )
    assert (code, err.getvalue()) == (0, ""), out.getvalue()
    return json.loads(out.getvalue())


def test_a_query_is_the_answer_ow_query_gives(project: Path) -> None:
    answer = _corpus(project).query("terminate agreement notice")
    assert answer_json(answer) == _cli(project, "terminate agreement notice")
    assert answer.state in {"ok", "low_confidence"}


def test_k_mode_and_max_chars_reach_the_query(project: Path) -> None:
    sdk_answer = _corpus(project).query("fees payable", k=5, mode="cite", max_chars=2000)
    cli = _cli(project, "fees payable", "--k", "5", "--mode", "cite", "--max-chars", "2000")
    assert answer_json(sdk_answer) == cli


def test_filters_reach_retrieval(project: Path) -> None:
    """The one parameter the CLI cannot spell (07:1663), so the SDK's is the only way to ask."""
    (project / ".omniweave" / "index.owstore").unlink()
    _seed(project / ".omniweave" / "index.owstore", method="roundtrip")
    handle = _corpus(project)
    open_ = handle.query("fees payable monthly arrears")
    denied = handle.query(
        "fees payable monthly arrears",
        filters=Filters(deny_methods=frozenset({Method.ROUNDTRIP})),
    )
    assert answer_json(open_) != answer_json(denied)
    assert "d1#3" in json.dumps(answer_json(open_))
    assert "d1#3" not in json.dumps(answer_json(denied))


def test_open_resolves_a_cite_as_ow_open_does(project: Path) -> None:
    from omniweave.surface import opening  # noqa: PLC0415

    out, err = io.StringIO(), io.StringIO()
    code = opening.main(
        ["open", "d1#2", "--render", "json"], cwd=project, env=_env(project), stdout=out, stderr=err
    )
    assert code == 0, err.getvalue()
    assert answer_json(_corpus(project).open("d1#2")) == json.loads(out.getvalue())
    assert answer_json(_corpus(project).open(["d1#2"])) == json.loads(out.getvalue())


def test_k_bounds_the_evidence_as_ow_query_k_does(project: Path) -> None:
    one = _corpus(project).query("terminate fees", k=1)
    assert answer_json(one) == _cli(project, "terminate fees", "--k", "1")
    assert len(answer_json(one)["evidence"]) == 1
    assert len(answer_json(_corpus(project).query("terminate fees"))["evidence"]) == 2


def test_the_query_built_is_the_one_asked(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`mode` changes nothing this store can show, so the `Query` handed to `execute` is read."""
    from omniweave_core.retrieve import execute as ex  # noqa: PLC0415

    seen = []
    real = ex.execute

    def spy(reader: object, q: object, pol: object, **kw: object) -> object:
        seen.append(q)
        return real(reader, q, pol, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(ex, "execute", spy)
    deny = Filters(deny_methods=frozenset({Method.ROUNDTRIP}))
    _corpus(project).query("fees", mode="prove_absent", k=7, filters=deny)
    [q] = seen
    assert (q.text, q.mode, q.k, q.filters) == ("fees", "prove_absent", 7, deny)  # type: ignore[attr-defined]


def test_an_unknown_mode_names_the_four(project: Path) -> None:
    with pytest.raises(UsageError, match=r"mode='bogus' is not one of find, cite, explore"):
        _corpus(project).query("fees", mode="bogus")


def test_the_projects_policy_is_the_one_ow_query_reads(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D780's `[licence] deny_restrictions`, the mask `ow query` and `ow serve` read: one policy.

    The mask is read and handed to `execute`, and the answer is `ow query`'s. Whether `execute`
    then bars the block is core's (D859), not the SDK's."""
    from omniweave_core.drivers.licence import Restriction  # noqa: PLC0415
    from omniweave_core.retrieve import execute as ex  # noqa: PLC0415

    bit = Restriction.NO_MODEL_TRAINING.bit
    (project / ".omniweave" / "index.owstore").unlink()
    _seed(project / ".omniweave" / "index.owstore", restriction_bits=bit)
    toml = project / "omniweave.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8")
        + '\n[licence]\ndeny_restrictions = ["no_model_training"]\n',
        encoding="utf-8",
    )
    policies = []
    real = ex.execute

    def spy(reader: object, q: object, pol: object, **kw: object) -> object:
        policies.append(pol)
        return real(reader, q, pol, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(ex, "execute", spy)
    answer = _corpus(project).query("fees payable monthly arrears")
    [policy] = policies
    assert policy.deny_restriction_bits == bit  # type: ignore[attr-defined]
    monkeypatch.setattr(ex, "execute", real)
    assert answer_json(answer) == _cli(project, "fees payable monthly arrears")
    #  D859: and core now bars it, saying the policy withheld it rather than claiming absence.
    assert "d1#3" not in json.dumps(answer_json(answer))
    assert answer.state == "degraded"


def test_a_too_small_budget_is_a_usage_error(project: Path) -> None:
    with pytest.raises(UsageError, match="max_chars"):
        _corpus(project).query("fees", max_chars=10)


# --- what is not served is refused by name (ruling 2) ---------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "named"),
    [
        ({"refs": ("d1#2",)}, "refs"),
        ({"scope": "contract.pdf"}, "scope"),
        ({"want": "table"}, "want"),
        ({"max_blocks": 10}, "max_blocks"),
        ({"expand": object()}, "expand"),
        ({"route_hints": object()}, "route_hints"),
    ],
)
def test_a_query_parameter_not_served_is_refused(
    project: Path, kwargs: dict[str, object], named: str
) -> None:
    with pytest.raises(UsageError, match=f"^{named} is not served"):
        _corpus(project).query("fees", **kwargs)  # type: ignore[arg-type]


def test_an_unknown_want_names_the_five_presets(project: Path) -> None:
    with pytest.raises(UsageError, match=r"passages, table, fields, outline, related"):
        _corpus(project).query("fees", want="essay")


@pytest.mark.parametrize(
    ("kwargs", "named"), [({"raw": True}, "raw"), ({"want_impact": True}, "want_impact")]
)
def test_an_open_parameter_not_served_is_refused(
    project: Path, kwargs: dict[str, object], named: str
) -> None:
    with pytest.raises(UsageError, match=f"^{named} is not served"):
        _corpus(project).open("d1#2", **kwargs)  # type: ignore[arg-type]


def test_two_refusals_are_named_together(project: Path) -> None:
    with pytest.raises(UsageError, match=r"^refs, scope are not served"):
        _corpus(project).query("fees", refs=("d1#2",), scope="x")


# --- corpora() and doctor(): the last two entry points (D860) -------------------------------


def _card(project: Path) -> None:
    """The store's own builder and writer, as `test_serve_corpora.py` makes a card."""
    from omniweave_core.store import card as store_card  # noqa: PLC0415

    conn = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = store_card.build_card(
            conn,
            name="handbook",
            root="/corpus",
            card_gen=3,
            built_at_ns=NOW_NS,
            writer_version="0.1.0",
        )
        store_card.write_card(conn, row)
        conn.execute("COMMIT")
    finally:
        conn.close()


@pytest.fixture
def here(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The entry points with no `cwd` parameter read it through `sdk._ambient` (ruling 6)."""
    from omniweave.sdk import _ambient  # noqa: PLC0415

    monkeypatch.setattr(_ambient, "process_cwd", lambda: project)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    return project


def _cli_cards(project: Path) -> list[dict[str, object]]:
    from omniweave.surface import corpora as corpora_verb  # noqa: PLC0415

    out, err = io.StringIO(), io.StringIO()
    code = corpora_verb.main(
        ["corpora", "handbook", "--detail", "card", "--render", "json"],
        cwd=project,
        env=_env(project),
        stdout=out,
        stderr=err,
    )
    assert code == 0, err.getvalue()
    return json.loads(out.getvalue())["corpora"]


def test_corpora_is_every_card_ow_corpora_prints(here: Path) -> None:
    _card(here)
    [card] = omniweave.corpora()
    [printed] = _cli_cards(here)
    assert (card.name, card.default, card.readable, card.card_gen) == ("handbook", True, True, 3)
    for field in ("counts", "formats", "langs", "date_range", "verbatim_fraction", "card_stale"):
        assert getattr(card, field) == printed[field], field
    assert card.achieved is not None
    assert card.achieved.spatial == printed["achieved"]["spatial"]  # type: ignore[index]
    assert tuple(card.outline) == tuple(printed["outline"])  # type: ignore[arg-type]


@pytest.mark.usefixtures("here")
def test_a_corpus_with_no_card_is_a_card_with_nothing_achieved() -> None:
    """Ruling 5: `achieved=None`, as `capability_floor()` and `ow_corpora` say it, never the bottom
    of every ladder."""
    [card] = omniweave.corpora()
    assert (card.card_gen, card.achieved, card.counts, card.gaps) == (0, None, {}, ())


def test_a_store_that_will_not_open_is_a_card_saying_why(here: Path) -> None:
    toml = here / "omniweave.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[corpora.contracts]\npath = "missing.owstore"\n',
        encoding="utf-8",
    )
    cards = omniweave.corpora()
    assert [c.name for c in cards] == ["handbook", "contracts"], "default first"
    broken = cards[1]
    assert (broken.readable, broken.achieved) == (False, None)
    assert broken.reason


@pytest.mark.usefixtures("here")
def test_corpora_of_names_is_the_fan_out_handle_and_is_refused() -> None:
    with pytest.raises(UsageError, match=r"fan-out handle, CorpusSet, deferred past v1.0"):
        omniweave.corpora(["handbook"])


def test_corpora_reads_an_explicit_config(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from omniweave.sdk import _ambient  # noqa: PLC0415

    monkeypatch.setattr(_ambient, "process_cwd", lambda: project.parent)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    [card] = omniweave.corpora(config=project / "omniweave.toml")
    assert card.name == "handbook"


def test_doctor_is_ow_doctors_report(here: Path) -> None:
    from omniweave import doctor as doctor_package  # noqa: PLC0415

    report = sdk.doctor()
    assert report == doctor_package.run(cwd=here, env=_env(here) | dict(__import__("os").environ))
    runtime = sdk.doctor(runtime=True)
    rows = [(*one.ok, *one.warned, *one.failed) for one in (report, runtime)]
    runtime_rows = {"D-10", "D-19"}  # D958, D965: the rows only --runtime runs
    assert [one for one in rows[1] if one.check not in runtime_rows] == list(rows[0])
    assert sorted(one.check for one in rows[1] if one.check in runtime_rows) == sorted(runtime_rows)


def test_a_submodule_name_is_the_submodule_not_the_sdk_function() -> None:
    """D860: `omniweave.doctor` is the `ow doctor` package; the SDK's is `omniweave.sdk.doctor`."""
    import types  # noqa: PLC0415

    from omniweave import doctor  # noqa: PLC0415

    assert isinstance(doctor, types.ModuleType)
    assert callable(sdk.doctor) and not isinstance(sdk.doctor, types.ModuleType)
    assert omniweave.corpora is api.corpora


def test_corpora_is_never_cut_at_the_list_cap(here: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ruling 5: a tuple has no `truncated`, so the SDK returns every corpus the list would cut."""
    from omniweave_core.store import card as store_card  # noqa: PLC0415

    toml = here / "omniweave.toml"
    toml.write_text(
        toml.read_text(encoding="utf-8") + '\n[corpora.contracts]\npath = "missing.owstore"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(store_card, "CORPORA_LIST_MAX", 1)
    assert len(omniweave.corpora()) == 2


def test_a_cards_gaps_arrive_as_gap_records(here: Path) -> None:
    """10:1085: a gap carries both spellings of its code, and the SDK hands it on typed."""
    import dataclasses  # noqa: PLC0415

    from omniweave_core.store import card as store_card  # noqa: PLC0415

    gap = {
        "code": "OW-A-013",
        "symbol": "OW_PARSE_GAP_IN_SCOPE",
        "meaning": "a parse gap in scope",
        "docs": 1,
        "pages": 2,
        "severity": "blocking",
        "fix": "ow ingest",
    }
    conn = sqlite3.connect(here / ".omniweave" / "index.owstore")
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = store_card.build_card(
            conn,
            name="handbook",
            root="/corpus",
            card_gen=4,
            built_at_ns=NOW_NS,
            writer_version="0.1.0",
        )
        store_card.write_card(conn, dataclasses.replace(row, gaps_json=json.dumps([gap])))
        conn.execute("COMMIT")
    finally:
        conn.close()
    [card] = omniweave.corpora()
    assert card.gaps == (store_card.Gap(**gap),)


# --- Corpus.card() and Corpus.coverage() (D861) ---------------------------------------------


def test_card_is_this_corpus_entry_and_is_kept_for_the_handles_life(here: Path) -> None:
    _card(here)
    handle = _corpus(here)
    first = handle.card()
    assert first == omniweave.corpora()[0]
    assert first.card_gen == 3
    conn = sqlite3.connect(here / ".omniweave" / "index.owstore")
    try:
        conn.execute("UPDATE corpus_card SET card_gen = 9")
        conn.commit()
    finally:
        conn.close()
    assert handle.card() is first, "18:460: read once and memoised"
    assert _corpus(here).card().card_gen == 9, "a new handle reads it again"


def test_coverage_is_the_live_gap_list_ow_corpora_prints(here: Path) -> None:
    from omniweave.surface import corpora as corpora_verb  # noqa: PLC0415

    out, err = io.StringIO(), io.StringIO()
    code = corpora_verb.main(
        ["corpora", "handbook", "--detail", "coverage", "--render", "json"],
        cwd=here,
        env=_env(here),
        stdout=out,
        stderr=err,
    )
    assert code == 0, err.getvalue()
    [printed] = json.loads(out.getvalue())["corpora"]
    coverage = _corpus(here).coverage()
    for name in ("discovered", "indexed", "complete", "scope_rows", "pending_work"):
        assert getattr(coverage, name) == printed["coverage"][name], name
    assert coverage.scope_rows == 1


def test_coverage_is_read_fresh_on_every_call(here: Path) -> None:
    """A held handle sees the scan go missing: `scope_rows == 0` is coverage UNKNOWN."""
    handle = _corpus(here)
    assert handle.coverage().scope_rows == 1
    conn = sqlite3.connect(here / ".omniweave" / "index.owstore")
    try:
        conn.execute("DELETE FROM ingest_scope")
        conn.commit()
    finally:
        conn.close()
    assert handle.coverage().scope_rows == 0


# --- Corpus.add(): ow add's write path, in the caller's process (D862) ----------------------

PAST_NS = 1_700_000_000_000_000_000
"""An mtime far enough behind the add that `stat_fresh()`'s granularity clause holds (05:344)."""


@pytest.fixture
def fresh(tmp_path: Path) -> Path:
    """A project with two `.txt` files and no store, as `test_add_verb.py` makes one. The quiet
    poll is shortened in config, since `add()` has no `sweep_ms` (D564)."""
    import os  # noqa: PLC0415

    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
        "[runtime]\ndeferred_sweep_ms = 20\n",
        encoding="utf-8",
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, body in (("a.txt", "Fees are payable monthly."), ("b.txt", "Notice is 30 days.")):
        (docs / name).write_text(body, encoding="utf-8")
        os.utime(docs / name, ns=(PAST_NS, PAST_NS))
    return tmp_path


def _writer(project: Path) -> api.Corpus:
    return omniweave.corpus("handbook", readonly=False, cwd=project, env=_env(project))


def _triggers(project: Path) -> list[str]:
    conn = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        return [row[0] for row in conn.execute("SELECT trigger FROM run ORDER BY generation")]
    finally:
        conn.close()


def test_a_writer_may_open_a_corpus_whose_store_add_will_create(fresh: Path) -> None:
    from omniweave_core.contract import SCHEMA  # noqa: PLC0415

    handle = _writer(fresh)
    assert (handle.generation, handle.schema) == (0, SCHEMA)
    assert not (fresh / ".omniweave" / "index.owstore").exists()
    #  A reader still refuses a store that is not there.
    with pytest.raises(NotFoundError):
        _corpus(fresh)


def test_add_rosters_drains_and_reports_as_ow_add_does_with_an_sdk_trigger(fresh: Path) -> None:
    report = _writer(fresh).add("docs")
    assert (report.corpus, report.discovered, report.queued) == ("handbook", 2, 2)
    assert report.deadline_reached is False
    assert {p.uri.rsplit("/", 1)[-1] for p in report.pending} == {"a.txt", "b.txt"}
    assert {p.reason for p in report.pending} == {"no_driver"}, "parse.text.builtin is absent"
    assert _triggers(fresh) == ["sdk"], "18:440: never cli, the consent a human gave by typing"


def test_ow_add_still_records_cli(fresh: Path) -> None:
    from omniweave.surface import add as add_verb  # noqa: PLC0415

    out, err = io.StringIO(), io.StringIO()
    code = add_verb.main(
        ["add", "docs"], env=_env(fresh), cwd=fresh, stdout=out, stderr=err, sweep_ms=20
    )
    assert code == 0, err.getvalue()
    assert _triggers(fresh) == ["cli"]


def test_a_second_add_of_the_same_sources_is_unchanged(fresh: Path) -> None:
    """18:445: idempotency is the store's -- the second call's rows collide and are unchanged."""
    _writer(fresh).add("docs")
    again = _writer(fresh).add(["docs/a.txt", "docs/b.txt"])
    assert (again.queued, again.unchanged) == (0, 2)


def test_a_dry_run_writes_nothing_and_names_the_command_that_would(fresh: Path) -> None:
    report = _writer(fresh).add("docs", dry_run=True)
    assert (report.discovered, report.queued) == (2, 0)
    assert {p.reason for p in report.pending} == {"dry_run"}
    assert {p.approve for p in report.pending} == {"ow add docs --corpus handbook"}
    assert not (fresh / ".omniweave" / "index.owstore").exists()


def test_a_readonly_handle_refuses_to_add(project: Path) -> None:
    with pytest.raises(UsageError) as refused:
        _corpus(project).add("docs")
    assert refused.value.code() == "OW_READONLY_HANDLE"
    assert "readonly=False" in refused.value.fix


@pytest.mark.parametrize(
    ("kwargs", "named"),
    [
        ({"schema": {"type": "object"}}, "schema"),
        ({"allow_cost": 1000}, "allow_cost"),
        ({"allow_egress": "example"}, "allow_egress"),
        ({"wait_ms": 5000}, "wait_ms"),
    ],
)
def test_an_add_parameter_ow_add_refuses_is_refused(
    fresh: Path, kwargs: dict[str, object], named: str
) -> None:
    with pytest.raises(UsageError, match=f"^{named} is not served"):
        _writer(fresh).add("docs", **kwargs)  # type: ignore[arg-type]
    assert not (fresh / ".omniweave" / "index.owstore").exists()


def test_a_source_outside_the_corpus_is_refused(
    fresh: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    from omniweave_core.errors import PolicyRefusal  # noqa: PLC0415

    elsewhere = tmp_path_factory.mktemp("elsewhere")
    with pytest.raises(PolicyRefusal):
        _writer(fresh).add(str(elsewhere))


def test_a_trigger_outside_run_triggers_check_never_opens_a_run(tmp_path: Path) -> None:
    """`run.trigger`'s CHECK, held before anything opens: a typo is a ValueError, not a row."""
    from omniweave.run import ingest as run_ingest  # noqa: PLC0415

    assert {"cli", "hook", "upstream", "watch", "mcp", "sdk"} == run_ingest.TRIGGERS
    store = tmp_path / "index.owstore"
    with pytest.raises(ValueError, match="trigger 'bogus' is not one of"):
        run_ingest.ingest(
            store,
            config=None,  # type: ignore[arg-type]
            source_root=tmp_path,
            output_root=tmp_path,
            cache_root=tmp_path,
            argv=[],
            paths=(tmp_path,),
            trigger="bogus",  # type: ignore[arg-type]
        )
    assert not store.exists()


# --- Corpus.doc(): the L2 lazy handle over the store (ruling 9) ---------------------------------


@pytest.mark.parametrize("ref", ["d1", "d1#2", "file:///corpus/contract.pdf", "contract.pdf"])
def test_doc_resolves_a_doc_ord_a_cite_a_uri_and_a_file_name(project: Path, ref: str) -> None:
    doc = _corpus(project).doc(ref)
    assert (doc.doc_ord, doc.gen) == (1, 1)


def test_a_doc_reads_the_stored_document(project: Path) -> None:
    from omniweave_core.model.block import Cite  # noqa: PLC0415
    from omniweave_core.model.enums import Kind  # noqa: PLC0415

    doc = _corpus(project).doc("contract.pdf")
    assert [block.text for block in doc.blocks()] == [TEXTS[1], TEXTS[2], TEXTS[3]]
    assert [block.cite for block in doc.blocks(kinds=[Kind.HEADING])] == ["d1#1"]
    found = doc.by_cite(Cite("d1#3"))
    assert found is not None
    assert found.text == TEXTS[3]
    assert doc.block(found.id) == found


def test_the_ladder_names_the_document_it_resolves(project: Path) -> None:
    conn = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        conn.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
            "                format_evidence, source_bytes, gen, status, model_version, declared, "
            "                achieved) "
            "VALUES(2, ?, ?, 'file:///corpus/other.pdf', 'application/pdf', 'pdf', '{}', 1, 1,"
            "       'ok', '1.1', '{}', '{}')",
            (b"" * 16, DIGEST),
        )
        conn.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
            "SELECT 2, 1, 1, page_kind, method, producer_id FROM page WHERE doc_ord = 1"
        )
        conn.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text, "
            "                  content_digest, os_kind, producer_id, method, trust, quote, "
            "                  origin_operator, origin_driver, driver_schema_v, state) "
            "SELECT 4, 2, 1, 1, 'p1/1', 'd2#1', 1, kind, layer, 'Other.', content_digest, "
            "       os_kind, producer_id, method, trust, quote, origin_operator, origin_driver, "
            "       driver_schema_v, 0 FROM block WHERE block_id = 2"
        )
        conn.commit()
    finally:
        conn.close()
    handle = _corpus(project)
    for ref in ("other.pdf", "d2#1", "file:///corpus/other.pdf", "d2"):
        doc = handle.doc(ref)
        assert doc.doc_ord == 2
        assert [block.text for block in doc.blocks()] == ["Other."]
    assert handle.doc("contract.pdf").doc_ord == 1


@pytest.mark.parametrize("ref", ["d9", "nothing.pdf", "d9#1"])
def test_a_ref_that_names_no_document_is_refused(project: Path, ref: str) -> None:
    from omniweave_core.errors import OwError  # noqa: PLC0415

    with pytest.raises(OwError):
        _corpus(project).doc(ref)


def test_every_read_closes_its_connection_and_the_cursor_holds_one(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniweave_core.model.block import Cite  # noqa: PLC0415
    from omniweave_core.store import sqlite as store_sqlite  # noqa: PLC0415

    opened: list[sqlite3.Connection] = []
    connect = store_sqlite.connect_readonly

    def counting(*args: object, **kw: object) -> sqlite3.Connection:
        connection = connect(*args, **kw)  # type: ignore[arg-type]
        opened.append(connection)
        return connection

    def open_ones() -> int:
        live = 0
        for connection in opened:
            try:
                connection.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                continue
            live += 1
        return live

    monkeypatch.setattr(store_sqlite, "connect_readonly", counting)
    doc = _corpus(project).doc("d1")
    assert doc.by_cite(Cite("d1#2")) is not None
    assert opened
    assert open_ones() == 0
    cursor = doc.blocks()
    next(cursor)
    assert open_ones() == 1
    list(cursor)
    assert open_ones() == 0


def test_a_doc_kept_across_a_reparse_misses_rather_than_reads_another_generation(
    project: Path,
) -> None:
    from omniweave_core.model.block import Cite  # noqa: PLC0415

    doc = _corpus(project).doc("d1")
    conn = sqlite3.connect(project / ".omniweave" / "index.owstore")
    try:
        conn.execute("UPDATE block SET state = 1")
        conn.execute("UPDATE doc SET gen = 2")
        conn.commit()
    finally:
        conn.close()
    assert doc.by_cite(Cite("d1#1")) is None
    assert list(doc.blocks()) == []
    with pytest.raises(NotFoundError, match="generation"):
        _ = doc.rec


def test_what_the_store_reader_refuses_the_doc_refuses(project: Path) -> None:
    with pytest.raises(UsageError, match=r"Doc\.frames\(\) is not built"):
        _corpus(project).doc("d1").frames()


def test_a_doc_serializes_the_stored_document(project: Path) -> None:
    text, _spans = _corpus(project).doc("contract.pdf").serialize("text")
    assert [line for line in text.splitlines() if line] == [TEXTS[1], TEXTS[2], TEXTS[3]]
