"""Generate ``tools/config_axes.toml`` from the ``omniweave_core.config`` declaration sites.

``tools/config_axes.toml`` is T-GENERATED: never hand-written, byte-identical to this module's
output, and byte-diff gated by G18 (``tools/gate_config_axes.py``). Its input is the ONE registry
that already holds every fact it carries -- ``omniweave_core.config.KEYS``, whose ``ConfigKey``
docstring says outright that "the registry of these is what ``tools/config_axes.toml`` is generated
from and G18 byte-diffs" (02-architecture.md section 8.4; section 8.3 for "generated into
``tools/config_axes.toml``, committed, and byte-diff gated").

Two facts per key, not one. 02-architecture.md section 8.2 rules that a key's ``OMNIWEAVE_*`` twin
is "declared, not derived" and is "emitted into ``tools/config_axes.toml``", so "the same G18 byte
diff therefore covers both, and a key with no twin fails CI". Hence the ``[env]`` table beside the
two axis lists: without it the twin has no gated home, and ``[serve] listed`` ->
``OMNIWEAVE_MCP_LISTED``, which no mechanical rule produces, could rot unnoticed.

Bytes, not text. Every line ends ``\\n`` and the file is written in binary, because a Windows
checkout that translated the endings would fail G18's byte diff against a Linux CI run for a reason
that has nothing to do with configuration (11-repo-layout.md section 5.2's generated-file
discipline). ``render()`` returns the text; ``main()`` is the only writer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from omniweave_core.config import KEYS, ConfigKey

__all__ = ["OUTPUT_PATH", "main", "render"]

REPO: Final[Path] = Path(__file__).resolve().parents[1]
OUTPUT_PATH: Final[Path] = REPO / "tools" / "config_axes.toml"

# charter.md's `tools/config_axes.toml` header block, transcribed rather than paraphrased: it is
# both the specification of this file's shape and the statement of the properties G18 checks, and a
# reader deciding an axis must find the rule inside the file the decision is recorded in. The KEY
# ENUMERATION paragraph is ADR-3 decision 3's, which the same block "gains, beside the glob-arity
# paragraph"; without it "covers omniweave.toml.example EXACTLY" is not decidable, because tomllib
# cannot tell an inline table from a sub-table and the answer flips on which it is.
_CHARTER_HEADER: Final[str] = """\
# tools/config_axes.toml — GENERATED from omniweave_core.config declarations, committed,
# byte-diff gated (G18). AN UNCLASSIFIED KEY FAILS CI and is treated at runtime as `semantic`
# (FAIL EXPENSIVE, NEVER WRONG). semantic_digest = sha256_canonical(the semantic projection).
#
# GLOB ARITY, STATED SO COVERAGE CAN BE EVALUATED AT ALL:
#   `*`  matches EXACTLY ONE key segment.       `drivers.*.config` matches `drivers."x.y".config`.
#   `**` matches ONE OR MORE segments.          `runtime.**` matches `runtime.claim.batch`.
#   An EXPLICIT key beats a glob. TWO GLOBS matching one key is a G18 FAILURE, not a precedence
#   puzzle. G18 additionally asserts that the union of the two lists covers every key in
#   `omniweave.toml.example` EXACTLY — neither over nor under — which is the assertion that was
#   missing while sixteen keys of the shipped config matched no pattern at all.
#
# KEY ENUMERATION, so "covers omniweave.toml.example EXACTLY" is decidable (ADR-3 decision 3):
#   An INLINE TABLE is ONE key: `drivers.max_workers = {free=4,...}` is the key
#   `drivers.max_workers`, not three. A key quoted because it holds dots is ONE
#   SEGMENT: `[drivers."parse.pdf.pdfium"] config` matches `drivers.*.config`.
#
# THE CLASSIFICATION RULE, so a reader can check a row rather than trust it:
#   A key is `semantic` IFF changing it can change the CONTENT of a produced row for a driver whose
#   identity, schema_version and config are unchanged. Everything else is `operational`.
#   WHICH DRIVER RUNS IS ALREADY IN THE KEY — `producer.operator`, `schema_version`,
#   `code_fingerprint`, `options_digest` — so an ALLOWLIST that merely selects among drivers is
#   `operational`. Classifying `drivers.enabled` as semantic would re-bill an entire corpus every
#   time an operator enabled an unrelated driver, which is the failure this axis exists to prevent,
#   pointed the other way.
"""

# Why the emitted list is finer than the charter's sixty patterns. The charter block was written by
# hand, so it wrote coarse globs. This file is generated from the declaration sites, where EVERY key
# carries its own axis, so a glob survives only where the declared KEY is a glob. Exactly one
# classification moves under the finer grain -- `store.retain_parts`, which the charter's `store.**`
# swept into `operational` and which 18-api-sketch.md section 4's Axis column marks semantic in its
# own row. It is semantic under the rule: `never` makes `quote = 'verbatim'` unreachable (INV-10),
# which changes what a produced row can say.
_GRAIN_NOTE: Final[str] = """\
#
# ONE PATTERN PER DECLARATION SITE. A glob appears below only where the declared KEY is a glob
# (`corpora.*.path`, `services.*.model_id`, `drivers.*.config`, `drivers.resolve.*`); charter.md's
# coarse `store.**` / `runtime.**` / `serve.**` / `observe.**` are expanded into the keys they stood
# for, which is what lets `store.retain_parts` carry the `semantic` axis its own row in
# 18-api-sketch.md section 4 gives it. The classification rule above is unchanged by the grain.
"""

# The trailing comment on each axis header, charter.md's wording. `[semantic]` feeds two consumers
# and `[operational]` must feed neither, and saying so on the header line is what stops a reviewer
# reading the second list as "the leftovers".
_AXIS_COMMENT: Final[dict[str, str]] = {
    "semantic": "    # enters cache keys AND sets the full-scan latch",
    "operational": " # NEVER enters a cache key. Changing these must not cost a dollar.",
}

_ENV_NOTE: Final[str] = """\
# THE DECLARED TWIN, one row per pattern above. 02-architecture.md section 8.2: a twin is DECLARED,
# NOT DERIVED -- `[serve] listed` twins as `OMNIWEAVE_MCP_LISTED`, which no mechanical `section_key`
# rule produces -- and it is emitted here so THE SAME G18 BYTE DIFF COVERS BOTH. A KEY WITH NO TWIN
# FAILS CI. A glob pattern's twin carries one `*` per glob segment: that is the slot
# `ConfigKey.env_for()` substitutes an instance name into, and an arity mismatch is a G18 failure.\
"""


def _rows(axis: str) -> tuple[ConfigKey, ...]:
    """Declaration order, filtered by axis. Registry order keeps the byte diff stable and legible.

    Sorting instead would scatter the sections a reader checks a row against; the registry is
    already written in `omniweave.toml` section order, so declaration order IS file order.
    """
    return tuple(spec for spec in KEYS.values() if spec.axis == axis)


def _axis_block(axis: str) -> str:
    lines = [f"[{axis}]{_AXIS_COMMENT[axis]}", "keys = ["]
    lines += [f'  "{spec.name}",' for spec in _rows(axis)]
    lines.append("]")
    return "\n".join(lines)


def render() -> str:
    """The complete file text, newline-terminated. The single source of the committed bytes."""
    semantic, operational = _rows("semantic"), _rows("operational")
    counted = (
        f"#\n# {len(KEYS)} patterns from the omniweave_core.config registry: "
        f"{len(semantic)} semantic, {len(operational)} operational.\n"
    )
    env_block = "\n".join(f'"{spec.name}" = "{spec.env}"' for spec in KEYS.values())
    blocks = [
        _CHARTER_HEADER + _GRAIN_NOTE + counted,
        _axis_block("semantic"),
        _axis_block("operational"),
        "[env]\n" + _ENV_NOTE + "\n" + env_block,
    ]
    return "\n".join(blocks) + "\n"


def _self() -> str:
    return f"tools/{Path(__file__).name}"


def main(argv: list[str] | None = None) -> int:
    """``--check`` byte-diffs the committed file and writes nothing; no flag rewrites it."""
    args = list(sys.argv[1:] if argv is None else argv)
    want = render().encode("utf-8")
    if args == ["--check"]:
        if not OUTPUT_PATH.exists():
            sys.stdout.write(f"G18: {OUTPUT_PATH} is not committed; run `uv run {_self()}`\n")
            return 1
        have = OUTPUT_PATH.read_bytes()
        if have != want:
            sys.stdout.write(
                f"G18: {OUTPUT_PATH} is {len(have)} bytes and the generator emits {len(want)}; "
                f"it is GENERATED, so run `uv run {_self()}` rather than editing it\n"
            )
            return 1
        sys.stdout.write(f"G18: {OUTPUT_PATH} matches the generator ({len(want)} bytes)\n")
        return 0
    if args:
        sys.stdout.write(f"usage: {_self()} [--check]\n")
        return 2
    OUTPUT_PATH.write_bytes(want)
    sys.stdout.write(f"wrote {OUTPUT_PATH} ({len(want)} bytes)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
