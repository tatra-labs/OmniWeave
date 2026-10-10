"""`derive.report.llm` (D731): one community's context, one call, one report."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_llm.decision_pass import DecisionPass
from omniweave_llm.lane_pass import CHAT_PATH
from omniweave_llm.prompt import decodable, render
from omniweave_llm.report import answer_frames, read_community, unparsed_frames
from omniweave_llm.report_llm.driver import DRIVER_ID, ReportLLM
from omniweave_ports import DriverError, FailureClass, ProbeStatus
from omniweave_ports.types import DeriveScope, UnitRef
from test_entity_driver import _IO, _Handle, _reply

if TYPE_CHECKING:
    from pathlib import Path

WITNESS = [{"unit_uri": "file:///docs/a.md", "unit_part": "", "token": "com:7"}]
RECORDS: list[dict[str, Any]] = [
    {"t": "member", "title": "Northwind Traders", "etype": "org", "description": "A supplier."},
    {"t": "member", "title": "Contoso Bank", "etype": "org", "description": "The lender."},
    {"t": "edge", "src": "Contoso Bank", "relation": "lends_to", "dst": "Northwind Traders",
     "quote": "Contoso Bank lends to Northwind"},
    {"t": "claim", "subject": "Northwind Traders", "predicate": "deliver", "object": "4,000 units",
     "status": "asserted", "t_start": "2026-06-30"},
]  # fmt: skip


def _community(name: str = "com:0123456789abcdef", *records: dict[str, Any]) -> bytes:
    header = {"t": "community", "community": name, "level": 0, "coverage": 0.5, "witness": WITNESS}
    frames = [header, *(records or RECORDS)]
    return b"".join(json.dumps(f).encode() + b"\n" for f in frames)


def _report(**fields: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "Northwind and its lender",
        "summary": "A supplier financed by one bank.",
        "findings": [{"summary": "Contoso lends.", "explanation": "The memo says so."}],
        "rating": 6.5,
        "rating_explanation": "One supply chain.",
    }
    base.update(fields)
    return base


def _run(
    tmp_path: Path, handle: _Handle, *bodies: bytes
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any]:
    blobs = MemoryBlobStore(tmp_path / "blobs")
    units = tuple(
        UnitRef(uri=f"com:{i}", part="", content_sha256=blobs.add(b), byte_len=len(b))
        for i, b in enumerate(bodies)
    )
    io = _IO(make_io(blobs, tmp_path / "tmp"), handle)
    result = ReportLLM().derive(
        DeriveScope(lane="report", units=units, allowed_cites=frozenset()),
        io,  # type: ignore[arg-type]
    )
    assert result.outcome == "ok"
    items, witness = result.produced
    assert (items.kind, witness.kind) == ("graph_items", "witness_set")
    assert ReportLLM().is_valid_nonempty(items)

    def lines(ref: Any) -> list[dict[str, Any]]:
        body = ref.inline if ref.inline is not None else blobs.open(str(ref.blob)).read()
        return [json.loads(line) for line in body.decode().splitlines()]

    return lines(items), lines(witness), result.metrics


# ---------------------------------------------------------------------------------------------
# the view
# ---------------------------------------------------------------------------------------------


def test_a_community_is_its_header_and_its_records() -> None:
    """Ruling 1: the body the model reads is the records alone."""
    view = read_community(_community())
    assert (view.community, view.level, view.coverage) == ("com:0123456789abcdef", 0, 0.5)
    assert view.witness == tuple(WITNESS)
    assert view.source == view.community
    assert [json.loads(line)["t"] for line in view.body.splitlines()] == [
        "member", "member", "edge", "claim",
    ]  # fmt: skip
    assert '"community"' not in view.body


@pytest.mark.parametrize(
    ("body", "why"),
    [
        (b"", "JSON object lines"),
        (b"[1]\n", "JSON object lines"),
        (b'{"t": "member", "title": "x"}\n', "opens with its community header"),
        (b'{"t": "community", "community": "com:x"}\n', "one or more records"),
        (_community("com:x", {"t": "pair", "pair": 0}), "one or more records"),
    ],
    ids=["empty", "array", "headless", "bare", "foreign"],
)
def test_a_body_that_is_not_a_community_is_refused(body: bytes, why: str) -> None:
    with pytest.raises(ValueError, match=why):
        read_community(body)


def test_a_parent_is_written_from_its_childrens_summaries() -> None:
    """Ruling 1 (06:2017)."""
    child = {"t": "child", "title": "Northwind and its lender", "summary": "A supplier."}
    view = read_community(_community("com:parent", child))
    assert json.loads(view.body) == child


def test_no_identifier_reaches_the_prompt() -> None:
    """INV-8: the witness's units and tokens stay in the header, out of the prompt."""
    view = read_community(_community())
    text = render("report", body=view.body, source=view.source).text
    assert "file:///" not in text and "com:7" not in text
    assert "Contoso Bank lends to Northwind" in text


# ---------------------------------------------------------------------------------------------
# the answer
# ---------------------------------------------------------------------------------------------


def test_the_report_is_kept_whole() -> None:
    """Ruling 3: everything the model wrote, and nothing the host measures."""
    view = read_community(_community())
    frames = answer_frames(view, _report())
    assert frames == [
        {"t": "community", "community": view.community},
        {"t": "report", **_report()},
    ]
    assert "coverage" not in frames[1]


def test_an_answer_that_does_not_parse_writes_no_report() -> None:
    """Ruling 4."""
    view = read_community(_community())
    assert unparsed_frames(view, "{oops", ["$: not JSON"]) == [
        {"t": "community", "community": view.community},
        {"t": "report", "unparsed": "{oops", "problems": ["$: not JSON"]},
    ]


# ---------------------------------------------------------------------------------------------
# the Pass
# ---------------------------------------------------------------------------------------------


def test_one_community_is_one_call_constrained_by_the_report_schema(tmp_path: Path) -> None:
    """D726's rulings, lifted into `DecisionPass` (D731): one call, no glean, the witness echoed."""
    handle = _Handle([_reply(_report(), tokens=(3000, 400))])
    frames, witness, metrics = _run(tmp_path, handle, _community())
    view = read_community(_community())
    assert frames == answer_frames(view, _report())
    [(path, request, size)] = handle.requests
    prompt = render("report", body=view.body, source=view.source)
    assert path == CHAT_PATH
    assert request["messages"] == [{"role": "user", "content": prompt.text}]
    assert request["response_format"]["json_schema"] == {
        "name": "owgraph_report", "schema": decodable(prompt.schema), "strict": True,
    }  # fmt: skip
    assert (metrics.calls, metrics.tokens_in, metrics.tokens_out) == (1, 3000, 400)
    assert metrics.bytes_egress == size
    assert witness == WITNESS


def test_each_community_is_its_own_call(tmp_path: Path) -> None:
    handle = _Handle([_reply(_report(title="One")), _reply(_report(title="Two"))])
    frames, witness, metrics = _run(tmp_path, handle, _community("com:a"), _community("com:b"))
    assert [f.get("community") for f in frames if f["t"] == "community"] == ["com:a", "com:b"]
    assert [f["title"] for f in frames if f["t"] == "report"] == ["One", "Two"]
    assert metrics.calls == 2
    assert witness == [*WITNESS, *WITNESS]


def test_an_answer_off_the_schema_is_one_malformed_report(tmp_path: Path) -> None:
    handle = _Handle([_reply(_report(rating=11))])
    frames, _witness, _metrics = _run(tmp_path, handle, _community())
    [malformed] = frames[1:]
    assert "title" not in malformed
    assert malformed["problems"] == ["$.rating: 11 is outside the bounds"]


def test_a_body_that_is_not_a_community_is_corrupt_input(tmp_path: Path) -> None:
    with pytest.raises(DriverError) as raised:
        _run(tmp_path, _Handle([]), b'{"t": "pairs", "batch": "band:x", "n": 1}\n')
    assert raised.value.cls is FailureClass.CORRUPT_INPUT


def test_the_driver_is_the_shared_decision_pass_and_takes_no_other_config() -> None:
    assert issubclass(ReportLLM, DecisionPass)
    assert ReportLLM.probe(None).status is ProbeStatus.OK  # type: ignore[arg-type]
    assert ReportLLM().service == "llm"
    with pytest.raises(ValueError, match=DRIVER_ID):
        ReportLLM(model="x")
