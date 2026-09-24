"""The tier rule, 10:1185-1188 verbatim: one core skill, and nothing else is core.

10:1195: *"a retrieval-only session pays for one 150-line skill and nothing else."* The rule is
a name comparison and not a pattern, because hyperframes' pattern (`hyperframes-*` plus
`media-use`) is how a core tier grows without anyone deciding it should.
"""

from __future__ import annotations

from typing import Final

__all__ = ["CORE", "is_core"]

CORE: Final = "omniweave"
"""The entry router, `skills/omniweave/` (10:1151)."""


def is_core(name: str) -> bool:
    """AND NOTHING ELSE (10:1188)."""
    return name == CORE
