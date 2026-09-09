"""The L2 records the store persists: `Producer`, `DocRecord`, `PageRecord`, assets, `Rel`, `Diag`.

Specified in 03-document-model.md section 2.8 (:390-435 prints seven of them) and section 9
(:1795-1804 prints `Diag`). Section 2.8's `Frame` is deliberately NOT here -- see below -- and
`DocKey`, 03:162's fourth identity, IS, because `DocRecord` is its only consumer and
`block.py:90` declined it on exactly that ground (INV-21: one name, one home).

**These are the values that become rows.** Every field maps to a column of `doc`, `page`,
`asset`, `rel`, `diag` or `producer` in `store/schema/migrations/0001_init.sql`, and
`test_model_records.py` asserts that correspondence in both directions off a MIGRATED database's
`PRAGMA table_info`, not off a transcription of the DDL. The reverse direction has three
allowances and each is named per record in that test's `ROW_SHAPES`: a column the sink mints
(`producer_id`, `store_ref`, `asset_id`), a column carrying the document scope the record is
written inside (`doc_ord`, `gen`), and a column with a DEFAULT (`next_cite_n`,
`restriction_bits`). Nothing else may be absent, because a record whose fields the store cannot
persist is worse than no record.

**Validation is what a CHECK constraint would refuse, and nothing more.** `Block` carries no
`__post_init__` at all (see `block.py`) because every rule a Block obeys is a rule about its
relationship to something else, enforced at `DocSink.add_block` (03:583). The records here are
the same kind of value, with one difference: three of their columns carry an *inline* CHECK
constraint over a single field --

| column | CHECK | field |
|---|---|---|
| `doc.status` | `IN ('ok','partial','failed','skipped')` | `DocRecord.status` |
| `page.quad_origin` | `IN ('topleft','bottomleft')` | `PageRecord.quad_origin` |
| `diag.severity` | `IN ('error','warning','info')` | `Diag.severity` |

-- and a `Literal` annotation is not enforced at runtime, so without these three checks the
failure surfaces as an `sqlite3.IntegrityError` inside the store thread, five frames from the
driver that produced the value. Refusing here makes it a `ModelError` carrying the offending
value and the allowed set. `page.status` gets no check on purpose: 03:418 prints it as `str`,
not a `Literal`, and the DDL gives it `DEFAULT 'ok'` and no CHECK.

**Two rules beyond the CHECKs, both rules about one value.**

* `Diag.code` holds the **symbol** from `codes.toml` (`OW_TABLE_SPAN_CLAMPED`), never the
  numeric: "callers branch on the symbol, and the CLI prints the numeric" (03:1806-1808). A
  numeric slipping into `diag.code` is silent -- `code TEXT NOT NULL` accepts it and
  `CREATE INDEX diag_code` indexes it, and the absence contract's `parse_gap_in_scope` gate then
  joins against a spelling no caller branches on. `errors.NUMERIC_RE` and `errors.SYMBOL_RE` are
  the register's own two shapes and they are imported, never retyped.
* `DocRecord.x` keys must match `x\\.[a-z0-9_]+\\.[a-z0-9_]+`, the vendor segment `ow` reserved
  for the framework (03:302). Enforced here and NOT on `Block.x`, and the asymmetry is
  deliberate: 03 section 2.10's table gives `add_block` an enforcement site for every rule a
  `BlockDraft` carries, and gives `begin_doc` "inserts or looks up `doc` by `doc_key`; assigns
  `doc_ord`; fixes `g_t = doc.gen + 1`; copies `declared` onto `doc`" -- `doc.x` is on no
  method's list, so a malformed key there has no gate at all before it is durable.
  `MAX_X_BYTES` over `canonical(x)` is NOT checked here: it is a limit at the boundary
  (03:3009's P25) and the boundary is `DocSink`.

**The two asymmetries this module transcribes rather than smoothing.** They are the plan's, and
recording them is cheaper than a later reader rediscovering them.

1. `DocRecord.x` and `PageRecord.stats` default to `MappingProxyType({})` (03:412, 03:424) while
   `Diag.detail` defaults to `field(default_factory=dict)` (03:1803) -- two different answers to
   one problem, in two sections of one document. Both are transcribed as printed, and both are
   safe for different reasons: an empty `MappingProxyType` is immutable, so sharing one instance
   between records is sound (the same argument `BlockDraft.origin = OriginNone()` makes); a
   `default_factory` allocates a fresh `dict` per instance, so mutating one `Diag.detail` cannot
   reach another. `test_model_records.py` proves both properties rather than asserting the
   syntax.
2. `Diag` is **recorded**; `OwError` is **raised** (03:1806). Two names for two things, and this
   module owns the recorded one. A recoverable producer quirk lands in a `Diag`, never in an
   exception -- anydoc's stated discipline (03:1819-1822).

**`Frame` is not here.** 03:444-447 prints it in section 2.8, but it is already declared at
`omniweave_core/archive/frames.py:94` against section 13.3 (:2526) and 03:2483's `frames.json`
member list, where its sole producer and consumer live. Declaring it a second time would put one
name in two homes, which INV-21 forbids, and the two prints disagree about `sha256` -- 03:452
says `bytes`, 03:2483 and `frames.json` say 64 lowercase hex -- so a second declaration would
also have to pick a side. Reported, not re-homed.

**`CellDraft` is not here either.** 03:337-338 puts it in section 2.6, which is `block.py`'s
(`CellPos` and `BlockDraft` are already there), so it belongs to that cluster's owner.

Stdlib only, like everything under `omniweave_core.model` (03 section 2). This module is inside
one of the nine LAZY subpackages (11-repo-layout.md section 1.3), so nothing eager may reach it:
G17 asserts a bare `import omniweave_core` loads none of the nine.

Tier T-SCHEMA: 02-architecture.md section 2 row 24.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, Literal, NewType

from omniweave_core.errors import NUMERIC_RE, SYMBOL_RE, ModelError
from omniweave_core.model.block import BlockId, Capabilities
from omniweave_core.model.enums import Method, PageKind, RelKind, Trust

# `Mapping` is a runtime import and not an `if TYPE_CHECKING:` one, for the reason `block.py`
# records: five fields below are annotated `Mapping[str, ...]`, and a name that exists only for a
# type checker makes `typing.get_type_hints()` raise `NameError` -- which is the call the
# field-to-column test, `ow schema emit`'s reflector and `tools/schemagen.py` all go through.
# `Capabilities` is a runtime import for the same reason: `DocRecord.declared` names it.

__all__ = [
    "DOC_STATUSES",
    "QUAD_ORIGINS",
    "SEVERITIES",
    "AssetDraft",
    "AssetRef",
    "Diag",
    "DocKey",
    "DocRecord",
    "PageRecord",
    "Producer",
    "Rel",
]


# ---------------------------------------------------------------------------
# 0. The three closed field vocabularies, and the refusal that carries them.
# ---------------------------------------------------------------------------

DOC_STATUSES: Final[tuple[str, ...]] = ("ok", "partial", "failed", "skipped")
"""`doc.status`'s CHECK, in the DDL's order. 03:409 prints the same four as a `Literal`.

Declared once as data because a `Literal` is not enforced at runtime and a hand-typed tuple
inside a validator would be a third transcription of the same four words.
`test_model_records.py` asserts this tuple equals `get_type_hints(DocRecord)["status"]`'s
arguments AND equals the shipped CHECK constraint's own membership, so the annotation, the
constant and the database cannot drift apart.
"""

QUAD_ORIGINS: Final[tuple[str, ...]] = ("topleft", "bottomleft")
"""`page.quad_origin`'s CHECK. **What the DRIVER handed us**, not what we stored.

`Quad` has exactly one stored frame -- topleft, 1/1000 pt, unrotated -- normalised once inside
`Quad.from_driver` (`spans.py`). This column records the frame the driver was speaking, so the
transform stays auditable after the fact; it is NULL when the driver declared no frame.
"""

SEVERITIES: Final[tuple[str, ...]] = ("error", "warning", "info")
"""`diag.severity`'s CHECK, in the DDL's order. 03:1799 prints the same three as a `Literal`."""

_DOC_FIX = "ow ingest --dry-run <path>  # the producer built an invalid doc record"
"""The command that clears a `DocRecord` refusal.

`OwError.__init__` refuses an empty `fix` (`errors.py`), and every refusal in this module means a
producer handed the host a value the `doc`, `page` or `diag` table would reject -- which a
dry-run ingest surfaces before anything is durable.
"""

_PAGE_FIX = "ow doc verify <cite>  # the driver declared an unknown quad origin"
_DIAG_FIX = "ow explain <symbol>  # diag.code is the codes.toml SYMBOL, not the numeric"

_X_KEY_RE: Final = re.compile(r"^x\.[a-z0-9_]+\.[a-z0-9_]+$")
"""03:302's extension-key grammar, INCLUDING the leading `x.` segment.

The prefix is part of the stored key rather than implied by the column: the archive writes
`x["x.ow.cite"]` and `x["x.ow.unknown"]` (`archive/owdoc.py:663`, `archive/manifest.py:98`), so a
pattern anchored after the prefix would accept a key nothing in this framework writes.
"""


def _refuse_member(value: object, allowed: tuple[str, ...], what: str, fix: str) -> None:
    """Raise unless `value` is one of `allowed`, naming both the value and the whole set.

    One helper for all three CHECK-backed fields, so the message shape is identical wherever the
    failure comes from and the allowed set is always printed: a driver author reading
    `PageRecord.quad_origin was 'bottom-left'` still has to guess, and one that also reads
    `allows only 'topleft', 'bottomleft'` does not.
    """
    if value in allowed:
        return
    permitted = ", ".join(repr(member) for member in allowed)
    msg = f"{what} was {value!r}; the column's CHECK allows only {permitted}"
    raise ModelError(msg, fix=fix)


# ---------------------------------------------------------------------------
# 1. `DocKey` -- 03:162's fourth identity, homed with its only consumer.
# ---------------------------------------------------------------------------

DocKey = NewType("DocKey", bytes)
"""`sha256(NORMALIZED source bytes)[:16]`. 03:162; `doc.doc_key` is `BLOB NOT NULL UNIQUE`.

The **document** identity, and the reason `doc` has one row per `doc_key` rather than one per
URI: a re-ingest of the same bytes from a second path is the same document, keeps its `doc_ord`,
and therefore keeps every `cite` ever handed to a model. Normalised bytes and not raw, so a
metadata-only touch (a PDF `/ModDate`, an OOXML `w:rsid*`) is not a new document;
`DocRecord.source_sha256` keeps the raw digest beside it for the audit.

Declared here rather than in `block.py` beside the other three identities of 03 section 2.2,
because a `Block` never carries it and `DocRecord` is its only consumer -- the reasoning
`block.py:90-93` records in a comment standing where the declaration is not.

`NewType` and not an alias: a `bytes` that is a `DocKey` is not interchangeable with a
`source_sha256`, and at a glance the two differ only in length.
"""


# ---------------------------------------------------------------------------
# 2. `Producer` -- one type, two layers. 03:396-401.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Producer:
    """The reproduction tuple. **== L5's `OperatorIdentity`. ONE TYPE, TWO LAYERS** (03:396).

    Every `block`, `page` and `rel` row carries a `producer_id` FK to this table, which is what
    makes "who produced this, with what code, against what model" answerable without a re-parse.

    `op_version` is **an integer at every site**: here, on the `producer` table, and on
    `work`/`work_done` -- the DDL says so in a comment beside the column. There is no `str()`
    round-trip anywhere in the framework, so `"07"` and `7` can never disagree between this key
    and `work_identity`.

    `model_rev` is an exact commit sha and `"main"` is a **lint error** (03:399 and the DDL's own
    comment). It is deliberately not refused here: a lint error is a lint error, the driver-card
    check that owns RT14's rule is where it belongs, and a value type that raised on it would
    turn a reviewable warning into a crash in the middle of a parse. Reported.

    `options_digest` defaults to `b""` and the column is `BLOB NOT NULL`, so the default is a
    real value -- "no options" -- rather than a missing one, the same choice `OriginNone()` makes.
    """

    operator: str
    op_version: int
    code_fingerprint: str
    model_id: str | None = None
    model_rev: str | None = None
    runtime: str | None = None
    runtime_version: str | None = None
    prompt_fp: str | None = None
    options_digest: bytes = b""


# ---------------------------------------------------------------------------
# 3. `DocRecord` -- the `doc` row, and what `begin_doc`/`end_doc` return. 03:403-412.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)  # Extends the charter: named in D2, never defined.
class DocRecord:
    """One `doc` row. 03 section 2.8; the DDL is 03 section 13.1's `CREATE TABLE doc`.

    **`gen` is the generation this record DESCRIBES** (03:455): the target generation `g_t` while
    a parse is running, the committed head afterwards. `DocSink.begin_doc(rec)` returns the
    resolved record -- `doc_ord` assigned on first sight, `gen = g_t` -- and `end_doc(status)`
    returns the record at the post-commit head. Both return a `DocRecord` rather than `None`
    precisely because this type is frozen, so a caller's record cannot carry either value on
    first sight (03:601-606, recorded as Q11).

    **`format` holds a format token, and exactly one token is minted rather than detected**
    (03:459): `owjob`, the format of a synthetic job document written by `omniweave_core.out`'s
    job runner before `bake` produces a byte, carrying
    `media_type = "application/vnd.omniweave.job+json"`,
    `uri = "ow-job://<corpus>/<artifact_slug>/<job_digest>"`, `normalizer = "canonical/1"` (the
    bytes were canonical when produced, so normalising them is the identity -- **not** `NULL`,
    which means the normaliser threw), `status = "ok"` and `page_count = NULL`. It exists because
    `asset.doc_ord` is NOT NULL and a compile-produced asset has no ingested document to belong
    to. `WHERE format = 'owjob'` is the exhaustive selector for synthetic documents and no
    `doc.origin` column is added (ADR-12). The token register itself is 05 section 2.2's.

    **`normalizer = NULL` is not "no normaliser"**: the DDL's comment reads
    "NULL => raw bytes were hashed (OW_NORMALIZER_FAILED)", so NULL records a normaliser that
    threw and `source_sha256` is then the digest that was actually used.

    `declared` is the card's claim, copied onto `doc` at parse time. `achieved` is what the driver
    delivered on THIS document, **computed by the host from the committed rows** at `end_doc`
    rather than reported by the driver (INV-7 at the capability grain, 03:536), and it may be
    lower, never higher. **Serve reads `achieved`** (charter section 5 X9): a card cannot know
    what a particular PDF permitted.

    `confidence` is `{component: mean | None, "n_scored": {component: int}}` (03:1780-1789), so a
    component with `n_scored == 0` is `null`, **not** `0.0`, and is excluded from any aggregate
    grade. That is the corrected form of docling's `nanmean` over an all-NaN `table_score` list,
    whose published grade was a three-component mean wearing four. The value type carries the map;
    03 section 8.6 computes it. The annotation is `Mapping[str, float | None]` as printed, and the
    nested `n_scored` sub-map is why the runtime type is wider than the annotation -- transcribed,
    not narrowed.

    Two `doc` columns are deliberately not fields. `next_cite_n` is the durable per-document cite
    counter -- monotonic, never reset, never reused -- which belongs to the sink and to nobody
    else, and the DDL defaults it to 1. `revision` is a `block` column and not a `doc` column: the
    field table at 03:288 that names it is `Block`'s.
    """

    doc_ord: int
    doc_key: DocKey
    gen: int
    source_sha256: bytes
    normalizer: str | None
    uri: str
    media_type: str
    format: str
    format_evidence: Mapping[str, Any]
    source_bytes: int
    status: Literal["ok", "partial", "failed", "skipped"]
    page_count: int | None
    model_version: str
    declared: Capabilities
    achieved: Capabilities
    confidence: Mapping[str, float | None]
    timings_ms: Mapping[str, int]
    x: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        """Refuse what `doc.status`'s CHECK and 03:302's key grammar refuse. Nothing else.

        Two checks, both local to one instance. `status` is the CHECK. `x`'s keys are the rule
        with no other gate before the row is durable -- see this module's docstring for why
        `Block.x` is not checked and this is.
        """
        _refuse_member(self.status, DOC_STATUSES, "DocRecord.status", _DOC_FIX)
        for key in self.x:
            if not isinstance(key, str) or not _X_KEY_RE.match(key):
                msg = (
                    f"DocRecord.x key {key!r} is not shaped x.<vendor>.<name> over [a-z0-9_] "
                    f"segments (03:302); the vendor segment 'ow' is the framework's"
                )
                raise ModelError(msg, fix=_DOC_FIX)


# ---------------------------------------------------------------------------
# 4. `PageRecord` -- a coordinate frame with a size, a rotation and four scores. 03:414-424.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)  # Extends the charter.
class PageRecord:
    """One `page` row: a coordinate frame with a size, a rotation, a label and four scores.

    03 section 2.8; the DDL is 03 section 13.1's `CREATE TABLE page`, keyed
    `(doc_ord, gen, page)` `WITHOUT ROWID`. A page is the `page` **table** and not a `Block`,
    because modelling it as a block would put `w_mpt` on `Block` (03:905).

    `page` is the **ORIGINAL** source index, 0-based, and **never a batch index** (03:2278): a
    driver that processed pages 40-59 as batch 2 writes 40-59, and the conformance kit ships a
    `limits` fixture that passes under batch indexing and fails. `label` carries the printed
    label (`"iv"`, `"A-3"`) separately, because a citation that says "page 4" when the document
    says "page iv" is wrong in the way a user notices.

    **`method` is the branch that ran on THIS page**, which is what makes per-page escalation
    (INV-13) auditable: a 400-page PDF with three OCR'd pages has three rows at
    `method = 'ocr_page'` and 397 at `method = 'text_layer'` (03:470-472).

    `table_score` is the mean of **that page's** `table_meta.recon_score` values, or NULL and
    excluded from the mean (03:474). `ocr_error_score` is the SCORE surya publishes, not the
    label surya derives from it.

    **`w_mpt`/`h_mpt` are NOT validated against `page_kind`, and that is a reported conflict.**
    03:470 says they are "NULL exactly when `page_kind == STREAM`", but 03:2273 -- section 12.5's
    own page-kind table -- says a `sheet` is "NULL unless the sheet has a print area", and
    04-driver-system.md:2259 and 18-api-sketch.md:2047 both print a `stream` page fragment
    carrying `"w_mpt": 0, "h_mpt": 0`. Three sites against one sentence, and enforcing the
    biconditional would refuse both a spreadsheet with no print area and every stream fragment
    the plan prints. Recorded and reported rather than guessed at.

    `status` is a bare `str` and gets no membership check: 03:418 prints it as `str`, not a
    `Literal`, and the DDL gives the column `DEFAULT 'ok'` and no CHECK -- unlike `doc.status`.
    The asymmetry is the plan's.

    **`producer_id` is not a field.** The DDL makes `page.producer_id` NOT NULL with no default
    ("page segmentation owner"), and `PageRecord` is the driver-facing half of the row exactly as
    `BlockDraft` is the driver-facing half of `block`: the runner stamps provenance and the driver
    never does (03 section 2.10's `add_block` row stamps `producer_id`; its `begin_page` row says
    only "inserts the `page` row"). So `DocSink.begin_page` must obtain it from the resolved
    candidate rather than from this record, and that is reported, because `begin_page`'s printed
    signature (03:559) takes the record and nothing else.
    """

    page: int
    page_kind: PageKind
    label: str | None
    w_mpt: int | None
    h_mpt: int | None
    rotation: int
    quad_origin: Literal["topleft", "bottomleft"] | None
    method: Method
    status: str
    ocr_error_score: float | None = None
    parse_score: float | None = None
    layout_score: float | None = None
    table_score: float | None = None
    ocr_score: float | None = None
    stats: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        """Refuse a `quad_origin` the column's CHECK would refuse.

        NULL is legal and is not "unset": it records that the driver declared no coordinate
        frame, which is the case for every driver with no geometry at all.
        """
        if self.quad_origin is not None:
            _refuse_member(self.quad_origin, QUAD_ORIGINS, "PageRecord.quad_origin", _PAGE_FIX)


# ---------------------------------------------------------------------------
# 5. Assets -- the draft that goes in, the ref that comes out. 03:426-436.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)  # Extends the charter.
class AssetDraft:
    """What a driver hands `DocSink.add_asset(a, blob)`. 03 section 2.8; 03 section 11's rules.

    A **draft**, in the sense `BlockDraft` is one: it carries everything except what the host
    mints. Three `asset` columns are therefore absent by design -- `asset_id` (the surrogate),
    `doc_ord` (the document scope, assigned by `begin_doc`) and `store_ref` (the
    `cas://ab/cd/<sha256>` locator, which only the CAS writer can produce). `restriction_bits` is
    absent too and is **stamped from the producing card**, propagating to every derived item
    (INV-16); the column defaults to 0.

    `add_asset` **hashes the stream itself** and raises `OW_ASSET_DIGEST_MISMATCH` when the stream
    disagrees with the `sha256` here (03 section 2.10), so this field is a claim the store
    verifies rather than trusts. Dedup is on `(doc_ord, sha256, IFNULL(origin_part, ''))`, which
    is why `origin_part` is part of an asset's identity and not decoration.

    `origin_part` is anydoc's `origin_part`, unique in the collection: the named byte stream of
    the original container this asset came out of. Non-NULL is what `Capabilities.asset_origin`
    is derived from -- `EXISTS(... WHERE origin_part IS NOT NULL)`, 03:521.

    The five licence fields are nullable and carried per asset rather than per document, because
    an embedded image's licence is frequently not the document's. `retrieved_at_ns` is a wall
    clock **the caller reads**: `time.time` is banned in library code, so a value type takes the
    clock as data and never reads it.

    **NO INLINE BYTES, EVER** (03 section 11): the bytes live in the CAS under
    `.omniweave/cas/ab/cd/<sha256>` and this record carries only their digest and length.
    """

    media_type: str
    sha256: bytes
    byte_len: int
    origin_part: str | None = None
    width: int | None = None
    height: int | None = None
    licence: str | None = None
    licence_url: str | None = None
    spdx: str | None = None
    source_url: str | None = None
    retrieved_at_ns: int | None = None


@dataclass(frozen=True, slots=True)  # Extends the charter.
class AssetRef:
    """A stored asset as a reader sees it. 03:434-436; `Doc.asset(ref)` takes one (03:2597).

    The READ projection of `asset`, and so the mirror of `AssetDraft`: it carries the three
    columns a draft cannot (`asset_id`, `store_ref`, `restriction_bits`) and drops the five
    licence-provenance columns plus `origin_part`, which a byte reader has no use for. `doc_ord`
    is not on it either -- a ref is resolved through a `Doc`, which already knows its document.

    `store_ref` is the `cas://ab/cd/<sha256>` locator and the column is `NOT NULL` even when the
    bytes were not retained: `Capabilities.assets == "refs"` is precisely the case of "rows with
    `store_ref` pointing at bytes we did not retain" (03:519), and `"bytes"` is the case where
    they are there.

    `restriction_bits` is the 32 reserved licence codes propagated from the producing card to
    every derived item (INV-16), so a consumer holding a ref holds the restrictions with it and
    cannot reach the bytes without them.

    No field has a default: all eight are read out of a row that exists.
    """

    asset_id: int
    media_type: str
    sha256: bytes
    byte_len: int
    width: int | None
    height: int | None
    store_ref: str
    restriction_bits: int


# ---------------------------------------------------------------------------
# 6. `Rel` -- the closed intra-document DAG. 03:438-442.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)  # Extends the charter.
class Rel:
    """One `rel` row: a typed edge between two Blocks. **Containment is NOT here.**

    03 section 2.8; the DDL is 03 section 13.1's `CREATE TABLE rel`. The containment spine is
    `block.parent_id` plus `block.ord`, so this table carries only the seven members of `RelKind`
    -- `caption_of`, `note_ref`, `continues`, `anchor_ref`, `heading_of`, `derived_from`,
    `supersedes` -- and `DocSink.add_rel` rejects anything outside them.

    `src`/`dst` are the field names 03:440 prints; the columns are `src_id`/`dst_id`, both FKs to
    `block(block_id)`. Two `rel` columns are not fields -- `doc_ord` and `gen`, the document scope
    the sink writes the row inside -- and one more, `x`, which the DDL defaults to `'{}'`.

    **Identity is in the schema**: `UNIQUE (src_id, dst_id, kind, producer_id)`, because without
    it `INSERT OR IGNORE` is a no-op with nothing to conflict on (the DDL says exactly that beside
    the constraint). `producer_id` is part of the identity, so two producers may both assert the
    same edge and both rows are kept.

    `score` and `score_kind` are nullable **together** -- the same rule `Block` obeys (03:308) --
    and that pairing is a CHECK on `block` but, in the shipped DDL, **not** on `rel`. `add_rel`
    takes both (03:608-612, Q11) precisely so a scored `rel` is resolvable against
    `tools/scorekinds.toml`; the pairing is enforced there and re-proved by `owcheck`, not here,
    because neither field means anything without the other's register.

    `trust` is clamped by `MAX_TRUST_BY_METHOD` at `add_rel`, after the driver returns (03 section
    8.2). This value type carries what the driver said.
    """

    src: BlockId
    dst: BlockId
    kind: RelKind
    producer_id: int
    trust: Trust
    score: float | None
    score_kind: str | None
    origin_operator: str


# ---------------------------------------------------------------------------
# 7. `Diag` -- failure is a field. 03 section 9 (:1798-1804).
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Diag:
    """A recorded diagnostic. **`Diag` is recorded; `OwError` is raised** (03:1806).

    Two names for two things, and the model's half is the recorded one. Every recoverable
    producer quirk lands here rather than in an exception -- anydoc's stated discipline, where an
    error means a complete conversion was impossible while recoverable quirks are recovered or
    skipped and the conversion continues (03:1819-1822).

    `code` is the **symbol** from `codes.toml` (`OW_TABLE_SPAN_CLAMPED`), never the numeric:
    callers branch on the symbol and the CLI prints the numeric (03:1807). `__post_init__` refuses
    a numeric with a message naming the register, because `code TEXT NOT NULL` would accept
    `"OW-M-014"` silently and `CREATE INDEX diag_code` would then index a spelling no caller
    branches on -- and that index exists specifically so the absence contract's
    `parse_gap_in_scope` gate can join against this table (03:1809-1811).

    **`block` is deliberately not a foreign key** (03:1817): a diagnostic often concerns a block
    the parse then refused to write, and a FK would force the model to choose between losing the
    diagnostic and writing a block it rejected. The column is `block_id`; the field is `block`,
    which is what 03:1801 prints.

    `fatal = True` on a `RESOURCE_LIMIT` diag makes the document's `status` `partial`, with the
    coverage gap surfacing in `corpus_card` before any query runs: **a limit breach is never
    swallowed** (03:1824). The column is `INTEGER NOT NULL` with no DEFAULT, so the field's
    `False` default is what fills it -- absent `fatal` means "not fatal", never "unknown".

    `detail` uses `field(default_factory=dict)` where every other mapping in section 2.8 uses
    `MappingProxyType({})`. Transcribed as printed; the asymmetry is the plan's and this module's
    docstring records why both are safe.

    `doc_ord` and `gen` are not fields: `DocSink.diag(d)` writes the row inside the **current
    page's** transaction, so a diagnostic about page 3,000 survives a crash at page 3,001, and the
    sink supplies the scope. Like every other staged row it is invisible until the `doc.gen` bump
    and swept if the generation is abandoned (03:1813-1815).
    """

    code: str
    severity: Literal["error", "warning", "info"]
    component: str
    message: str
    page: int | None = None
    block: BlockId | None = None
    part: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)
    fatal: bool = False

    def __post_init__(self) -> None:
        """Refuse a numeric `code`, a malformed symbol, and a `severity` the CHECK would refuse.

        The numeric case gets its own message because it is the mistake that is *plausible*: the
        numeric is the form a human reads in a CLI transcript, so it is the spelling that gets
        pasted into a `Diag`. `errors.NUMERIC_RE` and `errors.SYMBOL_RE` are the register's own
        two shapes, imported rather than retyped (INV-21).
        """
        if NUMERIC_RE.match(self.code):
            msg = (
                f"Diag.code is the codes.toml SYMBOL, not the numeric: got {self.code!r}, want "
                f"the OW_SCREAMING_SNAKE spelling (03:1807 -- callers branch on the symbol, the "
                f"CLI prints the numeric). `ow explain {self.code}` names it."
            )
            raise ModelError(msg, fix=_DIAG_FIX)
        if not SYMBOL_RE.match(self.code):
            msg = (
                f"Diag.code {self.code!r} is not a codes.toml symbol; a symbol is shaped "
                f"{SYMBOL_RE.pattern}"
            )
            raise ModelError(msg, fix=_DIAG_FIX)
        _refuse_member(self.severity, SEVERITIES, "Diag.severity", _DIAG_FIX)
