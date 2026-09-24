"""Artefact 7, `skills/omniweave/references/actions.md`: the router skill's catalog. 10:214.

10:206's last row: *"`skills/omniweave/references/actions.md` | Actions with an `mcp_name`, grouped
by `cli[0]` | the router skill's catalog"*. 10:1154's tree calls it *"GENERATED from ACTIONS: the
narrow-capability catalog"*. It is the seventh and last of the seven, so `ow surface emit` writes
all seven from this cell on and `check()`'s `PENDING` clause has no row left to fire on.

## WHO READS IT, AND WHY THAT IS NOT ARTEFACT 5'S READER OR ARTEFACT 6'S

The router. `skills/omniweave/SKILL.md` is *"the ONLY always-resident skill"* (10:1151), is capped
at 150 lines, and *"contains no workflow"* -- it is six sections of routing, and this file is the
reference it consults when the question is *"does a capability for this exist, and which one do I
call?"*. Three consequences, and each decides a field:

* **`decision` is published here and is NOT in artefact 6.** 10:192 makes it the <= 90-character
  disambiguator *"an agent reads at pick time"*, and picking is exactly what a router does.
  `docs/AGENTS.md`'s reader is editing the registry and never picks between tools, which is why
  W7.2f left it out; leaving it out here would remove the one field written for this reader.
* **The listing rule is the first section, before any Action.** A router that concluded a
  capability does not exist because it is not in `tools/list` would decline work the server would
  have done -- LEANN's defect arrived at from the routing side. 10:2465's note is the answer and it
  is `llms.LISTED_NOTE`, imported rather than transcribed, with the two variable names filled from
  `omniweave_core.config.KEYS` exactly as artefact 5 fills them.
* **Every block carries its CLI twin.** The router may be driving a shell rather than an MCP
  client, and a twin works whatever the listing says. 10:2519: *"every MCP tool has a CLI twin."*

## "ACTIONS WITH AN `mcp_name`" AND "THE NARROW-CAPABILITY CATALOG" ARE DIFFERENT SETS

10:214's `generated from` cell says every Action with an `mcp_name` -- nine today, four of them in
the front door. 10:1154's tree comment says *"the narrow-capability catalog"*, which reads as the
five that are listed only under `full`. A catalog of five would omit `ow_query` and `ow_open` from
the file a router reads to pick between them.

The source cell wins, for W7.2e's reason and D312's: the `generated from` column is the register's
constraint and the tree comment is a description of purpose. All nine get a block, each marked with
the profiles that LIST it, so the narrow ones are identifiable by reading a field rather than by
trusting a title. That also keeps this artefact's roster equal to artefact 5's -- the two source
cells select the same rows -- and a test binds them. D336 is the entry.

## GROUPED BY `cli[0]`, WHICH IS THE ONE PROJECTION THIS ARTEFACT IS TOLD TO USE

Every other artefact orders Actions by `name` (10:225). This one groups first, and the grouping key
is the CLI ROOT rather than the Action's dotted prefix -- `corpus.coverage` sits under `corpora`
because its `cli` is `("corpora",)`, not under a `corpus` group that no command spells. That is
10:1424's flag-valued twin (D299) seen from the catalog side, and it is the reason the group heading
is the root and every block still prints its own full spelling.

## WHAT IS NOT HERE, AND WHICH OF IT IS SCHEDULE

`SKILL.md` is `omniweave.skills.router`'s (W7.6a) and is checked against `skills/expected/`
(10:1371), not by G25. The ten route stubs under `references/routes/` are generated too (10:2801)
and are in neither gate's set yet. W7.2 ended this directory with one file and a bundle that could
not install (D338); W7.6a's router made it installable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from omniweave_core.config import KEYS
from omniweave_core.errors import SurfaceError

from omniweave.gen.agents import ABSENT
from omniweave.gen.llms import LISTED_NOTE
from omniweave.gen.wrap import wrapped
from omniweave.surface.registry import ACTIONS, PROFILES, listed

if TYPE_CHECKING:
    from omniweave.surface.registry import ActionSpec

__all__ = [
    "LABEL",
    "WIDTH",
    "declared",
    "groups",
    "render",
    "tool_block",
]


WIDTH: Final[int] = 96
"""The column prose and a label block's value wrap at. Artefact 6's measure, for one reason:
both files are Markdown read by an agent, and a reader moving between them should not meet two."""

LABEL: Final[int] = 12
"""The column a label block's value starts at. 10:1280's own measure, transcribed.

The route stub the plan prints beside this file uses a twelve-column label field -- `inputs`,
`outputs`, `triggers`, `non-goals`, `determinism`, `gate`, `entry Q`, `refuses if` -- and this is
the directory's established grammar rather than this module's taste. A continuation line is
indented to the same column, so a line starting in column one is always a new label.
"""


# =============================================================================================
# 1. The roster, and what could not be rendered from it
# =============================================================================================


def declared() -> tuple[str, ...]:
    """The `mcp_name`s this catalog renders a block for, sorted. Every one the registry has.

    The same roster `llms.declared()` returns, because 10:212 and 10:214 select the same rows
    with different words. A test binds the two: two artefacts disagreeing about which tools exist
    is the defect both of them are generated to prevent.
    """
    return tuple(sorted(spec.mcp_name for spec in ACTIONS.values() if spec.mcp_name is not None))


def groups() -> tuple[tuple[str, tuple[ActionSpec, ...]], ...]:
    """`cli[0]` -> its Actions, both sorted. 10:214's *"grouped by `cli[0]`"*, and nothing else.

    Roots sorted lexically and Actions within a root by `name`, which is 10:224's ban on iterating
    an unsorted set plus 10:225's *"Actions by `name`"* applied inside each group. Two Actions
    sharing a root is ordinary -- `corpora` holds `corpora` and `corpus.coverage` -- and two
    sharing a whole CLI tuple is D299, which changes nothing here because this file keys on the
    root and prints each Action's spelling in its own block.
    """
    found: dict[str, list[ActionSpec]] = {}
    for spec in sorted(ACTIONS.values(), key=lambda row: row.name):
        if spec.mcp_name is not None and spec.cli:
            found.setdefault(spec.cli[0], []).append(spec)
    return tuple((root, tuple(members)) for root, members in sorted(found.items()))


def _catalog_failures() -> tuple[str, ...]:
    """Every reason a block could not be rendered, or would be rendered wrong. Raised at import.

    Three clauses. The first two are the LEANN property as a biconditional, the shape
    `llms._manifest_failures()` established: a catalog that named a tool the registry does not
    define sends a router at nothing, and one that omitted a tool the registry does define is the
    hand-written manifest G25 is named after. Checking one direction is how the defect ships.

    The third is this artefact's own grammar. A value here is laid out in a twelve-column label
    block, so a line break inside `summary` or `decision` produces a line starting in column one,
    which reads as a new label rather than as a continuation. Check 7 caps both strings and
    forbids a trailing full stop; it says nothing about a newline. Refused rather than joined,
    because joining publishes a sentence nobody wrote.
    """
    findings: list[str] = []
    named = {spec.mcp_name for spec in ACTIONS.values() if spec.mcp_name is not None}
    rendered = {str(spec.mcp_name) for _root, members in groups() for spec in members}
    findings.extend(
        f"{name}: an Action declares this mcp_name and no block is rendered for it"
        for name in sorted(named - rendered)
    )
    findings.extend(
        f"{name}: a block is rendered and no Action declares this mcp_name"
        for name in sorted(rendered - {str(name) for name in named})
    )
    for _root, members in groups():
        for spec in members:
            findings.extend(
                f"{spec.name}: {field} contains a line break, which reads as a new label"
                for field, text in (("summary", spec.summary), ("decision", spec.decision))
                if "\n" in text or "\r" in text
            )
    return tuple(findings)


_FAILURES: Final[tuple[str, ...]] = _catalog_failures()
if _FAILURES:  # pragma: no cover -- the shipped registry agrees with itself; a test builds one
    raise SurfaceError(
        "the router catalog cannot be rendered from this registry: " + "; ".join(_FAILURES),
        symbol="OW_SURFACE_REGISTRY_INVALID",
        fix="fix every row named above in omniweave/surface/registry.py",
    )


# =============================================================================================
# 2. Lines
# =============================================================================================


def _labelled(label: str, value: str) -> list[str]:
    """One `label` / `value` pair, wrapped, with the value's continuation under the value."""
    indent = " " * LABEL
    return wrapped(f"{label.ljust(LABEL)}{value}", width=WIDTH, indent=indent)


def tool_block(spec: ActionSpec) -> list[str]:
    """One tool's block: a heading and five labels, every one of them a field.

    `action` is published beside `tool` because 10:790 has both environment variables accept
    *"the bare Action name (`route.explain`) and the MCP name (`ow_route_explain`)"* -- so a
    router widening a listing to reach a capability needs the pair, and the block that tells it
    the capability exists is where the pair belongs.

    `cost` is printed for every block and never conditionally on its value, which is 10:216's
    rule about artefact 1's annotation keys read one artefact over: a field dropped where it is
    `free` would make its presence mean something the register does not declare.

    `listed` falls back to `agents.ABSENT` -- artefact 6's em dash, imported rather than spelled
    again, the way this package already imports `llms.PRODUCT` and `llms.SUMMARY`. The branch is
    reachable: check 5 forbids `listed_in` on an Action with no `mcp_name` and says nothing about
    the reverse, so a reachable-but-unlisted Action is legal and `route.explain` is the one the
    plan already names (10:43).
    """
    profiles = ", ".join(sorted(spec.listed_in)) if spec.listed_in else ABSENT
    return [
        f"### {spec.mcp_name}",
        "",
        *_labelled("action", spec.name),
        *_labelled("cli", f"ow {' '.join(spec.cli)}"),
        *_labelled("listed", profiles),
        *_labelled("cost", spec.cost_class.value),
        *_labelled("pick it", spec.decision),
        *_labelled("it does", spec.summary),
    ]


def _listing_lines() -> list[str]:
    """The section a router reads before it concludes a capability is missing.

    Every line is derived. The profile rosters come from `listed()`, the note from
    `llms.LISTED_NOTE` -- 10:2465's sentence, transcribed once in the artefact that found the
    defect behind it -- and the two variable names from `omniweave_core.config.KEYS`, which is
    what W7.2e's D327 makes non-negotiable: the manifest had published a name nothing read.
    """
    lines: list[str] = []
    for profile in PROFILES:
        tools = ", ".join(sorted(str(ACTIONS[name].mcp_name) for name in listed(profile)))
        lines.extend(_labelled(profile, tools))
    lines.append("")
    lines.extend(
        wrapped(
            LISTED_NOTE.format(listed=KEYS["serve.listed"].env, enabled=KEYS["serve.enabled"].env),
            width=WIDTH,
        )
    )
    return lines


# =============================================================================================
# 3. The bytes
# =============================================================================================


def render() -> bytes:
    """`skills/omniweave/references/actions.md`, whole. Pure: `ACTIONS`, `PROFILES`, `KEYS`.

    10:232 fixes the encoding -- *"Output is `\\n`-terminated UTF-8 with no BOM"* -- and the final
    newline is added here so no section has to remember it.
    """
    lines: list[str] = [
        "<!-- skills/omniweave/references/actions.md — GENERATED by `ow surface emit` from",
        "     omniweave.surface.registry. Byte-diff gated (G25). Do not edit. -->",
        "# Action catalog",
        "",
        *wrapped(
            "Every capability this build can dispatch, grouped by the CLI root it runs under. "
            "Read a block to decide WHICH capability a request wants; the `pick it` line is the "
            "one written for that decision.",
            width=WIDTH,
        ),
        "",
        "## Before deciding a capability is missing",
        "",
        *_listing_lines(),
        "",
        *wrapped(
            "Every tool below also has a CLI twin, which runs whatever the listing says. If a "
            "route needs a capability the client does not offer, the twin is the route.",
            width=WIDTH,
        ),
    ]
    for root, members in groups():
        lines.extend(["", f"## ow {root}", ""])
        for index, spec in enumerate(members):
            if index:
                lines.append("")
            lines.extend(tool_block(spec))
    return ("\n".join(lines) + "\n").encode("utf-8")
