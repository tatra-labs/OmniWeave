"""`fuzz/seeds/`, mirrored from `vendor/anydoc/fuzz/seeds/`. Write it, or check it.

Four plan sites say the corpus is mirrored and none of them says by hand:

* 11-repo-layout.md:390 -- `fuzz/  targets/  seeds/   (atheris; seeds mirrored from vendor/anydoc)`
* 13-quality.md:163 -- "`fuzz/seeds/` holds the atheris corpus, mirrored from `vendor/anydoc`"
* 04-driver-system.md:2093 -- "its seeds are mirrored into `fuzz/seeds/`"
* 14-security.md:477 -- "`fuzz/`, one target per format handler, nightly, seeded from
  `anydoc/fuzz/seeds/` -- the only defence in the collection that found bugs before shipping"

## Why a copy at all, when the bytes are already in the tree

Two reasons, and the first is the one that matters.

**A fuzzer writes, and nothing under `vendor/` may be written.** libFuzzer's *first* corpus
argument is read-write by construction -- new coverage is written back into it, `-merge=1` rewrites
it, and `-runs=0` still creates it. `vendor/anydoc/` is the artefact `vendor/anydoc/anydoc.sha256`
digests file by file, and G12 fails the build if one byte differs from the recorded upstream blob,
so a single mistyped argument would make a green fuzzing run and a red `gate_vendor.py` the same
event. The rule that removes the class of mistake rather than the instance is that a vendored path
is never passed to a fuzzer at all. `fuzz/README.md` gives the two-directory invocation
(`fuzz/corpus/<name>` writable, `fuzz/seeds/<name>` read-only) and `fuzz/corpus/` is gitignored.

**One seeds root.** A target's corpus is the mirrored half plus this repository's own -- `wire/` is
authored here, because framing is a grammar this repository owns. `fuzz/seeds/` is the one place
both live, and a target that reached across into `vendor/` for half of its inputs would make the
vendored tree a runtime input to a gate rather than an artefact under one.

**A mirror is checkable and a symlink is not.** A symlink does not survive a Windows checkout
without a developer-mode flag, does not survive an sdist, and becomes a silent copy on the first
machine that could not make one -- at which point the drift is invisible.

## Why that copy is not a second home for one fact

Because it is generated and because the generator can fail. `--check` compares the mirror against
`vendor/anydoc/fuzz/seeds/` byte for byte, both directions, and exits 1 on any drift -- so the
vendored tree is the single source and `fuzz/seeds/` is an artefact of it. That is
11-repo-layout.md:396's rule for everything under `tools/`: "either append-only against the
previous tag or generated from a declaration site". The declaration site here is the vendored
directory itself, and the provenance written into `fuzz/seeds/MIRROR.toml` comes from
`tools/vendor.toml`'s row, never re-typed.

`MIRROR.toml` records no digests. `vendor/anydoc/anydoc.sha256` already holds one per file and G12
already checks them; a second digest list would be the second home this section exists to avoid.
What `MIRROR.toml` answers is the question a reader standing in `fuzz/seeds/` actually has -- where
did these bytes come from, at what commit, under what licence, and what may I do to them.

## What the mirror does NOT bring

`vendor/anydoc/fuzz/fuzz_targets/*.rs`. Those are the twelve Rust targets 04-driver-system.md:2091
counts, they call a Rust API, and they run under `cargo +nightly fuzz`. `fuzz/targets/` holds the
Python targets over the Python surface. Same corpus, two languages, and the seeds are the only
thing both can read.

## Exit codes

`0` written, or checked and identical. `1` `--check` found drift. `2` the source is missing or the
register does not describe it.

Specified in 11-repo-layout.md sections 1.1 and 1.7 (:390, :396), 13-quality.md section 2.2
(:163-168), 04-driver-system.md section 8.2 (:2092-2094) and 14-security.md section 2.9 (:477-481).
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
REGISTER = REPO / "tools" / "vendor.toml"
ARTEFACT = "vendor/anydoc"
SOURCE = REPO / "vendor" / "anydoc" / "fuzz" / "seeds"
DEST = REPO / "fuzz" / "seeds"
MANIFEST = DEST / "MIRROR.toml"
ATTRIBUTES = DEST / ".gitattributes"

MINE = ("wire",)
"""Subdirectories of `fuzz/seeds/` this tool does not own.

`fuzz/seeds/wire/` is this repository's own corpus for `fuzz/targets/wire.py`, written by that
target's `--write-seeds`. It lives beside the mirrored corpora because a fuzzer wants one seeds
root, and it is excluded here so a mirror run never deletes it. Anything else under `fuzz/seeds/`
that is not in `vendor/anydoc/fuzz/seeds/` is drift, and `--check` says so."""

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_USAGE = 2

ATTRIBUTES_TEXT = """\
# Seed bytes are a fuzzing corpus: never EOL-convert them.
#
# The repository root sets `* text=auto eol=lf` (11-repo-layout.md section 1.9), which rewrites any
# file git decides is text. Ten of the mirrored seeds are `numfmt` format codes with no newline in
# them at all, so the rule is a no-op on today's corpus -- and that is precisely why the attribute
# has to be written rather than inferred: the first upstream seed that is text-shaped and carries a
# CR would otherwise be rewritten at checkout, and `mirror_fuzz_seeds.py --check` would then fail on
# Windows and pass on Linux for a reason that has nothing to do with the corpus.
#
# The rule covers `wire/` too, which this tool does not own -- those seeds are written by
# `fuzz/targets/wire.py --write-seeds` and are encoded frames, so `header-not-utf8` is four bytes
# that are deliberately not UTF-8 and `valid-invoke` carries a length prefix a CR would move.
#
# `vendor/anydoc/.gitattributes` carries the same line for the same reason, one layer up, and
# `packages/*/fixtures/.gitattributes` carry it for a third: bytes that are ground truth are bytes.
* -text
MIRROR.toml text eol=lf
.gitattributes text eol=lf
"""


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def artefact_row() -> dict[str, Any] | None:
    """The `vendor/anydoc` row of `tools/vendor.toml`, which is where provenance lives."""
    if not REGISTER.is_file():
        return None
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    for row in register.get("artefact", []):
        if str(row.get("path", "")) == ARTEFACT:
            return row
    return None


def source_files() -> list[Path]:
    """Every seed under the vendored corpus, path-sorted so the manifest is stable."""
    found = (path for path in SOURCE.rglob("*") if path.is_file())
    return sorted(found, key=lambda path: path.as_posix())


def mirrored_files() -> list[Path]:
    """Every file under `fuzz/seeds/` this tool owns -- excluding `MINE` and its own bookkeeping."""
    out: list[Path] = []
    for path in sorted(DEST.rglob("*"), key=lambda p: p.as_posix()):
        if not path.is_file():
            continue
        relative = path.relative_to(DEST)
        if relative.parts[0] in MINE or relative.name in {MANIFEST.name, ATTRIBUTES.name}:
            continue
        out.append(path)
    return out


def _quoted(names: list[str]) -> str:
    """A TOML array body. Built with `chr(34)` because an f-string expression may hold no
    backslash on the 3.11 floor this repository targets, and a nested escape is the usual way
    that rule is discovered."""
    quote = chr(34)
    return ", ".join(quote + name + quote for name in names)


def manifest_text(row: dict[str, Any], files: list[Path]) -> str:
    """`fuzz/seeds/MIRROR.toml`. Provenance and an inventory; deliberately no digests."""
    corpora = sorted({path.relative_to(SOURCE).parts[0] for path in files})
    total = sum(path.stat().st_size for path in files)
    lines = [
        "# fuzz/seeds/MIRROR.toml -- GENERATED by tools/mirror_fuzz_seeds.py. Do not edit.",
        "#",
        "# The atheris seed corpus, mirrored from the vendored anydoc tree (11-repo-layout.md:390,",
        "# 13-quality.md:163, 04-driver-system.md:2093, 14-security.md:477). The vendored tree is",
        "# the source; this is the WRITABLE copy, because a fuzzer writes into its corpus",
        "# directory and vendor/ is the artefact G12 digests byte for byte.",
        "#",
        "# `uv run tools/mirror_fuzz_seeds.py --check` fails on any drift. No digests are recorded",
        "# here: vendor/anydoc/anydoc.sha256 holds one per file and G12 already checks them.",
        "",
        "[mirror]",
        'source       = "' + SOURCE.relative_to(REPO).as_posix() + '"',
        'upstream     = "' + str(row.get("upstream", "")) + '"',
        'commit       = "' + str(row.get("commit", "")) + '"',
        'version      = "' + str(row.get("version", "")) + '"',
        'spdx         = "' + str(row.get("spdx", "")) + '"',
        'copyright    = "' + str(row.get("copyright", "")) + '"',
        "files        = " + str(len(files)),
        "bytes        = " + str(total),
        "corpora      = [" + _quoted(corpora) + "]",
        "",
        "# The inventory, source-relative and sorted. A file here and not in the tree, or in the",
        "# tree and not here, is drift.",
        "paths = [",
        *('  "' + path.relative_to(SOURCE).as_posix() + '",' for path in files),
        "]",
        "",
        "# Which Python target reads which corpus. `numfmt` has no Python reader and that is",
        "# not an oversight: vendor/anydoc/fuzz/README.md says its numfmt target wraps the",
        "# input in a valid styles part so mutation reaches the format-code parser, and",
        "# wrapping it is format knowledge this repository deliberately does not hold --",
        "# the drivers do. The ten numfmt seeds are mirrored because the corpus is mirrored,",
        "# and from the Python side that parser is reachable only inside a whole workbook,",
        "# which is what fuzz/seeds/xlsx/ already is.",
        "[readers]",
        'xls    = "fuzz/targets/office.py"',
        'xlsb   = "fuzz/targets/office.py"',
        'xlsx   = "fuzz/targets/office.py"',
        'numfmt = ""',
        "",
    ]
    return "\n".join(lines)


def write(row: dict[str, Any]) -> int:
    files = source_files()
    for stale in mirrored_files():
        stale.unlink()
    for path in files:
        target = DEST / path.relative_to(SOURCE)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    DEST.mkdir(parents=True, exist_ok=True)
    for directory in sorted(DEST.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if directory.is_dir() and directory.name not in MINE and not any(directory.iterdir()):
            directory.rmdir()
    # newline="\n" explicitly: 11-repo-layout.md section 1.9 rule 2, and semgrep bans a bare
    # `open(..., "w")` under tools/ for exactly this reason.
    with MANIFEST.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(manifest_text(row, files))
    with ATTRIBUTES.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(ATTRIBUTES_TEXT)
    emit("mirrored " + str(len(files)) + " seed(s) into " + DEST.relative_to(REPO).as_posix() + "/")
    return EXIT_OK


def check(row: dict[str, Any]) -> int:
    """Byte for byte, both directions, plus the two generated files."""
    drift: list[str] = []
    files = source_files()
    expected = {path.relative_to(SOURCE).as_posix() for path in files}
    present = {path.relative_to(DEST).as_posix() for path in mirrored_files()}
    drift.extend(
        f"{name} is in the vendored corpus and not in the mirror"
        for name in sorted(expected - present)
    )
    drift.extend(
        f"{name} is in the mirror and not in the vendored corpus"
        for name in sorted(present - expected)
    )
    for name in sorted(expected & present):
        # shallow=False: a same-size, same-mtime pair is exactly the drift a checkout can create,
        # and it is the only kind `filecmp` would otherwise call equal without reading a byte.
        if not filecmp.cmp(SOURCE / name, DEST / name, shallow=False):
            drift.append(f"{name} differs from the vendored bytes")
    for path, wanted in ((MANIFEST, manifest_text(row, files)), (ATTRIBUTES, ATTRIBUTES_TEXT)):
        got = path.read_text(encoding="utf-8") if path.is_file() else ""
        # CRLF-normalised, which is 11-repo-layout.md section 1.9 rule 3 for every `--check` gate.
        if got.replace("\r\n", "\n") != wanted:
            drift.append(f"{path.relative_to(REPO).as_posix()} is not what the generator writes")
    if drift:
        here = SOURCE.relative_to(REPO).as_posix()
        emit(f"mirror_fuzz_seeds: {len(drift)} drift(s) against {here}/")
        for line in drift[:20]:
            emit(f"  {line}")
        emit("  fix: uv run tools/mirror_fuzz_seeds.py")
        return EXIT_DRIFT
    emit(f"mirror ok  {len(files)} seed(s) identical to {SOURCE.relative_to(REPO).as_posix()}/")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mirror vendor/anydoc/fuzz/seeds into fuzz/seeds.")
    parser.add_argument(
        "--check", action="store_true", help="compare instead of writing; 1 on drift"
    )
    args = parser.parse_args(argv)

    if not SOURCE.is_dir():
        emit(f"mirror_fuzz_seeds: no vendored corpus at {SOURCE.relative_to(REPO).as_posix()}")
        return EXIT_USAGE
    row = artefact_row()
    if row is None:
        emit(
            f"mirror_fuzz_seeds: {REGISTER.name} has no row for {ARTEFACT!r}; "
            f"provenance would be invented"
        )
        return EXIT_USAGE
    return check(row) if args.check else write(row)


if __name__ == "__main__":
    raise SystemExit(main())
