"""The store boundary is 33 methods, and this file is what makes that a number and not a claim.

07-store-and-retrieval.md:49-52 prices the boundary at "four Protocols in `omniweave_core.store`,
33 methods in total" and 02-architecture.md:702 restates it as "**33 methods, not four**", because
"saying 'the store boundary is four methods' understates it by an order of magnitude and would
misprice any decision to swap the backend". 03-document-model.md:568-572 says what happens if the
number moves: "Eleven, and the count is fixed ... A twelfth re-prices 07 section 1.2's T3 Postgres
swap and widens the only boundary a second backend has to reimplement, so adding one is an ADR, not
a patch." 16-roadmap.md:428 freezes all four at P2's exit.

**Everything here is counted or read off the Protocol classes and the plan, never off a list typed
in this file.** That is the difference between a test and a second transcription. Concretely:

* the method counts come from `vars(cls)`, so a twelfth `DocSink` method fails the build;
* the method NAMES and their ORDER come from `_plan/`'s own `python` fences, parsed with `ast`, so
  a renamed or reordered method fails against the document that declares it;
* every parameter name, keyword-only marker, default and annotation is compared against the same
  parsed fence, so a widened signature fails even when the count is right.

`tests/unit/test_enum_val_parity.py` is the pattern: two enforcers, one truth, and parity is what
stops the enforcer becoming a second truth. Here the truth is the plan.

**Two normalisations are applied before comparing an annotation, and both are declared.** The plan
quotes forward references (`rec: "DocRecord"`) and this module does not, since `from __future__
import annotations` already makes every annotation lazy; and 07:63 prints
`ContextManager["Snapshot"]`, whose `typing` spelling has been a deprecated alias since 3.9 and is
rejected outright by ruff UP035, so the shipped signature says `AbstractContextManager`. Both are
spelling changes over the same type. Nothing else is normalised -- in particular no name is
substituted for another, so `Sequence` against `Iterable` or `frozenset` against `set` would fail.

Specified in 07-store-and-retrieval.md section 1.1, 03-document-model.md section 2.10,
06-structure-extraction.md section 1.7 and 16-roadmap.md section 5 (W2.3).
"""

from __future__ import annotations

import ast
import builtins
import dataclasses
import inspect
import typing
from pathlib import Path
from typing import Protocol

import omniweave_core.store as store_module
import pytest
from omniweave_core.model.enums import Layer
from omniweave_core.store import (
    ChannelInput,
    ChannelSpec,
    Coverage,
    DocSink,
    Expand,
    Filters,
    GraphSink,
    IndexCaps,
    Narrowing,
    Reader,
    Snapshot,
    Store,
)

# The `plan` and `interpreter` parameters below are left UNANNOTATED, which is this suite's house
# style (`test_catalog.py`, `test_ci_workflows.py`) and here is also a requirement rather than a
# preference. `PlanDocs` and `Interpreter` live in `tests/conftest.py`, and naming them would mean
# `from tests.conftest import ...` -- an import of a top-level `tests` package that maps to no
# installed distribution, which `tools/gate_licences.py`'s import-graph surface denies under DR18
# even inside an `if TYPE_CHECKING:` block. `ANN` is off under `**/tests/**` (pyproject.toml).

STORE_PACKAGE = Path(inspect.getfile(Store)).parent
STORE_INIT = STORE_PACKAGE / "__init__.py"
STORE_TYPES = STORE_PACKAGE / "types.py"

# The document that DEFINES each protocol, per 07:66-67's own delegation: "DocSink (11 methods)
# writes L2 and is specified in 03-document-model.md. GraphSink (12 methods) writes L3 and is
# specified in 06-structure-extraction.md."
PROTOCOL_HOME: dict[str, str] = {
    "Store": "07-store-and-retrieval.md",
    "Reader": "07-store-and-retrieval.md",
    "DocSink": "03-document-model.md",
    "GraphSink": "06-structure-extraction.md",
}

PROTOCOLS: dict[str, type] = {
    "Store": Store,
    "Reader": Reader,
    "DocSink": DocSink,
    "GraphSink": GraphSink,
}

# 07:49-52 and 02:702's arithmetic. The only literals in this file that are not read off the plan
# are these four, and `test_the_counts_this_file_asserts_are_the_plans_own_numbers` reads them back
# out of the documents so they cannot drift either.
PRICED_METHOD_COUNT: dict[str, int] = {"Store": 4, "Reader": 6, "DocSink": 11, "GraphSink": 12}

# The nine LAZY names, verbatim from 11-repo-layout.md section 1.3. Kept in step with
# `tests/unit/test_core_eager_surface.py`'s `LAZY`, which is G17's primary assertion; this file
# repeats it because filling `store/` with imports is exactly the change that could break it.
LAZY = (
    "model",
    "store",
    "archive",
    "retrieve",
    "answer",
    "out",
    "host",
    "toolchain",
    "modelserver",
)

# The types these 33 signatures name that have no module in the tree yet, each with the plan
# section that homes it. This set is the counterpart of `store/__init__.py`'s file-level
# `ruff` F821 suppression: that suppression removes ruff's check, and pinning the set here is
# what replaces it. A typo in an annotation shows up as a new member; a type that later lands
# shows up as a stale one. Either way someone has to come back here and say which.
EXPECTED_UNRESOLVED: frozenset[str] = frozenset(
    {
        # 07:56-58 -- the queue's two, and BOTH are gone from this set now. `WorkRow` left with
        # P4 W4.1 (02-architecture.md:246) and `StepResult` with `omniweave_core.operator`
        # (08-runtime.md:177, 18-api-sketch.md:844), which is what a row leaving here is supposed
        # to look like: the home lands, `store/__init__.py` imports the name, and the boundary
        # declaration stops quoting the type it returns. `Store.complete()` is the one signature
        # both appear in, so it now resolves end to end.
        # 07:1225, :2251 -- the query path's, sent there by 07:3348. P6.
        "ChannelResult",
        "Hit",
        # 03:404, :415, :426, :1800, :1880 -- `omniweave_core.model`'s, still owed by W2.1.
        "DocRecord",
        "PageRecord",
        "AssetDraft",
        "Diag",
        "Grid",
        # 06:337-384 -- `omniweave_core/store/graph.py`'s, which 06:381-384 names as their home.
        "SegmentRef",
        "PassIdentity",
        "RunId",
        "RunStatus",
        "RunReport",
        "EntityDraft",
        "EntityId",
        "AliasDraft",
        "MentionDraft",
        "MentionId",
        "EdgeDraft",
        "EdgeId",
        "ClaimDraft",
        "ClaimId",
        "AnchorDraft",
        "XrefDraft",
        # 05-ingest-and-routing.md:2370 -- the physical spend vector. P4.
        "Spend",
    }
)


# ---------------------------------------------------------------------------
# Reading the plan's own printed classes
# ---------------------------------------------------------------------------


def _printed_class(plan, document: str, name: str) -> ast.ClassDef:
    """The plan's own `class <name>` node, parsed out of a ```python fence in `document`.

    Every fence in the document is parsed rather than the one that happens to match a regex,
    because a fence boundary is a claim: 07 prints `Store` in section 1.1 and 08 prints a WIDER
    variant in its section 9.2, and a scan that did not scope by document would silently pick
    whichever came last.
    """
    plan.require()
    found: ast.ClassDef | None = None
    for body in plan.fences(document, "python"):
        if f"class {name}(" not in body and f"class {name}:" not in body:
            continue
        for node in ast.parse(body).body:
            if isinstance(node, ast.ClassDef) and node.name == name:
                assert found is None, f"_plan/{document} prints class {name} more than once"
                found = node
    assert found is not None, f"_plan/{document} prints no class {name}"
    return found


def _printed_methods(node: ast.ClassDef) -> tuple[ast.FunctionDef, ...]:
    return tuple(child for child in node.body if isinstance(child, ast.FunctionDef))


def _printed_fields(node: ast.ClassDef) -> tuple[str, ...]:
    return tuple(
        child.target.id
        for child in node.body
        if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
    )


def _declared_methods(cls: type) -> tuple[tuple[str, typing.Any], ...]:
    """The Protocol's own methods, in definition order, off the class body.

    `vars(cls)` and not `dir(cls)`: `dir` walks `Protocol`'s own machinery, and the question this
    file asks -- how many methods does the boundary have -- is a question about the class body.

    Dunders are dropped because `typing.Protocol` injects one: subclassing it binds
    `_no_init_or_replace_init` as `__init__`, so an unfiltered `vars()` prices every one of the
    four at one method more than the plan does. No public method on any of the four begins with an
    underscore, and none may -- a private method on a distribution boundary is a contradiction in
    terms.
    """
    return tuple(
        (name, member)
        for name, member in vars(cls).items()
        if inspect.isfunction(member) and not name.startswith("_")
    )


# ---------------------------------------------------------------------------
# Annotation normalisation -- the two declared spellings, and nothing else
# ---------------------------------------------------------------------------


class _Unquote(ast.NodeTransformer):
    """Replace a string-literal forward reference with the expression it spells.

    `rec: "DocRecord"` and `rec: DocRecord` are the same annotation under PEP 563, and the plan
    uses the quoted form because the document that prints the signature is not the document that
    defines the type.
    """

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # ast's own method name.
        if isinstance(node.value, str):
            return self.visit(ast.parse(node.value, mode="eval").body)
        return node


class _RenameDeprecatedAliases(ast.NodeTransformer):
    """`typing.ContextManager` -> `contextlib.AbstractContextManager`.

    The one substitution this file permits, declared in the module docstring: the two spell the
    same protocol, the `typing` name has been a deprecated alias since 3.9, and ruff UP035 rejects
    importing it at all.
    """

    def visit_Name(self, node: ast.Name) -> ast.AST:  # ast's own method name.
        if node.id == "ContextManager":
            return ast.Name(id="AbstractContextManager", ctx=node.ctx)
        return node


def _normalise(annotation: str | ast.expr | None) -> str | None:
    if annotation is None:
        return None
    tree = ast.parse(annotation, mode="eval") if isinstance(annotation, str) else annotation
    tree = ast.fix_missing_locations(_Unquote().visit(ast.Expression(body=tree)))
    tree = ast.fix_missing_locations(_RenameDeprecatedAliases().visit(tree))
    return ast.unparse(tree)


@dataclasses.dataclass(frozen=True, slots=True)
class _Shape:
    """One method reduced to everything a caller can observe about how it is called."""

    positional: tuple[tuple[str, str | None, str | None], ...]
    keyword_only: tuple[tuple[str, str | None, str | None], ...]
    var_keyword: tuple[str, str | None] | None
    returns: str | None


def _shape_from_plan(node: ast.FunctionDef) -> _Shape:
    args = node.args
    assert args.posonlyargs == [], f"{node.name}: the plan prints no positional-only parameters"
    assert args.vararg is None, f"{node.name}: the plan prints no *args"
    padding: list[ast.expr | None] = [None] * (len(args.args) - len(args.defaults))
    positional = tuple(
        (arg.arg, _normalise(arg.annotation), _normalise(default))
        for arg, default in zip(args.args, [*padding, *args.defaults], strict=True)
    )
    keyword_only = tuple(
        (arg.arg, _normalise(arg.annotation), _normalise(default))
        for arg, default in zip(args.kwonlyargs, args.kw_defaults, strict=True)
    )
    var_keyword = (
        None if args.kwarg is None else (args.kwarg.arg, _normalise(args.kwarg.annotation))
    )
    return _Shape(
        positional=positional,
        keyword_only=keyword_only,
        var_keyword=var_keyword,
        returns=_normalise(node.returns),
    )


def _shape_from_code(member: typing.Any) -> _Shape:
    signature = inspect.signature(member)
    positional: list[tuple[str, str | None, str | None]] = []
    keyword_only: list[tuple[str, str | None, str | None]] = []
    var_keyword: tuple[str, str | None] | None = None
    for parameter in signature.parameters.values():
        annotation = (
            None if parameter.annotation is inspect.Parameter.empty else parameter.annotation
        )
        default = None if parameter.default is inspect.Parameter.empty else repr(parameter.default)
        entry = (parameter.name, _normalise(annotation), default)
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            keyword_only.append(entry)
        elif parameter.kind is inspect.Parameter.VAR_KEYWORD:
            var_keyword = (parameter.name, _normalise(annotation))
        else:
            assert parameter.kind is inspect.Parameter.POSITIONAL_OR_KEYWORD, (
                f"{member.__qualname__}: unexpected parameter kind {parameter.kind}"
            )
            positional.append(entry)
    returns = (
        None
        if signature.return_annotation is inspect.Signature.empty
        else _normalise(signature.return_annotation)
    )
    return _Shape(
        positional=tuple(positional),
        keyword_only=tuple(keyword_only),
        var_keyword=var_keyword,
        returns=returns,
    )


# ---------------------------------------------------------------------------
# The 33
# ---------------------------------------------------------------------------


def test_the_four_protocols_declare_exactly_thirty_three_methods() -> None:
    """07:49-52 and 02:702: "33 methods, not four". Counted, not transcribed."""
    total = sum(len(_declared_methods(cls)) for cls in PROTOCOLS.values())
    per_protocol = {name: len(_declared_methods(cls)) for name, cls in PROTOCOLS.items()}
    assert total == 33, f"the boundary is priced at 33 methods; found {total}: {per_protocol}"


@pytest.mark.parametrize("protocol", sorted(PROTOCOLS))
def test_each_protocol_declares_the_method_count_the_plan_prices_it_at(protocol: str) -> None:
    """A twelfth `DocSink` method is an ADR, not a patch (03:568-572)."""
    declared = [name for name, _ in _declared_methods(PROTOCOLS[protocol])]
    assert len(declared) == PRICED_METHOD_COUNT[protocol], (
        f"{protocol} is priced at {PRICED_METHOD_COUNT[protocol]} methods "
        f"(07:49-52, 02:702) but declares {len(declared)}: {declared}"
    )


def test_the_counts_this_file_asserts_are_the_plans_own_numbers(plan) -> None:
    """`PRICED_METHOD_COUNT` is read back out of the plan, so it cannot drift silently.

    Without this, the four literals above are a second transcription of the boundary's price and
    an agreement between them and the code would prove only self-agreement. 07:52 and 02:702 both
    print the arithmetic in prose; 03:542 prints it a third time as a parenthesised list.
    """
    plan.require()
    priced = "(`Store` 4, `Reader` 6, `DocSink` 11, `GraphSink` 12)"
    assert priced in plan.text("03-document-model.md"), (
        f"03-document-model.md no longer prints {priced}; the boundary has been repriced"
    )
    assert "33 methods, not four" in plan.text("02-architecture.md")
    assert "33 methods in total" in plan.text("07-store-and-retrieval.md")
    assert sum(PRICED_METHOD_COUNT.values()) == 33


@pytest.mark.parametrize("protocol", sorted(PROTOCOLS))
def test_the_method_names_are_the_plans_own_in_the_plans_own_order(protocol: str, plan) -> None:
    """Order matters as much as membership: 07:63-68's `Reader` is the order `--explain` prints."""
    printed = _printed_class(plan, PROTOCOL_HOME[protocol], protocol)
    expected = [node.name for node in _printed_methods(printed)]
    declared = [name for name, _ in _declared_methods(PROTOCOLS[protocol])]
    assert declared == expected


@pytest.mark.parametrize("protocol", sorted(PROTOCOLS))
def test_every_signature_is_the_plans_printed_signature(protocol: str, plan) -> None:
    """Parameter names, annotations, defaults, keyword-only markers and the return type.

    The count being right is not the same as the boundary being right: a `complete()` that grew a
    `deps` keyword would still count as one of four. See the defect note on `Store` in
    `store/__init__.py` -- 08-runtime.md:2478-2485 prints exactly that wider variant.
    """
    printed = _printed_class(plan, PROTOCOL_HOME[protocol], protocol)
    expected = {node.name: _shape_from_plan(node) for node in _printed_methods(printed)}
    for name, member in _declared_methods(PROTOCOLS[protocol]):
        assert name in expected, f"{protocol}.{name} is not a method _plan/ prints at all"
        assert _shape_from_code(member) == expected[name], f"{protocol}.{name}"


def test_the_two_keyword_only_markers_are_where_the_plan_puts_them() -> None:
    """`DocSink.add_rel` and `GraphSink.cover` are the only two, at 03:558 and 06:371.

    A `*` in a signature is a compatibility decision, not a formatting one: `add_rel`'s `trust` is
    keyword-only because the sink CLAMPS it (03:586) and a positional trust beside a positional
    `kind` is the one confusion that would silently write the wrong trust tier.
    """
    keyword_only: dict[str, tuple[str, ...]] = {}
    for protocol, cls in PROTOCOLS.items():
        for name, member in _declared_methods(cls):
            names = tuple(
                parameter.name
                for parameter in inspect.signature(member).parameters.values()
                if parameter.kind is inspect.Parameter.KEYWORD_ONLY
            )
            if names:
                keyword_only[f"{protocol}.{name}"] = names
    assert keyword_only == {
        "DocSink.add_rel": ("trust", "score", "score_kind"),
        "GraphSink.cover": ("empty_reason",),
    }


def test_none_of_the_four_is_an_abc_and_all_four_are_protocols() -> None:
    """18-api-sketch.md:1779 states the house rule verbatim: "NOT an ABC: a Protocol"."""
    for name, cls in PROTOCOLS.items():
        assert Protocol in cls.__bases__, f"{name} is not a Protocol"
        assert getattr(cls, "_is_protocol", False) is True, f"{name} lost its protocol marker"


def test_none_of_the_four_protocols_is_runtime_checkable() -> None:
    """`@runtime_checkable` appears at exactly two sites in the plan, and neither is here.

    04-driver-system.md:108 and 18-api-sketch.md:1780 are both `DriverBase`, where `activate()`
    really does `isinstance`-check a class loaded from an entry point. `isinstance` against a
    runtime-checkable Protocol tests only that the ATTRIBUTES exist, never their signatures, so a
    checkable `Store` would accept any object with four callables of any shape -- which is the
    exact property `test_every_signature_is_the_plans_printed_signature` exists to police.
    """
    for name, cls in PROTOCOLS.items():
        assert getattr(cls, "_is_runtime_protocol", False) is False, (
            f"{name} became runtime_checkable; isinstance would then pass on shape alone"
        )
        with pytest.raises(TypeError):
            isinstance(object(), cls)


# ---------------------------------------------------------------------------
# Snapshot -- 07 section 10.4
# ---------------------------------------------------------------------------


def test_snapshot_token_is_annotated_object_and_nothing_narrower() -> None:
    """07:72-78. Read off `__annotations__`, because the annotation is the whole invariant.

    "Typing that field `sqlite3.Connection` would make T3 unrepresentable in the type system --
    which is the premise the whole scale-out section rests on" (07:77-78). 02:702 says the same
    from the other side: "an opaque backend-owned `token: object`, never a `sqlite3.Connection`,
    so INV-17 holds by construction in a backend that has no SQLite at all".
    """
    assert Snapshot.__annotations__["token"] == "object"  # noqa: S105 -- a FIELD name.


def test_no_annotation_in_the_store_package_names_a_sqlite_type() -> None:
    """The `sqlite3.Connection` that 07:74 says lives in `token` must not reach the TYPE.

    Broader than the field, on purpose: a `Reader` or `Store` method that grew a
    `sqlite3.Cursor` parameter would breach the same premise and would not be caught by reading
    `Snapshot.token` alone.
    """
    annotations: list[str] = [
        text for text in Snapshot.__annotations__.values() if isinstance(text, str)
    ]
    for cls in PROTOCOLS.values():
        for _, member in _declared_methods(cls):
            signature = inspect.signature(member)
            annotations.extend(
                str(parameter.annotation)
                for parameter in signature.parameters.values()
                if parameter.annotation is not inspect.Parameter.empty
            )
            if signature.return_annotation is not inspect.Signature.empty:
                annotations.append(str(signature.return_annotation))
    offenders = [text for text in annotations if "sqlite" in text.lower()]
    assert offenders == []


def test_snapshot_is_frozen_and_slotted(plan) -> None:
    """07:2765-2766 prints `@dataclass(frozen=True, slots=True)`, and both halves are asserted.

    Frozen: gate 3 compares `index_state.generation` read at plan time against the value read
    after the snapshot closes (07:2795-2799), which a rebindable `generation` would defeat.
    Slotted: this is the one object every Channel, the hydration and the coverage scan all carry,
    so a `__dict__` is per-query allocation for nothing.
    """
    plan.require()
    assert "@dataclass(frozen=True, slots=True)\nclass Snapshot:" in plan.text(
        "07-store-and-retrieval.md"
    )
    snapshot = Snapshot(
        token=object(), generation=7, corpus_id="c", schema=1, vec_attached=False, opened_ns=0
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.generation = 8  # type: ignore[misc]
    assert not hasattr(snapshot, "__dict__")
    assert Snapshot.__slots__ == tuple(f.name for f in dataclasses.fields(Snapshot))


def test_snapshot_carries_the_six_fields_the_plan_prints_in_that_order() -> None:
    """07:2767-2769, field for field."""
    assert [f.name for f in dataclasses.fields(Snapshot)] == [
        "token",
        "generation",
        "corpus_id",
        "schema",
        "vec_attached",
        "opened_ns",
    ]


# ---------------------------------------------------------------------------
# INV-17 -- the absence of sqlite3 from a file that is allowed to have it
# ---------------------------------------------------------------------------


def test_neither_module_of_the_boundary_mentions_sqlite3_in_its_source() -> None:
    """The declaration is backend-agnostic BY CONSTRUCTION, not by review (07:72-78).

    ruff's TID251 per-file-ignore covers `store/*.py`, so these two files are among the five
    places in the repository where `import sqlite3` is legal. The point of the assertion is that
    the absence is a decision: `sqlite.py` is the only module that connects (ST1, 07:2721).
    """
    for path in (STORE_INIT, STORE_TYPES):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        assert [name for name in imported if name.split(".")[0] == "sqlite3"] == [], (
            f"{path.name} imports sqlite3; ST1 puts the only connect in store/sqlite.py"
        )


def test_importing_the_store_package_loads_no_sqlite3_module(interpreter) -> None:
    """Measured from a fresh interpreter, the way `test_core_eager_surface.py` measures G17.

    The source check above is necessary and not sufficient: `sqlite3` could arrive through
    anything this package imports. Once a pytest process has imported half the tree for its own
    reasons `sys.modules` can no longer answer the question, so a subprocess is not an
    optimisation here but the only witness. The `interpreter` fixture owns the subprocess and its
    `# noqa: TID251`, which is why this file needs neither.
    """
    added = interpreter.modules_added_by("import omniweave_core.store")
    assert "sqlite3" not in added
    assert not [name for name in added if name.startswith("sqlite3")]


def test_a_bare_import_of_omniweave_core_still_loads_none_of_the_nine_lazy_names(
    interpreter,
) -> None:
    """G17, re-asserted here because filling `store/` is the change that could break it.

    `tests/unit/test_core_eager_surface.py` is the primary home of this assertion. It is repeated
    rather than weakened: 11-repo-layout.md section 1.3 makes the nine names "a STRUCTURAL
    property, not a convention", and the property holds because `omniweave_core/__init__.py`
    imports none of them and exposes them through `__getattr__` -- not because they are empty.
    """
    loaded = interpreter.modules_after("import omniweave_core")
    eager = sorted(name for name in LAZY if f"omniweave_core.{name}" in loaded)
    assert eager == []


def test_the_store_package_pulls_in_nothing_outside_the_standard_library(interpreter) -> None:
    """INV-2 / G1: `omniweave-core` has zero third-party runtime dependencies.

    Measured as a difference against a bare interpreter so an editable-install finder or a `.pth`
    hook cancels out rather than reading as a dependency -- `test_core_eager_surface.py`'s D1 test
    records the reasoning.
    """
    added = interpreter.modules_added_by("import omniweave_core.store")
    third_party = sorted(
        name
        for name in added
        if not name.startswith("_")
        and name.split(".")[0] not in __import__("sys").stdlib_module_names
        and not name.startswith(("omniweave_core", "omniweave_ports"))
    )
    assert third_party == []


# ---------------------------------------------------------------------------
# The forward references, pinned
# ---------------------------------------------------------------------------


def _annotation_names(text: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(text, mode="eval")):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found |= _annotation_names(node.value)
    return found


def test_the_unresolved_forward_references_are_exactly_the_expected_set() -> None:
    """What `# ruff: noqa: F821` in `store/__init__.py` gives up, this test takes back.

    Twenty-six of the names in these 33 signatures have no module in the tree yet, and the file
    suppresses F821 for that reason. A blanket suppression would also hide a typo, so the set is
    pinned: a misspelling arrives as a new member, and a type that lands in its real home arrives
    as a stale one. `EXPECTED_UNRESOLVED` carries the plan section that homes each name, so
    removing a row means naming the file that now holds it.
    """
    namespace = vars(store_module)
    unresolved: set[str] = set()
    for cls in PROTOCOLS.values():
        for _, member in _declared_methods(cls):
            signature = inspect.signature(member)
            texts = [
                parameter.annotation
                for parameter in signature.parameters.values()
                if parameter.annotation is not inspect.Parameter.empty
            ]
            if signature.return_annotation is not inspect.Signature.empty:
                texts.append(signature.return_annotation)
            for text in texts:
                unresolved |= {
                    name
                    for name in _annotation_names(text)
                    if name not in namespace and not hasattr(builtins, name)
                }
    assert unresolved == EXPECTED_UNRESOLVED


def test_every_other_name_in_the_signatures_really_does_resolve() -> None:
    """The complement of the test above, so the pin cannot pass by resolving nothing.

    `BlockId`, `BlockDraft`, `Mark`, `Cite`, `RelKind` and `Trust` are `omniweave_core.model`'s and
    are imported, not quoted; `Snapshot`, `IndexCaps`, `Filters`, `Narrowing`, `ChannelSpec` and
    `Coverage` are this package's own.
    """
    for name in ("BlockId", "BlockDraft", "Mark", "Cite", "RelKind", "Trust"):
        assert hasattr(store_module, name), f"{name} is imported by the docstring's own table"


# ---------------------------------------------------------------------------
# The boundary value types -- 07 sections 6.1, 6.3, 10.4 and 16
# ---------------------------------------------------------------------------

VALUE_TYPES: dict[str, type] = {
    "Snapshot": Snapshot,
    "Filters": Filters,
    "IndexCaps": IndexCaps,
    "Expand": Expand,
    "ChannelInput": ChannelInput,
    "ChannelSpec": ChannelSpec,
    "Coverage": Coverage,
}

VALUE_TYPE_HOME: dict[str, str] = dict.fromkeys(VALUE_TYPES, "07-store-and-retrieval.md")

# Fields a build ADDED to a printed shape, each with the phase that added it and the reason.
# A shape cannot gain a field by accident, only by someone adding a row here and saying why --
# the same discipline `test_core_eager_surface.py`'s `FILLED_HOMES` uses for the same purpose.
# Every entry is asserted to be a SUFFIX below, so the printed fields keep the printed order.
ADDED_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "ChannelInput": (
        (
            "seeds",
            "P6 W6.2c (D246) -- 07:1327-1332 seeds `structural` from the `identity` and `exact` "
            "ranked sets, choosing among them is 07:1333's runtime step and therefore "
            "`retrieve()`'s, and `Reader.channel(s, spec, n)` is frozen, so the chosen seed has "
            "no other carrier across the boundary",
        ),
        (
            "filters",
            'P6 W6.4 (D262) -- 07:1671 post-filters above `PREFILTER_MAX`, a `kind="all"` '
            "`Narrowing` carries a proof and no predicate, and the same frozen signature leaves "
            "the Channel nothing to post-filter with; without it the filter is silently dropped "
            "on every corpus above 200,000 narrowed blocks",
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(VALUE_TYPES))
def test_every_boundary_value_type_is_frozen_and_slotted(name: str) -> None:
    """The plan decorates all seven `@dataclass(frozen=True, slots=True)`.

    Asserted over the set rather than per class, the way `test_model_block.py` does it, so a type
    cannot arrive mutable by omission.
    """
    cls = VALUE_TYPES[name]
    assert dataclasses.is_dataclass(cls)
    assert cls.__dataclass_params__.frozen is True, f"{name} is not frozen"
    assert "__slots__" in vars(cls), f"{name} is not slotted"


@pytest.mark.parametrize("name", sorted(VALUE_TYPES))
def test_every_boundary_value_type_has_the_plans_fields_in_the_plans_order(name: str, plan) -> None:
    """Field ORDER is load-bearing for at least one of them, so it is asserted for all seven.

    `IndexCaps.caps_digest` is "sha256_canonical of every field above; memoises plan()" (07:3280),
    which makes this shape's field order an input to a cache key.

    A shape may carry MORE fields than the plan prints, and only through `ADDED_FIELDS`: the
    printed names must still come first, in the printed order, and the additions must be exactly
    the rows that table names for this shape. So an addition is visible in a diff of that table
    and nowhere else, and a REMOVED field is still a failure.
    """
    printed = _printed_class(plan, VALUE_TYPE_HOME[name], name)
    added = tuple(field for field, _why in ADDED_FIELDS.get(name, ()))
    assert [f.name for f in dataclasses.fields(VALUE_TYPES[name])] == [
        *_printed_fields(printed),
        *added,
    ]


def test_every_added_field_names_a_field_the_shape_really_has() -> None:
    """Without this, `ADDED_FIELDS` is a way to switch the parity test off.

    A row with no field behind it would exempt a name from the printed-fields comparison while
    proving nothing, and a row left behind after a revert would go unnoticed. Read the other way,
    it also stops a row being added for a shape that is not under test at all.
    """
    for name, rows in ADDED_FIELDS.items():
        assert name in VALUE_TYPES, f"{name} is not a boundary value type"
        shipped = {f.name for f in dataclasses.fields(VALUE_TYPES[name])}
        for field, why in rows:
            assert field in shipped, f"{name}.{field} is listed as added but does not exist"
            assert len(why) > 40, f"{name}.{field} is added with no stated reason"


def test_narrowing_is_a_named_tuple_with_the_plans_three_fields(plan) -> None:
    """07:1579 prints `class Narrowing(NamedTuple)`, not a dataclass, and the tag is field zero."""
    printed = _printed_class(plan, "07-store-and-retrieval.md", "Narrowing")
    assert _printed_fields(printed) == ("kind", "table", "n")
    assert Narrowing._fields == ("kind", "table", "n")
    assert issubclass(Narrowing, tuple)


def test_narrowing_carries_no_information_in_its_truth_value() -> None:
    """ST5: "no restriction" is not "restrict to nothing", so `if narrowing:` must be useless.

    07:1670-1680 prices the failure it prevents. In jcodemunch's `build_structural_channel`
    (`signal_fusion.py:203-224`) `candidate_ids` was falsy-checked, so a query matching nothing
    produced an empty candidate set that SKIPPED the filter and returned the whole repository
    ranked by centrality, labelled "Confident matches returned". This asserts the shape that makes
    the same mistake impossible to write here: the two opposite outcomes are indistinguishable by
    truth-testing the value, so the tag has to be read.
    """
    everything = Narrowing(kind="all", table=None, n=0)
    nothing = Narrowing(kind="empty", table=None, n=0)
    assert bool(everything) == bool(nothing)
    assert everything != nothing
    assert everything.kind != nothing.kind


def test_filters_defaults_are_the_plans_own_and_empty_means_no_restriction() -> None:
    """07:1565-1577's defaults, and ST5 (07:1637-1640) for the two deny fields.

    `deny_methods` is `frozenset[Method]` and NOT `frozenset[Method] | None` "because there is no
    third state to represent; `deny_methods=frozenset()` and the field's absence are the same
    query". `layers` defaulting to BODY alone is the one default here that changes what a query
    returns -- furniture is excluded unless asked for.
    """
    filters = Filters()
    assert filters.layers == frozenset({Layer.BODY})
    assert filters.deny_methods == frozenset()
    assert filters.deny_restriction_bits == 0
    assert filters.gen == "head"
    assert filters.doc_keys is None
    assert Filters(deny_methods=frozenset()) == filters


def test_expand_requires_its_relation_set_and_defaults_the_four_ceilings() -> None:
    """07:1344: "REQUIRED, no default. NEVER 'all relations'".

    07:1360-1362 is the reason: "all relations" on a document graph reaches every block in the
    corpus within three hops, and a relation absent from `relation_vocab` is a usage error naming
    the vocabulary, "because silently traversing nothing is indistinguishable from a corpus with
    no links".
    """
    with pytest.raises(TypeError):
        Expand()  # type: ignore[call-arg]
    expand = Expand(relations=frozenset({"note_ref"}))
    assert (expand.max_hops, expand.beam, expand.max_visited, expand.hub_cap) == (2, 64, 4096, 4096)


def test_channel_spec_distinguishes_an_unset_weight_from_a_zero_weight() -> None:
    """07:3298 and 07:1232: "explicit (0.0 included) wins", and "0.0 IS A VALUE".

    A plain `float` defaulting to `0.0` would make a Channel deliberately weighted out
    indistinguishable from one nobody configured, which is why the field is `float | None`.
    """
    unset = ChannelSpec(name="lexical", budget_ms=50, limit=64, overfetch=1, weight=None, params={})
    zeroed = ChannelSpec(name="lexical", budget_ms=50, limit=64, overfetch=1, weight=0.0, params={})
    assert unset.weight is None
    assert zeroed.weight == 0.0
    assert unset != zeroed
    assert unset.bind is None, "a ChannelSpec in a QueryPlan carries no query material (07:3300)"


def test_channel_input_defaults_to_carrying_no_query_embedding() -> None:
    """ST22: `q_sig` and `q_full` come from phase 2 and are never computed inside the snapshot.

    07:3288 and 07's Extends-the-charter row 6. The default being `None` is what lets a
    `ChannelInput` exist before phase 2 has run.
    """
    bound = ChannelInput()
    assert (bound.q_sig, bound.q_full, bound.expand) == (None, None, None)
    assert bound.terms == ()


def test_coverage_can_report_that_coverage_is_unknown() -> None:
    """07:3335: `scope_rows == 0` means NO `ingest_scope` row in view, which is gate 4 firing.

    18-api-sketch.md:466-469 repeats the warning on the public handle: "that is gate 4 firing, not
    a clean bill of health". The assertion is that `complete` and `scope_rows` are independent
    fields, so "nothing is missing" and "we cannot tell what is missing" are different values
    rather than the same one.
    """
    unknown = Coverage(
        discovered=0,
        indexed=0,
        partial=0,
        failed=0,
        skipped=0,
        complete=True,
        scope_rows=0,
        pending_work=0,
        stale_units=0,
        unreadable_units=0,
        gaps=(),
    )
    assert unknown.scope_rows == 0
    assert unknown.complete is True


# ---------------------------------------------------------------------------
# The re-export surface, and the defect this module records
# ---------------------------------------------------------------------------


def test_the_reexport_surface_is_the_four_protocols_the_backend_and_the_value_types() -> None:
    """A flat surface, like `omniweave_core.model`'s (02-architecture.md:248).

    A caller writes `from omniweave_core.store import Reader`, never
    `... .store.types import Reader`, so `types.py` being a separate module is an implementation
    detail of this package and not part of the boundary.

    `VectorBackend` is here and is NOT one of the four: 07:86-92 calls it *"a fifth boundary
    type ... deliberately not one of the four Protocols"*, because "seam" is the charter's word
    for the four numbered process/FFI boundaries and a Backend crosses none of them. It is in
    `__all__` because 07:3132 puts it in `T-CONTRACT` beside the four, and it is absent from
    `PROTOCOLS` above because the 33-method price counts four.

    `NO_JOB_DOCS` is the one name here that is not a type. 07:750 puts the predicate in
    `omniweave_core.store` and nowhere else, and the six sites 07:759-766 lists reach it from four
    subpackages -- so a flat surface is what the plan asked for, and a `predicates.py` would be the
    second home the constant exists to prevent. It sorts between `IndexCaps` and `Narrowing`
    because `sorted()` compares codepoints and `O` precedes `a`; the order is the sort's, not a
    curated one.
    """
    assert sorted(store_module.__all__) == [
        "ChannelInput",
        "ChannelSpec",
        "Coverage",
        "DocSink",
        "Expand",
        "Filters",
        "GraphSink",
        "IndexCaps",
        "NO_JOB_DOCS",
        "Narrowing",
        "Reader",
        "Snapshot",
        "Store",
        "VecManifest",
        "VectorBackend",
    ]
    for name in store_module.__all__:
        assert hasattr(store_module, name), f"{name} is exported but not bound"


def test_the_plan_still_prints_a_second_wider_store_and_this_module_records_it(plan) -> None:
    """The `Store` divergence is a live plan defect, and the ruling must stay visible.

    Two definition sites carry the four-parameter `claim` and three-parameter `complete`
    transcribed here -- 07:56-60 and `_notes/charter.md`:3393-3397. One carries a wider form,
    08-runtime.md:2478-2485, with a leading `cost_class` on `claim` and keyword-only `deps` and
    `rows` on `complete`. Definition sites, not mentions: two against one, and the charter is law.

    This test fails in both directions on purpose. If 08 is corrected, it fails and the defect note
    in `store/__init__.py` should come out. If someone widens `Store` to 08's shape, the signature
    test fails instead. What must not happen is the disagreement being quietly forgotten.
    """
    plan.require()
    runtime = plan.text("08-runtime.md")
    assert "def claim(self, cost_class: CostClass, batch: int, gen: int," in runtime, (
        "08-runtime.md no longer prints the wider claim(); re-check the ruling in store/__init__.py"
    )
    recorded = STORE_INIT.read_text(encoding="utf-8")
    assert "DEFECT -- `Store` is printed twice, and the two prints disagree." in recorded
