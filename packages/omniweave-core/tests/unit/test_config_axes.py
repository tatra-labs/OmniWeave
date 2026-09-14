"""G18: `tools/config_axes.toml` is generated, and it covers the shipped example EXACTLY.

Two properties, and the second is the one W1.4's estimation basis singles out. The first is the
byte diff: the file is T-GENERATED, so a hand edit is a gate failure and `\\r\\n` can never be
emitted from a Windows checkout. The second is the exact-coverage assertion -- "the assertion that
was missing while sixteen shipped config keys matched no pattern at all" (16-roadmap.md W1.4) --
which 02-architecture.md section 8.3 states as three distinct failure conditions:

  * a key no pattern matches (UNCLASSIFIED: "an unclassified key fails CI and is treated at
    runtime as `semantic`: fail expensive, never wrong"),
  * a key TWO GLOBS match ("a G18 failure, not a precedence puzzle"), and
  * a pattern no key matches, because "covers ... EXACTLY -- neither over nor under" is
    bidirectional (ADR-3: "a pattern matching no key fails the same 'neither over' clause").

Every one is tested in BOTH directions -- a fixture that must fail and a fixture that must pass --
because a coverage assertion that only ever sees covered input is the assertion that was missing.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from omniweave_core.config import (
    KEYS,
    REQUIRED,
    ConfigError,
    ConfigKey,
    Inherit,
    resolve_key,
    split_key,
)

REPO = Path(__file__).resolve().parents[4]
SHIPPED = Path(__file__).parent / "shipped_config_example.toml"

# `tools/` is a script directory and not a distribution, so it is not importable by installation.
# Prepending it is the same act `uv run tools/gate_config_axes.py` performs implicitly through
# `sys.path[0]`; the two imports below are what E402 flags and what makes the gate testable at all.
sys.path.insert(0, str(REPO / "tools"))

import gate_config_axes  # noqa: E402
import gen_config_axes  # noqa: E402

AxisRow = gate_config_axes.AxisRow

# The fifteen declared keys the shipped configuration does not instantiate. They are real keys
# with real defaults -- 18-api-sketch.md section 4 carries a row for ten, ADR-3 decision 3 adds
# `[drivers.resolve]`, and 08-runtime.md:2598-2606's "New keys this document introduces" adds the
# last four -- so the gap is in the fixture, not in the registry. The ROOT
# `omniweave.toml.example` carries all fifteen already; this fixture quotes charter.md:462-670,
# which predates every one of them.
#
# The four `[runtime]` rows arrive one cell at a time, by the rule D149 set: a key is declared by
# the cell that READS it, never by the cell that notices it is missing. `max_sequence_units` came
# with W4.7's Sequence claim; `shutdown_grace_ms`, `deferred_sweep_ms` and `stall_poll_ms` come
# with W4.2's loop, which is the one consumer of all three.
OWED_BY_THE_EXAMPLE = frozenset(
    {
        "drivers.resolve.*",
        "retrieval.event_log_query",
        "retrieval.budget.hydration_reserve_ms",
        "serve.add_deadline_ms",
        "serve.max_sessions",
        "serve.read_timeout_ms",
        "serve.allowed_origins",
        "serve.allowed_hosts",
        "observe.level",
        "observe.redact",
        "observe.retain_days",
        "runtime.max_sequence_units",
        "runtime.shutdown_grace_ms",
        "runtime.deferred_sweep_ms",
        "runtime.stall_poll_ms",
    }
)


def _shipped_document() -> dict[str, object]:
    return tomllib.loads(SHIPPED.read_text(encoding="utf-8"))


def _committed_rows() -> tuple[AxisRow, ...]:
    rows, findings = gate_config_axes.read_rows(gen_config_axes.OUTPUT_PATH.read_text("utf-8"))
    assert findings == (), findings
    return rows


def _codes(findings: tuple[gate_config_axes.Finding, ...]) -> list[str]:
    return [f.code for f in findings]


# ---------------------------------------------------------------------------------------------
# GENERATED MEANS GENERATED: the byte diff, and the line endings it would otherwise hide
# ---------------------------------------------------------------------------------------------


def test_the_committed_file_is_byte_identical_to_the_generator() -> None:
    assert gen_config_axes.OUTPUT_PATH.exists(), "tools/config_axes.toml is committed"
    assert gen_config_axes.OUTPUT_PATH.read_bytes() == gen_config_axes.render().encode("utf-8")


def test_the_generator_never_emits_a_carriage_return(tmp_path: Path, monkeypatch) -> None:
    """A Windows checkout that translated the endings would fail the byte diff on Linux CI for a
    reason with nothing to do with configuration. `main()` writes BYTES, so text-mode translation
    cannot reach it -- asserted against a real write, not against `render()` alone."""
    target = tmp_path / "config_axes.toml"
    monkeypatch.setattr(gen_config_axes, "OUTPUT_PATH", target)
    assert gen_config_axes.main([]) == 0
    written = target.read_bytes()
    assert b"\r" not in written
    assert written.endswith(b"\n")
    assert written == gen_config_axes.render().encode("utf-8")
    assert b"\r" not in gen_config_axes.OUTPUT_PATH.read_bytes()


def test_render_is_deterministic() -> None:
    assert gen_config_axes.render() == gen_config_axes.render()


def test_check_accepts_the_committed_file(capsys: pytest.CaptureFixture[str]) -> None:
    assert gen_config_axes.main(["--check"]) == 0
    assert "matches the generator" in capsys.readouterr().out


def test_check_refuses_an_edited_file(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "config_axes.toml"
    target.write_bytes(gen_config_axes.render().encode("utf-8") + b'"x" = "Y"\n')
    monkeypatch.setattr(gen_config_axes, "OUTPUT_PATH", target)
    assert gen_config_axes.main(["--check"]) == 1
    assert "gen_config_axes.py" in capsys.readouterr().out


def test_check_refuses_a_missing_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gen_config_axes, "OUTPUT_PATH", tmp_path / "absent.toml")
    assert gen_config_axes.main(["--check"]) == 1


def test_an_unknown_flag_is_neither_a_write_nor_a_pass(tmp_path: Path, monkeypatch) -> None:
    """`--bless` and `--force` do not exist here: this file has no blessing ceremony, because its
    input is a declaration site rather than an observation."""
    target = tmp_path / "config_axes.toml"
    monkeypatch.setattr(gen_config_axes, "OUTPUT_PATH", target)
    assert gen_config_axes.main(["--bless"]) == 2
    assert not target.exists()


# ---------------------------------------------------------------------------------------------
# The file's CONTENT, not its shape. A 1,810-line document once truncated to 491 and passed every
# structural check on this project, so the load-bearing sentences are asserted by their text.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        "AN UNCLASSIFIED KEY FAILS CI and is treated at runtime as `semantic`",
        "`*`  matches EXACTLY ONE key segment.",
        "`**` matches ONE OR MORE segments.",
        "An EXPLICIT key beats a glob. TWO GLOBS matching one key is a G18 FAILURE, not a "
        "precedence",
        "EXACTLY — neither over nor under",
        "An INLINE TABLE is ONE key",
        "A key quoted because it holds dots is ONE",
        "A key is `semantic` IFF changing it can change the CONTENT of a produced row",
        "A KEY WITH NO TWIN\n# FAILS CI",
    ],
)
def test_the_header_states_the_rule_a_reader_must_apply(sentence: str) -> None:
    assert sentence in gen_config_axes.OUTPUT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# The file reproduces the registry: one row per declaration site, both facts, no third state
# ---------------------------------------------------------------------------------------------


def test_every_declared_key_appears_under_exactly_one_axis() -> None:
    rows = _committed_rows()
    assert len(rows) == len(KEYS)
    assert {row.name: row.axis for row in rows} == {name: k.axis for name, k in KEYS.items()}


def test_the_two_lists_are_disjoint_and_exhaustive() -> None:
    """There is no third state -- which is what makes the coverage assertion decidable at all
    (glossary.md's `ConfigAxis` row)."""
    document = tomllib.loads(gen_config_axes.OUTPUT_PATH.read_text(encoding="utf-8"))
    semantic = set(document["semantic"]["keys"])
    operational = set(document["operational"]["keys"])
    assert semantic & operational == set()
    assert semantic | operational == set(KEYS)
    assert len(document["semantic"]["keys"]) == len(semantic)
    assert len(document["operational"]["keys"]) == len(operational)


def test_every_pattern_carries_its_declared_twin() -> None:
    """02-architecture.md section 8.2: the twin is emitted here, "the same G18 byte diff therefore
    covers both, and a key with no twin fails CI"."""
    document = tomllib.loads(gen_config_axes.OUTPUT_PATH.read_text(encoding="utf-8"))
    assert document["env"] == {name: spec.env for name, spec in KEYS.items()}
    assert gate_config_axes.check_twins(_committed_rows()) == ()


def test_the_one_twin_no_mechanical_rule_produces_is_in_the_file() -> None:
    """`[serve] listed` -> `OMNIWEAVE_MCP_LISTED` is the whole reason the twin is DECLARED rather
    than DERIVED, so it is the row whose presence proves the file carries declarations."""
    document = tomllib.loads(gen_config_axes.OUTPUT_PATH.read_text(encoding="utf-8"))
    assert document["env"]["serve.listed"] == "OMNIWEAVE_MCP_LISTED"


def test_a_glob_pattern_twin_carries_one_slot_per_glob_segment() -> None:
    globs = [row for row in _committed_rows() if row.is_glob]
    assert {row.name for row in globs} == {
        "corpora.*.path",
        "corpora.*.source",
        "drivers.resolve.*",
        "drivers.*.config",
        "services.*.model_id",
        "services.*.model_revision",
        "services.*.endpoint",
        "services.*.autostart",
        "services.*.capacity",
        "services.*.batch_wait_ms",
        "services.*.max_batch",
        "services.*.keep_alive_s",
    }
    for row in globs:
        assert row.env_glob_count == row.glob_count == 1, row


def test_a_missing_twin_and_a_mis_arity_twin_are_both_findings() -> None:
    rows = (
        AxisRow(name="a.b", axis="semantic", env=""),
        AxisRow(name="c.*.d", axis="operational", env="OMNIWEAVE_C_D"),
        AxisRow(name="e.f", axis="operational", env="OMNIWEAVE_E_F"),
    )
    assert _codes(gate_config_axes.check_twins(rows)) == [
        gate_config_axes.TWIN_MISSING,
        gate_config_axes.TWIN_ARITY,
    ]


# ---------------------------------------------------------------------------------------------
# GLOB ARITY. `*` is exactly one segment, `**` is one or more -- so coverage can be evaluated
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "key", "hit"),
    [
        ("drivers.*.config", 'drivers."parse.pdf.pdfium".config', True),
        ("drivers.*.config", "drivers.a.b.config", False),  # `*` is EXACTLY one segment
        ("drivers.*.config", "drivers.config", False),  # and never zero
        ("runtime.**", "runtime.claim.batch", True),
        ("runtime.**", "runtime.plan_batch", True),
        ("runtime.**", "runtime", False),  # `**` is ONE OR MORE, never zero
        ("limits.**", "limits.max_entry_bytes", True),
        ("corpora.*.path", "corpora.handbook.path", True),
        ("corpora.*.path", "corpora.path", False),
    ],
)
def test_glob_arity_is_the_charter_header_block(pattern: str, key: str, hit: bool) -> None:
    assert AxisRow(name=pattern, axis="operational", env="OMNIWEAVE_X").matches(key) is hit


def test_a_segment_holding_a_dot_is_one_segment() -> None:
    """ADR-3 decision 3: `[drivers."parse.pdf.pdfium"] config` matches `drivers.*.config`. If the
    quoted key split on `.` instead, the shipped example would be 131 keys with fourteen uncovered
    -- which is the reading ADR-3 measured and rejected."""
    assert split_key('drivers."parse.pdf.pdfium".config') == (
        "drivers",
        "parse.pdf.pdfium",
        "config",
    )
    document = {"drivers": {"parse.pdf.pdfium": {"config": {"dpi": 192}}}}
    rows = (AxisRow(name="drivers.*.config", axis="semantic", env="OMNIWEAVE_DRIVERS_*_CONFIG"),)
    keys, findings = gate_config_axes.enumerate_keys(document, rows)
    assert keys == ('drivers."parse.pdf.pdfium".config',)
    assert findings == ()


# ---------------------------------------------------------------------------------------------
# KEY ENUMERATION: an inline table is ONE key. The answer flips on it (ADR-3)
# ---------------------------------------------------------------------------------------------


def test_an_inline_table_is_one_key_when_a_pattern_names_it() -> None:
    document = {"drivers": {"max_workers": {"free": 4, "local_compute": 4, "billed_api": 8}}}
    rows = (
        AxisRow(
            name="drivers.max_workers", axis="operational", env="OMNIWEAVE_DRIVERS_MAX_WORKERS"
        ),
    )
    keys, findings = gate_config_axes.enumerate_keys(document, rows)
    assert keys == ("drivers.max_workers",)
    assert findings == ()


def test_the_same_table_is_three_keys_when_the_patterns_name_the_leaves() -> None:
    """The document is identical; only the pattern list moved. That is precisely why the rule has
    to be stated in the file rather than inferred from TOML."""
    document = {"drivers": {"max_workers": {"free": 4, "local_compute": 4, "billed_api": 8}}}
    rows = tuple(
        AxisRow(name=f"drivers.max_workers.{leaf}", axis="operational", env="OMNIWEAVE_X")
        for leaf in ("free", "local_compute", "billed_api")
    )
    keys, findings = gate_config_axes.enumerate_keys(document, rows)
    assert set(keys) == {
        "drivers.max_workers.free",
        "drivers.max_workers.local_compute",
        "drivers.max_workers.billed_api",
    }
    assert findings == ()


# ---------------------------------------------------------------------------------------------
# FAILURE 1 -- an unclassified key. Zero patterns matching is a failure
# ---------------------------------------------------------------------------------------------


def test_a_key_no_pattern_matches_is_named_as_a_g18_failure() -> None:
    document = {"retrieval": {"vectors": "off", "reranker": "cohere"}}
    rows = (
        AxisRow(name="retrieval.vectors", axis="operational", env="OMNIWEAVE_RETRIEVAL_VECTORS"),
    )
    _, findings = gate_config_axes.enumerate_keys(document, rows)
    assert _codes(findings) == [gate_config_axes.UNCLASSIFIED_KEY]
    assert findings[0].subject == "retrieval.reranker"
    assert "fail expensive, never wrong" in findings[0].detail
    assert "omniweave_core.config" in findings[0].fix


def test_a_whole_unknown_section_is_named_once_and_not_swallowed() -> None:
    document = {"telemetry": {"sink": "s3", "region": "eu"}}
    rows = (AxisRow(name="observe.sinks", axis="operational", env="OMNIWEAVE_OBSERVE_SINKS"),)
    keys, findings = gate_config_axes.enumerate_keys(document, rows)
    assert keys == ("telemetry",)
    assert _codes(findings) == [gate_config_axes.UNCLASSIFIED_KEY]


def test_the_shipped_configuration_has_no_unclassified_key() -> None:
    """The direction that was broken: sixteen shipped keys matched no pattern at all."""
    _, findings = gate_config_axes.enumerate_keys(_shipped_document(), _committed_rows())
    assert findings == ()


# ---------------------------------------------------------------------------------------------
# FAILURE 2 -- two globs on one key. A failure, not a precedence puzzle
# ---------------------------------------------------------------------------------------------


def test_two_globs_matching_one_key_is_a_failure() -> None:
    document = {"services": {"vlm": {"model_id": "allenai/olmOCR-7B"}}}
    rows = (
        AxisRow(name="services.*.model_id", axis="semantic", env="OMNIWEAVE_SERVICES_*_MODEL_ID"),
        AxisRow(name="services.vlm.*", axis="operational", env="OMNIWEAVE_SERVICES_VLM_*"),
    )
    _, findings = gate_config_axes.enumerate_keys(document, rows)
    assert _codes(findings) == [gate_config_axes.TWO_GLOBS]
    assert findings[0].subject == "services.vlm.model_id"
    assert "not a precedence puzzle" in findings[0].detail
    assert findings[0].fix == (
        "make one pattern in tools/config_axes.toml explicit so exactly one matches"
    )


def test_the_gate_and_the_loader_print_the_same_fix_for_the_same_failure() -> None:
    """INV-21, made checkable. `config.py:966` already emits this fix at RUNTIME; this module is
    the CI half of one property, so an operator must read ONE sentence in both places. If either
    side is reworded alone, the two halves have quietly become two rules."""
    rows = (
        AxisRow(name="services.*.model_id", axis="semantic", env="OMNIWEAVE_SERVICES_*_MODEL_ID"),
        AxisRow(name="services.vlm.*", axis="operational", env="OMNIWEAVE_SERVICES_VLM_*"),
    )
    _, findings = gate_config_axes.enumerate_keys({"services": {"vlm": {"model_id": "x"}}}, rows)
    declarations = tuple(
        ConfigKey(name=row.name, kind="str", default="", axis=row.axis, env=row.env) for row in rows
    )
    with pytest.raises(ConfigError) as raised:
        resolve_key("services.vlm.model_id", keys=declarations)
    assert findings[0].fix == raised.value.fix
    assert "not a precedence puzzle" in str(raised.value)


def test_an_explicit_key_beats_a_glob_and_is_not_a_double_match() -> None:
    """ "An EXPLICIT key beats a glob" -- so one explicit plus one glob is resolved, not a failure.
    Only TWO GLOBS is the unresolvable case."""
    document = {"drivers": {"enabled": ["parse.pdf.pdfium"]}}
    rows = (
        AxisRow(name="drivers.enabled", axis="operational", env="OMNIWEAVE_DRIVERS_ENABLED"),
        AxisRow(name="drivers.*", axis="operational", env="OMNIWEAVE_DRIVERS_*"),
    )
    keys, findings = gate_config_axes.enumerate_keys(document, rows)
    assert keys == ("drivers.enabled",)
    assert findings == ()


def test_the_committed_patterns_double_match_nothing_in_the_shipped_configuration() -> None:
    rows = _committed_rows()
    _, findings = gate_config_axes.enumerate_keys(_shipped_document(), rows)
    assert [f for f in findings if f.code == gate_config_axes.TWO_GLOBS] == []


@pytest.mark.parametrize("name", sorted(n for n, k in KEYS.items() if not k.is_glob))
def test_every_concrete_declared_key_is_matched_by_exactly_one_committed_pattern(name: str) -> None:
    hits = [row for row in _committed_rows() if row.matches(name)]
    assert [row.name for row in hits] == [name], hits


# ---------------------------------------------------------------------------------------------
# FAILURE 3 -- a pattern no key matches. "EXACTLY" is bidirectional
# ---------------------------------------------------------------------------------------------


def test_a_pattern_matching_no_key_is_a_failure() -> None:
    document = {"cache": {"recipe": 1}}
    rows = (
        AxisRow(name="cache.recipe", axis="semantic", env="OMNIWEAVE_CACHE_RECIPE"),
        AxisRow(name="cache.min_free_bytes", axis="operational", env="OMNIWEAVE_CACHE_MIN_FREE"),
    )
    findings = gate_config_axes.check_coverage(document, rows)
    assert _codes(findings) == [gate_config_axes.DEAD_PATTERN]
    assert findings[0].subject == "cache.min_free_bytes"
    assert "neither over nor under" in findings[0].detail


def test_exact_coverage_reports_nothing_when_it_is_exact() -> None:
    document = {"cache": {"recipe": 1, "min_free_bytes": 5368709120}}
    rows = (
        AxisRow(name="cache.recipe", axis="semantic", env="OMNIWEAVE_CACHE_RECIPE"),
        AxisRow(name="cache.min_free_bytes", axis="operational", env="OMNIWEAVE_CACHE_MIN_FREE"),
    )
    assert gate_config_axes.check_coverage(document, rows) == ()


def test_the_shipped_fixture_leaves_exactly_the_owed_lines_uninstantiated() -> None:
    """The `over` direction cannot pass until the root artefact `omniweave.toml.example` is
    committed with a line per key: the test fixture beside this file quotes charter.md:462-670 and
    that block predates fifteen declared keys. Each name in `OWED_BY_THE_EXAMPLE` has a row in
    18-api-sketch.md section 4, in ADR-3 decision 3, or in 08-runtime.md:2598-2606, so the debt is
    in the example and not in the registry. ADR-3 states the consequence: "adding a config key now
    costs a pattern AND a line in `omniweave.toml.example`"."""
    findings = gate_config_axes.check_coverage(_shipped_document(), _committed_rows())
    assert {f.subject for f in findings} == set(OWED_BY_THE_EXAMPLE)
    assert set(_codes(findings)) == {gate_config_axes.DEAD_PATTERN}
    assert set(KEYS) >= OWED_BY_THE_EXAMPLE


# ---------------------------------------------------------------------------------------------
# The axis file itself: a malformed or self-contradictory register is reported, never raised
# ---------------------------------------------------------------------------------------------


def test_a_key_declared_under_both_axes_is_a_finding_not_a_silent_win() -> None:
    text = (
        '[semantic]\nkeys = ["a.b"]\n[operational]\nkeys = ["a.b"]\n'
        '[env]\n"a.b" = "OMNIWEAVE_A_B"\n'
    )
    rows, findings = gate_config_axes.read_rows(text)
    assert _codes(findings) == [gate_config_axes.DUPLICATE_PATTERN]
    assert [row.axis for row in rows] == ["semantic"]


def test_a_malformed_axis_file_is_a_finding_not_a_traceback() -> None:
    rows, findings = gate_config_axes.read_rows("[semantic]\nkeys = [oops\n")
    assert rows == ()
    assert _codes(findings) == [gate_config_axes.MALFORMED]


@pytest.mark.parametrize(
    "text",
    [
        '[semantic]\nkeys = "a.b"\n[env]\n"a.b" = "X"\n',
        '[semantic]\nkeys = [1]\n[env]\n"a.b" = "X"\n',
        'env = 3\n[semantic]\nkeys = ["a.b"]\n',
    ],
)
def test_a_wrongly_shaped_axis_file_is_reported_by_shape(text: str) -> None:
    _, findings = gate_config_axes.read_rows(text)
    assert gate_config_axes.MALFORMED in _codes(findings)


def test_every_finding_names_the_command_or_edit_that_clears_it() -> None:
    text = '[semantic]\nkeys = ["a.*.b", "dead.key"]\n[env]\n"a.*.b" = "OMNIWEAVE_A_*_B"\n'
    rows, findings = gate_config_axes.read_rows(text)
    all_findings = (
        *findings,
        *gate_config_axes.check_twins(rows),
        *gate_config_axes.check_coverage({"a": {"c": {"b": 1}}, "x": 1}, rows),
    )
    assert all_findings
    for finding in all_findings:
        assert finding.fix.strip(), finding
        assert finding.detail.strip(), finding
        assert finding.render().startswith("G18 ")


# ---------------------------------------------------------------------------------------------
# `check()` -- all of G18 over three strings, and the gate's own entry point
# ---------------------------------------------------------------------------------------------


_SELF_CONSISTENT = (
    '[semantic]\nkeys = ["cache.recipe"]\n'
    '[operational]\nkeys = ["roots.source"]\n'
    '[env]\n"cache.recipe" = "OMNIWEAVE_CACHE_RECIPE"\n"roots.source" = "OMNIWEAVE_ROOTS_SOURCE"\n'
)
_SELF_CONSISTENT_EXAMPLE = '[roots]\nsource = "."\n[cache]\nrecipe = 1\n'


def test_check_is_silent_on_a_consistent_triple() -> None:
    assert (
        gate_config_axes.check(_SELF_CONSISTENT, _SELF_CONSISTENT_EXAMPLE, _SELF_CONSISTENT) == ()
    )


def test_check_reports_the_byte_diff_first() -> None:
    findings = gate_config_axes.check(
        _SELF_CONSISTENT, _SELF_CONSISTENT_EXAMPLE, _SELF_CONSISTENT + "# drifted\n"
    )
    assert _codes(findings) == [gate_config_axes.BYTE_DIFF]
    assert "T-GENERATED" in findings[0].detail


def test_check_reports_a_malformed_example_without_raising() -> None:
    findings = gate_config_axes.check(_SELF_CONSISTENT, "[roots\n", _SELF_CONSISTENT)
    assert _codes(findings) == [gate_config_axes.MALFORMED]


def test_check_finds_all_three_conditions_in_one_run() -> None:
    """G18 must name every offender in one CI run rather than the first one it trips over."""
    axes = (
        '[semantic]\nkeys = ["a.*.b", "a.c.*"]\n'
        '[operational]\nkeys = ["never.instantiated"]\n'
        '[env]\n"a.*.b" = "OMNIWEAVE_A_*_B"\n"a.c.*" = "OMNIWEAVE_A_C_*"\n'
        '"never.instantiated" = "OMNIWEAVE_NEVER_INSTANTIATED"\n'
    )
    example = "[a.c]\nb = 1\n[unknown]\nkey = 2\n"
    findings = gate_config_axes.check(axes, example, axes)
    assert set(_codes(findings)) == {
        gate_config_axes.TWO_GLOBS,
        gate_config_axes.UNCLASSIFIED_KEY,
        gate_config_axes.DEAD_PATTERN,
    }


def test_the_gate_refuses_to_evaluate_coverage_without_an_example(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate that quietly passed when its subject was absent would be the same silence G18 exists
    to end, so the missing example is a named failure with the artefact that clears it."""
    assert gate_config_axes.main(["--example", str(tmp_path / "absent.toml")]) == 1
    out = capsys.readouterr().out
    assert gate_config_axes.EXAMPLE_MISSING in out
    assert "omniweave.toml.example" in out


def test_the_gate_rejects_arguments_it_does_not_define(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gate_config_axes.main(["--fix"]) == 1
    assert "usage:" in capsys.readouterr().out


def test_the_gate_exits_non_zero_on_the_shipped_fixture_and_says_why(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gate_config_axes.main(["--example", str(SHIPPED)]) == 1
    out = capsys.readouterr().out
    assert gate_config_axes.DEAD_PATTERN in out
    assert f"G18 FAILED: {len(OWED_BY_THE_EXAMPLE)} finding(s)" in out


# ---------------------------------------------------------------------------------------------
# Property: over any subset of the shipped configuration, enumeration is the subset itself
# ---------------------------------------------------------------------------------------------

_CONCRETE_SHIPPED = sorted(
    name
    for name, spec in KEYS.items()
    if not spec.is_glob and not isinstance(spec.default, (type(REQUIRED), Inherit))
)
_TABLE_VALUED = frozenset(
    name for name, spec in KEYS.items() if spec.kind in ("table", "matrix") and not spec.is_glob
)


def _document_of(names: frozenset[str]) -> dict[str, object]:
    """Build the TOML document those keys would be written as, tables inline."""
    root: dict[str, object] = {}
    for name in sorted(names):
        node = root
        segments = split_key(name)
        for segment in segments[:-1]:
            node = node.setdefault(segment, {})  # type: ignore[assignment]
        node[segments[-1]] = {"free": 1} if name in _TABLE_VALUED else 1
    return root


@settings(max_examples=200, deadline=None)
@given(st.frozensets(st.sampled_from(_CONCRETE_SHIPPED), min_size=1, max_size=40))
def test_any_subset_of_declared_keys_enumerates_to_itself(names: frozenset[str]) -> None:
    """The adversarial part is the table-valued keys: `drivers.max_workers`, `cache.gc`,
    `observe.sample`, `runtime.claim.batch`, `budget.max_inflight`, `retrieval.budget.channel_ms`,
    `drivers.crash_quarantine` and `serve.packing.tier` are mappings in the document, so a walk
    driven by the DOCUMENT would descend into them and produce keys no pattern covers."""
    rows = _committed_rows()
    keys, findings = gate_config_axes.enumerate_keys(_document_of(names), rows)
    assert set(keys) == set(names)
    assert findings == ()


# ---------------------------------------------------------------------------------------------
# The emitted classification is charter.md's axis table, refined -- not a second opinion of it
# ---------------------------------------------------------------------------------------------

# charter.md's `tools/config_axes.toml` `[semantic]` and `[operational]` blocks, transcribed one
# pattern per line, with ADR-1's `[retrieval.vec] max_blocks` -> `max_segments` rename applied
# (ADR-3, "Ordering": consequence 3 must be written against `retrieval.vec.max_segments`).
CHARTER_SEMANTIC = (
    "limits.**",
    "cache.recipe",
    "drivers.*.config",
    "targets.*.*",
    "graph.etypes",
    "graph.segment_target_tokens",
    "graph.llm_coverage_floor",
    "graph.max_items_per_segment",
    "services.*.model_id",
    "services.*.model_revision",
    "retrieval.vec.model_key",
)
CHARTER_OPERATIONAL = (
    "schema",
    "roots.source",
    "roots.output",
    "roots.cache",
    "corpora.*.*",
    "store.**",
    "runtime.**",
    "budget.**",
    "observe.**",
    "serve.**",
    "cache.gc",
    "cache.max_bytes.*",
    "cache.min_free_bytes",
    "retrieval.vectors",
    "retrieval.scorer",
    "retrieval.fusion_k",
    "retrieval.snapshot_ms",
    "retrieval.trigram",
    "retrieval.event_log",
    "retrieval.weights.*",
    "retrieval.lex.*",
    "retrieval.budget.*",
    "retrieval.vec.backend",
    "retrieval.vec.storage",
    "retrieval.vec.max_segments",
    "targets.enabled",
    "licence.allow_tiers",
    "licence.jurisdiction",
    "licence.fields_of_use",
    "drivers.enabled",
    "drivers.inproc",
    "drivers.require_lock",
    "drivers.allow_unattested",
    "drivers.isolation_floor",
    "drivers.probe_timeout_ms",
    "drivers.max_workers",
    "drivers.worker_idle_ttl_s",
    "drivers.crash_quarantine",
    "drivers.cost.allow_classes",
    "drivers.cost.auto_refresh_classes",
    "graph.enabled",
    "graph.passes.order",
    "graph.passes.enable",
    "services.*.endpoint",
    "services.*.autostart",
    "services.*.capacity",
    "services.*.batch_wait_ms",
    "services.*.max_batch",
    "services.*.keep_alive_s",
)

# The ONE key whose axis moves when the coarse charter globs are expanded to declaration sites:
# `store.**` swept it into `operational`, and 18-api-sketch.md section 4 gives its own row
# `store.retain_parts | enum | "when_citable" | **semantic**`. It is semantic under the rule --
# `never` makes `quote = 'verbatim'` unreachable (INV-10), which changes what a produced row says.
CHARTER_REFINED = frozenset({"store.retain_parts"})

# The two declared keys no charter pattern reaches at all: one is post-charter, one is ADR-3's.
CHARTER_SILENT = frozenset({"retrieval.event_log_query", "drivers.resolve.*"})

_CHARTER_ROWS = tuple(
    AxisRow(name=name, axis=axis, env="OMNIWEAVE_X")
    for axis, block in (("semantic", CHARTER_SEMANTIC), ("operational", CHARTER_OPERATIONAL))
    for name in block
)


def _instance(name: str) -> str:
    """A glob KEY rendered as one concrete instance, so pattern-versus-pattern never happens."""
    return name.replace("**", "x").replace("*", "x")


def test_the_charter_block_is_sixty_patterns() -> None:
    """ADR-3 measured "the sixty patterns cover the example exactly" and "118 keys against 61
    patterns" once `drivers.resolve.*` is added. If this count does not reproduce, the transcription
    above is wrong and every comparison below is worthless."""
    assert len(CHARTER_SEMANTIC) + len(CHARTER_OPERATIONAL) == 60
    assert len(set(CHARTER_SEMANTIC) | set(CHARTER_OPERATIONAL)) == 60
    assert len(_CHARTER_ROWS) + len(CHARTER_SILENT & set(KEYS)) == 62


def test_no_charter_pattern_double_matches_a_declared_key() -> None:
    """G18's second condition, turned back on the charter's own list."""
    for name in KEYS:
        globs = [r for r in _CHARTER_ROWS if r.is_glob and r.matches(_instance(name))]
        assert len(globs) <= 1, (name, [g.name for g in globs])


@pytest.mark.parametrize("name", sorted(KEYS))
def test_every_emitted_axis_agrees_with_the_charter_where_the_charter_speaks(name: str) -> None:
    hits = [row for row in _CHARTER_ROWS if row.matches(_instance(name))]
    if not hits:
        assert name in CHARTER_SILENT, f"{name} is classified by no charter pattern"
        return
    explicit = [row for row in hits if not row.is_glob]
    charter_axis = (explicit or hits)[0].axis
    if name in CHARTER_REFINED:
        assert KEYS[name].axis != charter_axis
        assert KEYS[name].axis == "semantic", "fail expensive, never wrong"
        return
    assert KEYS[name].axis == charter_axis, name
