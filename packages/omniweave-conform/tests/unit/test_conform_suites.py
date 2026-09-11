"""The twelve suites, and the negative control for each one that can have one.

**A conformance suite that cannot fail is worse than no suite**, because it produces a badge. So
the shape of this file is: one test that the template passes, and then one test per suite that
breaks the template in the specific way that suite exists to catch and asserts it goes red -- with
the assertion's own `locus` checked, so a suite that fails for an unrelated reason does not read as
a caught defect.

That discipline is the ledger's C39/C53 rule and it is also the plan's: 04-driver-system.md:2334
requires a failing `capability` to name "the fixture, the block and the two strings that differed",
which is only checkable by making one differ.

## How a driver is broken, without touching the shipped one

`_variant()` copies the template's card and driver into a `tmp_path`, applies one textual edit,
and points a `Subject` at the copy. The shipped template is never mutated, the copy is a real
importable package under a unique module name, and the edit is one line -- so when a test goes red
the diff between the passing subject and the failing one is a single string.

Specified in 04-driver-system.md section 8.2; 13-quality.md section 12.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave_conform import Subject, Verdict, run
from omniweave_conform.harness import run_parse
from omniweave_conform.result import MANDATORY, SUITES
from omniweave_conform.suites import (
    SUITE_RUNNERS,
    determinism,
    fuzz,
    idempotence,
    purity,
    run_suite,
)

if TYPE_CHECKING:
    from omniweave_conform.result import SuiteResult

TEMPLATE = Path(__file__).resolve().parents[2] / "src/omniweave_conform/template"
CARD = TEMPLATE / "driver.toml"
FIXTURES = TEMPLATE / "fixtures"

# `tools/ow_conform.py` measures three things in child processes. They are supplied here as the
# values a passing run would have produced, because this file's subject is the SUITES rather
# than the tool -- the tool's own measurements are `test_ow_conform.py`'s. A test that left them
# out would be testing the "nothing was supplied" branch twelve times over.


def _subject(tmp_path: Path, **kwargs: object) -> Subject:
    return Subject.of(  # type: ignore[arg-type]
        CARD, fixtures_dir=FIXTURES, workdir=tmp_path, **kwargs
    )


def _variant(
    tmp_path: Path,
    name: str,
    *,
    card: tuple[str, str] = ("", ""),
    driver: tuple[str, str] = ("", ""),
) -> Subject:
    """A copy of the template with one edit, importable under its own module name.

    The module name is derived from `name` so two variants in one test session cannot collide in
    `sys.modules` -- which would make the second variant silently test the first one's code, and
    is exactly the kind of failure `idempotence` exists to catch one level down.
    """
    package = f"owconform_variant_{name}"
    root = tmp_path / package
    shutil.copytree(TEMPLATE, root)
    (root / "__init__.py").write_text('"""A conformance-suite negative control."""\n', "utf-8")

    driver_py = root / "driver.py"
    if driver[0]:
        text = driver_py.read_text(encoding="utf-8")
        assert driver[0] in text, f"the driver edit anchor is gone: {driver[0]!r}"
        driver_py.write_text(text.replace(driver[0], driver[1]), encoding="utf-8")

    card_path = root / "driver.toml"
    text = card_path.read_text(encoding="utf-8")
    text = text.replace(
        "omniweave_conform.template.driver:PlainTextParser",
        f"{package}.driver:PlainTextParser",
    )
    if card[0]:
        assert card[0] in text, f"the card edit anchor is gone: {card[0]!r}"
        text = text.replace(card[0], card[1])
    card_path.write_text(text, encoding="utf-8")

    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    return Subject.of(card_path, fixtures_dir=FIXTURES, workdir=tmp_path / "work")


def _failed(result: SuiteResult, locus_prefix: str) -> bool:
    return result.verdict is Verdict.FAIL and any(
        a.locus.startswith(locus_prefix) for a in result.failures()
    )


# ---------------------------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------------------------


def test_there_is_an_implementation_for_exactly_the_twelve_suites_the_card_names() -> None:
    """A thirteenth suite in the card grammar with no runner here is a red test, not a gap.

    Both sides are transcriptions of 04-driver-system.md:2068's table, so this pins agreement
    between two transcriptions rather than proving anything about the plan. It is worth having for
    the first reason: `[quality.suites]` is a closed table, and a suite the kit runs but the card
    cannot record would fail at the moment of writing the results and not before.
    """
    assert tuple(SUITE_RUNNERS) == SUITES


def test_exactly_one_suite_is_not_mandatory_and_it_is_quality() -> None:
    """04-driver-system.md:2083 is the only `mandatory = no` cell; `MANDATORY` derives it."""
    assert set(SUITES) - MANDATORY == {"quality"}
    assert len(MANDATORY) == len(SUITES) - 1


def test_asking_for_a_suite_outside_the_twelve_raises_rather_than_returning_a_verdict(
    tmp_path: Path,
) -> None:
    """A verdict for a suite that never ran would put a row in a report for nothing."""
    with pytest.raises(KeyError):
        run_suite("bogus", _subject(tmp_path))


# ---------------------------------------------------------------------------------------------
# The positive control: the shipped template passes the tier it is shipped to demonstrate
# ---------------------------------------------------------------------------------------------


def test_the_template_driver_passes_every_mandatory_suite(tmp_path: Path) -> None:
    """16-roadmap.md:486 ships this driver so that the kit has a subject that passes.

    The three cross-process measurements are supplied as `tools/ow_conform.py` would supply them;
    what is under test here is the eleven suites, not the tool that spawns for three of them.
    """
    subject = _subject(tmp_path)
    digests = _digests(subject)
    report = run(
        Subject.of(
            CARD,
            fixtures_dir=FIXTURES,
            workdir=tmp_path / "run",
            measurements={
                idempotence.CROSS_PROCESS_KEY: digests,
                determinism.CROSS_PROCESS_KEY: digests,
                fuzz.SEGFAULT_KEY: True,
                purity.CLEAN_PROCESS_KEY: {"verdict": "pass", "summary": "clean interpreter"},
            },
        )
    )
    failures = {r.suite: [a.line() for a in r.failures()] for r in report if r.failures()}
    assert failures == {}, failures
    assert report.passed
    assert report.mandatory_passed == report.mandatory_total == 11
    assert report.verdict_of("quality") is Verdict.UNKNOWN


def _digests(subject: Subject) -> dict[str, str]:
    """What a second process would have produced: this process's own digests.

    Legitimate here and nowhere else. `test_ow_conform.py` runs the real child; this file's
    subject is the comparison the suite performs, and supplying digests that agree is how the
    positive control reaches the branch where the comparison actually happens.
    """
    driver = subject.instantiate()
    out: dict[str, str] = {}
    for index, fixture in enumerate(subject.fixtures):
        try:
            result = run_parse(driver, fixture, subject.workdir / f"d{index}")
        except Exception as exc:
            # A refused fixture yields no digest, exactly as it does in the real child.
            del exc
            continue
        out[fixture.name] = hashlib.sha256(result.body).hexdigest()
    return out


# ---------------------------------------------------------------------------------------------
# The negative controls. One per suite, each breaking the thing that suite exists to catch.
# ---------------------------------------------------------------------------------------------


def test_card_fails_when_the_declared_attestation_does_not_recompute(tmp_path: Path) -> None:
    """Tamper-evidence: the loader carries `attested = False` and does not refuse. This reads it."""
    subject = _variant(
        tmp_path,
        "attest",
        card=("card_schema = 1", 'card_schema = 1\nattestation = "sha256:' + "0" * 64 + '"'),
    )
    result = run_suite("card", subject)
    assert _failed(result, "attestation"), [a.line() for a in result.assertions]


def test_card_fails_when_a_capability_key_is_ignored_as_unknown(tmp_path: Path) -> None:
    """An unknown `[capability.parse]` key LOADS, with a degradation nobody would otherwise read."""
    subject = _variant(
        tmp_path, "degraded", card=('spatial = "none"', 'spatial = "none"\nspacial = "line_bbox"')
    )
    assert subject.card.degradations, "the loader should have recorded a degradation"
    result = run_suite("card", subject)
    assert _failed(result, "cap:degradations"), [a.line() for a in result.assertions]


def test_contract_fails_when_a_protocol_method_is_missing(tmp_path: Path) -> None:
    """`omniweave_ports/base.py:29-31` gives this suite the structural check `isinstance` cannot."""
    subject = _variant(
        tmp_path,
        "nosniff",
        driver=(
            "    def sniff(self, head: bytes, hint: StreamHint)",
            "    def sniff_(self, head: bytes, hint: StreamHint)",
        ),
    )
    result = run_suite("contract", subject)
    assert _failed(result, "signature:sniff"), [a.line() for a in result.assertions]


def test_contract_fails_when_a_parameter_is_renamed(tmp_path: Path) -> None:
    """Names, not arity: a host may call by keyword and a renamed parameter is a latent break."""
    subject = _variant(
        tmp_path,
        "renamed",
        driver=(
            "    def parse(self, unit: UnitRef, parts: PartSelector, io: DriverIO)",
            "    def parse(self, u: UnitRef, parts: PartSelector, io: DriverIO)",
        ),
    )
    result = run_suite("contract", subject)
    failures = [a for a in result.failures() if a.locus == "signature:parse"]
    assert failures, [a.line() for a in result.assertions]
    assert "unit" in failures[0].expected and "u" in failures[0].actual


def test_contract_fails_when_init_opens_a_file(tmp_path: Path) -> None:
    """`ports/base.py:52-55`: constructing a driver MUST load no model and open no file."""
    subject = _variant(
        tmp_path,
        "opener",
        driver=(
            '        self.errors = str(config.get("errors", "strict"))',
            '        self.errors = str(config.get("errors", "strict"))\n'
            "        import pathlib\n"
            "        pathlib.Path(__file__).read_bytes()",
        ),
    )
    result = run_suite("contract", subject)
    assert _failed(result, "__init__:open"), [a.line() for a in result.assertions]


def test_contract_fails_when_the_driver_ignores_cancellation(tmp_path: Path) -> None:
    """04-driver-system.md:1738 makes `io.cancelled()` a check at every loop top."""
    subject = _variant(
        tmp_path,
        "uncancellable",
        driver=("            if io.cancelled():", "            if False:"),
    )
    result = run_suite("contract", subject)
    assert _failed(result, "cancel"), [a.line() for a in result.assertions]


def test_capability_fails_when_origin_span_exact_does_not_reverify(tmp_path: Path) -> None:
    """**The P3 demo, as a test.** 16-roadmap.md's demo changes a card to claim `exact` and
    watches this suite fail "on the first fixture by re-reading the retained part".

    Here the card keeps its claim and the CODE breaks it -- one byte of drift in the recorded
    span -- which is the same disagreement from the other side and is the shape a real driver's
    regression takes. 04:2334 requires the message to name the fixture, the block and the two
    strings; all three are asserted.
    """
    subject = _variant(tmp_path, "offby1", driver=('"start": byte_a,', '"start": byte_a + 1,'))
    result = run_suite("capability", subject)
    failures = [a for a in result.failures() if a.locus.startswith("P7:")]
    assert failures, [a.line() for a in result.assertions]
    first = failures[0]
    assert first.fixture, "the message must name the fixture"
    assert first.locus.startswith("P7:b"), "the message must name the block"
    assert first.expected and first.actual and first.expected != first.actual


def test_capability_fails_when_the_code_achieves_more_than_the_card_declares(
    tmp_path: Path,
) -> None:
    """P15: `achieved <= declared`, and the inverted direction is the aspirational card."""
    subject = _variant(
        tmp_path, "overclaim", driver=('"tables": "none",', '"tables": "cells_with_spans",')
    )
    result = run_suite("capability", subject)
    assert _failed(result, "P15:tables"), [a.line() for a in result.assertions]


def test_capability_fails_when_marks_false_is_contradicted_by_a_mark(tmp_path: Path) -> None:
    """P14 is written over ABSENCE: `marks = false` asserts marks are absent."""
    subject = _variant(
        tmp_path,
        "marked",
        driver=(
            '                    "marks": [],',
            '                    "marks": [{"kind": "emph", "a": 0, "b": 1}],',
        ),
    )
    result = run_suite("capability", subject)
    assert _failed(result, "P14:marks"), [a.line() for a in result.assertions]


def test_capability_fails_when_a_declared_format_token_never_appears_in_sniff(
    tmp_path: Path,
) -> None:
    """04-driver-system.md:512 makes this a conformance failure in as many words."""
    subject = _variant(
        tmp_path,
        "tokenless",
        card=(
            '{ media_type = "text/plain", token = "txt" }',
            '{ media_type = "text/plain", token = "plain" }',
        ),
    )
    result = run_suite("capability", subject)
    assert _failed(result, "format_tokens:plain"), [a.line() for a in result.assertions]


def test_idempotence_fails_on_per_instance_state(tmp_path: Path) -> None:
    """The defect the row names: hidden per-instance state, caught by calling twice."""
    subject = _variant(
        tmp_path,
        "stateful",
        driver=(
            '        self.errors = str(config.get("errors", "strict"))',
            '        self.errors = str(config.get("errors", "strict"))\n        self._calls = 0',
        ),
    )
    # A counter that leaks into the output on the second call and not the first.
    driver_py = next(tmp_path.glob("owconform_variant_stateful/driver.py"))
    text = driver_py.read_text(encoding="utf-8")
    text = text.replace(
        "        out: list[dict[str, object]] = [",
        "        self._calls += 1\n        out: list[dict[str, object]] = [",
    )
    text = text.replace('"format": "txt",', '"format": "txt" if self._calls == 1 else "txt2",')
    driver_py.write_text(text, encoding="utf-8")
    result = run_suite("idempotence", subject)
    assert _failed(result, "same:"), [a.line() for a in result.assertions]


def test_determinism_fails_when_the_output_depends_on_the_ambient_locale(tmp_path: Path) -> None:
    """`byte_exact` is a promise across `TZ`, `LC_ALL` and `TMPDIR`, and this reads one of them."""
    subject = _variant(
        tmp_path,
        "locale",
        driver=(
            "        out: list[dict[str, object]] = [",
            "        import os\n"
            '        _tz = os.environ.get("TZ", "")\n'
            "        out: list[dict[str, object]] = [",
        ),
    )
    driver_py = next(tmp_path.glob("owconform_variant_locale/driver.py"))
    text = driver_py.read_text(encoding="utf-8")
    text = text.replace('"media_type": "text/plain",', '"media_type": "text/plain" + _tz,')
    driver_py.write_text(text, encoding="utf-8")
    result = run_suite("determinism", subject)
    assert _failed(result, "ambient:"), [a.line() for a in result.assertions]


def test_limits_fails_when_the_driver_rechecks_a_host_enforced_ceiling(tmp_path: Path) -> None:
    """DR20's inverted assertion: re-checking `max_input_bytes` is a second safety limit."""
    subject = _variant(
        tmp_path,
        "rechecker",
        driver=(
            "        with io.blobs.open(unit.content_sha256) as fh:",
            # `retry_after_ms` is REQUIRED: `resource_limit` is in `TRANSIENT_FAILURE_CLASSES`
            # and `DriverError.__post_init__` enforces charter D3's "required iff transient".
            # Omitting it makes the constructor raise `ValueError` instead, which is a different
            # defect and would test a different branch.
            "        if unit.byte_len > 33554432:\n"
            "            raise DriverError(cls=FailureClass.RESOURCE_LIMIT,\n"
            '                              message="too big", limit="max_input_bytes",\n'
            "                              retry_after_ms=0)\n"
            "        with io.blobs.open(unit.content_sha256) as fh:",
        ),
    )
    result = run_suite("limits", subject)
    assert _failed(result, "max_input_bytes"), [a.line() for a in result.assertions]


def test_limits_fails_when_a_card_declares_exactly_the_host_ceiling(tmp_path: Path) -> None:
    """A ceiling equal to the host's is not a limit of the driver's own."""
    subject = _variant(
        tmp_path, "maxed", card=("max_input_bytes = 33554432", "max_input_bytes = 134217728")
    )
    result = run_suite("limits", subject)
    assert _failed(result, "declared:max_input_bytes:meaning"), [
        a.line() for a in result.assertions
    ]


def test_sandbox_fails_when_the_driver_writes_outside_tmp(tmp_path: Path) -> None:
    """`io.tmpdir` is the one writable path a driver has; `DriverIO` carries no second one."""
    escape = tmp_path / "escaped.txt"
    subject = _variant(
        tmp_path,
        "escaper",
        driver=(
            "        out: list[dict[str, object]] = [",
            f'        open({str(escape)!r}, "w").close()\n        out: list[dict[str, object]] = [',
        ),
    )
    result = run_suite("sandbox", subject)
    assert _failed(result, "write:"), [a.line() for a in result.assertions]


def test_sandbox_fails_when_the_fragment_forges_provenance(tmp_path: Path) -> None:
    """P24: no `block_id`, no `producer_id`, no price, no cache-hit claim."""
    subject = _variant(
        tmp_path,
        "forger",
        driver=(
            '                    "t": "block",',
            '                    "t": "block",\n                    "block_id": 7,',
        ),
    )
    result = run_suite("sandbox", subject)
    assert _failed(result, "P24"), [a.line() for a in result.assertions]


def test_cost_fails_when_a_free_card_declares_a_billed_dimension(tmp_path: Path) -> None:
    """The defect the row names: a "free" driver that phones home, priced in a real dimension."""
    subject = _variant(
        tmp_path,
        "notfree",
        card=("per_part    = { wall_ms = 1 }", "per_part    = { tokens_out = 100 }"),
    )
    result = run_suite("cost", subject)
    assert _failed(result, "free:spend"), [a.line() for a in result.assertions]


def test_cost_fails_when_a_free_card_also_declares_it_needs_the_network(tmp_path: Path) -> None:
    subject = _variant(
        tmp_path, "phonehome", card=("needs_network  = false", "needs_network  = true")
    )
    result = run_suite("cost", subject)
    assert _failed(result, "free:network"), [a.line() for a in result.assertions]


def test_licence_fails_when_the_card_declares_no_spdx(tmp_path: Path) -> None:
    """A driver with no declared licence is a driver an operator cannot clear."""
    subject = _variant(tmp_path, "unlicensed", card=('spdx = "Apache-2.0"', 'spdx = ""'))
    result = run_suite("licence", subject)
    assert _failed(result, "card:spdx"), [a.line() for a in result.assertions]


def test_fuzz_fails_when_a_malformed_input_raises_something_untyped(tmp_path: Path) -> None:
    """P28: a corrupt fixture yields a typed `DriverError`; a bare exception is the finding."""
    subject = _variant(
        tmp_path,
        "untyped",
        driver=(
            "        except UnicodeDecodeError as exc:",
            "        except UnicodeDecodeError as exc:\n"
            "            raise ValueError(str(exc)) from None\n"
            "        except AssertionError as exc:",
        ),
    )
    result = run_suite("fuzz", subject)
    assert _failed(result, "typed"), [a.line() for a in result.assertions]


def test_quality_is_unknown_rather_than_failing_when_there_is_no_benchmark(
    tmp_path: Path,
) -> None:
    """13-quality.md:1747: declining to produce a number is honest rather than deficient."""
    result = run_suite("quality", _subject(tmp_path))
    assert result.verdict is Verdict.UNKNOWN
    assert not result.mandatory
    assert "ow conform --bench" in result.summary
