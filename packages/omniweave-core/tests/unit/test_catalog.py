"""`Catalog` — the printed declaration, the two digests, trust, and the tombstone seed set.

The properties under test are 04-driver-system.md's, and three of them are load-bearing enough that
the module would be wrong without them rather than merely untidy:

* **`catalog_digest` is order-independent.** It is the third component of `resolve()`'s memo key,
  and `resolve()` is memoised. A digest that moved with `entry_points()` enumeration order would
  make the memo a cache with a machine-dependent key — every run recomputing on one machine and
  hitting on another, with nothing in the report saying why. Asserted over 100 distinct orderings
  of one catalog, taken from `itertools.permutations` rather than from `random` (which is banned
  repo-wide, and which would make the failing ordering unreproducible anyway).
* **`catalog_digest` moves when a probe verdict moves and stands still when anything outside the
  recipe does.** Section 4.7's preflight loop re-resolves once against a refreshed catalog; if the
  verdict were outside the digest, the second resolution would hit the memo and return the first
  one's answer.
* **Trust is first-match-wins over five rows.** One test per row, plus a card satisfying rows 1 and
  3 at once, plus the missing-manifest case — which is not an edge case at all but the state of
  every developer's checkout (11-repo-layout.md section 7.2).

Every plan-fidelity test reads `_plan/` through the `plan` fixture and skips when the design tree is
absent, so a clean clone still runs the behavioural half.
"""

from __future__ import annotations

import dataclasses
import re
from itertools import islice, permutations
from pathlib import Path
from typing import get_args

import pytest
from conftest import INTERPRETER
from hypothesis import given
from hypothesis import strategies as st
from omniweave_core.canonical import sha256_canonical
from omniweave_core.drivers.card import DriverCard, Tombstone, load_card
from omniweave_core.drivers.catalog import (
    CATALOG_PROBE_STATUSES,
    FIRST_PARTY_NAME,
    FIRST_PARTY_SCHEMA,
    PROBE_UNKNOWN,
    TRUST_TABLE,
    UNPINNED_DEGRADATION,
    Catalog,
    CatalogProbeStatus,
    FirstPartyManifest,
    FirstPartyRow,
    compute_catalog_digest,
    compute_trust,
    compute_validity_key,
    first_party_path,
    read_first_party,
    tombstone_licence_digests,
)
from omniweave_core.errors import ConfigError, InternalError
from omniweave_ports.types import ProbeStatus, TrustTier

DOC = "04-driver-system.md"

CARD = """card_schema = 1

[driver]
id = "{driver_id}"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "pkg.driver:Cls"
granularity = "document"
replay_class = "byte_exact"
title = "{title}"

[capability]
formats = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""

TOMBSTONE = """card_schema = 1

[driver]
id = "{driver_id}"
port = "parse/1"
title = "a forbidden driver"

[tombstone]
reason = "{reason}"
replaced_by = "parse.page.olmocr"
review_by = "2027-06-01"

[licence.weights]
licence_sha256 = "sha256:{digest}"
weights_revision = "n/a"
"""

KEY = sha256_canonical(["a-validity-key"])


def card(driver_id: str, *, title: str = "t", origin: str = "entry_point") -> DriverCard:
    """One minimal, valid `DriverCard`. `title` is the knob that moves `card_sha256`."""
    loaded = load_card(
        CARD.format(driver_id=driver_id, title=title).encode("utf-8"),
        origin=origin,
        source=f"{driver_id}/driver.toml",
    )
    assert isinstance(loaded, DriverCard)
    return loaded


def tombstone(driver_id: str, *, digest: str = "e1" * 32, reason: str = "a bar") -> Tombstone:
    loaded = load_card(
        TOMBSTONE.format(driver_id=driver_id, digest=digest, reason=reason).encode("utf-8"),
        origin="tombstone",
        source=f"{driver_id}.toml",
    )
    assert isinstance(loaded, Tombstone)
    return loaded


def cards(*ids: str) -> dict[str, DriverCard]:
    return {driver_id: card(driver_id) for driver_id in ids}


IDS = (
    "parse.notebook.ipynb",
    "parse.pdf.pdfium",
    "parse.office.anydoc",
    "parse.page.olmocr",
    "parse.web.html",
    "parse.mail.eml",
)


# ---------------------------------------------------------------------------
# The printed declaration (section 4.7)
# ---------------------------------------------------------------------------


def test_the_first_four_fields_are_section_4_7s_printed_declaration_in_its_order() -> None:
    """The plan prints four fields; this class carries three more and the four come first.

    Transcription, not invention: a reader following section 4.7 to this class must find the names
    it printed, spelled the same and in the same order.
    """
    names = [field.name for field in dataclasses.fields(Catalog)]
    assert names[:4] == ["cards", "probe_status", "validity_key", "catalog_digest"]
    assert names[4:] == ["trust", "tombstones", "tombstone_licence_digests"]


def test_the_printed_declaration_is_read_out_of_the_plan_itself(plan) -> None:
    """Assert against the document rather than against a comment quoting the document."""
    plan.require()
    fences = [body for body in plan.fences(DOC, "python") if "class Catalog:" in body]
    assert len(fences) == 1, "section 4.7 prints exactly one Catalog declaration"
    printed = re.findall(r"^    (\w+):", fences[0], flags=re.MULTILINE)
    assert printed == ["cards", "probe_status", "validity_key", "catalog_digest"]
    assert "omniweave_core/drivers/catalog.py" in fences[0], "the fence names this file"


def test_the_plan_says_catalog_digest_includes_probe_status(plan) -> None:
    """The one sentence the digest recipe's correctness rests on, quoted from its source."""
    plan.require()
    hits = plan.grep(r"`catalog_digest` includes `probe_status`", documents=[DOC])
    assert hits, "section 4.7 should state that catalog_digest includes probe_status"


def test_a_card_carries_no_trust_attribute_which_is_why_the_catalog_must(plan) -> None:
    """E13: trust is COMPUTED BY THE LOADER, never self-reported, so it is not on the card.

    This is the whole justification for `Catalog.trust` existing beside section 4.7's four printed
    fields: the printed `Catalog` cannot compute its own `catalog_digest` without it.
    """
    assert not hasattr(card(IDS[0]), "trust")
    assert "trust" not in {field.name for field in dataclasses.fields(DriverCard)}
    plan.require()
    hits = plan.grep(r"COMPUTED BY THE LOADER, NEVER SELF-REPORTED", documents=[DOC])
    assert hits, "section 4.2 should state that trust is computed and never self-reported"


def test_the_catalog_probe_status_domain_has_the_three_verdicts_plus_unknown() -> None:
    """`ProbeStatus` has three members; `unknown` is the catalog's own fourth (section 4.7)."""
    assert get_args(CatalogProbeStatus) == CATALOG_PROBE_STATUSES
    assert CATALOG_PROBE_STATUSES == ("ok", "degraded", "unavailable", PROBE_UNKNOWN)
    assert tuple(status.value for status in ProbeStatus) == CATALOG_PROBE_STATUSES[:3]
    assert PROBE_UNKNOWN not in {status.value for status in ProbeStatus}


# ---------------------------------------------------------------------------
# validity_key (section 4.3 step 2)
# ---------------------------------------------------------------------------


def test_validity_key_moves_on_mtime_ns() -> None:
    """An edited `dist-info` invalidates the wholesale card cache. One nanosecond is enough."""
    base = [("a.dist-info", 1_000_000_000, 4096), ("b.dist-info", 2_000_000_000, 8192)]
    moved = [("a.dist-info", 1_000_000_001, 4096), ("b.dist-info", 2_000_000_000, 8192)]
    assert compute_validity_key(base) != compute_validity_key(moved)


def test_validity_key_moves_on_size() -> None:
    """A same-mtime rewrite of a different length is the case a mtime-only key would miss."""
    base = [("a.dist-info", 1_000_000_000, 4096)]
    moved = [("a.dist-info", 1_000_000_000, 4097)]
    assert compute_validity_key(base) != compute_validity_key(moved)


def test_validity_key_moves_when_a_distribution_appears_or_disappears() -> None:
    one = [("a.dist-info", 1, 2)]
    two = [("a.dist-info", 1, 2), ("b.dist-info", 3, 4)]
    assert compute_validity_key(one) != compute_validity_key(two)
    assert compute_validity_key(()) != compute_validity_key(one)


def test_validity_key_is_independent_of_scandir_order() -> None:
    """`os.scandir` order is a filesystem property; two machines must compute one key."""
    triples = [(f"{name}.dist-info", i * 7, i * 13) for i, name in enumerate("abcdefg")]
    keys = {compute_validity_key(order) for order in islice(permutations(triples), 100)}
    assert len(keys) == 1


def test_the_three_components_are_distinguishable_rather_than_concatenated() -> None:
    """graphrag's `gen_sha512_hash` concatenates without a separator; canonical JSON does not.

    `("ab", 1, 2)` and `("a", 12, 2)` would collide under naive joining. They must not here.
    """
    assert compute_validity_key([("ab", 1, 2)]) != compute_validity_key([("a", 12, 2)])


def test_validity_key_is_sixty_four_lowercase_hex() -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", compute_validity_key([("a", 1, 2)]))


# ---------------------------------------------------------------------------
# catalog_digest (section 4.7) — DR4-adjacent
# ---------------------------------------------------------------------------


def test_catalog_digest_is_identical_over_one_hundred_shuffles_of_one_catalog() -> None:
    """The property that makes `resolve()`'s memo sound (DR4-adjacent).

    100 DISTINCT orderings of the same six drivers, taken from `itertools.permutations` because
    `random` is banned repo-wide and because a deterministic generator makes a failure
    reproducible from the test name alone.
    """
    built = cards(*IDS)
    statuses = dict(zip(IDS, ("ok", "degraded", "unavailable", "unknown", "ok", "ok"), strict=True))
    tiers = dict.fromkeys(IDS, TrustTier.LOCAL)
    orders = list(islice(permutations(IDS), 100))
    assert len({tuple(order) for order in orders}) == 100

    digests = {
        compute_catalog_digest(
            {driver_id: built[driver_id] for driver_id in order},
            {driver_id: statuses[driver_id] for driver_id in order},
            {driver_id: tiers[driver_id] for driver_id in order},
        )
        for order in orders
    }
    assert len(digests) == 1


@given(order=st.permutations(IDS))
def test_the_assembled_catalog_digest_is_order_independent(order: list[str]) -> None:
    """The same property through `assemble()`, over hypothesis-chosen orderings."""
    built = cards(*IDS)
    reference = Catalog.assemble(cards=built, validity_key=KEY)
    shuffled = Catalog.assemble(
        cards={driver_id: built[driver_id] for driver_id in order}, validity_key=KEY
    )
    assert shuffled.catalog_digest == reference.catalog_digest


def test_catalog_digest_moves_when_a_probe_status_moves() -> None:
    """Section 4.7's preflight loop is unsound without this.

    After `resolve()` returns, the runtime probes every `unknown` candidate and re-resolves ONCE
    against the refreshed catalog. If the verdict were outside the digest the second resolution
    would hit the memo, return the first one's answer, and dispatch to an `unavailable` driver.
    """
    built = cards(*IDS[:3])
    before = Catalog.assemble(cards=built, validity_key=KEY)
    assert set(before.probe_status.values()) == {PROBE_UNKNOWN}
    for verdict in ("ok", "degraded", "unavailable"):
        after = Catalog.assemble(cards=built, probe_status={IDS[0]: verdict}, validity_key=KEY)
        assert after.catalog_digest != before.catalog_digest, verdict


def test_every_pair_of_probe_verdicts_gives_a_different_catalog_digest() -> None:
    """Not merely "different from unknown": all four verdicts must be distinguishable."""
    built = cards(IDS[0])
    digests = {
        verdict: Catalog.assemble(
            cards=built, probe_status={IDS[0]: verdict}, validity_key=KEY
        ).catalog_digest
        for verdict in CATALOG_PROBE_STATUSES
    }
    assert len(set(digests.values())) == len(CATALOG_PROBE_STATUSES)


def test_catalog_digest_moves_when_trust_moves() -> None:
    """`trust` is in the recipe, and section 6.1 grants `inproc` on it."""
    built = cards(IDS[0])
    local = Catalog.assemble(cards=built, trust={IDS[0]: TrustTier.LOCAL}, validity_key=KEY)
    pinned = Catalog.assemble(cards=built, trust={IDS[0]: TrustTier.PINNED}, validity_key=KEY)
    assert local.catalog_digest != pinned.catalog_digest


def test_catalog_digest_moves_when_a_card_changes() -> None:
    """`card_sha256` is over the RAW bytes, so a title edit moves it and moves the digest."""
    one = Catalog.assemble(cards={IDS[0]: card(IDS[0], title="a")}, validity_key=KEY)
    two = Catalog.assemble(cards={IDS[0]: card(IDS[0], title="b")}, validity_key=KEY)
    assert one.cards[IDS[0]].card_sha256 != two.cards[IDS[0]].card_sha256
    assert one.catalog_digest != two.catalog_digest


def test_catalog_digest_moves_when_the_origin_changes() -> None:
    """`origin` is in the recipe: the same bytes from a `driver_path` are a different row."""
    installed = Catalog.assemble(
        cards={IDS[0]: card(IDS[0], origin="entry_point")}, validity_key=KEY
    )
    dropped_in = Catalog.assemble(
        cards={IDS[0]: card(IDS[0], origin="driver_path")}, validity_key=KEY
    )
    assert installed.catalog_digest != dropped_in.catalog_digest


def test_catalog_digest_does_not_move_when_the_validity_key_does() -> None:
    """The two digests answer different questions and are not each other's inputs.

    A touched `dist-info` on an unrelated distribution invalidates the CARD CACHE and must not
    invalidate the RESOLVE MEMO: nothing a driver resolves on changed.
    """
    built = cards(*IDS[:3])
    one = Catalog.assemble(cards=built, validity_key=KEY)
    two = Catalog.assemble(cards=built, validity_key=sha256_canonical(["another"]))
    assert one.validity_key != two.validity_key
    assert one.catalog_digest == two.catalog_digest


def test_catalog_digest_does_not_move_when_the_tombstone_set_does() -> None:
    """Deliberate, and section 4.8 says where the fact enters instead.

    The tombstone digest set is loaded into `Policy` at startup and `policy_digest` covers it, so
    a changed tombstone set already moves the memo key through its other component. Putting it in
    both would be INV-21's second home for one fact.
    """
    built = cards(*IDS[:3])
    bare = Catalog.assemble(cards=built, validity_key=KEY)
    stoned = Catalog.assemble(
        cards=built, tombstones=[tombstone("parse.page.surya")], validity_key=KEY
    )
    assert stoned.tombstones
    assert stoned.catalog_digest == bare.catalog_digest


def test_catalog_digest_is_sixty_four_lowercase_hex() -> None:
    catalog = Catalog.assemble(cards=cards(*IDS), validity_key=KEY)
    assert re.fullmatch(r"[0-9a-f]{64}", catalog.catalog_digest)


def test_two_catalogs_differing_only_in_which_driver_is_unavailable_differ() -> None:
    """A digest that keyed on the multiset of verdicts rather than on the pairing would collide."""
    built = cards(*IDS[:2])
    first = Catalog.assemble(
        cards=built, probe_status={IDS[0]: "unavailable", IDS[1]: "ok"}, validity_key=KEY
    )
    second = Catalog.assemble(
        cards=built, probe_status={IDS[0]: "ok", IDS[1]: "unavailable"}, validity_key=KEY
    )
    assert first.catalog_digest != second.catalog_digest


# ---------------------------------------------------------------------------
# assemble() — the seam, and what it refuses
# ---------------------------------------------------------------------------


def test_an_unprobed_driver_defaults_to_unknown_which_resolve_treats_as_passing() -> None:
    catalog = Catalog.assemble(cards=cards(*IDS[:2]), probe_status={IDS[0]: "ok"}, validity_key=KEY)
    assert catalog.probe_status == {IDS[0]: "ok", IDS[1]: PROBE_UNKNOWN}


def test_a_driver_with_no_computed_trust_defaults_to_unpinned() -> None:
    """Row 5 of section 4.2's table, and the safe direction: `unpinned` grants no `inproc`."""
    catalog = Catalog.assemble(
        cards=cards(*IDS[:2]), trust={IDS[0]: TrustTier.LOCAL}, validity_key=KEY
    )
    assert catalog.trust == {IDS[0]: TrustTier.LOCAL, IDS[1]: TrustTier.UNPINNED}


def test_a_card_filed_under_the_wrong_key_is_refused_naming_both_spellings() -> None:
    with pytest.raises(InternalError) as caught:
        Catalog.assemble(cards={"parse.pdf.wrong": card(IDS[0])}, validity_key=KEY)
    assert "parse.pdf.wrong" in str(caught.value)
    assert IDS[0] in str(caught.value)


def test_a_probe_status_for_an_unknown_id_is_refused_naming_the_id() -> None:
    with pytest.raises(InternalError) as caught:
        Catalog.assemble(
            cards=cards(IDS[0]), probe_status={"parse.pdf.ghost": "ok"}, validity_key=KEY
        )
    assert "parse.pdf.ghost" in str(caught.value)
    assert "probe_status" in str(caught.value)


def test_a_trust_tier_for_an_unknown_id_is_refused_naming_the_id() -> None:
    with pytest.raises(InternalError) as caught:
        Catalog.assemble(
            cards=cards(IDS[0]), trust={"parse.pdf.ghost": TrustTier.LOCAL}, validity_key=KEY
        )
    assert "parse.pdf.ghost" in str(caught.value)
    assert "trust" in str(caught.value)


@pytest.mark.parametrize("verdict", ["OK", "missing", "", "unknown ", "pass"])
def test_a_probe_verdict_outside_the_four_is_refused_naming_the_domain(verdict: str) -> None:
    with pytest.raises(InternalError) as caught:
        Catalog.assemble(cards=cards(IDS[0]), probe_status={IDS[0]: verdict}, validity_key=KEY)
    assert repr(verdict) in str(caught.value)
    assert "unavailable" in str(caught.value), "the message names the whole domain"


def test_a_trust_value_that_is_not_a_trust_tier_is_refused() -> None:
    with pytest.raises(InternalError):
        Catalog.assemble(cards=cards(IDS[0]), trust={IDS[0]: "first_party"}, validity_key=KEY)  # type: ignore[dict-item]


@pytest.mark.parametrize("key", ["", "sha256:" + "a" * 64, "A" * 64, "a" * 63, "z" * 64])
def test_a_validity_key_that_is_not_a_bare_digest_is_refused(key: str) -> None:
    with pytest.raises(InternalError):
        Catalog.assemble(cards=cards(IDS[0]), validity_key=key)


def test_two_tombstones_for_one_id_are_refused_rather_than_last_wins() -> None:
    with pytest.raises(InternalError) as caught:
        Catalog.assemble(
            cards={},
            tombstones=[tombstone("parse.page.surya"), tombstone("parse.page.surya")],
            validity_key=KEY,
        )
    assert "parse.page.surya" in str(caught.value)


def test_the_catalog_mappings_are_read_only() -> None:
    """One catalog per run, never mutated: a caller must not be able to add a driver mid-run."""
    catalog = Catalog.assemble(cards=cards(IDS[0]), validity_key=KEY)
    with pytest.raises(TypeError):
        catalog.cards["x"] = card(IDS[1])  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        catalog.validity_key = KEY  # type: ignore[misc]


def test_mutating_the_caller_s_dict_after_assembly_does_not_move_the_catalog() -> None:
    """`assemble()` copies. A catalog that aliased its input could change under a plan."""
    source = cards(IDS[0])
    catalog = Catalog.assemble(cards=source, validity_key=KEY)
    source[IDS[1]] = card(IDS[1])
    assert set(catalog.cards) == {IDS[0]}


def test_an_empty_catalog_is_legal_and_has_a_digest() -> None:
    """No driver installed is a valid state: `resolve()` returns zero candidates, not an error."""
    empty = Catalog.assemble(cards={}, validity_key=KEY)
    assert empty.cards == {}
    assert re.fullmatch(r"[0-9a-f]{64}", empty.catalog_digest)


# ---------------------------------------------------------------------------
# Tombstones (section 7.5)
# ---------------------------------------------------------------------------


def test_a_tombstone_is_reachable_by_id_with_its_quoted_reason() -> None:
    """DR22: a forbidden id resolves to a quoted reason and a named replacement."""
    stone = tombstone("parse.page.surya", reason="Attachment A clause 2(c) is a competitor bar")
    catalog = Catalog.assemble(cards={}, tombstones=[stone], validity_key=KEY)
    found = catalog.tombstone_for("parse.page.surya")
    assert found is not None
    assert "competitor bar" in found.reason
    assert found.replaced_by == "parse.page.olmocr"
    assert catalog.tombstone_for(IDS[0]) is None


def test_the_licence_seed_set_is_hash_keyed_so_it_survives_a_rename() -> None:
    """Section 7.5's second job: a third party wrapping the same weights computes `forbidden` too.

    The set holds DIGESTS, not ids, which is exactly what a denylist of ids cannot do.
    """
    digest = "e1" * 32
    stone = tombstone("parse.page.surya", digest=digest)
    catalog = Catalog.assemble(cards={}, tombstones=[stone], validity_key=KEY)
    assert catalog.tombstone_licence_digests == frozenset({f"sha256:{digest}"})
    renamed = tombstone("parse.page.someoneelse", digest=digest)
    assert tombstone_licence_digests([renamed]) == catalog.tombstone_licence_digests


def test_the_licence_seed_set_is_a_frozenset_that_does_not_grow_with_the_roster() -> None:
    """Section 7.5: a `frozenset[str]` of a few dozen digests, one membership test per card."""
    stones = [tombstone(f"parse.page.x{i}", digest=f"{i:02d}" * 32) for i in range(6)]
    catalog = Catalog.assemble(cards=cards(*IDS), tombstones=stones, validity_key=KEY)
    assert isinstance(catalog.tombstone_licence_digests, frozenset)
    assert len(catalog.tombstone_licence_digests) == 6


def test_a_tombstone_with_no_licence_facts_contributes_nothing_not_an_empty_digest() -> None:
    """An empty `licence_sha256` in the set would make every card with none of its own forbidden."""
    bare = """card_schema = 1

[driver]
id = "parse.page.gone"
port = "parse/1"
title = "removed"

[tombstone]
reason = "removed at release 2"
review_by = "2027-06-01"
"""
    loaded = load_card(bare.encode("utf-8"), origin="tombstone", source="gone.toml")
    assert isinstance(loaded, Tombstone)
    assert tombstone_licence_digests([loaded]) == frozenset()


# ---------------------------------------------------------------------------
# Trust (section 4.2) — one test per row, first-match-wins
# ---------------------------------------------------------------------------

DIST = "omniweave-office"
SHA = "sha256:" + "9a" * 32
OTHER_SHA = "sha256:" + "4b" * 32


def manifest(*, vendored: bool = False, digest: str = SHA) -> FirstPartyManifest:
    return FirstPartyManifest(
        schema=FIRST_PARTY_SCHEMA,
        release="0.4.2",
        dists={DIST: FirstPartyRow(DIST, "0.4.2", digest, vendored=vendored)},
    )


def test_trust_table_reproduces_the_plans_own_five_rows(plan) -> None:
    """`TRUST_TABLE` against section 4.2's markdown table, tier by tier, in the printed order."""
    plan.require()
    lines = plan.lines(DOC)
    start = next(i for i, line in enumerate(lines) if line.startswith("| condition | trust |"))
    rows = []
    for line in lines[start + 2 :]:
        if not line.startswith("|"):
            break
        rows.append(line.strip("|").split("|")[-1].strip().strip("`"))
    assert rows == [row[1] for row in TRUST_TABLE]
    assert rows == [tier.value for tier in TrustTier]


def test_row_1_first_party_needs_the_manifest_and_a_matching_dist_sha256() -> None:
    decision = compute_trust(
        driver_id=IDS[0],
        origin="entry_point",
        distribution=DIST,
        dist_sha256=SHA,
        manifest=manifest(),
    )
    assert (decision.tier, decision.row) == (TrustTier.FIRST_PARTY, 1)
    assert decision.degradation == ""


def test_row_1_does_not_fire_when_the_dist_sha256_has_drifted() -> None:
    """A drifted `dist_sha256` is row 5's own printed wording, not row 1's."""
    decision = compute_trust(
        driver_id=IDS[0],
        origin="entry_point",
        distribution=DIST,
        dist_sha256=OTHER_SHA,
        manifest=manifest(),
    )
    assert (decision.tier, decision.row) == (TrustTier.UNPINNED, 5)


def test_row_2_vendored_is_the_tier_that_makes_anydoc_inproc_eligible() -> None:
    """Section 4.2's own worked example, which is what forces row 1's extra conjunct.

    `omniweave-office` is first-party AND carries `firecrawl-anydoc`'s source under
    `vendor/anydoc/` at a recorded SHA, and section 4.2 says its tier is `vendored`. Under a
    literal reading of the printed table it would match row 1 first and `vendored` would be
    unreachable; see `TRUST_TABLE`'s docstring.
    """
    decision = compute_trust(
        driver_id="parse.office.anydoc",
        origin="entry_point",
        distribution=DIST,
        dist_sha256=SHA,
        manifest=manifest(vendored=True),
    )
    assert (decision.tier, decision.row) == (TrustTier.VENDORED, 2)


def test_row_2_can_be_stated_by_the_caller_rather_than_by_the_manifest() -> None:
    decision = compute_trust(
        driver_id="parse.office.anydoc",
        origin="entry_point",
        distribution=DIST,
        dist_sha256=SHA,
        manifest=manifest(vendored=False),
        vendored=True,
    )
    assert decision.tier is TrustTier.VENDORED


def test_row_3_pinned_is_the_lockfile_with_a_matching_dist_sha256() -> None:
    decision = compute_trust(
        driver_id=IDS[0],
        origin="entry_point",
        distribution="omniweave-driver-ipynb",
        dist_sha256=SHA,
        manifest=None,
        locked={IDS[0]: SHA},
    )
    assert (decision.tier, decision.row) == (TrustTier.PINNED, 3)


def test_row_3_does_not_fire_when_the_locked_dist_sha256_disagrees() -> None:
    decision = compute_trust(
        driver_id=IDS[0],
        origin="entry_point",
        distribution="omniweave-driver-ipynb",
        dist_sha256=SHA,
        locked={IDS[0]: OTHER_SHA},
    )
    assert (decision.tier, decision.row) == (TrustTier.UNPINNED, 5)


@pytest.mark.parametrize("origin", ["driver_path", "project"])
def test_row_4_local_is_an_origin_and_needs_no_file_at_all(origin: str) -> None:
    decision = compute_trust(driver_id=IDS[0], origin=origin)
    assert (decision.tier, decision.row) == (TrustTier.LOCAL, 4)
    assert decision.degradation == "", "a local driver is a choice, not a degradation"


def test_row_4_beats_the_lockfile_because_a_local_card_is_not_an_installed_distribution() -> None:
    """Row 3 is `origin == entry_point`; a `driver_path` card in the lockfile is still `local`."""
    decision = compute_trust(
        driver_id=IDS[0], origin="driver_path", dist_sha256=SHA, locked={IDS[0]: SHA}
    )
    assert (decision.tier, decision.row) == (TrustTier.LOCAL, 4)


def test_row_5_unpinned_is_an_installed_distribution_absent_from_the_lockfile() -> None:
    decision = compute_trust(
        driver_id=IDS[0], origin="entry_point", distribution="somebody-elses", dist_sha256=SHA
    )
    assert (decision.tier, decision.row) == (TrustTier.UNPINNED, 5)
    assert decision.degradation == UNPINNED_DEGRADATION


def test_first_match_wins_row_1_beats_row_3_on_a_driver_that_satisfies_both() -> None:
    """The overlap that actually happens: a first-party wheel is also in the lockfile.

    Asserting on the tier alone cannot tell "row 1 won" from "row 3 happened to agree", which is
    why `TrustDecision` carries the row.
    """
    decision = compute_trust(
        driver_id="parse.office.anydoc",
        origin="entry_point",
        distribution=DIST,
        dist_sha256=SHA,
        manifest=manifest(),
        locked={"parse.office.anydoc": SHA},
    )
    assert (decision.tier, decision.row) == (TrustTier.FIRST_PARTY, 1)


def test_first_match_wins_row_2_beats_row_3_on_a_vendored_and_locked_driver() -> None:
    decision = compute_trust(
        driver_id="parse.office.anydoc",
        origin="entry_point",
        distribution=DIST,
        dist_sha256=SHA,
        manifest=manifest(vendored=True),
        locked={"parse.office.anydoc": SHA},
    )
    assert (decision.tier, decision.row) == (TrustTier.VENDORED, 2)


def test_a_missing_release_manifest_degrades_one_trust_computation_to_unpinned() -> None:
    """11-repo-layout.md section 7.2: the state of EVERY developer's checkout, not an edge case.

    `first_party.toml` is generated into `src/` at build time and `.gitignore`d, so a workspace
    install has no manifest and no `dist_sha256` to attest. The reason says so, and the run
    records `Degradation(kind="pin")` — row 14 of 15-observability.md section 6.3's register.
    """
    decision = compute_trust(
        driver_id="parse.office.anydoc",
        origin="entry_point",
        distribution=DIST,
        dist_sha256=SHA,
        manifest=None,
    )
    assert (decision.tier, decision.row) == (TrustTier.UNPINNED, 5)
    assert decision.degradation == UNPINNED_DEGRADATION
    assert "no release manifest" in decision.reason


def test_the_packaged_manifests_absence_is_none_and_never_an_exception() -> None:
    """Section 7.2: absence degrades one trust computation and never makes anything fail.

    This checkout is the absent case by construction — `first_party.toml` is generated into `src/`
    at build time and `.gitignore`d — but the assertion is written to hold either way, because the
    `conform` job runs the same test against installed wheels where the manifest IS present.
    """
    located = first_party_path()
    assert located is None or located.name == FIRST_PARTY_NAME
    read = read_first_party()
    assert read is None or isinstance(read, FirstPartyManifest)
    assert (read is None) == (located is None)


def test_an_explicitly_named_missing_path_is_a_named_error_not_a_silent_none(
    tmp_path: Path,
) -> None:
    """Rule 3 of 11-repo-layout.md section 2.6, and the line between it and section 7.2.

    Section 7.2 excuses the PACKAGED manifest's absence, which `first_party_path()` reports as
    `None` without ever opening a file. A caller that names a path is asserting the file is there,
    and rule 3 makes that a named `OwError` carrying the command that clears it rather than a
    `FileNotFoundError` or a silent empty default.
    """
    with pytest.raises(ConfigError) as caught:
        read_first_party(tmp_path / "absent.toml")
    assert caught.value.fix == "pip install --force-reinstall omniweave-core"


def test_the_degradation_kind_is_a_member_of_the_closed_twenty_seven(plan) -> None:
    """`pin` is row 14 of 15-observability.md section 6.3's register, not an invented member."""
    plan.require()
    hits = plan.grep(rf"\| 14 \| `{UNPINNED_DEGRADATION}` \|", documents=["15-observability.md"])
    assert hits, "15-observability.md section 6.3 row 14 should be `pin`"


def test_an_origin_outside_the_card_origins_is_a_refusal_and_not_a_silent_unpinned() -> None:
    with pytest.raises(InternalError) as caught:
        compute_trust(driver_id=IDS[0], origin="somewhere_else")
    assert "somewhere_else" in str(caught.value)


def test_the_reason_names_the_row_and_the_distribution() -> None:
    """`ow drivers explain` prints it; a reason that names neither is not actionable."""
    decision = compute_trust(
        driver_id=IDS[0], origin="entry_point", distribution="somebody-elses", dist_sha256=SHA
    )
    assert "row 5" in decision.reason
    assert "somebody-elses" in decision.reason


# ---------------------------------------------------------------------------
# The release manifest reader (11-repo-layout.md sections 2.6 and 7.2)
# ---------------------------------------------------------------------------

MANIFEST = f"""schema = 1
release = "0.4.2"

[dist."omniweave-ports"]
version = "1.0.0"
dist_sha256 = "{SHA}"

[dist."omniweave-office"]
version = "0.4.2"
dist_sha256 = "{OTHER_SHA}"
vendored = true
"""


def test_a_well_formed_manifest_parses_into_rows(tmp_path: Path) -> None:
    path = tmp_path / "ok.toml"
    path.write_text(MANIFEST, encoding="utf-8")
    read = read_first_party(path)
    assert read is not None
    assert read.release == "0.4.2"
    assert set(read.dists) == {"omniweave-ports", "omniweave-office"}
    assert read.dists["omniweave-office"].vendored is True
    assert read.dists["omniweave-ports"].vendored is False


def test_core_has_no_row_and_that_is_the_correct_answer(tmp_path: Path) -> None:
    """A row asserting core's own hash would be a witness testifying to itself (section 7.2)."""
    path = tmp_path / "nocore.toml"
    path.write_text(MANIFEST, encoding="utf-8")
    read = read_first_party(path)
    assert read is not None
    assert "omniweave-core" not in read.dists


def test_an_unparseable_manifest_is_a_named_error_and_never_a_silent_empty_default(
    tmp_path: Path,
) -> None:
    """Rule 3 of 11-repo-layout.md section 2.6, and why absence and corruption differ here.

    An empty default would compute `unpinned` for a first-party wheel and read as an attestation
    failure rather than as a corrupt file.
    """
    path = tmp_path / "broken.toml"
    path.write_text("schema = 1\n[dist.\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        read_first_party(path)
    assert caught.value.fix
    assert str(path) in str(caught.value)


def test_a_manifest_from_a_future_release_is_refused_rather_than_half_read(tmp_path: Path) -> None:
    path = tmp_path / "future.toml"
    path.write_text(MANIFEST.replace("schema = 1", "schema = 2"), encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        read_first_party(path)
    assert "schema = 2" in str(caught.value)
    assert "upgrade" in caught.value.fix


@pytest.mark.parametrize(
    "digest",
    ['""', '"9a9a"', '"sha256:zz"', '"' + "9a" * 32 + '"', '"SHA256:' + "9a" * 32 + '"'],
)
def test_a_dist_sha256_that_is_not_the_prefixed_form_is_refused(
    tmp_path: Path, digest: str
) -> None:
    """The prefixed spelling is `omniweave.lock`'s and `ow drivers verify`'s; a third is a bug."""
    path = tmp_path / f"bad{abs(hash(digest))}.toml"
    path.write_text(
        f'schema = 1\nrelease = "0.4.2"\n[dist."omniweave-ports"]\ndist_sha256 = {digest}\n',
        encoding="utf-8",
    )
    with pytest.raises(ConfigError) as caught:
        read_first_party(path)
    assert "dist_sha256" in str(caught.value)


def test_a_dist_table_that_is_not_a_table_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "notatable.toml"
    path.write_text('schema = 1\nrelease = "0.4.2"\ndist = "nope"\n', encoding="utf-8")
    with pytest.raises(ConfigError):
        read_first_party(path)


def test_the_manifest_is_read_at_use_time_and_not_at_import_time(interpreter) -> None:
    """Rule 2 of 11-repo-layout.md section 2.6: a corrupt packaged file must not brick import.

    graphify's `install.py:35-57` records the reason in its own docstring — deferring to use time
    is what stops a missing block crashing every command instead of the one that needed the file.
    """
    report = interpreter.audit("import omniweave_core.drivers.catalog")
    assert not [path for path in report.non_python_files if path.endswith(".toml")], report.opened


def test_build_takes_no_arguments_because_the_cold_start_gate_times_exactly_that_call() -> None:
    """Section 4.3, section 4.4's budget table and `tools/gate_coldstart.py` all say
    `Catalog.build()`.

    The gate spawns a fresh interpreter, imports `Catalog` from this module and calls `build()`
    with no arguments; a signature needing one would make section 4.4's whole budget unmeasurable.
    """
    catalog = Catalog.build()
    assert isinstance(catalog, Catalog)
    assert re.fullmatch(r"[0-9a-f]{64}", catalog.validity_key)
    assert re.fullmatch(r"[0-9a-f]{64}", catalog.catalog_digest)


def test_build_carries_the_six_shipped_tombstones_from_step_5() -> None:
    """Step 5 of section 4.3, and section 10.4's six framework tombstones at release 1."""
    catalog = Catalog.build()
    assert len(catalog.tombstones) == 6
    assert all(stone.reason for stone in catalog.tombstones.values())


def test_build_computes_trust_which_discovery_declines_to() -> None:
    """`discover()` returns materials; trust (E13) and `catalog_digest` are this module's.

    A `driver_path` card is row 4 (`local`); an `entry_point` card with no `dist_sha256` to attest
    is row 5 (`unpinned`), which is 11-repo-layout.md section 7.2's description of a checkout.
    """
    from omniweave_core.discovery import CardSource, DiscoveredCard, Discovery  # noqa: PLC0415

    def discovered(driver_id: str, origin: str, dist: str = "") -> DiscoveredCard:
        return DiscoveredCard(
            card=card(driver_id, origin=origin),
            source=CardSource(
                origin=origin,
                path=Path(f"{driver_id}.toml"),
                card_path="d/driver.toml",
                dist_name=dist,
            ),
        )

    catalog = Catalog.build(
        Discovery(
            found=(
                discovered(IDS[0], "entry_point", "omniweave-driver-ipynb"),
                discovered(IDS[1], "driver_path"),
            ),
            validity_key=KEY,
        )
    )
    assert catalog.trust == {IDS[0]: TrustTier.UNPINNED, IDS[1]: TrustTier.LOCAL}
    assert catalog.validity_key == KEY
    assert set(catalog.probe_status.values()) == {PROBE_UNKNOWN}


def test_build_refuses_two_distributions_declaring_one_id() -> None:
    """DR3 reaches the catalog: discovery returns a tuple precisely so neither is dropped."""
    from omniweave_core.discovery import CardSource, DiscoveredCard, Discovery  # noqa: PLC0415
    from omniweave_core.registry import DuplicateDriver  # noqa: PLC0415

    def claimed(dist: str) -> DiscoveredCard:
        return DiscoveredCard(
            card=card(IDS[0]),
            source=CardSource(
                origin="entry_point",
                path=Path("d.toml"),
                card_path="d/driver.toml",
                dist_name=dist,
            ),
        )

    found = Discovery(found=(claimed("omniweave-office"), claimed("impostor")), validity_key=KEY)
    with pytest.raises(DuplicateDriver) as caught:
        Catalog.build(found)
    assert "omniweave-office" in str(caught.value)
    assert "impostor" in str(caught.value)

    disambiguated = Catalog.build(found, resolve={IDS[0]: "impostor"})
    assert set(disambiguated.cards) == {IDS[0]}


def test_build_drops_a_probe_verdict_for_a_driver_this_run_cannot_see() -> None:
    """The probe cache is a per-machine tree that outlives any one environment (section 4.7)."""
    from omniweave_core.discovery import Discovery  # noqa: PLC0415

    catalog = Catalog.build(
        Discovery(validity_key=KEY), probe_status={"parse.pdf.uninstalled": "unavailable"}
    )
    assert catalog.probe_status == {}


def test_catalog_reaches_no_filesystem_and_no_network_at_import() -> None:
    """This module is what `resolve()` reads, and `resolve()` is pure (section 4.8).

    Importing it must open nothing, connect nowhere and spawn nothing: the only route to a
    filesystem is a caller explicitly asking for one (`read_first_party`, `Catalog.build`).
    """
    report = INTERPRETER.audit("import omniweave_core.drivers.catalog")
    assert report.sockets == 0
    assert report.subprocesses == 0
    assert report.non_python_files == ()
