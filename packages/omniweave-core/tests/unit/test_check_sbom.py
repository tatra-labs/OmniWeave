"""`tools/check_sbom.py`: rule 4's three bounds over one SBOM, and which of them ran. D1035.

Section 7.3 rule 4's threat is a trivy scan that partially fails, emits a near-empty SBOM and
exits 0, after which cosign signs it into something that looks authoritative. So the tests that
matter are the ones that make a small document fail, and the ones that hold rule 4's floor to its
actual shape: ONE bound with two arms, the 80%-of-prior arm and the declared-direct-dependency arm
that "replaces the hard floor of 50" when no prior count can be read. Exactly one runs.
`test_only_one_arm_of_the_floor_runs_when_a_prior_count_exists` is the test that would catch them
being run together, which is the reading this module was first written against and corrected from.
At 1.0.0 no prior count exists for any of the six, so section 6.8's refusal of a check that cannot
fail is why the report must name the arm that did not apply.

**The three profile counts are MEASURED, not declared.** The test that names them
freezes 2, 10 and 12, which is what the three profiles' closures declare today. Adding a
third-party dependency to any shipped distribution moves the one that owns it, and that is the
point: the floor is supposed to track the profile. Rule 4's own "which is 2 for the minimum
profile" is what pins the first of the three and, with it, the reading in ruling 1.

Loaded by file path under a private name at module scope, as `test_check_build.py` loads its tool.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "check_sbom.py"
    spec = importlib.util.spec_from_file_location("_owgate_check_sbom", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()


def _spdx(count: int) -> dict[str, object]:
    return {"spdxVersion": "SPDX-2.3", "packages": [{"name": f"p{i}"} for i in range(count)]}


def _cdx(count: int) -> dict[str, object]:
    return {"bomFormat": "CycloneDX", "components": [{"name": f"c{i}"} for i in range(count)]}


def _run(document: dict[str, object], fmt: str, profile: str, baseline: object = None) -> object:
    return GATE.check(document=document, fmt=fmt, profile=profile, repo=REPO, baseline=baseline)


# -- the six SBOMs section 7.1 names -----------------------------------------------------------


def test_the_two_formats_and_three_profiles_are_section_7_1s_six() -> None:
    """Two formats times three install profiles is six, and the spellings are section 7.1's."""
    assert GATE.FORMATS == ("spdx", "cyclonedx")
    assert GATE.PROFILES == ("minimum", "recommended", "all-minus-vision")
    assert len(GATE.FORMATS) * len(GATE.PROFILES) == 6


def test_each_format_is_counted_from_its_own_key() -> None:
    """SPDX counts `packages`, CycloneDX counts `components`. Rule 4's floor is per format
    precisely because the two disagree, so reading one key for both would defeat it."""
    assert GATE.component_count(_spdx(7), "spdx") == 7
    assert GATE.component_count(_cdx(7), "cyclonedx") == 7
    assert GATE.component_count({"packages": [], "components": [1, 2, 3]}, "spdx") == 0


# -- ruling 1: the direct-dependency floor -----------------------------------------------------


def test_each_profile_floor_is_its_declared_third_party_count() -> None:
    """2, 10 and 12, measured 2026-11-24 over the profiles' first-party closures.

    Rule 4 states the first of these itself -- "which is 2 for the minimum profile" -- and that is
    what selects ruling 1's reading: `omniweave`'s own direct requirements are three first-party
    siblings and the closure's first-party members are four, so only "distinct third-party across
    the closure" yields 2. A new third-party dependency on a shipped distribution moves whichever
    of these three owns it, which is the floor doing its job.
    """
    assert GATE.direct_dependency_floor(REPO, "minimum") == 2
    assert GATE.direct_dependency_floor(REPO, "recommended") == 10
    assert GATE.direct_dependency_floor(REPO, "all-minus-vision") == 12


def test_the_minimum_profiles_two_are_the_two_a_release_check_resolved() -> None:
    """The minimum profile's floor is 2 because its closure declares exactly `defusedxml` and
    `firecrawl-anydoc`, which is what `pip install omniweave` resolved into a fresh 3.13 venv at
    the v1.0.0 release check. Two independent routes to the same pair."""
    roots = GATE.gate_weights.profile_roots(REPO, "minimum")
    assert roots == {"omniweave", "omniweave-core", "omniweave-ports", "omniweave-office"}


def test_a_near_empty_sbom_fails_the_direct_dependency_floor() -> None:
    """The threat rule 4 names: a partial scan that exits 0 with nothing in it."""
    result = _run(_spdx(0), "spdx", "minimum")
    assert len(result.findings) == 1
    assert "below the profile's own 2" in result.findings[0]


def test_a_document_at_the_floor_passes_and_one_below_it_does_not() -> None:
    assert _run(_spdx(2), "spdx", "minimum").findings == ()
    assert _run(_spdx(1), "spdx", "minimum").findings != ()


# -- the cap -----------------------------------------------------------------------------------


def test_the_cap_is_2000_and_fires_one_above_it() -> None:
    assert GATE.CAP == 2000
    assert _run(_cdx(2000), "cyclonedx", "recommended").findings == ()
    findings = _run(_cdx(2001), "cyclonedx", "recommended").findings
    assert len(findings) == 1
    assert "exceeds the cap of 2000" in findings[0]


# -- the previous-release floor, and ruling 3 ---------------------------------------------------


def test_the_previous_release_floor_is_eighty_percent_per_format() -> None:
    assert GATE.PREVIOUS_FRACTION == 0.8
    baseline = {("spdx", "minimum"): 40}
    assert _run(_spdx(32), "spdx", "minimum", baseline).findings == ()
    findings = _run(_spdx(31), "spdx", "minimum", baseline).findings
    assert len(findings) == 1
    assert "80% of the previous release's 40" in findings[0]


def test_a_baseline_row_for_another_format_does_not_bound_this_one() -> None:
    """Per format, not per profile pair: an SPDX row says nothing about a CycloneDX document."""
    baseline = {("spdx", "minimum"): 400}
    result = _run(_cdx(30), "cyclonedx", "minimum", baseline)
    assert result.findings == ()
    assert any("prior arm     did not apply" in line for line in result.report)


def test_only_one_arm_of_the_floor_runs_when_a_prior_count_exists() -> None:
    """Ruling 1, and the sharpest case for it: 4 components against a previous release of 5 is
    above the prior arm's bound of 4 and below `recommended`'s declared count of 10. Running both
    arms would fail this document; rule 4 makes the declared count the FALLBACK for a missing
    prior, so the prior arm alone decides and this passes."""
    result = _run(_cdx(4), "cyclonedx", "recommended", {("cyclonedx", "recommended"): 5})
    assert result.findings == ()
    assert any("no-prior arm  did not apply" in line for line in result.report)
    assert GATE.direct_dependency_floor(REPO, "recommended") == 10


def test_the_no_prior_arm_is_the_whole_floor_at_a_first_release() -> None:
    """Ruling 4 and section 6.8. At 1.0.0 the prior arm has no input, so the report names the arm
    that ran with its number and prints the other as having not applied -- a reader can tell a
    two-bound pass from a three-bound one."""
    result = _run(_spdx(31), "spdx", "minimum", None)
    assert result.findings == ()
    ran = [line for line in result.report if "  ran" in line]
    assert len(ran) == 2, result.report
    assert any("cap" in line for line in ran)
    assert any("no-prior arm  2  ran" in line for line in ran)
    absent = [line for line in result.report if "did not apply" in line]
    assert len(absent) == 1
    assert "no previous stable release" in absent[0]


def test_both_arms_and_the_cap_name_themselves_in_the_report() -> None:
    """Whichever arm runs, all three labels appear, so the step summary is readable either way."""
    for baseline in (None, {("spdx", "minimum"): 50}):
        report = "\n".join(_run(_spdx(50), "spdx", "minimum", baseline).report)
        assert "cap" in report
        assert "floor, prior arm" in report
        assert "floor, no-prior arm" in report


# -- a malformed document is exit 2, not a small one ---------------------------------------------


def test_an_absent_component_array_is_malformed_and_not_empty() -> None:
    """Zero components is a finding; no `packages` key at all is a document this check cannot
    judge, and the caller turns that into exit 2."""
    with pytest.raises(ValueError, match="malformed, not empty"):
        GATE.component_count({"spdxVersion": "SPDX-2.3"}, "spdx")


def test_a_component_array_that_is_not_a_list_raises() -> None:
    """A dict where an array belongs is a type contract broken, so TypeError rather than
    ValueError -- and `main()` catches both, because either way the check did not run."""
    with pytest.raises(TypeError, match="not a list"):
        GATE.component_count({"packages": {"name": "p"}}, "spdx")


def test_an_unknown_format_or_profile_raises() -> None:
    with pytest.raises(ValueError, match="unknown format"):
        GATE.component_count(_spdx(3), "spdx-json")
    with pytest.raises(ValueError, match="unknown profile"):
        GATE.direct_dependency_floor(REPO, "gpu-server")


# -- the baseline file ---------------------------------------------------------------------------


def test_a_missing_baseline_file_is_empty_and_not_an_error() -> None:
    assert GATE.load_baseline(REPO / "tools" / "no-such-baseline.toml") == {}


def test_the_baseline_round_trips_through_its_own_renderer(tmp_path: Path) -> None:
    """Ruling 4: a release writes this file, so what `--write-baseline` emits must be what
    `load_baseline` reads back."""
    rows = {
        ("spdx", "minimum"): 31,
        ("spdx", "all-minus-vision"): 402,
        ("cyclonedx", "recommended"): 118,
    }
    path = tmp_path / "sbom_baseline.toml"
    path.write_text(GATE._render_baseline(rows), encoding="utf-8")
    assert GATE.load_baseline(path) == rows


def test_the_baseline_renderer_keeps_section_7_1s_profile_order() -> None:
    rows = {("spdx", p): 10 for p in ("all-minus-vision", "recommended", "minimum")}
    rendered = GATE._render_baseline(rows)
    positions = [rendered.index(f'"{profile}"') for profile in GATE.PROFILES]
    assert positions == sorted(positions), rendered


# -- main() and its three exit codes -------------------------------------------------------------


def test_main_returns_zero_on_a_healthy_document(tmp_path: Path) -> None:
    sbom = tmp_path / "sbom-spdx-minimum.json"
    sbom.write_text(json.dumps(_spdx(31)), encoding="utf-8")
    code = GATE.main(
        [
            "--sbom",
            str(sbom),
            "--format",
            "spdx",
            "--profile",
            "minimum",
            "--repo",
            str(REPO),
            "--baseline",
            str(tmp_path / "absent.toml"),
        ]
    )
    assert code == 0


def test_main_returns_one_when_a_bound_is_violated(tmp_path: Path) -> None:
    sbom = tmp_path / "sbom-spdx-minimum.json"
    sbom.write_text(json.dumps(_spdx(0)), encoding="utf-8")
    code = GATE.main(
        [
            "--sbom",
            str(sbom),
            "--format",
            "spdx",
            "--profile",
            "minimum",
            "--repo",
            str(REPO),
            "--baseline",
            str(tmp_path / "absent.toml"),
        ]
    )
    assert code == 1


@pytest.mark.parametrize(
    "payload",
    ["", "not json at all", '["a", "list"]'],
    ids=["empty", "not-json", "not-an-object"],
)
def test_main_returns_two_when_the_check_could_not_run(tmp_path: Path, payload: str) -> None:
    sbom = tmp_path / "sbom.json"
    sbom.write_text(payload, encoding="utf-8")
    code = GATE.main(
        [
            "--sbom",
            str(sbom),
            "--format",
            "spdx",
            "--profile",
            "minimum",
            "--repo",
            str(REPO),
            "--baseline",
            str(tmp_path / "absent.toml"),
        ]
    )
    assert code == 2


def test_main_returns_two_when_the_sbom_does_not_exist(tmp_path: Path) -> None:
    code = GATE.main(
        [
            "--sbom",
            str(tmp_path / "never-written.json"),
            "--format",
            "spdx",
            "--profile",
            "minimum",
            "--repo",
            str(REPO),
        ]
    )
    assert code == 2


def test_write_baseline_records_the_count_it_just_passed(tmp_path: Path) -> None:
    sbom = tmp_path / "sbom-cyclonedx-recommended.json"
    sbom.write_text(json.dumps(_cdx(118)), encoding="utf-8")
    baseline = tmp_path / "sbom_baseline.toml"
    code = GATE.main(
        [
            "--sbom",
            str(sbom),
            "--format",
            "cyclonedx",
            "--profile",
            "recommended",
            "--repo",
            str(REPO),
            "--baseline",
            str(baseline),
            "--write-baseline",
        ]
    )
    assert code == 0
    assert GATE.load_baseline(baseline) == {("cyclonedx", "recommended"): 118}


def test_write_baseline_does_not_run_when_a_bound_failed(tmp_path: Path) -> None:
    """A failing SBOM must not become the number the next release is measured against."""
    sbom = tmp_path / "sbom-spdx-minimum.json"
    sbom.write_text(json.dumps(_spdx(0)), encoding="utf-8")
    baseline = tmp_path / "sbom_baseline.toml"
    code = GATE.main(
        [
            "--sbom",
            str(sbom),
            "--format",
            "spdx",
            "--profile",
            "minimum",
            "--repo",
            str(REPO),
            "--baseline",
            str(baseline),
            "--write-baseline",
        ]
    )
    assert code == 1
    assert not baseline.exists()


def test_the_committed_baseline_is_the_renderers_own_empty_output() -> None:
    """`tools/sbom_baseline.toml` exists and holds no rows, which is the truth before the first
    release that publishes SBOMs.

    It is byte-for-byte what `_render_baseline({})` emits, so the first `--write-baseline` of a
    release adds rows to a file of the shape it already has rather than replacing a hand-written
    one. The equality is also the guard ruling 5 wants: a hand-edited baseline fails here before
    it can lower a floor.
    """
    committed = GATE.BASELINE
    assert committed.exists(), committed
    assert committed.read_text(encoding="utf-8") == GATE._render_baseline({})
    assert GATE.load_baseline(committed) == {}
