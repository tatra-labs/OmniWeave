"""`<sessions>/`: the locator, the journal, the markers and the sweep.

Everything here is deterministic. No test sleeps, every clock reading arrives as an argument, and
`tmp_path` is the only filesystem any of them touches -- which is the whole of what a unit tier may
assert about a directory three processes write to at once.

**The one thing this file cannot reach lives next door.** D400's loss needs concurrent writers, so
`tests/conform/test_hooks_session_append.py` carries it under the `conform` marker; what is left
here is the reader that counts the loss, tested against journals written by hand.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import textwrap
from pathlib import Path

import omniweave.hooks.session as session_module
from omniweave.hooks.session import (
    AT_NS,
    CONTROL_DIR,
    JOURNAL_MAX_BYTES,
    LIVE_SUFFIX,
    PID,
    PROJECT_FILE,
    READ_AGE_MIN,
    RECORD_MAX_BYTES,
    ROTATED_SUFFIX,
    SEQ,
    SESSIONS_DIR,
    SESSIONS_MAX_FILES,
    SWEEP_AGE_S,
    Journal,
    anchor,
    append,
    encode_record,
    journal_paths,
    read,
    rotate,
    sessions_dir,
    sweep,
    unmeasured,
    write_marker,
)

NOW: int = 1_800_000_000_000_000_000
MINUTE: int = 60 * 1_000_000_000
HOUR: int = 60 * MINUTE


def _store(tmp_path: Path) -> Path:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    return root


def _lines(path: Path) -> list[bytes]:
    return [line for line in path.read_bytes().split(b"\n") if line]


# ---------------------------------------------------------------------------------------------
# Locating `<sessions>`. 10:1893.
# ---------------------------------------------------------------------------------------------


def test_the_sessions_directory_sits_beside_the_resolved_project_file(tmp_path: Path) -> None:
    (tmp_path / PROJECT_FILE).write_text("[roots]\n", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)

    assert sessions_dir(nested) == tmp_path / CONTROL_DIR / SESSIONS_DIR


def test_the_walk_up_stops_at_a_git_directory_the_way_the_config_loader_does(
    tmp_path: Path,
) -> None:
    """`anchor` and `omniweave_core.config._walk_up` must agree or the two halves read two files.

    A test tree may import across the layers row that costs a hook 42 ms at run time (D401), so the
    agreement is checked against the real function rather than against a transcription of it.
    """
    from omniweave_core.config import _walk_up  # noqa: PLC0415

    (tmp_path / PROJECT_FILE).write_text("", encoding="utf-8")
    inner = tmp_path / "repo"
    (inner / ".git").mkdir(parents=True)
    deep = inner / "src"
    deep.mkdir()

    assert anchor(deep) is None
    assert _walk_up(deep, PROJECT_FILE) is None
    assert anchor(tmp_path) == _walk_up(tmp_path, PROJECT_FILE)


def test_a_deployment_with_no_project_file_has_no_sessions_directory_at_all(
    tmp_path: Path,
) -> None:
    """D403: `None` is a working install, not an error, and every hook in it is silent."""
    (tmp_path / ".git").mkdir()

    assert sessions_dir(tmp_path) is None


def test_the_control_directory_is_spelled_the_same_here_as_in_the_register_that_owns_it() -> None:
    """D401. The respelling is a budget decision; this is what stops it becoming a divergence."""
    from omniweave_core.config import CONTROL_DIR as DECLARED  # noqa: PLC0415

    assert CONTROL_DIR == DECLARED


def test_importing_the_config_register_costs_a_hook_a_measurable_part_of_its_budget() -> None:
    """D401: `omniweave_core.config` is not one of G17's nine, so no gate bounds what it drags in.

    Asserted as an import list rather than a duration, because a timing assertion in a unit suite
    is a flake. These are the names `-X importtime` attributes the 42 ms to: `tomllib` and
    `difflib` directly, and `importlib.resources` through `omniweave_core.errors`, which `config`
    imports at module scope inside a bootstrap `try`.
    """
    from omniweave_core import errors as errors_module  # noqa: PLC0415
    from omniweave_core.config import __file__ as config_file  # noqa: PLC0415

    config_imports = _module_scope_imports(Path(str(config_file)))
    errors_imports = _module_scope_imports(Path(str(errors_module.__file__)))

    assert {"tomllib", "difflib"} <= config_imports
    assert "omniweave_core.errors" in config_imports
    assert "importlib" in errors_imports
    assert "config" not in _lazy_names()


def _module_scope_imports(path: Path) -> set[str]:
    """Every name a module imports outside a function body -- what an import of it actually pays.

    A `try`/`except ImportError` shim and an `if TYPE_CHECKING` block read the same to `ast.walk`
    and do not cost the same, so only the first is counted: a `TYPE_CHECKING` import is free at
    run time and including it would overstate the very budget this test exists to measure.
    """
    found: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
            elif isinstance(node, ast.Try) or (
                isinstance(node, ast.If) and not _is_type_checking(node.test)
            ):
                visit(node.body)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return found


def _is_type_checking(test: ast.expr) -> bool:
    return isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"


def _lazy_names() -> tuple[str, ...]:
    root = Path(__file__).resolve()
    while not (root / "tools").is_dir():
        root = root.parent
    source = (root / "tools" / "gate_lazy_core.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "LAZY"
            and node.value is not None
        ):
            return tuple(str(name) for name in ast.literal_eval(node.value))
    raise AssertionError("gate_lazy_core.py no longer declares LAZY")


# ---------------------------------------------------------------------------------------------
# The record: the cap, the stamps, and what a caller cannot overwrite.
# ---------------------------------------------------------------------------------------------


def test_a_record_carries_the_three_stamps_a_reader_bounds_and_counts_by() -> None:
    line = encode_record({"kind": "query"}, at_ns=NOW, pid=41, seq=7)
    record = json.loads(line)

    assert record == {"kind": "query", AT_NS: NOW, PID: 41, SEQ: 7}
    assert line.endswith(b"\n")


def test_a_payload_cannot_forge_its_own_timestamp_pid_or_sequence() -> None:
    """A journal whose age came from the record would let one writer pin a dead session live."""
    line = encode_record({AT_NS: 1, PID: 2, SEQ: 3, "kind": "x"}, at_ns=NOW, pid=41, seq=7)

    assert json.loads(line) == {"kind": "x", AT_NS: NOW, PID: 41, SEQ: 7}


def test_an_oversize_record_is_refused_and_never_trimmed_to_the_cap() -> None:
    """Trimming would manufacture the malformed line 10:1912 tells the reader to skip."""
    line = encode_record({"pad": "x" * RECORD_MAX_BYTES}, at_ns=NOW, pid=1, seq=1)

    assert line == b""


def test_a_record_exactly_at_the_cap_is_written() -> None:
    room = RECORD_MAX_BYTES - len(encode_record({"pad": ""}, at_ns=NOW, pid=1, seq=1))
    line = encode_record({"pad": "x" * room}, at_ns=NOW, pid=1, seq=1)

    assert len(line) == RECORD_MAX_BYTES


def test_an_unserialisable_record_is_refused_rather_than_raised() -> None:
    assert encode_record({"handle": object()}, at_ns=NOW, pid=1, seq=1) == b""
    assert encode_record({"bad": float("nan")}, at_ns=NOW, pid=1, seq=1) == b""


def test_the_record_cap_is_the_plans_number_and_so_is_the_rotation_threshold() -> None:
    assert RECORD_MAX_BYTES == 4_096
    assert JOURNAL_MAX_BYTES == 4 * 1024 * 1024
    assert SESSIONS_MAX_FILES == 2_000
    assert READ_AGE_MIN == 240
    assert SWEEP_AGE_S == 24 * 60 * 60


# ---------------------------------------------------------------------------------------------
# Appending.
# ---------------------------------------------------------------------------------------------


def test_the_append_is_one_write_call_and_the_ast_says_so() -> None:
    """10:1913's defence is the single write. A second one would halve it with no visible change."""
    source = inspect.getsource(session_module.append)
    tree = ast.parse(textwrap.dedent(source))
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "write"
    ]

    assert len(writes) == 1


def test_the_handle_is_opened_in_append_mode_and_in_binary() -> None:
    """Binary, because text mode on Windows turns the capped line into a longer one."""
    source = inspect.getsource(session_module.append)
    tree = ast.parse(textwrap.dedent(source))
    modes = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "open"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ]

    assert modes == ["ab"]


def test_an_append_without_a_key_writes_nothing(tmp_path: Path) -> None:
    root = _store(tmp_path)

    written = append(root, "", {"kind": "x"}, at_ns=NOW)

    assert not written.ok
    assert written.reason == "no_key"
    assert list(root.iterdir()) == []


def test_an_oversize_append_reports_the_reason_and_leaves_the_journal_untouched(
    tmp_path: Path,
) -> None:
    root = _store(tmp_path)
    append(root, "k", {"kind": "first"}, at_ns=NOW)

    written = append(root, "k", {"pad": "x" * RECORD_MAX_BYTES}, at_ns=NOW)

    assert written.reason == "oversize"
    assert len(_lines(journal_paths(root, "k")[0])) == 1


def test_an_append_creates_the_sessions_directory_when_it_is_missing(tmp_path: Path) -> None:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR

    assert append(root, "k", {"kind": "x"}, at_ns=NOW).ok
    assert journal_paths(root, "k")[0].is_file()


def test_an_unwritable_root_is_a_reason_and_never_an_exception(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    written = append(blocker / "sessions", "k", {"kind": "x"}, at_ns=NOW)

    assert not written.ok
    assert written.reason == "io"


def test_the_sequence_advances_without_the_caller_supplying_one(tmp_path: Path) -> None:
    root = _store(tmp_path)
    for _ in range(3):
        append(root, "k", {"kind": "x"}, at_ns=NOW)

    seqs = [json.loads(line)[SEQ] for line in _lines(journal_paths(root, "k")[0])]

    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 3


def test_every_record_records_the_process_that_offered_it(tmp_path: Path) -> None:
    root = _store(tmp_path)
    append(root, "k", {"kind": "x"}, at_ns=NOW)

    assert json.loads(_lines(journal_paths(root, "k")[0])[0])[PID] == os.getpid()


# ---------------------------------------------------------------------------------------------
# Rotation. 10:1914, one generation.
# ---------------------------------------------------------------------------------------------


def test_the_journal_rotates_at_the_threshold_and_keeps_exactly_one_generation(
    tmp_path: Path,
) -> None:
    root = _store(tmp_path)
    live, rotated = journal_paths(root, "k")
    live.write_bytes(b"x" * JOURNAL_MAX_BYTES)

    written = append(root, "k", {"kind": "after"}, at_ns=NOW)

    assert written.rotated
    assert rotated.stat().st_size == JOURNAL_MAX_BYTES
    assert len(_lines(live)) == 1


def test_a_second_rotation_discards_the_older_generation_rather_than_keeping_two(
    tmp_path: Path,
) -> None:
    root = _store(tmp_path)
    live, rotated = journal_paths(root, "k")
    live.write_bytes(b"a" * 64)
    rotate(root, "k", max_bytes=8)
    live.write_bytes(b"b" * 64)
    rotate(root, "k", max_bytes=8)

    assert rotated.read_bytes() == b"b" * 64
    assert sorted(p.name for p in root.iterdir()) == [f"k{ROTATED_SUFFIX}"]


def test_rotation_of_a_journal_that_does_not_exist_is_false_and_not_an_error(
    tmp_path: Path,
) -> None:
    assert rotate(_store(tmp_path), "k") is False


def test_a_journal_below_the_threshold_does_not_rotate(tmp_path: Path) -> None:
    root = _store(tmp_path)
    append(root, "k", {"kind": "x"}, at_ns=NOW)

    assert rotate(root, "k") is False
    assert not journal_paths(root, "k")[1].exists()


# ---------------------------------------------------------------------------------------------
# Reading. 10:1912 and 10:1884.
# ---------------------------------------------------------------------------------------------


def test_a_read_skips_and_counts_malformed_lines_and_never_raises(tmp_path: Path) -> None:
    """*"A truncated last line after a `SIGKILL` is normal, not corruption."* 10:1912."""
    root = _store(tmp_path)
    live = journal_paths(root, "k")[0]
    good = encode_record({"kind": "ok"}, at_ns=NOW, pid=1, seq=0)
    live.write_bytes(good + b'{"kind": "trunc' + b"\n" + b"[]\n" + b"null\n" + good)

    journal = read(root, "k", now_ns=NOW)

    assert journal.skipped == 3
    assert len(journal.records) == 2


def test_a_record_with_no_usable_timestamp_is_skipped_because_it_cannot_be_age_bounded(
    tmp_path: Path,
) -> None:
    root = _store(tmp_path)
    live = journal_paths(root, "k")[0]
    live.write_bytes(b'{"kind":"x"}\n{"kind":"y","at_ns":"soon"}\n{"kind":"z","at_ns":true}\n')

    journal = read(root, "k", now_ns=NOW)

    assert journal.skipped == 3
    assert journal.records == ()


def test_records_outside_the_two_hundred_and_forty_minute_window_are_stale_not_skipped(
    tmp_path: Path,
) -> None:
    root = _store(tmp_path)
    append(root, "k", {"kind": "old"}, at_ns=NOW - 5 * HOUR, seq=0)
    append(root, "k", {"kind": "fresh"}, at_ns=NOW - 10 * MINUTE, seq=1)

    journal = read(root, "k", now_ns=NOW)

    assert journal.stale == 1
    assert journal.skipped == 0
    assert [record["kind"] for record in journal.records] == ["fresh"]


def test_a_journal_entirely_outside_the_window_reads_empty_and_says_so(tmp_path: Path) -> None:
    """10:1884's other clause: *"never renders a zero-state snapshot as data."*"""
    root = _store(tmp_path)
    append(root, "k", {"kind": "old"}, at_ns=NOW - 30 * HOUR, seq=0)

    journal = read(root, "k", now_ns=NOW)

    assert journal.empty()
    assert journal.stale == 1


def test_a_missing_journal_reads_as_the_zero_value_and_names_no_sources(tmp_path: Path) -> None:
    journal = read(_store(tmp_path), "absent", now_ns=NOW)

    assert journal == Journal()


def test_a_read_without_a_key_is_the_zero_value(tmp_path: Path) -> None:
    assert read(_store(tmp_path), "", now_ns=NOW) == Journal()


def test_the_rotated_generation_is_read_too_and_oldest_comes_first(tmp_path: Path) -> None:
    """D404: rotation and the 240-minute window are independent boundaries.

    A rotation at minute 239 leaves a live file holding seconds. Reading only that file would make
    the reader go quiet exactly after the busiest session inside the window it claims to cover.
    """
    root = _store(tmp_path)
    live, rotated = journal_paths(root, "k")
    rotated.write_bytes(encode_record({"kind": "earlier"}, at_ns=NOW - HOUR, pid=1, seq=0))
    live.write_bytes(encode_record({"kind": "later"}, at_ns=NOW - MINUTE, pid=1, seq=1))

    journal = read(root, "k", now_ns=NOW)

    assert [record["kind"] for record in journal.records] == ["earlier", "later"]
    assert journal.sources == (f"k{ROTATED_SUFFIX}", f"k{LIVE_SUFFIX}")


def test_an_age_bound_the_caller_widens_still_reads_both_generations(tmp_path: Path) -> None:
    root = _store(tmp_path)
    append(root, "k", {"kind": "old"}, at_ns=NOW - 10 * HOUR, seq=0)

    assert read(root, "k", now_ns=NOW, max_age_min=12 * 60).records != ()


# ---------------------------------------------------------------------------------------------
# The gap count: D400's instrument.
# ---------------------------------------------------------------------------------------------


def test_a_hole_in_one_writers_sequence_is_counted(tmp_path: Path) -> None:
    root = _store(tmp_path)
    live = journal_paths(root, "k")[0]
    live.write_bytes(
        b"".join(encode_record({"i": i}, at_ns=NOW, pid=7, seq=i) for i in (0, 1, 4, 5))
    )

    assert read(root, "k", now_ns=NOW).gaps == 2


def test_two_writers_are_counted_separately_and_never_against_each_other(tmp_path: Path) -> None:
    """`seq` is per-process, so interleaving two writers must not read as a gap."""
    root = _store(tmp_path)
    live = journal_paths(root, "k")[0]
    live.write_bytes(
        encode_record({"i": 0}, at_ns=NOW, pid=1, seq=0)
        + encode_record({"i": 0}, at_ns=NOW, pid=2, seq=0)
        + encode_record({"i": 1}, at_ns=NOW, pid=1, seq=1)
        + encode_record({"i": 1}, at_ns=NOW, pid=2, seq=1)
    )

    assert read(root, "k", now_ns=NOW).gaps == 0


def test_the_gap_count_is_a_lower_bound_and_cannot_overstate_the_loss(tmp_path: Path) -> None:
    """Records lost at the ends of a run are invisible, which is the right direction to be wrong."""
    root = _store(tmp_path)
    live = journal_paths(root, "k")[0]
    live.write_bytes(encode_record({"i": 9}, at_ns=NOW, pid=7, seq=9))

    assert read(root, "k", now_ns=NOW).gaps == 0


def test_a_record_whose_stamps_were_lost_is_ignored_by_the_gap_count(tmp_path: Path) -> None:
    root = _store(tmp_path)
    live = journal_paths(root, "k")[0]
    live.write_bytes(b'{"at_ns":%d,"pid":"seven","seq":3}\n' % NOW)

    assert read(root, "k", now_ns=NOW).gaps == 0


# ---------------------------------------------------------------------------------------------
# Markers. 10:1938.
# ---------------------------------------------------------------------------------------------


def test_a_marker_is_written_whole_and_replaces_the_previous_one(tmp_path: Path) -> None:
    root = _store(tmp_path)

    assert write_marker(root, "k", "compacted", {"at_ns": 1, "reason": "auto"})
    assert write_marker(root, "k", "compacted", {"at_ns": 2, "reason": "manual"})

    assert json.loads((root / "k.compacted").read_text(encoding="utf-8"))["at_ns"] == 2


def test_a_marker_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
    root = _store(tmp_path)
    write_marker(root, "k", "briefing", {"text": "restored"})

    assert sorted(p.name for p in root.iterdir()) == ["k.briefing"]


def test_a_marker_with_no_key_or_no_name_is_refused(tmp_path: Path) -> None:
    root = _store(tmp_path)

    assert write_marker(root, "", "compacted", {}) is False
    assert write_marker(root, "k", "", {}) is False
    assert list(root.iterdir()) == []


def test_an_unserialisable_marker_is_false_rather_than_an_exception(tmp_path: Path) -> None:
    assert write_marker(_store(tmp_path), "k", "compacted", {"h": object()}) is False


def test_a_marker_never_raises_when_the_root_cannot_be_made(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")

    assert write_marker(blocker / "sessions", "k", "compacted", {"a": 1}) is False


# ---------------------------------------------------------------------------------------------
# The sweep. 10:1918.
# ---------------------------------------------------------------------------------------------


def _age(path: Path, ns_ago: int) -> None:
    stamp = (NOW - ns_ago) / 1_000_000_000
    os.utime(path, (stamp, stamp))


def test_files_older_than_twenty_four_hours_are_removed(tmp_path: Path) -> None:
    root = _store(tmp_path)
    for name, ns_ago in (("old.jsonl", 30 * HOUR), ("fresh.jsonl", 2 * HOUR)):
        (root / name).write_text("{}\n", encoding="utf-8")
        _age(root / name, ns_ago)

    swept = sweep(root, now_ns=NOW)

    assert swept.aged == ("old.jsonl",)
    assert sorted(p.name for p in root.iterdir()) == ["fresh.jsonl"]


def test_eviction_above_the_cap_takes_the_oldest_first(tmp_path: Path) -> None:
    root = _store(tmp_path)
    for index in range(6):
        path = root / f"s{index}.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        _age(path, (6 - index) * MINUTE)

    swept = sweep(root, now_ns=NOW, max_files=4)

    assert swept.evicted == ("s0.jsonl", "s1.jsonl")
    assert swept.kept == 4


def test_the_sweep_does_not_depend_on_session_end_having_fired(tmp_path: Path) -> None:
    """*"A host that crashes never fires `SessionEnd`."* Age alone is the whole criterion."""
    root = _store(tmp_path)
    live = root / "crashed.jsonl"
    live.write_text("{}\n", encoding="utf-8")
    _age(live, 25 * HOUR)

    assert sweep(root, now_ns=NOW).aged == ("crashed.jsonl",)


def test_the_literal_rule_deletes_the_counters_file_and_keep_is_where_a_decision_lands(
    tmp_path: Path,
) -> None:
    """D402. The default is the plan read literally; the argument is the place to disagree."""
    root = _store(tmp_path)
    counters = root / "counters.json"
    counters.write_text("{}", encoding="utf-8")
    _age(counters, 30 * HOUR)

    assert not (root / "counters.json").exists() if sweep(root, now_ns=NOW).aged else False

    counters.write_text("{}", encoding="utf-8")
    _age(counters, 30 * HOUR)
    swept = sweep(root, now_ns=NOW, keep=frozenset({"counters.json"}))

    assert swept.aged == ("counters.json",)
    assert counters.exists()


def test_a_sweep_that_tears_a_session_group_in_half_reports_the_orphan(tmp_path: Path) -> None:
    """D402's other half: eviction is per file and a session is a group of them."""
    root = _store(tmp_path)
    journal = root / f"abc{LIVE_SUFFIX}"
    journal.write_text("{}\n", encoding="utf-8")
    _age(journal, 30 * HOUR)
    briefing = root / "abc.briefing"
    briefing.write_text("{}", encoding="utf-8")
    _age(briefing, MINUTE)

    swept = sweep(root, now_ns=NOW)

    assert swept.aged == (f"abc{LIVE_SUFFIX}",)
    assert swept.orphaned == ("abc",)
    assert briefing.exists()


def test_a_session_swept_whole_is_not_an_orphan(tmp_path: Path) -> None:
    root = _store(tmp_path)
    for name in (f"abc{LIVE_SUFFIX}", "abc.briefing"):
        (root / name).write_text("{}\n", encoding="utf-8")
        _age(root / name, 30 * HOUR)

    assert sweep(root, now_ns=NOW).orphaned == ()


def test_directories_under_the_sessions_root_are_left_alone(tmp_path: Path) -> None:
    root = _store(tmp_path)
    nested = root / "somedir"
    nested.mkdir()
    _age(nested, 40 * HOUR)

    swept = sweep(root, now_ns=NOW)

    assert swept.aged == ()
    assert nested.is_dir()


def test_a_missing_sessions_root_sweeps_to_the_zero_value(tmp_path: Path) -> None:
    swept = sweep(tmp_path / "absent", now_ns=NOW)

    assert swept.aged == ()
    assert swept.kept == 0


def test_the_sweep_runs_the_age_pass_before_the_eviction_cap(tmp_path: Path) -> None:
    """An aged file must not consume one of the 2,000 slots the cap is counting."""
    root = _store(tmp_path)
    for index in range(4):
        path = root / f"s{index}.jsonl"
        path.write_text("{}\n", encoding="utf-8")
        _age(path, 30 * HOUR if index < 2 else MINUTE * (4 - index))

    swept = sweep(root, now_ns=NOW, max_files=2)

    assert set(swept.aged) == {"s0.jsonl", "s1.jsonl"}
    assert swept.evicted == ()


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_module_imports_nothing_first_party() -> None:
    """The envelope's rule, and this module inherits it. D401 is why it is worth a test."""
    tree = ast.parse(Path(str(session_module.__file__)).read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)

    assert not [name for name in names if name.startswith("omniweave")]
    assert set(names) <= {
        "__future__",
        "itertools",
        "json",
        "os",
        "tempfile",
        "dataclasses",
        "pathlib",
        "typing",
        "collections.abc",
    }


def test_the_module_names_no_loop_no_socket_and_no_store() -> None:
    """02:255 row 34's forbidden column, read as a check: a hook must not pay a loop import."""
    source = Path(str(session_module.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }

    assert names.isdisjoint({"asyncio", "selectors", "socket", "sqlite3"})


def test_every_public_name_is_exported() -> None:
    public = {
        name
        for name in vars(session_module)
        if not name.startswith("_") and name not in {"annotations", "TYPE_CHECKING"}
    }
    declared = set(session_module.__all__)

    assert declared <= public
    assert public - declared <= {
        "GIT_DIR",
        "Path",
        "Any",
        "Final",
        "dataclass",
        "itertools",
        "json",
        "os",
        "tempfile",
    }


def test_the_unmeasured_list_names_the_four_things_this_suite_cannot_reach() -> None:
    stated = unmeasured()

    assert len(stated) == 4
    assert any("POSIX" in item for item in stated)
    assert any("counters.json" in item for item in stated)


def test_the_package_re_exports_the_session_store() -> None:
    import omniweave.hooks as package  # noqa: PLC0415

    assert "append" in package.__all__
    assert package.read is read
