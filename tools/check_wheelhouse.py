"""`build.wheelhouse_profiles`: three install profiles, offline, from the wheels release publishes.

11-repo-layout.md section 2.4: *"Three of the six are built in the `build` job from the wheels that
release will publish, into fresh virtual environments, from an offline wheelhouse (§6.6), and each
one carries one assertion that fails loudly."* **D885.**

The three profiles and the one assertion each carries:

- **minimum**, `omniweave`: adding a PDF refuses, naming `pip install omniweave-pdf`, with an `OW-`
  code and no traceback; `import omniweave_core` loads no third-party module (G9).
- **working**, `omniweave[recommended]`: `ow doctor` exits 0; the summed `RECORD` sizes are within
  G2's `aggregate_mb`, and are written to `eval/baselines/weights-<os>-<py>.json`.
- **all-but-vision**, the thirteen bounded distributions: they install together.

## Rulings

1. **The wheelhouse is the lock's, for this interpreter.** One `uv export --frozen --package <m>
   --no-dev --no-emit-workspace` per bounded member pins its third-party closure as `uv.lock`
   resolved it, and `pip download` fetches the union once, online, for `sys.executable`. Every
   profile then installs with `uv pip install --no-index`, from the wheelhouse and the
   first-party wheels alone. A profile that needs anything else fails, which is what "offline"
   means.
2. **The minimum refusal is asserted on `ow add`.** Section 2.4 writes `ow parse report.pdf`, and
   there is no `parse` verb; `ow add` is the verb that parses. The refusal must exit 64
   (`CapabilityMissing`), name `pip install omniweave-pdf`, carry `OW-D-009`, and print no
   traceback: section 2.4's "exit code and `OW-D-*` code as declared", which D888 declared.
3. **"Third-party" in the G9 clause** is any module `-X importtime` reports whose top-level name is
   neither stdlib nor `omniweave_*`.
4. **`vision` is excluded from the third profile**, as section 2.4 names it, and therefore from
   the wheelhouse: `torch` is the one dependency the other twelve do not need.

## Exit codes

`0` every assertion holds. `1` an assertion fails, named. `2` the check did not run: no wheels, or
the wheelhouse could not be built.

Specified in 11-repo-layout.md sections 2.3, 2.4 and 6.6 step 4.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess  # noqa: TID251 -- a build tool runs installers, and only children read them.
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.errors import CapabilityMissing

if TYPE_CHECKING:
    from collections.abc import Sequence

REPO: Final = Path(__file__).resolve().parent.parent
EXIT_OK, EXIT_FAIL, EXIT_NOT_RUN = 0, 1, 2
VISION: Final = "omniweave-vision"
PDF_FIX: Final = "pip install omniweave-pdf"
DECLARED_CODE: Final = "OW-D-009"
"""`OW_DRIVER_FORMAT_UNSUPPORTED`, the code 18:2158 binds to a format no driver reads (D888)."""
MB: Final = 1_000_000
TIMEOUT_S: Final = 1800
RECORD_FIELDS: Final = 3
"""`path,hash,size`: a RECORD row with a size to add up."""


class NotRunError(RuntimeError):
    """The harness could not run (exit 2)."""


@dataclass(frozen=True, slots=True)
class Outcome:
    profile: str
    ok: bool
    detail: str


def _attachment(data: dict[str, Any]) -> bool:
    """D909: a member declaring `[tool.omniweave] attachment = true` is none of the fourteen."""
    return data.get("tool", {}).get("omniweave", {}).get("attachment") is True


def members(root: Path = REPO) -> tuple[str, ...]:
    """Every workspace member's distribution name."""
    names = []
    for pyproject in sorted((root / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = data.get("project", {})
        if "name" in project and not _attachment(data):
            names.append(str(project["name"]))
    return tuple(names)


def bounded(root: Path = REPO) -> tuple[str, ...]:
    """Ruling 4: every member but vision."""
    return tuple(name for name in members(root) if name != VISION)


SITE_HOOKS: Final = frozenset({"_virtualenv", "sitecustomize", "usercustomize"})
"""Ruling 3: what `site` imports in any venv before `-c` runs, which is no import of ours."""


def third_party(importtime_stderr: str) -> list[str]:
    """Ruling 3: top-level modules `-X importtime` loaded that are neither stdlib nor ours."""
    found: set[str] = set()
    for line in importtime_stderr.splitlines():
        if not line.startswith("import time:") or "|" not in line:
            continue
        name = line.rsplit("|", 1)[-1].strip().split(".")[0]
        if name == "imported package":  # the header row `-X importtime` prints first
            continue
        if not name or name.startswith("omniweave") or name in sys.stdlib_module_names:
            continue
        if name in SITE_HOOKS:
            continue
        if name.startswith("_") and name.lstrip("_") in sys.stdlib_module_names:
            continue
        found.add(name)
    return sorted(found)


def refusal(returncode: int, out: str) -> list[str]:
    """Ruling 2: what is wrong with the minimum profile's refusal, if anything."""
    problems = []
    if returncode != CapabilityMissing.EXIT:
        problems.append(
            f"ow add exited {returncode} on a PDF with no PDF driver installed, not the "
            f"declared {CapabilityMissing.EXIT} (CapabilityMissing, D888)"
        )
    if PDF_FIX not in out:
        problems.append(f"the refusal does not name `{PDF_FIX}`")
    if DECLARED_CODE not in out:
        problems.append(f"the refusal does not carry its declared code, {DECLARED_CODE}")
    if "Traceback" in out:
        problems.append("the refusal printed a traceback")
    return problems


def _run(
    argv: Sequence[str], *, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv is built here, never from input.
        list(argv),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT_S,
        check=False,
    )


def _must(argv: Sequence[str], what: str, **kw: object) -> subprocess.CompletedProcess[str]:
    done = _run(argv, **kw)  # type: ignore[arg-type]
    if done.returncode != 0:
        msg = f"{what} exited {done.returncode}: {(done.stderr or done.stdout)[-1500:]}"
        raise NotRunError(msg)
    return done


def wheelhouse(work: Path, dist: Path) -> Path:
    """Ruling 1: the lock's third-party pins, downloaded once into `work/wheelhouse`."""
    house = work / "wheelhouse"
    house.mkdir(parents=True, exist_ok=True)
    pins = work / "pins.txt"
    #  Ruling 4 by construction: the union of each bounded member's own closure, so vision's
    #  dependencies (torch, pinned on Linux to an index `pip download` does not read) are in the
    #  wheelhouse only if a bounded member needs them too.
    lines: set[str] = set()
    for name in bounded():
        exported = _must(
            (
                "uv",
                "export",
                "--frozen",
                "--package",
                name,
                "--no-dev",
                "--no-emit-workspace",
                "--no-hashes",
            ),
            f"uv export --package {name}",
            cwd=REPO,
        )
        lines.update(
            line.strip()
            for line in exported.stdout.splitlines()
            if line.strip() and not line.lstrip().startswith(("#", "-e", "./", ".", "--"))
        )
    pins.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    wanted = [str(w) for w in sorted(dist.glob("*.whl")) if VISION.replace("-", "_") not in w.name]
    _must(
        (
            "uvx",
            "--python",
            sys.executable,
            "pip",
            "download",
            "--dest",
            str(house),
            "--find-links",
            str(dist),
            "--constraint",
            str(pins),
            "--only-binary",
            ":all:",
            *wanted,
        ),
        "pip download",
        cwd=work,
    )
    return house


def _venv(path: Path) -> Path:
    _must(("uv", "venv", "--quiet", "--python", sys.executable, str(path)), f"uv venv {path.name}")
    bindir = "Scripts" if os.name == "nt" else "bin"
    return path / bindir


def _install(
    bindir: Path, house: Path, dist: Path, requirements: Sequence[str]
) -> subprocess.CompletedProcess[str]:
    """Offline, and from these files exactly: `--no-cache`, because uv's cache keys a wheel by
    its filename and a rebuilt `omniweave_core-0.1.0` would otherwise install the previous build's
    bytes. It did, and the minimum profile tested a core with no packaged register (D897)."""
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    return _run(
        (
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--no-index",
            "--offline",
            "--no-cache",
            "--find-links",
            str(house),
            "--find-links",
            str(dist),
            *requirements,
        )
    )


def minimum(work: Path, house: Path, dist: Path, pdf: Path) -> Outcome:
    bindir = _venv(work / "minimum")
    done = _install(bindir, house, dist, ["omniweave"])
    if done.returncode != 0:
        return Outcome("minimum", False, f"offline install failed: {done.stderr[-800:]}")
    project = work / "minimum-project"
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(
        '[corpora.docs]\npath = ".omniweave/docs.owstore"\n[serve]\ndefault_corpus = "docs"\n',
        encoding="utf-8",
    )
    (project / "docs" / "report.pdf").write_bytes(pdf.read_bytes())
    env = {**os.environ, "OMNIWEAVE_HOME": str(work / "minimum-home")}
    ow = bindir / ("ow.exe" if os.name == "nt" else "ow")
    added = _run((str(ow), "add", "docs/report.pdf"), cwd=project, env=env)
    said = added.stdout + added.stderr
    problems = refusal(added.returncode, said)
    if problems:
        problems.append(f"ow add printed: {said.strip()[-400:]!r}")
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    imported = _run((str(python), "-X", "importtime", "-c", "import omniweave_core"))
    leaked = third_party(imported.stderr)
    if leaked:
        problems.append(f"import omniweave_core loaded third-party modules: {', '.join(leaked)}")
    detail = "; ".join(problems) or (
        f"ow add refused with exit {added.returncode}, named `{PDF_FIX}`; "
        "import omniweave_core loaded no third-party module"
    )
    return Outcome("minimum", not problems, detail)


def working(work: Path, house: Path, dist: Path, baselines: Path) -> Outcome:
    bindir = _venv(work / "working")
    done = _install(bindir, house, dist, ["omniweave[recommended]"])
    if done.returncode != 0:
        return Outcome("working", False, f"offline install failed: {done.stderr[-800:]}")
    ow = bindir / ("ow.exe" if os.name == "nt" else "ow")
    env = {**os.environ, "OMNIWEAVE_HOME": str(work / "working-home")}
    doctor = _run((str(ow), "doctor"), cwd=work, env=env)
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    site = _must(
        (str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"),
        "purelib",
    ).stdout.strip()
    total = _record_bytes(Path(site))
    ceiling = tomllib.loads((REPO / "tools" / "weights.toml").read_text(encoding="utf-8"))[
        "aggregate_mb"
    ]
    problems = []
    if doctor.returncode != 0:
        problems.append(
            f"ow doctor exited {doctor.returncode}: {(doctor.stdout + doctor.stderr)[-600:]}"
        )
    if total > ceiling * MB:
        problems.append(f"[recommended] is {total / MB:.1f} MB, over aggregate_mb {ceiling}")
    baselines.mkdir(parents=True, exist_ok=True)
    tag = f"{platform.system().lower()}-{sys.version_info.major}.{sys.version_info.minor}"
    (baselines / f"weights-{tag}.json").write_text(
        json.dumps(
            {"profile": "omniweave[recommended]", "record_bytes": total, "aggregate_mb": ceiling},
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    detail = "; ".join(problems) or f"ow doctor exit 0; {total / MB:.1f} MB of {ceiling} MB"
    return Outcome("working", not problems, detail)


def everything(work: Path, house: Path, dist: Path) -> Outcome:
    bindir = _venv(work / "bounded")
    names = bounded()
    done = _install(bindir, house, dist, list(names))
    if done.returncode != 0:
        return Outcome("all-but-vision", False, f"offline install failed: {done.stderr[-800:]}")
    #  D899: G2's measured half, which section 2.5 runs "in the `build` job over an offline
    #  wheelhouse install" -- this one, the thirteen bounded distributions installed together.
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    site = _must(
        (str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"),
        "purelib",
    ).stdout.strip()
    weighed = _run((sys.executable, str(REPO / "tools" / "gate_weights.py"), "--measure", site))
    if weighed.returncode != 0:
        failures = [line.strip() for line in weighed.stdout.splitlines() if "FAIL" in line]
        return Outcome("all-but-vision", False, "G2 measured: " + "; ".join(failures)[:800])
    return Outcome(
        "all-but-vision",
        True,
        f"{len(names)} bounded distributions installed together; G2 measured every ceiling",
    )


def _record_bytes(site: Path) -> int:
    """G2's union: every installed `RECORD` row's size, each path counted once."""
    seen: dict[str, int] = {}
    for record in site.glob("*.dist-info/RECORD"):
        for row in record.read_text(encoding="utf-8").splitlines():
            parts = row.rsplit(",", 2)
            if len(parts) == RECORD_FIELDS and parts[2].isdigit():
                seen[parts[0]] = int(parts[2])
    return sum(seen.values())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_wheelhouse", description="section 2.4's profiles")
    parser.add_argument("--dist", type=Path, default=REPO / "dist", help="the built wheels")
    parser.add_argument("--baselines", type=Path, default=REPO / "eval" / "baselines")
    args = parser.parse_args(argv)
    #  Absolute from here: `pip download` and the installs run with cwd set to a temp directory,
    #  where CI's relative `--dist dist` named nothing (D897's first CI run).
    dist: Path = args.dist.resolve()
    pdf = REPO / "packages" / "omniweave-pdf" / "fixtures" / "gen01p.pdf"
    if not any(dist.glob("*.whl")):
        sys.stdout.write(
            f"build.wheelhouse_profiles did not run: no wheels in {dist}; build them with "
            f"`uv build --all-packages --out-dir {dist}`\n"
        )
        return EXIT_NOT_RUN
    try:
        with tempfile.TemporaryDirectory(prefix="ow-wheelhouse-") as scratch:
            work = Path(scratch)
            house = wheelhouse(work, dist)
            outcomes = [
                minimum(work, house, dist, pdf),
                working(work, house, dist, args.baselines),
                everything(work, house, dist),
            ]
    except (NotRunError, OSError, subprocess.TimeoutExpired) as error:
        sys.stdout.write(f"build.wheelhouse_profiles did not run: {error}\n")
        return EXIT_NOT_RUN
    for outcome in outcomes:
        sys.stdout.write(
            f"{'ok  ' if outcome.ok else 'FAIL'}  {outcome.profile:<15} {outcome.detail}\n"
        )
    held = all(outcome.ok for outcome in outcomes)
    sys.stdout.write(f"build.wheelhouse_profiles {'ok' if held else 'FAILED'}\n")
    return EXIT_OK if held else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
