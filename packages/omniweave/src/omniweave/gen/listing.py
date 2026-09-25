"""`omniweave_serve/mcp-listing-v1.json`: what `tools/list` and `initialize` send. D340.

D340 is W7.3's blocking decision: `tools/list` needs three transforms over the payload -- select a
profile, compact, promote `corpus` to required -- and `initialize` needs the instructions string,
and all four live in `omniweave`, which `omniweave_serve` may not import (02:361, G4). Of D340's
three routes the build takes the second, *"an eighth generated data artefact ... generated from
`ACTIONS` and read by the server the way the payload is"*.

## THE FILE CARRIES THE TRANSFORMED OBJECTS, NOT THE RULES

D340's sketch is a file of `listed_in` and `advanced` sets, which would leave the server to strip,
demote and promote on its own. That is a second home for `omniweave.surface.schema`'s three
functions, and `omniweave_serve.catalog.Tool` already argues against it: *"a server that rebuilt
the object from its parts would send a payload nobody measured"*. So every listed tool's three
transformed forms -- `compact`, `required_corpus`, and both -- are rendered HERE, by the functions
that own them, and the server selects bytes. It transforms nothing.

The untransformed form is artefact 1 itself, so it is not repeated: the file carries
`catalogue_sha256`, the digest of `schema/mcp-tools-v1.json` as committed, and the server refuses
a listing whose digest is not the catalogue's it loaded. The two files cannot drift apart silently.

## A PROFILE CAN LIST A TOOL THE CATALOGUE DOES NOT PUBLISH

`full` lists nine tools and the catalogue carries four: five `full`-profile rows have an
`mcp_name` and no published `inputSchema` (`mcp_tools.unpublished()`). A tool object without one
cannot be sent. So each profile records `tools`, the listed names the catalogue has, in the
catalogue's order, and `unpublished`, the ones it does not. The server serves the first and says
the second out loud. D507.

## WHY IT IS NOT AN EIGHTH ROW IN `artefacts.ARTEFACTS`

G25 is *"seven artefacts"* (16:716), a closed set the charter fixes, and D340 route 2 names this
shape *"an unnumbered `[[job_assertion]]` ... rather than a widened gate"*. So `check()` here is its
own assertion, run by `test_gen_listing.py`, like `skills.cite.check()` (D505).

## WHY IT LIVES INSIDE `omniweave_serve`

`schema/` is G6's closed inventory of thirteen, and `tools/schemagen.py`'s stray-file clause would
report a fourteenth. Inside the package, `importlib.resources.files("omniweave_serve")` finds it
and the wheel ships it, so this file is not a fourth case of D341's *"ships in no wheel"*.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any, Final

from omniweave.gen.instructions import instructions
from omniweave.gen.mcp_tools import tools as catalogue_tools
from omniweave.surface.registry import ACTIONS, PROFILES, listed
from omniweave.surface.schema import compact, with_required_corpus

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "CATALOGUE",
    "LISTING",
    "VARIANTS",
    "VERSION",
    "catalogue_digest",
    "check",
    "document",
    "emit",
    "render",
]

VERSION: Final = 1

CATALOGUE: Final = "schema/mcp-tools-v1.json"
"""Artefact 1's path, whose bytes `catalogue_sha256` pins."""

LISTING: Final = "packages/omniweave-serve/src/omniweave_serve/mcp-listing-v1.json"
"""Where the file lands, relative to the repository root."""

VARIANTS: Final[tuple[str, ...]] = ("compact", "required_corpus", "compact_required_corpus")
"""The three transformed forms. The fourth, neither, is artefact 1's own object."""


def catalogue_digest(raw: bytes) -> str:
    """sha256 of the catalogue, CRLF normalised as G25 compares it. The server computes the same."""
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _variants(tool: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "compact": compact(tool),
        "required_corpus": with_required_corpus(tool),
        "compact_required_corpus": with_required_corpus(compact(tool)),
    }


def document(catalogue_raw: bytes) -> dict[str, Any]:
    """The listing as a mapping, over the catalogue bytes it pins."""
    published = [tool["name"] for tool in catalogue_tools()]
    profiles: dict[str, dict[str, list[str]]] = {}
    for profile in PROFILES:
        names = {str(ACTIONS[name].mcp_name) for name in listed(profile)}
        profiles[profile] = {
            "tools": [name for name in published if name in names],
            "unpublished": sorted(name for name in names if name not in published),
        }
    listed_anywhere = {name for entry in profiles.values() for name in entry["tools"]}
    variants = {
        str(tool["name"]): _variants(tool)
        for tool in catalogue_tools()
        if tool["name"] in listed_anywhere
    }
    return {
        "version": VERSION,
        "catalogue": CATALOGUE,
        "catalogue_sha256": catalogue_digest(catalogue_raw),
        "profiles": profiles,
        "variants": variants,
        "instructions": {
            profile: {
                "default_corpus": instructions(profile=profile, default_corpus=True),
                "no_default_corpus": instructions(profile=profile, default_corpus=False),
            }
            for profile in PROFILES
        },
    }


def render(root: Path) -> bytes:
    """The file's bytes: two-space JSON, keys in insertion order, real UTF-8, one final newline."""
    raw = (root / CATALOGUE).read_bytes()
    text = json.dumps(document(raw), indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def emit(root: Path) -> bool:
    """Write the listing under `root`; whether the bytes changed."""
    path = root / LISTING
    payload = render(root)
    try:
        if path.read_bytes().replace(b"\r\n", b"\n") == payload:
            return False
    except FileNotFoundError:
        pass
    path.write_bytes(payload)
    return True


def check(root: Path) -> tuple[str, ...]:
    """Empty when the committed listing is the render, CRLF-normalised; else the one finding."""
    path = root / LISTING
    try:
        found = path.read_bytes().replace(b"\r\n", b"\n")
    except FileNotFoundError:
        return (f"{LISTING} is missing: run omniweave.gen.listing.emit()",)
    if found != render(root):
        return (f"{LISTING} differs from the render: run omniweave.gen.listing.emit()",)
    return ()
