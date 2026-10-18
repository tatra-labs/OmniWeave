"""The `omniweave.eval` entry points: what `ow eval <verb>` calls in this distribution. **D833.**

D833 is `publish`; D840 adds `release_check`, D846 `bless`, and D868 `run`, which D869 widens
to the absence suite.

10-interfaces.md section 2.5: *"`omniweave-conform` implements the `eval` Action group"*, and
the split between the two distributions is a dispatch fact. `omniweave` may not import this
package (`tools/layers.toml`), so `omniweave.surface.dispatch.eval_entry()` loads each function
here by its entry-point name at call time, as it loads `ow serve`'s.

**Only builtin values cross**, as across `ow serve`'s boundary. A type defined on either side is
one the other side cannot import, so arguments are `str`, `bool` and `None`, and the result is a
`dict` of `str`, `int`, `float`, `bool`, `None`, and lists of `str` or of `dict`s of those. The CLI
builds its own report from that. The one exception is `run`'s `admit`, a function over
builtins, D869.

**Paths arrive absolute.** The CLI resolves each against its working directory, so this side
never reads one.

Specified in 10-interfaces.md section 2.5 and 13-quality.md sections 11.1 and 13.3.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from omniweave_core.clock import SystemClock
from omniweave_core.errors import QualityError
from omniweave_core.host.subproc import run_captured
from omniweave_core.store.oweval import Batch, open_oweval, write

from omniweave_conform import eval_run, inventory, release, scoreboard
from omniweave_conform.bless import BLESS_ENV, BLESS_ON, blessing

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = ["bless", "publish", "release_check", "run"]

GIT_TIMEOUT_S = 30.0


def publish(*, oweval: str, results: str, check: bool) -> dict[str, object]:
    """`ow eval publish`: `scoreboard.publish()` over two absolute paths, as builtins."""
    done = scoreboard.publish(Path(oweval), Path(results), check=check)
    return {
        "files": list(done.files),
        "rows": done.rows,
        "changed": list(done.changed),
        "written": done.written,
    }


def run(
    *,
    oweval: str,
    gates: str,
    root: str,
    suites: list[str],
    subject: str | None,
    witness: str,
    cassette: str,
    admit: Callable[[Sequence[str]], str | None],
) -> dict[str, object]:
    """`ow eval run`: each named suite's rows, written to `oweval` in one transaction. D868, D869.

    `suites` are run in the order given, every one of them built (`eval_run.BUILT`). `root` is the
    directory the register's `card` and `fixtures` paths are relative to, the working directory.
    `subject` narrows the parse suite's drivers and is refused for every other suite, whose
    subjects are its own: the product, or a target's compile driver. `admit` is
    `omniweave.surface.admit.admit`, 13:1306's check of a fix against the `ow` Action registry:
    the one callable that crosses, because this distribution may not import the registry, and
    it takes and returns builtins (`absence` ruling 1). The `.oweval` is created
    when it does not exist: a run is its writer. The clock is read here, at the edge.
    """
    register = Path(gates)
    if not register.is_file():
        raise QualityError(
            f"no file at {register}", fix="pass --gates PATH naming the metric register"
        )
    unbuilt = [suite for suite in suites if suite not in eval_run.BUILT]
    if unbuilt or not suites:
        raise QualityError(
            f"ow eval run measures {', '.join(eval_run.BUILT)} in this build, not "
            f"{', '.join(unbuilt) or 'nothing'}",
            fix="ow eval run --suite parse",
        )
    product = [suite for suite in suites if suite != "parse"]
    if subject is not None and product:
        raise QualityError(
            f"--subject names a parse driver, and the {product[0]} suite's subjects are its own",
            fix=f"ow eval run --suite {product[0]}  # without --subject",
        )
    rows = tomllib.loads(register.read_text(encoding="utf-8"))
    clock = SystemClock().wall_ns
    batches: list[Batch] = []
    done: list[eval_run.Measured] = []
    for suite in suites:
        if suite == "parse":
            batch, measured = eval_run.parse(
                rows,
                root=Path(root),
                subject=subject,
                witness=witness,
                cassette=cassette,
                now_ns=clock,
            )
        elif suite == "absence":
            batch, measured = eval_run.absence(
                rows, root=Path(root), witness=witness, cassette=cassette, now_ns=clock, admit=admit
            )
        elif suite == "retrieve":
            batch, measured = eval_run.retrieve(
                rows, root=Path(root), witness=witness, cassette=cassette, now_ns=clock
            )
        else:
            batch, measured = eval_run.roundtrip(
                rows, root=Path(root), witness=witness, cassette=cassette, now_ns=clock
            )
        batches.append(batch)
        done.extend(measured)
    connection = open_oweval(Path(oweval))
    try:
        write(connection, _merged(batches))
    finally:
        connection.close()
    return {
        "suites": list(suites),
        "oweval": oweval,
        "runs": [
            {
                "run_id": row.run_id,
                "suite": row.suite,
                "subject": row.subject,
                "slice": row.slice_key,
                "corpus": row.corpus_id,
                "metric": row.metric,
                "value": row.value,
                "n": row.n,
                "parsed": row.parsed,
                "refused": list(row.refused),
            }
            for row in done
        ],
    }


def _merged(batches: Sequence[Batch]) -> Batch:
    """Several suites' rows as one `Batch`, so one run is one transaction (13:385)."""
    corpora = {(corpus.corpus_id, corpus.version): corpus for b in batches for corpus in b.corpora}
    return Batch(
        corpora=tuple(corpora.values()),
        assertions=tuple(assertion for b in batches for assertion in b.assertions),
        runs=tuple(run for b in batches for run in b.runs),
        verdicts=tuple(verdict for b in batches for verdict in b.verdicts),
        metrics=tuple(metric for b in batches for metric in b.metrics),
    )


def release_check(*, oweval: str, gates: str, strict: bool) -> dict[str, object]:
    """`ow eval release-check`: `release.check_release()` over two absolute paths, as builtins.

    A missing `oweval` or register is refused rather than read. `open_oweval()` would create an
    empty store, and an absent register has no hard gates, so either would pass a release that
    nothing measured.
    """
    store, register = Path(oweval), Path(gates)
    for path, fix in (
        (store, "run the eval suites to write one, or pass --oweval PATH"),
        (register, "pass --gates PATH naming the metric register"),
    ):
        if not path.is_file():
            raise QualityError(f"no file at {path}", fix=fix)
    rows = tomllib.loads(register.read_text(encoding="utf-8"))
    connection = open_oweval(store)
    try:
        judged = release.check_release(connection, rows, strict=strict)
    finally:
        connection.close()
    return {
        "ok": judged.ok,
        "runs": judged.runs,
        "superseded": judged.superseded,
        "gates": judged.gates,
        "findings": [
            {"kind": f.kind, "names": f.names, "why": f.why, "fix": f.fix} for f in judged.findings
        ],
    }


def bless(*, root: str, reason: str, date: str, env: dict[str, str]) -> dict[str, object]:
    """`ow eval bless --inventory` (13:1847, :1872): `bless_inventory()` as builtins. D846.

    13-quality.md section 5.5's first requirement holds here as for a golden bless:
    *"`OMNIWEAVE_BLESS=1` in the environment"*, read from the `env` the CLI passes. The row's
    author is `<git-author-email>` (:804), read from `git config user.email` in `root`, because
    that is the address the commit carrying the row will be authored as.
    """
    if not blessing(env):
        raise QualityError(
            f"ow eval bless refuses: {BLESS_ENV}={BLESS_ON} is not in the environment",
            fix=f"{BLESS_ENV}={BLESS_ON} ow eval bless --inventory --reason '<why the tests went>'",
        )
    git = shutil.which("git", path=next((v for k, v in env.items() if k.upper() == "PATH"), None))
    found = (
        run_captured(
            (git, "config", "user.email"), stdin=b"", cwd=root, env=env, timeout_s=GIT_TIMEOUT_S
        )
        if git is not None
        else None
    )
    author = found.stdout.decode("utf-8", "replace").strip() if found is not None else ""
    if not author:
        raise QualityError(
            "the BLESS.log row needs an author, and `git config user.email` names none",
            fix="git config user.email <your address>",
        )
    done = inventory.bless_inventory(Path(root), reason=reason, date=date, author=author, env=env)
    return {
        "inventory": inventory.INVENTORY,
        "log": inventory.LOG,
        "row": done.row,
        "fell": list(done.fell),
        "changed": list(done.changed),
        "tests": done.tests,
    }
