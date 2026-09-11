"""G12 — the vendored-artefact gate: sha256, a parity test, an arch assertion and a NOTICE.

**The four checks are named, in this order, in two places.** 11-repo-layout.md:1555 lists the gate
as "every vendored artefact: sha256, parity test, arch assertion, NOTICE row"; 14-security.md:1273
gives the same four as the rule a vendored binary must satisfy and prices the alternative from the
mined collection — Unlimited-OCR's documented install step one is "a 12.4 MB unsigned prebuilt wheel
committed to git, with no hash, no signature and no index"; codegraph "records shas in comments with
a parity test and no NOTICE"; hyperframes "checks architecture with no hash and no NOTICE". Each of
those has one or two of the four. This gate is what makes "all four, for every artefact" a command
rather than a reviewer's memory.

**What it reads.** `tools/vendor.toml` (the register), every directory under `vendor/`, each
artefact's own `<manifest>` / `NOTICE` / `LICENSE` / `FORK-TRIGGER.md`, the vendored Rust source
that the parity test joins on, and — for the arch assertion — the installed distribution's
metadata. It imports no first-party module, so it runs against a tree whose packages are broken,
which is the condition a vendoring mistake tends to arrive with.

**The four, as this gate implements them.**

1. **sha256.** Every file under the artefact directory has a row in the manifest, every row names a
   file that exists, and every digest matches. Extra files and missing files are both findings: a
   manifest that covers only what someone remembered to list is not a manifest.
2. **Parity between copies.** A vendored SOURCE tree and an installed BINARY wheel cannot be
   compared byte for byte, so the comparison is over what both must agree about — the version, the
   eleven limit constants (14-security.md:498's parity test, `core >= anydoc` so the Python-side
   ceiling is never silently the tighter one), the exported error classes, and `py.detach` around
   the decode, which is the whole warrant for the S1 in-process seam (14:502). A source that
   drifted from the shipped binary passes a source-only check and fails this one.
3. **Arch assertion.** The artefact declares what shape it is (`abi3` for anydoc) and the gate
   asserts the installed distribution is that shape and actually imports on this interpreter. A
   recorded sha over source says nothing about the binary a user will run.
4. **NOTICE row.** Every `vendor/<name>/` has a row in the register; every row names an artefact
   that exists; every artefact carries the NOTICE, LICENSE and FORK-TRIGGER the row names; the
   declared SPDX id is on `tools/licences.toml`'s allowlist; and the recorded commit is a full
   40-character SHA rather than a branch name.

Exit 0 clean, 1 with one `G12 FAIL` block per finding. Specified in 11-repo-layout.md sections 1.7
and 6.4, 14-security.md sections 8 and 9, and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import hashlib
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ANYDOC_LIMITS",
    "Finding",
    "check_artefact",
    "main",
]

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
REGISTER = ROOT / "tools" / "vendor.toml"
ALLOWLIST = ROOT / "tools" / "licences.toml"

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^([0-9a-f]{64})\s\s(.+)$")
_CONST_RE = re.compile(r"^pub const (MAX_[A-Z_]+):\s*\w+\s*=\s*([^;]+);", re.MULTILINE)
_LIMIT_STRING_RE = re.compile(r'limit:\s*"([a-z_]+)"')

ANYDOC_LIMITS: dict[str, str] = {
    "MAX_ENTRY_BYTES": "MAX_ENTRY_BYTES",
    "MAX_TOTAL_BYTES": "MAX_CONTAINER_TOTAL_BYTES",
    "MAX_ENTRY_COUNT": "MAX_ENTRY_COUNT",
    "MAX_XML_DEPTH": "MAX_XML_DEPTH",
    "MAX_XML_NODES": "MAX_XML_NODES",
    "MAX_GRID_SLOTS": "MAX_GRID_SLOTS",
    "MAX_EXPANSION": "MAX_EXPANSION",
    "MAX_EXPANSION_TEXT_BYTES": "MAX_EXPANSION_TEXT_BYTES",
    "MAX_ASSET_TOTAL_BYTES": "MAX_ASSET_TOTAL_BYTES",
    "MAX_RECORD_DEPTH": "MAX_RECORD_DEPTH",
    "MAX_RECORDS": "MAX_RECORDS",
}
"""anydoc's constant -> the `omniweave_core.limits` constant that bounds the SAME vector.

Eleven rows. The plan says "twelve" in five places and `_plan/_notes/build-defects.md` D123 records
the recount with the command that produced it; the gate re-derives the count from the vendored
source on every run rather than trusting this table's length, so a twelfth constant upstream is a
finding here and not a silent omission.

The map is duplicated from `omniweave_office.limits.CEILINGS` **on purpose**, and it is the one
place in this repository where that is the right answer: this gate imports nothing first-party, so
that it can run against a tree whose packages do not import. The duplication is not unchecked —
`check_parity()` asserts the two agree, which is the shape INV-21 asks for when a fact genuinely
must exist twice: one home, and a test that the copy is a copy."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation: which artefact, which of the four checks, and what is wrong."""

    artefact: str
    check: str
    message: str

    def block(self) -> str:
        return f"G12 FAIL  {self.artefact}  [{self.check}]\n          {self.message}"


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


# ---------------------------------------------------------------------------
# check 1 -- sha256
# ---------------------------------------------------------------------------


def check_digests(name: str, directory: Path, manifest_name: str) -> list[Finding]:
    """Every file matches the manifest, and the manifest covers every file."""
    manifest = directory / manifest_name
    if not manifest.is_file():
        return [Finding(name, "sha256", f"no digest manifest at {manifest.relative_to(ROOT)}")]
    recorded: dict[str, str] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        match = _DIGEST_RE.match(line)
        if match is None:
            return [Finding(name, "sha256", f"unparseable manifest line: {line[:70]!r}")]
        recorded[match.group(2)] = match.group(1)

    # The manifest's own four companions are the files it cannot digest: three of them change
    # whenever a reviewer edits prose, and the fourth is the manifest itself.
    skip = {manifest_name, ".gitattributes", "NOTICE", "FORK-TRIGGER.md"}
    present = {
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and path.relative_to(directory).as_posix() not in skip
    }
    findings: list[Finding] = []
    for extra in sorted(present - set(recorded)):
        findings.append(
            Finding(name, "sha256", f"{extra} is in the tree and not in {manifest_name}")
        )
    for missing in sorted(set(recorded) - present):
        findings.append(
            Finding(name, "sha256", f"{manifest_name} records {missing}, which is not in the tree")
        )
    for relative in sorted(present & set(recorded)):
        actual = hashlib.sha256((directory / relative).read_bytes()).hexdigest()
        if actual != recorded[relative]:
            findings.append(
                Finding(
                    name,
                    "sha256",
                    f"{relative}: recorded {recorded[relative][:16]}..., found {actual[:16]}...",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# check 2 -- parity between the vendored source and the installed binary
# ---------------------------------------------------------------------------


def check_parity(name: str, directory: Path, row: dict[str, object]) -> list[Finding]:
    """The vendored source and the installed wheel agree about everything both can state."""
    if name != "anydoc":  # the only artefact with a parity surface at release 1.
        return []
    findings: list[Finding] = []
    findings.extend(_parity_version(name, directory, row))
    findings.extend(_parity_limits(name, directory))
    findings.extend(_parity_detach(name, directory))
    findings.extend(_parity_api(name, directory))
    return findings


def _parity_version(name: str, directory: Path, row: dict[str, object]) -> list[Finding]:
    cargo = (directory / "Cargo.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', cargo, re.MULTILINE)
    source_version = match.group(1) if match else "<absent>"
    declared = str(row.get("version", ""))
    findings: list[Finding] = []
    if source_version != declared:
        findings.append(
            Finding(
                name,
                "parity",
                f"Cargo.toml says version {source_version}, vendor.toml says {declared}",
            )
        )
    installed = _installed_version(str(row.get("distribution", "")))
    if installed is None:
        findings.append(
            Finding(name, "parity", f"{row.get('distribution')} is not installed; cannot compare")
        )
    elif installed != declared:
        findings.append(
            Finding(
                name,
                "parity",
                f"the installed wheel is {installed}, the vendored source is {declared}",
            )
        )
    return findings


def _parity_limits(name: str, directory: Path) -> list[Finding]:
    """14-security.md:498's parity test: `omniweave_core.limits >= anydoc`, on every vector.

    Three copies are joined, not two. The vendored `limits.rs` gives the numbers; the vendored
    crate's `ConvertError::ResourceLimit { limit: "..." }` spellings give the names that can reach
    Python; `omniweave_core.limits` gives omniweave's ceiling for the same vector. A constant
    upstream adds, or renames, or raises is a finding in whichever of the three it lands in.
    """
    source = (directory / "src" / "package" / "limits.rs").read_text(encoding="utf-8")
    constants = {match.group(1): _rust_int(match.group(2)) for match in _CONST_RE.finditer(source)}
    findings: list[Finding] = []
    unknown = sorted(set(constants) - set(ANYDOC_LIMITS))
    if unknown:
        findings.append(
            Finding(
                name,
                "parity",
                f"limits.rs declares {', '.join(unknown)}, which this gate has no row for; "
                f"adding a ceiling upstream is a reviewed event, not a silent pass",
            )
        )
    absent = sorted(set(ANYDOC_LIMITS) - set(constants))
    if absent:
        findings.append(
            Finding(name, "parity", f"limits.rs no longer declares {', '.join(absent)}")
        )

    raised = _core_limits()
    for anydoc_name, core_name in ANYDOC_LIMITS.items():
        value = constants.get(anydoc_name)
        ceiling = raised.get(core_name)
        if value is None:
            continue
        if ceiling is None:
            findings.append(Finding(name, "parity", f"omniweave_core.limits has no {core_name}"))
        elif ceiling < value:
            findings.append(
                Finding(
                    name,
                    "parity",
                    f"{core_name} = {ceiling} is BELOW anydoc's {anydoc_name} = {value}; the "
                    f"Python-side ceiling must never silently be the tighter one (14:498)",
                )
            )

    spellings = set(_LIMIT_STRING_RE.findall(_crate_text(directory)))
    expected = {constant.lower() for constant in ANYDOC_LIMITS}
    if spellings != expected:
        findings.append(
            Finding(
                name,
                "parity",
                f"the limit names the crate can raise are {sorted(spellings)}, which is not the "
                f"eleven this gate maps: {sorted(expected)}",
            )
        )
    return findings


def _parity_detach(name: str, directory: Path) -> list[Finding]:
    """`py.detach` around the decode, which is the S1 seam's entire warrant.

    14-security.md:502: "The FFI call is one call per document with `py.detach` around the decode
    (S1)". `parse.office.anydoc` is the one driver the host may grant `Isolation.INPROC`, and it
    holds the GIL for the whole call if this ever stops being true — which would not raise, would
    not fail a test, and would quietly serialise every worker in the process.
    """
    binding = (directory / "python" / "src" / "lib.rs").read_text(encoding="utf-8")
    if "py.detach(|| anydoc::to_document" not in binding:
        return [
            Finding(
                name,
                "parity",
                "python/src/lib.rs no longer wraps `to_document` in `py.detach`; the inproc seam "
                "(DR9, 04:1653) rests on that call releasing the GIL",
            )
        ]
    return []


def _parity_api(name: str, directory: Path) -> list[Finding]:
    """Every error class the driver catches by name still exists in the vendored binding."""
    binding = (directory / "python" / "src" / "lib.rs").read_text(encoding="utf-8")
    required = (
        "ResourceLimitError",
        "EncryptedError",
        "NeedsOcrError",
        "UnsupportedError",
        "MalformedError",
        "MissingPartError",
        "ConvertError",
    )
    absent = [cls for cls in required if cls not in binding]
    if absent:
        return [
            Finding(
                name,
                "parity",
                f"the binding no longer defines {', '.join(absent)}, which "
                f"omniweave_office.driver catches by name",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# check 3 -- the arch assertion
# ---------------------------------------------------------------------------


def check_arch(name: str, row: dict[str, object]) -> list[Finding]:
    """The installed distribution is the shape the register says, and it imports here.

    A recorded digest over source says nothing about the binary a user will run. For an `abi3`
    wheel the checkable claims are that it is installed, that it carries a compiled extension
    rather than pure Python, and that the extension loads on this interpreter — which is
    17-risks.md R-E5's own trigger condition ("an `abi3` break on a supported cell") turned into a
    command.
    """
    shape = str(row.get("arch", ""))
    distribution = str(row.get("distribution", ""))
    if not shape or not distribution:
        return []
    from importlib import metadata  # noqa: PLC0415 -- a gate, not library code.

    try:
        files = metadata.distribution(distribution).files or []
    except metadata.PackageNotFoundError:
        return [Finding(name, "arch", f"{distribution} is not installed")]
    suffixes = {Path(str(entry)).suffix for entry in files}
    compiled = {".so", ".pyd", ".dylib"} & suffixes
    if shape == "abi3" and not compiled:
        return [
            Finding(
                name,
                "arch",
                f"{distribution} declares arch={shape} and ships no compiled extension "
                f"(found {sorted(suffixes)})",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# check 4 -- the NOTICE row
# ---------------------------------------------------------------------------


def check_register(
    name: str, directory: Path, row: dict[str, object], allow: set[str]
) -> list[Finding]:
    """The register's own claims: files that exist, an allowlisted SPDX id, a real commit."""
    findings: list[Finding] = []
    for key in ("notice", "fork_trigger"):
        target = directory / str(row.get(key, ""))
        if not target.is_file():
            findings.append(Finding(name, "notice", f"{key} names {target.name}, which is absent"))
    if not (directory / "LICENSE").is_file():
        findings.append(Finding(name, "notice", "no LICENSE in the artefact directory"))
    spdx = str(row.get("spdx", ""))
    if spdx not in allow:
        findings.append(
            Finding(
                name,
                "notice",
                f"spdx = {spdx!r} is not on tools/licences.toml [allow] spdx",
            )
        )
    commit = str(row.get("commit", ""))
    if not _SHA_RE.match(commit):
        findings.append(
            Finding(
                name,
                "notice",
                f"commit = {commit!r} is not a 40-character SHA; a branch name is not a pin",
            )
        )
    pinned_by = ROOT / str(row.get("pinned_by", ""))
    distribution = str(row.get("distribution", ""))
    if distribution and pinned_by.is_file():
        text = " ".join(pinned_by.read_text(encoding="utf-8").split())
        wanted = f"{distribution} == {row.get('version')}"
        if wanted not in text and wanted.replace(" ", "") not in text.replace(" ", ""):
            findings.append(
                Finding(
                    name,
                    "notice",
                    f"{row.get('pinned_by')} does not pin {distribution} == {row.get('version')}",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def _rust_int(expression: str) -> int:
    """`128 * 1024 * 1024` and `2_000_000` are both integers; nothing else is evaluated."""
    cleaned = expression.strip().replace("_", "")
    total = 1
    for factor in cleaned.split("*"):
        total *= int(factor.strip())
    return total


def _crate_text(directory: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in sorted((directory / "src").rglob("*.rs"))
    )


def _core_limits() -> dict[str, int]:
    """`omniweave_core.limits`'s constants, read as TEXT rather than imported.

    This gate imports no first-party module — the whole point is that it runs against a tree whose
    packages are broken — so the constants are read out of the source with a regular expression,
    the same discipline `gate_layers.py` applies to the import graph.
    """
    source = (
        ROOT / "packages" / "omniweave-core" / "src" / "omniweave_core" / "limits.py"
    ).read_text(encoding="utf-8")
    found: dict[str, int] = {}
    for match in re.finditer(r"^(MAX_[A-Z_]+)\s*:\s*int\s*=\s*([0-9_]+)", source, re.MULTILINE):
        found[match.group(1)] = int(match.group(2).replace("_", ""))
    return found


def _installed_version(distribution: str) -> str | None:
    from importlib import metadata  # noqa: PLC0415 -- a gate, not library code.

    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def _allowed_spdx() -> set[str]:
    table = tomllib.loads(ALLOWLIST.read_text(encoding="utf-8"))
    allow = table.get("allow", {})
    return set(allow.get("spdx", [])) if isinstance(allow, dict) else set()


def check_artefact(row: dict[str, object], allow: set[str]) -> list[Finding]:
    """All four checks for one registered artefact."""
    path = ROOT / str(row.get("path", ""))
    name = path.name
    if not path.is_dir():
        return [Finding(name, "notice", f"{row.get('path')} is registered and does not exist")]
    findings = check_digests(name, path, str(row.get("manifest", "")))
    findings.extend(check_parity(name, path, row))
    findings.extend(check_arch(name, row))
    findings.extend(check_register(name, path, row, allow))
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run G12 over every registered artefact. 0 clean, 1 with one block per finding, 2 on args.

    Exit 2 is distinguished from 1 on purpose: 1 is "the property is false", 2 is "the gate did not
    run". CI treats both as failure and a human needs to know which.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        emit(f"usage: {Path(__file__).name}   (no arguments; tools/vendor.toml is the register)")
        return 2
    if not REGISTER.is_file():
        emit(f"G12 FAIL  no register at {REGISTER.relative_to(ROOT)}")
        return 1
    register = tomllib.loads(REGISTER.read_text(encoding="utf-8"))
    rows = register.get("artefact", [])
    allow = _allowed_spdx()

    findings: list[Finding] = []
    registered = set()
    for row in rows:
        registered.add((ROOT / str(row.get("path", ""))).name)
        findings.extend(check_artefact(row, allow))

    if VENDOR.is_dir():
        for directory in sorted(VENDOR.iterdir()):
            if directory.is_dir() and directory.name not in registered:
                findings.append(
                    Finding(
                        directory.name,
                        "notice",
                        "is under vendor/ with no row in tools/vendor.toml; an unregistered "
                        "artefact is source nobody attributed and nobody is checking",
                    )
                )

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G12 FAIL  {len(findings)} finding(s) over {len(rows)} artefact(s).")
        return 1

    files = sum(
        1 for row in rows for path in (ROOT / str(row.get("path", ""))).rglob("*") if path.is_file()
    )
    emit(f"G12 ok  {len(rows)} artefact(s), {files} files, sha + parity + arch + NOTICE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
