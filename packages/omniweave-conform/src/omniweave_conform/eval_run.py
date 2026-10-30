"""`ow eval run`: five suites measured (D868-D871, D903), and the other two reported unknown.

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
11. **What the half does not measure is named**: the Injectors the table owes and nothing builds.
    A failed pair is a confounder, by name, and lowers the rate, which `release-check` then
    refuses as off its hard budget. The absence corpus's metrics are the removal half's
    (rulings 25-28), and a `--deterministic-half` run names them as left out.

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
16. **R2 is the hard `address_survival` row** (D902, a user ruling of 2026-10-19). 13:1564 gives
    R2 *"the `roundtrip` assertion type"* and no metric, so until the ruling a failed element was
    a failed verdict on the record and refused nothing. Each judged target's run now writes one
    `address_survival` metric, its slice the target, the surviving fraction of its elements; the
    register's row is `hard` at 1.000, so `release-check` refuses on any element that did not
    survive. An R2 the suite could not judge (a gate short of `lower()`, OUT23) writes no metric
    and is a run with status `unknown` and the suite's reason, which `release-check` refuses too.

## The suites this build cannot measure (D872)

17. **Every suite can report `unknown`.** 16-roadmap.md:942: *"`skip` is not a state, so every
    suite must be able to report `unknown` and `release-check` must refuse on it."* So
    `ow eval run --suite extract` or `perf` writes one run with status `unknown`
    whose `not_measured` says, in `UNMEASURABLE`, exactly what is missing. Nothing is measured and
    nothing is pretended: the run has no corpus row, no metric and no perf row, its corpus fields
    say `none`, and its one confounder says it exists only to name the gap. `release-check`
    then refuses it by that reason, where `--strict` alone would have said *"no run at all"*.
18. **They are named, never run by default.** `--suite` omitted runs `BUILT`, the suites whose
    runs this machine can judge; an `unknown` run is written only when a caller asks for one.

## The parse suite's labelled half (D912)

22. **A fixture's labels are judged over the parse's own pages.** A fixture with a
    `<file>.assertions.toml` (`omniweave_conform.labels`) has its assertions loaded under the
    subject's corpus, and its parse is decoded into a scratch store and served page by page as
    Markdown, the text a reader gets. `judge()` (D827) runs them and `rollup()` (D816) turns the
    verdicts into each of `RATES`' metrics that some assertion's type feeds: `table_rel_acc`,
    `order_acc` and `field_acc`. The verdicts and the assertions are written with the run.
23. **The labels are the corpus.** The assertions files are digested with the fixtures, so a
    relabel is a new corpus version, and `n_assertions` and `n_checked` count them. An unverified
    assertion runs and never scores (13:1022), so a corpus with none verified writes `unknown`
    rows, which `release-check` refuses: drafted labels are a corpus nobody has vouched for.
    Each run's `not_measured` says how many ran unscored and which were not run and why.
24. **`structure_f1` is measured where a reference exists (D982).** `omniweave_conform.structure`
    loads each fixture's `<file>.structure.jsonl`, scores it against the same candidate store the
    owdoc evaluator reads, and `structure.metrics()` writes its slice rows. The references are
    digested with the labels, so adding one is a new corpus version. A subject whose card declares
    `sections = "none"` with `tables = "none"` is NOT scored: `structure.inapplicable()` has the
    card's reason and the run's `not_measured` prints it, because scoring a driver that emits no
    heading or table against a labelled tree measures the declaration. A referenced document whose
    reference is not fully signed is named unscored, one row per run.

## The absence suite's removal half (D933)

25. **`--suite absence` runs both halves, and `--deterministic-half` the paired-damage half
    alone**, the half 16:690 names. The removal half is `removal.run_suite()`: 13 section 8.6's
    Construction 1 over the adoption catalogue, each answerable question asked of its corpus as
    generated and with its planted sentence deleted. It is its own run, over its own corpus,
    `absence_corpus/quick`: `release.latest()` keeps one run per `(suite, subject, corpus)`, so
    sharing the damage half's corpus id would supersede it.
26. **Three metrics, each from `Verdict.state` alone.** `false_confident_zero` is the
    answerable questions answered `absent`, over the answerable (13:1095), against the register's
    ceiling row, whose `truth_kind` all three carry. `absent_recall` is the genuinely-absent
    questions answered `absent`, over the genuinely absent, and `absent_precision` the answered-
    `absent` that are genuinely absent, over the answered `absent`: both ungated (13:1137).
27. **`min_slice_n` applies**: none of the three is a hard row, and 13:1088 macro-averages every
    other row at 30 a slice. Below it, `false_confident_zero` is written `unknown`, which
    `release-check` refuses, because a ceiling no row can judge is not met. The two ungated rates
    are written only when measured, so an ungated rate cannot refuse a release; below it, each is
    named in `not_measured` with its counts.
28. **What the half is not is said**: the corpus is Tier A and generated where 13 section 8.6
    names a Tier-B document; the answer key is the catalogue's, which no reviewer has verified;
    and the task `removal.SHARED` keeps answerable is named. `qa_accuracy` needs a judge and is
    named as not measured.

## The portability suite (D903)

19. **Portability is the same inputs giving identical results on every cell** (a user ruling of
    2026-10-19, #7.4; `omniweave_conform.portability`). Until then it was the third suite
    reported `unknown`. A run holds this cell to committed frozen values, so its metric is the
    register's hard `cell_identity` row: the share of names identical to the frozen ones. A
    missing or extra name counts against it, and every difference is a confounder, by name.
20. **One run for the shape half, then one per register `[[target]]` for the part half.** The
    shape run's subject is `omniweave`, its corpus the Tier-A fixtures `fixtures/index.toml`
    lists, its slice `shape`, and its timing `spawn_inclusive`, because the ingest is a child
    `ow add`. A target's run is its compile driver over its golden, as ruling 15's, sliced by
    the target, `in_process`. Neither is publishable (ruling 3).
21. **What cannot be compared is refused or unknown, never passed.** A target with no row in
    `eval/portability.toml` is a `QualityError` before anything runs. An ingest that fails is one
    too, as a compile that fails is in ruling 15. No committed shape at all writes no metric and
    an `unknown` run.

Specified in 13-quality.md sections 2.10, 8.3, 8.6, 8.8, 9 and 13.3, and 16-roadmap.md W10.6.
"""

from __future__ import annotations

import hashlib
import platform
import tempfile
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.drivers.card import MIN_SLICE_N, MeasuredOn
from omniweave_core.errors import QualityError
from omniweave_core.host.activate import code_fingerprint
from omniweave_core.store.oweval import Assertion, Batch, Corpus, Metric, Run, Verdict
from omniweave_ports.types import DriverError

from omniweave_conform import absence as damage_half
from omniweave_conform import labels, structure
from omniweave_conform import portability as cell_half
from omniweave_conform import removal as removal_half
from omniweave_conform import retrieval as cite_half
from omniweave_conform import roundtrip as r2_half
from omniweave_conform.assertions import OWDOC_ONLY
from omniweave_conform.badge import kit_version
from omniweave_conform.damage import INJECTORS, TABLE
from omniweave_conform.evaluate import span_exact_rate
from omniweave_conform.harness import run_parse
from omniweave_conform.judge import Judged, judge
from omniweave_conform.rollup import RATES, rollup
from omniweave_conform.stats import rate
from omniweave_conform.subject import Subject

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from omniweave_core.model.doc import Doc

    from omniweave_conform.evaluate import MetricResult

__all__ = [
    "ABSENCE_UNMEASURED",
    "BUILT",
    "MEASURED",
    "NOT_APPLICABLE_SUITES",
    "PARSE_UNMEASURED",
    "SUITES",
    "TRUTH_KINDS",
    "TRUTH_OF",
    "UNMEASURABLE",
    "UNRUNNABLE",
    "Measured",
    "absence",
    "corpus_digest",
    "parse",
    "portability",
    "retrieve",
    "roundtrip",
    "unknown",
]

BUILT: Final[tuple[str, ...]] = ("parse", "absence", "retrieve", "roundtrip", "portability")
"""The suites `ow eval run` measures in this build, in run order. The other two are unknown."""

NOT_APPLICABLE_SUITES: Final[Mapping[str, str]] = {
    "extract": (
        "not applicable at this release: no field-extraction driver ships, `parse.fields.lift` is "
        "a tombstone with no successor, so field_acc, doc_acc and hallucination_rate are defined "
        "over a pass this build does not have (13-quality.md:1096, 1179-1192; a user ruling of "
        "2026-10-23, and 2026-10-26 for the state)"
    ),
}
"""D987: the suites this release does not owe a number for, each with the reason and the ruling.

`release.NOT_APPLICABLE` is the policy -- which suites do not refuse -- and this mapping is the
reason, one fact each; `test_conform_release.py` asserts the two agree. `extract` moved here from
`UNMEASURABLE` because the two say different things: "nothing here measures it yet" is a gap that
stays open, and "no such pass ships" is a decision with a date. Writing the second as the first
left `ow eval release-check --strict` owing a number for a driver that is a tombstone."""

UNMEASURABLE: Final[Mapping[str, str]] = {
    "perf": (
        "eval_perf rows pass or fail against 7-run rolling medians on the pinned runner "
        "ow-bench-1 (eval/perf.toml [pacer], 12-performance.md section 7), which this machine is "
        "not; one paced reading is unknown by definition"
    ),
}
"""Ruling 17: each suite this build cannot measure, and exactly why."""

UNRUNNABLE: Final[Mapping[str, str]] = {**NOT_APPLICABLE_SUITES, **UNMEASURABLE}
"""D987: every suite that writes a row and measures nothing, whichever reason it carries. One
membership test, because the dispatch in `entry.py` read `UNMEASURABLE` alone and `extract` moving
out of it sent the suite down a fall-through branch that ran `portability` instead -- which is also
why that branch is now named rather than a default."""

SUITES: Final[tuple[str, ...]] = (*BUILT, "extract", *UNMEASURABLE)
"""Every suite `ow eval run` accepts, in 13:1881's order: the five it measures, `extract` which it
reports not applicable (D987), and `perf` which it reports unknown."""

ADDRESS: Final = "address_survival"
"""Ruling 16: R2's hard row in the metric register (D902)."""

ROUNDTRIP_CONFOUNDER: Final = (
    "R2 is the hard address_survival row at 1.000 (D902), so a single element that does not "
    "survive the round trip refuses a release"
)
"""Ruling 16, said in every roundtrip run."""

CELL_CONFOUNDER: Final = (
    "one cell, this machine's, held to frozen values blessed on win32 (D886); the other cells "
    "are CI's matrix, each running this suite against the same values"
)
"""Ruling 19, said in every portability run."""

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
    "false_confident_zero, absent_precision, absent_recall: the removal half, which "
    "--deterministic-half leaves out (D933)",
)
"""Ruling 11: the half not run, named in a `--deterministic-half` run's `not_measured`."""

FALSE_CONFIDENT: Final = "false_confident_zero"
ABSENT_RECALL: Final = "absent_recall"
ABSENT_PRECISION: Final = "absent_precision"
"""Ruling 26: the removal half's three metrics. The first is the register's ceiling row."""

REMOVAL_CORPUS: Final = "absence_corpus/quick"
REMOVAL_SLICE: Final = "removal"
"""Ruling 25: the removal half's corpus id, never the damage half's, and its slice."""

REMOVAL_UNMEASURED: Final = (
    "qa_accuracy: the absence corpus's judge-graded metric, and no judge runs here (13 section 8.6)"
)
"""Ruling 28: named in every removal run's `not_measured`."""

TRUTH_KINDS: Final[frozenset[str]] = frozenset(
    {"human", "rendered", "native_run", "synth_ocr", "agreement", "self"}
)
"""`eval_metric.truth_kind`'s CHECK, the six `TruthKind`s 13:1452 tabulates."""

MEASURED: Final[Mapping[str, tuple[Callable[..., MetricResult], str]]] = {
    "span_exact_rate": (span_exact_rate, "native_run"),
}
"""Each parse metric this build computes, with its `TruthKind` (rulings 2 and 4)."""

PARSE_UNMEASURED: Final[tuple[str, ...]] = (
    "structure_f1: no fixture carries the structure.jsonl reference it scores against (13:1104)",
)
"""Rulings 2 and 24: what a subject with no structure reference at all says it did not measure.
Since D982 a subject that carries one reports per document instead, and one whose card declares no
structure reports `structure.inapplicable()`'s reason. The rates a fixture's assertions feed are
ruling 22's."""
UNLABELLED: Final = "{metrics}: no fixture in {corpus} carries an assertions file to score them"
"""Ruling 22: what a parse run over a fixture set with no labels says it did not measure."""

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


def parse(  # noqa: PLR0915 -- one subject's run, its metrics and its labels, rulings 1-7 and 22
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
    #  D983: `MEASURED` is the metrics this function measures from the parses themselves. The
    #  labelled half computes three more -- `RATES`' verdict rollups and `structure.METRIC` -- and
    #  since their register rows landed, reading `MEASURED` alone made a run claim it does not
    #  compute `order_acc` in the same breath as reporting how many of its assertions ran.
    computes = {*MEASURED, *RATES, structure.METRIC}
    unmeasured = [
        f"{row.get('metric')}: this build does not compute it"
        for row in gates
        if row.get("metric") not in computes
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
    assertions: list[Assertion] = []
    verdicts: list[Verdict] = []
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
            corpus, labelled, pages, stores, refs = _labelled(
                root, fixtures_dir, found, parses, workdir
            )
            run_id = _run_id("parse", found.driver_id, corpus.corpus_digest, started)
            #  D932: an owdoc-only assertion reads the parsed document, so it is judged here,
            #  while the candidate stores still exist, and not after the workdir is gone. D982's
            #  structure reference reads the same documents, for the same reason.
            wanted = {one.doc for one in labelled if one.type in OWDOC_ONLY} | set(refs)
            with labels.opened({doc: stores[doc] for doc in wanted if doc in stores}) as docs:
                judged = judge(labelled, pages, run_id=run_id, docs=docs)
                structures = _structure(found, refs, docs)
        corpora[corpus.corpus_id, corpus.version] = corpus
        slice_key = str(row.get("slice", "*"))
        vacuous = [
            f"{result.metric}: vacuous, no block claims verbatimness, so nothing could fail "
            f"(13:661, R-T16); {result.blocks_seen} block(s) seen"
            for _gate, result in results
            if result.value is None
        ]
        run = Run(
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
            not_measured=(*vacuous, *unmeasured, *_structure_notes(found, structures)),
            confounders=(
                "the fixtures are the driver's own, written by its authors",
                f"{len(refused)} fixture(s) refused by the driver"
                + (f": {', '.join(refused)}" if refused else ""),
            ),
        )
        rates, judged_verdicts, run = _rates(run, labelled, judged)
        runs.append(run)
        metrics.extend(rates)
        if structures and not structure.inapplicable(found.card):
            metrics.extend(structure.metrics(run, structures))
        assertions.extend(labelled)
        verdicts.extend(judged_verdicts)
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
    batch = Batch(
        corpora=tuple(corpora.values()),
        assertions=tuple(assertions),
        runs=tuple(runs),
        verdicts=tuple(verdicts),
        metrics=tuple(metrics),
    )
    return batch, tuple(done)


def _labelled(
    root: Path, fixtures_dir: Path, found: Subject, parses: Sequence[Any], workdir: Path
) -> tuple[
    Corpus,
    tuple[Assertion, ...],
    dict[tuple[str, int], str],
    dict[str, Path],
    dict[str, tuple[structure.Triple, ...]],
]:
    """Rulings 22, 23 and 29: the corpus with its labels and structure references digested, its
    assertions, the pages each labelled fixture's parse serves, the candidate store each was
    written to (D932), and each fixture's structure reference (D982)."""
    base = fixtures_dir.resolve()
    files = [fixture.path for fixture in found.fixtures]
    labels_files = [labels.labels_of(path) for path in files if labels.labels_of(path).is_file()]
    reference_files = [
        structure.reference_of(path) for path in files if structure.reference_of(path).is_file()
    ]
    corpus = _corpus(
        root, fixtures_dir, [*files, *labels_files, *reference_files], n_docs=len(files)
    )
    loaded = tuple(
        one
        for path in files
        for one in labels.load(
            path, fixtures_dir=base, corpus_id=corpus.corpus_id, corpus_version=corpus.version
        )
    )
    #  `slices=` is not optional here, though the signature allows it. A `.structure.jsonl` row
    #  declares no slices of its own, so it inherits the fixture sidecar's exactly as an assertion
    #  does (`labels` ruling 4) -- and without this argument every row inherits nothing, `score()`
    #  falls back to `*`, and `fnmatchcase("*", "office/*")` is FALSE, so `structure_f1`'s blocking
    #  0.90 floor matches no row at all. That is the "law over an empty set" eval/gates.toml's own
    #  header describes, and it was live until this line was fixed.
    refs = {
        path.relative_to(base).as_posix(): structure.load(path, slices=labels.sidecar_slices(path))
        for path in files
        if structure.reference_of(path).is_file()
    }
    wanted = {one.doc for one in loaded} | set(refs)
    pages: dict[tuple[str, int], str] = {}
    stores: dict[str, Path] = {}
    for index, parse in enumerate(parses):
        doc = parse.fixture.path.relative_to(base).as_posix()
        if doc in wanted:
            where = workdir / f"candidate-{index}"
            pages |= labels.candidate(parse, found.card, doc=doc, workdir=where)
            stores[doc] = where / labels.STORE
    checked = sum(1 for one in loaded if one.checked == "verified")
    return (
        replace(corpus, n_assertions=len(loaded), n_checked=checked),
        loaded,
        pages,
        stores,
        refs,
    )


def _structure(
    found: Subject, refs: Mapping[str, tuple[structure.Triple, ...]], docs: Mapping[str, Doc]
) -> tuple[structure.Scored, ...]:
    """Ruling 29: each referenced document's `structure_f1`, or why it does not score (D982).

    A subject whose card declares no structure is scored nowhere: `structure.inapplicable()` has
    the reason and `_structure_notes()` prints it, so the rows are absent rather than zero.
    """
    if structure.inapplicable(found.card):
        return ()
    return tuple(
        structure.score(doc, docs[doc], reference)
        for doc, reference in sorted(refs.items())
        if doc in docs
    )


def _structure_notes(found: Subject, scored: Sequence[structure.Scored]) -> tuple[str, ...]:
    """Ruling 29: what this run did not measure about `structure_f1` (D982)."""
    why = structure.inapplicable(found.card)
    if why:
        return (f"{structure.METRIC}: not applicable -- {why}",)
    if not scored:
        return PARSE_UNMEASURED
    unscored = [one for one in scored if not one.scored]
    if not unscored:
        return ()
    #  One line, whatever the corpus size: naming ten documents and their row counts made a
    #  release-check line nobody reads. The aggregate says what to do; `ow eval explain` and the
    #  reference files say which rows.
    unsigned = [one for one in unscored if "unsigned" in one.why]
    said = [
        f"{len(unscored)} of {len(scored)} referenced document(s) not scored",
        *(
            [f"{sum(one.reference for one in unsigned)} reference row(s) unsigned (ruling 3)"]
            if unsigned
            else []
        ),
        *(f"{one.doc}: {one.why}" for one in unscored if one not in unsigned),
    ]
    return (f"{structure.METRIC}: " + "; ".join(said),)


def _rates(
    run: Run, labelled: Sequence[Assertion], judged: Judged
) -> tuple[list[Metric], tuple[Verdict, ...], Run]:
    """Rulings 22 and 23: the verdicts, each fed rate's rows, and the run saying what they did not
    score."""
    if not labelled:
        corpus = run.corpus_id
        said = UNLABELLED.format(metrics=", ".join(sorted(RATES)), corpus=corpus)
        return [], (), replace(run, not_measured=(*run.not_measured, said))
    rows: list[Metric] = []
    notes = [f"assertion {aid} not run: {why}" for aid, why in judged.not_run]
    for spec in RATES.values():
        if not any(one.type in spec.types for one in labelled):
            continue
        rolled = rollup(run, spec, judged.verdicts, labelled, evaluator="text")
        rows.extend(rolled.metrics)
        if rolled.unscored:
            notes.append(
                f"{spec.metric}: {rolled.unscored} unverified assertion(s) ran and were not "
                f"scored (13:1022)"
            )
    return rows, judged.verdicts, replace(run, not_measured=(*run.not_measured, *notes))


def absence(
    register: Mapping[str, Any],
    *,
    root: Path,
    witness: str,
    cassette: str,
    now_ns: Callable[[], int],
    admit: Callable[[Sequence[str]], str | None],
    workers: int = 4,
    deterministic_half: bool = False,
) -> tuple[Batch, tuple[Measured, ...]]:
    """The absence suite as one `Batch`: the paired-damage half (rulings 8-11), then, unless
    `deterministic_half`, the removal half (rulings 25-28)."""
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
            *(ABSENCE_UNMEASURED if deterministic_half else ()),
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
    damaged = Batch(corpora=(corpus,), runs=(run,), metrics=metrics)
    if deterministic_half:
        return damaged, (done,)
    removed, measured = _removal(
        register, root=root, witness=witness, cassette=cassette, now_ns=now_ns
    )
    return (
        Batch(
            corpora=(*damaged.corpora, *removed.corpora),
            runs=(*damaged.runs, *removed.runs),
            metrics=(*damaged.metrics, *removed.metrics),
        ),
        (done, measured),
    )


def _removal(
    register: Mapping[str, Any],
    *,
    root: Path,
    witness: str,
    cassette: str,
    now_ns: Callable[[], int],
) -> tuple[Batch, Measured]:
    """The absence suite's removal half as one run (rulings 25-28)."""
    truth = _row_truth(register, "absence", FALSE_CONFIDENT)
    started = now_ns()
    try:
        with tempfile.TemporaryDirectory(prefix="ow-eval-removal-") as work:
            removal = removal_half.run_suite(root, work=Path(work), now_ns=now_ns)
    except (RuntimeError, OSError) as error:
        raise QualityError(
            f"the absence suite's removal half could not run: {type(error).__name__}: {error}",
            fix="python fixtures/gen/gen_reference_corpora.py --all  # every corpus generates?",
        ) from error
    ended = now_ns()
    digest = damage_half.documents_digest(removal.documents)
    corpus = Corpus(
        corpus_id=REMOVAL_CORPUS,
        version=digest[:16],
        corpus_digest=digest,
        tier="A",
        n_docs=len(removal.documents),
        n_assertions=0,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )
    run_id = _run_id("absence", "omniweave", digest, started)
    answerable = removal.answerable
    wrong = tuple(one.question.task_id for one in answerable if one.answered_absent)
    absent = removal.genuinely_absent
    called = removal.called_absent
    counted = (
        (FALSE_CONFIDENT, len(wrong), len(answerable), "answerable question(s) answered absent"),
        (
            ABSENT_RECALL,
            sum(1 for one in absent if one.answered_absent),
            len(absent),
            "genuinely absent question(s) answered absent",
        ),
        (
            ABSENT_PRECISION,
            sum(1 for one in called if one.question.genuinely_absent),
            len(called),
            "question(s) answered absent genuinely absent",
        ),
    )
    notes: list[str] = []
    metrics: list[Metric] = []
    headline: float | None = None
    for metric, hits, n, said in counted:
        if n < MIN_SLICE_N:
            notes.append(
                f"{metric}: {hits} of {n} {said}, under min_slice_n = {MIN_SLICE_N} (13:1088)"
                if n
                else f"{metric}: no question was in its denominator, so it has no rate"
            )
            if metric == FALSE_CONFIDENT:
                metrics.append(
                    Metric(
                        run_id=run_id,
                        metric=metric,
                        value=None,
                        n=n,
                        ci_lo=None,
                        ci_hi=None,
                        method="none",
                        truth_kind=truth,
                        state="unknown",
                        slice_key=REMOVAL_SLICE,
                    )
                )
            continue
        estimate = rate(hits, n)
        if metric == FALSE_CONFIDENT:
            headline = estimate.value
        metrics.append(
            Metric(
                run_id=run_id,
                metric=metric,
                value=estimate.value,
                n=estimate.n,
                ci_lo=estimate.ci_lo,
                ci_hi=estimate.ci_hi,
                method=estimate.method,
                truth_kind=truth,
                state="ok",
                slice_key=REMOVAL_SLICE,
            )
        )
    kept = [f"{task}: {removal_half.SHARED[task]}" for task in removal.shared]
    run = Run(
        run_id=run_id,
        suite="absence",
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
        not_measured=(*notes, REMOVAL_UNMEASURED),
        confounders=(
            "the documents are the repository's own generated reference corpora, quick scale "
            "and Tier A, where 13 section 8.6 removes a section of a Tier-B document",
            "the answer key is the adoption catalogue's, written against the generator's "
            "PLANTED table, and no reviewer has verified it",
            *(f"kept answerable: {line}" for line in kept),
            f"{len(wrong)} answerable question(s) answered absent"
            + (f": {', '.join(wrong)}" if wrong else ""),
        ),
    )
    done = Measured(
        run_id=run_id,
        suite="absence",
        subject="omniweave",
        slice_key=REMOVAL_SLICE,
        corpus_id=corpus.corpus_id,
        metric=FALSE_CONFIDENT,
        value=headline,
        n=len(answerable),
        parsed=len(answerable) - len(wrong),
        refused=wrong,
    )
    return Batch(corpora=(corpus,), runs=(run,), metrics=tuple(metrics)), done


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
            #  D922: a count over every answer asked has no sampling error, so its interval is
            #  the count itself. Null bounds with an `exact` method fail Q-G19's row clause,
            #  which keeps null for a row whose method is `none` (`scoreboard` ruling 5).
            ci_lo=float(checked.violations),
            ci_hi=float(checked.violations),
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
    truth = _row_truth(register, "roundtrip", ADDRESS)
    metrics: list[Metric] = []
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
        #  D1014: `_golden_corpus` and not a row built here. `eval_corpus` is keyed by
        #  (corpus_id, version), so a corpus RELEASE has one row, and this suite and the
        #  portability suite both describe `fixtures/out/golden/<target>` at the same digest.
        #  This site used to write `n_assertions=len(judged.elements)` -- the elements THIS RUN
        #  judged, 7 for docx and 26 for pptx -- against portability's 0, and the second suite to
        #  write into one `.oweval` was refused: "already recorded with other content; a corpus
        #  version is immutable". Ruling 23 settles which is right: `n_assertions` counts the
        #  corpus's own assertion files, a golden output tree has none, so 0 is the count and the
        #  judged total belongs where it already is, on the metric row's `n`.
        corpus = _golden_corpus(root, target.golden, digest)
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
        #  An R2 the suite could not judge carries no elements (`roundtrip.judge`), so writes none.
        if judged.elements:
            estimate = rate(survived, len(judged.elements))
            metrics.append(
                Metric(
                    run_id=run_id,
                    metric=ADDRESS,
                    value=estimate.value,
                    n=estimate.n,
                    ci_lo=estimate.ci_lo,
                    ci_hi=estimate.ci_hi,
                    method=estimate.method,
                    truth_kind=truth,
                    state="ok",
                    slice_key=target.target,
                )
            )
        done.append(
            Measured(
                run_id=run_id,
                suite="roundtrip",
                subject=judged.driver,
                slice_key=target.target,
                corpus_id=corpus.corpus_id,
                metric=ADDRESS,
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
        metrics=tuple(metrics),
    )
    return batch, tuple(done)


def _row_truth(register: Mapping[str, Any], suite: str, metric: str) -> str:
    """Rulings 16, 19 and 26: a row's TruthKind, or a refusal naming the missing row."""
    gate = next(
        (
            row
            for row in register.get("gate", [])
            if row.get("suite") == suite and row.get("metric") == metric
        ),
        None,
    )
    if gate is None:
        raise QualityError(
            f"the metric register has no {suite} {metric} row to measure against",
            fix=f"add a [[gate]] row with metric = {metric!r} and suite = {suite!r}",
        )
    return _truth(gate, metric)


def portability(
    register: Mapping[str, Any],
    *,
    root: Path,
    witness: str,
    cassette: str,
    now_ns: Callable[[], int],
) -> tuple[Batch, tuple[Measured, ...]]:
    """Rulings 19-21: the shape half's run, then one run per register `[[target]]`'s parts."""
    truth = _row_truth(register, "portability", cell_half.METRIC)
    rows = r2_half.targets(register, root)
    frozen_parts = cell_half.read_parts(root)
    unwritten = [target.target for target in rows if target.target not in frozen_parts]
    if unwritten:
        raise QualityError(
            f"{cell_half.PARTS} has no row for {', '.join(unwritten)}",
            fix="uv run tools/ow_portability.py --write  # on the cell that blessed the goldens",
        )
    batch, shape = _shape_half(root, truth=truth, witness=witness, cassette=cassette, now_ns=now_ns)
    runs, metrics, corpora, done = (
        list(batch.runs),
        list(batch.metrics),
        list(batch.corpora),
        [shape],
    )
    for target in rows:
        started = now_ns()
        try:
            driver, version, fingerprint, members = cell_half.parts(target)
        except (QualityError, RuntimeError, OSError, TypeError) as error:
            raise QualityError(
                f"the portability suite could not compile {target.target}: "
                f"{type(error).__name__}: {error}",
                fix=f"ow conform --target {target.target}  # the target suite, every law",
            ) from error
        held = cell_half.differences(frozen_parts[target.target], members)
        digest = r2_half.golden_digest(target.golden)
        corpus = _golden_corpus(root, target.golden, digest)
        corpora.append(corpus)
        run_id = _run_id("portability", driver, digest, started)
        runs.append(
            _cell_run(
                run_id,
                corpus,
                subject=driver,
                subject_version=version,
                fingerprint=fingerprint,
                timing="in_process",
                started=started,
                ended=now_ns(),
                held=held,
                witness=witness,
                cassette=cassette,
            )
        )
        metrics.append(_cell_metric(run_id, held, truth=truth, slice_key=target.target))
        done.append(_cell_measured(run_id, driver, target.target, corpus, held))
    return Batch(corpora=tuple(corpora), runs=tuple(runs), metrics=tuple(metrics)), tuple(done)


def _shape_half(
    root: Path, *, truth: str, witness: str, cassette: str, now_ns: Callable[[], int]
) -> tuple[Batch, Measured]:
    """Ruling 20: the Tier-A fixtures ingested, each `.shape` held to the committed goldens."""
    started = now_ns()
    try:
        frozen, found = cell_half.shapes(root)
    except OSError as error:
        raise QualityError(
            f"the portability suite could not ingest the Tier-A fixtures: {error}",
            fix="uv run tools/ow_golden.py  # the same ingest, its refusal printed",
        ) from error
    ended = now_ns()
    held = cell_half.differences(frozen, found)
    index = tomllib.loads((root / "fixtures" / "index.toml").read_text(encoding="utf-8"))
    files = [root / str(row["path"]) for row in index.get("fixture", [])]
    digest = corpus_digest(root, files)
    corpus = Corpus(
        corpus_id="fixtures/index.toml",
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
    run_id = _run_id("portability", "omniweave", corpus.corpus_digest, started)
    run = _cell_run(
        run_id,
        corpus,
        subject="omniweave",
        subject_version=_version("omniweave"),
        fingerprint=code_fingerprint(_core_sources()),
        timing="spawn_inclusive",
        started=started,
        ended=ended,
        held=held,
        witness=witness,
        cassette=cassette,
    )
    metrics = (
        (_cell_metric(run_id, held, truth=truth, slice_key=cell_half.SHAPE),) if frozen else ()
    )
    batch = Batch(corpora=(corpus,), runs=(run,), metrics=metrics)
    return batch, _cell_measured(run_id, "omniweave", cell_half.SHAPE, corpus, held)


def _cell_run(
    run_id: str,
    corpus: Corpus,
    *,
    subject: str,
    subject_version: str,
    fingerprint: str,
    timing: str,
    started: int,
    ended: int,
    held: cell_half.Held,
    witness: str,
    cassette: str,
) -> Run:
    """Rulings 19-21: one half's run; no frozen value at all is `unknown`."""
    nothing = held.compared == 0
    return Run(
        run_id=run_id,
        suite="portability",
        corpus_id=corpus.corpus_id,
        corpus_version=corpus.version,
        corpus_digest=corpus.corpus_digest,
        subject=subject,
        subject_version=subject_version,
        producer_id=None,
        measured_on=_measured_on(corpus),
        timing_basis=timing,
        witness=witness,
        cassette=cassette,
        policy_digest=None,
        pricebook_digest=None,
        harness_version=kit_version(),
        code_fingerprint=fingerprint,
        hardware=_hardware(),
        started_ns=started,
        ended_ns=ended,
        status="unknown" if nothing else "ok",
        not_measured=(
            *(
                ("nothing frozen to compare: no committed value and nothing produced",)
                if nothing
                else ()
            ),
            "pages and outline Reductions, and byte digests: tracked or pinned-only, so not "
            "promised across cells (D886, 13:1568)",
        ),
        confounders=(
            CELL_CONFOUNDER,
            f"{len(held.differences)} of {held.compared} differ"
            + (f": {', '.join(held.differences)}" if held.differences else ""),
        ),
    )


def _cell_metric(run_id: str, held: cell_half.Held, *, truth: str, slice_key: str) -> Metric:
    """Ruling 19: the identical share, as `stats.rate()`."""
    estimate = rate(held.matched, held.compared)
    return Metric(
        run_id=run_id,
        metric=cell_half.METRIC,
        value=estimate.value,
        n=estimate.n,
        ci_lo=estimate.ci_lo,
        ci_hi=estimate.ci_hi,
        method=estimate.method,
        truth_kind=truth,
        state="ok",
        slice_key=slice_key,
    )


def _cell_measured(
    run_id: str, subject: str, slice_key: str, corpus: Corpus, held: cell_half.Held
) -> Measured:
    return Measured(
        run_id=run_id,
        suite="portability",
        subject=subject,
        slice_key=slice_key,
        corpus_id=corpus.corpus_id,
        metric=cell_half.METRIC,
        value=held.matched / held.compared if held.compared else None,
        n=held.compared,
        parsed=held.matched,
        refused=held.differences,
    )


def _golden_corpus(root: Path, golden: Path, digest: str) -> Corpus:
    """Ruling 20: a target's golden as a Tier A corpus, versioned by its digest, as ruling 15's."""
    return Corpus(
        corpus_id=golden.relative_to(root).as_posix(),
        version=digest[:16],
        corpus_digest=digest,
        tier="A",
        n_docs=sum(1 for path in (golden / "il").iterdir() if path.is_file()),
        n_assertions=0,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )


def unknown(
    suite: str, *, witness: str, cassette: str, now_ns: Callable[[], int]
) -> tuple[Batch, tuple[Measured, ...]]:
    """Ruling 17: one `unknown` run naming why `suite` cannot be measured here.

    D987: a suite in `NOT_APPLICABLE_SUITES` writes the same row with its own reason. The
    stored `status` stays `unknown` -- the `.oweval` CHECK admits `ok`, `partial` and `unknown`,
    and a fourth value is a migration plus a `harness_version` bump for a distinction the report
    carries perfectly well -- and `release.check_release` classifies the row by its suite, which
    is where the policy lives anyway.
    """
    reason = UNRUNNABLE.get(suite)
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
            *(
                ("not applicable by a user ruling of 2026-10-26, disclosed and not refused",)
                if suite in NOT_APPLICABLE_SUITES
                else ()
            ),
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


def _corpus(
    root: Path, fixtures_dir: Path, files: Sequence[Path], *, n_docs: int | None = None
) -> Corpus:
    """Rulings 3 and 23: a fixture set as a Tier A corpus, versioned by its digest."""
    digest = corpus_digest(fixtures_dir, files)
    return Corpus(
        corpus_id=fixtures_dir.relative_to(root).as_posix(),
        version=digest[:16],
        corpus_digest=digest,
        tier="A",
        n_docs=len(files) if n_docs is None else n_docs,
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
