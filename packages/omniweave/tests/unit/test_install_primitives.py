"""The shared write primitives: each one against the measured way its obvious version fails.

**The sharpest test is `test_install_then_uninstall_is_byte_identical_in_every_host_style`.** It is
G-install (10:1775) in miniature, over one JSON file per style this machine's hosts actually write:
add `mcpServers.omniweave` beside an unrelated server, take it out, and compare bytes. With
Python's default serialiser it fails four of the five (D441); in the file's fitted style it passes
all five. The second is `test_the_blank_line_separator_is_not_invertible`, which is why the marked
section is inserted after exactly one newline (D446).
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.install import primitives as module
from omniweave.install.primitives import (
    BEGIN,
    BOM,
    DEFAULT_STYLE,
    END,
    REPLACE_BACKOFF_S,
    UNPARSEABLE,
    JsonStyle,
    atomic_write,
    backup,
    fit_style,
    json_deep_equal,
    read_json,
    remove_marked_section,
    render_json,
    section_span,
    temp_name,
    unbuilt,
    upsert_marked_section,
    write_json,
)

if TYPE_CHECKING:
    from conftest import PlanDocs

PID = 4242
WINDOWS = sys.platform == "win32"
BACKSLASH = chr(92)

# One file per style measured on this machine (the module docstring's table), with synthetic
# content: the shapes are the hosts', the values are not anybody's.
HOST_STYLES: dict[str, bytes] = {
    "claude.json: 2, LF, none, non-ASCII": (
        '{\n  "numStartups": 12,\n  "userName": "Zoë Åström",\n'
        '  "mcpServers": {\n    "other": {\n      "command": "x"\n    }\n  }\n}'
    ).encode(),
    "claude settings.json: 2, LF, newline": (
        b'{\n  "permissions": {\n    "allow": [\n      "Bash(git:*)"\n    ]\n  },\n'
        b'  "mcpServers": {\n    "other": {\n      "command": "x"\n    }\n  }\n}\n'
    ),
    "cursor mcp.json: 2, LF, none": (
        b'{\n  "mcpServers": {\n    "other": {\n      "command": "x",\n'
        b'      "args": []\n    }\n  }\n}'
    ),
    "vscode settings.json: 4, CRLF, none": (
        b'{\r\n    "editor.fontSize": 14,\r\n    "mcpServers": {\r\n        "other": {\r\n'
        b'            "command": "x"\r\n        }\r\n    }\r\n}'
    ),
    "cursor settings.json: 4, LF, none": (
        b'{\n    "window.zoomLevel": 1,\n    "mcpServers": {\n        "other": {\n'
        b'            "command": "x"\n        }\n    }\n}'
    ),
}


def _install_and_uninstall(raw: bytes, style: JsonStyle) -> bytes:
    value = json.loads(raw.decode("utf-8-sig"))
    value["mcpServers"]["omniweave"] = {"type": "stdio", "command": "/x/ow", "args": ["serve"]}
    installed = render_json(value, style)
    after = json.loads(installed.decode("utf-8-sig"))
    del after["mcpServers"]["omniweave"]
    return render_json(after, style)


# ---------------------------------------------------------------------------------------------
# D441: the reversal gate and the serialiser.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(HOST_STYLES))
def test_install_then_uninstall_is_byte_identical_in_every_host_style(name: str) -> None:
    raw = HOST_STYLES[name]
    text = raw.decode()
    style = fit_style(text, json.loads(text))
    assert style is not None, name
    assert _install_and_uninstall(raw, style) == raw


def test_pythons_default_serialiser_fails_four_of_the_five() -> None:
    """The measurement that makes the style a primitive rather than a nicety."""
    naive = JsonStyle(indent="  ", ascii=True, trailing="")
    survived = [
        name for name, raw in HOST_STYLES.items() if _install_and_uninstall(raw, naive) == raw
    ]
    assert survived == ["cursor mcp.json: 2, LF, none"]


def test_the_default_style_is_what_claude_code_writes_settings_json_in() -> None:
    assert render_json({"a": [1]}) == b'{\n  "a": [\n    1\n  ]\n}\n'
    assert DEFAULT_STYLE.ascii is False


@pytest.mark.parametrize(
    ("text", "indent", "item", "key"),
    [
        ('{"a":1,"b":[1,2]}', None, ",", ":"),
        ('{"a": 1, "b": [1, 2]}', None, ", ", ": "),
        ('{\n\t"a": 1\n}\n', "\t", ",", ": "),
        ("{}\n", "  ", ",", ": "),
    ],
)
def test_compact_tab_and_empty_files_fit(
    text: str, indent: str | None, item: str, key: str
) -> None:
    style = fit_style(text, json.loads(text))
    assert style is not None
    assert (style.indent, style.item_separator, style.key_separator) == (indent, item, key)


def test_an_empty_object_file_gets_the_default_indent() -> None:
    """So a key added later is written as a created file would be, not on one long line."""
    style = fit_style("{}\n", {})
    assert style is not None
    assert render_json({"a": {"b": 1}}, style) == b'{\n  "a": {\n    "b": 1\n  }\n}\n'


def test_an_ascii_escaped_file_is_written_back_escaped() -> None:
    text = '{\n  "name": "Zo' + BACKSLASH + 'u00eb"\n}'
    style = fit_style(text, json.loads(text))
    assert style is not None
    assert style.ascii is True


@pytest.mark.parametrize(
    "text",
    [
        '{\n  "a": 1,\n  "a": 2\n}',  # a duplicate key: the parse keeps one
        '{\n  "a": 1e5\n}',  # a number spelled another way
        '{\r\n  "a": 1,\n  "b": 2\r\n}',  # mixed newlines
        '  {\n  "a": 1\n}',  # leading whitespace
        '{\n  "a": 1,\n    "b": 2\n}',  # inconsistent indent
    ],
)
def test_a_file_that_cannot_round_trip_is_known_in_advance(tmp_path: Path, text: str) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(text.encode())
    read = read_json(path, pid=PID)
    assert read.state == "parsed"
    assert read.round_trips is False
    assert read.value


def test_this_machines_own_host_configs_round_trip() -> None:
    """Read-only: parse each host config present and fit its style. Nothing is written."""
    home = Path.home()
    names = (
        ".claude.json",
        ".claude/settings.json",
        ".cursor/mcp.json",
        "AppData/Roaming/Code/User/settings.json",
        "AppData/Roaming/Cursor/User/settings.json",
        ".gemini/settings.json",
    )
    fitted = 0
    for name in names:
        path = home / name
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig")
            value = json.loads(text)
        except (OSError, ValueError):
            continue
        assert fit_style(text, value, bom=raw.startswith(BOM)) is not None, name
        fitted += 1
    if not fitted:
        pytest.skip("no host config on this machine")


# ---------------------------------------------------------------------------------------------
# D442: json_deep_equal is not ==.
# ---------------------------------------------------------------------------------------------


def test_python_equality_conflates_true_one_and_one_point_zero() -> None:
    assert {"a": True} == {"a": 1} == {"a": 1.0}
    assert not json_deep_equal({"a": True}, {"a": 1})
    assert not json_deep_equal({"a": 1}, {"a": 1.0})
    assert not json_deep_equal([False], [0])
    assert not json_deep_equal(None, False)


def test_object_order_is_ignored_and_array_order_is_not() -> None:
    assert json_deep_equal({"a": 1, "b": [1, {"c": None}]}, {"b": [1, {"c": None}], "a": 1})
    assert not json_deep_equal({"a": [1, 2]}, {"a": [2, 1]})
    assert not json_deep_equal({"a": 1}, {"a": 1, "b": 1})


def test_a_tuple_is_an_array() -> None:
    assert json_deep_equal({"args": ("serve", "--mcp")}, {"args": ["serve", "--mcp"]})


# ---------------------------------------------------------------------------------------------
# D443: read_json, the BOM, and backups that do not clobber.
# ---------------------------------------------------------------------------------------------


def test_json_loads_rejects_a_bom_and_read_json_does_not(tmp_path: Path) -> None:
    raw = BOM + b'{\n  "a": 1\n}\n'
    with pytest.raises(ValueError, match="BOM"):
        json.loads(raw.decode("utf-8"))
    path = tmp_path / "settings.json"
    path.write_bytes(raw)
    read = read_json(path, pid=PID)
    assert (read.state, read.value, read.style.bom, read.round_trips) == (
        "parsed",
        {"a": 1},
        True,
        True,
    )
    assert not path.with_name("settings.json.backup").exists()
    action, _, _ = write_json(path, {"a": 2}, read, pid=PID)
    assert action == "updated"
    assert path.read_bytes() == BOM + b'{\n  "a": 2\n}\n'


def test_a_missing_file_is_an_empty_object_that_round_trips(tmp_path: Path) -> None:
    read = read_json(tmp_path / "absent.json", pid=PID)
    assert (read.state, read.value, read.round_trips, read.raw) == ("missing", {}, True, None)


def test_an_empty_file_is_not_backed_up_and_cannot_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"  \n")
    read = read_json(path, pid=PID)
    assert (read.state, read.round_trips, read.backup) == ("empty", False, None)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        (b'{"a": 1,}', "JSONDecodeError"),  # a trailing comma: JSONC, as VS Code allows
        (b'// a comment\n{"a": 1}', "JSONDecodeError"),
        (b"[1, 2]", "the top level is array"),
        (b'{"a": NaN}', "NaN is not JSON"),
        (b'{"a": "\xff"}', "not UTF-8"),
    ],
)
def test_an_unparseable_config_is_backed_up_byte_for_byte_first(
    tmp_path: Path, raw: bytes, why: str
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(raw)
    read = read_json(path, pid=PID)
    assert (read.state, read.value, read.code) == ("unparseable", {}, UNPARSEABLE)
    assert read.backup == tmp_path / "settings.json.backup"
    assert read.backup is not None
    assert read.backup.read_bytes() == raw
    assert why in read.reason
    assert str(read.backup) in read.reason


def test_a_second_failure_does_not_overwrite_the_first_backup(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"{ the original")
    first = read_json(path, pid=PID)
    path.write_bytes(b"{ broken again")
    second = read_json(path, pid=PID)
    assert first.backup == tmp_path / "settings.json.backup"
    assert second.backup == tmp_path / "settings.json.backup.1"
    assert first.backup is not None
    assert second.backup is not None
    assert first.backup.read_bytes() == b"{ the original"
    assert second.backup.read_bytes() == b"{ broken again"


def test_the_same_bytes_reuse_their_backup(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"{ broken")
    assert read_json(path, pid=PID).backup == read_json(path, pid=PID).backup
    assert sorted(p.name for p in tmp_path.iterdir()) == ["settings.json", "settings.json.backup"]


def test_no_backup_means_no_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "BACKUP_LIMIT", 1)
    path = tmp_path / "settings.json"
    path.with_name("settings.json.backup").write_bytes(b"somebody else's")
    path.write_bytes(b"{ broken")
    read = read_json(path, pid=PID)
    assert read.backup is None
    assert "could not be backed up" in read.reason
    action, wrote, _ = write_json(path, {"mcpServers": {}}, read, pid=PID)
    assert (action, wrote) == ("kept", None)
    assert path.read_bytes() == b"{ broken"


def test_backup_refuses_past_the_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "BACKUP_LIMIT", 2)
    path = tmp_path / "c.json"
    for suffix in (".backup", ".backup.1"):
        path.with_name("c.json" + suffix).write_bytes(b"other")
    assert backup(path, b"mine", pid=PID) == "2 backups of c.json already exist"


def test_an_unreadable_path_is_refused_not_backed_up(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.mkdir()
    read = read_json(path, pid=PID)
    assert (read.state, read.backup) == ("unreadable", None)
    assert write_json(path, {"a": 1}, read, pid=PID)[0] == "kept"


# ---------------------------------------------------------------------------------------------
# write_json.
# ---------------------------------------------------------------------------------------------


def test_a_created_file_is_written_in_the_default_style(tmp_path: Path) -> None:
    path = tmp_path / "nested" / ".mcp.json"
    before = read_json(path, pid=PID)
    action, wrote, _ = write_json(path, {"mcpServers": {"omniweave": {}}}, before, pid=PID)
    assert action == "created"
    assert wrote is not None
    assert path.read_bytes() == render_json({"mcpServers": {"omniweave": {}}})


def test_an_equal_value_is_unchanged_and_nothing_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b'{\n    "b": 1,\n    "a": 2\n}')
    before = read_json(path, pid=PID)

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("an unchanged file was written")

    monkeypatch.setattr(module, "atomic_write", refuse)
    assert write_json(path, {"a": 2, "b": 1}, before, pid=PID) == ("unchanged", None, "")


def test_a_type_change_python_calls_equal_is_written(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b'{\n  "enabled": 1\n}\n')
    action, _, _ = write_json(path, {"enabled": True}, read_json(path, pid=PID), pid=PID)
    assert action == "updated"
    assert path.read_bytes() == b'{\n  "enabled": true\n}\n'


def test_an_unparseable_config_is_written_over_after_its_backup(tmp_path: Path) -> None:
    """10:1652 as written: back up, return {}, and the caller fills it. D443 records the cost."""
    path = tmp_path / "settings.json"
    path.write_bytes(b'{"a": 1,}')
    before = read_json(path, pid=PID)
    action, _, note = write_json(path, {"b": 2}, before, pid=PID)
    assert action == "updated"
    assert "backed up to" in note
    assert json.loads(path.read_bytes()) == {"b": 2}
    assert (tmp_path / "settings.json.backup").read_bytes() == b'{"a": 1,}'


def test_a_value_json_cannot_hold_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    assert write_json(path, {"a": float("nan")}, read_json(path, pid=PID), pid=PID)[0] == "kept"
    assert not path.exists()


# ---------------------------------------------------------------------------------------------
# atomic_write. 10:1650, D444, D445.
# ---------------------------------------------------------------------------------------------


def test_the_temp_file_is_a_sibling_named_tmp_pid() -> None:
    assert temp_name(Path("/h/.claude/settings.json"), 77) == Path(
        "/h/.claude/settings.json.tmp.77"
    )


def test_a_write_lands_whole_and_leaves_no_temp(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "settings.json"
    wrote = atomic_write(path, b"{}\n", pid=PID)
    assert wrote.ok
    assert wrote.attempts == 1
    assert path.read_bytes() == b"{}\n"
    assert wrote.sha256 == "ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356"
    assert sorted(p.name for p in path.parent.iterdir()) == ["settings.json"]


def test_a_stale_temp_from_a_reused_pid_is_replaced(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    temp_name(path, PID).write_bytes(b"left by a crash")
    assert atomic_write(path, b"new", pid=PID).ok
    assert path.read_bytes() == b"new"
    assert not temp_name(path, PID).exists()


def test_a_failed_write_unlinks_its_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")

    def broken(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", broken)
    wrote = atomic_write(path, b"new", pid=PID)
    assert not wrote.ok
    assert wrote.attempts == 1  # not a PermissionError, so not retried
    assert path.read_bytes() == b"old"
    assert not temp_name(path, PID).exists()


def test_a_directory_is_refused(tmp_path: Path) -> None:
    wrote = atomic_write(tmp_path, b"x", pid=PID)
    assert not wrote.ok
    assert "is a directory" in wrote.reason


def test_a_parent_that_is_a_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "f").write_bytes(b"")
    assert not atomic_write(tmp_path / "f" / "settings.json", b"x", pid=PID).ok


def test_a_read_only_file_is_refused_and_untouched(tmp_path: Path) -> None:
    """Windows refuses the replace anyway (measured); POSIX's rename would not. D444."""
    path = tmp_path / "managed.json"
    path.write_bytes(b"locked")
    path.chmod(stat.S_IREAD)
    try:
        wrote = atomic_write(path, b"new", pid=PID)
        assert not wrote.ok
        assert "read-only" in wrote.reason
        assert path.read_bytes() == b"locked"
        assert not temp_name(path, PID).exists()
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


@pytest.mark.skipif(WINDOWS, reason="POSIX mode bits")
def test_an_existing_files_mode_is_kept(tmp_path: Path) -> None:  # pragma: no cover -- POSIX
    path = tmp_path / ".claude.json"
    path.write_bytes(b"{}")
    path.chmod(0o600)
    assert atomic_write(path, b'{"a":1}', pid=PID).ok
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as error:  # pragma: no cover -- Windows without developer mode
        pytest.skip(f"cannot create a symlink here: {error}")


def test_os_replace_over_a_symlink_replaces_the_link(tmp_path: Path) -> None:
    """The measurement: the obvious write turns a dotfile manager's link into a file. D444."""
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_bytes(b"{}")
    link = tmp_path / "settings.json"
    _symlink(link, real)
    staged = tmp_path / "staged"
    staged.write_bytes(b'{"a":1}')
    staged.replace(link)
    assert not link.is_symlink()
    assert real.read_bytes() == b"{}"


def test_a_write_goes_through_a_symlink(tmp_path: Path) -> None:
    real = tmp_path / "dotfiles" / "settings.json"
    real.parent.mkdir()
    real.write_bytes(b"{}")
    link = tmp_path / "settings.json"
    _symlink(link, real)
    wrote = atomic_write(link, b'{"a":1}', pid=PID)
    assert wrote.ok
    assert wrote.path == real.resolve()
    assert link.is_symlink()
    assert real.read_bytes() == b'{"a":1}'


def test_a_symlink_loop_is_refused(tmp_path: Path) -> None:
    one, two = tmp_path / "one", tmp_path / "two"
    _symlink(one, two)
    _symlink(two, one)
    wrote = atomic_write(one, b"x", pid=PID)
    assert not wrote.ok


def test_a_locked_replace_is_retried_with_a_doubling_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    real_replace = Path.replace
    failures = [PermissionError(13, "held"), PermissionError(13, "held")]

    def flaky(self: Path, target: Path) -> Path:
        if failures:
            raise failures.pop(0)
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    waits: list[float] = []
    wrote = atomic_write(path, b"x", pid=PID, sleep=waits.append)
    assert wrote.ok
    assert wrote.attempts == 3
    assert waits == [REPLACE_BACKOFF_S, REPLACE_BACKOFF_S * 2]


def test_a_replace_locked_for_good_gives_up_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")

    def held(*_: object) -> None:
        error = PermissionError(13, "held")
        error.winerror = 32  # type: ignore[attr-defined]
        raise error

    monkeypatch.setattr(Path, "replace", held)
    waits: list[float] = []
    wrote = atomic_write(path, b"new", pid=PID, sleep=waits.append, attempts=4)
    assert not wrote.ok
    assert wrote.attempts == 4
    assert len(waits) == 3
    assert "another process has it open" in wrote.reason
    assert path.read_bytes() == b"old"
    assert not temp_name(path, PID).exists()


def test_a_real_reader_holding_the_file_is_waited_out(tmp_path: Path) -> None:
    """D445 against the OS: on Windows the first replace fails while the handle is open."""
    path = tmp_path / "settings.json"
    path.write_bytes(b"old")
    handle = path.open("rb")
    waits: list[float] = []

    def close_then_wait(seconds: float) -> None:
        waits.append(seconds)
        handle.close()

    try:
        wrote = atomic_write(path, b"new", pid=PID, sleep=close_then_wait)
    finally:
        handle.close()
    assert wrote.ok
    assert path.read_bytes() == b"new"
    if WINDOWS:
        assert wrote.attempts == 2
        assert waits == [REPLACE_BACKOFF_S]
    else:  # pragma: no cover -- POSIX renames over an open file
        assert wrote.attempts == 1


# ---------------------------------------------------------------------------------------------
# The marked section. D446.
# ---------------------------------------------------------------------------------------------

BODY = "## omniweave\n\nUse `ow_query` first."


def _block(newline: str = "\n") -> str:
    return newline.join([BEGIN, "## omniweave", "", "Use `ow_query` first.", END]) + newline


def test_the_plan_names_the_begin_marker_and_no_end_marker(plan: PlanDocs) -> None:
    plan.require()
    text = plan.text("10-interfaces.md") + plan.text("18-api-sketch.md")
    assert BEGIN in text
    assert "omniweave:end" not in text
    assert END not in text


def test_the_blank_line_separator_is_not_invertible() -> None:
    """The obvious insert maps two files to one; ours maps them to two."""

    def blank_line(text: str) -> str:
        return text.rstrip("\n") + "\n\n" + _block()

    assert blank_line("X\n") == blank_line("X")
    assert upsert_marked_section("X\n", BODY).text != upsert_marked_section("X", BODY).text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "\n\n",
        "X",
        "X\n",
        "X\n\n",
        "# Title\n\nBody text.\n",
        "  ",
        "X\r\n",
        "X\r\nY",
        "X\r\n\r\n",
        "Zoë\n",
        "```\ncode\n```\n",
    ],
)
def test_remove_undoes_upsert_byte_for_byte(text: str) -> None:
    inserted = upsert_marked_section(text, BODY)
    assert inserted.action == "created"
    assert inserted.text is not None
    removed = remove_marked_section(inserted.text)
    assert removed.action == "removed"
    assert removed.text == text


def test_one_newline_then_the_block() -> None:
    assert upsert_marked_section("", BODY).text == _block()
    assert upsert_marked_section("X", BODY).text == "X\n" + _block()
    assert upsert_marked_section("X\n", BODY).text == "X\n\n" + _block()


def test_a_crlf_file_gets_a_crlf_block() -> None:
    result = upsert_marked_section("X\r\n", "a\nb\r\nc\n\n")
    assert result.text == "X\r\n\r\n" + "\r\n".join([BEGIN, "a", "b", "c", END]) + "\r\n"


def test_an_existing_block_is_replaced_in_place_and_the_users_text_kept() -> None:
    old = "Mine above.\n\n" + BEGIN + "\nold words\n" + END + "\n\nMine below.\n"
    result = upsert_marked_section(old, BODY)
    assert result.action == "updated"
    assert result.text == "Mine above.\n\n" + _block() + "\nMine below.\n"
    assert result.text is not None
    assert upsert_marked_section(result.text, BODY).action == "unchanged"


def test_text_after_the_block_survives_its_removal() -> None:
    text = "X\n" + _block() + "Y\n"
    assert remove_marked_section(text).text == "X\nY\n"


def test_a_marker_inside_a_fence_is_not_the_section() -> None:
    quoted = "Docs:\n\n```markdown\n" + BEGIN + "\nexample\n" + END + "\n```\n"
    assert section_span(quoted) is None
    inserted = upsert_marked_section(quoted, BODY)
    assert inserted.text == quoted + "\n" + _block()
    assert inserted.text is not None
    assert remove_marked_section(inserted.text).text == quoted


def test_tilde_and_longer_fences_close_only_on_their_own_kind() -> None:
    text = "~~~~\n" + BEGIN + "\n```\n" + END + "\n~~~\n~~~~\n"
    assert section_span(text) is None


def test_a_marker_with_trailing_space_counts_and_an_indented_one_does_not() -> None:
    assert isinstance(section_span(BEGIN + "  \nx\n" + END + "\n"), tuple)
    assert section_span("    " + BEGIN + "\n") is None


@pytest.mark.parametrize(
    "text",
    [
        BEGIN + "\na\n" + END + "\n" + BEGIN + "\nb\n" + END + "\n",
        "mine\n" + BEGIN + "\nno end, and everything after is the user's\n",
        END + "\n" + BEGIN + "\n",
        "mine\n" + END + "\n",
    ],
)
def test_an_ambiguous_section_is_refused_by_both_edits(text: str) -> None:
    for result in (upsert_marked_section(text, BODY), remove_marked_section(text)):
        assert result.text is None
        assert result.action == "kept"
        assert "markers" in result.reason


def test_removing_an_absent_section_is_not_found() -> None:
    assert remove_marked_section("mine\n").action == "not-found"
    assert remove_marked_section("mine\n").text == "mine\n"


# ---------------------------------------------------------------------------------------------
# What is not here.
# ---------------------------------------------------------------------------------------------


def test_unbuilt_names_pruning_refresh_and_the_two_decisions_owed() -> None:
    listed = unbuilt()
    assert len(listed) == 4
    assert any("pruning" in line for line in listed)
    assert any("refresh_targets" in line for line in listed)
    assert any("D441" in line for line in listed)
    assert any("D443" in line for line in listed)


def test_every_exported_name_exists() -> None:
    for name in module.__all__:
        assert hasattr(module, name), name
