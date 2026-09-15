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


# --------------------------------------------------------------------------------------------
# 4. `scoreboard`, `propose` and `promote` -- the three that open the store.
# --------------------------------------------------------------------------------------------

SLICE = "pdf/workiva/true/en"

_DECISION = (
    "INSERT INTO route_decision (decision_id, content_sha256, unit_part, lane, rung, "
    "policy_digest, pricebook_digest, hints_digest, read_set_digest, driver, cost_class, "
    "rule_id, rule_origin, slice_key, evidence_digest, est_spend, est_micros, reserved_micros, "
    "admission, generation, decided_at) "
    "VALUES (?, ?, '', 'text', 1, 'p', 'b', 'h', ?, 'parse.page.olmocr', 'local_compute', "
    "'decode.part-text-unusable', 'o', ?, ?, '{}', 854, 2732, 'admitted', 1, 0)"
)


def _store(tmp_path: Path, *, install: bool = True, decisions: int = 50) -> Path:
    """A store carrying section 10.3's slice: forty photo pages and ten genuine scans.

    The population is the one 05:3155-3162 describes -- a full-page photograph with a caption
    escalates, `agree.decode_vs_page` comes back at 0.94, and the 858 micros bought nothing -- so
    the proposal this produces is a claim about the shipped policy and not about a fixture.
    """
    from omniweave.route import ledger as rlg  # noqa: PLC0415 -- the tool's own dependency
    from omniweave.route import policy as rp  # noqa: PLC0415
    from omniweave_core.store.sqlite import connect  # noqa: PLC0415

    path = tmp_path / "index.owstore"
    conn = connect(path)
    migrations = REPO_ROOT / "packages" / "omniweave-core" / "src" / "omniweave_core" / "store"
    for sql in sorted((migrations / "schema" / "migrations").glob("[0-9]*.sql")):
        conn.executescript(sql.read_text(encoding="utf-8"))
    conn.execute("PRAGMA foreign_keys = ON")
    if install:
        rlg.install_thresholds(conn, rp.compile_policy([rp.builtin_layer()], registry=None))
    for index in range(decisions):
        photo = index < decisions * 4 // 5
        name = f"d{index:03d}"
        payload = rlg.payload_bytes(
            [("ink.coverage", "1", (0.10 if photo else 0.01) + (index % 10) * 0.001)]
        )
        conn.execute(
            "INSERT INTO route_evidence (evidence_digest, payload, first_seen_at) VALUES (?, ?, 0)",
            (name, payload),
        )
        conn.execute(_DECISION, (name, name, name, SLICE, name))
        for source in ("agree", "audit"):
            conn.execute(
                "INSERT INTO route_quality (decision_id, source, metric, agreement, created_at) "
                "VALUES (?, ?, 'norm_edit_agreement', ?, 0)",
                (name, source, 0.94 if photo else 0.30),
            )
        conn.execute(
            "INSERT INTO route_spend (decision_id, attempt, micros, outcome) "
            "VALUES (?, 1, 858, 'ok')",
            (name,),
        )
    conn.close()
    return path


def test_scoreboard_refuses_rather_than_printing_a_wall_of_ok(tmp_path: Path) -> None:
    """D-12 (15:1525) checked BEFORE the rows print. Every `state` the view produces with a
    threshold row missing is `'OK'`, so printing first and warning second would put a wall of green
    in front of an operator and the reason for it underneath."""
    out = StringIO()
    store = _store(tmp_path, install=False, decisions=1)
    assert tool.main(["scoreboard", "--store", str(store)], writer=out) == tool.EXIT_NOT_RUN
    report = out.getvalue()
    assert "missing audit.min_audit_n" in report
    assert "falls through to" in report


def test_scoreboard_prints_the_views_own_state_column(tmp_path: Path) -> None:
    """Fifty decisions, fifty audited, against a `min_audit_n` of thirty: the slice has left
    `UNKNOWN`, and at a mean divergence of 0.19 against `regress_at = 0.08` it is REGRESSED."""
    out = StringIO()
    store = _store(tmp_path)
    assert tool.main(["scoreboard", "--store", str(store)], writer=out) == tool.EXIT_CLEAN
    report = out.getvalue()
    assert "REGRESSED" in report
    assert SLICE in report
    assert "1 slice/rule/driver rollup(s)" in report


def test_propose_without_the_exchange_rate_refuses(tmp_path: Path) -> None:
    """D209. No `PriceBook` row prices a unit of divergence, so a default here would put a number
    nobody chose inside every proposal the framework ever emits."""
    out = StringIO()
    store = _store(tmp_path)
    assert tool.main(["propose", "--store", str(store)], writer=out) == tool.EXIT_NOT_RUN
    assert "--divergence-micros has no default" in out.getvalue()


def test_propose_emits_a_diff_that_lowers_ink_coverage_min(tmp_path: Path) -> None:
    """D223, end to end. 05:2321 and 05:3161 both call this evidence what `ow route propose` reads
    *"to raise `ink_coverage_min`"*, and the rule escalates BELOW the threshold -- so raising it
    escalates more of exactly the pages the section calls the known false positive."""
    out = StringIO()
    store = _store(tmp_path)
    code = tool.main(["propose", "--store", str(store), "--divergence-micros", "10000"], writer=out)
    assert code == tool.EXIT_CLEAN
    report = out.getvalue()
    assert "-ink_coverage_min = 0.25" in report
    plus = next(line for line in report.splitlines() if line.startswith("+ink_coverage_min"))
    assert float(plus.split("=")[1]) < 0.25
    assert "unfittable  garble_min_chars" in report
    assert "14 pass(es), 1 proposal(s) over 1 slice(s)" in report


def test_promote_is_a_dry_run_until_apply(tmp_path: Path) -> None:
    """05:2996: *"Neither writes without a commit."* A command that wrote on the way to being read
    is one the reviewer meets after the fact."""
    target = tmp_path / "route.toml"
    target.write_text(
        "[thresholds]\nink_coverage_min = 0.25              # marker layout_coverage_threshold\n",
        encoding="utf-8",
        newline="\n",
    )
    diff = tmp_path / "route.diff"
    diff.write_text(
        "--- a/route.toml\n+++ b/route.toml\n [thresholds]\n"
        "#  ink_coverage_min = 0.02 (was 0.25, slice pdf/workiva/true/en, n=50)\n"
        "-ink_coverage_min = 0.25\n+ink_coverage_min = 0.02\n",
        encoding="utf-8",
        newline="\n",
    )
    dry = StringIO()
    argv = ["promote", "--diff", str(diff), "--target", str(target)]
    assert tool.main(argv, writer=dry) == tool.EXIT_CLEAN
    assert "would apply" in dry.getvalue()
    assert "0.25" in target.read_text("utf-8")

    wet = StringIO()
    assert tool.main([*argv, "--apply"], writer=wet) == tool.EXIT_CLEAN
    after = target.read_text("utf-8")
    assert "ink_coverage_min = 0.02              # marker layout_coverage_threshold" in after
    assert "written to" in wet.getvalue()


def test_promote_refuses_a_file_that_moved_since_the_review(tmp_path: Path) -> None:
    target = tmp_path / "route.toml"
    target.write_text("[thresholds]\nink_coverage_min = 0.30\n", encoding="utf-8", newline="\n")
    diff = tmp_path / "route.diff"
    diff.write_text(
        "--- a/route.toml\n+++ b/route.toml\n-ink_coverage_min = 0.25\n+ink_coverage_min = 0.02\n",
        encoding="utf-8",
        newline="\n",
    )
    out = StringIO()
    argv = ["promote", "--diff", str(diff), "--target", str(target), "--apply"]
    assert tool.main(argv, writer=out) == tool.EXIT_FAIL
    assert "moved between the propose and the promote" in out.getvalue()
    assert target.read_text("utf-8") == "[thresholds]\nink_coverage_min = 0.30\n"


def test_promote_without_a_diff_says_which_flag_is_missing() -> None:
    out = StringIO()
    assert tool.main(["promote"], writer=out) == tool.EXIT_NOT_RUN
    assert "--diff names the reviewed diff" in out.getvalue()


def test_a_store_that_is_not_there_is_named_rather_than_raised(tmp_path: Path) -> None:
    out = StringIO()
    missing = tmp_path / "nope.owstore"
    assert tool.main(["scoreboard", "--store", str(missing)], writer=out) == tool.EXIT_NOT_RUN
    assert "--store names another" in out.getvalue()
