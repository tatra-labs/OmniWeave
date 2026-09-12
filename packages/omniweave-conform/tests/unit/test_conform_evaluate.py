"""`span_exact_rate`, the metric half — the denominator, the sample, and the vacuous state.

`omniweave_conform.evaluate` computes 13-quality.md:1092's row, and almost every way this metric
could be wrong is a way of getting the **denominator** wrong. 13:1092, verbatim:

> over Blocks with `quote == VERBATIM`, the fraction whose `span` assertion re-verifies on the
> branch its `os_kind` selects. **Denominator is blocks that claim verbatimness**, so a slice with
> none passes vacuously — which is every office slice at release 1

So the tests here are mostly about what is counted rather than about arithmetic:

* a block that does not claim `verbatim` is not in the denominator, however good its address is;
* a block that claims `verbatim` IS in the denominator, however bad its address is — the point of
  a fidelity gate is that a claim you cannot prove is a failure and not an omission;
* an empty denominator is `vacuous` and is **never** 1.0. 13:36 names the failure mode a float
  there would be: *"a byte-exactness claim degrades into an accuracy percentage and nobody notices
  it fell."*

The sampler gets its own tests because `random` is banned in this workspace with the reason in
`pyproject.toml` — *"Sampling is blake2b. Determinism is a gate, not a habit."* — and a sampler
that was accidentally order-dependent would make this whole metric unreproducible between two runs
over the same corpus.

Specified in 13-quality.md sections 8.3 and 1.1, 01-principles.md INV-10, and 16-roadmap.md
section 6's P3 exit criteria.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from omniweave_conform.evaluate import (
    SAMPLE_N,
    VERBATIM,
    Claim,
    claims,
    sample,
    span_exact_rate,
)
from omniweave_conform.harness import reverify_origin

TEXT = "hello world"
DATA = TEXT.encode()


@dataclass(frozen=True, slots=True)
class FakeFixture:
    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class FakeRun:
    """Enough of a `ParseRun` for the metric: a fixture and the blocks it produced."""

    fixture: FakeFixture
    blocks: tuple[dict[str, Any], ...]


def block(
    tmp: str,
    *,
    quote: str = VERBATIM,
    start: int = 0,
    length: int = len(DATA),
    text: str = TEXT,
) -> dict[str, Any]:
    return {
        "tmp": tmp,
        "text": text,
        "quote": quote,
        "os": {"k": "bytes", "start": start, "length": length, "codec": "utf-8"},
    }


def run(*blocks: dict[str, Any], name: str = "f.txt") -> FakeRun:
    return FakeRun(fixture=FakeFixture(name=name, data=DATA), blocks=tuple(blocks))


# ---------------------------------------------------------------------------
# the denominator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("quote", ["normalized", "reflowed", "synthetic", "", "VERBATIM"])
def test_a_block_that_does_not_claim_verbatim_is_not_counted(quote: str) -> None:
    """However good its address is. The gate is over claims, not over blocks.

    `"VERBATIM"` is in the list on purpose: `owdoc-fragment/1` carries the lowercase name and a
    case-insensitive match here would quietly admit a value no driver emits.
    """
    assert claims([run(block("b1", quote=quote))]) == ()


def test_a_block_that_claims_verbatim_is_counted_however_bad_its_address() -> None:
    """A claim you cannot prove is a FAILURE, not an omission. If an unverifiable block fell out of
    the denominator, a driver could reach 1.000 by making its bad spans un-checkable."""
    result = span_exact_rate([run(block("b1", start=99, length=99))])
    assert result.denominator == 1
    assert result.numerator == 0
    assert result.value == 0.0
    assert "b1" in result.failures[0]


def test_the_rate_is_the_fraction_that_re_verifies() -> None:
    good = block("good")
    bad = block("bad", start=0, length=4)  # "hell" != "hello world"
    result = span_exact_rate([run(good, bad)])
    assert (result.numerator, result.denominator) == (1, 2)
    assert result.value == 0.5


def test_an_empty_denominator_is_vacuous_and_never_one_point_zero() -> None:
    """13-quality.md:661 — the gate "holds **vacuously** on that slice". A vacuous rate is not 1.0
    and is not 0.0; writing either is exactly 13:36's failure mode."""
    result = span_exact_rate([run(block("b1", quote="normalized"))])
    assert result.state == "vacuous"
    assert result.value is None
    assert result.denominator == 0
    assert result.blocks_seen == 1
    assert "vacuous" in result.line()


def test_no_runs_at_all_is_also_vacuous() -> None:
    result = span_exact_rate([])
    assert result.state == "vacuous"
    assert result.blocks_seen == 0


# ---------------------------------------------------------------------------
# R-T16's indicator
# ---------------------------------------------------------------------------


def test_the_denominator_share_is_reported_beside_the_rate() -> None:
    """17-risks.md R-T16's trigger is this share below 0.5 WHILE the rate reports 1.000 — "the two
    read together are the finding". A report that printed only the rate would show a green gate on
    a corpus where almost nothing was under it."""
    blocks = [block("v1"), block("v2"), *[block(f"n{i}", quote="normalized") for i in range(8)]]
    result = span_exact_rate([run(*blocks)])
    assert result.value == 1.0
    assert result.denominator_frac == pytest.approx(0.2)
    line = result.line()
    assert "1.0000" in line
    assert "0.2000 of 10 blocks" in line


def test_every_fraction_is_four_decimal_places_and_never_a_repr() -> None:
    """13-quality.md:655 makes the format load-bearing: "`%.4f` for every fraction and never a
    `repr()`, because `repr(0.1)` is a property of a runtime rather than of a document and is not
    something to bet a frozen gate on"."""
    blocks = [block("good"), block("bad", start=0, length=4), block("c"), block("d")]
    line = span_exact_rate([run(*blocks)]).line()
    assert "0.7500" in line
    assert "0.75 " not in line


# ---------------------------------------------------------------------------
# the sample
# ---------------------------------------------------------------------------


def make_claims(n: int) -> list[Claim]:
    return [
        Claim(fixture="f.txt", tmp=f"b{i}", text=TEXT, origin={"k": "bytes"}, data=DATA)
        for i in range(n)
    ]


def test_a_population_below_n_is_its_own_sample() -> None:
    population = make_claims(5)
    assert sample(population, 10) == tuple(population)


def test_the_sample_is_deterministic_and_order_independent() -> None:
    """The property that matters. Two runs over the same corpus that produced blocks in a different
    order must sample the same blocks, or the metric is unreproducible between machines."""
    population = make_claims(50)
    forwards = sample(population, 10)
    backwards = sample(list(reversed(population)), 10)
    assert {claim.tmp for claim in forwards} == {claim.tmp for claim in backwards}
    assert sample(population, 10) == forwards


def test_the_sample_key_distinguishes_two_blocks_with_identical_text() -> None:
    """The identity is `(fixture, tmp)` and not the text: two blocks with the same text are two
    claims and both belong in the denominator. Hashing the text would collapse them."""
    first = Claim(fixture="f.txt", tmp="b1", text=TEXT, origin={}, data=DATA)
    second = Claim(fixture="f.txt", tmp="b2", text=TEXT, origin={}, data=DATA)
    assert first.sort_key != second.sort_key


def test_the_same_tmp_in_two_fixtures_is_two_claims() -> None:
    here = Claim(fixture="a.txt", tmp="b1", text=TEXT, origin={}, data=DATA)
    there = Claim(fixture="b.txt", tmp="b1", text=TEXT, origin={}, data=DATA)
    assert here.sort_key != there.sort_key


def test_the_plan_names_one_thousand() -> None:
    """01-principles.md:328, 07-store-and-retrieval.md:2563 and 13-quality.md:1990 all say "a
    deterministic sample of n = 1000 blocks"."""
    assert SAMPLE_N == 1000


def test_sampling_reports_how_many_it_looked_at_and_how_many_there_were() -> None:
    """A rate over a sample is not a rate over the population, and a report that hid the difference
    would let 1.0000 over 1,000 sampled blocks read as 1.0000 over 40,000."""
    blocks = [block(f"b{i}") for i in range(20)]
    result = span_exact_rate([run(*blocks)], n=5)
    assert (result.sampled, result.denominator) == (5, 20)
    assert "sampled 5 of 20" in result.line()


# ---------------------------------------------------------------------------
# the shared re-read
# ---------------------------------------------------------------------------


def test_the_metric_and_the_capability_suite_share_one_re_read() -> None:
    """INV-21. `harness.reverify_origin` is the one home of INV-10's three-branch decision, and
    both P7 and this metric call it. Two copies that could drift apart is the defect."""
    origin = {"k": "bytes", "start": 0, "length": len(DATA), "codec": "utf-8"}
    assert reverify_origin(DATA, origin, TEXT).ok
    assert not reverify_origin(DATA, {**origin, "length": 4}, TEXT).ok


def test_a_branch_needing_a_hook_is_not_a_pass_without_one() -> None:
    """An unproved claim is what P7 exists to catch, so an absent hook is a failing verification
    and never a skip — which means it lowers the rate rather than shrinking the denominator."""
    result = span_exact_rate([run({**block("b1"), "os": {"k": "glyphs", "start": 0, "length": 1}})])
    assert result.denominator == 1
    assert result.value == 0.0
    assert "glyphs" in result.failures[0]


def test_a_hook_that_verifies_is_used() -> None:
    class Driver:
        @staticmethod
        def verify_origin(_part: bytes, _origin: Any, _text: str) -> tuple[bool, str]:
            return True, ""

    record = {**block("b1"), "os": {"k": "glyphs", "start": 0, "length": 1}}
    result = span_exact_rate([run(record)], Driver())
    assert result.value == 1.0
