"""The retained IL bundle: frozen into CAS at compile time, fetched back for an edit. **D752.**

09-generation.md section 3.1, decision 2: *"The bundle is frozen into CAS at compile time and
pointed at by `artifact.il_store_ref` (the bundle) and `artifact_unit.il_sha256` (per unit).
Editing an omniweave-built artefact fetches the retained IL. This is retention, not
reconstruction."* 16-roadmap.md's W9.7 names it beside the tables. `freeze()` is the compile's
half and runs before the seal, which stores what it returns. `fetch()` is the edit's half.

## Rulings

1. **One CAS object per IL file, plus one for the bundle whose bytes are `il_digest`'s
   preimage.** 09 section 4.5 defines `il_digest` as the sha256 of one
   `name 0x00 hex(sha256(bytes)) 0x0A` line per file, in basename order. The manifest is exactly
   those bytes, so its CAS digest is `il_digest`, `il_store_ref` is `cas://` plus `il_digest`, and
   a fetched bundle verifies itself. There is no second format and no second digest.
2. **Every file `il_digest` covers is retained**, `il.toml` and `template.nsig` among them, because
   an edit re-loads the bundle from them. A dot-file is not IL (D737 ruling 8) and is not retained.
3. **The bytes retained are the bytes the gate passed.** `freeze()` streams each file into CAS,
   hashing as it goes, and compares the digest with the bundle's row. A difference means the IL
   moved between the check and the compile, so the compile refuses with `OW_TARGET_IL_MOVED`
   (`OW-T-512`, appended) rather than seal bytes no gate saw. A file the row already records
   past `MAX_IL_FILE_BYTES` is refused before any byte is copied.
4. **A unit's `il_sha256` is its file's digest.** `Retained.units` maps each unit id to
   `sha256:` plus the hex of the file `OutUnit.il_path` names: the per-unit retained IL that
   `artifact_unit.il_sha256` stores.
5. **A fetch verifies everything it writes.**
   - The manifest is read bounded by `MAX_IL_FILE_BYTES`; 10,002 lines of at most 321 bytes is
     3.2 MB.
   - The manifest is hashed against the ref.
   - Each line is parsed strictly: a basename, 64 hex, in strictly ascending order.
   - Each file is streamed out of CAS into the destination, hashed and bounded as it goes.

   Any difference removes the destination and raises `StoreError`, with `ow store fsck --cas` as
   the fix.
6. **A fetch writes into a new directory only.** An existing destination is refused, so a
   retained bundle is never merged into a working one.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, BinaryIO, Final

from omniweave_core.blobs import format_ref, parse_ref
from omniweave_core.errors import StoreError, TargetError, UsageError
from omniweave_core.limits import MAX_IL_FILE_BYTES
from omniweave_core.out.job import ILFile, read_il_files

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_core.blobs import BlobStore
    from omniweave_core.out.job import ILBundle

__all__ = ["Retained", "fetch", "freeze", "manifest"]

_CHUNK: Final = 1 << 16
_FIX_FSCK: Final = "ow store fsck --cas"
_HEX64: Final = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class Retained:
    """What `freeze()` froze: the bundle's reference and each unit's digest (rulings 1 and 4)."""

    il_store_ref: str
    il_digest: str
    units: Mapping[str, str]
    """Unit id to `sha256:<hex>` of its IL file, for `artifact_unit.il_sha256`."""


def manifest(files: Sequence[ILFile]) -> bytes:
    """Ruling 1: `il_digest`'s preimage, the bytes of the bundle's own CAS object."""
    return b"".join(
        f.name.encode("utf-8") + b"\x00" + f.sha256.encode("ascii") + b"\n"
        for f in sorted(files, key=lambda f: f.name)
    )


def freeze(bundle: ILBundle, blobs: BlobStore) -> Retained:
    """Rulings 1-4: every file into CAS as the gate saw it, then the manifest."""
    root = Path(bundle.root)
    over = [f.name for f in bundle.files if f.byte_len > MAX_IL_FILE_BYTES]
    if over:
        raise TargetError(
            f"il/{', il/'.join(over)} past MAX_IL_FILE_BYTES ({MAX_IL_FILE_BYTES})",
            symbol="OW_TARGET_IL_MOVED",
            fix="ow out check --stage final",
        )
    for file in bundle.files:
        with (root / file.name).open("rb") as handle:
            stored = blobs.put(handle).hex()
        if stored != file.sha256:
            raise TargetError(
                f"il/{file.name} changed after the gate passed it: the gate saw "
                f"{file.sha256[:12]}, the compile read {stored[:12]}",
                symbol="OW_TARGET_IL_MOVED",
                fix="ow out check --stage final",
            )
    digest = blobs.put(io.BytesIO(manifest(bundle.files)))
    if "sha256:" + digest.hex() != bundle.il_digest:  # pragma: no cover -- ruling 1's identity.
        raise StoreError("the manifest is not il_digest's preimage", fix="report this as a bug")
    by_name = {f.name: f for f in bundle.files}
    return Retained(
        il_store_ref=format_ref(digest),
        il_digest=bundle.il_digest,
        units={
            u.id: "sha256:" + by_name[PurePosixPath(u.il_path).name].sha256 for u in bundle.units
        },
    )


def fetch(il_store_ref: str, blobs: BlobStore, dest: Path) -> tuple[ILFile, ...]:
    """Rulings 5 and 6: the retained bundle, verified, written into a new `dest`."""
    want = parse_ref(il_store_ref)
    if dest.exists():
        raise UsageError(
            f"{dest} exists; a retained bundle is fetched into a new directory",
            fix=f"remove {dest}, or name another directory",
        )
    with blobs.open(want) as handle:
        body = _take(handle, MAX_IL_FILE_BYTES, il_store_ref)
    if hashlib.sha256(body).digest() != want:
        raise _corrupt(il_store_ref, "the manifest does not hash to its reference")
    rows = _rows(body, il_store_ref)
    dest.mkdir(parents=True)
    try:
        for name, hexdigest in rows:
            _copy(blobs, hexdigest, dest / name, il_store_ref)
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    return read_il_files(dest)


def _rows(body: bytes, ref: str) -> list[tuple[str, str]]:
    if not body or not body.endswith(b"\n"):
        raise _corrupt(ref, "the manifest is empty or does not end in a newline")
    rows: list[tuple[str, str]] = []
    for line in body[:-1].split(b"\n"):
        raw_name, sep, raw_hex = line.partition(b"\x00")
        try:
            name = raw_name.decode("utf-8")
            hexdigest = raw_hex.decode("ascii")
        except UnicodeDecodeError:
            raise _corrupt(ref, f"manifest line {line[:40]!r} is not text") from None
        if not sep or not _basename(name) or _HEX64.fullmatch(hexdigest) is None:
            raise _corrupt(ref, f"manifest line {line[:80]!r} is not name NUL sha256")
        if rows and name <= rows[-1][0]:
            raise _corrupt(ref, f"manifest names {name!r} out of order or twice")
        rows.append((name, hexdigest))
    return rows


def _basename(name: str) -> bool:
    return bool(name) and not name.startswith(".") and "/" not in name and "\\" not in name


def _copy(blobs: BlobStore, hexdigest: str, target: Path, ref: str) -> None:
    digest = hashlib.sha256()
    size = 0
    with blobs.open(hexdigest) as source, target.open("xb") as sink:
        while chunk := source.read(_CHUNK):
            size += len(chunk)
            if size > MAX_IL_FILE_BYTES:
                raise _corrupt(ref, f"{target.name} runs past MAX_IL_FILE_BYTES")
            digest.update(chunk)
            sink.write(chunk)
    if digest.hexdigest() != hexdigest:
        raise _corrupt(ref, f"{target.name}'s CAS object does not hash to its name")


def _take(handle: BinaryIO, limit: int, ref: str) -> bytes:
    body = handle.read(limit + 1)
    if len(body) > limit:
        raise _corrupt(ref, f"the manifest runs past {limit} bytes")
    return body


def _corrupt(ref: str, why: str) -> StoreError:
    return StoreError(f"retained IL bundle {ref}: {why}", fix=_FIX_FSCK)
