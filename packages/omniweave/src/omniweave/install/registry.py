"""The registry 10:1628 means by *"one registry row"*: a target id and the class that serves it.

10:1663: an unknown id *"raises with the known list in the message"*. Two lists, because two are
true: the seven ids 10:1632 declares, and the ones built. An id that is declared but not yet built
is not *unknown* -- it is a host this release names and cannot yet write -- and saying so is the
difference between *"did you mistype?"* and *"not yet"*.

`--target`'s four resolutions (`auto`, `all`, `none`, a CSV list; 10:1662) are the verb's, which
needs detection across every built target; this is the table they resolve against.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave.install.claude_code import ClaudeCode
from omniweave.install.types import TARGET_IDS

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from omniweave.install.engine import HostEnv
    from omniweave.install.types import AgentTarget, TargetId

__all__ = ["BUILT", "TARGETS", "build"]

TARGETS: Final[Mapping[TargetId, Callable[[HostEnv], AgentTarget]]] = {
    "claude-code": ClaudeCode,
}

BUILT: Final[tuple[TargetId, ...]] = tuple(one for one in TARGET_IDS if one in TARGETS)
"""The built ids, in 10:1632's order."""


def build(target: str, env: HostEnv) -> AgentTarget:
    """The target for `target`; `ValueError` naming the known ids, or saying it is not built."""
    factory = TARGETS.get(target)  # type: ignore[call-overload]
    if factory is not None:
        return factory(env)
    if target in TARGET_IDS:
        raise ValueError(
            f"target {target!r} is declared (10:1632) but not built yet; built: {', '.join(BUILT)}"
        )
    raise ValueError(f"unknown target {target!r}; known: {', '.join(TARGET_IDS)}")
