"""Q-G3, golden bless, as a program: a landed change against the `BLESS.log` rows it adds. **D841.**

16-roadmap.md:979: `uv run tools/gate_bless.py  # bless flow + test_bless_flag_is_off()`.
13-quality.md:94: *"`Q-G3` | `BLESS.log` plus the reduction diff | a frozen or tracked diff has a
bless row in the same commit"*, and section 5.5 gives the four requirements. 11-repo-layout.md:2262
adds the `Bless:` footer: *"required in the **same commit** as any change to `schema/expected/` or
`eval/baselines/`, with a reason of at least 20 characters, mirrored into `eval/BLESS.log`"*. The
row grammar, append-only, coverage and the second-reviewer arithmetic are
`omniweave_conform.bless`'s (D820). This file reads git, applies them, prints, and exits, following
the standing pattern (ledger D25).

## Rulings

1. **The change judged is the commit that lands.** Merges are squash-only (11:2268), so a pull
   request lands as one commit: the diff from the merge base with `--base` to `--head`, and the
   `BLESS.log` at each end. A row added in a fix-up commit is in the same landed commit. On the base
   branch itself, where the merge base is `--head`, the last commit is the squash and is judged
   against its parent.
2. **A guarded path is one a bless must cover.** That is a frozen or tracked Reduction under
   `fixtures/goldens/` (`*.shape`, `*.pages`, `*.outline`, 13 section 5.1), or anything under
   `schema/expected/` or `eval/baselines/` (11:2262). A `.gitkeep` holds nothing to bless.
   A deleted guarded file is a change like any other.
3. **`eval/BLESS.log` is append-only**, the old file a byte prefix of the new, and every row it
   adds must parse. A rewritten or deleted log fails and is judged no further.
4. **Each guarded change needs an added row whose glob matches it, and each added row must match
   a guarded change.** A row that blesses nothing is a finding: the log is append-only, so a stray
   row can never be removed once it lands.
5. **An added row with `unexplained` above 0 fails.** Requirement 4 has no override.
6. **An added row whose `structural` share is above 20% prints that it needs a second reviewer.**
   Counting reviews needs the forge, which an offline gate cannot read, so this is a note and the
   branch protection rule is the check.
7. **A change to `schema/expected/` or `eval/baselines/` needs a `Bless:` footer** in a commit
   message in the range, a line `Bless: <reason>`, whose reason is an added row's. That is 11's
   *"mirrored"*. The reason length is the row's rule, so a footer mirroring a valid row is long
   enough.
8. **`OMNIWEAVE_BLESS=1` in the gate's own environment fails**: that is `test_bless_flag_is_off()`
   at the `X` column (13:1987), so a CI job that exported the flag cannot pass its own blesses.

Not checked: that a row's author is the commit's author. A squash merge can rewrite the author's
email to a forge address, so the check would fail a correct bless.

## Exit codes

`0` nothing guarded changed unblessed and nothing else failed. `1` a finding, named with its fix.
`2` the gate did not run: no git, an unknown ref, or an argument it cannot read.

Specified in 13-quality.md sections 2.1, 5.5 and 14, 11-repo-layout.md section 8.3, and
16-roadmap.md section 13.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess  # noqa: TID251 - the gate's input is a git range and `git` is its only reader.
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.bless import (  # noqa: E402
    BLESS_ENV,
    SECOND_REVIEWER_SHARE,
    BlessRow,
    append_only,
    blessing,
    covers,
)
from omniweave_core.errors import QualityError  # noqa: E402

__all__ = [
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "LOG",
    "Finding",
    "GitError",
    "file_at",
    "guarded",
    "judge",
    "landed",
    "main",
]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

LOG: Final = "eval/BLESS.log"
_REDUCTIONS: Final = ("fixtures/goldens/", (".shape", ".pages", ".outline"))
_FOOTED: Final = ("schema/expected/", "eval/baselines/")
_FOOTER: Final = re.compile(r"^Bless:[ \t]*(.*?)[ \t]*$", re.MULTILINE)
_EMPTY_TREE: Final = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
_BLESS_FIX: Final = (
    f"{BLESS_ENV}=1 ow eval golden --bless --reason '<why, 20+ characters>', and commit the "
    f"{LOG} row with the change"
)


@dataclass(frozen=True, slots=True)
class Finding:
    """One line of the report. `failing` is False for a note."""

    failing: bool
    subject: str
    detail: str


class GitError(Exception):
    """git could not answer: the gate did not run."""


def guarded(path: str) -> bool:
    """Ruling 2."""
    if path.rsplit("/", 1)[-1] == ".gitkeep":
        return False
    root, suffixes = _REDUCTIONS
    return (path.startswith(root) and path.endswith(suffixes)) or path.startswith(_FOOTED)


def judge(
    changed: list[str],
    old_log: str,
    new_log: str,
    messages: list[str],
    env: Mapping[str, str],
) -> list[Finding]:
    """Rulings 3-8 over one landed change: its changed paths, its log at each end, its messages."""
    findings = []
    if blessing(env):
        findings.append(
            Finding(
                True,
                BLESS_ENV,
                "is 1 in the gate's environment: unset it in CI (test_bless_flag_is_off)",
            )
        )
    paths = sorted(path for path in changed if guarded(path))
    try:
        added = append_only(old_log, new_log)
    except QualityError as exc:
        return [*findings, Finding(True, LOG, f"{exc}; restore the old rows and append")]
    coverage = covers(paths, added)
    findings += [
        Finding(True, path, f"changed with no {LOG} row whose glob matches it; {_BLESS_FIX}")
        for path in coverage.unblessed
    ]
    findings += [
        Finding(True, f"{LOG} row {row.glob}", "blesses no guarded change in this commit")
        for row in coverage.idle
    ]
    for row in added:
        findings.extend(_row(row))
    if any(path.startswith(_FOOTED) for path in paths):
        reasons = {row.reason.strip() for row in added}
        footers = [m.group(1) for text in messages for m in _FOOTER.finditer(text)]
        if not any(footer in reasons for footer in footers):
            findings.append(
                Finding(
                    True,
                    "Bless: footer",
                    "schema/expected/ or eval/baselines/ changed and no commit message carries "
                    f"a Bless: footer mirroring an added {LOG} row's reason",
                )
            )
    return findings


def _row(row: BlessRow) -> list[Finding]:
    """Rulings 5 and 6 for one added row."""
    out = []
    touched = sum(row.counts.values())
    if row.counts["unexplained"]:
        out.append(
            Finding(
                True,
                f"{LOG} row {row.glob}",
                f"blesses {row.counts['unexplained']} unexplained change(s), and there is no "
                "override: ow eval golden --explain <file>",
            )
        )
    if touched and row.counts["structural"] / touched > SECOND_REVIEWER_SHARE:
        out.append(
            Finding(
                False,
                f"{LOG} row {row.glob}",
                f"needs a second reviewer: {row.counts['structural']}/{touched} structural is "
                f"above {SECOND_REVIEWER_SHARE:.0%}",
            )
        )
    return out


def _git(repo: Path, *arguments: str) -> bytes:
    """`git <arguments>` in `repo`, or `GitError`."""
    executable = shutil.which("git")
    if executable is None:
        raise GitError("git is not on PATH")
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, argv[0] from `shutil.which`.
        [executable, *arguments],
        cwd=repo,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {' '.join(arguments)}: {message}")
    return completed.stdout


def _rev(repo: Path, ref: str) -> str:
    return _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").decode().strip()


def file_at(repo: Path, rev: str, path: str) -> str:
    """`path` at `rev`, or empty when it does not exist there. Q-G24 reads it too (D845)."""
    if rev == _EMPTY_TREE:
        return ""
    listed = _git(repo, "ls-tree", "--name-only", rev, "--", path).decode().strip()
    return _git(repo, "show", f"{rev}:{path}").decode("utf-8") if listed else ""


def landed(repo: Path, base: str, head: str) -> tuple[str, str]:
    """Ruling 1: the `(old, new)` revisions of the change that lands."""
    head_rev = _rev(repo, head)
    merge_base = _git(repo, "merge-base", _rev(repo, base), head_rev).decode().strip()
    if merge_base != head_rev:
        return merge_base, head_rev
    parents = _git(repo, "rev-list", "--parents", "-n", "1", head_rev).decode().split()
    return (parents[1] if len(parents) > 1 else _EMPTY_TREE), head_rev


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    """0 clean, 1 a finding, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_bless.py",
        description="Q-G3: every frozen or tracked diff has a BLESS.log row in the same commit.",
    )
    parser.add_argument("--base", default="origin/master", metavar="REF")
    parser.add_argument("--head", default="HEAD", metavar="REF")
    parser.add_argument("--repo", type=Path, default=REPO, metavar="PATH")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    try:
        old, new = landed(args.repo, args.base, args.head)
        changed = (
            _git(args.repo, "diff", "--name-only", "-z", "--no-renames", old, new)
            .decode("utf-8")
            .split("\0")
        )
        messages = (
            _git(args.repo, "log", "--format=%B%x00", f"{old}..{new}").decode("utf-8").split("\0")
            if old != _EMPTY_TREE
            else [_git(args.repo, "log", "-1", "--format=%B", new).decode("utf-8")]
        )
        old_log, new_log = file_at(args.repo, old, LOG), file_at(args.repo, new, LOG)
    except (GitError, UnicodeDecodeError) as exc:
        _say(f"Q-G3 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN

    changed = [path for path in changed if path]
    findings = judge(changed, old_log, new_log, messages, os.environ if env is None else env)
    span = "the root commit" if old == _EMPTY_TREE else f"{old[:12]}..{new[:12]}"
    guarded_n = sum(1 for path in changed if guarded(path))
    _say(f"Q-G3  {span}: {len(changed)} changed path(s), {guarded_n} guarded")
    for one in findings:
        _say(f"  {'FAIL' if one.failing else 'note'}  {one.subject}: {one.detail}")
    failing = [one for one in findings if one.failing]
    _say(f"Q-G3 {'FAIL' if failing else 'ok'}  {len(failing)} finding(s)")
    return EXIT_FAIL if failing else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
