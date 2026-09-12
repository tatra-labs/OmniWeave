"""The malformed-input generator: the one home of how this repository breaks bytes.

Two callers, and they are not the same mechanism:

* `omniweave_conform.suites.fuzz` runs it over an author's own fixtures on the author's own
  machine, as suite 11 of 12, and reports the result as `Assertion`s on a card.
* `fuzz/targets/` runs it over `fuzz/seeds/` in `--replay`, which is 16-roadmap.md:520's
  `uv run pytest ... fuzz/ -q`, and under `atheris` in the nightly job 14-security.md:477
  specifies -- where libFuzzer supplies its own mutations and this module supplies the
  starting corpus only.

They exist separately on purpose and they must agree on what "malformed" means, because a
driver that is green under one and red under the other has been told two different things by
one framework. INV-21: no second home for one fact. This is the home.

## Why the set is six, and what each one accuses the parser of

The names are the accusation, which is the point of naming them at all -- a failing
`giant_length` says where to look, and a failing `mutation #4` does not.

| name | the bug it is hunting |
|---|---|
| `truncated@0.5`, `truncated@0.05` | a read past the end of the buffer |
| `bitflip` | a checksum, CRC or magic nobody actually checks |
| `nul` | a C-string boundary reached through an FFI |
| `nested` | unbounded recursion in a container parser |
| `giant_length` | a length field read from the input and trusted |
| `empty` | the degenerate case every parser forgets |

Two truncation fractions rather than one because 0.5 lands mid-structure and 0.05 lands inside
the header, and a parser that survives one routinely dies on the other.

## What this module deliberately is not

A format-aware mutator. Every mutation here is derived from bytes the caller already had, so a
mutation of a DOCX is malformed *in DOCX* by construction and a mutation of a PDF is malformed
in PDF -- without this module knowing what either is. 04-driver-system.md:2082 asks the `fuzz`
suite for "a corpus of malformed inputs", and a kit that shipped one corpus per format would be
shipping the format knowledge the drivers exist to hold. The format-aware half is upstream's:
anydoc's twelve cargo-fuzz targets wrap `xls`, `xlsb` and `numfmt` inputs in a valid container
so mutation reaches the record parser rather than dying at the container gate
(`vendor/anydoc/fuzz/README.md`), and those are Rust targets over a Rust API.

It is also not random. Nothing here draws from a generator; `mutations(data)` is a pure
function of `data` and yields the same six in the same order every time. `random` is banned
across this workspace with the reason in the root `pyproject.toml` -- "Sampling is blake2b.
Determinism is a gate, not a habit" -- and a fuzz corpus that differed between two runs would
make a red build a coin flip, which is 13-quality.md:471's argument for `derandomize=True` on
PRs applied one layer down.

Specified in 04-driver-system.md section 8.2 row 11 (:2082, :2089-2094), 03-document-model.md
P28 (:3012), 14-security.md:477-481 and 13-quality.md:163-168.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterator

__all__ = ["MUTATION_NAMES", "NESTING_DEPTH", "TRUNCATE_FRACTIONS", "count", "mutations"]

TRUNCATE_FRACTIONS: Final = (0.5, 0.05)
"""Where to cut. 0.5 lands mid-structure, 0.05 lands inside the header."""

NESTING_DEPTH: Final = 10_000
"""Brackets deep enough to exhaust a recursive-descent parser's stack.

Ten thousand and not a hundred thousand: the input is 20 kB at this depth and 200 kB at the
next order, and a parser with no depth cap dies at both while a parser with one refuses at
both. The extra 180 kB buys nothing and is carried through every mutation of every fixture."""

MUTATION_NAMES: Final[tuple[str, ...]] = (
    *(f"truncated@{fraction}" for fraction in TRUNCATE_FRACTIONS),
    "bitflip",
    "nul",
    "nested",
    "giant_length",
    "empty",
)
"""Every name `mutations()` can yield, in order.

`bitflip` is conditional on a non-empty input, so this is the *vocabulary* and not the count.
A caller that needs the count must call `count()`, which generates -- see its docstring for the
off-by-one this exists to prevent."""


def mutations(data: bytes) -> Iterator[tuple[str, bytes]]:
    """The six, as `(name, bytes)`. Pure, ordered, and the same every time.

    `bitflip` is skipped for a zero-byte input because there is no byte to flip, which is the
    one place the yielded count is not `len(MUTATION_NAMES)`.
    """
    for fraction in TRUNCATE_FRACTIONS:
        cut = max(0, int(len(data) * fraction))
        yield f"truncated@{fraction}", data[:cut]
    if data:
        index = len(data) // 2
        flipped = bytearray(data)
        flipped[index] ^= 0xFF
        yield "bitflip", bytes(flipped)
    yield "nul", data[: len(data) // 2] + b"\x00" * 64 + data[len(data) // 2 :]
    yield "nested", b"[" * NESTING_DEPTH + b"]" * NESTING_DEPTH
    yield "giant_length", b"\xff\xff\xff\x7f" + data
    yield "empty", b""


def count(data: bytes) -> int:
    """How many mutations `data` actually yields.

    It generates rather than multiplying, and that is the whole reason the function exists: a
    hand-written `len(MUTATION_NAMES) * len(fixtures)` is off by one for every zero-byte input,
    and the assertion it feeds then fails for a reason that is about arithmetic rather than
    about the driver. It did, in `suites/fuzz.py`, before this was extracted.
    """
    return sum(1 for _ in mutations(data))
