"""`ow eval run`: four suites measured (D868-D871), and the other three reported unknown (D872).

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

## The retrieve suite's self-verifying half (D870)

12. **It is `retrieval.run_suite()`**: the adoption catalogue's questions, every one but the
    `damaged`, asked of the three generated corpora at `quick` scale, each built by a real `ow add`.
    Its two metrics are the register's two self-verifying retrieve rows. `citability_violations` is
    a **count** (13:1094), so its value is the number of Answers with an unresolved cite, its `n`
    the Answers asked, its method `exact` and its interval none. `citation_soundness` is the sound
    cites over the cites, as `stats.rate()`. Both are sliced `born_digital`, the catalogue's only
    `source` in the tree, the six scanned tasks being owed.
13. **The register's `self_verifying` is `native_run` here too** (ruling 4): a cite resolving to
    the block it names is checked against the store the Answer was read from, which is fidelity.
    One map, `TRUTH_OF`, carries the register's word to a `TruthKind`; any other word must already
    be one.
14. **The subject is `omniweave` and the corpus `reference_corpora/quick`**, as rulings 9 and 10
    hold for the absence half; its documents are all three corpora's, so its digest, and so its
    version, differ from the absence half's. What the half does not measure is named: the
    relevance metrics (`recall_at_10`, `ndcg_at_10`, `qa_accuracy`), which need relevance labels
    (16:689's `golden-queries.jsonl`); OUT11's artefact half of `citability_violations`; and the
    `damaged` tasks.

## The roundtrip suite (D871)

15. **One run per register `[[target]]`**, its subject the compile driver, over `roundtrip.judge()`:
    the target's golden compiled, read back, and law R2 stated for every element carrying
    `data-ow-el`. Each element is one `eval_assertion` of 13:1011's `roundtrip` type and one
    `owdoc` verdict, passed when no R2 failure names it. The golden is the corpus, Tier A and not
    publishable, as ruling 3, and an assertion's id carries the corpus version, so a changed golden
    names new assertions rather than editing immutable ones. An assertion's `checked` is NULL: it is
    derived from the golden's IL by the harness, and no reviewer verified it. Its
    `derived_from_sha256` is the sha256 of the IL unit file its element lives in, the bytes it was
    written from (D875), so Q-G26 can hold it to its own corpus; D871 wrote the golden's digest.
16. **No metric row, because the plan names none.** 13:1564 gives R2 *"the `roundtrip` assertion
    type"* and no metric, so a failed element is a failed verdict on the record and not a gate:
    `release-check` refuses on a metric or a run, never on a verdict. That is named in every run's
    confounders. An R2 the suite could not judge (a gate short of `lower()`, OUT23) is a run with
    status `unknown` and the suite's reason, which `release-check` does refuse.

## The three suites this build cannot measure (D872)

17. **Every suite can report `unknown`.** 16-roadmap.md:942: *"`skip` is not a state, so every
    suite must be able to report `unknown` and `release-check` must refuse on it."* So
    `ow eval run --suite extract`, `portability` or `perf` writes one run with status `unknown`
    whose `not_measured` says, in `UNMEASURABLE`, exactly what is missing. Nothing is measured and
    nothing is pretended: the run has no corpus row, no metric and no perf row, its corpus fields
    say `none`, and its one confounder says it exists only to name the gap. `release-check`
    then refuses it by that reason, where `--strict` alone would have said *"no run at all"*.
18. **They are named, never run by default.** `--suite` omitted runs `BUILT`, the suites whose
    runs this machine can judge; an `unknown` run is written only when a caller asks for one.

Specified in 13-quality.md sections 2.10, 8.3, 8.6, 8.8, 9 and 13.3, and 16-roadmap.md W10.6.
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
from omniweave_core.store.oweval import Assertion, Batch, Corpus, Metric, Run, Verdict
from omniweave_ports.types import DriverError

from omniweave_conform import absence as damage_half
from omniweave_conform import retrieval as cite_half
from omniweave_conform import roundtrip as r2_half
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
    "SUITES",
    "TRUTH_KINDS",
    "TRUTH_OF",
    "UNMEASURABLE",
    "Measured",
    "absence",
    "corpus_digest",
    "parse",
    "retrieve",
    "roundtrip",
    "unknown",
]

BUILT: Final[tuple[str, ...]] = ("parse", "absence", "retrieve", "roundtrip")
"""The suites `ow eval run` measures in this build, in run order. The other three are refused."""

UNMEASURABLE: Final[Mapping[str, str]] = {
    "extract": (
        "no extraction harness and no labelled extraction corpus: field_acc, doc_acc and "
        "hallucination_rate need one (13-quality.md:1179-1192, W10.8)"
    ),
    "portability": (
        "13-quality.md defines the portability suite by its name alone (13:238, 13:2056): there "
        "is nothing to run until the plan says what it measures"
    ),
    "perf": (
        "eval_perf rows pass or fail against 7-run rolling medians on the pinned runner "
        "ow-bench-1 (eval/perf.toml [pacer], 12-performance.md section 7), which this machine is "
        "not; one paced reading is unknown by definition"
    ),
}
"""Ruling 17: each suite this build cannot measure, and exactly why."""

SUITES: Final[tuple[str, ...]] = (*BUILT, *UNMEASURABLE)
"""Every suite `ow eval run` accepts: the four it measures, then the three it reports unknown."""

ROUNDTRIP_CONFOUNDER: Final = (
    "no eval/gates.toml row folds R2 into a metric (13-quality.md:1564 names the roundtrip "
    "assertion type and no metric), so a failed element is a failed verdict and does not refuse "
    "a release"
)
"""Ruling 16, said in every roundtrip run."""

VIOLATIONS: Final = "citability_violations"
SOUNDNESS: Final = "citation_soundness"
"""Ruling 12: the retrieve half's two metrics, the register's two self-verifying retrieve rows."""

RETRIEVE_UNMEASURED: Final[tuple[str, ...]] = (
    "recall_at_10, ndcg_at_10, qa_accuracy: no relevance labels exist to score them "
    "(16-roadmap.md:689's golden-queries.jsonl)",
    "citability_violations' artefact half, OUT11's restricted items: no compile is run",
)
"""Ruling 14: what every retrieve run names in `not_measured`, after the damaged tasks."""

TRUTH_OF: Final[Mapping[str, str]] = {"self_verifying": "native_run"}
"""Rulings 4 and 13: the register's one word that is not a `TruthKind`, and the one it means."""

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


def retrieve(
    register: Mapping[str, Any],
    *,
    root: Path,
    witness: str,
    cassette: str,
    now_ns: Callable[[], int],
) -> tuple[Batch, tuple[Measured, ...]]:
    """The retrieve suite's self-verifying half as one `Batch` (rulings 12-14)."""
    rows = {
        str(row.get("metric")): row
        for row in register.get("gate", [])
        if row.get("suite") == "retrieve" and row.get("metric") in (VIOLATIONS, SOUNDNESS)
    }
    missing = [metric for metric in (VIOLATIONS, SOUNDNESS) if metric not in rows]
    if missing:
        raise QualityError(
            f"the metric register has no retrieve {', '.join(missing)} row to measure against",
            fix="add the retrieve [[gate]] rows 13-quality.md:1094 and :1101 define",
        )
    truth = {metric: _truth(rows[metric], metric) for metric in rows}
    started = now_ns()
    try:
        with tempfile.TemporaryDirectory(prefix="ow-eval-retrieve-") as work:
            checked = cite_half.run_suite(root, work=Path(work), now_ns=now_ns)
    except (RuntimeError, OSError) as error:
        raise QualityError(
            f"the retrieve suite could not run: {type(error).__name__}: {error}",
            fix="python fixtures/gen/gen_reference_corpora.py --all  # every corpus generates?",
        ) from error
    ended = now_ns()
    digest = damage_half.documents_digest(checked.documents)
    corpus = Corpus(
        corpus_id="reference_corpora/quick",
        version=digest[:16],
        corpus_digest=digest,
        tier="A",
        n_docs=len(checked.documents),
        n_assertions=0,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )
    unsound = tuple(f"{one.task_id}: {cite}" for one in checked.asked for cite in one.unsound)
    run_id = _run_id("retrieve", "omniweave", digest, started)
    run = Run(
        run_id=run_id,
        suite="retrieve",
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        corpus_digest=digest,
        subject="omniweave",
        subject_version=_version("omniweave"),
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
            f"{checked.skipped} damaged task(s): each needs a damaged corpus, the absence "
            "suite's business",
            *RETRIEVE_UNMEASURED,
        ),
        confounders=(
            "the questions are the adoption catalogue's and the documents the repository's own "
            "generated reference corpora, quick scale",
            f"{len(unsound)} cite(s) did not resolve"
            + (f": {', '.join(unsound)}" if unsound else ""),
        ),
    )
    soundness = rate(checked.sound, checked.cites)
    metrics = (
        Metric(
            run_id=run_id,
            metric=VIOLATIONS,
            value=float(checked.violations),
            n=len(checked.asked),
            ci_lo=None,
            ci_hi=None,
            method="exact",
            truth_kind=truth[VIOLATIONS],
            state="ok",
            slice_key="born_digital",
        ),
        Metric(
            run_id=run_id,
            metric=SOUNDNESS,
            value=soundness.value,
            n=soundness.n,
            ci_lo=soundness.ci_lo,
            ci_hi=soundness.ci_hi,
            method=soundness.method,
            truth_kind=truth[SOUNDNESS],
            state="ok" if soundness.value is not None else "unknown",
            slice_key="born_digital",
        ),
    )
    done = Measured(
        run_id=run_id,
        suite="retrieve",
        subject="omniweave",
        slice_key="born_digital",
        corpus_id=corpus.corpus_id,
        metric=VIOLATIONS,
        value=float(checked.violations),
        n=len(checked.asked),
        parsed=checked.sound,
        refused=unsound,
    )
    return Batch(corpora=(corpus,), runs=(run,), metrics=metrics), (done,)


def roundtrip(
    register: Mapping[str, Any],
    *,
    root: Path,
    witness: str,
    cassette: str,
    now_ns: Callable[[], int],
) -> tuple[Batch, tuple[Measured, ...]]:
    """One run per register `[[target]]`, its R2 as one verdict per element (rulings 15-16)."""
    rows = r2_half.targets(register, root)
    if not rows:
        raise QualityError(
            "the metric register names no [[target]] for the roundtrip suite to read back",
            fix="add a [[target]] row: a card, its read_back card and a golden, to eval/gates.toml",
        )
    corpora: list[Corpus] = []
    assertions: list[Assertion] = []
    runs: list[Run] = []
    verdicts: list[Verdict] = []
    done: list[Measured] = []
    for target in rows:
        started = now_ns()
        try:
            judged = r2_half.judge(target)
        except (RuntimeError, OSError, TypeError) as error:
            raise QualityError(
                f"the roundtrip suite could not run {target.target}: "
                f"{type(error).__name__}: {error}",
                fix=f"ow conform --target {target.target}  # the target suite, every law",
            ) from error
        ended = now_ns()
        digest = r2_half.golden_digest(target.golden)
        corpus = Corpus(
            corpus_id=target.golden.relative_to(root).as_posix(),
            version=digest[:16],
            corpus_digest=digest,
            tier="A",
            n_docs=len(judged.il_units),
            n_assertions=len(judged.elements),
            n_checked=0,
            document_redistributable=True,
            assertions_redistributable=True,
            publishable=False,
        )
        corpora.append(corpus)
        run_id = _run_id("roundtrip", judged.driver, digest, started)
        failed = tuple(f"{e.el} ({e.explanation})" for e in judged.elements if not e.passed)
        runs.append(
            Run(
                run_id=run_id,
                suite="roundtrip",
                corpus_id=corpus.corpus_id,
                corpus_version=corpus.version,
                corpus_digest=digest,
                subject=judged.driver,
                subject_version=judged.version,
                producer_id=None,
                measured_on=_measured_on(corpus),
                timing_basis="in_process",
                witness=witness,
                cassette=cassette,
                policy_digest=None,
                pricebook_digest=None,
                harness_version=kit_version(),
                code_fingerprint=judged.fingerprint,
                hardware=_hardware(),
                started_ns=started,
                ended_ns=ended,
                status="unknown" if judged.unknown is not None else "ok",
                not_measured=(
                    *((f"R2: {judged.unknown}",) if judged.unknown is not None else ()),
                    "R1 and R3-R7 are the target suite's to judge (ow conform --target); this run "
                    "states R2, 13's roundtrip assertion type",
                ),
                confounders=(
                    f"the golden is the target's own fixture, its gate {judged.gate}",
                    ROUNDTRIP_CONFOUNDER,
                    f"{len(failed)} element(s) failed R2"
                    + (f": {', '.join(failed)}" if failed else ""),
                ),
            )
        )
        units = {path.stem: path for path in judged.il_units}
        for element in judged.elements:
            assertion_id = f"roundtrip/{target.target}@{corpus.version}/{element.el}"
            unit = units.get(element.el.split("/", 1)[0])
            assertions.append(
                Assertion(
                    assertion_id=assertion_id,
                    corpus_id=corpus.corpus_id,
                    corpus_version=corpus.version,
                    doc=f"il/{unit.name if unit is not None else element.el.split('/', 1)[0]}",
                    page=None,
                    type="roundtrip",
                    spec={"law": r2_half.LAW, "construct": element.construct},
                    addr=element.el,
                    evaluable_in="owdoc",
                    checked=None,
                    derived_from_sha256=(
                        hashlib.sha256(unit.read_bytes()).hexdigest()
                        if unit is not None
                        else digest
                    ),
                    slices=(target.target,),
                )
            )
            verdicts.append(
                Verdict(
                    run_id=run_id,
                    assertion_id=assertion_id,
                    evaluator="owdoc",
                    passed=element.passed,
                    score=None,
                    slice_key=target.target,
                    explanation=element.explanation,
                )
            )
        survived = sum(1 for e in judged.elements if e.passed)
        done.append(
            Measured(
                run_id=run_id,
                suite="roundtrip",
                subject=judged.driver,
                slice_key=target.target,
                corpus_id=corpus.corpus_id,
                metric=r2_half.LAW,
                value=None if not judged.elements else survived / len(judged.elements),
                n=len(judged.elements),
                parsed=survived,
                refused=failed if judged.unknown is None else (f"unknown: {judged.unknown}",),
            )
        )
    batch = Batch(
        corpora=tuple(corpora),
        assertions=tuple(assertions),
        runs=tuple(runs),
        verdicts=tuple(verdicts),
    )
    return batch, tuple(done)


def unknown(
    suite: str, *, witness: str, cassette: str, now_ns: Callable[[], int]
) -> tuple[Batch, tuple[Measured, ...]]:
    """Ruling 17: one `unknown` run naming why `suite` cannot be measured here."""
    reason = UNMEASURABLE.get(suite)
    if reason is None:
        raise QualityError(
            f"{suite!r} is a suite this build measures or none of the seven",
            fix=f"ow eval run --suite {suite}",
        )
    started = now_ns()
    digest = hashlib.sha256(b"").hexdigest()
    corpus = Corpus(
        corpus_id="none",
        version="none",
        corpus_digest=digest,
        tier="A",
        n_docs=0,
        n_assertions=0,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )
    run_id = _run_id(suite, "omniweave", digest, started)
    run = Run(
        run_id=run_id,
        suite=suite,
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        corpus_digest=digest,
        subject="omniweave",
        subject_version=_version("omniweave"),
        producer_id=None,
        measured_on=_measured_on(corpus),
        timing_basis="in_process",
        witness=witness,
        cassette=cassette,
        policy_digest=None,
        pricebook_digest=None,
        harness_version=kit_version(),
        code_fingerprint=code_fingerprint(_core_sources()),
        hardware=_hardware(),
        started_ns=started,
        ended_ns=now_ns(),
        status="unknown",
        not_measured=(reason,),
        confounders=(
            "nothing was measured: this run exists so release-check names the gap, as 16:942 "
            "requires of every suite",
        ),
    )
    done = Measured(
        run_id=run_id,
        suite=suite,
        subject="omniweave",
        slice_key="none",
        corpus_id=corpus.corpus_id,
        metric="none",
        value=None,
        n=0,
        parsed=0,
        refused=(reason,),
    )
    return Batch(runs=(run,)), (done,)


def _truth(row: Mapping[str, Any], metric: str) -> str:
    """Ruling 13: a register row's `truth_kind` as a `TruthKind`, or a refusal naming it."""
    word = str(row.get("truth_kind", ""))
    truth = TRUTH_OF.get(word, word)
    if truth not in TRUTH_KINDS:
        raise QualityError(
            f"the register's {metric} truth_kind {word!r} is not one of "
            f"{', '.join(sorted(TRUTH_KINDS))}",
            fix="name one of the six TruthKinds (13-quality.md:1452) in eval/gates.toml",
        )
    return truth


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
