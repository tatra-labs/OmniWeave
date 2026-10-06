"""Build the environment G10's first discovery row describes, and run G10 inside it. D659.

04-driver-system.md section 4.4's first row -- D1's original *"driver discovery, 20 installed
<= 20 ms"* -- is stated about **20 drivers in 20 installed distributions, cold**, and
`tools/gate_coldstart.py` asserts a row only in the environment it describes
(`check_discovery_budget`'s second rule). The workspace's own venv holds about a hundred
distributions, so the row has been ABSENT on every run, and V01-3 PARTIAL with it.

This builds that environment and nothing else:

* a fresh venv (`uv venv`, no seed packages, so it holds no `pip` or `setuptools` dist);
* `omniweave-ports` and `omniweave-core`, installed `--no-deps` -- V01-1 is that core resolves to
  core + ports and zero third-party, so nothing is missing;
* eighteen generated driver distributions carrying **twenty** cards between them, two of them
  holding a second driver in a subpackage, as `omniweave-office` holds `parse.text.builtin`.

That is 20 distributions and 20 drivers. Then it runs `gate_coldstart.py` with the venv's own
interpreter -- the gate is standard library only, and times `Catalog.build()` in fresh children of
`sys.executable` -- and reports what row 1 said. The venv is a temporary directory, removed after.

Run it:

    uv run python tools/env_twenty.py           # build, measure, report; exit 1 if row 1 fails
    uv run python tools/env_twenty.py --json    # the gate's JSON report from inside the venv
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # noqa: TID251 -- building a venv and running a gate in it are both spawns.
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GATE = REPO / "tools" / "gate_coldstart.py"
PACKAGES = (REPO / "packages" / "omniweave-ports", REPO / "packages" / "omniweave-core")
ROW = "20 drivers, 20 installed distributions, cold"

DISTRIBUTIONS = 18
"""Generated driver distributions. With core and ports that is the row's 20 installed."""

SECOND_CARD_IN = (0, 1)
"""The generated distributions that carry a second driver: 18 + 2 = the row's 20 drivers."""

CARD = """card_schema = 1

[driver]
id = "{id}"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "{package}.driver:Driver"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""
"""The smallest card `load_card()` accepts -- `test_discovery.py`'s `MINIMAL`, the same shape --
so the twenty cost what a real card's parse and validation cost, and nothing extra."""


def _run(argv: list[str], *, cwd: Path = REPO) -> str:
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)  # noqa: S603
    if done.returncode != 0:
        msg = f"{' '.join(argv[:3])} ... exited {done.returncode}\n{done.stderr[-2000:]}"
        raise RuntimeError(msg)
    return done.stdout


def _python(venv: Path) -> Path:
    windows = venv / "Scripts" / "python.exe"
    return windows if windows.exists() else venv / "bin" / "python"


def _driver(site: Path, index: int) -> None:
    """One generated distribution: a `.dist-info` and a package holding one or two cards."""
    dist = f"ow-twenty-d{index:02d}"
    package = f"ow_twenty_d{index:02d}"
    drivers = {f"parse.twenty.d{index:02d}": package}
    (site / package).mkdir()
    (site / package / "__init__.py").write_text("", encoding="utf-8")
    (site / package / "driver.toml").write_text(
        CARD.format(id=f"parse.twenty.d{index:02d}", package=package), encoding="utf-8"
    )
    if index in SECOND_CARD_IN:
        second = f"{package}.second"
        drivers[f"parse.twenty.d{index:02d}b"] = second
        (site / package / "second").mkdir()
        (site / package / "second" / "__init__.py").write_text("", encoding="utf-8")
        (site / package / "second" / "driver.toml").write_text(
            CARD.format(id=f"parse.twenty.d{index:02d}b", package=second), encoding="utf-8"
        )
    info = site / f"{package}-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {dist}\nVersion: 0.1.0\n", encoding="utf-8"
    )
    rows = "".join(f"{name} = {value}\n" for name, value in drivers.items())
    (info / "entry_points.txt").write_text(f"[omniweave.drivers]\n{rows}", encoding="utf-8")
    (info / "INSTALLER").write_text("env_twenty\n", encoding="utf-8")
    (info / "RECORD").write_text("", encoding="utf-8")


def build(root: Path) -> Path:
    """The venv, populated. Returns its interpreter."""
    venv = root / "venv"
    _run(["uv", "venv", str(venv), "--python", sys.executable, "--no-project", "--quiet"])
    python = _python(venv)
    _run(
        [
            "uv", "pip", "install", "--python", str(python), "--no-deps", "--quiet",
            *(str(p) for p in PACKAGES),
        ]
    )  # fmt: skip
    site = Path(
        _run(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"]
        ).strip()
    )
    for index in range(DISTRIBUTIONS):
        _driver(site, index)
    return python


def measure(python: Path) -> dict[str, object]:
    """`gate_coldstart.py --json` under the venv's interpreter, from a directory with no dists."""
    neutral = python.parent
    done = subprocess.run(  # noqa: S603 -- a fixed argv, no shell
        [str(python), str(GATE), "--json"], cwd=neutral, capture_output=True, text=True, check=False
    )
    if not done.stdout.strip():
        said = done.stderr[-2000:]
        msg = f"gate_coldstart.py produced no report (exit {done.returncode}): {said}"
        raise RuntimeError(msg)
    report: dict[str, object] = json.loads(done.stdout)
    report["exit_code"] = done.returncode
    return report


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")


def _table(report: dict[str, object], key: str) -> dict[str, object]:
    value = report.get(key)
    if not isinstance(value, dict):
        msg = f"the gate's report has no {key!r} table; gate_coldstart.py's --json shape changed"
        raise TypeError(msg)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print the gate's report as JSON")
    args = parser.parse_args(argv)
    root = Path(tempfile.mkdtemp(prefix="ow-twenty-"))
    try:
        report = measure(build(root))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    env = _table(report, "environment")
    found = _table(report, "measurements").get("Catalog.build()")
    findings = report.get("findings")
    rows = [
        f for f in (findings if isinstance(findings, list) else [])
        if isinstance(f, dict) and f.get("subject") == ROW
    ]  # fmt: skip
    if args.json:
        _out(json.dumps(report, indent=2, sort_keys=True))
    else:
        _out(
            f"env_twenty: {env['installed_distributions']} installed distributions, "
            f"{env['operating_system']} / {env['python']}"
        )
        if isinstance(found, dict):
            _out(f"  Catalog.build()  {found.get('value')} ms, best of {report['measured_runs']}")
        for finding in rows or [{"severity": "ABSENT", "message": "the row was not asserted"}]:
            _out(f"  {finding['severity']:<9} {ROW}: {finding['message']}")
    if not rows:
        return 2
    return 1 if any(f["severity"] == "FAIL" for f in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
