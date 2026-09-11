"""G11 — discovery never imports: the rogue driver, installed.

INV-4's layer 2. 04-driver-system.md section 4.6 calls it "the one decision here that cannot be
reversed" and enforces it three times over. Layer 1 is `tools/semgrep/omniweave.yaml`, which bans
`EntryPoint.load()` under `omniweave_core/drivers/` alongside `importlib.import_module` and
`__import__` outside `host/`. Layer 3 is
`packages/omniweave-core/tests/unit/test_discovery_never_imports.py`, which discovers thirty cards
and asserts `sys.modules` gains no `omniweave_driver_*` key. **This file is layer 2**, stated
identically in five places -- 00-vision.md:408 and V01-4, 01-principles.md:187,
02-architecture.md:171, 04-driver-system.md:1234 and 14-security.md:1693: *installs a rogue driver
whose module body writes a file and raises `SystemExit`, and asserts `ow doctor` succeeds and the
file is absent*.

**What layer 2 asserts that layer 3 cannot.** Layer 3 hands `discover()` an explicit
`distributions=` and `search_path=`, so what it proves is that the enumeration it supplied is not
imported. That leaves the production path untested: a `discover()` which behaved only when handed
its distributions would pass layer 3 and import the world in a real process. This gate calls
`omniweave_core.discovery.catalog()` -- the owner interface 02-architecture.md section 2 row 12
fixes for this module, and the one `ow doctor` will call -- **with no injection at all**, over a
real `*.dist-info` on a real `sys.path`. It also covers a second route into discovery that layer 3
does not: `OMNIWEAVE_DRIVER_PATH`, where the hostile module is named by the card's `entrypoint`
field rather than by an entry-point value, so a loader that resolved *that* string early would be
invisible to the entry-point route entirely.

**`ow doctor` does not exist yet**, and this script does not invent it. `packages/omniweave/` is a
bare skeleton and the CLI is P7's (16-roadmap.md section 10), so the standing pattern is ledger D25:
the library function lives in the package and a `tools/` script drives it. "`ow doctor` succeeds" is
asserted here as its two checkable halves -- `catalog()` returns a `Catalog` holding the rogue's
card, and the process that called it exits 0 -- which is exactly what `ow doctor` will do when it
wraps this call.

**What it reads.** Nothing in the repository. The fixture is built under a temporary directory and
deleted afterwards: two hostile packages, each with a real `*.dist-info`, a real `entry_points.txt`,
a real `driver.toml`, and a module body whose **first statement** writes a sentinel file before it
raises `SystemExit`. The write comes first on purpose. A `SystemExit` can be caught, and an import
that raised halfway is still an import -- INV-4 forbids the execution and not the completion -- so
the file on disk is the instrument that survives both.

**What it asserts**, five clauses:

1. **the cards were read** -- `catalog().cards` holds both rogue ids, and each card's
   `identity.entrypoint` is the string naming its hostile module. First, because every clause below
   is vacuous without it: "nothing was imported" is trivially true of a pass that found nothing, and
   a fixture that quietly stopped being discovered is this gate's likeliest way to go green for the
   wrong reason. The `entrypoint` assertion is the sharp one -- discovery read the field that names
   the module and still did not resolve it.
2. **the process survived** -- exit 0. A module body reached during discovery takes the interpreter
   down with it, which is the failure `ow doctor` must not have on a machine where one installed
   wheel is hostile.
3. **the payload did not run** -- neither sentinel file exists.
4. **`sys.modules` is clean** -- no `omniweave_driver_*` key after the pass (DR1, V01-4).
5. **the negative control** -- the same fixture and the same instruments, plus one real
   `import omniweave_driver_rogue`, must exit **non-zero** and leave the sentinel **present**. A
   gate that can only pass is not a gate: without this clause an inert fixture, a site that was
   never on `sys.path`, and a typo in the module prefix all read as a pass.

**What is deliberately not asserted.** That no *other* module was imported. A discovery pass imports
`tomllib`, `importlib.metadata` and the rest of core, so a gate counting `sys.modules` wholesale
would fail on an unrelated refactor and teach everyone to ignore it. The `omniweave_driver_*` prefix
is the discriminator, and it is the one the plan prints.

The charter records what the alternative costs.
`docling/docling/models/factories/base_factory.py:96` calls
`plugin_manager.load_setuptools_entrypoints(plugin_name)`, and the `allow_external_plugins` test
sits in the **next** loop over `list_name_plugin()` at `:98-105` -- so that gate suppresses
*registration* by code which has already *executed*, and `process_plugin` then swallows a duplicate
as a `logger.warning`. Installation is not a decision about what may run.

Exit 0 clean, 1 with one `G11 FAIL` block per finding, 2 when the gate itself could not run.
Specified in 04-driver-system.md section 4.6, 01-principles.md INV-4, 11-repo-layout.md section 6.4
and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: TID251 -- a fresh interpreter is the only witness INV-4 has.
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "DRIVER_PATH_ID",
    "ENTRY_POINT_ID",
    "EXPECTED_ENTRYPOINTS",
    "MODULE_PREFIX",
    "Finding",
    "Observation",
    "Site",
    "build_site",
    "check_control",
    "check_discovery",
    "main",
    "observe",
    "run",
]

ROOT = Path(__file__).resolve().parent.parent

MODULE_PREFIX = "omniweave_driver_"
"""The prefix 04-driver-system.md section 4.6 clause 3 and INV-4 both print, and the one clause 4
counts. Layer 3 uses the same string for the same reason."""

ENTRY_POINT_MODULE = f"{MODULE_PREFIX}rogue"
DRIVER_PATH_MODULE = f"{MODULE_PREFIX}ambush"

ENTRY_POINT_ID = "parse.rogue.entrypoint"
DRIVER_PATH_ID = "parse.rogue.driverpath"

EXPECTED_ENTRYPOINTS: dict[str, str] = {
    ENTRY_POINT_ID: f"{ENTRY_POINT_MODULE}:Driver",
    DRIVER_PATH_ID: f"{DRIVER_PATH_MODULE}:Driver",
}
"""Each rogue id -> the `[driver] entrypoint` its card declares.

Clause 1 compares against this rather than merely asserting the id is present, because `entrypoint`
is the field a loader would have to resolve in order to violate INV-4. Reading it back intact proves
discovery held the name of the hostile module in its hand and did nothing with it."""

PROBE_TIMEOUT_S = 120
"""Generous on purpose. `tools/gates.toml` budgets G11 at 10 s and two interpreter starts plus two
`Distribution.discover()` passes land far inside that; the timeout exists to turn a hang into a
diagnosable exit 2 rather than a CI job that runs until the runner kills it."""


# ---------------------------------------------------------------------------
# the fixture
# ---------------------------------------------------------------------------

CARD = """card_schema = 1

[driver]
id = "{driver_id}"
port = "parse/1"
version = "1.0.0"
schema_version = 1
entrypoint = "{module}:Driver"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/x-omniweave-rogue"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""

MODULE_BODY = '''"""A hostile driver module body. The write comes first; the exit comes second.

Nothing here is library code and none of omniweave's rules apply to it -- a driver is third-party
code and may do anything at all, which is the entire reason its CARD is read rather than its MODULE
imported. The sentinel is written before the exit because a `SystemExit` can be caught by a caller
and a file on disk cannot be un-written: an import that raised halfway is still an import.
"""

import pathlib

pathlib.Path({sentinel!r}).write_text("the module body ran", encoding="utf-8")

raise SystemExit("a rogue driver module body")
'''

PROBE = '''"""G11's probe: one `ow doctor`-shaped discovery pass, reported as JSON on stdout.

Two positional arguments -- the `OMNIWEAVE_DRIVER_PATH` directory, and either `import-rogue` or
`no-control`. Nothing is injected into `catalog()` except the declared environment: `distributions`,
`search_path` and `tombstone_dir` are all left at their defaults, so this pass enumerates the real
`sys.path` exactly as a real run does.
"""

import json
import sys

driver_path, control = sys.argv[1], sys.argv[2]

from omniweave_core.discovery import catalog, discover

result = catalog(env={"OMNIWEAVE_DRIVER_PATH": driver_path})

# A second, separate pass purely so a clause-1 failure can say WHY a card is missing: `catalog()`
# narrows to one card per id and drops the faults on the floor, and `discover()` keeps them.
faults = discover(env={"OMNIWEAVE_DRIVER_PATH": driver_path}).faults

if control == "import-rogue":
    import omniweave_driver_rogue  # noqa: F401 -- the control, and it must take us down.

sys.stdout.write(
    json.dumps(
        {
            "cards": sorted(result.cards),
            "entrypoints": {
                name: result.cards[name].identity.entrypoint
                for name in sorted(result.cards)
                if name.startswith("parse.rogue.")
            },
            "modules": sorted(m for m in sys.modules if m.startswith("omniweave_driver_")),
            "faults": [
                f"{fault.symbol} {fault.detail} ({fault.source})"
                for fault in faults
                if "rogue" in fault.source or "ambush" in fault.source
            ],
        }
    )
)
'''


@dataclass(frozen=True, slots=True)
class Site:
    """Where the fixture put its four pieces."""

    site: Path
    """The install root. Goes on `PYTHONPATH`, so its `*.dist-info` is on the probe's `sys.path`."""

    drivers: Path
    """The `OMNIWEAVE_DRIVER_PATH` root: `<drivers>/<name>/driver.toml`, depth one."""

    sentinels: Path
    """Empty if INV-4 holds. One file per module body that ran if it does not."""

    probe: Path
    """The program above, on disk rather than passed to `-c`, so a traceback names a real file."""


def build_site(root: Path) -> Site:
    """Two hostile installations, reachable by the two routes that name a module.

    The entry-point rogue is what `pip install` produces: a package directory holding the card, and
    a `*.dist-info` whose `entry_points.txt` names the package under `[omniweave.drivers]`. The
    driver-path rogue is the other shape -- a bare `driver.toml` in a directory on
    `OMNIWEAVE_DRIVER_PATH`, with no `dist-info` anywhere and its module sitting importable on
    `sys.path`, named only by the card's own `entrypoint` field.

    Both module bodies are identical and both are armed. Neither may run.
    """
    site = root / "site"
    drivers = root / "drivers"
    sentinels = root / "sentinels"
    sentinels.mkdir(parents=True)

    # Route 1 -- an installed distribution.
    package = site / ENTRY_POINT_MODULE
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        MODULE_BODY.format(sentinel=str(sentinels / f"{ENTRY_POINT_MODULE}.imported")),
        encoding="utf-8",
    )
    (package / "driver.toml").write_text(
        CARD.format(driver_id=ENTRY_POINT_ID, module=ENTRY_POINT_MODULE), encoding="utf-8"
    )
    dist_info = site / f"{ENTRY_POINT_MODULE}-1.0.0.dist-info"
    dist_info.mkdir()
    distribution = ENTRY_POINT_MODULE.replace("_", "-")
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {distribution}\nVersion: 1.0.0\n", encoding="utf-8"
    )
    (dist_info / "entry_points.txt").write_text(
        f"[omniweave.drivers]\n{ENTRY_POINT_ID} = {ENTRY_POINT_MODULE}\n", encoding="utf-8"
    )

    # Route 2 -- OMNIWEAVE_DRIVER_PATH. The module is importable and NOTHING advertises it except
    # the card's own `entrypoint`, which is the string a premature `activate()` would resolve.
    ambush = site / DRIVER_PATH_MODULE
    ambush.mkdir()
    (ambush / "__init__.py").write_text(
        MODULE_BODY.format(sentinel=str(sentinels / f"{DRIVER_PATH_MODULE}.imported")),
        encoding="utf-8",
    )
    carded = drivers / "ambush"
    carded.mkdir(parents=True)
    (carded / "driver.toml").write_text(
        CARD.format(driver_id=DRIVER_PATH_ID, module=DRIVER_PATH_MODULE), encoding="utf-8"
    )

    probe = root / "probe.py"
    probe.write_text(PROBE, encoding="utf-8")
    return Site(site=site, drivers=drivers, sentinels=sentinels, probe=probe)


# ---------------------------------------------------------------------------
# the observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Observation:
    """What one probe run saw. Every clause below is a pure function of this."""

    returncode: int
    sentinels: tuple[str, ...]
    cards: tuple[str, ...] = ()
    entrypoints: Mapping[str, str] = field(default_factory=dict)
    modules: tuple[str, ...] = ()
    faults: tuple[str, ...] = ()
    stderr: str = ""
    decoded: bool = True
    """False when the probe printed no parseable JSON, which is the normal and expected state of
    the negative control: the import that proves the fixture is armed kills it before it prints."""


def observe(fixture: Site, *, control: bool) -> Observation:
    """Run the probe in a fresh interpreter and read both instruments.

    `sentinels` is read from disk rather than from the probe's own report, because the control run
    dies before it can report anything and the file it left behind is the whole point.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(fixture.site), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [
        sys.executable,
        str(fixture.probe),
        str(fixture.drivers),
        "import-rogue" if control else "no-control",
    ]
    proc = subprocess.run(  # noqa: S603 -- `sys.executable` and a file this module just wrote.
        command,
        capture_output=True,
        text=True,
        check=False,
        timeout=PROBE_TIMEOUT_S,
        env=env,
    )
    found = tuple(sorted(path.name for path in fixture.sentinels.iterdir()))
    try:
        seen = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return Observation(
            returncode=proc.returncode, sentinels=found, stderr=proc.stderr, decoded=False
        )
    return Observation(
        returncode=proc.returncode,
        sentinels=found,
        cards=tuple(seen["cards"]),
        entrypoints=dict(seen["entrypoints"]),
        modules=tuple(seen["modules"]),
        faults=tuple(seen["faults"]),
        stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# the five clauses
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation: which clause, and what is wrong."""

    clause: str
    message: str

    def block(self) -> str:
        return f"G11 FAIL  [{self.clause}]\n          {self.message}"


def _tail(stderr: str) -> str:
    """The last few stderr lines, indented to sit under a finding's message."""
    lines = stderr.strip().splitlines()[-6:] or ["<empty>"]
    return "\n          ".join(lines)


def check_discovery(seen: Observation) -> list[Finding]:
    """Clauses 1-4, over the pass that must find both rogues and run neither."""
    if not seen.decoded:
        return [
            Finding(
                "discovered",
                "the probe printed no JSON, so nothing below could be measured. That is the "
                "shape a driver module body reaching the interpreter takes. stderr:\n          "
                + _tail(seen.stderr),
            )
        ]

    findings: list[Finding] = []
    for driver_id, entrypoint in EXPECTED_ENTRYPOINTS.items():
        if driver_id not in seen.cards:
            findings.append(
                Finding(
                    "discovered",
                    f"{driver_id} is not in the catalog, so every clause below it is vacuous. "
                    f"Discovery returned {len(seen.cards)} card(s); "
                    f"faults: {list(seen.faults) or 'none'}",
                )
            )
        elif seen.entrypoints.get(driver_id) != entrypoint:
            findings.append(
                Finding(
                    "discovered",
                    f"{driver_id} declares entrypoint {entrypoint!r} and the catalog holds "
                    f"{seen.entrypoints.get(driver_id)!r}; the field a loader would resolve is "
                    f"not the field that was read back",
                )
            )

    if seen.returncode != 0:
        findings.append(
            Finding(
                "survived",
                f"the discovery pass exited {seen.returncode}; `ow doctor` must succeed on a "
                f"machine where one installed wheel is hostile. stderr:\n          "
                + _tail(seen.stderr),
            )
        )

    if seen.sentinels:
        findings.append(
            Finding(
                "payload",
                f"a driver module body RAN during discovery: {', '.join(seen.sentinels)}. "
                f"INV-4 is the one decision 04-driver-system.md section 4.6 says cannot be "
                f"reversed",
            )
        )

    if seen.modules:
        findings.append(
            Finding(
                "sys.modules",
                f"discovery imported {', '.join(seen.modules)}; a pass over installed cards must "
                f"add no {MODULE_PREFIX}* key (DR1, 00-vision.md V01-4)",
            )
        )
    return findings


def check_control(seen: Observation) -> list[Finding]:
    """Clause 5 -- the instruments, shown an import that really happens.

    Both must fire. A green `check_discovery` over a fixture whose module body is inert, or whose
    site never reached `sys.path`, proves nothing whatever; this is the clause that says so.
    """
    findings: list[Finding] = []
    sentinel = f"{ENTRY_POINT_MODULE}.imported"
    if seen.returncode == 0:
        findings.append(
            Finding(
                "control",
                "importing the rogue exited 0. The fixture's module body is not armed, so the "
                "pass above was measuring an inert file and could only have succeeded",
            )
        )
    if sentinel not in seen.sentinels:
        findings.append(
            Finding(
                "control",
                f"importing the rogue left no {sentinel}. Either the site was never on "
                f"`sys.path` or the sentinel is written somewhere this gate does not look, and "
                f"either way the absence asserted above is an absence of instrumentation",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def run(root: Path) -> list[Finding]:
    """Build the fixture under `root`, run both probes, return every finding.

    Order matters and is not an accident: the discovery pass runs FIRST, over a sentinel directory
    this function has just created empty. Running the control first would leave its sentinel on
    disk and clause 3 would then fail on evidence the gate itself planted.
    """
    fixture = build_site(root)
    findings = check_discovery(observe(fixture, control=False))
    findings.extend(check_control(observe(fixture, control=True)))
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run G11. 0 clean, 1 with one block per finding, 2 when the gate could not run.

    Exit 2 is distinguished from 1 deliberately: 1 is "INV-4 is false", 2 is "this gate did not get
    to ask". CI treats both as failure and a human needs to know which one happened.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        emit(f"usage: {Path(__file__).name}   (no arguments; the fixture is built and deleted)")
        return 2

    with tempfile.TemporaryDirectory(prefix="ow-g11-") as scratch:
        try:
            findings = run(Path(scratch))
        except subprocess.TimeoutExpired:
            emit(f"G11 ERROR  the probe did not finish inside {PROBE_TIMEOUT_S}s.")
            return 2
        except OSError as error:
            emit(f"G11 ERROR  the fixture could not be built: {error}")
            return 2

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G11 FAIL  {len(findings)} finding(s).")
        return 1

    emit(
        f"G11 ok  2 rogue installations over 2 routes, catalog built, exit 0, "
        f"no {MODULE_PREFIX}* import, no module body run."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
