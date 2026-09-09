"""The `OwError` tree and the `codes.toml` reader behind `ow explain`.

This module raises and explains. It does NOT record: a `Diag` is L2's, a `Finding` is L6's
and a `Rejection` is `resolve()`'s, and 02-architecture.md section 7.1 keeps all six
diagnostic kinds apart on purpose.

Two levels, two axes. Level 1 is 02-architecture.md section 7.2 -- one class per `codes.toml`
area letter, plus the cross-area `ResourceLimit`. Level 2 is 10-interfaces.md section 9.3 --
the six additional leaves whose class alone fixes the CLI exit code. Both hold at once because
`__init__` takes a per-instance `symbol`: **the class picks the exit code, the instance's
symbol picks the register row and therefore the area letter** (18-api-sketch.md section 0.3).

Stdlib only (INV-2, gate G1), and nothing here imports a lazy subpackage (G17). The register
is read at use time and memoised, never at import time, and a missing or unparseable one
raises a named `OwError` carrying the command that clears it -- the three rules of
11-repo-layout.md section 2.6.

Specified in 02-architecture.md sections 2 (row 6) and 7.2, 18-api-sketch.md section 0.3 and
section 9 item 7, 10-interfaces.md section 9.3, and charter.md section 6.4.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import ClassVar, Final

__all__ = (
    "AREA_CLASSES",
    "AREA_LETTERS",
    "FAILURE_CLASS_IS_FATAL",
    "NUMERIC_RE",
    "SYMBOL_RE",
    "BudgetExhausted",
    "CapabilityMissing",
    "CodeRow",
    "ConfigError",
    "DriverHostError",
    "GraphError",
    "InternalError",
    "ModelError",
    "NotFoundError",
    "OwError",
    "PolicyRefusal",
    "QualityError",
    "Register",
    "ResourceLimit",
    "RouteError",
    "StoreBusy",
    "StoreError",
    "SurfaceError",
    "TargetError",
    "UsageError",
    "check_register",
    "explain",
    "is_fatal_failure",
    "load_register",
    "register_path",
)


# ---------------------------------------------------------------------------
# Level 1 -- one class per codes.toml area letter (02-architecture.md section 7.2).
# ---------------------------------------------------------------------------


class OwError(Exception):
    """Every framework error. Carries a `codes.toml` symbol, a fatality bit and a fix command.

    `EXIT` is the floor. A raise site wanting another exit code raises a level-2 leaf; it never
    passes an exit code as an argument, because 10-interfaces.md section 9.3 makes the exit a
    pure function of the exception class and an argument would make it two things.

    Specified in 02-architecture.md section 7.2 and 18-api-sketch.md section 0.3.
    """

    SYMBOL: ClassVar[str] = ""
    EXIT: ClassVar[int] = 70

    def __init__(self, message: str, *, symbol: str | None = None, fix: str) -> None:
        if not fix:
            raise ValueError("every OwError names the exact command that clears it")
        super().__init__(message)
        self._symbol = symbol or self.SYMBOL
        self.fix = fix  # THE EXACT COMMAND THAT CLEARS IT. Never empty. charter.md section 6.4.

    def code(self) -> str:
        """The SYMBOL -- the stored and wire form (charter.md section 5 C9).

        `OW-S-010` is the human form, resolved from `codes.toml` by `ow explain`, which accepts
        either spelling.
        """
        return self._symbol

    def numeric(self) -> str:
        """`OW-A-013` -- the human form, resolved from `codes.toml`.

        Returns `""` when the symbol has no register row, which is the case for the ten class
        default symbols: they name an area, not a condition. Resolving a numeric must never be
        able to fail an error path, so an unreadable register degrades to `""` here rather than
        raising on top of the error being reported. 18-api-sketch.md section 0.3.
        """
        try:
            return load_register().by_symbol[self._symbol].numeric
        except (KeyError, OwError):
            return ""

    def is_fatal(self) -> bool:
        """A limit breach is never swallowed (anydoc's `is_fatal()`).

        Fatal means "may not be absorbed by a try-the-optional-part-and-ignore-failures helper",
        which is a different axis from retryability: 05-ingest-and-routing.md section 4 rule 3
        lets the container walker's per-member `except` catch only `UNSUPPORTED_FORMAT` and
        `CORRUPT_INPUT`, and a raised `OwError` is never one of those. Retryability is
        `omniweave_core.work.classify()`'s and there is no second ladder (08-runtime.md
        section 1.6); `FAILURE_CLASS_IS_FATAL` below is this axis over a `FailureClass`.
        """
        return True


class ConfigError(OwError):
    """Configuration, startup only. `OW-C-*`. Exit 1."""

    SYMBOL = "OW_CONFIG"
    EXIT = 1


class ModelError(OwError):
    """An unknown kind, a retired cite. `OW-M-*`."""

    SYMBOL = "OW_MODEL"


class DriverHostError(OwError):
    """A protocol, card or code mismatch -- OUR bug, never the driver's. `OW-D-*`.

    02-architecture.md section 7.5: a frame that violates `wire.py`'s caps or carries an unknown
    kind is this, and not a `driver_bug` attributed to a third party.
    """

    SYMBOL = "OW_DRIVER_HOST"


class RouteError(OwError):
    """A policy that will not lint. `OW-R-*`."""

    SYMBOL = "OW_ROUTE"


class StoreError(OwError):
    """Snapshot expiry, a busy writer. `OW-S-*`."""

    SYMBOL = "OW_STORE"


class GraphError(OwError):
    """A cluster above the cap. `OW-G-*`."""

    SYMBOL = "OW_GRAPH"


class TargetError(OwError):
    """An OUT failure that must raise. `OW-T-*`."""

    SYMBOL = "OW_TARGET"


class SurfaceError(OwError):
    """An ambiguous cite, a bad bind. `OW-A-*`."""

    SYMBOL = "OW_SURFACE"


class PolicyRefusal(OwError):  # noqa: N818 -- the charter fixes the name; a refusal is not a bug.
    """A licence tier, a missing grant, a path outside roots. `OW-P-*`. Exit 6."""

    SYMBOL = "OW_POLICY"
    EXIT = 6


class QualityError(OwError):
    """An incomplete `measured_on`. `OW-Q-*`."""

    SYMBOL = "OW_QUALITY"


class ResourceLimit(OwError):  # noqa: N818 -- 02-architecture.md section 7.2 fixes the name.
    """Cross-area, because it is the ONE error required to name a knob.

    Exit 1, not 70: `.limit` names the configuration knob that would clear it, and "usage or
    configuration error" is exactly what that is (18-api-sketch.md section 0.3).
    """

    SYMBOL = "OW_RESOURCE_LIMIT"
    EXIT = 1

    def __init__(self, message: str, *, limit: str, fix: str, symbol: str | None = None) -> None:
        if not limit:
            raise ValueError("a ResourceLimit names WHICH knob would need raising")
        super().__init__(message, symbol=symbol, fix=fix)
        self.limit = limit


# ---------------------------------------------------------------------------
# Level 2 -- the exit map (10-interfaces.md section 9.3). Six leaves; PolicyRefusal is level 1.
# ---------------------------------------------------------------------------


class UsageError(SurfaceError):
    """An argument failed validation before any store read. Exit 1."""

    EXIT = 1


class NotFoundError(SurfaceError):
    """No such corpus, cite, addr, document or Action. Exit 2."""

    EXIT = 2


class BudgetExhausted(RouteError):  # noqa: N818 -- 10-interfaces.md section 9.3 fixes the name.
    """`DEFERRED_BUDGET`. Exit 5. `.approve_command` carries the `--allow-cost` line."""

    EXIT = 5

    def __init__(
        self,
        message: str,
        *,
        approve_command: str,
        symbol: str | None = None,
        fix: str | None = None,
    ) -> None:
        if not approve_command:
            raise ValueError("a BudgetExhausted names the command that approves the spend")
        super().__init__(message, symbol=symbol, fix=fix or approve_command)
        self.approve_command = approve_command


class StoreBusy(StoreError):  # noqa: N818 -- 10-interfaces.md section 9.3 fixes the name.
    """Another writer holds the corpus. Exit 7. `.holder` is `(host, pid, age_s)`."""

    EXIT = 7

    def __init__(
        self,
        message: str,
        *,
        holder: tuple[str, int, float],
        fix: str,
        symbol: str | None = None,
    ) -> None:
        super().__init__(message, symbol=symbol, fix=fix)
        self.holder = holder


class CapabilityMissing(DriverHostError):  # noqa: N818 -- 10-interfaces.md section 9.3 names it.
    """A required toolchain or driver is absent. Exit 64. `.missing` is machine-actionable."""

    EXIT = 64

    def __init__(
        self,
        message: str,
        *,
        missing: tuple[str, ...],
        fix: str,
        symbol: str | None = None,
    ) -> None:
        if not missing:
            raise ValueError("a CapabilityMissing NAMES the missing thing")
        super().__init__(message, symbol=symbol, fix=fix)
        self.missing = missing


class InternalError(OwError):
    """Anything else, with the `OW-*` code and the report command. Exit 70."""

    EXIT = 70


#: The ten area letters, which are exactly the areas of `codes.toml`
#: (02-architecture.md section 7.2, charter.md section 6.4). `ResourceLimit` is cross-area and
#: allocates no letter of its own.
AREA_LETTERS: Final[tuple[str, ...]] = ("C", "M", "D", "R", "S", "G", "T", "A", "P", "Q")

#: Area letter -> the level-1 class that owns it. The register's `[area.*]` tables are checked
#: against this by `check_register()`, so a new letter cannot appear on only one side.
AREA_CLASSES: Final[Mapping[str, type[OwError]]] = MappingProxyType(
    {
        "C": ConfigError,
        "M": ModelError,
        "D": DriverHostError,
        "R": RouteError,
        "S": StoreError,
        "G": GraphError,
        "T": TargetError,
        "A": SurfaceError,
        "P": PolicyRefusal,
        "Q": QualityError,
    }
)


# ---------------------------------------------------------------------------
# Fatality over FailureClass -- the other half of `is_fatal()`.
# ---------------------------------------------------------------------------

#: Whether a `FailureClass` may be absorbed by a per-member "try the optional part, ignore
#: failures" helper. Keyed on the enum's WIRE value, which for a `StrEnum` is the member itself,
#: so `FAILURE_CLASS_IS_FATAL[FailureClass.TIMEOUT]` works without importing `omniweave_ports`.
#:
#: Exactly three are not fatal, and each for a stated reason.
#:   `unsupported_format`, `corrupt_input` -- 05-ingest-and-routing.md section 4 rule 3: these
#:      two are the ONLY classes the container walker's per-member `except` catches.
#:   `needs_ocr` -- 02-architecture.md section 7.1: it is not a failure at all. It is routing
#:      data; `DriverError.pages` names the pages and the router escalates exactly those parts.
#:
#: Fatality is NOT retryability. `resource_limit` is transient in 08-runtime.md section 1.6's
#: ladder (60 s, then `adapt_batch`) and fatal here, because a bomb refusal a helper could
#: swallow is how one 512 MB container budget gets spent twice. `work.classify()` owns the retry
#: axis and this module does not duplicate it.
FAILURE_CLASS_IS_FATAL: Final[Mapping[str, bool]] = MappingProxyType(
    {
        "encrypted": True,
        "needs_ocr": False,
        "unsupported_format": False,
        "corrupt_input": False,
        "resource_limit": True,
        "too_large": True,
        "timeout": True,
        "upstream_unavailable": True,
        "rate_limited": True,
        "auth": True,
        "empty_result": True,
        "driver_crashed": True,
        "driver_bug": True,
    }
)


def is_fatal_failure(failure_class: str) -> bool:
    """Whether a `FailureClass` may be swallowed by an ignore-failures helper.

    Accepts an `omniweave_ports.FailureClass` member directly, because that enum is a `StrEnum`
    whose wire value is its lower-case member name (18-api-sketch.md section 0.2), so no import
    of `omniweave_ports` is needed to answer.

    An unrecognised class raises `DriverHostError` rather than guessing: 02-architecture.md
    section 7.5 makes an unknown wire `kind` our bug and never the driver's, and defaulting
    silently is how a new `FailureClass` member ships with no fatality decision behind it.
    """
    try:
        return FAILURE_CLASS_IS_FATAL[str(failure_class)]
    except KeyError:
        raise DriverHostError(
            f"unknown FailureClass {failure_class!r}: it has no fatality decision in "
            f"omniweave_core.errors.FAILURE_CLASS_IS_FATAL",
            fix="ow doctor --deep --render json   # attach the report to the issue",
        ) from None


# ---------------------------------------------------------------------------
# The register -- codes.toml, read at use time and memoised (11-repo-layout.md section 2.6).
# ---------------------------------------------------------------------------

_REGISTER_NAME: Final = "codes.toml"

#: 18-api-sketch.md section 9 item 7 fixes both token shapes for the `codes-unique` lint, and
#: `ow explain --check` is its other half over the register itself.
NUMERIC_RE: Final = re.compile(r"^OW-[A-Z]-\d{3}$")
SYMBOL_RE: Final = re.compile(r"^OW_[A-Z0-9_]{3,}$")

_NEAREST: Final = 3  # "listing the nearest three by edit distance" (18-api-sketch.md line 232).


@dataclass(frozen=True, slots=True)
class CodeRow:
    """One row of the register, as `ow explain` prints it. 18-api-sketch.md section 1.1."""

    numeric: str
    symbol: str
    meaning: str
    fix: str
    owner_doc: str


@dataclass(frozen=True, slots=True)
class Register:
    """The whole parsed `codes.toml`: the ten area tables and every `[[code]]` row."""

    path: Path
    areas: Mapping[str, str]  # area letter -> the level-1 class name it declares
    rows: tuple[CodeRow, ...]
    by_numeric: Mapping[str, CodeRow]
    by_symbol: Mapping[str, CodeRow]


def register_path() -> Path:
    """Locate `codes.toml`.

    Read through `importlib.resources.files()` and never `__file__` or `__path__[0]`
    (11-repo-layout.md section 2.6 rule 1). The register is not among the five packaged files
    that section enumerates, so a workspace checkout falls back to the repo root, which is where
    11-repo-layout.md section 1.1 puts it.
    """
    anchor = resources.files("omniweave_core")
    packaged = anchor.joinpath(_REGISTER_NAME)
    if packaged.is_file():
        return Path(str(packaged))
    for parent in _ancestors(anchor):
        candidate = parent / _REGISTER_NAME
        if candidate.is_file():
            return candidate
    raise ConfigError(
        f"{_REGISTER_NAME} is not readable: this install carries no error-code register, so "
        f"`ow explain` cannot resolve either spelling of a code",
        fix="pip install --force-reinstall omniweave-core",
    )


def _ancestors(anchor: object) -> Iterator[Path]:
    """The directories above the package, when the package has a real filesystem path."""
    if not isinstance(anchor, Path):
        return
    yield from anchor.resolve().parents


def load_register(path: Path | None = None) -> Register:
    """Parse `codes.toml`. Read at use time, memoised, never at import time.

    11-repo-layout.md section 2.6 rule 2 states the reason: a missing or corrupt packaged file
    must degrade one operation, not brick module import. Rule 3 makes an unparseable one a named
    `OwError` carrying the command that clears it, never a `KeyError`, a `FileNotFoundError` or
    a silent empty default.
    """
    return _load_register(path or register_path())


@cache
def _load_register(path: Path) -> Register:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            f"{path} is not a readable error-code register: {exc}",
            fix="pip install --force-reinstall omniweave-core",
        ) from exc

    areas = {
        letter: str(table.get("error_class", ""))
        for letter, table in _tables(raw.get("area", {})).items()
    }
    code_entries = raw.get("code", ())
    rows = tuple(_row(entry) for entry in code_entries) if isinstance(code_entries, list) else ()
    return Register(
        path=path,
        areas=MappingProxyType(areas),
        rows=rows,
        by_numeric=MappingProxyType({row.numeric: row for row in rows}),
        by_symbol=MappingProxyType({row.symbol: row for row in rows}),
    )


def _tables(value: object) -> Mapping[str, Mapping[str, object]]:
    return value if isinstance(value, dict) else {}


def _row(entry: object) -> CodeRow:
    """One `[[code]]` table to a `CodeRow`.

    `owner_doc` is derived from the row's first `sites` entry -- the plan file that binds the
    numeric to the symbol -- because the seeded register records `sites` where 18-api-sketch.md
    section 1.1's `CodeRow` names `owner_doc`. `fix` and `meaning` are empty on a row W1.3 has
    not filled in yet; `ow explain --check` is the gate that closes that half.
    """
    table = entry if isinstance(entry, dict) else {}
    sites = table.get("sites", ())
    first_site = str(sites[0]) if isinstance(sites, list) and sites else ""
    return CodeRow(
        numeric=str(table.get("numeric", "")),
        symbol=str(table.get("symbol", "")),
        meaning=str(table.get("meaning", "")),
        fix=str(table.get("fix", "")),
        owner_doc=first_site.split(":")[0],
    )


def explain(code: str) -> CodeRow:
    """Resolve either spelling -- `OW-A-013` or `OW_PARSE_GAP_IN_SCOPE` -- against `codes.toml`.

    Returns the numeric, the symbol, the one-line meaning, the fix command and the owning
    document. Raises `NotFoundError(OW_UNKNOWN_CODE, OW-A-026)` listing the nearest three by
    edit distance. Specified in 18-api-sketch.md section 1.1.
    """
    wanted = code.strip().upper()
    register = load_register()
    row = register.by_numeric.get(wanted) or register.by_symbol.get(wanted)
    if row is not None:
        return row
    nearest = _nearest(wanted, register)
    raise NotFoundError(
        f"{code} is not in {_REGISTER_NAME}. Nearest: {' - '.join(nearest)}",
        symbol="OW_UNKNOWN_CODE",
        fix="ow explain --check   # prints every registered code, in both spellings",
    )


def _nearest(wanted: str, register: Register) -> tuple[str, ...]:
    """The three closest rows by Levenshtein distance, over whichever spelling was given."""
    numeric_form = "-" in wanted
    scored = sorted(
        register.rows,
        key=lambda row: (
            _edit_distance(wanted, row.numeric if numeric_form else row.symbol),
            row.numeric,
        ),
    )
    return tuple(f"{row.numeric} {row.symbol}" for row in scored[:_NEAREST])


def _edit_distance(a: str, b: str) -> int:
    """Levenshtein, stdlib only.

    `difflib` ranks by matching-block ratio, not by edit distance, and 18-api-sketch.md
    section 1.1 says edit distance.
    """
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def check_register(path: Path | None = None) -> tuple[str, ...]:
    """The register half of `ow explain --check`. One line per failure; `()` is clean.

    18-api-sketch.md section 9 item 7 defines the pair: `codes-unique` covers the plan prose
    before the register exists, this covers the register after. It fails in BOTH directions --
    "a symbol that drifted onto a second numeric is the same build failure seen from the other
    end" -- because reading has already failed twice on exactly that (`OW-A-023` and
    `OW-A-041`), and it also holds the register's ten `[area]` tables against the ten level-1
    classes so a letter cannot exist on only one side.
    """
    register = load_register(path)
    failures: list[str] = []
    numerics: dict[str, list[str]] = {}
    symbols: dict[str, list[str]] = {}

    for row in register.rows:
        if not NUMERIC_RE.match(row.numeric):
            failures.append(f"{row.numeric!r} is not shaped OW-<AREA>-nnn (symbol {row.symbol})")
        elif row.numeric[3] not in register.areas:
            failures.append(f"{row.numeric} names area {row.numeric[3]!r}, which has no table")
        if not SYMBOL_RE.match(row.symbol):
            failures.append(f"{row.symbol!r} is not shaped OW_SCREAMING_SNAKE ({row.numeric})")
        numerics.setdefault(row.numeric, []).append(row.symbol)
        symbols.setdefault(row.symbol, []).append(row.numeric)

    failures.extend(
        f"{numeric} binds {len(set(bound))} symbols: {', '.join(sorted(set(bound)))}"
        for numeric, bound in sorted(numerics.items())
        if len(set(bound)) > 1
    )
    failures.extend(
        f"{symbol} binds {len(set(bound))} numerics: {', '.join(sorted(set(bound)))}"
        for symbol, bound in sorted(symbols.items())
        if len(set(bound)) > 1
    )
    failures.extend(
        f"[area.{letter}] declares error_class {declared!r}, not "
        f"{AREA_CLASSES[letter].__name__ if letter in AREA_CLASSES else '<no such letter>'}"
        for letter, declared in sorted(register.areas.items())
        if letter not in AREA_CLASSES or declared != AREA_CLASSES[letter].__name__
    )
    failures.extend(
        f"[area.{letter}] is missing from {register.path.name}"
        for letter in AREA_LETTERS
        if letter not in register.areas
    )
    return tuple(failures)
