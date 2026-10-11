"""`ow out constructs`: a target's ConstructTable, found from its card, and its agent document.

**D762.** 09-generation.md section 3.3: *"`ow out constructs pptx --format md` renders the
ConstructTable as agent documentation under a CI-gated ceiling (`agent_doc_tokens_max = 6000` for
`pptx`). The document is generated from the table, so a construct not in the table cannot be
documented and a construct in the table cannot be undocumented."* Its arithmetic, about 33 tokens a
construct, is *"an id, one canonical spelling and one clause"*, and `--group text` *"emits one
group under its own budget"*. Section 3.5 item 5 gates the budget per target, and `OW-T-009`'s fix
is this verb, which *"loads the table and names the row and the key"*.

## Rulings

1. **The table is read beside its card, and no driver code runs.** `[compile] constructs` names a
   file in the card's directory. The normalizers a `normalize` row may name are the top-level
   functions that directory's `normalizers.py` defines, read with `ast`. So `ConstructTable.load()`
   still refuses a row naming a function the target does not ship, and documenting a target imports
   nothing from it, the way `ow out targets` lists a kind without resolving its driver. Whether a
   normalizer is idempotent is the target suite's question.
2. **A table whose digest is not the card's `constructs_digest` is the card's error**,
   `OW_CARD_INVALID`. The compile refuses that pairing, so documenting it would describe a contract
   nothing enforces.
3. **A card that names no table has none to read**, and refuses with `OW-T-514` and its reason.
   That is an unimplemented target such as video, whose table "was never written". D781 narrows
   the refusal from every unimplemented card: docx's table and rules are built before its
   lowering, and `ow out check` gates IL against them while `ow out compile` still refuses.
4. **A group is the id's first dotted segment**: `attr`, `elem`, `style`, as 09's `--group text`
   names one. Groups follow the order the table first uses them, and rows keep table order, which
   is the author's (the mandatory rows first).
5. **One line a row, with one clause chosen by the disposition.** A native row gives its canonical
   spelling and any `forbidden_when` condition. A normalize row names the row to write instead. A
   bake row gives its DPI, and says so when the card cannot bake. A forbidden row gives its message.
   Each line ends with the row's code as the register's numeric: section 3.4's file comment
   resolves it at render time, so an agent holding a finding's code can find the row.
6. **The budget is counted in CI, never here.** `tiktoken` is a dev-only dependency (10:2585), so
   this module renders and `test_out_agentdoc.py` counts `cl100k_base` tokens, the whole document
   and each group's, against the card's `agent_doc_tokens_max`. That key is required of an
   implemented card (D762, `omniweave_core.out.card`).
7. **An unknown group or construct is `OW_CONSTRUCT_UNKNOWN`**, exit 2, naming what the table has:
   `ow explain`'s precedent for a name with no row.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import DriverHostError, NotFoundError, TargetError, load_register
from omniweave_core.out.constructs import ConstructTable, Disposition

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from omniweave_core.out.card import CompileCard
    from omniweave_core.out.constructs import Construct

__all__ = ["NORMALIZERS_FILE", "agent_doc", "group_of", "groups", "load_table", "select"]

NORMALIZERS_FILE: Final = "normalizers.py"
"""09 section 1's ninth file: the pure `str -> str` functions a `normalize` row names."""

_PREAMBLE: Final = (
    "native: write it as shown. normalize: accepted with a warning; write the row it names. "
    "bake: rasterised, so avoid it. forbidden: an error, never fixed for you."
)


def load_table(card_path: Path, card: CompileCard) -> ConstructTable:
    """Rulings 1-3: the table beside `card_path`, held to the card's digest."""
    if not card.constructs:
        raise TargetError(
            f"{card.driver} has no construct table: [compile] implemented = false, because "
            f"{card.reason}",
            symbol="OW_TARGET_NOT_IMPLEMENTED",
            fix="ow out targets",
        )
    here = card_path.parent
    names = _normalizer_names(here / NORMALIZERS_FILE)
    table = ConstructTable.load(here / card.constructs, dict.fromkeys(names, _documented_only))
    if table.digest() != card.constructs_digest:
        raise DriverHostError(
            f"{card_path}: [compile] constructs_digest is {card.constructs_digest}, and "
            f"{card.constructs} digests to {table.digest()}",
            symbol="OW_CARD_INVALID",
            fix=f"ow drivers check {card_path}",
        )
    return table


def group_of(construct_id: str) -> str:
    """Ruling 4: `attr.class.upper` is in `attr`."""
    return construct_id.split(".", 1)[0]


def groups(rows: Sequence[Construct]) -> tuple[str, ...]:
    """Ruling 4: each group once, in the order `rows` first uses it."""
    return tuple(dict.fromkeys(group_of(row.id) for row in rows))


def select(
    table: ConstructTable, target: str, *, group: str | None = None, construct: str | None = None
) -> tuple[Construct, ...]:
    """The rows `--group` or `--construct` names, or every row. Ruling 7 for a name with none."""
    if construct is not None:
        try:
            return (table.row(construct),)
        except KeyError:
            ids = ", ".join(row.id for row in table.rows)
            raise NotFoundError(
                f"{table.il} has no construct {construct!r}; its rows are {ids}",
                symbol="OW_CONSTRUCT_UNKNOWN",
                fix=f"ow out constructs {target}",
            ) from None
    if group is None:
        return table.rows
    rows = tuple(row for row in table.rows if group_of(row.id) == group)
    if not rows:
        raise NotFoundError(
            f"{table.il} has no construct group {group!r}; its groups are "
            f"{', '.join(groups(table.rows))}",
            symbol="OW_CONSTRUCT_UNKNOWN",
            fix=f"ow out constructs {target}",
        )
    return rows


def agent_doc(
    card: CompileCard,
    table: ConstructTable,
    rows: Sequence[Construct] | None = None,
    *,
    numeric: Callable[[str], str] | None = None,
) -> str:
    """Ruling 5: the Markdown `--format md` prints, over `rows` (every row by default)."""
    chosen = table.rows if rows is None else tuple(rows)
    spell = numeric if numeric is not None else _register_numeric()
    lines = [
        f"# {table.il} constructs, target {card.target}",
        "",
        f"Carrier `{table.carrier}`, table version {table.version}. Write only these constructs; "
        "any other is an error.",
        _PREAMBLE,
    ]
    if table.ignore:
        lines.append("Ignored: " + ", ".join(f"`{one}`" for one in table.ignore) + ".")
    for group in groups(chosen):
        lines += ["", f"## {group}"]
        lines += [_line(row, card, spell) for row in chosen if group_of(row.id) == group]
    return "\n".join(lines) + "\n"


def _line(row: Construct, card: CompileCard, numeric: Callable[[str], str]) -> str:
    code = numeric(row.code)
    if row.disposition is Disposition.NORMALIZE:
        return f"- `{row.id}` normalize to `{row.normalizes_to}`: {row.canonical} ({code})"
    head = f"- `{row.id}` `{row.selector}` {row.disposition.value}"
    if row.disposition is Disposition.NATIVE:
        when = f"; forbidden when `{row.forbidden_when}` is present" if row.forbidden_when else ""
        return f"{head}: {row.canonical}{when} ({code})"
    if row.disposition is Disposition.BAKE:
        dpi = row.bake.dpi if row.bake is not None else 0
        unable = (
            ": this target cannot bake, so it is an error" if card.bake == "unavailable" else ""
        )
        return f"{head} at {dpi} dpi{unable} ({code})"
    return f"{head}: {row.msg} ({code})"


def _register_numeric() -> Callable[[str], str]:
    by_symbol = load_register().by_symbol

    def numeric(symbol: str) -> str:
        row = by_symbol.get(symbol)
        return row.numeric if row is not None and row.numeric else symbol

    return numeric


def _normalizer_names(path: Path) -> frozenset[str]:
    """Ruling 1: the module's top-level `def`s, read and never imported."""
    if not path.is_file():
        return frozenset()
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise TargetError(
            f"{path.name} does not parse, so no normalize row can name a function in it: {exc}",
            symbol="OW_TARGET_CONSTRUCTS_INVALID",
            fix=f"python -m py_compile {path}",
        ) from None
    return frozenset(node.name for node in module.body if isinstance(node, ast.FunctionDef))


def _documented_only(_value: str) -> str:
    """The stand-in a name maps to: the table is documented here, never normalised."""
    raise TargetError(
        "a normalizer was called while a construct table was being documented",
        symbol="OW_TARGET_CONSTRUCTS_INVALID",
        fix="ow out normalize, which imports the target's normalizers",
    )
