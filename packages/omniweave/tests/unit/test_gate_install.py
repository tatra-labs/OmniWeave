"""G-install (10:1775-1780), over every built target: the claim "a new host is one file plus one
registry row" (10:1628) as a gate, not a sentence.

Every test here is parametrised by `registry.BUILT`, so a fourth row is gated the moment it is
added, and nothing in this file names a host. 10:1775's procedure is followed as written -- a
fixture home, the byte state of every path, install, uninstall, byte identity -- and each of
10:1778-1780's four cases is a test of its own, written generically by file type:

1. files that already hold unrelated servers, permissions and hooks;
2. the user's text on both sides of the block, written after install;
3. a second tool writing into the same files after ours; what remains is that tool's install
   alone, compared against a twin home that never had omniweave;
4. two local installs in two project roots, uninstalling one.

Beyond the four: every target installed together and uninstalled in every order (D481), `--check`
9 -> 0 -> 9 (10:1780), a re-install that changes nothing, `print_config` touching nothing
(10:1641), and install writing nothing that `describe_paths` does not name -- the list 10:1775
records, which is only a gate if nothing escapes it.

G-install has no row in `tools/gates.toml` and no rendering in 11 section 6.4 (D484), so this
module is the gate until one is registered.
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.install import verbs
from omniweave.install.engine import HostEnv
from omniweave.install.primitives import render_json
from omniweave.install.receipt import expand, load
from omniweave.install.registry import BUILT, TARGETS, build
from omniweave.install.types import LOCATIONS, TARGET_IDS, InstallOptions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from omniweave.install.types import HostTarget, Location, WriteResult

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
LAUNCH = (sys.executable, "-m", "omniweave")
ROUTER = "---\nname: omniweave\n---\nthe router\n"

#  Three option sets, from writing the least to the most: every kind each host has is written by
#  one of them, and `none`/`none` is the install that must still reverse to nothing.
OPTIONS = {
    "bare": InstallOptions(hooks="none", skills="none"),
    "context": InstallOptions(hooks="context", skills="core"),
    "steer": InstallOptions(hooks="steer", skills="all", allow_cli=True),
}

#  Case 1's unrelated content, one shape per file type.
SEED_JSON = {
    "mcpServers": {"other": {"command": "x"}},
    "permissions": {"allow": ["Bash(git:*)"]},
    "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "their.sh"}]}]},
}
SEED_TOML = 'model = "gpt-5"\n\n[profiles.fast]\nmodel = "mini"\n'
SEED_TEXT = "# Mine\n\nKeep this.\n"


class _Clock:
    def wall_ns(self) -> int:
        return T0

    def monotonic_ns(self) -> int:
        return 0


def _env(tmp: Path, *, root: Path | None = None, found: bool = False) -> HostEnv:
    (tmp / "home").mkdir(exist_ok=True)
    for name in ("omniweave", "extra"):
        bundle = tmp / "skills" / name
        bundle.mkdir(parents=True, exist_ok=True)
        (bundle / "SKILL.md").write_bytes(ROUTER.replace("omniweave", name).encode())
    return HostEnv(
        omniweave_home=tmp / "owhome",
        user_home=tmp / "home",
        clock=_Clock(),
        pid=PID,
        launch=LAUNCH,
        project_root=root,
        windows=sys.platform == "win32",
        which=(lambda name: f"/bin/{name}") if found else (lambda _name: None),
        lock_wait_ms=0,
        skills_root=tmp / "skills",
    )


def _host(target: str, tmp: Path, loc: Location, **kwargs: Any) -> HostTarget:
    root = tmp / "proj" if loc == "local" else None
    if root is not None:
        root.mkdir(exist_ok=True)
    return build(target, _env(tmp, root=root, **kwargs))


def _state(tmp: Path) -> dict[str, bytes | None]:
    """The byte state of the home and the project: every path, a file's bytes or `None`."""
    found: dict[str, bytes | None] = {}
    for top in ("home", "proj"):
        root = tmp / top
        if root.exists():
            for one in sorted(root.rglob("*")):
                found[one.relative_to(tmp).as_posix()] = one.read_bytes() if one.is_file() else None
    return found


def _ok(result: WriteResult) -> WriteResult:
    assert not result.refused, result.refused
    kept = [one for one in result.actions if one.action == "kept"]
    assert not kept, kept
    return result


def _described(host: HostTarget, loc: Location) -> list[Path]:
    return [expand(one, host.env.user_home) for one in host.describe_paths(loc)]  # type: ignore[attr-defined]


def _files(host: HostTarget, loc: Location) -> Iterator[Path]:
    """The described paths that are files, not skill directories."""
    return (one for one in _described(host, loc) if one.suffix)


def _seed(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_bytes((json.dumps(SEED_JSON, indent=4) + "\n").encode())
    elif path.suffix == ".toml":
        path.write_bytes(SEED_TOML.encode())
    else:
        path.write_bytes(SEED_TEXT.encode())


def _second_tool(path: Path) -> None:
    """Another installer writing into the same file after ours, each in its own file type's way."""
    if not path.exists():
        return
    if path.suffix == ".json":
        document = json.loads(path.read_bytes())
        document.setdefault("mcpServers", {})["later"] = {"command": "y"}
        path.write_bytes(render_json(document))
    elif path.suffix == ".toml":
        path.write_bytes(path.read_bytes() + b"\n[later_tool]\non = true\n")
    else:
        path.write_bytes(path.read_bytes() + b"\nThe other tool's line.\n")


GRID = [
    pytest.param(target, loc, name, id=f"{target}-{loc}-{name}")
    for target in BUILT
    for loc in LOCATIONS
    for name in OPTIONS
]
PLACES = [pytest.param(target, loc, id=f"{target}-{loc}") for target in BUILT for loc in LOCATIONS]


# ---------------------------------------------------------------------------------------------
# The gate covers the registry.
# ---------------------------------------------------------------------------------------------


def test_every_registered_target_is_built_and_gated() -> None:
    assert set(TARGETS) == set(BUILT)
    assert set(BUILT) <= set(TARGET_IDS)
    assert {param.values[0] for param in PLACES} == set(BUILT)


# ---------------------------------------------------------------------------------------------
# 10:1775: install, uninstall, byte identity -- from nothing, and over case 1's content.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("target", "loc", "name"), GRID)
def test_an_empty_home_comes_back_empty(
    tmp_path: Path, target: str, loc: Location, name: str
) -> None:
    host = _host(target, tmp_path, loc)
    before = _state(tmp_path)
    _ok(host.install(loc, OPTIONS[name]))
    assert {one.action for one in _ok(host.install(loc, OPTIONS[name])).actions} <= {"unchanged"}
    _ok(host.uninstall(loc))
    assert _state(tmp_path) == before
    assert list(load(tmp_path / "owhome", pid=PID).receipt.entries) == []


@pytest.mark.parametrize(("target", "loc", "name"), GRID)
def test_case_1_unrelated_content_survives_byte_for_byte(
    tmp_path: Path, target: str, loc: Location, name: str
) -> None:
    """10:1778: files that already had unrelated MCP servers, permissions and hooks."""
    host = _host(target, tmp_path, loc)
    for path in _files(host, loc):
        _seed(path)
    before = _state(tmp_path)
    _ok(host.install(loc, OPTIONS[name]))
    assert _state(tmp_path) != before
    _ok(host.uninstall(loc))
    assert _state(tmp_path) == before


@pytest.mark.parametrize(("target", "loc"), PLACES)
def test_install_writes_nothing_describe_paths_does_not_name(
    tmp_path: Path, target: str, loc: Location
) -> None:
    host = _host(target, tmp_path, loc)
    before = _state(tmp_path)
    _ok(host.install(loc, OPTIONS["steer"]))
    after = _state(tmp_path)
    described = _described(host, loc)
    changed = [key for key in after if after[key] != before.get(key, b"\0absent")]
    for key in changed:
        path = tmp_path / key
        covered = any(
            path == one or one in path.parents or path in one.parents for one in described
        )
        assert covered, f"{key} was written and describe_paths does not name it"


# ---------------------------------------------------------------------------------------------
# 10:1778-1780's other three cases.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("target", "loc"), PLACES)
def test_case_2_the_users_text_around_the_block_is_kept(
    tmp_path: Path, target: str, loc: Location
) -> None:
    host = _host(target, tmp_path, loc)
    texts = [one for one in _files(host, loc) if one.suffix in {".md", ".mdc"}]
    if not texts:
        pytest.skip(f"{target} writes no instruction file at {loc}")
    for path in texts:
        _seed(path)
    _ok(host.install(loc, OPTIONS["context"]))
    for path in texts:
        path.write_bytes(b"Above.\n\n" + path.read_bytes() + b"\nBelow.\n")
    _ok(host.uninstall(loc))
    for path in texts:
        assert path.read_bytes() == b"Above.\n\n" + SEED_TEXT.encode() + b"\nBelow.\n", path


@pytest.mark.parametrize(("target", "loc"), PLACES)
def test_case_3_a_second_tool_in_the_same_files_is_left_as_it_wrote_them(
    tmp_path: Path, target: str, loc: Location
) -> None:
    """10:1779: what remains is the other tool's install alone, against a twin that never had us."""
    ours, alone = tmp_path / "ours", tmp_path / "alone"
    for tmp in (ours, alone):
        tmp.mkdir()
    host = _host(target, ours, loc)
    twin = _host(target, alone, loc)
    for one in (host, twin):
        for path in _files(one, loc):
            _seed(path)
    _ok(host.install(loc, OPTIONS["context"]))
    for one in (host, twin):
        for path in _files(one, loc):
            _second_tool(path)
    _ok(host.uninstall(loc))
    assert _state(ours) == _state(alone)


@pytest.mark.parametrize("target", BUILT)
def test_case_4_two_project_roots_uninstalling_one_leaves_the_other(
    tmp_path: Path, target: str
) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    for root in (one, two):
        root.mkdir()
    first = build(target, _env(tmp_path, root=one))
    second = build(target, _env(tmp_path, root=two))
    empty = sorted(one.rglob("*"))
    _ok(first.install("local", OPTIONS["context"]))
    _ok(second.install("local", OPTIONS["context"]))
    installed = {p: p.read_bytes() for p in two.rglob("*") if p.is_file()}
    _ok(first.uninstall("local"))
    assert sorted(one.rglob("*")) == empty
    assert {p: p.read_bytes() for p in two.rglob("*") if p.is_file()} == installed
    _ok(second.uninstall("local"))
    assert sorted(two.rglob("*")) == []


# ---------------------------------------------------------------------------------------------
# Every target at once, and the verbs' view of it.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("loc", LOCATIONS)
@pytest.mark.parametrize("order", list(itertools.permutations(BUILT)), ids=">".join)
def test_every_target_together_reverses_in_every_order(
    tmp_path: Path, loc: Location, order: tuple[str, ...]
) -> None:
    """Hosts that share a path -- Codex reads Claude Code's skill directory -- included. D481.

    Every host is `found`: a host not detected is `not installed` to `--check`, which then reads
    none of its rows, and a local install creates no host home -- so without it the check below
    passed vacuously at `local`, and a skill taken from a host still wired went unseen.
    """
    hosts = {target: _host(target, tmp_path, loc, found=True) for target in BUILT}
    before = _state(tmp_path)
    for target in BUILT:
        _ok(hosts[target].install(loc, OPTIONS["context"]))
    for target in order:
        undone = hosts[target].uninstall(loc)
        assert not undone.refused
        for other in order[order.index(target) + 1 :]:
            status = verbs.check(other, loc, hosts[other].env)  # type: ignore[attr-defined]
            assert status.exit_code == verbs.OK, status.lines
    assert _state(tmp_path) == before


@pytest.mark.parametrize(("target", "loc"), PLACES)
def test_check_is_9_then_0_then_9(tmp_path: Path, target: str, loc: Location) -> None:
    """10:1780: *"exits 9 when not configured and 0 when configured"*, both directions."""
    host = _host(target, tmp_path, loc, found=True)
    assert verbs.check(target, loc, host.env).exit_code == verbs.NOT_CONFIGURED  # type: ignore[attr-defined]
    _ok(host.install(loc, OPTIONS["context"]))
    configured = verbs.check(target, loc, host.env)  # type: ignore[attr-defined]
    assert configured.exit_code == verbs.OK, configured.lines
    assert "MODIFIED" not in configured.text() and "MISSING" not in configured.text()
    _ok(host.uninstall(loc))
    assert verbs.check(target, loc, host.env).exit_code == verbs.NOT_CONFIGURED  # type: ignore[attr-defined]


@pytest.mark.parametrize(("target", "loc"), PLACES)
def test_print_config_touches_nothing(tmp_path: Path, target: str, loc: Location) -> None:
    """10:1641: *"MUST NOT touch the filesystem"*."""
    host = _host(target, tmp_path, loc)
    before = _state(tmp_path)
    assert host.print_config(loc).strip()
    assert _state(tmp_path) == before
    assert not (tmp_path / "owhome").exists()
