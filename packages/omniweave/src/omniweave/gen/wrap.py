"""The one text wrapper the Markdown artefacts share. 10:229's purity, and INV-21's one home.

Two renderers produce prose: `agents.py` (artefact 6) and `skill_catalog.py` (artefact 7). Both
wrap at a column, both indent a continuation line, and both are read by an agent that will GREP
them for the command it is about to run. Written twice that would be two homes for one behaviour,
and the second copy is the one that stops matching the first.

`llms.py` has its own `_wrapped()` and keeps it, which is not an exception to the rule: LEANN's
grammar is *"a line that does not start in column one continues the one before it"* with a
two-space continuation and no indent parameter, and 10:2431 makes that grammar the artefact's
contract rather than its formatting. A shared function with a mode switch would be one home for
two contracts, which is the same defect wearing the other hat.

## WHY NOT `textwrap`

`textwrap.wrap()` splits on whitespace, so `` `ow surface emit --check` `` becomes `` `ow surface ``
at the end of one line and `` emit --check` `` at the start of the next. That renders correctly and
greps wrong, and both artefacts that use this module are read by something that greps. `tokens()`
keeps a backtick span whole, which `textwrap` has no parameter for.
"""

from __future__ import annotations

__all__ = ["tokens", "wrapped"]


def tokens(text: str) -> list[str]:
    """One paragraph split into the units a wrap may break between. A code span is one unit.

    The rule is the backtick count. A piece whose running text has an odd number of backticks is
    inside a span, so the next piece joins it. Punctuation stays attached because the join is over
    the space-split pieces and never over characters.

    An unclosed span at the end of the text absorbs the rest of the line, which is correct: the
    alternative is guessing where the writer meant it to close.
    """
    out: list[str] = []
    for piece in text.split(" "):
        if out and out[-1].count("`") % 2:
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def wrapped(text: str, *, width: int, indent: str = "") -> list[str]:
    """`text` wrapped at `width`, with `indent` opening every line after the first.

    A token wider than `width` is never broken -- a path or a dotted symbol split across two lines
    stops being greppable -- so a line over the column happens and is correct.

    `indent` is what a Markdown list item and a label block both need: a continuation line in
    column one ends the item in the first case and reads as a new label in the second.
    """
    parts = tokens(text)
    lines: list[str] = []
    current = parts[0]
    for token in parts[1:]:
        candidate = f"{current} {token}"
        if len(candidate) > width:
            lines.append(current)
            current = f"{indent}{token}"
        else:
            current = candidate
    lines.append(current)
    return lines
