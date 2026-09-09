"""`load_card()` — the card grammar, the tombstone branch, the caps and the four digests.

The golden fixture is 04-driver-system.md section 3's complete card, and it is embedded here
BYTE FOR BYTE rather than paraphrased: `test_the_embedded_golden_card_is_the_plans_own` reads the
plan's own ```toml fence and asserts the two are identical, so a card that drifts from the
document fails here rather than in six months. Every other test in this module builds on
`MINIMAL`, the smallest card that loads, so a negative test asserts one thing.

The properties are 04-driver-system.md's:

* the complete card parses and every field lands with the value the document prints;
* each of section 4.5's seven caps: at the cap it loads, one over it is `CARD_INVALID` naming
  BOTH the key and the cap;
* `[tombstone]` branches before anything else is validated, which is observable because a
  tombstone has none of the four fields a `DriverCard` requires;
* `attestation` is a top-level key written before the first table header, and a card that puts
  it after one is refused rather than silently scoping it to that table;
* a comment-only edit moves `card_sha256` and does NOT move `attestation` — the whole reason
  both digests exist;
* the `forfeits` exception: an unknown MEMBER is kept, where an unknown member of every other
  set is dropped;
* an unknown key inside `[capability.<port>]` is ignored and recorded, and the same key in a
  `[<port>]` sibling or at the top level is a hard error;
* the `[config]` subset accepts its fourteen keyword spellings and refuses each of its ten
  rejected ones BY NAME;
* `MeasuredOn` with nine of its ten fields raises `TypeError` at construction (DR14).
"""

from __future__ import annotations

import hashlib
import tomllib

import pytest
from omniweave_core.canonical import sha256_canonical
from omniweave_core.drivers.card import (
    CARD_CAPABILITY_UNKNOWN,
    CONFIG_KEYWORDS,
    CONFIG_REJECTED_KEYWORDS,
    MEASURED_ON_FIELDS,
    MIN_SLICE_N,
    PARSE_LADDERS,
    PARSE_SETS,
    ArtifactKind,
    CostClass,
    DriverCard,
    FormatTokenPair,
    Isolation,
    MeasuredOn,
    Port,
    ReplayClass,
    Tombstone,
    attestation_of,
    card_sha256,
    load_card,
    pins_digest,
    served_tokens,
)
from omniweave_core.errors import ConfigError, DriverHostError, ResourceLimit, explain
from omniweave_core.limits import (
    MAX_CARD_BENCHMARKS,
    MAX_CARD_BINARIES,
    MAX_CARD_BYTES,
    MAX_CARD_CONFIG_PROPERTIES,
    MAX_CARD_DEPTH,
    MAX_CARD_FORMATS,
    MAX_CARD_PINS,
    MAX_ENTRY_BYTES,
    MAX_ENTRY_COUNT,
)

# --------------------------------------------------------------------------------------------
# The golden card — 04-driver-system.md section 3, verbatim.
# --------------------------------------------------------------------------------------------

GOLDEN = """# omniweave-driver-ipynb/src/omniweave_driver_ipynb/driver.toml
# ONE KEY PER LINE. `;` is not a TOML separator. An inline table may not span a newline.
# `attestation` is a TOP-LEVEL key and is written HERE, before the first table header: TOML scopes a
# bare key to the most recent header, so writing it at the end of the file would make it
# `quality.suites.attestation` and the loader's recomputation would read nothing.
card_schema = 1
attestation = "sha256:f745a15153c4dacf0ea4bbf57265e73283941f8335939b33c693975315cf5916"

[driver]
id             = "parse.notebook.ipynb"
port           = "parse/1"
version        = "0.1.0"
schema_version = 1
title          = "ipynb"
summary        = "Jupyter notebook decoder. Stdlib json only. Exact JSON-pointer node paths."
homepage       = "https://github.com/example/omniweave-driver-ipynb"
entrypoint     = "omniweave_driver_ipynb.driver:IpynbParser"
granularity    = "document"
replay_class   = "byte_exact"
detects        = true

[capability]
formats  = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[capability.parse]
spatial       = "none"
origin_span   = "exact"
text_span     = true
marks         = false
reading_order = "source"
sections      = "markdown_only"
tables        = "none"
math          = []
assets        = "bytes"
asset_origin  = true
notes         = "none"
confidence    = "none"
furniture     = "flagged"
round_trip    = "structure"
forfeits      = []
# `ipynb` is already one of core's forty-eight, so this is a CLAIM TO THE TOKEN — it puts the driver
# in `format_token_for`'s table for that media type — and not a widening of `unit.format`'s domain.
# PAIR-SHAPED (section 2.2): the media type is the lookup key, the token is what a rule matches, and
# `media_type` must also appear in `[capability] formats` above. An array MAY span newlines in TOML;
# each inline table may not.
format_tokens = [
  { media_type = "application/x-ipynb+json", token = "ipynb" },
]

[hardware]
gpu            = "none"
vram_gb_min    = 0
ram_gb_min     = 0.125
cpu_arch       = ["x86_64", "aarch64"]
os             = ["linux", "darwin", "windows"]
needs_network  = false
needs_binaries = []
imports_torch  = false
install_bytes  = 41000
services       = []

[isolation]
requires        = "subproc"
memory_mb       = 256
progress_ms     = 15000
wall_ms_hard    = 60000
batch_max_units = 32

[limits]
max_input_bytes = 67108864
max_parts       = 1

[licence.code]
spdx = "Apache-2.0"
licence_sha256 = "sha256:c693279643b8cd5d248172d9c22cb7cf4ed163a3c98c8a3f69c2717edd3eacb7"
licence_url = "https://github.com/example/omniweave-driver-ipynb/blob/v0.1.0/LICENSE"
notice_path = "NOTICE"
redistribution = "allowed"
output_share_alike = false
competitor_bar = false
requires_credential = false
revenue_gate_usd = 0
mau_gate = 0
territory_excluded = []
field_of_use_excluded = []
attribution_per_output = false
no_model_training = false
remote_kill_switch = false
clause_refs = []

[deps]
pins = []

[config]
type = "object"
additionalProperties = false
required = []
[config.properties.include_outputs]
type = "boolean"
default = true
[config.properties.max_output_chars]
type = "integer"
minimum = 0
maximum = 65536
default = 4096

[cost.model]
class   = "free"
shape   = "linear_per_byte"
unit    = "document"
per_part    = { wall_ms = 3 }
per_session = { }
scaling     = { key = "input_bytes", exponent = 1.0, reference = 65536 }
tokens_out_p95_multiple = 1.0
max_retries = 0

# ══ EVERYTHING BELOW IS WRITTEN BY `ow conform`. AUTHOR VALUES ARE REJECTED. ══
[cost.measured]
p50_ms_per_unit = 3
p95_ms_per_unit = 19
spend_per_unit  = { wall_ms = 3, cpu_ms = 3 }
hardware          = "x86_64-linux 8c/16GiB · min-of-5 warm · in-process"
hardware_spawn    = "x86_64-linux 8c/16GiB · min-of-5 warm · spawn-inclusive"
timing_basis      = "in_process"
# NOT `measured_on`: on a card `measured_on` is always the frozen ten-field MeasuredOn of
# [[quality.benchmark]], so a loader reading the wrong one gets a missing key, never a str
# where it expects a record. `timing_basis` already carries in-process versus spawn.

[quality]
kit_version = "1.0.0"
kit_run = "2026-09-02T11:04:18Z"
[quality.suites]
card = "pass"
purity = "pass"
contract = "pass"
capability = "pass"
idempotence = "pass"
determinism = "pass"
limits = "pass"
sandbox = "pass"
cost = "pass"
licence = "pass"
fuzz = "pass"
quality = "unknown"
"""

MINIMAL = """card_schema = 1

[driver]
id = "parse.notebook.ipynb"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "pkg.driver:Cls"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""

MEASURED_ON = dict.fromkeys(MEASURED_ON_FIELDS, "n/a")


def load(text: str, *, origin: str = "entry_point", source: str = "driver.toml") -> object:
    return load_card(text.encode("utf-8"), origin=origin, source=source)


def refusal(text: str, **kwargs: str) -> DriverHostError:
    """Load `text` expecting a refusal, and hand back the error so a test can read it."""
    with pytest.raises(DriverHostError) as caught:
        load(text, **kwargs)
    return caught.value


def benchmark_row(metric: str, n: int = MIN_SLICE_N) -> str:
    fields = "\n".join(f'{name} = "n/a"' for name in MEASURED_ON_FIELDS)
    return (
        f"\n[[quality.benchmark]]\n"
        f'metric = "{metric}"\nvalue = 0.9\nn = {n}\nci95 = [0.8, 0.95]\nwitness = "ci"\n'
        f"[quality.benchmark.measured_on]\n{fields}\n"
    )


# --------------------------------------------------------------------------------------------
# 1. The golden card
# --------------------------------------------------------------------------------------------


def test_the_embedded_golden_card_is_the_plans_own(plan) -> None:
    """The fixture is the document's text, not a paraphrase of it.

    A structural check would pass on a truncated card, which is the project's own hard-won
    lesson, so this compares the whole fence body byte for byte.
    """
    plan.require()
    fences = [
        body
        for body in plan.fences("04-driver-system.md", "toml")
        if 'id             = "parse.notebook.ipynb"' in body
    ]
    assert len(fences) == 1, "section 3's complete card is the only fence that declares that id"
    assert fences[0].strip() == GOLDEN.strip()


def test_the_complete_card_parses() -> None:
    card = load(GOLDEN)
    assert isinstance(card, DriverCard)
    assert card.card_schema == 1
    assert card.origin == "entry_point"


def test_every_driver_field_lands_with_the_printed_value() -> None:
    card = load(GOLDEN)
    assert isinstance(card, DriverCard)
    identity = card.identity
    assert identity.id == "parse.notebook.ipynb"
    assert (identity.port, identity.port_major) == (Port.PARSE, 1)
    assert identity.version == "0.1.0"
    assert identity.schema_version == 1
    assert identity.title == "ipynb"
    assert identity.summary.startswith("Jupyter notebook decoder.")
    assert identity.homepage == "https://github.com/example/omniweave-driver-ipynb"
    assert identity.entrypoint == "omniweave_driver_ipynb.driver:IpynbParser"
    assert identity.exec is None
    assert identity.granularity == "document"
    assert identity.replay_class is ReplayClass.BYTE_EXACT
    assert identity.detects is True


def test_every_capability_field_lands_with_the_printed_value() -> None:
    card = load(GOLDEN)
    assert isinstance(card, DriverCard)
    assert card.capability.formats == ("application/x-ipynb+json",)
    assert card.capability.consumes == frozenset({ArtifactKind.RAW_BYTES})
    assert card.capability.produces == frozenset({ArtifactKind.DOC_FRAGMENT})
    parse = card.parse
    assert parse is not None
    printed = {
        "spatial": "none",
        "origin_span": "exact",
        "text_span": True,
        "marks": False,
        "reading_order": "source",
        "sections": "markdown_only",
        "tables": "none",
        "assets": "bytes",
        "asset_origin": True,
        "notes": "none",
        "confidence": "none",
        "furniture": "flagged",
        "round_trip": "structure",
    }
    for field, value in printed.items():
        assert getattr(parse, field) == value, field
    assert parse.math == frozenset()
    assert parse.forfeits == frozenset()
    assert parse.format_tokens == (
        FormatTokenPair(media_type="application/x-ipynb+json", token="ipynb"),  # noqa: S106
    )
    assert card.degradations == ()


def test_every_remaining_table_lands_with_the_printed_value() -> None:
    card = load(GOLDEN)
    assert isinstance(card, DriverCard)
    assert card.hardware.gpu == "none"
    assert card.hardware.ram_gb_min == 0.125
    assert card.hardware.cpu_arch == ("x86_64", "aarch64")
    assert card.hardware.os == ("linux", "darwin", "windows")
    assert card.hardware.install_bytes == 41000
    assert card.isolation.requires is Isolation.SUBPROC
    assert (card.isolation.memory_mb, card.isolation.batch_max_units) == (256, 32)
    assert (card.isolation.progress_ms, card.isolation.wall_ms_hard) == (15000, 60000)
    assert card.limits.max_input_bytes == 67108864
    assert card.limits.max_parts == 1
    assert card.licence_code.spdx == "Apache-2.0"
    assert card.licence_code.redistribution == "allowed"
    assert card.licence_weights is None
    assert card.deps.pins == ()
    assert card.cost_model is not None
    assert card.cost_model.cost_class is CostClass.FREE
    assert card.cost_model.shape == "linear_per_byte"
    assert card.cost_model.unit == "document"
    assert dict(card.cost_model.per_part) == {"wall_ms": 3.0}
    assert dict(card.cost_model.per_session) == {}
    assert card.cost_model.scaling is not None
    assert card.cost_model.scaling.key == "input_bytes"
    assert card.cost_model.scaling.reference == 65536
    assert card.cost_measured is not None
    assert card.cost_measured.p95_ms_per_unit == 19
    assert card.cost_measured.timing_basis == "in_process"
    assert card.quality.kit_version == "1.0.0"
    assert card.quality.suites["quality"] == "unknown"
    assert len(card.quality.suites) == 12
    assert card.deprecation is None, "an ABSENT [deprecation] means 'not scheduled'"
    assert card.config.effective() == {"include_outputs": True, "max_output_chars": 4096}


def test_the_golden_cards_attestation_does_not_reproduce_and_that_is_not_a_rejection() -> None:
    """The printed digest is a placeholder in the document, so `attested` is False and the card
    still loads. Attestation is tamper-evidence, not authentication (section 8.3)."""
    card = load(GOLDEN)
    assert isinstance(card, DriverCard)
    assert card.attestation is not None
    assert card.attestation.startswith("sha256:")
    assert card.attested is False


# --------------------------------------------------------------------------------------------
# 2. The seven caps of section 4.5. At the cap it loads; one over it names the key AND the cap.
# --------------------------------------------------------------------------------------------


def test_max_card_bytes_at_the_cap_loads_and_one_over_is_refused() -> None:
    pad = MAX_CARD_BYTES - len(MINIMAL.encode()) - 2
    at_cap = MINIMAL + "\n#" + "x" * pad
    assert len(at_cap.encode()) == MAX_CARD_BYTES
    assert isinstance(load(at_cap), DriverCard)
    error = refusal(at_cap + "x")
    assert "MAX_CARD_BYTES" in str(error)
    assert str(MAX_CARD_BYTES) in str(error)
    assert error.code() == "OW_CARD_INVALID"


def test_max_card_depth_refuses_one_table_deeper_than_the_cap() -> None:
    at_cap = MINIMAL + "\n[" + ".".join("abcdef"[:MAX_CARD_DEPTH]) + "]\nx = 1\n"
    over = MINIMAL + "\n[" + ".".join("abcdefg"[: MAX_CARD_DEPTH + 1]) + "]\nx = 1\n"
    assert "nests deeper" not in str(refusal(at_cap)), "at the cap the depth check passes"
    error = refusal(over)
    assert "nests deeper" in str(error)
    assert str(MAX_CARD_DEPTH) in str(error)


def test_max_card_formats_at_the_cap_loads_and_one_over_names_the_key_and_the_cap() -> None:
    def card(count: int) -> str:
        members = ", ".join(f'"application/x-{i}"' for i in range(count))
        return MINIMAL.replace('formats = ["application/x-ipynb+json"]', f"formats = [{members}]")

    assert isinstance(load(card(MAX_CARD_FORMATS)), DriverCard)
    error = refusal(card(MAX_CARD_FORMATS + 1))
    assert "[capability] formats" in str(error)
    assert str(MAX_CARD_FORMATS) in str(error)


def test_max_card_binaries_at_the_cap_loads_and_one_over_names_the_key_and_the_cap() -> None:
    def card(count: int) -> str:
        members = ", ".join(f'"bin{i}"' for i in range(count))
        return MINIMAL + f"\n[hardware]\nneeds_binaries = [{members}]\n"

    assert isinstance(load(card(MAX_CARD_BINARIES)), DriverCard)
    error = refusal(card(MAX_CARD_BINARIES + 1))
    assert "[hardware] needs_binaries" in str(error)
    assert str(MAX_CARD_BINARIES) in str(error)


def test_max_card_pins_at_the_cap_loads_and_one_over_names_the_key_and_the_cap() -> None:
    def card(count: int) -> str:
        members = ", ".join(f'"pkg{i}==1.0"' for i in range(count))
        return MINIMAL + f"\n[deps]\npins = [{members}]\n"

    assert isinstance(load(card(MAX_CARD_PINS)), DriverCard)
    error = refusal(card(MAX_CARD_PINS + 1))
    assert "[deps] pins" in str(error)
    assert str(MAX_CARD_PINS) in str(error)


def test_max_card_benchmarks_at_the_cap_loads_and_one_over_names_the_key_and_the_cap() -> None:
    def card(count: int) -> str:
        rows = "".join(benchmark_row(f"metric_{i}") for i in range(count))
        return MINIMAL + '\n[quality]\nkit_version = "1.0.0"\n' + rows

    loaded = load(card(MAX_CARD_BENCHMARKS))
    assert isinstance(loaded, DriverCard)
    assert len(loaded.quality.benchmarks) == MAX_CARD_BENCHMARKS
    error = refusal(card(MAX_CARD_BENCHMARKS + 1))
    assert "[[quality.benchmark]]" in str(error)
    assert str(MAX_CARD_BENCHMARKS) in str(error)


def test_max_card_config_properties_at_the_cap_loads_and_one_over_names_key_and_cap() -> None:
    def card(count: int) -> str:
        blocks = "".join(
            f'[config.properties.p{i}]\ntype = "integer"\ndefault = 0\n' for i in range(count)
        )
        return MINIMAL + '\n[config]\ntype = "object"\nadditionalProperties = false\n' + blocks

    assert isinstance(load(card(MAX_CARD_CONFIG_PROPERTIES)), DriverCard)
    error = refusal(card(MAX_CARD_CONFIG_PROPERTIES + 1))
    assert "[config] properties" in str(error)
    assert str(MAX_CARD_CONFIG_PROPERTIES) in str(error)


# --------------------------------------------------------------------------------------------
# 3. The tombstone branch
# --------------------------------------------------------------------------------------------

TOMBSTONE = """card_schema = 1

[driver]
id = "parse.page.surya"
port = "parse/1"
title = "surya"

[tombstone]
reason = "MODEL_LICENSE Attachment A clause 2(c) is a competitor bar with no revenue threshold."
replaced_by = "parse.page.olmocr"
review_by = "2027-06-01"

[licence.weights]
licence_sha256 = "sha256:e1f69b64dee2f1641a9b1ab12adf24d6e1f69b64dee2f1641a9b1ab12adf24d6"
weights_revision = "n/a"
"""


def test_a_tombstone_loads_although_it_has_none_of_the_four_required_driver_fields() -> None:
    """The branch-first property, stated as the thing that would otherwise break.

    A tombstone has no `entrypoint`, no `schema_version`, no `granularity` and no
    `replay_class` — all non-optional on `DriverCard` — so a loader that validated it as a
    driver card would produce a guaranteed spurious `CARD_INVALID` (sections 2.1 and 7.5).
    """
    for absent in ("entrypoint", "schema_version", "granularity", "replay_class"):
        assert absent not in TOMBSTONE
    stone = load(TOMBSTONE, origin="tombstone", source="tombstones/surya.toml")
    assert isinstance(stone, Tombstone)
    assert stone.id == "parse.page.surya"
    assert stone.port is Port.PARSE
    assert stone.replaced_by == "parse.page.olmocr"
    assert stone.review_by == "2027-06-01"
    assert stone.reason.startswith("MODEL_LICENSE")
    assert stone.licence_weights is not None
    assert stone.licence_weights.licence_sha256.startswith("sha256:")
    assert stone.licence_code is None


def test_the_same_bytes_without_the_tombstone_table_are_refused_as_a_driver_card() -> None:
    """The branch is what makes the difference, not the rest of the file."""
    without = TOMBSTONE.replace("[tombstone]", "[deprecation]")
    assert isinstance(refusal(without), DriverHostError)


def test_only_id_port_and_title_are_legal_in_a_tombstones_driver_table() -> None:
    error = refusal(
        TOMBSTONE.replace('title = "surya"', 'title = "surya"\nversion = "*"'),
        origin="tombstone",
    )
    assert "version" in str(error)
    assert "[driver]" in str(error)


def test_a_tombstone_with_an_empty_reason_is_refused() -> None:
    """DR22: a removed driver resolves to a QUOTED REASON, never to 'unknown driver'."""
    blanked = TOMBSTONE.replace(
        'reason = "MODEL_LICENSE Attachment A clause 2(c) is a competitor bar with no revenue '
        'threshold."',
        'reason = ""',
    )
    assert 'reason = ""' in blanked
    error = refusal(blanked, origin="tombstone")
    assert "reason" in str(error)


def test_a_tombstone_review_by_must_be_a_date() -> None:
    error = refusal(TOMBSTONE.replace('"2027-06-01"', '"soon"'), origin="tombstone")
    assert "review_by" in str(error)


# --------------------------------------------------------------------------------------------
# 4. The digests
# --------------------------------------------------------------------------------------------


def test_a_comment_only_edit_moves_card_sha256_and_not_attestation() -> None:
    """The deliberate consequence of section 2.8, and the reason both digests exist.

    `ow drivers verify` fails on the first (the installed bytes are not the locked bytes) while
    `card.attested` stays true (the contract did not change).
    """
    edited = MINIMAL + "\n# a comment that changes no fact about this driver\n"
    assert card_sha256(MINIMAL.encode()) != card_sha256(edited.encode())
    assert attestation_of(tomllib.loads(MINIMAL)) == attestation_of(tomllib.loads(edited))


def test_attestation_is_over_the_card_with_its_own_key_deleted() -> None:
    body = tomllib.loads(MINIMAL)
    digest = attestation_of(body)
    signed = MINIMAL.replace("card_schema = 1", f'card_schema = 1\nattestation = "{digest}"')
    card = load(signed)
    assert isinstance(card, DriverCard)
    assert card.attestation == digest
    assert card.attested is True, "a recomputation that reads the card minus its own key"
    assert digest == "sha256:" + sha256_canonical(body)


def test_an_attestation_written_after_a_table_header_is_refused_by_position() -> None:
    """TOML scopes a bare key to the most recent header, so an `attestation` line after
    `[quality.suites]` parses as `quality.suites.attestation` and the recomputation reads
    nothing. The position is asserted, not the parse (section 2.1)."""
    misplaced = MINIMAL + '\nattestation = "sha256:00"\n'
    error = refusal(misplaced)
    assert "attestation" in str(error)
    assert "top-level" in str(error).lower()
    assert "header" in str(error)


def test_card_sha256_is_over_the_raw_bytes_and_needs_no_canonicaliser() -> None:
    raw = GOLDEN.encode("utf-8")
    assert card_sha256(raw) == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_the_pins_digest_is_over_the_sorted_pins_and_is_order_free() -> None:
    assert pins_digest(["b==2", "a==1"]) == pins_digest(["a==1", "b==2"])
    assert pins_digest([]) != pins_digest(["a==1"])
    assert pins_digest(["a==1"]) == sha256_canonical(["a==1"])


# --------------------------------------------------------------------------------------------
# 5. The closed/open asymmetry, and its one exception
# --------------------------------------------------------------------------------------------


def test_an_unknown_key_in_capability_parse_is_ignored_with_a_recorded_degradation() -> None:
    card = load(MINIMAL + '\n[capability.parse]\nspatial = "page_bbox"\nglyph_bbox = "yes"\n')
    assert isinstance(card, DriverCard)
    assert card.parse is not None
    assert card.parse.spatial == "page_bbox", "the recognised floors still land"
    kinds = [note.kind for note in card.degradations]
    assert kinds == [CARD_CAPABILITY_UNKNOWN]
    assert card.degradations[0].key == "glyph_bbox"
    assert card.degradations[0].table == "[capability.parse]"


def test_an_unknown_key_in_a_port_sibling_is_a_hard_error() -> None:
    embed = MINIMAL.replace("parse.notebook.ipynb", "embed.bge.m3").replace(
        'port = "parse/1"', 'port = "embed/1"'
    )
    error = refusal(embed + "\n[embed]\ndim = 1024\nquantisation = 4\n")
    assert "[embed]" in str(error)
    assert "quantisation" in str(error)


def test_an_unknown_top_level_table_or_key_is_a_hard_error() -> None:
    """A card is a contract, not config: the closed half of the asymmetry."""
    unknown_table = MINIMAL + "\n[telemetry]\nx = 1\n"
    unknown_key = MINIMAL.replace("card_schema = 1", "card_schema = 1\nvendor = 1")
    for text, name in ((unknown_table, "telemetry"), (unknown_key, "vendor")):
        error = refusal(text)
        assert name in str(error)
        assert "top level" in str(error)


def test_an_unknown_member_of_forfeits_is_kept_where_every_other_set_drops_one() -> None:
    """The ONE exception, and it runs the other way for a stated reason.

    `forfeits` is the only inverted comparison on the card, so an ignored unknown member would
    make the driver look MORE capable. It is therefore kept — `resolve()` fails the match with
    detail `forfeits_unknown_member` — while an unknown member of a `⊇` floor like `math` is
    dropped, which can only shrink the floor (section 2.2).
    """
    card = load(
        MINIMAL
        + '\n[capability.parse]\nforfeits = ["spatial", "telepathy"]\n'
        + 'math = ["latex", "asciimath"]\n'
    )
    assert isinstance(card, DriverCard)
    assert card.parse is not None
    assert card.parse.forfeits == frozenset({"spatial", "telepathy"})
    assert card.parse.math == frozenset({"latex"}), "an unknown floor member is dropped"
    recorded = {(note.key, note.kind) for note in card.degradations}
    assert recorded == {("forfeits", CARD_CAPABILITY_UNKNOWN), ("math", CARD_CAPABILITY_UNKNOWN)}
    kept = next(n for n in card.degradations if n.key == "forfeits")
    assert "KEPT" in kept.detail


def test_an_out_of_domain_ladder_value_is_refused_rather_than_ignored() -> None:
    error = refusal(MINIMAL + '\n[capability.parse]\nspatial = "glyph_bbox"\n')
    assert "spatial" in str(error)
    assert "page_bbox" in str(error), "the refusal prints the ladder"


def test_the_fifteen_parse_floors_are_ten_ladders_three_booleans_and_two_sets() -> None:
    assert len(PARSE_LADDERS) + len(PARSE_SETS) + 3 == 15
    assert set(PARSE_SETS) == {"math", "forfeits"}
    assert PARSE_LADDERS["reading_order"] == (
        "raster",
        "learned",
        "model_emitted",
        "char_stream",
        "source",
    )


# --------------------------------------------------------------------------------------------
# 6. Every CARD_INVALID branch names its subject
# --------------------------------------------------------------------------------------------


def test_an_entrypoint_without_exactly_one_colon_is_card_entrypoint_malformed() -> None:
    for bad in ("pkg.driver", "pkg/driver:Cls", "a:b:c"):
        error = refusal(MINIMAL.replace('entrypoint = "pkg.driver:Cls"', f'entrypoint = "{bad}"'))
        assert error.code() == "OW_CARD_ENTRYPOINT_MALFORMED"
        assert bad in str(error)


def test_both_entrypoint_and_exec_or_neither_is_refused() -> None:
    both = MINIMAL.replace(
        'entrypoint = "pkg.driver:Cls"', 'entrypoint = "pkg.driver:Cls"\nexec = ["bin/x"]'
    )
    neither = MINIMAL.replace('entrypoint = "pkg.driver:Cls"\n', "")
    for text in (both, neither):
        error = refusal(text)
        assert "exactly one of entrypoint and exec" in str(error)


def test_exec_is_refused_for_an_entry_point_origin_and_outside_the_card_directory() -> None:
    exec_card = (
        MINIMAL.replace('entrypoint = "pkg.driver:Cls"', 'exec = ["bin/owdwg", "--serve"]')
        + '\n[isolation]\nrequires = "subproc"\n'
    )
    assert "driver_path" in str(refusal(exec_card, origin="entry_point"))
    escape = exec_card.replace('"bin/owdwg"', '"../../bin/owdwg"')
    error = refusal(escape, origin="driver_path", source="drivers/dwg/driver.toml")
    assert "outside the card's own directory" in str(error)
    metachar = exec_card.replace('"--serve"', '"--serve; rm -rf /"')
    assert "shell metacharacters" in str(refusal(metachar, origin="project"))


def test_an_exec_driver_must_request_subproc_isolation() -> None:
    exec_card = (
        MINIMAL.replace('entrypoint = "pkg.driver:Cls"', 'exec = ["bin/owdwg"]')
        + '\n[isolation]\nrequires = "inproc"\n'
    )
    error = refusal(exec_card, origin="driver_path", source="drivers/dwg/driver.toml")
    assert "subproc" in str(error)
    good = exec_card.replace('requires = "inproc"', 'requires = "subproc"')
    assert isinstance(
        load(good, origin="driver_path", source="drivers/dwg/driver.toml"), DriverCard
    )


def test_a_driver_id_outside_the_grammar_or_disagreeing_with_the_port_is_refused() -> None:
    assert "DriverId grammar" in str(refusal(MINIMAL.replace("parse.notebook.ipynb", "Parse.X")))
    crossed = MINIMAL.replace('id = "parse.notebook.ipynb"', 'id = "derive.notebook.ipynb"')
    error = refusal(crossed)
    assert "first segment IS the Port" in str(error)


def test_a_limits_value_above_host_max_is_refused_naming_the_knob_and_the_ceiling() -> None:
    over = MINIMAL + f"\n[limits]\nmax_input_bytes = {MAX_ENTRY_BYTES + 1}\n"
    error = refusal(over)
    assert "max_input_bytes" in str(error)
    assert str(MAX_ENTRY_BYTES) in str(error)
    at_cap = MINIMAL + f"\n[limits]\nmax_input_bytes = {MAX_ENTRY_BYTES}\nmax_parts = 1\n"
    assert isinstance(load(at_cap), DriverCard)
    assert "max_parts" in str(refusal(MINIMAL + f"\n[limits]\nmax_parts = {MAX_ENTRY_COUNT + 1}\n"))


def test_revision_main_is_refused_on_both_card_sites() -> None:
    embed = MINIMAL.replace("parse.notebook.ipynb", "embed.bge.m3").replace(
        'port = "parse/1"', 'port = "embed/1"'
    )
    error = refusal(embed + '\n[embed]\nmodel_revision = "main"\n')
    assert "model_revision" in str(error)
    assert "main" in str(error)
    weights = MINIMAL + '\n[licence.weights]\nspdx = "x"\nweights_revision = "main"\n'
    assert "weights_revision" in str(refusal(weights))


def test_licence_weights_is_omitted_rather_than_emptied() -> None:
    """An empty table is a different statement from an absent one (section 3 note 6)."""
    assert isinstance(load(MINIMAL), DriverCard)
    error = refusal(MINIMAL + "\n[licence.weights]\n")
    assert "[licence.weights]" in str(error)
    assert "empty" in str(error)


def test_an_empty_deprecation_table_is_refused_and_an_absent_one_is_not_scheduled() -> None:
    card = load(MINIMAL)
    assert isinstance(card, DriverCard)
    assert card.deprecation is None
    error = refusal(MINIMAL + "\n[deprecation]\n")
    assert "[deprecation]" in str(error)
    assert "not scheduled" in str(error)


def test_a_deprecation_window_shorter_than_two_minors_is_refused() -> None:
    def card(since: str, removed: str) -> str:
        return (
            MINIMAL
            + f'\n[deprecation]\nsince = "{since}"\nremoved_in = "{removed}"\n'
            + 'replaced_by = "parse.pdf.pdfium2"\nreason = "glyph run grouping changed."\n'
        )

    loaded = load(card("0.4.0", "0.6.0"))
    assert isinstance(loaded, DriverCard)
    assert loaded.deprecation is not None
    assert loaded.deprecation.replaced_by == "parse.pdf.pdfium2"
    assert "MINOR" in str(refusal(card("0.4.0", "0.5.0")))
    assert "not after" in str(refusal(card("0.6.0", "0.4.0")))


def test_a_shape_naming_a_scaling_dimension_with_an_empty_scaling_table_is_refused() -> None:
    def card(shape: str, scaling: str) -> str:
        return (
            MINIMAL
            + f'\n[cost.model]\nclass = "free"\nshape = "{shape}"\nunit = "document"\n{scaling}'
        )

    assert isinstance(load(card("constant", "")), DriverCard)
    error = refusal(card("linear_per_byte", ""))
    assert "scaling" in str(error)
    assert "linear_per_byte" in str(error)
    good = card(
        "linear_per_byte", 'scaling = { key = "input_bytes", exponent = 1.0, reference = 1 }\n'
    )
    assert isinstance(load(good), DriverCard)


def test_a_driver_never_retries_internally() -> None:
    base = MINIMAL + '\n[cost.model]\nclass = "free"\nshape = "constant"\nunit = "document"\n'
    assert "max_retries" in str(refusal(base + "max_retries = 3\n"))
    assert isinstance(load(base + "max_retries = 0\n"), DriverCard)


def test_a_spend_vector_carries_physical_dimensions_only() -> None:
    base = MINIMAL + '\n[cost.model]\nclass = "free"\nshape = "constant"\nunit = "document"\n'
    error = refusal(base + "per_part = { cost_micros = 12 }\n")
    assert "cost_micros" in str(error)
    assert "INV-15" in str(error)


def test_a_benchmark_row_below_min_slice_n_is_refused_at_load() -> None:
    head = MINIMAL + '\n[quality]\nkit_version = "1.0.0"\n'
    assert isinstance(load(head + benchmark_row("f1", MIN_SLICE_N)), DriverCard)
    error = refusal(head + benchmark_row("f1", MIN_SLICE_N - 1))
    assert str(MIN_SLICE_N) in str(error)
    assert "f1" in str(error)


def test_an_unrecognised_witness_is_downgraded_to_self_rather_than_refused() -> None:
    head = MINIMAL + '\n[quality]\nkit_version = "1.0.0"\n'
    card = load(head + benchmark_row("f1").replace('witness = "ci"', 'witness = "trust me"'))
    assert isinstance(card, DriverCard)
    assert card.quality.benchmarks[0].witness == "self"


def test_a_benchmark_row_with_an_incomplete_measured_on_is_refused() -> None:
    head = MINIMAL + '\n[quality]\nkit_version = "1.0.0"\n'
    short = benchmark_row("f1").replace('harness_version = "n/a"\n', "")
    error = refusal(head + short)
    assert "measured_on" in str(error)


def test_an_artifact_kind_outside_the_closed_vocabulary_is_refused_naming_the_member() -> None:
    error = refusal(MINIMAL.replace('produces = ["doc_fragment"]', 'produces = ["hologram"]'))
    assert "hologram" in str(error)
    assert "closed artifact-kind set" in str(error)


def test_diag_is_never_the_sole_member_of_produces() -> None:
    error = refusal(MINIMAL.replace('produces = ["doc_fragment"]', 'produces = ["diag"]'))
    assert "diag" in str(error)
    both = MINIMAL.replace('produces = ["doc_fragment"]', 'produces = ["doc_fragment", "diag"]')
    assert isinstance(load(both), DriverCard)


def test_a_format_token_pair_is_validated_on_both_halves() -> None:
    def card(media_type: str, token: str) -> str:
        return (
            MINIMAL
            + f'\n[capability.parse]\nformat_tokens = [{{ media_type = "{media_type}", '
            + f'token = "{token}" }}]\n'
        )

    assert isinstance(load(card("application/x-ipynb+json", "ipynb")), DriverCard)
    assert "[a-z0-9]" in str(refusal(card("application/x-ipynb+json", "IPYNB")))
    assert "[a-z0-9]" in str(refusal(card("application/x-ipynb+json", "a" * 17)))
    unpaired = refusal(card("application/warc", "warc"))
    assert "application/warc" in str(unpaired)
    assert "[capability] formats" in str(unpaired)


def test_a_card_schema_from_the_future_is_its_own_code_and_its_own_fix() -> None:
    error = refusal(MINIMAL.replace("card_schema = 1", "card_schema = 2"))
    assert error.code() == "OW_CARD_SCHEMA_TOO_NEW"
    assert error.fix == "pip install --upgrade omniweave-core"


def test_a_card_declaring_a_second_ports_tables_is_refused() -> None:
    error = refusal(MINIMAL + '\n[capability.embed]\ninputs = ["text"]\n')
    assert "[capability.embed]" in str(error)
    assert "exactly one Port" in str(error)


def test_a_toml_native_date_is_refused_because_it_cannot_reach_a_digest() -> None:
    error = refusal(MINIMAL + "\n[quality]\nkit_run = 2026-09-02T11:04:18Z\n")
    assert "kit_run" in str(error)
    assert "digest" in str(error)


# --------------------------------------------------------------------------------------------
# 7. The closed JSON-Schema subset
# --------------------------------------------------------------------------------------------

_EVERY_LEGAL_KEYWORD = """
[config]
type = "object"
additionalProperties = false
required = ["name"]
[config.properties.name]
type = "string"
enum = ["a", "b"]
minLength = 1
maxLength = 16
pattern = "^[ab]$"
[config.properties.count]
type = "integer"
minimum = 0
maximum = 10
default = 3
[config.properties.tags]
type = "array"
minItems = 0
maxItems = 4
items = { type = "string" }
default = []
"""


def test_the_subsets_table_has_eleven_rows_and_fourteen_keyword_spellings() -> None:
    """Three rows pair two keywords: minimum/maximum, minLength/maxLength, minItems/maxItems."""
    paired = {"maximum", "maxLength", "maxItems"}
    assert len(CONFIG_KEYWORDS) == 14
    assert len(set(CONFIG_KEYWORDS) - paired) == 11


def test_every_legal_keyword_is_accepted() -> None:
    card = load(MINIMAL + _EVERY_LEGAL_KEYWORD)
    assert isinstance(card, DriverCard)
    assert set(card.config.properties) == {"name", "count", "tags"}
    assert card.config.required == frozenset({"name"})
    used = set().union(*(set(schema) for schema in card.config.properties.values()))
    assert used | {"additionalProperties", "properties", "required"} == set(CONFIG_KEYWORDS)


@pytest.mark.parametrize("keyword", CONFIG_REJECTED_KEYWORDS)
def test_each_rejected_keyword_is_refused_by_name(keyword: str) -> None:
    """`CARD_INVALID` NAMING THE KEYWORD — the author has to know which of the ten they used."""
    value = '"x"' if keyword != "not" else '{ type = "string" }'
    written = keyword if keyword.isidentifier() else f'"{keyword}"'
    card = (
        MINIMAL
        + '\n[config]\ntype = "object"\nadditionalProperties = false\nrequired = []\n'
        + f'[config.properties.a]\ntype = "string"\ndefault = "x"\n{written} = {value}\n'
    )
    error = refusal(card)
    assert keyword in str(error)
    assert "outside the closed subset" in str(error)


def test_nesting_below_depth_three_is_refused_naming_the_keyword() -> None:
    card = (
        MINIMAL
        + '\n[config]\ntype = "object"\nadditionalProperties = false\nrequired = []\n'
        + '[config.properties.a]\ntype = "object"\ndefault = {}\n'
        + '[config.properties.a.properties.b]\ntype = "string"\n'
    )
    error = refusal(card)
    assert "properties" in str(error)
    assert "outside the closed subset" in str(error)


def test_additional_properties_must_be_present_and_false() -> None:
    for tail in (
        'type = "object"\nrequired = []\n',
        'type = "object"\nadditionalProperties = true\n',
    ):
        error = refusal(MINIMAL + "\n[config]\n" + tail)
        assert "additionalProperties" in str(error)


def test_an_optional_property_without_a_default_is_refused() -> None:
    card = (
        MINIMAL
        + '\n[config]\ntype = "object"\nadditionalProperties = false\nrequired = []\n'
        + '[config.properties.a]\ntype = "string"\n'
    )
    error = refusal(card)
    assert "default" in str(error)
    assert "config_digest" in str(error)


def test_a_keyword_on_the_wrong_type_is_refused() -> None:
    card = (
        MINIMAL
        + '\n[config]\ntype = "object"\nadditionalProperties = false\nrequired = []\n'
        + '[config.properties.a]\ntype = "integer"\ndefault = 1\npattern = "^x$"\n'
    )
    error = refusal(card)
    assert "pattern" in str(error)
    assert "string" in str(error)


def test_a_pattern_is_compiled_at_load() -> None:
    card = (
        MINIMAL
        + '\n[config]\ntype = "object"\nadditionalProperties = false\nrequired = []\n'
        + '[config.properties.a]\ntype = "string"\ndefault = "x"\npattern = "^[unclosed"\n'
    )
    error = refusal(card)
    assert "does not compile" in str(error)


def test_arrays_of_objects_are_not_in_the_subset() -> None:
    card = (
        MINIMAL
        + '\n[config]\ntype = "object"\nadditionalProperties = false\nrequired = []\n'
        + '[config.properties.a]\ntype = "array"\ndefault = []\nitems = { type = "object" }\n'
    )
    assert "arrays of objects" in str(refusal(card))


def test_defaults_are_filled_and_the_digest_is_order_free() -> None:
    """Two callers passing the same values in a different order must share a worker."""
    card = load(MINIMAL + _EVERY_LEGAL_KEYWORD)
    assert isinstance(card, DriverCard)
    schema = card.config
    filled = schema.effective({"name": "a"})
    assert filled == {"name": "a", "count": 3, "tags": []}
    one = schema.config_digest({"name": "a", "count": 7, "tags": ["x"]})
    other = schema.config_digest({"tags": ["x"], "name": "a", "count": 7})
    assert one == other
    assert one != schema.config_digest({"name": "b", "count": 7, "tags": ["x"]})
    assert len(one) == 64


def test_effective_refuses_an_undeclared_key_a_missing_required_one_and_a_bad_value() -> None:
    card = load(MINIMAL + _EVERY_LEGAL_KEYWORD)
    assert isinstance(card, DriverCard)
    schema = card.config
    with pytest.raises(ConfigError) as unknown:
        schema.effective({"name": "a", "nonsense": 1})
    assert "nonsense" in str(unknown.value)
    with pytest.raises(ConfigError) as missing:
        schema.effective({})
    assert "name" in str(missing.value)
    with pytest.raises(ConfigError) as domain:
        schema.effective({"name": "z"})
    assert "enum" in str(domain.value)
    with pytest.raises(ConfigError) as typed:
        schema.effective({"name": 4})
    assert "string" in str(typed.value)


# --------------------------------------------------------------------------------------------
# 8. MeasuredOn (DR14) and served_tokens
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("dropped", MEASURED_ON_FIELDS)
def test_measured_on_with_nine_of_ten_fields_raises_type_error(dropped: str) -> None:
    """Frozen with NO defaults, so a card supplying nine raises rather than writing a blank cell.

    13-quality.md P-22 is the property; the receipt is HunyuanOCR's published 94.10 measured on
    TensorRT against a repo shipping Transformers and vLLM.
    """
    nine = {name: "n/a" for name in MEASURED_ON_FIELDS if name != dropped}
    assert len(nine) == 9
    with pytest.raises(TypeError):
        MeasuredOn(**nine)


def test_measured_on_with_all_ten_constructs_and_rejects_a_main_revision() -> None:
    assert MeasuredOn(**MEASURED_ON).weights_revision == "n/a"
    with pytest.raises(ValueError, match="weights_revision"):
        MeasuredOn(**{**MEASURED_ON, "weights_revision": "main"})
    with pytest.raises(ValueError, match="weights"):
        MeasuredOn(**{**MEASURED_ON, "weights": ""})


def test_measured_on_has_no_row_level_corpus_digest_twin() -> None:
    """Two fields that must agree are one field plus a bug (section 2.6)."""
    assert "corpus_digest" in MEASURED_ON_FIELDS
    head = MINIMAL + '\n[quality]\nkit_version = "1.0.0"\n'
    assert isinstance(load(head + benchmark_row("f1")), DriverCard)
    twinned = benchmark_row("f1").replace(
        'witness = "ci"\n', 'witness = "ci"\ncorpus_digest = "sha256:00"\n'
    )
    error = refusal(head + twinned)
    assert "corpus_digest" in str(error)
    assert "[[quality.benchmark]]" in str(error)


def test_served_tokens_is_the_cards_own_pairs_and_the_routers_lookup() -> None:
    """This section's derived set, over ONE card — not routing's computed domain."""
    card = load(GOLDEN)
    assert isinstance(card, DriverCard)
    assert served_tokens(card) == frozenset({"ipynb"})
    table = {"application/x-ipynb+json": "notebook"}
    assert served_tokens(card, table.get) == frozenset({"ipynb", "notebook"})
    assert served_tokens(card, lambda _media_type: None) == frozenset({"ipynb"})


def test_load_card_refuses_an_origin_outside_the_four() -> None:
    error = refusal(MINIMAL, origin="the_internet")
    assert "the_internet" in str(error)
    assert "driver_path" in str(error)


# --------------------------------------------------------------------------------------------
# 9. The register. Every symbol this module raises has an OW-D-nnn row (section 5.3).
# --------------------------------------------------------------------------------------------


def test_every_symbol_the_loader_raises_has_a_codes_toml_row() -> None:
    """A code with no register row is a code `ow explain` cannot resolve for the author."""
    raised = {
        "OW_CARD_INVALID": refusal(MINIMAL + "\n[telemetry]\nx = 1\n"),
        "OW_CARD_ENTRYPOINT_MALFORMED": refusal(
            MINIMAL.replace('entrypoint = "pkg.driver:Cls"', 'entrypoint = "pkg.driver"')
        ),
        "OW_CARD_SCHEMA_TOO_NEW": refusal(MINIMAL.replace("card_schema = 1", "card_schema = 99")),
    }
    for symbol, error in raised.items():
        assert error.code() == symbol
        row = explain(symbol)
        assert row.numeric.startswith("OW-D-"), f"{symbol} is a driver-host area code"
        assert row.meaning, f"{symbol} has no one-line meaning"
        assert row.fix, f"{symbol} names no command that clears it"
        assert error.numeric() == row.numeric


def test_a_card_fault_is_never_a_resource_limit_even_at_a_cap() -> None:
    """A card is a contract and a malformed one is refused, not clamped (section 4.5)."""
    members = ", ".join(['"p"'] * (MAX_CARD_PINS + 1))
    error = refusal(MINIMAL + "\n[deps]\npins = [" + members + "]\n")
    assert not isinstance(error, ResourceLimit)
    assert error.code() == "OW_CARD_INVALID"
    assert error.fix.startswith("ow drivers check")
