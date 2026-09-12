"""`Spend` -- seven physical units and a provider tag -- and the `PriceBook` that is the only price.

02-architecture.md section 2 row 35 homes `Spend` and `PriceBook` in `omniweave.route`, and row 10
names this module from the other side: `omniweave_core.operator`'s exclusion column is *"scheduling
(L5's) and pricing (`route/spend.py`'s)"*. 11-repo-layout.md:250 puts the file in the tree.
16-roadmap.md:545 schedules it with W4.5, beside the durable ledger it prices for.

**INV-15, in one sentence: `Spend.micros(book)` is THE ONLY PLACE MONEY APPEARS.** 05:2373 writes it
in capitals in the printed class, and every other site in the framework is downstream of it:
`DriverMetrics` has no currency field, `[cost.*]` on a card has none, `derive_run.spend` holds
*"canonical JSON of Spend. NO DOLLARS HERE"*, and `omniweave_core.store.graph.SpendVector` -- the
structural stand-in core reads this type through -- deliberately omits `micros()` so that a sink
cannot price. 05:2376 gives the reason it is one place and not several: *"a contributor on a rented
A100 cannot know your GPU-hour cost, and if they guess, every estimate in your fleet is wrong in a
way you cannot audit."*

## Seven units, and why `wall_ms` is one of them

05:2382-2385: *"Seven units and not six: `bytes_egress` is separate from `calls` because it is the
dimension a `Grant` gates, and its budget defaults to **0** so the first hosted escalation is a
deliberate act. `wall_ms` is priced at 0.0 by default. It is in the vector because it is the
dimension a *deadline* is expressed in, and because a `wall_ms` budget is the only guard against a
driver that is free and slow; pricing it would double-count CPU on a single-tenant machine."*

## Money is `Decimal`, and the integer is the last step

Rates are read out of TOML as floats -- `cpu_ms_micros = 0.00928` is not 0.00928 in binary -- and a
bill is a number two machines must agree on to the micro. Every rate is converted through
`Decimal(str(rate))` at load, the sum is exact decimal arithmetic in `DIMS` order, and the single
rounding is `ROUND_HALF_EVEN` at the end. Summing floats would make `Σ route_spend.micros ==
manifest.cost.billed_micros` (I30, *"not within a tolerance"*) a property of the order the rows
happened to be added in.

## `0.0` is UNPRICED, which is not the same as free

05:2410 writes that beside `wall_ms_micros = 0.0`, and this module keeps the distinction visible
rather than enforcing it: a rate that is **declared** `0.0` prices to nothing on purpose, and a rate
that is **absent** is a hole in the book. `micros()` treats an absent rate as zero -- pricing must
not raise in the middle of a run -- and `PriceBook.undeclared()` is the reporting hook that makes
the hole visible to `ow doctor` and `ow route lint` instead. A `RouteError` per attempt would turn a
mis-edited pricebook into a failed corpus.

Ports-only plus stdlib. No core import, so nothing here can reach a store.

Tier T-PUBLIC: 18-api-sketch.md:843.

Specified in 05-ingest-and-routing.md sections 6.1-6.4 (:2360-2600), 02-architecture.md section 2
row 35 and 08-runtime.md section 7.1.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_EVEN, Decimal
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import ConfigError, RouteError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "DIMS",
    "LOCAL_TABLE",
    "LOCAL_UNITS",
    "PROVIDER_PREFIX",
    "PROVIDER_UNITS",
    "RATE_SUFFIX",
    "PriceBook",
    "Spend",
]

DIMS: Final[tuple[str, ...]] = (
    "wall_ms",
    "cpu_ms",
    "gpu_ms",
    "tokens_in",
    "tokens_out",
    "calls",
    "bytes_egress",
)
"""The seven physical dimensions, in the order 05:2370-2372 declares them.

The order is load-bearing twice. `route_spend` prints its columns *"in the order `Spend` declares
them"* (05:2569), and `micros()` sums in this order so that two machines pricing the same vector
perform the same additions -- which matters even in `Decimal`, because a reader comparing two bills
should not have to reason about associativity to explain a difference.

`omniweave_core.budget.DIMS` has **eight** and the extra one is `micros`: a budget is declared in
money, a driver reports none. `test_route_spend.py` asserts this tuple is that one minus `micros`,
which is the whole cost model stated as a set difference.
"""

LOCAL_UNITS: Final[tuple[str, ...]] = ("wall_ms", "cpu_ms", "gpu_ms")
"""Always priced from `[local]`: they are your machine's time whoever served the request.

A Service-backed driver spends GPU on hardware you host, and a hosted API spends none of yours, so
the split is by *whose resource* rather than by who was called.
"""

PROVIDER_UNITS: Final[tuple[str, ...]] = ("tokens_in", "tokens_out", "calls", "bytes_egress")
"""Priced from `[provider.<tag>]` when `Spend.provider` is set, and from `[local]` when it is not.

`bytes_egress` appears in both tables in 05:2400-2418's printed book, and that is not redundancy: a
local run's egress is whatever your own network costs (`0.0` in the shipped example), and a
provider's is that provider's per-GB rate. The tag is what chooses.

A local driver may still report `tokens_out` -- `parse.page.olmocr` is `local_compute` and produces
tokens -- and the shipped `[local]` table declares no token rate, so those tokens price to nothing
and `undeclared()` says so. That is the intended reading: a local VLM's cost is its `gpu_ms`, and
counting its tokens as money would double-count the same second of compute.
"""

LOCAL_TABLE: Final = "local"
PROVIDER_PREFIX: Final = "provider"
RATE_SUFFIX: Final = "_micros"
"""`[local] cpu_ms_micros`, `[provider.parasail] tokens_in_micros`. 05:2400-2418."""

_MICRO = Decimal(1)


@dataclass(frozen=True, slots=True)
class Spend:
    """Seven physical units plus a provider tag. 05:2366-2374, field names and order verbatim.

    `provider` is `""` for local, which 05:2374 writes as a comment on the field and `route_spend`
    repeats as a column default -- *"`'' == local`, the same convention as `Spend`"*. It is a tag
    and not an enum: the set of providers is the operator's pricebook's, and a closed list in code
    would make adding one a release.
    """

    wall_ms: int = 0
    cpu_ms: int = 0
    gpu_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    bytes_egress: int = 0
    provider: str = ""

    def __add__(self, other: Spend) -> Spend:
        """Sum the seven. **Refuses to add across providers**, and that refusal is the point.

        05:2372 prints `__add__` and says nothing about the tag, which leaves one question the
        implementation must answer: what is the provider of `openai_spend + parasail_spend`? Every
        available answer is wrong. Keeping the left tag prices the right operand's tokens at the
        left's rates; blanking it prices them at `[local]`'s, which declares no token rate at all,
        so a mixed sum would silently bill **zero**. There is no third option, because the tag is
        what selects the rate table and one vector has one tag.

        The zero vector adds to anything and adopts the other's tag, which is what makes
        `sum(spends, Spend())` and a fold over one provider's attempts work without a special case.
        """
        if self.provider and other.provider and self.provider != other.provider:
            raise RouteError(
                f"a Spend tagged {self.provider!r} cannot be added to one tagged "
                f"{other.provider!r}: the tag selects the rate table, so the sum would price one "
                f"provider's tokens at the other's rates",
                fix="price each provider's Spend separately and add the micros",
            )
        return Spend(
            wall_ms=self.wall_ms + other.wall_ms,
            cpu_ms=self.cpu_ms + other.cpu_ms,
            gpu_ms=self.gpu_ms + other.gpu_ms,
            tokens_in=self.tokens_in + other.tokens_in,
            tokens_out=self.tokens_out + other.tokens_out,
            calls=self.calls + other.calls,
            bytes_egress=self.bytes_egress + other.bytes_egress,
            provider=self.provider or other.provider,
        )

    def __radd__(self, other: object) -> Spend:
        """`sum()` starts at `0`, so the zero integer is the only non-`Spend` this accepts."""
        if other == 0:
            return self
        return NotImplemented  # type: ignore[return-value]

    def scaled(self, multiple: float, dims: tuple[str, ...]) -> Spend:
        """`dims` multiplied by `multiple`, rounded **up**; every other dimension unchanged.

        05:2461's `reserved_micros` recipe -- *"`est_spend` with its OUTPUT-PROPORTIONAL dimensions
        x `tokens_out_p95_multiple`, priced <- THE p95 CEILING"* -- applied to the vector rather
        than to the price, which is the order the plan prints. The two coincide only because every
        rate is linear in its unit; scaling the vector first is what keeps that an *observation*
        about this pricebook rather than an assumption a non-linear one would break.

        Up, because 08:2251 says *"a reservation that under-estimates admits work the budget cannot
        pay for."* `omniweave_core.budget.reserved_amount()` rounds the same way for the same
        reason, one dimension at a time.
        """
        if multiple < 1.0:
            raise ConfigError(
                f"a p95 multiple of {multiple} scales an estimate DOWN, which under-reserves",
                fix="declare tokens_out_p95_multiple >= 1.0 in [cost.model]",
            )
        unknown = tuple(dim for dim in dims if dim not in DIMS)
        if unknown:
            raise ConfigError(
                f"{unknown} are not Spend dimensions; the seven are {DIMS}",
                fix="scale one of the seven physical units",
            )
        changes = {dim: -int(-getattr(self, dim) * multiple // 1) for dim in dims}
        return replace(self, **changes)

    def micros(self, book: PriceBook) -> int:
        """THE ONLY PLACE MONEY APPEARS (INV-15). 05:2373.

        Each of the seven is multiplied by its rate and the sum is rounded once, at the end, with
        `ROUND_HALF_EVEN`. Rounding per dimension would bias every bill upward by up to half a
        micro per dimension per attempt, which on a 116,400-page reference ingest is a number an
        operator can see.

        A dimension whose rate is undeclared prices to zero. `PriceBook.undeclared()` is where that
        becomes visible; see this module's docstring for why it is not a raise.
        """
        total = Decimal(0)
        for dim in DIMS:
            value = getattr(self, dim)
            if value:
                total += Decimal(value) * book.rate(dim, self.provider)
        return int(total.quantize(_MICRO, rounding=ROUND_HALF_EVEN))


@dataclass(frozen=True, slots=True)
class PriceBook:
    """`.omniweave/pricebook.toml` -- operator-owned, versioned, digested. 05:2390-2420.

    *"The `PriceBook` **is** the shadow prices; a separate `[objective]` block would have been two
    versioned artefacts for one job"* (05:2427). `pricebook_digest` enters `route_decision`'s
    identity, so *"a price change makes a **new** decision row rather than silently rewriting
    history -- and `ow route replay --pricebook <old>` re-prices the whole log against the previous
    book for $0."*

    `rates` is `{table: {dim: Decimal}}` where `table` is `"local"` or `"provider.<name>"`. The
    values are `Decimal` rather than `float` because a bill is a number two machines must agree on;
    see the module docstring.
    """

    version: int
    currency: str
    effective_from: str
    rates: Mapping[str, Mapping[str, Decimal]]

    def rate(self, dim: str, provider: str) -> Decimal:
        """The micros-per-unit rate for one dimension under one provider tag. Zero if undeclared.

        `LOCAL_UNITS` always resolve against `[local]`: they are your machine's time whoever served
        the call. `PROVIDER_UNITS` resolve against `[provider.<tag>]` when the tag is set and
        against `[local]` when it is not, which is what makes a local run's `bytes_egress` your own
        network's cost and a hosted one's the provider's.
        """
        if dim not in DIMS:
            raise ConfigError(
                f"{dim!r} is not one of the seven physical dimensions {DIMS}",
                fix="price one of the seven units a driver may report",
            )
        table = LOCAL_TABLE
        if dim in PROVIDER_UNITS and provider:
            table = f"{PROVIDER_PREFIX}.{provider}"
        return self.rates.get(table, {}).get(dim, Decimal(0))

    def undeclared(self, provider: str = "") -> tuple[str, ...]:
        """The dimensions this book prices at zero because it names no rate for them at all.

        The reporting hook that keeps *"`0.0` is UNPRICED, which is not the same as free"* (05:2410)
        checkable: a declared `0.0` is absent from this tuple and a missing key is in it.
        `ow doctor` and `ow route lint` are its callers; `micros()` never consults it, because
        pricing must not fail in the middle of a run.

        An unknown provider tag reports all four `PROVIDER_UNITS`, which is the honest answer: a
        book with no table for the provider a driver reported prices its tokens at nothing.
        """
        missing = []
        for dim in DIMS:
            table = LOCAL_TABLE
            if dim in PROVIDER_UNITS and provider:
                table = f"{PROVIDER_PREFIX}.{provider}"
            if dim not in self.rates.get(table, {}):
                missing.append(dim)
        return tuple(missing)

    @property
    def providers(self) -> tuple[str, ...]:
        """Every `[provider.<name>]` table in the book, sorted. `[local]` is not one of them."""
        prefix = f"{PROVIDER_PREFIX}."
        return tuple(sorted(name[len(prefix) :] for name in self.rates if name.startswith(prefix)))

    @classmethod
    def loads(cls, text: str) -> PriceBook:
        """Parse a pricebook from TOML. Every rate becomes a `Decimal` through its own text.

        `Decimal(str(value))` and not `Decimal(value)`: the latter takes the exact binary value
        `tomllib` produced, so `0.00928` would enter the book as
        `0.009280000000000000217...`, and two machines agreeing on that is an accident of
        `float.__repr__` rather than a property of the file. Going back through `str()` recovers the
        shortest decimal that round-trips, which is what the operator typed.
        """
        raw = tomllib.loads(text)
        for key in ("version", "currency"):
            if key not in raw:
                raise ConfigError(
                    f"a pricebook declares {key!r}; 05:2394 prints all three of version, currency "
                    f"and effective_from",
                    fix=f"add {key} to .omniweave/pricebook.toml",
                )
        tables: dict[str, Mapping[str, Decimal]] = {}
        if LOCAL_TABLE in raw:
            tables[LOCAL_TABLE] = cls._rates(raw[LOCAL_TABLE], LOCAL_TABLE)
        for name, body in raw.get(PROVIDER_PREFIX, {}).items():
            tables[f"{PROVIDER_PREFIX}.{name}"] = cls._rates(body, f"{PROVIDER_PREFIX}.{name}")
        return cls(
            version=int(raw["version"]),
            currency=str(raw["currency"]),
            effective_from=str(raw.get("effective_from", "")),
            rates=MappingProxyType(tables),
        )

    @classmethod
    def load(cls, path: Path) -> PriceBook:
        """`loads()` over a file's text. UTF-8, because a currency code is not the operator's."""
        return cls.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _rates(body: object, table: str) -> Mapping[str, Decimal]:
        """One table's `<dim>_micros` keys, as `Decimal`. An unknown key is refused by name."""
        if not isinstance(body, dict):
            raise ConfigError(
                f"[{table}] is not a table of rates",
                fix="write [local] or [provider.<name>] as a TOML table",
            )
        out: dict[str, Decimal] = {}
        for key, value in body.items():
            if not key.endswith(RATE_SUFFIX):
                raise ConfigError(
                    f"[{table}] {key} is not a rate; every key is '<dim>{RATE_SUFFIX}'",
                    fix=f"name the key after one of {DIMS}",
                )
            dim = key[: -len(RATE_SUFFIX)]
            if dim not in DIMS:
                raise ConfigError(
                    f"[{table}] {key} prices {dim!r}, which is not one of the seven {DIMS}",
                    fix="a pricebook prices physical units, and micros is not one",
                )
            if not isinstance(value, (int, float)):
                raise ConfigError(
                    f"[{table}] {key} is {value!r}; a rate is a number of micros per unit",
                    fix="write the rate as a TOML float, e.g. 0.00928",
                )
            out[dim] = Decimal(str(value))
        return MappingProxyType(out)
