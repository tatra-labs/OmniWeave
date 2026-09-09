"""The six shipped tombstones, and the clock that stops them ossifying.

`omniweave_core/drivers/tombstones/*.toml` is a refusal set: six cards that exist so a vetoed
`DriverId` resolves to a QUOTED REASON and a named replacement rather than to "unknown driver"
(DR22), and so `compute_tier()` returns `forbidden` for any card whose licence hash matches one
of theirs -- hash-keyed, therefore surviving a rename. A refusal set is the kind of artefact that
is right on the day it is written and quietly wrong two years later, so there are four kinds of
test here and only the first is the obvious one:

* **the data is a tombstone**, not a driver card with holes. All six load through the real
  `load_card()` and come back as `Tombstone`; the grammar's own negatives (a `version` key, a
  `tier` key, an unknown table) are shown to be refused, because a tombstone that quietly parsed
  as something else would be a refusal nothing enforces.
* **the roster is the plan's.** The ids, the replacements and the tier column are re-derived from
  04-driver-system.md section 10.4's own markdown table rather than copied here as literals, so a
  tombstone added, dropped or re-pointed in one place and not the other fails. The two repos
  section 10.4 deliberately does NOT tombstone are asserted ABSENT, because "we considered it and
  declined" is a fact worth protecting from a well-meaning PR, and so is `parse.pdf.pymupdf`,
  whose AGPL is a decision that belongs to the operator.
* **the content is the clause, not a summary of it.** Every reason is checked for the specific
  citations 10.4 prints -- `MODEL_LICENSE:58`, `README.md:232`, `License.txt:3,17,31,35`,
  `LICENSE:29-33,82-84`, `LICENSE:1-2` -- and for the md5 the three Datalab files share. A
  1,810-line document once truncated to 491 and passed every structural check on this project; a
  reason that says "licence problems" would pass a length assertion too.
* **the gate goes red when it is shown the violation it exists for.** `tools/gate_tombstones.py`
  is exercised over synthetic trees in `tmp_path`: a date in the past, a date so far out the
  clock never fires, an empty reason, a missing card, a card for a declined id, a replacement
  that disagrees with the plan, three different Datalab digests, and an absent `replaced_by`
  whose reason does not say there is none. Each assertion names the check that must fire, not
  merely that something did.

Specified in 04-driver-system.md sections 7.5 and 10.4, 01-principles.md DR22, 17-risks.md R-L1,
11-repo-layout.md section 9.2 layer 6 and 14-security.md section 9.5.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest
from omniweave_core.drivers.card import DRIVER_ID_RE, DriverCard, Tombstone, load_card
from omniweave_core.errors import DriverHostError

if TYPE_CHECKING:
    from conftest import PlanDocs

TOMBSTONES = (
    Path(__file__).resolve().parents[2] / "src" / "omniweave_core" / "drivers" / "tombstones"
)
"""The shipped set, reached from this file rather than from the gate, so the two agree by
measurement rather than by construction."""


def _gate() -> ModuleType:
    """Load `tools/gate_tombstones.py` by path. See `test_gates_structural._load` for why.

    Never `importlib.import_module` (banned outside `host/` by `tools/semgrep/omniweave.yaml`)
    and never by putting `tools/` on `sys.path`, which would make the bare name `gate_tombstones`
    importable for the rest of the session.
    """
    path = Path(__file__).resolve().parents[4] / "tools" / "gate_tombstones.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_tombstones", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    return _gate()


@pytest.fixture(scope="module")
def cards() -> dict[str, Tombstone]:
    """Every shipped tombstone, loaded through the real grammar and keyed by id."""
    loaded: dict[str, Tombstone] = {}
    for path in sorted(TOMBSTONES.glob("*.toml")):
        card = load_card(path.read_bytes(), origin="tombstone", source=path.as_posix())
        assert isinstance(card, Tombstone), f"{path.name} loaded as {type(card).__name__}"
        loaded[card.id] = card
    return loaded


IDS = (
    "derive.code.jcodemunch",
    "parse.doc.omniparse",
    "parse.fields.lift",
    "parse.page.hunyuan",
    "parse.page.marker",
    "parse.page.surya",
)
"""The six ids, in sorted order. Only ever used to parametrise; the roster itself is checked
against the plan's table by `test_the_roster_is_the_plans_own_table`."""


# ---------------------------------------------------------------------------
# The data is a tombstone
# ---------------------------------------------------------------------------


def test_all_six_load_and_none_is_a_driver_card(cards: dict[str, Tombstone]) -> None:
    """`[tombstone]` branches BEFORE driver-card validation (04 section 7.5).

    That branch is what makes these files loadable at all: a tombstone has no `entrypoint`, no
    `schema_version`, no `granularity` and no `replay_class`, all non-optional on `DriverCard`,
    so validating one as a driver card is a guaranteed spurious `CARD_INVALID` on a file whose
    only job is to explain a refusal.
    """
    assert sorted(cards) == list(IDS)
    assert not any(isinstance(card, DriverCard) for card in cards.values())


@pytest.mark.parametrize("driver_id", IDS)
def test_dr22_every_vetoed_id_has_a_reason_and_a_future_review_by(
    cards: dict[str, Tombstone], driver_id: str
) -> None:
    """DR22, verbatim from 04 section 7.5: "a non-empty reason and a future `review_by`".

    The reason floor is 200 characters rather than 1 because DR22's point is a reason an operator
    can act on. A one-word reason satisfies "non-empty" and satisfies nobody.
    """
    card = cards[driver_id]
    assert len(card.reason.strip()) > 200, card.reason
    assert dt.date.fromisoformat(card.review_by) > dt.datetime.now(tz=dt.UTC).date()


@pytest.mark.parametrize("driver_id", IDS)
def test_the_id_the_port_and_the_filename_are_one_fact(
    cards: dict[str, Tombstone], driver_id: str
) -> None:
    """The first segment of a `DriverId` IS the Port (charter section 5 X35), and the file is
    named for the id it retires so a reader looking for a refusal finds it without opening six
    files."""
    card = cards[driver_id]
    assert DRIVER_ID_RE.match(card.id) is not None
    assert card.id.split(".", 1)[0] == card.port.value
    assert card.port_major == 1
    assert Path(card.source).stem == card.id


@pytest.mark.parametrize(
    ("insert", "fragment"),
    [
        ('version = "*"\n', "a tombstone's [driver]"),
        ("schema_version = 1\n", "a tombstone's [driver]"),
    ],
)
def test_a_tombstone_driver_table_takes_only_id_port_and_title(insert: str, fragment: str) -> None:
    """04 section 7.5: "Only three keys are legal in a tombstone's `[driver]` table".

    Section 2.1 says instead that a tombstone's `version` "is a wildcard, which is not semver",
    which implies the key is present; `card.py` implements 7.5's explicit enumeration and records
    the disagreement. This test pins the behaviour that shipped, so the two cannot drift silently
    while the plan is being reconciled.
    """
    raw = (TOMBSTONES / "parse.page.surya.toml").read_bytes()
    mutated = raw.replace(b'port  = "parse/1"\n', b'port  = "parse/1"\n' + insert.encode())
    assert mutated != raw
    with pytest.raises(DriverHostError) as caught:
        load_card(mutated, origin="tombstone", source="surya")
    assert caught.value.code() == "OW_CARD_INVALID"
    assert fragment in str(caught.value)


def test_a_tier_key_is_refused_because_the_tier_is_computed() -> None:
    """The card carries FACTS; `compute_tier()` computes the tier, so an author cannot mislabel
    (04 section 7.1, DR15).

    Worth its own test because an earlier charter draft printed a tombstone with
    `[tombstone] tier = "forbidden"`, and 10.4's table has a `tier` column -- which is that
    computation's output and not a card key. A card that could state its own tier would make
    `ow drivers check`'s "stored tier differs from the computed one" check compare a value with
    itself.
    """
    raw = (TOMBSTONES / "parse.page.surya.toml").read_bytes()
    mutated = raw.replace(b"[tombstone]\n", b'[tombstone]\ntier = "forbidden"\n')
    with pytest.raises(DriverHostError) as caught:
        load_card(mutated, origin="tombstone", source="surya")
    assert caught.value.code() == "OW_CARD_INVALID"
    assert "[tombstone]" in str(caught.value)


def test_no_tombstone_declares_an_attestation(cards: dict[str, Tombstone]) -> None:
    """`attestation` is written by `ow conform` over a conformance run. A tombstone has no
    driver to run, so an attested tombstone would be a conformance claim about nothing."""
    assert [card.id for card in cards.values() if card.attestation is not None] == []
    assert not any(card.attested for card in cards.values())


# ---------------------------------------------------------------------------
# The roster is the plan's
# ---------------------------------------------------------------------------

_ROW = re.compile(r"^\|\s*`([a-z.]+)`\s*\|\s*(\*none\*|`[a-z.]+`)\s*\|\s*(\w+)\s*\|")


def _plan_roster(plan: PlanDocs) -> dict[str, tuple[str | None, str]]:
    """04 section 10.4's table, re-derived: id -> (replaced_by or None, tier)."""
    lines = plan.lines("04-driver-system.md")
    start = next(i for i, line in enumerate(lines) if line.startswith("### 10.4 Tombstones"))
    rows: dict[str, tuple[str | None, str]] = {}
    for line in lines[start:]:
        if line.startswith("### ") and not line.startswith("### 10.4"):
            break
        match = _ROW.match(line)
        if match is None:
            continue
        replaced = None if match.group(2) == "*none*" else match.group(2).strip("`")
        rows[match.group(1)] = (replaced, match.group(3))
    return rows


def test_the_roster_is_the_plans_own_table(plan: PlanDocs, cards: dict[str, Tombstone]) -> None:
    """The shipped set is 04 section 10.4's table, re-parsed rather than restated.

    Section 7.5 closes with "The six tombstones shipped at release 1 are in section 10.4", so the
    count, the ids and the replacements are all the document's. Copying them here as literals
    would put a second home under one fact (INV-21) and would go stale in exactly the direction
    that matters: silently permitting an id the plan vetoes.
    """
    plan.require()
    roster = _plan_roster(plan)
    assert len(roster) == 6, roster
    assert sorted(roster) == sorted(cards)
    for driver_id, (replaced, tier) in roster.items():
        assert cards[driver_id].replaced_by == replaced, driver_id
        assert tier == "forbidden", driver_id


def test_the_gate_roster_agrees_with_the_plan(plan: PlanDocs, gate: ModuleType) -> None:
    """`tools/gate_tombstones.py`'s `SHIPPED` is the CI half of the same table.

    Two halves of one property is two chances to be subtly different, which is why they are made
    to meet here rather than trusted apart.
    """
    plan.require()
    roster = {name: replaced for name, (replaced, _) in _plan_roster(plan).items()}
    assert roster == gate.SHIPPED


@pytest.mark.parametrize("declined", ["Unlimited-OCR", "Ollama-OCR", "parse.pdf.pymupdf"])
def test_the_declined_repositories_are_not_tombstoned(
    cards: dict[str, Tombstone], gate: ModuleType, declined: str
) -> None:
    """Three ids considered for a tombstone and refused one, on the record.

    Unlimited-OCR and Ollama-OCR because the objection is SUPPLY CHAIN and a tombstone is a
    licence instrument -- neither was ever shipped, so there is nothing to retire, and both are
    refused by `require_lock`, by G3 and by `[licence] allow_tiers` when their transitive AGPL
    surfaces (04 section 10.4). `parse.pdf.pymupdf` because AGPL code computes `restricted` and
    an operator running internally may knowingly accept it: tombstoning it would remove a
    decision that is theirs to make, which is the whole reason `restricted` and `forbidden` are
    different tiers (04 section 7.5).
    """
    assert declined not in cards
    assert declined in gate.NOT_TOMBSTONED
    assert gate.NOT_TOMBSTONED[declined].strip()


def test_the_declined_reasons_are_the_plans(plan: PlanDocs) -> None:
    """The two supply-chain refusals are stated in 04 section 10.4's closing paragraph, and the
    facts that make them supply-chain rather than licence are specific: a 12.4 MB unsigned
    prebuilt wheel, and an abandoned unpinned tree with transitive AGPL."""
    plan.require()
    text = plan.text("04-driver-system.md")
    assert "12.4 MB unsigned prebuilt sglang wheel" in text
    assert "MIT, abandoned, unpinned, AGPL PyMuPDF transitively" in text
    assert "`parse.pdf.pymupdf` is **not** tombstoned" in text


# ---------------------------------------------------------------------------
# The licence seeds
# ---------------------------------------------------------------------------


def _seeds(card: Tombstone) -> tuple[str, ...]:
    facts = (card.licence_code, card.licence_weights)
    return tuple(f.licence_sha256 for f in facts if f is not None and f.licence_sha256)


def test_the_three_datalab_tombstones_share_one_licence_hash(
    cards: dict[str, Tombstone], gate: ModuleType
) -> None:
    """`md5sum marker/MODEL_LICENSE surya/MODEL_LICENSE lift/MODEL_LICENSE` returns ONE digest
    three times (04 section 10.4), and that byte-identity is the whole reason the forbidden set
    is keyed on a hash rather than on an id: three distributions, three driver ids, one licence
    file. Three different digests here would look correct and would stop surviving a rename."""
    assert gate.DATALAB_TOMBSTONES == ("parse.fields.lift", "parse.page.marker", "parse.page.surya")
    values = {name: _seeds(cards[name]) for name in gate.DATALAB_TOMBSTONES}
    assert len(set(values.values())) == 1, values
    assert set(values.values()) == {(gate.DATALAB_LICENCE_SEED,)}


def test_only_those_three_carry_the_datalab_seed(
    cards: dict[str, Tombstone], gate: ModuleType
) -> None:
    """`parse.doc.omniparse` pulls marker-pdf, surya-ocr and texify and is therefore triply
    encumbered -- but it does not restate their licence hash. It is one file, seeded once per
    distribution that ships it, and a fourth copy would break 10.4's own "the THREE Datalab
    tombstones additionally seed the known-bad weights hash set"."""
    carriers = {name for name, card in cards.items() if gate.DATALAB_LICENCE_SEED in _seeds(card)}
    assert carriers == set(gate.DATALAB_TOMBSTONES)
    assert "marker-pdf" in cards["parse.doc.omniparse"].reason
    assert "e1f69b64dee2f1641a9b1ab12adf24d6" in cards["parse.doc.omniparse"].reason


@pytest.mark.parametrize("driver_id", IDS)
def test_every_tombstone_carries_exactly_one_well_formed_seed(
    cards: dict[str, Tombstone], gate: ModuleType, driver_id: str
) -> None:
    """One seed each, on the code side or the weights side (04 section 7.5 keys on either), and
    never the empty string.

    The empty string is the hazard this test exists for. A forbidden set built by unioning
    `[licence.code].licence_sha256` and `[licence.weights].licence_sha256` over these six files
    would, if `""` reached it, match every card that omits its own digest -- turning
    `compute_tier()`'s narrowest check into a blanket `forbidden`. Two of the six ship no weights
    at all, so this is not hypothetical: it is what would happen if their absent
    `[licence.weights]` were spelled as an empty one.
    """
    found = _seeds(cards[driver_id])
    assert len(found) == 1, found
    assert found[0] != ""
    assert gate.SEED_RE.match(found[0]) is not None, found


def test_the_seed_set_holds_no_empty_string(cards: dict[str, Tombstone]) -> None:
    """The same property stated over the union, which is the shape `compute_tier()` will build."""
    union = {seed for card in cards.values() for seed in _seeds(card)}
    assert "" not in union
    assert len(union) == 4, sorted(union)


# ---------------------------------------------------------------------------
# The content is the clause
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("driver_id", "must_contain"),
    [
        (
            "parse.page.surya",
            ("e1f69b64dee2f1641a9b1ab12adf24d6", "2(c)", ":58", ":56-57", ":39", ":41", "olmocr"),
        ),
        ("parse.page.marker", ("md5sum", "e1f69b64dee2f1641a9b1ab12adf24d6", "2(c)", ":58")),
        ("parse.fields.lift", ("lift/README.md:232", "competitively with our API", "$5M")),
        (
            "parse.page.hunyuan",
            ("License.txt:3,17,31,35", "Territory", "100-million-MAU", "AUP 12/14"),
        ),
        (
            "derive.code.jcodemunch",
            ("LICENSE:29-33,82-84", "$1,999", "package registry, index, marketplace, or app store"),
        ),
        (
            "parse.doc.omniparse",
            ("omniparse/LICENSE:1-2", "pyproject.toml:6", "GPL-3.0", "Apache", "anydoc"),
        ),
    ],
)
def test_each_reason_carries_the_citation_the_plan_prints(
    cards: dict[str, Tombstone], driver_id: str, must_contain: tuple[str, ...]
) -> None:
    """A reason is evidence, so it cites the clause rather than characterising it.

    These strings are 04 section 10.4's own, and they are the difference between a refusal an
    operator's counsel can check in ten minutes and a refusal they have to take on trust. A
    summary would satisfy every structural assertion in this file and none of this one.
    """
    reason = cards[driver_id].reason
    missing = [fragment for fragment in must_contain if fragment not in reason]
    assert missing == [], f"{driver_id} reason omits {missing}"


def test_the_competitor_bar_is_not_recorded_as_a_revenue_gate(
    cards: dict[str, Tombstone],
) -> None:
    """The single most quoted mistake about this licence, refused as data.

    R-L1: the "$5M startup exemption" everyone quotes is Attachment A clauses 2(a) and 2(b) at
    `marker/MODEL_LICENSE:56-57`, a DIFFERENT clause from 2(c) at `:58`, which has no revenue
    threshold, no funding threshold and no research carve-out. A card recording
    `revenue_gate_usd = 5_000_000` here would compute `restricted` -- acknowledgeable -- instead
    of the bar that no configuration satisfies.
    """
    for name in ("parse.page.surya", "parse.page.marker", "parse.fields.lift"):
        weights = cards[name].licence_weights
        assert weights is not None
        assert weights.revenue_gate_usd == 0, name
        assert weights.competitor_bar is True, name
        assert weights.output_share_alike is True, name
        assert weights.remote_kill_switch is True, name
        assert weights.attribution_per_output is True, name


def test_hunyuans_jurisdiction_facts_are_present_and_include_our_own_field_of_use(
    cards: dict[str, Tombstone],
) -> None:
    """The territorial row. 14-security.md section 9.5: "Territory excludes EU/UK/KR **including
    the Output**; 100M-MAU gate; no distillation; AUP 12/14 bar the enterprise document market".

    `enterprise_documents` is in `field_of_use_excluded` because it is omniweave's own shipped
    `fields_of_use` (04 section 7.4's posture report verdict line). Recording the AUP's four
    sectors and omitting the one that bars omniweave itself would clear the driver over the only
    field it cannot be used in.
    """
    weights = cards["parse.page.hunyuan"].licence_weights
    assert weights is not None
    assert weights.territory_excluded == ("EU", "UK", "KR")
    assert weights.mau_gate == 100_000_000
    assert weights.no_model_training is True
    assert "enterprise_documents" in weights.field_of_use_excluded
    assert {"insurance", "credit", "health", "employment"} <= set(weights.field_of_use_excluded)


def test_a_missing_replacement_is_stated_rather_than_omitted(
    cards: dict[str, Tombstone], gate: ModuleType
) -> None:
    """The grammar spells "no successor" as an ABSENT `replaced_by`, and an absent key is also
    how a card spells "nobody wrote one down".

    `card.py`'s `_tombstone_replacement()` resolves the ambiguity in prose -- "`replaced_by` may
    be omitted only when there is no successor; then `reason` says so" -- and this is the half
    that makes "then `reason` says so" checkable. The two rows 10.4 marks *none* are
    `parse.fields.lift` and `derive.code.jcodemunch`.
    """
    without = {name for name, card in cards.items() if card.replaced_by is None}
    assert without == {"parse.fields.lift", "derive.code.jcodemunch"}
    for name in without:
        assert gate.NO_REPLACEMENT in cards[name].reason, name


# ---------------------------------------------------------------------------
# The gate goes red when it is shown the violation it exists for
# ---------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A writable copy of the shipped set, so a mutation test never touches the real one."""
    root = tmp_path / "tombstones"
    root.mkdir()
    for path in sorted(TOMBSTONES.glob("*.toml")):
        (root / path.name).write_bytes(path.read_bytes())
    return root


NOW = dt.date(2026, 9, 20)
"""A fixed 'today' for the gate tests. The gate takes `now` as an argument precisely so its
own tests are not a function of the day they run: a clock test that passes only in September is
the failure mode the clock exists to prevent, reproduced inside its own test suite."""


def _swap(root: Path, name: str, old: bytes, new: bytes) -> None:
    path = root / f"{name}.toml"
    raw = path.read_bytes()
    assert old in raw, f"{name}: {old!r} not present to mutate"
    path.write_bytes(raw.replace(old, new, 1))


def test_the_gate_is_green_on_head(gate: ModuleType) -> None:
    """`uv run tools/gate_tombstones.py` on the shipped tree, at the real wall clock."""
    assert gate.main([]) == gate.EXIT_CLEAN


def test_the_gate_refuses_arguments_rather_than_ignoring_them(gate: ModuleType) -> None:
    """Exit 2 is "the gate did not run", distinguished from exit 1 "the property is false"."""
    with pytest.raises(SystemExit) as caught:
        gate.main(["--as-of", "2020-01-01"])
    assert caught.value.code == 2


def test_the_gate_is_green_on_the_copied_tree(gate: ModuleType, tree: Path) -> None:
    """The fixture itself has to be clean, or every red below proves nothing."""
    assert gate.audit(tree, NOW) == []


def test_a_tombstone_past_its_review_by_fails(gate: ModuleType, tree: Path) -> None:
    """The clock, and the reason this gate exists: CI **fails** a tombstone past its `review_by`
    date, so the refusal set cannot silently ossify (04 section 7.5)."""
    _swap(tree, "parse.page.surya", b'review_by   = "2026-12-03"', b'review_by   = "2026-09-19"')
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("review_by", "parse.page.surya")]
    assert "is not in the future as of 2026-09-20" in findings[0].detail
    assert "Re-READ the licence" in findings[0].detail


def test_a_review_by_on_the_day_itself_is_already_late(gate: ModuleType, tree: Path) -> None:
    """`> now`, not `>= now`: a card whose review falls due today has not been re-read today."""
    _swap(tree, "parse.page.marker", b'review_by   = "2026-12-03"', b'review_by   = "2026-09-20"')
    assert [f.check for f in gate.audit(tree, NOW)] == ["review_by"]


def test_a_review_by_far_enough_out_never_fires_and_fails(gate: ModuleType, tree: Path) -> None:
    """ "A future date" alone is not a clock. `review_by = "2099-01-01"` satisfies the future test
    forever, which is 17-risks.md section 1 rule 4's `review_by - reviewed_at <=
    review_every_days` restated: a review interval longer than the cadence is not a review."""
    _swap(tree, "parse.fields.lift", b'review_by = "2026-12-03"', b'review_by = "2099-01-01"')
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("review_by", "parse.fields.lift")]
    assert f"more than {gate.REVIEW_EVERY_DAYS} days" in findings[0].detail


def test_an_unreadable_review_by_fails_rather_than_being_skipped(
    gate: ModuleType, tree: Path
) -> None:
    """A clock nobody can read is a clock that never fires, so it is a finding and not a pass."""
    _swap(tree, "parse.page.hunyuan", b'review_by   = "2026-12-03"', b'review_by   = "soon"')
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("review_by", "parse.page.hunyuan")]
    assert "not a YYYY-MM-DD date" in findings[0].detail


def test_a_vetoed_id_with_an_empty_reason_fails(gate: ModuleType, tree: Path) -> None:
    """DR22's other half: a vetoed id resolves to a QUOTED REASON, never to "unknown driver"."""
    path = tree / "derive.code.jcodemunch.toml"
    raw = path.read_text(encoding="utf-8")
    head, _, _ = raw.partition("reason = ")
    path.write_text(f'{head}reason = ""\nreview_by = "2026-12-03"\n', encoding="utf-8")
    findings = gate.audit(tree, NOW)
    checks = {(f.check, f.subject) for f in findings}
    assert ("reason", "derive.code.jcodemunch") in checks
    assert any("QUOTED REASON" in f.detail for f in findings)


def test_a_missing_tombstone_fails(gate: ModuleType, tree: Path) -> None:
    """A vetoed id with no tombstone resolves to "unknown driver", which is what DR22 forbids."""
    (tree / "parse.page.surya.toml").unlink()
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("roster", "parse.page.surya")]
    assert "'unknown driver'" in findings[0].detail


def test_a_tombstone_for_a_declined_id_fails(gate: ModuleType, tree: Path) -> None:
    """`parse.pdf.pymupdf` under a tombstone is a silent policy change: it takes a decision that
    belongs to the operator (04 sections 7.5 and 10.4). The gate refuses it twice -- once as an
    id outside 10.4's table, once by name as a declined one."""
    raw = (tree / "parse.doc.omniparse.toml").read_text(encoding="utf-8")
    raw = raw.replace('id    = "parse.doc.omniparse"', 'id    = "parse.pdf.pymupdf"')
    (tree / "parse.pdf.pymupdf.toml").write_text(raw, encoding="utf-8")
    findings = gate.audit(tree, NOW)
    checks = {(f.check, f.subject) for f in findings}
    assert ("roster", "parse.pdf.pymupdf") in checks
    assert ("declined", "parse.pdf.pymupdf") in checks
    assert any("a decision that is theirs to make" in f.detail for f in findings)


def test_a_replacement_that_disagrees_with_the_plan_fails(gate: ModuleType, tree: Path) -> None:
    """Re-pointing a refusal at a different successor is a plan change, not an edit."""
    _swap(
        tree,
        "parse.page.surya",
        b'replaced_by = "parse.page.olmocr"',
        b'replaced_by = "parse.page.marker"',
    )
    findings = gate.audit(tree, NOW)
    assert ("replaced_by", "parse.page.surya") in {(f.check, f.subject) for f in findings}


def test_dropping_replaced_by_without_saying_so_fails(gate: ModuleType, tree: Path) -> None:
    """An absent `replaced_by` and a reason that does not say there is none are indistinguishable
    from a card nobody finished."""
    _swap(tree, "parse.doc.omniparse", b'replaced_by = "parse.office.anydoc"\n', b"")
    findings = gate.audit(tree, NOW)
    checks = {(f.check, f.subject) for f in findings}
    assert ("replaced_by", "parse.doc.omniparse") in checks
    assert any(gate.NO_REPLACEMENT in f.detail for f in findings)


def test_three_different_datalab_digests_fail(gate: ModuleType, tree: Path) -> None:
    """The byte-identical-file property, defended. Three distinct digests would still look like a
    working seed set and would no longer survive a rename, which is the one thing hash-keying
    buys (04 section 7.5)."""
    _swap(
        tree,
        "parse.page.marker",
        b"unresolved:md5=e1f69b64dee2f1641a9b1ab12adf24d6",
        b"sha256:" + b"a" * 64,
    )
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("datalab", "parse.page.marker")]
    assert "share ONE MODEL_LICENSE file" in findings[0].detail


def test_a_fourth_carrier_of_the_datalab_digest_fails(gate: ModuleType, tree: Path) -> None:
    """One file, seeded once per distribution that ships it. A fourth copy makes 10.4's "the
    three Datalab tombstones" false and puts one fact in four places (INV-21)."""
    _swap(
        tree,
        "parse.doc.omniparse",
        b'licence_sha256 = "unresolved:omniparse/LICENSE"',
        b'licence_sha256 = "unresolved:md5=e1f69b64dee2f1641a9b1ab12adf24d6"',
    )
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("datalab", "parse.doc.omniparse")]
    assert "state a transitive encumbrance in the reason" in findings[0].detail


def test_an_empty_licence_seed_fails(gate: ModuleType, tree: Path) -> None:
    """A tombstone with no seed does only half its job, and an empty-string seed would do worse
    than none: it matches every card that omits its own digest."""
    _swap(
        tree,
        "parse.page.hunyuan",
        b'licence_sha256        = "unresolved:HunyuanOCR/License.txt"\n',
        b"",
    )
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("licence_sha256", "parse.page.hunyuan")]
    assert "hash-keyed" in findings[0].detail


def test_a_seed_that_is_neither_a_digest_nor_a_marked_unknown_fails(
    gate: ModuleType, tree: Path
) -> None:
    """`sha256:<64 hex>` or an explicit `unresolved:<what to fetch>`, and nothing else. A bare
    md5, a truncated digest or the word "TODO" would all sit in the forbidden set looking like a
    hash and matching nothing."""
    _swap(
        tree,
        "parse.page.surya",
        b"unresolved:md5=e1f69b64dee2f1641a9b1ab12adf24d6",
        b"e1f69b64dee2f1641a9b1ab12adf24d6",
    )
    findings = gate.audit(tree, NOW)
    checks = {(f.check, f.subject) for f in findings}
    assert ("licence_sha256", "parse.page.surya") in checks
    assert ("datalab", "parse.page.surya") in checks


def test_a_file_not_named_for_its_id_fails(gate: ModuleType, tree: Path) -> None:
    """Six refusals in one directory: the filename is how a reader finds the one they want."""
    (tree / "parse.page.surya.toml").rename(tree / "surya.toml")
    findings = gate.audit(tree, NOW)
    assert [(f.check, f.subject) for f in findings] == [("filename", "parse.page.surya")]


def test_the_gate_reports_not_run_when_the_directory_is_absent(
    gate: ModuleType, tmp_path: Path
) -> None:
    """Exit 2, not exit 1: an absent directory is "the gate did not run", and a CI log that
    cannot tell those apart sends a human to read the wrong file."""
    with pytest.raises(NotADirectoryError):
        gate.load_tombstones(tmp_path / "nowhere")


def test_every_shipped_review_by_is_the_same_date(cards: dict[str, Tombstone]) -> None:
    """One date for all six, on purpose: the refusal set is re-read in one sitting rather than
    six, which is what "re-read rather than inherited" means. The date is R-L1's own
    `review_by` from 17-risks.md section 1, because this set is R-L1's second mitigation and
    firing on a different day would make the licence owner read the same evidence twice."""
    assert {card.review_by for card in cards.values()} == {"2026-12-03"}


def test_the_review_interval_is_the_registers_cadence(plan: PlanDocs, gate: ModuleType) -> None:
    """`REVIEW_EVERY_DAYS` is not a number this cluster chose: it is 17-risks.md section 1's
    `[register] review_every_days`, and 2026-12-03 is R-L1's own `review_by` in the same fence."""
    plan.require()
    text = plan.text("17-risks.md")
    assert f"review_every_days = {gate.REVIEW_EVERY_DAYS}" in text
    assert 'reviewed_at = "2026-09-04"' in text
    assert 'review_by   = "2026-12-03"' in text
    assert (dt.date(2026, 12, 3) - dt.date(2026, 9, 4)).days == gate.REVIEW_EVERY_DAYS


# ---------------------------------------------------------------------------
# The set is package data, and it reaches the wheel
# ---------------------------------------------------------------------------


def test_the_directory_is_package_data_and_not_a_module() -> None:
    """No `__init__.py` here, and nothing imports a tombstone.

    A tombstone is read by `Catalog.build()` at step 5 the way any other card is read -- as
    bytes, through `load_card()`. Making the directory a package would put six licence readings
    on the import graph, and `omniweave_core/drivers/__init__.py` is asserted docstring-only by
    `test_core_eager_surface.py` precisely so that `omniweave_core.drivers.card` is imported
    directly and nothing is re-exported.
    """
    assert not (TOMBSTONES / "__init__.py").exists()
    assert sorted(p.suffix for p in TOMBSTONES.iterdir()) == [".toml"] * 6


def test_the_wheel_configuration_ships_them() -> None:
    """`[tool.hatch.build.targets.wheel] packages = ["src/omniweave_core"]` includes every file
    under the package, not only `*.py`, which is what puts these six in the wheel -- verified by
    building it. Asserted here because the six are DATA: a build config narrowed to Python
    sources would ship a core whose refusal set is empty, and an empty refusal set fails open.
    """
    core = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = core.read_text(encoding="utf-8")
    assert 'packages = ["src/omniweave_core"]' in text
    assert "only-include" not in text
    assert 'include = ["src"' in text
