"""`omniweave_core.drivers.digest`: `dist_sha256` over `RECORD`, one from a wheel and an install.

D894, D576's first ruling (2026-10-20). Every row rule is pinned, the two sides are shown to agree
over a synthetic wheel and its synthetic install, and the catalog is shown to read only the
manifest's distributions.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest
from omniweave_core import discovery
from omniweave_core.drivers import digest
from omniweave_core.drivers.catalog import FirstPartyManifest, FirstPartyRow


def _hash(data: bytes) -> str:
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")


FILES = {
    "omniweave_demo/__init__.py": b"x = 1\n",
    "omniweave_demo/driver.toml": b"[driver]\n",
    "omniweave_demo-1.0.dist-info/METADATA": b"Name: omniweave-demo\n",
    "omniweave_demo-1.0.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
    "omniweave_demo-1.0.dist-info/entry_points.txt": b"[omniweave.drivers]\n",
    "omniweave_demo-1.0.dist-info/licenses/LICENSE": b"MIT\n",
}


def _record(files: dict[str, bytes], extra: str = "") -> str:
    rows = "".join(f"{path},{_hash(data)},{len(data)}\n" for path, data in files.items())
    return rows + "omniweave_demo-1.0.dist-info/RECORD,,\n" + extra


def test_every_kept_row_moves_the_digest_and_every_dropped_one_does_not() -> None:
    base = digest.record_digest(_record(FILES))
    assert base.startswith("sha256:")
    for path, data in FILES.items():
        changed = {**FILES, path: data + b"#"}
        assert digest.record_digest(_record(changed)) != base, path
    dropped = (
        "omniweave_demo/__pycache__/__init__.cpython-312.pyc,sha256=AAAA,10\n"
        "omniweave_demo/stale.pyc,sha256=BBBB,10\n"
        "../../Scripts/ow-demo.exe,sha256=CCCC,10\n"
        "omniweave_demo-1.0.data/scripts/x,sha256=DDDD,10\n"
        "omniweave_demo-1.0.dist-info/INSTALLER,sha256=EEEE,3\n"
        "omniweave_demo-1.0.dist-info/REQUESTED,sha256=FFFF,0\n"
        "omniweave_demo-1.0.dist-info/direct_url.json,sha256=GGGG,40\n"
        "omniweave_demo/unhashed.py,,\n"
    )
    assert digest.record_digest(_record(FILES, dropped)) == base


def test_row_order_and_windows_separators_do_not_move_the_digest() -> None:
    rows = _record(FILES).splitlines(keepends=True)
    shuffled = "".join(reversed(rows)).replace("omniweave_demo/", "omniweave_demo\\")
    assert digest.record_digest(shuffled) == digest.record_digest(_record(FILES))


def _wheel(tmp_path: Path) -> Path:
    path = tmp_path / "omniweave_demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in FILES.items():
            archive.writestr(name, data)
        archive.writestr("omniweave_demo-1.0.dist-info/RECORD", _record(FILES))
    return path


def _install(site: Path, *, editable: bool = False) -> metadata.Distribution:
    """What an installer leaves: the files, its own additions, and a RECORD naming them all."""
    for name, data in FILES.items():
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    info = site / "omniweave_demo-1.0.dist-info"
    (info / "INSTALLER").write_text("uv\n", encoding="utf-8")
    added = "omniweave_demo-1.0.dist-info/INSTALLER,sha256=x,3\n../../bin/ow-demo,sha256=y,9\n"
    if editable:
        url = {"url": "file:///src", "dir_info": {"editable": True}}
        (info / "direct_url.json").write_text(json.dumps(url), encoding="utf-8")
    (info / "RECORD").write_text(_record(FILES, added), encoding="utf-8")
    return metadata.PathDistribution(info)


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> metadata.Distribution:
    dist = _install(tmp_path / "site")
    monkeypatch.setattr(digest.metadata, "distribution", lambda _name: dist)
    return dist


def test_the_wheel_and_its_install_have_one_digest(
    tmp_path: Path, installed: metadata.Distribution
) -> None:
    del installed
    assert digest.wheel_digest(_wheel(tmp_path)) == digest.installed_digest("omniweave-demo")


def test_an_editable_install_has_no_digest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = _install(tmp_path / "site", editable=True)
    monkeypatch.setattr(digest.metadata, "distribution", lambda _name: dist)
    assert digest.installed_digest("omniweave-demo") == ""


def test_an_absent_distribution_has_no_digest() -> None:
    assert digest.installed_digest("omniweave-no-such-distribution") == ""


def test_verify_names_a_changed_file_and_a_missing_one(
    tmp_path: Path, installed: metadata.Distribution
) -> None:
    del installed
    assert digest.verify_installed("omniweave-demo") == ()
    site = tmp_path / "site"
    (site / "omniweave_demo/__init__.py").write_bytes(b"x = 2\n")
    (site / "omniweave_demo/driver.toml").unlink()
    assert digest.verify_installed("omniweave-demo") == (
        "omniweave_demo/__init__.py: changed",
        "omniweave_demo/driver.toml: missing",
    )


def test_a_wheel_without_exactly_one_record_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("x.py", b"")
    with pytest.raises(ValueError, match=r"0 \.dist-info/RECORD"):
        digest.wheel_digest(path)


def _found(origin: str, dist_name: str) -> SimpleNamespace:
    return SimpleNamespace(source=SimpleNamespace(origin=origin, dist_name=dist_name))


def test_the_catalog_reads_only_the_manifests_distributions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[str] = []
    monkeypatch.setattr(digest, "installed_digest", lambda name: asked.append(name) or "sha256:x")
    row = FirstPartyRow(name="omniweave-pdf", version="1", dist_sha256="sha256:" + "0" * 64)
    office = FirstPartyRow(name="omniweave-office", version="1", dist_sha256=row.dist_sha256)
    manifest = FirstPartyManifest(
        schema=1, release="1", dists={"omniweave-pdf": row, "omniweave-office": office}
    )
    found = [
        _found("entry_point", "omniweave-pdf"),
        _found("entry_point", "omniweave-pdf"),
        _found("entry_point", "someone-elses-driver"),
        _found("driver_path", "omniweave-office"),
    ]
    assert discovery._manifest_digests(found, manifest) == {"omniweave-pdf": "sha256:x"}  # type: ignore[arg-type]
    assert asked == ["omniweave-pdf"], "one RECORD read per manifest distribution"
    assert discovery._manifest_digests(found, None) == {}  # type: ignore[arg-type]
