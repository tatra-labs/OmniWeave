"""The kit's non-suite modules: the report shapes, the two entitled strings, DR13's gate, Q-G23.

Four subjects, one file, because each is small and all four are about the same thing -- what a run
is allowed to SAY once the suites have finished:

* `result` -- the arithmetic a badge is computed from. `11/11` has to mean eleven of the eleven
  that exist, and `mandatory_total` returning "the number that reported" would let a run that lost
  a suite print `10/10` and read as a pass.
* `badge` -- the two strings 04-driver-system.md:2115 and :2398 entitle an author to, and the fact
  that they are GENERATED is itself the mechanism refusing "certified" and "verified by omniweave"
  (:2119-2121).
* `publish` -- DR13's refusal, and the one writer of the three kit-written regions. The
  `attestation` position test is the one that matters: a misplaced attestation PARSES, lands in
  the wrong table, and the loader's recomputation then reads nothing (04:859-862).
* `normalize` -- Q-G23's property. "Two normalisers that quietly converge are one normaliser with
  two names" (13-quality.md:1078).

Specified in 04-driver-system.md sections 8.3 and 8.4; 13-quality.md section 8.2.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import omniweave_conform.suites as suites_module
import pytest
from omniweave_conform import Subject, badge, run, sentence
from omniweave_conform.badge import DISTRIBUTION, SENTENCE, suite_table
from omniweave_conform.normalize import normalize_eval, strip_md
from omniweave_conform.publish import check as publish_check
from omniweave_conform.publish import write_results
from omniweave_conform.result import (
    MANDATORY,
    SUITES,
    Assertion,
    ConformReport,
    SuiteResult,
    Verdict,
)
from omniweave_conform.runner import (
    MANDATORY_BUDGET_S,
    mandatory_budget_exceeded,
    verdict_line,
)
from omniweave_conform.suites import run_suite
from omniweave_core.drivers.card import (
    QUALITY_SUITES,
    QUALITY_VERDICTS,
    attestation_of,
    load_card,
    read_card_bytes,
)
from omniweave_core.ident import fold_common, normalize_k

TEMPLATE = Path(__file__).resolve().parents[2] / "src/omniweave_conform/template"
CARD = TEMPLATE / "driver.toml"
FIXTURES = TEMPLATE / "fixtures"


def _result(suite: str, verdict: Verdict) -> SuiteResult:
    return SuiteResult(suite, verdict, (Assertion("x", ok=verdict is Verdict.PASS),), "s", 1.0)


def _report(**overrides: Verdict) -> ConformReport:
    """A report where every suite passes unless named otherwise."""
    verdicts = dict.fromkeys(SUITES, Verdict.PASS)
    verdicts.update(overrides)
    return ConformReport(
        results=tuple(_result(name, verdict) for name, verdict in verdicts.items()),
        card_sha256="sha256:" + "a" * 64,
        kit_version="1.0.0",
        driver_id="parse.text.plain",
    )


# ---------------------------------------------------------------------------------------------
# result
# ---------------------------------------------------------------------------------------------


def test_the_verdict_vocabulary_is_the_cards_and_not_a_second_one() -> None:
    """Both sides are transcriptions of the same plan sentence, so this pins agreement.

    It catches drift between two transcriptions and proves nothing about the plan; the module
    docstring of `result.py` says so rather than letting the test imply otherwise.
    """
    assert tuple(v.value for v in Verdict) == QUALITY_VERDICTS
    assert SUITES is QUALITY_SUITES


def test_the_mandatory_denominator_is_the_eleven_that_exist_not_the_ones_that_reported() -> None:
    """A run that lost a suite must not be able to print 10/10 and read as a pass."""
    short = ConformReport(
        results=tuple(
            _result(name, Verdict.PASS) for name in SUITES if name not in {"fuzz", "quality"}
        ),
        card_sha256="sha256:" + "b" * 64,
        kit_version="1.0.0",
    )
    assert short.mandatory_passed == len(MANDATORY) - 1
    assert short.mandatory_total == len(MANDATORY) == 11
    assert not short.passed
    assert short.verdict_of("fuzz") is Verdict.UNKNOWN


def test_quality_never_gates_a_run() -> None:
    """13-quality.md:1740: the twelfth suite is deliberately not mandatory."""
    assert _report(quality=Verdict.UNKNOWN).passed
    assert _report(quality=Verdict.FAIL).passed
    assert not _report(fuzz=Verdict.UNKNOWN).passed


def test_a_suite_result_refuses_a_name_outside_the_twelve() -> None:
    with pytest.raises(ValueError, match="not one of the twelve"):
        SuiteResult("invented", Verdict.PASS)


def test_of_derives_the_verdict_from_the_assertions_and_never_takes_one() -> None:
    """There must be no argument a caller can pass that turns an unchecked suite into a pass."""
    assert SuiteResult.of("card", [Assertion("a", ok=True)]).verdict is Verdict.PASS
    assert SuiteResult.of("card", [Assertion("a", ok=False)]).verdict is Verdict.FAIL
    assert SuiteResult.of("card", []).verdict is Verdict.UNKNOWN
    unknown = SuiteResult.of("card", [Assertion("a", ok=True)], unknown="no corpus")
    assert unknown.verdict is Verdict.UNKNOWN
    assert unknown.summary == "no corpus"


def test_an_empty_verdict_set_is_unknown_rather_than_pass() -> None:
    """A kit reporting a pass for a run that asserted nothing is the defect, not the answer."""
    assert Verdict.worst([]) is Verdict.UNKNOWN
    assert Verdict.worst([Verdict.PASS, Verdict.UNKNOWN]) is Verdict.UNKNOWN
    assert Verdict.worst([Verdict.PASS, Verdict.UNKNOWN, Verdict.FAIL]) is Verdict.FAIL


def test_an_assertion_line_names_the_fixture_the_locus_and_both_strings() -> None:
    """04-driver-system.md:2334 is a requirement about the MESSAGE, so the message is tested."""
    line = Assertion(
        "origin_span re-verifies",
        ok=False,
        fixture="simple.txt",
        locus="P7:b2",
        expected="hello",
        actual="hellp",
    ).line()
    assert "FAIL" in line
    assert "simple.txt" in line and "P7:b2" in line
    assert "'hello'" in line and "'hellp'" in line


# ---------------------------------------------------------------------------------------------
# badge
# ---------------------------------------------------------------------------------------------


def test_the_badge_carries_the_kit_version_the_tally_and_the_card_digest() -> None:
    """04-driver-system.md:2115's three, and :2395's exact shape."""
    text = badge(_report(quality=Verdict.UNKNOWN))
    assert text.startswith(f"{DISTRIBUTION} 1.0.0")
    assert "mandatory 11/11 pass" in text
    assert "quality unknown" in text
    assert "card sha256:aaaaaaaa..." in text
    assert text.count("·") == 3


def test_a_failing_run_gets_no_entitled_sentence() -> None:
    """There is no honest softer form; :2134 is about exactly this surface."""
    assert sentence(_report()) == SENTENCE.format(version="1.0.0")
    assert sentence(_report(fuzz=Verdict.FAIL)) == ""
    assert "FAIL" in badge(_report(fuzz=Verdict.FAIL))


def test_the_suite_table_names_all_twelve_even_when_one_did_not_report() -> None:
    """An absent suite writes `unknown`, which is the card grammar's word for "we do not know"."""
    short = ConformReport(
        results=(_result("card", Verdict.PASS),),
        card_sha256="sha256:" + "c" * 64,
        kit_version="1.0.0",
    )
    table = suite_table(short)
    assert list(table) == list(SUITES)
    assert table["card"] == "pass"
    assert set(table.values()) - {"pass"} == {"unknown"}


# ---------------------------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------------------------


def test_the_verdict_line_is_the_plans_own_arithmetic() -> None:
    """04-driver-system.md:2332's shape: `12 suites, 11 pass, 1 unknown, 0 fail, ... -> PASS`."""
    line = verdict_line(_report(quality=Verdict.UNKNOWN))
    assert line.startswith("12 suites, 11 pass, 1 unknown, 0 fail")
    assert line.endswith("-> PASS (mandatory tier)")


def test_the_five_minute_budget_is_a_predicate_and_not_a_timeout() -> None:
    """04:2085 asks for a CI timing assertion, and an assertion needs a number to read."""
    fast = _report()
    assert not mandatory_budget_exceeded(fast)
    slow = ConformReport(
        results=tuple(
            SuiteResult(name, Verdict.PASS, (), "", MANDATORY_BUDGET_S * 1000) for name in SUITES
        ),
        card_sha256="sha256:" + "d" * 64,
        kit_version="1.0.0",
    )
    assert mandatory_budget_exceeded(slow)


def test_a_suite_that_raises_is_attributed_to_the_kit_and_costs_the_others_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One broken suite must not take the run with it, and must not read as `unknown`."""

    def explode(subject: object) -> SuiteResult:  # noqa: ARG001 -- the signature is the Protocol's.
        msg = "deliberate"
        raise RuntimeError(msg)

    monkeypatch.setitem(dict(suites_module.SUITE_RUNNERS), "card", explode)
    monkeypatch.setattr(
        suites_module, "SUITE_RUNNERS", {**suites_module.SUITE_RUNNERS, "card": explode}
    )
    report = run(Subject.of(CARD, fixtures_dir=FIXTURES, workdir=tmp_path))
    card_result = report.by_suite()["card"]
    assert card_result.verdict is Verdict.FAIL
    assert "omniweave-conform" in card_result.failures()[0].detail
    assert card_result.failures()[0].locus == "kit"
    assert len(report.results) == len(SUITES), "the other eleven still ran"


# ---------------------------------------------------------------------------------------------
# publish (DR13)
# ---------------------------------------------------------------------------------------------


def test_the_template_card_is_publishable_because_it_writes_none_of_the_kit_regions() -> None:
    """A template shipping a `[quality]` block would ship an unearned claim."""
    assert publish_check(CARD.read_bytes()) == ()


@pytest.mark.parametrize(
    ("region", "injection"),
    [
        ("quality", '\n[quality]\nkit_version = "9.9.9"\n'),
        ("cost.measured", "\n[cost.measured]\np50_ms_per_unit = 1\n"),
        ("quality.suites", '\n[quality.suites]\ncard = "pass"\n'),
    ],
)
def test_an_author_written_kit_region_is_refused_with_its_line(region: str, injection: str) -> None:
    """DR13: `[cost.measured]` and `[quality]` are kit-written; author values are rejected."""
    findings = publish_check(CARD.read_bytes() + injection.encode())
    assert [f.region for f in findings] == [region]
    assert findings[0].line > 0
    assert "ow conform" in findings[0].detail


def test_an_author_written_attestation_is_refused() -> None:
    """It parses, and the loader then recomputes it and sets `attested = False`."""
    raw = CARD.read_bytes().replace(
        b"card_schema = 1", b'card_schema = 1\nattestation = "sha256:' + b"0" * 64 + b'"'
    )
    findings = publish_check(raw)
    assert [f.region for f in findings] == ["attestation"]


def test_write_results_puts_the_attestation_where_the_loader_will_find_it(
    tmp_path: Path,
) -> None:
    """**The position is not cosmetic.**

    04-driver-system.md:859-862: TOML scopes a bare key to the most recent header, so an
    `attestation` written after `[quality.suites]` parses as `quality.suites.attestation` and the
    loader's recomputation reads nothing. This asserts three things about the result: the key is
    top-level in the PARSED document, it appears before the first `[` in the BYTES, and the card
    the loader then builds reports `attested = True`.
    """
    card = tmp_path / "driver.toml"
    card.write_bytes(CARD.read_bytes())
    written = write_results(card, _report(quality=Verdict.UNKNOWN))

    document = tomllib.loads(written.decode("utf-8"))
    assert "attestation" in document, "the key must be top-level, not inside a table"
    assert "attestation" not in document.get("quality", {}).get("suites", {})

    # A table header is a LINE beginning with `[`, not the first `[` anywhere: this card's
    # comment header quotes several table names, and an earlier version of this assertion
    # found one of those and failed a correctly written card.
    lines = written.decode("utf-8").splitlines()
    first_header = next(i for i, line in enumerate(lines) if line.startswith("["))
    attestation_at = next(i for i, line in enumerate(lines) if line.startswith("attestation"))
    assert attestation_at < first_header, "before the first table header"

    body = {k: v for k, v in document.items() if k != "attestation"}
    assert document["attestation"] == attestation_of(body)

    reloaded = load_card(written, origin="driver_path", source=str(card))
    assert reloaded.attested, "the loader must recompute to the same value"
    assert dict(reloaded.quality.suites) == suite_table(_report(quality=Verdict.UNKNOWN))


def test_write_results_is_idempotent_and_replaces_rather_than_appends(tmp_path: Path) -> None:
    """Two runs must not leave two `[quality]` blocks, which `tomllib` refuses outright."""
    card = tmp_path / "driver.toml"
    card.write_bytes(CARD.read_bytes())
    first = write_results(card, _report(quality=Verdict.UNKNOWN))
    second = write_results(card, _report(quality=Verdict.UNKNOWN))
    assert first == second
    # Counted over HEADER LINES, not over substrings: this card's comment header mentions
    # `[quality]` three times while explaining that it ships without one, and a substring count
    # therefore says 4 for a correctly written file.
    lines = second.decode("utf-8").splitlines()
    assert [line for line in lines if line.strip() == "[quality]"] == ["[quality]"]
    assert len([line for line in lines if line.startswith("attestation =")]) == 1


def test_write_results_keeps_every_comment_the_author_wrote(tmp_path: Path) -> None:
    """A card is a file a human maintains, and a round-trip through a writer would drop them."""
    card = tmp_path / "driver.toml"
    card.write_bytes(CARD.read_bytes())
    before = CARD.read_text(encoding="utf-8")
    written = write_results(card, _report()).decode("utf-8")
    kept = [
        line
        for line in before.splitlines()
        if line.strip().startswith("#") and "OMITTED ENTIRELY" in line
    ]
    assert kept, "the fixture must contain the comment this test is about"
    for line in kept:
        assert line in written


def test_a_written_card_still_passes_the_card_suite(tmp_path: Path) -> None:
    """The end of the loop: what the kit writes, the kit can then validate."""
    card = tmp_path / "driver.toml"
    card.write_bytes(CARD.read_bytes())
    write_results(card, _report(quality=Verdict.UNKNOWN))
    subject = Subject.of(card, fixtures_dir=FIXTURES, workdir=tmp_path / "w")
    result = run_suite("card", subject)
    assert result.verdict is Verdict.PASS, [a.line() for a in result.failures()]
    assert "attestation ok" in result.summary


# ---------------------------------------------------------------------------------------------
# normalize (Q-G23)
# ---------------------------------------------------------------------------------------------


def test_normalize_eval_is_case_sensitive_and_normalize_k_is_not() -> None:
    """Q-G23, 13-quality.md:1076-1079.

    "Two normalisers that quietly converge are one normaliser with two names." Fed a corpus of
    case-varied strings, the two must DISAGREE about case -- which is the whole reason the second
    one exists, and the only property that makes it worth its own module.
    """
    corpus = ["Revenue Analysis", "ABC", "Introduction", "iPhone", "SEC Filing"]
    for text in corpus:
        assert normalize_eval(text) != normalize_eval(text.lower()) or text == text.lower()
        assert normalize_k(text)[0] == normalize_k(text.lower())[0]


def test_normalize_eval_folds_the_quote_families_nfkc_leaves_alone() -> None:
    """The fold BETWEEN the two: more than `nfc`, less than `normalize_k`."""
    assert normalize_eval("‘a’") == normalize_eval("'a'")
    assert normalize_eval("“a”") == normalize_eval('"a"')


@pytest.mark.parametrize(
    ("marked", "plain"),
    [
        ("**bold**", "bold"),
        ("__bold__", "bold"),
        ("<b>bold</b>", "bold"),
        ("<i>ital</i>", "ital"),
        ("*ital*", "ital"),
        ("_ital_", "ital"),
        ("a<br>b", "a b"),
        ("a<br/>b", "a b"),
    ],
)
def test_strip_md_removes_each_paired_form_olmocr_bench_removes(marked: str, plain: str) -> None:
    """olmOCR-Bench `tests.py:47-81`, exactly."""
    assert strip_md(marked) == plain


def test_strip_md_leaves_an_unpaired_delimiter_alone() -> None:
    """13:1056: "PAIRED, so `**a \\n\\n b**` is not matched".

    An unpaired asterisk is a character the reference text contains, and stripping it would
    silently delete it -- scoring a parser wrong for reproducing its input faithfully.
    """
    assert strip_md("**a \n\n b**") == "**a \n\n b**"
    assert strip_md("2 * 3 * 4") == "2 * 3 * 4"
    # `snake_case_name` IS folded to `snakecasename`, and that is deliberate rather than
    # asserted here: see `normalize.py`'s `_PAIRED` docstring. 13:1054 says "exactly"
    # olmOCR-Bench, the evaluator folds both sides of every comparison, and this file does
    # not assert a behaviour it cannot check against the cited source.


def test_normalize_eval_is_a_composition_and_not_a_second_fold_table() -> None:
    """13:1072: a dash added to `fold_common` must be added to both, because there is one table."""
    text = "en–dash and em—dash"
    assert normalize_eval(text) == fold_common(text, quotes=True, casefold=False)


def test_the_card_the_template_ships_loads_through_the_real_loader() -> None:
    """Ledger D121's regression: `18-api-sketch.md`'s printed card is refused on seven keys.

    The template's card is that card with the six corrected. This test is what stops it drifting
    back -- and it is the cheapest possible guard on the one artefact a third party copies.
    """
    card = load_card(read_card_bytes(CARD), origin="driver_path", source=str(CARD))
    assert card.identity.id == "parse.text.plain"
    assert card.parse is not None
    assert card.parse.origin_span == "exact"
    assert card.degradations == (), "a template must not ship a key the loader ignores"
    assert card.hardware.gpu == "none"
    assert card.hardware.needs_network is False
    assert card.limits.max_parts == 1
