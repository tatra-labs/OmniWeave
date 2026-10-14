"""The `omniweave.eval` entry points: what `ow eval <verb>` calls in this distribution. **D833.**

10-interfaces.md section 2.5: *"`omniweave-conform` implements the `eval` Action group"*, and
the split between the two distributions is a dispatch fact. `omniweave` may not import this
package (`tools/layers.toml`), so `omniweave.surface.dispatch.eval_entry()` loads each function
here by its entry-point name at call time, as it loads `ow serve`'s.

**Only builtin values cross**, as across `ow serve`'s boundary. A type defined on either side is
one the other side cannot import, so arguments are `str` and `bool`, and the result is a `dict` of
`str`, `int`, `bool` and lists of `str`. The CLI builds its own report from that.

**Paths arrive absolute.** The CLI resolves each against its working directory, so this side
never reads one.

Specified in 10-interfaces.md section 2.5 and 13-quality.md sections 11.1 and 13.3.
"""

from __future__ import annotations

from pathlib import Path

from omniweave_conform import scoreboard

__all__ = ["publish"]


def publish(*, oweval: str, results: str, check: bool) -> dict[str, object]:
    """`ow eval publish`: `scoreboard.publish()` over two absolute paths, as builtins."""
    done = scoreboard.publish(Path(oweval), Path(results), check=check)
    return {
        "files": list(done.files),
        "rows": done.rows,
        "changed": list(done.changed),
        "written": done.written,
    }
