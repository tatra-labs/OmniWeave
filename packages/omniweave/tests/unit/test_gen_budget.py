"""`omniweave.gen.budget` and the frozen `benchmarks/serve_schema_baseline.json`.

Three things are under test and they fail for different reasons, which is why they are separated
here as they are separated in the module.

* **The counting** is 10:321's recipe, and it is checked against a stand-in encoder so the shape of
  a finding is testable on a machine with no encoding table. Every test in this file runs offline.
* **The frozen file** is checked against itself -- its arithmetic, its ceilings, its key order --
  with no tokenizer at all, because a baseline somebody edited by hand should fail on the machine
  that cannot count.
* **The drift** is SV2, and it is the only part that needs `tiktoken`. It skips rather than fails
  when the encoding cannot be resolved, and D371 is why that is not paranoia: resolving
  `cl100k_base` on a cache miss fetches it from a host with no row in `tools/egress.toml`.

The five numbers this file asserts that the plan prints differently -- `ow_corpora` at 195 in both
columns, and the three totals it moves -- are D316's, not this cell's. That entry did the counting
and shipped the fix; this one freezes the result.
"""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.gen.budget as budget_module
import pytest
from omniweave.gen.budget import (
    BASELINE_DIR,
    BASELINE_NAME,
    CEILINGS,
    DRIFT_TOLERANCE,
    NO_CORPUS_SUFFIX,
    RECIPE,
    TOKENIZER,
    Baseline,
    Measurement,
    baseline_path,
    blessed,
    drift,
    findings,
    measure,
    read_baseline,
    serialised,
    tokens,
)
from omniweave.gen.emit import REPO_ROOT
from omniweave.gen.instructions import FRONT_DOOR, instructions
from omniweave.gen.llms import RELEASE
from omniweave.gen.mcp_tools import listing, omitted, tools, unpublished
from omniweave.surface.registry import ACTIONS, DEFAULT_PROFILE, PROFILES, listed
from omniweave.surface.schema import compact, with_required_corpus

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave.gen.budget import Encoder


# =============================================================================================
# Fixtures and stand-ins
# =============================================================================================


def _words(text: str) -> list[int]:
    """A tokenizer with no table: one token per whitespace-separated run, plus one per brace.

    It is not `cl100k_base` and does not pretend to be. What it preserves is the only property the
    module depends on -- that a longer serialisation counts higher -- so every structural test runs
    without the 1.7 MB merge table and therefore without the network. D371.
    """
    return [1] * (len(text.split()) + text.count("{") + text.count("}"))


def _real_encoder() -> Encoder:
    """`cl100k_base`, or a skip naming why it could not be had.

    A skip and not a failure: 10:2585 makes the tokenizer a dev dependency, and D371 records that
    resolving the encoding on a cache miss reaches an unregistered host. A CI machine that cannot
    make that request should report SV2 as unmeasured, not as violated.
    """
    tiktoken = pytest.importorskip("tiktoken", reason="tiktoken is a dev-only dependency (10:2585)")
    try:
        return tiktoken.get_encoding(TOKENIZER).encode
    except Exception as exc:
        pytest.skip(f"{TOKENIZER} could not be resolved offline: {exc}")


def _committed() -> Baseline:
    """The baseline this repository ships."""
    return read_baseline()


def _edited(**changes: Any) -> Baseline:
    """The committed baseline with fields replaced, for the findings that need a broken file."""
    fields = {
        "path": Path("serve_schema_baseline.json"),
        "tokenizer": TOKENIZER,
        "recipe": RECIPE,
        "release": RELEASE,
        "default_compact": 856,
        "default_full": 1037,
        "default_compact_corpus_required": 871,
        "full_compact": None,
        "full_full": None,
        "per_tool_compact": {"ow_query": 289, "ow_open": 210, "ow_corpora": 195, "ow_add": 162},
        "per_tool_full": {"ow_query": 411, "ow_open": 258, "ow_corpora": 195, "ow_add": 173},
        "instructions_chars": {"default": 977, "no_corpus": 996},
        "ceilings": dict(CEILINGS),
        "drift_tolerance": DRIFT_TOLERANCE,
    }
    fields.update(changes)
    return Baseline(**fields)  # type: ignore[arg-type]


# =============================================================================================
# 1. The recipe
# =============================================================================================


def test_serialised_is_the_recipe_constant_executed() -> None:
    """10:2586's `recipe` field is a string in the file and a call in the code, and they must be
    the same call. A baseline whose recipe says one thing while the counter does another is a
    number with no reproduction instructions."""
    entry = listing(DEFAULT_PROFILE)[0]
    assert serialised(entry) == json.dumps(entry, separators=(",", ":"), ensure_ascii=False)
    assert RECIPE == "json.dumps(tool,separators=(',',':'),ensure_ascii=False)"


def test_ensure_ascii_false_is_load_bearing() -> None:
    """10:331: *"the descriptions contain `—` and `·`, and `ensure_ascii=True` would emit them as
    six-character `\\uXXXX` escapes, inflating the count by an artefact of the serializer rather
    than of the wire."* The payload is real UTF-8, so the check is that no escape survives."""
    text = "".join(serialised(entry) for entry in listing(DEFAULT_PROFILE))
    assert "\\u2014" not in text, "an em dash was escaped; the count would be the serializer's"
    assert "—" in text or "·" in text, "no non-ASCII survived, so the test proves nothing"


def test_serialised_is_the_most_compact_json_there_is() -> None:
    """Separators without spaces, because the count is of the wire and not of a pretty-print. The
    artefact on disk is two-space indented and that indentation is not what an agent pays for."""
    entry = listing(DEFAULT_PROFILE)[0]
    assert len(serialised(entry)) < len(json.dumps(entry, ensure_ascii=False))
    assert len(serialised(entry)) < len(json.dumps(entry, indent=2, ensure_ascii=False))


def test_tokens_counts_what_the_encoder_returns() -> None:
    """The only arithmetic in `tokens()` is a length, which is what makes the encoder swappable."""
    entry = listing(DEFAULT_PROFILE)[0]
    assert tokens(entry, _words) == len(_words(serialised(entry)))


# =============================================================================================
# 2. `listing()` -- the three transforms, in one place, in the right order
# =============================================================================================


def test_listing_is_the_artefact_selected_by_profile() -> None:
    """`tools()` is every renderable tool and `listing()` is one profile's subset of it, unchanged
    when neither transform is asked for. If these two ever disagree, the server and the gate are
    measuring different payloads."""
    whole = {entry["name"]: entry for entry in tools()}
    selected = listing(DEFAULT_PROFILE, compact_schemas=False, corpus_required=False)
    assert [entry["name"] for entry in selected] == sorted(whole)
    for entry in selected:
        assert entry == whole[entry["name"]]


def test_listing_preserves_the_artefacts_order() -> None:
    """10:225 sorts artefact 1 by Action name. A payload re-sorted here would make a reviewer
    holding the file and a reviewer holding a capture read two different orders for one surface."""
    assert [entry["name"] for entry in listing(DEFAULT_PROFILE)] == [
        entry["name"] for entry in tools()
    ]


@pytest.mark.parametrize("profile", PROFILES)
def test_listing_drops_only_what_cannot_be_rendered(profile: str) -> None:
    """Every Action the profile lists is in the payload unless `omitted()` names it, and the two
    sets are complementary. That is the property that lets `full_compact` stay `null` honestly."""
    wanted = {ACTIONS[action].mcp_name for action in listed(profile)}
    present = {entry["name"] for entry in listing(profile)}
    assert present | set(omitted(profile)) == wanted
    assert present & set(omitted(profile)) == set()


def test_omitted_is_unpublished_narrowed_to_a_profile() -> None:
    """`unpublished()` is the registry against the generator and `omitted()` is one profile against
    the generator, so the second is contained in the first for every profile there is."""
    for profile in PROFILES:
        assert set(omitted(profile)) <= set(unpublished())
    assert omitted(DEFAULT_PROFILE) == (), "the default profile must render whole"
    assert omitted("full") == ("ow_coverage", "ow_diff", "ow_doctor", "ow_explain", "ow_grid")


def test_no_listed_action_declares_corpus_advanced() -> None:
    """This is what makes the transform order safe rather than lucky.

    `compact()` removes the advanced properties and `with_required_corpus()` re-derives `required`
    in property order. If `corpus` were advanced, promoting before compacting would leave a schema
    requiring a parameter it does not declare -- and `additionalProperties: false` would make that
    unsatisfiable rather than merely odd."""
    for profile in PROFILES:
        for action in listed(profile):
            assert "corpus" not in ACTIONS[action].advanced, action


@pytest.mark.parametrize("profile", PROFILES)
def test_the_two_transforms_commute_today(profile: str) -> None:
    """Given the assertion above they commute, and pinning it turns the order in `listing()` from a
    decision a reader has to trust into one a failure would announce."""
    for entry in listing(profile, compact_schemas=False):
        assert with_required_corpus(compact(entry)) == compact(with_required_corpus(entry))


def test_corpus_promotion_adds_corpus_to_every_corpus_scoped_tool() -> None:
    """10:525's promotion, observed on the payload rather than on one object: every tool declaring
    `corpus` requires it afterwards, and no tool gains a property it did not declare."""
    for entry in listing(DEFAULT_PROFILE, corpus_required=True):
        schema = entry["inputSchema"]
        if "corpus" in schema.get("properties", {}):
            assert "corpus" in schema.get("required", [])
        for name in schema.get("required", []):
            assert name in schema["properties"], f"{entry['name']} requires an absent {name}"


def test_compaction_is_what_the_plan_measured_it_to_be() -> None:
    """10:349: the strip saves tokens on three of the four and changes `ow_corpora` not at all,
    *"which is a property of the row rather than a special case"* -- it declares no advanced
    parameters. Measured with the stand-in encoder, so this runs without a table."""
    lean = {entry["name"]: tokens(entry, _words) for entry in listing(DEFAULT_PROFILE)}
    fat = {
        entry["name"]: tokens(entry, _words)
        for entry in listing(DEFAULT_PROFILE, compact_schemas=False)
    }
    assert lean["ow_corpora"] == fat["ow_corpora"]
    assert sum(lean.values()) < sum(fat.values())


# =============================================================================================
# 3. `measure()`
# =============================================================================================


def test_measure_totals_are_their_per_tool_rows() -> None:
    """The arithmetic a reviewer checks by hand. If a total were computed any other way, the file
    would carry five numbers that could disagree with each other."""
    measured = measure(_words)
    assert measured.default_compact == sum(
        tokens(entry, _words) for entry in listing(DEFAULT_PROFILE)
    )
    assert measured.default_full == sum(
        tokens(entry, _words) for entry in listing(DEFAULT_PROFILE, compact_schemas=False)
    )


def test_measure_per_tool_rows_are_the_union_over_profiles() -> None:
    """One tool object does not vary with the profile that selected it, so the per-tool block
    covers every listed tool and the 700-token cap governs a narrow Action as it governs a
    front-door one. Four rows today; eighteen when 10:807's roster renders."""
    measured = measure(_words)
    rendered = {entry["name"] for profile in PROFILES for entry in listing(profile)}
    assert set(measured.per_tool_compact) == rendered
    assert set(measured.per_tool_full) == rendered


def test_measure_reports_the_full_profile_as_unmeasured() -> None:
    """10:2593's `null` condition, as a property rather than as a constant: the totals exist, and
    `measured("full")` is what says they cover a subset."""
    measured = measure(_words)
    assert measured.measured(DEFAULT_PROFILE) is True
    assert measured.measured("full") is False
    assert measured.omitted["full"] == unpublished()


def test_measure_counts_all_four_instructions_strings() -> None:
    """The baseline freezes two of the four (10:2596). `Measurement` carries all four because the
    cap governs every string `initialize` can deliver, and D374 is the entry for the naming."""
    measured = measure(_words)
    assert set(measured.instructions_chars) == {
        profile + suffix for profile in PROFILES for suffix in ("", NO_CORPUS_SUFFIX)
    }
    for profile in PROFILES:
        assert measured.instructions_chars[profile] == len(
            instructions(profile=profile, default_corpus=True)
        )
        assert measured.instructions_chars[profile + NO_CORPUS_SUFFIX] == len(
            instructions(profile=profile, default_corpus=False)
        )


def test_the_no_corpus_variant_is_always_the_longer_one() -> None:
    """10:2596 freezes 977 and 996 in that order, and the reason is structural: the no-corpus
    variant carries an extra imperative sentence. A build where it were shorter would mean the
    variant selection had inverted."""
    measured = measure(_words)
    for profile in PROFILES:
        assert (
            measured.instructions_chars[profile + NO_CORPUS_SUFFIX]
            > measured.instructions_chars[profile]
        )


# =============================================================================================
# 4. `drift()`
# =============================================================================================


def test_drift_is_symmetric() -> None:
    """10:363 gives a magnitude and no sign, and the module reads it as both directions. A gate
    that watched only growth would pass a description accidentally emptied. D372."""
    assert drift(100, 105) == drift(100, 95)
    assert drift(856, 856) == 0.0


def test_drift_against_an_unblessed_zero_is_total() -> None:
    """A frozen zero is a baseline nobody wrote, so anything measured against it is a finding
    rather than a division by nothing."""
    assert drift(0, 0) == 0.0
    assert drift(0, 1) == 1.0


@pytest.mark.parametrize(("frozen", "now"), [(100, 104), (100, 96), (856, 890), (856, 820)])
def test_drift_inside_the_tolerance_is_silent(frozen: int, now: int) -> None:
    """Under five per cent is a description edit, and 10:365 wants those to land without a
    re-bless. The gate exists for a payload that changed shape, not for a word."""
    assert drift(frozen, now) <= DRIFT_TOLERANCE


# =============================================================================================
# 5. `findings()` -- the half that needs no tokenizer
# =============================================================================================


def test_the_committed_baseline_has_no_structural_findings() -> None:
    """The file against itself, its ceilings and its arithmetic. This is the check a machine with
    no encoding table can still run, and it is the one that catches a hand edit."""
    assert findings(_committed()) == ()


@pytest.mark.parametrize(
    ("changes", "fragment"),
    [
        ({"tokenizer": "o200k_base"}, "tokenizer is"),
        ({"recipe": "json.dumps(tool)"}, "recipe is"),
        ({"drift_tolerance": 0.2}, "drift_tolerance is"),
        ({"ceilings": {"default": 9000}}, "ceilings are"),
        ({"default_compact": 900}, "per-tool rows sum to"),
        ({"per_tool_full": {"ow_query": 411}}, "name different tools"),
    ],
)
def test_a_hand_edited_baseline_is_refused(changes: dict[str, Any], fragment: str) -> None:
    """Six ways to edit the file into something that no longer means what it says, each named. The
    ceilings row matters most: a baseline that raised its own ceiling would pass every other
    check in this file while gating nothing."""
    reported = findings(_edited(**changes))
    assert any(fragment in line for line in reported), reported


def test_a_tool_over_the_per_tool_cap_is_named() -> None:
    """700 per tool (00:713). The cap is per tool and not only on the total, because one tool that
    ate the budget would be a listing decision and not a description edit."""
    reported = findings(
        _edited(
            per_tool_compact={"ow_query": 900, "ow_open": 210, "ow_corpora": 195, "ow_add": 162},
            default_compact=1467,
        )
    )
    assert any("ow_query compact is 900 tokens, over the 700 per-tool cap" in x for x in reported)


def test_a_total_over_the_default_ceiling_is_named() -> None:
    """1,900 is L4 (10:261), and the promoted variant is checked against it too -- 10:2592 freezes
    `default_compact_corpus_required` and gives it no ceiling of its own, so it takes the one for
    the payload it is a variant of."""
    reported = findings(_edited(default_compact_corpus_required=2000))
    assert any("default_compact_corpus_required is 2000 tokens" in line for line in reported)


def test_a_null_full_total_is_not_a_finding_on_its_own() -> None:
    """10:2593 makes `null` the correct value while the roster is partial, so the structural pass
    must not object to it. Only the drift pass has the measurement that could."""
    assert findings(_edited(full_compact=None, full_full=None)) == ()


def test_a_full_total_over_its_own_ceiling_is_named() -> None:
    """4,200, which 10:831 derives from the eighteen-row roster rather than choosing."""
    reported = findings(_edited(full_compact=5000))
    assert any("full_compact is 5000 tokens, over the 4200 ceiling" in line for line in reported)


def test_an_instructions_count_over_the_cap_is_named_from_the_file_alone() -> None:
    """SV2's 1,000 characters, checked against the frozen numbers as well as the live ones, so a
    baseline blessed on a machine that was over the cap does not become the new truth."""
    reported = findings(_edited(instructions_chars={"default": 1200, "no_corpus": 996}))
    assert any("instructions default is 1200 chars" in line for line in reported)


# =============================================================================================
# 6. `findings()` -- the drift half
# =============================================================================================


def test_drift_beyond_the_tolerance_names_the_file_and_the_repair() -> None:
    """10:366's own instruction, preserved: *"if the schema legitimately needs to grow, update the
    baseline in the same PR so the CI diff makes the change reviewable."* A finding that did not
    say so would leave a reader to guess between shrinking a description and re-blessing."""
    measured = measure(_words)
    stale = _edited(default_compact=measured.default_compact * 2)
    reported = findings(stale, measured)
    assert any("re-bless serve_schema_baseline.json in the same change" in x for x in reported)


def test_a_tool_that_stopped_rendering_is_a_finding_and_not_a_silence() -> None:
    """A frozen row with no live twin is the failure mode a drift check is most likely to miss:
    nothing to compare against reads as nothing wrong."""
    measured = measure(_words)
    stale = _edited(
        per_tool_compact={**dict(measured.per_tool_compact), "ow_gone": 100},
        default_compact=sum(measured.per_tool_compact.values()) + 100,
    )
    reported = findings(stale, measured)
    assert any("ow_gone compact is frozen at 100" in line for line in reported)


def test_a_frozen_full_total_against_a_partial_roster_is_a_finding() -> None:
    """The mistake 10:2593 exists to prevent, caught from the other side: a number blessed while
    five of eighteen tools cannot render counts a subset and says so."""
    measured = measure(_words)
    reported = findings(_edited(full_compact=3000, full_full=3600), measured)
    assert any("it counts a subset" in line for line in reported)
    assert any("ow_coverage" in line for line in reported)


def test_a_null_full_total_against_a_complete_roster_asks_for_a_bless() -> None:
    """The other direction, which is the day the eighteen land: `null` stops being correct and the
    finding is an instruction rather than a failure of the surface."""
    measured = measure(_words)
    complete = Measurement(
        per_tool_compact=measured.per_tool_compact,
        per_tool_full=measured.per_tool_full,
        default_compact=measured.default_compact,
        default_full=measured.default_full,
        default_compact_corpus_required=measured.default_compact_corpus_required,
        full_compact=measured.full_compact,
        full_full=measured.full_full,
        instructions_chars=measured.instructions_chars,
        omitted=dict.fromkeys(PROFILES, ()),
    )
    reported = findings(_edited(), complete)
    assert any("full_compact is null and the full roster now renders" in x for x in reported)


def test_the_live_instructions_breach_is_reported_and_is_the_known_one() -> None:
    """The `full` profile's `instructions` string is 1,031 characters and its no-corpus variant is
    1,050, both over SV2's 1,000. That is the W7.2a entry rather than this cell's, and the two
    breaches are the only findings the live surface produces -- which is what makes the assertion
    worth writing as an equality rather than a containment."""
    measured = measure(_real_encoder())
    reported = findings(_committed(), measured)
    assert [line for line in reported if "chars, over" not in line] == []
    assert {line.split(" is ")[0] for line in reported} == {
        "instructions full",
        "instructions full_no_corpus",
    }


# =============================================================================================
# 7. `blessed()` and the committed file
# =============================================================================================


def test_blessed_round_trips_through_read_baseline(tmp_path: Path) -> None:
    """What `--bless` writes is what `--check` reads. Anything else and the first re-bless after a
    legitimate growth would fail the gate it just satisfied."""
    measured = measure(_words)
    target = tmp_path / BASELINE_NAME
    target.write_bytes(blessed(measured, release=RELEASE).encode("utf-8"))
    parsed = read_baseline(target)
    assert parsed.default_compact == measured.default_compact
    assert parsed.default_full == measured.default_full
    assert dict(parsed.per_tool_compact) == dict(measured.per_tool_compact)
    assert parsed.full_compact is None, "the roster is partial, so it must bless as null"
    assert [line for line in findings(parsed, measured) if "drifted" in line] == []


def test_blessed_writes_the_plans_key_order() -> None:
    """10:2589's block, key for key. The file is data a reviewer diffs against the plan, and a
    reordering would make that diff unreadable for no gain."""
    text = blessed(measure(_words), release=RELEASE)
    assert list(json.loads(text)) == [
        "tokenizer",
        "recipe",
        "release",
        "default_compact",
        "default_full",
        "default_compact_corpus_required",
        "full_compact",
        "full_full",
        "per_tool_compact",
        "per_tool_full",
        "instructions_chars",
        "ceilings",
        "drift_tolerance",
    ]


def test_blessed_orders_the_per_tool_rows_by_the_front_door() -> None:
    """10:2594 prints `ow_query`, `ow_open`, `ow_corpora`, `ow_add` -- the order the instructions
    string argues them in, which is not the Action-name sort artefact 1 uses. Two files, two
    readers, two orders, and each is right for its diff."""
    body = json.loads(blessed(measure(_words), release=RELEASE))
    ladder = [ACTIONS[action].mcp_name for action in FRONT_DOOR]
    assert list(body["per_tool_compact"]) == ladder
    assert list(body["per_tool_full"]) == ladder


def test_blessed_ends_with_one_newline_and_holds_no_carriage_return() -> None:
    """The house rule for every committed artefact, and the one Windows breaks silently."""
    text = blessed(measure(_words), release=RELEASE)
    assert text.endswith("}\n")
    assert "\r" not in text


def test_the_committed_file_is_where_the_module_says_it_is() -> None:
    """Three plan documents name `benchmarks/serve_schema_baseline.json` and none of 11's trees
    carries the directory, so the path is asserted here rather than assumed. D373."""
    assert baseline_path() == REPO_ROOT / BASELINE_DIR / BASELINE_NAME
    assert baseline_path().is_file()
    assert BASELINE_DIR == "benchmarks"


def test_the_committed_file_carries_the_release_the_generator_publishes() -> None:
    """`llms.RELEASE` is the one home for the version string (it binds to `pyproject.toml` by its
    own test), and a baseline blessed under a different one names a payload nobody shipped."""
    assert _committed().release == RELEASE


def test_the_committed_file_has_unix_line_endings_and_one_trailing_newline() -> None:
    """Asserted on the bytes, because a checkout that normalised them would make the byte-level
    claim untestable everywhere else."""
    raw = baseline_path().read_bytes()
    assert b"\r" not in raw
    assert raw.endswith(b"}\n")


def test_the_committed_file_carries_d316s_five_numbers() -> None:
    """D316 counted the cost of `ow_corpora`'s missing `destructiveHint` at six tokens and named
    the five figures it moves. This file is where those five now live, so the entry is discharged
    by a frozen artefact rather than by a test that re-derives the arithmetic."""
    base = _committed()
    assert base.per_tool_compact["ow_corpora"] == 195
    assert base.per_tool_full["ow_corpora"] == 195
    assert base.default_compact == 856
    assert base.default_full == 1037
    assert base.default_compact_corpus_required == 871


def test_the_promotion_costs_what_the_plan_measured() -> None:
    """10:538's *"+15 tokens"* is a delta and D316 confirmed it is unmoved by the six-token
    correction: 856 to 871. A delta is worth pinning separately from its endpoints, because it is
    the number that argues the promotion is affordable."""
    base = _committed()
    assert base.default_compact_corpus_required - base.default_compact == 15


# =============================================================================================
# 8. The tokenizer, and what it may not be
# =============================================================================================


def test_the_module_never_imports_a_tokenizer() -> None:
    """10:2585: *"a dev-only dependency and never a runtime one"*. `omniweave` is a runtime
    distribution, so the sentence is only true if no module in it resolves the name -- which is a
    property of the source and is asserted over the source."""
    source = Path(budget_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(alias.name != "tiktoken" for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module != "tiktoken"


def test_no_shipped_distribution_depends_on_a_tokenizer() -> None:
    """The other half of the same sentence, read off the metadata a wheel would carry. `tiktoken`
    belongs to the workspace root's `dev` group and to nothing that is published."""
    for manifest in sorted((REPO_ROOT / "packages").glob("*/pyproject.toml")):
        table = tomllib.loads(manifest.read_text(encoding="utf-8"))
        project = table.get("project", {})
        declared = list(project.get("dependencies", []))
        for extra in project.get("optional-dependencies", {}).values():
            declared.extend(extra)
        assert not any("tiktoken" in row for row in declared), manifest


def test_the_structural_half_needs_no_encoder_at_all() -> None:
    """The property D371 makes necessary: a machine that cannot reach the encoding table still
    fails a baseline somebody edited. Every test above this section proves it by running; this one
    states it, so the intent survives a refactor that reached for a module-level encoder."""
    assert findings(_edited(tokenizer="wrong")) != ()
    assert findings(_committed()) == ()


# =============================================================================================
# 9. SV2 itself, with the real tokenizer
# =============================================================================================


def test_sv2_the_live_payload_matches_the_frozen_baseline() -> None:
    """00:713's V01-12 and 10:362's test, which is the one check this whole module exists for.

    Skips rather than fails when `cl100k_base` cannot be resolved offline -- D371 -- so SV2 reads
    as unmeasured on a machine that cannot make the request, never as satisfied."""
    measured = measure(_real_encoder())
    reported = [line for line in findings(_committed(), measured) if "chars, over" not in line]
    assert reported == [], reported


def test_sv2_the_plans_own_table_is_reproduced_tool_for_tool() -> None:
    """10:340's four rows, three of which the shipped generator lands on the nose and the fourth of
    which D316 moved by six. Asserted against the plan's numbers directly rather than against the
    baseline, so this fails if the baseline and the plan ever drift together."""
    measured = measure(_real_encoder())
    assert dict(measured.per_tool_compact) == {
        "ow_add": 162,
        "ow_corpora": 195,
        "ow_open": 210,
        "ow_query": 289,
    }
    assert dict(measured.per_tool_full) == {
        "ow_add": 173,
        "ow_corpora": 195,
        "ow_open": 258,
        "ow_query": 411,
    }


def test_sv2_the_front_door_sits_inside_its_ceiling_with_headroom() -> None:
    """10:344's reading 1: *"the rejection of a fifth tool is therefore not a budget decision"*.
    The assertion is the headroom and not just the ceiling, because the argument that reading
    supports is the one a reviewer will reach for when refusing a tool."""
    measured = measure(_real_encoder())
    ceiling = CEILINGS["default"]
    assert measured.default_compact < ceiling
    assert ceiling - measured.default_compact > 1000, "reading 1 claims roughly 1,050 of headroom"


def test_sv2_compaction_saves_what_reading_2_says_it_saves() -> None:
    """10:349: *"`compact_schemas = true` saves 181 tokens (17.6%), not thousands."* With D316's
    six tokens landing in both columns the delta is unchanged, which is the point of measuring a
    delta separately from its endpoints."""
    measured = measure(_real_encoder())
    assert measured.default_full - measured.default_compact == 181


def test_sv2_every_tool_is_inside_the_per_tool_cap_in_both_columns() -> None:
    """The cap an operator can reach by turning compaction off, which is the column a per-tool
    budget has to hold in."""
    measured = measure(_real_encoder())
    for column in (measured.per_tool_compact, measured.per_tool_full):
        for name, value in column.items():
            assert value <= CEILINGS["per_tool"], f"{name} at {value}"


# =============================================================================================
# 10. The module's own shape
# =============================================================================================


def test_all_names_every_public_symbol_and_nothing_else() -> None:
    """Derived from the module's AST rather than from `vars()`, which would pick up the imports.
    `__all__` is what a reader greps and a drifted one is how a public name becomes private by
    accident."""
    tree = ast.parse(Path(budget_module.__file__).read_text(encoding="utf-8"))
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
    assert {name for name in defined if not name.startswith("_")} == set(budget_module.__all__)


def test_the_ceilings_constant_and_the_committed_block_agree() -> None:
    """Two homes for four integers, which is the `ANNOTATION_KEYS` pattern: the file is data and
    the constant is what a reader greps, and a test is what keeps them one number each."""
    assert dict(_committed().ceilings) == dict(CEILINGS)
    assert dict(CEILINGS) == {
        "default": 1900,
        "full": 4200,
        "per_tool": 700,
        "instructions_chars": 1000,
    }


def test_read_baseline_reports_an_unreadable_file_by_name(tmp_path: Path) -> None:
    """11 section 2.6 rule 3's shape: a named error carrying the path, never a `KeyError` or a
    bare `FileNotFoundError` from four frames down."""
    missing = tmp_path / BASELINE_NAME
    with pytest.raises(ValueError, match=r"not a readable schema baseline"):
        read_baseline(missing)
    broken = tmp_path / "broken.json"
    broken.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match=r"not the baseline object"):
        read_baseline(broken)


def test_read_baseline_turns_a_malformed_row_into_a_finding_rather_than_a_raise(
    tmp_path: Path,
) -> None:
    """Per-field tolerance, so a baseline with three defects costs one edit cycle rather than
    three. `catalog._tool()` is the same shape one distribution over."""
    target = tmp_path / BASELINE_NAME
    body: dict[str, Any] = json.loads(blessed(measure(_words), release=RELEASE))
    body["default_compact"] = "eight hundred"
    target.write_text(json.dumps(body), encoding="utf-8")
    parsed = read_baseline(target)
    assert parsed.default_compact == 0
    assert findings(parsed) != ()


def test_the_measurement_is_frozen_and_holds_no_mutable_mapping() -> None:
    """A caller that mutated a row would corrupt every later comparison in the same process, and
    the baseline is compared more than once per run."""
    measured = measure(_words)
    with pytest.raises((TypeError, AttributeError)):
        measured.per_tool_compact["ow_query"] = 1  # type: ignore[index]
    with pytest.raises(AttributeError):
        measured.default_compact = 1  # type: ignore[misc]


def test_a_stand_in_encoder_produces_a_coherent_measurement() -> None:
    """The property that makes every offline test above meaningful: the module's arithmetic holds
    for any encoder, because nothing in it inspects a token."""
    measured: Measurement = measure(_words)
    rows: Mapping[str, int] = measured.per_tool_compact
    assert all(value > 0 for value in rows.values())
    assert measured.default_compact == sum(rows.values())
