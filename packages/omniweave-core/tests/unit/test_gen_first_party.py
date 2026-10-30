"""`tools/gen_first_party.py`: the first-party release manifest, from `dist/`. D895.

11-repo-layout.md section 7.2. Synthetic wheels stand in for `dist/`: each carries the `METADATA`
and `RECORD` the generator reads, so every ruling is checked without a build. The real build is
`ci.yml`'s step 2, which runs this tool over pass one's 26 non-core files.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import tomllib
import zipfile
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from omniweave_core.drivers.catalog import read_first_party
from omniweave_core.drivers.digest import wheel_digest

REPO = Path(__file__).resolve().parents[4]

CORE_VERSION: Final[str] = tomllib.loads(
    (REPO / "packages" / "omniweave-core" / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
"""`RELEASE`, read from the one site that defines it (D1022)."""


def _load() -> ModuleType:
    path = REPO / "tools" / "gen_first_party.py"
    spec = importlib.util.spec_from_file_location("_owtool_gen_first_party", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GEN = _load()


def _wheel(dist: Path, name: str, version: str = "0.1.0", body: bytes = b"x = 1\n") -> Path:
    stem = name.replace("-", "_")
    path = dist / f"{stem}-{version}-py3-none-any.whl"
    info = f"{stem}-{version}.dist-info"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{stem}/__init__.py", body)
        archive.writestr(
            f"{info}/METADATA", f"Metadata-Version: 2.4\nName: {name}\nVersion: {version}\n"
        )
        digest = hashlib.sha256(body).hexdigest()
        archive.writestr(f"{info}/RECORD", f"{stem}/__init__.py,sha256={digest},{len(body)}\n")
    return path


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """One wheel per workspace member, core included, as pass one leaves them."""
    out = tmp_path / "dist"
    out.mkdir()
    for name in GEN.members():
        _wheel(out, name, version="1.0.0" if name == "omniweave-ports" else "0.1.0")
    return out


def test_thirteen_rows_core_absent_every_digest_the_wheels(dist: Path, tmp_path: Path) -> None:
    out = tmp_path / "first_party.toml"
    assert GEN.main(["--dist", str(dist), "--out", str(out)]) == 0
    manifest = read_first_party(out)
    assert manifest is not None
    assert len(manifest.dists) == 13 == len(GEN.members()) - 1
    assert "omniweave-langchain" not in GEN.members(), "an attachment is not first party (D909)"
    assert GEN.CORE not in manifest.dists
    for wheel in dist.glob("*.whl"):
        name, version = GEN.wheel_identity(wheel)
        if name != GEN.CORE:
            row = manifest.dists[name]
            assert (row.version, row.dist_sha256) == (version, wheel_digest(wheel)), name
    assert manifest.release == CORE_VERSION, (
        "core's version is RELEASE, and it is READ from the tree rather than from the"
        " synthetic wheels: this fixture builds them at 0.1.0 while the tree is at"
        f" {CORE_VERSION}, so this also says where gen_first_party takes `release` from"
    )


def test_vendored_follows_g12s_register(dist: Path, tmp_path: Path) -> None:
    out = tmp_path / "first_party.toml"
    GEN.main(["--dist", str(dist), "--out", str(out)])
    manifest = read_first_party(out)
    assert manifest is not None
    assert {name for name, row in manifest.dists.items() if row.vendored} == {"omniweave-office"}
    assert GEN.vendored() == {"omniweave-office"}


def test_a_missing_wheel_writes_nothing_and_names_it(dist: Path, tmp_path: Path) -> None:
    next(dist.glob("omniweave_pdf-*.whl")).unlink()
    out = tmp_path / "first_party.toml"
    assert GEN.main(["--dist", str(dist), "--out", str(out)]) == 1
    assert not out.exists()


def test_a_stranger_or_a_second_wheel_is_a_finding(dist: Path) -> None:
    _wheel(dist, "someone-elses-package")
    _wheel(dist, "omniweave-pdf", version="0.1.1")
    _text, findings = GEN.build(dist, None)
    assert any("someone-elses-package is not a workspace member" in f for f in findings)
    assert any("a second wheel for omniweave-pdf" in f for f in findings)


def test_check_passes_the_written_manifest_and_fails_a_stale_one(
    dist: Path, tmp_path: Path
) -> None:
    out = tmp_path / "first_party.toml"
    GEN.main(["--dist", str(dist), "--out", str(out)])
    assert GEN.main(["--dist", str(dist), "--out", str(out), "--check"]) == 0
    next(dist.glob("omniweave_pdf-*.whl")).unlink()
    _wheel(dist, "omniweave-pdf", body=b"x = 2\n")
    assert GEN.main(["--dist", str(dist), "--out", str(out), "--check"]) == 1


def test_release_can_be_given(dist: Path, tmp_path: Path) -> None:
    out = tmp_path / "first_party.toml"
    GEN.main(["--dist", str(dist), "--out", str(out), "--release", "0.4.2"])
    manifest = read_first_party(out)
    assert manifest is not None
    assert manifest.release == "0.4.2"


def test_no_dist_did_not_run(tmp_path: Path) -> None:
    assert GEN.main(["--dist", str(tmp_path / "absent")]) == 2


def test_the_default_destination_is_cores_gitignored_package_data() -> None:
    assert GEN.OUT == REPO / "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml"
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml" in ignore
