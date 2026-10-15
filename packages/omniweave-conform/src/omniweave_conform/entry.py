"""The `omniweave.eval` entry points: what `ow eval <verb>` calls in this distribution. **D833.**

D833 is `publish`; D840 adds `release_check`.

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

import tomllib
from pathlib import Path

from omniweave_core.errors import QualityError
from omniweave_core.store.oweval import open_oweval

from omniweave_conform import release, scoreboard

__all__ = ["publish", "release_check"]


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
