"""`omniweave_core.out.receipt`: the delivery evidence, refused unless it is consistent.

09-generation.md section 5.3 (`CheckValue`'s six values, the `Receipt`, the console line, the
three-way report status) and section 6 (`part` is the floor). The receipt never gates; these tests
hold it to saying only what is true.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from omniweave_core.errors import TargetError
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.opc import part_digest
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.out.receipt import (
    ArtefactDeterminism,
    CheckValue,
    Receipt,
    console_line,
    receipt_part_digest,
    report_status,
)

HEX = "a" * 64
UNITS = {
    "u01": UnitOutcome.NATIVE,
    "u02": UnitOutcome.NATIVE,
    "u03": UnitOutcome.PASSTHROUGH,
    "u04": UnitOutcome.BAKED,
}


def _receipt(**fields: Any) -> Receipt:
    base: dict[str, Any] = {
        "schema": "omniweave.out-receipt/1",
        "target": "pptx",
        "slug": "q3-board",
        "artifact_gen": 4,
        "output": {"path": "q3-board@4/q3-board.pptx", "bytes": 1_843_112, "sha256": HEX},
        "part_digest": HEX,
        "determinism": (ArtefactDeterminism.PART, ArtefactDeterminism.BYTE),
        "gate_status": GateStatus.PASSED,
        "delivery": "release",
        "checks": (
            CheckValue("zip_integrity", "passed"),
            CheckValue(
                "internal_relationships",
                "enforced-at-build",
                fixture="test_pack_raises_on_a_dangling_rel",
            ),
            CheckValue("measure_available", "not-applicable", detail="measure = none"),
        ),
        "units": UNITS,
        "counts": {UnitOutcome.NATIVE: 2, UnitOutcome.PASSTHROUGH: 1, UnitOutcome.BAKED: 1},
        "portability": {"generic_only_font_stacks": ()},
        "normalizations": (),
        "degradations": (),
        "skipped_checks": (),
        "truncations": (),
    }
    base.update(fields)
    return Receipt(**base)


def test_a_consistent_receipt_builds_and_serialises() -> None:
    receipt = _receipt()
    doc = receipt.as_json()
    assert doc["counts"] == {"baked": 1, "native": 2, "passthrough": 1}
    assert doc["checks"][1] == {
        "name": "internal_relationships",
        "value": "enforced-at-build",
        "fixture": "test_pack_raises_on_a_dangling_rel",
    }
    assert doc["checks"][2] == {
        "name": "measure_available",
        "value": "not-applicable",
        "detail": "measure = none",
    }
    assert doc["determinism"] == ["part", "byte"]
    assert doc["gate_status"] == "passed"


@pytest.mark.parametrize(
    ("name", "value", "fixture", "match"),
    [
        ("Zip", "passed", None, "is not"),
        ("zi", "passed", None, "is not"),
        ("a" * 41, "passed", None, "is not"),
        ("zip_integrity", "ok", None, "is not one of"),
        ("zip_integrity", "enforced-at-build", None, "fixture"),
        ("zip_integrity", "passed", "test_x", "fixture"),
    ],
)
def test_a_check_value_holds_its_grammar_and_its_iff(
    name: str, value: str, fixture: str | None, match: str
) -> None:
    with pytest.raises(ValueError, match=match):
        CheckValue(name, value, fixture=fixture)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("fields", "match"),
    [
        ({"schema": "omniweave.out-receipt/2"}, "schema"),
        (
            {
                "checks": (
                    CheckValue("zip_integrity", "passed"),
                    CheckValue("zip_integrity", "warning"),
                )
            },
            "repeat",
        ),
        ({"counts": {UnitOutcome.NATIVE: 4}}, "tally"),
        ({"determinism": (ArtefactDeterminism.BYTE,)}, "part"),
        ({"part_digest": "sha256:" + HEX}, "64 hex"),
        ({"output": {"path": "x", "bytes": 1}}, "sha256"),
        ({"gate_status": GateStatus.MANUAL_REQUIRED}, "release receipt carries gate passed"),
        ({"delivery": "draft"}, "draft receipt carries gate manual-required"),
    ],
)
def test_an_inconsistent_receipt_is_refused(fields: dict[str, Any], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _receipt(**fields)


def test_a_draft_keeps_the_gate_it_had() -> None:
    draft = _receipt(delivery="draft", gate_status=GateStatus.MANUAL_REQUIRED)
    assert draft.gate_status is GateStatus.MANUAL_REQUIRED


def test_the_receipt_holds_the_part_digest_as_hex() -> None:
    members = {"[Content_Types].xml": b"<Types/>", "_rels/.rels": b"<Relationships/>"}
    hex_digest = receipt_part_digest(part_digest(members))
    assert _receipt(part_digest=hex_digest).part_digest == hex_digest
    with pytest.raises(ValueError, match="not a sha256"):
        receipt_part_digest("md5:" + HEX)


@pytest.mark.parametrize(
    ("gate", "introduced", "portability", "normalizations", "status"),
    [
        (GateStatus.FAILED, 0, {}, (), "failed"),
        (GateStatus.PASSED, 0, {"generic_only_font_stacks": ()}, (), "passed"),
        (GateStatus.PASSED, 1, {}, (), "passed-with-warnings"),
        (GateStatus.PASSED, 0, {"external_asset_refs": ("https://x",)}, (), "passed-with-warnings"),
        (GateStatus.PASSED, 0, {}, ({"action": "upper_hex"},), "passed-with-warnings"),
        (GateStatus.MANUAL_REQUIRED, 0, {}, (), "passed-with-warnings"),
    ],
)
def test_the_report_status_is_09s_three_way_derivation(
    gate: GateStatus,
    introduced: int,
    portability: dict[str, tuple[str, ...]],
    normalizations: tuple[dict[str, str], ...],
    status: str,
) -> None:
    assert report_status(gate, introduced, portability, normalizations) == status


def test_the_console_line_is_09s() -> None:
    line = console_line(_receipt(), introduced_warning_count=1)
    assert line == (
        "[POSTFLIGHT] slug=q3-board gen=4 status=passed-with-warnings gate=passed units=4\n"
        "             native=2 baked=1 passthrough=1 determinism=part,byte bytes=1843112"
    )
    clean = replace(_receipt(), portability={})
    assert "status=passed gate=passed" in console_line(clean, introduced_warning_count=0)


# ---------------------------------------------------------------------------------------------
# Ruling 6 (D771): read back from JSON, and built again
# ---------------------------------------------------------------------------------------------


def _full() -> Receipt:
    """A receipt with every list and mapping populated, so the round trip reads each back."""
    return _receipt(
        portability={"generic_only_font_stacks": ("Inter",), "external_asset_refs": ()},
        normalizations=({"construct": "attr.class.upper", "unit": "u01"},),
        degradations=({"kind": "font_fallback", "count": 2},),
        skipped_checks=({"rule": "ow.measure@1", "needs": "measure"},),
        truncations=({"rule": "ow.cites@1", "kept": 50},),
    )


def test_a_receipt_reads_back_as_itself() -> None:
    receipt = _full()
    again = Receipt.from_json(receipt.as_json())
    assert again == receipt
    assert again.to_bytes() == receipt.to_bytes()
    assert receipt.to_bytes().endswith(b"}\n")
    assert receipt.to_bytes().startswith(b'{\n "artifact_gen": 4,')


def test_the_bytes_read_back_through_json() -> None:
    import json  # noqa: PLC0415

    receipt = _full()
    assert Receipt.from_json(json.loads(receipt.to_bytes())) == receipt


def _corrupt(raw: object) -> str:
    with pytest.raises(TargetError) as caught:
        Receipt.from_json(raw)
    assert caught.value.code() == "OW_TARGET_PACKAGE_CORRUPT"
    return str(caught.value)


def test_a_receipt_with_a_key_too_many_or_too_few_is_refused() -> None:
    doc = _full().as_json()
    assert "'verdict'" in _corrupt({**doc, "verdict": "passed"})
    del doc["truncations"]
    got, _, wanted = _corrupt(doc).partition(", not ")
    assert ("'truncations'" in got, "'truncations'" in wanted) == (False, True)
    assert "its keys are list" in _corrupt([doc])


@pytest.mark.parametrize(
    ("key", "value", "named"),
    [
        ("artifact_gen", True, "artifact_gen"),
        ("artifact_gen", "4", "artifact_gen"),
        ("slug", 4, "slug"),
        ("output", {"path": "x", "bytes": 1.5, "sha256": HEX}, "1.5"),
        ("output", {"path": "x", "bytes": False, "sha256": HEX}, "False"),
        ("determinism", ["part", "pixel"], "pixel"),
        ("gate_status", "green", "green"),
        ("units", {"u01": "native", "u02": "magic"}, "magic"),
        ("units", {"u01": 1}, "1"),
        ("counts", {"native": "2"}, "'2'"),
        ("counts", {"native": True}, "True"),
        ("portability", {"generic_only_font_stacks": "Inter"}, "Inter"),
        ("portability", {"generic_only_font_stacks": [1]}, "1"),
        ("normalizations", [{"unit": 1}], "1"),
        ("degradations", ["font_fallback"], "font_fallback"),
        ("degradations", [{1: "x"}], "object"),
        ("checks", [{"name": "zip_integrity"}], "name, value"),
        ("checks", [{"name": "zip_integrity", "value": "passed", "why": "x"}], "name, value"),
        ("checks", [{"name": "zip_integrity", "value": 1}], "1"),
        ("checks", [{"name": "zip_integrity", "value": "passed", "detail": 2}], "2"),
        ("checks", ["zip_integrity"], "object"),
    ],
)
def test_a_value_outside_its_type_is_refused_by_name(key: str, value: object, named: str) -> None:
    doc = {**_full().as_json(), key: value}
    assert named in _corrupt(doc)


def test_a_receipt_that_does_not_hold_together_is_refused_on_reading() -> None:
    """Ruling 1 again, on the host: the counts are not the tally of the units."""
    doc = {**_full().as_json(), "counts": {"native": 4}}
    assert "tally" in _corrupt(doc)


def test_a_check_reads_back_with_its_optional_fields() -> None:
    doc = _full().as_json()
    again = Receipt.from_json(doc)
    assert again.checks[1].fixture == "test_pack_raises_on_a_dangling_rel"
    assert again.checks[2].detail == "measure = none"
    assert again.checks[0] == CheckValue("zip_integrity", "passed")
