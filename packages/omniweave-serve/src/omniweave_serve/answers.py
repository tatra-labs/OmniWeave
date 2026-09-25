"""The three `tools/call` result shapes both retrievers share. 10:920.

`ow_query` and `ow_open` answer every outcome with `isError: false`, and in one of three shapes:
the Answer document, an Answer carrying only `ow:blocking`, or a one-line text refusal. They are
here, and not in either tool's module, because both tools produce all three and a second copy of
the refusal line is a second place its format can drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from omniweave_core.answer import Answer, render

if TYPE_CHECKING:
    from pathlib import Path

    from omniweave_core.errors import OwError

__all__ = ["blocked", "refusal", "text_result", "unreadable"]


def text_result(text: str) -> dict[str, Any]:
    """A `tools/call` result: one text content block, never `isError` (10:920)."""
    return {"content": [{"type": "text", "text": text}], "isError": False}


def refusal(code: str, message: str, fix: str) -> dict[str, Any]:
    """10:920's *"text refusal"* shape: one line, the code, and the command that clears it."""
    prefix = f"{code}: " if code else ""
    return text_result(f"ow: {prefix}{message}. Fix: {fix}")


def blocked(corpus: str, code: str, message: str, fix: str) -> dict[str, Any]:
    """An Answer carrying only `ow:blocking` -- 10:920's success shape for a recoverable condition.

    `degraded` is the state: nothing was read, and the one Verdict state that says so is the one
    that is never citable as absence.
    """
    answer = Answer(
        state="degraded",
        corpus=corpus,
        generation=0,
        freshness="unknown",
        blocking=(f"> {message}. Fix: `{fix}` [{code}]",),
        trailer_extra=(("verdict.gates", "[]"),),
    )
    return text_result(render(answer))


def unreadable(corpus: str, path: Path, error: OwError) -> dict[str, Any]:
    """10:920's third row: the corpus is declared and its store cannot be read."""
    return blocked(corpus, "OW-A-002", f"{path} is not readable: {error}", "ow doctor")
