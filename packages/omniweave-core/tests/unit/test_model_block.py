"""`Block` is the DDL's forty columns, and `BlockDraft` is the only mutable type in the tree.

Two properties here are load-bearing at P2's exit and everything else supports them.

**`Block`'s field set is FROZEN when P2 ends** (16-roadmap.md section 5), so the field set is
asserted against `CREATE TABLE block` in BOTH directions off the plan's own SQL fence: a field
with no column and a column with no field are each a defect, and the two columns that are
deliberately fieldless (`payload`, `decision_id`, read through a join -- 03:311) and the one
field that is deliberately columnless (`marks`, the `mark` table hydrated in windows -- 03:387)
are named here rather than inferred. The mapping is a literal golden, not a derivation: a
derivation from the DDL would agree with a wrong dataclass by construction.

**`BlockDraft` is the ONE mutable type** (03:91, 16-roadmap.md:414), so mutability is asserted
over the WHOLE MODULE rather than per class -- every dataclass but that one must be
`frozen=True, slots=True`. A type cannot arrive mutable by omission, which is exactly how it
would arrive.

`Quad`, the five `OriginSpan` variants, `TextSpan` and `SERIALIZER_CAPS` belong to
`omniweave_core.model.spans` and are tested there. What is tested here is the SEAM: that
`block.py` imports them rather than declaring a second copy (INV-21), and that `Block`'s three
geometry-and-address fields resolve to those types and no others.

Specified in 03-document-model.md sections 2.2, 2.5, 2.6, 2.9 and 13.1, with charter.md's
`block` DDL (:1018-1077) as the second transcription of the column list and ADR-1 decision 2 as
the ruling between them.
"""

from __future__ import annotations

import ast
import dataclasses
import re
import sys
from pathlib import Path
from typing import Literal, get_args, get_type_hints

import pytest
from omniweave_core.drivers import card
from omniweave_core.model import block as block_module
from omniweave_core.model.block import Block, BlockDraft, Capabilities, CellPos, Mark
from omniweave_core.model.enums import Kind, Layer, Method, Quote, Trust
from omniweave_core.model.spans import (
    SERIALIZER_CAPS,
    OriginBytes,
    OriginGlyphs,
    OriginNodePath,
    OriginNone,
    OriginPixels,
    OriginSpan,
    Quad,
    TextSpan,
)

CORE_SRC = Path(block_module.__file__).resolve().parents[1]
"""`.../src/omniweave_core`, found from the module rather than by counting `parents[n]`."""


# ---------------------------------------------------------------------------
# Reading the plan: the DDL fence and the type fences
# ---------------------------------------------------------------------------


def _create_table(text: str, table: str) -> str:
    """The body of `CREATE TABLE <table> (...)`, paren-matched rather than line-matched."""
    marker = f"CREATE TABLE {table} ("
    start = text.index(marker) + len(marker)
    depth = 1
    for offset in range(start, len(text)):
        if text[offset] == "(":
            depth += 1
        elif text[offset] == ")":
            depth -= 1
            if depth == 0:
                return text[start:offset]
    message = f"unterminated CREATE TABLE {table}"
    raise AssertionError(message)


def _columns(body: str) -> tuple[str, ...]:
    """The column names of a `CREATE TABLE` body, in declaration order.

    Split on commas at paren depth 0, because four of the plan's lines declare two or three
    columns each (`os_part TEXT, os_a INTEGER, ...`) while `FOREIGN KEY (doc_ord, gen, page)`
    and `CHECK ((os_a IS NULL) = (os_b IS NULL))` carry commas that are not separators.
    Comments go first: `-- os_b is a LENGTH (section 7.2)` contains a comma too.
    """
    stripped = "\n".join(re.sub(r"--.*$", "", line) for line in body.splitlines())
    clauses: list[str] = []
    token: list[str] = []
    depth = 0
    for char in stripped:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            clauses.append("".join(token))
            token = []
        else:
            token.append(char)
    clauses.append("".join(token))
    reserved = {"CHECK", "FOREIGN", "PRIMARY", "UNIQUE", "CONSTRAINT"}
    names: list[str] = []
    for clause in clauses:
        words = clause.split()
        if not words or words[0].upper() in reserved:
            continue
        names.append(words[0])
    return tuple(names)


def _block_columns(plan, document: str) -> tuple[str, ...]:
    """`block`'s column list as `document` prints it."""
    plan.require()
    fences = [body for body in plan.fences(document, "sql") if "CREATE TABLE block (" in body]
    assert len(fences) == 1, f"{document} prints {len(fences)} `CREATE TABLE block` fences"
    return _columns(_create_table(fences[0], "block"))


def _fence_class(plan, name: str) -> ast.ClassDef:
    """The plan's own declaration of `name`, parsed out of 03's Python fences.

    03 section 2's fences are valid Python -- `class Mark: a: int; b: int` and all -- so `ast`
    is the right reader. A regex over `field: Type` lines would miss the fences that put several
    fields on one line, which is most of them.
    """
    plan.require()
    for body in plan.fences("03-document-model.md", "python"):
        try:
            tree = ast.parse(body)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == name:
                return node
    message = f"03-document-model.md prints no `class {name}`"
    raise AssertionError(message)


def _fence_fields(node: ast.ClassDef) -> tuple[str, ...]:
    """The annotated attribute names of a plan fence's class, in declaration order."""
    return tuple(
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    )


def _declared_fields(cls: type) -> tuple[str, ...]:
    return tuple(field.name for field in dataclasses.fields(cls))


def _defaulted_fields(cls: type) -> tuple[str, ...]:
    return tuple(
        field.name
        for field in dataclasses.fields(cls)
        if field.default is not dataclasses.MISSING
        or field.default_factory is not dataclasses.MISSING
    )


# ---------------------------------------------------------------------------
# The golden: every `block` column, and the `Block` field that carries it
# ---------------------------------------------------------------------------

COLUMN_TO_FIELD: tuple[tuple[str, str | None], ...] = (
    ("block_id", "id"),
    ("doc_ord", "doc_ord"),
    ("gen", "gen"),
    ("page", "page"),
    ("addr", "addr"),
    ("cite", "cite"),
    ("parent_id", "parent"),
    ("ord", "ord"),
    ("kind", "kind"),
    ("raw_kind", "raw_kind"),
    ("layer", "layer"),
    ("label", "label"),
    ("text", "text"),
    ("content_digest", "content_digest"),
    ("layout_digest", "layout_digest"),
    ("revision", "revision"),
    ("quad", "quad"),
    # The seven `os_*` columns are ONE tagged union on the value type. 03 section 7.2's mapping
    # table is the only correct way to fill them, and the CHECKs make it enforceable.
    ("os_kind", "origin"),
    ("os_part", "origin"),
    ("os_a", "origin"),
    ("os_b", "origin"),
    ("os_path", "origin"),
    ("os_extractor", "origin"),
    ("os_codec", "origin"),
    ("ts_a", "span"),
    ("ts_b", "span"),
    ("producer_id", "producer_id"),
    ("method", "method"),
    ("trust", "trust"),
    ("score", "score"),
    ("score_kind", "score_kind"),
    ("quote", "quote"),
    ("origin_operator", "origin_operator"),
    ("origin_driver", "origin_driver"),
    ("driver_schema_v", "driver_schema_v"),
    ("restriction_bits", "restriction_bits"),
    # 03:311, verbatim: "Two columns are on the `block` table but not on `Block`" -- `payload`,
    # read through `Doc.payload(id)`, and `decision_id`, read through the runtime's
    # `route_decision`. Neither is meaningful without a join and neither is on the hot path of a
    # render, and materialising a JSON object per block would put a `json.loads` on every row of
    # a 600k-block scan for a field two consumers read (03:985).
    ("decision_id", None),
    ("payload", None),
    ("state", "tombstoned"),
    ("x", "x"),
)

FIELDS_WITHOUT_A_COLUMN: tuple[str, ...] = ("marks",)
"""`Block.marks` is the `mark` table, not a `block` column.

It is a tuple on the value type and a separate table with a SURROGATE `mark_id`, because two
links may cover exactly the same range (03:354). `Doc.blocks()` hydrates it in windows of
`MARK_HYDRATE_WINDOW = 512` block ids -- 1,172 extra statements for a 600k-block document
instead of 600,000 (03:385).
"""

COLUMNS = 40
"""03 section 13.1 and charter.md:1018-1077, counted. Asserted below, not trusted."""

FROZEN_FIELD_SET: tuple[str, ...] = (
    # identity
    "id",
    "addr",
    "cite",
    "doc_ord",
    "gen",
    "page",
    # the containment spine
    "parent",
    "ord",
    # classification
    "kind",
    "raw_kind",
    "layer",
    "label",
    "text",
    # digests and revision
    "content_digest",
    "layout_digest",
    "revision",
    # position and address in the original container
    "quad",
    "origin",
    "span",
    # provenance -- six axes, never conflated
    "producer_id",
    "method",
    "trust",
    "quote",
    "score",
    "score_kind",
    "origin_operator",
    "origin_driver",
    "driver_schema_v",
    "restriction_bits",
    # satellites and state
    "marks",
    "tombstoned",
    "x",
)
"""The FROZEN field set, spelled out, because 16-roadmap.md:429 freezes it at the end of P2.

**Why a literal list is here on top of the two derivations above it.** `COLUMN_TO_FIELD` proves
every field carries a column and `test_block_declares_the_plans_fields_in_the_plans_order` proves
the declaration order is 03:236-258's own -- and both of those are relations, not values. A
reviewer in P5 holding a patch that adds a field reads a relation and sees a rule that the new
field can be made to satisfy: give it a column, add a row to the mapping, and both derivations go
green again. What that reviewer needs to meet instead is a list of thirty-two names with
16-roadmap.md:429 written next to it, because the freeze is a claim about the LIST and the
paragraph at :433 is why -- a field that forces a re-parse of an existing corpus "is a defect, not
a migration, because it re-mints cites".

So this is the snapshot taken at the moment of the freeze, and adding a field means editing it,
which is the point. It is not a second home for the field set: `Block` is the home, this is a
golden, and the test below compares the two rather than deriving either from the other.

**And a golden is only a golden while it is spelled out.** An adversarial pass replaced these
thirty-two lines with `FROZEN_FIELD_SET = _declared_fields(Block)` -- one line, the shape a reader
reaches for the first time the golden fails -- and the suite stayed green over 155 tests, because
both sides of the comparison below had become the same object.
`test_the_frozen_field_set_is_written_down_and_not_derived_from_block` reads this module's own AST
to stop that, and the reason it is worth a test of its own is that the other pin on this surface,
`test_block_declares_the_plans_fields_in_the_plans_order`, takes the `plan` fixture and therefore
SKIPS on a checkout without `_plan/`. On a clean clone the golden is the only thing left holding
the names and the order.
"""


# ---------------------------------------------------------------------------
# 1. `Block` against the DDL, in both directions
# ---------------------------------------------------------------------------


def test_the_plan_prints_forty_block_columns_and_the_golden_is_them_in_order(plan) -> None:
    """The golden's left column IS 03 section 13.1's, so a DDL change fails here first."""
    printed = _block_columns(plan, "03-document-model.md")
    assert len(printed) == COLUMNS
    assert printed == tuple(column for column, _field in COLUMN_TO_FIELD)


def test_the_charter_prints_the_same_forty_columns_except_label__adr_1_decision_2(plan) -> None:
    """The one place the two DDLs disagree, named so it cannot be re-litigated silently.

    charter.md:1029 spells the column `title`; 03-document-model.md:2333 spells it `label`, and
    03:283 says why -- "Renamed from `title` by ADR-1 decision 7, so that `Kind.TITLE` keeps the
    word". ADR-0001 decision 2 (`_plan/adr/0001-terminology-lock-bulk-pass.md`:103) makes it
    "the column becomes **`block.label`**, and its wire key with it", and its consequence 4
    (:176, :179) puts the rename in P2 as a DDL column and a wire key. `label` is therefore the
    implemented spelling and the charter is the superseded site.
    """
    charter = _block_columns(plan, "_notes/charter.md")
    document = _block_columns(plan, "03-document-model.md")
    assert len(charter) == len(document) == COLUMNS
    differences = [
        (left, right) for left, right in zip(charter, document, strict=True) if left != right
    ]
    assert differences == [("title", "label")]


def test_every_block_column_is_carried_by_a_field_or_is_read_through_a_join() -> None:
    """A column with no field is a defect unless 03:311 names it. Two are named."""
    fields = set(_declared_fields(Block))
    unmapped = [
        column for column, name in COLUMN_TO_FIELD if name is not None and name not in fields
    ]
    assert unmapped == [], f"columns whose field is missing from Block: {unmapped}"
    fieldless = sorted(column for column, name in COLUMN_TO_FIELD if name is None)
    assert fieldless == ["decision_id", "payload"]


def test_every_block_field_carries_a_column_or_is_a_named_satellite() -> None:
    """A field with no column is a defect unless it is `marks`. Nothing else may join it."""
    carried = {name for _column, name in COLUMN_TO_FIELD if name is not None}
    orphans = [name for name in _declared_fields(Block) if name not in carried]
    assert orphans == list(FIELDS_WITHOUT_A_COLUMN), f"fields with no column: {orphans}"


def test_block_declares_the_plans_fields_in_the_plans_order(plan) -> None:
    """03:236-258, transcribed. Order matters because the fence is read as a record."""
    assert _declared_fields(Block) == _fence_fields(_fence_class(plan, "Block"))


def test_block_carries_thirty_two_fields_over_forty_columns() -> None:
    """The arithmetic of the collapse, stated so a silent widening shows up as a number.

    40 columns - 7 `os_*` + 1 `origin` - 2 `ts_*` + 1 `span` - 2 read through a join = 31, plus
    `marks`, which has no column at all = 32.
    """
    collapsed = COLUMNS - 7 + 1 - 2 + 1 - 2 + len(FIELDS_WITHOUT_A_COLUMN)
    assert len(_declared_fields(Block)) == collapsed == 32


def test_the_frozen_field_set_is_these_thirty_two_names_in_this_order__16_429() -> None:
    """16-roadmap.md:429, "`Block`'s field set", frozen at the end of P2 (week 16).

    The comparison is against `FROZEN_FIELD_SET`, whose docstring says why a literal golden is
    the right instrument for a freeze and why the two derivations above it are not. Read as a
    failure message: a field added, removed, renamed or MOVED shows up here, and the fix is not
    to edit the golden -- it is to notice that 16-roadmap.md:433 calls this freeze's obligation
    one "nothing else in the plan does" carry, and that a field which forces a re-parse is a
    defect rather than a migration. `tests/unit/test_p2_freeze.py` indexes this test as the pin
    for that surface, and it will fail if this function is renamed away.
    """
    assert _declared_fields(Block) == FROZEN_FIELD_SET
    assert len(FROZEN_FIELD_SET) == 32
    assert len(set(FROZEN_FIELD_SET)) == 32, "a name appears twice in the golden"


def _sole_binding(source: str, filename: str, name: str) -> ast.AST:
    """The ONE statement in `source` that binds `name`, or an assertion naming the others.

    Every binding form is counted and not just the annotated one at module scope, which is the
    hole the first version of this had: annotating the golden as a literal and then adding a plain
    `NAME = <derivation>` line further down satisfied a check that only looked for `AnnAssign`,
    and the module-level rebinding is what the tests then read. `ast.walk` rather than
    `tree.body`, for the same reason one level out -- a `global NAME` inside a function reaches
    the same value.
    """
    tree = ast.parse(source, filename=filename)
    bindings: list[ast.AST] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AugAssign | ast.NamedExpr):
            targets = [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            bindings.append(node)
    assert len(bindings) == 1, (
        f"{name} is bound {len(bindings)} times in {filename} (lines "
        f"{[getattr(node, 'lineno', '?') for node in bindings]}); it is a golden, and a golden "
        f"rebound anywhere is whatever the last binding made it"
    )
    binding = bindings[0]
    assert isinstance(binding, ast.AnnAssign), f"{name} is declared with its type annotation"
    assert binding.value is not None
    return binding.value


def test_the_frozen_field_set_is_written_down_and_not_derived_from_block() -> None:
    """`FROZEN_FIELD_SET` is a tuple of thirty-two string literals in this module's own source.

    Rule 5, on the one constant in this file where it bites: a golden compared against its own
    subject is not an assertion, it is a restatement. See `FROZEN_FIELD_SET`'s docstring for the
    one-line edit this catches and for why the plan-backed pin beside it is not a substitute.

    The names are read back out of the AST rather than off the tuple so that the failure is about
    HOW the constant is written -- a comprehension, a call, a splat of another tuple all read as
    thirty-two names at runtime and as something other than `ast.Constant` here.
    """
    value = _sole_binding(Path(__file__).read_text(encoding="utf-8"), __file__, "FROZEN_FIELD_SET")
    assert isinstance(value, ast.Tuple), (
        "FROZEN_FIELD_SET is a tuple display and not an expression over `Block`; a derived golden "
        "agrees with any dataclass by construction. 16-roadmap.md:429 freezes the LIST, so the "
        "list is written here -- see the constant's docstring before changing this."
    )
    spelled = [
        element.value
        for element in value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]
    assert len(spelled) == len(value.elts) == 32, (
        f"FROZEN_FIELD_SET holds {len(value.elts)} elements of which {len(spelled)} are string "
        f"literals; every one of the thirty-two names is spelled out or the golden is a derivation"
    )
    assert tuple(spelled) == FROZEN_FIELD_SET


def test_block_has_neither_a_payload_nor_a_decision_id_attribute() -> None:
    """Not merely absent from `fields()`: absent from the type, so no one can read it (03:311)."""
    instance = _a_block()
    for absent in ("payload", "decision_id"):
        assert not hasattr(instance, absent)


def test_method_trust_and_quote_have_no_default__03_243() -> None:
    """ "NO DEFAULT. State it." A driver that has not stated trust must be COUNTED, not clean."""
    required = set(_declared_fields(Block)) - set(_defaulted_fields(Block))
    assert {"method", "trust", "quote"} <= required


def test_the_defaulted_fields_are_exactly_the_plans_nine() -> None:
    """03:246-252's tail. A tenth default would let a host mint a row without stating a fact."""
    assert _defaulted_fields(Block) == (
        "score",
        "score_kind",
        "origin_operator",
        "origin_driver",
        "driver_schema_v",
        "restriction_bits",
        "marks",
        "tombstoned",
        "x",
    )


def test_x_defaults_to_a_read_only_mapping_shared_by_no_one__03_262() -> None:
    """ "a shared mutable default on the framework's hottest type is a bug waiting for its first
    author". A `Mapping`, not a `dict`, and not `field(default_factory=dict)`."""
    first, second = _a_block(), _a_block()
    assert first.x == {}
    assert first.x is second.x
    with pytest.raises(TypeError):
        first.x["x.vendor.key"] = 1  # type: ignore[index]


def test_a_block_is_frozen_and_carries_no_instance_dict() -> None:
    """`frozen=True, slots=True`: an assignment raises and there is nowhere to put a stray
    attribute, which is what lets a reader hand one instance to two consumers."""
    instance = _a_block()
    with pytest.raises(dataclasses.FrozenInstanceError):
        instance.page = 3  # type: ignore[misc]
    assert "__slots__" in vars(Block)
    assert not hasattr(instance, "__dict__")


def _a_block() -> Block:
    """A minimal legal `Block`. Every required field stated, nothing invented."""
    return Block(
        id=1,  # type: ignore[arg-type]
        addr="p14/3",  # type: ignore[arg-type]
        cite="d7#412",  # type: ignore[arg-type]
        doc_ord=7,
        gen=1,
        page=14,
        parent=None,
        ord=3,
        kind=Kind.PARAGRAPH,
        raw_kind=None,
        layer=Layer.BODY,
        label=None,
        text="hello",
        content_digest=b"\x00" * 16,
        layout_digest=None,
        revision=0,
        quad=None,
        origin=OriginNone(),
        span=None,
        producer_id=1,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM,
    )


# ---------------------------------------------------------------------------
# 2. The seam with `omniweave_core.model.spans`
# ---------------------------------------------------------------------------


def test_the_three_geometry_and_address_fields_resolve_to_the_spans_types() -> None:
    """`Block` names `Quad`, `OriginSpan` and `TextSpan`; it does not define them.

    Resolved through `get_type_hints`, which is the assertion that matters: `from __future__
    import annotations` makes every annotation a string, so a `Quad` that had quietly become a
    local shadow would still read `Quad | None` in the source and differ only here. It is also
    why `collections.abc.Mapping` is a runtime import in `block.py` -- under `TYPE_CHECKING`
    this call would raise `NameError` on `Block.x` instead.
    """
    hints = get_type_hints(Block)
    assert set(get_args(hints["quad"])) == {Quad, type(None)}
    assert set(get_args(hints["span"])) == {TextSpan, type(None)}
    assert set(get_args(hints["origin"])) == {
        OriginBytes,
        OriginNodePath,
        OriginGlyphs,
        OriginPixels,
        OriginNone,
    }
    assert set(get_args(hints["origin"])) == set(get_args(OriginSpan))


def test_a_block_may_carry_any_of_the_five_origin_variants() -> None:
    """The union is nullable only as a whole and `OriginNone()` is a **value**, not a null
    (03:1466): `os_kind` is `NOT NULL` on the table."""
    quad = Quad.from_driver(
        ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        origin="topleft",
        unit="pt",
        page_h=100.0,
        dpi=None,
        rotation=0,
    )
    variants = (
        OriginBytes(part="file", start=0, length=5, codec="utf-8/strict"),
        OriginNodePath(part="word/document.xml", path=(0, 3, 1, 7)),
        OriginGlyphs(part="pdf:page=12/content=0", extractor="pdftext@0.6", start=0, length=5),
        OriginPixels(page=14, quad=quad),
        OriginNone(),
    )
    for variant in variants:
        assert dataclasses.replace(_a_block(), origin=variant).origin == variant


def test_neither_quad_nor_a_span_type_is_declared_in_this_module__inv_21() -> None:
    """One name, one home. `spans.py` declares them; `block.py` imports them.

    Counting DEFINITION SITES rather than mentions, over the whole distribution's source, and
    naming the one file each is allowed to live in. AST rather than `__subclasses__`, because
    `omniweave_core.model` is LAZY and a subclass walk only sees what this session loaded.
    """
    homes = {
        "Quad": "spans.py",
        "TextSpan": "spans.py",
        "RenderSpan": "spans.py",
        "OriginBytes": "spans.py",
        "OriginNodePath": "spans.py",
        "OriginGlyphs": "spans.py",
        "OriginPixels": "spans.py",
        "OriginNone": "spans.py",
        "Block": "block.py",
        "BlockDraft": "block.py",
        "Capabilities": "block.py",
        "CellPos": "block.py",
        "Mark": "block.py",
    }
    sites: dict[str, list[str]] = {name: [] for name in homes}
    for path in sorted(CORE_SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in sites:
                sites[node.name].append(path.name)
    for name, home in homes.items():
        assert sites[name] == [home], f"{name} is declared in {sites[name]}, not just {home}"


# ---------------------------------------------------------------------------
# 3. Mutability, asserted over the module rather than per class
# ---------------------------------------------------------------------------


def _module_classes() -> tuple[type, ...]:
    """Every class this module DECLARES -- not the ones it imported."""
    return tuple(
        value
        for value in vars(block_module).values()
        if isinstance(value, type) and value.__module__ == block_module.__name__
    )


def test_the_module_declares_the_five_types_this_cluster_owns() -> None:
    """The set the three tests below quantify over, so none of them can pass vacuously."""
    assert sorted(cls.__name__ for cls in _module_classes()) == [
        "Block",
        "BlockDraft",
        "Capabilities",
        "CellPos",
        "Mark",
    ]


def test_blockdraft_is_the_only_mutable_dataclass_in_this_module() -> None:
    """03:91: "There is exactly one mutable model type, `BlockDraft`, and it never reaches a
    reader." Asserted over the module so a new type cannot arrive mutable by omission."""
    mutable = sorted(
        cls.__name__
        for cls in _module_classes()
        if dataclasses.is_dataclass(cls) and not cls.__dataclass_params__.frozen
    )
    assert mutable == ["BlockDraft"]


def test_every_other_dataclass_here_is_frozen_and_slotted() -> None:
    for cls in _module_classes():
        if not dataclasses.is_dataclass(cls) or cls is BlockDraft:
            continue
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} is not frozen"
        assert "__slots__" in vars(cls), f"{cls.__name__} is not slotted"


def test_every_class_here_is_a_dataclass() -> None:
    """The partition the two tests above rely on. A plain mutable class would slip past both,
    because `__dataclass_params__` is what they read."""
    for cls in _module_classes():
        assert dataclasses.is_dataclass(cls), cls.__name__


def test_blockdraft_is_slotted_even_though_it_is_mutable() -> None:
    """Mutable is not the same as open: 03:321 prints `@dataclass(slots=True)`, and 03:2578's
    resident-state arithmetic prices a draft as "a `slots=True` dataclass instance"."""
    assert "__slots__" in vars(BlockDraft)
    with pytest.raises(AttributeError):
        _a_draft().invented = 1  # type: ignore[attr-defined]


def test_no_type_here_carries_a_rendered_projection__03_39() -> None:
    """ "No model class in this framework has an `html`, `markdown` or `md` attribute."

    A projection is a pure function of `(scope, options, store snapshot)`; it may be cached as a
    hash-pinned view in `manifest.views[]` but it is never a FIELD.
    """
    for cls in _module_classes():
        names = set(_declared_fields(cls))
        assert not names & {"html", "markdown", "md", "gfm", "otsl"}, cls.__name__


# ---------------------------------------------------------------------------
# 4. `BlockDraft` -- what the host mints is what the draft omits
# ---------------------------------------------------------------------------

HOST_MINTED: tuple[str, ...] = (
    "id",
    "addr",
    "cite",
    "doc_ord",
    "gen",
    "page",
    "ord",
    "content_digest",
    "layout_digest",
    "revision",
    "producer_id",
    "origin_operator",
    "origin_driver",
    "driver_schema_v",
    "restriction_bits",
    "tombstoned",
)
"""Every `Block` field a `BlockDraft` must NOT carry. 03:322-324.

"Everything `Block` carries except what the HOST mints -- no `id`, no `addr`, no `cite`, no
`producer_id`, no `origin_*`, no `restriction_bits`." The list is longer than that sentence
because `doc_ord`, `gen`, `ord`, the two digests, `revision` and `state` are host-written too
(03 section 2.5's `written by` column), and a draft carrying any of them would be proposing an
identity -- which is INV-6 and INV-7's whole subject.
"""


def _a_draft() -> BlockDraft:
    return BlockDraft(
        kind=Kind.PARAGRAPH,
        layer=Layer.BODY,
        method=Method.NATIVE,
        trust=Trust.EXTRACTED,
        quote=Quote.VERBATIM,
    )


def test_blockdraft_declares_the_plans_fields_in_the_plans_order(plan) -> None:
    assert _declared_fields(BlockDraft) == _fence_fields(_fence_class(plan, "BlockDraft"))


def test_a_draft_carries_no_host_minted_field() -> None:
    """The mechanism behind INV-6: no `block_id` ever crosses the driver wire, which is what
    makes a fragment portable between stores (03:50)."""
    present = sorted(set(_declared_fields(BlockDraft)) & set(HOST_MINTED))
    assert present == []


def test_a_draft_carries_every_other_block_field_plus_payload_and_cell() -> None:
    """Both directions, so a field added to `Block` cannot quietly become undraftable."""
    expected = {name for name in _declared_fields(Block) if name not in HOST_MINTED}
    expected |= {"payload", "cell"}
    assert set(_declared_fields(BlockDraft)) == expected


def test_the_five_classification_fields_have_no_default__03_339() -> None:
    """ "A driver that has not thought about trust cannot silently ship `EXTRACTED`; it must
    write `Trust.AMBIGUOUS` and be counted." """
    required = tuple(
        name for name in _declared_fields(BlockDraft) if name not in _defaulted_fields(BlockDraft)
    )
    assert required == ("kind", "layer", "method", "trust", "quote")
    with pytest.raises(TypeError):
        BlockDraft(kind=Kind.PARAGRAPH, layer=Layer.BODY)  # type: ignore[call-arg]


def test_the_two_mutable_defaults_are_per_instance_not_shared() -> None:
    """`marks` and `x` are the only `default_factory` fields, which is what makes two drafts
    independent -- the bug 03:262 names, on the one type that is allowed to be mutable."""
    first, second = _a_draft(), _a_draft()
    first.marks.append(Mark(a=0, b=1, kind="bold"))
    first.x["x.vendor.key"] = 1
    assert second.marks == []
    assert second.x == {}


def test_a_draft_is_mutable_field_by_field() -> None:
    """ "Mutable on purpose, so an assembler can fill fields in the order the source yields
    them" (03:324). It is the only type in the framework this is true of."""
    draft = _a_draft()
    draft.text = "a paragraph"
    draft.cell = CellPos(r=2, c=5)
    draft.trust = Trust.AMBIGUOUS
    assert (draft.text, draft.cell, draft.trust) == ("a paragraph", CellPos(2, 5), Trust.AMBIGUOUS)


def test_a_drafts_origin_defaults_to_the_value_none_not_to_python_none__03_1466() -> None:
    """ "`OriginNone()` is a **value**, not a null." `os_kind` is `NOT NULL` on the table."""
    assert _a_draft().origin == OriginNone()
    assert _a_draft().origin is not None


def test_cellpos_defaults_to_a_one_by_one_cell__03_319() -> None:
    assert CellPos(r=2, c=5) == CellPos(r=2, c=5, row_span=1, col_span=1)


def test_cellpos_declares_the_plans_fields(plan) -> None:
    assert _declared_fields(CellPos) == _fence_fields(_fence_class(plan, "CellPos"))


# ---------------------------------------------------------------------------
# 5. `Mark`
# ---------------------------------------------------------------------------


def test_mark_declares_the_plans_fields_in_order(plan) -> None:
    assert _declared_fields(Mark) == _fence_fields(_fence_class(plan, "Mark"))


def test_a_mark_may_be_zero_width__03_381() -> None:
    """ "a zero-width mark (`a == b`) is legal and meaningful for `anchor` and `note_ref`"."""
    anchor = Mark(a=7, b=7, kind="anchor", value={"name": "sec-4-2", "akind": "section"})
    assert anchor.a == anchor.b


def test_two_marks_may_cover_exactly_the_same_range__03_354() -> None:
    """Which is why `mark_id` is a SURROGATE, and why `Block.marks` is a tuple rather than a
    mapping keyed on the range."""
    both = (
        Mark(a=0, b=12, kind="link", value={"target": "a", "kind": "external"}),
        Mark(a=0, b=12, kind="link", value={"target": "b", "kind": "external"}),
    )
    assert both[0] != both[1]


def test_mark_kind_is_a_string_because_the_vocabulary_is_open_at_the_edges() -> None:
    """`mark.kind` is `TEXT NOT NULL` in the DDL (03:2412) and is NOT one of `enum_val`'s
    fifteen closed domains: the section 2.7 table keeps `raw_style` for "a run style the model
    has no field for", so a producer may name a style core does not know."""
    assert get_type_hints(Mark)["kind"] is str


def test_a_mark_with_a_scalar_value_hashes_and_one_with_a_json_object_does_not() -> None:
    """`Mark.value` is `Any` -- a JSON value -- so `Block.marks` is only conditionally hashable.

    Stated rather than discovered, because `marks` is a tuple a reader may put in a cache key: a
    `dict` value makes that raise at the call site, which is the right place for it to raise.
    """
    assert hash(Mark(a=0, b=1, kind="bold")) is not None
    with pytest.raises(TypeError):
        hash(Mark(a=0, b=1, kind="lang", value={"bcp47": "de-CH"}))


# ---------------------------------------------------------------------------
# 6. `Capabilities` -- one field set, three homes
# ---------------------------------------------------------------------------


def test_capabilities_declares_the_plans_fifteen_in_order(plan) -> None:
    """03:483-498. Fifteen, which 03:530 also prints as a count."""
    fields = _declared_fields(Capabilities)
    assert len(fields) == 15
    assert fields == _fence_fields(_fence_class(plan, "Capabilities"))


def test_the_fifteen_are_the_cards_fifteen__one_field_set_three_homes() -> None:
    """`ParseCapability` carries a SIXTEENTH key, `format_tokens`, which is card-only: it never
    appears on a `Doc`, and it is the key that makes a format a third party invented reachable
    at all (`drivers/card.py`'s `ParseCapability`, 04-driver-system.md section 2.2)."""
    card_fields = _declared_fields(card.ParseCapability)
    assert card_fields[-1] == "format_tokens"
    assert card_fields[:-1] == _declared_fields(Capabilities)


def test_spanmap_is_not_one_of_the_fifteen__03_531() -> None:
    """ "a `SpanMap` is emitted by core's own serializer over core's own five formats, which a
    parse driver never calls, so the field had no writer". That fact lives in `SERIALIZER_CAPS`,
    which is why the five formats are asserted here beside the absence."""
    assert "spanmap" not in _declared_fields(Capabilities)
    assert "spanmap" not in _declared_fields(card.ParseCapability)
    assert tuple(SERIALIZER_CAPS) == ("md", "gfm", "html", "text", "otsl")


def _is_literal(annotation: object) -> bool:
    """`Literal[...]`'s `__origin__` is `Literal` itself."""
    return getattr(annotation, "__origin__", None) is Literal


def test_the_ten_ladders_are_the_cards_ladders_member_for_member_and_in_order() -> None:
    """The `Literal` arms here and `card.PARSE_LADDERS` are two transcriptions of one table, and
    the ORDER is load-bearing: a ladder is compared `>=`, so a reordered arm changes which
    driver matches. `reading_order` in particular is ordered by marker's measured 75%-versus-56%
    char-stream-over-learned-head result, not by how the words sound (03:555)."""
    ladders = {
        name: get_args(annotation)
        for name, annotation in get_type_hints(Capabilities).items()
        if _is_literal(annotation)
    }
    assert set(ladders) == set(card.PARSE_LADDERS)
    for name, arms in ladders.items():
        assert arms == card.PARSE_LADDERS[name], name


def test_the_three_booleans_and_the_two_sets_are_the_cards() -> None:
    """`math` is compared as a superset and `forfeits` as a subset -- the only inverted
    comparison on the whole card -- so neither may drift into a ladder."""
    hints = get_type_hints(Capabilities)
    booleans = tuple(name for name, annotation in hints.items() if annotation is bool)
    assert booleans == card.PARSE_BOOLS
    sets = tuple(name for name, annotation in hints.items() if annotation == frozenset[str])
    assert set(sets) == set(card.PARSE_SETS)


def test_the_fifteen_partition_into_ten_ladders_three_bools_and_two_sets() -> None:
    """No sixteenth shape. A field that is none of the three has no comparison rule at all, so
    `resolve()` could not match a card against it (04-driver-system.md section 2.2)."""
    assert len(card.PARSE_LADDERS) + len(card.PARSE_BOOLS) + len(card.PARSE_SETS) == 15


def test_forfeits_is_the_only_field_with_a_default__03_498() -> None:
    """ "`forfeits` is the exception in the other direction and defaults empty, because
    'forfeits nothing' is what an absent forfeits list says." Every OTHER field is stated,
    because on this dataclass a default is a claim about a document."""
    assert _defaulted_fields(Capabilities) == ("forfeits",)


def test_achieved_may_be_lower_than_declared_and_the_type_does_not_stop_it__03_534() -> None:
    """ "`achieved` is what the driver actually delivered on this document ... and it may be
    lower, never higher." Both are this one type, so the ordering is enforced where `achieved`
    is COMPUTED -- from the committed rows at `end_doc` (03:536) -- and not by the value type.
    That is precisely what lets one field set have three homes.
    """
    declared = Capabilities(
        spatial="block_bbox",
        origin_span="exact",
        text_span=True,
        marks=True,
        reading_order="char_stream",
        sections="typed_levels",
        tables="cells_with_spans",
        math=frozenset({"latex"}),
        assets="bytes",
        asset_origin=True,
        notes="linked",
        confidence="element",
        furniture="separated",
        round_trip="structure",
    )
    achieved = dataclasses.replace(declared, spatial="none", origin_span="none", marks=False)
    assert achieved != declared
    assert achieved.forfeits == frozenset()
    ladder = card.PARSE_LADDERS["spatial"]
    assert ladder.index(achieved.spatial) < ladder.index(declared.spatial)


# ---------------------------------------------------------------------------
# 7. Laziness and purity, from a fresh interpreter
# ---------------------------------------------------------------------------


def test_a_bare_core_import_loads_no_part_of_the_model_package__g17(interpreter) -> None:
    """G17, measured rather than reasoned. `model` is one of the nine LAZY names
    (11-repo-layout.md section 1.3) and `ow hook prompt` pays for every module a bare
    `import omniweave_core` touches, so this file landing must not change what that costs."""
    loaded = interpreter.modules_added_by("import omniweave_core")
    eager = sorted(name for name in loaded if name.startswith("omniweave_core.model"))
    assert eager == [], f"a bare core import loaded {eager}"


def test_the_block_module_reaches_nothing_outside_the_standard_library__inv_2(interpreter) -> None:
    """INV-2 / 03:89: `omniweave_core.model` is stdlib only -- no pydantic, no numpy, no PIL, no
    pandas, no pyarrow. Measured as a difference against a bare interpreter so whatever a
    virtualenv injects at startup cancels instead of reading as a dependency."""
    added = interpreter.modules_added_by("import omniweave_core.model.block")
    third_party = sorted(
        name
        for name in added
        if not name.startswith("_")
        and name.split(".")[0] not in sys.stdlib_module_names
        and not name.startswith(("omniweave_core", "omniweave_ports"))
    )
    assert third_party == [], f"omniweave_core.model.block pulled in {third_party}"


def test_the_block_module_never_reaches_sqlite3__inv_17(interpreter) -> None:
    """INV-17: `sqlite3` is `omniweave_core.store`'s alone, and the value types are what the
    store persists -- not the other way round."""
    assert "sqlite3" not in interpreter.modules_added_by("import omniweave_core.model.block")


def test_the_module_opens_no_file_and_starts_nothing_at_import_time__inv_3(interpreter) -> None:
    """INV-3: a module body reads no data. Every default here is a literal, so there is nothing
    in this module that could want a file, a socket, a subprocess or a thread."""
    report = interpreter.audit("import omniweave_core.model.block")
    assert report.non_python_files == ()
    assert report.sockets == 0
    assert report.subprocesses == 0
    assert report.threads_started == 0
