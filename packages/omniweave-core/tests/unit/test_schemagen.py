"""`tools/schemagen.py` — the inventory is the plan's, and the bytes are LF on every OS.

Three things are asserted here and they are not the same thing:

1. **The inventory is a transcription, not a reading.** Three plan documents enumerate the thirteen
   generated schemas — 02-architecture.md section 2 row 49, 11-repo-layout.md section 1.7 and
   18-api-sketch.md section 8 — and the tests below re-extract all three lists from `_plan/` and
   compare them to `INVENTORY`. A count that lives in a docstring is a claim; a count re-derived
   from the document it cites is a check.

2. **CRLF.** 16-roadmap.md W1.8's estimation basis says outright that "CRLF normalisation is the
   only subtlety and it is the one that bites on Windows". `test_render_never_emits_a_carriage_
   return` and `test_the_writer_never_puts_a_carriage_return_on_disk` are the deliverable that
   warning asks for, and `test_the_generator_never_opens_a_file_in_text_mode` is the structural
   half — semgrep bans a bare `open(..., "w")` under `tools/` (11-repo-layout.md section 1.9 rule
   2) and this asserts the rule from inside the test suite, where it runs on the Windows cells too.

3. **The gate's honesty.** `--check` must pass on a row whose declaring type has not landed and
   fail the instant it does. Every arm of that state machine is exercised against a synthetic
   declaration module rather than against the real tree, because the real tree has thirteen pending
   rows and zero live ones and would test only one arm.

`test_bless_flag_is_off` is docling's `tests/test_data_gen_flag.py` adopted whole, as
13-quality.md section 5.5 requirement 1 specifies.
"""

from __future__ import annotations

import ast
import dataclasses
import enum
import importlib.util
import io
import os
import re
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pytest


def _repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "tools" / "schemagen.py").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = "no omniweave workspace root above this test"
    raise RuntimeError(message)


REPO = _repo_root()
SCHEMAGEN_PATH = REPO / "tools" / "schemagen.py"


def _load() -> Any:
    """Import `tools/schemagen.py` by path. `tools/` is not a package and must not become one.

    11-repo-layout.md section 1.7 lists `tools/` as loose scripts beside the declaration files they
    read; adding an `__init__.py` would make it importable from `src/` and put a build tool inside
    the layer graph G4 checks.
    """
    spec = importlib.util.spec_from_file_location("_omniweave_schemagen", SCHEMAGEN_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: `@dataclass(slots=True)` reads `sys.modules[cls.__module__]`
    # while it rebuilds the class, and a module absent from that table raises there.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


schemagen = _load()


# ---------------------------------------------------------------------------
# Synthetic declarations. Adversarial on purpose: every shape the reflector claims
# to handle plus three it must refuse.
# ---------------------------------------------------------------------------


class Colour(enum.StrEnum):
    RED = "red"
    GREEN = "green"


class Rung(enum.IntEnum):
    LOW = 1
    HIGH = 7


class Mixed(enum.Enum):
    A = "a"
    B = 2


@dataclass(frozen=True, slots=True)
class Leaf:
    """A leaf record.

    A second paragraph that must not reach the schema.
    """

    name: str
    count: int


@dataclass(frozen=True, slots=True)
class Sample:
    """One synthetic wire record."""

    text: str
    flag: bool
    ratio: float
    label: str | None
    colour: Colour
    rung: Rung
    span: tuple[int, int]
    tags: tuple[str, ...]
    counts: dict[str, int]
    leaf: Leaf
    maybe_leaf: Leaf | None
    either: int | str
    mode: Literal["fast", "slow"]
    free: Any
    defaulted: int = 3


@dataclass(frozen=True, slots=True)
class SelfRef:
    """A record that contains itself."""

    child: SelfRef | None


@dataclass(frozen=True, slots=True)
class HasBytes:
    """`bytes` IS reflectable -- as 32 lowercase hex characters. Kept as a positive fixture."""

    payload: bytes


@dataclass(frozen=True, slots=True)
class HasComplex:
    """`complex` has no JSON type and no plausible encoding, so it is the unreflectable case.

    It replaced `bytes` here when `bytes` gained a handler: 03-document-model.md:665 gives the wire
    rendering of a digest ("32 hex chars"), which is a decision the plan had already made, whereas
    a complex number is not mentioned anywhere in the plan and could not be rendered without
    inventing a convention. A test asserting "the reflector refuses what it cannot encode" needs a
    subject the reflector should NEVER learn to encode.
    """

    payload: complex


@dataclass(frozen=True, slots=True)
class HasIntKeys:
    table: dict[int, str]


@dataclass(frozen=True, slots=True)
class HasMixedEnum:
    value: Mixed


@dataclass(frozen=True, slots=True)
class NoDoc:
    name: str


def _entry(module: str, symbol: str | None, *, file: str = "sample-v1.json", root: str = "object"):
    return schemagen.SchemaSource(
        file=file,
        module=module,
        symbol=symbol,
        landed_by="a test",
        locus="a test",
        root=root,
    )


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """A module named `_fake_decls` carrying `Sample`, with `schema/` pointed at `tmp_path`."""
    module = types.ModuleType("_fake_decls")
    module.Sample = Sample
    module.SelfRef = SelfRef
    module.HasBytes = HasBytes
    module.HasComplex = HasComplex
    module.HasIntKeys = HasIntKeys
    module.HasMixedEnum = HasMixedEnum
    module.NoDoc = NoDoc
    module.NOT_A_CLASS = (1, 2, 3)
    monkeypatch.setitem(sys.modules, "_fake_decls", module)
    monkeypatch.setattr(schemagen, "SCHEMA_DIR", tmp_path)
    monkeypatch.setattr(schemagen, "EXPECTED_DIR", tmp_path / "expected")
    (tmp_path / "expected").mkdir()
    return module


def _sample_schema() -> dict[str, Any]:
    return schemagen.build_schema(_entry("_fake_decls", "Sample"), Sample)


# ---------------------------------------------------------------------------
# 1. The inventory is the plan's thirteen
# ---------------------------------------------------------------------------

_NAME = re.compile(r"`?([a-z][a-z-]*-v1)(?:\.json)?`?")

EXPECTED_THIRTEEN: tuple[str, ...] = (
    "document-v1",
    "fragment-v1",
    "job-v1",
    "receipt-v1",
    "event-v1",
    "driver-card-v1",
    "run-manifest-v1",
    "answer-v1",
    "verdict-v1",
    "mcp-tools-v1",
    "open-out-v1",
    "corpora-out-v1",
    "add-out-v1",
)


def test_the_inventory_holds_exactly_thirteen_rows_in_the_planned_order() -> None:
    """W1.8's estimation basis is '13 generated schema files'. Thirteen, and in which order."""
    files = tuple(entry.file for entry in schemagen.INVENTORY)
    assert files == tuple(f"{name}.json" for name in EXPECTED_THIRTEEN)
    assert len(set(files)) == 13


def _names_in(line: str) -> tuple[str, ...]:
    return tuple(match.group(1) for match in _NAME.finditer(line))


def test_the_component_table_enumerates_the_same_thirteen(plan) -> None:
    """02-architecture.md section 2 row 49 is the first of the three enumerations."""
    plan.require()
    hits = plan.grep(r"Generated schemas", documents=["02-architecture.md"])
    assert len(hits) == 1, hits
    found = [name for name in _names_in(hits[0].text) if name in set(EXPECTED_THIRTEEN)]
    assert tuple(found) == EXPECTED_THIRTEEN, hits[0]


def test_the_api_sketch_enumerates_the_same_thirteen(plan) -> None:
    """18-api-sketch.md section 8's `T-GENERATED` row, the third independent enumeration.

    It writes the names bare — `document` `fragment` `job` … — with a trailing "all `-v1`", so the
    comparison is against the stems rather than against the filenames.
    """
    plan.require()
    hits = plan.grep(r"the thirteen `schema/\*\.json`", documents=["18-api-sketch.md"])
    assert len(hits) == 1, hits
    stems = tuple(name.removesuffix("-v1") for name in EXPECTED_THIRTEEN)
    order = [stem for stem in stems if f"`{stem}`" in hits[0].text]
    assert tuple(order) == stems, hits[0]
    positions = [hits[0].text.index(f"`{stem}`") for stem in stems]
    assert positions == sorted(positions), "the plan prints them in a different order"


def test_the_repo_layout_tree_enumerates_the_same_thirteen(plan) -> None:
    """11-repo-layout.md section 1.7's `schema/` tree, the second enumeration, over three lines."""
    plan.require()
    lines = plan.lines("11-repo-layout.md")
    start = next(i for i, line in enumerate(lines) if line.startswith("schema/"))
    block = " ".join(lines[start : start + 4])
    found = [name for name in _names_in(block) if name in set(EXPECTED_THIRTEEN)]
    assert tuple(found) == EXPECTED_THIRTEEN, block


def test_il_digest_is_not_in_the_inventory(plan) -> None:
    """`schema/il-digest-v1.md` is prose and hand-written — the one exception in the directory."""
    plan.require()
    assert all("il-digest" not in entry.file for entry in schemagen.INVENTORY)
    hits = plan.grep(r"il-digest-v1\.md.*hand-written", documents=["18-api-sketch.md"])
    assert hits, "the plan no longer says il-digest-v1.md is the hand-written one"


def test_every_row_names_a_module_a_landing_item_and_a_locus() -> None:
    """A pending row that cites nothing is a promise nobody can check later."""
    for entry in schemagen.INVENTORY:
        assert entry.module.startswith("omniweave"), entry
        assert re.fullmatch(r"P\d+ W\d+\.\d+", entry.landed_by), entry
        assert ".md section" in entry.locus, entry
        assert entry.root in {"object", "array"}, entry


def test_exactly_one_row_declines_to_name_a_symbol() -> None:
    """`open-out-v1.json` is the one file the plan never attributes to a declaring type."""
    unnamed = [entry.file for entry in schemagen.INVENTORY if entry.symbol is None]
    assert unnamed == ["open-out-v1.json"]


# ---------------------------------------------------------------------------
# 2. CRLF — W1.8's stated subtlety
# ---------------------------------------------------------------------------


def test_render_never_emits_a_carriage_return() -> None:
    """The deliverable W1.8's estimation basis asks for.

    A carriage return can reach the output only through a string that already holds one — a
    docstring read off a Windows checkout under `core.autocrlf` — so the input here holds three
    of them, in the three positions JSON would carry them through.
    """
    document = {
        "$schema": schemagen.DIALECT,
        "$id": "schema/crlf-v1.json",
        "description": "one\r\ntwo\rthree",
        "properties": {"a": {"description": "x\r\ny"}},
        "enum": ["p\r\nq"],
    }
    payload = schemagen.render(document)
    assert b"\r" not in payload
    assert payload.endswith(b"\n")
    assert payload.count(b"\n") > 1


def test_render_is_utf8_two_space_indented_and_newline_terminated() -> None:
    payload = schemagen.render(_sample_schema())
    assert payload.endswith(b"\n")
    assert not payload.endswith(b"\n\n")
    lines = payload.decode("utf-8").splitlines()
    assert lines[1].startswith('  "$schema"'), lines[1]
    assert lines[2].startswith('  "$id"'), lines[2]
    assert b"\r" not in payload


def test_render_preserves_declaration_order_and_does_not_sort_keys() -> None:
    """`--check` is a byte diff, so key order is the contract. `$schema` precedes `$id`."""
    text = schemagen.render(_sample_schema()).decode("utf-8")
    assert text.index('"$schema"') < text.index('"$id"')
    order = [name for name in ("text", "flag", "ratio", "label", "colour") if f'"{name}"' in text]
    positions = [text.index(f'"{name}": {{') for name in order]
    assert positions == sorted(positions), "properties were reordered"


def test_render_is_deterministic() -> None:
    assert schemagen.render(_sample_schema()) == schemagen.render(_sample_schema())


def test_the_writer_never_puts_a_carriage_return_on_disk(tmp_path: Path) -> None:
    """The half a `render()` test cannot reach: text-mode translation on Windows.

    `_write` is the only writer in the module. If it ever opened the file in text mode this would
    fail on the Windows cells and pass everywhere else, which is exactly the failure 11-repo-
    layout.md section 1.9 rule 2 exists to prevent.
    """
    target = tmp_path / "nested" / "sample-v1.json"
    payload = schemagen.render(_sample_schema())
    assert schemagen._write(target, payload) is True
    raw = target.read_bytes()
    assert raw == payload
    assert b"\r" not in raw
    assert schemagen._write(target, payload) is False, "an identical write must not touch the file"


def test_check_normalises_crlf_on_the_committed_side(live, tmp_path: Path) -> None:  # noqa: ARG001
    """G6 is 'byte-diff, CRLF-normalised'. A CRLF checkout must not fail a developer's build."""
    entry = _entry("_fake_decls", "Sample")
    payload = schemagen.render(schemagen.build_schema(entry, Sample))
    entry.path.write_bytes(payload.replace(b"\n", b"\r\n"))
    assert b"\r\n" in entry.path.read_bytes()
    assert schemagen._check_one(schemagen.resolve(entry)) is None


def test_the_generator_never_opens_a_file_in_text_mode() -> None:
    """11-repo-layout.md section 1.9 rule 2, asserted structurally rather than by review.

    `ast`, not a regex: a regex sees `open(` in a docstring and misses `Path.open` behind an alias.
    """
    tree = ast.parse(SCHEMAGEN_PATH.read_text(encoding="utf-8"), filename=str(SCHEMAGEN_PATH))
    banned = {"open", "write_text", "read_text", "writelines"}
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in banned:
            found.append(f"{name} at line {node.lineno}")
    assert not found, f"a text-mode file call reaches the emit path: {found}"


def test_gitattributes_pins_the_two_rows_this_generator_depends_on() -> None:
    """Without them G6 fails on the Windows cells (11-repo-layout.md section 1.9's own header)."""
    rows = (REPO / ".gitattributes").read_text(encoding="utf-8").split("\n")
    normalised = {" ".join(row.split()) for row in rows}
    assert "schema/** text eol=lf" in normalised
    assert "schema/expected/** -diff" in normalised


# ---------------------------------------------------------------------------
# 3. The reflector
# ---------------------------------------------------------------------------


def test_the_envelope_carries_the_dialect_and_a_relative_id() -> None:
    schema = _sample_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "schema/sample-v1.json"
    assert schema["title"] == "Sample"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False


def test_every_field_is_required_including_one_with_a_default() -> None:
    """18-api-sketch.md section 3.5 prints all eleven of `AddReport`'s fields as required."""
    schema = _sample_schema()
    assert "defaulted" in schema["required"]
    assert schema["required"] == [field.name for field in dataclasses.fields(Sample)]


def test_the_class_description_is_the_first_paragraph_only() -> None:
    schema = _sample_schema()
    assert schema["description"] == "One synthetic wire record."
    leaf = schema["$defs"]["Leaf"]
    assert leaf["description"] == "A leaf record."
    assert "second paragraph" not in leaf["description"]


def test_a_dataclass_with_no_docstring_carries_no_description() -> None:
    """`inspect.getdoc` would inherit the auto-generated `NoDoc(name: str)` signature and emit it.

    That string carries no information and would churn the committed bytes on any field rename,
    which for a T-GENERATED file means a byte diff in a review that has nothing to review.
    """
    schema = schemagen.build_schema(_entry("_fake_decls", "NoDoc"), NoDoc)
    assert "description" not in schema
    assert NoDoc.__doc__ is not None and NoDoc.__doc__.startswith("NoDoc(")


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("text", {"type": "string"}),
        ("flag", {"type": "boolean"}),
        ("ratio", {"type": "number"}),
        ("defaulted", {"type": "integer"}),
        ("label", {"type": ["string", "null"]}),
        ("colour", {"type": "string", "enum": ["red", "green"]}),
        ("rung", {"type": "integer", "enum": [1, 7]}),
        ("span", {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}),
        ("tags", {"type": "array", "items": {"type": "string"}}),
        ("counts", {"type": "object", "additionalProperties": {"type": "integer"}}),
        ("leaf", {"$ref": "#/$defs/Leaf"}),
        ("maybe_leaf", {"oneOf": [{"$ref": "#/$defs/Leaf"}, {"type": "null"}]}),
        ("either", {"oneOf": [{"type": "integer"}, {"type": "string"}]}),
        ("mode", {"type": "string", "enum": ["fast", "slow"]}),
        ("free", {}),
    ],
)
def test_the_reflector_encodes_each_shape(field: str, expected: dict[str, Any]) -> None:
    assert _sample_schema()["properties"][field] == expected


def test_a_nullable_enum_becomes_a_one_of_and_not_a_widened_type() -> None:
    """A `type` list beside an `enum` would admit `null` against an enum that does not list it."""

    @dataclass(frozen=True, slots=True)
    class NullableEnum:
        colour: Colour | None

    ctx = schemagen._Ctx(defs={}, where="t")
    assert schemagen._schema_for(Colour | None, ctx) == {
        "oneOf": [{"type": "string", "enum": ["red", "green"]}, {"type": "null"}]
    }
    assert NullableEnum is not None


def test_a_self_referential_record_terminates_and_refs_itself() -> None:
    schema = schemagen.build_schema(_entry("_fake_decls", "SelfRef"), SelfRef)
    assert schema["properties"]["child"] == {
        "oneOf": [{"$ref": "#/$defs/SelfRef"}, {"type": "null"}]
    }
    assert schema["$defs"]["SelfRef"]["properties"]["child"] == schema["properties"]["child"]


def test_defs_are_sorted_so_a_field_reorder_does_not_move_them() -> None:
    schema = _sample_schema()
    assert list(schema["$defs"]) == sorted(schema["$defs"])


def test_an_array_rooted_row_puts_the_record_under_items() -> None:
    """`corpora-out-v1.json` is 'the wire form of a tuple of these' (18-api-sketch.md 1.4)."""
    schema = schemagen.build_schema(_entry("_fake_decls", "Leaf", root="array"), Leaf)
    assert schema["type"] == "array"
    assert schema["items"] == {"$ref": "#/$defs/Leaf"}
    assert "properties" not in schema
    assert schema["$defs"]["Leaf"]["required"] == ["name", "count"]


@pytest.mark.parametrize(
    ("declaration", "fragment"),
    [
        (HasComplex, "complex"),
        (HasIntKeys, "must be `str`"),
        (HasMixedEnum, "mixes JSON types"),
    ],
)
def test_an_unreflectable_declaration_raises_naming_the_field(
    declaration: type, fragment: str
) -> None:
    """No fallback encoding. A schema that quietly drops a field is a contract that lies."""
    with pytest.raises(schemagen.UnsupportedDeclarationError) as excinfo:
        schemagen.build_schema(_entry("_fake_decls", declaration.__name__), declaration)
    message = str(excinfo.value)
    assert fragment in message
    assert declaration.__name__ in message or "." in message


def test_a_non_dataclass_declaration_is_refused_naming_the_row() -> None:
    """`mcp-tools-v1.json`'s source is `ACTIONS`, a sequence — the refusal must say so."""
    entry = _entry("_fake_decls", "NOT_A_CLASS", file="mcp-tools-v1.json")
    with pytest.raises(schemagen.UnsupportedDeclarationError) as excinfo:
        schemagen.build_schema(entry, (1, 2, 3))
    assert "mcp-tools-v1.json" in str(excinfo.value)
    assert "not a dataclass" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. The gate's state machine
# ---------------------------------------------------------------------------


def test_a_missing_module_is_pending_not_a_failure() -> None:
    item = schemagen.resolve(_entry("_omniweave_no_such_module", "Nope"))
    assert item.state is schemagen.State.PENDING
    assert "not importable" in item.detail


def test_a_present_module_with_no_symbol_is_pending() -> None:
    """The eight docstring-only subpackage homes exist today; they are not broken declarations."""
    item = schemagen.resolve(_entry("omniweave_core.model", "Doc"))
    assert item.state is schemagen.State.PENDING
    assert "declares no Doc yet" in item.detail


def test_a_row_with_no_declaring_type_is_unresolved_once_its_module_exists(live) -> None:  # noqa: ARG001
    item = schemagen.resolve(_entry("_fake_decls", None))
    assert item.state is schemagen.State.UNRESOLVED
    assert schemagen._check_one(item) is not None
    assert "UNRESOLVED" in schemagen._check_one(item)


def test_a_pending_row_passes_check_while_its_file_is_absent() -> None:
    item = schemagen.resolve(_entry("_omniweave_no_such_module", "Nope"))
    assert schemagen._check_one(item) is None


def test_a_pending_row_with_a_committed_file_fails(live, tmp_path: Path) -> None:  # noqa: ARG001
    entry = _entry("_fake_decls", "Nope")
    entry.path.write_bytes(b'{"hand": "written"}\n')
    message = schemagen._check_one(schemagen.resolve(entry))
    assert message is not None
    assert "hand-written" in message


def test_a_live_row_with_no_file_fails(live) -> None:  # noqa: ARG001
    entry = _entry("_fake_decls", "Sample")
    message = schemagen._check_one(schemagen.resolve(entry))
    assert message is not None
    assert "has landed and the schema is absent" in message


def test_a_live_row_with_a_stale_file_fails_on_a_single_byte(live) -> None:  # noqa: ARG001
    """A byte diff, not a semantic comparison: reordered keys parse equal and must still fail."""
    entry = _entry("_fake_decls", "Sample")
    payload = schemagen.render(schemagen.build_schema(entry, Sample))
    entry.path.write_bytes(payload.replace(b'"title"', b'"titel"', 1))
    message = schemagen._check_one(schemagen.resolve(entry))
    assert message is not None
    assert "byte diff" in message


def test_a_semantically_equal_but_reordered_file_still_fails(live) -> None:  # noqa: ARG001
    entry = _entry("_fake_decls", "Sample")
    document = schemagen.build_schema(entry, Sample)
    reordered = {key: document[key] for key in sorted(document)}
    entry.path.write_bytes(schemagen.render(reordered))
    assert schemagen._check_one(schemagen.resolve(entry)) is not None


def test_a_live_row_emitted_then_checked_is_green(live) -> None:  # noqa: ARG001
    entry = _entry("_fake_decls", "Sample")
    schemagen._write(entry.path, schemagen.render(schemagen.build_schema(entry, Sample)))
    assert schemagen._check_one(schemagen.resolve(entry)) is None


def test_emit_writes_nothing_for_a_pending_row(live, tmp_path: Path) -> None:  # noqa: ARG001
    """'Do not emit a placeholder JSON file that looks generated but is not.'

    Stated as the live/pending *mapping* rather than as an emptiness check on the directory.
    `DriverCard` landed with P1 W1.5, so `emit` now legitimately writes one file, and a bare
    `glob("*.json") == []` would fail for exactly the reason the gate exists to permit. What must
    stay true is that no PENDING row acquires a file -- and phrasing it this way is also what
    lets P2 land `Doc` and `BlockDraft` without editing a hard-coded count here.
    """
    out = io.StringIO()
    assert schemagen.emit(out) == 0
    resolved = [schemagen.resolve(entry) for entry in schemagen.INVENTORY]
    live_files = {r.entry.file for r in resolved if r.state is schemagen.State.LIVE}
    pending_files = {r.entry.file for r in resolved if r.state is schemagen.State.PENDING}
    on_disk = {path.name for path in tmp_path.glob("*.json")}
    assert on_disk == live_files, "emit wrote a file for a row that is not live"
    assert on_disk.isdisjoint(pending_files)
    assert f"{len(live_files)} file(s) written" in out.getvalue()


def test_a_stray_json_file_in_schema_fails_the_gate(live, tmp_path: Path) -> None:  # noqa: ARG001
    (tmp_path / "invented-v1.json").write_bytes(b"{}\n")
    out = io.StringIO()
    assert schemagen.check(out) == 1
    assert "not one of the thirteen" in out.getvalue()


def test_a_stray_golden_in_expected_fails_the_gate(live, tmp_path: Path) -> None:  # noqa: ARG001
    (tmp_path / "expected" / "invented.txt").write_bytes(b"golden\n")
    out = io.StringIO()
    assert schemagen.check(out) == 1
    assert "no registered render writes it" in out.getvalue()


def test_a_gitkeep_in_expected_is_not_a_stray(live, tmp_path: Path) -> None:  # noqa: ARG001
    (tmp_path / "expected" / ".gitkeep").write_bytes(b"")
    assert schemagen._check_renders() == []


def test_check_reports_every_row_and_its_landing_item() -> None:
    """The pending table is the honest half of this gate and must be printed, not counted."""
    out = io.StringIO()
    schemagen.check(out)
    text = out.getvalue()
    assert "13 declared" in text
    for entry in schemagen.INVENTORY:
        assert entry.file in text
        assert entry.landed_by in text


def test_the_committed_tree_passes_the_gate() -> None:
    """G6 against the real repository, which is what CI runs."""
    out = io.StringIO()
    assert schemagen.check(out) == 0, out.getvalue()


def test_the_schema_directory_holds_no_file_the_inventory_does_not_claim() -> None:
    assert schemagen._stray_files() == ()


def test_the_expected_directory_exists_in_the_checkout() -> None:
    """`.gitattributes` names `schema/expected/**`; a row over a directory git does not track is
    a rule that never fires."""
    assert (REPO / "schema" / "expected").is_dir()
    assert (REPO / "schema" / "expected" / ".gitkeep").is_file()


# ---------------------------------------------------------------------------
# 5. --bless
# ---------------------------------------------------------------------------


def test_bless_flag_is_off() -> None:
    """docling's `tests/test_data_gen_flag.py`, adopted whole (13-quality.md section 5.5).

    A contributor who leaves `OMNIWEAVE_BLESS` exported locally must not be able to land a
    self-blessing PR, and the only way to enforce that is to fail the suite when it is set.
    """
    assert os.environ.get(schemagen.BLESS_ENV) != "1", (
        f"{schemagen.BLESS_ENV}=1 is set. A blessed run is never a test run."
    )


def test_bless_refuses_without_the_environment_flag(
    live,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(schemagen.BLESS_ENV, raising=False)
    out = io.StringIO()
    assert schemagen.bless(out) == 1
    assert "refuses" in out.getvalue()
    assert "13-quality.md" in out.getvalue()


def test_bless_runs_with_the_flag_and_writes_the_registered_renders(
    live,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(schemagen.BLESS_ENV, "1")
    monkeypatch.setattr(schemagen, "RENDERS", (("golden.txt", "one\ntwo\n"),))
    out = io.StringIO()
    assert schemagen.bless(out) == 0
    written = (tmp_path / "expected" / "golden.txt").read_bytes()
    assert written == b"one\ntwo\n"
    assert b"\r" not in written


def test_bless_never_silences_a_schema_byte_diff(
    live,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--bless` is 'never a bypass flag' (11-repo-layout.md section 1.7)."""
    monkeypatch.setenv(schemagen.BLESS_ENV, "1")
    entry = _entry("_fake_decls", "Sample")
    entry.path.write_bytes(b'{"stale": true}\n')
    schemagen.bless(io.StringIO())
    assert schemagen._check_one(schemagen.resolve(entry)) is not None


def test_the_renders_registry_is_empty_at_p1() -> None:
    """The plan reserves `schema/expected/` and never says what a render contains.

    If this starts failing, a render was registered — which is the point at which the plan's
    silence has been resolved and this test should be replaced by one over that render's content.
    """
    assert schemagen.RENDERS == ()


# ---------------------------------------------------------------------------
# 6. The CLI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [[], ["emit"], ["--check"], ["emit", "--check"]])
def test_both_spellings_of_the_invocation_are_accepted(
    argv: list[str],
    live,  # noqa: ARG001
) -> None:
    """The brief's `tools/schemagen.py --check` and the plan's `... emit --check` are one call.

    The tree is emitted first so the two `--check` spellings have something to check. That step
    became load-bearing when `DriverCard` landed with P1 W1.5: `live` points `SCHEMA_DIR` at an
    empty tmp_path, and checking an empty directory against a live row is a real G6 failure
    rather than the argument-parsing failure this test is about. `emit` is idempotent, so the two
    emit spellings are unaffected by running it twice.
    """
    assert schemagen.emit(io.StringIO()) == 0
    assert schemagen.main(argv) == 0


def test_check_and_bless_are_mutually_exclusive(live) -> None:  # noqa: ARG001
    with pytest.raises(SystemExit):
        schemagen.main(["emit", "--check", "--bless"])


def test_an_unknown_verb_is_refused() -> None:
    with pytest.raises(SystemExit):
        schemagen.main(["scaffold"])


def test_there_is_still_no_ow_console_script() -> None:
    """The exit criteria spell G6 `uv run ow schema emit --check`; `ow` arrives with W7.1/W7.2.

    INV-20 and forcing-edge FE5 say every CLI verb is generated from `omniweave/surface/
    registry.py`, so hand-writing one now would make the registry's arrival a reconciliation
    between two surfaces that already disagree. This test records the divergence rather than
    hiding it: when W7.1 lands the script, this test goes and `ow schema emit --check` becomes
    the spelling of the same gate.
    """
    text = (REPO / "packages" / "omniweave" / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" not in text


# ---------------------------------------------------------------------------
# 7. The gate becomes binding on the day a declaration lands
# ---------------------------------------------------------------------------


def test_check_fails_the_moment_a_declaration_lands_with_no_schema(
    live,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the pending mechanism, driven through the public entry point.

    Yesterday's tree had `Sample` unwritten and `check()` returned 0. The only thing that changed
    here is that the declaration exists, and the gate is now binding without anyone having armed
    it.
    """
    entry = _entry("_fake_decls", "Sample")
    monkeypatch.setattr(schemagen, "INVENTORY", (entry,))
    before = io.StringIO()
    assert schemagen.check(before) == 1
    assert "the schema is absent" in before.getvalue()

    assert schemagen.emit(io.StringIO()) == 0
    after = io.StringIO()
    assert schemagen.check(after) == 0, after.getvalue()
    assert entry.path.read_bytes() == schemagen.render(schemagen.build_schema(entry, Sample))


def test_check_stays_green_end_to_end_while_every_row_is_pending(
    live,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The honest half: thirteen pending rows, no files, exit 0 — which is today's real tree."""
    monkeypatch.setattr(
        schemagen,
        "INVENTORY",
        tuple(
            _entry("_omniweave_no_such_module", "Nope", file=f"row-{i}-v1.json") for i in range(3)
        ),
    )
    out = io.StringIO()
    assert schemagen.check(out) == 0
    assert "0 live" in out.getvalue()
    assert list(tmp_path.glob("*.json")) == []
