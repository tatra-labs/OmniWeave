"""The honest card, and the tripwire that fires the day it stops being honest.

`parse.office.anydoc`'s card is a statement about what `firecrawl-anydoc == 0.2.4` **cannot** do,
and a statement like that decays silently: upstream adds a field, the card keeps under-claiming, and
nobody finds out because nothing fails. So the two claims that matter are asserted against the
installed wheel rather than against a docstring.

1. **`origin_span = "none"` is checkable.** The eight `Block` variants carry no source address of
   any kind (03-document-model.md:1564). `vendor/anydoc/FORK-TRIGGER.md` clause 1 names the day
   that changes, and the test below is the clause's own named test: it reads the variant set and
   the field set out of the wheel's type stub and fails when an address field appears.
2. **The twelve formats are the twelve.** `resolve()` filters on `format in capability.formats`
   before anything else, so the list is the input to `format_token_for`, to `ow route lint`
   check 11 and to `V01-17`. The card and `MEDIA_TYPES` are images of each other and neither may
   drift alone.

Specified in 16-roadmap.md W3.4; 04-driver-system.md sections 2.2 and 10.1.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from omniweave_core.drivers.card import PARSE_BOOLS, PARSE_LADDERS, PARSE_SETS, load_card
from omniweave_office.driver import ACHIEVED_CONSTANTS, MEDIA_TYPES, AnydocParser

DIST_ROOT = Path(__file__).resolve().parents[2]
CARD_PATH = DIST_ROOT / "src" / "omniweave_office" / "driver.toml"
REPO = DIST_ROOT.parents[1]
VENDOR = REPO / "vendor" / "anydoc"

FIFTEEN = (*PARSE_LADDERS, *PARSE_BOOLS, *PARSE_SETS)

ADDRESS_WORDS = ("part", "path", "offset", "node", "origin", "span", "addr", "byte")
"""Words a source-address field on `Block` would plausibly be spelled with.

Deliberately generous. This is a tripwire, and a tripwire that only catches the exact spelling
someone guessed in advance is not one. A false positive here costs a reader two minutes and a
revision of this list; a false negative costs the `VERBATIM` tier staying shut after upstream
opened it."""


@pytest.fixture(scope="module")
def card() -> object:
    return load_card(CARD_PATH.read_bytes(), origin="driver_path", source=str(CARD_PATH))


@pytest.fixture(scope="module")
def raw() -> dict[str, object]:
    return tomllib.loads(CARD_PATH.read_text(encoding="utf-8"))


def test_the_card_loads_with_no_degradation(card: object) -> None:
    """A `CardDegradation` is an unknown key inside `[capability.<port>]`, ignored and recorded.

    Zero of them is the claim: every key in this card is one this release's loader knows, so the
    card is not quietly declaring less than its author wrote.
    """
    assert card.identity.id == "parse.office.anydoc"  # type: ignore[attr-defined]
    assert card.identity.port.value == "parse"  # type: ignore[attr-defined]
    assert card.identity.port_major == 1  # type: ignore[attr-defined]
    assert card.degradations == ()  # type: ignore[attr-defined]


def test_origin_span_is_none_and_the_reason_is_checkable() -> None:
    """FORK-TRIGGER clause 1's named test. It fails the day anydoc emits a source address.

    The vendored `src/model/block.rs` is the warrant a reviewer reads; the installed wheel's
    `_anydoc.pyi` is what the driver actually calls, and they are checked together -- a vendored
    tree that drifted from the shipped binary would otherwise let this pass on the copy nobody
    runs.

    On the day this fails, the response is written and costed: `driver.toml`'s `origin_span`
    becomes `"exact"`, `os.k` becomes `"nodepath"`, and the `VERBATIM` tier opens on the office
    path. It is not a fork.
    """
    from anydoc import _anydoc  # noqa: PLC0415 -- the installed wheel, read for its shape.

    stub = Path(_anydoc.__file__).with_suffix(".pyi")
    text = stub.read_text(encoding="utf-8")
    block = text.split("class Block:", 1)[1].split("@final", 1)[0]
    fields = re.findall(r"^\s{4}(\w+):", block, re.MULTILINE)
    offenders = [
        name
        for name in fields
        if name not in {"kind", "content", "blocks", "text"}
        and any(word in name.lower() for word in ADDRESS_WORDS)
    ]
    assert not offenders, (
        f"anydoc's Block now carries {offenders}, which may be the source address "
        f"vendor/anydoc/FORK-TRIGGER.md clause 1 names. If it is: origin_span becomes 'exact', "
        f"os.k becomes 'nodepath', and the VERBATIM tier opens on the office path."
    )

    variants = re.search(r"kind:\s*Literal\[([^\]]+)\]", block)
    assert variants is not None
    assert len(re.findall(r'"', variants.group(1))) // 2 == 8, (
        "anydoc's Block variant count changed; 03-document-model.md:1564 records eight and "
        "blocks.BLOCK_KINDS maps exactly those"
    )


def test_the_vendored_source_agrees_with_the_wheel_about_the_variants() -> None:
    """`src/model/block.rs` is the reviewable half of the same claim."""
    source = (VENDOR / "src" / "model" / "block.rs").read_text(encoding="utf-8")
    body = source.split("pub enum Block", 1)[1]
    depth, end = 0, 0
    for index, character in enumerate(body):
        depth += character == "{"
        depth -= character == "}"
        if depth == 0 and index:
            end = index
            break
    variants = re.findall(r"^\s{4}([A-Z]\w+)", body[:end], re.MULTILINE)
    assert len(variants) == 8, f"expected eight Block variants, found {variants}"
    assert "Address" not in " ".join(variants)


def test_the_declared_formats_are_exactly_the_drivers_media_types(
    raw: dict[str, object],
) -> None:
    """The card's list and the driver's table are images of each other, and there are twelve.

    `application/pdf` is excluded from both although anydoc decodes it: `parse.pdf.pdfium` owns
    that path (04:2564) and `to_document()` refuses it from anydoc's side, so the exclusion is
    enforced at both ends.
    """
    capability = raw["capability"]
    assert isinstance(capability, dict)
    declared = list(capability["formats"])  # type: ignore[index]
    assert len(declared) == 12
    assert declared == list(MEDIA_TYPES)
    assert "application/pdf" not in declared


def test_every_format_token_pair_matches_the_drivers_table(raw: dict[str, object]) -> None:
    """`format_tokens` is pair-shaped, and the pairing is the declaration (04 section 2.2)."""
    parse = raw["capability"]["parse"]  # type: ignore[index]
    pairs = {row["media_type"]: row["token"] for row in parse["format_tokens"]}  # type: ignore[index]
    assert pairs == {media: token for media, (_name, token) in MEDIA_TYPES.items()}
    assert pairs["application/vnd.ms-excel"] == "xls", (
        "the legacy workbook's omniweave token is `xls` even though anydoc's own name for it is "
        "`xlsx`, a parser family covering three container generations"
    )


def test_achieved_constants_are_a_subset_of_the_fifteen_and_never_exceed_the_card(
    card: object,
) -> None:
    """The eight constant keys of `achieved` do not over-claim against the declaration.

    P15 is asserted per fixture by the conform `capability` suite; this is the same property over
    the constants alone, where it can be checked without running a document -- and it is the half
    that would go wrong silently, because a constant is edited once and then trusted forever.
    """
    parse = card.parse  # type: ignore[attr-defined]
    assert set(ACHIEVED_CONSTANTS) <= set(FIFTEEN)
    for key, claimed in ACHIEVED_CONSTANTS.items():
        declared = getattr(parse, key)
        if key in PARSE_LADDERS:
            ladder = PARSE_LADDERS[key]
            assert ladder.index(str(claimed)) <= ladder.index(str(declared)), key
        elif key in PARSE_BOOLS:
            assert claimed <= declared, key
        else:
            assert set(claimed) <= set(declared), key  # type: ignore[arg-type]


def test_the_card_is_not_signed_by_its_author(raw: dict[str, object]) -> None:
    """DR13: `[cost.measured]`, `[quality]` and the attestation are the KIT's regions.

    A card carrying them before a run has made a claim no run backed, and the publish gate rejects
    author values in those blocks. Asserting their absence here is cheaper than discovering it at
    publish time.
    """
    assert "quality" not in raw
    assert "attestation" not in raw
    assert "measured" not in raw.get("cost", {})  # type: ignore[union-attr]


def test_the_entrypoint_resolves_to_the_class_the_card_names(raw: dict[str, object]) -> None:
    """`module:attr`, exactly one colon, and the attr is this driver."""
    entrypoint = raw["driver"]["entrypoint"]  # type: ignore[index]
    module, _, attribute = str(entrypoint).partition(":")
    assert module == "omniweave_office.driver"
    assert attribute == AnydocParser.__name__
    assert raw["driver"]["port"] == AnydocParser.PORT  # type: ignore[index]
    assert raw["driver"]["schema_version"] == AnydocParser.SCHEMA_VERSION  # type: ignore[index]
