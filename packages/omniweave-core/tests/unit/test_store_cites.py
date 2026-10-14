"""`SqliteCiteResolver` against a real store, and `out.cites`' predicate and refusing resolver.

09-generation.md section 10: batched resolution, a pinned `doc_gen`, and verbatimness that is
proved, never claimed. The store holds one document at its second generation, with a retired
first-generation block, and a second document beside it.
"""

from __future__ import annotations

import sqlite3  # noqa: TID251 -- the fixture writes the rows the resolver reads.
import unicodedata
from typing import TYPE_CHECKING

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.model.enums import Quote, enum_val_rows
from omniweave_core.out.cites import NO_CITES, CitedBlock, CiteResolver, verbatim
from omniweave_core.store import cites as cites_module
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as ow
from omniweave_core.store.cites import RESOLVE_SQL, SqliteCiteResolver

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

NOW_NS = 1_700_000_000_000_000_000
ORD = {(domain, name): ordinal for domain, ordinal, name in enum_val_rows()}
CAFE = unicodedata.normalize("NFD", "Revenue at the café rose 12%.")


def _seed(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint, options_digest)"
        " VALUES (1, 'parse.pdf', 1, 'f', x'00')"
    )
    for doc_ord, gen in ((7, 2), (8, 1)):
        connection.execute(
            "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
            " format_evidence, source_bytes, gen, status, model_version, declared, achieved)"
            " VALUES (?, ?, ?, ?, 'application/pdf', 'pdf', '{}', 10, ?, 'ok', '1.1', '{}', '{}')",
            (doc_ord, bytes([doc_ord]) * 16, b"\x00" * 32, f"file:///c/{doc_ord}.pdf", gen),
        )
    for doc_ord, gen in ((7, 1), (7, 2), (8, 1)):
        connection.execute(
            "INSERT INTO page(doc_ord, gen, page, page_kind, method, producer_id)"
            " VALUES (?, ?, 0, ?, ?, 1)",
            (doc_ord, gen, ORD["page_kind", "page"], ORD["method", "native_xml"]),
        )
    blocks = [
        (101, 7, 2, "d7#1", Quote.VERBATIM, 0, 0, CAFE),
        (102, 7, 2, "d7#2", Quote.NORMALIZED, 4, 0, "Margins held."),
        (103, 7, 1, "d7#3", Quote.VERBATIM, 0, 1, "A retired sentence."),
        (104, 8, 1, "d8#1", Quote.VERBATIM, 0, 0, "Another document."),
        (105, 7, 2, "d7#5", Quote.VERBATIM, 0, 1, "A tombstone at the head generation."),
        (106, 7, 1, "d7#6", Quote.VERBATIM, 0, 0, "Live state, an old generation."),
    ]
    for block_id, doc_ord, gen, cite, quote, bits, state, text in blocks:
        connection.execute(
            "INSERT INTO block(block_id, doc_ord, gen, page, addr, cite, ord, kind, layer, text,"
            " content_digest, os_kind, producer_id, method, trust, quote, origin_operator,"
            " origin_driver, driver_schema_v, restriction_bits, state)"
            " VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?, ?, x'00', ?, 1, ?, 2, ?, 'parse.pdf',"
            " 'parse.pdf.text', 1, ?, ?)",
            (
                block_id,
                doc_ord,
                gen,
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
                state,
            ),
        )


@pytest.fixture
def owstore(tmp_path: Path) -> Path:
    path = tmp_path / "index.owstore"
    connection = ow.connect(path)
    try:
        assert len(migrate.apply_pending(connection, now_ns=NOW_NS)) == 5
        connection.execute("BEGIN IMMEDIATE")
        _seed(connection)
        connection.execute("COMMIT")
    finally:
        connection.close()
    return path


@pytest.fixture
def resolver(owstore: Path) -> Iterator[SqliteCiteResolver]:
    thread = ow.StoreThread(lambda: ow.connect(owstore)).start()
    try:
        yield SqliteCiteResolver(thread, corpus="acme")
    finally:
        thread.close()


# ---------------------------------------------------------------------------
# The resolver
# ---------------------------------------------------------------------------


def test_a_live_cite_resolves_with_its_documents_head_generation(
    resolver: SqliteCiteResolver,
) -> None:
    found = resolver.by_cites(("d7#1", "d7#2", "d8#1"))
    assert found["d7#1"] == CitedBlock("d7#1", 101, 7, 2, CAFE, Quote.VERBATIM, 0)
    assert found["d7#2"] == CitedBlock("d7#2", 102, 7, 2, "Margins held.", Quote.NORMALIZED, 4)
    assert found["d8#1"] is not None and found["d8#1"].doc_gen == 1


def test_a_retired_cite_does_not_resolve(resolver: SqliteCiteResolver) -> None:
    """Ruling 2: a compile cites what is live; `ow open` names the successor."""
    assert resolver.by_cite("d7#3") is None
    assert resolver.by_cite("d7#5") is None
    assert resolver.by_cite("d7#6") is None, "only the head generation is live"


@pytest.mark.parametrize("token", ["d7#99", "d9#1", "not a cite", "other:d7#1", "d7#1 ", ""])
def test_anything_else_is_none_and_never_an_error(resolver: SqliteCiteResolver, token: str) -> None:
    assert resolver.by_cites((token,)) == {token: None}


def test_tokens_are_keyed_as_asked(resolver: SqliteCiteResolver) -> None:
    """Ruling 3: this corpus's qualified form resolves, keyed by the token as written."""
    found = resolver.by_cites(("acme:d7#1", "d7#1", "acme:d7#1", "other:d7#1"))
    assert list(found) == ["acme:d7#1", "d7#1", "other:d7#1"]
    qualified = found["acme:d7#1"]
    assert qualified is not None and qualified == found["d7#1"]
    assert qualified.cite == "d7#1"
    assert found["other:d7#1"] is None


def test_a_large_batch_is_chunked_and_still_whole(
    resolver: SqliteCiteResolver, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cites_module, "BATCH", 2)
    asked = ("d8#1", "d7#2", "d7#99", "d7#1", "d7#3")
    found = resolver.by_cites(asked)
    assert {t for t, b in found.items() if b is not None} == {"d8#1", "d7#2", "d7#1"}


def test_nothing_to_resolve_touches_no_store() -> None:
    class Unreachable:
        def run(self, *_args: object, **_kw: object) -> object:  # pragma: no cover -- the point.
            raise AssertionError("the store was read for a batch with no cite in it")

    resolver = SqliteCiteResolver(Unreachable(), corpus="acme")  # type: ignore[arg-type]
    assert resolver.by_cites(("nope", "other:d7#1")) == {"nope": None, "other:d7#1": None}


def test_the_batch_rides_the_block_cite_index(owstore: Path) -> None:
    connection = sqlite3.connect(owstore)
    try:
        plan = " ".join(
            str(r[-1])
            for r in connection.execute(
                f"EXPLAIN QUERY PLAN {RESOLVE_SQL}", {"pairs": '[[7, "d7#1"]]'}
            )
        )
    finally:
        connection.close()
    assert "block_cite" in plan, plan


def test_the_resolver_is_a_cite_resolver(resolver: SqliteCiteResolver) -> None:
    typed: CiteResolver = resolver
    assert typed.by_cite("d8#1") is not None


# ---------------------------------------------------------------------------
# out.cites: the refusing resolver and the predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call", [lambda: NO_CITES.by_cite("d7#1"), lambda: NO_CITES.by_cites(("d7#1",))]
)
def test_no_cites_refuses_and_names_the_missing_need(call: object) -> None:
    with pytest.raises(TargetError, match="given no CiteResolver") as caught:
        call()  # type: ignore[operator]
    assert caught.value.code() == "OW_TARGET_RULE_RAISED"
    assert '"cites"' in caught.value.fix


BLOCK = CitedBlock("d7#1", 101, 7, 2, CAFE, Quote.VERBATIM, 0)


@pytest.mark.parametrize(
    ("visible", "block", "span", "proved"),
    [
        ("café rose", BLOCK, (len("Revenue at the "), len(CAFE) - len(" 12%.")), True),
        (unicodedata.normalize("NFC", CAFE), BLOCK, (0, len(CAFE)), True),
        ("Revenue", BLOCK, (0, 7), True),
        ("Revenue", BLOCK, (0, 8), False),
        ("revenue", BLOCK, (0, 7), False),
        ("Revenue", BLOCK, None, False),
        ("Revenue", BLOCK, (7, 7), False),
        ("Revenue", BLOCK, (-1, 7), False),
        ("", BLOCK, (7, 7), False),
        ("", BLOCK, (-1, 0), False),
        ("", BLOCK, (len(CAFE), len(CAFE) + 5), False),
        ("x", BLOCK, (len(CAFE), len(CAFE) + 1), False),
        ("Revenue", CitedBlock("d7#2", 102, 7, 2, CAFE, Quote.NORMALIZED, 0), (0, 7), False),
        ("Revenue", CitedBlock("d7#4", 105, 7, 2, None, Quote.VERBATIM, 0), (0, 7), False),
    ],
)
def test_verbatim_is_section_10s_predicate_whole(
    visible: str, block: CitedBlock, span: tuple[int, int] | None, proved: bool
) -> None:
    assert verbatim(visible, block, span) is proved
