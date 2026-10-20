"""`dist_sha256`: one distribution's digest, the same from its wheel and from its install. D894.

04-driver-system.md section 4.2 computes `first_party` when a distribution's `dist_sha256` matches
the release manifest's (11-repo-layout.md section 7.2), and section 5.5 has `ow drivers verify`
recompute it *"from what is installed"*. The wheel's own sha256 cannot be that: an installed
distribution keeps no copy of the archive it came from. **A user ruling of 2026-10-20 (D576,
ruling 1)** fixes the digest as one both sides can compute: a sha256 over the distribution's own
`RECORD` rows.

## Rulings

1. **The rows are `path,hash` for the files the wheel itself carries.** A wheel's `RECORD` lists
   every member with its `sha256=` hash, and an installer copies those members unchanged and
   records the same hashes. The digest is sha256 over the kept rows, sorted, one
   `path,hash\\n` line each, printed `sha256:<hex>` as `omniweave.lock` and the manifest print it.
2. **What an installer adds is not the distribution's, and is dropped:**
   - a row with no hash (`RECORD` itself);
   - anything under `__pycache__/` or ending `.pyc` (bytecode an installer compiles);
   - a path leaving the install root (`../`: console scripts an installer generates);
   - `<name>.data/` rows on the wheel side, which an installer relocates;
   - every `*.dist-info/` row but `METADATA`, `WHEEL`, `entry_points.txt` and `licenses/`
     (installers write `INSTALLER`, `REQUESTED`, `direct_url.json` and their own caches there).
3. **Reading `RECORD` is not hashing the files.** It is one small file per distribution, which
   is what keeps it affordable when a catalog is built. Tamper-evidence over the installed bytes
   is `ow drivers verify`'s, which re-hashes each kept file against its row
   (`verify_installed()`).
4. **An editable or absent distribution has no digest** (`""`). A workspace checkout computes
   `unpinned` with the `pin` degradation, as 11-repo-layout.md section 7.2 says it must.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import zipfile
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "KEPT_DIST_INFO",
    "installed_digest",
    "record_digest",
    "verify_installed",
    "wheel_digest",
]

KEPT_DIST_INFO: Final = frozenset({"METADATA", "WHEEL", "entry_points.txt"})
"""Ruling 2: the `*.dist-info/` files the wheel carries and no installer rewrites."""
_LICENSES: Final = "licenses"
_TOP: Final = 2
"""`<name>.dist-info/<file>`: a path two parts deep is one of the directory's own files."""
_PREFIX: Final = "sha256:"


def _kept(path: str, digest: str) -> bool:
    """Ruling 2, for one `RECORD` row."""
    if not digest:
        return False
    parts = PurePosixPath(path).parts
    if not parts or parts[0] == ".." or "__pycache__" in parts or path.endswith(".pyc"):
        return False
    if parts[0].endswith(".data"):
        return False
    if parts[0].endswith(".dist-info"):
        return (len(parts) == _TOP and parts[1] in KEPT_DIST_INFO) or (
            len(parts) > _TOP and parts[1] == _LICENSES
        )
    return True


def _rows(record: str) -> list[tuple[str, str]]:
    """Every `(path, hash)` of a `RECORD`, paths in `/` form."""
    out = []
    for row in csv.reader(io.StringIO(record)):
        if len(row) >= 2:  # noqa: PLR2004 -- path, hash[, size]
            out.append((row[0].replace("\\", "/"), row[1]))
    return out


def record_digest(record: str) -> str:
    """Ruling 1: `sha256:` over the kept `path,hash` rows of one `RECORD`, sorted."""
    lines = sorted(f"{path},{digest}\n" for path, digest in _rows(record) if _kept(path, digest))
    return _PREFIX + hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def wheel_digest(wheel: Path) -> str:
    """The digest of a built wheel, from the `RECORD` inside it (`tools/gen_first_party.py`)."""
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.endswith(".dist-info/RECORD")]
        if len(names) != 1:
            msg = f"{wheel.name} holds {len(names)} .dist-info/RECORD files, not 1"
            raise ValueError(msg)
        return record_digest(archive.read(names[0]).decode("utf-8"))


def installed_digest(distribution: str) -> str:
    """Ruling 4: the installed distribution's digest, or `""` when it has none to give."""
    try:
        dist = metadata.distribution(distribution)
    except metadata.PackageNotFoundError:
        return ""
    if _editable(dist.read_text("direct_url.json")):
        return ""
    record = dist.read_text("RECORD")
    return record_digest(record) if record else ""


def _editable(direct_url: str | None) -> bool:
    """PEP 610: an editable install says so in `direct_url.json`'s `dir_info`."""
    if not direct_url:
        return False
    try:
        info = json.loads(direct_url)
    except ValueError:
        return False
    dir_info = info.get("dir_info") if isinstance(info, dict) else None
    return isinstance(dir_info, dict) and dir_info.get("editable") is True


def verify_installed(distribution: str) -> tuple[str, ...]:
    """Ruling 3: each kept file whose bytes no longer match its `RECORD` row, or is gone."""
    dist = metadata.distribution(distribution)
    record = dist.read_text("RECORD") or ""
    root = Path(str(dist.locate_file("")))
    return tuple(_drifted(root, _rows(record)))


def _drifted(root: Path, rows: Iterable[tuple[str, str]]) -> list[str]:
    out = []
    for path, digest in rows:
        if not _kept(path, digest):
            continue
        algorithm, _, want = digest.partition("=")
        target = root / path
        if not target.is_file():
            out.append(f"{path}: missing")
            continue
        got = base64.urlsafe_b64encode(hashlib.new(algorithm, target.read_bytes()).digest())
        if got.decode("ascii").rstrip("=") != want.rstrip("="):
            out.append(f"{path}: changed")
    return out
