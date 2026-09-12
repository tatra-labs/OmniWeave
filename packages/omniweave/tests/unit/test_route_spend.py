"""`omniweave.route.spend` against 05-ingest-and-routing.md Part 6, including its worked arithmetic.

05 does something unusual for a design document: it prices a page and shows the multiplication.
*"At `gpu_ms_micros = 0.3556` and olmocr's p50 of 2.4 s, one `PAGE` call is `2400 x 0.3556 = 853.4`
micros"*, and the reference ingest is `116,400 x 853.4 = 99.3e6` micros. Those numbers are the best
test this module can have, because they were computed by a human who was not looking at this code.
The pricebook they were computed from is printed in the same section and is transcribed here.
"""

from __future__ import annotations

import ast
from dataclasses import fields
from decimal import Decimal

import pytest
from omniweave.route.spend import (
    DIMS,
    LOCAL_TABLE,
    LOCAL_UNITS,
    PROVIDER_UNITS,
    PriceBook,
    Spend,
)
from omniweave_core.budget import DIMS as BUDGET_DIMS
from omniweave_core.errors import ConfigError, RouteError
from omniweave_core.operator import SpendVector

ROUTING = "05-ingest-and-routing.md"

BOOK_TOML = """
version        = 3
currency       = "USD"
effective_from = 2026-09-01

[local]
cpu_ms_micros       = 0.00928
gpu_ms_micros       = 0.3556
wall_ms_micros      = 0.0
bytes_egress_micros = 0.0

[provider.parasail]
tokens_in_micros    = 0.10
tokens_out_micros   = 0.20
calls_micros        = 0.0
bytes_egress_micros = 0.00009

[provider.openai]
tokens_in_micros    = 0.15
tokens_out_micros   = 0.60
calls_micros        = 0.0
bytes_egress_micros = 0.00009
"""
"""05:2400-2418, transcribed. The two local rates are 05's own *"examples of the shape"*."""

OLMOCR_P50_MS = 2_400
REFERENCE_PAGES = 116_400


@pytest.fixture
def book() -> PriceBook:
    return PriceBook.loads(BOOK_TOML)


# ---------------------------------------------------------------------------------------------
# 1. The vector
# ---------------------------------------------------------------------------------------------


def test_the_seven_fields_are_the_plans_own_in_the_plans_own_order(plan) -> None:
    """05:2366-2374's printed `class Spend`, read out of the fence with `ast`."""
    plan.require()
    found = None
    for body in plan.fences(ROUTING, "python"):
        for node in ast.parse(body).body:
            if isinstance(node, ast.ClassDef) and node.name == "Spend":
                assert found is None, "05 prints class Spend once"
                found = node
    assert found is not None

    printed = tuple(
        child.target.id
        for child in found.body
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
    )
    assert printed == tuple(field.name for field in fields(Spend))
    assert printed == (*DIMS, "provider")


def test_the_seven_are_the_ledgers_eight_minus_micros() -> None:
    """INV-15 as a set difference: a driver reports physical units, a budget declares money."""
    assert set(BUDGET_DIMS) - set(DIMS) == {"micros"}
    assert set(DIMS) - set(BUDGET_DIMS) == set()
    assert set(LOCAL_UNITS) | set(PROVIDER_UNITS) == set(DIMS)


def test_a_spend_satisfies_the_structural_stand_in_core_reads_it_through() -> None:
    """`SpendVector` is `omniweave_core.operator`'s, and this is the only place both types exist.

    Core may not import this module -- `tools/layers.toml` gives `omniweave_core` exactly
    `["omniweave_ports"]` -- so `StepMetrics.spend` is typed against a Protocol naming the eight
    attributes (D139). Without this test the stand-in is an assertion in a docstring.

    `micros()` is deliberately absent from the Protocol, so a sink that holds a `SpendVector`
    cannot price: INV-15's *"THE ONLY PLACE MONEY APPEARS"* is a property of what the type a caller
    was handed can do, not of what this class can.
    """
    assert isinstance(Spend(), SpendVector)
    assert not hasattr(SpendVector, "micros")
    assert hasattr(Spend, "micros")


def test_adding_across_providers_is_refused_rather_than_silently_wrong() -> None:
    """Every available answer is wrong, so the sum is not one of them.

    Keeping the left tag prices the right operand's tokens at the left's rates; blanking it prices
    them at `[local]`'s, which declares no token rate at all, so a mixed sum would bill **zero**.
    """
    parasail = Spend(tokens_out=100, provider="parasail")
    openai = Spend(tokens_out=100, provider="openai")
    with pytest.raises(RouteError, match="selects the rate table"):
        _ = parasail + openai


def test_the_zero_vector_adopts_the_others_tag_so_a_fold_needs_no_special_case() -> None:
    """`sum(spends, Spend())` over one provider's attempts is the shape the runner uses."""
    attempts = [Spend(tokens_out=10, provider="parasail"), Spend(tokens_out=5, provider="parasail")]
    total = sum(attempts, Spend())
    assert total == Spend(tokens_out=15, provider="parasail")
    assert (Spend() + Spend(calls=1, provider="openai")).provider == "openai"


def test_addition_sums_every_one_of_the_seven() -> None:
    """A dimension dropped from `__add__` is a bill that under-reports and never says so."""
    left = Spend(1, 2, 3, 4, 5, 6, 7, "parasail")
    assert left + left == Spend(2, 4, 6, 8, 10, 12, 14, "parasail")


def test_scaled_rounds_up_and_leaves_the_input_proportional_dimensions_alone() -> None:
    """05:2461-2473. The p95 ceiling is the vector scaled, then priced -- in that order."""
    spend = Spend(gpu_ms=2_400, tokens_in=1_800, tokens_out=1_100, calls=1, provider="parasail")
    scaled = spend.scaled(3.2, ("tokens_out", "gpu_ms"))

    assert scaled.tokens_out == 3_520
    assert scaled.gpu_ms == 7_680
    assert scaled.tokens_in == 1_800
    assert scaled.calls == 1
    assert scaled.provider == "parasail"
    assert Spend(tokens_out=1).scaled(1.1, ("tokens_out",)).tokens_out == 2


def test_scaling_refuses_a_multiple_below_one_and_a_dimension_that_is_not_one() -> None:
    """A `[cost.model]` declaring 0.8 would reserve less than its own estimate (08:2251)."""
    with pytest.raises(ConfigError, match="scales an estimate DOWN"):
        Spend().scaled(0.8, ("tokens_out",))
    with pytest.raises(ConfigError, match="not Spend dimensions"):
        Spend().scaled(2.0, ("micros",))


# ---------------------------------------------------------------------------------------------
# 2. The plan's own arithmetic
# ---------------------------------------------------------------------------------------------


def test_one_olmocr_page_costs_what_the_plan_says_it_costs(book: PriceBook) -> None:
    """05:2420 -- *"one `PAGE` call is `2400 x 0.3556 = 853.4` micros"*, stored as an INTEGER."""
    assert Spend(gpu_ms=OLMOCR_P50_MS).micros(book) == 853
    assert Decimal(OLMOCR_P50_MS) * Decimal("0.3556") == Decimal("853.44")


def test_the_reference_ingest_lands_inside_the_charters_band(book: PriceBook) -> None:
    """05:2421-2423 -- `116,400 x 853.4 = 99.3e6` micros, about $99, against a $23-$80 band once
    server-side coalescing is counted. This asserts the *total*, which is the number an operator
    actually sees, and is the reason `micros` is an integer rather than a float: 116,400 additions
    of a rounded page cost must equal 116,400 times one page cost, exactly."""
    page = Spend(gpu_ms=OLMOCR_P50_MS).micros(book)
    total = page * REFERENCE_PAGES
    assert total == 99_289_200
    assert 99_000_000 <= total <= 100_000_000


def test_a_parasail_page_prices_its_tokens_and_not_its_gpu(book: PriceBook) -> None:
    """1800 x 0.10 + 1100 x 0.20 = 180 + 220 = 400 micros, and `calls_micros` is a declared 0.0."""
    spend = Spend(tokens_in=1_800, tokens_out=1_100, calls=1, provider="parasail")
    assert spend.micros(book) == 400


def test_the_same_vector_costs_more_at_openai(book: PriceBook) -> None:
    """The provider tag is what selects the table, so it is what changes the bill."""
    parasail = Spend(tokens_in=1_800, tokens_out=1_100, provider="parasail")
    openai = Spend(tokens_in=1_800, tokens_out=1_100, provider="openai")
    assert parasail.micros(book) == 400
    assert openai.micros(book) == 930


def test_local_time_is_priced_from_local_whatever_the_provider_tag_says(book: PriceBook) -> None:
    """A hosted call still spends your CPU, and a Service-backed one spends your GPU."""
    assert Spend(cpu_ms=1_000, provider="parasail").micros(book) == 9
    assert Spend(cpu_ms=1_000).micros(book) == 9
    assert Spend(gpu_ms=1_000, provider="openai").micros(book) == 356


def test_egress_is_priced_by_the_provider_and_locally_by_the_local_table(book: PriceBook) -> None:
    """`bytes_egress` is the one dimension the printed book declares in both tables (05:2400)."""
    assert Spend(bytes_egress=1_000_000).micros(book) == 0
    assert Spend(bytes_egress=1_000_000, provider="parasail").micros(book) == 90


def test_rounding_happens_once_at_the_end_and_not_per_dimension(book: PriceBook) -> None:
    """Per-dimension rounding biases every bill upward by up to half a micro per dimension.

    `cpu_ms=1` is 0.00928 micros and `gpu_ms=1` is 0.3556: rounded separately they are 0 and 0,
    summing to 0; rounded once they are 0.36492, which is still 0. The case that separates the two
    is a vector whose dimensions each land below a half and together do not.
    """
    spend = Spend(cpu_ms=30, gpu_ms=1)  # 0.2784 + 0.3556 = 0.634 -> 1
    assert spend.micros(book) == 1
    assert Spend(cpu_ms=30).micros(book) == 0
    assert Spend(gpu_ms=1).micros(book) == 0


def test_the_rate_is_the_decimal_the_operator_typed_and_not_the_float(book: PriceBook) -> None:
    """`Decimal(str(rate))`, so a bill is reproducible rather than an accident of `float.__repr__`.

    The trap is real and one line wide: `Decimal(0.00928)` is
    `0.00928000000000000021...`, and 116,400 multiplications of that are not 116,400
    multiplications of `Decimal("0.00928")`.
    """
    assert book.rate("cpu_ms", "") == Decimal("0.00928")
    assert book.rate("cpu_ms", "") != Decimal(0.00928)  # noqa: RUF032 -- the trap IS the test.
    assert str(book.rate("gpu_ms", "")) == "0.3556"


# ---------------------------------------------------------------------------------------------
# 3. The book
# ---------------------------------------------------------------------------------------------


def test_the_book_reads_its_three_header_fields_and_its_providers(book: PriceBook) -> None:
    """05:2394-2397. `[local]` is a rate table and not a provider."""
    assert book.version == 3
    assert book.currency == "USD"
    assert book.effective_from == "2026-09-01"
    assert book.providers == ("openai", "parasail")
    assert LOCAL_TABLE not in book.providers


def test_an_undeclared_rate_prices_to_zero_and_is_reported_rather_than_raised(
    book: PriceBook,
) -> None:
    """*"`0.0` is UNPRICED, which is not the same as free"* (05:2410), kept checkable.

    The shipped `[local]` table declares no token rate, so a local VLM's tokens price to nothing --
    which is the intended reading, since its cost is its `gpu_ms` and counting both would
    double-count the same second of compute. `undeclared()` is what makes the silence visible.
    """
    assert Spend(tokens_out=10_000).micros(book) == 0
    assert book.undeclared() == ("tokens_in", "tokens_out", "calls")
    assert "wall_ms" not in book.undeclared(), "a declared 0.0 is a decision, not a hole"
    assert book.undeclared("parasail") == (), "the printed book prices parasail completely"


def test_an_unknown_provider_prices_nothing_and_says_so(book: PriceBook) -> None:
    """A driver reporting a provider the book has no table for is a hole, not a crash mid-run."""
    assert Spend(tokens_out=1_000, provider="acme").micros(book) == 0
    assert set(book.undeclared("acme")) == set(PROVIDER_UNITS)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ('currency = "USD"\n[local]\n', "declares 'version'"),
        ("version = 1\n[local]\n", "declares 'currency'"),
        ('version = 1\ncurrency = "USD"\n[local]\ncpu_ms = 1.0\n', "is not a rate"),
        ('version = 1\ncurrency = "USD"\n[local]\nmicros_micros = 1.0\n', "not one of the seven"),
        ('version = 1\ncurrency = "USD"\n[local]\ncpu_ms_micros = "free"\n', "micros per unit"),
    ],
)
def test_a_malformed_book_is_refused_by_naming_the_key(body: str, match: str) -> None:
    """A pricebook is edited by hand, so every refusal names the line that caused it.

    `micros_micros` is the one worth spelling out: a book that priced `micros` would be pricing
    money in money, and the seven physical dimensions are the whole domain a rate may name.
    """
    with pytest.raises(ConfigError, match=match):
        PriceBook.loads(body)


def test_a_book_with_no_local_table_still_loads() -> None:
    """An operator who bills only through providers has no local rates to declare."""
    narrow = PriceBook.loads('version = 1\ncurrency = "EUR"\n[provider.acme]\ncalls_micros = 5.0\n')
    assert narrow.providers == ("acme",)
    assert Spend(calls=3, provider="acme").micros(narrow) == 15
    assert Spend(cpu_ms=1_000_000).micros(narrow) == 0


def test_loading_from_a_file_is_the_same_as_loading_from_its_text(
    tmp_path, book: PriceBook
) -> None:
    """`.omniweave/pricebook.toml` is the shipped path; UTF-8, because a currency code is not
    the operator's locale's business."""
    path = tmp_path / "pricebook.toml"
    path.write_text(BOOK_TOML, encoding="utf-8")
    assert PriceBook.load(path) == book
