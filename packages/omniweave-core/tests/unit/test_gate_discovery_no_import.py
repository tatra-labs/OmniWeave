"""G11 tested as a program: all five clauses, each shown a red.

`tools/gate_discovery_no_import.py` is INV-4's layer 2 — *installs a rogue driver whose module body
writes a file and raises `SystemExit`, and asserts `ow doctor` succeeds and the file is absent*
(04-driver-system.md:1234, and four more sites saying it identically). Layer 3 is
`test_discovery_never_imports.py` beside this file, which asserts the same invariant over an
injected enumeration; **this file asserts things about the GATE**, not about discovery, and the two
are different subjects.

**A gate nobody has seen fail is a gate nobody has tested.** Clauses 1-4 are pure functions of an
`Observation`, so each is shown the violation it exists for directly. Clause 5 — the negative
control — is the one that cannot be tested that way and is worth the subprocess: it is tested by
**disarming the fixture** and asserting the gate notices, because a gate whose fixture has quietly
become inert reports a green that means nothing at all, and that is the failure mode this whole
file exists to make impossible.

The two end-to-end tests are the expensive ones and they earn it. One corrupts a rogue's card and
asserts clause 1 fires with the fault named, which is the plumbing that reports *why* a card went
missing. The other runs `main()` over the real machine and asserts 0 — the same assertion CI makes,
here so a developer sees it fail locally rather than in a merge queue.

Specified in 04-driver-system.md section 4.6, 01-principles.md INV-4, 11-repo-layout.md section 6.4
and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture(scope="session")
def gate(repo_root: Path) -> ModuleType:
    """`tools/gate_discovery_no_import.py`, loaded by path and never put on `sys.path`."""
    path = repo_root / "tools" / "gate_discovery_no_import.py"
    spec = importlib.util.spec_from_file_location("_owgate_discovery_no_import", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clean(gate: ModuleType, **overrides: object) -> object:
    """The observation a healthy discovery pass produces, with one thing broken on request."""
    fields: dict[str, object] = {
        "returncode": 0,
        "sentinels": (),
        "cards": tuple(gate.EXPECTED_ENTRYPOINTS),
        "entrypoints": dict(gate.EXPECTED_ENTRYPOINTS),
        "modules": (),
        "faults": (),
        "stderr": "",
    }
    fields.update(overrides)
    return gate.Observation(**fields)


def clauses(findings: list[Any]) -> list[str]:
    """The clause name of each finding, in order — which is what every assertion below reads.

    `Any` and not `Finding`: the gate is loaded by path rather than imported, so its types are not
    nameable here. That is the same trade `test_gate_vendor.py` makes, and for the same reason —
    a `tools/` script is a program under test, not a dependency.
    """
    return [finding.clause for finding in findings]


# ---------------------------------------------------------------------------
# the baseline — a green must be reachable, or every red below proves nothing
# ---------------------------------------------------------------------------


def test_a_healthy_pass_produces_no_finding(gate: ModuleType) -> None:
    """Both rogues discovered, exit 0, no sentinel, no driver module. That is the whole gate."""
    assert gate.check_discovery(clean(gate)) == []


def test_a_healthy_control_produces_no_finding(gate: ModuleType) -> None:
    """The control's green is the opposite shape: non-zero exit, sentinel PRESENT."""
    seen = clean(
        gate,
        returncode=1,
        sentinels=("omniweave_driver_rogue.imported",),
        decoded=False,
    )
    assert gate.check_control(seen) == []


# ---------------------------------------------------------------------------
# clause 1 — the cards were read
# ---------------------------------------------------------------------------


def test_a_rogue_missing_from_the_catalog_is_a_finding(gate: ModuleType) -> None:
    """The anti-vacuity clause. "Nothing was imported" is trivially true of a pass that found
    nothing, and a fixture that quietly stopped being discovered is this gate's likeliest way to
    go green for the wrong reason."""
    seen = clean(gate, cards=(gate.ENTRY_POINT_ID,))
    findings = gate.check_discovery(seen)
    assert clauses(findings) == ["discovered"]
    assert gate.DRIVER_PATH_ID in findings[0].message


def test_a_missing_card_reports_the_fault_that_explains_it(gate: ModuleType) -> None:
    """A finding that says only "absent" sends a reader to the wrong place. Discovery records why
    it refused a card, and that record is what the message must carry."""
    seen = clean(gate, cards=(), faults=("OW_CARD_INVALID card_missing (.../ambush)",))
    findings = gate.check_discovery(seen)
    assert all("card_missing" in finding.message for finding in findings)


def test_a_rewritten_entrypoint_is_a_finding(gate: ModuleType) -> None:
    """The sharp assertion. `entrypoint` is the field a loader would have to resolve in order to
    violate INV-4, so reading it back CHANGED means the thing being proved untouched is not the
    thing that was measured."""
    seen = clean(
        gate,
        entrypoints={**gate.EXPECTED_ENTRYPOINTS, gate.ENTRY_POINT_ID: "something_else:Driver"},
    )
    findings = gate.check_discovery(seen)
    assert clauses(findings) == ["discovered"]
    assert "something_else:Driver" in findings[0].message


def test_a_probe_that_printed_no_json_is_one_finding_carrying_stderr(gate: ModuleType) -> None:
    """This is the shape a driver module body reaching the interpreter actually takes, so the
    finding must stand alone and must carry the traceback rather than reporting four derived
    absences with no cause."""
    seen = clean(gate, decoded=False, returncode=1, stderr="Traceback\na rogue driver module body")
    findings = gate.check_discovery(seen)
    assert clauses(findings) == ["discovered"]
    assert "a rogue driver module body" in findings[0].message


# ---------------------------------------------------------------------------
# clauses 2, 3 and 4 — survived, payload, sys.modules
# ---------------------------------------------------------------------------


def test_a_non_zero_exit_is_a_finding(gate: ModuleType) -> None:
    """`ow doctor` must succeed on a machine where one installed wheel is hostile. A module body
    reached during discovery takes the interpreter down with it."""
    findings = gate.check_discovery(clean(gate, returncode=1, stderr="boom"))
    assert clauses(findings) == ["survived"]


def test_a_sentinel_on_disk_is_a_finding(gate: ModuleType) -> None:
    """The instrument that survives a caught `SystemExit`: an import that raised halfway is still
    an import, and INV-4 forbids the execution rather than the completion."""
    findings = gate.check_discovery(clean(gate, sentinels=("omniweave_driver_rogue.imported",)))
    assert clauses(findings) == ["payload"]
    assert "RAN during discovery" in findings[0].message


def test_a_driver_module_in_sys_modules_is_a_finding(gate: ModuleType) -> None:
    """DR1 and 00-vision.md V01-4 state it as a `sys.modules` assertion, so the gate makes it."""
    findings = gate.check_discovery(clean(gate, modules=("omniweave_driver_rogue",)))
    assert clauses(findings) == ["sys.modules"]


def test_every_clause_reports_independently(gate: ModuleType) -> None:
    """Four findings, not one. A gate that stops at the first violation makes a reader fix one
    thing at a time and re-run a ten-second job between each."""
    seen = clean(
        gate,
        returncode=1,
        cards=(),
        sentinels=("omniweave_driver_rogue.imported",),
        modules=("omniweave_driver_rogue",),
        stderr="boom",
    )
    assert clauses(gate.check_discovery(seen)) == [
        "discovered",
        "discovered",
        "survived",
        "payload",
        "sys.modules",
    ]


# ---------------------------------------------------------------------------
# clause 5 — the negative control, which is the clause that makes the rest mean anything
# ---------------------------------------------------------------------------


def test_a_control_that_exits_zero_is_a_finding(gate: ModuleType) -> None:
    """An inert module body. Every absence asserted above would still hold, and would be an
    absence of instrumentation rather than an absence of execution."""
    seen = clean(gate, returncode=0, sentinels=("omniweave_driver_rogue.imported",))
    findings = gate.check_control(seen)
    assert clauses(findings) == ["control"]
    assert "not armed" in findings[0].message


def test_a_control_that_leaves_no_sentinel_is_a_finding(gate: ModuleType) -> None:
    """The site never reached `sys.path`, or the sentinel is written where the gate does not
    look. Either way clause 3 was reading an empty directory it would never have filled."""
    findings = gate.check_control(clean(gate, returncode=1, sentinels=(), decoded=False))
    assert clauses(findings) == ["control"]


# ---------------------------------------------------------------------------
# the fixture itself — two routes, and both of them armed
# ---------------------------------------------------------------------------


def test_the_fixture_installs_both_routes(gate: ModuleType, tmp_path: Path) -> None:
    """Route 1 is what `pip install` produces; route 2 names its module ONLY from inside the card.

    The two routes fail differently, which is the reason for both: an entry-point value is read by
    `importlib.metadata`, and a card's `entrypoint` is read by `tomllib` out of a file discovery
    found on `OMNIWEAVE_DRIVER_PATH`. A loader that resolved the second early would be invisible to
    a gate that only installed the first.
    """
    site = gate.build_site(tmp_path)
    dist_info = site.site / "omniweave_driver_rogue-1.0.0.dist-info"
    assert (dist_info / "entry_points.txt").is_file()
    assert (site.site / "omniweave_driver_rogue" / "driver.toml").is_file()

    assert (site.drivers / "ambush" / "driver.toml").is_file()
    assert not list(site.drivers.glob("*/*.dist-info"))
    assert (site.site / "omniweave_driver_ambush" / "__init__.py").is_file()

    assert list(site.sentinels.iterdir()) == []


def test_both_module_bodies_are_armed(gate: ModuleType, tmp_path: Path) -> None:
    """Written as a property of the fixture rather than left to the control run, which only ever
    imports one of the two. A disarmed second rogue would make route 2's absence meaningless."""
    site = gate.build_site(tmp_path)
    for module in ("omniweave_driver_rogue", "omniweave_driver_ambush"):
        body = (site.site / module / "__init__.py").read_text(encoding="utf-8")
        assert "raise SystemExit" in body
        # `repr` and not the bare path: this fixture is generated source, and on Windows a bare
        # `C:\Users\...` interpolated into a string literal is a pile of escape sequences. The
        # gate interpolates with `{sentinel!r}`, which is what makes the fixture portable.
        assert repr(str(site.sentinels / f"{module}.imported")) in body
        assert body.index("write_text") < body.index("raise SystemExit"), (
            "the sentinel must be written BEFORE the exit: a SystemExit can be caught and a file "
            "on disk cannot be un-written"
        )


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------


def test_a_disarmed_fixture_is_caught_by_the_control(gate: ModuleType, tmp_path: Path) -> None:
    """THE META-TEST. Replace both hostile bodies with inert ones and run the real gate.

    `check_discovery` still passes — nothing was imported, because there was nothing worth
    importing — and clause 5 is the only thing standing between that and a meaningless green. Both
    of its instruments must fire: the exit code is 0 and no sentinel appears.
    """
    site = gate.build_site(tmp_path)
    for module in ("omniweave_driver_rogue", "omniweave_driver_ambush"):
        (site.site / module / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

    assert gate.check_discovery(gate.observe(site, control=False)) == []
    findings = gate.check_control(gate.observe(site, control=True))
    assert clauses(findings) == ["control", "control"]


def test_a_corrupt_card_fires_clause_one_with_the_fault(gate: ModuleType, tmp_path: Path) -> None:
    """A real discovery pass over a rogue whose card will not parse.

    Discovery never raises — a broken neighbour cannot stop a catalog (section 4.5) — so the card
    simply vanishes from the catalog, which is exactly the silence clause 1 exists to break. The
    fault has to travel from `discover()` through the probe's JSON into the message, and this is
    the test that the plumbing carrying it is connected.
    """
    site = gate.build_site(tmp_path)
    (site.drivers / "ambush" / "driver.toml").write_text("this is not toml [[[", encoding="utf-8")

    findings = gate.check_discovery(gate.observe(site, control=False))
    assert clauses(findings) == ["discovered"]
    assert gate.DRIVER_PATH_ID in findings[0].message
    assert "ambush" in findings[0].message, "the fault naming the unparseable card is not reported"


def test_the_gate_passes_on_this_machine(gate: ModuleType) -> None:
    """The assertion CI makes, made here so it fails on a laptop first.

    This spawns two interpreters and builds two installations; it is the most expensive test in
    the file and it is the only one that proves the five clauses hold against a real `sys.path`,
    a real `importlib.metadata` enumeration and the real `omniweave_core.discovery`.
    """
    assert gate.main([]) == 0


def test_an_argument_is_exit_two_and_not_exit_one(gate: ModuleType) -> None:
    """1 is "INV-4 is false" and 2 is "this gate did not get to ask". CI fails on both and a human
    needs to know which one happened."""
    assert gate.main(["--refresh"]) == 2
