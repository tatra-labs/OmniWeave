"""Q-G1 and Q-G2: every fixture byte has a manifest row, and the bytes fit their budget. **D843.**

13-quality.md:92: *"`Q-G1` | `fixtures/index.toml` | every fixture byte has a manifest row
`{spdx, source_url, retrieved_at, sha256}`"*. :1985 names this file: *"`tools/gate_fixtures.py`
over the generated `fixtures/index.toml`; every sidecar key is `NOT NULL`-equivalent in the
generator"*. Section 4.4 (:493): *"One sidecar per file. `fixtures/index.toml` is **generated** from
the sidecars -- sorted by relpath, LF, no timestamps -- and byte-diff gated"*. Section 4.2 gives
the four admissible provenances, *"and no fifth"*, with what each must record.

This file generates the index, byte-diffs it, and holds every row to its file, following the
standing pattern (ledger D25). D844 adds Q-G2, which :1986 makes *"the same gate: 64 MB total,
256 KiB per Reduction, ≥ 40% real scans, ≤ 32 MiB of Cassettes, no orphan cassette,
`size-pack ≤ 200_000` KiB after `git gc`"*, with section 4.1's *"≤ 4 MB per binary"*.

## Rulings

1. **A fixture is a committed file under `packages/<dist>/fixtures/` or `fixtures/docs/`.** Its
   sidecar, `README.md`, `.gitattributes` and `EXPECTED.sha256` are not fixtures. Committed means
   `git ls-files`: Q-G1 is a static gate over committed bytes, and a stray file in a working copy
   is not in the corpus. The other trees under `fixtures/` are not documents a driver reads:
   - `gen/` holds the generators;
   - `generated/` is their ignored output;
   - `cassettes/` is out of scope **pending a ruling**. Section 4.7 says *"`Q-G1`'s manifest
     rule applies to it"*, but none of section 4.2's five provenances fits a recorded model
     response. A cassette is content-addressed, its name the digest of its inputs, and the
     560 committed ones have no sidecar. Bringing them in needs that provenance decided first;
   - `goldens/` holds Reductions, Q-G3's;
   - `out/` holds target goldens, and `incremental/` a plan.

   A `fixtures/` directory under `src/` ships in a wheel, so it is package data, not the corpus.
2. **A fixture's sidecar is `<file>.meta.toml` beside it, with a `[fixture]` table.** A fixture
   with no sidecar fails, and so does a sidecar with no file.
3. **A row holds its file and its provenance to account.**
   - `sha256` and `bytes` equal the file's.
   - `provenance` is one of section 4.2's five spellings: `generated`, `public_domain`, `cc0`,
     `cc_by` or `authored`.
   - `spdx` is present, and `path` is not: it is the index's own key.
   - Section 4.2's per-provenance record is present:
     - `generated`: `generator`, a committed file under `fixtures/gen/`;
     - `public_domain`: `source_url`, `retrieved_at` and `statutory`;
     - `cc0`: `source_url` and `retrieved_at`;
     - `cc_by`: those and `attribution`;
     - `authored`: `contributor` and `cla`.

   :92's four-key list is section 4.2's `public_domain` and `cc*` record in brief, and a
   `generated` fixture has no `source_url` to give. `retrieved_at` is `YYYY-MM-DD`.
4. **`NOT NULL`-equivalent means no key holds an empty value**: not `""`, `[]` or `{}`. An empty
   value is a claim that says nothing, and the generator refuses to carry one into the index.
5. **`fixtures/index.toml` is one `[[fixture]]` per sidecar.**
   - Rows are sorted by the fixture's path. Each row is `path` first, then the sidecar's keys
     sorted, with subtables after the scalars.
   - The file is LF with no timestamps, and its header names this generator.
   - The gate byte-diffs the committed file against a fresh generation, and `--write` writes it.
     A finding in a sidecar is reported whether or not the index matches.
6. **Not judged here:** the SPDX allowlist, which is Q-G7's, and `review_by`, which is Q-G17's.
   `tools/gate_gate_rot.py` (D830) already reads the sidecars for the latter.

## Q-G2's rulings (D844)

7. **Tier A is every committed byte under `fixtures/` or a `packages/<dist>/fixtures/` tree.**
   Section 4.1 writes Tier A as *"`fixtures/` -- bytes in the repository"*. The drivers'
   conformance fixtures are bytes in the repository too, under a `fixtures/` of their own, so
   the generators, cassettes, index and package fixtures all count.
8. **`MB` is a million bytes.** The same table row writes `KiB` and `MiB` where it means binary
   units, so its `64 MB` and `4 MB` are the decimal ones, which are also the stricter reading.
9. **The caps:**
   - Tier A at most 64 MB;
   - each Q-G1 fixture at most 4 MB, section 4.1's *"per binary"*;
   - each `.shape`, `.pages` or `.outline` under `fixtures/goldens/` at most
     `MAX_REDUCTION_BYTES`;
   - each committed cassette at most `MAX_CASSETTE_BYTES`, and all of them together at most
     `MAX_CASSETTE_BYTES_TOTAL`.

   The limits come from `omniweave_core.limits`, where they are declared, and are not written
   twice. The `golden` job's cassette audit (D650) holds the same two cassette caps, which
   :1986 lists here as well.
10. **The 40% scan floor is measured over `fixtures/docs/`.** With no fixture there it has
    nothing to measure, which is printed. With one, it fails closed: section 4.4's sidecar has no
    key that says a document is a scan, so the floor cannot be measured until one is ruled.
11. **`size-pack` is read after `git gc --auto --quiet`, and is at most 200,000 KiB.** Section
    4.6 calls the `gc` *"load-bearing"*. `--skip-pack` leaves the clause out for a run that must
    not touch the object store, and the report says it was left out. A pack the gate cannot
    measure means the gate did not run.
12. **Not run, and printed as not run:**
    - the orphan-cassette sweep, which reads `eval/cassette-usage.toml`, and nothing writes that
      yet;
    - the pack ratchet, which needs a recorded baseline to ratchet against.

## Exit codes

`0` every fixture has a well-formed row and the index matches. `1` a finding, named with its path
and the fix, or a budget clause is over. `2` the gate did not run: git could not list the tree, or
the pack could not be measured.

Specified in 13-quality.md sections 2.1, 4.2, 4.4 and 14.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import shutil
import subprocess  # noqa: TID251 - "committed" is git's answer, and `git` is its only reader.
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_core.limits import (  # noqa: E402
    MAX_CASSETTE_BYTES,
    MAX_CASSETTE_BYTES_TOTAL,
    MAX_REDUCTION_BYTES,
)

__all__ = [
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "INDEX",
    "MAX_BINARY_BYTES",
    "PROVENANCES",
    "SIZE_PACK_KIB",
    "TIER_A_BYTES",
    "Budget",
    "Finding",
    "budget",
    "check_row",
    "main",
    "render",
    "scope",
    "size_pack",
    "tier_a",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

INDEX: Final = "fixtures/index.toml"
SIDECAR: Final = ".meta.toml"
HOUSEKEEPING: Final = frozenset({"README.md", ".gitattributes", "EXPECTED.sha256"})
PROVENANCES: Final[Mapping[str, tuple[str, ...]]] = {
    "generated": ("generator",),
    "public_domain": ("source_url", "retrieved_at", "statutory"),
    "cc0": ("source_url", "retrieved_at"),
    "cc_by": ("source_url", "retrieved_at", "attribution"),
    "authored": ("contributor", "cla"),
}
"""Ruling 3: section 4.2's provenances and what each records."""
COMMON: Final = ("sha256", "bytes", "provenance", "spdx")
GENERATORS: Final = "fixtures/gen/"
HEADER: Final = (
    "# fixtures/index.toml -- GENERATED by `uv run tools/gate_fixtures.py --write` from every\n"
    "# fixture's `.meta.toml` sidecar; do not edit. Q-G1 byte-diffs it (13-quality.md section\n"
    "# 4.4): sorted by path, LF, no timestamps.\n"
)
_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")
_BARE: Final = re.compile(r"[A-Za-z0-9_-]+")
_FIX_ROW: Final = "mend the sidecar, then run `uv run tools/gate_fixtures.py --write`"

TIER_A_BYTES: Final = 64_000_000
"""Ruling 8: section 4.1's 64 MB, decimal."""
MAX_BINARY_BYTES: Final = 4_000_000
"""Ruling 8: section 4.1's 4 MB per binary, decimal."""
SIZE_PACK_KIB: Final = 200_000
"""Ruling 11: section 4.6's `size-pack` ceiling, in the KiB `git count-objects -v` reports."""
SCAN_FLOOR: Final = 0.40
REDUCTIONS: Final = ("fixtures/goldens/", (".shape", ".pages", ".outline"))
CASSETTES: Final = "fixtures/cassettes/"
DOCS: Final = "fixtures/docs/"
_SIZE_PACK: Final = re.compile(r"^size-pack:\s*(\d+)\s*$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Finding:
    """One failing line: the path it names and why."""

    path: str
    detail: str


def scope(committed: Sequence[str]) -> tuple[list[str], list[str]]:
    """Ruling 1: the committed fixtures and sidecars, each sorted."""
    fixtures, sidecars = [], []
    for path in committed:
        parts = path.split("/")
        in_package = len(parts) > 3 and parts[0] == "packages" and parts[2] == "fixtures"  # noqa: PLR2004
        if not (in_package or path.startswith("fixtures/docs/")):
            continue
        if path.endswith(SIDECAR):
            sidecars.append(path)
        elif parts[-1] not in HOUSEKEEPING:
            fixtures.append(path)
    return sorted(fixtures), sorted(sidecars)


def _empty(value: object) -> bool:
    return value is None or (isinstance(value, str | list | dict) and not value)


def _empties(table: Mapping[str, Any], prefix: str = "") -> list[str]:
    """Ruling 4: every key, at any depth, whose value says nothing."""
    out = []
    for key, value in table.items():
        if _empty(value):
            out.append(prefix + key)
        elif isinstance(value, dict):
            out.extend(_empties(value, f"{prefix}{key}."))
    return out


def check_row(row: Mapping[str, Any], data: bytes | None, committed: frozenset[str]) -> list[str]:
    """Rulings 2-4 for one fixture's `[fixture]` table; why it fails, or nothing."""
    if data is None:
        return ["the sidecar names no committed file"]
    why = [f"{key} is empty" for key in _empties(row)]
    if "path" in row:
        why.append("path is the index's own key, and a sidecar may not set it")
    missing = [key for key in COMMON if key not in row]
    provenance = row.get("provenance")
    if isinstance(provenance, str) and provenance in PROVENANCES:
        missing += [key for key in PROVENANCES[provenance] if key not in row]
    elif "provenance" in row:
        why.append(f"provenance {provenance!r} is not one of {', '.join(PROVENANCES)}")
    if missing:
        why.append(f"no {', '.join(missing)}")
    digest = hashlib.sha256(data).hexdigest()
    if "sha256" in row and row["sha256"] != digest:
        why.append(f"sha256 {row['sha256']} is not the file's {digest}")
    if "bytes" in row and row["bytes"] != len(data):
        why.append(f"bytes {row['bytes']} is not the file's {len(data)}")
    generator = row.get("generator")
    if (
        provenance == "generated"
        and isinstance(generator, str)
        and generator
        and (not generator.startswith(GENERATORS) or generator not in committed)
    ):
        why.append(f"generator {generator} is not a committed file under {GENERATORS}")
    retrieved = row.get("retrieved_at")
    if "retrieved_at" in row and not (
        isinstance(retrieved, dt.date)
        or (isinstance(retrieved, str) and _DATE.fullmatch(retrieved))
    ):
        why.append(f"retrieved_at {retrieved!r} is not YYYY-MM-DD")
    return why


def _key(name: str) -> str:
    return name if _BARE.fullmatch(name) else json.dumps(name, ensure_ascii=False)


def _value(value: object) -> str:
    """One TOML value. Strings take JSON's escapes, which are TOML basic strings' too."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, dt.date | dt.datetime | dt.time):
        return value.isoformat()
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    message = f"{type(value).__name__} has no TOML value here"
    raise TypeError(message)


def _table(lines: list[str], name: str, table: Mapping[str, Any]) -> None:
    for key in sorted(k for k, v in table.items() if not isinstance(v, dict)):
        lines.append(f"{_key(key)} = {_value(table[key])}")
    for key in sorted(k for k, v in table.items() if isinstance(v, dict)):
        lines.append("")
        lines.append(f"[{name}.{_key(key)}]")
        _table(lines, f"{name}.{_key(key)}", table[key])


def render(rows: Sequence[tuple[str, Mapping[str, Any]]]) -> str:
    """Ruling 5: the index, from `(fixture path, [fixture] table)` pairs."""
    lines = [HEADER.rstrip("\n")]
    for path, table in sorted(rows, key=lambda pair: pair[0]):
        lines += ["", "[[fixture]]", f"path = {_value(path)}"]
        _table(lines, "fixture", table)
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class Budget:
    """What Q-G2 measured, its findings, and the clauses it could not run."""

    tier_a: int
    cassettes: int
    cassette_bytes: int
    reductions: int
    findings: tuple[Finding, ...]
    notes: tuple[str, ...]


def tier_a(committed: Sequence[str]) -> list[str]:
    """Ruling 7: every committed path under `fixtures/` or a `packages/<dist>/fixtures/` tree."""
    out = []
    for path in committed:
        parts = path.split("/")
        in_package = len(parts) > 3 and parts[0] == "packages" and parts[2] == "fixtures"  # noqa: PLR2004
        if in_package or path.startswith("fixtures/"):
            out.append(path)
    return sorted(out)


def budget(sizes: Mapping[str, int], fixtures: Sequence[str]) -> Budget:
    """Rulings 7-10 over `{path: bytes}` for Tier A and the Q-G1 fixtures within it."""
    findings: list[Finding] = []
    total = sum(sizes.values())
    if total > TIER_A_BYTES:
        findings.append(Finding("fixtures/", f"Tier A is {total} bytes, over {TIER_A_BYTES}"))
    findings += [
        Finding(path, f"{sizes[path]} bytes, over {MAX_BINARY_BYTES} per binary")
        for path in fixtures
        if sizes.get(path, 0) > MAX_BINARY_BYTES
    ]
    root, suffixes = REDUCTIONS
    reductions = [path for path in sizes if path.startswith(root) and path.endswith(suffixes)]
    findings += [
        Finding(path, f"{sizes[path]} bytes, over MAX_REDUCTION_BYTES ({MAX_REDUCTION_BYTES})")
        for path in sorted(reductions)
        if sizes[path] > MAX_REDUCTION_BYTES
    ]
    cassettes = sorted(path for path in sizes if path.startswith(CASSETTES))
    findings += [
        Finding(path, f"{sizes[path]} bytes, over MAX_CASSETTE_BYTES ({MAX_CASSETTE_BYTES})")
        for path in cassettes
        if sizes[path] > MAX_CASSETTE_BYTES
    ]
    cassette_bytes = sum(sizes[path] for path in cassettes)
    if cassette_bytes > MAX_CASSETTE_BYTES_TOTAL:
        findings.append(
            Finding(
                CASSETTES,
                f"{cassette_bytes} bytes, over MAX_CASSETTE_BYTES_TOTAL"
                f" ({MAX_CASSETTE_BYTES_TOTAL})",
            )
        )
    notes = []
    docs = [path for path in fixtures if path.startswith(DOCS)]
    if docs:
        findings.append(
            Finding(
                DOCS,
                f"{len(docs)} fixture(s), and the {SCAN_FLOOR:.0%} scan floor cannot be measured: "
                "no sidecar key says a document is a scan (13-quality.md section 4.4)",
            )
        )
    else:
        notes.append(f"the {SCAN_FLOOR:.0%} scan floor: {DOCS} holds no fixture to measure")
    notes.append("orphan cassettes: not run, because nothing writes eval/cassette-usage.toml yet")
    return Budget(
        total, len(cassettes), cassette_bytes, len(reductions), tuple(findings), tuple(notes)
    )


def size_pack(root: Path) -> int:
    """Ruling 11: `size-pack` in KiB after `git gc --auto --quiet`, or `OSError`."""
    _git(root, "gc", "--auto", "--quiet")
    match = _SIZE_PACK.search(_git(root, "count-objects", "-v").decode("utf-8", "replace"))
    if match is None:
        message = "git count-objects -v reported no size-pack"
        raise OSError(message)
    return int(match.group(1))


def _git(root: Path, *arguments: str) -> bytes:
    git = shutil.which("git")
    if git is None:
        message = "git is not on PATH"
        raise OSError(message)
    done = subprocess.run(  # noqa: S603 - argv[0] from `shutil.which`, no shell.
        [git, *arguments], cwd=root, capture_output=True, check=False
    )
    if done.returncode != 0:
        message = f"git {arguments[0]}: " + done.stderr.decode("utf-8", "replace").strip()
        raise OSError(message)
    return done.stdout


def _committed(root: Path) -> list[str]:
    return [path for path in _git(root, "ls-files", "-z").decode("utf-8").split("\0") if path]


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(
    argv: list[str] | None = None,
    *,
    committed: Sequence[str] | None = None,
    pack: Callable[[Path], int] = size_pack,
) -> int:
    """0 clean, 1 a finding, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_fixtures.py",
        description="Q-G1 and Q-G2: every fixture byte has a manifest row and fits its budget.",
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="PATH")
    parser.add_argument("--write", action="store_true", help=f"regenerate {INDEX}")
    parser.add_argument("--skip-pack", action="store_true", help="leave out git gc and size-pack")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    root: Path = args.root
    try:
        listed = list(committed) if committed is not None else _committed(root)
    except OSError as exc:
        _say(f"Q-G1 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN
    fixtures, sidecars = scope(listed)
    findings, rows = _rows(root, fixtures, sidecars, frozenset(listed))
    index = render(rows)
    target = root / INDEX
    if args.write:
        target.write_bytes(index.encode("utf-8"))
    elif not target.is_file() or target.read_bytes() != index.encode("utf-8"):
        state = "differs from what the sidecars generate" if target.is_file() else "is missing"
        findings.append(Finding(INDEX, f"{state}; run `uv run tools/gate_fixtures.py --write`"))
    _say(f"Q-G1  {len(fixtures)} fixture(s), {len(sidecars)} sidecar(s), {len(rows)} indexed")
    for one in findings:
        _say(f"  FAIL  {one.path}: {one.detail}")
    if any(one.path.endswith(SIDECAR) for one in findings):
        _say(f"  fix   {_FIX_ROW}")
    if args.write:
        _say(f"  wrote {INDEX}")
    _say(f"Q-G1 {'FAIL' if findings else 'ok'}  {len(findings)} finding(s)")
    over = _q_g2(root, listed, fixtures, pack if not args.skip_pack else None)
    if over is None:
        return EXIT_NOT_RUN
    return EXIT_FAIL if findings or over else EXIT_CLEAN


def _q_g2(
    root: Path, listed: Sequence[str], fixtures: Sequence[str], pack: Callable[[Path], int] | None
) -> list[Finding] | None:
    """Rulings 7-12, printed: the findings, or `None` when the pack could not be measured."""
    spent = budget({path: _size(root / path) for path in tier_a(listed)}, fixtures)
    over = list(spent.findings)
    _say(
        f"Q-G2  Tier A {spent.tier_a} of {TIER_A_BYTES} bytes; {spent.cassettes} cassette(s),"
        f" {spent.cassette_bytes} of {MAX_CASSETTE_BYTES_TOTAL} bytes; {spent.reductions}"
        " Reduction(s)"
    )
    if pack is None:
        _say("  note  size-pack: not measured (--skip-pack)")
    else:
        try:
            kib = pack(root)
        except OSError as exc:
            _say(f"Q-G2 DID NOT RUN  size-pack: {exc}")
            return None
        if kib > SIZE_PACK_KIB:
            over.append(Finding("size-pack", f"{kib} KiB after git gc, over {SIZE_PACK_KIB}"))
        _say(f"  size-pack {kib} of {SIZE_PACK_KIB} KiB after git gc --auto")
    for one in over:
        _say(f"  FAIL  {one.path}: {one.detail}")
    for note in spent.notes:
        _say(f"  note  {note}")
    _say(f"Q-G2 {'FAIL' if over else 'ok'}  {len(over)} finding(s)")
    return over


def _size(path: Path) -> int:
    """A committed file's bytes in the working tree; 0 for one the checkout deleted."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _rows(
    root: Path, fixtures: list[str], sidecars: list[str], committed: frozenset[str]
) -> tuple[list[Finding], list[tuple[str, Mapping[str, Any]]]]:
    """Rulings 2-4 over every fixture and sidecar: the findings, and the rows fit to index."""
    findings: list[Finding] = []
    rows: list[tuple[str, Mapping[str, Any]]] = []
    described = {sidecar.removesuffix(SIDECAR) for sidecar in sidecars}
    findings += [
        Finding(path, f"no manifest row; write {Path(path).name}{SIDECAR} beside it")
        for path in fixtures
        if path not in described
    ]
    for sidecar in sidecars:
        path = sidecar.removesuffix(SIDECAR)
        try:
            doc = tomllib.loads((root / sidecar).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            findings.append(Finding(sidecar, f"unreadable: {exc}"))
            continue
        table = doc.get("fixture")
        if not isinstance(table, dict):
            findings.append(Finding(sidecar, "has no [fixture] table"))
            continue
        target = root / path
        data = target.read_bytes() if path in committed and target.is_file() else None
        why = check_row(table, data, committed)
        findings += [Finding(sidecar, reason) for reason in why]
        if not why:
            rows.append((path, table))
    return findings, rows


if __name__ == "__main__":
    raise SystemExit(main())
