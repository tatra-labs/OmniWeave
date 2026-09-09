"""`omniweave.index.lock` -- the corpus receipt: its byte-stable format and its merge driver.

**Which lock this is.** `omniweave_core/locks.py` (11-repo-layout.md:198) is the *scoped process
lock* -- the thing that makes a second writer raise `StoreBusy` / `OW-S-016`. This module is a
different object with an unfortunately similar name: `omniweave.index.lock` is a **committed text
artefact**, one of the six config files (02-architecture.md:1168), and holds no OS lock, no
connection and no process state. Nothing here imports `locks.py` and nothing here takes a lock.

**What it is.** *"The corpus receipt: one sorted, timestamp-free line per document, ~200 B, with a
merge driver registered for that path only. A deleted line stays deleted"* (02-architecture.md:1168;
the same sentence at 01-principles.md:688, 00-vision.md:583 and glossary.md:811). It is the index's
**receipt, not the index**: the `.owstore` is a cache, is `.gitignore`d, and a tracked store is
`OW-S-060` (07-store-and-retrieval.md:3103-3104). The format and the merge semantics are fixed by
07-store-and-retrieval.md section 13.2, "Git, and the merge-driver question -- decided", at
:3099-3160; the printed fence is :3117-3118.

FORMAT (07:3117-3118, transcribed)
-----------------------------------
::

    # schema=1 scorer=1 segmenter=derive.segment.spine@3:9c1e space=bge-m3@a1b2c3/768/cosine/i8
    <doc_key hex>  <gen>  <status>  <n_blocks>  <n_segments>  <root content_digest>  <uri>

One header line, then one row per document. Seven columns separated by **two spaces**, which is what
:3118 prints; `FIELD_SEP` carries it. `uri` is last and is the only column whose value is free text,
so a two-space separator plus `maxsplit=6` is total for every `uri` a single space can appear in --
and `_escape_uri` below closes the rest.

Every column is a stored field, so the receipt is re-derivable from the store by
`ow store verify --lock` and never needs a re-parse. Each has a definition site:

* `doc_key` -- `doc.doc_key`, `BLOB NOT NULL UNIQUE`, `sha256(NORMALIZED source bytes)[:16]`, so 16
  bytes and 32 hex characters (`0001_init.sql:150`).
* `gen` -- `doc.gen`, *"the parse generation, and nothing else"* (07:2919, `0001_init.sql:158`).
* `status` -- `DocRecord.status: Literal["ok","partial","failed","skipped"]`
  (03-document-model.md:408; enforced on disk by the `CHECK` at `0001_init.sql:161`).
* `n_blocks`, `n_segments` -- the document's block and segment counts.
* `root content_digest` -- *"Its `content_digest` is the document merkle root and is the `root
  content_digest` column of `omniweave.index.lock`"*, so the `document` block's `ow128`: 16 bytes,
  32 hex characters (03-document-model.md:816, :665, :1174).
* `uri` -- `doc.uri`, `TEXT NOT NULL` (`0001_init.sql:154`), `canonical_uri`'s path/URL form.

The header's four keys are `schema`, `scorer`, `segmenter`, `space`, in the order :3117 prints them,
which is therefore the byte order. `schema` is `omniweave_core.contract.SCHEMA` -- the major alone,
as printed, not `SCHEMA_STRING`. **`scorer` is where the retrieval weights are pinned:** *"Weights
are pinned in `omniweave.index.lock`'s header line (`scorer=1`)"* (07:1500), so the header pins the
weight SET BY VERSION and does not enumerate the weights themselves; an eval run against unpinned
weights is published `UNRANKED` (07:1501, Q-G8). `segmenter` and `space` are opaque tokens owned
elsewhere (`derive.segment.spine`'s identity, and `embed_space`'s rendering at 07:2080); this module
validates their SHAPE and never their grammar, because a second grammar here would be a second home
for a fact (INV-21).

BYTE STABILITY -- what makes it true rather than usually true (01-principles.md:688)
------------------------------------------------------------------------------------
1. **Sorted by `doc_key` BYTES, never a locale collation.** `write_lock` sorts on `LockRow.doc_key`,
   the raw 16 bytes. No `locale`, no `str.casefold`, no `cmp_to_key`: the order is `bytes.__lt__`,
   which is identical on every platform and under every `LC_COLLATE`.
2. **The rendered hex is monotone in the raw bytes**, because `bytes.hex()` emits `0-9a-f` only and
   that alphabet is ASCII-monotone. So sorting the raw `doc_key`s and sorting the rendered LINES
   agree, which is what lets the streaming merge below compare column 1 as text without decoding
   it. `test_hex_order_is_the_same_total_order_as_byte_order` is the assertion.
3. **No timestamps.** Stated three times (01-principles.md:688, 02-architecture.md:489, :1168), and
   nothing here reads a clock: no `time`, no `datetime`, no injected `Clock`.
4. **LF only, UTF-8, no BOM, one trailing newline.** `write_lock` returns text whose only newline is
   LF; a caller writes it with `open(path, "w", newline="\\n", encoding="utf-8")`, which is
   11-repo-layout.md section 1.9 rule 2. `read_lock` normalises CRLF first, which is rule 3
   (11:490-493): `.gitattributes` pins `eol=lf`, but a tree checked out before that line landed
   holds CRLF, and a receipt that failed to parse for that reason would be a false alarm.
5. **No float ever reaches the file.** Every numeric column is an `int` rendered by `str()`, so
   there is no `repr(float)` to differ between builds.

THE MERGE DRIVER (07:3122-3131)
--------------------------------
The plan's four resolution rows are, exactly, the four arms of the classical three-way merge, and
`_resolve` below is those four arms in four lines:

* *"identical line on both sides | union"* -> `ours == theirs`: take it.
* *"a line present on one side and absent from base | added; take it"* -> `base == ours`: take
  `theirs`; or its mirror, `base == theirs`: take `ours`.
* *"a line present in base and absent from one side | **deleted; it stays deleted**"* -> the same
  two arms, in the case where the other side is unchanged.
* *"conflicting lines for one `doc_key` | a **real conflict** a human resolves"* -> all three
  differ: `_CONFLICT`.

**Why the ancestor is not optional.** A union driver has no third arm: it cannot tell "absent
because nobody ever had it" from "absent because someone deleted it", so it resurrects the deletion.
That is not hypothetical -- it is graphify's shipped defect, `_nx.compose(G_cur, G_oth)` at
`graphify/cli.py:2572`, *"a pure union that loads `_base_path` and never uses it"* (07:3105-3107) --
and 00-vision.md:583 names the property it throws away in one clause: **a deleted line stays
deleted**. `_resolve` reaches that answer through `base == theirs` -> take `ours`, which is why the
ancestor is a required argument here and not a courtesy one.

**Delete-versus-modify is a CONFLICT, and the plan says so twice.** 07:3128 read alone (*"present in
base and absent from one side | deleted; it stays deleted"*) would silently drop a line the other
side had just rewritten. It does not mean that, because :3106 states the defect it answers with the
scope inside the sentence -- *"A node deleted on one branch **and untouched on the other** comes
back"* -- and :3129 catches the remainder: two sides making incompatible claims about one `doc_key`
is *"a real conflict a human resolves"*. A delete and a rewrite are incompatible claims. So row 3
governs delete-versus-unchanged, row 4 governs delete-versus-modify, and `_resolve` splits them on
exactly that test. The alternative readings both lose information a human asked for: a silent delete
discards a re-parse, a silent resurrect discards a removal.

**The header is its own conflict row** (07:3130): *"the header line differs | a real conflict:
`schema`, `scorer` or `space` changed, and merging two corpora indexed by different scorers silently
is exactly the drift the header exists to catch"*.

**Whole lines are compared byte-for-byte; only column 1 is parsed.** The driver extracts `doc_key`
and otherwise treats a row as opaque text. Two reasons, either sufficient: a driver that
re-serialised would rewrite bytes it does not understand (a column a later `schema` adds), and byte
equality is exactly the relation "identical line" at 07:3126 -- parsing first would make two
spellings of one value compare equal and union a line the human should have been shown.

**Memory, and no caps.** The merge is a true streaming three-way sort-merge: `_Cursor` holds
ONE line per input, so peak memory is three lines plus whatever the caller does with the output,
independent of the number of documents. Nothing is sorted here and nothing is accumulated -- the
inputs are already sorted, and `_Cursor.advance` REFUSES a non-increasing key rather than silently
dropping rows, which is the only way a sort-merge can be wrong. This is deliberate, and it is the
second half of the graphify finding: its caps `_MERGE_MAX_BYTES = 50 MB` and
`_MERGE_MAX_NODES = 100_000` (`graphify/cli.py:2547-2548`) are *"two to three orders of magnitude
below a real corpus"* (07:3108), so *"a merge strategy that is wrong at small scale and inoperative
at large scale is not a strategy"* (07:3110). There is therefore **no cap of any kind in this
module**, and the only constant carrying a number is the conflict-marker length.

REGISTRATION -- for that path only
-----------------------------------
`GITATTRIBUTES_LINE` and `git_config_argv()` transcribe 07:3141-3146. Both name the literal path
`omniweave.index.lock` and nothing else: the plan says *"a merge driver is registered **for that
path only**"* (07:3112-3113, restated at 01-principles.md:689 and 02-architecture.md:1168), so a
glob here would widen a driver that deletes lines onto every text file in the repository.
`test_no_registration_form_mentions_a_glob` asserts it.

`-diff` on the `.gitattributes` line is deliberate, and it is NOT `binary`:

* the receipt's reviewable diff is `ow store diff`, which speaks documents -- *"these four documents
  were re-parsed and this one was removed"* (07:3155-3157) -- while `git diff` would speak in lines
  of hex, ~3 MB of them at 20,000 documents (07:3121);
* `-diff` suppresses the DISPLAY and leaves the MERGE alone, so the quiet half never makes the loud
  half quieter;
* `binary` would imply `-text` and forfeit two things the plan depends on: the `eol=lf` contract of
  11-repo-layout.md section 1.9, and git's default text merge -- the sanctioned fallback for a fresh
  clone that has the attribute and not the driver, *"safe because it is loud"*, since it writes
  conflict markers and `ow store verify --lock` refuses any file containing one with `OW-S-061`
  (07:3147-3152).

NOT HERE, and who owns it
--------------------------
`ow store lock | verify --lock | diff` are CLI verbs (07:3154) and belong to W2.7's second half.
This module is the format and the merge and nothing else: it builds no rows from a store, opens no
connection, and takes the rows as an argument. `has_conflict_markers` lives here because the
predicate is a property of the format and INV-21 gives a fact one home; the `OW-S-061` refusal that
uses it is `ow store verify --lock`'s (07:3151, 15-observability.md:1516), and **`OW-S-061` and
`OW-S-060` are both absent from `codes.toml`** -- reported, not invented here, which is why every
`StoreError` below carries the area default symbol and a `fix` rather than a numeric.

Stdlib only (INV-2, gate G1). No `sqlite3`: ruff's TID251 per-file-ignore covers `store/*.py`, so
this file COULD take it and has no use for it -- the receipt is text and the rows arrive as values.
Inside one of the nine LAZY subpackages, so `import omniweave_core` must not reach it (G17).

Tier T-SCHEMA: `omniweave.index.lock` is listed there by name (18-api-sketch.md:3133).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Final, NamedTuple

from omniweave_core.contract import SCHEMA
from omniweave_core.errors import StoreError

__all__ = (
    "CONFLICT_MARKER_LEN",
    "DOC_STATUSES",
    "DRIVER_COMMAND",
    "DRIVER_DESCRIPTION",
    "FIELD_SEP",
    "GITATTRIBUTES_LINE",
    "HEADER_KEYS",
    "HEADER_PREFIX",
    "LOCK_PATH",
    "MARKERS",
    "MERGE_DRIVER_NAME",
    "LockFile",
    "LockHeader",
    "LockRow",
    "MergeReport",
    "MergeResult",
    "git_config_argv",
    "has_conflict_markers",
    "merge_lock",
    "merge_streams",
    "parse_header",
    "parse_row",
    "read_lock",
    "write_lock",
)

# ---------------------------------------------------------------------------
# The transcribed constants. Each names the line it came from.
# ---------------------------------------------------------------------------

LOCK_PATH: Final = "omniweave.index.lock"
"""The one committed store artefact, spelled as git sees it (02-architecture.md:1168).

A repository-relative path with no directory part: the receipt sits beside `omniweave.toml` at the
project root (02-architecture.md section 8.1's six-file table), and 07:142 places it outside
`.omniweave/` for exactly that reason -- everything inside `.omniweave/` is `.gitignore`d.
"""

MERGE_DRIVER_NAME: Final = "ow-index-lock"
"""The git merge-driver name. **The plan spells it two ways and this is the ruling.**

* `07-store-and-retrieval.md` section 13.2 spells it **`owlock`** at four sites: `:3136` (prose),
  `:3141` (its own `.gitattributes` fence), `:3144` (`merge.owlock.name`) and `:3145`
  (`merge.owlock.driver`).
* `11-repo-layout.md` section 1.9 spells it **`ow-index-lock`** at three: `:473` (its own
  `.gitattributes` fence), `:496` (prose) and `:503` (`merge.ow-index-lock.driver`).

Four sites against three, so a raw count favours `owlock` -- and the count is **not** the right
tiebreaker here, because both documents are internally consistent and each prints a complete
`.gitattributes` fence. What decides it is which document OWNS the artefact.

`.gitattributes` is 11-repo-layout.md section 1.9's file. Section 1.9 is titled
*"`.gitattributes`, and why a byte-diff gate needs one"*, its fence at `:466-473` is the **only**
place in the plan that gives the file's complete contents, and the repository's committed
`.gitattributes` carries the header *"Specified verbatim in 11-repo-layout.md section 1.9"*.
07 section 13.2 owns the merge SEMANTICS -- sort-merge by `doc_key`, identical lines union, a
deleted line stays deleted -- and names the driver only in passing, while making a point about
installation. Choosing 07's spelling would mean editing the one file the plan specifies verbatim in
order to satisfy a name mentioned incidentally elsewhere.

11 also carries more operational weight for the name: `ow store git-install` writes
`merge.ow-index-lock.driver` (`:503`), and `ow doctor`'s user-visible string is
`index-lock merge driver: not installed` (`:504`).

**Why this mattered rather than being cosmetic.** Until this was fixed the committed
`.gitattributes` said `ow-index-lock` and this module said `owlock`, so the attribute named a
driver nothing registered and **the driver would never have fired** -- git would have silently
fallen back to its default text merge, which unions both sides and resurrects a deleted line. That
is the exact defect `omniweave.index.lock`'s driver exists to refuse
(`00-vision.md:583`, graphify's `nx.compose` at `graphify/cli.py:2572`). Worse,
`11:496-505` names this failure mode precisely -- *"a driver lives in the developer's `.git/config`
... so a fresh clone silently falls back"* -- and a name that matches nothing is
**indistinguishable from an uninstalled driver**, so `ow doctor` would have reported the honest
"not installed" warning and nobody would have looked further.

Nothing in the tree noticed. `test_the_gitattributes_line_is_the_one_the_plan_prints` asserted the
CONSTANT against itself and never read the committed file.
`test_the_committed_gitattributes_names_the_driver_this_module_registers` now closes that.
`_plan/_notes/build-defects.md` D20 is the finding; the erratum owed is to 07's four sites.
"""

DRIVER_DESCRIPTION: Final = "omniweave index lock sort-merge"
"""`git config merge.<name>.name`'s value, transcribed from 07:3145.

The VALUE is 07's; only the driver name is 11's. See `MERGE_DRIVER_NAME`."""

DRIVER_COMMAND: Final = "ow store merge-lock %O %A %B %L %P"
"""`git config merge.<name>.driver`'s value, transcribed from 07:3146.

Five placeholders: `%O` ancestor, `%A` ours (**and the file the driver writes**), `%B` theirs, `%L`
the conflict-marker length and `%P` the pathname. `tools/ow_merge_index_lock.py` accepts `%L` and
`%P` as optional trailing arguments for this reason -- the plan registers five, and a driver that
refused the last two would be unregisterable.
"""

GITATTRIBUTES_LINE: Final = f"{LOCK_PATH} merge={MERGE_DRIVER_NAME} -diff"
"""The committed `.gitattributes` line. The FORM is 07:3141's, the NAME is 11:473's.

`-diff` is deliberate and is not `binary`; the module docstring gives the three reasons.
"""

FIELD_SEP: Final = "  "
"""Two spaces between columns, which is what 07:3118 prints.

Column 7 (`uri`) is the only free-text column and it is LAST, so `split(FIELD_SEP, 6)` is total: a
`uri` holding single spaces (`/home/me/my report.pdf` -- `canonical_uri`'s `file` kind is a path
form and percent-encodes nothing, identity.py:82-85) round-trips untouched, and the four characters
that could not round-trip are escaped by `_escape_uri`.
"""

HEADER_PREFIX: Final = "# "
"""The header line's marker, from 07:3117. It is the ONLY line that may begin with `#`."""

HEADER_KEYS: Final = ("schema", "scorer", "segmenter", "space")
"""The header's four keys in the order 07:3117 prints them, which is therefore the byte order."""

DOC_STATUSES: Final = ("ok", "partial", "failed", "skipped")
"""`doc.status`'s closed vocabulary, from `DocRecord.status` at 03-document-model.md:408.

Not an `enum_val` domain (`0001_init.sql:363` says so); its on-disk enforcement is the `CHECK` at
`0001_init.sql:161`, and this tuple is the same four values in the same order.
"""

CONFLICT_MARKER_LEN: Final = 7
"""Git's conflict-marker length. Seven is git's default and `%L` overrides it per invocation.

The three marker strings this produces are `<<<<<<<`, `=======` and `>>>>>>>`, which are exactly the
three `ow store verify --lock` refuses on (07:3149-3151), so a longer `%L` still contains each of
them as a prefix and the refusal stays total.
"""

MARKERS: Final = ("<", "=", ">")
"""The three conflict-marker characters, in git's order: ours, separator, theirs."""

_KEY_HEX_LEN: Final = 32
"""`doc_key` is `sha256(...)[:16]` -- 16 bytes, 32 hex characters (`0001_init.sql:150`)."""

_DIGEST_HEX_LEN: Final = 32
"""`content_digest` is an `ow128`: *"32 hex chars (a 16-byte `ow128`)"*, 03-document-model.md:665.
"""

_N_COLUMNS: Final = 7
"""Seven columns at 07:3118. A row with any other count is refused rather than padded."""

_HEX_RE: Final = re.compile(r"\A[0-9a-f]+\Z")
"""LOWER-CASE hex only. `bytes.hex()` emits lower case, and accepting upper case would admit two
spellings of one digest into a file whose whole promise is that the same corpus is the same bytes.
"""

_TOKEN_RE: Final = re.compile(r"\A[!-~]+\Z")
"""A header value: one or more printable ASCII characters, no space.

Shape only. The grammars of `segmenter` (`derive.segment.spine@3:9c1e`) and `space`
(`bge-m3@a1b2c3/768/cosine/i8`, whose fields are `embed_space`'s at 07:2080) belong to their own
tables and are deliberately not re-stated here.
"""

_BACKSLASH: Final = "\\"

_URI_ESCAPES: Final = (
    (_BACKSLASH, _BACKSLASH * 2),
    ("\n", _BACKSLASH + "n"),
    ("\r", _BACKSLASH + "r"),
    ("\t", _BACKSLASH + "t"),
)
"""The four characters a `uri` may hold that one line cannot, with the backslash FIRST.

A POSIX filename may contain LF, CR and TAB, and `canonical_uri`'s `file` kind is a path form that
percent-encodes nothing, so an unescaped `uri` could end its line early and turn one document into
two rows -- which breaks "one line per document" (02-architecture.md:1168) outright. The escape is
therefore required by the format, not a convenience. Order matters on the way out and is reversed on
the way in, which is what makes the pair a bijection.
"""

_UNESCAPE: Final = {_BACKSLASH: _BACKSLASH, "n": "\n", "r": "\r", "t": "\t"}
"""`_escape_uri`'s inverse table, keyed by the character FOLLOWING the backslash."""

_FIX_LOCK: Final = "ow store lock"
"""The command that rewrites a malformed receipt from the store (07:3154).

Never empty: charter section 6.4, and `OwError.__init__` refuses an empty one.
"""

_FIX_MERGE: Final = "ow store merge-lock"
"""The command a conflict marker names (11-repo-layout.md:504)."""

_CONFLICT: Final = object()
"""`_resolve`'s fourth arm. A sentinel and not `None`, because `None` already means "absent"."""


# ---------------------------------------------------------------------------
# The values.
# ---------------------------------------------------------------------------


class LockHeader(NamedTuple):
    """The one header line: `# schema=1 scorer=1 segmenter=... space=...` (07:3117).

    `schema` is the MAJOR alone -- :3117 prints `schema=1`, not `schema=1.0` -- so it defaults to
    `contract.SCHEMA` and never to `SCHEMA_STRING`. It is the only default here, and it is last in
    the field order for that reason while `render` emits the printed order regardless: field order
    is a Python convenience, byte order is the format.
    """

    scorer: int
    segmenter: str
    space: str
    schema: int = SCHEMA

    def render(self) -> str:
        """The header line, without its newline. Byte-identical for equal fields on any machine."""
        self.validate()
        return HEADER_PREFIX + " ".join(
            (
                f"schema={self.schema}",
                f"scorer={self.scorer}",
                f"segmenter={self.segmenter}",
                f"space={self.space}",
            )
        )

    def validate(self) -> None:
        """Refuse a header that could not round-trip. Checked at RENDER time, not at construction.

        A `NamedTuple` has no `__post_init__`, and forcing one through `__new__` would make the type
        unusable as a plain tuple. Validating in `render` and in `parse_header` instead puts the
        check on both sides of the byte boundary, which is where it earns its keep.
        """
        for name, number in (("schema", self.schema), ("scorer", self.scorer)):
            if not _is_count(number):
                raise StoreError(
                    f"{LOCK_PATH}: header {name}={number!r} is not a non-negative int",
                    fix=_FIX_LOCK,
                )
        for name, token in (("segmenter", self.segmenter), ("space", self.space)):
            if not isinstance(token, str) or not _TOKEN_RE.match(token):
                raise StoreError(
                    f"{LOCK_PATH}: header {name}={token!r} is not a printable ASCII token",
                    fix=_FIX_LOCK,
                )


class LockRow(NamedTuple):
    """One document's line. Seven columns, in the order 07:3118 prints them.

    `doc_key` and `content_digest` are the RAW bytes, not their hex: the hex is a rendering and the
    bytes are the fact, so the sort key is `bytes` (see `write_lock`) and a caller reading
    `doc.doc_key` out of the store passes it straight through with no encode/decode round trip.
    """

    doc_key: bytes
    gen: int
    status: str
    n_blocks: int
    n_segments: int
    content_digest: bytes
    uri: str

    def render(self) -> str:
        """The row's line, without its newline."""
        self.validate()
        return FIELD_SEP.join(
            (
                self.doc_key.hex(),
                str(self.gen),
                self.status,
                str(self.n_blocks),
                str(self.n_segments),
                self.content_digest.hex(),
                _escape_uri(self.uri),
            )
        )

    def validate(self) -> None:
        """Refuse a row that could not round-trip, naming the column and the rule it broke."""
        _require_digest("doc_key", self.doc_key, _KEY_HEX_LEN // 2)
        _require_digest("content_digest", self.content_digest, _DIGEST_HEX_LEN // 2)
        if self.status not in DOC_STATUSES:
            raise StoreError(
                f"{LOCK_PATH}: status={self.status!r} is not one of {DOC_STATUSES}"
                " (03-document-model.md:408)",
                fix=_FIX_LOCK,
            )
        for name, number in (
            ("gen", self.gen),
            ("n_blocks", self.n_blocks),
            ("n_segments", self.n_segments),
        ):
            if not _is_count(number):
                raise StoreError(
                    f"{LOCK_PATH}: {name}={number!r} is not a non-negative int", fix=_FIX_LOCK
                )
        if not isinstance(self.uri, str) or not self.uri:
            raise StoreError(
                f"{LOCK_PATH}: uri={self.uri!r} is empty (`doc.uri` is TEXT NOT NULL)",
                fix=_FIX_LOCK,
            )


class LockFile(NamedTuple):
    """A parsed receipt: the header and the rows, in file order (which is `doc_key` byte order)."""

    header: LockHeader
    rows: tuple[LockRow, ...]

    def render(self) -> str:
        """The whole file. `read_lock(x.render()) == x` for any `LockFile` `read_lock` produced."""
        return write_lock(self.header, self.rows)


@dataclass(slots=True)
class MergeReport:
    """What a merge decided, accumulated as the streaming merge runs.

    Mutable and passed IN to `merge_streams`, because `merge_streams` is a generator: a return value
    would only exist after the caller had already consumed every line, and a driver has to know
    whether to exit non-zero before it renames its output into place.
    """

    header_conflict: bool = False
    conflicts: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        """True when nothing needs a human. This is the driver's exit-0 predicate."""
        return not self.header_conflict and not self.conflicts


class MergeResult(NamedTuple):
    """`merge_lock`'s answer: the merged text plus what it took to get there.

    `conflicts` holds the `doc_key` hex of every conflicting row, in output order, so a caller can
    name them without re-scanning the text it was just handed.
    """

    text: str
    header_conflict: bool
    conflicts: tuple[str, ...]

    @property
    def clean(self) -> bool:
        """True when the merge resolved without markers -- git's exit-0 condition."""
        return not self.header_conflict and not self.conflicts


# ---------------------------------------------------------------------------
# Rendering and parsing.
# ---------------------------------------------------------------------------


def _is_count(value: object) -> bool:
    """A non-negative `int` that is not a `bool`.

    `bool` is excluded on purpose: `True` is an `int` and would render as `1`, so a caller that
    passed a flag where a count belongs would produce a plausible receipt with a wrong number in it.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_digest(name: str, value: object, size: int) -> None:
    if not isinstance(value, bytes):
        raise StoreError(f"{LOCK_PATH}: {name}={value!r} is not bytes", fix=_FIX_LOCK)
    if len(value) != size:
        raise StoreError(f"{LOCK_PATH}: {name} is {len(value)} bytes, not {size}", fix=_FIX_LOCK)


def _escape_uri(uri: str) -> str:
    """Make a `uri` safe for one line. Backslash first; see `_URI_ESCAPES`."""
    for raw, escaped in _URI_ESCAPES:
        uri = uri.replace(raw, escaped)
    return uri


def _unescape_uri(text: str) -> str:
    """The inverse of `_escape_uri`. An undefined escape is refused, never passed through."""
    if _BACKSLASH not in text:
        return text
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != _BACKSLASH:
            out.append(char)
            index += 1
            continue
        following = text[index + 1 : index + 2]
        if following not in _UNESCAPE:
            raise StoreError(
                f"{LOCK_PATH}: uri holds the undefined escape {char + following!r}",
                fix=_FIX_LOCK,
            )
        out.append(_UNESCAPE[following])
        index += 2
    return "".join(out)


def write_lock(header: LockHeader, rows: Iterable[LockRow]) -> str:
    """Render the receipt. Same corpus, same bytes, on any machine, in any locale.

    Rows are sorted HERE rather than assumed sorted, so byte stability is a property of this
    function and not of every caller. **The sort is over `doc_key` BYTES** -- `key=lambda r:
    r.doc_key` -- and never a locale collation: `bytes.__lt__` is the same total order under every
    `LC_COLLATE`, whereas `locale.strcoll` is a different order in `de_DE` and in `C` and would make
    the receipt machine-dependent, which 01-principles.md:688 forbids in as many words.

    A duplicate `doc_key` is refused: `doc.doc_key` is `NOT NULL UNIQUE` (`0001_init.sql:150`), so
    two rows for one key is a caller bug, and silently keeping one of them would produce a receipt
    `ow store verify --lock` could never reproduce.

    The result ends in exactly one newline, so an empty corpus is the header line and nothing more.
    """
    ordered = sorted(rows, key=lambda row: row.doc_key)
    lines = [header.render()]
    previous: bytes | None = None
    for row in ordered:
        if row.doc_key == previous:
            raise StoreError(
                f"{LOCK_PATH}: two rows for doc_key {row.doc_key.hex()}"
                " (`doc.doc_key` is NOT NULL UNIQUE)",
                fix=_FIX_LOCK,
            )
        previous = row.doc_key
        lines.append(row.render())
    return "".join(line + "\n" for line in lines)


def parse_header(line: str) -> LockHeader:
    """Parse the header line. Refuses a missing key, an extra key and a reordered key.

    ORDER is checked and not merely membership: the header is a byte-stable line, so `scorer` before
    `schema` is a different file even though it carries the same facts, and a parser that accepted
    both would let two spellings of one header exist and then conflict on merge for no reason.
    """
    if not line.startswith(HEADER_PREFIX):
        raise StoreError(
            f"{LOCK_PATH}: the first line is not a header (07:3117 prints `# schema=...`)",
            fix=_FIX_LOCK,
        )
    parts = line[len(HEADER_PREFIX) :].split(" ")
    keys = tuple(part.partition("=")[0] for part in parts)
    if keys != HEADER_KEYS or not all("=" in part for part in parts):
        raise StoreError(
            f"{LOCK_PATH}: header keys are {keys}, not {HEADER_KEYS} in that order (07:3117)",
            fix=_FIX_LOCK,
        )
    values = [part.partition("=")[2] for part in parts]
    for name, value in (("schema", values[0]), ("scorer", values[1])):
        if not value.isdecimal() or not value.isascii():
            raise StoreError(
                f"{LOCK_PATH}: header {name}={value!r} is not a decimal int", fix=_FIX_LOCK
            )
    header = LockHeader(
        schema=int(values[0]), scorer=int(values[1]), segmenter=values[2], space=values[3]
    )
    header.validate()
    return header


def parse_row(line: str) -> LockRow:
    """Parse one document line. Seven columns, `maxsplit=6` so a `uri` holding spaces survives."""
    columns = line.split(FIELD_SEP, _N_COLUMNS - 1)
    if len(columns) != _N_COLUMNS:
        raise StoreError(
            f"{LOCK_PATH}: {len(columns)} columns, not {_N_COLUMNS} (07:3118)", fix=_FIX_LOCK
        )
    key_hex, gen, status, n_blocks, n_segments, digest_hex, uri = columns
    for name, value, width in (
        ("doc_key", key_hex, _KEY_HEX_LEN),
        ("content_digest", digest_hex, _DIGEST_HEX_LEN),
    ):
        if len(value) != width or not _HEX_RE.match(value):
            raise StoreError(
                f"{LOCK_PATH}: {name}={value!r} is not {width} lower-case hex characters",
                fix=_FIX_LOCK,
            )
    for name, value in (("gen", gen), ("n_blocks", n_blocks), ("n_segments", n_segments)):
        if not value.isdecimal() or not value.isascii():
            raise StoreError(f"{LOCK_PATH}: {name}={value!r} is not a decimal int", fix=_FIX_LOCK)
    row = LockRow(
        doc_key=bytes.fromhex(key_hex),
        gen=int(gen),
        status=status,
        n_blocks=int(n_blocks),
        n_segments=int(n_segments),
        content_digest=bytes.fromhex(digest_hex),
        uri=_unescape_uri(uri),
    )
    row.validate()
    return row


def has_conflict_markers(text: str) -> bool:
    """True when any line begins with a run of `<`, `=` or `>` of marker length or more.

    The predicate `ow store verify --lock` refuses on: *"refuses any file containing `<<<<<<<`,
    `=======` or `>>>>>>>` with `OW-S-061`"* (07:3149-3151). Anchored at the line start, which is
    where git writes a marker and where a `uri` cannot put one -- column 1 of a row is 32 hex
    characters, so a false positive is unrepresentable.
    """
    return any(
        line.startswith(marker * CONFLICT_MARKER_LEN)
        for line in text.splitlines()
        for marker in MARKERS
    )


def read_lock(text: str) -> LockFile:
    """Parse a whole receipt. `read_lock(write_lock(h, rows))` round-trips exactly.

    CRLF is normalised first (11-repo-layout.md:490-493 rule 3) and a trailing newline is optional,
    so a receipt written on Windows before `.gitattributes` pinned `eol=lf` still parses.

    An unresolved merge is refused rather than half-parsed: a conflict marker is not a document line
    and treating it as one would let a merge in progress be mistaken for a valid receipt, which is
    the failure `OW-S-061` exists for.

    The rows are checked to be strictly increasing in `doc_key`. A receipt that is not sorted is not
    the artefact the plan describes (01-principles.md:688), and accepting one here would let a
    hand-edited file through into the streaming merge, where an out-of-order key silently drops
    every row after it.
    """
    if has_conflict_markers(text):
        raise StoreError(
            f"{LOCK_PATH}: the file holds conflict markers -- an unresolved merge is not a"
            " receipt (07:3149-3151, OW-S-061)",
            fix=_FIX_MERGE,
        )
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise StoreError(f"{LOCK_PATH}: the file is empty; it has no header", fix=_FIX_LOCK)
    header = parse_header(lines[0])
    rows: list[LockRow] = []
    previous: bytes | None = None
    for number, line in enumerate(lines[1:], start=2):
        row = parse_row(line)
        if previous is not None and row.doc_key <= previous:
            raise StoreError(
                f"{LOCK_PATH}:{number}: doc_key {row.doc_key.hex()} does not follow"
                f" {previous.hex()}; the file is not sorted by doc_key bytes",
                fix=_FIX_LOCK,
            )
        previous = row.doc_key
        rows.append(row)
    return LockFile(header=header, rows=tuple(rows))


# ---------------------------------------------------------------------------
# Registration -- for that path only (07:3112-3113, :3141-3146).
# ---------------------------------------------------------------------------


def git_config_argv(*, command: str = DRIVER_COMMAND) -> tuple[tuple[str, ...], ...]:
    """The two `git config` invocations `ow store git-install` runs, as argv tuples.

    Transcribed from 07:3145-3146. Returned as argv rather than as a shell string because this
    module is library code and library code does not build shell commands; the caller that runs them
    is `ow store git-install`, and the one module allowed to spawn a process is `toolchain.py` (S2).

    Neither entry names a path: a merge driver is registered by NAME in `git config` and bound to a
    path by `.gitattributes`, so `GITATTRIBUTES_LINE` is the half that scopes it and it names
    `omniweave.index.lock` literally. There is no glob in either half, by construction.
    """
    return (
        ("git", "config", f"merge.{MERGE_DRIVER_NAME}.name", DRIVER_DESCRIPTION),
        ("git", "config", f"merge.{MERGE_DRIVER_NAME}.driver", command),
    )


# ---------------------------------------------------------------------------
# The three-way sort-merge.
# ---------------------------------------------------------------------------


def _row_key(line: str) -> str:
    """Column 1 of a row, validated as 32 lower-case hex characters and returned AS TEXT.

    Text and not bytes, deliberately. `bytes.hex()` emits `0-9a-f`, an ASCII-monotone alphabet, so
    the hex order and the raw byte order are the same total order -- proved by
    `test_hex_order_is_the_same_total_order_as_byte_order` -- and comparing the text keeps the merge
    free of any decode step over a column it is not otherwise parsing.
    """
    key = line.split(FIELD_SEP, 1)[0]
    if len(key) != _KEY_HEX_LEN or not _HEX_RE.match(key):
        raise StoreError(
            f"{LOCK_PATH}: {key!r} is not a {_KEY_HEX_LEN}-character lower-case hex doc_key",
            fix=_FIX_LOCK,
        )
    return key


class _Cursor:
    """One input's position: the header, plus at most ONE buffered row line.

    This is where the merge's O(1) memory comes from, and where its correctness does. `advance`
    refuses a key that does not strictly increase, because a sort-merge over an unsorted input does
    not fail -- it silently drops every row after the inversion, which is a wrong receipt that looks
    like a right one.
    """

    __slots__ = ("_lines", "_side", "header", "key", "line")

    def __init__(self, side: str, lines: Iterable[str]) -> None:
        self._side = side
        self._lines = iter(lines)
        self.header: str | None = None
        self.key: str | None = None
        self.line: str | None = None
        for raw in self._lines:
            text = raw.rstrip("\n").removesuffix("\r")
            if text == "":
                continue
            self.header = text
            break
        self.advance()

    def advance(self) -> None:
        """Load the next row line, or reach the end. Refuses a non-increasing `doc_key`."""
        previous = self.key
        for raw in self._lines:
            text = raw.rstrip("\n").removesuffix("\r")
            if text == "":
                continue
            key = _row_key(text)
            if previous is not None and key <= previous:
                raise StoreError(
                    f"{LOCK_PATH} ({self._side}): doc_key {key} does not follow {previous};"
                    " a sort-merge cannot read an unsorted receipt",
                    fix=_FIX_LOCK,
                )
            self.key, self.line = key, text
            return
        self.key, self.line = None, None

    def take(self, key: str) -> str | None:
        """The line for `key` if this input holds it, consuming it; otherwise `None`."""
        if self.key != key:
            return None
        line = self.line
        self.advance()
        return line


def _resolve(base: str | None, ours: str | None, theirs: str | None) -> str | object | None:
    """The classical three-way merge, which is 07:3126-3130's four rows in four arms.

    Returns the winning line, `None` for "the row is absent from the result" (a delete that stays
    deleted), or the `_CONFLICT` sentinel.

    Read the arms in order and the plan's table falls out:

    1. `ours == theirs` -- both sides agree, including agreeing that it is gone. Row 1, "union".
    2. `base == ours` -- our side did not touch it, so their side's answer is the only claim on the
       table. Their answer may be a line (row 2, "added; take it", when `base` is `None`) or an
       absence (row 3, "**deleted; it stays deleted**").
    3. `base == theirs` -- the mirror. This is the arm that defeats `nx.compose`: with `base` and
       `theirs` both holding a line and `ours` holding none, a union takes `theirs` and resurrects
       the row, while this returns `ours` -- which is `None` (00-vision.md:583,
       `graphify/cli.py:2572`).
    4. Otherwise all three differ -- two incompatible claims about one `doc_key`. Row 4, "a real
       conflict a human resolves". Delete-versus-modify lands here, and the module docstring says
       why that is row 4 and not row 3.
    """
    if ours == theirs:
        return ours
    if base == ours:
        return theirs
    if base == theirs:
        return ours
    return _CONFLICT


def _conflict_block(key: str, ours: str | None, theirs: str | None, marker_len: int) -> list[str]:
    """Git-standard conflict markers around one `doc_key`, naming the command that resolves them.

    The label carries `ow store merge-lock` because 11-repo-layout.md:504 requires it: *"the driver
    itself writes a conflict marker naming `ow store merge-lock` rather than resolving"*. A side
    that deleted the row contributes no line, so the reviewer sees an empty half and reads the
    deletion off the shape.
    """
    ours_label = f"ours {LOCK_PATH} {key} ({_FIX_MERGE})"
    theirs_label = f"theirs {LOCK_PATH} {key} ({_FIX_MERGE})"
    block = [f"{'<' * marker_len} {ours_label}"]
    if ours is not None:
        block.append(ours)
    block.append("=" * marker_len)
    if theirs is not None:
        block.append(theirs)
    block.append(f"{'>' * marker_len} {theirs_label}")
    return block


def merge_streams(
    base: Iterable[str],
    ours: Iterable[str],
    theirs: Iterable[str],
    *,
    report: MergeReport,
    marker_len: int = CONFLICT_MARKER_LEN,
) -> Iterator[str]:
    """The streaming three-way sort-merge. Yields output lines WITHOUT their newlines.

    Each argument is an iterable of lines -- an open text file, a `str.splitlines()`, anything. Peak
    memory is one buffered line per input plus the current output line, so there is no size cap and
    none is needed (07:3108-3110).

    `report` is filled in as the generator runs and is complete once it is exhausted. A caller that
    needs the verdict before writing must drain the generator first, which is what
    `tools/ow_merge_index_lock.py` does and why it writes to a temporary file.

    Header handling, in the order 07:3130 fixes it: an absent side contributes no header, so a side
    git handed us empty simply loses every argument; two present headers that agree pass through;
    two that disagree are a **real conflict** and both are emitted inside markers, because
    *"merging two corpora indexed by different scorers silently is exactly the drift the header
    exists to catch"*.
    """
    cursors = (_Cursor("base", base), _Cursor("ours", ours), _Cursor("theirs", theirs))
    _, ours_cursor, theirs_cursor = cursors
    yield from _merge_headers(ours_cursor.header, theirs_cursor.header, report, marker_len)
    while True:
        keys = [cursor.key for cursor in cursors if cursor.key is not None]
        if not keys:
            return
        key = min(keys)
        lines = tuple(cursor.take(key) for cursor in cursors)
        decided = _resolve(*lines)
        if decided is _CONFLICT:
            report.conflicts.append(key)
            yield from _conflict_block(key, lines[1], lines[2], marker_len)
        elif isinstance(decided, str):
            yield decided


def _merge_headers(
    ours: str | None, theirs: str | None, report: MergeReport, marker_len: int
) -> Iterator[str]:
    """Resolve the two header lines. `None` means the side was empty and claims nothing."""
    if ours == theirs or theirs is None:
        if ours is not None:
            yield ours
        return
    if ours is None:
        yield theirs
        return
    report.header_conflict = True
    label = f"{LOCK_PATH} header ({_FIX_MERGE})"
    yield f"{'<' * marker_len} ours {label}"
    yield ours
    yield "=" * marker_len
    yield theirs
    yield f"{'>' * marker_len} theirs {label}"


def merge_lock(
    base: str, ours: str, theirs: str, *, marker_len: int = CONFLICT_MARKER_LEN
) -> MergeResult:
    """`merge_streams` over three whole texts. The form a test and a small receipt both want.

    The streaming form is the one the driver uses; this one materialises the result, which is the
    only place in the module where the corpus size costs memory, and it is a convenience rather than
    the contract. A clean result re-reads through `read_lock` and re-renders to the same bytes --
    `test_a_clean_merge_of_two_large_disjoint_corpora_is_sorted_and_byte_stable` asserts it.
    """
    report = MergeReport()
    lines = list(
        merge_streams(
            base.splitlines(),
            ours.splitlines(),
            theirs.splitlines(),
            report=report,
            marker_len=marker_len,
        )
    )
    text = "".join(line + "\n" for line in lines)
    return MergeResult(
        text=text, header_conflict=report.header_conflict, conflicts=tuple(report.conflicts)
    )
