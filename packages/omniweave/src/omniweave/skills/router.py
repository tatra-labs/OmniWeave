"""The router body: `skills/omniweave/SKILL.md`, rendered, and checked against `skills/expected/`.

16:720 makes it *"generated"*. 10 section 5.2 gives the frontmatter verbatim and 10 section 5.3 the
body's shape -- six sections in order, plus *"When NOT to load this skill"* and a low-confidence
stop rule -- and this module renders both from tables, with every tool and verb spelled from
`omniweave.surface.registry`. A renamed Action changes the router without anyone editing it, which
is 10:111's reason for generating the catalog, applied to the one skill every session loads.

## THE CHECK IS NOT G25'S

G25 gates *"seven artefacts"* (16:716) and this is not one of them: 10:1371 gives the router its own
check, `ow skills check --check`, which *"byte-diffs the rendered `SKILL.md` set against
`skills/expected/`, and `--bless` is the only way to update it"*. `check()` is that comparison and
`bless()` that update, as functions; the verbs have no `ACTIONS` row yet (D487).

## WHAT THE PLAN GIVES, AND WHAT THIS MODULE HAD TO WRITE

Verbatim: the frontmatter (10:1216-1231, measured here at 994 characters as 10:1213 says), the six
headings (10:1250-1263), the state table's six conditions in order (10:1251-1253), the ten routes
(10:1157-1158), the stop rule and the three "when not" cases (10:1266-1269), and the quoted
phrasings each route matches, which are the description's own (10:1219-1223) and the `pptx` stub's
triggers (10:1285).

Written here, because the plan gives the shape and not the cell (D486): the state table's *skip*
column, three of the seven ambiguity bullets (10:1256 promises seven and names four), and where the
description's four non-deliverable uses go -- diagnose, index, resolve a cite, explain a parse --
since the ten-row table routes only one of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave.skills.tier import CORE
from omniweave.surface.registry import ACTIONS

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "AMBIGUITIES",
    "EXPECTED",
    "FRONTMATTER",
    "ROUTES",
    "SHIPPED",
    "STATES",
    "Route",
    "bless",
    "check",
    "description",
    "emit",
    "render",
    "unregistered",
]

SHIPPED: Final = f"{CORE}/SKILL.md"
"""Where the router ships, relative to the `skills/` root (10:1151)."""

EXPECTED: Final = f"expected/{CORE}/SKILL.md"
"""The blessed copy `check()` compares against (10:1371's `skills/expected/`)."""

MAX_LINES: Final = 150
"""10:1151: *"SKILL.md <= 150 lines"*."""

# 10:1216-1231, verbatim. YAML: a folded block scalar and a double-quoted scalar across two lines,
# both of which a YAML reader joins with single spaces.
FRONTMATTER: Final[tuple[str, ...]] = (
    f"name: {CORE}",
    "description: >",
    "  Mandatory entry point for any request to build, edit, or check a document-derived deliverable",  # noqa: E501 -- 10 section 5.2 verbatim
    '  from indexed sources: read this first when the user says "make a deck", "build a presentation",',  # noqa: E501 -- 10 section 5.2 verbatim
    '  "turn this into slides", "write a report from these PDFs", "summarise these contracts into a',  # noqa: E501 -- 10 section 5.2 verbatim
    '  document", "make a Word doc", "make a video", "extract fields from these invoices", "review this',  # noqa: E501 -- 10 section 5.2 verbatim
    '  deck against the source", "apply these comments", "fix the citations", "which document says',
    '  this", or "add a parser/driver for <format>". Also use it to diagnose an omniweave corpus, index',  # noqa: E501 -- 10 section 5.2 verbatim
    "  new documents, resolve a `d7#412` citation, or explain why a block was parsed the way it was.",  # noqa: E501 -- 10 section 5.2 verbatim
    "  Inputs may be a folder of PDF/DOCX/PPTX/XLSX/scans, a single file, a URL, a `cite`, an existing",  # noqa: E501 -- 10 section 5.2 verbatim
    "  omniweave-built artefact to edit, or a corpus name. It resumes artefact state, routes to the",  # noqa: E501 -- 10 section 5.2 verbatim
    "  owning workflow skill, installs that skill, and hands off. It does NOT itself retrieve — the",  # noqa: E501 -- 10 section 5.2 verbatim
    "  ow_query/ow_open MCP tools or `ow query` do that.",
    "metadata:",
    '  keywords: "pptx, powerpoint, deck, slides, docx, word, report, video, pdf, xlsx, extract,',
    '             citation, provenance, corpus, index, rag, document, driver, ocr, omniweave"',
)


def description() -> str:
    """The folded `description`, as a YAML reader yields it: the block's lines, joined by spaces."""
    start = FRONTMATTER.index("description: >") + 1
    stop = FRONTMATTER.index("metadata:")
    return " ".join(line.strip() for line in FRONTMATTER[start:stop])


# ---------------------------------------------------------------------------------------------
# Verbs. Every one the body names is an Action; those without a row yet are spelled as the plan
# spells them and reported by `unregistered()` (D487), so the day a row lands the body follows it.
# ---------------------------------------------------------------------------------------------

_PLANNED: Final[dict[str, str]] = {
    "skills.install": "ow skills install",  # 10:1159, 10:1261
    "out.targets": "ow out targets",  # 10:1290, 10:1305
    "out.check": "ow out check",  # 10:75, 10:1288
    "ingest": "ow ingest",  # 10:1115
    "route.explain": "ow why",  # 10:816, 10:1449
}


def _cli(action: str) -> str:
    spec = ACTIONS.get(action)
    if spec is not None:
        return "ow " + " ".join(spec.cli)
    return _PLANNED[action]


def _tool(action: str) -> str:
    """An Action's MCP name, from the registry: the body never spells a tool by hand."""
    name = ACTIONS[action].mcp_name
    if name is None:
        raise ValueError(f"{action} has no mcp_name, and the router names it as a tool")
    return name


def unregistered() -> tuple[str, ...]:
    """The Actions the body names that `ACTIONS` does not hold yet. D487."""
    return tuple(name for name in _PLANNED if name not in ACTIONS)


# ---------------------------------------------------------------------------------------------
# The tables.
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Route:
    """One row of section 2: a route stub's name (10:1157-1158), what it hands to, the phrasings."""

    name: str
    cues: tuple[str, ...]
    verb: str = ""

    @property
    def skill(self) -> str:
        return "" if self.verb else f"{CORE}-{self.name}"


# 10:1251-1253's six conditions, in the plan's order, and D486's skip column.
STATES: Final[tuple[tuple[str, str], ...]] = (
    ("an `.owdeck`/IL bundle exists for this slug",
     "routing, the stub and the brief: install the bundle's own skill (section 4) and resume it"),
    ("an existing artefact is being edited",
     "indexing and the route table: the route is the artefact's own kind"),
    ("a specific element edit was named",
     "indexing and the route table: carry the named edit into `BRIEF.md` as its whole scope"),
    ("a `BRIEF.md` exists",
     "indexing and writing the brief: route from the brief"),
    ("a corpus exists but no brief",
     "indexing"),
    ("nothing exists",
     "nothing: index first, then route"),
)  # fmt: skip

# 10:1157-1158's ten stubs, in that order. Each cue is quoted from the description (10:1219-1223)
# or, for `pptx`, from its stub's `triggers` line (10:1285); `ingest` routes to a verb (10:1170).
ROUTES: Final[tuple[Route, ...]] = (
    Route("pptx", ('"make a powerpoint"', '"pptx"', '"OOXML slides"',
                   '"editable slides for finance"')),
    Route("deck", ('"make a deck"', '"build a presentation"', '"turn this into slides"')),
    Route("docx", ('"make a Word doc"',)),
    Route("video", ('"make a video"',)),
    Route("report", ('"write a report from these PDFs"',
                     '"summarise these contracts into a document"')),
    Route("extract", ('"extract fields from these invoices"',)),
    Route("review", ('"review this deck against the source"',)),
    Route("apply-comments", ('"apply these comments"', '"fix the citations"')),
    Route("driver", ('"add a parser/driver for <format>"',)),
    Route("ingest", ("index new documents",), verb="add"),
)  # fmt: skip

# 10:1256-1260: seven promised, four named. The first two carry the plan's own distinction; the
# other two are D486's.
AMBIGUITIES: Final[tuple[tuple[str, str], ...]] = (
    ("report vs docx", "a report is authored prose with citations; a docx is a document structure"),
    ("deck vs pptx",
     "`omniweave-target-deck` is a toolchain HTML deck; `omniweave-pptx` is an OOXML file"),
    ("extract vs query",
     "extract fills named fields across many documents; a single question is `{query}`"),
    ("review vs apply-comments",
     "review checks an artefact against its sources and reports; apply-comments changes it"),
)  # fmt: skip


# ---------------------------------------------------------------------------------------------
# Rendering.
# ---------------------------------------------------------------------------------------------

_BANNER: Final = (
    f"<!-- skills/{SHIPPED} — GENERATED by omniweave.skills.router from its tables and",
    "     omniweave.surface.registry. Checked against skills/expected/ (10:1371). Do not edit. -->",
)


def _destination(route: Route) -> str:
    if route.verb:
        return f"`{_cli(route.verb)}` or `{_cli('ingest')}` (a verb, not a skill)"
    return f"skill `{route.skill}`"


def _sections() -> list[str]:
    query, opened, corpora = _tool("query"), _tool("open"), _tool("corpora")
    return [
        f"# {CORE} — the router",
        "",
        "Route a deliverable request to the workflow skill that owns it, then leave.",
        f"This skill does not retrieve: `{query}` and `{opened}` (or `{_cli('query')}` /",
        f"`{_cli('open')}`) do that.",
        "",
        "## When NOT to load this skill",
        "",
        f"- You already hold the cite: open it with `{opened}`.",
        f'- The task is retrieval only ("which document says this"): ask `{query}`.',
        "- The corpus is unindexed and you do not intend to index it.",
        "",
        "## 1. Start from artefact state",
        "",
        "Apply the first matching row; do not evaluate lower rows.",
        "",
        "| # | state | skip |",
        "|---|---|---|",
        *(f"| {i} | {state} | {skip} |" for i, (state, skip) in enumerate(STATES, 1)),
        "",
        f"If you do not know what exists, `{corpora}` lists the corpora.",
        "",
        "## 2. Route the deliverable",
        "",
        "Match on the requested *deliverable*, not on a file type mentioned in passing. The first",
        "matching row wins.",
        "",
        "| # | route | the user asks for | destination |",
        "|---|---|---|---|",
        *(
            f"| {i} | {route.name} | {', '.join(route.cues)} | {_destination(route)} |"
            for i, route in enumerate(ROUTES, 1)
        ),
        "",
        f"Not a deliverable: diagnose a corpus with `{_cli('doctor')}`, resolve a `d7#412`",
        f"cite with `{opened}`, and explain why a block was parsed the way it was with",
        f"`{_cli('route.explain')}`.",
        "",
        "### Resolve common ambiguities",
        "",
        *(f"- **{pair}**: {text.format(query=query)}." for pair, text in AMBIGUITIES),
        "",
        "## 3. Read the route stub before committing",
        "",
        "Read only the matched route's `references/routes/<route>.md`: its inputs, outputs,",
        "non-goals, gate and `refuses if` line. Run the command its `refuses if` line names",
        f"(`{_cli('out.targets')}`), because a target missing on this machine is caught by a call,",
        "not by the stub. If the candidate does not satisfy its contract, continue routing instead",
        "of forcing the match. If the stub is absent, this release does not ship that route:",
        "say so and stop.",
        "",
        "## 4. Install and enter",
        "",
        f"Run `{_cli('skills.install')} <skill>`. If the command fails, surface the error; do not",
        "reconstruct the workflow from memory.",
        "",
        "## 5. Hand off and leave",
        "",
        "The router writes `BRIEF.md` and stops. The brief is the only routing artefact the",
        "workflow reads; nothing later re-opens this skill.",
        "",
        "## Low-confidence stop rule",
        "",
        f"If `{query}` returns `low_confidence` twice on the same question, report the gap; do not",
        "keep re-querying hoping it appears.",
        "",
        "## References",
        "",
        "- `references/actions.md`: every capability this build can dispatch, generated from the",
        "  same registry as this file.",
    ]


def render() -> str:
    """The router's `SKILL.md`: frontmatter, the banner, the body. LF, one final newline."""
    lines = ["---", *FRONTMATTER, "---", *_BANNER, *_sections()]
    text = "\n".join(lines) + "\n"
    count = text.count("\n")
    if count > MAX_LINES:
        raise ValueError(f"the router renders {count} lines; 10:1151 allows {MAX_LINES}")
    return text


# ---------------------------------------------------------------------------------------------
# emit, check, bless. `root` is the repository's `skills/`.
# ---------------------------------------------------------------------------------------------


def _read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None


def emit(root: Path) -> bool:
    """Write the rendered router to `root/omniweave/SKILL.md`; whether the bytes changed."""
    path = root / SHIPPED
    text = render()
    if _read(path) == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return True


def check(root: Path) -> tuple[str, ...]:
    """10:1371's comparison: the render against the blessed copy, and the shipped file against both.

    Empty when all three agree. A shipped file that differs from the render is a hand edit or a
    stale emit; a render that differs from `skills/expected/` is a change nobody has blessed.
    """
    text = render()
    problems: list[str] = []
    for relative, what in ((EXPECTED, "blessed"), (SHIPPED, "shipped")):
        found = _read(root / relative)
        if found is None:
            problems.append(f"skills/{relative} is missing ({what} copy)")
        elif found != text:
            problems.append(f"skills/{relative} differs from the render ({what} copy)")
    return tuple(problems)


def bless(root: Path) -> None:
    """`--bless`: make the current render the expected one (10:1371). The only way to update it."""
    path = root / EXPECTED
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render().encode("utf-8"))
