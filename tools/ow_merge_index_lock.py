"""The git merge driver for `omniweave.index.lock` -- the executable git invokes.

`git config merge.ow-index-lock.driver "ow store merge-lock %O %A %B %L %P"`
is the shipped registration -- 07-store-and-retrieval.md:3146's value with
11-repo-layout.md:503's driver name, ruled in `indexlock.MERGE_DRIVER_NAME` and recorded as D20.
`ow store merge-lock` is a CLI verb W2.7's second half owns.
This file is the same driver as a standalone script, so the merge semantics can be registered,
tested and run before the CLI exists:

```text
git config merge.ow-index-lock.name   "omniweave index lock sort-merge"
git config merge.ow-index-lock.driver "uv run tools/ow_merge_index_lock.py %O %A %B %L %P"
```

`uv run tools/ow_merge_index_lock.py --print-registration` prints both, plus the `.gitattributes`
line, and every one of them names the literal path `omniweave.index.lock`. **There is no glob
anywhere in this file.** The plan says the driver is registered *"for that path only"*
(07:3112-3113, 01-principles.md:689, 02-architecture.md:1168), and this driver deletes lines: a
`*` here would union-or-delete every text file in the repository on every merge.

WHAT GIT PASSES, AND WHAT IT EXPECTS BACK
------------------------------------------
Positionally: `%O` the merge base, `%A` **ours -- and the file the driver must write**, `%B` theirs,
then optionally `%L` the conflict-marker length and `%P` the pathname being merged. The plan
registers all five; the task's contract is the first three; so the last two are optional here, which
makes one file satisfy both. Exit 0 means "resolved, `%A` is the answer"; any non-zero exit means
"conflict remains", and git then leaves the path conflicted for a human.

Three exit codes, because "conflict" and "I could not run" are different facts a human needs told
apart -- git treats both as a conflict, and only one of them is the merge working correctly:

* `0` -- clean. `%A` holds the merged receipt.
* `1` -- a real conflict. `%A` holds the merge WITH standard conflict markers, so
  `ow store verify --lock` refuses it with `OW-S-061` (07:3149-3151) until a human resolves it.
* `2` -- refused: an input is not a receipt (unsorted, malformed, not UTF-8). **`%A` is left
  untouched**, because the honest answer to "I cannot read your inputs" is not a rewritten file.
  This is the one case where ours survives verbatim and it is deliberate: git still reports the
  path as conflicted, and the diagnostic on stderr names the file and the rule it broke.

THE OUTPUT IS WRITTEN, THEN MOVED
----------------------------------
`%A` is both an input and the output, so the merged text goes to a sibling temporary file and is
`Path.replace`d into place -- one atomic rename on both POSIX and Windows. Two reasons: a driver
that truncated `%A` before it finished reading it would lose "ours" on any later failure, and an
interrupted driver must leave either the old file or the new one and never half of each. The
temporary lands beside `%A` rather than in `TMPDIR` so the rename stays within one filesystem.

MEMORY
------
`omniweave_core.store.indexlock.merge_streams` is a generator over three line iterators, and this
file feeds it three open file objects and writes what comes out. Peak memory is one buffered line
per input plus one output line -- **independent of corpus size**, which is the point: graphify's
equivalent driver caps out at `_MERGE_MAX_BYTES = 50 MB` / `_MERGE_MAX_NODES = 100_000`
(`graphify/cli.py:2547-2548`), *"two to three orders of magnitude below a real corpus"* (07:3108).
There is no cap in this file. The `report` has to be complete before the rename, so the generator is
drained into the temporary file first and the exit code is decided after -- which is exactly why the
rename is the last thing that happens.

`print` is banned repo-wide by ruff's `T20` and `tools/` has no `per-file-ignores` row, so every
diagnostic goes through `_emit` to an injected `TextIO`, defaulting to **stderr**: `%A` is the data
channel and stdout carries nothing a caller parses.

Specified by 07-store-and-retrieval.md section 13.2 (:3099-3160), 00-vision.md:583,
01-principles.md:688, 02-architecture.md:1168 and 11-repo-layout.md:496-505.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from omniweave_core.errors import OwError
from omniweave_core.store.indexlock import (
    CONFLICT_MARKER_LEN,
    DRIVER_DESCRIPTION,
    GITATTRIBUTES_LINE,
    LOCK_PATH,
    MergeReport,
    git_config_argv,
    merge_streams,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import TextIO

EXIT_CLEAN = 0
EXIT_CONFLICT = 1
EXIT_REFUSED = 2

TEMP_SUFFIX = ".owmerge-tmp"
"""The sibling temporary file's suffix. Beside `%A`, so the rename never crosses a filesystem."""

SCRIPT_COMMAND = "uv run tools/ow_merge_index_lock.py %O %A %B %L %P"
"""What to register while `ow store merge-lock` (07:3146) does not exist yet.

The placeholders are git's and are passed through verbatim, so the two registrations differ only in
the executable. `--print-registration` prints this one; `indexlock.DRIVER_COMMAND` is the shipped
one and stays the transcription of :3146.
"""


def _emit(out: TextIO, message: str = "") -> None:
    """The only stream write. T20 is on repo-wide, so a tool reports through an injected file."""
    out.write(message + "\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ow_merge_index_lock",
        description=f"The three-way sort-merge driver for {LOCK_PATH} (07:3122-3131).",
    )
    parser.add_argument(
        "--print-registration",
        action="store_true",
        help="print the .gitattributes line and the two `git config` commands, then exit 0",
    )
    parser.add_argument("ancestor", nargs="?", help="%%O -- the merge base")
    parser.add_argument("ours", nargs="?", help="%%A -- ours, AND the file this driver writes")
    parser.add_argument("theirs", nargs="?", help="%%B -- theirs")
    parser.add_argument(
        "marker_len",
        nargs="?",
        default=str(CONFLICT_MARKER_LEN),
        help="%%L -- git's conflict-marker length (default 7)",
    )
    parser.add_argument("pathname", nargs="?", default=LOCK_PATH, help="%%P -- the merged path")
    return parser


def _registration_lines(*, command: str = SCRIPT_COMMAND) -> tuple[str, ...]:
    """Everything an operator has to install, and nothing that widens the scope.

    Two halves, because a merge driver does not travel with a clone: `.gitattributes` is committed
    and binds the NAME to the path, `git config` is local and binds the name to a COMMAND
    (07:3136-3146). Both are printed together so the reader sees that only the first mentions a
    path, and that the path it mentions is one literal filename.
    """
    lines = ["# .gitattributes  (committed)", GITATTRIBUTES_LINE, ""]
    lines.append("# installed by `ow store git-install`, checked by `ow doctor` (07:3143)")
    for argv in git_config_argv(command=command):
        keyword, verb, key, value = argv
        lines.append(f'{keyword} {verb} {key} "{value}"')
    lines.append("")
    lines.append(f"# driver name: {DRIVER_DESCRIPTION}")
    return tuple(lines)


def _open_lines(path: str | None) -> TextIO | None:
    """Open one of git's inputs for reading, or answer `None` for "this side is empty".

    `newline=""` disables universal-newline translation on purpose: the `_Cursor` in `indexlock`
    strips a trailing CR itself (11-repo-layout.md:490-493 rule 3), and letting Python rewrite line
    endings on the way in would mean a CRLF working tree merged to different bytes than an LF one.

    A missing `%O` is empty rather than an error: git passes an empty ancestor for a path added on
    both branches, and some callers pass no ancestor path at all. A side that IS present but holds
    nothing reads as empty too, and both mean the same thing to `_resolve`: it claims nothing.
    """
    if path is None:
        return None
    handle = Path(path)
    if not handle.is_file():
        return None
    return handle.open(encoding="utf-8", newline="")


def _merge_to_temp(
    ancestor: str | None, ours: str, theirs: str, *, marker_len: int, report: MergeReport
) -> Path:
    """Stream the merge into a sibling temporary file and return it. Nothing is renamed here."""
    target = Path(ours)
    temp = target.with_name(target.name + TEMP_SUFFIX)
    base_handle = _open_lines(ancestor)
    ours_handle = _open_lines(ours)
    theirs_handle = _open_lines(theirs)
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as sink:
            for line in merge_streams(
                base_handle or (),
                ours_handle or (),
                theirs_handle or (),
                report=report,
                marker_len=marker_len,
            ):
                sink.write(line + "\n")
    finally:
        for handle in (base_handle, ours_handle, theirs_handle):
            if handle is not None:
                handle.close()
    return temp


def _reject(namespace: argparse.Namespace) -> str | None:
    """The argument checks, as one function, so `main` keeps its return count under PLR0911.

    Split out rather than inlined because each of the three is a distinct wrong invocation and a
    human reading a failed merge needs to be told which: too few arguments is a bad registration,
    a non-numeric `%L` is a bad `git config`, and a missing `%A` is not a merge at all.
    """
    if namespace.ours is None or namespace.theirs is None:
        return f"{LOCK_PATH}: usage: ow_merge_index_lock %O %A %B [%L] [%P]"
    if not namespace.marker_len.isdecimal() or int(namespace.marker_len) < 1:
        return f"{LOCK_PATH}: %L={namespace.marker_len!r} is not a positive int"
    if not Path(namespace.ours).is_file():
        # %A is the output file and git always creates it. If it is absent the invocation is not a
        # merge, and writing a fresh file there would invent a receipt nobody committed.
        return f"{namespace.pathname}: %A ({namespace.ours}) does not exist"
    return None


def main(argv: Sequence[str] | None = None, *, out: TextIO | None = None) -> int:
    """Merge, or refuse. Writes `%A` only on a completed merge; see the module docstring."""
    writer = sys.stderr if out is None else out
    namespace = _parser().parse_args(sys.argv[1:] if argv is None else list(argv))

    if namespace.print_registration:
        for line in _registration_lines():
            _emit(writer, line)
        return EXIT_CLEAN

    rejection = _reject(namespace)
    if rejection is not None:
        _emit(writer, rejection)
        return EXIT_REFUSED

    report = MergeReport()
    try:
        temp = _merge_to_temp(
            namespace.ancestor,
            namespace.ours,
            namespace.theirs,
            marker_len=int(namespace.marker_len),
            report=report,
        )
    except OwError as error:
        _emit(writer, f"{namespace.pathname}: {error}")
        _emit(writer, f"  fix: {error.fix}")
        _emit(writer, f"  {namespace.ours} is UNCHANGED; the merge is refused, not resolved.")
        return EXIT_REFUSED
    except UnicodeDecodeError as error:
        _emit(writer, f"{namespace.pathname}: not valid UTF-8 ({error.reason})")
        _emit(writer, "  fix: ow store lock")
        return EXIT_REFUSED

    temp.replace(Path(namespace.ours))
    if report.clean:
        return EXIT_CLEAN
    if report.header_conflict:
        _emit(
            writer,
            f"{namespace.pathname}: the header line differs -- schema, scorer, segmenter or space"
            " changed (07:3130)",
        )
    for key in report.conflicts:
        _emit(writer, f"{namespace.pathname}: conflicting lines for doc_key {key} (07:3129)")
    _emit(writer, f"  resolve {namespace.ours} by hand, then: ow store verify --lock")
    return EXIT_CONFLICT


if __name__ == "__main__":
    raise SystemExit(main())
