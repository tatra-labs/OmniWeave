"""The one text wrapper artefacts 6 and 7 share. `omniweave.gen.wrap`.

It has its own module because it has two consumers. The property worth testing is the one
`textwrap` does not have and the reason this function exists at all: a backtick span survives the
wrap, because both artefacts are read by an agent that will grep them for a command.
"""

from __future__ import annotations

import ast
from pathlib import Path

import omniweave.gen.wrap as wrap_module
from omniweave.gen.wrap import tokens, wrapped


def test_a_code_span_with_spaces_is_one_token() -> None:
    assert tokens("run `ow surface emit` now") == ["run", "`ow surface emit`", "now"]
    assert tokens("plain words only") == ["plain", "words", "only"]


def test_punctuation_stays_attached_to_the_span_it_follows() -> None:
    """The join is over space-split pieces and never over characters, so a trailing comma or
    full stop travels with its span instead of opening the next line."""
    assert tokens("use `ow add`, then `ow query`.") == ["use", "`ow add`,", "then", "`ow query`."]


def test_an_unclosed_span_absorbs_the_rest_of_the_line() -> None:
    """Stated in the docstring and asserted here, because the alternative is guessing where the
    writer meant it to close."""
    assert tokens("a `b c d") == ["a", "`b c d"]


def test_a_span_never_straddles_a_line_break() -> None:
    text = "padding " * 9 + "`ow surface emit --check` and more words after it"
    for line in wrapped(text, width=40):
        assert line.count("`") % 2 == 0, line


def test_a_token_wider_than_the_column_is_not_broken() -> None:
    """A path split across two lines stops being greppable, so the line runs over instead."""
    path = "packages/omniweave/src/omniweave/surface/registry.py"
    lines = wrapped(f"edit {path} now", width=20)
    assert any(path in line for line in lines)


def test_the_indent_opens_every_line_but_the_first() -> None:
    lines = wrapped("one two three four five six seven eight", width=16, indent="    ")
    assert not lines[0].startswith(" ")
    assert all(line.startswith("    ") for line in lines[1:])
    assert len(lines) > 1, "the width has to force a wrap or this proves nothing"


def test_the_text_survives_the_round_trip() -> None:
    """Whatever the wrap does to line boundaries, no word is lost or duplicated."""
    text = "the quick `brown fox` jumps over the lazy dog and keeps going for a while"
    assert " ".join(line.strip() for line in wrapped(text, width=24)) == text


def test_a_short_text_is_one_line() -> None:
    assert wrapped("short", width=40) == ["short"]


def test_the_wrapper_reads_no_clock_no_environment_and_no_file() -> None:
    """10:229's ban. It is imported by two renderers, so its purity is theirs."""
    tree = ast.parse(Path(wrap_module.__file__).read_text(encoding="utf-8"))
    banned = {"time", "random", "secrets", "os", "datetime", "pathlib", "textwrap"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & banned
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in banned, node.module
