"""`manifest_diff.py` -- the in-wheel first-party manifest against the signed asset. D1012.

11-repo-layout.md section 7.2: *"The published `first-party-<RELEASE>.json` asset is the same
content in JSON, `cosign sign-blob`ed, so an auditor can compare the in-wheel copy against a signed
one without trusting the wheel that carries it."* This is the comparison. It is recipe 4 of section
7.5, and section 7.6's checklist step 15 runs all four from a clean machine.

    python tools/manifest_diff.py first-party-0.1.0.json first_party.toml
    python -c "..." | python tools/manifest_diff.py first-party-0.1.0.json -

## Rulings

1. **It runs on a machine with no omniweave installed.** An auditor downloads a signed asset and a
   wheel; the tool that compares them cannot be a module inside the thing under audit. So this file
   imports `json`, `tomllib` and `sys` and nothing else, takes paths and `-` for stdin, and is
   runnable straight out of a source checkout or copied beside the two files.
2. **It compares the DOCUMENT, not the bytes.** Section 7.2 says *"the same content in JSON"*, and
   two encodings of one mapping are never byte-equal, so a byte comparison would answer a question
   nobody asked. The comparison is over the parsed mappings, key by key.
3. **An absent `vendored` is `false`.** `gen_first_party.py` ruling 3 writes `vendored = true` only
   when the flag is set (`render()` appends the line inside `if is_vendored`), so the key is absent
   on the common row. Treating absent and `false` as different would report every unvendored
   distribution as a mismatch, which is the failure mode that makes a verification tool useless:
   noise an auditor learns to skip past. Normalised in one place, `_rows()`.
4. **Every difference names both sides.** A tool that says "the manifests differ" sends the auditor
   back to a diff they could have run themselves. Each finding prints the distribution, the field,
   the asset's value and the wheel's, in that order -- signed value first, because the signed one is
   the one with provenance behind it.
5. **`omniweave-core` has no row in either**, and its absence is not a finding. Section 7.2: *"Core
   is the verifier ... a row asserting core's own hash would be a witness testifying to itself."*
   Nothing here special-cases the name: both documents omit it, so the symmetric comparison says
   nothing about it, and a core row appearing in one and not the other IS reported, as any other
   asymmetry would be.
6. **Exit codes:** `0` the two agree; `1` they differ, every difference printed; `2` a file could
   not be read or parsed. The three are distinguished because step 15 is run by a person who needs
   "the recipe is broken" to look different from "the artefact is wrong".

What this proves and what it does not is section 7.5's honest paragraph, carried in `docs/verify.md`
beside the recipe: agreement means the wheel's manifest is the one that was signed. It says nothing
about a third-party driver, whose `Attestation` is a hash over its own card computed by its own kit.
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path
from typing import Any, Final

EXIT_OK: Final = 0
EXIT_FINDING: Final = 1
EXIT_NOT_RUN: Final = 2

FIELDS: Final = ("version", "dist_sha256", "vendored")
"""The per-distribution fields `gen_first_party.py` writes, in the order it writes them."""

SCALARS: Final = ("schema", "release")
"""The document's own two keys, outside `[dist.*]`."""

STDIN: Final = "-"

ARGUMENTS: Final = 2
"""The signed asset and the in-wheel copy. Ruling 6 needs a usage error to differ from both."""


def _read(where: str) -> bytes:
    """The bytes of `where`, or stdin for `-`. Raises `OSError` the caller turns into exit 2."""
    if where == STDIN:
        return sys.stdin.buffer.read()
    return Path(where).read_bytes()


def _parse(where: str, raw: bytes) -> dict[str, Any]:
    """TOML or JSON by the file's own name, so neither side is guessed from its content."""
    if where != STDIN and where.endswith(".json"):
        loaded = json.loads(raw.decode("utf-8"))
    else:
        loaded = tomllib.loads(raw.decode("utf-8"))
    if not isinstance(loaded, dict):
        message = f"{where}: the manifest is not a table"
        raise TypeError(message)
    return loaded


def _rows(document: dict[str, Any]) -> dict[str, dict[str, object]]:
    """`[dist.*]` as `{name: {field: value}}`, with ruling 3's `vendored` default applied."""
    table = document.get("dist", {})
    if not isinstance(table, dict):
        message = "dist is not a table"
        raise TypeError(message)
    out: dict[str, dict[str, object]] = {}
    for name, row in table.items():
        if not isinstance(row, dict):
            message = f"dist.{name} is not a table"
            raise TypeError(message)
        out[str(name)] = {field: row.get(field, field == "vendored" and False) for field in FIELDS}
    return out


def compare(asset: dict[str, Any], wheel: dict[str, Any]) -> list[str]:
    """Ruling 4: every difference between the signed asset and the in-wheel copy, both sides named.

    Pure, and the only place the comparison lives, so `main()` is argument handling and printing.
    """
    findings: list[str] = []
    for key in SCALARS:
        if asset.get(key) != wheel.get(key):
            findings.append(f"{key}: asset {asset.get(key)!r}, wheel {wheel.get(key)!r}")
    signed, carried = _rows(asset), _rows(wheel)
    for name in sorted(set(signed) | set(carried)):
        if name not in carried:
            findings.append(f"{name}: in the signed asset, absent from the wheel's manifest")
            continue
        if name not in signed:
            findings.append(f"{name}: in the wheel's manifest, absent from the signed asset")
            continue
        findings.extend(
            f"{name}.{field}: asset {signed[name][field]!r}, wheel {carried[name][field]!r}"
            for field in FIELDS
            if signed[name][field] != carried[name][field]
        )
    return findings


def main(argv: list[str] | None = None) -> int:
    """`manifest_diff.py <signed .json> <in-wheel .toml|->`. Ruling 6's three exit codes."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != ARGUMENTS or any(one in ("-h", "--help") for one in args):
        sys.stderr.write(
            "usage: manifest_diff.py <first-party-RELEASE.json> <first_party.toml|->\n"
            "  the signed asset first, the copy out of the wheel second; `-` reads stdin\n"
        )
        return EXIT_NOT_RUN
    where_asset, where_wheel = args
    if where_asset == where_wheel == STDIN:
        sys.stderr.write("manifest_diff.py: only one side can be stdin\n")
        return EXIT_NOT_RUN
    # `_rows()` is the deferred half of parsing -- a `dist` that is not a table of tables is a
    # manifest this tool could not read, not a manifest that disagrees -- so the comparison runs
    # inside the same `try` that the reads do, and both reach ruling 6's exit 2.
    try:
        asset = _parse(where_asset, _read(where_asset))
        wheel = _parse(where_wheel, _read(where_wheel))
        findings = compare(asset, wheel)
        rows = len(_rows(asset))
    except (OSError, TypeError, UnicodeDecodeError, ValueError) as problem:
        sys.stderr.write(f"manifest_diff.py: {problem}\n")
        return EXIT_NOT_RUN
    for finding in findings:
        sys.stdout.write(f"manifest_diff FAIL  {finding}\n")
    if findings:
        sys.stdout.write(f"manifest_diff FAIL  {len(findings)} difference(s)\n")
        return EXIT_FINDING
    release = asset.get("release")
    sys.stdout.write(f"manifest_diff ok  {rows} row(s), release {release}, asset and wheel agree\n")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
