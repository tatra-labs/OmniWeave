"""`tools/ow_route.py` -- the driver for `ow route lint` and `ow route lint --explain`.

The library halves are tested in `test_route_checks.py`; what is left here is the part a `tools/`
script owns and a package function cannot: the exit codes, the `Installation` assembled from the
workspace, and the two flags whose behaviour is a decision rather than a lookup.

The strongest test is the last one: **the shipped policy lints clean on this checkout**, at zero
errors and one warning, which is 16-roadmap.md:632's P5 exit-criteria line minus the `--estimates`
half that has no specification.
"""

from __future__ import annotations

import importlib.util
import sys
from io import StringIO
from pathlib import Path

import pytest


def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "ow_route.py"

_SPEC = importlib.util.spec_from_file_location("omniweave_ow_route", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - the file is in this repository
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
tool = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = tool
_SPEC.loader.exec_module(tool)

BOOK = """
version = 1
currency = "USD"
effective_from = "2026-01-01"
[local]
gpu_ms = 0.3556
cpu_ms = 0.00928
wall_ms = 0.0
"""
"""Section 6.2's three rates, as the file `--pricebook` reads. 05:3081 prices section 10 with it."""


# --------------------------------------------------------------------------------------------
# 1. The Installation the script assembles from a checkout.
# --------------------------------------------------------------------------------------------


def test_the_provider_name_comes_from_the_entry_point_and_not_the_directory() -> None:
    """`omniweave-pdf` declares `"pdfium" = "omniweave_pdf"` and `omniweave-office` declares
    `"officexml"`. Deriving the provider from the directory would put `pdf` and `office` into
    every read-set triple, and `route_signal` is keyed on the provider's version -- so the wrong
    name is a wrong cache namespace rather than a cosmetic slip."""
    providers = {spec.provider for spec in tool.signal_specs()}
    assert {"pdfium", "officexml"} <= providers
    assert not {"pdf", "office"} & providers


def test_the_registry_it_builds_is_the_day_one_fifty_three() -> None:
    """Section 5.1 tabulates 54 keys and 53 register; the fifty-fourth is `layout.class_hist`,
    whose provider column reads *"none (day 1)"* (05:2161)."""
    keys = {spec.key for spec in tool.signal_specs()}
    assert len(keys) == 53
    assert "layout.class_hist" not in keys


def test_the_cards_it_finds_are_the_two_first_party_parse_drivers() -> None:
    """`omniweave-vision` is W5.6's, so `parse.page.olmocr` has no card on this tree -- which is
    what makes checks 9, 11 and 13 partly undecidable rather than green."""
    cards = tool.installed_cards()
    assert sorted(cards) == ["parse.office.anydoc", "parse.pdf.pdfium"]
    assert "parse.page.olmocr" not in cards


def test_the_retrieval_budget_is_the_declared_default() -> None:
    budget = tool.retrieval_budget()
    assert sorted(budget) == [
        "retrieval.budget.channel_ms",
        "retrieval.budget.hydration_reserve_ms",
        "retrieval.budget.query_ms",
    ]
    assert budget["retrieval.budget.query_ms"] == 250


# --------------------------------------------------------------------------------------------
# 2. The exit codes.
# --------------------------------------------------------------------------------------------


def test_the_shipped_policy_lints_clean() -> None:
    """Zero errors, one warning, and every check that did not run says why. 16-roadmap.md:632."""
    out = StringIO()
    assert tool.main([], writer=out) == tool.EXIT_CLEAN
    report = out.getvalue()
    assert "0 error(s), 1 warning(s)" in report
    assert "not run: check 5:" in report
    assert "not run: check 13:" in report


def test_strict_turns_the_one_warning_into_a_failure() -> None:
    """`--strict` is "treat the `expect_unavailable` exemption as spent" and nothing else: it is
    the only warning the fourteen produce (05:1001)."""
    out = StringIO()
    assert tool.main(["--strict"], writer=out) == tool.EXIT_FAIL
    assert "fields.extract" in out.getvalue()


def test_estimates_refuses_rather_than_being_accepted_and_ignored() -> None:
    """No line in the plan says what `--estimates` asserts. A flag that exits 0 without doing
    anything is a CI line that tests nothing."""
    out = StringIO()
    assert tool.main(["--estimates"], writer=out) == tool.EXIT_NOT_RUN
    assert "not implemented" in out.getvalue()


def test_a_pricebook_turns_check_thirteen_from_not_run_into_a_verdict(tmp_path: Path) -> None:
    """Check 13 compares micros against micros, and a card declares physical units."""
    book = tmp_path / "pricebook.toml"
    book.write_text(BOOK, encoding="utf-8")
    plain, priced = StringIO(), StringIO()
    tool.main([], writer=plain)
    assert tool.main(["--pricebook", str(book)], writer=priced) == tool.EXIT_CLEAN
    assert "not run: check 13:" in plain.getvalue()
    assert "not run: check 13:" not in priced.getvalue()


def test_a_format_domain_turns_check_ten_from_not_run_into_a_verdict(tmp_path: Path) -> None:
    """Check 10's target is the COMPUTED domain and `route/detect.py` has not shipped it, so the
    file is the only way to supply one -- and supplying a wrong one is a finding, which is the
    check doing its job."""
    domain = tmp_path / "tokens.txt"
    domain.write_text("pdf docx warc\n", encoding="utf-8")
    out = StringIO()
    assert tool.main(["--format-domain", str(domain)], writer=out) == tool.EXIT_FAIL
    report = out.getvalue()
    assert "OW-P-014" in report
    assert "warc" in report
    assert "not run: check 10:" not in report


def test_an_overlay_layer_is_merged_over_the_builtin_rather_than_replacing_it(
    tmp_path: Path,
) -> None:
    """05:936: merge is concatenation with the higher layer PREPENDED, so an operator linting
    their own overlay sees both."""
    overlay = tmp_path / "90-site.toml"
    overlay.write_text(
        'surface = "route"\n\n[[rule]]\nid = "site.extra"\nrung = "GATE"\n'
        'when = { "unit.bytes" = { gt = 0 } }\nthen = { outcome = "not_eligible" }\n',
        encoding="utf-8",
    )
    out = StringIO()
    tool.main(["--layer", str(overlay)], writer=out)
    assert "41 rule(s)" in out.getvalue()


# --------------------------------------------------------------------------------------------
# 3. `--explain`.
# --------------------------------------------------------------------------------------------


def test_explain_prints_the_group_a_key_lands_in() -> None:
    """`ink.coverage` is the only LOCAL_COMPUTE key at `DECODE/text/settle`, so it lands in group 1
    -- and it is the only clause that can falsify `decode.part-text-unusable` (D216)."""
    out = StringIO()
    assert tool.main(["--explain", "decode.part-text-unusable"], writer=out) == tool.EXIT_CLEAN
    report = out.getvalue()
    assert "DECODE/text/settle  action" in report
    assert "ink.coverage" in report
    assert "group 1" in report
    assert "local_compute" in report


def test_explain_with_formats_shows_that_block_type_has_no_pdf_row() -> None:
    """05:2224, as a command: *"how a reviewer sees at a glance that `block.type` has no PDF
    row."*"""
    out = StringIO()
    tool.main(["--explain", "decode.admit-table-lane", "--formats", "pdf"], writer=out)
    assert "UNSERVED on pdf" in out.getvalue()


def test_explain_on_an_unknown_rule_is_not_run_rather_than_a_crash() -> None:
    out = StringIO()
    assert tool.main(["--explain", "nope"], writer=out) == tool.EXIT_NOT_RUN
    assert "is not a rule in this policy" in out.getvalue()


@pytest.mark.parametrize("rule_id", ["gate.empty", "decode.office-native", "page.output-invalid"])
def test_every_shipped_rule_explains_without_raising(rule_id: str) -> None:
    """A rule whose read set is empty, one whose driver has a card, and one at a later rung."""
    out = StringIO()
    assert tool.main(["--explain", rule_id], writer=out) == tool.EXIT_CLEAN
    assert rule_id in out.getvalue()
