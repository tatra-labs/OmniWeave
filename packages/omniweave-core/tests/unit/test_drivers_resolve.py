"""`resolve()` — the gate order, the floors, `RejectCode`'s bijection with `codes.toml`, purity.

Every property here is a sentence from a plan document, and where the document is the authority
the test READS the document rather than restating it: the gate order is re-derived from
04-driver-system.md's own printed fence, and the `RejectCode` membership from section 5.3's own
table. That is deliberate — the two numbers the plan states about this module (16-roadmap.md:481's
"eight gates" and 04-driver-system.md:1557's "Twenty-five `RejectCode` members") are both wrong
against the enumerations beside them, so a test that trusted a tally would have shipped the tally's
error. `test_the_reject_code_count_the_prose_states_disagrees_with_its_own_table` pins that finding
so it cannot be quietly lost.

The families, and what each is for:

* **the gate order** — 04-driver-system.md:1340-1360 is the definition site, the order is
  observable because it decides which code a driver failing several gates reports, and that code
  is what `ow drivers explain` prints. FIVE tests assert the earlier code wins across five
  different pairs of gates, so the property is not carried by one lucky pair, and the whole
  nineteen-name order is pinned as a literal beside the document-derived test — because that test
  drops the three codes section 4.8's fence does not print before comparing, which left the three
  positions that are our engineering call unpinned by anything.
* **`RejectCode` <-> `OW-D-nnn`** — 01-principles.md:605 names "a new `RejectCode` member with no
  `OW-D-nnn` row" as a defect class. The bijection is asserted strictly in both directions: the
  forward direction over every member's symbol, and the reverse against a pinned literal of the
  three `OW-D` rows that are deliberately not `RejectCode` members. The forward half used to skip
  while the register was unwritten, which made it a test that could not fail; the rows landed with
  W3.1 and the skip is gone.
* **DR5** — 01-principles.md:210 makes a typed `RejectCode` *required to construct* a
  `Resolution`. That is a type-level obligation, so the tests construct the illegal values and
  assert the constructor refuses: a missing code, a bare string in its place, an empty detail, and
  a `Resolution` whose `rejected` holds something that is not a `Rejection`.
* **the floors** — 04-driver-system.md section 2.2 is a per-field comparison table and each row is
  a test. The three named bugs are each asserted as bugs that do not happen, over **all four**
  Ports that declare a ladder and not over `parse` alone: an ordered field compared as a boolean
  (every rung is truthy, so a boolean comparison passes every floor), a set compared with `==`,
  and `forfeits` compared the way `math` is. Plus the roadmap's own assertion: a floor is a filter
  and never a ranking key, tested TWICE — with the richer card sorting last and with it sorting
  first — because two candidates admit two orders and one direction of a ranking always coincides
  with the lexical one.
* **purity** — a pinned import set over the module's `ast` (the assertion that fails the moment
  something in here can probe, import or spawn), the `pure_unit` side-effect guard over a real
  `resolve()` call, an environment-and-cwd invariance test, and a hundred deterministic catalog
  permutations through `resolve_uncached()`. `resolve()` returning the same object twice is
  asserted separately and as *memoisation*, which is what it is.
* **the memo key** — 13-quality.md section 2.4's four allocated `capability` properties, one per
  `Requirement` field the charter's six-tuple omitted, plus a pinned field-name literal so that a
  ninth field cannot be added without this file noticing.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import importlib.util
import re
import sys
import tomllib
from io import StringIO
from pathlib import Path

import pytest
from omniweave_core.canonical import sha256_canonical
from omniweave_core.drivers import resolve as resolve_module
from omniweave_core.drivers.card import (
    ACQUIRE_LADDERS,
    DERIVE_LADDERS,
    EMBED_LADDERS,
    PARSE_BOOLS,
    PARSE_LADDERS,
    PARSE_SETS,
    PORT_RE,
    DriverCard,
    Tombstone,
    load_card,
)
from omniweave_core.drivers.catalog import Catalog
from omniweave_core.drivers.licence import (
    TIER_ORDER,
    Ack,
    AckSet,
    AckWhich,
    LicenceSeeds,
)
from omniweave_core.drivers.resolve import (
    COST_CLASS_ORDER,
    FLOOR_KINDS,
    GATE_ORDER,
    INPROC_TRUST,
    ISOLATION_CONTAINMENT,
    PORT_MAJORS_SUPPORTED,
    RESOLVE_DEGRADATION_KINDS,
    RESOLVE_MEMO_MAX,
    Candidate,
    FloorKind,
    Policy,
    RejectCode,
    Rejection,
    Requirement,
    Resolution,
    ResolveDegradation,
    clear_memo,
    considered_ids,
    floor_kind,
    meets_floor,
    memo_stats,
    resolution_report,
    resolve,
    resolve_uncached,
)
from omniweave_ports.types import (
    ArtifactKind,
    CostClass,
    Isolation,
    LicenceTier,
    Port,
    ProbeEnv,
    TrustTier,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
TOOL_PATH = REPO_ROOT / "tools" / "ow_drivers.py"

# The runner is a script in `tools/`, not a distribution, so there is no package to import
# it from. `spec_from_file_location` loads it by path -- the same mechanism
# `test_gate_crash.py` uses, and for the same two reasons: not `importlib.import_module`,
# which is banned outside `host/`, and not a `sys.path` mutation, which would leak into
# every later test.
_SPEC = importlib.util.spec_from_file_location("omniweave_ow_drivers", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover -- the file is in this repo.
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
runner = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)


RESOLVE_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "omniweave_core" / "drivers" / "resolve.py"
)

# The gate count, written out. 04-driver-system.md:1340-1360 prints SIXTEEN filters; three more
# exist because section 5.3:1563 files `PORT_MISMATCH`, `ID_COLLISION_UNQUALIFIED` and
# `DEPRECATED_REMOVED` under "resolve — identity" and the printed order places none of them. 16 + 3.
GATE_COUNT = 19

# The WHOLE order, written out, gate name by gate name.
#
# WHY THIS LITERAL EXISTS AND WHY THE DOCUMENT-DERIVED TEST BESIDE IT IS NOT ENOUGH.
# `test_the_gate_order_reproduces_the_documents_own_printed_filter_order` compares only the codes
# 04-driver-system.md:1340-1360 PRINTS, and therefore drops `PORT_MISMATCH`,
# `ID_COLLISION_UNQUALIFIED` and `DEPRECATED_REMOVED` before comparing. That leaves the three
# gates whose position is our engineering call unpinned by every other test in this file: moving
# `not_removed` from position 5 to position 19, or swapping `port_matches_requirement` with
# `id_unambiguous`, changed which `RejectCode` a driver failing several gates reports and no test
# went red. Both were verified as surviving mutations before this literal was written. The order is
# observable — it decides what `ow drivers explain` prints (:1340) — so it is pinned here as a
# literal rather than read back off the subject, and the three positions marked OURS are the three
# `Gate.plan` strings that say `ORDER IS OURS`.
GATE_NAMES_IN_ORDER = (
    "port_major_supported",
    "port_matches_requirement",  # OURS
    "id_unambiguous",  # OURS
    "not_tombstoned",
    "not_removed",  # OURS
    "card_schema_supported",
    "format_supported",
    "produces_sufficient",
    "granularity_matches",
    "capability_floors_met",
    "licence_allowed_and_acknowledged",
    "cost_class_permitted",
    "hardware_satisfiable",
    "witness_set_or_cohort",
    "probe_not_unavailable",
    "not_quarantined",
    "attested_or_pinned",
    "in_lockfile",
    "isolation_grantable",
)

# Every Port that declares an ORDERED capability field, with the card module's ladder table. The
# mapping is written out here rather than imported from `resolve._PORT_LADDERS`, because a test
# that read the subject's own per-Port mapping would compare that mapping with itself; the ladder
# CONTENTS are `card.py`'s and are imported, since the rungs are one fact with one home (INV-21).
# `compile` is absent: 04-driver-system.md section 10.3 leaves `[capability.compile]` to
# 09-generation.md and `FLOOR_KINDS[Port.COMPILE]` is empty by intent.
PORT_LADDERS = {
    Port.PARSE: PARSE_LADDERS,
    Port.ACQUIRE: ACQUIRE_LADDERS,
    Port.DERIVE: DERIVE_LADDERS,
    Port.EMBED: EMBED_LADDERS,
}

# 04-driver-system.md:1562-1568's table, counted: 3 discovery + 5 identity + 5 fit + 6 policy
# + 5 environment + 1 preflight + 1 activate.
REJECT_CODE_COUNT = 26

# The four rows `codes.toml` carries today for a `RejectCode` member, as numeric/symbol pairs read
# off the register at P1. Written out rather than derived so this is a pin and not an agreement.
REGISTERED_ROWS = {
    RejectCode.FORMAT_UNSUPPORTED: ("OW-D-009", "OW_DRIVER_FORMAT_UNSUPPORTED"),
    RejectCode.CARD_INVALID: ("OW-D-010", "OW_CARD_INVALID"),
    RejectCode.CARD_ENTRYPOINT_MALFORMED: ("OW-D-011", "OW_CARD_ENTRYPOINT_MALFORMED"),
    RejectCode.CARD_SCHEMA_TOO_NEW: ("OW-D-012", "OW_CARD_SCHEMA_TOO_NEW"),
}

# `OW-D` rows that are deliberately NOT `RejectCode` members, each with the reason. A member added
# for one of these three without amending the plan fails `test_no_ow_d_row_is_claimed_twice`.
NON_MEMBER_OW_D = {
    "OW-D-013": "a duplicate id at DISCOVERY; resolve()'s code is ID_COLLISION_UNQUALIFIED",
    "OW-D-024": "a format-token collision at ACTIVATION (04-driver-system.md:546)",
    "OW-D-051": "an unclassified driver message at RUNTIME (08-runtime.md:549)",
}

# `Requirement`'s eight fields, written out. 04-driver-system.md:1404 calls them "the charter's
# eight fields, unchanged" and :1397 names the four the charter's memo tuple omitted. A ninth
# field enters `Requirement.digest` by construction (`fields()`), and this literal is what makes
# somebody look at 13-quality.md section 2.4's property list when one appears.
REQUIREMENT_FIELDS = (
    "port",
    "format",
    "floors",
    "max_cost_class",
    "granularity",
    "input_kind",
    "requires_produces",
    "pinned",
)

# The module roots `resolve.py` may import. This is the purity assertion: nothing here can probe,
# import a driver, spawn, read a clock, touch the filesystem or reach the network, and adding an
# import that could is what makes this test red. 04-driver-system.md:1248-1253 is the reason.
ALLOWED_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "dataclasses",
        "enum",
        "re",
        "types",
        "typing",
        "omniweave_ports",
        "omniweave_core",
    }
)

# `omniweave_core` submodules `resolve.py` may reach. `probe`, `host`, `discovery` and `store` are
# absent on purpose: a probe verdict is an INPUT (section 4.7), `activate()` is the only site that
# imports a card's entrypoint (02-architecture.md:237), and G17 keeps the nine lazy names lazy.
ALLOWED_CORE_MODULES = frozenset(
    {
        "omniweave_core.canonical",
        "omniweave_core.contract",
        "omniweave_core.drivers.card",
        "omniweave_core.drivers.catalog",
        "omniweave_core.drivers.licence",
        "omniweave_core.errors",
    }
)

# The module roots `tools/ow_drivers.py` may import, written out. The runner is I/O — that is its
# whole reason to exist under `tools/` — so this set is wider than `resolve.py`'s and its point is
# different: `importlib` is ABSENT, because `activate()` is "the only site that imports a card's
# entrypoint" (02-architecture.md:237) and a verb that ran over a hostile wheel and imported it
# would be the INV-4 / G11 breach the runner's own docstring promises it is not.
TOOL_IMPORT_ROOTS = frozenset(
    {
        "__future__",
        "argparse",
        "collections",
        "ctypes",
        "dataclasses",
        "os",
        "pathlib",
        "platform",
        "shutil",
        "sys",
        "tomllib",
        "typing",
        "omniweave_core",
        "omniweave_ports",
    }
)

# Every way to import a name at runtime without an `import` statement. A pinned root set alone
# would not see `__import__("pkg.driver")`, which is why the call names are checked too.
BANNED_DYNAMIC_IMPORT_CALLS = frozenset(
    {
        "__import__",
        "import_module",
        "exec_module",
        "load_module",
        "module_from_spec",
        "spec_from_file_location",
        "eval",
        "exec",
    }
)

HOST_ENV = ProbeEnv(
    platform="linux",
    machine="x86_64",
    python=(3, 12),
    which={"tesseract": "/usr/bin/tesseract"},
    gpu_present=False,
    vram_gb=0.0,
    offline=False,
)

MINIMAL_CARD = """card_schema = 1

[driver]
id = "{id}"
port = "{port}"
version = "0.1.0"
schema_version = 1
entrypoint = "pkg.driver:Cls"
granularity = "{granularity}"
replay_class = "byte_exact"

[capability]
formats = ["application/pdf"]
consumes = ["raw_bytes"]
produces = [{produces}]
"""

OPEN_LICENCE = """
[licence.code]
spdx = "Apache-2.0"
"""


RESTRICTED_LICENCE = """
[licence.code]
spdx = "AGPL-3.0-only"
licence_sha256 = "sha256:37a680133bd09342f934afb8dd2c7d9e1b624da5f35e3a38adb103e37c055ed1"
"""
"""A `[licence.code]` table whose facts compute `restricted`: AGPL-3.0-only is a
COPYLEFT_NETWORK spdx. The digest is a fixture and is deliberately not the md5
`e1f69b64dee2f1641a9b1ab12adf24d6` 01-principles.md:204 records for the shared modified AI
Pubs OpenRAIL-M `MODEL_LICENSE` -- an ack binds a sha256 of the text, not that md5."""

PERMISSIVE_CODE_RESTRICTIVE_WEIGHTS = """
[licence.code]
spdx = "Apache-2.0"

[licence.weights]
spdx = "LicenseRef-OpenRAIL-M"
licence_sha256 = "sha256:5c1e4bd0a4e0ec1e5b90dd0f4b8e6d3a2f1c0b9a8877665544332211aabbccdd"
weights_revision = "9f2c1a7d3e5b4c8a6f0d9e2b1c3a4d5e6f708192"
competitor_bar = true
"""
"""**The Datalab trap** (01-principles.md:205-209): a permissive code licence over weights nobody
may use against the author. `[licence.code]` computes `open` and `[licence.weights]` computes
`restricted` from `competitor_bar`, so `compute_tier` returns `restricted` — "the weakest link
governs" (04:1855) — and the ack that clears it is the WEIGHTS row and not the code one.

`weights_revision` is required on `[licence.weights]` and must be an exact sha (`card.py`; RT14),
which is why a fixture that omits it is `CARD_INVALID` rather than a weaker version of this one."""

TERRITORIAL_WEIGHTS = """
[licence.code]
spdx = "MIT"

[licence.weights]
spdx = "LicenseRef-OpenRAIL-M"
weights_revision = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"
territory_excluded = ["DE"]
"""
"""A territorial exclusion declared on the WEIGHTS table and not the code one.

04-driver-system.md:1918-1921 makes `[licence] jurisdiction` a local refusal and does not say it
reads one of the two tables, and it cannot: a model whose weights bar a territory bars it whatever
the code says."""

BILLED = (
    '\n[cost.model]\nclass = "billed_api"\nshape = "linear_per_byte"\nunit = "byte"\n'
    'scaling = { key = "input_bytes", exponent = 1.0, reference = 65536 }\n'
)
"""A billed `[cost.model]`. The `scaling` table is not decoration: `card.py` refuses a
non-`constant` `shape` whose `scaling` is empty, because "the term shape declares has to be
carried by scaling" (04-driver-system.md section 3 note 4)."""


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cold_memo() -> None:
    """Every test starts on an empty memo.

    The memo is module-level because `Catalog` is a frozen slotted dataclass that can hold neither
    an attribute nor a weak reference (see `resolve.py`'s docstring), so it outlives a test unless
    a test clears it. This is a *setup* fixture and not a cleanup one on purpose: a cleanup step
    is only tested by state the next run will not recreate, and a cold start is what each test
    below actually depends on.
    """
    clear_memo()


def card(
    text: str = "",
    *,
    origin: str = "entry_point",
    licence: str = OPEN_LICENCE,
    produces: str = '"doc_fragment"',
    **fmt: str,
) -> DriverCard:
    """One `DriverCard` from `MINIMAL_CARD`, its licence block and `text`, in that order.

    The licence block is a PARAMETER rather than part of `text` because TOML refuses a table
    declared twice, so a test that wanted a restricted licence would otherwise have to restate
    the whole card and a negative test would stop asserting one thing.
    """
    body = MINIMAL_CARD.format(
        id=fmt.get("id", "parse.pdf.pdfium"),
        port=fmt.get("port", "parse/1"),
        granularity=fmt.get("granularity", "document"),
        produces=produces,
    )
    loaded = load_card((body + text + licence).encode("utf-8"), origin=origin, source="driver.toml")
    assert isinstance(loaded, DriverCard)
    return loaded


def tombstone(driver_id: str, reason: str) -> Tombstone:
    text = f"""card_schema = 1

[driver]
id = "{driver_id}"
port = "parse/1"

[tombstone]
reason = "{reason}"
review_by = "2099-01-01"
"""
    loaded = load_card(text.encode("utf-8"), origin="tombstone", source="tombstones/x.toml")
    assert isinstance(loaded, Tombstone)
    return loaded


def catalog_of(
    *cards: DriverCard,
    probe: dict[str, str] | None = None,
    trust: dict[str, TrustTier] | None = None,
    tombstones: tuple[Tombstone, ...] = (),
    salt: str = "",
) -> Catalog:
    """A `Catalog` over `cards`, every driver `first_party` and unprobed unless told otherwise."""
    by_id = {c.identity.id: c for c in cards}
    return Catalog.assemble(
        validity_key=hashlib.sha256(salt.encode()).hexdigest(),
        cards=by_id,
        probe_status=probe or {},
        trust=trust or dict.fromkeys(by_id, TrustTier.FIRST_PARTY),
        tombstones=tombstones,
    )


def policy(**overrides: object) -> Policy:
    """A `Policy` that lets a well-formed open-licence card through, so a test asserts one thing.

    `require_lock = False` and `allow_unattested = True` are departures from the shipped defaults
    (`true` and `false`) and each has its own test below; every other field is the shipped value.
    There is no tier override: `resolve()` computes the tier from card facts through
    `omniweave_core.drivers.licence.compute_tier` on every call (DR15), so a test that wants a
    restricted driver ships restricted FACTS.
    """
    base: dict[str, object] = {
        "require_lock": False,
        "allow_unattested": True,
        "host_env": HOST_ENV,
    }
    base.update(overrides)
    return Policy(**base)  # type: ignore[arg-type]


def ack_set(subject: DriverCard, licence_sha256: str, *, which: AckWhich = AckWhich.CODE) -> AckSet:
    """One `omniweave.acks.toml` row for one of `subject`'s licensed artefacts.

    `AckSet` and `Ack` are `omniweave_core.drivers.licence`'s (W3.3) and are not restated here: an
    ack is one fact and 04-driver-system.md:1911 gives it one home, which `resolve()` reads out of
    `Policy` rather than off the disk.

    `which` is a parameter because 04-driver-system.md:1903 is "one row per licensed artefact" and
    01-principles.md:205-209's Datalab trap is a permissive CODE licence over restrictive WEIGHTS:
    a helper that could only sign the code row could not express the case INV-5 was written for.
    """
    row = Ack(
        driver=subject.identity.id,
        licence_sha256=licence_sha256,
        which=which,
        tier="restricted",
        acknowledged_by="legal@example.com",
        acknowledged_at="2026-08-30T09:12:00Z",
        note="AGPL-3.0 accepted for internal-only deployment; ticket LEGAL-4471.",
    )
    return AckSet(rows={(subject.identity.id, which): row})


def parse_requirement(**overrides: object) -> Requirement:
    base: dict[str, object] = {"port": "parse/1", "format": "application/pdf"}
    base.update(overrides)
    return Requirement(**base)  # type: ignore[arg-type]


def only_rejection(resolution: Resolution) -> Rejection:
    assert len(resolution.rejected) == 1, resolution.rejected
    assert resolution.candidates == ()
    return resolution.rejected[0]


def register_rows() -> tuple[dict[str, str], dict[str, str]]:
    """`codes.toml`'s `OW-D` rows as `(numeric -> symbol, symbol -> numeric)`."""
    path = Path(__file__).resolve().parents[4] / "codes.toml"
    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = [row for row in parsed["code"] if str(row["numeric"]).startswith("OW-D-")]
    return (
        {str(row["numeric"]): str(row["symbol"]) for row in rows},
        {str(row["symbol"]): str(row["numeric"]) for row in rows},
    )


def printed_gate_codes(plan) -> tuple[str, ...]:
    """The `RejectCode` names of 04-driver-system.md section 4.8's printed filter order, in order.

    The fence is found by content rather than by line number so that an edit above it does not
    silently make this test read a different block.
    """
    fences = [
        body
        for body in plan.fences("04-driver-system.md", "text")
        if "PORT_UNSUPPORTED" in body and "ISOLATION_NOT_PERMITTED" in body
    ]
    assert len(fences) == 1, f"expected one printed filter order, found {len(fences)}"
    names: list[str] = []
    for line in fences[0].splitlines():
        _, _, tail = line.rpartition("->")
        if not tail:
            continue
        names.extend(re.findall(r"\b[A-Z][A-Z_]{3,}\b", tail))
    return tuple(names)


def table_reject_codes(plan) -> dict[str, tuple[str, ...]]:
    """Section 5.3's complete code set, as `refusal point -> the codes it files`."""
    found: dict[str, tuple[str, ...]] = {}
    for line in plan.lines("04-driver-system.md"):
        if not line.startswith("| ") or "`" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        point = cells[0].replace("**", "")
        if point not in {
            "discovery",
            "resolve — identity",
            "resolve — fit",
            "resolve — policy",
            "resolve — environment",
            "preflight",
            "activate",
        }:
            continue
        found[point] = tuple(re.findall(r"`([A-Z][A-Z_]+)`", cells[1]))
    return found


def permutations_of(cards: tuple[DriverCard, ...], count: int) -> list[tuple[DriverCard, ...]]:
    """`count` deterministic shufflings of `cards`, keyed by blake2b.

    `random` is banned framework-wide — 11-repo-layout.md:2185 states the reason as a message
    string, *"Sampling is blake2b. Determinism is a gate, not a habit."* — so the permutations are
    a keyed sort. A CI failure is reproducible from the salt alone.
    """
    orders: list[tuple[DriverCard, ...]] = []
    for salt in range(count):
        keyed = sorted(
            cards,
            key=lambda c: hashlib.blake2b(
                f"{salt}:{c.identity.id}".encode(), digest_size=8
            ).digest(),
        )
        orders.append(tuple(keyed))
    return orders


# --------------------------------------------------------------------------------------------
# 1. The gate order is the specification
# --------------------------------------------------------------------------------------------


def test_the_gate_order_reproduces_the_documents_own_printed_filter_order(plan) -> None:
    plan.require()
    printed = printed_gate_codes(plan)
    unplaced = {
        RejectCode.PORT_MISMATCH.name,
        RejectCode.ID_COLLISION_UNQUALIFIED.name,
        RejectCode.DEPRECATED_REMOVED.name,
    }
    ours = tuple(
        code.name for gate in GATE_ORDER for code in gate.codes if code.name not in unplaced
    )
    assert ours == printed


def test_the_three_codes_the_printed_order_omits_are_the_three_section_5_3_files_as_identity(
    plan,
) -> None:
    plan.require()
    printed = set(printed_gate_codes(plan))
    identity = set(table_reject_codes(plan)["resolve — identity"])
    assert identity - printed == {
        RejectCode.PORT_MISMATCH.name,
        RejectCode.ID_COLLISION_UNQUALIFIED.name,
        RejectCode.DEPRECATED_REMOVED.name,
    }


def test_the_gate_order_holds_nineteen_uniquely_named_gates() -> None:
    assert len(GATE_ORDER) == GATE_COUNT
    assert len({gate.name for gate in GATE_ORDER}) == GATE_COUNT
    assert all(gate.plan.startswith("04-driver-system.md:") for gate in GATE_ORDER)


def test_the_whole_gate_order_is_pinned_and_not_only_the_part_the_document_prints() -> None:
    """Every one of the nineteen positions, against a literal.

    The document-derived test above drops the three codes section 4.8's fence does not print
    before comparing, so it cannot see `not_removed` move to the end of the order or
    `port_matches_requirement` and `id_unambiguous` change places. Both of those were applied as
    mutations and both left this file green, which is why the literal is here.
    """
    assert tuple(gate.name for gate in GATE_ORDER) == GATE_NAMES_IN_ORDER
    ours = {gate.name for gate in GATE_ORDER if "ORDER IS OURS" in gate.plan}
    assert ours == {"port_matches_requirement", "id_unambiguous", "not_removed"}


def test_a_port_mismatch_outranks_a_colliding_id_because_that_is_where_we_placed_it() -> None:
    """The `port_matches_requirement` / `id_unambiguous` boundary, as behaviour.

    Neither position is the plan's — section 5.3:1563 files both codes under "resolve — identity"
    and section 4.8's printed order places neither — so the boundary is our call and the code a
    caller sees for a driver failing both is the observable consequence. Asked for `derive/1`
    against a `parse/1` card whose id is also in `[drivers] collisions`, the caller-bug code wins.
    """
    subject = card()
    rejection = only_rejection(
        resolve(
            Requirement(port="derive/1"),
            catalog_of(subject),
            policy(collisions=frozenset({subject.identity.id})),
        )
    )
    assert rejection.code is RejectCode.PORT_MISMATCH
    assert rejection.gate == "port_matches_requirement"


def test_a_removed_driver_reports_its_removal_and_not_the_lockfile_it_also_fails() -> None:
    """The `not_removed` / `in_lockfile` boundary, as behaviour.

    `DEPRECATED_REMOVED` sits at position 5 and `NOT_IN_LOCKFILE` at 18, so a card that is both
    past its `removed_in` and absent from the lockfile reports the removal — the fact an operator
    can act on, since adding a removed driver to `omniweave.lock` would not make it run. Moving
    `not_removed` to the end of the order was a surviving mutation until this test existed.
    """
    subject = card(DEPRECATED)
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(release="0.3.0", require_lock=True),
        )
    )
    assert rejection.code is RejectCode.DEPRECATED_REMOVED
    assert rejection.gate == "not_removed"


def test_every_gate_declares_at_least_one_code_and_no_code_is_declared_by_two_gates() -> None:
    seen: dict[RejectCode, str] = {}
    for gate in GATE_ORDER:
        assert gate.codes, gate.name
        for code in gate.codes:
            assert code not in seen, f"{code.name} is declared by {seen.get(code)} and {gate.name}"
            seen[code] = gate.name
    assert len(seen) == 23


def test_a_driver_that_is_both_tombstoned_and_format_unsupported_reports_the_tombstone() -> None:
    subject = card()
    stone = tombstone(subject.identity.id, "pymupdf is AGPL and the weights bar competitors")
    resolution = resolve(
        parse_requirement(format="application/vnd.ms-excel"),
        catalog_of(subject, tombstones=(stone,)),
        policy(),
    )
    rejection = only_rejection(resolution)
    assert rejection.code is RejectCode.TOMBSTONED
    assert rejection.gate == "not_tombstoned"
    assert "bar competitors" in rejection.detail


def test_a_driver_failing_both_the_licence_and_the_cost_gates_reports_the_licence() -> None:
    subject = card(BILLED, licence=RESTRICTED_LICENCE)
    resolution = resolve(
        parse_requirement(max_cost_class=CostClass.FREE),
        catalog_of(subject),
        policy(),
    )
    rejection = only_rejection(resolution)
    assert rejection.code is RejectCode.LICENCE_TIER_NOT_ALLOWED
    assert rejection.gate == "licence_allowed_and_acknowledged"


def test_a_driver_failing_both_the_lockfile_and_the_isolation_gates_reports_the_lockfile() -> None:
    subject = card('\n[isolation]\nrequires = "wasm"\n')
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            require_lock=True,
        ),
    )
    rejection = only_rejection(resolution)
    assert rejection.code is RejectCode.NOT_IN_LOCKFILE
    assert rejection.gate == "in_lockfile"


def test_clearing_the_earlier_gate_lets_the_later_one_speak() -> None:
    subject = card('\n[isolation]\nrequires = "wasm"\n')
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            require_lock=True,
            locked_ids=frozenset({subject.identity.id}),
        ),
    )
    assert only_rejection(resolution).code is RejectCode.ISOLATION_NOT_PERMITTED


# --------------------------------------------------------------------------------------------
# 2. RejectCode is a typed view over the one register
# --------------------------------------------------------------------------------------------


def test_the_reject_code_membership_is_section_5_3s_own_enumeration(plan) -> None:
    plan.require()
    from_plan = {name for codes in table_reject_codes(plan).values() for name in codes}
    assert from_plan == {code.name for code in RejectCode}
    assert len(RejectCode) == REJECT_CODE_COUNT


def test_the_reject_code_count_the_prose_states_disagrees_with_its_own_table(plan) -> None:
    """A FINDING, pinned so it cannot be lost: :1557 says twenty-five, its table has twenty-six.

    The brief's rule is that when a number and an enumeration disagree the enumeration is the
    thing to check, so `RejectCode` implements the table. This test asserts both halves of the
    disagreement, and it is the test that fails if the document is ever corrected — at which point
    the finding is closed and this test is deleted rather than adjusted.
    """
    plan.require()
    prose = plan.grep(r"Twenty-five `RejectCode` members", documents=["04-driver-system.md"])
    assert len(prose) == 1, prose
    rows = table_reject_codes(plan)
    counted = sum(len(codes) for codes in rows.values())
    assert counted == REJECT_CODE_COUNT
    assert {point: len(codes) for point, codes in rows.items()} == {
        "discovery": 3,
        "resolve — identity": 5,
        "resolve — fit": 5,
        "resolve — policy": 6,
        "resolve — environment": 5,
        "preflight": 1,
        "activate": 1,
    }


def test_the_twenty_one_resolve_codes_are_the_number_section_5_3_states(plan) -> None:
    plan.require()
    rows = table_reject_codes(plan)
    resolve_owned = sum(
        len(codes) for point, codes in rows.items() if point.startswith("resolve —")
    )
    assert resolve_owned == 21
    assert plan.grep(
        r"the full filter order of section 4\.8, twenty-one codes",
        documents=["04-driver-system.md"],
    )


def test_a_reject_codes_wire_value_is_its_lower_case_member_name() -> None:
    for code in RejectCode:
        assert code.value == code.name.lower()


def test_every_reject_code_symbol_the_register_already_carries_is_reproduced() -> None:
    by_numeric, by_symbol = register_rows()
    for code, (numeric, symbol) in REGISTERED_ROWS.items():
        assert by_numeric[numeric] == symbol
        assert by_symbol[symbol] == numeric
        assert code.symbol == symbol


def test_every_reject_code_member_has_a_row_in_the_one_register() -> None:
    """The forward direction of the bijection 01-principles.md:605 makes a defect class.

    **Asserted, and no longer skipped.** This test called `pytest.skip` while rows were missing,
    naming each one — which is a test that cannot fail, reporting a defect the plan names by name
    ("a new `RejectCode` member with no `OW-D-nnn` row") as an absence of information. `codes.toml`
    now carries a row for every one of the twenty-six members: `OW-D-009` for `format_unsupported`
    (18-api-sketch.md:2158), `OW-D-010`..`-012` for the three card codes
    (04-driver-system.md:1522-1524), and `OW-D-052`..`-073` allocated at W3.1 from the rule
    04-driver-system.md:1444 states. A twenty-seventh member added without a row now fails here.

    The register is the integration agent's file and this test only reads it, so a reverted or
    re-numbered `codes.toml` turns this red — which is the intended coupling: the symbol is
    plan-stated and the row's existence is an obligation, not a courtesy.
    """
    _, by_symbol = register_rows()
    missing = sorted(code.symbol for code in RejectCode if code.symbol not in by_symbol)
    assert missing == [], (
        f"codes.toml has no OW-D row for {len(missing)} of {len(RejectCode)} RejectCode "
        f"members: {missing}. 01-principles.md:605 names exactly this a defect class, and "
        f"04-driver-system.md:1444 states the symbol the row must carry"
    )
    assert len(by_symbol) >= len(RejectCode)


def test_no_ow_d_row_is_claimed_twice_and_the_three_non_member_rows_are_named() -> None:
    by_numeric, by_symbol = register_rows()
    claimed: dict[str, RejectCode] = {}
    for code in RejectCode:
        numeric = by_symbol.get(code.symbol)
        if numeric is None:
            continue
        assert numeric not in claimed, f"{numeric} is claimed by {claimed[numeric]} and {code}"
        claimed[numeric] = code
    unclaimed = {numeric for numeric in by_numeric if numeric not in claimed}
    assert unclaimed == set(NON_MEMBER_OW_D)


def test_a_symbol_is_the_ow_driver_form_except_for_the_four_card_members() -> None:
    for code in RejectCode:
        if code.name.startswith("CARD_"):
            assert code.symbol == f"OW_{code.name}"
        else:
            assert code.symbol == f"OW_DRIVER_{code.name}"


# --------------------------------------------------------------------------------------------
# 3. DR5 — a RejectCode is required to construct a Resolution
# --------------------------------------------------------------------------------------------


def test_a_rejection_cannot_be_constructed_without_a_code() -> None:
    with pytest.raises(TypeError):
        Rejection(driver_id="parse.pdf.pdfium")  # type: ignore[call-arg]


def test_a_rejection_refuses_a_bare_string_where_a_reject_code_belongs() -> None:
    with pytest.raises(TypeError) as caught:
        Rejection(driver_id="parse.pdf.pdfium", code="format_unsupported", detail="x")  # type: ignore[arg-type]
    assert "RejectCode" in str(caught.value)


def test_a_rejection_refuses_an_empty_detail_because_a_verdict_is_not_a_report() -> None:
    with pytest.raises(ValueError, match="empty detail"):
        Rejection(driver_id="parse.pdf.pdfium", code=RejectCode.QUARANTINED, detail="")


def test_a_resolution_refuses_a_rejected_entry_that_is_not_a_rejection() -> None:
    with pytest.raises(TypeError, match="typed RejectCode"):
        Resolution(
            requirement=parse_requirement(),
            candidates=(),
            rejected=(("parse.pdf.pdfium", "format_unsupported", "x"),),  # type: ignore[arg-type]
            catalog_digest="0" * 64,
            policy_digest="0" * 64,
        )


def test_candidates_plus_rejected_equals_every_driver_considered() -> None:
    good, bad = card(id="parse.pdf.pdfium"), card(id="parse.text.plain")
    library = catalog_of(good, bad)
    resolution = resolve(
        parse_requirement(floors={"origin_span": "exact"}),
        library,
        policy(),
    )
    assert resolution.considered == len(considered_ids(library)) == 2
    assert len(resolution.candidates) + len(resolution.rejected) == 2


def test_rejection_of_finds_the_named_drivers_refusal_and_answers_none_for_a_stranger() -> None:
    """`Resolution.rejection_of` is exported public API and had no caller and no test.

    Replacing its whole body with `return None` was a surviving mutation. It is the lookup
    `ow drivers explain` and `ow doctor` need — "which of these twenty-two drivers refused MY
    driver, and why" — so it answering `None` for a driver that was in fact rejected is a silent
    wrong answer rather than a crash.
    """
    one, two = card(id="parse.aaa.one"), card(id="parse.bbb.two")
    resolution = resolve(
        parse_requirement(format="application/x-nonesuch"),
        catalog_of(one, two),
        policy(),
    )
    assert len(resolution.rejected) == 2
    found = resolution.rejection_of("parse.bbb.two")
    assert found is not None
    assert found.driver_id == "parse.bbb.two"
    assert found.code is RejectCode.FORMAT_UNSUPPORTED
    assert resolution.rejection_of("parse.zzz.absent") is None


def test_considered_ids_is_ascending_and_not_merely_the_catalogs_insertion_order() -> None:
    """Every id `resolve()` considers, "**in the order it considers them**" — its own docstring.

    `Catalog.assemble` keeps `cards` in insertion order (`MappingProxyType(dict(cards))`), so a
    `list(catalog.cards)` here would answer a different question from `sorted(catalog.cards)` and
    the only test that read this function asserted its LENGTH. The order is what makes it usable
    beside a `Resolution`, whose rejections come out in the order the gate walk produced them.
    """
    library = catalog_of(card(id="parse.zzz.last"), card(id="parse.aaa.first"))
    assert list(library.cards) == ["parse.zzz.last", "parse.aaa.first"]
    assert list(considered_ids(library)) == ["parse.aaa.first", "parse.zzz.last"]
    resolution = resolve(parse_requirement(), library, policy())
    assert [c.driver_id for c in resolution.candidates] == list(considered_ids(library))


def test_a_zero_candidate_resolution_is_a_value_and_never_a_raise() -> None:
    subject = card()
    resolution = resolve(
        parse_requirement(format="application/x-nonesuch"),
        catalog_of(subject),
        policy(),
    )
    assert resolution.candidates == ()
    assert only_rejection(resolution).code is RejectCode.FORMAT_UNSUPPORTED


# --------------------------------------------------------------------------------------------
# 4. Candidates are canonicalised and never ranked
# --------------------------------------------------------------------------------------------


def test_candidates_come_back_in_ascending_driver_id_order() -> None:
    cards = tuple(
        card(id=name) for name in ("parse.zzz.last", "parse.aaa.first", "parse.mmm.middle")
    )
    resolution = resolve(parse_requirement(), catalog_of(*cards), policy())
    ids = [candidate.driver_id for candidate in resolution.candidates]
    assert ids == ["parse.aaa.first", "parse.mmm.middle", "parse.zzz.last"]


def test_a_resolution_refuses_candidates_in_any_other_order() -> None:
    subject_a, subject_b = card(id="parse.aaa.first"), card(id="parse.zzz.last")
    out_of_order = tuple(
        Candidate(
            card=c, isolation_granted=Isolation.SUBPROC, effective_config={}, config_digest=""
        )
        for c in (subject_b, subject_a)
    )
    with pytest.raises(ValueError, match="ascending driver_id order"):
        Resolution(
            requirement=parse_requirement(),
            candidates=out_of_order,
            rejected=(),
            catalog_digest="0" * 64,
            policy_digest="0" * 64,
        )


def test_a_capability_floor_filters_and_never_orders_the_survivors() -> None:
    """16-roadmap.md:481's own assertion: a floor is a filter and never a ranking key.

    `parse.zzz.rich` declares `tables = "cells_with_spans"` and `parse.aaa.thin` declares
    `tables = "cells"`; the floor is `"cells"`, which both meet. A ranking **that put the richer
    driver first** would reorder these two. The canonical order puts `parse.aaa.thin` first,
    because that is what `resolution_digest` needs and ranking is the router's
    (02-architecture.md:280).

    This test alone does not carry the property, and saying so is the point: a ranking key sorting
    the WEAKEST driver first produces exactly this order for exactly these two cards, and that
    mutation was green against this file until the mirror test below existed. Two cards admit two
    orders, so one direction of ranking always coincides with the lexical one; the pair of tests
    is what closes it.
    """
    thin = card('\n[capability.parse]\ntables = "cells"\n', id="parse.aaa.thin")
    rich = card('\n[capability.parse]\ntables = "cells_with_spans"\n', id="parse.zzz.rich")
    resolution = resolve(
        parse_requirement(floors={"tables": "cells"}),
        catalog_of(thin, rich),
        policy(),
    )
    assert [c.driver_id for c in resolution.candidates] == ["parse.aaa.thin", "parse.zzz.rich"]


def test_a_floor_does_not_order_the_survivors_when_the_richer_driver_sorts_first_either() -> None:
    """The mirror of the test above, with the capability and the id anti-correlated.

    `parse.aaa.rich` declares `tables = "cells_with_spans"` and `parse.zzz.thin` declares
    `tables = "cells"`, so a ranking sorting the weakest survivor first has to put `parse.zzz.thin`
    ahead of `parse.aaa.rich` and the lexical order cannot absorb it. Between the two tests, a
    capability-derived ordering in EITHER direction is refused — by
    `Resolution.__post_init__`, which is where the refusal belongs, since it makes the order
    unconstructible rather than merely unbuilt.
    """
    rich = card('\n[capability.parse]\ntables = "cells_with_spans"\n', id="parse.aaa.rich")
    thin = card('\n[capability.parse]\ntables = "cells"\n', id="parse.zzz.thin")
    resolution = resolve(
        parse_requirement(floors={"tables": "cells"}),
        catalog_of(rich, thin),
        policy(),
    )
    assert [c.driver_id for c in resolution.candidates] == ["parse.aaa.rich", "parse.zzz.thin"]


# --------------------------------------------------------------------------------------------
# 5. The floors — 04-driver-system.md section 2.2, one row at a time
# --------------------------------------------------------------------------------------------


def test_the_parse_floor_table_covers_exactly_section_2_2s_sixteen_keys(plan) -> None:
    plan.require()
    rows = [
        line
        for line in plan.lines("04-driver-system.md")
        if (line.startswith("| `") and "| `>=`" in line) or line.startswith("| `forfeits`")
    ]
    named = {re.match(r"\| `([a-z_]+)`", line)[1] for line in rows}  # type: ignore[index]
    named |= {"math", "format_tokens"}
    assert named == set(FLOOR_KINDS[Port.PARSE])
    assert len(FLOOR_KINDS[Port.PARSE]) == 16


@pytest.mark.parametrize("name", sorted(PARSE_LADDERS))
def test_each_ordered_parse_ladder_is_compared_with_greater_or_equal(name: str) -> None:
    rungs = PARSE_LADDERS[name]
    for index, rung in enumerate(rungs):
        for floor_index, floor in enumerate(rungs):
            assert meets_floor(Port.PARSE, name, rung, floor) is (index >= floor_index)


@pytest.mark.parametrize("port", sorted(PORT_LADDERS, key=lambda p: p.value))
def test_an_ordered_field_compared_as_a_boolean_would_pass_every_floor_and_does_not(
    port: Port,
) -> None:
    """The first of the three named bugs: every rung of every ladder is a truthy string.

    `bool("none")` is `True`, so a boolean comparison of `spatial` admits the least capable driver
    for the most demanding floor. The assertion is that the two disagree.

    Parametrised over **all four** Ports that declare a ladder, not over `parse` alone: mapping
    `DERIVE_LADDERS` to `FloorKind.BOOLEAN` — this exact bug, on the `derive` half — was a
    surviving mutation while this test read only `PARSE_LADDERS`. `embed` contributes one ladder
    and `compile` declares none (04-driver-system.md section 10.3), which is why `PORT_LADDERS`
    has four keys and `FLOOR_KINDS` five.
    """
    ladders = PORT_LADDERS[port]
    assert ladders, port
    for name, rungs in ladders.items():
        weakest, strongest = rungs[0], rungs[-1]
        assert bool(weakest) >= bool(strongest)
        assert floor_kind(port, name) is FloorKind.LADDER
        assert meets_floor(port, name, weakest, strongest) is False
        assert meets_floor(port, name, strongest, weakest) is True


def test_math_is_a_set_compared_as_a_superset_and_never_with_equality() -> None:
    both = frozenset({"latex", "mathml"})
    assert meets_floor(Port.PARSE, "math", both, frozenset({"latex"})) is True
    assert both != frozenset({"latex"})
    assert meets_floor(Port.PARSE, "math", frozenset({"latex"}), both) is False
    assert floor_kind(Port.PARSE, "math") is FloorKind.SUPERSET


def test_forfeits_is_the_one_inverted_comparison_on_the_whole_card() -> None:
    inverted = [
        name
        for port in FLOOR_KINDS
        for name, kind in FLOOR_KINDS[port].items()
        if kind is FloorKind.SUBSET_INVERTED
    ]
    assert inverted == ["forfeits"]
    tolerated = frozenset({"round_trip"})
    assert meets_floor(Port.PARSE, "forfeits", frozenset({"round_trip"}), tolerated) is True
    assert meets_floor(Port.PARSE, "forfeits", frozenset({"text_span"}), tolerated) is False
    assert meets_floor(Port.PARSE, "forfeits", frozenset(), tolerated) is True


def test_comparing_forfeits_the_way_math_is_compared_would_admit_the_wrong_driver() -> None:
    card_forfeits, needed_kept = frozenset({"text_span"}), frozenset()
    assert card_forfeits >= needed_kept
    assert meets_floor(Port.PARSE, "forfeits", card_forfeits, needed_kept) is False


@pytest.mark.parametrize("name", PARSE_BOOLS)
def test_the_three_parse_booleans_are_compared_as_plain_booleans(name: str) -> None:
    assert floor_kind(Port.PARSE, name) is FloorKind.BOOLEAN
    assert meets_floor(Port.PARSE, name, True, True) is True
    assert meets_floor(Port.PARSE, name, True, False) is True
    assert meets_floor(Port.PARSE, name, False, False) is True
    assert meets_floor(Port.PARSE, name, False, True) is False


def test_every_floor_comparison_returns_a_bool_and_offers_no_score() -> None:
    cases = (
        (Port.PARSE, "spatial", "char_bbox", "page_bbox"),
        (Port.PARSE, "text_span", True, True),
        (Port.PARSE, "math", frozenset({"latex"}), frozenset({"latex"})),
        (Port.PARSE, "forfeits", frozenset(), frozenset()),
    )
    kinds = {floor_kind(port, name) for port, name, _, _ in cases}
    assert kinds == set(FloorKind)
    for port, name, declared, floor in cases:
        assert type(meets_floor(port, name, declared, floor)) is bool


def test_an_absent_ladder_key_reads_as_the_least_capable_rung() -> None:
    """A card with no `[capability.parse]` table declares every ladder at rung 0.

    `card.py` defaults the table rather than leaving it `None`, and every ladder's element 0 "is
    the only default that cannot over-claim" (`PARSE_LADDERS`' docstring). So the refusal names
    the rung the card declares by omission, not the absence of the table.
    """
    subject = card()
    assert subject.parse is not None
    assert subject.parse.origin_span == PARSE_LADDERS["origin_span"][0]
    rejection = only_rejection(
        resolve(
            parse_requirement(floors={"origin_span": "exact"}),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.CAPABILITY_BELOW_FLOOR
    assert "origin_span declares 'none' and the floor is 'exact'" in rejection.detail


def test_an_unknown_forfeits_member_is_a_match_failure_and_not_an_ignore() -> None:
    subject = card('\n[capability.parse]\nforfeits = ["blocks", "invented_thing"]\n')
    assert "invented_thing" in subject.parse.forfeits
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.CAPABILITY_BELOW_FLOOR
    assert "forfeits_unknown_member" in rejection.detail


def test_a_floor_naming_a_field_the_port_does_not_declare_is_never_a_silent_pass() -> None:
    subject = card('\n[capability.parse]\ntables = "cells"\n')
    rejection = only_rejection(
        resolve(
            parse_requirement(floors={"spanmap": True}),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.CAPABILITY_BELOW_FLOOR
    assert "unknown_floor" in rejection.detail


def test_a_derive_card_that_does_not_honour_scope_is_permanently_unactivatable() -> None:
    subject = card(
        '\n[capability.derive]\nitems = ["segment"]\nscope_honoured = false\n',
        id="derive.graph.local",
        port="derive/1",
    )
    rejection = only_rejection(
        resolve(
            Requirement(port="derive/1"),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.CAPABILITY_BELOW_FLOOR
    assert "scope_not_honoured" in rejection.detail


def test_an_input_kind_the_card_does_not_consume_is_a_capability_failure() -> None:
    subject = card()
    rejection = only_rejection(
        resolve(
            parse_requirement(input_kind=ArtifactKind.IL_BUNDLE),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.CAPABILITY_BELOW_FLOOR
    assert "input_kind_not_consumed" in rejection.detail


def test_the_four_per_port_floor_tables_derive_their_ladders_from_the_card_module() -> None:
    """Every ladder of every Port is a `LADDER`, and the five keys of `FLOOR_KINDS` are these.

    The four-port claim in the name used to be checked over one port. It is checked over four
    here, and the ladder NAMES are checked too: a floor table that silently dropped a ladder key
    would leave that field undeclarable as a floor — `unknown_floor`, a refusal — rather than
    mis-compared, which is the quieter half of the same defect.
    """
    for port, ladders in PORT_LADDERS.items():
        assert set(ladders) <= set(FLOOR_KINDS[port])
        for name in ladders:
            assert FLOOR_KINDS[port][name] is FloorKind.LADDER, (port, name)
    assert set(PARSE_SETS) <= set(FLOOR_KINDS[Port.PARSE])
    assert set(FLOOR_KINDS) == {Port.PARSE, Port.ACQUIRE, Port.DERIVE, Port.EMBED, Port.COMPILE}
    assert FLOOR_KINDS[Port.COMPILE] == {}
    assert floor_kind(Port.COMPILE, "origin_span") is None


# --------------------------------------------------------------------------------------------
# 6. Purity, and the probe that is an input rather than an action
# --------------------------------------------------------------------------------------------


def test_the_module_imports_nothing_that_can_probe_import_or_spawn() -> None:
    tree = ast.parse(RESOLVE_SOURCE.read_text(encoding="utf-8"))
    roots: set[str] = set()
    dotted: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
                dotted.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
            dotted.add(node.module)
    assert roots == ALLOWED_IMPORT_ROOTS
    assert {name for name in dotted if name.startswith("omniweave_core.")} == ALLOWED_CORE_MODULES


def test_resolve_opens_no_file_spawns_nothing_and_reads_no_clock(pure_unit) -> None:  # noqa: ARG001
    subject = card()
    resolution = resolve(parse_requirement(), catalog_of(subject), policy())
    assert [c.driver_id for c in resolution.candidates] == [subject.identity.id]


def test_resolve_is_unaffected_by_the_environment_and_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    subject = card()
    library, rules = catalog_of(subject), policy()
    requirement = parse_requirement()
    before = resolve_uncached(requirement, library, rules)
    monkeypatch.setenv("OMNIWEAVE_DRIVER_PATH", str(tmp_path))
    monkeypatch.setenv("OMNIWEAVE_HOME", str(tmp_path))
    monkeypatch.setenv("OMNIWEAVE_PROBE_EPOCH", "17")
    monkeypatch.chdir(tmp_path)
    after = resolve_uncached(requirement, library, rules)
    assert before.resolution_digest == after.resolution_digest
    assert before == after


def test_a_hundred_catalog_permutations_yield_one_identical_resolution() -> None:
    """DR4 (04-driver-system.md:1377): shuffle the catalog 100x, assert an identical `Resolution`.

    Through `resolve_uncached()`, because the memo would answer 99 of the 100 from the first
    call's result and the test would then be asserting that a dictionary works.
    """
    cards = tuple(card(id=f"parse.p{index:02d}.driver") for index in range(8))
    rules = policy()
    requirement = parse_requirement()
    digests = {
        resolve_uncached(requirement, catalog_of(*order), rules).resolution_digest
        for order in permutations_of(cards, 100)
    }
    assert len(digests) == 1


def test_an_unprobed_driver_is_a_candidate_and_not_a_refusal() -> None:
    subject = card()
    library = catalog_of(subject)
    assert library.probe_status[subject.identity.id] == "unknown"
    resolution = resolve(parse_requirement(), library, policy())
    assert [c.driver_id for c in resolution.candidates] == [subject.identity.id]


@pytest.mark.parametrize("verdict", ["ok", "degraded", "unknown"])
def test_every_probe_verdict_but_unavailable_passes_the_probe_gate(verdict: str) -> None:
    subject = card()
    library = catalog_of(subject, probe={subject.identity.id: verdict})
    resolution = resolve(parse_requirement(), library, policy())
    assert len(resolution.candidates) == 1


def test_an_unavailable_probe_verdict_is_read_off_the_catalog_and_rejected() -> None:
    subject = card()
    library = catalog_of(subject, probe={subject.identity.id: "unavailable"})
    rejection = only_rejection(resolve(parse_requirement(), library, policy()))
    assert rejection.code is RejectCode.PROBE_UNAVAILABLE
    assert rejection.gate == "probe_not_unavailable"


def test_a_moved_probe_verdict_invalidates_the_memo_through_the_catalog_digest() -> None:
    subject = card()
    unprobed = catalog_of(subject)
    unavailable = catalog_of(subject, probe={subject.identity.id: "unavailable"})
    assert unprobed.catalog_digest != unavailable.catalog_digest
    rules = policy()
    requirement = parse_requirement()
    assert len(resolve(requirement, unprobed, rules).candidates) == 1
    assert len(resolve(requirement, unavailable, rules).candidates) == 0
    assert memo_stats().misses == 2


# --------------------------------------------------------------------------------------------
# 7. The memo, and its key
# --------------------------------------------------------------------------------------------


def test_the_memo_returns_the_same_object_for_the_same_three_digests() -> None:
    subject = card()
    library, rules = catalog_of(subject), policy()
    requirement = parse_requirement()
    first = resolve(requirement, library, rules)
    assert resolve(requirement, library, rules) is first
    assert memo_stats() == (1, 1, 1, 0)


def test_resolve_uncached_never_touches_the_memo() -> None:
    subject = card()
    library, rules = catalog_of(subject), policy()
    resolve_uncached(parse_requirement(), library, rules)
    assert memo_stats() == (0, 0, 0, 0)


def test_the_memo_is_bounded_at_the_ceiling_and_counts_what_it_dropped() -> None:
    """The BOUND, and only the bound: 513 distinct keys leave 512 entries and one eviction.

    Which entry went is a separate question and this test cannot answer it — evicting the entry
    just inserted satisfies every assertion here. The test below is the one that answers it.
    """
    subject = card()
    library, rules = catalog_of(subject), policy()
    for index in range(RESOLVE_MEMO_MAX + 1):
        resolve(parse_requirement(format=f"application/x-{index}"), library, rules)
    stats = memo_stats()
    assert stats.entries == RESOLVE_MEMO_MAX
    assert stats.evictions == 1
    assert stats.misses == RESOLVE_MEMO_MAX + 1


def test_a_touched_entry_outlives_an_untouched_one_because_the_memo_is_an_lru() -> None:
    """04-driver-system.md:1436 says LRU in as many words, so recency is a property and not a note.

    Nothing else in this file distinguishes an LRU from a FIFO or from a cache that drops the
    entry it has just computed: `_MEMO.popitem()` in place of `_MEMO.pop(next(iter(_MEMO)))` was a
    surviving mutation, and a memo that evicts the newest entry serves a served process by
    recomputing every second call. The witness is the oldest key, TOUCHED once before the
    overflow: an LRU keeps it and drops the key after it, and any other policy does not.
    """
    subject = card()
    library, rules = catalog_of(subject), policy()
    filled = [
        parse_requirement(format=f"application/x-{index}") for index in range(RESOLVE_MEMO_MAX)
    ]
    for requirement in filled:
        resolve(requirement, library, rules)
    assert memo_stats() == (RESOLVE_MEMO_MAX, 0, RESOLVE_MEMO_MAX, 0)

    oldest, next_oldest = filled[0], filled[1]
    touched = resolve(oldest, library, rules)
    assert memo_stats().hits == 1

    resolve(parse_requirement(format="application/x-one-too-many"), library, rules)
    assert memo_stats().evictions == 1

    assert resolve(oldest, library, rules) is touched
    assert memo_stats().hits == 2
    resolve(next_oldest, library, rules)
    assert memo_stats().misses == RESOLVE_MEMO_MAX + 2


def test_the_memo_key_is_the_three_digests_and_not_a_wider_tuple() -> None:
    subject = card()
    library, rules = catalog_of(subject), policy()
    twin = policy()
    assert rules.policy_digest == twin.policy_digest
    requirement = parse_requirement()
    first = resolve(requirement, library, rules)
    assert resolve(requirement, library, twin) is first


@pytest.mark.parametrize(
    ("field_name", "left", "right", "strict"),
    [
        ("granularity", "document", "part", False),
        ("input_kind", ArtifactKind.RAW_BYTES, ArtifactKind.IL_BUNDLE, False),
        (
            "requires_produces",
            frozenset({ArtifactKind.DOC_FRAGMENT}),
            frozenset({ArtifactKind.WITNESS_SET}),
            False,
        ),
        ("pinned", None, "parse.pdf.pdfium", True),
    ],
)
def test_two_requirements_differing_only_in_one_omitted_field_resolve_differently(
    field_name: str, left: object, right: object, strict: bool
) -> None:
    """13-quality.md:216-220's four allocated `capability` properties, built in P3.

    Each varies exactly one of the four fields the charter's memo tuple omitted and asserts the
    two `Resolution`s differ. The wrong answer each forbids is a *plausible* one — the second
    requirement silently receiving the first's driver (R-T15) — which is why the digest covers
    `dataclasses.fields()` rather than a written-out key list.
    """
    subject = card(
        "\n[capability.parse]\ntext_span = true\n",
        id="parse.pdf.pdfium",
        granularity="document",
    )
    library = catalog_of(subject)
    rules = policy(allow_unattested=not strict)
    one = parse_requirement(**{field_name: left})
    two = parse_requirement(**{field_name: right})
    assert one.digest != two.digest
    first, second = resolve(one, library, rules), resolve(two, library, rules)
    assert first is not second
    assert first.resolution_digest != second.resolution_digest
    assert (len(first.candidates), len(second.candidates)) != (0, 0)
    assert len(first.candidates) != len(second.candidates)


def test_requirement_carries_exactly_the_eight_fields_plus_the_derived_digest() -> None:
    declared = tuple(f.name for f in dataclasses.fields(Requirement))
    assert declared == (*REQUIREMENT_FIELDS, "digest")


def test_the_requirement_digest_is_over_every_field_and_over_no_written_out_list() -> None:
    requirement = parse_requirement(
        floors={"text_span": True, "math": frozenset({"latex"})},
        granularity="part",
        input_kind=ArtifactKind.RAW_BYTES,
        requires_produces=frozenset({ArtifactKind.DOC_FRAGMENT}),
        pinned="parse.pdf.pdfium@omniweave-pdf",
    )
    expected = sha256_canonical(
        {
            "port": "parse/1",
            "format": "application/pdf",
            "floors": {"math": ["latex"], "text_span": True},
            "max_cost_class": "local_compute",
            "granularity": "part",
            "input_kind": "raw_bytes",
            "requires_produces": ["doc_fragment"],
            "pinned": "parse.pdf.pdfium@omniweave-pdf",
        }
    )
    assert requirement.digest == expected


def test_a_requirement_with_a_port_outside_the_five_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="five Ports"):
        Requirement(port="render/1")
    with pytest.raises(ValueError, match="five Ports"):
        Requirement(port="parse")


def test_the_requirement_port_grammar_matches_the_cards_own() -> None:
    assert resolve_module._PORT_RE.pattern == PORT_RE.pattern


# --------------------------------------------------------------------------------------------
# 8. INV-5 — [drivers] enabled is the one gate that is NOT inside resolve()
# --------------------------------------------------------------------------------------------


def test_no_reject_code_and_no_gate_exists_for_a_driver_absent_from_drivers_enabled() -> None:
    """04-driver-system.md:1360: `[drivers] enabled` is "the gate that is not inside `resolve()`
    at all", and the twenty-six members carry no code for it — the same fact, stated twice."""
    assert not [code for code in RejectCode if "ENABLED" in code.name]
    assert not [gate for gate in GATE_ORDER if "enabled" in gate.name]


@pytest.mark.parametrize(
    ("other", "why"),
    [
        (frozenset(), "an empty enabled list"),
        (frozenset({"parse.other.driver"}), "an enabled list naming a DIFFERENT driver"),
    ],
)
def test_two_policies_differing_only_in_enabled_yield_the_same_candidate_set(
    other: frozenset[str], why: str
) -> None:
    """`[drivers] enabled` moves `policy_digest` and moves no candidate (04:1360).

    **The second case is the one that carries the property.** An `enabled` gate written inside
    `resolve()` as `if policy.enabled and driver_id not in policy.enabled` — the natural way to
    write it, treating an empty list as "unrestricted" — is invisible to the empty-set pair,
    because the empty set takes that guard's own early exit. It was applied as a mutation and this
    file stayed green. A non-empty list naming somebody else is what a real misplaced gate refuses.
    """
    subject = card()
    library = catalog_of(subject)
    listed = policy(enabled=frozenset({subject.identity.id}))
    unlisted = policy(enabled=other)
    requirement = parse_requirement()
    left, right = resolve(requirement, library, listed), resolve(requirement, library, unlisted)
    assert [c.driver_id for c in left.candidates] == [subject.identity.id], why
    assert [c.driver_id for c in right.candidates] == [subject.identity.id], why
    assert right.rejected == ()
    assert listed.policy_digest != unlisted.policy_digest
    assert left.resolution_digest != right.resolution_digest


# --------------------------------------------------------------------------------------------
# 9. One test per remaining gate
# --------------------------------------------------------------------------------------------


def test_a_port_major_this_build_does_not_implement_is_port_unsupported() -> None:
    subject = card(port="parse/2")
    rejection = only_rejection(
        resolve(
            Requirement(port="parse/2", format="application/pdf"),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.PORT_UNSUPPORTED
    assert str(sorted(PORT_MAJORS_SUPPORTED)) in rejection.detail


def test_asking_a_parse_card_for_derive_is_a_caller_bug_reported_as_a_rejection() -> None:
    subject = card()
    rejection = only_rejection(resolve(Requirement(port="derive/1"), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.PORT_MISMATCH


def test_a_colliding_id_never_wins_silently_and_an_explicit_row_lets_it_through() -> None:
    subject = card()
    library = catalog_of(subject)
    colliding = policy(collisions=frozenset({subject.identity.id}))
    rejection = only_rejection(resolve(parse_requirement(), library, colliding))
    assert rejection.code is RejectCode.ID_COLLISION_UNQUALIFIED
    disambiguated = policy(
        collisions=frozenset({subject.identity.id}),
        collision_resolution={subject.identity.id: "omniweave-pdf"},
    )
    assert len(resolve(parse_requirement(), library, disambiguated).candidates) == 1


def test_a_card_from_a_newer_grammar_is_card_schema_too_new_and_the_fix_is_an_upgrade() -> None:
    subject = dataclasses.replace(card(), card_schema=99)
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.CARD_SCHEMA_TOO_NEW
    assert "upgrade" in rejection.detail


def test_a_format_refusal_names_the_media_type_and_the_cards_own_list() -> None:
    subject = card()
    rejection = only_rejection(
        resolve(
            parse_requirement(format="application/x-ipynb+json"),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.FORMAT_UNSUPPORTED
    assert "application/x-ipynb+json" in rejection.detail
    assert "application/pdf" in rejection.detail


def test_a_requirement_demanding_a_produced_kind_the_card_lacks_is_produces_insufficient() -> None:
    subject = card()
    rejection = only_rejection(
        resolve(
            parse_requirement(requires_produces=frozenset({ArtifactKind.WITNESS_SET})),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.PRODUCES_INSUFFICIENT
    assert "witness_set" in rejection.detail


def test_a_granularity_the_card_does_not_declare_is_granularity_mismatch() -> None:
    subject = card(granularity="document")
    rejection = only_rejection(
        resolve(
            parse_requirement(granularity="part"),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.GRANULARITY_MISMATCH


def test_a_granularity_the_requirement_does_not_ask_for_is_not_a_gate() -> None:
    subject = card(granularity="corpus")
    resolution = resolve(
        parse_requirement(granularity=None),
        catalog_of(subject),
        policy(),
    )
    assert len(resolution.candidates) == 1


def test_a_computed_tier_outside_allow_tiers_is_licence_tier_not_allowed() -> None:
    subject = card(licence=RESTRICTED_LICENCE)
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.LICENCE_TIER_NOT_ALLOWED
    assert "restricted" in rejection.detail
    assert "allow_tiers" in rejection.detail


def test_the_tier_is_computed_from_card_facts_and_a_policy_cannot_override_it() -> None:
    """DR15 in the shape it has to have here: there is no field for a tier on `Policy`.

    An operator-supplied tier map would reinstate the mislabelling channel one level out from the
    card, so the absence of the field IS the enforcement. `omniweave_core.drivers.licence` owns
    the computation and `resolve()` calls it on every gate walk.
    """
    assert "tier_of" not in {f.name for f in dataclasses.fields(Policy)}
    assert "licence_seeds" in {f.name for f in dataclasses.fields(Policy)}
    assert TIER_ORDER == (
        LicenceTier.OPEN,
        LicenceTier.RESTRICTED,
        LicenceTier.COMMERCIAL,
        LicenceTier.FORBIDDEN,
    )


def test_a_seeded_licence_digest_computes_forbidden_and_survives_a_rename() -> None:
    """04-driver-system.md:1844: `forbidden` when a licence digest matches a shipped tombstone's.

    The seed set reaches `resolve()` through `Policy.licence_seeds` — 04:1379's "tombstone digest
    set ... loaded into `Policy` at startup" — and it is hash-keyed, so wrapping the same weights
    under a different driver id computes `forbidden` too.
    """
    subject = card(licence=RESTRICTED_LICENCE, id="parse.pdf.renamed")
    seeded = policy(
        allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED, LicenceTier.COMMERCIAL}),
        licence_seeds=LicenceSeeds(digests=frozenset({subject.licence_code.licence_sha256})),
    )
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), seeded))
    assert rejection.code is RejectCode.LICENCE_TIER_NOT_ALLOWED
    assert "forbidden" in rejection.detail


def test_a_restricted_driver_never_activates_without_an_ack() -> None:
    subject = card(licence=RESTRICTED_LICENCE)
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED})),
        )
    )
    assert rejection.code is RejectCode.LICENCE_ACK_MISSING
    assert "Installation is not consent" in rejection.detail
    assert subject.licence_code.licence_sha256 in rejection.detail


def test_a_mutated_licence_text_makes_the_ack_stale_and_the_hash_diff_is_printed() -> None:
    """04-driver-system.md:1911 makes this a REQUIRED test, "with the hash diff printed"."""
    subject = card(licence=RESTRICTED_LICENCE)
    signed_against = "sha256:" + "de" * 32
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                allow_tiers=frozenset({LicenceTier.RESTRICTED}),
                acks=ack_set(subject, signed_against),
            ),
        )
    )
    assert rejection.code is RejectCode.LICENCE_ACK_STALE
    assert signed_against in rejection.detail
    assert subject.licence_code.licence_sha256 in rejection.detail
    assert "first differ" in rejection.detail


def test_a_valid_ack_bound_to_the_installed_licence_hash_activates_the_driver() -> None:
    subject = card(licence=RESTRICTED_LICENCE)
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            allow_tiers=frozenset({LicenceTier.RESTRICTED}),
            acks=ack_set(subject, subject.licence_code.licence_sha256),
        ),
    )
    assert len(resolution.candidates) == 1


def test_an_ack_over_the_code_licence_never_acknowledges_the_weights_licence() -> None:
    """01-principles.md:205-209's Datalab trap, which is the case INV-5 was written for.

    A permissive `[licence.code]` over a restrictive `[licence.weights]`: `compute_tier` returns
    `restricted` because the weakest link governs, and the ack that clears it is the WEIGHTS row.
    The `AckSet` here is the sharpest wrong answer available — a `code` row carrying the WEIGHTS
    digest, i.e. an operator who signed the right text against the wrong artefact — and it must
    not satisfy the gate.

    Dropping `(AckWhich.WEIGHTS, card.licence_weights)` from `_first_ack_failure`'s artefact
    tuple was a surviving mutation before this test: every restricted fixture in this file
    declared its restriction on `[licence.code]`, so the second half of "one row per licensed
    artefact" (04:1903) was never executed.
    """
    subject = card(licence=PERMISSIVE_CODE_RESTRICTIVE_WEIGHTS)
    assert subject.licence_code.spdx == "Apache-2.0"
    weights_digest = subject.licence_weights.licence_sha256
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED}),
                acks=ack_set(subject, weights_digest, which=AckWhich.CODE),
            ),
        )
    )
    assert rejection.code is RejectCode.LICENCE_ACK_MISSING
    assert "(weights)" in rejection.detail
    assert weights_digest in rejection.detail


def test_an_ack_bound_to_the_weights_licence_activates_the_datalab_shaped_driver() -> None:
    subject = card(licence=PERMISSIVE_CODE_RESTRICTIVE_WEIGHTS)
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED}),
            acks=ack_set(subject, subject.licence_weights.licence_sha256, which=AckWhich.WEIGHTS),
        ),
    )
    assert len(resolution.candidates) == 1


def test_an_open_driver_needs_no_ack_at_all() -> None:
    subject = card()
    resolution = resolve(parse_requirement(), catalog_of(subject), policy())
    assert len(resolution.candidates) == 1
    assert subject.licence_code.spdx == "Apache-2.0"


def test_a_territorial_exclusion_is_a_local_refusal_naming_the_jurisdiction() -> None:
    subject = card(licence='\n[licence.code]\nspdx = "MIT"\nterritory_excluded = ["DE"]\n')
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                jurisdiction="DE",
                allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED}),
            ),
        )
    )
    assert rejection.code is RejectCode.LICENCE_TIER_NOT_ALLOWED
    assert "territory_excluded" in rejection.detail and "'DE'" in rejection.detail


def test_a_field_of_use_exclusion_is_a_local_refusal_naming_the_field() -> None:
    subject = card(
        licence=(
            '\n[licence.code]\nspdx = "MIT"\nfield_of_use_excluded = ["enterprise_documents"]\n'
        )
    )
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                fields_of_use=frozenset({"enterprise_documents"}),
                allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED}),
            ),
        )
    )
    assert rejection.code is RejectCode.LICENCE_TIER_NOT_ALLOWED
    assert "field_of_use_excluded" in rejection.detail


def test_a_territorial_exclusion_on_the_weights_table_is_a_local_refusal_too() -> None:
    """The exclusion declared on `[licence.weights]`, which the code table does not mention.

    `_local_licence_refusal` walks both tables and the tests above only ever exercised the first,
    so narrowing that walk to `(("code", card.licence_code),)` was a surviving mutation. A model
    whose WEIGHTS bar a territory bars it whatever the code licence says, and the detail has to
    name which of the two tables refused or an operator cannot find the clause.
    """
    subject = card(licence=TERRITORIAL_WEIGHTS)
    assert subject.licence_code.territory_excluded == ()
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                jurisdiction="DE",
                allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED}),
            ),
        )
    )
    assert rejection.code is RejectCode.LICENCE_TIER_NOT_ALLOWED
    assert "[licence.weights] territory_excluded" in rejection.detail
    assert "'DE'" in rejection.detail


def test_a_jurisdiction_a_card_does_not_exclude_is_not_a_refusal() -> None:
    subject = card(licence='\n[licence.code]\nspdx = "MIT"\nterritory_excluded = ["CN"]\n')
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            jurisdiction="DE",
            allow_tiers=frozenset({LicenceTier.OPEN, LicenceTier.RESTRICTED}),
        ),
    )
    assert len(resolution.candidates) == 1


def test_a_cost_class_above_the_requirements_ceiling_is_not_permitted() -> None:
    subject = card(BILLED)
    rejection = only_rejection(
        resolve(
            parse_requirement(max_cost_class=CostClass.LOCAL_COMPUTE),
            catalog_of(subject),
            policy(
                allow_cost_classes=frozenset(COST_CLASS_ORDER),
            ),
        )
    )
    assert rejection.code is RejectCode.COST_CLASS_NOT_PERMITTED
    assert "max_cost_class" in rejection.detail


def test_a_cost_class_absent_from_allow_classes_is_not_permitted() -> None:
    subject = card(BILLED)
    rejection = only_rejection(
        resolve(
            parse_requirement(max_cost_class=CostClass.BILLED_API),
            catalog_of(subject),
            policy(),
        )
    )
    assert rejection.code is RejectCode.COST_CLASS_NOT_PERMITTED
    assert "allow_classes" in rejection.detail


def test_a_card_with_no_cost_model_has_declared_no_cost_and_that_reads_as_free() -> None:
    subject = card()
    assert subject.cost_model is None
    resolution = resolve(
        parse_requirement(max_cost_class=CostClass.FREE),
        catalog_of(subject),
        policy(
            allow_cost_classes=frozenset({CostClass.FREE}),
        ),
    )
    assert len(resolution.candidates) == 1


def test_the_cost_class_order_is_cheapest_first() -> None:
    assert COST_CLASS_ORDER == (CostClass.FREE, CostClass.LOCAL_COMPUTE, CostClass.BILLED_API)


def test_a_gpu_a_host_does_not_have_is_hardware_absent() -> None:
    subject = card('\n[hardware]\ngpu = "required"\nvram_gb_min = 24.0\n')
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.HARDWARE_ABSENT
    assert "gpu_present" in rejection.detail


def test_a_binary_shutil_which_did_not_find_is_binary_absent_and_names_it() -> None:
    subject = card('\n[hardware]\nneeds_binaries = ["tesseract", "pdftoppm"]\n')
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.BINARY_ABSENT
    assert "pdftoppm" in rejection.detail
    assert "tesseract'" not in rejection.detail


def test_hardware_is_checked_before_binaries_because_that_is_the_printed_order() -> None:
    subject = card('\n[hardware]\ngpu = "required"\nneeds_binaries = ["nonesuch"]\n')
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.HARDWARE_ABSENT


def test_a_hardware_demand_with_no_declared_host_environment_fails_closed() -> None:
    subject = card("\n[hardware]\nneeds_network = true\n")
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                host_env=None,
            ),
        )
    )
    assert rejection.code is RejectCode.HARDWARE_ABSENT
    assert "host_env_undeclared" in rejection.detail


def test_a_card_with_no_hardware_demand_needs_no_declared_environment() -> None:
    subject = card()
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            host_env=None,
        ),
    )
    assert len(resolution.candidates) == 1


DERIVE_CAPABILITY = """
[capability.derive]
items = ["segment"]
scope_honoured = true
"""
"""A minimal honest `[capability.derive]` table.

`scope_honoured = false` makes a derive card permanently unactivatable
(04-driver-system.md:686), so a corpus test that wanted to assert anything else
would never reach its own gate."""


def corpus_card(text: str = "", *, produces: str = '"graph_items"', **fmt: str) -> DriverCard:
    """A corpus-granularity `derive/1` card, honest about scope."""
    return card(
        DERIVE_CAPABILITY + text,
        produces=produces,
        id=fmt.get("id", "derive.merge.llm"),
        port="derive/1",
        granularity="corpus",
    )


def test_a_billed_corpus_driver_declaring_no_witness_set_is_refused() -> None:
    subject = corpus_card(BILLED)
    rejection = only_rejection(
        resolve(
            Requirement(port="derive/1", max_cost_class=CostClass.BILLED_API),
            catalog_of(subject),
            policy(allow_cost_classes=frozenset(COST_CLASS_ORDER)),
        )
    )
    assert rejection.code is RejectCode.NO_WITNESS_SET
    assert rejection.gate == "witness_set_or_cohort"


def test_a_free_corpus_driver_may_take_the_cohort_route_and_is_not_refused() -> None:
    subject = corpus_card(id="derive.merge.local")
    resolution = resolve(Requirement(port="derive/1"), catalog_of(subject), policy())
    assert len(resolution.candidates) == 1


def test_a_billed_corpus_driver_declaring_a_witness_set_passes() -> None:
    subject = corpus_card(BILLED, produces='"graph_items", "witness_set"')
    resolution = resolve(
        Requirement(port="derive/1", max_cost_class=CostClass.BILLED_API),
        catalog_of(subject),
        policy(allow_cost_classes=frozenset(COST_CLASS_ORDER)),
    )
    assert len(resolution.candidates) == 1


def test_a_billed_document_granularity_driver_needs_no_witness_set() -> None:
    subject = card(BILLED)
    resolution = resolve(
        parse_requirement(max_cost_class=CostClass.BILLED_API),
        catalog_of(subject),
        policy(allow_cost_classes=frozenset(COST_CLASS_ORDER)),
    )
    assert len(resolution.candidates) == 1


def test_a_quarantined_driver_is_refused_for_the_rest_of_the_run() -> None:
    subject = card()
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                quarantined=frozenset({subject.identity.id}),
            ),
        )
    )
    assert rejection.code is RejectCode.QUARANTINED
    assert "crash_quarantine" in rejection.detail


def test_an_unattested_card_is_refused_unless_explicitly_pinned() -> None:
    subject = card()
    assert subject.attested is False
    library = catalog_of(subject)
    strict = policy(allow_unattested=False)
    rejection = only_rejection(resolve(parse_requirement(), library, strict))
    assert rejection.code is RejectCode.UNATTESTED
    pinned = parse_requirement(pinned=subject.identity.id)
    assert len(resolve(pinned, library, strict).candidates) == 1


def test_a_pin_in_the_qualified_id_at_dist_form_also_waives_attestation() -> None:
    subject = card()
    pinned = parse_requirement(pinned=f"{subject.identity.id}@omniweave-pdf")
    resolution = resolve(
        pinned,
        catalog_of(subject),
        policy(
            allow_unattested=False,
        ),
    )
    assert len(resolution.candidates) == 1


def test_an_unlocked_id_is_refused_when_require_lock_is_the_shipped_default() -> None:
    subject = card()
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                require_lock=True,
            ),
        )
    )
    assert rejection.code is RejectCode.NOT_IN_LOCKFILE
    assert "omniweave.lock" in rejection.detail


def test_an_isolation_mode_this_build_cannot_grant_is_isolation_not_permitted() -> None:
    assert ISOLATION_CONTAINMENT == (Isolation.INPROC, Isolation.SUBPROC)
    subject = card('\n[isolation]\nrequires = "wasm"\n')
    rejection = only_rejection(resolve(parse_requirement(), catalog_of(subject), policy()))
    assert rejection.code is RejectCode.ISOLATION_NOT_PERMITTED
    assert "not\nbuilt at v1" in rejection.detail or "not built at v1" in rejection.detail


def test_an_operator_naming_an_untrusted_id_in_drivers_inproc_is_trust_insufficient() -> None:
    subject = card()
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject, trust={subject.identity.id: TrustTier.UNPINNED}),
            policy(
                inproc_ids=frozenset({subject.identity.id}),
            ),
        )
    )
    assert rejection.code is RejectCode.TRUST_INSUFFICIENT
    assert sorted(t.value for t in INPROC_TRUST) == ["first_party", "vendored"]


# --------------------------------------------------------------------------------------------
# 10. Degradations — a shortfall and a deprecation window are not refusals
# --------------------------------------------------------------------------------------------


INPROC_REQUEST = '\n[isolation]\nrequires = "inproc"\n'


def test_a_card_asking_for_inproc_that_fails_a_conjunct_runs_subproc_and_records_it() -> None:
    subject = card(INPROC_REQUEST)
    resolution = resolve(parse_requirement(), catalog_of(subject), policy())
    assert len(resolution.candidates) == 1
    assert resolution.candidates[0].isolation_granted is Isolation.SUBPROC
    assert [d.kind for d in resolution.degradations] == ["isolation_shortfall"]
    assert "listed_in_drivers_inproc" in resolution.degradations[0].detail


def test_a_card_meeting_all_six_conjuncts_is_granted_inproc() -> None:
    subject = card(
        INPROC_REQUEST + '\n[quality.suites]\nfuzz = "pass"\n',
        id="parse.office.anydoc",
    )
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject, trust={subject.identity.id: TrustTier.VENDORED}),
        policy(
            inproc_ids=frozenset({subject.identity.id}),
        ),
    )
    assert resolution.candidates[0].isolation_granted is Isolation.INPROC
    assert resolution.degradations == ()


def test_a_card_asking_for_subproc_is_never_relaxed_to_inproc_by_config() -> None:
    subject = card('\n[quality.suites]\nfuzz = "pass"\n', id="parse.office.anydoc")
    assert subject.isolation.requires is Isolation.SUBPROC
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject, trust={subject.identity.id: TrustTier.VENDORED}),
        policy(
            inproc_ids=frozenset({subject.identity.id}),
            isolation_floor=Isolation.INPROC,
        ),
    )
    assert resolution.candidates[0].isolation_granted is Isolation.SUBPROC


DEPRECATED = """
[deprecation]
since = "0.1.0"
removed_in = "0.3.0"
replaced_by = "parse.pdf.pdfium2"
reason = "pdfium 6.x changes glyph run grouping."
"""


def test_a_driver_inside_its_deprecation_window_still_runs_and_names_its_replacement() -> None:
    subject = card(DEPRECATED)
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            release="0.2.0",
        ),
    )
    assert len(resolution.candidates) == 1
    assert [d.kind for d in resolution.degradations] == ["deprecation"]
    assert "parse.pdf.pdfium2" in resolution.degradations[0].detail


def test_a_driver_past_removed_in_is_deprecated_removed_and_resolves_to_a_reason() -> None:
    subject = card(DEPRECATED)
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                release="0.3.0",
            ),
        )
    )
    assert rejection.code is RejectCode.DEPRECATED_REMOVED
    assert "parse.pdf.pdfium2" in rejection.detail
    assert "glyph run grouping" in rejection.detail


def test_a_driver_before_its_deprecation_window_records_nothing() -> None:
    subject = card(DEPRECATED)
    resolution = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            release="0.0.9",
        ),
    )
    assert len(resolution.candidates) == 1
    assert resolution.degradations == ()


def test_a_resolve_degradation_kind_outside_the_two_is_refused() -> None:
    assert frozenset({"deprecation", "isolation_shortfall"}) == RESOLVE_DEGRADATION_KINDS
    with pytest.raises(ValueError, match="DegradationKind"):
        ResolveDegradation(kind="quarantine", driver_id="parse.pdf.pdfium", detail="x")


# --------------------------------------------------------------------------------------------
# 11. The Candidate, the config and resolution_report()
# --------------------------------------------------------------------------------------------


CONFIG_SCHEMA = """
[config]
type = "object"
additionalProperties = false

[config.properties.dpi]
type = "integer"
minimum = 72
maximum = 600
default = 200
"""


def test_a_candidates_effective_config_fills_the_cards_declared_defaults() -> None:
    subject = card(CONFIG_SCHEMA)
    resolution = resolve(parse_requirement(), catalog_of(subject), policy())
    candidate = resolution.candidates[0]
    assert dict(candidate.effective_config) == {"dpi": 200}
    assert candidate.config_digest == sha256_canonical({"dpi": 200})


def test_two_callers_supplying_one_config_in_a_different_order_share_a_config_digest() -> None:
    subject = card(CONFIG_SCHEMA)
    left = resolve(
        parse_requirement(),
        catalog_of(subject),
        policy(
            driver_config={subject.identity.id: {"dpi": 300}},
        ),
    )
    assert left.candidates[0].config_digest == sha256_canonical({"dpi": 300})


def test_a_config_value_the_cards_schema_refuses_is_a_rejection_and_never_a_raise() -> None:
    subject = card(CONFIG_SCHEMA)
    rejection = only_rejection(
        resolve(
            parse_requirement(),
            catalog_of(subject),
            policy(
                driver_config={subject.identity.id: {"dpi": 5000}},
            ),
        )
    )
    assert rejection.code is RejectCode.CARD_INVALID
    assert rejection.detail.startswith("config_invalid:")


def test_the_report_row_stores_the_enums_own_lower_case_wire_value() -> None:
    subject = card()
    resolution = resolve(
        parse_requirement(format="application/x-nonesuch"),
        catalog_of(subject),
        policy(),
    )
    report = resolution_report(resolution)
    rejected = report["report_json"]["rejected"]  # type: ignore[index]
    assert rejected[0]["code"] == "format_unsupported"
    assert rejected[0]["symbol"] == "OW_DRIVER_FORMAT_UNSUPPORTED"
    assert rejected[0]["gate"] == "format_supported"


def test_the_report_holds_the_whole_requirement_in_canonical_json() -> None:
    requirement = parse_requirement(granularity="part", pinned="parse.pdf.pdfium")
    subject = card()
    report = resolution_report(resolve(requirement, catalog_of(subject), policy()))
    assert set(report["requirement_json"]) == set(REQUIREMENT_FIELDS)  # type: ignore[arg-type]
    assert sha256_canonical(report["requirement_json"]) == requirement.digest  # type: ignore[arg-type]


def test_the_report_counts_every_driver_considered() -> None:
    good, bad = card(id="parse.aaa.one"), card(id="parse.bbb.two")
    resolution = resolve(
        parse_requirement(floors={"marks": True}),
        catalog_of(good, bad),
        policy(),
    )
    report = resolution_report(resolution)
    assert report["report_json"]["considered"] == 2  # type: ignore[index]


def test_the_resolution_digest_carries_the_sha256_prefix_the_plan_prints() -> None:
    subject = card()
    resolution = resolve(parse_requirement(), catalog_of(subject), policy())
    assert resolution.resolution_digest.startswith("sha256:")
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", resolution.resolution_digest)
    assert re.fullmatch(r"[0-9a-f]{64}", resolution.requirement.digest)
    assert re.fullmatch(r"[0-9a-f]{64}", resolution.policy_digest)


def test_the_resolution_digest_moves_when_any_of_its_three_key_digests_moves() -> None:
    """A moved `catalog_digest` and a moved `requirement_digest` each move the digest.

    This says nothing at all about the outcome, and the docstring it replaces claimed it did:
    both halves below hold for a digest taken over the three key strings ALONE — the first moves
    `catalog_digest` and the second moves `requirement_digest`. Deleting `candidates` and
    `rejected` from `Resolution._digest()` was a surviving mutation until
    `test_the_resolution_digest_covers_the_outcome_and_not_only_its_key` was written, and that
    test is where the plan's own reason for the digest ("two runs agreeing on the digest agree on
    what resolution decided") is actually asserted."""
    thin = card('\n[capability.parse]\ntables = "cells"\n', id="parse.aaa.thin")
    rich = card('\n[capability.parse]\ntables = "cells_with_spans"\n', id="parse.aaa.thin")
    requirement = parse_requirement(floors={"tables": "cells"})
    rules = policy()
    left = resolve_uncached(requirement, catalog_of(thin), rules)
    right = resolve_uncached(requirement, catalog_of(rich), rules)
    assert left.catalog_digest != right.catalog_digest
    assert left.resolution_digest != right.resolution_digest
    assert [c.driver_id for c in left.candidates] == [c.driver_id for c in right.candidates]
    demanding = parse_requirement(floors={"tables": "cells_with_spans"})
    refused = resolve_uncached(demanding, catalog_of(thin), rules)
    assert refused.candidates == ()
    assert refused.resolution_digest != left.resolution_digest


def test_the_resolution_digest_covers_the_outcome_and_not_only_its_key() -> None:
    """Eight resolutions over ONE `(requirement, policy, catalog)` key, eight distinct digests.

    `resolve()` cannot produce this pair — it is deterministic, so equal keys give equal outcomes
    — which is exactly why the outcome half of the recipe has to be asserted on the constructor.
    `Resolution` takes `catalog_digest` and `policy_digest` as plain strings, so the eight values
    below share all three key digests and differ only in what resolution DECIDED: which driver
    survived, what isolation it was granted, which config digest it carries, which code refused
    it and what the refusal said.

    `adr/0007-driver-resolution-keys.md` records that the plan prints no recipe for
    `resolution_digest`, and `resolve.py`'s own docstring states the engineering call this test
    pins: "the three memo-key strings plus the *outcome* ... so that two runs agreeing on the
    digest agree on what resolution decided and not merely on what it was asked". A digest over
    the three key strings alone satisfies every other digest test in this file.
    """
    requirement = parse_requirement()
    one, two = card(id="parse.aaa.one"), card(id="parse.bbb.two")

    def built(
        candidates: tuple[Candidate, ...] = (), rejected: tuple[Rejection, ...] = ()
    ) -> Resolution:
        return Resolution(
            requirement=requirement,
            candidates=candidates,
            rejected=rejected,
            catalog_digest="a" * 64,
            policy_digest="b" * 64,
        )

    def candidate(subject: DriverCard, isolation: Isolation, digest: str) -> Candidate:
        return Candidate(
            card=subject,
            isolation_granted=isolation,
            effective_config={},
            config_digest=digest,
        )

    outcomes = (
        built(),
        built(candidates=(candidate(one, Isolation.SUBPROC, "c0"),)),
        built(candidates=(candidate(two, Isolation.SUBPROC, "c0"),)),
        built(candidates=(candidate(one, Isolation.INPROC, "c0"),)),
        built(candidates=(candidate(one, Isolation.SUBPROC, "c1"),)),
        built(rejected=(Rejection("parse.aaa.one", RejectCode.FORMAT_UNSUPPORTED, "no pdf"),)),
        built(rejected=(Rejection("parse.aaa.one", RejectCode.QUARANTINED, "no pdf"),)),
        built(rejected=(Rejection("parse.aaa.one", RejectCode.FORMAT_UNSUPPORTED, "no xlsx"),)),
    )
    assert len({outcome.resolution_digest for outcome in outcomes}) == len(outcomes)
    keys = {
        (outcome.requirement.digest, outcome.policy_digest, outcome.catalog_digest)
        for outcome in outcomes
    }
    assert len(keys) == 1


LOCK_WITH_A_WRONG_TIER = """
lock_version = 1
release = "0.1.0"
contract = 1

[[driver]]
id = "parse.pdf.pdfium"
version = "0.1.0"
dist = "omniweave-pdf"
dist_sha256 = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
card_sha256 = "sha256:0000000000000000000000000000000000000000000000000000000000000000"
tier = "restricted"
restriction_bits = 0
"""
"""An `omniweave.lock` whose recorded tier is a lie about an Apache-2.0 card.

`card_sha256` is sixty-four zeroes, which is drift by construction: `verify` and `check`
read different columns of the same row and each has to fail on its own column."""


# --------------------------------------------------------------------------------------------
# 12. tools/ow_drivers.py -- the four verbs' runner, under ledger D25
# --------------------------------------------------------------------------------------------


def run_verb(*argv: str) -> tuple[int, str]:
    """The runner, with its report captured. Nothing here writes to the real stdout."""
    buffer = StringIO()
    code = runner.main(list(argv), out=buffer)
    return code, buffer.getvalue()


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A project root holding one card, so the runner has something to read."""
    directory = tmp_path / "cards" / "pdfium"
    directory.mkdir(parents=True)
    (directory / "driver.toml").write_text(
        MINIMAL_CARD.format(
            id="parse.pdf.pdfium",
            port="parse/1",
            granularity="document",
            produces='"doc_fragment"',
        )
        + OPEN_LICENCE,
        encoding="utf-8",
    )
    return tmp_path


def test_the_runners_verbs_are_w3_1s_four_and_a_subset_of_the_groups_seven(plan) -> None:
    """16-roadmap.md:481 names four verbs; 04-driver-system.md:1449 makes the whole `ow drivers`
    group **exactly seven** and says no eighth may be added without amending the generated agent
    surface (G25). So a fifth verb here would be a fifth of the four, and a verb outside the seven
    would be an eighth of the group. Both are read off the documents rather than restated."""
    plan.require()
    parser = runner._parser()
    verb = next(action for action in parser._actions if action.dest == "verb")
    assert set(verb.choices) == {"list", "check", "verify", "explain"}
    seven = plan.grep(
        r"`scaffold`, `list`, `add`, `verify`, `check`, `explain`, `ack`",
        documents=["04-driver-system.md"],
    )
    assert len(seven) == 1, seven
    assert set(verb.choices) <= {
        "scaffold",
        "list",
        "add",
        "verify",
        "check",
        "explain",
        "ack",
    }


def test_the_three_exit_codes_are_distinguished() -> None:
    assert (runner.EXIT_CLEAN, runner.EXIT_FAIL, runner.EXIT_NOT_RUN) == (0, 1, 2)


def test_no_verb_can_import_a_card_entrypoint_because_the_runner_cannot_import_at_all() -> None:
    """G11 / INV-4, as an assertion rather than as a sentence in the runner's docstring.

    `tools/ow_drivers.py` says of itself that it "does **not** activate a driver ... so
    `ow drivers list` over a hostile wheel imports nothing (INV-4, G11)", and until this test
    existed nothing checked it: adding `importlib.import_module(card.identity.entrypoint...)` to
    `verb_list` — an `activate()` bypass, on the one code path whose whole purpose is to be
    runnable against an untrusted tree — left every test in this file green.

    The import roots are pinned as a literal, the way `resolve.py`'s are, and the dynamic-import
    call names are refused by name because a root set alone would miss `__import__`, which needs
    no import of its own. `discovery` is imported and that is the point of the split:
    `omniweave_core.discovery` reads metadata and never imports a distribution (G11), which is
    `tools/ow_discover.py`'s subject and not this one's.
    """
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
    assert roots == TOOL_IMPORT_ROOTS
    assert not called & BANNED_DYNAMIC_IMPORT_CALLS


def test_list_filters_on_port_and_the_filter_selects_rather_than_excludes(tmp_path: Path) -> None:
    """`--port parse/1` prints the parse driver and not the derive one.

    Inverting the comparison to `!=` was a surviving mutation: no test passed `--port` to `list`
    at all, so the verb's one filter was reachable only through `explain`, where the same argument
    means something else entirely (it builds the `Requirement`).
    """
    for driver_id, port in (("parse.pdf.pdfium", "parse/1"), ("derive.graph.local", "derive/1")):
        directory = tmp_path / "cards" / driver_id
        directory.mkdir(parents=True)
        (directory / "driver.toml").write_text(
            MINIMAL_CARD.format(
                id=driver_id, port=port, granularity="document", produces='"doc_fragment"'
            )
            + OPEN_LICENCE,
            encoding="utf-8",
        )
    code, report = run_verb(
        "list", "--root", str(tmp_path), "--cards", str(tmp_path / "cards"), "--port", "parse/1"
    )
    assert code == runner.EXIT_CLEAN
    assert "parse.pdf.pdfium" in report
    assert "derive.graph.local" not in report
    _, both = run_verb("list", "--root", str(tmp_path), "--cards", str(tmp_path / "cards"))
    assert "parse.pdf.pdfium" in both and "derive.graph.local" in both


def test_list_prints_not_enabled_for_a_driver_absent_from_drivers_enabled(tree: Path) -> None:
    """The column INV-5 exists for. `resolve()` does not apply this gate (:1360), so
    the listing is the only place an operator learns that an installed, attested, locked
    driver can never run."""
    code, report = run_verb("list", "--root", str(tree), "--cards", str(tree / "cards"))
    assert code == runner.EXIT_CLEAN
    assert "NOT ENABLED" in report
    assert "[drivers] enabled" in report and "INV-5" in report
    code, enabled_report = run_verb(
        "list",
        "--root",
        str(tree),
        "--cards",
        str(tree / "cards"),
        "--enabled",
        "parse.pdf.pdfium",
    )
    assert code == runner.EXIT_CLEAN
    assert "NOT ENABLED" not in enabled_report


def test_check_exits_non_zero_when_a_locked_tier_disagrees_with_compute_tier(tree: Path) -> None:
    """02-architecture.md:1194 and 04-driver-system.md:1626, in as many words.

    The card's facts are `Apache-2.0` and compute `open`; the lock row claims `restricted`.
    The lock is a witness rather than an authority, so the disagreement is the finding."""
    (tree / "omniweave.lock").write_text(LOCK_WITH_A_WRONG_TIER, encoding="utf-8")
    code, report = run_verb("check", "--root", str(tree), "--cards", str(tree / "cards"))
    assert code == runner.EXIT_FAIL
    assert "records licence tier 'restricted'" in report
    assert "compute 'open'" in report


def test_check_posture_prints_the_tier_the_bits_and_the_restriction_names(tmp_path: Path) -> None:
    """`--posture` is section 7.4's report mode, and nothing exercised it.

    Turning the whole `if posture:` block off was a surviving mutation, which is what an untested
    flag always is. The card here is AGPL-3.0-only, so the posture line has content to print: the
    tier is `restricted`, the restriction is `copyleft_network`, and its bit is `1 << 10` — the
    tenth of section 7.2's twelve, `COPYLEFT_STRONG=11` being the last (04-driver-system.md:1868).
    The hex is written out rather than recomputed here; a test that called `restriction_bits`
    itself would print the runner's own answer back at it.
    """
    directory = tmp_path / "cards" / "pdfium"
    directory.mkdir(parents=True)
    (directory / "driver.toml").write_text(
        MINIMAL_CARD.format(
            id="parse.pdf.pdfium",
            port="parse/1",
            granularity="document",
            produces='"doc_fragment"',
        )
        + RESTRICTED_LICENCE,
        encoding="utf-8",
    )
    code, report = run_verb(
        "check", "--root", str(tmp_path), "--cards", str(tmp_path / "cards"), "--posture"
    )
    assert code == runner.EXIT_CLEAN
    assert "parse.pdf.pdfium" in report
    assert "restricted" in report
    assert "bits=0x400" in report
    assert "['copyleft_network']" in report
    _, without = run_verb("check", "--root", str(tmp_path), "--cards", str(tmp_path / "cards"))
    assert "bits=0x400" not in without


def test_check_is_clean_when_the_lock_agrees(tree: Path) -> None:
    (tree / "omniweave.lock").write_text(
        LOCK_WITH_A_WRONG_TIER.replace('tier = "restricted"', 'tier = "open"'),
        encoding="utf-8",
    )
    code, report = run_verb("check", "--root", str(tree), "--cards", str(tree / "cards"))
    assert code == runner.EXIT_CLEAN
    assert "every recorded tier agrees" in report


def test_verify_exits_non_zero_on_card_digest_drift_and_names_both_digests(tree: Path) -> None:
    (tree / "omniweave.lock").write_text(LOCK_WITH_A_WRONG_TIER, encoding="utf-8")
    code, report = run_verb("verify", "--root", str(tree), "--cards", str(tree / "cards"))
    assert code == runner.EXIT_FAIL
    assert "card_sha256 drift" in report
    assert "sha256:" + "0" * 64 in report


def test_verify_reports_dist_sha256_as_unverified_rather_than_inventing_a_recipe(
    tree: Path,
) -> None:
    """04-driver-system.md:1620 asks for both digests and prints a recipe for one.

    A comparison against a recipe this repository invented would be a comparison with
    itself, so the second half is reported as unverified with the citation."""
    (tree / "omniweave.lock").write_text(LOCK_WITH_A_WRONG_TIER, encoding="utf-8")
    _, report = run_verb("verify", "--root", str(tree), "--cards", str(tree / "cards"))
    assert "dist_sha256 UNVERIFIED" in report
    assert "RECORD walk" in report


def test_explain_prints_the_gate_that_refused_and_the_codes_toml_row(tree: Path) -> None:
    code, report = run_verb(
        "explain",
        "--root",
        str(tree),
        "--cards",
        str(tree / "cards"),
        "--port",
        "parse/1",
        "--format",
        "application/vnd.ms-excel",
        "--no-require-lock",
        "--allow-unattested",
    )
    assert code == runner.EXIT_CLEAN
    assert "format_unsupported" in report
    assert "OW-D-009 / OW_DRIVER_FORMAT_UNSUPPORTED" in report
    assert "gate format_supported" in report
    assert "resolution_digest sha256:" in report


def test_explain_exits_non_zero_on_a_zero_candidate_resolution_only_when_asked(tree: Path) -> None:
    """A zero-candidate `Resolution` IS the error message (:1366) and is not by
    itself a failure, which is why `--require-candidate` has to be a flag."""
    argv = (
        "explain",
        "--root",
        str(tree),
        "--cards",
        str(tree / "cards"),
        "--format",
        "application/x-nonesuch",
        "--no-require-lock",
        "--allow-unattested",
    )
    assert run_verb(*argv)[0] == runner.EXIT_CLEAN
    code, report = run_verb(*argv, "--require-candidate")
    assert code == runner.EXIT_FAIL
    assert "zero-candidate" in report


def test_explain_gates_prints_the_whole_order_with_a_plan_citation_per_gate(tree: Path) -> None:
    code, report = run_verb(
        "explain",
        "--root",
        str(tree),
        "--cards",
        str(tree / "cards"),
        "--gates",
        "--no-require-lock",
        "--allow-unattested",
    )
    assert code == runner.EXIT_CLEAN
    for gate in GATE_ORDER:
        assert gate.name in report
        assert gate.plan in report
    assert report.index("port_major_supported") < report.index("isolation_grantable")


def test_a_verb_that_cannot_read_its_tree_exits_two_and_not_one(tmp_path: Path) -> None:
    """`1` and `2` are distinguished because CI treats both as failure and a human
    needs to know which."""
    (tmp_path / "omniweave.lock").write_text("this is not toml [", encoding="utf-8")
    directory = tmp_path / "cards"
    directory.mkdir()
    code, report = run_verb("check", "--root", str(tmp_path), "--cards", str(directory))
    assert code == runner.EXIT_NOT_RUN
    assert "DID NOT RUN" in report


# ---------------------------------------------------------------------------------------------
# D574: the hardware gate reads CPython's spellings in the cards' vocabulary
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("machine", "canonical"),
    [("AMD64", "x86_64"), ("x86_64", "x86_64"), ("arm64", "aarch64"), ("aarch64", "aarch64")],
)
def test_cpython_s_machine_names_are_the_card_s_architectures(machine: str, canonical: str) -> None:
    """CPython reports `AMD64` on 64-bit Windows and `arm64` on Apple silicon; 04:912's cards say
    `x86_64` and `aarch64`. Compared raw, all three first-party drivers were HARDWARE_ABSENT on
    every Windows x64 host."""
    from omniweave_core.drivers.resolve import canonical_arch  # noqa: PLC0415

    assert canonical_arch(machine) == canonical


def test_win32_is_the_card_s_windows() -> None:
    from omniweave_core.drivers.resolve import canonical_os  # noqa: PLC0415

    assert (canonical_os("win32"), canonical_os("linux"), canonical_os("darwin")) == (
        "windows",
        "linux",
        "darwin",
    )


def test_the_office_card_passes_the_hardware_gate_on_a_windows_x64_host() -> None:
    """The real card through the real gate, with the host CPython reports on this platform class."""
    from omniweave_core.discovery import catalog  # noqa: PLC0415
    from omniweave_core.drivers.resolve import Policy, Requirement, resolve  # noqa: PLC0415
    from omniweave_ports.types import ProbeEnv  # noqa: PLC0415

    env = ProbeEnv(
        platform="win32", machine="AMD64", python=(3, 12), which={}, gpu_present=False,
        vram_gb=0.0, offline=False,
    )  # fmt: skip
    media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    policy = Policy(host_env=env, allow_unattested=True, require_lock=False)
    found = resolve(Requirement(port="parse/1", format=media), catalog(), policy)
    assert [one.driver_id for one in found.candidates] == ["parse.office.anydoc"]
