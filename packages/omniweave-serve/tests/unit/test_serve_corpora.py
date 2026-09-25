"""`ow_corpora` over `tools/call`: the four modes, and 10:1029-1040's three degradations on the row.

Every store is migrated by the shipped migrations and seeded with SQL; the card is written by
`store.card.build_card()` and `write_card()`, the real builder, because nothing in the ingest path
writes one yet (D550). A `card` entry is validated against `schema/corpora-out-v1.json`'s entry
definition, which is what `--render json` promises.

**10:920's one rule is asserted on every outcome**: nothing here is `isError: true`.
"""

from __future__ import annotations

import json
import sqlite3  # noqa: TID251 -- the fixtures seed a REAL store, as core's reader tests do.
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from omniweave_core.store import card as store_card
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_serve import corpora as corpora_module
from omniweave_serve.corpora import CORPORA_LIST_MAX, DETAILS
from omniweave_serve.query import QueryCaller

REPO = Path(__file__).resolve().parents[4]
NOW_NS = 1_757_400_000_000_000_000
DIGEST = b"\x00" * 16
ACHIEVED = {
    "spatial": "line_bbox",
    "origin_span": "normalized",
    "text_span": True,
    "marks": False,
    "reading_order": "char_stream",
    "sections": "typed_levels",
    "tables": "cells",
    "math": [],
    "assets": "refs",
    "asset_origin": False,
    "notes": "linked",
    "confidence": "page",
    "furniture": "flagged",
    "round_trip": "none",
    "forfeits": [],
}


def _code(conn: sqlite3.Connection, domain: str, name: str) -> int:
    row = conn.execute(
        "SELECT ord FROM enum_val WHERE domain = ? AND name = ?", (domain, name)
    ).fetchone()
    return int(row[0])


def _store(path: Path, *, card: bool = True, gen: int = 1) -> Path:
    """One document and one paragraph, and -- unless `card=False` -- a card built at `gen`."""
    conn = ow.connect(path)
    try:
        migrate.apply_pending(conn, now_ns=NOW_NS)
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO producer(operator, op_version, code_fingerprint, options_digest) "
            "VALUES('op.parse', 1, 'fp', X'00')"
        )
        conn.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format, "
            "                format_evidence, source_bytes, gen, status, model_version, "
            "                declared, achieved) "
            "VALUES(1, ?, ?, 'file:///corpus/contract.pdf', 'application/pdf', 'pdf', '{}', "
            "       2048, 1, 'ok', '1.1', '{}', ?)",
            (b"\x01" * 16, DIGEST, json.dumps(ACHIEVED)),
        )
        conn.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id) "
            "VALUES(1, 1, 1, ?, ?, 1)",
            (_code(conn, "page_kind", "page"), _code(conn, "method", "native")),
        )
        conn.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text, "
            "                  content_digest, os_kind, producer_id, method, trust, quote, "
            "                  origin_operator, origin_driver, driver_schema_v, "
            "                  restriction_bits, state) "
            "VALUES(1, 1, 1, 1, 'p1/1', 'd1#1', 1, ?, ?, 'Fees are payable monthly.', ?, ?, 1, "
            "       ?, 2, 4, 'op.parse', 'drv', 1, 0, 0)",
            (
                _code(conn, "kind", "paragraph"),
                _code(conn, "layer", "body"),
                DIGEST,
                _code(conn, "origin_span_kind", "none"),
                _code(conn, "method", "native"),
            ),
        )
        conn.execute(
            "INSERT INTO ingest_scope(scope_id, discovered, indexed, skipped, scanned_at_ns, "
            "                         complete) VALUES('corpus', 1, 1, 0, ?, 1)",
            (NOW_NS,),
        )
        if card:
            row = store_card.build_card(
                conn,
                name=path.stem,
                root="/corpus",
                card_gen=gen,
                built_at_ns=NOW_NS,
                writer_version="0.1.0",
            )
            store_card.write_card(conn, row)
        conn.execute("COMMIT")
    finally:
        conn.close()
    return path


def _answer(caller: QueryCaller, **arguments: Any) -> str:
    result = caller.respond_corpora(arguments)
    assert result["isError"] is False, "10:920: isError is reserved for security refusals"
    (content,) = result["content"]
    return str(content["text"])


def _json(caller: QueryCaller, **arguments: Any) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(_answer(caller, **arguments))
    return document


def _caller(corpora: dict[str, Path], default: str | None = None) -> QueryCaller:
    return QueryCaller(corpora=corpora, default=default, wall_ns=lambda: NOW_NS)


def _entry_validator() -> Draft202012Validator:
    schema = json.loads((REPO / "schema" / "corpora-out-v1.json").read_text(encoding="utf-8"))
    entry = {"$ref": "#/$defs/CorpusCard", "$defs": schema["$defs"]}
    return Draft202012Validator(entry)


# ---------------------------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------------------------


def test_list_is_the_envelope_10_1044_prints(tmp_path: Path) -> None:
    caller = _caller({"handbook": _store(tmp_path / "handbook.owstore")}, default="handbook")
    document = _json(caller)
    assert set(document) == {"corpora", "truncated", "degradations", "schema"}
    assert document["schema"] == 1
    assert document["truncated"] is False
    (row,) = document["corpora"]
    assert row["name"] == "handbook"
    assert row["default"] is True
    assert (row["readable"], row["reason"], row["card_stale"]) == (True, None, False)
    assert row["counts"]["docs_indexed"] == 1
    assert row["counts"]["blocks"] == 1
    assert "verbatim_fraction" in row


def test_list_orders_the_default_first_then_card_gen_then_name(tmp_path: Path) -> None:
    corpora = {
        "alpha": _store(tmp_path / "alpha.owstore", gen=1),
        "beta": _store(tmp_path / "beta.owstore", gen=3),
        "gamma": _store(tmp_path / "gamma.owstore", gen=3),
        "zulu": _store(tmp_path / "zulu.owstore", gen=1),
    }
    document = _json(_caller(corpora, default="zulu"))
    assert [row["name"] for row in document["corpora"]] == ["zulu", "beta", "gamma", "alpha"]


def test_list_filters_by_exact_name_or_prefix_wildcard(tmp_path: Path) -> None:
    corpora = {
        "legal-eu": _store(tmp_path / "a.owstore"),
        "legal-us": _store(tmp_path / "b.owstore"),
        "hr": _store(tmp_path / "c.owstore"),
    }
    caller = _caller(corpora)
    assert [r["name"] for r in _json(caller, corpus="legal-*")["corpora"]] == [
        "legal-eu",
        "legal-us",
    ]
    assert [r["name"] for r in _json(caller, corpus="hr")["corpora"]] == ["hr"]


def test_list_is_capped_at_64_and_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """10:1023. The cap is patched down so the test builds three stores and not sixty-five."""
    monkeypatch.setattr(corpora_module, "CORPORA_LIST_MAX", 2)
    corpora = {name: _store(tmp_path / f"{name}.owstore") for name in ("a", "b", "c")}
    document = _json(_caller(corpora))
    assert len(document["corpora"]) == 2
    assert document["truncated"] is True
    assert CORPORA_LIST_MAX == 64


def test_no_corpus_declared_is_an_empty_list_not_an_error() -> None:
    assert _json(_caller({}))["corpora"] == []


# ---------------------------------------------------------------------------------------------
# the three degradations, on the row
# ---------------------------------------------------------------------------------------------


def test_a_missing_store_is_listed_unreadable_with_its_reason(tmp_path: Path) -> None:
    """10:1031: *"listed with `readable: false` and a `reason`, and never omitted and never
    fatal"* -- and one bad store does not hide a good one."""
    corpora = {
        "good": _store(tmp_path / "good.owstore"),
        "gone": tmp_path / "gone.owstore",
    }
    rows = {row["name"]: row for row in _json(_caller(corpora))["corpora"]}
    assert rows["good"]["readable"] is True
    assert rows["gone"]["readable"] is False
    assert "gone.owstore" in rows["gone"]["reason"]


def test_a_file_that_is_not_a_store_is_unreadable_and_not_fatal(tmp_path: Path) -> None:
    bogus = tmp_path / "bogus.owstore"
    ow.connect(bogus).close()
    (row,) = _json(_caller({"bogus": bogus}))["corpora"]
    assert row["readable"] is False
    assert row["reason"]


def test_a_store_with_no_card_is_stale_with_the_refresh_command(tmp_path: Path) -> None:
    """10:1036. D550: nothing writes a card yet, so this is every real corpus today."""
    caller = _caller({"handbook": _store(tmp_path / "h.owstore", card=False)})
    document = _json(caller)
    (row,) = document["corpora"]
    assert row["card_stale"] is True
    assert row["counts"] == {}
    assert document["degradations"] == ["card_stale: handbook: ow index update --corpus handbook"]


def test_a_card_older_than_the_newest_doc_gen_is_stale(tmp_path: Path) -> None:
    path = _store(tmp_path / "h.owstore")
    conn = ow.connect(path)
    conn.execute("UPDATE doc SET gen = 2")
    conn.commit()
    conn.close()
    (row,) = _json(_caller({"handbook": path}))["corpora"]
    assert row["card_stale"] is True
    assert row["counts"]["docs_indexed"] == 1, "a stale card still shows the counts it has"


# ---------------------------------------------------------------------------------------------
# card, coverage, actions
# ---------------------------------------------------------------------------------------------


def test_card_is_one_whole_entry_that_the_schema_accepts(tmp_path: Path) -> None:
    caller = _caller({"handbook": _store(tmp_path / "h.owstore")}, default="handbook")
    (entry,) = _json(caller, detail="card")["corpora"]
    errors = sorted(error.message for error in _entry_validator().iter_errors(entry))
    assert errors == []
    assert entry["achieved"]["origin_span"] == "normalized"
    assert entry["abstract"] is None
    assert entry["abstract_producer"] is None


def test_card_accepts_exactly_one_corpus_and_refuses_a_wildcard(tmp_path: Path) -> None:
    caller = _caller({"handbook": _store(tmp_path / "h.owstore")})
    assert "refuses a wildcard" in _answer(caller, detail="card", corpus="hand*")
    assert "none was named" in _answer(caller, detail="card")
    assert _answer(caller, detail="card", corpus="legal").startswith("ow: OW-A-002: ")


def test_coverage_carries_the_live_roll_up_absence_gates_read(tmp_path: Path) -> None:
    caller = _caller({"handbook": _store(tmp_path / "h.owstore")}, default="handbook")
    (entry,) = _json(caller, detail="coverage")["corpora"]
    live = entry["coverage"]
    assert (live["discovered"], live["indexed"], live["scope_rows"]) == (1, 1, 1)
    assert live["complete"] is True
    assert entry["gaps"] == []


def test_actions_is_refused_by_name() -> None:
    """D551: the catalog it prints is `omniweave.surface.registry`'s, and no file this server
    loads carries it."""
    text = _answer(_caller({}), detail="actions")
    assert text.startswith("ow: ")
    assert "summary and decision" in text


@pytest.mark.parametrize(
    ("arguments", "needle"),
    [
        ({"detail": "everything"}, "detail must be one of list, card, coverage, actions"),
        ({"corpus": 3}, "corpus must be"),
        ({"corpus": ""}, "corpus must be"),
        ({"verbose": True}, "takes no argument verbose"),
    ],
)
def test_an_argument_problem_is_a_one_line_refusal(arguments: dict[str, Any], needle: str) -> None:
    text = _answer(_caller({}), **arguments)
    assert text.startswith("ow: ")
    assert needle in text
    assert text.count("\n") == 0


def test_the_arguments_are_the_published_schemas_properties() -> None:
    catalogue = json.loads((REPO / "schema" / "mcp-tools-v1.json").read_text(encoding="utf-8"))
    (tool,) = [one for one in catalogue if one["name"] == corpora_module.CORPORA_TOOL]
    schema = tool["inputSchema"]
    assert set(schema["properties"]) == corpora_module._ARGUMENTS
    assert tuple(schema["properties"]["detail"]["enum"]) == DETAILS
    assert "outputSchema" not in tool, "D549"


def test_the_reference_the_plan_prints_cannot_be_resolved_by_a_client() -> None:
    """D549's cause, pinned: 18:1348's `{"$ref": "schema/corpora-out-v1.json"}` is what the
    reference client would validate `structuredContent` against, and it does not resolve."""
    from jsonschema import validate  # noqa: PLC0415
    from referencing.exceptions import Unresolvable  # noqa: PLC0415

    with pytest.raises(Unresolvable):
        validate({"corpora": []}, {"$ref": "schema/corpora-out-v1.json"})
