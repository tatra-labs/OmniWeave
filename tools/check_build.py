"""The `build` job's two artefact assertions, runnable on any machine: 28 files, reproducible. D874.

11-repo-layout.md section 7.1: *"28 PyPI files, zero platform wheels, one runner. That is the
whole point of the py3-none-any decision."* Section 6.6 step 3, `build.reproducible`: *"two build
passes produce 28 identical sha256s"*. `ci.yml`'s `build` job asserts both in shell, and the `ci`
workflow is off, so V10-2 (*"14 sdists and 14 wheels, py3-none-any"*) had no instrument that ran.
This script is the same two assertions for a machine with no CI. `ci.yml` keeps its shell steps:
section 6.6's step 2, the first-party manifest, sits between them and will change what step 3
compares (its own comment says so), so folding both into one call belongs to the cell that wires
step 2. Until then the two are one rule in two spellings, and this file says which job it mirrors.

It is `check_build.py` and not `gate_build.py` for the same reason: a `tools/gate_*.py` is a
registered gate whose register row's runner CI invokes (`test_gates_register.py`), and the
`build` job's two assertions are `build.reproducible`'s and the count step's, still in shell.

    uv run tools/check_build.py                  # pass one and pass two, in a scratch directory
    uv run tools/check_build.py --dist dist      # pass one already built, as the job builds it

## Rulings

1. **The 28 are named, not counted.** Every workspace member (`packages/*/pyproject.toml`'s
   `[project] name`) must have exactly one sdist and exactly one wheel, and nothing else may be
   there. A count alone passes 27 files and a stray, which is why `ci.yml`'s count needed its
   `-name "omniweave*"` filter to step over `uv build`'s own `dist/.gitignore`.
2. **Every wheel is `py3-none-any`.** A platform wheel is a finding naming the file.
3. **Reproducibility is two passes compared by sha256**, the second always built fresh into a
   scratch directory. Both passes run under one `SOURCE_DATE_EPOCH`, the commit's date, as
   section 7.4 requires, so nothing before the approval pause depends on the wall clock; a value
   already in the environment is kept, as CI sets it.
4. **Exit codes:** `0` every assertion holds; `1` a finding; `2` the build could not run (no `uv`,
   no git, or `uv build` failed).

Specified in 11-repo-layout.md sections 6.6 and 7.1-7.4, and V10-2 (00-vision.md section 9.2).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess  # noqa: TID251 -- the gate's inputs are `git` and `uv build`, and only children read them.
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = ["Finding", "expected", "judge", "main", "members"]

REPO: Final = Path(__file__).resolve().parent.parent
PURE: Final = "-py3-none-any.whl"
BUILD_TIMEOUT_S: Final = 900
EXIT_OK, EXIT_FINDING, EXIT_NOT_RUN = 0, 1, 2


@dataclass(frozen=True, slots=True)
class Finding:
    """One way the artefacts are not section 7.1's 28."""

    kind: str
    names: str


def members(root: Path) -> tuple[str, ...]:
    """Every workspace member's distribution name, from `packages/*/pyproject.toml` (ruling 1)."""
    names = []
    for pyproject in sorted((root / "packages").glob("*/pyproject.toml")):
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        if "name" in project:
            names.append(str(project["name"]))
    return tuple(names)


def expected(name: str) -> str:
    """The stem both artefacts of `name` begin with: `omniweave-core` is `omniweave_core`."""
    return name.replace("-", "_").lower()


def judge(names: Sequence[str], files: Sequence[str]) -> list[Finding]:
    """Rulings 1 and 2: exactly one sdist and one pure wheel per member, and nothing else."""
    findings: list[Finding] = []
    claimed: set[str] = set()
    for name in names:
        stem = expected(name)
        sdists = [f for f in files if f.startswith(f"{stem}-") and f.endswith(".tar.gz")]
        wheels = [f for f in files if f.startswith(f"{stem}-") and f.endswith(".whl")]
        if len(sdists) != 1:
            findings.append(Finding("sdist", f"{name}: {len(sdists)} sdists, not 1"))
        if len(wheels) != 1:
            findings.append(Finding("wheel", f"{name}: {len(wheels)} wheels, not 1"))
        findings += [
            Finding("platform", f"{wheel} is not py3-none-any (section 7.1)")
            for wheel in wheels
            if not wheel.endswith(PURE)
        ]
        claimed.update(sdists, wheels)
    findings += [
        Finding("stray", f"{f} is no workspace member's artefact")
        for f in files
        if f not in claimed
    ]
    return findings


def digests(directory: Path) -> dict[str, str]:
    """Each artefact's sha256, `dist/.gitignore` and other dotfiles left out (ruling 1)."""
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.iterdir())
        if path.is_file() and not path.name.startswith(".")
    }


def reproduced(first: Mapping[str, str], second: Mapping[str, str]) -> list[Finding]:
    """Ruling 3: the two passes' artefacts, name for name and byte for byte."""
    findings = [
        Finding("reproducible", f"{name}: pass two's sha256 differs from pass one's")
        for name in sorted(first.keys() & second.keys())
        if first[name] != second[name]
    ]
    findings += [
        Finding("reproducible", f"{name}: built by one pass only")
        for name in sorted(first.keys() ^ second.keys())
    ]
    return findings


class BuildError(RuntimeError):
    """A child could not run: the gate did not run (exit 2)."""


def _epoch(root: Path, env: Mapping[str, str]) -> str:
    """Ruling 3: `SOURCE_DATE_EPOCH` as given, else the commit's date."""
    if env.get("SOURCE_DATE_EPOCH"):
        return env["SOURCE_DATE_EPOCH"]
    git = shutil.which("git")
    if git is None:
        raise BuildError("no git to read the commit date from; set SOURCE_DATE_EPOCH")
    done = subprocess.run(  # noqa: S603 -- a fixed argv, no shell
        [git, "show", "-s", "--format=%ct", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
        timeout=60,
    )
    if done.returncode != 0:
        raise BuildError(
            f"git show exited {done.returncode}: {done.stderr.decode(errors='replace')}"
        )
    return done.stdout.decode().strip()


def build(root: Path, out: Path, epoch: str) -> None:
    """`uv build --all-packages --out-dir out` under one `SOURCE_DATE_EPOCH`."""
    uv = shutil.which("uv")
    if uv is None:
        raise BuildError("no uv on PATH")
    done = subprocess.run(  # noqa: S603 -- a fixed argv, no shell
        [uv, "build", "--all-packages", "--out-dir", str(out)],
        cwd=root,
        env={**os.environ, "SOURCE_DATE_EPOCH": epoch},
        capture_output=True,
        check=False,
        timeout=BUILD_TIMEOUT_S,
    )
    if done.returncode != 0:
        tail = done.stderr.decode(errors="replace")[-1500:]
        raise BuildError(f"uv build exited {done.returncode}:\n{tail}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_build", description="The build job's 28-file and reproducibility assertions."
    )
    parser.add_argument(
        "--dist", type=Path, help="pass one's directory, already built (CI); else built here"
    )
    args = parser.parse_args(argv)
    names = members(REPO)
    with tempfile.TemporaryDirectory(prefix="ow-gate-build-") as scratch:
        work = Path(scratch)
        try:
            epoch = _epoch(REPO, os.environ)
            first_dir = args.dist if args.dist is not None else work / "pass1"
            if args.dist is None:
                build(REPO, first_dir, epoch)
            build(REPO, work / "pass2", epoch)
        except (BuildError, OSError, subprocess.TimeoutExpired) as error:
            sys.stdout.write(f"check_build: the build could not run: {error}\n")
            return EXIT_NOT_RUN
        first, second = digests(first_dir), digests(work / "pass2")
    findings = judge(names, sorted(first)) + reproduced(first, second)
    for finding in findings:
        sys.stdout.write(f"  {finding.kind:<12}  {finding.names}\n")
    wheels = sum(1 for name in first if name.endswith(".whl"))
    sdists = sum(1 for name in first if name.endswith(".tar.gz"))
    summary = f"{len(names)} members, {sdists} sdists, {wheels} wheels, SOURCE_DATE_EPOCH={epoch}"
    if findings:
        sys.stdout.write(f"check_build FAILED: {len(findings)} finding(s); {summary}\n")
        return EXIT_FINDING
    sys.stdout.write(
        f"check_build ok: {summary}; every wheel py3-none-any; two passes, "
        f"{len(first)} identical sha256s\n"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
