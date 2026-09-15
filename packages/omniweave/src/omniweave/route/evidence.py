"""`Evidence` -- a read log with no mapping -- and the `SignalSpec` registry that fills it.

05-ingest-and-routing.md section 4.6 (:1851-1900) prints `Evidence`; section 5.1 (:2050-2196)
prints `SignalSpec` and declares itself *"the sole home of the signal registry"*; section 5.2
(:2196-2232) gives per-format provider resolution and `OW-P-022`; section 5.4 (:2338-2366) gives
the `route_signal` cache these values are read back from. 16-roadmap.md:603 schedules the lot as
W5.1, and 11-repo-layout.md:250 puts the file in the tree.

**What this module is for, in one sentence: it is the half of INV-14 that a type can carry.**
INV-14 says routing is pure -- `evaluate()` sees no ledger, no clock, no RNG, no environment, no IO
and no `RunContext` -- and 05:1818 says why a type has to be the enforcement: *"A purity claim is
only checkable if the types on both sides of the function are printed, because purity is a property
of a **signature** plus what the argument types can reach."* `Evidence` is the argument that could
have reached everything, so it reaches nothing: `read(key) -> Scalar` is the only accessor, a
`Scalar` is a `bool | int | float | str | None`, and there is no `__getitem__`, no `keys()`, no
`items()` and no `__contains__` to walk back through. `evaluate()` cannot obtain a clock from a
float.

## Three-valued, and `None` is not a default

`read()` returns `None` for UNKNOWN -- uncomputable, no provider for this format, or the provider
raised or timed out -- and 05:1870 writes the consequence in the class: *"Three-valued: `None` is
not a default and compares equal to nothing."* The policy grammar's `on_unknown` is what decides
what an UNKNOWN does (05:1126-1130), and it has three values because the answer differs per rule. A
default would collapse the distinction the whole escalation ladder is built on: "the text layer is
clean" and "we could not read the text layer" send a page to different rungs.

`computed()` is the second half of the same discipline and 05:1877 gives it one caller and one
prohibition: *"`DemandPlan.deferrals_pending(ev)` is the ONLY caller, and it must not go through
`read()`: a planner probe is not a read and may not enter the read set."* So the two questions are
different methods rather than one method and a sentinel.

## The read set is an OBSERVATION, which is why `read()` and not a declaration

05:1871: *"APPENDS to the read log, so the read set is an OBSERVATION and not a declaration a
programmer can forget to update."* `read_set_digest()` is one of the eight identity columns of
`route_decision` (05:1913-1930), so "which values this decision depended on" is not a comment: it
is in the primary key, and a decision taken on a different read set is a different row.

**The plan prints five methods and one phrase they cannot implement, and this module adds a sixth.**
05:1880 says `read_set()` is *"IN READ ORDER, for the winning path and nothing else"*. Nothing in
the printed surface can produce that, because 05:1096's loop calls `evaluate()` once per
`CostClass` group -- FREE, then LOCAL_COMPUTE, then BILLED_API -- re-evaluating every rule after
each, and the log is append-only. By the time a rule matches on the LOCAL group, the log already
holds every read the FREE round performed and every read of every rule that did not match.
`clear_read_log()` is the demarcation, and W5.2's loop calls it immediately before the `evaluate()`
whose result is written. The alternative -- letting the digest cover the losing rounds too -- makes
`read_set_digest` depend on how many groups happened to run, so the same decision on the same bytes
gets two identities on two machines whose demand plans differ by a deferral. D197 files the gap.

That is also why `put()` refuses to change a value the current window has already read: a value
that moves under the reader makes the digest describe a state that never existed. It refuses only
on a DIFFERENT value, and only within the window, because `admit()` legitimately writes
`budget.exhausted` between one rung's decision and the next's (05:1893, RT9).

## `SignalSpec` is data, read by `tomllib`, and registration executes no provider code

05:2041 applies INV-4 to providers: *"Registration is a `SignalSpec` row read from a `signals.toml`
by the same import-free `tomllib` loader that reads a `DriverCard`, so registration executes no
provider code."* A provider is *"an `omniweave.signals` entry point plus a `signals.toml`"* and
*"is **not** a `DriverCard` (no capability floors, never in `resolve()`)"*.

`builtin`'s rows are this package's own package data and are NOT reached through an entry point,
which is `omniweave_core.discovery`'s own `TOMBSTONE_DIRNAME` precedent: the framework's own
declarations are package data because a distribution does not discover itself. `pdfium` and
`officexml` are entry points, and they have to be: `tools/layers.toml` gives `omniweave` the row
`["omniweave_core", "omniweave_ports", "omniweave_office"]`, so this package **may not import
`omniweave_pdf` at all**. Locating its `signals.toml` by name through `Distribution.locate_file`
is not a stylistic preference here; it is the only legal way to read it.

## Per-format resolution, and why a wildcard is not "a precedence puzzle"

Three rows serve `unit.part_count` -- `FPDF_GetPageCount` on a PDF, a sheet count on an XLSX, and
builtin everywhere else -- and 05:2219 sets the rule: *"two providers naming the same `(key,
format)` is `OW-P-022` at startup, not a precedence puzzle, so exactly one provider serves a key
for a given `unit.format`."* `serves` empty *"means every format"* (05:2113).

**Those two sentences only compose under one reading, and the day-one table forces it.** A row with
empty `serves` NAMES no format; it is the fallback. So `(key, format)` resolves to the row that
names the format, else the one that names none, else UNKNOWN -- and `OW-P-022` fires when two rows
name one format, or when two rows for one key name none. The alternative reading, where a wildcard
collides with every specific row, makes `unit.part_count` unregisterable: it is `nullable = false`,
so it must answer for the whole of `unit.format`'s domain, and that domain is **computed and open**
(core's 48 tokens union the enabled cards' `format_tokens`), so no finite list of `serves` can
cover it. A fallback row is the only construction that satisfies both columns of the plan's own
table. D198 files the ambiguity with the reading shipped here.

`resolve()` is a two-step lookup and takes no lock, because the registry is immutable once built.

## Seven of twelve `SignalSpec` fields are properties of the KEY, and three files declare them

`scope`, `kind`, `dtype`, `domain`, `cost_class`, `nullable` and `requires` are columns of 05
section 5.1's table, which has one row per KEY. `provider`, `version`, `est` and `serves` are the
per-provider half. Three `signals.toml` files therefore restate the same seven facts about
`unit.part_count`, and nothing in the plan checks that they agree -- so `build_registry()` does:
a disagreement is `OW-P-022`, naming the field and both providers. Without it a PDF and an XLSX
could disagree about whether `unit.part_count` is nullable, and `ow route lint` check 4 would pass
or fail depending on which file it read first. D199.

## `est` is a declared budget in whole milliseconds, and the table declares tenths

05:2060: *"**`est` is a declared budget, not a measurement**: `SignalSpec.est` is author-declared
exactly as `[cost.model]` is, and `ow conform --bench` overwrites it into `signals.lock`."* It is a
`Spend`, and `Spend.cpu_ms` is an `int` (05:2371). **Sixteen** day-one rows declare a budget
between 0.1 and 0.9 ms and **twenty-three** declare exactly 0. This module's `signals.toml` files
round each fractional figure **up** to the next whole millisecond and keep an exact `0` exactly
`0`, so the table's only structural distinction -- costs something against costs nothing --
survives. Rounding down would collapse those sixteen into the twenty-three and make 05:2063's
*"a provider whose measured p50 exceeds its declared `est` by more than 2x fails
`ow drivers check`"* a comparison against zero. D200.

Core plus this package's `rung` and `spend`. No store, no clock, no loop, no driver import.

Tier T-PUBLIC: 18-api-sketch.md:843.

Specified in 05-ingest-and-routing.md sections 4.6, 5.1, 5.2 and 5.4; 02-architecture.md section 2
row 35; 01-principles.md INV-4 and INV-14; 16-roadmap.md:605.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from importlib.metadata import Distribution
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.canonical import sha256_canonical
from omniweave_core.discovery import PACKAGE_PATH_RE
from omniweave_core.drivers.resolve import COST_CLASS_ORDER
from omniweave_core.errors import PolicyRefusal, RouteError
from omniweave_ports.types import CostClass

from omniweave.route.rung import RUNG_BY_NAME, Rung
from omniweave.route.spend import DIMS, Spend

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "BUILTIN_PROVIDER",
    "BUILTIN_SIGNALS",
    "DTYPES",
    "KEY_RE",
    "KINDS",
    "RESERVED_PROVIDERS",
    "SCOPES",
    "SIGNALS_FILENAME",
    "SIGNAL_GROUP",
    "SIGNAL_TABLE",
    "UNREGISTERED_AT_RELEASE_1",
    "ComputedDomain",
    "Evidence",
    "Installed",
    "Scalar",
    "SignalRegistry",
    "SignalSpec",
    "build_registry",
    "builtin_specs",
    "installed_specs",
    "load_signals",
    "signals_relative_path",
]

# --------------------------------------------------------------------------------------------
# 1. The names. One entry-point group, one filename, one reserved provider.
# --------------------------------------------------------------------------------------------

SIGNAL_GROUP: Final[str] = "omniweave.signals"
"""The provider group. 05:3521: *"A provider is declared by this plus a `signals.toml`, read by the
import-free card loader; it is never a `DriverCard` and never enters `resolve()`."*

Absent from `omniweave_core.discovery`'s four groups on purpose. `DRIVER_GROUP`, `TARGET_GROUP` and
`BACKEND_GROUP` are read by `discover()` on the path INV-3 holds to 80 ms; a signal provider is
needed when a policy is compiled, which happens once per run and after discovery. Enumerating it
there would price a fifth group into every `Catalog.build()` for a consumer that is not core's.
"""

SIGNALS_FILENAME: Final[str] = "signals.toml"
"""The one filename, the same shape as `discovery.CARD_FILENAME`: the entry-point VALUE names a
package and the declaration is a fixed filename inside it."""

BUILTIN_PROVIDER: Final[str] = "builtin"
"""05:2046's first shipped provider -- *"`builtin` (in `omniweave`, stdlib only)"*.

It is package data of this module's own directory and is NOT declared as an entry point. That is
`discovery.TOMBSTONE_DIRNAME`'s precedent applied to signals: the framework's own declarations are
read as package data because a distribution does not discover itself, and an entry point pointing
`omniweave.signals` at `omniweave.route` would make `builtin`'s registration depend on this
distribution's own metadata being installed -- which it is not, in a source checkout.
"""

RESERVED_PROVIDERS: Final[frozenset[str]] = frozenset({"admit"})
"""Provider names that are NOT entry points and that no distribution may claim.

`budget.exhausted`'s provider column in 05 section 5.1's table is `admit()` -- the function, not a
package. 05:1893 makes it one of the three callers of `put()` and *"the single channel by which
budget reaches routing (RT9, section 6.4)"*, so the key is registered like every other (it has a
scope, a dtype and a `nullable` column that lint check 4 reads) while its producer is a function
inside this process. A row naming a reserved provider is legal in a `signals.toml`; an entry point
naming one is refused, because it would put a locatable package behind a name that has none.
"""

SIGNAL_TABLE: Final[str] = "signal"
"""The top-level table: `[signal."math.part_frac"]`, 05:2207's literal shape. Quoted, because the
key contains a dot and a bare `[signal.math.part_frac]` is three nested tables."""

KEY_RE: Final = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
"""05:2093: *"`"<group>.<name>"`, both `[a-z][a-z0-9_]*`"*. Exactly one dot.

The grammar is checked rather than assumed because the key is what a policy file names, what
`route_signal`'s primary key stores and what `ow route lint` check 1 resolves. A key with two dots
would make `[signal.a.b.c]` parse as a nested table and register nothing, silently.
"""

SCOPES: Final[frozenset[str]] = frozenset({"unit", "part", "block", "doc"})
"""The `scope` column. 05:2094."""

KINDS: Final[frozenset[str]] = frozenset({"fact", "measure", "classifier", "count"})
"""The `kind` column. 05:2095. `classifier` is the one with a registration rule of its own (RT5)."""

DTYPES: Final[frozenset[str]] = frozenset({"bool", "int", "float", "str"})
"""The `dtype` column. 05:2096. It is `Scalar` minus `None`, because `None` is UNKNOWN and never a
declared type: a signal does not have a null dtype, it has a `nullable` column."""

CLASSIFIER_DOMAIN: Final[tuple[float, float]] = (0.0, 1.0)
"""RT5's domain, closed on both ends. 05:2100-2101: *"Registration REFUSES kind="classifier" whose
domain is not `[0.0, 1.0]` closed on both ends (RT5) -- a softmax legitimately returns 0.0 and
1.0."* The two endpoints are the reason the check is worth having: an open interval would make a
provider that returns a confident 1.0 fail its own domain check on the one value that matters.
"""

UNREGISTERED_AT_RELEASE_1: Final[frozenset[str]] = frozenset({"layout.class_hist"})
"""The one key 05 section 5.1's table lists whose provider column reads **none (day 1)**.

It has no row in any `signals.toml`, and that is the registration: a `SignalSpec` requires a
provider and a version, and inventing either would claim a value can be computed. 05:2325 states
the consequence and this constant makes it greppable: *"`layout.class_hist` is absent at release 1
and every decision that would have read it records `cause = "layout_unavailable"`."* Reading it
returns `None` through the ordinary UNKNOWN path, which is why no rule needs a special case -- but
a test asserts the key is absent from the built registry, so a later provider lands deliberately.
"""

_INTERVAL_ENDS: Final[int] = 2
"""A `domain` interval has two ends. Named because 05:2098 calls the pair *"INCLUSIVE ON BOTH
ENDS"*, and a three-element list is a literal set of numbers the grammar has no shape for."""

_FIX_SIGNALS = "ow route lint --explain"
"""The command that prints the resolved provider per format (05:2224) -- the one that shows a
reader which row won and which one collided."""

# The seven columns of 05 section 5.1's table, which describe the KEY and not the provider that
# serves it. `build_registry()` asserts agreement across every row for one key.
_KEY_FIELDS: Final[tuple[str, ...]] = (
    "scope",
    "kind",
    "dtype",
    "domain",
    "cost_class",
    "nullable",
    "requires",
)

Scalar = bool | int | float | str | None
"""What a signal is worth. 05:1868's `read()` return type.

Deliberately not `Decimal`, not a tuple and not a nested structure: the record is *"flat,
namespaced, scalar-valued"* (05:1856), and the policy grammar is *"closed, total, comparison-only"*
(05:964). A value a rule cannot compare is a value the router cannot act on, so there is no shape
for it to have.
"""


class ComputedDomain(Enum):
    """A domain that is not a literal in `signals.toml` because it depends on which drivers are on.

    05:2085, verbatim: *"Resolved at policy-compile time and folded into `policy_digest`, so a rule
    naming a driver-contributed token lints exactly as a builtin token does."*
    """

    FORMAT_TOKENS = "format_tokens"
    """Core's 48 tokens union the `token` fields of the enabled cards' `[capability.parse]
    format_tokens` (05:2087-2089, 04 section 2.2). `unit.format` is its only member in the day-one
    registry, and `enum_val`'s `format` domain is seeded from the same union."""


Domain = tuple[float, float] | frozenset[str] | ComputedDomain | None
"""The `domain` column's four shapes. 05:2097-2101.

*"A float pair is INCLUSIVE ON BOTH ENDS; a `frozenset[str]` is what `ow route lint` check 2 tests
a rule's literals against; `None` is a bool or an unbounded int."*
"""


@dataclass(frozen=True, slots=True)
class SignalSpec:
    """One `(key, provider)` registration. 05:2093-2122's twelve fields, in the plan's order.

    Frozen, because a registry that could be mutated after a policy was compiled would make
    `policy_digest` describe a registry that no longer exists. `slots=True` for the same reason
    every record in this framework has them: 54 keys times four providers is not large, but a
    per-instance `__dict__` on a type whose whole content is twelve scalars is pure overhead.

    One instance per `(key, provider)`: 05:2080 says so and gives the example -- *"`unit.part_count`
    has three, disjoint by `serves`, and the registry resolves the pair at read time"*.
    """

    key: str
    scope: str
    kind: str
    dtype: str
    domain: Domain
    cost_class: CostClass
    est: Spend
    provider: str
    version: str
    serves: frozenset[str] = frozenset()
    requires: tuple[Rung, ...] = ()
    nullable: bool = True
    origin: str = ""
    """Where the row was read from -- `"omniweave/route/signals.toml"`. Not one of the plan's
    twelve. It exists because every refusal in this module names two rows, and a message that says
    "`unit.part_count` is declared twice" without saying *where* sends the reader to `grep`. The
    same argument `RouteDecision.rule_origin` makes for itself (05:1933)."""

    def __post_init__(self) -> None:
        """Every check registration performs. A wrong registration is a wrong route, not a crash.

        05:2125 names the three fields that carry the discipline and what each is read by:
        *"`nullable` is what lint check 4 reads, `requires` is what derives the phase and what
        check 7 reads, and `domain` is what check 2 reads. A signal that gets any of the three
        wrong fails a lint rather than producing a wrong route, which is the reason the
        registration is data rather than a decorator."* This method is the earlier half of that
        sentence: the lint checks are W5.5's and they can only test a spec that parsed.
        """
        where = f"{self.key!r} from {self.origin or 'an unnamed source'}"
        if not KEY_RE.match(self.key):
            raise RouteError(
                f"signal key {where} is not '<group>.<name>' with both [a-z][a-z0-9_]*",
                fix=_FIX_SIGNALS,
            )
        for name, value, allowed in (
            ("scope", self.scope, SCOPES),
            ("kind", self.kind, KINDS),
            ("dtype", self.dtype, DTYPES),
        ):
            if value not in allowed:
                listed = ", ".join(sorted(allowed))
                raise RouteError(
                    f"{name} {value!r} of {where} is not one of {listed}", fix=_FIX_SIGNALS
                )
        if not self.provider:
            raise RouteError(f"{where} names no provider", fix=_FIX_SIGNALS)
        if not self.version:
            raise RouteError(
                f"{where} names no provider version, which enters the read set (05:2110)",
                fix=_FIX_SIGNALS,
            )
        _check_domain(self, where)


def _check_domain(spec: SignalSpec, where: str) -> None:
    """The `domain` column against the `dtype` and `kind` columns. RT5 is the last clause.

    Split out of `__post_init__` so that the shape rules and the identity rules are two
    readable functions rather than one method with eleven branches -- and so `PLR0912` is
    satisfied by structure rather than by a `noqa`.
    """
    domain = spec.domain
    if isinstance(domain, tuple):
        low, high = domain
        if spec.dtype not in {"int", "float"}:
            raise RouteError(
                f"{where} declares a numeric interval on a {spec.dtype} signal", fix=_FIX_SIGNALS
            )
        if not (low <= high):
            raise RouteError(f"{where} declares the interval [{low}, {high}]", fix=_FIX_SIGNALS)
    elif isinstance(domain, frozenset):
        if spec.dtype != "str":
            raise RouteError(
                f"{where} declares a string set on a {spec.dtype} signal", fix=_FIX_SIGNALS
            )
        if not domain:
            raise RouteError(
                f"{where} declares an EMPTY string domain, which no literal can satisfy;"
                " omit `domain` to leave it unbounded",
                fix=_FIX_SIGNALS,
            )
    elif isinstance(domain, ComputedDomain) and spec.dtype != "str":
        raise RouteError(
            f"{where} declares the computed domain {domain.value!r} on a {spec.dtype} signal",
            fix=_FIX_SIGNALS,
        )
    if spec.kind == "classifier" and domain != CLASSIFIER_DOMAIN:
        raise RouteError(
            f"RT5: {where} is a classifier whose domain is {domain!r} and not"
            f" {list(CLASSIFIER_DOMAIN)} closed on both ends -- a softmax returns 0.0 and 1.0",
            fix=_FIX_SIGNALS,
        )


# --------------------------------------------------------------------------------------------
# 2. `Evidence`. The read log, and nothing a rule could walk back through.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Cell:
    """One computed value. Not exported: a caller holding a `_Cell` would have a mapping."""

    value: Scalar
    provider_version: str
    unavailable_reason: str | None


class Evidence:
    """The flat, namespaced, scalar-valued record of Signal values for ONE `(unit, part)`.

    05:1858-1863, verbatim: *"NOT a frozen dataclass, and not a Mapping. It is a handle over a read
    log that the demand plan fills group by group, so freezing it would say something false about
    what it holds -- the same reason `Doc` and `Grid` are not dataclasses. There is no
    `__getitem__`, no `keys()`, no `items()` and no `__contains__`: a third party must be able to
    add `garble.acme_blur` without a core release, and the policy must be able to name a key core
    has never heard of, so the accessor is by string and the registry does the checking."*

    The absences are the design and a test asserts each of them by name. A `__contains__` would
    let a rule branch on whether a key was computed without reading it, which is exactly the
    declaration-instead-of-observation that `read_set_digest` exists to rule out; `keys()` would
    let `evaluate()` enumerate the record and behave differently on a machine with one more
    provider installed, which is a purity break that no semgrep rule could see.

    `__slots__` is 05:1865's, verbatim -- and it is also what makes the absences hold: a subclass
    cannot quietly add a `__dict__` and stash a `RunContext` on the instance.
    """

    __slots__ = ("_read", "_scope", "_v")

    def __init__(self, *, content_sha256: str, unit_part: str = "") -> None:
        """`_scope` is the `(content_sha256, unit_part)` this record is for. 05:1856's "ONE".

        Keyed on CONTENT and not on `unit_uri`, the same key `route_signal` and
        `route_decision_identity` use (05:1915, :2345): *"the same PDF in three folders is one
        decision and one parse."* `unit_part` is `''` for a unit-grain record, *"because NULLs are
        distinct in a UNIQUE index"* -- so the empty string folds the NULL here too rather than
        leaving two spellings for one scope.

        The scope is carried and never read by `read()`. It is here so a cache writer can address
        `route_signal` rows without a second argument, and so a record cannot be filled from one
        part and evaluated for another.
        """
        self._scope: tuple[str, str] = (content_sha256, unit_part)
        self._v: dict[str, _Cell] = {}
        self._read: list[str] = []

    @property
    def scope(self) -> tuple[str, str]:
        """`(content_sha256, unit_part)`. A tuple, so a caller cannot rebind half of it."""
        return self._scope

    # ---- the only accessor. Reading is what puts a key in the read set (RT3). ----

    def read(self, key: str) -> Scalar:
        """The value, or `None` for UNKNOWN. APPENDS to the read log.

        05:1869-1873: *"Returns `None` for UNKNOWN -- uncomputable, no provider for this format, or
        the provider raised or timed out. Three-valued: `None` is not a default and compares equal
        to nothing. APPENDS to the read log, so the read set is an OBSERVATION and not a
        declaration a programmer can forget to update."*

        A key read twice appears in the read set ONCE, at its first position. Rules are tested in
        file order and several of them legitimately read `unit.format`; a log that recorded each
        would make `read_set_digest` a function of how many rules happened to be tested before the
        winner, which is a property of the policy's layout rather than of the evidence.
        """
        cell = self._v.get(key)
        if key not in self._read:
            self._read.append(key)
        return None if cell is None else cell.value

    def computed(self, key: str) -> bool:
        """Whether a group holding `key` has already run. NOT a read, and never in the read set.

        05:1874-1878: *"'computed and unavailable' against 'not computed yet'.
        `DemandPlan.deferrals_pending(ev)` is the ONLY caller, and it must not go through
        `read()`: a planner probe is not a read and may not enter the read set."*

        The distinction is mechanical here rather than conventional: `put()` records a cell even
        when the value is `None`, so "we tried and could not" is a present cell with a reason and
        "not computed yet" is an absent one. Both `read()` as `None`.
        """
        return key in self._v

    def unavailable_reason(self, key: str) -> str | None:
        """Why a computed key is `None`, for `Degradation(kind="signal_unavailable")`.

        05:1130 requires the degradation to name *"the key and its provider"*, and 05:2352 requires
        the reason to survive into `route_signal` *"because 'we tried and could not' is a cacheable
        fact -- otherwise every run re-attempts a signal whose provider is not installed."* Like
        `computed()`, a probe and not a read: the degradation is written after the decision, and a
        read at that point would change the digest of a row already inserted.
        """
        cell = self._v.get(key)
        return None if cell is None else cell.unavailable_reason

    def read_set(self) -> tuple[tuple[str, str, Scalar], ...]:
        """`(key, provider_version, value)` triples, IN READ ORDER, for the current window.

        05:1880-1882: *"`provider_version` is the version of the provider section 5.2's per-format
        resolution actually chose, which is why an `officexml` bump does not invalidate a PDF
        decision."*

        A key that was read but never computed contributes `("", None)` -- the empty version is
        honest, because no provider produced the value, and the triple must still be present: the
        decision depended on that key being UNKNOWN, and a read set that omitted it would give the
        same identity to a decision taken when the key was available.
        """
        out: list[tuple[str, str, Scalar]] = []
        for key in self._read:
            cell = self._v.get(key)
            version = "" if cell is None else cell.provider_version
            out.append((key, version, None if cell is None else cell.value))
        return tuple(out)

    def read_set_digest(self) -> str:
        """`sha256_canonical(read_set())`. One of the eight identity columns (05:1885).

        `canonical()` rejects NaN and Infinity outright, which is stronger than the
        `allow_nan=False` 05:1885 asks for and is the property that matters: a NaN in a read set
        would digest to a stable string while comparing equal to nothing, so two decisions taken on
        two different broken values would share an identity.

        The triples are rendered as lists because canonical JSON has no tuple, and the value's own
        type is preserved -- `True` is not `1` -- so a bool signal and an int signal that happen to
        agree do not collide.
        """
        return sha256_canonical([[key, version, value] for key, version, value in self.read_set()])

    def clear_read_log(self) -> None:
        """Start a new read window. The sixth method, and the module docstring argues for it.

        Called by W5.2's rung loop immediately before the `evaluate()` whose `RouteDecision` is
        written, so that `read_set()` is *"for the winning path and nothing else"* (05:1880). It
        clears the LOG and never the values: re-computing a `CostClass` group because the digest
        was reset would be the opposite of what the demand plan is for.
        """
        self._read.clear()

    # ---- the only writer, and it is never called from `route/eval.py` ----

    def put(
        self,
        key: str,
        value: Scalar,
        *,
        provider_version: str,
        unavailable_reason: str | None = None,
    ) -> None:
        """Record a computed value. Three callers, all outside `evaluate()` (05:1888-1897).

        The signal computer as each `CostClass` group runs; the compiler's pre-evaluation
        resolution probe, which writes one `driver.unavailable` boolean per reachable driver *"so
        `evaluate()` needs no live `resolve()`"*; and `admit()`, which writes `budget.exhausted` --
        *"the single channel by which budget reaches routing (RT9, section 6.4)"*.

        **Refuses to change a value the current window has already read.** Not a general
        immutability rule -- `admit()` writes `budget.exhausted` between one rung's decision and the
        next's, and the loop clears the log in between, so that write is legal by construction.
        What it refuses is the case where the refusal is the only thing standing between a written
        `route_decision` row and a `read_set_digest` describing a state that never existed.

        A `None` value with no reason is refused too. 05:2352 makes the reason a cacheable fact;
        an unexplained `None` is indistinguishable from a provider that returned nothing on
        purpose, and `route_signal` would cache the silence.
        """
        if value is None and not unavailable_reason:
            raise RouteError(
                f"{key!r} was put UNKNOWN with no `unavailable_reason`; 05:2352 caches the reason",
                fix=_FIX_SIGNALS,
            )
        if value is not None and unavailable_reason:
            raise RouteError(
                f"{key!r} was put {value!r} AND an `unavailable_reason`; it is one or the other",
                fix=_FIX_SIGNALS,
            )
        seen = self._v.get(key)
        if key in self._read and seen is not None and seen.value != value:
            raise RouteError(
                f"{key!r} was read as {seen.value!r} in this window and is now being put"
                f" {value!r}; the read set already written would describe a state that never was",
                fix=_FIX_SIGNALS,
            )
        self._v[key] = _Cell(value, provider_version, unavailable_reason)


# --------------------------------------------------------------------------------------------
# 3. The registry, and per-format resolution.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignalRegistry:
    """Every `SignalSpec` on the machine, indexed for the one question a reader asks.

    The question is `(key, unit.format) -> which provider, at which version`, and 05:2222 gives
    the three rules that make it answerable: *"Registration refuses an overlapping claim ... A
    format no provider claims yields UNKNOWN, which is the three-valued path and not a default.
    And the read set records the resolved provider's version, so `read_set_digest` still names
    exactly which code produced each value and a decision taken on a PDF is not invalidated by an
    `officexml` version bump."*

    Built by `build_registry()` and never mutated, so `resolve()` takes no lock and the whole
    object is safe to share across the threads `omniweave.run` already has.
    """

    specs: tuple[SignalSpec, ...]
    _named: Mapping[str, Mapping[str, SignalSpec]] = field(repr=False)
    _fallback: Mapping[str, SignalSpec] = field(repr=False)

    def keys(self) -> tuple[str, ...]:
        """Every registered key, sorted. `ow route lint` check 1 resolves against this.

        A `tuple` and not a view: the registry is what a policy is compiled against, and a caller
        holding a live view of it would be holding something that cannot change but looks as
        though it could.
        """
        return tuple(sorted(set(self._named) | set(self._fallback)))

    def providers(self) -> tuple[str, ...]:
        """Every provider name that registered at least one key, sorted."""
        return tuple(sorted({spec.provider for spec in self.specs}))

    def specs_for(self, key: str) -> tuple[SignalSpec, ...]:
        """Every row for one key, in provider order. What `ow route lint --explain` prints."""
        return tuple(sorted((s for s in self.specs if s.key == key), key=lambda s: s.provider))

    def requires_of(self, key: str) -> tuple[Rung, ...]:
        """The `req` column for one KEY, independent of format. `()` for an unregistered key.

        **Format-independent on purpose, and the alternative is a bug.** `requires` is one of the
        seven columns 05 section 5.1's table gives per KEY rather than per provider, and
        `build_registry()` refuses a disagreement (D199) -- so any spec for the key answers. Going
        through `resolve(key, format)` instead would return `None` for a format no provider serves
        and read that as "requires nothing", which makes a RULE's derived phase depend on the unit's
        format: `decode.admit-table-lane` reads `block.type`, which has no PDF row (05:2162), so it
        would be a `select` rule on a PDF and a `settle` rule on a DOCX. Section 4.3 builds ONE
        demand plan per `(rung, lane, phase)` at policy-compile time and memoises it on
        `(policy_digest, caps_digest)` -- neither of which carries a format. D205.
        """
        specs = self.specs_for(key)
        return specs[0].requires if specs else ()

    def nullable_of(self, key: str) -> bool:
        """The `null` column for one KEY, independent of format. `True` for an unregistered key.

        Format-independent for `requires_of()`'s reason: `nullable` is a per-KEY column and
        `build_registry()` refuses a disagreement. An UNREGISTERED key answers `True`, which is the
        conservative direction and the one 05:2222's three-valued rule implies -- a key no provider
        serves yields UNKNOWN, so a rule reading `layout.class_hist` (absent at release 1 by design)
        needs an `on_unknown` for exactly the reason a nullable key does.
        """
        specs = self.specs_for(key)
        return specs[0].nullable if specs else True

    def dtype_of(self, key: str) -> str:
        """The `dtype` column for one KEY, independent of format. `""` for an unregistered key.

        `requires_of()`'s argument again -- `dtype` is per KEY and `build_registry()` refuses a
        disagreement. The subsumption linter reads it to decide whether a key's values form an
        interval or a finite set, and a key whose dtype moved with the corpus would put one rule in
        two algebras.
        """
        specs = self.specs_for(key)
        return specs[0].dtype if specs else ""

    def domain_of(self, key: str) -> Domain:
        """The `domain` column for one KEY, independent of format. `None` for an unregistered key.

        `None` is genuinely ambiguous here and the ambiguity is the plan's: 05:2101 gives it to
        *"a bool or an unbounded int"*, and an unregistered key lands on the same value. Callers
        that need the difference read `dtype_of()` alongside, which is what `lint._universe()`
        does -- a `bool` has the two-member universe its dtype implies and no `domain` column, and
        an unbounded int has no universe at all.
        """
        specs = self.specs_for(key)
        return specs[0].domain if specs else None

    def resolve(self, key: str, format_token: str) -> SignalSpec | None:
        """The row that serves `key` for a unit of this format, or `None` for UNKNOWN.

        Two steps, and the order is the whole of the module docstring's argument: the row that
        NAMES this format wins, then the row that names none, then nothing. `None` is the
        three-valued path -- 05:2222's *"A format no provider claims yields UNKNOWN"* -- and not an
        error, because a corpus containing one `mp4` must not fail to route on the grounds that no
        provider computes `decode.cid_ratio` for it.
        """
        named = self._named.get(key)
        if named is not None:
            hit = named.get(format_token)
            if hit is not None:
                return hit
        return self._fallback.get(key)


def build_registry(specs: Iterable[SignalSpec]) -> SignalRegistry:
    """Index the rows and refuse every collision. `OW-P-022`, at startup.

    05:2219: *"two providers naming the same `(key, format)` is `OW-P-022` at startup, not a
    precedence puzzle."* Four collisions are refused and each is that sentence applied once:

    1. two rows naming the same `(key, format)` -- the plan's own case;
    2. two FALLBACK rows for one key, which name every format and therefore name each other's;
    3. two rows for the same `(key, provider)`, which is one provider registering a key twice and
       is the case `serves` cannot disambiguate because both rows are the same provider's;
    4. two rows for one key disagreeing about one of the seven columns 05 section 5.1's table gives
       per KEY. That one is not in the plan and D199 files it: `scope`, `kind`, `dtype`, `domain`,
       `cost_class`, `nullable` and `requires` describe the signal, not its provider, and three
       files restate them for `unit.part_count` with nothing checking they agree.

    Refusing at startup rather than at read time is the point: a per-format collision that fired
    only on the corpus containing that format would be a routing bug that appears on one machine.
    """
    rows = tuple(specs)
    named: dict[str, dict[str, SignalSpec]] = {}
    fallback: dict[str, SignalSpec] = {}
    by_provider: dict[tuple[str, str], SignalSpec] = {}
    for spec in rows:
        _check_agreement(spec, rows)
        prior = by_provider.get((spec.key, spec.provider))
        if prior is not None:
            raise _conflict(spec, prior, f"provider {spec.provider!r} registers it twice")
        by_provider[spec.key, spec.provider] = spec
        if not spec.serves:
            clash = fallback.get(spec.key)
            if clash is not None:
                raise _conflict(spec, clash, "both name no format, so both serve every format")
            fallback[spec.key] = spec
            continue
        slot = named.setdefault(spec.key, {})
        for token in sorted(spec.serves):
            clash = slot.get(token)
            if clash is not None:
                raise _conflict(spec, clash, f"both serve the format {token!r}")
            slot[token] = spec
    return SignalRegistry(
        specs=rows,
        _named=MappingProxyType({k: MappingProxyType(v) for k, v in named.items()}),
        _fallback=MappingProxyType(fallback),
    )


def _check_agreement(spec: SignalSpec, rows: Sequence[SignalSpec]) -> None:
    """Rule 4 of `build_registry()`: the seven per-KEY columns must agree across providers."""
    for other in rows:
        if other.key != spec.key or other is spec or other.provider == spec.provider:
            continue
        for name in _KEY_FIELDS:
            mine, theirs = getattr(spec, name), getattr(other, name)
            if mine != theirs:
                raise _conflict(
                    spec,
                    other,
                    f"they disagree about {name}: {mine!r} against {theirs!r}."
                    " 05 section 5.1's table has one row per KEY and that column is on it",
                )


def _conflict(spec: SignalSpec, other: SignalSpec, why: str) -> PolicyRefusal:
    """One message shape for every `OW-P-022`, naming both rows and both origins.

    Both origins, because the reader's next move is to open one of the two files, and a message
    that names only the loser sends them to the wrong one half the time.
    """
    return PolicyRefusal(
        f"OW-P-022: {spec.key!r} is claimed by {spec.provider!r}"
        f" ({spec.origin or 'unnamed'}) and by {other.provider!r}"
        f" ({other.origin or 'unnamed'}): {why}",
        symbol="OW_SIGNAL_PROVIDER_CONFLICT",
        fix=_FIX_SIGNALS,
    )


# --------------------------------------------------------------------------------------------
# 4. The loader. `tomllib` and nothing else -- INV-4, applied to providers.
# --------------------------------------------------------------------------------------------


def load_signals(raw: bytes, *, provider: str, origin: str) -> tuple[SignalSpec, ...]:
    """Parse one `signals.toml`. Executes no provider code and imports nothing.

    05:2041: *"Registration is a `SignalSpec` row read from a `signals.toml` by the same
    import-free `tomllib` loader that reads a `DriverCard`, so registration executes no provider
    code -- INV-4's rule, applied to providers."*

    `provider` is the entry-point name and is the DEFAULT for each row rather than a constant: 05
    section 5.1's table gives `budget.exhausted` the provider `admit()`, which is a function in
    this process and not a package, so a row may name a `RESERVED_PROVIDERS` member explicitly.
    A row naming any other provider than its file's is refused -- that is a distribution
    registering on another's behalf, and `read_set_digest` would then name a version nothing on the
    machine can be checked against.

    Raises `RouteError` on anything malformed. Unlike `omniweave_core.discovery`, which *"never
    raises"* because a broken neighbour cannot stop a catalog, a broken `signals.toml` DOES stop:
    discovery's failure mode is one driver missing from a catalog that still routes, and this one
    is a policy compiled against a registry missing a key its rules name. The linter would then
    report `OW-P-001` on a rule the operator wrote correctly.
    """
    try:
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RouteError(f"{origin} is not readable TOML: {exc}", fix=_FIX_SIGNALS) from exc
    table = parsed.get(SIGNAL_TABLE)
    if table is None:
        return ()
    if not isinstance(table, dict):
        raise RouteError(f"{origin}: [{SIGNAL_TABLE}] is not a table", fix=_FIX_SIGNALS)
    return tuple(
        _spec(key, body, provider=provider, origin=origin) for key, body in sorted(table.items())
    )


def _spec(key: str, body: object, *, provider: str, origin: str) -> SignalSpec:
    """One `[signal."<key>"]` block. 05:2207's shape, every field validated at its own type."""
    where = f'{origin}: [{SIGNAL_TABLE}."{key}"]'
    if not isinstance(body, dict):
        raise RouteError(f"{where} is not a table", fix=_FIX_SIGNALS)
    declared = _text(body, "provider", where, default=provider)
    if declared != provider and declared not in RESERVED_PROVIDERS:
        raise RouteError(
            f"{where} declares provider {declared!r} in {provider!r}'s file; a distribution"
            " registers only its own rows",
            fix=_FIX_SIGNALS,
        )
    return SignalSpec(
        key=key,
        scope=_text(body, "scope", where),
        kind=_text(body, "kind", where),
        dtype=_text(body, "dtype", where),
        domain=_domain(body.get("domain"), where),
        cost_class=_cost_class(body, where),
        est=_est(body.get("est"), where),
        provider=declared,
        version=_text(body, "version", where),
        serves=frozenset(_str_list(body.get("serves", []), "serves", where)),
        requires=_requires(body.get("requires", []), where),
        nullable=_flag(body, "nullable", where),
        origin=origin,
    )


def _text(body: Mapping[str, object], name: str, where: str, *, default: str | None = None) -> str:
    value = body.get(name, default)
    if not isinstance(value, str) or not value:
        raise RouteError(f"{where} needs a non-empty string `{name}`", fix=_FIX_SIGNALS)
    return value


def _flag(body: Mapping[str, object], name: str, where: str) -> bool:
    value = body.get(name, True)
    if not isinstance(value, bool):
        raise RouteError(f"{where}: `{name}` is {value!r} and not a boolean", fix=_FIX_SIGNALS)
    return value


def _cost_class(body: Mapping[str, object], where: str) -> CostClass:
    """The `cost` column. The demand plan groups by it ASCENDING (05:2103), so the value has to be
    the same enum `COST_CLASS_ORDER` indexes and not a second three-member vocabulary."""
    raw = _text(body, "cost_class", where)
    try:
        value = CostClass(raw)
    except ValueError as exc:
        listed = ", ".join(member.value for member in COST_CLASS_ORDER)
        raise RouteError(
            f"{where}: cost_class {raw!r} is not one of {listed}", fix=_FIX_SIGNALS
        ) from exc
    return value


def _domain(raw: object, where: str) -> Domain:
    """Four shapes, distinguished by what was written rather than by a tag.

    A two-element list of numbers is the inclusive interval; a list of strings is the literal set;
    the bare string `"format_tokens"` is the `ComputedDomain`; absent is unbounded. An empty list
    is refused rather than read as either, because `domain = []` is the one spelling that could
    plausibly mean "no members" or "no bound" and the two are opposites.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return ComputedDomain(raw)
        except ValueError as exc:
            listed = ", ".join(member.value for member in ComputedDomain)
            raise RouteError(
                f"{where}: domain {raw!r} is not a computed domain ({listed})", fix=_FIX_SIGNALS
            ) from exc
    if not isinstance(raw, list) or not raw:
        raise RouteError(
            f"{where}: domain is {raw!r}; write [low, high], a list of literals,"
            ' "format_tokens", or omit it',
            fix=_FIX_SIGNALS,
        )
    if all(isinstance(item, str) for item in raw):
        return frozenset(str(item) for item in raw)
    numeric = all(isinstance(item, int | float) and not isinstance(item, bool) for item in raw)
    if numeric and len(raw) == _INTERVAL_ENDS:
        low, high = raw
        return (float(low), float(high))
    raise RouteError(
        f"{where}: domain {raw!r} is neither a list of literals nor a [low, high] pair",
        fix=_FIX_SIGNALS,
    )


def _est(raw: object, where: str) -> Spend:
    """`est = { cpu_ms = 1 }` -- 05:2216's literal shape, over `Spend`'s seven dimensions.

    A declared budget, and every key is checked against `DIMS` so that `est = { cpu_sec = 1 }`
    fails the load rather than declaring nothing. `provider` is not accepted: a signal's cost is
    the machine's, and `Spend.provider` is `""` for local (05:2373).
    """
    if raw is None:
        return Spend()
    if not isinstance(raw, dict):
        raise RouteError(f"{where}: `est` is {raw!r} and not a table", fix=_FIX_SIGNALS)
    unknown = sorted(set(raw) - set(DIMS))
    if unknown:
        raise RouteError(
            f"{where}: `est` names {', '.join(unknown)}, which is not one of {', '.join(DIMS)}",
            fix=_FIX_SIGNALS,
        )
    for dim, value in raw.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RouteError(
                f"{where}: est.{dim} is {value!r}; Spend's dimensions are non-negative integers",
                fix=_FIX_SIGNALS,
            )
    return Spend(**raw)


def _requires(raw: object, where: str) -> tuple[Rung, ...]:
    """The `req` column: *"rungs whose DRIVER OUTPUT this signal reads"* (05:2116).

    Sorted by ordinal and deduplicated, because it is compared: 05:1140 derives a rule's phase from
    whether ANY key in its read set has this rung in `requires`, and check 7 rejects a rule reading
    a key that requires a rung strictly greater than its own. Order in the file is the author's;
    order in the type is the ladder's.
    """
    names = _str_list(raw, "requires", where)
    unknown = sorted(set(names) - set(RUNG_BY_NAME))
    if unknown:
        raise RouteError(
            f"{where}: requires names {', '.join(unknown)};"
            f" the seven rungs are {', '.join(RUNG_BY_NAME)}",
            fix=_FIX_SIGNALS,
        )
    return tuple(sorted({RUNG_BY_NAME[name] for name in names}))


def _str_list(raw: object, name: str, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise RouteError(
            f"{where}: `{name}` is {raw!r} and not a list of strings", fix=_FIX_SIGNALS
        )
    return tuple(str(item) for item in raw)


# --------------------------------------------------------------------------------------------
# 5. Where the files are. Package data for ours; `locate_file` for everyone else's.
# --------------------------------------------------------------------------------------------

BUILTIN_SIGNALS: Final[Path] = Path(__file__).with_name(SIGNALS_FILENAME)
"""`omniweave/route/signals.toml` -- the `builtin` provider's rows, as package data.

`Path(__file__).with_name(...)` and not `importlib.resources`, matching how this repository already
ships `driver.toml` beside `driver.py`: the file is a sibling of the module that documents it, so a
reader who has one has the other. A zip-safe install would need the resources API; nothing in this
framework is zip-safe, because `omniweave_core.discovery` locates every card as a filesystem path.
"""


def signals_relative_path(value: str) -> str:
    """`"omniweave_pdf"` -> `"omniweave_pdf/signals.toml"`. `card_relative_path`'s twin.

    Forward slashes even on Windows, because `Distribution.locate_file` joins through `pathlib`,
    which accepts them on every platform. 04:the card-location expression, with one filename
    changed; the caller has already checked the value against `discovery.PACKAGE_PATH_RE`, so this
    is the join and nothing else.
    """
    return value.replace(".", "/") + "/" + SIGNALS_FILENAME


def builtin_specs() -> tuple[SignalSpec, ...]:
    """The `builtin` provider's rows. Read from disk on every call, and deliberately not cached.

    A policy is compiled once per run (05:1084), so this is read once per run, and a module-level
    cache would make `ow route lint` in a long-lived process serve the registry the file had when
    the process started -- which is precisely the loop an author editing `signals.toml` is in.
    `omniweave_core.discovery` prices its own cache against a measurement; this one has no
    measurement to price it against, so it does not have one.
    """
    return load_signals(
        BUILTIN_SIGNALS.read_bytes(),
        provider=BUILTIN_PROVIDER,
        origin=f"{BUILTIN_PROVIDER}:{SIGNALS_FILENAME}",
    )


@dataclass(frozen=True, slots=True)
class Installed:
    """What `installed_specs()` found, and what it could not read. `discovery`'s shape, narrowed.

    Two fields rather than a bare tuple because the second is not an error path a caller may
    ignore: `missing` is non-empty on **every developer checkout in this repository**, for the
    reason D128 files -- an editable install writes a `.pth` shim and leaves `site-packages` empty,
    so `Distribution.locate_file` joins against a directory the package is not in. The same call
    returns a non-existent path for `driver.toml` today (`omniweave_core.discovery` records it as a
    `card_missing` fault and carries on), so this is the mechanism the plan prescribes behaving as
    the plan's own §4.3 anticipates, not a new failure.
    """

    specs: tuple[SignalSpec, ...]
    missing: tuple[str, ...]
    """One line per provider whose `signals.toml` could not be read, naming the path tried."""


def installed_specs(distributions: Iterable[Distribution]) -> Installed:
    """Every third-party provider's rows, located by NAME and never by walking `Distribution.files`.

    `Distribution.locate_file(signals_relative_path(value))`, one path join per provider --
    04-driver-system.md section 4.1's rule, and its measurement is the reason: scanning `RECORD`
    for declarations was **2124 ms** for 328 installed distributions against a claimed 1-4 ms.

    **Three failures, and they are not the same failure.**

    A `signals.toml` that is ABSENT is *reported*, not raised. `omniweave_core.discovery` makes the
    same call for `driver.toml` and *"never raises"* because *"a broken neighbour cannot stop a
    catalog"*, and the reason applies with more force here: D128 establishes that an editable
    install makes every first-party package's data unreachable by this route, so raising would make
    `ow route lint` fail on every checkout of this repository including this one. What it must not
    do is stay silent -- a policy compiled against a registry missing keys its rules name reports
    `OW-P-001` on a rule the operator wrote correctly -- so the reason comes back in `missing` and
    the caller prints it.

    A `signals.toml` that is PRESENT and malformed raises, because that is a defect in a file whose
    author can fix it and skipping it hides the fix behind a lint error somewhere else.

    A DECLARATION error raises: an entry point whose NAME is a `RESERVED_PROVIDERS` member (`admit`
    names a function in this process, and a distribution claiming it would put a locatable package
    behind a name that has none), and a VALUE that fails `discovery.PACKAGE_PATH_RE` -- that
    module's own rule and its own reasoning, that a value with a leading empty segment makes
    `Path(parent) / "//signals.toml"` an ABSOLUTE path and the join escapes the distribution.
    """
    out: list[SignalSpec] = []
    missing: list[str] = []
    for dist, name, value in _signal_entry_points(distributions):
        if name in RESERVED_PROVIDERS:
            raise RouteError(
                f'[{SIGNAL_GROUP}] "{name}" is a reserved provider name and names no package',
                fix=_FIX_SIGNALS,
            )
        if not PACKAGE_PATH_RE.match(value):
            raise RouteError(
                f'[{SIGNAL_GROUP}] "{name}" = "{value}" is not a colon-free dotted package path',
                fix=_FIX_SIGNALS,
            )
        located = Path(dist.locate_file(signals_relative_path(value)))
        try:
            raw = located.read_bytes()
        except OSError:
            missing.append(f'[{SIGNAL_GROUP}] "{name}" = "{value}": no file at {located}')
            continue
        out.extend(load_signals(raw, provider=name, origin=f"{name}:{located}"))
    return Installed(specs=tuple(out), missing=tuple(missing))


def _signal_entry_points(
    distributions: Iterable[Distribution],
) -> tuple[tuple[Distribution, str, str], ...]:
    """Every `SIGNAL_GROUP` row, with **no `EntryPoint.load()`**.

    `Distribution.entry_points` parses `entry_points.txt` and nothing else -- the same read
    `omniweave_core.discovery.entry_point_refs` performs, and the reason that function is not
    called here is that it returns `EntryPointRef`s without the `Distribution`, and locating the
    file needs the distribution it came from.
    """
    rows: list[tuple[Distribution, str, str]] = []
    for dist in distributions:
        for entry in dist.entry_points:
            if entry.group == SIGNAL_GROUP:
                rows.append((dist, entry.name, entry.value))
    return tuple(rows)
