"""`ow eval golden`'s first half: the Tier-A goldens, checked or blessed. **D848.**

13-quality.md section 5.5 prints the flow, *"`OMNIWEAVE_BLESS=1 ow eval golden --bless --reason
'...'`"*, with its four requirements, and section 5.1 says what is committed. This file:
1. copies every fixture `fixtures/index.toml` lists into a scratch project;
2. ingests them with `python -m omniweave add` in a child process, as a user's `ow add` would;
3. reduces every stored document through `omniweave_conform.golden`;
4. compares the result with `fixtures/goldens/<corpus>/`, or writes it.

The arithmetic is the library's, following the standing pattern (ledger D25). It is a `tools/`
script until `ow eval golden` is an Action.

## Rulings

1. **`--check` (the default) fails on any change.** A frozen `shape` that moved is a build failure
   by section 5.1. A tracked `pages` or `outline` that moved merges only with a bless row, and this
   gate is where a missing one shows. Each change prints its class and why, with
   `churn.classify()`'s reasons.
2. **`--bless --reason TEXT` writes the goldens and appends their `BLESS.log` row in one step.**
   It holds section 5.5's four requirements through `omniweave_conform.bless.plan()`:
   - `OMNIWEAVE_BLESS=1` in the environment;
   - a reason of 20 characters;
   - a second reviewer printed above 20% `structural`;
   - no `unexplained` change, ever.

   The row's glob is `fixtures/goldens/<corpus>/*`, its author `git config user.email`, its date
   today's, UTC. Files no document produces any more are removed, so the tree is exactly the
   ingest's.
3. **The ingest is a child process with the three `[drivers]` opt-ins a checkout needs** (D576),
   in a scratch directory that is removed afterwards. Its exit must be 0, and anything else means
   the gate did not run. `ow add` exits 0 when it finishes, even with the refused fixtures
   (corrupt, encrypted, not a document): each refusal is recorded per unit and reported as
   `partial`, which is this corpus's normal state.

## Exit codes

`0` the goldens match, or were blessed. `1` they differ (`--check`), or the bless was refused.
`2` the gate did not run: the ingest failed, or an argument it cannot read.

Specified in 13-quality.md sections 5.1-5.5, and 16-roadmap.md W10.2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess  # noqa: TID251 - the ingest is a real `ow add` child, and git names the author.
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Final

REPO = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave_conform.bless import BLESS_ENV, blessing, parse_log, plan  # noqa: E402
from omniweave_conform.churn import load_decomposition  # noqa: E402
from omniweave_conform.golden import CORPUS, GOLDENS, changes, read_tree, reductions  # noqa: E402
from omniweave_core.errors import QualityError  # noqa: E402
from omniweave_core.store import sqlite as ow  # noqa: E402

__all__ = ["EXIT_CLEAN", "EXIT_FAIL", "EXIT_NOT_RUN", "PROJECT", "ingest", "main"]

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2
PROJECT: Final = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
"""Ruling 3: the project file a scratch ingest runs under, as the conform tests' (D576)."""
LOG: Final = "eval/BLESS.log"
INGEST_TIMEOUT_S: Final = 1800


def ingest(root: Path, corpus: str = CORPUS) -> dict[str, str]:
    """Rulings 3 and 1: every `fixtures/index.toml` fixture ingested and reduced, or `OSError`."""
    rows = tomllib.loads((root / "fixtures" / "index.toml").read_text(encoding="utf-8"))
    scratch = Path(tempfile.mkdtemp(prefix="ow-golden-"))
    try:
        for row in rows.get("fixture", []):
            source = root / row["path"]
            parts = Path(row["path"]).parts
            target = scratch / "docs" / Path(*parts[1:2], *parts[3:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
        (scratch / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
        env["OMNIWEAVE_HOME"] = str(scratch / "owhome")
        log = scratch / "add.log"
        with log.open("wb") as sink:
            code = subprocess.call(
                [sys.executable, "-m", "omniweave", "add", "docs"],
                cwd=scratch,
                env=env,
                stdout=sink,
                stderr=subprocess.STDOUT,
                timeout=INGEST_TIMEOUT_S,
            )
        if code != 0:
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
            message = f"ow add exited {code}: " + " | ".join(tail)
            raise OSError(message)
        connection = ow.connect_readonly(scratch / ".omniweave" / "index.owstore")
        try:
            return reductions(connection, scratch / ".omniweave" / "cas", corpus=corpus)
        finally:
            connection.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _author(root: Path) -> str:
    git = shutil.which("git")
    if git is None:
        return ""
    done = subprocess.run(  # noqa: S603 - argv[0] from `shutil.which`, no shell.
        [git, "config", "user.email"], cwd=root, capture_output=True, check=False
    )
    return done.stdout.decode("utf-8", "replace").strip()


def main(argv: list[str] | None = None) -> int:
    """0 the goldens match or were blessed, 1 they differ or the bless was refused, 2 not run."""
    parser = argparse.ArgumentParser(
        prog="ow_golden.py", description="The Tier-A golden Reductions: --check, or --bless."
    )
    parser.add_argument("--root", type=Path, default=REPO, metavar="PATH")
    parser.add_argument("--bless", action="store_true", help="write the goldens and their row")
    parser.add_argument("--reason", default=None, metavar="TEXT")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    root: Path = args.root
    try:
        fresh = ingest(root)
        decomposition = load_decomposition(root / GOLDENS / "DECOMPOSITION.toml")
    except (OSError, ValueError, QualityError) as exc:
        _say(f"golden DID NOT RUN  {exc}")
        return EXIT_NOT_RUN
    committed = read_tree(root)
    moved = changes(committed, fresh, decomposition)
    _say(f"golden  {CORPUS}: {len(fresh)} file(s) from the ingest, {len(committed)} committed")
    for change in moved:
        why = "; ".join(change.churn.reasons) or ", ".join(d.key for d in change.churn.delta)
        _say(f"  {change.churn.cls:<12} {change.doc}: {why}")
    if not args.bless:
        _say(f"golden {'FAIL' if moved else 'ok'}  {len(moved)} document(s) changed")
        return EXIT_FAIL if moved else EXIT_CLEAN
    return _bless(root, committed, fresh, moved, args.reason)


def _bless(
    root: Path, committed: dict[str, str], fresh: dict[str, str], moved: list, reason: str | None
) -> int:
    """Ruling 2."""
    if not moved:
        _say("golden ok  nothing to bless: the goldens already match the ingest")
        return EXIT_CLEAN
    today = dt.datetime.now(tz=dt.UTC).date().isoformat()
    if not blessing(os.environ):
        _say(f"golden FAIL  the bless is refused: {BLESS_ENV}=1 is not in the environment")
        _say(f"  fix   {BLESS_ENV}=1 uv run tools/ow_golden.py --bless --reason '<why>'")
        return EXIT_FAIL
    author = _author(root)
    if not author:
        _say("golden FAIL  the bless is refused: `git config user.email` names no author")
        _say("  fix   git config user.email <your address>")
        return EXIT_FAIL
    try:
        blessed = plan(
            {change.doc: change.churn for change in moved},
            env=os.environ,
            date=today,
            author=author,
            glob=f"{GOLDENS}/{CORPUS}/*",
            reason=reason or "",
        )
        log = root / LOG
        old = log.read_text(encoding="utf-8") if log.is_file() else ""
        parse_log(old)
    except QualityError as exc:
        _say(f"golden FAIL  the bless is refused: {exc}")
        _say(f"  fix   {exc.fix}")
        return EXIT_FAIL
    base = root / GOLDENS
    for path in committed:
        if path not in fresh:
            (base / path).unlink()
    for path, text in fresh.items():
        (base / path).parent.mkdir(parents=True, exist_ok=True)
        (base / path).write_bytes(text.encode("utf-8"))
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_bytes((old + blessed.row.line()).encode("utf-8"))
    if blessed.second_reviewer:
        _say(
            f"  note  a second reviewer is required: {blessed.structural}/{blessed.touched}"
            " structural is above 20%"
        )
    _say(f"golden blessed  {len(moved)} document(s); wrote {GOLDENS}/{CORPUS}/ and a row in {LOG}")
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
