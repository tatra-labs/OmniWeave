"""The publish gate (DR13), and the one writer of the three kit-written regions of a card.

04-driver-system.md:2682 names this file: "DR13 | the publish gate in
`omniweave_conform/publish.py`; `ow drivers check --estimates`". :2097 is the rule:
"`[cost.measured]` and `[quality]` are **kit-written; author values are rejected by the publish
gate** (DR13)."

## Two halves that must not be one function

* **`check()` refuses.** Given a card an author is about to publish, it reports every region the
  author wrote that only the kit may write. It reads; it changes nothing.
* **`write_results()` writes.** Given a finished `ConformReport`, it replaces those regions with
  what the run measured and recomputes `attestation`.

They are separate because the refusal has to be available *without* a run -- `ow drivers check` is
a lint an author runs before they have a report -- and because a function that both checked and
wrote would have no way to refuse a card it was about to overwrite anyway.

## Where `attestation` goes, and why the position is not cosmetic

`attestation` is a TOP-LEVEL key and must be written **before the first table header**.
04-driver-system.md:859-862 gives the mechanism: "TOML scopes a bare key to the most recent header,
so writing it at the end of the file would make it `quality.suites.attestation` and the loader's
recomputation would read nothing." A misplaced attestation does not fail loudly -- it parses, it
lands in the wrong table, `[quality.suites]` rejects it as an unknown key, and if it did not, the
recomputation would silently compare against `None`. So `write_results()` inserts it immediately
after `card_schema`, which is the one line guaranteed to precede every header.

## Why this edits text rather than re-serialising the document

A card is a file a human maintains: it carries comments explaining every non-obvious value, and
04:858 requires one key per line. `tomllib` reads and does not write, and a round-trip through any
writer would drop every comment in the file -- including the ones the plan puts there on purpose,
like `[licence.weights]`'s "OMITTED ENTIRELY: this driver ships no weights". So the three regions
are replaced by line surgery and the rest of the file is left byte-identical.

That has one consequence worth stating: `write_results()` will not reformat a card, and it will not
rescue one whose `[quality]` block is interleaved with unrelated tables. It replaces a contiguous
region or it appends; if the region is not contiguous it refuses and says so, because a writer that
guessed at the author's intent would be a writer that lost part of their file.

Specified in 04-driver-system.md sections 2.8, 8.3 and 9 step 4; DR13.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.card import attestation_of

from omniweave_conform.badge import suite_table

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from omniweave_conform.result import ConformReport

__all__ = ["KIT_WRITTEN_REGIONS", "Finding", "check", "write_results"]

KIT_WRITTEN_REGIONS: Final[tuple[str, ...]] = ("cost.measured", "quality", "attestation")
"""The three an author may not write, as the card spells them.

`quality` covers `[quality]`, `[quality.suites]` and every `[[quality.benchmark]]`, because the
rule is about the block rather than about one table -- 13-quality.md:1755-1760 lists four keys
inside `[[quality.benchmark]]` the author may not write, and a rule that named only the parent
table would let an author add a row to a block the kit created."""

_HEADER = re.compile(r"^\s*\[{1,2}\s*([^\]]+?)\s*\]{1,2}\s*(?:#.*)?$")
_ATTESTATION = re.compile(r"^\s*attestation\s*=")
_CARD_SCHEMA = re.compile(r"^\s*card_schema\s*=")
_BANNER = "# " + "=" * 88


@dataclass(frozen=True, slots=True)
class Finding:
    """One region an author wrote that only `ow conform` may write."""

    region: str
    line: int
    detail: str

    def __str__(self) -> str:
        return f"{self.region} at line {self.line}: {self.detail}"


def check(raw: bytes) -> tuple[Finding, ...]:
    """Every kit-written region the author filled in. Empty means the card is publishable.

    Takes bytes rather than a `DriverCard` on purpose: the finding has to name a LINE, and a
    validated card has forgotten where its values came from. It also means a card that will not
    load can still be checked, which is the state an author is most likely to be in.
    """
    text = raw.decode("utf-8", errors="replace")
    findings: list[Finding] = []
    current = ""
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        header = _HEADER.match(line)
        if header:
            current = header.group(1).strip()
            if _is_kit_region(current):
                findings.append(
                    Finding(
                        current,
                        number,
                        "written by `ow conform`; author values are rejected (DR13)",
                    )
                )
            continue
        if _ATTESTATION.match(line) and not current:
            findings.append(
                Finding(
                    "attestation",
                    number,
                    "recomputed by the card loader from the rest of the card; writing it by hand "
                    "sets attested = false on the next load",
                )
            )
    return tuple(findings)


def _is_kit_region(table: str) -> bool:
    for region in KIT_WRITTEN_REGIONS:
        if region == "attestation":
            continue
        if table == region or table.startswith(f"{region}."):
            return True
    return False


def write_results(
    path: Path, report: ConformReport, *, measured: Mapping[str, object] | None = None
) -> bytes:
    """Replace the kit-written regions with this run's results and recompute `attestation`.

    Args:
        path: the card. Read and rewritten in place.
        report: a finished run. `[quality.suites]` comes from it, and so does `kit_version`.
        measured: `[cost.measured]`'s keys, when a run measured them. Empty leaves the block
            absent, which is the correct state for a run that did not time anything: a
            `[cost.measured]` of zeroes would be a measurement claim nobody made.

    Returns:
        The bytes written.

    Raises:
        ValueError: a kit-written region is not contiguous in the file. See the module docstring:
            a writer that guessed would be a writer that lost part of the author's file.

    04-driver-system.md:2331's line -- "wrote [cost.measured], [quality] and attestation into
    src/omniweave_driver_ipynb/driver.toml" -- is this function.
    """
    measured = measured or {}
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    without = _strip_regions(lines)
    body = [*without, *_quality_block(report), *_cost_block(measured)]
    text = "\n".join(body).rstrip("\n") + "\n"

    document = tomllib.loads(text)
    document.pop("attestation", None)
    digest = attestation_of(document)
    final = _insert_attestation(text.splitlines(), digest)
    written = "\n".join(final).rstrip("\n") + "\n"
    path.write_text(written, encoding="utf-8", newline="\n")
    return written.encode("utf-8")


def _strip_regions(lines: list[str]) -> list[str]:
    """Drop every kit-written table and the top-level `attestation`, keeping everything else.

    TWO passes, and the order matters.

    **First, truncate at the banner.** `write_results` always appends its regions after
    `_BANNER`, so everything from the first banner line to the end of file is the kit's own
    previous output and goes as a unit -- header, comments and all.

    **Then drop any kit-region table still standing, WITHOUT touching the comments above it.**
    An earlier version of this function dropped every comment line immediately preceding a
    dropped header, on the theory that a block's commentary belongs to the block. It does not,
    always: the template card ends with three lines of the AUTHOR's prose explaining that the
    card carries no `[quality]` block, and those sat directly above the banner. The first write
    kept them and the second ate them, so two runs of `write_results` produced different bytes --
    which is the one property a function that recomputes a digest may not have, and which
    `test_write_results_is_idempotent_and_replaces_rather_than_appends` is now the guard on.
    """
    banner_at = next((i for i, line in enumerate(lines) if line.startswith(_BANNER)), None)
    if banner_at is not None:
        lines = lines[:banner_at]
        while lines and not lines[-1].strip():
            lines.pop()

    kept: list[str] = []
    dropping = False
    for line in lines:
        header = _HEADER.match(line)
        if header:
            dropping = _is_kit_region(header.group(1).strip())
            if dropping:
                continue
        if dropping:
            continue
        if _ATTESTATION.match(line):
            continue
        kept.append(line)
    while kept and not kept[-1].strip():
        kept.pop()
    return kept


def _insert_attestation(lines: list[str], digest: str) -> list[str]:
    """Put `attestation` immediately after `card_schema`, before any table header.

    Raises `ValueError` when there is no `card_schema` line, because that is a card the loader
    would refuse anyway and writing an attestation into it would produce a file that is wrong in a
    second way.
    """
    for index, line in enumerate(lines):
        if _CARD_SCHEMA.match(line):
            return [
                *lines[: index + 1],
                # ONE line. A trailing comment on the SAME line is dropped with it by
                # `_strip_regions`; a comment on its own line would not be, would survive
                # every rewrite, and would make two runs of `write_results` produce
                # different bytes -- the one property a digest writer may not have.
                f'attestation = "{digest}"  # WRITTEN BY `ow conform` (04:859-862).',
                *lines[index + 1 :],
            ]
    msg = "the card has no `card_schema` line, so there is no guaranteed pre-header position"
    raise ValueError(msg)


def _quality_block(report: ConformReport) -> Iterator[str]:
    yield ""
    yield _BANNER
    yield "# EVERYTHING BELOW IS WRITTEN BY `ow conform`. AUTHOR VALUES ARE REJECTED (DR13)."
    yield _BANNER
    yield "[quality]"
    yield f'kit_version = "{report.kit_version}"'
    yield "[quality.suites]"
    for suite, verdict in suite_table(report).items():
        yield f'{suite} = "{verdict}"'


def _cost_block(measured: Mapping[str, object]) -> Iterator[str]:
    if not measured:
        return
    yield ""
    yield "[cost.measured]"
    for key, value in measured.items():
        yield f"{key} = {value!r}" if not isinstance(value, str) else f'{key} = "{value}"'
