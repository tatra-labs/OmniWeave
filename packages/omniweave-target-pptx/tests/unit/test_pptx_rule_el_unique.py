"""`pptx.el.unique@1`: `data-ow-el` is unique in the unit (OUT21). D789 ruling 4."""

from __future__ import annotations

from dataclasses import dataclass, field

from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.finding import Finding
from omniweave_core.out.plan import OutUnit
from omniweave_target_pptx.driver import PptxCompiler
from omniweave_target_pptx.rules.el_unique import SPEC

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="u01/e1">'


@dataclass
class _Ctx:
    doc: CarrierDoc | None
    unit: OutUnit | None = field(
        default_factory=lambda: OutUnit(id="u01", ord=1, il_path="il/u01.svg")
    )


def _run(body: str) -> list[Finding]:
    doc = PptxCompiler().carrier("il/u01.svg", f"{SVG}{body}</svg>")
    return list(SPEC.fn(_Ctx(doc)))  # type: ignore[arg-type]


def test_the_spec() -> None:
    assert (SPEC.id, SPEC.order, SPEC.codes) == (
        "pptx.el.unique@1",
        12,
        {"OW_TARGET_EL_DUPLICATE"},
    )


def test_distinct_addresses_say_nothing() -> None:
    assert _run('<text data-ow-el="u01/e2" x="1" y="1">a</text><g data-ow-el="u01/e3"/>') == []


def test_each_repeat_names_the_first_and_its_own_place() -> None:
    found = _run(
        '<text data-ow-el="u01/e2" x="1" y="1">a</text>'
        '<text data-ow-el="u01/e2" x="1" y="2">b</text>'
        '<g data-ow-el="u01/e2"/><g data-ow-el="u01/e1"/>'
    )
    assert [(f.code, f.construct, f.el) for f in found] == [
        ("OW_TARGET_EL_DUPLICATE", "ow.el", "u01/e2"),
        ("OW_TARGET_EL_DUPLICATE", "ow.el", "u01/e2"),
        ("OW_TARGET_EL_DUPLICATE", "ow.el", "u01/e1"),
    ]
    first = found[0].msg.split(" appears at ")[1].split(" and ")[0]
    assert all(f.msg.startswith("data-ow-el=") for f in found)
    assert found[1].msg.split(" appears at ")[1].split(" and ")[0] == first
    assert found[0].at != found[1].at


def test_a_document_scope_context_reads_nothing() -> None:
    assert list(SPEC.fn(_Ctx(None, None))) == []  # type: ignore[arg-type]
