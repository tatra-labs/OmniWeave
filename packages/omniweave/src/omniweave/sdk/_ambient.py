"""The SDK's one ambient read: the process's working directory. D858.

`omniweave.corpus()` is an entry point, as `__main__.py` is: it is where a user's process meets the
library, and 18:154 prints it with no directory argument. Library code may not read the process's
directory (G8's `omniweave-no-getcwd-in-library-code`, OUT14), so `sdk.api` takes a `cwd` and asks
this module only when the caller gave none. G8 exempts this file and `__main__.py`, and nothing
else, so the exemption has exactly one site to review.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["process_cwd"]


def process_cwd() -> Path:
    """The process's current directory, read when a caller of `omniweave.corpus()` named none."""
    return Path.cwd()
