"""The configuration model: the six-layer precedence chain, flat scalar coercion, per-value
source tracking, and each key's ``semantic``/``operational`` axis plus its ``OMNIWEAVE_*`` twin.

Specified in 02-architecture.md sections 8.1-8.4 (the layered model, the schema, the axis, and the
printed ``Config`` type) and 18-api-sketch.md section 4 (the key table). Stdlib only, by contract:
the value grammar is finite and NON-RECURSIVE, which is what keeps coercion at ~250 property-tested
lines and makes "JSON-canonicalisable by contract" checkable -- there is no ``str()`` fallback and
no un-canonicalisable value survives ``load()`` (charter I12).

This module does NOT validate a *driver's* config table: that is the closed JSON-Schema-2020-12
subset validator in ``omniweave`` and ``omniweave-conform``, off the hot path
(02-architecture.md section 2 row 8). A driver's ``[config]`` table is preserved verbatim here.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import posixpath
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path, PurePosixPath
from typing import Final, Literal, TypeAlias

__all__ = [
    "CONFIG_AXES",
    "CONFIG_KINDS",
    "CONFIG_SCHEMA",
    "COST_CLASSES",
    "ENV_OVERRIDES",
    "ENV_PREFIX",
    "KEYS",
    "NON_KEY_ENV_VARS",
    "REQUIRED",
    "SHIPPED_DRIVERS",
    "SHIPPED_PASSES",
    "Config",
    "ConfigAxis",
    "ConfigError",
    "ConfigKey",
    "ConfigKind",
    "ConfigLayer",
    "ConfigSource",
    "ConfigValue",
    "Inherit",
    "Scalar",
    "coerce",
    "default_env_name",
    "env_name_of",
    "flatten",
    "join_key",
    "key_of_env_name",
    "load",
    "resolve_key",
    "scan_lines",
    "split_key",
]

# --------------------------------------------------------------------------------------------
# Cross-module seams. `errors.py` is W1.3 and `canonical.py` is W1.2 (16-roadmap.md section 4);
# both are eager modules of this same distribution. Until they land, the two shims below stand in
# with EXACTLY the signature and the recipe those documents print, so no caller and no test sees
# a different shape when they arrive. Reported as a deviation.
# --------------------------------------------------------------------------------------------
try:  # pragma: no cover - which branch runs depends on whether W1.3 has landed
    from omniweave_core.errors import ConfigError
except ImportError:  # pragma: no cover - bootstrap until W1.3

    class ConfigError(Exception):  # type: ignore[no-redef]
        """``OW-C-*``: a configuration or startup failure, raised ONLY during resolution.

        The two-level tree and this constructor are printed in 18-api-sketch.md section 0.3;
        ``fix`` is THE EXACT COMMAND THAT CLEARS IT and an empty one raises ``ValueError``.
        """

        SYMBOL: str = "OW_CONFIG"
        EXIT: int = 1

        def __init__(self, message: str, *, symbol: str | None = None, fix: str) -> None:
            if not fix:
                raise ValueError("an OwError names the exact command that clears it")
            super().__init__(message)
            self.fix = fix
            self._symbol = symbol or self.SYMBOL

        def code(self) -> str:
            return self._symbol

        def is_fatal(self) -> bool:
            return True


def _sha256_canonical(obj: object) -> str:
    """``sha256(canonical(obj))`` as 64-char hex (glossary.md; 02-architecture.md section 8.3).

    Delegates to ``omniweave_core.canonical`` once it exists (module row 3 owns the encoding).
    The inline recipe is the one 02-architecture.md section 8.3 states -- sorted keys, no
    whitespace, ``allow_nan=False`` -- and is replaced by the import when W1.2 lands.
    """
    try:  # pragma: no cover - exercised once canonical.py lands
        from omniweave_core.canonical import sha256_canonical
    except ImportError:  # pragma: no cover - bootstrap until W1.2
        blob = json.dumps(
            obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()
    return sha256_canonical(obj)


# --------------------------------------------------------------------------------------------
# The value grammar (02-architecture.md section 8.4). Four shapes, non-recursive.
# --------------------------------------------------------------------------------------------

Scalar: TypeAlias = str | int | float | bool | None
ConfigValue: TypeAlias = (
    Scalar  # int - float - str - bool - path - enum
    | tuple[Scalar, ...]  # list[str] - list[enum]         e.g. `drivers.enabled`
    | tuple[tuple[Scalar, ...], ...]  # THE ONE NESTED SHAPE: `serve.packing.tier`
    | Mapping[str, Scalar]  # table[str, int|float|Scalar]  e.g. `budget.max_inflight`
)

ConfigAxis: TypeAlias = Literal["semantic", "operational"]
CONFIG_AXES: Final[tuple[ConfigAxis, ...]] = ("semantic", "operational")

ConfigKind: TypeAlias = Literal[
    "str", "int", "float", "bool", "path", "enum", "list", "table", "matrix", "str_or_list"
]
CONFIG_KINDS: Final[tuple[ConfigKind, ...]] = (
    "str",
    "int",
    "float",
    "bool",
    "path",
    "enum",
    "list",
    "table",
    "matrix",
    "str_or_list",
)

CONFIG_SCHEMA: Final[int] = 1
"""``schema = 1`` is line 1 of ``omniweave.toml``; a newer value refuses at startup."""

ENV_PREFIX: Final[str] = "OMNIWEAVE_"

NON_KEY_ENV_VARS: Final[frozenset[str]] = frozenset(
    {
        "OMNIWEAVE_HOME",
        "OMNIWEAVE_ENFORCE",
        "OMNIWEAVE_HOOK_TTL",
        "OMNIWEAVE_API_KEY",
        "OMNIWEAVE_PROBE_EPOCH",
    }
)
"""The ``OMNIWEAVE_*`` variables the framework reads that are NOT config keys.

``OMNIWEAVE_HOME`` is the state root; ``OMNIWEAVE_ENFORCE`` and ``OMNIWEAVE_HOOK_TTL`` gate hook
behaviour; ``OMNIWEAVE_API_KEY`` is the ``--api-key`` twin -- a flag's environment form;
``OMNIWEAVE_PROBE_EPOCH`` is the probe cache's manual invalidator.

**Five, where 18-api-sketch.md section 4 enumerates four.** That section says "Three env vars that
are not config keys" and then names ``OMNIWEAVE_API_KEY`` as "the fourth"; it does not reach
``OMNIWEAVE_PROBE_EPOCH``, which 04-driver-system.md section 4.7 reads inside ``env_digest`` (":
``int(os.environ.get("OMNIWEAVE_PROBE_EPOCH", "0"))``") and which the glossary's ``env_digest`` row
carries as a digest component. It twins no key -- all 126 declared keys are checked against it -- so
a set of four would leave one ``OMNIWEAVE_*`` name the framework reads belonging to neither
population, and any gate asserting that partition is total would fail on it. The membership follows
what the framework reads; 18 section 4's count is the stale side and is recorded as such.
"""

CONTROL_DIR: Final[str] = ".omniweave"
"""The per-project control directory, which the default Scope excludes (05-ingest-and-routing.md
section 3: ``exclude = [..., "**/.omniweave/**", ...]``)."""


class ConfigLayer(IntEnum):
    """Precedence, lowest first.

    02-architecture.md section 8.1's numbered list orders the FILE chain; ``ENV`` sits above all
    of it, because the declared twins are "applied over the file layers".
    """

    BUILTIN = 0  # the `ConfigKey.default`s below
    USER_FILE = 1  # $OMNIWEAVE_HOME/config.toml  (default ~/.omniweave)
    PYPROJECT = 2  # [tool.omniweave], ONLY when no omniweave.toml was found
    PROJECT_FILE = 3  # ./omniweave.toml, walking up to .git or the filesystem root
    EXPLICIT_FILE = 4  # --config <path>
    ENV = 5  # the DECLARED OMNIWEAVE_* twin


FILE_LAYERS: Final[tuple[ConfigLayer, ...]] = (
    ConfigLayer.USER_FILE,
    ConfigLayer.PYPROJECT,
    ConfigLayer.PROJECT_FILE,
    ConfigLayer.EXPLICIT_FILE,
)


@dataclass(frozen=True, slots=True)
class ConfigSource:
    """Where ONE resolved value came from.

    ``ow show-config`` prints ``render()`` and nothing else (02-architecture.md section 8.4).
    """

    layer: ConfigLayer
    path: Path | None = None  # the file, for the three file layers; None otherwise
    line: int | None = None  # tomllib reports no line numbers, so the loader records each
    #                          key's line during its single raw scan
    env_var: str | None = None  # the twin that won, for ENV. DECLARED, never derived

    def render(self) -> str:
        """``'./omniweave.toml:141'`` - ``'OMNIWEAVE_MCP_LISTED'`` - ``'(built-in)'``."""
        if self.layer is ConfigLayer.ENV:
            return self.env_var or "(env)"
        if self.path is None:
            return "(built-in)"
        shown = self.path.as_posix()
        return shown if self.line is None else f"{shown}:{self.line}"


class _Required:
    """The sentinel for a key 18-api-sketch.md section 4 prints with a ``—`` default cell."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "REQUIRED"


REQUIRED: Final[_Required] = _Required()


@dataclass(frozen=True, slots=True)
class Inherit:
    """A default that is another key's resolved value: ``corpora.*.source`` <- ``roots.source``.

    18-api-sketch.md section 4 prints that cell as ``roots.source`` rather than a literal. The
    inheriting key keeps the ``ConfigSource`` of the key it came from, so ``ow show-config`` names
    the file and line an operator would actually have to edit.
    """

    from_key: str


Default: TypeAlias = ConfigValue | _Required | Inherit


# --------------------------------------------------------------------------------------------
# Dotted keys. A segment holding a dot is QUOTED and is ONE segment (ADR-3 decision 3's key
# enumeration rule): `drivers."parse.pdf.pdfium".config` is three segments, not five.
# --------------------------------------------------------------------------------------------


def split_key(dotted: str) -> tuple[str, ...]:
    """Split a dotted key into segments, honouring ``"..."`` quoting of a segment with dots."""
    segments: list[str] = []
    buf: list[str] = []
    quoted = False
    for ch in dotted:
        if ch == '"':
            quoted = not quoted
        elif ch == "." and not quoted:
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if quoted:
        raise ConfigError(
            f"unterminated quoted segment in config key {dotted!r}",
            symbol="OW_CONFIG_UNKNOWN_KEY",
            fix='quote a dotted segment as drivers."parse.pdf.pdfium".config',
        )
    segments.append("".join(buf))
    if any(seg == "" for seg in segments):
        raise ConfigError(
            f"empty segment in config key {dotted!r}",
            symbol="OW_CONFIG_UNKNOWN_KEY",
            fix="write the key as a dotted path with no empty segment",
        )
    return tuple(segments)


def join_key(segments: Sequence[str]) -> str:
    """Join segments into the canonical dotted form, quoting any segment that holds a dot."""
    return ".".join(f'"{s}"' if "." in s else s for s in segments)


def _match_segments(pattern: Sequence[str], key: Sequence[str]) -> bool:
    """Glob arity, from charter.md's ``tools/config_axes.toml`` header block.

    ``*`` matches EXACTLY ONE segment; ``**`` matches ONE OR MORE.
    """
    if not pattern:
        return not key
    head, rest = pattern[0], pattern[1:]
    if head == "**":
        return any(_match_segments(rest, key[take:]) for take in range(1, len(key) + 1))
    if not key:
        return False
    if head not in ("*", key[0]):
        return False
    return _match_segments(rest, key[1:])


def _env_segment(segment: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in segment).upper()


def default_env_name(name: str) -> str:
    """The mechanical twin: ``OMNIWEAVE_`` + the dotted key upper-cased, dots to underscores.

    02-architecture.md section 8.2 rules that the twin is DECLARED and not derived, because
    ``[serve] listed`` -> ``OMNIWEAVE_MCP_LISTED`` has no mechanical rule. This function is the
    default a declaration site may take, not a rule the loader applies: every ``ConfigKey.env``
    is still stored on the key, and ``ENV_OVERRIDES`` records the exceptions.
    """
    return ENV_PREFIX + "".join(ch if (ch.isalnum() or ch == "*") else "_" for ch in name).upper()


ENV_OVERRIDES: Final[Mapping[str, str]] = {
    # 02-architecture.md section 8.2: the twins no mechanical rule produces. Both are `[serve]`
    # keys whose published name says MCP rather than serve, and both are published to an agent:
    # 10-interfaces.md:780 tables them together as the two highest-precedence mechanisms, and
    # 10-interfaces.md:2466's `llms.txt` prints both names in one sentence. `serve.enabled` was
    # missing here until W7.2e, which meant `assert_sv1()`'s own fix string named a variable the
    # loader did not read; D327 is the entry.
    "serve.listed": "OMNIWEAVE_MCP_LISTED",
    "serve.enabled": "OMNIWEAVE_MCP_ENABLED",
}


@dataclass(frozen=True, slots=True)
class ConfigKey:
    """One key's DECLARATION SITE -- the single home of its axis and its twin.

    The registry of these is what ``tools/config_axes.toml`` is generated from and G18 byte-diffs
    (02-architecture.md section 8.4). ``axis`` is REQUIRED with no default, so an unclassified key
    is a ``TypeError`` at import rather than a CI finding -- decision (a).
    """

    name: str  # dotted; a segment may be `*` or `**` (`corpora.*.path`)
    kind: ConfigKind
    default: Default
    axis: ConfigAxis  # REQUIRED, no default
    env: str  # the declared twin, e.g. 'OMNIWEAVE_MCP_LISTED'
    choices: tuple[str, ...] = ()  # non-empty iff `kind` is 'enum', 'list' over an enum, or
    #                                'str_or_list' (whose string half is an enum)
    item_kind: ConfigKind | None = None  # the element coercer for 'list' - 'table' - 'matrix'

    def __post_init__(self) -> None:
        if self.axis not in CONFIG_AXES:
            raise TypeError(
                f"{self.name}: axis must be 'semantic' or 'operational', not {self.axis!r}"
            )
        if self.kind not in CONFIG_KINDS:
            raise TypeError(f"{self.name}: unknown ConfigKind {self.kind!r}")
        if self.item_kind is not None and self.item_kind not in CONFIG_KINDS:
            raise TypeError(f"{self.name}: unknown item ConfigKind {self.item_kind!r}")
        if not self.env.startswith(ENV_PREFIX):
            raise TypeError(f"{self.name}: the twin {self.env!r} must start with {ENV_PREFIX!r}")
        if self.kind == "enum" and not self.choices:
            raise TypeError(f"{self.name}: an 'enum' key declares its choices")
        if self.kind == "list" and self.item_kind is None:
            raise TypeError(f"{self.name}: a 'list' key declares its item_kind")
        if self.kind == "list" and self.item_kind == "enum" and not self.choices:
            raise TypeError(f"{self.name}: a list over an enum declares its choices")
        if self.kind not in ("enum", "list", "str_or_list") and self.choices:
            raise TypeError(f"{self.name}: choices are only meaningful for an enum-valued kind")
        globs = sum(1 for s in self.segments if s in ("*", "**"))
        # A `**` segment is ONE placeholder that happens to be spelled with two characters, so the
        # twin is checked against maximal runs of `*`, not against `*` characters. Counting
        # characters would reject the mechanically-derived twin of any `**` key.
        #
        # The check is deliberately this weak: 02-architecture.md:1213 rules that a twin is
        # "declared, not derived" -- `[serve] listed` twins as `OMNIWEAVE_MCP_LISTED`, which no
        # mechanical `section_key` rule produces. So arity is the only property a declared name
        # must still satisfy: a glob key's twin needs one slot per glob to name an instance.
        env_globs = sum(
            1 for i, ch in enumerate(self.env) if ch == "*" and (i == 0 or self.env[i - 1] != "*")
        )
        if env_globs != globs:
            raise TypeError(f"{self.name}: the twin {self.env!r} carries one * per glob segment")

    @property
    def segments(self) -> tuple[str, ...]:
        return split_key(self.name)

    @property
    def is_glob(self) -> bool:
        return "*" in self.name

    def matches(self, key: str) -> bool:
        """True iff this declaration governs the dotted key ``key``."""
        return _match_segments(self.segments, split_key(key))

    def env_for(self, key: str) -> str:
        """The concrete twin for one instance, e.g. ``OMNIWEAVE_CORPORA_HANDBOOK_PATH``."""
        if not self.is_glob:
            return self.env
        out = self.env
        for pattern_seg, key_seg in zip(self.segments, split_key(key), strict=False):
            if pattern_seg in ("*", "**"):
                out = out.replace("*", _env_segment(key_seg), 1)
        return out


# --------------------------------------------------------------------------------------------
# Coercion. Ten kinds, one coercer each; no `else` branch and no `str()` fallback (I12).
# --------------------------------------------------------------------------------------------


def _reject(key: str, raw: object, want: str) -> ConfigError:
    return ConfigError(
        f"{key}: expected {want}, got {type(raw).__name__} ({raw!r})",
        symbol="OW_CONFIG_VALUE",
        fix=f"set {key} to {want} in omniweave.toml, or remove it to take the default",
    )


def _not_canonicalisable(key: str, raw: float) -> ConfigError:
    return ConfigError(
        f"{key}: {raw!r} is not JSON-canonicalisable (allow_nan=False)",
        symbol="OW_CONFIG_VALUE",
        fix=f"set {key} to a finite number in omniweave.toml",
    )


def _as_scalar(key: str, raw: object) -> Scalar:
    """A verbatim Scalar: the ONE place a driver's own value passes through unclassified."""
    if raw is None or isinstance(raw, (str, bool, int)):
        return raw
    if isinstance(raw, float):
        if not math.isfinite(raw):
            raise _not_canonicalisable(key, raw)
        return raw
    raise _reject(key, raw, "a flat scalar (str, int, float, bool or null)")


def _as_bool(key: str, raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    raise _reject(key, raw, "a bool")


def _as_int(key: str, raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise _reject(key, raw, "an int")
    return raw


def _as_float(key: str, raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise _reject(key, raw, "a float")
    value = float(raw)
    if not math.isfinite(value):
        raise _not_canonicalisable(key, value)
    return value


def _as_str(key: str, raw: object) -> str:
    if isinstance(raw, str):
        return raw
    raise _reject(key, raw, "a str")


def _as_path(key: str, raw: object) -> str:
    """A path leaf is a STRING in the value grammar, normalised to forward slashes.

    ``Scalar`` has no ``Path`` member -- 02-architecture.md section 8.4 lists ``path`` among the
    scalar kinds -- and a ``Path`` is not JSON-canonicalisable. Normalising the separator is what
    keeps a Windows checkout and a POSIX one digesting identically.
    """
    text = _as_str(key, raw)
    if not text:
        raise _reject(key, raw, "a non-empty path")
    return PurePosixPath(text.replace("\\", "/")).as_posix()


def _as_enum(key: str, raw: object, choices: Sequence[str]) -> str:
    text = _as_str(key, raw)
    if text not in choices:
        raise ConfigError(
            f"{key}: {text!r} is not one of {', '.join(choices)}",
            symbol="OW_CONFIG_VALUE",
            fix=f"set {key} to one of: {' | '.join(choices)}",
        )
    return text


def _as_sequence(key: str, raw: object) -> Sequence[object]:
    if isinstance(raw, (list, tuple)):
        return raw
    raise _reject(key, raw, "a list")


def _as_mapping(key: str, raw: object) -> Mapping[str, object]:
    if isinstance(raw, Mapping) and all(isinstance(k, str) for k in raw):
        return raw
    raise _reject(key, raw, "a table with string keys")


_ELEMENT: Final[Mapping[str, object]] = {}


def _coerce_element(
    kind: ConfigKind | None, where: str, raw: object, choices: Sequence[str]
) -> Scalar:
    match kind:
        case "enum":
            return _as_enum(where, raw, choices)
        case "str":
            return _as_str(where, raw)
        case "int":
            return _as_int(where, raw)
        case "float":
            return _as_float(where, raw)
        case "bool":
            return _as_bool(where, raw)
        case "path":
            return _as_path(where, raw)
        case _:
            # `drivers.*.config` and `serve.packing.tier`: a cell is a verbatim Scalar, because
            # the first belongs to the driver and the second is heterogeneous by column.
            return _as_scalar(where, raw)


def coerce(spec: ConfigKey, raw: object, *, key: str | None = None) -> ConfigValue:
    """Coerce one raw TOML or env value to the declared shape, or raise ``ConfigError``.

    Ten kinds, one branch each, no ``else`` (02-architecture.md section 8.4). An
    un-canonicalisable value is a startup error (section 8.2).
    """
    name = key or spec.name
    match spec.kind:
        case "str":
            return _as_str(name, raw)
        case "int":
            return _as_int(name, raw)
        case "float":
            return _as_float(name, raw)
        case "bool":
            return _as_bool(name, raw)
        case "path":
            return _as_path(name, raw)
        case "enum":
            return _as_enum(name, raw, spec.choices)
        case "list":
            return tuple(
                _coerce_element(spec.item_kind, f"{name}[{n}]", element, spec.choices)
                for n, element in enumerate(_as_sequence(name, raw))
            )
        case "table":
            return {
                cell: _coerce_element(spec.item_kind, f"{name}.{cell}", value, spec.choices)
                for cell, value in _as_mapping(name, raw).items()
            }
        case "matrix":
            return tuple(
                tuple(
                    _coerce_element(spec.item_kind, f"{name}[{r}][{c}]", cell, spec.choices)
                    for c, cell in enumerate(_as_sequence(f"{name}[{r}]", row))
                )
                for r, row in enumerate(_as_sequence(name, raw))
            )
        case "str_or_list":
            if isinstance(raw, str):
                return _as_enum(name, raw, spec.choices) if spec.choices else raw
            return tuple(
                _as_str(f"{name}[{n}]", element)
                for n, element in enumerate(_as_sequence(name, raw))
            )
    raise AssertionError(f"unreachable ConfigKind {spec.kind!r}")  # pragma: no cover


# --------------------------------------------------------------------------------------------
# The env-value grammar. A twin arrives as a string; the declared kind decides how it is read.
# --------------------------------------------------------------------------------------------

_TRUE: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})
_FALSE: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})


def _from_env_text(spec: ConfigKey, text: str, *, key: str, var: str) -> ConfigValue:
    """Read one ``OMNIWEAVE_*`` value. Scalars parse; the shaped kinds take JSON or a CSV list."""

    def bad(want: str) -> ConfigError:
        return ConfigError(
            f"{var}: {text!r} is not {want} for {key}",
            symbol="OW_CONFIG_VALUE",
            fix=f"set {var} to {want}, or unset it and set {key} in omniweave.toml",
        )

    match spec.kind:
        case "bool":
            lowered = text.strip().lower()
            if lowered in _TRUE:
                return True
            if lowered in _FALSE:
                return False
            raise bad("a bool (true/false)")
        case "int":
            try:
                return int(text.strip(), 10)
            except ValueError:
                raise bad("an int") from None
        case "float":
            try:
                parsed = float(text.strip())
            except ValueError:
                raise bad("a float") from None
            return _as_float(key, parsed)
        case "str" | "path" | "enum":
            return coerce(spec, text, key=key)
        case "list" | "str_or_list" | "table" | "matrix":
            stripped = text.strip()
            if spec.kind in ("list", "str_or_list") and not stripped.startswith(("[", "{")):
                if spec.kind == "str_or_list" and (not spec.choices or stripped in spec.choices):
                    return coerce(spec, stripped, key=key)
                return coerce(spec, [p.strip() for p in stripped.split(",") if p.strip()], key=key)
            try:
                parsed_json = json.loads(stripped)
            except json.JSONDecodeError:
                raise bad("valid JSON") from None
            return coerce(spec, parsed_json, key=key)
    raise AssertionError(f"unreachable ConfigKind {spec.kind!r}")  # pragma: no cover


# --------------------------------------------------------------------------------------------
# The registry. Every declared key, glob segments included. Axes are charter.md's
# tools/config_axes.toml block, cross-checked against 18-api-sketch.md section 4's Axis column.
# --------------------------------------------------------------------------------------------

COST_CLASSES: Final[tuple[str, ...]] = ("free", "local_compute", "billed_api")
LICENCE_TIERS: Final[tuple[str, ...]] = ("open", "restricted", "commercial", "forbidden")
TRUST_VALUES: Final[tuple[str, ...]] = ("ambiguous", "inferred", "extracted")

SHIPPED_DRIVERS: Final[tuple[str, ...]] = (
    # ADR-3 decision 1: the ten ids charter.md's shipped `omniweave.toml` names, plus the three
    # that make `ow doctor` green on a fresh install -- `parse.text.builtin`, and the two Drivers
    # the `pptx` Target is implemented by.
    "parse.office.anydoc",
    "parse.pdf.pdfium",
    "parse.page.olmocr",
    "parse.text.builtin",
    "parse.pptx.native",
    "compile.pptx.native",
    "derive.segment.spine",
    "derive.anchor.native",
    "derive.anchor.defterm",
    "derive.xref.native",
    "derive.xref.pattern",
    "derive.entity.table",
    "derive.entity.gazetteer",
)

SHIPPED_PASSES: Final[tuple[str, ...]] = (
    "derive.segment.spine",
    "derive.anchor.native",
    "derive.anchor.defterm",
    "derive.xref.native",
    "derive.xref.pattern",
    "derive.entity.table",
    "derive.entity.gazetteer",
)

PACKING_TIER: Final[tuple[tuple[Scalar, ...], ...]] = (
    # [blocks_below, max_chars, max_docs, chars_per_doc, calls, related, pointers, meta_text]
    (5000, 12000, 4, 3500, 1, False, False, False),
    (50000, 18000, 6, 4500, 2, False, True, False),
    (500000, 22000, 8, 5000, 3, True, True, True),
    (5000000, 24000, 8, 5500, 4, True, True, True),
    (9223372036854775807, 24000, 10, 5500, 5, True, True, True),
)


def _key(
    name: str,
    kind: ConfigKind,
    default: Default,
    axis: ConfigAxis,
    *,
    choices: tuple[str, ...] = (),
    item_kind: ConfigKind | None = None,
) -> ConfigKey:
    return ConfigKey(
        name=name,
        kind=kind,
        default=default,
        axis=axis,
        env=ENV_OVERRIDES.get(name) or default_env_name(name),
        choices=choices,
        item_kind=item_kind,
    )


_DECLARATIONS: Final[tuple[ConfigKey, ...]] = (
    _key("schema", "int", CONFIG_SCHEMA, "operational"),
    # [roots] -- THREE ROOTS, ALWAYS SEPARATE
    _key("roots.source", "path", ".", "operational"),
    _key("roots.output", "path", ".omniweave/out", "operational"),
    _key("roots.cache", "path", ".omniweave/cache", "operational"),
    # [corpora.<name>] -- the registry `ow_corpora` enumerates
    _key("corpora.*.path", "path", REQUIRED, "operational"),
    _key("corpora.*.source", "path", Inherit("roots.source"), "operational"),
    # [store]
    _key(
        "store.backend", "enum", "sqlite", "operational", choices=("sqlite", "postgres", "fabric")
    ),
    _key("store.path", "path", ".omniweave/index.owstore", "operational"),
    _key(
        "store.retain_parts",
        "enum",
        "when_citable",
        "semantic",
        choices=("always", "when_citable", "never"),
    ),
    _key("store.wal_valve_mb", "int", 0, "operational"),
    _key("store.wal_heal_mb", "int", 64, "operational"),
    _key("store.bulk_windows", "bool", True, "operational"),
    # [limits] -- clamps BELOW omniweave_core.limits' MAX_*; a lower limit TRUNCATES output
    _key("limits.max_entry_bytes", "int", 33554432, "semantic"),
    # [drivers] -- DISCOVERY IS NOT CONSENT (INV-5)
    _key("drivers.enabled", "list", SHIPPED_DRIVERS, "operational", item_kind="str"),
    _key("drivers.require_lock", "bool", True, "operational"),
    _key("drivers.allow_unattested", "bool", False, "operational"),
    _key(
        "drivers.isolation_floor", "enum", "subproc", "operational", choices=("inproc", "subproc")
    ),
    _key("drivers.inproc", "list", ("parse.office.anydoc",), "operational", item_kind="str"),
    _key("drivers.probe_timeout_ms", "int", 2000, "operational"),
    _key(
        "drivers.max_workers",
        "table",
        {"free": 4, "local_compute": 4, "billed_api": 8},
        "operational",
        item_kind="int",
    ),
    _key("drivers.worker_idle_ttl_s", "int", 300, "operational"),
    _key(
        "drivers.crash_quarantine",
        "table",
        {"crashes": 3, "window_s": 60},
        "operational",
        item_kind="int",
    ),
    _key(
        "drivers.cost.allow_classes",
        "list",
        ("free", "local_compute"),
        "operational",
        choices=COST_CLASSES,
        item_kind="enum",
    ),
    _key(
        "drivers.cost.auto_refresh_classes",
        "list",
        ("free",),
        "operational",
        choices=COST_CLASSES,
        item_kind="enum",
    ),
    # ADR-3 decision 3: `[drivers.resolve]` -- a duplicate id never wins silently
    _key("drivers.resolve.*", "str", REQUIRED, "operational"),
    # A driver's OWN config table: preserved VERBATIM, and it enters `options_digest`
    _key("drivers.*.config", "table", {}, "semantic", item_kind=None),
    # [services.<name>] -- SEAM S3. A Service is named and NEVER routed
    _key("services.*.model_id", "str", REQUIRED, "semantic"),
    _key("services.*.model_revision", "str", REQUIRED, "semantic"),
    _key("services.*.endpoint", "str", "", "operational"),
    _key("services.*.autostart", "bool", True, "operational"),
    _key("services.*.capacity", "int", 0, "operational"),
    _key("services.*.batch_wait_ms", "int", 5, "operational"),
    _key("services.*.max_batch", "int", 8, "operational"),
    _key("services.*.keep_alive_s", "int", 300, "operational"),
    # [licence] -- selectors, checked against card facts
    _key(
        "licence.allow_tiers",
        "list",
        ("open",),
        "operational",
        choices=LICENCE_TIERS,
        item_kind="enum",
    ),
    _key("licence.jurisdiction", "str", "DE", "operational"),
    _key(
        "licence.fields_of_use", "list", ("enterprise_documents",), "operational", item_kind="str"
    ),
    # [targets] -- an artefact-kind allowlist; `targets.*.*` is SEMANTIC
    _key("targets.enabled", "list", ("pptx",), "operational", item_kind="str"),
    _key("targets.video.ffmpeg", "enum", "system", "semantic", choices=("system",)),
    _key("targets.video.codec", "enum", "vp9", "semantic", choices=("vp9", "h264")),
    # [budget] -- admission only; currency caps live in .omniweave/policy.d/*.toml
    _key(
        "budget.max_inflight",
        "table",
        {"free": 32, "local_compute": 4, "billed_api": 2},
        "operational",
        item_kind="int",
    ),
    # [runtime]
    _key("runtime.queue_high_water", "int", 50000, "operational"),
    _key("runtime.queue_low_water", "int", 25000, "operational"),
    _key("runtime.plan_batch", "int", 512, "operational"),
    _key("runtime.store_group_commit_ms", "int", 20, "operational"),
    _key("runtime.lease_ms", "int", 120000, "operational"),
    _key("runtime.lease_extend_ms", "int", 60000, "operational"),
    _key("runtime.watchdog_ms", "int", 60000, "operational"),
    _key("runtime.loop_lag_max_ms", "int", 250, "operational"),
    _key("runtime.yield_interval", "int", 1000, "operational"),
    _key("runtime.interactive_wait_ms", "int", 2000, "operational"),
    _key("runtime.batch_wait_lock_ms", "int", 60000, "operational"),
    _key("runtime.max_inproc", "int", 2, "operational"),
    _key("runtime.inproc_bulk_threshold", "int", 64, "operational"),
    _key("runtime.max_deps_per_unit", "int", 256, "operational"),
    _key("runtime.work_compact_above", "int", 5000000, "operational"),
    _key("runtime.max_sequence_units", "int", 64, "operational"),
    # 08-runtime.md:2598-2606's "New keys this document introduces", declared by W4.2's loop,
    # which is the cell that reads all three (D137, D149).
    _key("runtime.shutdown_grace_ms", "int", 5000, "operational"),
    _key("runtime.deferred_sweep_ms", "int", 5000, "operational"),
    _key("runtime.stall_poll_ms", "int", 30000, "operational"),
    _key(
        "runtime.claim.batch",
        "table",
        {"free": 256, "local_compute": 32, "billed_api": 8},
        "operational",
        item_kind="int",
    ),
    # [cache]
    _key("cache.recipe", "int", 1, "semantic"),
    _key(
        "cache.gc",
        "table",
        {"free_after_days": 7, "local_after_days": 90, "billed_after_days": 0},
        "operational",
        item_kind="int",
    ),
    _key("cache.min_free_bytes", "int", 5368709120, "operational"),
    _key("cache.max_bytes.blob", "int", 107374182400, "operational"),
    _key("cache.max_bytes.render", "int", 21474836480, "operational"),
    _key("cache.max_bytes.signal", "int", 2147483648, "operational"),
    _key("cache.max_bytes.call", "int", 0, "operational"),
    _key("cache.max_bytes.embed", "int", 0, "operational"),
    # [retrieval] -- THE DEFAULT IS OFF
    _key("retrieval.vectors", "enum", "off", "operational", choices=("off", "on")),
    _key("retrieval.scorer", "int", 1, "operational"),
    _key("retrieval.fusion_k", "int", 60, "operational"),
    _key("retrieval.snapshot_ms", "int", 2000, "operational"),
    _key("retrieval.trigram", "bool", False, "operational"),
    _key("retrieval.event_log", "bool", True, "operational"),
    _key("retrieval.event_log_query", "bool", False, "operational"),
    _key("retrieval.weights.identity", "float", 2.0, "operational"),
    _key("retrieval.weights.exact", "float", 1.2, "operational"),
    _key("retrieval.weights.lexical", "float", 1.0, "operational"),
    _key("retrieval.weights.semantic", "float", 0.8, "operational"),
    _key("retrieval.weights.structural", "float", 0.4, "operational"),
    _key("retrieval.lex.w_body", "float", 1.0, "operational"),
    _key("retrieval.lex.w_head", "float", 6.0, "operational"),
    _key("retrieval.lex.spine_decay", "float", 0.6, "operational"),
    _key("retrieval.lex.overfetch", "int", 5, "operational"),
    _key("retrieval.budget.query_ms", "int", 250, "operational"),
    _key("retrieval.budget.hydration_reserve_ms", "int", 40, "operational"),
    _key(
        "retrieval.budget.channel_ms",
        "table",
        {"identity": 15, "exact": 25, "lexical": 50, "structural": 40, "semantic": 80},
        "operational",
        item_kind="int",
    ),
    _key("retrieval.vec.model_key", "str", "", "semantic"),
    _key("retrieval.vec.backend", "str", "vector.brute", "operational"),
    _key(
        "retrieval.vec.storage",
        "enum",
        "auto",
        "operational",
        choices=("auto", "sig_only", "sig_full"),
    ),
    _key("retrieval.vec.max_segments", "int", 250000, "operational"),
    # [graph]
    _key("graph.enabled", "bool", True, "operational"),
    _key("graph.etypes", "str", "auto", "semantic"),
    _key("graph.segment_target_tokens", "int", 1200, "semantic"),
    _key("graph.llm_coverage_floor", "float", 0.60, "semantic"),
    _key("graph.max_items_per_segment", "int", 2048, "semantic"),
    _key("graph.passes.order", "enum", "cost_class", "operational", choices=("cost_class",)),
    _key("graph.passes.enable", "list", SHIPPED_PASSES, "operational", item_kind="str"),
    # [serve]
    _key("serve.profile", "enum", "default", "operational", choices=("default", "full")),
    _key("serve.listed", "list", (), "operational", item_kind="str"),
    _key(
        "serve.enabled",
        "str_or_list",
        "read_only+add",
        "operational",
        choices=("all", "read_only", "read_only+add"),
    ),
    _key("serve.compact_schemas", "bool", True, "operational"),
    _key("serve.default_corpus", "str", "handbook", "operational"),
    _key("serve.tool_prefix", "str", "ow_", "operational"),
    _key("serve.add_deadline_ms", "int", 20000, "operational"),
    # The admission queue, 10-interfaces.md:958. Two numbers and not one: `max_concurrent_queries`
    # bounds SNAPSHOTS in flight, which is a WAL bound before it is a latency one (07 section 10.5
    # -- a held read transaction pins the WAL), and `max_queued_queries` bounds what waits behind
    # them. Beyond both the call is refused OW-A-022 with a `retry_after_ms` rather than blocked
    # without an answer. Both `operational`: neither can change the CONTENT of a produced row.
    _key("serve.max_concurrent_queries", "int", 2, "operational"),
    _key("serve.max_queued_queries", "int", 8, "operational"),
    _key("serve.max_sessions", "int", 64, "operational"),
    _key("serve.read_timeout_ms", "int", 30000, "operational"),
    _key("serve.allowed_origins", "list", (), "operational", item_kind="str"),
    _key(
        "serve.allowed_hosts",
        "list",
        ("localhost", "127.0.0.1", "[::1]"),
        "operational",
        item_kind="str",
    ),
    _key("serve.packing.hard_ceiling", "int", 24000, "operational"),
    _key("serve.packing.cliff_fraction", "float", 0.15, "operational"),
    _key(
        "serve.packing.cliff_exempt_trust",
        "enum",
        "extracted",
        "operational",
        choices=TRUST_VALUES,
    ),
    _key("serve.packing.min_chars", "int", 600, "operational"),
    _key("serve.packing.max_share", "float", 0.60, "operational"),
    _key("serve.packing.doc_overhead", "int", 180, "operational"),
    _key("serve.packing.block_overhead", "int", 95, "operational"),
    _key("serve.packing.spine_boost", "float", 2.0, "operational"),
    _key("serve.packing.whole_section_buy", "float", 0.60, "operational"),
    _key("serve.packing.buy_pool", "float", 0.15, "operational"),
    _key("serve.packing.tier", "matrix", PACKING_TIER, "operational"),
    # [observe] -- every key here is operational; none can change a produced row
    _key(
        "observe.sinks",
        "list",
        ("console", "ndjson"),
        "operational",
        choices=("console", "ndjson"),
        item_kind="enum",
    ),
    _key("observe.ndjson_path", "str", ".omniweave/events/{run_id}.ndjson", "operational"),
    _key("observe.shard_bytes", "int", 67108864, "operational"),
    _key(
        "observe.sample",
        "table",
        {"non_ok": 1.0, "ok": 0.015625},
        "operational",
        item_kind="float",
    ),
    _key("observe.timings", "enum", "always", "operational", choices=("always", "never")),
    _key("observe.otlp_endpoint", "str", "", "operational"),
    _key(
        "observe.level",
        "enum",
        "info",
        "operational",
        choices=("debug", "info", "notice", "warn", "error"),
    ),
    _key("observe.redact", "enum", "none", "operational", choices=("none", "paths")),
    _key("observe.retain_days", "int", 14, "operational"),
)

KEYS: Final[Mapping[str, ConfigKey]] = {k.name: k for k in _DECLARATIONS}
if len(KEYS) != len(_DECLARATIONS):  # pragma: no cover - a duplicated declaration site
    raise AssertionError("a config key is declared twice")

_LITERAL_KEYS: Final[tuple[ConfigKey, ...]] = tuple(k for k in _DECLARATIONS if not k.is_glob)
_GLOB_KEYS: Final[tuple[ConfigKey, ...]] = tuple(k for k in _DECLARATIONS if k.is_glob)


def resolve_key(name: str, *, keys: Iterable[ConfigKey] | None = None) -> ConfigKey:
    """The declaration governing ``name``. An explicit key beats a glob; TWO globs is a failure.

    Glob arity is charter.md's ``tools/config_axes.toml`` header block, restated in
    02-architecture.md section 8.3: "two globs matching one key is a G18 FAILURE, not a precedence
    puzzle". An undeclared key raises ``ConfigError`` naming the nearest known one (section 8.2).
    """
    declarations = tuple(keys) if keys is not None else _DECLARATIONS
    for spec in declarations:
        if not spec.is_glob and spec.name == name:
            return spec
    hits = [spec for spec in declarations if spec.is_glob and spec.matches(name)]
    if len(hits) > 1:
        raise ConfigError(
            f"{name} is matched by {len(hits)} glob patterns "
            f"({', '.join(h.name for h in hits)}): that is a G18 failure, not a precedence puzzle",
            symbol="OW_CONFIG_GLOB_ARITY",
            fix="make one pattern in tools/config_axes.toml explicit so exactly one matches",
        )
    if hits:
        return hits[0]
    nearest = difflib.get_close_matches(name, list(KEYS), n=1, cutoff=0.0)
    hint = f"; did you mean {nearest[0]}?" if nearest else ""
    raise ConfigError(
        f"unknown config key {name!r}{hint}",
        symbol="OW_CONFIG_UNKNOWN_KEY",
        fix=f"remove {name} from omniweave.toml, or run `ow show-config` to list every known key",
    )


def env_name_of(name: str) -> str:
    """The declared ``OMNIWEAVE_*`` twin for a key, with glob segments substituted."""
    return resolve_key(name).env_for(name)


def _env_pattern_match(pattern: str, var: str) -> tuple[str, ...] | None:
    """Match ``OMNIWEAVE_CORPORA_*_PATH`` against a variable, returning the captured ``*`` parts."""
    parts = pattern.split("*")
    if not var.startswith(parts[0]):
        return None
    rest = var[len(parts[0]) :]
    captured: list[str] = []
    for tail in parts[1:]:
        if tail == "":
            if not rest:
                return None
            captured.append(rest)
            rest = ""
            continue
        cut = rest.find(tail)
        if cut <= 0:
            return None
        captured.append(rest[:cut])
        rest = rest[cut + len(tail) :]
    if rest:
        return None
    return tuple(captured)


def key_of_env_name(var: str) -> str | None:
    """The key a twin names, or ``None`` when the variable is not a config twin.

    The inverse of :func:`env_name_of` over the registry: an exact twin wins, then a glob twin,
    and two glob twins matching one variable raises the same G18 failure two globs on one key do.
    A glob twin's captured segment comes back lower-cased with ``-`` and ``.`` already collapsed
    to ``_`` by :func:`_env_segment`; :func:`load` reconciles it against the instances the file
    layers actually declared.
    """
    if not var.startswith(ENV_PREFIX) or var in NON_KEY_ENV_VARS:
        return None
    for spec in _LITERAL_KEYS:
        if spec.env == var:
            return spec.name
    hits = [spec for spec in _GLOB_KEYS if _env_pattern_match(spec.env, var) is not None]
    if len(hits) > 1:
        raise ConfigError(
            f"{var} is matched by {len(hits)} twin patterns "
            f"({', '.join(h.env for h in hits)}): that is a G18 failure, not a precedence puzzle",
            symbol="OW_CONFIG_GLOB_ARITY",
            fix="rename one declared twin so exactly one pattern matches",
        )
    if not hits:
        return None
    spec = hits[0]
    captured = _env_pattern_match(spec.env, var)
    if captured is None:  # pragma: no cover - guarded by the membership test above
        return None
    segments = list(spec.segments)
    slots = [i for i, s in enumerate(segments) if s in ("*", "**")]
    for slot, value in zip(slots, captured, strict=False):
        segments[slot] = value.lower()
    return join_key(segments)


# --------------------------------------------------------------------------------------------
# The raw line scan. tomllib reports no line numbers, so the loader records each key's line
# during ONE pass over the file text (02-architecture.md section 8.4, `ConfigSource.line`).
# --------------------------------------------------------------------------------------------


def _strip_comment(line: str) -> str:
    out: list[str] = []
    quote: str | None = None
    for ch in line:
        if quote is not None:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def _depth_delta(text: str) -> int:
    return text.count("[") + text.count("{") - text.count("]") - text.count("}")


def scan_lines(text: str) -> Mapping[str, int]:
    """Map every dotted leaf key in a TOML document to the 1-based line it was written on."""
    lines: dict[str, int] = {}
    prefix: tuple[str, ...] = ()
    depth = 0
    for number, raw in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw).strip()
        if depth > 0:
            depth += _depth_delta(line)
            continue
        if not line:
            continue
        if line.startswith("[["):
            prefix = split_key(line[2:].split("]]", 1)[0].strip())
            continue
        if line.startswith("["):
            prefix = split_key(line[1:].split("]", 1)[0].strip())
            continue
        if "=" not in line:
            continue
        name, _, value = line.partition("=")
        try:
            segments = prefix + split_key(name.strip())
        except ConfigError:  # pragma: no cover - malformed TOML fails in tomllib anyway
            continue
        lines.setdefault(join_key(segments), number)
        depth += _depth_delta(value)
    return lines


# --------------------------------------------------------------------------------------------
# Flattening. Registry-driven, which is what makes ADR-3 decision 3's rule decidable: an INLINE
# TABLE is ONE key, and tomllib cannot tell one from a sub-table -- but the declaration can.
# --------------------------------------------------------------------------------------------


def _is_declared_leaf(segments: tuple[str, ...]) -> bool:
    name = join_key(segments)
    if any(spec.name == name for spec in _LITERAL_KEYS):
        return True
    return any(spec.matches(name) for spec in _GLOB_KEYS)


def _may_descend(segments: tuple[str, ...]) -> bool:
    """True when some declared key lives strictly below ``segments``."""
    for spec in _DECLARATIONS:
        pattern = spec.segments
        if len(pattern) > len(segments) and _match_segments(pattern[: len(segments)], segments):
            return True
    return False


def flatten(document: Mapping[str, object]) -> Mapping[str, object]:
    """Flatten a parsed TOML document to dotted leaf keys, stopping at every declared leaf.

    An unknown key raises ``ConfigError`` naming the nearest known one, because a silently ignored
    key is a config value with no effect, no source and no digest contribution (section 8.2).
    """
    out: dict[str, object] = {}

    def walk(node: Mapping[str, object], segments: tuple[str, ...]) -> None:
        for name, value in node.items():
            here = (*segments, name)
            dotted = join_key(here)
            if isinstance(value, Mapping) and not _is_declared_leaf(here) and _may_descend(here):
                walk(value, here)
                continue
            if not _is_declared_leaf(here):
                resolve_key(dotted)  # raises, naming the nearest known key
            out[dotted] = value

    walk(document, ())
    return out


# --------------------------------------------------------------------------------------------
# The resolved object.
# --------------------------------------------------------------------------------------------


def _digestable(value: ConfigValue) -> object:
    if isinstance(value, Mapping):
        return {k: value[k] for k in sorted(value)}
    if isinstance(value, tuple):
        return [_digestable(v) for v in value]
    return value


def _digest(values: Mapping[str, ConfigValue]) -> str:
    return _sha256_canonical({k: _digestable(values[k]) for k in sorted(values)})


@dataclass(frozen=True, slots=True)
class Config:
    """The frozen result of resolving the six layers, exactly once at startup step 2.

    Printed in 02-architecture.md section 8.4. There is no ``set``, no ``replace`` and no
    ``copy(update=...)``: a call-site override is an argument to an ``Action`` and never reaches
    this object, which is what makes ``ow show-config`` a true statement rather than a snapshot.
    """

    values: Mapping[str, ConfigValue]  # EVERY declared key, resolved. Never partial
    sources: Mapping[str, ConfigSource]  # exactly the same key set as `values`
    config_digest: str  # sha256_canonical(values). 64-char hex
    semantic_digest: str  # sha256_canonical(semantic_projection()). 64-char hex

    def get(self, key: str) -> ConfigValue:
        """The resolved value. Takes NO caller-supplied default (section 8.4 decision (b))."""
        if key in self.values:
            return self.values[key]
        resolve_key(key)  # raises ConfigError naming the nearest known key
        raise ConfigError(
            f"{key} is declared but no layer instantiated it",
            symbol="OW_CONFIG_MISSING_KEY",
            fix=f"declare the section that carries {key} in omniweave.toml",
        )

    def source_of(self, key: str) -> ConfigSource:
        """Which layer supplied this value -- the point of the module."""
        if key in self.sources:
            return self.sources[key]
        self.get(key)  # raises with the right message and the right fix
        raise AssertionError(f"unreachable: {key} has a value and no source")  # pragma: no cover

    def axis_of(self, key: str) -> ConfigAxis:
        """``semantic`` or ``operational``, read off the key's declaration site."""
        return resolve_key(key).axis

    def subkeys(self, prefix: str) -> tuple[str, ...]:
        """The declared ``<name>`` segments under an open-ended section.

        ``subkeys("corpora")`` is the set ``ow_corpora`` enumerates and ``subkeys("services")``
        the set ``ServiceRegistry`` builds a ``ServiceSpec`` from (section 8.4 decision (f)).
        """
        head = split_key(prefix)
        found: set[str] = set()
        for key in self.values:
            segments = split_key(key)
            if len(segments) > len(head) and segments[: len(head)] == head:
                found.add(segments[len(head)])
        return tuple(sorted(found))

    def driver_config(self, driver_id: str) -> Mapping[str, Scalar]:
        """The verbatim-preserved ``drivers."<id>".config`` table.

        This is the ``effective_config`` the ``HELLO`` frame carries (02-architecture.md section
        5.6 row 12). Unknown keys inside it belong to the driver and enter ``options_digest``.
        """
        value = self.values.get(join_key(("drivers", driver_id, "config")))
        if not isinstance(value, Mapping):
            return {}
        return value

    def semantic_projection(self) -> Mapping[str, ConfigValue]:
        """The ``semantic`` half, and the only half a cache key ever sees (section 8.3)."""
        return {k: v for k, v in self.values.items() if resolve_key(k).axis == "semantic"}


# --------------------------------------------------------------------------------------------
# load()
# --------------------------------------------------------------------------------------------


def _read_toml(path: Path) -> tuple[Mapping[str, object], Mapping[str, int]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(
            f"cannot read {path}: {exc}",
            symbol="OW_CONFIG_UNREADABLE",
            fix=f"make {path} readable, or pass a different --config",
        ) from exc
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(
            f"{path} is not valid TOML: {exc}",
            symbol="OW_CONFIG_UNPARSEABLE",
            fix=f"fix the TOML syntax in {path}",
        ) from exc
    return document, scan_lines(text)


def _walk_up(start: Path, name: str) -> Path | None:
    """Walk up from ``start`` for ``name``, stopping at a ``.git`` directory or the root."""
    here = start.resolve()
    for directory in (here, *here.parents):
        candidate = directory / name
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            return None
    return None


def _home_config(env: Mapping[str, str]) -> Path | None:
    """``$OMNIWEAVE_HOME/config.toml``, defaulting to ``~/.omniweave`` read from ``env``."""
    home = env.get("OMNIWEAVE_HOME")
    if home:
        return Path(home) / "config.toml"
    user = env.get("HOME") or env.get("USERPROFILE")
    if not user:
        return None
    return Path(user) / ".omniweave" / "config.toml"


def load(*, cwd: Path, env: Mapping[str, str], explicit: Path | None = None) -> Config:
    """Resolve the six layers plus every declared ``OMNIWEAVE_*`` twin, exactly once.

    ``cwd`` and ``env`` are keyword arguments because ``os.getcwd()`` and ``Path(".")`` are
    semgrep-banned and the project-file search walks up from ``cwd``; ``env`` is injected for the
    same reason the ``Clock`` is (02-architecture.md section 8.4 decision (e)). The precedence
    chain is section 8.1's, resolved lowest rung first.
    """
    values: dict[str, ConfigValue] = {}
    sources: dict[str, ConfigSource] = {}
    inherited: list[tuple[str, Inherit]] = []

    # ---- rung 0: built-in defaults ------------------------------------------------------
    for spec in _LITERAL_KEYS:
        if isinstance(spec.default, _Required):  # pragma: no cover - no literal key is REQUIRED
            continue
        if isinstance(spec.default, Inherit):  # pragma: no cover - no literal key inherits today
            inherited.append((spec.name, spec.default))
            continue
        values[spec.name] = spec.default
        sources[spec.name] = ConfigSource(layer=ConfigLayer.BUILTIN)

    # ---- rungs 1-4: the four file layers, lowest first -----------------------------------
    project_file = _walk_up(cwd, "omniweave.toml")
    for layer in FILE_LAYERS:
        match layer:
            case ConfigLayer.USER_FILE:
                candidate = _home_config(env)
                path = candidate if candidate is not None and candidate.is_file() else None
            case ConfigLayer.PYPROJECT:
                # ONLY when no omniweave.toml was found (section 8.1 rung 3)
                path = None if project_file is not None else _walk_up(cwd, "pyproject.toml")
            case ConfigLayer.PROJECT_FILE:
                path = project_file
            case _:
                path = explicit
        if path is None:
            continue
        document, lines = _read_toml(path)
        if layer is ConfigLayer.PYPROJECT:
            tool = document.get("tool")
            section = tool.get("omniweave") if isinstance(tool, Mapping) else None
            if not isinstance(section, Mapping):
                continue
            document = section
            lines = {
                key.removeprefix("tool.omniweave."): line
                for key, line in lines.items()
                if key.startswith("tool.omniweave.")
            }
        for dotted, raw in flatten(document).items():
            values[dotted] = coerce(resolve_key(dotted), raw, key=dotted)
            sources[dotted] = ConfigSource(layer=layer, path=path, line=lines.get(dotted))

    # ---- the open-ended sections: fill each instance's remaining keys --------------------
    _instantiate_sections(values, sources, inherited)

    # ---- rung 5: the declared OMNIWEAVE_* twins, applied over the file layers ------------
    for var in sorted(env):
        key = key_of_env_name(var)
        if key is None:
            continue
        key = _reconcile_instance(key, values)
        if key is None:
            continue
        values[key] = _from_env_text(resolve_key(key), env[var], key=key, var=var)
        sources[key] = ConfigSource(layer=ConfigLayer.ENV, env_var=var)

    for dotted, rule in inherited:
        if dotted in values:
            continue
        values[dotted] = values[rule.from_key]
        sources[dotted] = sources[rule.from_key]

    _check_startup_invariants(values, cwd=cwd)

    return Config(
        values=dict(values),
        sources=dict(sources),
        config_digest=_digest(values),
        semantic_digest=_digest(
            {k: v for k, v in values.items() if resolve_key(k).axis == "semantic"}
        ),
    )


_OPEN_SECTIONS: Final[tuple[str, ...]] = ("corpora", "services")


def _instantiate_sections(
    values: dict[str, ConfigValue],
    sources: dict[str, ConfigSource],
    inherited: list[tuple[str, Inherit]],
) -> None:
    """Give every ``[corpora.<name>]`` and ``[services.<name>]`` instance its remaining keys.

    A ``REQUIRED`` key the operator did not set is a startup error naming the exact key, which is
    the half of "never partial" (section 8.4) that a glob declaration cannot supply on its own.
    """
    for section in _OPEN_SECTIONS:
        instances = {
            split_key(k)[1] for k in values if split_key(k)[0] == section and len(split_key(k)) > 2
        }
        for name in sorted(instances):
            for spec in _GLOB_KEYS:
                pattern = spec.segments
                if pattern[0] != section or len(pattern) != 3 or pattern[1] != "*":
                    continue
                dotted = join_key((section, name, pattern[2]))
                if dotted in values:
                    continue
                if isinstance(spec.default, _Required):
                    raise ConfigError(
                        f"{dotted} has no default and was not set",
                        symbol="OW_CONFIG_MISSING_KEY",
                        fix=f"set {dotted} in omniweave.toml",
                    )
                if isinstance(spec.default, Inherit):
                    inherited.append((dotted, spec.default))
                    continue
                values[dotted] = spec.default
                sources[dotted] = ConfigSource(layer=ConfigLayer.BUILTIN)


def _reconcile_instance(key: str, values: Mapping[str, ConfigValue]) -> str | None:
    """Map a twin's captured segment back onto an instance a file layer actually declared.

    ``_env_segment`` collapses ``.`` and ``-`` to ``_``, so ``OMNIWEAVE_CORPORA_MY_DOCS_PATH``
    could name ``my-docs`` or ``my_docs``. An environment variable never *creates* a corpus, a
    service or a driver instance -- a file layer does -- so a twin whose instance no layer
    declared is ignored rather than guessed at.
    """
    if key in values:
        return key
    spec = resolve_key(key)
    if not spec.is_glob:
        return key
    segments = split_key(key)
    slots = [i for i, s in enumerate(spec.segments) if s in ("*", "**")]
    candidates: set[str] = set()
    for existing in values:
        other = split_key(existing)
        if len(other) != len(segments) or not spec.matches(existing):
            continue
        if all(other[i] == segments[i] for i in range(len(segments)) if i not in slots) and all(
            _env_segment(other[i]) == _env_segment(segments[i]) for i in slots
        ):
            candidates.add(existing)
    if len(candidates) == 1:
        return candidates.pop()
    if len(candidates) > 1:
        raise ConfigError(
            f"{env_name_of(key)} could name any of {', '.join(sorted(candidates))}",
            symbol="OW_CONFIG_GLOB_ARITY",
            fix=f"set the key directly in omniweave.toml instead of {env_name_of(key)}",
        )
    return None


def _check_startup_invariants(values: Mapping[str, ConfigValue], *, cwd: Path) -> None:
    """The two checks 02-architecture.md section 5.3 row 2 attributes to the config step.

    Everything else -- ``set(listed) <= set(enabled)``, ``default_corpus`` naming a ``[corpora]``
    entry, ``sum(channel_ms) + hydration_reserve_ms <= query_ms`` -- is startup step 5's surface
    invariants or ``ow route lint``, and is deliberately NOT here. The third is check 3 and the
    reserve is a TERM of it (07:1114); the shipped defaults sum to exactly ``query_ms``, so a
    paraphrase that dropped the reserve would describe an arithmetic the shipped file fails.
    """
    schema = values.get("schema")
    if isinstance(schema, int) and schema > CONFIG_SCHEMA:
        raise ConfigError(
            f"omniweave.toml declares schema = {schema}; this build understands {CONFIG_SCHEMA}",
            symbol="OW_CONFIG_SCHEMA_TOO_NEW",
            fix="upgrade omniweave, or set schema = 1 in omniweave.toml",
        )
    source, cache = values.get("roots.source"), values.get("roots.cache")
    if isinstance(source, str) and isinstance(cache, str) and _is_inside(cwd, cache, source):
        raise ConfigError(
            f"[roots] cache = {cache!r} is inside source = {source!r}",
            symbol="OW_CONFIG_CACHE_INSIDE_SOURCE",
            fix="set [roots] cache to a path outside [roots] source in omniweave.toml",
        )


def _is_inside(cwd: Path, inner: str, outer: str) -> bool:
    """True iff ``inner`` lies strictly below ``outer`` and is NOT under the control directory.

    A purely lexical comparison against the injected ``cwd``: no filesystem access, so the check
    is the same on a machine where neither path exists. The ``.omniweave/`` exemption is forced by
    the shipped defaults -- ``source = "."`` with ``cache = ".omniweave/cache"`` -- which the
    default Scope excludes from the walk (05-ingest-and-routing.md section 3). Reported as a
    deviation.
    """
    base = cwd.as_posix()
    a = posixpath.normpath(posixpath.join(base, inner))
    b = posixpath.normpath(posixpath.join(base, outer))
    if a == b or not a.startswith(b.rstrip("/") + "/"):
        return False
    relative = a[len(b.rstrip("/")) + 1 :]
    return relative.split("/", 1)[0] != CONTROL_DIR
