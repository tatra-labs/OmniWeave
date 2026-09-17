"""P6's exit criterion: no `= ...` default in a shipped shape.

16-roadmap.md:694 names this script by path -- `uv run tools/gate_no_ellipsis_default.py  # no
`= ...` in a shipped shape` -- and 16:674 makes the property part of P6's FREEZE, in bold:
*"**No field in any of these types defaults to `...`**: a default is a real value or the field
is required, and there is no third option."* A freeze rule has to hold before the freeze, which is
why this gate lands with the phase rather than after it.

## What the ban actually is

07:1239 states the mechanism rather than the taste: *"`x = ...` is legal Python that binds
`Ellipsis`, so the field is neither required nor defaulted and every consumer type-checks against
`EllipsisType`."* 18:57 says the same of the API surface and charter.md:3498 shouts it. The failure
is specific and silent: a reader sees `x = ...` and reads "to be filled in"; the type checker sees
a field whose default is an object of type `ellipsis`; a `dataclasses.asdict` sees a value it will
happily serialise; and a JSON encoder raises at the first row that used the default. None of those
is the author's intent, and the language offers no way to say the intended thing badly -- so the
ban costs nothing, which is what makes it a gate rather than a review note.

## Three shapes are checked and one idiom is not

CHECKED, all in `packages/*/src/**/*.py`:

1. an ANNOTATED class-level field, `x: int = ...` -- the dataclass, `NamedTuple` and `TypedDict`
   case, and the one 16:674 names;
2. a BARE class-level assignment, `x = ...` -- the same defect one annotation short, and the form
   charter.md:3498's *"ANYWHERE IN A SHIPPED SHAPE"* reaches;
3. a FUNCTION PARAMETER default, `def f(x: int = ...)` -- 18:57's *"There is no `= ...` default
   anywhere"*, and the form that leaks `Ellipsis` into a call the caller thought it had omitted.

NOT CHECKED, and D290 is the entry: a DECLARATION. A function whose whole body is `...` -- a
`Protocol` method, an `@overload`, an abstract stub -- declares a signature and implements nothing,
so `def execute(self, sql: str, parameters: Mapping[str, object] = ..., /) -> Any: ...` binds no
default at any call site. The call goes to the implementation, whose own default is a real value or
absent. The framework already ships three of these, all of them structural stand-ins for
`sqlite3.Connection.execute` written where `import sqlite3` is banned (INV-17): `acquire.py`,
`route/ledger.py` and `run/discover.py`.

**This is a reading, and it is the mechanism's rather than the letter's.** charter.md:3498 says
*"NO `= ...` ANYWHERE IN A SHIPPED SHAPE"* and a `Protocol` is a shipped shape, so the letter
forbids those three. But 07:1239 states the rule through its HARM -- *"the field is neither required
nor defaulted and every consumer type-checks against `EllipsisType`"* -- and that harm needs a
binding, which a declaration never makes. 16-roadmap.md:674's freeze clause is narrower still and
says FIELD. Where a rule's letter and its stated mechanism disagree, this gate takes the mechanism
and D290 records the gap.

A function BODY that is `...` was never in scope either, for a plainer reason: it is an expression
statement and not a default, so walking assignments and parameter defaults excludes it by
construction -- better than an allowlist naming every Protocol in the framework.

`.pyi` files are excluded for the same structural reason: in a stub, `def f(x: int = ...)` is the
CORRECT spelling of "this parameter has a default whose value the stub does not state", and
`packages/omniweave/src/omniweave/sdk/_generated.pyi` is a shipped, generated stub. A rule that
failed there would be asking a stub to state a value it exists not to state.

Exit codes: 0 green, 1 a finding, 2 the checker could not read the tree.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Final, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
"""The repository root. `tools/` is one level down, and this file is never installed."""

SHIPPED: Final[str] = "packages/*/src/**/*.py"
"""The shipped surface: every source file in every distribution, and no test and no tool.

`packages/*/src/**` is the same glob `tools/gate_semgrep.py`'s `LIBRARY` uses, so "shipped" means
one thing in both gates. A test fixture may bind `Ellipsis` deliberately -- proving a refusal needs
a value to refuse -- and a tool is not a shape anyone types against."""

_KINDS: Final[dict[str, str]] = {
    "field": "an annotated class field",
    "assign": "a bare class-level assignment",
    "param": "a function parameter default",
}
"""The three forms, for the report. Keyed by the tag `Finding.kind` carries."""


class Finding(NamedTuple):
    """One `= ...`, with enough to open the file at the line and see the shape it is in."""

    path: str
    line: int
    kind: str
    owner: str

    def render(self) -> str:
        """`path:line  kind  owner` -- the form an editor's jump-to-line accepts."""
        return f"  {self.path}:{self.line}  {_KINDS[self.kind]}  in `{self.owner}`"


def _is_ellipsis(node: ast.expr | None) -> bool:
    """Whether an expression is the literal `...`.

    `ast.Constant` with `value is Ellipsis`, and the identity check is the point: `Ellipsis` is a
    singleton, and `== Ellipsis` would be True for anything whose `__eq__` says so.
    """
    return isinstance(node, ast.Constant) and node.value is Ellipsis


def _class_findings(rel: str, node: ast.ClassDef) -> Iterator[Finding]:
    """Forms 1 and 2: the class body's own statements, not its methods'.

    `node.body` and not `ast.walk`, deliberately: a nested function's parameter defaults belong to
    form 3 and are found by the module-wide pass, and finding them here as well would report one
    defect twice.
    """
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and _is_ellipsis(stmt.value):
            yield Finding(rel, stmt.lineno, "field", node.name)
        elif isinstance(stmt, ast.Assign) and _is_ellipsis(stmt.value):
            yield Finding(rel, stmt.lineno, "assign", node.name)


def _is_declaration(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the function declares a signature and implements nothing.

    True when the body is `...`, optionally preceded by a docstring: a `Protocol` method, an
    `@overload`, an abstract stub. Structural rather than an allowlist of decorators, because the
    property that matters is that no call ever reaches this body, and `@runtime_checkable`,
    `@abstractmethod`, `@overload` and a bare `Protocol` member all share it.
    """
    body = list(node.body)
    head = body[0] if body else None
    if (
        isinstance(head, ast.Expr)
        and isinstance(head.value, ast.Constant)
        and isinstance(head.value.value, str)
    ):
        body = body[1:]
    return len(body) == 1 and isinstance(body[0], ast.Expr) and _is_ellipsis(body[0].value)


def _param_findings(rel: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[Finding]:
    """Form 3: every default in every parameter group, including keyword-only.

    Skipped entirely for a declaration -- see the module docstring and D290.
    """
    if _is_declaration(node):
        return
    defaults = [*node.args.defaults, *node.args.kw_defaults]
    for default in defaults:
        if _is_ellipsis(default):
            yield Finding(rel, getattr(default, "lineno", node.lineno), "param", node.name)


def findings(root: Path | None = None) -> list[Finding]:
    """Every `= ...` in the shipped surface, sorted by path and line."""
    base = REPO_ROOT if root is None else root
    found: list[Finding] = []
    for path in sorted(base.glob(SHIPPED)):
        rel = path.relative_to(base).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                found.extend(_class_findings(rel, node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found.extend(_param_findings(rel, node))
    return sorted(found)


def _say(text: str) -> None:
    """One line to stdout. `print` is banned repo-wide by ruff's T20 and `tools/` has no ignore."""
    sys.stdout.write(text + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    """Report every `= ...` in the shipped surface, and fail on any."""
    del argv
    try:
        found = findings()
    except (OSError, SyntaxError) as error:  # pragma: no cover - a broken tree is not a finding
        _say(f"ELLIPSIS FAIL  the shipped surface did not parse: {error}")
        _say("               fix: this is a syntax error, not a lint -- `uv run ruff check`.")
        return 2

    if found:
        _say(f"ELLIPSIS FAIL  {len(found)} `= ...` default(s) in a shipped shape.")
        for finding in found:
            _say(finding.render())
        _say("               07:1239 -- `x = ...` binds `Ellipsis`, so the field is neither")
        _say("               required nor defaulted and every consumer type-checks against")
        _say("               `EllipsisType`.")
        _say("               fix: give the field a real default, or drop the `= ...` and let it")
        _say("               be required. Those are the only two options.")
        return 1

    scanned = sum(1 for _ in REPO_ROOT.glob(SHIPPED))
    _say(f"ELLIPSIS ok  no `= ...` default in any shipped shape; {scanned} file(s) scanned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
