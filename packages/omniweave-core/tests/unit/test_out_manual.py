"""`omniweave_core.out.manual`: the `ow:manual` region, the bundle's reading of it, and evidence.

09-generation.md section 9. A region is an element carrying `data-ow-manual`, its value a
`ManualReason`; `ManualEvidence` records what is visibly present and refuses anything decided.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.errors import explain
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.finding import Provenance, Severity
from omniweave_core.out.job import ILBundle
from omniweave_core.out.manual import (
    EVIDENCE_SCHEMA,
    EvidenceRegion,
    ManualEvidence,
    ManualRegion,
    manual_regions,
)
from omniweave_core.out.plan import ManualReason

TABLE = """\
schema = "omniweave.out-constructs/1"
carrier = "html"
il = "owtext/1"
version = 1
unknown_construct = "forbidden"

[[construct]]
id = "attr.ow-cite"
selector = "@data-ow-cite"
disposition = "native"
round_trip = "exact"
canonical = "cite tokens"
maps_to = "lower.cites:sidecar"
code = "OW_TARGET_CITE_MALFORMED"
since = "0.1.0"

[[construct]]
id = "attr.ow-el"
selector = "@data-ow-el"
disposition = "native"
round_trip = "exact"
canonical = "u<NN>e<NN>"
maps_to = "lower.ids:passthrough"
code = "OW_TARGET_EL_DUPLICATE"
since = "0.1.0"

[[construct]]
id = "elem.ow-manual"
selector = "html|div[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
since = "0.1.0"
"""
CONSTRUCTS = ConstructTable.parse(tomllib.loads(TABLE), {}, source="constructs.toml")
TWO = (
    '<section data-ow-el="u01/e1">'
    '<div data-ow-el="u01/e2" data-ow-manual="guesswork">a</div>'
    '<div data-ow-el="u01/e3" data-ow-manual="unverifiable_data">b</div>'
    '<div data-ow-manual="unrepresentable">c</div>'
    "</section>"
)


def carrier(path: str, text: str) -> CarrierDoc:
    return html_carrier(path, text, strict=False)


# ---------------------------------------------------------------------------
# The region
# ---------------------------------------------------------------------------


def test_every_region_in_document_order_with_its_reason() -> None:
    regions = manual_regions("u01", carrier("il/u01.html", TWO))
    assert [(r.el, r.raw, r.reason) for r in regions] == [
        ("u01/e2", "guesswork", None),
        ("u01/e3", "unverifiable_data", ManualReason.UNVERIFIABLE_DATA),
        (None, "unrepresentable", ManualReason.UNREPRESENTABLE),
    ]
    assert regions[1].as_json() == {"unit": "u01", "el": "u01/e3", "reason": "unverifiable_data"}
    assert manual_regions("u01", carrier("il/u01.html", "<section><p>x</p></section>")) == ()


def test_an_unknown_reason_is_the_frameworks_error_at_the_region() -> None:
    region = manual_regions("u01", carrier("il/u01.html", TWO))[0]
    finding = region.finding()
    assert (finding.code, finding.severity, finding.provenance) == (
        "OW_TARGET_MANUAL_REASON_UNKNOWN",
        Severity.ERROR,
        Provenance.FRAMEWORK,
    )
    assert (finding.unit, finding.el, finding.at) == ("u01", "u01/e2", region.at)
    assert "'guesswork'" in finding.msg and "unverifiable_wording" in finding.msg
    assert explain("OW_TARGET_MANUAL_REASON_UNKNOWN").numeric == "OW-T-513"


def test_an_empty_value_is_unknown_never_a_reason() -> None:
    region = ManualRegion("u01", "u01/e2", "")
    assert region.reason is None


# ---------------------------------------------------------------------------
# The bundle
# ---------------------------------------------------------------------------


def _bundle(tmp_path: Path, u01: str, u02: str = "<section><p>y</p></section>") -> ILBundle:
    il = tmp_path / "il"
    il.mkdir()
    (il / "il.toml").write_text(
        'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "sha256:'
        + "7" * 64
        + '"\n\n[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n\n'
        '[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n',
        encoding="utf-8",
    )
    (il / "u01.html").write_text(u01, encoding="utf-8")
    (il / "u02.html").write_text(u02, encoding="utf-8")
    return ILBundle.load(il, carrier=carrier, constructs=CONSTRUCTS)


def test_the_bundle_gives_each_unit_its_first_known_reason(tmp_path: Path) -> None:
    """Job ruling 17: an unknown value is skipped for the reason, never for the gate."""
    bundle = _bundle(tmp_path, TWO)
    assert [u.manual_reason for u in bundle.units] == [ManualReason.UNVERIFIABLE_DATA, None]
    assert [r.raw for r in bundle.manual["u01"]] == [
        "guesswork",
        "unverifiable_data",
        "unrepresentable",
    ]
    assert "u02" not in bundle.manual


def test_a_unit_whose_only_region_is_unknown_has_no_reason(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path, '<section><div data-ow-manual="x">a</div></section>')
    assert bundle.units[0].manual_reason is None
    assert len(bundle.manual["u01"]) == 1


# ---------------------------------------------------------------------------
# ManualEvidence
# ---------------------------------------------------------------------------


def _region(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "r1",
        "bbox": [10, 10, 100, 40],
        "family": "text",
        "text": "Q3 revenue",
        "confidence": 0.9,
        "sufficiency": "sufficient",
        "boundary_complete": True,
        "occluded": False,
    }
    base.update(over)
    return base


def _evidence(*regions: dict[str, Any], **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "schema": EVIDENCE_SCHEMA,
        "source": "frames/slide-07.png",
        "sha256": "ab" * 32,
        "width": 1920,
        "height": 1080,
        "regions": list(regions) or [_region()],
    }
    base.update(over)
    return base


def test_evidence_reads_what_is_visibly_present() -> None:
    evidence = ManualEvidence.from_json(
        _evidence(
            _region(),
            _region(
                id="logo",
                family="graphic",
                text=None,
                sufficiency="insufficient",
                identity_verifiable=False,
                overlaps=["r1"],
                z=2,
            ),
        )
    )
    assert [r.id for r in evidence.regions] == ["r1", "logo"]
    assert evidence.regions[1] == EvidenceRegion(
        id="logo",
        bbox=(10, 10, 100, 40),
        family="graphic",
        confidence=0.9,
        sufficiency="insufficient",
        boundary_complete=True,
        occluded=False,
        identity_verifiable=False,
        overlaps=("r1",),
        z=2,
    )


@pytest.mark.parametrize("decision", ["prompt", "realization", "output", "il", "reason"])
def test_evidence_refuses_a_decision_riding_along(decision: str) -> None:
    with pytest.raises(ValueError, match="not observations"):
        ManualEvidence.from_json(_evidence(_region(**{decision: "anything"})))
    with pytest.raises(ValueError, match="not observations"):
        ManualEvidence.from_json(_evidence(**{decision: "anything"}))


@pytest.mark.parametrize(
    ("doc", "said"),
    [
        (_evidence(schema="omniweave.out-manual-evidence/2"), "schema"),
        (_evidence(_region(bbox=[1900, 0, 100, 10])), "leaves the frame"),
        (_evidence(_region(bbox=[0, 0, 0, 10])), "is not a box"),
        (_evidence(_region(bbox=[-1, 0, 5, 10])), "is not a box"),
        (_evidence(_region(), _region()), "ids repeat"),
        (_evidence(_region(overlaps=["ghost"])), "unknown regions"),
        (_evidence(_region(overlaps=["r1"])), "overlaps itself"),
        (_evidence(_region(confidence=1.5)), "not in"),
        (_evidence(_region(family="chart")), "family"),
        (_evidence(_region(sufficiency="fine")), "sufficiency"),
        (_evidence(_region(id="r 1")), "stable token"),
        (_evidence(sha256="AB" * 32), "64 lower-case hex"),
        (_evidence(width=0), "no pixels"),
    ],
)
def test_evidence_refuses_what_cannot_have_been_observed(doc: dict[str, Any], said: str) -> None:
    with pytest.raises(ValueError, match=said):
        ManualEvidence.from_json(doc)


@pytest.mark.parametrize(
    ("doc", "error", "said"),
    [
        ({k: v for k, v in _evidence().items() if k != "width"}, ValueError, "missing"),
        (
            _evidence(regions=[{k: v for k, v in _region().items() if k != "occluded"}]),
            ValueError,
            "missing",
        ),
        (_evidence(regions={}), TypeError, "not a list"),
        (_evidence(regions=["r1"]), TypeError, "not an object"),
        (["not", "a", "mapping"], TypeError, "not an object"),
    ],
)
def test_evidence_is_exactly_its_shape(doc: Any, error: type[Exception], said: str) -> None:
    with pytest.raises(error, match=said):
        ManualEvidence.from_json(doc)
