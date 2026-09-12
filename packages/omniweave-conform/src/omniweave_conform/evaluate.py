"""The metric half of the kit: what `eval/gates.toml`'s rows actually measure.

Two registers in this repository are called `gates.toml` and they mean different things
(11-repo-layout.md:394): `tools/gates.toml` holds the **G-series**, the numbered CI gates, and
`eval/gates.toml` holds the **metric** gates — `span_exact_rate`, `structure_f1`,
`hallucination_rate` and the rest, *"each with an owner, a review date, a budget and a guard"*.
Neither file may name a row the other owns. This module computes what the second file gates.

**`span_exact_rate` is the only row implemented at P3**, and the reason it is first is that it is
the cheapest honest thing this framework measures. 13-quality.md:36 puts it in the **fidelity**
row — *"the extracted bytes equal the source bytes"* — against **accuracy** ("the structure we
recovered matches ground truth") and **honesty** ("when we do not know, we say so"); and 13:44 is
the sentence that makes it buildable now:

> `quote == VERBATIM` is self-verifying against the user's own bytes: the block text either equals
> the retained slice on the branch its `os_kind` selects or it does not (INV-10). **That needs no
> corpus, no labels and no model**, which is why `span_exact_rate` is a **hard gate at 1.000** in
> `eval/gates.toml` rather than a score with a floor.

No corpus. The T4 accuracy suites need `fixtures/docs/` with ≥40% real public-domain scans; this
does not, and conflating the two is how a hard gate gets deferred behind a licensing problem it
never had.

## The denominator is the whole design

13-quality.md:1092, the register row, verbatim:

> over Blocks with `quote == VERBATIM`, the fraction whose `span` assertion re-verifies on the
> branch its `os_kind` selects. **Denominator is blocks that claim verbatimness**, so a slice with
> none passes vacuously — which is every office slice at release 1

So this is a gate over **claims**, not over blocks. `parse.office.anydoc` emits
`quote = "normalized"` on every block, because anydoc's eight `Block` variants carry no source
address of any kind — so the office denominator is zero and the rate is **vacuous**, which
13:661 says in those words and 17-risks.md R-T16 registers as a risk rather than a defect.
`parse.pdf.pdfium` emits `quote = "verbatim"` by construction and is where the gate has teeth.

A vacuous result is **not** a pass and is not reported as one. `MetricResult.state` is a third
value, the denominator is printed beside the rate, and `verbatim_denominator_frac` — R-T16's own
named indicator, the claiming blocks as a share of all blocks — is carried so a reader can see
that 1.000 was earned rather than dodged. R-T16's trigger is precisely the two read together:
`span_exact_rate` reporting 1.000 *while* the denominator share is below 0.5.

## The sample is deterministic and RNG-free

01-principles.md:328, 07-store-and-retrieval.md:2563 and 13-quality.md:1990 all say *"a
deterministic sample of n = 1000 blocks"*. `random` is a banned import in this workspace with the
reason in `pyproject.toml` — *"Sampling is blake2b. Determinism is a gate, not a habit."* — so the
sample is the `n` claims with the lowest `blake2b(fixture, tmp)` key. Stable under reordering,
stable across machines, and it does not need the whole population in memory to be reproducible.

Below `n` the sample is the population, which is every slice this repository has today.

Specified in 13-quality.md sections 8.3 and 1.1, 11-repo-layout.md section 3.3, 01-principles.md
INV-10, and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_conform.harness import ORIGIN_VERIFIER, reverify_origin

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_conform.harness import ParseRun

__all__ = [
    "SAMPLE_N",
    "VERBATIM",
    "Claim",
    "MetricResult",
    "claims",
    "sample",
    "span_exact_rate",
]

VERBATIM: Final = "verbatim"
"""The `quote` value that makes a block part of the denominator.

`Quote` is an ordered `IntEnum` with the weakest tier lowest (`SYNTHETIC = 0`, `VERBATIM = 4`,
01-principles.md:329) and `owdoc-fragment/1` carries it as the spelled-out lowercase name. The
fragment's vocabulary is what this reads, because the fragment is what a driver emits and the
enum is what the store holds; going through the enum here would make the metric depend on an
import path the wire deliberately does not have."""

SAMPLE_N: Final = 1000
"""The deterministic sample size the plan names three times over."""

_SAMPLE_PERSON: Final = b"ow.eval.sample"
"""`blake2b(person=...)` domain separation, so this sampler's ordering can never coincide with
another keyed hash in the tree. 16 bytes is `blake2b.PERSON_SIZE`'s ceiling; this is 14."""


@dataclass(frozen=True, slots=True)
class Claim:
    """One block that claims verbatimness, with everything needed to re-prove it.

    `data` is the retained part's bytes — the fixture's own, at P3, because the kit seeds one part
    per fixture. When a driver retains several, this becomes the part the block's address is
    relative to and nothing else about this module changes.
    """

    fixture: str
    tmp: str
    text: str
    origin: Mapping[str, Any]
    data: bytes

    @property
    def sort_key(self) -> bytes:
        """`blake2b(fixture + "\\x00" + tmp)` — the sample's ordering.

        The identity is `(fixture, tmp)` rather than the text: two blocks with identical text are
        two claims and both belong in the denominator, and hashing the text would silently collapse
        them. `tmp` is the driver's per-invocation id, which is the only block identifier that
        crosses `owdoc-fragment/1` — no `block_id` ever does.
        """
        raw = f"{self.fixture}\x00{self.tmp}".encode()
        return hashlib.blake2b(raw, digest_size=16, person=_SAMPLE_PERSON).digest()


@dataclass(frozen=True, slots=True)
class MetricResult:
    """One metric, measured. What it is compared against is `eval/gates.toml`'s, not this."""

    metric: str
    state: str
    """`measured` or `vacuous`. **Never `pass`**: this type reports what was measured and the
    register's row decides whether that meets the bar, because a measurement that knew its own
    floor would be a floor with two homes."""

    value: float | None
    """`None` exactly when `state == "vacuous"`. A vacuous rate is not 1.0 and is not 0.0, and
    writing either would be the whole defect this metric is guarding against: 13:36's failure mode
    is "a byte-exactness claim degrades into an accuracy percentage and nobody notices it fell"."""

    numerator: int
    denominator: int
    sampled: int
    blocks_seen: int
    failures: tuple[str, ...]

    @property
    def denominator_frac(self) -> float:
        """The claiming blocks as a share of all blocks — R-T16's named indicator.

        17-risks.md R-T16's trigger is this number below 0.5 *while* `span_exact_rate` reports
        1.000. The two read together are the finding; either alone is not.
        """
        return self.denominator / self.blocks_seen if self.blocks_seen else 0.0

    def line(self) -> str:
        """One line, `%.4f` for the fraction and never a `repr()`.

        13-quality.md:655 makes the format load-bearing: *"`%.4f` for every fraction and never a
        `repr()`, because `repr(0.1)` is a property of a runtime rather than of a document and is
        not something to bet a frozen gate on."*
        """
        if self.value is None:
            return (
                f"{self.metric}  vacuous  0 of {self.blocks_seen} block(s) claim {VERBATIM}; "
                f"nothing to verify"
            )
        return (
            f"{self.metric}  {self.value:.4f}  {self.numerator}/{self.denominator} verified "
            f"(sampled {self.sampled} of {self.denominator}; "
            f"{self.denominator_frac:.4f} of {self.blocks_seen} blocks claim {VERBATIM})"
        )


def claims(runs: Sequence[ParseRun]) -> tuple[Claim, ...]:
    """Every block whose own `quote` claims verbatimness, across every run.

    The card is not consulted. A card declares what a driver *can* do and `achieved` records what
    it did for one document, but neither is the block's claim — 07-store-and-retrieval.md:2558 puts
    it first among the four properties the renderer got wrong somewhere in the collection: *"It
    reads `doc.achieved`, never a driver card."* This reads neither: it reads the block.
    """
    found: list[Claim] = []
    for run_result in runs:
        for block in run_result.blocks:
            if str(block.get("quote", "")) != VERBATIM:
                continue
            found.append(
                Claim(
                    fixture=run_result.fixture.name,
                    tmp=str(block.get("tmp", "?")),
                    text=str(block.get("text", "")),
                    origin=block.get("os") or {},
                    data=run_result.fixture.data,
                )
            )
    return tuple(found)


def sample(population: Sequence[Claim], n: int = SAMPLE_N) -> tuple[Claim, ...]:
    """The `n` claims with the lowest `blake2b` key, or all of them when there are fewer.

    Deterministic and RNG-free; see the module docstring for why that is a rule and not a taste.
    """
    if len(population) <= n:
        return tuple(population)
    return tuple(sorted(population, key=lambda claim: claim.sort_key)[:n])


def span_exact_rate(
    runs: Sequence[ParseRun],
    driver: object = None,
    *,
    n: int = SAMPLE_N,
) -> MetricResult:
    """13-quality.md:1092's row, computed.

    `driver` is consulted only for its `verify_origin()` hook, which the `nodepath` and `glyphs`
    branches need and the `bytes` branch does not. The re-read itself is
    `harness.reverify_origin()` — the same call the `capability` suite's P7 makes, over a different
    population — so the two can never disagree about what INV-10 means.
    """
    blocks_seen = sum(len(run_result.blocks) for run_result in runs)
    population = claims(runs)
    if not population:
        return MetricResult(
            metric="span_exact_rate",
            state="vacuous",
            value=None,
            numerator=0,
            denominator=0,
            sampled=0,
            blocks_seen=blocks_seen,
            failures=(),
        )

    hook = getattr(driver, ORIGIN_VERIFIER, None) if driver is not None else None
    chosen = sample(population, n)
    verified = 0
    failures: list[str] = []
    for claim in chosen:
        check = reverify_origin(claim.data, claim.origin, claim.text, hook)
        if check.ok:
            verified += 1
        else:
            failures.append(
                f"{claim.fixture}:{claim.tmp} [{check.branch}] {check.detail} "
                f"| wanted {claim.text[:60]!r} got {check.got[:60]!r}"
            )
    return MetricResult(
        metric="span_exact_rate",
        state="measured",
        value=verified / len(chosen),
        numerator=verified,
        denominator=len(population),
        sampled=len(chosen),
        blocks_seen=blocks_seen,
        failures=tuple(failures),
    )
