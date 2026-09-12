"""Generate ``tools/events.toml`` from the ``omniweave_core.events`` declaration sites.

``tools/events.toml`` is T-GENERATED (02-architecture.md section 2 row 50): "never hand-written;
byte-identical to its generator's output", byte-diff gated by G20 (``tools/gate_events.py``). Its
input is the one registry that already holds every fact it carries -- ``omniweave_core.events
.EVENTS``, declared in append order, with ``level`` a required field so a row cannot exist without
one.

Which direction, and why this one
---------------------------------
Row 50's does-NOT column offers two shapes for this family of files: "each is either append-only
against the previous tag **or** generated from a declaration site". ``codes.toml`` takes the first;
``config_axes.toml`` takes the second and this file is its twin, for two reasons argued at length in
``omniweave_core/events.py``'s own docstring and summarised here so a reader of the generator does
not have to open the module:

1. ``tools/`` ships in no wheel (11-repo-layout.md section 2.6 enumerates the five kinds of packaged
   file and this is not one), so a vocabulary the runtime loaded from here would be absent from
   every install.
2. 15-observability.md:341 makes ``level`` required on every row. A required dataclass field is a
   ``TypeError`` at import; a gate is a failure in CI an hour later.

The append-only PROPERTY is untouched and is exactly what G20 checks: declaration order is append
order, a row is never removed, and a ``kind`` is never reused.

Bytes, not text
---------------
``render()`` returns the text and ``main()`` is the only writer, through ``write_bytes``: a Windows
checkout that translated the line endings would fail G20's byte diff against a Linux CI run for a
reason that has nothing to do with the vocabulary. ``gen_config_axes.py`` states the same rule and
this file follows it rather than restating the argument.

Specified in 15-observability.md section 3.1, _notes/charter.md:4456-4620, 02-architecture.md
section 2 rows 21 and 50, and 16-roadmap.md:548 (P4 W4.8).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from omniweave_core.events import EVENT_ORDER, EVENTS, Level

__all__ = ["OUTPUT_PATH", "main", "render"]

REPO: Final[Path] = Path(__file__).resolve().parents[1]
OUTPUT_PATH: Final[Path] = REPO / "tools" / "events.toml"

# charter.md:4456-4461's header block, transcribed rather than paraphrased, plus the two sentences
# this generator owes a reader: that the file is now generated, and from where. The charter's own
# note about "a real TOML shape and not a list of bare dotted words" is kept because it is the
# reason the file has `[[event]]` tables at all.
_HEADER: Final[str] = """\
# tools/events.toml — CLOSED, APPEND-ONLY, byte-diff gated (G20).
# GENERATED from omniweave_core.events._DECLARATIONS; run `uv run tools/gen_events.py`.
# 02-architecture.md:274 allows this family to be "either append-only against the previous tag or
# generated from a declaration site"; this one is generated, because `tools/` ships in no wheel
# (11-repo-layout.md section 2.6) and a runtime that loaded its vocabulary from here would have
# none. The append-only PROPERTY is unchanged and G20 is what checks it.
#
# schema/event-v1.json is GENERATED from the same declarations, so this file needs a real TOML shape
# and not a list of bare dotted words — which parses as nothing and left the D6 ADR's author to
# invent one.
# `fields` names the event-specific keys carried in `Event.fields`; every event ALSO carries the
# envelope (`ts_wall_ns`, `ts_mono_ns`, `run_id`, `writer_id`, `seq`, trace ids, `phase`, `level`,
# `unit`, `part`, `operator`, `driver`). A row is never removed and `kind` is never reused.
#
# `level` is REQUIRED on every row (15-observability.md:341) and is declared per kind, never chosen
# at a call site. `span` and `phase` appear only on the ten rows that carry a span BOUNDARY; the
# other rows are points and name neither.
"""


def _counts() -> str:
    per_level = {
        level.value: sum(1 for spec in EVENTS.values() if spec.level is level) for level in Level
    }
    tally = ", ".join(f"{count} {name}" for name, count in per_level.items())
    spans = sum(1 for spec in EVENTS.values() if spec.span is not None)
    return (
        f"#\n# {len(EVENT_ORDER)} rows in append order: {tally}. {spans} carry a span boundary.\n"
    )


def _fields(names: tuple[str, ...]) -> str:
    if not names:
        return "[]"
    return "[" + ", ".join(f'"{name}"' for name in names) + "]"


def _row(kind: str) -> str:
    spec = EVENTS[kind]
    lines = [
        "[[event]]",
        f'kind = "{spec.kind.value}"',
        f'level = "{spec.level.value}"',
        f"fields = {_fields(spec.fields)}",
    ]
    if spec.span is not None:
        lines.append(f'span = "{spec.span}"')
        lines.append(f'phase = "{spec.phase.value}"')
    return "\n".join(lines)


def render() -> str:
    """The complete file text, newline-terminated. The single source of the committed bytes."""
    body = "\n".join(_row(kind) for kind in EVENT_ORDER)
    return _HEADER + _counts() + body + "\n"


def _self() -> str:
    return f"tools/{Path(__file__).name}"


def main(argv: list[str] | None = None) -> int:
    """``--check`` byte-diffs the committed file and writes nothing; no flag rewrites it."""
    args = list(sys.argv[1:] if argv is None else argv)
    want = render().encode("utf-8")
    if args == ["--check"]:
        if not OUTPUT_PATH.exists():
            sys.stdout.write(f"G20: {OUTPUT_PATH} is not committed; run `uv run {_self()}`\n")
            return 1
        have = OUTPUT_PATH.read_bytes()
        if have != want:
            sys.stdout.write(
                f"G20: {OUTPUT_PATH} is {len(have)} bytes and the generator emits {len(want)}; "
                f"it is GENERATED, so run `uv run {_self()}` rather than editing it\n"
            )
            return 1
        sys.stdout.write(f"G20: {OUTPUT_PATH} matches the generator ({len(want)} bytes)\n")
        return 0
    if args:
        sys.stdout.write(f"usage: {_self()} [--check]\n")
        return 2
    OUTPUT_PATH.write_bytes(want)
    sys.stdout.write(f"wrote {OUTPUT_PATH} ({len(want)} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
