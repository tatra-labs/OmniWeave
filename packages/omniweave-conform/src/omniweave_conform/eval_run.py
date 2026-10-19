"""`ow eval run`: the parse suite (D868) and the absence suite's deterministic half (D869).

13-quality.md:1873 prints `ow eval run [--suite S] [--corpus C@V] [--subject D] [--witness W]
[--cassette MODE] [--validate-judge] [--emit PATH]`, and 16-roadmap.md:942 makes it W10.6's
instrument. Until this module nothing wrote an `.oweval`, so `ow eval release-check` had nothing to
judge. `tools/ow_eval.py golden --check span_exact_rate` measured the one parse metric this build
can compute and printed it; this module measures the same thing, through the same calls, and
returns it as `store.oweval` rows for one `write()`.

## Rulings

1. **The suite's subjects are the register's `[[subject]]` rows**, each a driver card and its
   fixture set, as `tools/ow_eval.py` reads them. `--subject D` keeps the rows whose card's driver
   id is `D`. Every fixture is parsed through `harness.run_parse()`; a `DriverError` is the driver
   refusing an abuse case and is counted, never hidden.
2. **The suite's metrics are the register's `[[gate]]` rows with `suite = "parse"` that this build
   computes**, which is `span_exact_rate` alone, over `evaluate.span_exact_rate()`. A parse row the
   build cannot compute is named in the run's `not_measured`, as are the three accuracy metrics
   (`structure_f1`, `table_rel_acc`, `order_acc`), which need a labelled corpus (W10.8).
3. **A subject's fixture set is its corpus, Tier A.** D844 made Tier A every committed byte under a
   `fixtures/` directory. `corpus_id` is the directory, relative and POSIX, and `corpus_digest` is
   the DDL's `sha256 over sorted (relpath, sha256)`, NUL-framed. `version` is the digest's first
   sixteen hex characters, so changing a fixture is a new corpus version, never an edit of an
   immutable one (`store.oweval` ruling 6). The documents are committed, so they are
   redistributable, and there are no assertions to restrict. **`publishable` is false**: a driver's
   own fixtures are written by its authors, and 13:1228 is plain that *"a scoreboard on which the
   author always wins is a marketing page"*. The scoreboard reads such a row as `WITHHELD`, never
   `UNKNOWN`.
4. **`span_exact_rate`'s truth is `native_run`.** The register writes `truth_kind =
   "self_verifying"`, which is not one of the six `TruthKind`s the `eval_metric` CHECK admits. The
   metric re-verifies each claimed span against the source bytes, which is 13:1457's `native_run`,
   *"the source ... run text"*, admissible for **fidelity only**, and byte-exactness is fidelity.
5. **A vacuous measurement writes no metric row.** A subject whose blocks claim no verbatimness has
   no denominator (13:661, *"holds **vacuously**"*). A `value` of `None` is neither the hard
   budget nor a pass, and `unknown` would refuse a release on a driver telling the truth
   (17-risks.md R-T16). So the run is `ok` and its `not_measured` says the rate was vacuous and why.
6. **The run is a hard fidelity row, so `min_slice_n` does not apply.** The rate is
   `stats.rate(verified, sampled)`, a Wilson interval and `closed_form`, never `rollup()`'s macro
   mean, which would turn a small fixture set `unknown` for a metric 13:1092 holds at 1.000 over
   whatever is claimed.
7. **Provenance is the run's own.** `harness_version` is `badge.kit_version()`; `code_fingerprint`
   is `host.activate.code_fingerprint()` over the driver distribution's `*.py`; `timing_basis` is
   `in_process`; `measured_on` is a full `MeasuredOn`, with `n/a` for the model fields a parse
   driver has none of. `run_id` is a blake2b digest of the suite, the subject, the corpus digest
   and the start time, so no RNG is involved (13 section 3). `confounders` names the fixtures'
   authorship and every refusal, because Q-G19 refuses a published row without one.

## The absence suite's deterministic half (D869)

8. **It is `absence.run_suite()` over every built Injector**, the harness `tools/ow_damage.py`
   ran, and its one metric is `degradation_detection`: the pairs whose four clauses all hold, over
   the pairs, as `stats.rate()`, against the register's `degradation_detection` row and that row's
   `truth_kind`. Ruling 6 holds: the row is hard and fidelity-shaped, so no `min_slice_n`. Its
   slice is `deterministic_half`, the half measured.
9. **The subject is `omniweave`, the product**: absence gates fire in a store `ow add` wrote and a
   query read, so no single driver is measured. `subject_version` is the installed `omniweave`'s,
   read from distribution metadata without importing it, and `code_fingerprint` is over
   `omniweave_core`'s `*.py`, where the fifteen gates are. Each `ow` is a child, so the timing
   basis is `spawn_inclusive`.
10. **The corpus is the generated reference documents**: `reference_corpora/quick`, from the
    repository's `fixtures/gen/gen_reference_corpora.py` at `quick` scale. That generator is
    committed under `fixtures/`, Tier A (D844), and its documents are digested by name and bytes,
    so a generator change is a new corpus version. Not `publishable`, as ruling 3.
11. **What the half does not measure is named**: the Injectors the table owes and nothing builds,
    and the absence-corpus half's metrics (`false_confident_zero`, `absent_precision`,
    `absent_recall`), which need the T4 absence corpus. A failed pair is a confounder, by name,
    and lowers the rate, which `release-check` then refuses as off its hard budget.

Specified in 13-quality.md sections 2.10, 8.3, 8.6 and 13.3, and 16-roadmap.md W10.6.
"""

from __future__ import annotations

import hashlib
import platform
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.drivers.card import MeasuredOn
from omniweave_core.errors import QualityError
from omniweave_core.host.activate import code_fingerprint
from omniweave_core.store.oweval import Batch, Corpus, Metric, Run
from omniweave_ports.types import DriverError

from omniweave_conform import absence as damage_half
from omniweave_conform.badge import kit_version
from omniweave_conform.damage import INJECTORS, TABLE
from omniweave_conform.evaluate import span_exact_rate
from omniweave_conform.harness import run_parse
from omniweave_conform.stats import rate
from omniweave_conform.subject import Subject

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_conform.evaluate import MetricResult

__all__ = [
    "ABSENCE_UNMEASURED",
    "BUILT",
    "MEASURED",
    "PARSE_UNMEASURED",
    "TRUTH_KINDS",
    "Measured",
    "absence",
    "corpus_digest",
    "parse",
]

BUILT: Final[tuple[str, ...]] = ("parse", "absence")
"""The suites `ow eval run` measures in this build, in run order. The other five are refused."""

DETECTION: Final = "degradation_detection"
"""Ruling 8: the absence half's one metric, the register's hard row."""

ABSENCE_UNMEASURED: Final[tuple[str, ...]] = (
    "false_confident_zero, absent_precision, absent_recall: the absence corpus half needs the "
    "T4 absence corpus, which does not exist (13 section 8.6)",
)
"""Ruling 11: the half not run, named in every absence run's `not_measured`."""

TRUTH_KINDS: Final[frozenset[str]] = frozenset(
    {"human", "rendered", "native_run", "synth_ocr", "agreement", "self"}
)
"""`eval_metric.truth_kind`'s CHECK, the six `TruthKind`s 13:1452 tabulates."""

MEASURED: Final[Mapping[str, tuple[Callable[..., MetricResult], str]]] = {
    "span_exact_rate": (span_exact_rate, "native_run"),
}
"""Each parse metric this build computes, with its `TruthKind` (rulings 2 and 4)."""

PARSE_UNMEASURED: Final[tuple[str, ...]] = (
    "structure_f1, table_rel_acc, order_acc: no labelled corpus exists to score them (W10.8)",
)
"""Ruling 2: the parse suite's accuracy metrics, named in every parse run's `not_measured`."""

NOT_APPLICABLE: Final = "n/a"
"""A `MeasuredOn` field a parse driver has no value for: it runs no model (ruling 7)."""


@dataclass(frozen=True, slots=True)
class Measured:
    """One subject's run, for the verb to print."""

    run_id: str
    suite: str
    subject: str
    slice_key: str
    corpus_id: str
    metric: str
    value: float | None
    n: int
    parsed: int
    """Parse: the fixtures the driver parsed. Absence: the pairs that passed."""
    refused: tuple[str, ...]
    """Parse: the fixtures the driver refused, each with its class. Absence: the failed pairs."""


def corpus_digest(root: Path, files: Sequence[Path]) -> str:
    """The DDL's `sha256 over sorted (relpath, sha256)`, NUL-framed (ruling 3)."""
    framed = hashlib.sha256()
    for relpath, digest in sorted(
        (path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in files
    ):
        framed.update(relpath.encode("utf-8") + b"\x00" + digest.encode("ascii") + b"\x00")
    return framed.hexdigest()


def parse(
    register: Mapping[str, Any],
    *,
    root: Path,
    subject: str | None,
    witness: str,
    cassette: str,
    now_ns: Callable[[], int],
) -> tuple[Batch, tuple[Measured, ...]]:
    """The parse suite over the register's subjects, as one `Batch` (rulings 1-7)."""
    gates = [row for row in register.get("gate", []) if row.get("suite") == "parse"]
    computed = [row for row in gates if row.get("metric") in MEASURED]
    unmeasured = [
        f"{row.get('metric')}: this build does not compute it"
        for row in gates
        if row.get("metric") not in MEASURED
    ]
    rows = [row for row in register.get("subject", []) if isinstance(row, dict)]
    if not rows:
        raise QualityError(
            "the metric register names no [[subject]] to run the parse suite over",
            fix="add a [[subject]] row with a card and its fixtures to eval/gates.toml",
        )
    corpora: dict[tuple[str, str], Corpus] = {}
    runs: list[Run] = []
    metrics: list[Metric] = []
    done: list[Measured] = []
    matched = 0
    for row in rows:
        card = root / str(row.get("card", ""))
        fixtures_dir = root / str(row.get("fixtures", ""))
        with tempfile.TemporaryDirectory(prefix="ow-eval-run-") as scratch:
            workdir = Path(scratch)
            found = Subject.of(card, fixtures_dir=fixtures_dir, workdir=workdir)
            if subject is not None and found.driver_id != subject:
                continue
            matched += 1
            started = now_ns()
            driver = found.instantiate()
            parses = []
            refused: list[str] = []
            for index, fixture in enumerate(found.fixtures):
                try:
                    parses.append(run_parse(driver, fixture, workdir / f"run-{index}"))
                except DriverError as error:
                    refused.append(f"{fixture.path.name} ({error.cls.value})")
            results = [
                (
                    gate,
                    MEASURED[str(gate["metric"])][0](
                        parses, driver, n=int(gate.get("sample_n", 1000))
                    ),
                )
                for gate in computed
            ]
            fingerprint = code_fingerprint(found.source_files())
        corpus = _corpus(root, fixtures_dir, [fixture.path for fixture in found.fixtures])
        corpora[corpus.corpus_id, corpus.version] = corpus
        slice_key = str(row.get("slice", "*"))
        run_id = _run_id("parse", found.driver_id, corpus.corpus_digest, started)
        vacuous = [
            f"{result.metric}: vacuous, no block claims verbatimness, so nothing could fail "
            f"(13:661, R-T16); {result.blocks_seen} block(s) seen"
            for _gate, result in results
            if result.value is None
        ]
        runs.append(
            Run(
                run_id=run_id,
                suite="parse",
                corpus_id=corpus.corpus_id,
                corpus_version=corpus.version,
                corpus_digest=corpus.corpus_digest,
                subject=found.driver_id,
                subject_version=found.card.identity.version,
                producer_id=None,
                measured_on=_measured_on(corpus),
                timing_basis="in_process",
                witness=witness,
                cassette=cassette,
                policy_digest=None,
                pricebook_digest=None,
                harness_version=kit_version(),
                code_fingerprint=fingerprint,
                hardware=_hardware(),
                started_ns=started,
                ended_ns=now_ns(),
                status="ok",
                not_measured=(*vacuous, *unmeasured, *PARSE_UNMEASURED),
                confounders=(
                    "the fixtures are the driver's own, written by its authors",
                    f"{len(refused)} fixture(s) refused by the driver"
                    + (f": {', '.join(refused)}" if refused else ""),
                ),
            )
        )
        for gate, result in results:
            if result.value is None:
                continue
            estimate = rate(result.numerator, result.sampled)
            metrics.append(
                Metric(
                    run_id=run_id,
                    metric=result.metric,
                    value=estimate.value,
                    n=estimate.n,
                    ci_lo=estimate.ci_lo,
                    ci_hi=estimate.ci_hi,
                    method=estimate.method,
                    truth_kind=MEASURED[str(gate["metric"])][1],
                    state="ok",
                    slice_key=slice_key,
                )
            )
        value = next((result.value for _gate, result in results), None)
        sampled = next((result.sampled for _gate, result in results), 0)
        done.append(
            Measured(
                run_id=run_id,
                suite="parse",
                subject=found.driver_id,
                slice_key=slice_key,
                corpus_id=corpus.corpus_id,
                metric=next(iter(MEASURED)),
                value=value,
                n=sampled,
                parsed=len(parses),
                refused=tuple(refused),
            )
        )
    if subject is not None and matched == 0:
        raise QualityError(
            f"no [[subject]] in the metric register is driver {subject!r}",
            fix="ow eval run --suite parse --subject <a driver id the register names>",
        )
    batch = Batch(corpora=tuple(corpora.values()), runs=tuple(runs), metrics=tuple(metrics))
    return batch, tuple(done)


def absence(
    register: Mapping[str, Any],
    *,
    root: Path,
    witness: str,
    cassette: str,
    now_ns: Callable[[], int],
    admit: Callable[[Sequence[str]], str | None],
    workers: int = 4,
) -> tuple[Batch, tuple[Measured, ...]]:
    """The absence suite's deterministic half as one `Batch` (rulings 8-11)."""
    gate = next(
        (
            row
            for row in register.get("gate", [])
            if row.get("suite") == "absence" and row.get("metric") == DETECTION
        ),
        None,
    )
    if gate is None:
        raise QualityError(
            f"the metric register has no absence {DETECTION} row to measure against",
            fix=f"add a [[gate]] row with metric = {DETECTION!r} and suite = 'absence'",
        )
    truth = str(gate.get("truth_kind", ""))
    if truth not in TRUTH_KINDS:
        raise QualityError(
            f"the register's {DETECTION} truth_kind {truth!r} is not one of "
            f"{', '.join(sorted(TRUTH_KINDS))}",
            fix="name one of the six TruthKinds (13-quality.md:1452) in eval/gates.toml",
        )
    started = now_ns()
    try:
        suite = damage_half.run_suite(
            list(INJECTORS), root=root, admit=admit, now_ns=now_ns, workers=workers
        )
    except (RuntimeError, OSError) as error:
        raise QualityError(
            f"the absence suite could not run: {type(error).__name__}: {error}",
            fix="python tools/ow_damage.py --deterministic-half --keep <dir>  # every clause, kept",
        ) from error
    ended = now_ns()
    digest = damage_half.documents_digest(suite.documents)
    corpus = Corpus(
        corpus_id="reference_corpora/quick",
        version=digest[:16],
        corpus_digest=digest,
        tier="A",
        n_docs=len(suite.documents),
        n_assertions=0,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )
    failed = tuple(
        f"{result.injector} x {result.fixture}" for result in suite.assessments if not result.ok
    )
    owed = [row.name for row in TABLE if row.name not in INJECTORS]
    subject_version = _version("omniweave")
    run_id = _run_id("absence", "omniweave", digest, started)
    run = Run(
        run_id=run_id,
        suite="absence",
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        corpus_digest=digest,
        subject="omniweave",
        subject_version=subject_version,
        producer_id=None,
        measured_on=_measured_on(corpus),
        timing_basis="spawn_inclusive",
        witness=witness,
        cassette=cassette,
        policy_digest=None,
        pricebook_digest=None,
        harness_version=kit_version(),
        code_fingerprint=code_fingerprint(_core_sources()),
        hardware=_hardware(),
        started_ns=started,
        ended_ns=ended,
        status="ok",
        not_measured=(
            f"{len(owed)} of {len(TABLE)} Injectors are not built: {', '.join(owed)}",
            *ABSENCE_UNMEASURED,
        ),
        confounders=(
            "the documents are the repository's own generated reference corpora, quick scale",
            f"{len(failed)} pair(s) failed" + (f": {', '.join(failed)}" if failed else ""),
        ),
    )
    passed = len(suite.assessments) - len(failed)
    estimate = rate(passed, len(suite.assessments))
    metrics: tuple[Metric, ...] = ()
    if suite.assessments:
        metrics = (
            Metric(
                run_id=run_id,
                metric=DETECTION,
                value=estimate.value,
                n=estimate.n,
                ci_lo=estimate.ci_lo,
                ci_hi=estimate.ci_hi,
                method=estimate.method,
                truth_kind=truth,
                state="ok",
                slice_key="deterministic_half",
            ),
        )
    done = Measured(
        run_id=run_id,
        suite="absence",
        subject="omniweave",
        slice_key="deterministic_half",
        corpus_id=corpus.corpus_id,
        metric=DETECTION,
        value=estimate.value,
        n=len(suite.assessments),
        parsed=passed,
        refused=failed,
    )
    return Batch(corpora=(corpus,), runs=(run,), metrics=metrics), (done,)


def _version(distribution: str) -> str:
    """Ruling 9: an installed distribution's version, read without importing it."""
    from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

    try:
        return version(distribution)
    except PackageNotFoundError:
        return "0+unknown"


def _core_sources() -> tuple[Path, ...]:
    """Ruling 9: `omniweave_core`'s `*.py`, where the absence gates are."""
    import omniweave_core  # noqa: PLC0415

    return tuple(sorted(Path(omniweave_core.__file__).parent.rglob("*.py")))


def _corpus(root: Path, fixtures_dir: Path, files: Sequence[Path]) -> Corpus:
    """Ruling 3: a fixture set as a Tier A corpus, versioned by its digest."""
    digest = corpus_digest(fixtures_dir, files)
    return Corpus(
        corpus_id=fixtures_dir.relative_to(root).as_posix(),
        version=digest[:16],
        corpus_digest=digest,
        tier="A",
        n_docs=len(files),
        n_assertions=0,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )


def _measured_on(corpus: Corpus) -> MeasuredOn:
    """Ruling 7: the ten fields, `n/a` where a parse driver has no model to name."""
    return MeasuredOn(
        weights=NOT_APPLICABLE,
        weights_revision=NOT_APPLICABLE,
        runtime=platform.python_implementation().lower(),
        runtime_version=platform.python_version(),
        sampling=NOT_APPLICABLE,
        prompt_version=NOT_APPLICABLE,
        hardware=_hardware(),
        corpus=f"{corpus.corpus_id}@{corpus.version}",
        corpus_digest=corpus.corpus_digest,
        harness_version=kit_version(),
    )


def _hardware() -> str:
    return f"{platform.system().lower()}-{platform.machine().lower()}"


def _run_id(suite: str, subject: str, digest: str, started_ns: int) -> str:
    """Ruling 7: a digest, not a random draw."""
    material = f"{suite}\x00{subject}\x00{digest}\x00{started_ns}".encode()
    return hashlib.blake2b(material, digest_size=16).hexdigest()
