"""13:1306's admission: is a `DegradeCause.fix` an `ow` Action, with that Action's parameters? D869.

13-quality.md:1306 has the absence suite's harness parse each emitted fix *"against the `ow`
Action registry"* before running it, so a cause whose fix names no runnable verb fails its pair
rather than being executed. The harness is `omniweave_conform.absence`, which may not import this
distribution (`tools/layers.toml`), so `ow eval run --suite absence` hands it this function, and
`tools/ow_damage.py` does too. It moved here from that script unchanged.

Three checks, each one 13:1306 names:
- the words resolve through `surface.registry.resolve_cli` to a verb, an argument or a bare root,
  and never to `no-such-root`, `no-such-verb`, `absent` or `unrostered`;
- the root is one this build dispatches (`omniweave.__main__.DISPATCHED`), so it runs;
- the whole argv parses under the generated CLI tree, so every flag is that Action's.
"""

from __future__ import annotations

import contextlib
import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["admit"]


def admit(argv: Sequence[str]) -> str | None:
    """`None` if `ow <argv>` names a runnable Action with that Action's parameters, else why not."""
    from omniweave.__main__ import DISPATCHED  # noqa: PLC0415
    from omniweave.cli import build_parser  # noqa: PLC0415
    from omniweave.surface.registry import resolve_cli  # noqa: PLC0415

    words = [word for word in argv[1:] if not word.startswith("-")]
    status = resolve_cli(words[:2])
    if status not in {"verb", "argument", "bare"}:
        return f"`{' '.join(words[:2])}` resolves as {status}, not as an Action"
    if words[0] not in DISPATCHED:
        return f"`ow {words[0]}` is an Action this build does not run"
    sink = io.StringIO()
    try:
        with contextlib.redirect_stderr(sink):
            build_parser().parse_args(list(argv[1:]))
    except SystemExit:
        return f"the parameters are not the Action's: {sink.getvalue().strip()}"
    return None
