"""`omniweave_core.limits` — every ceiling, the one floor, and the three-way clamp.

The value table below is the test: each row is `(name, value, locus)` and the locus is rendered into
the test id, so a failure reads `test_value[MAX_GRID_SLOTS-charter section 6.10]` and points at the
document that would have to change for the number to move.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest
from omniweave_core import limits

SOURCE = Path(limits.__file__)

CHARTER = "charter.md section 6.10"
DOC_MODEL = "03-document-model.md section 14"
INGEST = "05-ingest-and-routing.md, the container budget"
STORE = "07-store-and-retrieval.md"
OUT = "09-generation.md section 14.1"
QUALITY = "13-quality.md section 13.4"
SECURITY = "14-security.md section 2.1"
DRIVERS = "04-driver-system.md section 4.5"
RUNTIME = "08-runtime.md section 1.6"
OBSERVE_SAMPLING = "15-observability.md section 2.4"
OBSERVE_SUBSTRATE = "15-observability.md sections 1 and 3.2"

# (constant, value the plan prints, the document that sets it)
VALUES: list[tuple[str, object, str]] = [
    # The one floor
    ("MIN_SQLITE", (3, 42, 0), CHARTER),
    # The driver card. Erratum E6 — the charter states no bound on the TOML a third party wrote.
    ("MAX_CARD_BYTES", 65_536, DRIVERS),
    ("MAX_CARD_DEPTH", 6, DRIVERS),
    ("MAX_CARD_FORMATS", 64, DRIVERS),
    ("MAX_CARD_BINARIES", 16, DRIVERS),
    ("MAX_CARD_PINS", 256, DRIVERS),
    ("MAX_CARD_BENCHMARKS", 64, DRIVERS),
    ("MAX_CARD_CONFIG_PROPERTIES", 32, DRIVERS),
    # Acquisition: the container budget and the recursion limit
    ("MAX_ENTRY_BYTES", 134_217_728, INGEST),
    ("MAX_CONTAINER_TOTAL_BYTES", 536_870_912, INGEST),
    ("MAX_ENTRY_COUNT", 100_000, INGEST),
    ("MAX_CONTAINER_DEPTH", 3, INGEST),
    ("MAX_CONTAINER_UNITS", 10_000, INGEST),
    ("MAX_IDENTITY_BYTES", 65_536, INGEST),
    # L2, the document model
    ("MAX_ASSET_BYTES", 268_435_456, CHARTER),
    ("MAX_ASSET_TOTAL_BYTES", 536_870_912, SECURITY),
    ("MAX_GRID_SLOTS", 4_000_000, CHARTER),
    ("MAX_EXPANSION", 4_000_000, DOC_MODEL),
    ("MAX_SEGMENT_BLOCKS", 512, CHARTER),
    ("MAX_BLOCKS_PER_DOC", 8_388_608, DOC_MODEL),
    ("MAX_BLOCKS_PER_PAGE", 4_194_304, DOC_MODEL),
    ("MAX_BLOCK_TEXT_BYTES", 1_048_576, DOC_MODEL),
    ("MAX_MARKS_PER_BLOCK", 4_096, DOC_MODEL),
    ("MAX_BLOCK_DEPTH", 64, DOC_MODEL),
    ("MAX_PAYLOAD_BYTES", 16_384, DOC_MODEL),
    ("MAX_X_BYTES", 16_384, DOC_MODEL),
    ("MAX_RESIDENT_CELLS", 65_536, DOC_MODEL),
    ("MAX_VIEW_BYTES", 67_108_864, DOC_MODEL),
    ("INLINE_MAX", 262_144, CHARTER),
    # Hostile markup, legacy records, rasterisation
    ("MAX_XML_DEPTH", 256, SECURITY),
    ("MAX_XML_NODES", 2_000_000, SECURITY),
    ("MAX_EXPANSION_TEXT_BYTES", 67_108_864, SECURITY),
    ("MAX_RECORD_DEPTH", 64, SECURITY),
    ("MAX_RECORDS", 16_000_000, SECURITY),
    ("MAX_IMAGE_PIXELS", 89_478_485, SECURITY),
    ("MAX_RENDER_PIXELS", 40_000_000, SECURITY),
    # L3/L4: structure extraction and the graph
    ("MAX_SEGMENT_TOKENS", 2048, CHARTER),
    ("MAX_REF_SITES_PER_BLOCK", 32, CHARTER),
    ("MAX_LINKS_PER_BLOCK", 4096, CHARTER),
    ("MAX_ENTITY_DEGREE", 4096, CHARTER),
    ("MAX_MENTIONS_PER_DOC", 250_000, CHARTER),
    ("MAX_ITEMS_PER_SEGMENT", 2048, CHARTER),
    ("MAX_CLUSTER_EDGES", 8_000_000, CHARTER),
    # Retrieval and serve
    ("MAX_SNAPSHOT_MS", 5_000, CHARTER),
    ("PREFILTER_MAX", 200_000, CHARTER),
    ("VEC_BRUTE_MAX", 250_000, CHARTER),
    ("HARD_CEILING", 24_000, CHARTER),
    ("SEM_BLOCKS_PER_SEGMENT", 64, CHARTER),
    ("MAX_QUERY_CHARS", 4_000, f"{STORE} section 5.4"),
    ("MAX_QUERY_TERMS", 64, f"{STORE} section 5.4"),
    ("MAX_QUERY_REFS", 16, f"{STORE} section 5.4"),
    ("MAX_FILTER_DOC_KEYS", 1024, f"{STORE} section 6"),
    # The runtime
    ("MAX_AUTO_PARALLEL", 96, CHARTER),
    ("MAX_DEPS_PER_UNIT", 256, CHARTER),
    ("MAX_WORK_ATTEMPTS", 5, RUNTIME),
    # Observability: the two bounds 15-observability.md puts here rather than in a comment
    ("MAX_SPAN_BUFFER_EVENTS", 64, OBSERVE_SAMPLING),
    ("MAX_EVENT_QUEUE", 65_536, OBSERVE_SUBSTRATE),
    # The OUT framework
    ("MAX_IL_FILE_BYTES", 4_194_304, OUT),
    ("MAX_IL_NODES", 100_000, OUT),
    ("MAX_IL_DEPTH", 128, OUT),
    ("MAX_FINDINGS_PER_RULE", 5_000, OUT),
    ("MAX_FOLDED_FINDINGS", 20_000, OUT),
    ("MAX_REPORT_BYTES", 8_388_608, OUT),
    ("MAX_MARKER_PAYLOAD_BYTES", 4_096, OUT),
    ("MAX_MARKERS_PER_UNIT", 256, OUT),
    # Quality and eval
    ("MAX_DRIFT_BAND", 0.02, QUALITY),
    ("MAX_REDUCTION_BYTES", 262_144, QUALITY),
    ("MAX_CASSETTE_BYTES", 262_144, QUALITY),
    ("MAX_CASSETTE_BYTES_TOTAL", 33_554_432, QUALITY),
    ("MAX_PARTIAL_FRAC", 0.02, QUALITY),
]


@pytest.mark.parametrize(
    ("name", "value"),
    [(n, v) for n, v, _ in VALUES],
    ids=[f"{n}-{locus}" for n, _, locus in VALUES],
)
def test_value_is_what_the_plan_prints(name: str, value: object) -> None:
    assert getattr(limits, name) == value


def test_the_value_table_covers_every_exported_constant() -> None:
    """A ceiling added without a row here would be a number with no cited warrant."""
    tabled = {n for n, _, _ in VALUES}
    exported = set(limits.__all__) - {"effective"}
    assert exported == tabled


def _public_names(mod: object) -> set[str]:
    """Names a `from ... import *` would take. `annotations` is the `__future__` flag, and
    an `@`-prefixed name is pytest's assertion-rewriting machinery, not a public symbol."""
    return {
        n for n in vars(mod) if n.isidentifier() and not n.startswith("_") and n != "annotations"
    }


# ---------------------------------------------------------------------------
# effective() — the three-way clamp
# ---------------------------------------------------------------------------


def test_effective_is_the_three_way_minimum__charter_md_section_6_10() -> None:
    """`effective = min(tenant_cap, declared, HOST_MAX)`."""
    assert limits.effective(10, 20, 30) == 10
    assert limits.effective(30, 20, 10) == 10
    assert limits.effective(30, 10, 20) == 10


def test_effective_lets_each_party_win_in_turn__inv_22() -> None:
    assert limits.effective(1, 20, 30) == 1
    assert limits.effective(20, 1, 30) == 1
    assert limits.effective(20, 30, 1) == 1


def test_effective_treats_none_as_did_not_speak__charter_md_section_6_10() -> None:
    """A party that declared nothing must not clamp to zero."""
    assert limits.effective(None, None, 7) == 7
    assert limits.effective(None, 5, 7) == 5
    assert limits.effective(5, None, 7) == 5
    assert limits.effective(None, 9, 7) == 7


def test_effective_never_widens_past_the_host_ceiling__inv_22_dr20() -> None:
    """A card declaring above HOST_MAX is CARD_INVALID, rejected by the card validator; this
    function still takes the minimum, so an over-declaration is never silently honoured here."""
    assert limits.effective(10**9, 10**9, limits.MAX_ASSET_BYTES) == limits.MAX_ASSET_BYTES


def test_effective_clamps_a_float_ceiling__13_quality_md_section_13_4() -> None:
    """`MAX_DRIFT_BAND` and `MAX_PARTIAL_FRAC` are fractions, not counts."""
    assert limits.effective(None, 0.01, limits.MAX_DRIFT_BAND) == 0.01
    assert limits.effective(None, 0.5, limits.MAX_DRIFT_BAND) == limits.MAX_DRIFT_BAND


# ---------------------------------------------------------------------------
# The relations the plan asserts between ceilings
# ---------------------------------------------------------------------------


def test_max_expansion_equals_max_grid_slots__03_document_model_md_section_14() -> None:
    """`equal to MAX_GRID_SLOTS and asserted equal, so a table cannot build and then fail to
    store`."""
    assert limits.MAX_EXPANSION == limits.MAX_GRID_SLOTS


def test_max_asset_total_equals_container_total_and_is_not_the_same_ceiling__14_security_2_1() -> (
    None
):
    """`The two carry the identical number and are not the same ceiling` — the CONTAINER prefix is
    what keeps them apart (glossary.md, INV-21)."""
    assert limits.MAX_ASSET_TOTAL_BYTES == limits.MAX_CONTAINER_TOTAL_BYTES
    assert limits.MAX_ASSET_TOTAL_BYTES >= 2 * limits.MAX_ASSET_BYTES


def test_max_block_text_bytes_is_four_times_inline_max__03_document_model_md_section_14() -> None:
    """`four times INLINE_MAX, so any block arriving inline is already inside it`."""
    assert limits.MAX_BLOCK_TEXT_BYTES == 4 * limits.INLINE_MAX


def test_marks_and_links_share_one_number__03_document_model_md_section_14() -> None:
    """`the same 4,096 as MAX_LINKS_PER_BLOCK, and the maxItems in section 3.2`."""
    assert limits.MAX_MARKS_PER_BLOCK == limits.MAX_LINKS_PER_BLOCK == 4096


def test_hard_ceiling_is_far_below_max_view_bytes__03_document_model_md_section_13_5() -> None:
    """`three orders of magnitude below the cap`, which is why the Answer path never approaches a
    whole-document serialisation."""
    assert limits.MAX_VIEW_BYTES / limits.HARD_CEILING > 1000


def test_sem_blocks_per_segment_can_bite__07_store_and_retrieval_md_section_8() -> None:
    """`because MAX_SEGMENT_BLOCKS = 512, the cap can bite`."""
    assert limits.SEM_BLOCKS_PER_SEGMENT < limits.MAX_SEGMENT_BLOCKS


def test_max_report_bytes_matches_the_folded_finding_arithmetic__09_generation_md_14_1() -> None:
    """`20 000 x ~400 B = 8 MB = MAX_REPORT_BYTES`."""
    assert limits.MAX_FOLDED_FINDINGS * 400 <= limits.MAX_REPORT_BYTES
    assert limits.MAX_FOLDED_FINDINGS > limits.MAX_FINDINGS_PER_RULE


def test_il_file_bytes_matches_the_node_arithmetic__09_generation_md_section_14_1() -> None:
    """`MAX_IL_NODES x a mean 40 source bytes per element = 4 MB`."""
    assert limits.MAX_IL_NODES * 40 <= limits.MAX_IL_FILE_BYTES


# ---------------------------------------------------------------------------
# F29 — the two provisional numbers, and the fixture they are set against
# ---------------------------------------------------------------------------

F29_FIXTURE_CELLS = 4_000_000
"""The charter's celebrated 4M-cell sheet, on one page (03-document-model.md section 14.1)."""


def test_max_blocks_per_page_admits_the_f29_fixture_with_4_9_percent_headroom__03_14_1() -> None:
    """`chosen so the charter's 4M-cell sheet is admissible with 4.9% headroom`. Provisional: F29,
    the sub-page commit boundary, is the unrun measurement behind it."""
    assert limits.MAX_BLOCKS_PER_PAGE == 2**22
    assert limits.MAX_BLOCKS_PER_PAGE > F29_FIXTURE_CELLS
    headroom = limits.MAX_BLOCKS_PER_PAGE / F29_FIXTURE_CELLS - 1
    assert round(headroom * 100, 1) == 4.9


def test_max_grid_slots_does_not_fire_on_the_f29_fixture__03_document_model_md_14_1() -> None:
    """`exactly at MAX_GRID_SLOTS, which does not fire because 4,000,000 is not greater than
    4,000,000`. Non-firing is the specified behaviour, not an off-by-one."""
    assert limits.MAX_GRID_SLOTS == F29_FIXTURE_CELLS
    assert not F29_FIXTURE_CELLS > limits.MAX_GRID_SLOTS


def test_max_blocks_per_doc_is_twice_the_f29_fixture__03_document_model_md_section_14() -> None:
    """`2**23, chosen as twice the charter's celebrated 4M-cell sheet`."""
    assert limits.MAX_BLOCKS_PER_DOC == 2**23
    assert limits.MAX_BLOCKS_PER_DOC == 2 * limits.MAX_BLOCKS_PER_PAGE


def test_both_f29_constants_name_f29_in_their_docstrings__12_performance_md_section_5() -> None:
    """`A pessimistic answer moves two constants, not one` — so the next reader must find F29 from
    either one."""
    source = SOURCE.read_text(encoding="utf-8")
    for name in ("MAX_BLOCKS_PER_PAGE", "MAX_GRID_SLOTS"):
        doc = _attribute_docstring(source, name)
        assert "F29" in doc, f"{name}'s docstring does not name F29"
        assert "rovisional" in doc, f"{name}'s docstring does not mark the number provisional"


# ---------------------------------------------------------------------------
# The rulings this module has to honour
# ---------------------------------------------------------------------------


def test_it_carries_no_version_constant__adr_0009_and_store_property_st23() -> None:
    """`omniweave_core.limits holds no version constant, now or ever` — the grep gate, in code."""
    banned = (
        "SCHEMA",
        "SCHEMA_MINOR",
        "SCHEMAS_SUPPORTED",
        "CONTRACT",
        "CONTRACTS_SUPPORTED",
        "RELEASE",
        "VERSION",
    )
    for name in banned:
        assert not hasattr(limits, name), f"{name} must live in omniweave_core.contract"


def test_no_ceiling_is_a_target__inv_22_01_principles_md() -> None:
    """`A number a producer overshoots by design is a *_TARGET_*` and is not a MAX_."""
    assert [n for n in limits.__all__ if "TARGET" in n] == []
    assert not hasattr(limits, "SEGMENT_TARGET_TOKENS")


def test_all_is_sorted_and_complete() -> None:
    assert limits.__all__ == sorted(limits.__all__)
    public = _public_names(limits)
    assert public - set(limits.__all__) == set()


@pytest.mark.parametrize("name", [n for n, _, _ in VALUES])
def test_every_ceiling_cites_the_document_that_sets_it(name: str) -> None:
    """A reader must be able to get from the number to its warrant; an orphan ceiling gets raised by
    whoever hits it first (09-generation.md section 14.1)."""
    doc = _attribute_docstring(SOURCE.read_text(encoding="utf-8"), name)
    assert ".md" in doc or "charter" in doc, f"{name}'s docstring cites no document"


def test_effective_docstring_cites_its_specification() -> None:
    assert limits.effective.__doc__ is not None
    assert "charter section 6.10" in limits.effective.__doc__


# ---------------------------------------------------------------------------
# D1 — zero third-party runtime dependencies
# ---------------------------------------------------------------------------


def test_imports_nothing_outside_the_standard_library__charter_d1_and_gate_g1() -> None:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots
    assert roots <= sys.stdlib_module_names, roots - sys.stdlib_module_names


def _attribute_docstring(source: str, name: str) -> str:
    """The PEP 258 attribute docstring for `name`, read out of the source.

    Attribute docstrings are not introspectable at runtime, so the AST is the only honest reader.
    """
    body = ast.parse(source).body
    for i, node in enumerate(body[:-1]):
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        if target != name:
            continue
        nxt = body[i + 1]
        if isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant):
            value = nxt.value.value
            if isinstance(value, str):
                return value
    msg = f"{name} has no attribute docstring"
    raise AssertionError(msg)
