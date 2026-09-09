"""`discover()` — four origins, two grammars, one cache, and a loader that never raises.

Every fixture here is a real tree under `tmp_path`: a real `*.dist-info` with a real
`entry_points.txt` that `importlib.metadata` really enumerates, real `driver.toml` files that
`load_card()` really validates. A mocked `Distribution` would prove that discovery agrees with the
mock, which is the assertion this cluster least needs.

The properties, in the order 04-driver-system.md states them:

* section 4.1 — the four origins; the two names with two grammars (the entry-point VALUE is
  colon-free and dotted, the card's own `entrypoint` key carries exactly one colon); depth-1
  scanning of `OMNIWEAVE_DRIVER_PATH`;
* section 4.3 — the `driver_card_cache`, keyed `(prefix, dist_name, dist_version, card_path)` and
  validated on `(mtime_ns, size)`, and the editable-install blind spot the wholesale key has;
* section 4.4 — `discovery_slow` above the 250 ms ceiling is a report and not a refusal;
* section 4.5 — `card_missing` plus one `driver_unavailable` degradation, and **discovery never
  raises: a broken neighbour cannot stop a catalog**.

INV-4 itself — that nothing here imports a driver — is `test_discovery_never_imports.py`, because
it needs a fresh interpreter and a negative control to be worth anything.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

import pytest
from hypothesis import given
from hypothesis import strategies as st
from omniweave_core.discovery import (
    BACKEND_GROUP,
    CARD_FILENAME,
    DISCOVERY_CEILING_MS,
    DISCOVERY_DEGRADATION_KINDS,
    DRIVER_GROUP,
    DRIVER_PATH_ENV,
    OPERATOR_GROUP,
    PACKAGE_PATH_RE,
    PROJECT_DRIVER_DIR,
    TARGET_GROUP,
    TIMED_STEPS,
    CardCacheRow,
    CardSource,
    DiscoveryDegradation,
    EntryPointRef,
    MemoryCardCache,
    card_relative_path,
    catalog,
    discover,
    dist_info_triples,
    driver_path_sources,
    entry_point_value_fault,
    load_one,
    project_sources,
    tombstone_sources,
    validity_key,
)
from omniweave_core.drivers.card import DriverCard, Tombstone
from omniweave_core.drivers.catalog import compute_validity_key
from omniweave_core.limits import MAX_CARD_BYTES
from omniweave_ports.types import TrustTier

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# --------------------------------------------------------------------------------------------
# Fixtures. `MINIMAL` is the smallest card `load_card()` accepts, so a negative test asserts one
# thing; it is the same shape `test_card.py` uses, which keeps the two suites arguing about the
# same card rather than about two different ones.
# --------------------------------------------------------------------------------------------

MINIMAL = """card_schema = 1

[driver]
id = "{id}"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "pkg.driver:Cls"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""

EXEC_CARD = """card_schema = 1

[driver]
id = "parse.cad.dwg"
port = "parse/1"
version = "0.1.0"
schema_version = 1
exec = ["bin/owdwg", "--serve"]
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["image/vnd.dwg"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[isolation]
requires = "subproc"

[licence.code]
spdx = "Apache-2.0"
"""

TOMBSTONE = """card_schema = 1

[driver]
id = "parse.page.surya"
port = "parse/1"
title = "surya"

[tombstone]
reason = "MODEL_LICENSE Attachment A clause 2(c) is a competitor bar with no revenue threshold."
replaced_by = "parse.page.olmocr"
review_by = "2027-06-01"

[licence.weights]
licence_sha256 = "sha256:e1f69b64dee2f1641a9b1ab12adf24d6e1f69b64dee2f1641a9b1ab12adf24d6"
weights_revision = "n/a"
"""


def card(driver_id: str) -> str:
    return MINIMAL.format(id=driver_id)


def dist_info(
    site: Path,
    *,
    dist: str,
    version: str = "1.0.0",
    groups: dict[str, dict[str, str]],
    editable: bool = False,
) -> Path:
    """Write a `*.dist-info` `importlib.metadata` will really enumerate."""
    info = site / f"{dist.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {dist}\nVersion: {version}\n", encoding="utf-8"
    )
    lines: list[str] = []
    for group, rows in groups.items():
        lines.append(f"[{group}]")
        lines.extend(f"{name} = {value}" for name, value in rows.items())
        lines.append("")
    (info / "entry_points.txt").write_text("\n".join(lines), encoding="utf-8")
    if editable:
        (info / "direct_url.json").write_text(
            json.dumps({"url": "file:///src", "dir_info": {"editable": True}}), encoding="utf-8"
        )
    return info


def package(site: Path, name: str, *, text: str | None) -> Path:
    """A package directory holding a `driver.toml` — or holding none, which is the point."""
    pkg = site / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    if text is not None:
        (pkg / CARD_FILENAME).write_text(text, encoding="utf-8")
    return pkg


def dists(site: Path) -> Sequence[object]:
    """`Distribution.discover(path=[site])` — this site directory and nothing else.

    Scoping the enumeration is what makes the assertions exact: the interpreter running the
    suite has hundreds of real distributions installed, and a test asserting "three cards" must
    not be able to fail because a neighbouring package grew an `omniweave.drivers` row.
    """
    from importlib.metadata import Distribution  # noqa: PLC0415 - scoped to the fixture site

    return list(Distribution.discover(path=[str(site)]))


def run(site: Path, **kwargs: object) -> object:
    """`discover()` over one fixture site, with the shipped tombstones out of the way."""
    return discover(
        search_path=[str(site)],
        distributions=dists(site),
        tombstone_dir=kwargs.pop("tombstone_dir", site / "no-tombstones-here"),
        **kwargs,  # type: ignore[arg-type]
    )


def ids(result: object) -> list[str]:
    out: list[str] = []
    for found in result.found:  # type: ignore[attr-defined]
        out.append(found.card.identity.id if isinstance(found.card, DriverCard) else found.card.id)
    return sorted(out)


# --------------------------------------------------------------------------------------------
# 1. The four origins.
# --------------------------------------------------------------------------------------------


def test_all_four_origins_are_discovered_in_one_pass(tmp_path: Path) -> None:
    """04-driver-system.md section 4.1's table, end to end.

    `entry_point` through `locate_file`, `driver_path` and `project` through a depth-1 scan, and
    `tombstone` from package data. One pass finds all four, and each card carries the origin it
    was found at — which is the fact `[driver] exec` is gated on and the input `trust` (E13) is
    later computed from. A card can never name its own origin, because a card that could name
    its own origin could name its own trust.
    """
    site = tmp_path / "site"
    package(site, "omniweave_driver_ep", text=card("parse.notebook.ep"))
    dist_info(
        site,
        dist="omniweave-driver-ep",
        groups={DRIVER_GROUP: {"parse.notebook.ep": "omniweave_driver_ep"}},
    )

    (tmp_path / "dp" / "local").mkdir(parents=True)
    (tmp_path / "dp" / "local" / CARD_FILENAME).write_text(card("parse.notebook.local"))

    proj = tmp_path / "proj" / Path(*PROJECT_DRIVER_DIR) / "vendored"
    proj.mkdir(parents=True)
    (proj / CARD_FILENAME).write_text(card("parse.notebook.proj"))

    tombs = tmp_path / "tombstones"
    tombs.mkdir()
    (tombs / "parse.page.surya.toml").write_text(TOMBSTONE)

    result = run(
        site,
        env={DRIVER_PATH_ENV: str(tmp_path / "dp")},
        project_root=tmp_path / "proj",
        tombstone_dir=tombs,
    )

    assert ids(result) == [
        "parse.notebook.ep",
        "parse.notebook.local",
        "parse.notebook.proj",
        "parse.page.surya",
    ]
    assert {f.source.origin for f in result.found} == {
        "entry_point",
        "driver_path",
        "project",
        "tombstone",
    }
    assert result.faults == ()
    assert result.degradations == ()
    assert [c.origin for c in result.cards] == ["entry_point", "driver_path", "project"]
    assert [t.origin for t in result.tombstones] == ["tombstone"]


def test_a_tombstone_carries_its_quoted_reason_and_named_replacement(tmp_path: Path) -> None:
    """DR22: a removed driver resolves to a quoted reason and a named replacement, never to
    "unknown driver" (04-driver-system.md section 7.5). Discovery is where the reason enters the
    catalog, so a tombstone that discovery dropped would make DR22 unimplementable downstream."""
    tombs = tmp_path / "tombstones"
    tombs.mkdir()
    (tombs / "surya.toml").write_text(TOMBSTONE)
    result = run(tmp_path / "site", tombstone_dir=tombs)
    (stone,) = result.tombstones
    assert isinstance(stone, Tombstone)
    assert "competitor bar" in stone.reason
    assert stone.replaced_by == "parse.page.olmocr"
    assert stone.review_by == "2027-06-01"


def test_an_absent_tombstone_directory_is_not_a_fault(tmp_path: Path) -> None:
    """A source checkout before the six shipped tombstones land, or a wheel built without the
    package data, still has to be able to build a catalog. Discovery never raises."""
    result = run(tmp_path / "site", tombstone_dir=tmp_path / "does-not-exist")
    assert result.found == ()
    assert result.faults == ()


def test_the_tombstone_default_is_package_data_and_not_the_working_directory() -> None:
    """`tombstone_sources()` with no argument resolves against this module's own location.

    `os.getcwd()` and `Path(".")` are banned in library code: a relative root resolves against
    whatever directory the process happens to be in, which is how graphify #1774 wrote its cache
    into the analysed tree. At P1 the six shipped tombstones are not on disk yet, so the call
    returns `()` — and that empty answer is exactly the "never raises" property, not a bug.
    """
    import omniweave_core.discovery as discovery_module  # noqa: PLC0415

    expected = Path(discovery_module.__file__).resolve().parent / "drivers" / "tombstones"
    sources = tombstone_sources()
    assert all(s.path.parent == expected for s in sources)
    assert all(s.origin == "tombstone" for s in sources)


def test_an_exec_card_is_legal_from_driver_path_and_refused_from_an_entry_point(
    tmp_path: Path,
) -> None:
    """E7: `exec` is legal only for `origin in {driver_path, project}`.

    That gating is discovery's, because `origin` is discovery's fact. It is what keeps a
    non-Python driver permanently `trust = local`, unable to reach `inproc` and unable to satisfy
    `require_lock = true` (04-driver-system.md section 4.1). The same bytes must therefore load
    from one origin and be refused from the other, which is what this asserts.
    """
    local = tmp_path / "dp" / "dwg"
    local.mkdir(parents=True)
    (local / CARD_FILENAME).write_text(EXEC_CARD)
    result = run(tmp_path / "site", env={DRIVER_PATH_ENV: str(tmp_path / "dp")})
    assert ids(result) == ["parse.cad.dwg"]

    site = tmp_path / "site"
    package(site, "omniweave_driver_dwg", text=EXEC_CARD)
    dist_info(
        site,
        dist="omniweave-driver-dwg",
        groups={DRIVER_GROUP: {"parse.cad.dwg": "omniweave_driver_dwg"}},
    )
    from_wheel = run(site)
    assert from_wheel.found == ()
    (fault,) = from_wheel.faults
    assert fault.symbol == "OW_CARD_INVALID"
    assert "exec" in fault.detail


# --------------------------------------------------------------------------------------------
# 2. The two names with two grammars. This is the subtlest thing in the cluster.
# --------------------------------------------------------------------------------------------


def ref(value: str) -> EntryPointRef:
    return EntryPointRef(
        group=DRIVER_GROUP, name="parse.x.y", value=value, dist_name="d", dist_version="1"
    )


def test_the_entry_point_value_carrying_a_colon_is_rejected_and_says_which_grammar_it_is() -> None:
    """`"pkg.driver:Cls"` in an entry-point value is the CARD's grammar in the wrong field.

    The entry-point value is a colon-free dotted package path; the card's own `[driver]
    entrypoint` is `<dotted.module>:<Attr>`, and `activate()` is the only site in the framework
    that resolves the colon form, because it must assert the loaded *class's* `PORT` and
    `SCHEMA_VERSION` and a package has no such attributes (04-driver-system.md section 4.1, DR2).
    The message has to say that, or a developer fixes the wrong file.
    """
    fault = entry_point_value_fault(ref("pkg.driver:Cls"))
    assert fault is not None
    assert fault.detail == "entry_point_value_malformed"
    assert "':'" in fault.source
    assert "entrypoint" in fault.source


def test_the_entry_point_value_carrying_a_slash_is_rejected() -> None:
    """`setuptools._entry_points.validate` raises at BUILD time on a path-shaped value, so
    reaching this in a wheel means the wheel was not built by setuptools — which is exactly when
    a defence in depth earns its keep (04-driver-system.md section 4.1)."""
    for value in ("pkg/driver.toml", "pkg\\driver.toml"):
        fault = entry_point_value_fault(ref(value))
        assert fault is not None, value
        assert "path separator" in fault.source


def test_a_malformed_entry_point_value_yields_a_fault_and_no_card(tmp_path: Path) -> None:
    """The rejection is at DISCOVERY time and it costs the rest of the catalog nothing."""
    site = tmp_path / "site"
    package(site, "omniweave_driver_good", text=card("parse.notebook.good"))
    dist_info(
        site,
        dist="omniweave-driver-good",
        groups={DRIVER_GROUP: {"parse.notebook.good": "omniweave_driver_good"}},
    )
    dist_info(
        site,
        dist="omniweave-driver-bad",
        groups={DRIVER_GROUP: {"parse.notebook.bad": "omniweave_driver_bad:Cls"}},
    )
    result = run(site)
    assert ids(result) == ["parse.notebook.good"]
    (fault,) = result.faults
    assert fault.detail == "entry_point_value_malformed"
    assert fault.dist_name == "omniweave-driver-bad"


def test_a_value_with_an_empty_segment_cannot_escape_the_distribution() -> None:
    """`".."` and `"a..b"` are rejected, and the reason is a real escape, not tidiness.

    `card_relative_path` maps `.` to `/` before the join, so an empty dotted segment becomes a
    doubled slash. Leading, that makes the joined path **absolute** and it leaves the distribution
    entirely; interior, `pathlib` silently collapses it, so `"a..b"` would serve the card of the
    package `a.b` for a value nobody wrote. Both are the same defect and the same fix: an
    **absolute** path — the
    join leaves the distribution entirely. Requiring every segment to be a Python identifier
    removes the whole class without a second, subtler rule.
    """
    escaped = PurePosixPath("/site/pkg") / card_relative_path("..")
    assert escaped.is_absolute()
    assert not escaped.is_relative_to(PurePosixPath("/site/pkg"))
    assert "//" in card_relative_path("a..b")
    assert PurePosixPath(card_relative_path("a..b")) == PurePosixPath("a/b/driver.toml")
    for value in ("..", "a..b", ".pkg", "pkg.", "", "1pkg", "pkg-name", "pkg name"):
        assert entry_point_value_fault(ref(value)) is not None, value


@given(st.text(max_size=40))
def test_a_value_accepted_by_the_grammar_can_never_escape_its_distribution(value: str) -> None:
    """The property over adversarial input, rather than over the eight spellings above.

    Either the value is refused, or the relative path it produces stays strictly inside the
    distribution: relative, no empty component, no `..`, and ending at `driver.toml`. Stated over
    `PurePosixPath` because `locate_file` joins forward slashes on every platform, so the
    property must not depend on which one the suite is running on.
    """
    fault = entry_point_value_fault(ref(value))
    if fault is not None:
        assert not PACKAGE_PATH_RE.match(value)
        return
    relative = PurePosixPath(card_relative_path(value))
    assert not relative.is_absolute()
    assert relative.parts[-1] == CARD_FILENAME
    assert "" not in relative.parts
    assert ".." not in relative.parts
    assert (PurePosixPath("/site") / relative).is_relative_to(PurePosixPath("/site"))


def test_the_card_is_located_by_name_and_never_by_scanning_record(tmp_path: Path) -> None:
    """The located path is `locate_file(value.replace(".", "/") + "/driver.toml")` exactly.

    Scanning `Distribution.files` / `RECORD` to find cards is forbidden: it was measured at
    **2124 ms** for 328 installed distributions against a claimed 1-4 ms — three orders of
    magnitude wrong, on the discovery path (04-driver-system.md section 4.1). This asserts the
    cheap lookup is the one taken, by putting the card where only the name-join finds it: the
    distribution's `RECORD` file is absent entirely, so a scan would find nothing.
    """
    site = tmp_path / "site"
    package(site, "omniweave_driver_deep", text=None)
    nested = site / "omniweave_driver_deep" / "sub"
    nested.mkdir()
    (nested / CARD_FILENAME).write_text(card("parse.notebook.deep"))
    dist_info(
        site,
        dist="omniweave-driver-deep",
        groups={DRIVER_GROUP: {"parse.notebook.deep": "omniweave_driver_deep.sub"}},
    )
    result = run(site)
    (found,) = result.found
    assert found.source.card_path == "omniweave_driver_deep/sub/driver.toml"
    assert found.source.path == nested / CARD_FILENAME
    assert not (site / "omniweave_driver_deep-1.0.0.dist-info" / "RECORD").exists()


# --------------------------------------------------------------------------------------------
# 3. The groups. Cards come from one of them.
# --------------------------------------------------------------------------------------------


def test_the_targets_group_is_enumerated_but_mints_no_second_card(tmp_path: Path) -> None:
    """`omniweave.targets "pptx" = "omniweave_target_pptx"` aliases the SAME dotted package that
    `omniweave.drivers "compile.pptx.native"` names (04-driver-system.md section 4.1). Reading
    cards from both groups would load one `driver.toml` twice under two different keys, and the
    second copy would then collide with the first in `Registry`."""
    site = tmp_path / "site"
    package(site, "omniweave_target_pptx", text=card("parse.notebook.pptx"))
    dist_info(
        site,
        dist="omniweave-target-pptx",
        groups={
            DRIVER_GROUP: {"parse.notebook.pptx": "omniweave_target_pptx"},
            TARGET_GROUP: {"pptx": "omniweave_target_pptx"},
            BACKEND_GROUP: {"vseg": "omniweave_target_pptx"},
        },
    )
    result = run(site)
    assert len(result.found) == 1
    assert [r.name for r in result.targets] == ["pptx"]
    assert [r.name for r in result.backends] == ["vseg"]


def test_the_operators_group_is_reserved_and_discovery_does_not_read_it(tmp_path: Path) -> None:
    """`omniweave.operators` "stays reserved and uncreated" (04-driver-system.md section 4.1). A
    group that quietly began working would make the reservation untrue, so the assertion is that
    a row in it produces nothing at all — not a card, not a target, not a fault."""
    site = tmp_path / "site"
    package(site, "omniweave_operator_x", text=card("parse.notebook.op"))
    dist_info(
        site,
        dist="omniweave-operator-x",
        groups={OPERATOR_GROUP: {"parse.notebook.op": "omniweave_operator_x"}},
    )
    result = run(site)
    assert result.found == ()
    assert result.targets == ()
    assert result.backends == ()
    assert result.faults == ()


# --------------------------------------------------------------------------------------------
# 4. Section 4.5 — discovery never raises.
# --------------------------------------------------------------------------------------------


def test_a_missing_card_is_a_degradation_and_a_fault_and_never_an_exception(
    tmp_path: Path,
) -> None:
    """Section 4.5's first named failure mode, in full.

    "The entry point exists and the card does not" — a partially-uninstalled distribution, a
    wheel built without package data. It is `CARD_INVALID` with detail `card_missing`, **plus**
    one `Degradation(kind="driver_unavailable")` naming the distribution. The degradation names
    the distribution and not the file, because "reinstall omniweave-office" is the fix and "a
    card was missing" is not.
    """
    site = tmp_path / "site"
    package(site, "omniweave_driver_gone", text=None)
    dist_info(
        site,
        dist="omniweave-driver-gone",
        groups={DRIVER_GROUP: {"parse.notebook.gone": "omniweave_driver_gone"}},
    )
    result = run(site)
    assert result.found == ()
    (fault,) = result.faults
    assert (fault.symbol, fault.detail) == ("OW_CARD_INVALID", "card_missing")
    assert fault.dist_name == "omniweave-driver-gone"
    (degradation,) = result.degradations
    assert degradation.kind == "driver_unavailable"
    assert "omniweave-driver-gone" in degradation.message
    assert degradation.wanted_driver == "parse.notebook.gone"
    assert degradation.knob is None


def test_one_malformed_card_among_five_does_not_stop_the_other_four(tmp_path: Path) -> None:
    """**A broken neighbour cannot stop a catalog** (04-driver-system.md section 4.5).

    Five distributions, five different ways of being wrong or right: one good, one whose card is
    missing, one whose card is over `MAX_CARD_BYTES`, one from a grammar this build does not
    implement, and one whose top-level table is not in the closed set. Four faults, one card, no
    exception — and every fault names its own code, so `CARD_SCHEMA_TOO_NEW` still prints as an
    upgrade instruction rather than as a parse failure.
    """
    site = tmp_path / "site"
    cases = {
        "good": card("parse.notebook.good"),
        "missing": None,
        "huge": card("parse.notebook.huge") + "\n# " + "x" * MAX_CARD_BYTES,
        "future": card("parse.notebook.future").replace("card_schema = 1", "card_schema = 2"),
        "alien": card("parse.notebook.alien") + "\n[nonsense]\nx = 1\n",
    }
    for name, text in cases.items():
        package(site, f"omniweave_driver_{name}", text=text)
        dist_info(
            site,
            dist=f"omniweave-driver-{name}",
            groups={DRIVER_GROUP: {f"parse.notebook.{name}": f"omniweave_driver_{name}"}},
        )
    result = run(site)

    assert ids(result) == ["parse.notebook.good"]
    assert len(result.faults) == 4
    by_dist = {f.dist_name: f for f in result.faults}
    assert by_dist["omniweave-driver-missing"].detail == "card_missing"
    assert by_dist["omniweave-driver-future"].symbol == "OW_CARD_SCHEMA_TOO_NEW"
    assert "upgrade" in by_dist["omniweave-driver-future"].fix
    assert by_dist["omniweave-driver-huge"].symbol == "OW_CARD_INVALID"
    assert "MAX_CARD_BYTES" in by_dist["omniweave-driver-huge"].detail
    assert by_dist["omniweave-driver-alien"].symbol == "OW_CARD_INVALID"
    # Only the missing card is a driver_unavailable: a card that is PRESENT and wrong is the
    # author's bug, not an absent distribution.
    assert [d.kind for d in result.degradations] == ["driver_unavailable"]


def test_two_distributions_declaring_one_id_are_both_carried(tmp_path: Path) -> None:
    """Discovery reports both; `Registry.register` raises `DuplicateDriver` and `resolve()` emits
    `ID_COLLISION_UNQUALIFIED` (04-driver-system.md section 4.5).

    A dict keyed on id here would drop one of the two silently, which is precisely the DataFlow
    receipt the plan cites: a registry keyed on a bare `__name__`, first-wins and silent, so two
    plugins with one class name means one vanishes with no diagnostic. `Discovery.found` is a
    tuple of pairs for that reason and no other.
    """
    site = tmp_path / "site"
    for name in ("one", "two"):
        package(site, f"omniweave_driver_{name}", text=card("parse.notebook.same"))
        dist_info(
            site,
            dist=f"omniweave-driver-{name}",
            groups={DRIVER_GROUP: {"parse.notebook.same": f"omniweave_driver_{name}"}},
        )
    result = run(site)
    assert ids(result) == ["parse.notebook.same", "parse.notebook.same"]
    assert {f.source.dist_name for f in result.found} == {
        "omniweave-driver-one",
        "omniweave-driver-two",
    }


def test_an_unreadable_card_directory_is_a_fault_and_not_an_exception(tmp_path: Path) -> None:
    """`locate_file` pointed at a DIRECTORY rather than a file. `read_card_bytes` raises `OSError`
    (`IsADirectoryError` on POSIX, `PermissionError` on Windows) and discovery records it as
    `card_missing` — the same mode as an absent file, because from the operator's side it is."""
    site = tmp_path / "site"
    pkg = package(site, "omniweave_driver_dir", text=None)
    (pkg / CARD_FILENAME).mkdir()
    dist_info(
        site,
        dist="omniweave-driver-dir",
        groups={DRIVER_GROUP: {"parse.notebook.dir": "omniweave_driver_dir"}},
    )
    result = run(site)
    assert result.found == ()
    (fault,) = result.faults
    assert fault.detail == "card_missing"


# --------------------------------------------------------------------------------------------
# 5. The directory scans. Depth 1, never recursive.
# --------------------------------------------------------------------------------------------


def test_the_driver_path_is_scanned_depth_one_and_not_recursively(tmp_path: Path) -> None:
    """`*/driver.toml`, one level down and no further (04-driver-system.md section 4.1).

    A recursive walk over a development tree finds the `driver.toml` inside a nested `.venv`, a
    `build/` directory and a vendored checkout — three copies of one card at three paths, with no
    way to tell which the author meant — and the cost budget prices this step at ~0.1 ms per
    directory (section 4.3 step 3), which a walk is not.
    """
    root = tmp_path / "dp"
    (root / "shallow").mkdir(parents=True)
    (root / "shallow" / CARD_FILENAME).write_text(card("parse.notebook.shallow"))
    (root / "outer" / "inner").mkdir(parents=True)
    (root / "outer" / "inner" / CARD_FILENAME).write_text(card("parse.notebook.deep"))
    (root / "outer" / "inner" / "deeper").mkdir()
    (root / "outer" / "inner" / "deeper" / CARD_FILENAME).write_text(card("parse.notebook.deeper"))

    sources = driver_path_sources({DRIVER_PATH_ENV: str(root)})
    assert [s.path for s in sources] == [root / "shallow" / CARD_FILENAME]


def test_a_driver_toml_in_the_scanned_root_itself_is_not_picked_up(tmp_path: Path) -> None:
    """The pattern is `*/driver.toml` and it has a directory component. That directory's name is
    what a `driver_path` entry is identified by in a report, so a card with no directory has no
    name to be reported under."""
    root = tmp_path / "dp"
    root.mkdir()
    (root / CARD_FILENAME).write_text(card("parse.notebook.rootless"))
    assert driver_path_sources({DRIVER_PATH_ENV: str(root)}) == ()


def test_the_driver_path_reads_every_directory_on_the_pathsep_list_in_order(
    tmp_path: Path,
) -> None:
    """`OMNIWEAVE_DRIVER_PATH` is read as an `os.pathsep`-separated list, the universal reading of
    a `*_PATH` variable. Order is preserved so an operator can shadow a card by listing its
    directory first; discovery reports both and `Registry` decides, because two cards with one id
    is `DuplicateDriver`'s to raise and not this function's to resolve."""
    first, second = tmp_path / "a", tmp_path / "b"
    for root, name in ((first, "alpha"), (second, "beta")):
        (root / name).mkdir(parents=True)
        (root / name / CARD_FILENAME).write_text(card(f"parse.notebook.{name}"))
    joined = os.pathsep.join([str(first), "", str(second)])
    sources = driver_path_sources({DRIVER_PATH_ENV: joined})
    assert [s.path.parent.name for s in sources] == ["alpha", "beta"]


def test_no_declared_environment_yields_no_driver_path_cards(tmp_path: Path) -> None:
    """`env=None` means "no environment was declared" and yields nothing — an honest empty answer
    rather than a silent read of `os.environ`. The environment is one of the ambient inputs
    02-architecture.md section 8 clause (e) makes a caller declare, because a function that reads
    it cannot be varied by a test and behaves differently under `ow serve` than under
    `ow ingest`."""
    (tmp_path / "dp" / "x").mkdir(parents=True)
    (tmp_path / "dp" / "x" / CARD_FILENAME).write_text(card("parse.notebook.x"))
    assert driver_path_sources(None) == ()
    assert driver_path_sources({}) == ()


def test_the_project_origin_is_dot_omniweave_drivers_under_the_injected_root(
    tmp_path: Path,
) -> None:
    """`.omniweave/drivers/<name>/driver.toml`, resolved against a root that ARRIVES AS A
    PARAMETER. `os.getcwd()` and `Path(".")` are banned in library code — a relative root resolves
    against whatever directory the process happens to be in, which is how graphify #1774 wrote its
    cache into the analysed tree."""
    root = tmp_path / "proj"
    (root / Path(*PROJECT_DRIVER_DIR) / "vend").mkdir(parents=True)
    (root / Path(*PROJECT_DRIVER_DIR) / "vend" / CARD_FILENAME).write_text(card("parse.n.vend"))
    (root / "drivers" / "decoy").mkdir(parents=True)
    (root / "drivers" / "decoy" / CARD_FILENAME).write_text(card("parse.n.decoy"))

    sources = project_sources(root)
    assert [s.path.parent.name for s in sources] == ["vend"]
    assert all(s.origin == "project" for s in sources)
    assert project_sources(None) == ()


# --------------------------------------------------------------------------------------------
# 6. The driver_card_cache: keyed on four columns, validated on (mtime_ns, size).
# --------------------------------------------------------------------------------------------


def one_source(tmp_path: Path, *, text: str = "", origin: str = "driver_path") -> CardSource:
    path = tmp_path / "cards" / "d" / CARD_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text or card("parse.notebook.cached"), encoding="utf-8")
    return CardSource(origin=origin, path=path, card_path=str(path))


def test_the_cache_hits_when_neither_mtime_ns_nor_size_moved(tmp_path: Path) -> None:
    """Section 4.3: the row is keyed `(prefix, dist_name, dist_version, card_path)` and validated
    on `(mtime_ns, size)`. A second load of an untouched card is a hit."""
    source = one_source(tmp_path)
    cache = MemoryCardCache()
    first = load_one(source, cache=cache)
    assert first.found is not None and first.found.cached is False
    assert len(cache) == 1
    second = load_one(source, cache=cache)
    assert second.found is not None and second.found.cached is True
    assert second.found.card.card_sha256 == first.found.card.card_sha256


def test_the_cache_misses_when_mtime_ns_moves_although_the_size_did_not(tmp_path: Path) -> None:
    """The two-column validity key, one column at a time. A card rewritten with the same length
    — a version bumped from `0.1.0` to `0.9.0`, say — moves `mtime_ns` and nothing else, and a
    cache blind to that serves the old contract to `resolve()`."""
    source = one_source(tmp_path)
    cache = MemoryCardCache()
    load_one(source, cache=cache)
    before = source.path.stat()
    source.path.write_text(card("parse.notebook.cached").replace("0.1.0", "0.9.0"))
    after = source.path.stat()
    assert after.st_size == before.st_size
    os.utime(source.path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))

    outcome = load_one(source, cache=cache)
    assert outcome.found is not None and outcome.found.cached is False
    assert isinstance(outcome.found.card, DriverCard)
    assert outcome.found.card.identity.version == "0.9.0"


def test_the_cache_misses_when_the_size_moves_although_the_mtime_ns_did_not(
    tmp_path: Path,
) -> None:
    """The other column, with `mtime_ns` pinned back to the instant the row was written. A
    filesystem with a coarse timestamp — or a fast edit — makes this the only signal there is."""
    source = one_source(tmp_path)
    cache = MemoryCardCache()
    load_one(source, cache=cache)
    stat = source.path.stat()
    source.path.write_text(card("parse.notebook.cached") + "\n# a longer file\n")
    os.utime(source.path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.path.stat().st_mtime_ns == stat.st_mtime_ns

    outcome = load_one(source, cache=cache)
    assert outcome.found is not None and outcome.found.cached is False


def test_a_cache_row_whose_digest_disagrees_with_the_bytes_is_a_miss_not_a_wrong_card(
    tmp_path: Path,
) -> None:
    """A corrupt row is dropped and the file is read. A cache that can silently serve the wrong
    bytes for a `card_sha256` the lockfile pins is worse than no cache at all (AP-6: no soft
    fallback on an identity input)."""
    source = one_source(tmp_path)
    cache = MemoryCardCache()
    load_one(source, cache=cache)
    good = cache.get((source.origin, "", "", source.card_path))
    assert good is not None
    cache.put(
        CardCacheRow(
            prefix=good.prefix,
            dist_name=good.dist_name,
            dist_version=good.dist_version,
            card_path=good.card_path,
            mtime_ns=good.mtime_ns,
            size=good.size,
            card_json=json.dumps(card("parse.notebook.impostor")),
            card_sha256=good.card_sha256,
        )
    )
    outcome = load_one(source, cache=cache)
    assert outcome.found is not None
    assert isinstance(outcome.found.card, DriverCard)
    assert outcome.found.card.identity.id == "parse.notebook.cached"
    assert outcome.found.cached is False


def test_the_cache_key_is_the_four_columns_and_the_payload_round_trips(tmp_path: Path) -> None:
    """`prefix` is the ORIGIN. The plan gives the column no meaning anywhere; it is the only value
    that disambiguates the other three, because a `driver_path` card has no distribution and two
    origins could otherwise collide on one absolute path. Section 4.3's hit-path expression,
    `json.loads(driver_card_cache.card_json)`, is `CardCacheRow.text`."""
    source = one_source(tmp_path, origin="project")
    cache = MemoryCardCache()
    load_one(source, cache=cache)
    assert len(cache) == 1
    row = cache.get(("project", "", "", str(source.path)))
    assert row is not None, "the key is the origin plus the three columns and nothing else"
    assert row.key == ("project", "", "", str(source.path))
    assert row.text.encode("utf-8") == source.path.read_bytes()
    assert row.card_sha256.startswith("sha256:")
    assert (row.mtime_ns, row.size) == (source.path.stat().st_mtime_ns, source.path.stat().st_size)


def test_no_cache_at_all_still_loads_every_card(tmp_path: Path) -> None:
    """`cache=None` disables caching entirely — the shape a first run and `ow drivers check` take.
    Nothing about correctness may depend on the cache being present."""
    source = one_source(tmp_path)
    outcome = load_one(source, cache=None)
    assert outcome.found is not None and outcome.found.cached is False


def test_a_wholesale_valid_key_skips_the_stat_but_never_for_an_editable_install(
    tmp_path: Path,
) -> None:
    """Section 4.3's blind spot, and it is the developer's own workflow.

    The validity key stats `*.dist-info`; `uv pip install -e .` leaves `dist-info` untouched while
    the author edits `driver.toml` in the source tree, so a wholesale-valid cache would serve the
    OLD card through the entire edit-conform-fix loop. Resolution: an editable distribution is
    **always** stat'ed per card, wholesale key or not.

    The instrument is a card deleted after its row was written: with the wholesale key trusted the
    non-editable source still returns the cached card, and the editable one must not.
    """
    plain = one_source(tmp_path / "plain")
    editable = CardSource(
        origin="entry_point",
        path=one_source(tmp_path / "edit").path,
        card_path="pkg/driver.toml",
        dist_name="omniweave-driver-edit",
        dist_version="1.0.0",
        editable=True,
    )
    cache = MemoryCardCache()
    load_one(plain, cache=cache)
    load_one(editable, cache=cache)
    plain.path.unlink()
    editable.path.unlink()

    assert load_one(plain, cache=cache, trust_cache=True).found is not None
    stale = load_one(editable, cache=cache, trust_cache=True)
    assert stale.found is None
    assert stale.fault is not None and stale.fault.detail == "card_missing"


def test_a_second_pass_over_an_unchanged_machine_is_all_cache_hits(tmp_path: Path) -> None:
    """The end-to-end warm row: `discover()` twice over the same tree, the second run handed the
    first run's `validity_key`. Every card is a hit, and the answers agree."""
    site = tmp_path / "site"
    package(site, "omniweave_driver_warm", text=card("parse.notebook.warm"))
    dist_info(
        site,
        dist="omniweave-driver-warm",
        groups={DRIVER_GROUP: {"parse.notebook.warm": "omniweave_driver_warm"}},
    )
    cache = MemoryCardCache()
    cold = run(site, cache=cache)
    warm = run(site, cache=cache, cached_validity_key=cold.validity_key)
    assert [f.cached for f in cold.found] == [False]
    assert [f.cached for f in warm.found] == [True]
    assert ids(cold) == ids(warm)
    assert cold.validity_key == warm.validity_key


# --------------------------------------------------------------------------------------------
# 7. The wholesale validity key — 1.01 ms for 328 distributions, against 2124 ms for a RECORD scan.
# --------------------------------------------------------------------------------------------


def test_the_validity_key_moves_on_an_installed_distributions_mtime_and_size(
    tmp_path: Path,
) -> None:
    """The key is over `(dist-info path, mtime_ns, size)` triples and not over the paths alone: a
    wheel reinstalled at the same version moves `mtime_ns`, and an in-place edit of
    `entry_points.txt` moves `size`. A key blind to either serves a stale roster."""
    site = tmp_path / "site"
    info = dist_info(site, dist="omniweave-driver-k", groups={DRIVER_GROUP: {"a.b.c": "pkg"}})
    base = validity_key([str(site)])

    assert validity_key([str(site)]) == base, "the key must be stable over an unchanged tree"

    stat = info.stat()
    os.utime(info, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000))
    reinstalled = validity_key([str(site)])
    assert reinstalled != base, "a wheel reinstalled at the same version moves mtime_ns"

    dist_info(site, dist="omniweave-driver-second", groups={DRIVER_GROUP: {"d.e.f": "pkg2"}})
    installed = validity_key([str(site)])
    assert installed not in {base, reinstalled}, "installing a distribution moves the key"

    shutil.rmtree(site / "omniweave_driver_second-1.0.0.dist-info")
    assert validity_key([str(site)]) == reinstalled, "an uninstall returns the key it moved from"


def test_the_validity_key_ignores_files_that_are_not_install_metadata(tmp_path: Path) -> None:
    """It stats `*.dist-info` and `*.egg-info` and nothing else. A source tree beside the site
    directory changes constantly and must not invalidate a roster it cannot affect."""
    site = tmp_path / "site"
    dist_info(site, dist="omniweave-driver-k", groups={DRIVER_GROUP: {"a.b.c": "pkg"}})
    base = validity_key([str(site)])
    (site / "some_package").mkdir()
    (site / "some_package" / "module.py").write_text("x = 1\n")
    assert validity_key([str(site)]) == base


def test_the_validity_key_survives_a_search_path_entry_that_does_not_exist(
    tmp_path: Path,
) -> None:
    """`sys.path` routinely carries directories that are absent, empty strings and zip files.
    A missing root is skipped rather than being an error, because discovery never raises."""
    site = tmp_path / "site"
    dist_info(site, dist="omniweave-driver-k", groups={DRIVER_GROUP: {"a.b.c": "pkg"}})
    assert validity_key([str(site), str(tmp_path / "gone"), ""]) == validity_key([str(site)])


# --------------------------------------------------------------------------------------------
# 8. Section 4.4 — the ceiling is a report, not a refusal.
# --------------------------------------------------------------------------------------------


def clock(steps: Iterable[float]) -> object:
    """A monotonic clock that advances by a fixed amount on every other reading.

    Injected because `time.time()` is banned in library code and because a test asserting the
    250 ms ceiling must be able to cross it without actually taking 250 ms.
    """
    ticks = list(steps)
    state = {"now": 0.0, "i": 0}

    def read() -> float:
        if state["i"] % 2 == 1:  # every close of a `_timed` block advances the clock
            state["now"] += ticks[min(state["i"] // 2, len(ticks) - 1)]
        state["i"] += 1
        return state["now"]

    return read


def test_crossing_the_ceiling_records_discovery_slow_and_still_returns_the_catalog(
    tmp_path: Path,
) -> None:
    """Section 4.4: "It is **not** a failure: a user with 900 installed distributions gets a slow
    catalog and a report, not a refusal."

    The message names the slowest step and the installed-distribution count, which are the two
    facts that separate "the environment is large" from "omniweave regressed" — the warm row of
    the budget ladder is dominated by a single `entry_points()` call whose cost is a property of
    the environment rather than of omniweave. `knob is None` is a positive assertion: no
    configuration key raises this ceiling.
    """
    site = tmp_path / "site"
    package(site, "omniweave_driver_slow", text=card("parse.notebook.slow"))
    dist_info(
        site,
        dist="omniweave-driver-slow",
        groups={DRIVER_GROUP: {"parse.notebook.slow": "omniweave_driver_slow"}},
    )
    result = run(site, monotonic=clock([0.001, 0.001, 0.001, 0.001, 0.001, 0.4]))

    assert ids(result) == ["parse.notebook.slow"], "a slow catalog is still a catalog"
    (degradation,) = result.degradations
    assert degradation.kind == "discovery_slow"
    assert "'cards'" in degradation.message
    assert "1 installed distributions" in degradation.message
    assert str(DISCOVERY_CEILING_MS) in degradation.message
    assert degradation.knob is None
    assert result.total_ms > DISCOVERY_CEILING_MS


def test_a_fast_catalog_records_no_degradation_and_times_all_six_steps(tmp_path: Path) -> None:
    """The six steps are 04-driver-system.md section 4.3's table rows 1-7, with the per-card hit
    and miss folded together because a caller cannot act on the split. Rows 8 and 9 — the probe
    verdict cache and `catalog_digest` — are absent because they are `catalog.py`'s."""
    result = run(tmp_path / "site")
    assert result.degradations == ()
    assert tuple(result.elapsed_ms) == TIMED_STEPS
    assert all(value >= 0.0 for value in result.elapsed_ms.values())


def test_a_degradation_kind_outside_the_closed_two_is_refused() -> None:
    """`DiscoveryDegradation` validates against `DISCOVERY_DEGRADATION_KINDS`, both of which are
    real members of 15-observability.md section 6.3's closed twenty-seven-member `DegradationKind`
    literal. That check is what stops this module minting a twenty-eighth member by typo, which is
    exactly the failure the charter's "extended by literal, never re-invented per layer" forbids."""
    assert set(DISCOVERY_DEGRADATION_KINDS) == {"discovery_slow", "driver_unavailable"}
    with pytest.raises(ValueError, match="DegradationKind"):
        DiscoveryDegradation(kind="card_capability_unknown", message="x")
    with pytest.raises(ValueError, match="knob or the command"):
        DiscoveryDegradation(kind="discovery_slow", message="")


def test_the_elapsed_map_cannot_be_mutated_by_a_consumer(tmp_path: Path) -> None:
    """`Discovery` is frozen and its one mapping is a `MappingProxyType`, so a report that
    accumulates timings cannot rewrite the run's own record of them."""
    result = run(tmp_path / "site")
    with pytest.raises(TypeError):
        result.elapsed_ms["cards"] = 0.0  # type: ignore[index]


# --------------------------------------------------------------------------------------------
# 9. `catalog()` — the owner interface 02-architecture.md section 2 row 12 fixes.
# --------------------------------------------------------------------------------------------


def test_catalog_is_the_owner_interface_and_assembles_through_the_catalog_module(
    tmp_path: Path,
) -> None:
    """02-architecture.md section 2 row 12 fixes this module's owner interface as
    `catalog() -> Catalog`, and `Catalog.build()` calls it by exactly that name.

    The split is the point: discovery owns every byte of I/O in section 4.3's steps and
    `omniweave_core.drivers.catalog` owns the checking, the defaulting and the two digests. A
    `Catalog` that came back without a `catalog_digest`, or with a `validity_key` the catalog
    module would refuse, would mean the seam had been bypassed.
    """
    site = tmp_path / "site"
    package(site, "omniweave_driver_own", text=card("parse.notebook.own"))
    dist_info(
        site,
        dist="omniweave-driver-own",
        groups={DRIVER_GROUP: {"parse.notebook.own": "omniweave_driver_own"}},
    )
    built = catalog(
        search_path=[str(site)],
        distributions=dists(site),
        tombstone_dir=site / "none",
    )
    assert sorted(built.cards) == ["parse.notebook.own"]
    assert built.probe_status["parse.notebook.own"] == "unknown"
    assert built.trust["parse.notebook.own"] is TrustTier.UNPINNED
    assert len(built.validity_key) == 64
    assert len(built.catalog_digest) == 64
    assert built.tombstones == {}


def test_catalog_computes_local_trust_for_the_two_local_origins(tmp_path: Path) -> None:
    """Section 4.2 row 4: `origin in {driver_path, project}` is `local`, first-match-wins, and it
    needs neither the release manifest nor the lockfile — which is why it is the one tier
    discovery can compute at P1 without the `dist_sha256` map it deliberately does not build.

    Trust is never read off a card (E13): `DriverCard` has no `trust` attribute, because a card is
    a third party's assertion about itself and a self-reported trust tier is the one claim that
    must not be believed.
    """
    (tmp_path / "dp" / "local").mkdir(parents=True)
    (tmp_path / "dp" / "local" / CARD_FILENAME).write_text(card("parse.notebook.local"))
    built = catalog(
        search_path=[str(tmp_path / "site")],
        distributions=dists(tmp_path / "site"),
        tombstone_dir=tmp_path / "none",
        env={DRIVER_PATH_ENV: str(tmp_path / "dp")},
    )
    assert built.trust["parse.notebook.local"] is TrustTier.LOCAL


def test_catalog_accepts_probe_verdicts_as_an_input_and_never_probes(tmp_path: Path) -> None:
    """Section 4.7: "a probe verdict is an input to `resolve()`, not an action it takes."

    `probe()` may import the driver's heavy dependencies, so calling it inside discovery would
    import torch into a process INV-3 and G17 exist to keep at 80 ms. The verdict cache is the
    runtime's to read (step 8) and arrives here as a mapping; an id with no entry is `unknown`,
    which section 4.7 makes **passing** — an unprobed driver is a candidate, not a refusal.
    """
    site = tmp_path / "site"
    for name in ("seen", "unseen"):
        package(site, f"omniweave_driver_{name}", text=card(f"parse.notebook.{name}"))
        dist_info(
            site,
            dist=f"omniweave-driver-{name}",
            groups={DRIVER_GROUP: {f"parse.notebook.{name}": f"omniweave_driver_{name}"}},
        )
    built = catalog(
        search_path=[str(site)],
        distributions=dists(site),
        tombstone_dir=site / "none",
        probe_status={"parse.notebook.seen": "degraded", "parse.notebook.ghost": "unavailable"},
    )
    assert built.probe_status["parse.notebook.seen"] == "degraded"
    assert built.probe_status["parse.notebook.unseen"] == "unknown"
    assert "parse.notebook.ghost" not in built.probe_status


def test_catalog_narrows_a_duplicate_id_although_discover_carries_both(tmp_path: Path) -> None:
    """`Catalog.cards` is a `Mapping` and holds one card per id, so a narrowing happens somewhere.

    It happens in `catalog()` and NOT in `discover()`, which returns both halves of the collision
    — so the evidence DataFlow's receipt says must not vanish does not vanish. The narrowing is a
    placeholder for `Registry.register`'s `DuplicateDriver` (04-driver-system.md section 4.5),
    which is not on disk yet; when it lands, `catalog()` routes through it and this first-wins
    behaviour goes away.
    """
    site = tmp_path / "site"
    for name in ("one", "two"):
        package(site, f"omniweave_driver_{name}", text=card("parse.notebook.same"))
        dist_info(
            site,
            dist=f"omniweave-driver-{name}",
            groups={DRIVER_GROUP: {"parse.notebook.same": f"omniweave_driver_{name}"}},
        )
    kwargs = {
        "search_path": [str(site)],
        "distributions": dists(site),
        "tombstone_dir": site / "none",
    }
    assert len(discover(**kwargs).found) == 2
    assert len(catalog(**kwargs).cards) == 1


def test_the_shipped_tombstones_are_discovered_by_default_and_seed_the_licence_denylist() -> None:
    """The six tombstones shipped at release 1 (04-driver-system.md section 7.5, section 10.4).

    Two jobs, and this asserts both: DR22's quoted reason with a future `review_by`, and section
    7.5's known-bad-weights-licence seed set — `compute_tier` returns `forbidden` for any card
    whose `[licence.code]` or `[licence.weights]` `licence_sha256` matches a shipped tombstone's,
    which is **hash-keyed and therefore survives renaming**. Read through `discover()`'s default
    so the package-data path itself is under test, not a fixture standing in for it.
    """
    result = discover(search_path=[], distributions=())
    assert len(result.tombstones) == 6, [t.id for t in result.tombstones]
    assert result.faults == ()
    assert all(t.origin == "tombstone" for t in result.tombstones)
    assert all(t.reason for t in result.tombstones)
    assert all(t.review_by >= "2026" for t in result.tombstones)
    built = catalog(search_path=[], distributions=())
    assert built.cards == {}
    assert len(built.tombstone_licence_digests) >= 1
    assert all(built.tombstone_licence_digests), "an empty digest would match every card"
    # The shipped six carry `unresolved:<file>` placeholders where the licence text has not been
    # hashed yet, which is the tombstone author's fact and not discovery's. Asserted as
    # "non-empty" rather than as "sha256:" so this test does not pin a value it does not own.


def test_the_validity_key_is_the_catalog_modules_digest_and_not_a_second_recipe(
    tmp_path: Path,
) -> None:
    """INV-21: one key, one recipe. Discovery owns the I/O — which roots are scanned, which
    entries count, what a triple is — and `catalog.compute_validity_key` owns the digest, which is
    also what `Catalog.assemble()` validates its argument against. A hash re-implemented here
    would drift from that one on the first person who reformatted either."""
    site = tmp_path / "site"
    dist_info(site, dist="omniweave-driver-k", groups={DRIVER_GROUP: {"a.b.c": "pkg"}})
    triples = dist_info_triples([str(site)])
    assert [Path(p).name for p, _, _ in triples] == ["omniweave_driver_k-1.0.0.dist-info"]
    assert validity_key([str(site)]) == compute_validity_key(triples)
    assert validity_key([str(site)]) == compute_validity_key(reversed(triples)), (
        "the digest sorts, so scandir order cannot move the key between two machines"
    )


def test_a_corrupt_cache_row_is_overwritten_rather_than_re_read_every_run(
    tmp_path: Path,
) -> None:
    """The corrupt-row path is self-healing, and it does not recurse.

    Dropping a row whose payload disagrees with its own `card_sha256` is only half a fix: a
    re-read that left the bad row in place would pay the read on every run for the life of the
    file, and a *recursive* re-read would find the same matching key and loop forever. So the
    corrupt row falls through to the disk read and the write-back overwrites it — the second call
    is an ordinary hit.
    """
    source = one_source(tmp_path)
    cache = MemoryCardCache()
    load_one(source, cache=cache)
    key = (source.origin, "", "", source.card_path)
    good = cache.get(key)
    assert good is not None
    cache.put(
        CardCacheRow(
            prefix=good.prefix,
            dist_name=good.dist_name,
            dist_version=good.dist_version,
            card_path=good.card_path,
            mtime_ns=good.mtime_ns,
            size=good.size,
            card_json=json.dumps("card_schema = 1\n[nonsense]\nx = 1\n"),
            card_sha256=good.card_sha256,
        )
    )
    healed = load_one(source, cache=cache)
    assert healed.found is not None and healed.found.cached is False
    assert cache.get(key) == good, "the corrupt row was overwritten with the file's own"
    again = load_one(source, cache=cache)
    assert again.found is not None and again.found.cached is True


def test_the_cacheless_path_still_reports_a_missing_card(tmp_path: Path) -> None:
    """`cache=None` skips the write-back's `stat`, so `read_card_bytes()` is the only syscall that
    can fail — and it raises the same `OSError`, so `card_missing` still comes back. A cheaper
    path that lost a failure mode would be the wrong trade."""
    source = CardSource(
        origin="entry_point",
        path=tmp_path / "gone" / CARD_FILENAME,
        card_path="gone/driver.toml",
        dist_name="omniweave-driver-gone",
    )
    outcome = load_one(source, cache=None)
    assert outcome.found is None
    assert outcome.fault is not None and outcome.fault.detail == "card_missing"
    assert outcome.degradation is not None and outcome.degradation.kind == "driver_unavailable"
