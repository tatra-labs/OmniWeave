"""`gen_incremental.py` -- G19's 300-document corpus and its 40 scripted mutations.

16-roadmap.md:550 (W4.10) is the work item: *"The `fixtures/incremental/` 300-document /
40-mutation corpus and G19 (diffing `.owdoc` **exports**)"*. This module is the corpus and the
script; `tools/incremental_index.py` drives them through a store and `tools/gate_incremental.py`
is the harness and the comparator. Three files, and each one's docstring says which of the three
it is, because `gate_incremental.py` shipped at P2 declaring in as many words that it *"is
deliberately NOT the fixture, the indexer or the rebuilder"*.

## Why the documents are PDFs, and why they are this generator's PDFs

`tools/p2_stub_parse.py` reads exactly one grammar -- classic xref table, uncompressed objects,
unfiltered content streams, the `BT`/`Tf`/`Tm`/`Tj`/`ET` operator set `gen_5000p_pdf.py` freezes --
and it is the only parser in this tree that does not need a driver system. A corpus in any other
shape would need a second parser, and a second parser is a second thing that can be wrong in the
one gate whose whole job is to decide whether two builds agree.

So a document here is assembled by `gen_5000p_pdf.write_pdf`, which W4.10 made public for exactly
this: **one home for the byte format, two corpora over it.** A document is a tuple of page INDICES
into that module's frozen content space, and `page_content(i)` is a pure function of `i`, so the
content of every document in this corpus is pinned transitively by a digest that already exists.

## A document's identity, and the conflict it is built on top of

`0001_init.sql:150` makes `doc_key` *"sha256(NORMALIZED source bytes)[:16]"*, which makes a
document's identity its content -- so an edit produces a different document. 03:1316-1370's worked
example re-parses the same `doc_ord` at `gen = 2` after the source changed, which requires the
opposite. `tools/p2_demo.py`'s clause 5 hit this first and recorded it; **this corpus takes the
same side for the same reason**, and the reason is sharper here: G19 compares two stores archive by
archive, an archive is named `{doc_key}.owdoc`, and a `doc_key` that moved when the bytes moved
would make an edited document look like a deletion plus an addition on one side and a re-parse on
the other. Both would be "different", and neither would be the divergence the gate exists to find.

`doc_key` is therefore `blake2b(uri)[:16]`: stable across an edit, different after a rename, and a
pure function of the one thing that names a document from outside the store.

## The mutation mix, and where its proportions come from

06-structure-extraction.md:2405 is the only place the plan states a mutation mix, for the smaller
graph-level gate GR8: *"60 documents, 20 shuffled steps including 3 edits, 2 deletions and 1
driver-version re-parse"*. G19's own two numbers -- 300 and 40 -- are owned by `tools/gates.toml`'s
row (01-principles.md:506) and its mix is stated nowhere, so GR8's three named kinds are scaled and
the balance is chosen to exercise every way a document can enter or leave a roster:

| kind | n | what it is for |
|---|---|---|
| `edit` | 14 | the document changes in place: same uri, new bytes, a re-parse at a new `gen` |
| `add` | 7 | a document appears that no previous step had |
| `delete` | 7 | a document leaves the roster and must leave both stores |
| `touch` | 6 | the bytes do NOT change: the step must produce no re-parse and no divergence |
| `rename` | 4 | the same bytes at a new uri -- a delete and an add that must not lose content |
| `driver_version` | 2 | every document re-parses at a bumped `op_version` (GR8's third kind) |

`touch` is the one kind GR8 does not name and it is here because it tests the other direction:
every other row asks whether the incremental build did enough work, and `touch` asks whether it did
any work it should not have. A corpus with no unchanged steps cannot tell a correct incremental
build from one that quietly rebuilds everything.

Adds and deletes are balanced at seven each, so the roster ends at the 300 it started with and the
register's number describes the corpus at both ends of the script rather than only at the start.

## The regime, which is 13-quality.md:586-589

*"`fixtures/gen/*.py`, each deterministic under `SOURCE_DATE_EPOCH=0` with `random`, `secrets`,
`uuid4`, `time.time` and `datetime.now` monkeypatched to raise."* None of the five is imported
here and none is reachable: every choice this module makes -- which pages a document holds, which
document a mutation targets, what order the script runs in -- is a `blake2b` over a literal seed
string. Output lands in `fixtures/generated/incremental/`, which is `.gitignore`d, and
`fixtures/gen/EXPECTED.sha256` pins the manifest of the initial roster.

**12-performance.md:1519 calls this fixture "committed" and 13-quality.md:588 makes every
generator's output `.gitignore`d.** The two are reconciled the way the rest of `fixtures/gen/`
already reconciles them: what is committed is the *definition* -- this module, and
`fixtures/incremental/plan.toml`, which `tools/gate_incremental.py` reads -- and what is generated
is the bytes. A reader who wants the corpus runs one command; a reviewer who wants to see it change
reads a one-line diff. Recorded as a defect rather than resolved by preference.

Run it:

    uv run python fixtures/gen/gen_incremental.py --out DIR            # the initial roster
    uv run python fixtures/gen/gen_incremental.py --out DIR --step 40  # the roster after step 40
    uv run python fixtures/gen/gen_incremental.py --plan               # print plan.toml
    uv run python fixtures/gen/gen_incremental.py --manifest --print-sha256

Specified in 16-roadmap.md:550, 01-principles.md:506, 06-structure-extraction.md:2405,
07-store-and-retrieval.md:2971, 08-runtime.md:1858, 12-performance.md:1519 and
13-quality.md:586-589.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import importlib.util
import io
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Final, Literal

__all__ = [
    "CONTENT_PAGES",
    "DOCUMENTS",
    "MIX",
    "MUTATIONS",
    "PAGES_PER_DOC",
    "SCRIPT",
    "URI_PREFIX",
    "Document",
    "Mutation",
    "corpus_at",
    "doc_key",
    "document_bytes",
    "main",
    "manifest_bytes",
    "manifest_lines",
    "plan_toml",
    "repo_root",
    "roster_digest",
    "script",
    "sha256_of",
    "write_corpus",
    "write_document",
    "write_manifest",
]

# --------------------------------------------------------------------------------------------
# The two numbers the register owns, and the three this module chooses
# --------------------------------------------------------------------------------------------

DOCUMENTS: Final = 300
"""The initial roster size. `tools/gates.toml`'s G19 assertion owns it (01-principles.md:506).

Transcribed rather than computed, on `tools/gate_incremental.py`'s own rule for the same number:
*"a harness that carried its own copy would let the two drift"*. `test_fixture_incremental.py`
asserts this against the register row, so the copy is checked rather than trusted."""

MUTATIONS: Final = 40
"""The scripted mutation count. Same owner, same check, same reason."""

PAGES_PER_DOC: Final = 1
"""Pages per document. THIS module's choice, and a MEASURED budget decision.

`gen_5000p_pdf`'s page is 64 Blocks -- one heading, eight paragraphs, one table and its 54 cells --
so one page is already a document with real structure to diverge over: a container tree three deep,
a table with 54 cells, and text blocks whose `OriginBytes` point at real offsets.

Two was the first choice and the 40-step gate measured **390 s** with it, against the 420 s budget
`tools/gates.toml` gives the `incremental` job -- seven per cent of headroom on the machine that
took the measurement, and none at all on a slower runner. The cost is dominated by the two
`driver_version` mutations, which re-parse all 300 documents and which measured **160 s each**,
because a re-parse runs `rebind()` and costs roughly fifteen times a first parse (filed as D189).
Halving the document halves that term. One page buys the budget back and loses no kind of
divergence two pages could express: nothing in the fixture varies BY page, because a document's
pages are independent draws from one content space."""

CONTENT_PAGES: Final = 5_000
"""The index space `gen_5000p_pdf.page_content` covers: the pool a document draws its pages from.

Not a page count of anything: it is `gen_5000p_pdf.DEFAULT_PAGES`, the largest index that module's
own fixture exercises and therefore the largest one pinned by `EXPECTED.sha256`. Drawing beyond it
would put content in this corpus that no digest covers."""

URI_PREFIX: Final = "corpus://incremental/"
"""Every document's uri stem. A scheme with no filesystem behind it, deliberately.

The corpus is written to a temporary directory by whoever runs the gate and a `file://` uri would
make `doc.uri` -- which is exported in every manifest and therefore compared by G19 -- a function
of that directory. Two runs on two machines would then differ for a reason that is not a
divergence. `05-ingest-and-routing.md` makes a unit's uri the connector's business and imposes no
scheme, so a stable synthetic one is the honest choice."""

MIX: Final[Mapping[str, int]] = {
    "edit": 14,
    "add": 7,
    "delete": 7,
    "touch": 6,
    "rename": 4,
    "driver_version": 2,
}
"""The 40 mutations by kind. The module docstring's table carries the argument for each row."""

_SEED: Final = "omniweave/gen_incremental/1"
"""The one seed every deterministic choice in this module is derived from.

One literal and not five: a per-decision seed is a per-decision opportunity for two of them to
collide, and a single namespace with a distinct suffix per question cannot. Version `1` is part of
it because a change to any derivation is a change to the corpus, and a corpus change must be
visible as a digest change rather than inferred from a diff."""

Kind = Literal["edit", "add", "delete", "touch", "rename", "driver_version"]


def _draw(question: str, modulus: int) -> int:
    """A deterministic integer in `[0, modulus)`, from `blake2b` over the seed and the question.

    `blake2b` and not `hash()`: 12-performance.md:1546 makes `blake2b(work_id ‖ salt)` the
    framework's own sampling primitive and states the rule this obeys -- *"No RNG on the statistics
    path"* -- and Python's `hash()` is salted per process, which would make this corpus a function
    of the interpreter that generated it.
    """
    digest = hashlib.blake2b(f"{_SEED}/{question}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") % modulus


# --------------------------------------------------------------------------------------------
# A document
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Document:
    """One document of the corpus at one step of the script.

    `slot` is the identity that survives an edit and a rename; `uri` is what the store sees and is
    what `doc_key` is derived from. The two are separate because a rename changes one and not the
    other, and the gate's hardest case is a rename: the same content has to leave one archive and
    arrive in another without any of it going missing in between.
    """

    slot: int
    revision: int
    renames: int = 0

    @property
    def uri(self) -> str:
        """`corpus://incremental/doc-000017` -- plus a suffix once the document has been renamed.

        The suffix rather than a fresh slot number, so a reader of a failing diff can see that
        `doc-000017-r1` is what `doc-000017` became. A rename that reused the numbering would make
        the report say a document appeared and another vanished, which is true of the store and
        unhelpful to the person reading it.
        """
        stem = f"{URI_PREFIX}doc-{self.slot:06d}"
        return stem if self.renames == 0 else f"{stem}-r{self.renames}"

    @property
    def contents(self) -> tuple[int, ...]:
        """The page indices this document holds, a pure function of `(slot, revision)`.

        `PAGES_PER_DOC` draws, each from the whole content space, and duplicates are allowed: two
        pages with identical content in one document is a real shape (a repeated boilerplate page)
        and refusing it would be this module inventing a corpus property nothing asked for.
        """
        return tuple(
            1 + _draw(f"page/{self.slot}/{self.revision}/{position}", CONTENT_PAGES)
            for position in range(PAGES_PER_DOC)
        )

    @property
    def title(self) -> str:
        """`/Title`, carrying the revision so an edited document differs in its info dict too.

        Belt and braces: the content streams already differ because `contents` differs. A title
        that did not move would make a document whose two draws happened to collide byte-identical
        to its own previous revision, and an `edit` that changed nothing is a step the gate would
        pass for the wrong reason.
        """
        return f"omniweave incremental {self.slot:06d} r{self.revision}"

    @property
    def id_seed(self) -> str:
        """The `/ID` seed. The uri and the revision, because those are what make a file unique."""
        return f"{_SEED}/{self.uri}/{self.revision}"


def doc_key(uri: str) -> bytes:
    """A document's 16-byte store key, from its uri and nothing else. See the module docstring.

    `blake2b` at `digest_size=16` rather than a truncated sha256, for `_draw`'s reason: this module
    derives every value it invents from one primitive, and a second one would be a second thing to
    keep in step. The width is the schema's -- `0001_init.sql:150` makes `doc_key` 16 bytes -- and
    `archive/manifest.py` refuses anything else, so it is checked on every export rather than here.
    """
    return hashlib.blake2b(uri.encode("utf-8"), digest_size=16).digest()


# --------------------------------------------------------------------------------------------
# The script
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Mutation:
    """One scripted step. `name` is what `fixtures/incremental/plan.toml` records and the harness
    reads back.

    A `driver_version` mutation names no slot, because it targets the whole corpus: 06:2405's
    *"1 driver-version re-parse"* is a re-parse of everything at a bumped `op_version`, which is
    what the invalidation matrix calls a driver upgrade (08-runtime.md section 4.8).
    """

    kind: Kind
    slot: int = -1
    name: str = ""

    def labelled(self) -> Mutation:
        """The same mutation with `name` filled in. `kind:slot`, or `kind` alone when slot is -1."""
        label = self.kind if self.slot < 0 else f"{self.kind}:{self.slot:06d}"
        return replace(self, name=label)


def _kinds() -> tuple[Kind, ...]:
    """The 40 kinds in a deterministic shuffled order. GR8's *"20 shuffled steps"*, at G19's size.

    Shuffled rather than grouped, and that is the point of the word: forty edits followed by seven
    deletes would never exercise a delete of a document an edit had already moved to a second
    generation, which is precisely where a stale head survives a rebuild. The shuffle is a
    Fisher-Yates over `_draw`, so it is a pure function of `_SEED` and reproduces on every machine.
    """
    deck: list[Kind] = []
    for kind, count in MIX.items():
        deck.extend([kind] * count)  # type: ignore[list-item]
    for index in range(len(deck) - 1, 0, -1):
        swap = _draw(f"shuffle/{index}", index + 1)
        deck[index], deck[swap] = deck[swap], deck[index]
    return tuple(deck)


def script() -> tuple[Mutation, ...]:
    """The 40 mutations, each bound to a document that exists when its step runs.

    **Targets are chosen against the LIVE roster, one step at a time**, which is why this is a walk
    and not a table. A delete of a document a previous delete already removed is not a mutation, and
    a script that contained one would be a script whose 40 steps were not 40 mutations. The live set
    is kept sorted so the choice is a function of the corpus state rather than of dict ordering.
    """
    live: list[int] = list(range(DOCUMENTS))
    revisions: dict[int, int] = dict.fromkeys(live, 0)
    renames: dict[int, int] = dict.fromkeys(live, 0)
    next_slot = DOCUMENTS
    out: list[Mutation] = []

    for step, kind in enumerate(_kinds()):
        if kind == "driver_version":
            out.append(Mutation(kind).labelled())
            continue
        if kind == "add":
            out.append(Mutation(kind, next_slot).labelled())
            live.append(next_slot)
            revisions[next_slot] = 0
            renames[next_slot] = 0
            next_slot += 1
            continue
        target = live[_draw(f"target/{step}", len(live))]
        out.append(Mutation(kind, target).labelled())
        if kind == "delete":
            live.remove(target)
        elif kind == "edit":
            revisions[target] += 1
        elif kind == "rename":
            renames[target] += 1
    return tuple(out)


SCRIPT: Final[tuple[Mutation, ...]] = script()
"""The 40 mutations, computed once. A module-level constant because it is a pure function of
`_SEED` and every consumer -- `corpus_at`, `plan_toml`, the harness -- must see the same one."""


def corpus_at(step: int) -> tuple[Document, ...]:
    """The roster after the first `step` mutations. `step = 0` is the initial 300.

    Returns documents sorted by uri, which is the order `export_portable` does NOT use -- it orders
    by `doc_key` -- and that difference is deliberate: an ingest order that is a function of the uri
    and an export order that is a function of the key means the gate compares two stores that
    agreed on neither, so an ordering bug cannot be hidden by both sides making it.
    """
    if not 0 <= step <= len(SCRIPT):
        message = f"step must be in [0, {len(SCRIPT)}], got {step}"
        raise ValueError(message)
    live: dict[int, Document] = {slot: Document(slot=slot, revision=0) for slot in range(DOCUMENTS)}
    for mutation in SCRIPT[:step]:
        if mutation.kind in ("driver_version", "touch"):
            continue
        if mutation.kind == "add":
            live[mutation.slot] = Document(slot=mutation.slot, revision=0)
        elif mutation.kind == "delete":
            live.pop(mutation.slot, None)
        elif mutation.kind == "edit":
            current = live[mutation.slot]
            live[mutation.slot] = replace(current, revision=current.revision + 1)
        elif mutation.kind == "rename":
            current = live[mutation.slot]
            live[mutation.slot] = replace(current, renames=current.renames + 1)
    return tuple(sorted(live.values(), key=lambda document: document.uri))


def driver_version_at(step: int) -> int:
    """`op_version` after the first `step` mutations: 1, plus one per `driver_version` step.

    The version is a property of the SCRIPT and not of the store, so both the incremental build and
    the full rebuild read it from here. A rebuild that used a different version would re-parse at a
    different `producer` row and every archive would differ in its `producers` list -- a difference
    that is real, and that says nothing about whether the two builds converged.
    """
    return 1 + sum(1 for mutation in SCRIPT[:step] if mutation.kind == "driver_version")


# --------------------------------------------------------------------------------------------
# Bytes
# --------------------------------------------------------------------------------------------


@functools.cache
def _generator() -> ModuleType:
    """`fixtures/gen/gen_5000p_pdf.py`, loaded by path and loaded ONCE.

    The same mechanism `tools/p2_demo.py` uses and for the same two reasons it gives: `fixtures/`
    is not a distribution, so there is nothing to import; and `importlib.import_module` is banned
    outside `host/` while a `sys.path` mutation leaks into everything loaded afterwards.

    `functools.cache` because `document_bytes` is called once per document per step and a full
    G19 run calls it thousands of times: re-executing a module body per call measured 1 ms each,
    which is four seconds of a 420 s budget spent re-importing one file. The cache is keyed on no
    arguments, so it is a module-scope memo of a pure load rather than state about a run.
    """
    path = Path(__file__).resolve().parent / "gen_5000p_pdf.py"
    spec = importlib.util.spec_from_file_location("omniweave_fixture_gen_5000p_pdf", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- a broken checkout.
        message = f"cannot load {path}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def document_bytes(document: Document) -> bytes:
    """One document's PDF, in full. A pure function of the `Document` and nothing else."""
    buffer = io.BytesIO()
    _generator().write_pdf(
        buffer,
        document.contents,
        title=document.title,
        id_seed=document.id_seed,
    )
    return buffer.getvalue()


def write_document(directory: Path, document: Document) -> Path:
    """Write one document into `directory` as `<slot>-r<revision>.pdf` and return the path.

    Named by slot and revision rather than by uri, because a uri is not a filename -- and because a
    runner that writes two revisions of one document into the same directory is writing two files,
    which is what a re-parse reads.
    """
    directory.mkdir(parents=True, exist_ok=True)
    suffix = "" if document.renames == 0 else f"-n{document.renames}"
    path = directory / f"{document.slot:06d}-r{document.revision}{suffix}.pdf"
    path.write_bytes(document_bytes(document))
    return path


def write_corpus(directory: Path, documents: Sequence[Document]) -> tuple[Path, ...]:
    """Write every document of one roster. Returns the paths, in the roster's own order."""
    return tuple(write_document(directory, document) for document in documents)


def manifest_lines(documents: Sequence[Document]) -> Iterator[str]:
    """One `sha256  uri` line per document, sorted by uri. The pinnable projection of a roster.

    A roster is 300 files and `EXPECTED.sha256` is a line-oriented file of individual digests, so
    what gets pinned is this manifest rather than the corpus: one line in the pin file covering
    every byte of 300 documents, and a corpus change is still a one-line visible diff.
    """
    for document in sorted(documents, key=lambda d: d.uri):
        yield f"{hashlib.sha256(document_bytes(document)).hexdigest()}  {document.uri}"


def roster_digest(documents: Sequence[Document]) -> str:
    """`sha256` over the manifest bytes. The number `write_manifest`'s file hashes to."""
    return hashlib.sha256(manifest_bytes(documents)).hexdigest()


def manifest_bytes(documents: Sequence[Document]) -> bytes:
    """The manifest as it is written: ASCII, LF, one trailing newline.

    Written as bytes rather than text because the pin is a digest: a checkout that translated line
    endings would produce a file that hashes differently on Windows than on the runner that pinned
    it, which is the one failure a pin exists to prevent.
    """
    return "".join(f"{line}\n" for line in manifest_lines(documents)).encode("ascii")


def write_manifest(directory: Path, documents: Sequence[Document], *, step: int) -> Path:
    """Write `roster-step<N>.manifest` and return its path. What `EXPECTED.sha256` pins.

    A roster is 300 files and `EXPECTED.sha256` is `sha256sum` format -- one digest and one path
    per line -- so pinning the corpus directly would be 300 lines that all turn over whenever the
    generator changes. One manifest covers every byte of all 300 transitively, keeps the pin at
    one line, and keeps `sha256sum -c fixtures/gen/EXPECTED.sha256` working unchanged.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"roster-step{step}.manifest"
    path.write_bytes(manifest_bytes(documents))
    return path


def sha256_of(path: Path) -> str:
    """The digest `EXPECTED.sha256` pins, read back in 1 MiB chunks. `gen_5000p_pdf`'s shape."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_relative(path: Path) -> str:
    """`fixtures/generated/...`, forward-slashed. `EXPECTED.sha256` paths are workspace-relative."""
    try:
        return path.resolve().relative_to(repo_root()).as_posix()
    except ValueError:  # pragma: no cover -- an --out outside the workspace.
        return path.as_posix()


# --------------------------------------------------------------------------------------------
# `fixtures/incremental/plan.toml`
# --------------------------------------------------------------------------------------------


def plan_toml() -> str:
    """The committed plan `tools/gate_incremental.py` reads. Generated, so it cannot drift.

    `FixturePlan` wants two things -- `documents` and a `mutations` list -- and the harness checks
    both against the register. Writing it by hand would make the fixture's own description a third
    place the two numbers live; generating it from `SCRIPT` makes the plan a projection of the
    corpus, which is what `gate_incremental.py`'s `FixturePlan` docstring already says it is:
    *"a transcription of the corpus, not a second specification"*.
    """
    lines = [
        "# fixtures/incremental/plan.toml -- G19's corpus, as tools/gate_incremental.py reads it.",
        "#",
        "# GENERATED by fixtures/gen/gen_incremental.py. Do not edit: the script is a pure",
        "# function of that module's seed, and a hand edit here would describe a corpus the",
        "# generator does not produce. Regenerate with",
        "#",
        "#     uv run python fixtures/gen/gen_incremental.py --plan \\",
        "#         > fixtures/incremental/plan.toml",
        "#",
        "# 16-roadmap.md:550 (W4.10) names the directory; 01-principles.md:506 makes",
        "# tools/gates.toml's G19 row the owner of both numbers below.",
        "",
        f"documents = {DOCUMENTS}",
        "",
        "# The 40 scripted mutations, in order. `kind:slot`, or a bare kind for a corpus-wide one.",
        "# The mix is 06-structure-extraction.md:2405's three named kinds scaled from GR8, plus",
        "# three this corpus adds; gen_incremental.py's docstring carries the argument per row.",
        "mutations = [",
    ]
    lines.extend(f'  "{mutation.name}",' for mutation in SCRIPT)
    lines.append("]")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------------


def repo_root() -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {here}"
    raise RuntimeError(message)


def default_out() -> Path:
    """`<repo>/fixtures/generated/incremental/`, which is `.gitignore`d (13-quality.md:588)."""
    return repo_root() / "fixtures" / "generated" / "incremental"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gen_incremental.py",
        description="Generate G19's 300-document / 40-mutation corpus (16-roadmap.md:550).",
    )
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    parser.add_argument("--step", type=int, default=0, help="roster after this many mutations")
    parser.add_argument("--plan", action="store_true", help="print plan.toml and exit")
    parser.add_argument("--manifest", action="store_true", help="write the roster manifest")
    parser.add_argument(
        "--print-sha256", action="store_true", help="also print one EXPECTED.sha256 line"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """`python fixtures/gen/gen_incremental.py [--out DIR] [--step N] [--plan] [--manifest]`.

    `print` is banned by ruff's T20 across this repository, so every report is written to
    `sys.stdout` directly -- the same escape `gen_5000p_pdf.py` and the `tools/gate_*.py` runners
    take.
    """
    args = _parser().parse_args(argv)

    if args.plan:
        sys.stdout.write(plan_toml())
        return 0

    if not 0 <= args.step <= MUTATIONS:
        sys.stderr.write(f"gen_incremental.py: --step must be in [0, {MUTATIONS}]\n")
        return 2

    documents = corpus_at(args.step)
    out: Path = args.out if args.out is not None else default_out()

    if args.manifest:
        manifest = write_manifest(out, documents, step=args.step)
        sys.stdout.write(f"step       {args.step}\n")
        sys.stdout.write(f"documents  {len(documents)}\n")
        sys.stdout.write(f"manifest   {manifest}\n")
        if args.print_sha256:
            sys.stdout.write(f"{sha256_of(manifest)}  {_repo_relative(manifest)}\n")
        return 0

    written = write_corpus(out, documents)
    total = sum(path.stat().st_size for path in written)
    sys.stdout.write(f"step       {args.step}\n")
    sys.stdout.write(f"documents  {len(written)}\n")
    sys.stdout.write(f"bytes      {total}\n")
    sys.stdout.write(f"out        {out}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover -- the script path.
    raise SystemExit(main())
