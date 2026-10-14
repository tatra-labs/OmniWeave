"""The only ZIP-for-write: `write_opc()`, `part_digest()` and the package checks. **D747.**

09-generation.md section 5.3 (package validation: the four hard preconditions), section 6 (`part`
determinism) and section 14.4 (`write_opc()` builds in memory and returns bytes); charter OUT13 and
OUT15. `omniweave-no-zipfile-write-outside-opc` allows a `zipfile.ZipFile(..., "w")` here and in
`archive/owdoc.py` and nowhere else, so member order, timestamps and attributes are decided once.

## Rulings (the ledger's D747)

1. **The member order is canonical, never the caller's**: `[Content_Types].xml`, then
   `_rels/.rels`, then every other part sorted by name. The charter's `order` argument would let two
   targets, or one target twice, write one package two ways; a `part` digest is order-free, but the
   bytes are not, and `byte` determinism is recorded.
2. **Every member is built from `ZipInfo(name)` with each clock- and platform-dependent field
   pinned**, as `archive/owdoc.py` pins them: `date_time` the 1980 epoch, `create_system` 3,
   `external_attr` rw-r--r--, `ZIP_DEFLATED` at one `compresslevel`. `ZipFile.writestr()` with a
   bare name would stamp the local clock.
3. **A part name is an OPC part name**: relative, `/`-separated, no empty, `.` or `..` segment, no
   backslash, and unique case-insensitively, as OPC compares them. `[Content_Types].xml` and
   `_rels/.rels` are required. A violation raises `ValueError`, a target's bug and not a finding.
4. **`part_digest()` is 09's framing over parts, not bytes**: per part sorted by name,
   `name 0x00 hex(sha256(payload)) 0x0A`, hashed. It is the portable floor: equal parts are an equal
   digest whatever zlib did to the container.
5. **`check_package()` is section 5.3's four preconditions over the bytes produced, and raises**:
   a member that does not decompress is `OW_TARGET_PACKAGE_CORRUPT` naming it, a relationship whose
   internal target is no member is `OW_TARGET_DANGLING_REL`, a part no `Default` or `Override` types
   is `OW_TARGET_CONTENT_TYPE_GAP`, and the unit count is the caller's to compare
   (`OW_TARGET_UNIT_COUNT_MISMATCH`, printing both numbers). External targets
   (`TargetMode="External"`) are not members and are not checked.
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile
import zlib
from collections.abc import Callable, Mapping
from typing import Final, Never
from xml.parsers import expat

from omniweave_core.errors import TargetError

__all__ = [
    "CANONICAL_DATE",
    "CONTENT_TYPES",
    "ROOT_RELS",
    "check_package",
    "check_unit_count",
    "part_digest",
    "write_opc",
]

CANONICAL_DATE: Final = (1980, 1, 1, 0, 0, 0)
"""The ZIP epoch: the earliest date the format can hold, and the same on every machine."""
CONTENT_TYPES: Final = "[Content_Types].xml"
ROOT_RELS: Final = "_rels/.rels"
_CREATE_SYSTEM: Final = 3
_MEMBER_MODE: Final = 0o644 << 16
_COMPRESSLEVEL: Final = 6
_PKG_RELS: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
_PKG_TYPES: Final = "http://schemas.openxmlformats.org/package/2006/content-types"


def write_opc(members: Mapping[str, bytes], *, compresslevel: int = _COMPRESSLEVEL) -> bytes:
    """Rulings 1-3: the whole package, in memory, as bytes. Nothing is half-written on failure."""
    names = _ordered(members)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=compresslevel) as zf:
        for name in names:
            info = zipfile.ZipInfo(filename=name, date_time=CANONICAL_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = _CREATE_SYSTEM
            info.external_attr = _MEMBER_MODE
            zf.writestr(
                info, members[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=compresslevel
            )
    return buffer.getvalue()


def part_digest(members: Mapping[str, bytes]) -> str:
    """Ruling 4: `sha256:` over the parts, not the container."""
    digest = hashlib.sha256()
    for name in sorted(members):
        digest.update(
            name.encode("utf-8")
            + b"\x00"
            + hashlib.sha256(members[name]).hexdigest().encode()
            + b"\n"
        )
    return "sha256:" + digest.hexdigest()


def _ordered(members: Mapping[str, bytes]) -> list[str]:
    seen: dict[str, str] = {}
    for name in members:
        _check_name(name)
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"part names {seen[folded]!r} and {name!r} are one name to OPC")
        seen[folded] = name
    for required in (CONTENT_TYPES, ROOT_RELS):
        if required not in members:
            raise ValueError(f"a package needs {required}")
    rest = sorted(n for n in members if n not in {CONTENT_TYPES, ROOT_RELS})
    return [CONTENT_TYPES, ROOT_RELS, *rest]


def _check_name(name: str) -> None:
    """Ruling 3. An empty name and a leading `/` are both an empty segment."""
    if "\\" in name or any(s in {"", ".", ".."} for s in name.split("/")):
        raise ValueError(f"{name!r} is not an OPC part name")


# ---------------------------------------------------------------------------
# Package validation (09 section 5.3), ruling 5
# ---------------------------------------------------------------------------


def check_package(data: bytes) -> dict[str, bytes]:
    """The members, every one decompressed, every relationship and content type accounted for."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        _raise(
            "OW_TARGET_PACKAGE_CORRUPT",
            f"the package is not a ZIP: {exc}",
            "ow out verify <artefact>",
        )
    members: dict[str, bytes] = {}
    with zf:
        for info in zf.infolist():
            try:
                members[info.filename] = zf.read(info)
            except (zipfile.BadZipFile, zlib.error, OSError, EOFError, ValueError) as exc:
                _raise(
                    "OW_TARGET_PACKAGE_CORRUPT",
                    f"member {info.filename} does not decompress: {exc}",
                    "ow out verify <artefact>",
                )
    _check_rels(members)
    _check_types(members)
    return members


def check_unit_count(produced: int, planned: int) -> None:
    """`OW_TARGET_UNIT_COUNT_MISMATCH`, printing both numbers (09 section 5.3)."""
    if produced != planned:
        _raise(
            "OW_TARGET_UNIT_COUNT_MISMATCH",
            f"the package holds {produced} units and the plan commissioned {planned}",
            "ow out check --target <target> --stage final",
        )


def _check_rels(members: Mapping[str, bytes]) -> None:
    for name, payload in sorted(members.items()):
        if not name.endswith(".rels"):
            continue
        source_dir = posixpath.dirname(posixpath.dirname(name))
        for target in _rel_targets(name, payload):
            # `join` drops the base for an absolute `/ppt/...` target, so both forms land here.
            resolved = posixpath.normpath(posixpath.join(source_dir, target)).lstrip("/")
            if resolved not in members:
                _raise(
                    "OW_TARGET_DANGLING_REL",
                    f"{name} points at {target}, which is not a member",
                    "ow out verify <artefact>",
                )


def _rel_targets(name: str, payload: bytes) -> list[str]:
    targets: list[str] = []

    def start(tag: str, attrs: dict[str, str]) -> None:
        if tag == f"{_PKG_RELS} Relationship" and attrs.get("TargetMode") != "External":
            targets.append(attrs.get("Target", ""))

    _walk_xml(name, payload, start)
    return targets


def _check_types(members: Mapping[str, bytes]) -> None:
    defaults: set[str] = set()
    overrides: set[str] = set()

    def start(tag: str, attrs: dict[str, str]) -> None:
        if tag == f"{_PKG_TYPES} Default":
            defaults.add(attrs.get("Extension", "").casefold())
        elif tag == f"{_PKG_TYPES} Override":
            overrides.add(attrs.get("PartName", "").lstrip("/").casefold())

    _walk_xml(CONTENT_TYPES, members.get(CONTENT_TYPES, b""), start)
    for name in sorted(members):
        if name == CONTENT_TYPES:
            continue
        segment = name.rsplit("/", 1)[-1]
        # OPC's extension follows the segment's last dot: `.rels` is extension `rels`, though
        # `posixpath.splitext` reads it as a hidden file with none.
        extension = segment.rpartition(".")[2].casefold() if "." in segment else ""
        if name.casefold() not in overrides and extension not in defaults:
            _raise(
                "OW_TARGET_CONTENT_TYPE_GAP",
                f"{name} has no content type: no Override names it, no Default covers .{extension}",
                "ow out verify <artefact>",
            )


def _walk_xml(name: str, payload: bytes, start: Callable[[str, dict[str, str]], None]) -> None:
    """A strict expat walk with namespaces. A DOCTYPE or an entity is refused, as in a carrier."""
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    def refuse(*_: object) -> None:
        raise ValueError("a DOCTYPE or an entity declaration")

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.StartElementHandler = start
    try:
        parser.Parse(payload, True)
    except (expat.ExpatError, ValueError) as exc:
        _raise(
            "OW_TARGET_PACKAGE_CORRUPT",
            f"{name} is not well-formed XML: {exc}",
            "ow out verify <artefact>",
        )


def _raise(code: str, msg: str, fix: str) -> Never:
    raise TargetError(msg, symbol=code, fix=fix)
