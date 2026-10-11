"""`omniweave_core.out.brief`: the locked spec and every way `parse_brief()` refuses one.

09-generation.md section 13.2 (the grammar, the three tiers of prohibition, the `(user)` tag) and
section 4.1 (the optional `## template`). The fixture is 09's own example, less the plan's inline
`#` annotations (ruling 2), with its baseline row spelt as `baseline_rows()` generates it
(ruling 5).
"""

from __future__ import annotations

import json
import tomllib

import pytest
from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import TargetError, explain
from omniweave_core.out.brief import (
    BRIEF_SCHEMA,
    Brief,
    Prohibition,
    baseline_rows,
    parse_brief,
)
from omniweave_core.out.constructs import ConstructTable

SCRIPT = "elem.script: executable content in an authored artefact"

BRIEF = f"""{BRIEF_SCHEMA}
# Brief

## canvas
- format: 16:9
- unit: slide
## communication
- primary_language: en-GB
- audience: the board, non-technical
- objective: approve the FY26 budget envelope
- core_message: the envelope holds if hiring slips one quarter
## direction
- vibe: confident editorial
- cue: large display serif, tight grid, one bold accent
## density
- per_unit: light
## motion
- level: subtle
## typography
- title_family: Source Serif
- body_family: Inter
- body: 20
- title: 44
## rhythm
- u01: {{ anchor: cover,   dense: false, breathing: wide }}
- u02: {{ anchor: content, dense: false, breathing: normal }}
## forbidden
- {SCRIPT}
- no shadows and no glow anywhere (user)
"""

TABLE = """\
schema = "omniweave.out-constructs/1"
carrier = "html"
il = "owtext/1"
version = 1
unknown_construct = "forbidden"

[[construct]]
id = "attr.ow-cite"
selector = "@data-ow-cite"
disposition = "native"
round_trip = "exact"
canonical = "cite tokens"
maps_to = "lower.cites:sidecar"
code = "OW_TARGET_CITE_MALFORMED"
since = "0.1.0"

[[construct]]
id = "attr.ow-el"
selector = "@data-ow-el"
disposition = "native"
round_trip = "exact"
canonical = "u<NN>e<NN>"
maps_to = "lower.ids:passthrough"
code = "OW_TARGET_EL_DUPLICATE"
since = "0.1.0"

[[construct]]
id = "elem.ow-manual"
selector = "html|div[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
since = "0.1.0"

[[construct]]
id = "elem.script"
selector = "html|script"
disposition = "forbidden"
round_trip = "dropped"
code = "OW_TARGET_SCRIPT_FORBIDDEN"
msg = "executable content in an authored artefact"
since = "0.1.0"
"""


def _parse(text: str = BRIEF) -> object:
    return parse_brief(text, baseline=(SCRIPT,))


def _refused(text: str, match: str) -> TargetError:
    with pytest.raises(TargetError, match=match) as caught:
        _parse(text)
    assert caught.value.code() == "OW_TARGET_BRIEF_INVALID"
    return caught.value


def test_the_example_brief_parses() -> None:
    brief = parse_brief(BRIEF, baseline=(SCRIPT,))
    assert brief.value("canvas", "format") == "16:9"
    assert (
        brief.value("communication", "core_message")
        == "the envelope holds if hiring slips one quarter"
    )
    assert brief.value("typography", "title") == "44"
    assert brief.value("canvas", "absent") is None
    assert brief.forbidden == (
        Prohibition(SCRIPT, "baseline"),
        Prohibition("no shadows and no glow anywhere", "user"),
    )
    assert brief.template is None
    assert brief.rhythm()["u02"] == {"anchor": "content", "dense": "false", "breathing": "normal"}
    assert (brief.anchor("u01"), brief.anchor("u09")) == ("cover", "")
    assert "forbidden" not in brief.sections


def test_the_baseline_is_generated_from_the_tables_forbidden_rows() -> None:
    table = ConstructTable.parse(tomllib.loads(TABLE), {}, source="constructs.toml")
    assert baseline_rows(table) == (SCRIPT,)


def test_an_untagged_row_not_in_the_baseline_is_refused() -> None:
    error = _refused(
        BRIEF.replace("- no shadows and no glow anywhere (user)", "- no shadows anywhere"),
        "baseline",
    )
    assert "brief.md:29:" in str(error)


def test_a_user_row_is_verbatim_and_never_widened() -> None:
    text = BRIEF.replace("anywhere (user)", "anywhere, ever!  (user)")
    brief = parse_brief(text, baseline=(SCRIPT,))
    assert brief.forbidden[1] == Prohibition("no shadows and no glow anywhere, ever! ", "user")


def test_the_digest_ignores_layout_and_moves_with_a_value() -> None:
    first = parse_brief(BRIEF, baseline=(SCRIPT,)).digest()
    spaced = BRIEF.replace("## motion\n", "\n## motion\n").replace("\n", "\r\n")
    assert parse_brief(spaced, baseline=(SCRIPT,)).digest() == first
    assert parse_brief(BRIEF.replace("body: 20", "body: 21"), baseline=(SCRIPT,)).digest() != first
    assert parse_brief(BRIEF.replace("glow anywhere", "glow"), baseline=(SCRIPT,)).digest() != first
    assert first.startswith("sha256:")


def test_the_template_section_is_optional_and_asserted() -> None:
    slot = "asset-slot:" + "9f" * 32
    brief = parse_brief(
        BRIEF + f"## template\n- ref: {slot}\n- units: u01, u02\n", baseline=(SCRIPT,)
    )
    assert brief.template is not None
    assert (brief.template.ref, brief.template.units) == (slot, ("u01", "u02"))
    every = parse_brief(BRIEF + f"## template\n- ref: {slot}\n", baseline=(SCRIPT,))
    assert every.template is not None and every.template.units is None
    assert every.digest() != brief.digest()
    _refused(BRIEF + "## template\n- ref: asset-slot:9f3a\n", "asset-slot")
    _refused(BRIEF + f"## template\n- ref: {slot}\n- units: u1\n", "unit ids")
    _refused(BRIEF + f"## template\n- ref: {slot}\n- owner: x\n", "ref and units")


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda t: t.replace(BRIEF_SCHEMA, "<!-- brief -->"), "line 1"),
        (lambda t: t.replace("## motion\n- level: subtle\n", ""), "missing section"),
        (lambda t: t.replace("## motion", "## motions"), "not a Brief section"),
        (lambda t: t + "## canvas\n", "appears twice"),
        (lambda t: t.replace("- unit: slide", "- unit: slide\n- unit: page"), "unit appears twice"),
        (lambda t: t.replace("- unit: slide", "unit = slide"), "not a `- key: value` row"),
        (lambda t: t.replace("# Brief\n", "- stray: row\n"), "before the first"),
        (lambda t: t.replace("- format: 16:9\n", ""), "needs `- format"),
        (lambda t: t.replace("per_unit: light", "per_unit: airy"), "is one of"),
        (lambda t: t.replace("level: subtle", "level: wild"), "is one of"),
        (lambda t: t.replace("- u02:", "- u2:"), "not a unit id"),
        (lambda t: t.replace(f"- {SCRIPT}", f"* {SCRIPT}"), "is `- <rule>`"),
    ],
)
def test_each_way_a_brief_breaks_the_grammar_is_refused(change: object, match: str) -> None:
    _refused(change(BRIEF), match)  # type: ignore[operator]


@pytest.mark.parametrize(
    ("tag", "ok"),
    [
        ("en-GB", True),
        ("fr", True),
        ("zh-Hans-CN", True),
        ("zh-Hant", True),
        ("es-419", True),
        ("und", False),
        ("zh", False),
        ("zh-CN", False),
        ("en_GB", False),
        ("en-gb", False),
        ("EN", False),
        ("en-GB          # canonical BCP-47", False),
    ],
)
def test_primary_language_is_canonical_bcp47(tag: str, ok: bool) -> None:
    text = BRIEF.replace("primary_language: en-GB", f"primary_language: {tag}")
    if ok:
        assert (
            parse_brief(text, baseline=(SCRIPT,)).value("communication", "primary_language") == tag
        )
    else:
        _refused(text, "primary_language")


def test_the_code_is_registered() -> None:
    row = explain("OW_TARGET_BRIEF_INVALID")
    assert row.numeric == "OW-T-008"
    assert explain("OW-T-008").symbol == "OW_TARGET_BRIEF_INVALID"


def test_the_refusal_fix_runs() -> None:
    error = _refused(BRIEF.replace("level: subtle", "level: wild"), "is one of")
    command, _, argument = error.fix.partition(" explain ")
    assert command == "ow"
    assert explain(argument).symbol == "OW_TARGET_BRIEF_INVALID"


# ---------------------------------------------------------------------------------------------
# Ruling 8 (D775): the record is the digest's preimage, and reads back
# ---------------------------------------------------------------------------------------------

SLOT = "asset-slot:" + "9f" * 32


def _brief(text: str = BRIEF) -> Brief:
    return parse_brief(text, baseline=(SCRIPT,))


@pytest.mark.parametrize(
    "tail",
    ["", f"## template\n- ref: {SLOT}\n- units: u01, u02\n", f"## template\n- ref: {SLOT}\n"],
)
def test_the_record_is_the_digests_preimage_and_reads_back(tail: str) -> None:
    brief = _brief(BRIEF + tail)
    assert brief.digest() == "sha256:" + sha256_canonical(brief.record())
    again = Brief.from_record(json.loads(json.dumps(brief.record())))
    assert again == brief
    assert again.digest() == brief.digest()


def test_the_record_carries_both_forbidden_tiers_in_order() -> None:
    record = _brief().record()
    assert record["forbidden"] == [
        ["baseline", SCRIPT],
        ["user", "no shadows and no glow anywhere"],
    ]
    assert record["template"] is None


def test_an_empty_template_unit_list_reads_back_as_every_unit() -> None:
    record = {**_brief().record(), "template": {"ref": SLOT, "units": []}}
    template = Brief.from_record(record).template
    assert template is not None
    assert template.units is None


def _bad(change: dict[str, object]) -> dict[str, object]:
    return {**_brief().record(), **change}


@pytest.mark.parametrize(
    ("record", "named"),
    [
        ([], "list"),
        (_bad({"title": "x"}), "title"),
        ({"sections": {}, "forbidden": []}, "template"),
        (_bad({"sections": []}), "sections"),
        (_bad({"sections": {"canvas": {"format": 1}}}), "sections"),
        (_bad({"sections": {"canvas": "16:9"}}), "sections"),
        (_bad({"forbidden": [["baseline"]]}), "forbidden"),
        (_bad({"forbidden": [["house", "x"]]}), "forbidden"),
        (_bad({"forbidden": [["user", 1]]}), "forbidden"),
        (_bad({"forbidden": "x"}), "forbidden"),
        (_bad({"template": {"ref": SLOT}}), "brief.template has"),
        (_bad({"template": {"ref": 1, "units": []}}), "brief.template is not"),
        (_bad({"template": {"ref": SLOT, "units": [1]}}), "brief.template is not"),
        (_bad({"template": {"ref": SLOT, "units": "u01"}}), "brief.template is not"),
    ],
)
def test_a_record_that_is_not_a_briefs_is_refused(record: object, named: str) -> None:
    with pytest.raises(ValueError, match=named):
        Brief.from_record(record)
