"""`manifest.json` -- the archive's only mandatory member -- and the version refusal.

Specified in 03-document-model.md section 13.2: the key set is printed at :2482-2484, "Pretty-
printed. The ONLY mandatory member" at :2485, "An archive holds exactly one generation, named in
`manifest.json`" at :2503, and the refusal rule at :2516-2519. The version fields and their
release-1 values come from section 15.1 (:2707-2717).

**The three archive version stamps live here, and that is a ruling, not an oversight.**
03-document-model.md section 15.1 gives `container_version`, `min_reader` and `digest_recipe`
homes on disk (`meta` and `manifest.json`) and names no code home for any of them;
`adr/0009-schema-single-home.md` gives `omniweave_core.contract` exactly the `SCHEMA` pair and
`RELEASE`, and `omniweave_core.contract` at the time of writing declares only those. So the
envelope's own module is the home with a warrant, and the envelope is what these three govern.
If a later wave adds any of them to `omniweave_core.contract`, this module must **re-export**
rather than re-declare: two homes for one stamp is `OW_SCHEMA_SECOND_HOME` (OW-S-034), the code
the plan allocates for exactly that mistake.

**Tolerance is asymmetric and 03-document-model.md:2516 is why.** A missing or unparseable
member yields `status = partial` plus a `Diag`; only `manifest.json` is fatal to omit. An
unknown top-level *manifest key* is neither dropped nor fatal -- it is preserved verbatim under
`x["x.ow.unknown"]`, which is the reserved slot 03:2738-2742 introduces so that
`export(import(a)) == a` holds rather than almost holds. `x` is not a digest input, so
round-tripping an unknown key through it cannot move a `content_digest`.

Stdlib only (INV-2). No `sqlite3` (INV-17).

Tier T-SCHEMA: 02-architecture.md section 2 row 25.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

from omniweave_core.errors import ModelError

__all__ = [
    "CONTAINER_VERSION",
    "DIGEST_RECIPE",
    "MANIFEST_MEMBER",
    "MIN_READER",
    "MODEL_VERSION",
    "STATUSES",
    "UNKNOWN_KEY_SLOT",
    "Manifest",
    "manifest_json",
    "parse_manifest",
    "require_readable",
]

MANIFEST_MEMBER: Final = "manifest.json"
"""The one member whose absence is fatal (03-document-model.md:2485, :2516)."""

CONTAINER_VERSION: Final = "1.0"
"""The `.owdoc` envelope: member layout, compression, `frames.json` shape. 03:2712, :2717.

Frozen at the end of P2 together with the member layout (16-roadmap.md:428). It moves for a
change to the envelope and never for a change to the type layer -- 03:2734's last row spells
that out by leaving every other column blank for "change `.owdoc` member layout or compression".
"""

MODEL_VERSION: Final = "1.1"
"""The type layer: fields, kinds, payload schemas, wire keys. 03:2711, :2717.

`"1.1"` and not `"1.0"` because 03-document-model.md section 3.1 (:686-693) appends seven wire
keys -- `c`, `qt`, `mt`, `lb`, `pl`, `st`, `dc` -- to charter D2's frozen twenty-two, making
twenty-nine, and the charter already stamps `model_version = "1.1"` on `meta` at :969. Erratum
E52 names section 3.1's table as that mapping's sole home.
"""

MIN_READER: Final = "1.0"
"""The lowest `model_version` that can read an artefact this writer produces. 03:2713, :2717.

Below `MODEL_VERSION` on purpose: a 1.0 reader can read a 1.1 artefact, because 1.1's seven
appended keys are additive and 03:2723 makes an unknown optional key an ignore-and-preserve
rather than a refusal. `min_reader` rises only when a reader that does not know a name would be
WRONG rather than incomplete -- adding a `Kind` member is 03:2731's worked example.
"""

DIGEST_RECIPE: Final = 1
"""The digest definitions. 03:2714, :2717.

Bumped by a change to a digest input or to `canonical()`'s encoding (03:2732), and serviced by
`op.redigest` rather than a re-parse, because every digest input is a stored field (03:2764).
"""

STATUSES: Final = ("ok", "partial", "failed", "skipped")
"""`doc.status`'s CHECK, transcribed from the store's `0001_init.sql` `CREATE TABLE doc`.

The archive carries the document's status verbatim, and `import_` degrades it to `partial` when
a member was missing or unparseable (03:2516). `failed` and `skipped` are exportable: an archive
of a failed parse is how a failure travels to whoever can explain it.
"""

UNKNOWN_KEY_SLOT: Final = "x.ow.unknown"
"""Where an unknown top-level manifest key is preserved. 03-document-model.md:2738-2742.

The `ow` vendor segment is the framework's, so no third party can collide with it.
"""

_VERSION_RE: Final = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_DOC_KEY_RE: Final = re.compile(r"^[0-9a-f]{32}$")
"""`doc_key` is `sha256(NORMALIZED source bytes)[:16]` -- 16 bytes, so 32 hex characters.

The width is `CREATE TABLE doc`'s comment in the store's `0001_init.sql`; hex rather than base64
because 03-document-model.md:665 fixes hex as the wire spelling of every digest.
"""

_UPGRADE: Final = "pip install -U omniweave-core"
"""The upgrade command a refusal names. 18-api-sketch.md:176, 07-store-and-retrieval.md:287.

The same command `OW_SCHEMA_AHEAD` names for the store's schema major, because it is the same
remedy: the reader is old. There is no `--force` (03:2519).
"""


@dataclass(frozen=True, slots=True)
class Manifest:
    """`manifest.json`, key for key with 03-document-model.md:2482-2484, plus `gen`.

    **`gen` is added to the printed key set and that is a plan silence resolved, not an
    invention.** 03-document-model.md:2503 states that an archive holds exactly one generation
    "named in `manifest.json`", and :2482-2484's printed key list has no key that could name it.
    Exporting two generations of one document is two archives, and what makes the deep-golden
    `rebind()` diff a diff of two files rather than a query inside one is precisely that each
    file says which generation it is. Without the key the sentence at :2503 has no referent.

    Every open-ended field is a `Mapping`: `source`, `declared`, `achieved`, `confidence`,
    `timings_ms`, `counts` and `x` are carried through verbatim rather than typed here.
    `Capabilities` (the type behind `declared`/`achieved`) is `omniweave_core.model`'s and the
    `doc` table stores both as JSON TEXT, so the archive's job is to move the JSON without
    reinterpreting it -- a re-typing here would be a second home for the fifteen-field shape.
    """

    doc_key: str
    gen: int
    source: dict[str, Any]
    status: str
    declared: dict[str, Any]
    achieved: dict[str, Any]
    producers: tuple[dict[str, Any], ...] = ()
    parts: tuple[dict[str, Any], ...] = ()
    assets: tuple[dict[str, Any], ...] = ()
    views: tuple[dict[str, Any], ...] = ()
    confidence: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, Any] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    x: dict[str, Any] = field(default_factory=dict)
    container_version: str = CONTAINER_VERSION
    model_version: str = MODEL_VERSION
    min_reader: str = MIN_READER
    digest_recipe: int = DIGEST_RECIPE

    def __post_init__(self) -> None:
        if not _DOC_KEY_RE.match(self.doc_key):
            msg = f"manifest.doc_key is 32 lowercase hex chars, got {self.doc_key!r}"
            raise ModelError(msg, fix="ow doc export <doc>")
        if not isinstance(self.gen, int) or isinstance(self.gen, bool) or self.gen < 0:
            msg = f"manifest.gen is one non-negative generation (03:2503), got {self.gen!r}"
            raise ModelError(msg, fix="ow doc export <doc> --gen N")
        if self.status not in STATUSES:
            msg = f"manifest.status is one of {STATUSES}, got {self.status!r}"
            raise ModelError(msg, fix="ow doc export <doc>")
        for name in ("container_version", "model_version", "min_reader"):
            _major_minor(getattr(self, name), what=f"manifest.{name}")
        if not isinstance(self.digest_recipe, int) or isinstance(self.digest_recipe, bool):
            msg = f"manifest.digest_recipe is a small int (03:2714), got {self.digest_recipe!r}"
            raise ModelError(msg, fix="ow doc export <doc>")

    def as_record(self) -> dict[str, Any]:
        """The JSON object in 03-document-model.md:2482-2484's printed key order.

        Order is fixed here rather than sorted, for two reasons that point the same way. The
        archive is byte-stable (INV-10), so insertion order may not be an accident; and the
        printed order is the order a human reading `unzip -p x.owdoc manifest.json` wants -- the
        four version stamps first, because they decide whether the rest is even readable.
        """
        return {
            "container_version": self.container_version,
            "model_version": self.model_version,
            "min_reader": self.min_reader,
            "digest_recipe": self.digest_recipe,
            "doc_key": self.doc_key,
            "gen": self.gen,
            "source": dict(self.source),
            "status": self.status,
            "producers": [dict(p) for p in self.producers],
            "parts": [dict(p) for p in self.parts],
            "assets": [dict(a) for a in self.assets],
            "views": [dict(v) for v in self.views],
            "declared": dict(self.declared),
            "achieved": dict(self.achieved),
            "confidence": dict(self.confidence),
            "timings_ms": dict(self.timings_ms),
            "counts": dict(self.counts),
            "x": dict(self.x),
        }


_FIELD_NAMES: Final = MappingProxyType(
    {
        "container_version": str,
        "model_version": str,
        "min_reader": str,
        "digest_recipe": int,
        "doc_key": str,
        "gen": int,
        "source": dict,
        "status": str,
        "producers": list,
        "parts": list,
        "assets": list,
        "views": list,
        "declared": dict,
        "achieved": dict,
        "confidence": dict,
        "timings_ms": dict,
        "counts": dict,
        "x": dict,
    }
)
"""The eighteen keys `parse_manifest` knows, and the JSON type each must have.

Written as data rather than reflected off `Manifest.__dataclass_fields__` because the dataclass
declares defaults in a different order (the required fields first, which Python forces) and the
wire order is `as_record`'s. One list, used for both the type check and the unknown-key split.
"""

_REQUIRED: Final = ("doc_key", "gen", "source", "status", "declared", "achieved")
"""What a manifest cannot omit. The four version stamps are NOT here, on purpose.

An artefact with no `container_version` predates the stamp, which by 03:2708's own table can
only mean `"1.0"`; refusing it would refuse the very artefacts backward compatibility exists
for (03:2720). An artefact with no `doc_key` names no document and there is nothing to default.
"""


def manifest_json(manifest: Manifest) -> bytes:
    """`manifest.json`'s exact bytes. Pretty-printed, because a human reads it (03:2485).

    `indent=2` with an explicit `separators` for the same trailing-space reason `frames_json()`
    gives, and `ensure_ascii=False` because a `source.uri` with a non-ASCII path should read as
    itself under `unzip -p` rather than as `\\u`-escapes. `allow_nan=False` refuses `NaN` and
    `Infinity`, which are not JSON and which `jq` rejects -- a `confidence` value arriving as a
    float `nan` must fail here and not at whatever reads the archive next.
    """
    body = json.dumps(
        manifest.as_record(),
        indent=2,
        separators=(",", ": "),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (body + "\n").encode("utf-8")


def parse_manifest(raw: bytes) -> Manifest:
    """Decode `manifest.json`. A failure here is fatal: there is no archive without it.

    Unknown keys are preserved under `x["x.ow.unknown"]` (03:2738-2742) rather than dropped,
    which is what makes a 1.1 artefact survive a round trip through a reader that predates one
    of its keys.
    """
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"{MANIFEST_MEMBER} is not UTF-8 JSON: {exc}"
        raise ModelError(msg, fix="ow doc export <doc>") from exc
    if not isinstance(parsed, dict):
        msg = f"{MANIFEST_MEMBER} is an object, got {type(parsed).__name__}"
        raise ModelError(msg, fix="ow doc export <doc>")
    missing = [name for name in _REQUIRED if name not in parsed]
    if missing:
        msg = f"{MANIFEST_MEMBER} is missing {', '.join(missing)}"
        raise ModelError(msg, fix="ow doc export <doc>")
    known: dict[str, Any] = {}
    unknown: dict[str, Any] = {}
    for key, value in parsed.items():
        expected = _FIELD_NAMES.get(key)
        if expected is None:
            unknown[key] = value
            continue
        # No manifest key is a JSON boolean, and `isinstance(True, int)` is True in Python, so
        # the bool arm is what stops `"gen": true` from parsing as generation 1.
        if isinstance(value, bool) or not isinstance(value, expected):
            msg = (
                f"{MANIFEST_MEMBER}.{key} is a JSON {expected.__name__}, got {type(value).__name__}"
            )
            raise ModelError(msg, fix="ow doc export <doc>")
        known[key] = value
    for key in ("producers", "parts", "assets", "views"):
        if key in known:
            known[key] = tuple(known[key])
    extra = dict(known.pop("x", {}))
    if unknown:
        extra[UNKNOWN_KEY_SLOT] = {**extra.get(UNKNOWN_KEY_SLOT, {}), **unknown}
    return Manifest(x=extra, **known)


def require_readable(manifest: Manifest) -> None:
    """Refuse an artefact this reader would misread. 03-document-model.md:2516-2519, :2718-2721.

    Three comparisons, each a MAJOR comparison and none a best effort:

    * the artefact's `container_version` MAJOR above this reader's -- the envelope changed, so
      the member layout, the compression or `frames.json`'s shape is not what this code parses;
    * the artefact's `model_version` MAJOR above this reader's -- a field was removed or
      retyped (03:2733), so a record this reader parses would mean something else;
    * the artefact's `min_reader` above this reader's `model_version` -- the writer has already
      computed that a reader below that line is wrong rather than merely incomplete, which is
      what `min_reader` is for (03:2713).

    A MINOR above this reader's is NOT a refusal: 03:2723 makes a new optional key an
    ignore-and-preserve, and `parse_manifest` implements the preserve half. Silent misreading is
    the failure an operator cannot detect (03:2517), and there is no `--force` (03:2519).
    """
    ours_model = _major_minor(MODEL_VERSION, what="reader model_version")
    checks = (
        ("container_version", manifest.container_version, CONTAINER_VERSION),
        ("model_version", manifest.model_version, MODEL_VERSION),
    )
    for name, theirs_text, ours_text in checks:
        theirs = _major_minor(theirs_text, what=f"manifest.{name}")
        ours = _major_minor(ours_text, what=f"reader {name}")
        if theirs[0] > ours[0]:
            msg = (
                f"this archive declares {name} {theirs_text} and this reader is {ours_text}: "
                f"a MAJOR above the reader is refused, never best-efforted (03:2517). "
                f"Upgrade with `{_UPGRADE}`"
            )
            raise ModelError(msg, fix=_UPGRADE)
    theirs_min = _major_minor(manifest.min_reader, what="manifest.min_reader")
    if theirs_min > ours_model:
        msg = (
            f"this archive declares min_reader {manifest.min_reader} and this reader is "
            f"model_version {MODEL_VERSION}: the writer has already determined a reader below "
            f"{manifest.min_reader} reads it WRONG (03:2713). Upgrade with `{_UPGRADE}`"
        )
        raise ModelError(msg, fix=_UPGRADE)


def _major_minor(text: object, *, what: str) -> tuple[int, int]:
    """`"1.1"` to `(1, 1)`. A refusal, never a lenient parse.

    A version this function cannot read is worse than a version above the reader's: the reader
    does not know whether it is above or below, so the only safe answer is to stop. That is why
    there is no `except: return (0, 0)` arm here.
    """
    if not isinstance(text, str) or not _VERSION_RE.match(text):
        msg = f'{what} is "MAJOR.MINOR" with no leading zeros (03:2708), got {text!r}'
        raise ModelError(msg, fix=_UPGRADE)
    major, minor = text.split(".", 1)
    return int(major), int(minor)
