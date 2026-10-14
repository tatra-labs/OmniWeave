"""`pptx.unit.root@1`: the slide is one `<svg>` root, never nested. D789 ruling 2."""

from __future__ import annotations

from dataclasses import dataclass

from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.finding import Finding, Provenance, Severity
from omniweave_core.out.plan import OutUnit
from omniweave_target_pptx.driver import PptxCompiler
from omniweave_target_pptx.rules.unit_root import SPEC

SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720"'


@dataclass
class _Ctx:
    doc: CarrierDoc | None
    unit: OutUnit | None = OutUnit(id="u01", ord=1, il_path="il/u01.svg")  # noqa: RUF009


def _run(text: str) -> list[Finding]:
    return list(SPEC.fn(_Ctx(PptxCompiler().carrier("il/u01.svg", text))))  # type: ignore[arg-type]


def test_the_spec_is_the_structural_bands_first() -> None:
    assert (SPEC.id, SPEC.order, SPEC.scope, SPEC.codes) == (
        "pptx.unit.root@1",
        10,
        "unit",
        {"OW_TARGET_UNIT_MALFORMED"},
    )


def test_one_svg_root_is_a_slide() -> None:
    assert _run(f'{SVG}><g><rect width="1" height="1"/></g></svg>') == []


def test_a_root_of_another_element_is_refused() -> None:
    [found] = _run('<g xmlns="http://www.w3.org/2000/svg"><rect width="1" height="1"/></g>')
    assert (found.code, found.construct, found.severity, found.provenance) == (
        "OW_TARGET_UNIT_MALFORMED",
        "ow.unit",
        Severity.ERROR,
        Provenance.INTRODUCED,
    )
    assert found.msg == "the unit root is <g>; an owsvg/1 slide is one <svg>"
    assert found.fix == "ow out constructs pptx --construct ow.unit"


def test_each_nested_svg_is_its_own_finding() -> None:
    found = _run(f'{SVG}><svg viewBox="0 0 1 1"/><g><svg viewBox="0 0 1 1"/></g></svg>')
    assert [f.msg for f in found] == [
        "an <svg> inside the slide: one unit is one <svg>; crop with clip-path"
    ] * 2
    assert found[0].at != found[1].at


def test_a_document_scope_context_reads_nothing() -> None:
    assert list(SPEC.fn(_Ctx(None, None))) == []  # type: ignore[arg-type]
