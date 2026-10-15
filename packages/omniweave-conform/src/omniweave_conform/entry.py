"""The `omniweave.eval` entry points: what `ow eval <verb>` calls in this distribution. **D833.**

D833 is `publish`; D840 adds `release_check`, and D846 `bless`.

10-interfaces.md section 2.5: *"`omniweave-conform` implements the `eval` Action group"*, and
the split between the two distributions is a dispatch fact. `omniweave` may not import this
package (`tools/layers.toml`), so `omniweave.surface.dispatch.eval_entry()` loads each function
here by its entry-point name at call time, as it loads `ow serve`'s.

**Only builtin values cross**, as across `ow serve`'s boundary. A type defined on either side is
one the other side cannot import, so arguments are `str` and `bool`, and the result is a `dict` of
`str`, `int`, `bool`, and lists of `str` or of `dict`s of `str`. The CLI builds its own report
from that.

**Paths arrive absolute.** The CLI resolves each against its working directory, so this side
never reads one.

Specified in 10-interfaces.md section 2.5 and 13-quality.md sections 11.1 and 13.3.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

from omniweave_core.errors import QualityError
from omniweave_core.host.subproc import run_captured
from omniweave_core.store.oweval import open_oweval

from omniweave_conform import inventory, release, scoreboard
from omniweave_conform.bless import BLESS_ENV, BLESS_ON, blessing

__all__ = ["bless", "publish", "release_check"]

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
