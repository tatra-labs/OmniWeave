"""The install receipt: rows, scope, the lock, and what each of a row's two digests can still say.

**The sharpest test is `test_the_plans_two_settings_rows_cannot_both_match_the_file`.** It replays
10:1709-1722 -- a `permissions` row and then a `hooks` row, each with the file's post-write sha256,
into one `settings.json` -- and shows the first row's `sha256_after` is stale the moment the second
write lands, while its owned digest still says the permissions are exactly as written. D448.

The second is `test_a_live_holder_older_than_120_s_is_refused_not_broken`: the plan's age rule
would break the lock of an `ow install` waiting at its own prompt. D450.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.install.primitives import (
    UNPARSEABLE,
    read_json,
    render_json,
    upsert_marked_section,
    write_json,
)
from omniweave.install.receipt import (
    LOCK_NAME,
    LOCK_REPORT_AGE_S,
    RECEIPT_LOCKED,
    RECEIPT_NAME,
    SCHEMA,
    Entry,
    Receipt,
    dotted,
    expand,
    file_sha256,
    forget,
    load,
    lock_path,
    owned_array,
    owned_key,
    owned_section,
    receipt_path,
    record,
    same_scope,
    take_lock,
    tildify,
    unbuilt,
    verdict,
    written_at,
)
from omniweave_core.canonical import sha256_canonical
from omniweave_core.locks import LockHolder, inspect

if TYPE_CHECKING:
    from collections.abc import Iterator

    from conftest import PlanDocs
    from omniweave.install.receipt import InstallLock

INTERFACES = "10-interfaces.md"
PID = 4242
RELEASE = "0.1.0"
HEX = "a" * 64
WINDOWS = sys.platform == "win32"
T0 = 1_788_257_523 * 1_000_000_000  # 2026-09-01T10:12:03Z, 10:1706's stamp


class _Clock:
    def __init__(self, wall_ns: int = T0) -> None:
        self.wall = wall_ns

    def wall_ns(self) -> int:
        return self.wall

    def monotonic_ns(self) -> int:
        return 0


def _line(plan: PlanDocs, number: int) -> str:
    return plan.lines(INTERFACES)[number - 1]


def _entry(**changes: Any) -> Entry:
    base = Entry(
        target="claude-code",
        location="global",
        scope_root=None,
        written_at="2026-09-01T10:12:03Z",
        kind="mcp",
        path="~/.claude.json",
        mode="json-key",
        key="mcpServers.omniweave",
        sha256_after=HEX,
        owned_sha256=HEX,
    )
    return replace(base, **changes)


@pytest.fixture
def held(tmp_path: Path) -> Iterator[InstallLock]:
    taken = take_lock(tmp_path / "home", clock=_Clock(), wait_ms=0)
    assert taken.lock is not None
    with taken.lock as lock:
        yield lock


# ---------------------------------------------------------------------------------------------
# Names and spellings.
# ---------------------------------------------------------------------------------------------


def test_the_receipt_and_lock_are_where_10_1703_and_1744_put_them(plan: PlanDocs) -> None:
    plan.require()
    assert "$OMNIWEAVE_HOME/install-receipt.json" in _line(plan, 1703)
    assert "$OMNIWEAVE_HOME/.install.lock" in _line(plan, 1744)
    assert '"schema":1' in _line(plan, 1704)
    assert (RECEIPT_NAME, LOCK_NAME, SCHEMA) == ("install-receipt.json", ".install.lock", 1)
    assert receipt_path(Path("/h")) == Path("/h/install-receipt.json")
    assert lock_path(Path("/h")) == Path("/h/.install.lock")


def test_ow_a_033_is_the_codes_registry_row(repo_root: Path) -> None:
    text = (repo_root / "codes.toml").read_text("utf-8")
    assert re.search(r'numeric = "OW-A-033"\nsymbol  = "OW_INSTALL_RECEIPT_LOCKED"', text)
    assert RECEIPT_LOCKED == "OW-A-033"
    assert LOCK_REPORT_AGE_S == 120


def test_written_at_is_10_1706s_stamp(plan: PlanDocs) -> None:
    plan.require()
    assert '"written_at":"2026-09-01T10:12:03Z"' in _line(plan, 1706)
    assert written_at(T0) == "2026-09-01T10:12:03Z"
    assert written_at(T0 + 999_999_999) == "2026-09-01T10:12:03Z"


def test_a_path_under_home_is_tildified_with_forward_slashes(tmp_path: Path) -> None:
    home = tmp_path / "u"
    assert tildify(home / ".claude.json", home) == "~/.claude.json"
    assert tildify(home / ".claude" / "settings.json", home) == "~/.claude/settings.json"
    assert tildify(home, home) == "~"
    elsewhere = tmp_path / "work" / "proj" / ".mcp.json"
    assert tildify(elsewhere, home) == elsewhere.as_posix()
    assert "\\" not in tildify(elsewhere, home)
    for path in (home / ".claude.json", home, elsewhere):
        assert expand(tildify(path, home), home) == path


def test_a_dotted_key_refuses_a_segment_with_a_dot() -> None:
    assert dotted("mcpServers", "omniweave") == "mcpServers.omniweave"
    for bad in (("editor.fontSize",), ("a", ""), ()):
        with pytest.raises(ValueError, match="dotted"):
            dotted(*bad)


def test_scope_roots_compare_as_one_project(tmp_path: Path) -> None:
    root = str(tmp_path.resolve())
    assert same_scope(root, root + "/.")
    assert same_scope(None, None)
    assert not same_scope(None, root)
    assert not same_scope(root, str(tmp_path.parent.resolve()))
    if WINDOWS:
        assert same_scope(root, root.lower())
        # Measured: resolve() canonicalises an existing path's case on this platform.
        assert str(Path(root.lower()).resolve()) == root


# ---------------------------------------------------------------------------------------------
# Rows.
# ---------------------------------------------------------------------------------------------


def _plan_rows(plan: PlanDocs) -> list[dict[str, Any]]:
    """10:1702-1727's rows with the abbreviated digests filled in, which is all they lack."""
    block = "\n".join(plan.lines(INTERFACES)[1702:1726])  # 10:1703-1726, the comment dropped
    block = "\n".join(line for line in block.splitlines() if not line.strip().startswith("//"))
    block = re.sub(r'"[0-9a-f]{4}…"', f'"{HEX}"', block).replace("<full sha256>", HEX)
    if WINDOWS:  # `/home/u/...` is drive-relative on Windows, not absolute (D425's table)
        block = block.replace('"/home/u/', '"C:/home/u/')
    return json.loads(block)["entries"]


def test_every_row_the_plan_prints_parses_once_its_digests_are_whole(plan: PlanDocs) -> None:
    plan.require()
    rows = _plan_rows(plan)
    assert [row["kind"] for row in rows] == ["mcp", "permissions", "instructions", "hooks", "skill"]
    for row in rows:
        entry = Entry.from_json(row)
        assert isinstance(entry, Entry), entry
        again = entry.to_json()
        assert {k: again[k] for k in row} == row
        assert list(again)[: len(row)] == list(row)  # the plan's key order, then ours


def test_the_plans_abbreviated_digests_are_refused(plan: PlanDocs) -> None:
    plan.require()
    assert '"sha256_after":"9f2c…"' in _line(plan, 1708)
    row = _entry().to_json() | {"sha256_after": "9f2c…"}
    assert Entry.from_json(row) == "sha256_after is not a full sha256"


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"target": "vim"}, "target"),
        ({"location": "remote"}, "location"),
        ({"scope_root": "/home/u/proj"}, "scope_root"),  # global with a root
        ({"written_at": "yesterday"}, "written_at"),
        ({"mode": "json-key", "key": ""}, "needs key"),
        ({"path": ""}, "path"),
    ],
)
def test_a_bad_row_says_what_is_wrong(change: dict[str, Any], problem: str) -> None:
    result = Entry.from_json(_entry().to_json() | change)
    assert isinstance(result, str)
    assert problem in result


def test_a_local_row_needs_an_absolute_scope_root() -> None:
    local = _entry(location="local", scope_root="relative/proj").to_json()
    assert Entry.from_json(local) == "scope_root is missing or not valid"
    absolute = str(Path.cwd().resolve())
    assert isinstance(Entry.from_json(local | {"scope_root": absolute}), Entry)


def test_each_mode_needs_its_own_field() -> None:
    cases = {
        "json-array-add": {"kind": "permissions", "values": [1]},
        "marker-section": {"kind": "instructions", "marker": ""},
        "json-hook-rules": {"kind": "hooks", "events": ["SessionStart", 1]},
        "dir": {"kind": "skill", "bundle_sha256": "short"},
    }
    for mode, fields in cases.items():
        row = _entry().to_json() | {"mode": mode} | fields
        assert f"a {mode} row needs" in str(Entry.from_json(row))


def test_unknown_keys_survive_a_rewrite() -> None:
    row = _entry().to_json() | {"added_by_0_2": {"x": 1}}
    entry = Entry.from_json(row)
    assert isinstance(entry, Entry)
    assert entry.to_json()["added_by_0_2"] == {"x": 1}


def test_a_row_has_the_three_added_fields() -> None:
    row = _entry(created_file=True, created_parents=("mcpServers",)).to_json()
    assert (row["owned_sha256"], row["created_file"], row["created_parents"]) == (
        HEX,
        True,
        ["mcpServers"],
    )
    skill = _entry(kind="skill", mode="dir", key="", path="~/.agents/skills/omniweave")
    skill_row = replace(skill, bundle_sha256=HEX, sha256_after="").to_json()
    assert "sha256_after" not in skill_row
    assert "owned_sha256" not in skill_row
    assert "key" not in skill_row


# ---------------------------------------------------------------------------------------------
# The receipt: identity, order, scope.
# ---------------------------------------------------------------------------------------------


def test_a_reinstall_replaces_its_row_and_moves_it_last() -> None:
    """10:1739 says appended; appending twice would leave a stale row. D449."""
    mcp = _entry()
    perms = _entry(kind="permissions", path="~/.claude/settings.json", mode="json-array-add")
    perms = replace(perms, key="", values=("mcp__omniweave__*",))
    receipt = Receipt(RELEASE).with_entry(mcp, release=RELEASE).with_entry(perms, release=RELEASE)
    again = replace(mcp, written_at="2026-09-02T00:00:00Z")
    updated = receipt.with_entry(again, release="0.1.1")
    assert [e.kind for e in updated.entries] == ["permissions", "mcp"]
    assert updated.entries[-1].written_at == "2026-09-02T00:00:00Z"
    assert updated.release == "0.1.1"


def test_two_local_installs_uninstalling_one_sees_only_its_own(tmp_path: Path) -> None:
    """G-install's fourth case (10:1780), from the receipt's side: filter on scope_root first."""
    a, b = str((tmp_path / "a").resolve()), str((tmp_path / "b").resolve())
    rows = [
        _entry(),
        _entry(location="local", scope_root=a, path=f"{a}/.mcp.json"),
        _entry(location="local", scope_root=b, path=f"{b}/.mcp.json"),
    ]
    receipt = Receipt(RELEASE, entries=tuple(rows))
    assert [e.path for e in receipt.for_scope("local", b)] == [f"{b}/.mcp.json"]
    assert [e.path for e in receipt.for_scope("global", None)] == ["~/.claude.json"]
    assert receipt.for_scope("local", str((tmp_path / "c").resolve())) == ()


# ---------------------------------------------------------------------------------------------
# Reading and writing, under the lock.
# ---------------------------------------------------------------------------------------------


def test_record_writes_one_row_per_call_each_with_its_own_stamp(held: InstallLock) -> None:
    first = record(held, _entry(), release=RELEASE, pid=PID)
    second_row = _entry(kind="instructions", path="~/.claude/CLAUDE.md", mode="marker-section")
    second_row = replace(second_row, key="", marker="<!-- omniweave:begin -->")
    second_row = replace(second_row, written_at="2026-09-01T10:12:04Z")
    second = record(held, second_row, release=RELEASE, pid=PID)
    assert first.ok
    assert second.ok
    stored = json.loads(receipt_path(held.home).read_bytes())
    assert (stored["release"], stored["schema"]) == (RELEASE, 1)
    assert [row["written_at"] for row in stored["entries"]] == [
        "2026-09-01T10:12:03Z",
        "2026-09-01T10:12:04Z",
    ]
    assert receipt_path(held.home).read_bytes() == render_json(stored)


def test_forget_drops_rows_by_identity(held: InstallLock) -> None:
    record(held, _entry(), release=RELEASE, pid=PID)
    assert forget(held, [_entry().identity()], release=RELEASE, pid=PID).ok
    assert load(held.home, pid=PID).receipt.entries == ()


def test_the_receipt_is_written_only_under_a_held_lock(tmp_path: Path) -> None:
    taken = take_lock(tmp_path, clock=_Clock(), wait_ms=0)
    assert taken.lock is not None
    taken.lock.release()
    refused = record(taken.lock, _entry(), release=RELEASE, pid=PID)
    assert not refused.ok
    assert "not held" in refused.reason
    assert not receipt_path(tmp_path).exists()


def test_a_missing_or_empty_receipt_is_an_empty_writable_one(tmp_path: Path) -> None:
    missing = load(tmp_path, pid=PID, release=RELEASE)
    assert (missing.state, missing.writable, missing.receipt.entries) == ("missing", True, ())
    receipt_path(tmp_path).write_bytes(b"")
    assert load(tmp_path, pid=PID).writable


def test_an_unparseable_receipt_is_backed_up_before_it_is_replaced(held: InstallLock) -> None:
    receipt_path(held.home).write_bytes(b'{"entries": [')
    loaded = load(held.home, pid=PID)
    assert (loaded.state, loaded.code, loaded.writable) == ("unparseable", UNPARSEABLE, True)
    assert record(held, _entry(), release=RELEASE, pid=PID).ok
    backup = held.home / (RECEIPT_NAME + ".backup")
    assert backup.read_bytes() == b'{"entries": ['


def test_a_newer_schema_is_read_but_never_rewritten(held: InstallLock) -> None:
    newer = json.dumps({"release": "9.0.0", "schema": 2, "entries": []}).encode()
    receipt_path(held.home).write_bytes(newer)
    loaded = load(held.home, pid=PID)
    assert (loaded.state, loaded.writable) == ("newer", False)
    assert not record(held, _entry(), release=RELEASE, pid=PID).ok
    assert receipt_path(held.home).read_bytes() == newer


def test_a_row_this_release_cannot_read_is_kept_verbatim(held: InstallLock) -> None:
    odd = _entry().to_json() | {"mode": "toml-key"}
    body = {"release": RELEASE, "schema": 1, "entries": [odd]}
    receipt_path(held.home).write_bytes(json.dumps(body).encode())
    loaded = load(held.home, pid=PID)
    assert loaded.receipt.entries == ()
    assert loaded.skipped == ("entry 0: mode is missing or not valid",)
    assert record(held, _entry(), release=RELEASE, pid=PID).ok
    assert odd in json.loads(receipt_path(held.home).read_bytes())["entries"]


# ---------------------------------------------------------------------------------------------
# The lock. D450.
# ---------------------------------------------------------------------------------------------


def test_the_lock_is_the_house_lock_at_the_plans_path(tmp_path: Path) -> None:
    home = tmp_path / "fresh" / "home"
    taken = take_lock(home, clock=_Clock(), wait_ms=0)
    assert taken.ok
    assert (taken.broke, taken.code) == (None, "")
    state = inspect(lock_path(home))
    assert state.present
    assert state.live is True
    assert state.holder is not None
    assert state.holder.acquired_ns == T0
    assert taken.lock is not None
    taken.lock.release()
    assert not lock_path(home).exists()


def test_a_second_install_is_refused_naming_the_first(held: InstallLock) -> None:
    refused = take_lock(held.home, clock=_Clock(T0 + 3_000_000_000), wait_ms=0)
    assert not refused.ok
    assert refused.code == RECEIPT_LOCKED
    assert "another ow install or uninstall holds" in refused.reason
    assert ", 3 s" in refused.reason
    assert "not broken" not in refused.reason


def test_a_live_holder_older_than_120_s_is_refused_not_broken(
    plan: PlanDocs, held: InstallLock
) -> None:
    """10:1745's rule would break this lock; its holder is alive -- say, at its own prompt."""
    plan.require()
    assert "a lock older than 120 s is broken" in _line(plan, 1745)
    later = T0 + (LOCK_REPORT_AGE_S + 80) * 1_000_000_000
    state = inspect(lock_path(held.home))
    assert state.holder is not None
    assert state.holder.age_s(later) > LOCK_REPORT_AGE_S  # the plan's rule: break it
    assert state.live is True  # the kernel's answer: its writer is alive
    refused = take_lock(held.home, clock=_Clock(later), wait_ms=0)
    assert not refused.ok
    assert "200 s" in refused.reason
    assert "not broken" in refused.reason
    assert held.held


def test_a_dead_holders_lock_is_broken_at_any_age_and_reported(tmp_path: Path) -> None:
    """A file left behind with no advisory lock on it: its writer is gone."""
    dead = LockHolder("elsewhere", 99_999, 0.0, "unavailable", T0 - 5_000_000_000)
    lock_path(tmp_path).write_text(dead.as_json() + "\n", encoding="utf-8")
    assert inspect(lock_path(tmp_path)).stale
    taken = take_lock(tmp_path, clock=_Clock(), wait_ms=0)
    assert taken.ok
    assert taken.broke == dead
    assert taken.code == RECEIPT_LOCKED
    assert "elsewhere pid 99999, 5 s old; its writer is gone" in taken.reason
    assert taken.lock is not None
    taken.lock.release()


def test_an_unwritable_home_is_a_refusal_not_a_raise(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_bytes(b"")
    taken = take_lock(blocker / "home", clock=_Clock(), wait_ms=0)
    assert not taken.ok
    assert "cannot create" in taken.reason


# ---------------------------------------------------------------------------------------------
# The two digests. D448, D449.
# ---------------------------------------------------------------------------------------------


def _write(path: Path, value: dict[str, Any]) -> str:
    action, wrote, _ = write_json(path, value, read_json(path, pid=PID), pid=PID)
    assert action in {"created", "updated"}
    assert wrote is not None
    return wrote.sha256


def _judge(entry: Entry, path: Path, owned_now: str | None) -> str:
    return verdict(
        entry, exists=path.exists(), current_sha256=file_sha256(path), owned_now=owned_now
    )


def test_the_plans_two_settings_rows_cannot_both_match_the_file(tmp_path: Path) -> None:
    """10:1709-1722: permissions, then hooks, into one file, each with the file's sha256."""
    settings = tmp_path / "settings.json"
    settings.write_bytes(b'{\n  "model": "opus"\n}\n')
    allow = ["mcp__omniweave__*"]
    doc = json.loads(settings.read_bytes()) | {"permissions": {"allow": allow}}
    perms = _entry(
        kind="permissions",
        path="~/.claude/settings.json",
        mode="json-array-add",
        key="permissions.allow",
        values=tuple(allow),
        sha256_after=_write(settings, doc),
        owned_sha256=sha256_canonical(allow),
    )
    hooks_doc = doc | {"hooks": {"SessionStart": [{"hooks": [{"command": "/x/ow hook start"}]}]}}
    hooks = _entry(
        kind="hooks",
        path="~/.claude/settings.json",
        mode="json-hook-rules",
        key="",
        events=("SessionStart",),
        sha256_after=_write(settings, hooks_doc),
    )
    now = json.loads(settings.read_bytes())
    assert file_sha256(settings) != perms.sha256_after  # stale the moment hooks landed
    assert (
        _judge(perms, settings, owned_array(now, "permissions.allow", allow)) == "owned-untouched"
    )
    assert _judge(hooks, settings, None) == "untouched"
    # The whole-file hashes chain only newest first, and only because this file round-trips:
    _write(settings, doc)
    assert _judge(perms, settings, None) == "untouched"


def test_a_host_rewriting_its_own_keys_leaves_the_owned_digest_intact(tmp_path: Path) -> None:
    """~/.claude.json holds the host's state beside mcpServers, and the host rewrites it."""
    config = tmp_path / ".claude.json"
    server = {"type": "stdio", "command": "/x/ow", "args": ["serve", "--mcp"], "env": {}}
    doc = {"numStartups": 1, "mcpServers": {"omniweave": server}}
    row = _entry(sha256_after=_write(config, doc), owned_sha256=sha256_canonical(server))
    _write(config, doc | {"numStartups": 2})
    owned = owned_key(json.loads(config.read_bytes()), "mcpServers.omniweave")
    assert _judge(row, config, owned) == "owned-untouched"
    edited = doc | {"mcpServers": {"omniweave": server | {"args": ["serve"]}}}
    _write(config, edited)
    owned = owned_key(json.loads(config.read_bytes()), "mcpServers.omniweave")
    assert _judge(row, config, owned) == "modified"
    config.unlink()
    assert _judge(row, config, None) == "missing"


def test_an_array_value_removed_by_the_user_is_modified() -> None:
    ours = ["mcp__omniweave__*"]
    assert owned_array(
        {"permissions": {"allow": ["Bash(git:*)", *ours]}}, "permissions.allow", ours
    ) == (sha256_canonical(ours))
    assert owned_array({"permissions": {"allow": []}}, "permissions.allow", ours) != (
        sha256_canonical(ours)
    )
    assert owned_array({}, "permissions.allow", ours) is None
    assert owned_key({"a": {"b": 1}}, "a.c") is None


def test_the_section_digest_ignores_the_users_text_and_newline_style() -> None:
    body = "## omniweave\n\nUse ow_query."
    text = upsert_marked_section("Mine.\n", body).text
    assert text is not None
    digest = owned_section(text)
    assert digest is not None
    assert owned_section("More of mine.\n" + text + "And more.\n") == digest
    assert owned_section(text.replace("\n", "\r\n")) == digest
    assert owned_section(text.replace("Use ow_query.", "Use grep.")) != digest
    assert owned_section("no section\n") is None


def test_removing_the_value_alone_leaves_containers_the_install_created(tmp_path: Path) -> None:
    """Why rows carry `created_parents`: G-install's first case, one value into no permissions."""
    settings = tmp_path / "settings.json"
    settings.write_bytes(b'{\n  "model": "opus"\n}\n')
    before = settings.read_bytes()
    doc = json.loads(before)
    _write(settings, doc | {"permissions": {"allow": ["mcp__omniweave__*"]}})
    _write(settings, doc | {"permissions": {"allow": []}})  # the value removed, nothing else
    assert settings.read_bytes() != before
    _write(settings, doc)  # what created_parents=("permissions", "permissions.allow") permits
    assert settings.read_bytes() == before


def test_verdict_prefers_the_whole_file_digest() -> None:
    row = _entry()
    assert verdict(row, exists=True, current_sha256=HEX, owned_now="x") == "untouched"
    assert verdict(row, exists=True, current_sha256="b" * 64, owned_now=HEX) == "owned-untouched"
    assert verdict(row, exists=True, current_sha256="b" * 64, owned_now=None) == "modified"
    unowned = replace(row, owned_sha256="")
    assert verdict(unowned, exists=True, current_sha256="b" * 64, owned_now=HEX) == "modified"


def test_file_sha256_reads_bytes(tmp_path: Path) -> None:
    path = tmp_path / "f"
    path.write_bytes(b"abc")
    assert file_sha256(path) == hashlib.sha256(b"abc").hexdigest()
    assert file_sha256(tmp_path / "absent") is None


def test_unbuilt_names_the_four_things_left() -> None:
    listed = unbuilt()
    assert len(listed) == 4
    assert any("D451" in line for line in listed)
    assert any("json-hook-rules" in line for line in listed)
