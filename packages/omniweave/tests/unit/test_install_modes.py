"""The three file modes, install and uninstall, against G-install's cases file by file.

**The sharpest test is `test_this_machines_host_configs_come_back_byte_for_byte`.** It copies the
host configs this machine actually has into a scratch home -- the real files are only read -- and
installs, re-installs and uninstalls the MCP entry and the permission wildcard in each, asserting
byte identity. The second is `test_a_reinstall_without_the_previous_row_leaves_an_empty_container`:
the re-install D449 made replace its row would lose what the first install created, unless the new
row inherits it (D454).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.install.modes import (
    Applied,
    Site,
    add_values,
    remove_section,
    remove_values,
    set_key,
    unbuilt,
    unset_key,
    upsert_section,
)
from omniweave.install.primitives import BEGIN, BOM, END, render_json
from omniweave.install.receipt import Entry

if TYPE_CHECKING:
    from omniweave.install.types import Location

PID = 4242
T0 = 1_788_257_523 * 1_000_000_000
KEY = "mcpServers.omniweave"
ALLOW = "permissions.allow"
WILDCARD = "mcp__omniweave__*"
SERVER: dict[str, Any] = {
    "type": "stdio",
    "command": "C:/tools/ow.exe",
    "args": ["serve", "--mcp"],
    "env": {},
}
BODY = "## omniweave\n\nAsk `ow_query` before reading whole files."
WINDOWS = sys.platform == "win32"


class _Clock:
    def wall_ns(self) -> int:
        return T0

    def monotonic_ns(self) -> int:
        return 0


CLOCK = _Clock()


def _site(home: Path, relative: str, location: Location = "global") -> Site:
    root = str(home.resolve()) if location == "local" else None
    return Site("claude-code", location, home / relative, home, scope_root=root)


def _install(site: Site, previous: dict[str, Entry] | None = None) -> dict[str, Entry]:
    """The MCP entry and the wildcard into one file, returning the rows by kind."""
    previous = previous or {}
    rows: dict[str, Entry] = {}
    mcp = set_key(site, "mcp", KEY, SERVER, previous=previous.get("mcp"), clock=CLOCK, pid=PID)
    perms = add_values(
        site, "permissions", ALLOW, [WILDCARD], previous=previous.get("permissions"),
        clock=CLOCK, pid=PID,
    )  # fmt: skip
    for applied in (mcp, perms):
        assert applied.action.action in {"created", "updated", "unchanged"}, applied.action
        if applied.record is not None:
            rows[applied.record.kind] = applied.record
    return {**previous, **rows}


def _uninstall(site: Site, rows: dict[str, Entry]) -> list[Applied]:
    """Newest first, as the receipt's order has it."""
    return [
        remove_values(
            site, "permissions", ALLOW, [WILDCARD], entry=rows.get("permissions"), pid=PID
        ),
        unset_key(site, "mcp", KEY, entry=rows.get("mcp"), pid=PID),
    ]


# G-install's first case (10:1778), one file per style this machine's hosts write (D441).
STYLES: dict[str, str] = {
    "claude.json: 2, LF, no newline, non-ASCII": (
        '{\n  "numStartups": 12,\n  "userName": "Zoë",\n  "mcpServers": {\n    "other": {\n'
        '      "command": "x"\n    }\n  },\n  "permissions": {\n    "allow": [\n'
        '      "Bash(git:*)"\n    ]\n  }\n}'
    ),
    "settings.json: 2, LF, newline": (
        '{\n  "permissions": {\n    "allow": [\n      "Bash(git:*)"\n    ]\n  },\n'
        '  "mcpServers": {\n    "other": {\n      "command": "x"\n    }\n  }\n}\n'
    ),
    "vscode: 4, CRLF": (
        '{\r\n    "mcpServers": {\r\n        "other": {\r\n            "command": "x"\r\n'
        '        }\r\n    },\r\n    "permissions": {\r\n        "allow": [\r\n'
        '            "Bash(git:*)"\r\n        ]\r\n    }\r\n}'
    ),
    "no mcpServers and no permissions": '{\n  "model": "opus"\n}\n',
    "empty object": "{}\n",
}


@pytest.mark.parametrize("name", list(STYLES))
def test_install_then_uninstall_is_byte_identical(tmp_path: Path, name: str) -> None:
    site = _site(tmp_path, "settings.json")
    raw = STYLES[name].encode()
    site.path.write_bytes(raw)
    rows = _install(site)
    assert json.loads(site.path.read_bytes())["mcpServers"]["omniweave"] == SERVER
    results = _uninstall(site, rows)
    assert [r.action.action for r in results] == ["removed", "removed"]
    assert all(r.forget is not None for r in results)
    assert site.path.read_bytes() == raw


@pytest.mark.parametrize("name", list(STYLES))
def test_a_reinstall_then_uninstall_is_byte_identical(tmp_path: Path, name: str) -> None:
    site = _site(tmp_path, "settings.json")
    raw = STYLES[name].encode()
    site.path.write_bytes(raw)
    rows = _install(site, _install(site))
    _uninstall(site, rows)
    assert site.path.read_bytes() == raw


def test_a_reinstall_without_the_previous_row_leaves_an_empty_container(tmp_path: Path) -> None:
    """D454's failure, reproduced: the second row alone says nothing was created."""
    site = _site(tmp_path, "settings.json")
    raw = b'{\n  "model": "opus"\n}\n'
    site.path.write_bytes(raw)
    first = set_key(site, "mcp", KEY, SERVER, previous=None, clock=CLOCK, pid=PID).record
    assert first is not None
    assert first.created_parents == ("mcpServers",)
    changed = SERVER | {"args": ["serve"]}  # a second install that does write something
    alone = set_key(site, "mcp", KEY, changed, previous=None, clock=CLOCK, pid=PID).record
    assert alone is not None
    assert alone.created_parents == ()
    unset_key(site, "mcp", KEY, entry=alone, pid=PID)
    assert json.loads(site.path.read_bytes()) == {"model": "opus", "mcpServers": {}}
    # And with the previous row carried forward:
    site.path.write_bytes(raw)
    first = set_key(site, "mcp", KEY, SERVER, previous=None, clock=CLOCK, pid=PID).record
    carried = set_key(site, "mcp", KEY, changed, previous=first, clock=CLOCK, pid=PID).record
    assert carried is not None
    assert carried.created_parents == ("mcpServers",)
    unset_key(site, "mcp", KEY, entry=carried, pid=PID)
    assert site.path.read_bytes() == raw


def test_a_grant_the_user_already_had_survives_the_uninstall(tmp_path: Path) -> None:
    """10:1712's row records the mode's input; recording it would revoke the user's grant. D454."""
    site = _site(tmp_path, "settings.json")
    raw = b'{\n  "permissions": {\n    "allow": [\n      "mcp__omniweave__*"\n    ]\n  }\n}\n'
    site.path.write_bytes(raw)
    applied = add_values(
        site, "permissions", ALLOW, [WILDCARD], previous=None, clock=CLOCK, pid=PID
    )
    assert applied.action.action == "unchanged"
    assert applied.record is not None
    assert applied.record.values == ()
    back = remove_values(site, "permissions", ALLOW, [WILDCARD], entry=applied.record, pid=PID)
    assert back.action.action == "not-found"
    assert back.forget is applied.record
    assert site.path.read_bytes() == raw
    # Without the row, the fallback re-derives and takes the grant away:
    rederived = remove_values(site, "permissions", ALLOW, [WILDCARD], entry=None, pid=PID)
    assert rederived.action.action == "removed"
    assert json.loads(site.path.read_bytes())["permissions"]["allow"] == []


def test_a_created_file_and_its_directories_are_removed(tmp_path: Path) -> None:
    """A local `./.claude/settings.json` in a project that had no `.claude/`. D452."""
    project = tmp_path / "proj"
    project.mkdir()
    site = _site(project, ".claude/settings.json", location="local")
    rows = _install(site)
    assert rows["mcp"].created_file is True
    assert rows["mcp"].created_dirs == ((project / ".claude").as_posix(),)
    _uninstall(site, rows)
    assert list(project.iterdir()) == []


def test_a_created_directory_the_user_filled_is_named_not_removed(tmp_path: Path) -> None:
    site = _site(tmp_path, ".claude/settings.json")
    rows = _install(site)
    (tmp_path / ".claude" / "mine.md").write_text("mine", encoding="utf-8")
    removed = _uninstall(site, rows)[-1]
    assert removed.action.action == "removed"
    assert "Could not remove ~/.claude -- it is not empty" in removed.action.note
    assert (tmp_path / ".claude" / "mine.md").exists()


def test_a_second_tool_writing_after_install_keeps_its_entry(tmp_path: Path) -> None:
    """G-install's third case (10:1779): another tool's server lands in the same object."""
    site = _site(tmp_path, "settings.json")
    raw = STYLES["settings.json: 2, LF, newline"].encode()
    site.path.write_bytes(raw)
    rows = _install(site)
    document = json.loads(site.path.read_bytes())
    document["mcpServers"]["another-tool"] = {"command": "y"}
    site.path.write_bytes(render_json(document))
    removed = unset_key(site, "mcp", KEY, entry=rows["mcp"], pid=PID)
    assert removed.action.action == "removed"
    assert "only omniweave's part was removed" in removed.action.note
    after = json.loads(site.path.read_bytes())
    assert after["mcpServers"] == {"other": {"command": "x"}, "another-tool": {"command": "y"}}


def test_a_value_the_user_edited_is_kept_and_its_row_survives(tmp_path: Path) -> None:
    site = _site(tmp_path, "settings.json")
    rows = _install(site)
    document = json.loads(site.path.read_bytes())
    document["mcpServers"]["omniweave"]["args"] = ["serve", "--mcp", "--profile", "full"]
    site.path.write_bytes(render_json(document))
    kept = unset_key(site, "mcp", KEY, entry=rows["mcp"], pid=PID)
    assert kept.action.action == "kept"
    assert kept.action.note == "kept -- modified since install"
    assert kept.forget is None
    assert json.loads(site.path.read_bytes()) == document


def test_a_lost_row_is_re_derived_and_the_created_container_left(tmp_path: Path) -> None:
    """10:1758: a lost receipt never strands a user; it costs the byte-identity. D455."""
    site = _site(tmp_path, "settings.json")
    site.path.write_bytes(b'{\n  "model": "opus"\n}\n')
    _install(site)
    removed = unset_key(site, "mcp", KEY, entry=None, pid=PID)
    assert removed.action.action == "removed"
    assert "re-derivation" in removed.action.note
    assert json.loads(site.path.read_bytes())["mcpServers"] == {}


def test_uninstall_of_what_is_not_there_is_not_found(tmp_path: Path) -> None:
    site = _site(tmp_path, "settings.json")
    assert unset_key(site, "mcp", KEY, entry=None, pid=PID).action.action == "not-found"
    site.path.write_bytes(b"{}\n")
    assert unset_key(site, "mcp", KEY, entry=None, pid=PID).action.action == "not-found"
    assert remove_values(
        site, "permissions", ALLOW, [WILDCARD], entry=None, pid=PID
    ).action.action == ("not-found")


def test_a_container_of_the_wrong_type_is_refused(tmp_path: Path) -> None:
    site = _site(tmp_path, "settings.json")
    raw = b'{"mcpServers": [], "permissions": {"allow": "all"}}'
    site.path.write_bytes(raw)
    mcp = set_key(site, "mcp", KEY, SERVER, previous=None, clock=CLOCK, pid=PID)
    perms = add_values(site, "permissions", ALLOW, [WILDCARD], previous=None, clock=CLOCK, pid=PID)
    assert mcp.action.action == "kept"
    assert "mcpServers is list, not an object" in mcp.action.note
    assert perms.action.action == "kept"
    assert "not an array" in perms.action.note
    assert site.path.read_bytes() == raw


# ---------------------------------------------------------------------------------------------
# D453: nothing reads by writing.
# ---------------------------------------------------------------------------------------------


def test_a_dry_run_writes_nothing_not_even_a_backup(tmp_path: Path) -> None:
    site = _site(tmp_path, ".claude/settings.json")
    planned = set_key(site, "mcp", KEY, SERVER, previous=None, clock=CLOCK, pid=PID, dry_run=True)
    assert (planned.action.action, planned.record) == ("created", None)
    assert list(tmp_path.iterdir()) == []
    broken = _site(tmp_path, "settings.json")
    broken.path.write_bytes(b'{"a": 1,}')
    dry = add_values(
        broken, "permissions", ALLOW, [WILDCARD], previous=None, clock=CLOCK, pid=PID, dry_run=True
    )
    assert dry.action.action == "updated"
    assert "not backed up" in dry.action.note
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_an_uninstall_leaves_an_unparseable_file_alone(tmp_path: Path) -> None:
    site = _site(tmp_path, "settings.json")
    site.path.write_bytes(b'{"mcpServers": {"omniweave": {}},}')
    left = unset_key(site, "mcp", KEY, entry=None, pid=PID)
    assert left.action.action == "kept"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json"]


def test_an_install_over_an_unparseable_file_backs_it_up_first(tmp_path: Path) -> None:
    site = _site(tmp_path, "settings.json")
    site.path.write_bytes(b'{"a": 1,}')
    applied = set_key(site, "mcp", KEY, SERVER, previous=None, clock=CLOCK, pid=PID)
    assert (applied.action.action, applied.action.code) == ("updated", "OW-A-032")
    assert (tmp_path / "settings.json.backup").read_bytes() == b'{"a": 1,}'


def test_a_file_that_will_not_round_trip_says_so(tmp_path: Path) -> None:
    site = _site(tmp_path, "settings.json")
    site.path.write_bytes(b'{\n  "a": 1e5\n}\n')
    applied = set_key(site, "mcp", KEY, SERVER, previous=None, clock=CLOCK, pid=PID)
    assert "cannot restore it byte for byte (D441)" in applied.action.note


# ---------------------------------------------------------------------------------------------
# marker-section. G-install's second case (10:1778-1779).
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"# Mine\n\nMy rules.\n",
        b"# Mine\n\nNo final newline.",
        b"# Mine\r\n\r\nCRLF.\r\n",
        BOM + b"# Mine\n",
    ],
)
def test_a_section_goes_in_and_comes_out_byte_for_byte(tmp_path: Path, raw: bytes) -> None:
    site = _site(tmp_path, "CLAUDE.md")
    site.path.write_bytes(raw)
    applied = upsert_section(site, "instructions", BODY, previous=None, clock=CLOCK, pid=PID)
    assert applied.record is not None
    assert BEGIN.encode() in site.path.read_bytes()
    assert site.path.read_bytes().startswith(raw[:3] if raw.startswith(BOM) else b"")
    removed = remove_section(site, "instructions", entry=applied.record, pid=PID)
    assert removed.action.action == "removed"
    assert site.path.read_bytes() == raw


def test_the_users_text_around_the_block_survives(tmp_path: Path) -> None:
    site = _site(tmp_path, "CLAUDE.md")
    site.path.write_bytes(b"# Mine\n")
    row = upsert_section(site, "instructions", BODY, previous=None, clock=CLOCK, pid=PID).record
    site.path.write_bytes(site.path.read_bytes() + b"\n## Added later\n")
    removed = remove_section(site, "instructions", entry=row, pid=PID)
    assert removed.action.action == "removed"
    assert "only omniweave's part was removed" in removed.action.note
    assert site.path.read_bytes() == b"# Mine\n\n## Added later\n"


def test_an_edited_section_is_kept(tmp_path: Path) -> None:
    site = _site(tmp_path, "CLAUDE.md")
    row = upsert_section(site, "instructions", BODY, previous=None, clock=CLOCK, pid=PID).record
    edited = site.path.read_text("utf-8").replace("whole files", "anything")
    site.path.write_text(edited, encoding="utf-8")
    kept = remove_section(site, "instructions", entry=row, pid=PID)
    assert (kept.action.action, kept.forget) == ("kept", None)


def test_a_created_claude_md_and_its_directory_are_removed(tmp_path: Path) -> None:
    site = _site(tmp_path, ".claude/CLAUDE.md")
    applied = upsert_section(site, "instructions", BODY, previous=None, clock=CLOCK, pid=PID)
    assert applied.action.action == "created"
    assert applied.record is not None
    assert applied.record.created_file
    assert site.path.read_text("utf-8").endswith(END + "\n")
    again = upsert_section(
        site, "instructions", BODY, previous=applied.record, clock=CLOCK, pid=PID
    )
    assert again.action.action == "unchanged"
    remove_section(site, "instructions", entry=applied.record, pid=PID)
    assert list(tmp_path.iterdir()) == []


# ---------------------------------------------------------------------------------------------
# This machine's own host configs, copied. Read-only against the originals.
# ---------------------------------------------------------------------------------------------

REAL = (".claude.json", ".claude/settings.json", ".cursor/mcp.json")


def test_this_machines_host_configs_come_back_byte_for_byte(tmp_path: Path) -> None:
    home = Path.home()
    tried = 0
    for name in REAL:
        original = home / name
        if not original.is_file():
            continue
        copy = tmp_path / name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, copy)
        raw = copy.read_bytes()
        site = Site("claude-code", "global", copy, tmp_path)
        rows = _install(site, _install(site))
        assert json.loads(copy.read_bytes())["mcpServers"]["omniweave"] == SERVER, name
        _uninstall(site, rows)
        assert copy.read_bytes() == raw, name
        tried += 1
    if not tried:
        pytest.skip("no host config on this machine")


def test_unbuilt_names_the_two_modes_left_and_the_decision_owed() -> None:
    listed = unbuilt()
    assert len(listed) == 3
    assert any(line.startswith("json-hook-rules") for line in listed)
    assert any(line.startswith("dir") for line in listed)
