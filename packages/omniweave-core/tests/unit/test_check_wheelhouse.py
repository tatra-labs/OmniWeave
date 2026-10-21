"""`tools/check_wheelhouse.py`: section 2.4's three install profiles, offline. D897.

The profiles themselves are `ci.yml`'s build step 4 over the wheels release will publish, and take
minutes. These tests hold the harness's own judgements, each over the text an installer or `ow`
prints, so a judgement that drifts fails here rather than on a release.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "check_wheelhouse.py"
    spec = importlib.util.spec_from_file_location("_owtool_check_wheelhouse", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HARNESS = _load()
REFUSAL = (
    "ow: OW-D-009: no driver for .pdf is installed, so 1 unit(s) stopped at identify "
    "(first: file:///docs/report.pdf); omniweave-pdf reads them\n"
    "  fix: pip install omniweave-pdf   # then: ow ingest --corpus docs\n"
)


def _importtime(*names: str) -> str:
    rows = ["import time: self [us] | cumulative | imported package"]
    rows += [f"import time:       100 |        100 | {name}" for name in names]
    return "\n".join(rows)


def test_the_declared_refusal_has_nothing_wrong_with_it() -> None:
    assert HARNESS.refusal(64, REFUSAL) == []


def test_each_way_a_refusal_can_be_wrong_is_named() -> None:
    assert HARNESS.refusal(0, REFUSAL) == [
        "ow add exited 0 on a PDF with no PDF driver installed, not the declared 64 "
        "(CapabilityMissing, D888)"
    ]
    assert HARNESS.refusal(1, REFUSAL)[0].startswith("ow add exited 1")
    unnamed = REFUSAL.replace("pip install omniweave-pdf", "install a PDF driver")
    assert HARNESS.refusal(64, unnamed) == ["the refusal does not name `pip install omniweave-pdf`"]
    other_code = REFUSAL.replace("OW-D-009", "OW-D-010")
    assert HARNESS.refusal(64, other_code) == [
        "the refusal does not carry its declared code, OW-D-009"
    ]
    assert HARNESS.refusal(64, REFUSAL + "Traceback (most recent call last):\n") == [
        "the refusal printed a traceback"
    ]


def test_third_party_is_neither_stdlib_nor_ours_nor_a_site_hook() -> None:
    stderr = _importtime(
        "os",
        "_io",
        "encodings.utf_8",
        "omniweave_core",
        "omniweave_core.errors",
        "_virtualenv",
        "sitecustomize",
        "pydantic",
        "pydantic.main",
        "lxml.etree",
    )
    assert HARNESS.third_party(stderr) == ["lxml", "pydantic"]
    assert HARNESS.third_party(_importtime("os", "omniweave_core")) == []


def test_the_record_union_counts_each_path_once(tmp_path: Path) -> None:
    for dist, rows in {
        "a-1.dist-info": "a/x.py,sha256=1,100\na/y.py,sha256=2,50\na-1.dist-info/RECORD,,\n",
        "b-1.dist-info": "a/x.py,sha256=1,100\nb/z.py,sha256=3,7\n",
    }.items():
        (tmp_path / dist).mkdir()
        (tmp_path / dist / "RECORD").write_text(rows, encoding="utf-8")
    assert HARNESS._record_bytes(tmp_path) == 157


def test_the_bounded_set_is_every_member_but_vision() -> None:
    members = HARNESS.members()
    assert len(members) == 14
    assert "omniweave-langchain" not in members, "an attachment is in no profile (D909)"
    assert set(HARNESS.bounded()) == set(members) - {"omniweave-vision"}


def test_no_wheels_is_did_not_run(tmp_path: Path) -> None:
    assert HARNESS.main(["--dist", str(tmp_path)]) == 2
