"""The four identity recipes: one locator normaliser and three digests.

`canonical_uri()` is the ONE function that produces a `unit_uri`; `content_digest()` is the
merkle recipe every `block`/`segment` row carries; `config_digest()` and `semantic_digest()` are
the two halves of the `semantic`/`operational` config axis. Naming rows is NOT this module's
job -- `block_id`, `addr` and `cite` are L2's to mint (02-architecture.md section 2 row 4).

Specified in 05-ingest-and-routing.md section 1.2 (`canonical_uri`, all four locator kinds and
the container-child fragment), 03-document-model.md section 6.4 and charter.md section "Digests"
(`content_digest`), and 02-architecture.md sections 8.3/8.4 plus 08-runtime.md section 4.3 (the
two config digests and the axis that separates them).

The axis is in the signature rather than in a comment: `config_digest()` takes values alone and
CANNOT be given an axis map, `semantic_digest()` cannot be called without one. That is
02-architecture.md section 8.4(d) -- "an operational key entered a cache key" is a call that
does not type-check rather than a rule to remember.
"""

from __future__ import annotations

import hashlib
import os
import string
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

from omniweave_core.canonical import JsonValue, canonical, ow128, sha256_canonical

if TYPE_CHECKING:  # pragma: no cover - `omniweave_ports` carries no behaviour to import
    from omniweave_ports.ports import Locator

__all__ = ["canonical_uri", "config_digest", "content_digest", "semantic_digest"]

ConfigAxis = Literal["semantic", "operational"]

# RFC 3986 unreserved. Percent-escaping anything in this set is redundant, so a normalised URI
# never carries one: `%41` decodes to `A` and `A` stays `A`, which is what makes the normaliser
# idempotent rather than merely deterministic.
_UNRESERVED = frozenset(string.ascii_letters + string.digits + "-._~")
_SUB_DELIMS = frozenset("!$&'()*+,;=")
_PATH_SAFE = _UNRESERVED | _SUB_DELIMS | frozenset(":@/")
_QUERY_ITEM_SAFE = _UNRESERVED | frozenset("!$'()*+,;:@/?")  # `&` and `=` are the separators
_USERINFO_SAFE = _UNRESERVED | _SUB_DELIMS | frozenset(":")

# 05-ingest-and-routing.md section 1.2: the container-child fragment escapes `/ # ? %` and every
# byte outside `[A-Za-z0-9._~-]`, so a member named `a#b/c` cannot forge a sibling's identity
# and a non-UTF-8 member name is still representable.
_FRAGMENT_SAFE = frozenset(string.ascii_letters + string.digits + "._~-")
_CHILD_KINDS = frozenset({"att", "zip", "msg", "part"})
_MAX_FRAGMENT_BYTES = 512
_TRUNCATED_FRAGMENT_BYTES = 400
_FRAGMENT_HASH_CHARS = 16

_DEFAULT_PORT = {"http": 80, "https": 443}
_SHA256_HEX = 64
_HEXDIGITS = frozenset(string.hexdigits)
_LOWER_HEX = frozenset("0123456789abcdef")

_CONTENT_DOMAIN = b"ow.content.1"
_OW128_SIZE = 16


# --------------------------------------------------------------------------------------------
# 1. canonical_uri -- the one producer of a `unit_uri`
# --------------------------------------------------------------------------------------------


def canonical_uri(
    locator: Locator | str | os.PathLike[str],
    ident: str = "",
    *,
    child_kind: str | None = None,
    child_path: str | bytes | None = None,
) -> str:
    """The `unit_uri` for one unit, over the invocation's `Locator` and a connector-local `id`.

    Four kinds, one per row of 05-ingest-and-routing.md section 1.2's table:

    * `file`, `dir` -> `realpath` then `normcase` then forward slashes then a stripped Windows
      `\\\\?\\` prefix. This is a PATH form and carries no `file:` scheme, which is what
      "`canonical_uri()`'s path form of `ref`" means in section 1.1's `Locator.target` row.
      `normcase` is what makes `C:\\A\\B.PDF` and `c:/a/b.pdf` one row.
    * `http`, `https` -> scheme and host lower-cased, the default port dropped, the path
      percent-normalised, the fragment dropped, and the query KEPT and sorted by key: a
      fragment never changes the bytes, a query usually does.
    * any other scheme -> `<connector>://<stable connector id>`, the connector form. A title or
      a folder path is not an identity; both move.
    * `stream` -> `stream://sha256/<source_sha256>`. A stream has no external name, so its
      content is its name.

    A bare `str`/`PathLike` is the `file` kind, which is the `unit_uri = canonical_uri(path)`
    spelling of 02-architecture.md section 5 row 2.

    `child_kind` and `child_path` append a container child's fragment,
    `<parent unit_uri>#<kind>/<path>` -- an attachment, a ZIP member, an mbox message or a
    container part. Both are given together or neither is.

    Idempotent: `canonical_uri(canonical_uri(x)) == canonical_uri(x)` for every locator form.
    """
    scheme, target = _split_locator(locator)
    match scheme.lower():
        case "":
            raise ValueError("canonical_uri: the locator has no scheme")
        case "file" | "dir":
            uri = _canonical_path(_join_under(target, ident) if ident else target)
        case "http" | "https" as web:
            uri = _canonical_url(urljoin(target, ident) if ident else target, web)
        case "stream":
            uri = f"stream://sha256/{_require_sha256(ident or target)}"
        case connector:
            uri = f"{connector}://{_pct_normalise(ident or target, _PATH_SAFE)}"
    if child_kind is None and child_path is None:
        return uri
    return f"{uri}#{_child_fragment(child_kind, child_path)}"


def _split_locator(locator: Locator | str | os.PathLike[str]) -> tuple[str, str]:
    """`(scheme, target)`. A bare path is the `file` kind; anything else carries its own."""
    if isinstance(locator, (str, os.PathLike)):
        return "file", os.fspath(locator)
    scheme = getattr(locator, "scheme", None)
    target = getattr(locator, "target", None)
    if not isinstance(scheme, str) or not isinstance(target, str):
        raise TypeError(
            f"canonical_uri: {type(locator).__name__} is neither a path nor a Locator "
            f"(04-driver-system.md section 1.3: `scheme` and `target`, both `str`)"
        )
    return scheme, target


def _join_under(target: str, ident: str) -> str:
    """`ident` is a path RELATIVE to `Locator.target` and may never re-root it.

    `Path(root) / "/abs"` silently yields `/abs`, which is how a connector-supplied id would
    walk out of `[roots] source` before `confine()` ever saw it.
    """
    relative = PurePath(ident)
    if relative.is_absolute() or relative.drive or ident.startswith(("/", "\\")):
        raise ValueError(f"canonical_uri: {ident!r} is not relative to the locator target")
    return os.fspath(Path(target) / relative)


def _canonical_path(raw: str) -> str:
    """realpath, normcase, forward slashes, `\\\\?\\` stripped -- in that order.

    An absolute path is required. `realpath` resolves a relative path against the process
    working directory, and an identity that reads the ambient cwd is the bug 08-runtime.md
    section 1.3 bans `os.getcwd()` and `Path(".")` to prevent. The plan does not state the
    relative case; refusing it is the conservative reading.
    """
    if not raw:
        raise ValueError("canonical_uri: the path is empty")
    if not PurePath(raw).is_absolute():
        raise ValueError(
            f"canonical_uri: {raw!r} is relative; a unit_uri is absolute and this function "
            f"never reads the process working directory"
        )
    resolved = os.path.normcase(str(Path(raw).resolve())).replace("\\", "/")
    if resolved.lower().startswith("//?/unc/"):
        return "//" + resolved[len("//?/unc/") :]
    if resolved.startswith("//?/"):
        return resolved[len("//?/") :]
    return resolved


def _canonical_url(raw: str, scheme: str) -> str:
    """The `url` row of 05-ingest-and-routing.md section 1.2's table, in full."""
    parts = urlsplit(raw)
    if parts.scheme and parts.scheme.lower() != scheme:
        raise ValueError(f"canonical_uri: {raw!r} is not a {scheme} URL")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"canonical_uri: {raw!r} has no host")
    authority = f"[{host}]" if ":" in host else host
    port = parts.port
    if port is not None and port != _DEFAULT_PORT[scheme]:
        authority = f"{authority}:{port}"
    if parts.username is not None:
        # The plan is silent on userinfo. Dropping it would silently merge two units that a
        # server may answer differently, so it is preserved: keeping credentials OUT of a
        # locator is `resolve_locator()`'s job at the user-string boundary (14-security.md
        # section 4.2), not this function's.
        user = _pct_normalise(parts.username, _USERINFO_SAFE)
        if parts.password is not None:
            user = f"{user}:{_pct_normalise(parts.password, _USERINFO_SAFE)}"
        authority = f"{user}@{authority}"
    path = _remove_dot_segments(_pct_normalise(parts.path, _PATH_SAFE)) or "/"
    return urlunsplit((scheme, authority, path, _canonical_query(parts.query), ""))


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 section 5.2.4. The plan names four url operations and not this one, but
    `canonical_uri(locator, ref)` already resolves dot segments through `urljoin`, so leaving
    an absolute target unresolved would make `.../a/../b` and `.../b` two units by which call
    shape the host happened to use. `..` never climbs above the root.
    """
    out: list[str] = []
    for segment in path.split("/"):
        if segment == ".":
            continue
        if segment == "..":
            if len(out) > 1:
                out.pop()
            continue
        out.append(segment)
    if path.rsplit("/", 1)[-1] in (".", "..") and out[-1:] != [""]:
        out.append("")
    return "/".join(out)


def _canonical_query(query: str) -> str:
    """Kept and sorted BY KEY, stably -- two values under one key keep their given order,
    because `?a=1&a=2` and `?a=2&a=1` are not always the same request."""
    if not query:
        return ""
    items: list[tuple[str, str | None]] = []
    for raw in query.split("&"):
        if not raw:
            continue
        key, sep, value = raw.partition("=")
        items.append(
            (
                _pct_normalise(key, _QUERY_ITEM_SAFE),
                _pct_normalise(value, _QUERY_ITEM_SAFE) if sep else None,
            )
        )
    items.sort(key=lambda item: item[0])
    return "&".join(key if value is None else f"{key}={value}" for key, value in items)


def _pct_normalise(raw: str, safe: frozenset[str]) -> str:
    """Percent-normalise `raw`: decode an escaped unreserved octet, upper-case the hex of every
    other escape, and escape every character outside `safe`.

    Idempotent by construction -- an existing `%XX` is re-read as one octet rather than as a
    literal `%`, so re-running never doubles an escape.
    """
    out: list[str] = []
    i = 0
    end = len(raw)
    while i < end:
        char = raw[i]
        if char == "%" and _is_escape(raw, i):
            octet = int(raw[i + 1 : i + 3], 16)
            out.append(chr(octet) if chr(octet) in _UNRESERVED else f"%{octet:02X}")
            i += 3
            continue
        if char in safe:
            out.append(char)
        else:
            out.extend(f"%{byte:02X}" for byte in char.encode("utf-8", "surrogatepass"))
        i += 1
    return "".join(out)


def _is_escape(raw: str, i: int) -> bool:
    return i + 2 < len(raw) and raw[i + 1] in _HEXDIGITS and raw[i + 2] in _HEXDIGITS


def _require_sha256(value: str) -> str:
    if len(value) != _SHA256_HEX or not set(value) <= _LOWER_HEX:
        raise ValueError(f"canonical_uri: {value!r} is not a 64-char lowercase sha256")
    return value


def _child_fragment(kind: str | None, path: str | bytes | None) -> str:
    """`<kind>/<encoded path>`, bounded. 05-ingest-and-routing.md section 1.2.

    Over 512 bytes the fragment is truncated to its first 400 encoded bytes plus
    `~<sha256(full path)[:16]>`, which bounds `unit_uri` and keeps two long members distinct.
    """
    if kind is None or path is None:
        raise ValueError("canonical_uri: child_kind and child_path are given together")
    if kind not in _CHILD_KINDS:
        raise ValueError(f"canonical_uri: {kind!r} is not one of {sorted(_CHILD_KINDS)}")
    raw = path.encode("utf-8", "surrogatepass") if isinstance(path, str) else bytes(path)
    if not raw:
        raise ValueError("canonical_uri: the container child path is empty")
    encoded = "".join(chr(byte) if chr(byte) in _FRAGMENT_SAFE else f"%{byte:02X}" for byte in raw)
    fragment = f"{kind}/{encoded}"
    if len(fragment) <= _MAX_FRAGMENT_BYTES:
        return fragment
    head = _trim_partial_escape(fragment[:_TRUNCATED_FRAGMENT_BYTES])
    return f"{head}~{hashlib.sha256(raw).hexdigest()[:_FRAGMENT_HASH_CHARS]}"


def _trim_partial_escape(text: str) -> str:
    """A cut through `%4` or `%` would leave an escape that no longer decodes."""
    for back in (1, 2):
        if len(text) >= back and text[-back] == "%":
            return text[:-back]
    return text


# --------------------------------------------------------------------------------------------
# 2. content_digest -- the merkle recipe of 03-document-model.md section 6.4
# --------------------------------------------------------------------------------------------


def content_digest(
    kind: int,
    layer: int,
    text: str | None,
    payload: Mapping[str, JsonValue] | None = None,
    children: Sequence[bytes] = (),
) -> bytes:
    """`ow128(b'ow.content.1', [kind, layer, nfc(text), canonical(payload), children])`.

    16 raw bytes -- the `block.content_digest` and `segment.content_digest` BLOB. GEOMETRY IS
    NOT AN INPUT, so a driver upgrade's bbox jitter cannot orphan a document; neither are
    `block_id`, `addr`, `cite`, `ord`, `revision`, the provenance columns, `marks`, `x` or any
    span. `children` are the children's digests in `ord` ORDER, which is why a reordering of
    siblings moves the parent's digest and not the children's.

    `text` is NFC-normalised here, so the recipe is closed over its own inputs.
    `omniweave_core.ident.nfc` is the same transform under its own name and is INV-10's proof
    normaliser (06-structure-extraction.md section 1.7); this call is not a second definition
    of it. `None` (a container, `text IS NULL`) and `""` stay distinct, per the
    "three distinct encodings for absent / null / `""`" rule and section 6.4's own
    `# None != ""` annotation.

    Specified in 03-document-model.md section 6.4 and charter.md section "Digests".
    """
    for index, child in enumerate(children):
        if not isinstance(child, (bytes, bytearray)) or len(child) != _OW128_SIZE:
            raise ValueError(f"content_digest: children[{index}] is not a 16-byte ow128 digest")
    return ow128(
        _CONTENT_DOMAIN,
        [
            int(kind),
            int(layer),
            None if text is None else unicodedata.normalize("NFC", text),
            # The payload's own canonical bytes, embedded as a string: it pins the payload's
            # serialisation independently of the outer list, which is what section 6.4's
            # `canonical(payload)` inside a canonicalised list means.
            canonical(payload).decode("utf-8"),
            [bytes(child).hex() for child in children],
        ],
    )


# --------------------------------------------------------------------------------------------
# 3./4. the two config digests, and the axis between them
# --------------------------------------------------------------------------------------------


def config_digest(values: Mapping[str, JsonValue]) -> str:
    """`sha256_canonical(the FULL resolved config)` -- 64-char hex.

    Feeds the run manifest and the full-scan latch. **NEVER a cache key**: it holds
    `runtime.**`, `store.**` and `observe.**`, so raising `max_workers` would re-bill the
    corpus (I26). There is deliberately no axis parameter -- see `semantic_digest`.

    Specified in 02-architecture.md section 8.3 and 08-runtime.md section 4.2.
    """
    return sha256_canonical(dict(values))


def semantic_digest(
    values: Mapping[str, JsonValue],
    axes: Mapping[str, ConfigAxis],
) -> str:
    """`sha256_canonical(the SEMANTIC PROJECTION of the resolved config)` -- 64-char hex.

    The only config digest a cache key may see, and an input to the full-scan latch. A key is
    `semantic` **iff** changing it can change the CONTENT of a produced row for a driver whose
    identity, `schema_version` and config are unchanged; everything else is `operational` and
    is projected away here.

    `axes` is the resolved per-key axis -- `Config.axis_of` for each key of `values`, globs
    already applied. A key with NO entry is treated as `semantic`: an unclassified key fails
    CI, and at runtime fails expensive rather than wrong (02-architecture.md section 8.3). An
    entry that is neither word is a `ValueError`, because a typo must not silently become
    `operational` and drop a key out of every cache key in the corpus.

    Specified in 02-architecture.md sections 8.3 and 8.4 and 08-runtime.md section 4.3.
    """
    projection: dict[str, JsonValue] = {}
    for key, value in values.items():
        axis = axes.get(key, "semantic")
        if axis not in ("semantic", "operational"):
            raise ValueError(
                f"semantic_digest: axis {axis!r} for {key!r} is neither 'semantic' nor "
                f"'operational' (02-architecture.md section 8.3 admits no third state)"
            )
        if axis == "semantic":
            projection[key] = value
    return sha256_canonical(projection)
