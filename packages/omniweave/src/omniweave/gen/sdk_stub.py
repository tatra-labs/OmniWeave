"""Artefact 4: `omniweave/sdk/_generated.pyi`. 10 section 2.3 row 4; 18 section 1; 11:249.

10:211's row: generated from *"`inp`, `out`, `name`"*, consumed by *"mypy, IDEs, `ow surface
typescript`"*. 18:63 adds the half that column leaves out: the stub *"is emitted from
`ACTIONS` **plus these declaration sites**"* -- 18 section 1.1's four entry points,
section 1.2's `Corpus` and section 1.6's re-export table.

02:212 is what makes it a gate rather than documentation: `T-PUBLIC` is *"semver'd with `RELEASE`,
documented, SDK-typed"*, **proved by** *"`omniweave/sdk/_generated.pyi` byte-diff (G25)"*. So the
stub is the evidence for every stability promise the SDK makes, and 11:1103 spends it: a `@stable`
symbol may not be removed without a MAJOR, and *"`_generated.pyi` is byte-diff gated so the tier is
checked in the same PR as the change"*.

## A STUB MAY NOT DECLARE A SYMBOL THE PACKAGE DOES NOT EXPORT

That is the whole of this renderer's discipline and it is INV-20's, not a style choice. A stub is
read by a type checker and by `ow surface typescript`; one that declared `omniweave.sdk.corpus` on a
package with no `corpus` would make `corpus("handbook")` type-check and fail at runtime with an
`AttributeError`. A machine-readable manifest that over-declares its server is LEANN's `llms.txt`
exactly -- two tools against four -- and G25 is named after that defect (00:851).

So `render()` emits exactly `omniweave.sdk.__all__`, and `_stub_failures()` raises at import if the
two ever disagree in either direction. The stub cannot over-declare, and it cannot quietly fall
behind either: a symbol added to the package and not to the stub fails the same check.

Today that is nine report types, four of which are the `out` of a landed Action. 18 section 1.1's
`corpus()`, `corpora()`, `doctor()` and `explain()` and section 1.2's whole `Corpus` handle are
printed by the plan and exported by nothing, because the dispatcher they call does not exist --
D323's gap, reached from the SDK side rather than from the CLI's. `owed()` is the register of what
the stub will declare on the day it can.

## `SDK_HOMES`: WHERE EACH ACTION SURFACES, AND WHAT ITS SIGNATURE ACTUALLY IS

10:211 says the stub is generated from `inp`, `out` and `name`. Read against 18 section 1's own
printed signatures that is true of **two** of the seven Actions with a printed SDK spelling:
`doctor(*, runtime: bool = False)` and `explain(code: str)` match `DoctorIn` and `ExplainIn` field
for field. The other five do not, and `_mismatches()` prints each difference rather than describing
it. D324 is the entry; the shapes are worth naming here because each is a different KIND of
difference:

* **a rename** -- `QueryIn.query` is `Corpus.query(text=...)`;
* **a wider surface** -- the SDK adds `refs`, `filters`, `mode`, `k`, `max_blocks` and `expand` to
  `query`, `raw` and `want_impact` to `open`, and `schema`, `allow_cost`, `allow_egress` and
  `wait_ms` to `add`, none of which is a declared parameter;
* **a NARROWING** -- `CoverageIn` declares `scope` and 18:464's `Corpus.coverage()` takes no
  arguments at all, so the SDK cannot ask the question the Action declares;
* **a different operation under one name** -- `CorporaIn` is `(corpus, detail)` and 18:180's
  `corpora()` is `(names, config)`, which is the shape Open question 1 already records.

`SDK_HOMES` is that table, transcribed, and `_mismatches()` is the reporter over it. Reported and
not raised, for `_unrostered_full()`'s reason one package over: a signature the plan prints and the
registry spells differently is a defect in a DOCUMENT, and making the generator unimportable for it
would stop the other six artefacts over a disagreement no code can resolve.
"""

from __future__ import annotations

from dataclasses import fields
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import SurfaceError

from omniweave import sdk as _sdk
from omniweave.sdk import reports as _reports
from omniweave.surface.registry import ACTIONS

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "HANDLE_PARAM",
    "SDK_HOMES",
    "SOURCES",
    "SdkHome",
    "exported",
    "owed",
    "render",
]


HANDLE_PARAM: Final[str] = "corpus"
"""The one `inp` field a `Corpus` method never takes: the handle already is the corpus.

18:261 makes `Corpus` *"a lazy handle"* carrying `name`, so `Corpus.query` has no `corpus`
parameter and `QueryIn.corpus` is not a missing argument. `_mismatches()` subtracts it before
comparing, so the differences it reports are real ones.
"""


class SdkHome:
    """Where one Action surfaces in `omniweave.sdk`, and the signature the plan prints for it."""

    __slots__ = ("holder", "parameters", "symbol")

    def __init__(self, holder: str, symbol: str, parameters: tuple[str, ...]) -> None:
        self.holder = holder
        self.symbol = symbol
        self.parameters = parameters

    def __repr__(self) -> str:
        where = f"{self.holder}." if self.holder else ""
        return f"{where}{self.symbol}({', '.join(self.parameters)})"


SDK_HOMES: Final[Mapping[str, SdkHome]] = MappingProxyType(
    {
        "query": SdkHome(
            "Corpus",
            "query",
            (
                "text",
                "refs",
                "scope",
                "want",
                "filters",
                "mode",
                "k",
                "max_blocks",
                "max_chars",
                "expand",
                "route_hints",
            ),
        ),
        "open": SdkHome(
            "Corpus",
            "open",
            ("ref", "context", "layers", "raw", "want_impact", "max_chars"),
        ),
        "add": SdkHome(
            "Corpus",
            "add",
            ("source", "dry_run", "schema", "allow_cost", "allow_egress", "wait_ms"),
        ),
        "corpora": SdkHome("", "corpora", ("names", "config")),
        "corpus.coverage": SdkHome("Corpus", "coverage", ()),
        "doctor": SdkHome("", "doctor", ("runtime",)),
        "explain": SdkHome("", "explain", ("code",)),
    }
)
"""Each Action's SDK spelling, transcribed from 18:180, 18:211, 18:229, 18:267, 18:343, 18:399 and
18:464, with the parameters in their printed order and `self` dropped.

Seven of the nine landed Actions. `doc.grid` and `doc.diff` are not entry points: 18:500 routes the
document model through `Corpus.doc(ref) -> Doc` and gives `Doc` the accessors (*"`.grid()`"* among
them), whose signatures 03 section 13.5 owns and this document does not restate. So their absence is
a boundary rather than a gap, and `owed()` says which is which.
"""

_PRINTED_ENTRY_POINTS: Final[tuple[str, ...]] = (
    "Corpus",
    "corpus",
    "corpora",
    "doctor",
    "explain",
)
"""18 section 1.1's four module-level names plus section 1.2's class, in printed order.

None of them is exported today. They are listed so `owed()` names them rather than leaving a reader
to diff two documents, and so the day one lands, the stub's binding to `__all__` picks it up without
an edit here.
"""


# =============================================================================================
# 1. What the package exports, and what the plan is still owed
# =============================================================================================


def exported() -> tuple[str, ...]:
    """`omniweave.sdk.__all__`, sorted. The stub declares exactly this and nothing else."""
    return tuple(sorted(_sdk.__all__))


_SOURCE_MODULES: Final[tuple[tuple[str, object], ...]] = (("omniweave.sdk.reports", _reports),)
"""The modules `omniweave/sdk/__init__.py` re-exports from, paired with the module object.

Imported statically rather than looked up with `importlib.import_module`, which the semgrep bank
bans outside `host/` (INV-4, G11: discovery must never import a driver). `tools/schemagen.py` takes
the opposite route and says why it may -- it is a `tools/` script and the ban is scoped to the
package -- and this module is inside the package, so the rule applies to it. A static import is the
better shape here anyway: a second source module is a real edit to this file, which is exactly what
the docstring below claims it is.
"""

SOURCES: Final[tuple[str, ...]] = tuple(name for name, _ in _SOURCE_MODULES)
"""The module names, for the emitted import block and for a test to compare against."""


def _home_of(symbol: str) -> str:
    """The module `omniweave.sdk` re-exports `symbol` FROM -- not the module that defined it.

    Identity rather than `__module__`, and the difference is load-bearing: `Gap` is defined in
    `omniweave_core.store.card` and reaches the SDK through `omniweave.sdk.reports`, so
    `Gap.__module__` names a module `omniweave.sdk` does not import from. A stub must mirror the
    package's own import path, because that is the chain a type checker walks and the one a caller
    would write; naming the definition site would publish a second route to the same name and make
    the stub disagree with the package about where its surface comes from.
    """
    bound = getattr(_sdk, symbol, None)
    for module, source in _SOURCE_MODULES:
        if bound is not None and getattr(source, symbol, None) is bound:
            return module
    raise SurfaceError(
        f"omniweave.sdk exports {symbol!r} from a module this generator does not know",
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix="add the module to `_SOURCE_MODULES` in gen/sdk_stub.py so the stub can import it",
    )


def _stub_failures() -> tuple[str, ...]:
    """Every reason the stub could not be emitted truthfully.

    Two clauses, and they are the same rule read in both directions:

    1. a name in `__all__` that `omniweave.sdk` does not actually bind -- the package promising a
       symbol it does not have, which the stub would then repeat to a type checker;
    2. a name whose defining module this generator cannot import from, which would make the stub's
       import block a guess.

    Raised at import rather than reported, because both describe shipped source that is wrong: a
    stub emitted from either is a manifest that disagrees with its own server.
    """
    out: list[str] = []
    for symbol in exported():
        if not hasattr(_sdk, symbol):
            out.append(f"{symbol}: named in omniweave.sdk.__all__ and not bound by the package")
    return tuple(out)


_FAILURES: Final[tuple[str, ...]] = _stub_failures()
if _FAILURES:  # pragma: no cover -- the package agrees with itself; a test builds one that does not
    raise SurfaceError(
        "the SDK stub cannot be emitted from omniweave.sdk: " + "; ".join(_FAILURES),
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix="reconcile omniweave/sdk/__init__.py's __all__ with what the package binds",
    )


def owed() -> tuple[str, ...]:
    """Symbols 18 section 1 prints that `omniweave.sdk` does not export yet, sorted.

    Five today -- `Corpus`, `corpus`, `corpora`, `doctor` and `explain` -- and every one of them
    waits on the same thing: 02:719's ordered sequence, which the CLI needs for `main()` and the SDK
    needs for a method body. `sdk/__init__.py`'s own docstring said so at W7.1 (*"None of them
    exists yet -- they call `omniweave_core.retrieve.retrieve()` ... through a dispatcher that is
    W7.2's"*), and D323 records that no work item lands it.

    A register rather than a comment, so the distance is a number a test pins. The stub grows by
    itself when they arrive: `render()` reads `__all__`, so an entry point exported by the package
    is in the next byte diff without an edit to this module.
    """
    present = set(exported())
    return tuple(sorted(name for name in _PRINTED_ENTRY_POINTS if name not in present))


def _mismatches() -> tuple[str, ...]:
    """Every Action whose printed SDK signature is not its `inp` field list. D324.

    The comparison drops `HANDLE_PARAM` for a `Corpus` method, because the handle IS the corpus and
    its absence from the signature is the design rather than a difference. What is left is real:
    a parameter the Action declares and the SDK cannot pass, or one the SDK takes and the Action
    does not declare.
    """
    out: list[str] = []
    for name, home in SDK_HOMES.items():
        spec = ACTIONS[name]
        declared = {field.name for field in fields(spec.inp)}
        if home.holder == "Corpus":
            declared.discard(HANDLE_PARAM)
        published = set(home.parameters)
        only_declared = sorted(declared - published)
        only_published = sorted(published - declared)
        if not only_declared and not only_published:
            continue
        parts = []
        if only_declared:
            parts.append(f"{spec.inp.__name__} declares {', '.join(only_declared)}")
        if only_published:
            parts.append(f"the SDK takes {', '.join(only_published)}")
        out.append(f"{name} -> {home!r}: " + "; ".join(parts))
    return tuple(out)


def agreeing() -> tuple[str, ...]:
    """The Actions whose SDK signature IS their `inp` field list, sorted. Two of seven."""
    broken = {line.split(" ->", 1)[0] for line in _mismatches()}
    return tuple(sorted(name for name in SDK_HOMES if name not in broken))


# =============================================================================================
# 2. The bytes
# =============================================================================================

_WIDTH: Final[int] = 96


def _wrap(body: str, indent: str) -> list[str]:
    """`body` as comment lines that fit the line length. Used only for the generated table."""
    budget = _WIDTH - len(indent)
    lines: list[str] = []
    rest = body
    while rest:
        if len(rest) <= budget:
            lines.append(indent + rest)
            break
        cut = rest.rfind(" ", 0, budget)
        cut = budget if cut <= 0 else cut
        lines.append(indent + rest[:cut])
        rest = rest[cut:].lstrip()
    return lines


def _action_table() -> list[str]:
    """One docstring line per Action: its name, its input type and its result type.

    This is 10:211's `name`, `inp`, `out` in the artefact itself rather than only in the generator,
    so a reader of the stub can see which declaration each promise came from. It is prose inside a
    docstring and not a runtime mapping, because a stub declares types and holds no data.
    """
    rows = ["    name              inp                 out"]
    for name in sorted(ACTIONS):
        spec = ACTIONS[name]
        rows.append(f"    {name:<17} {spec.inp.__name__:<19} {spec.out.__name__}")
    return rows


def render() -> bytes:
    """`omniweave/sdk/_generated.pyi`'s committed bytes. Artefact 4's entry in `emit.RENDERERS`.

    Pure: `ACTIONS` and `omniweave.sdk.__all__`, and no clock, path or environment. 10:228 fixes
    the encoding -- *"`\\n`-terminated UTF-8 with no BOM"* -- and the explicit re-export form
    (`X as X`) is PEP 484's: in a stub, a plain `import` does not re-export, so the `as` is what
    makes each name part of `omniweave.sdk`'s public surface rather than an implementation detail
    a type checker would refuse to let a caller touch.
    """
    names = exported()
    # No `from __future__ import annotations`: a stub is never executed, so PEP 563's semantics
    # already hold inside it and the import would be a runtime statement in a file with no runtime.
    lines = [
        '"""The SDK\'s type surface. GENERATED by `ow surface emit`; do not edit.',
        "",
        "Artefact 4 of the seven (10 section 2.3), emitted from `ACTIONS` and from",
        "`omniweave.sdk.__all__` by `omniweave.gen.sdk_stub`, and byte-diff gated by G25.",
        "02:212 makes this file the PROOF of every `T-PUBLIC` promise the SDK makes, so a",
        "hand edit here is a stability claim nobody reviewed.",
        "",
        "It declares exactly what the package exports. A stub naming a symbol",
        "`omniweave.sdk` does not bind would make it type-check and fail at runtime, which",
        "is the defect G25 exists to catch -- so this file grows when the package does, and",
        "never before.",
        "",
        "The Actions this surface comes from, with the declaration behind each promise:",
        "",
        *_action_table(),
        '"""',
        "",
    ]
    grouped: dict[str, list[str]] = {}
    for symbol in names:
        grouped.setdefault(_home_of(symbol), []).append(symbol)
    for module in sorted(grouped):
        for symbol in sorted(grouped[module]):
            lines.append(f"from {module} import {symbol} as {symbol}")
    lines.extend(["", "__all__ = ["])
    lines.extend(f'    "{symbol}",' for symbol in names)
    lines.append("]")
    text = "\n".join(lines)
    return text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8") + b"\n"
