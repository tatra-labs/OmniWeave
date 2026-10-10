"""The prompt pack (D708): four lanes, each a prompt generated from the corpus and a schema."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from omniweave_llm.prompt import (
    EXTRACTION_LANES,
    LANES,
    decodable,
    prompt_fp,
    render,
    role,
    schema,
)
from omniweave_llm.wrap import OPENING

ETYPES = ["defined_term", "person", "org"]
RELATIONS = [
    ("cites", "source is the CITING entity; target the CITED."),
    ("party_to", "source is the PARTY; target the agreement it is party to."),
]
BODY = '{"t":"block","cite":"d7#412","text":"Acme Holdings Ltd pays on each Business Day."}'


def _head(lane: str, **kw: Any) -> str:
    """Parts 1-4: everything before the wrapped body."""
    text = render(lane, body=BODY, source="seg:9f2c1d4a77b03e51", **kw).text
    return text[: text.index(f"<{OPENING}")].rstrip()


def test_prompt_fp_is_parts_one_to_four_and_nothing_else() -> None:
    """Ruling 1: the body moves nothing; the vocabulary, the relations and the lane move it."""
    base = render("entity", body=BODY, source="seg:a", etypes=ETYPES, relations=RELATIONS)
    other_body = render("entity", body="{}", source="seg:b", etypes=ETYPES, relations=RELATIONS)
    assert base.fp == other_body.fp
    assert base.fp == prompt_fp(_head("entity", etypes=ETYPES, relations=RELATIONS))
    moved = [
        render(
            "entity", body=BODY, source="seg:a", etypes=[*ETYPES, "covenant"], relations=RELATIONS
        ),
        render("entity", body=BODY, source="seg:a", etypes=ETYPES, relations=RELATIONS[:1]),
        render("claim", body=BODY, source="seg:a", etypes=ETYPES, relations=RELATIONS),
    ]
    assert len({base.fp, *(p.fp for p in moved)}) == 4
    assert re.fullmatch(r"[0-9a-f]{12}", base.fp)


def test_prompt_fp_folds_crlf_and_trailing_whitespace() -> None:
    """06:1356: without it every Windows checkout re-bills the corpus."""
    assert prompt_fp("role \r\n\r\ntable\t\r\n\n\n") == prompt_fp("role\n\ntable")
    assert prompt_fp("role\rtable") == prompt_fp("role\ntable"), "a lone CR is a line break too"
    assert prompt_fp("role\n\ntable") != prompt_fp("role\ntable")


def test_the_vocabulary_enters_the_schema_where_it_enters_the_prompt() -> None:
    """Ruling 3: `unknown` once and last, a nullable enum keeps its null, relations by name."""
    entity = schema("entity", etypes=[*ETYPES, "unknown"], relations=["cites", "cites", "party_to"])
    etype = entity["properties"]["entities"]["items"]["properties"]["etype"]
    assert etype["enum"] == [*ETYPES, "unknown", None]
    relation = entity["properties"]["relations"]["items"]["properties"]["relation"]
    assert relation["enum"] == ["cites", "party_to"]
    claim = schema("claim", etypes=ETYPES)
    subject = claim["properties"]["claims"]["items"]["properties"]["subject_etype"]
    assert subject["enum"] == [*ETYPES, "unknown", None]


@pytest.mark.parametrize("lane", LANES)
def test_every_schema_is_closed_bounded_and_marker_free(lane: str) -> None:
    """06:1491-1500: additionalProperties false, required within properties, arrays bounded."""
    filled = schema(lane, etypes=ETYPES, relations=["cites"])
    assert "$ETYPES" not in json.dumps(filled) and "$RELATIONS" not in json.dumps(filled)

    def walk(node: dict[str, Any]) -> None:
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) <= set(node["properties"])
            for child in node["properties"].values():
                walk(child)
        if node.get("type") == "array":
            assert "minItems" in node and "maxItems" in node
            walk(node["items"])

    walk(filled)


def test_the_extraction_lanes_render_the_tables_and_the_decision_lanes_do_not() -> None:
    """Ruling 2."""
    for lane in LANES:
        head = _head(lane, etypes=ETYPES, relations=RELATIONS)
        tables = "Entity types:\n- defined_term" in head and "- cites: source is the CITING" in head
        assert tables == (lane in EXTRACTION_LANES), lane
    bare = _head("entity", etypes=ETYPES)
    assert "Relations: none in this corpus; emit no relationships." in bare


@pytest.mark.parametrize("lane", LANES)
def test_the_contract_names_every_field_the_schema_holds(lane: str) -> None:
    """Ruling 4: one line per top-level field and per item field."""
    head = _head(lane, etypes=ETYPES, relations=RELATIONS)
    filled = schema(lane, etypes=ETYPES, relations=[name for name, _ in RELATIONS])
    for name, field in filled["properties"].items():
        assert f"\n- {name}: " in head
        for sub in field.get("items", {}).get("properties", {}):
            assert f"\n    - {sub}: " in head


@pytest.mark.parametrize("lane", LANES)
def test_parts_one_to_four_carry_no_geometry_and_no_identifier(lane: str) -> None:
    """Ruling 5, GR11: no address, no cite, no path; every number is one of the schema's bounds."""
    head = _head(lane, etypes=ETYPES, relations=RELATIONS)
    assert not re.search(r"p\d+/\d+", head)
    assert not re.search(r"\bd\d+#\d+", head)
    assert not re.search(r"\w/\w+/\w", head)
    bound = r'"(?:maxItems|minItems|maxLength|minLength|minimum|maximum)": (\d+)'
    bounds = set(re.findall(bound, json.dumps(schema(lane))))
    assert set(re.findall(r"\d+", role(lane))) == set(), "the authored text names no number"
    assert set(re.findall(r"\d+", head)) <= bounds


def test_the_extraction_roles_carry_06s_three_rules() -> None:
    """06:1363-1374: the direction discipline, the covered-block rule, and the uncertainty rule."""
    for lane in EXTRACTION_LANES:
        text = role(lane)
        assert 'A block marked "covered": true has already been read by another extractor.' in text
        assert "Do NOT emit any item whose `cite` is a covered block." in text
        assert "it is NEVER expressed by a number." in text
    assert "Never reverse a direction to make a sentence read better." in role("entity")


def test_an_unknown_lane_is_refused() -> None:
    with pytest.raises(ValueError, match="entity, claim, merge, report"):
        render("summary", body="", source="x")


def _keys(node: Any) -> list[str]:
    if isinstance(node, dict):
        return [key for key, value in node.items() for key in (key, *_keys(value))]
    if isinstance(node, list):
        return [key for value in node for key in _keys(value)]
    return []


@pytest.mark.parametrize("lane", LANES)
def test_the_decoder_never_sees_a_pattern_and_the_contract_keeps_every_one(lane: str) -> None:
    """Ruling 6 (D717): Ollama's schema-to-grammar crashes on a `pattern`."""
    full = schema(lane, etypes=ETYPES, relations=[name for name, _ in RELATIONS])
    before = json.dumps(full, sort_keys=True)
    decoded = decodable(full)
    assert "pattern" not in _keys(decoded)
    assert json.dumps(full, sort_keys=True) == before, "the contract is not changed"
    assert ("pattern" in _keys(full)) == (lane in EXTRACTION_LANES), "the cite pattern is kept"


def test_a_corpus_with_no_relation_decodes_an_empty_relation_list() -> None:
    """Ruling 6: an enum with no member is dropped and its array can hold nothing."""
    decoded = decodable(schema("entity", etypes=ETYPES, relations=[]))
    relations = decoded["properties"]["relations"]
    assert relations["maxItems"] == 0
    assert "enum" not in relations["items"]["properties"]["relation"]
    assert decoded["properties"]["entities"]["maxItems"] == 40, "only the empty one is closed"
    named = decodable(schema("entity", etypes=ETYPES, relations=["cites"]))
    assert named["properties"]["relations"]["maxItems"] == 40
    assert named["properties"]["relations"]["items"]["properties"]["relation"]["enum"] == ["cites"]
    assert named["properties"]["entities"]["items"]["properties"]["etype"]["enum"] == [
        *ETYPES, "unknown", None
    ]  # fmt: skip
