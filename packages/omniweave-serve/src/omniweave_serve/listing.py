"""What `tools/list` and `initialize` send, selected from `mcp-listing-v1.json`. D340 closed.

`omniweave.gen.listing` renders the file from the registry, `omniweave.surface.schema` and
`omniweave.gen.instructions`, and this module reads it, which is D340's route 2. The transforms
are applied there, by the functions that own them, and this module SELECTS bytes: it strips
nothing, demotes nothing and promotes nothing. So the server sends objects that were rendered
and measured, which is `catalog.Tool`'s argument for loading rather than building.

## FOUR SWITCHES, AND WHO SETS EACH

| input | from | read by |
|---|---|---|
| `profile` | `[serve] profile` | `tools_list`, `instructions` |
| `compact` | `[serve] compact_schemas` | `tools_list` |
| `corpus_resolves` | whether `[serve] default_corpus` resolves at startup | both |

The first two are configuration values a caller hands in. The third is a fact about the
deployment that only the startup sequence knows -- `omniweave.surface.startup.servable().resolves`,
in the distribution this one may not import -- so it is an argument here too, and
`catalog.unservable()` now names it as the one input still owed.

## THE LISTING AND THE CATALOGUE ARE BOUND

The listing carries `catalogue_sha256`. `check()` refuses a listing whose digest is not the loaded
catalogue's, so a catalogue re-emitted without its listing -- a registry change that reached
artefact 1 and not this file -- is a named finding rather than a `tools/list` that mixes two
releases' objects.

## A LISTED TOOL WITH NO PUBLISHED SCHEMA IS SAID, NOT DROPPED

`full` lists nine tools and the catalogue publishes four (D507). `tools_list()` sends the four, and
`unpublished()` names the other five, so the gap is a line in a report and never a quiet shortening
of the list the profile promises.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from omniweave_core.errors import ConfigError

from omniweave_serve.catalog import Catalogue, load_catalogue

__all__ = [
    "LISTING_NAME",
    "VERSION",
    "Listing",
    "check",
    "instructions",
    "listing_path",
    "load_listing",
    "tools_list",
    "unpublished",
]

LISTING_NAME: Final[str] = "mcp-listing-v1.json"
VERSION: Final[int] = 1
_VARIANT_KEYS: Final[tuple[str, ...]] = ("compact", "required_corpus", "compact_required_corpus")
_REFRESH: Final[str] = "pip install --force-reinstall omniweave-serve"

_FORM: Final[Mapping[tuple[bool, bool], str]] = MappingProxyType(
    {
        (False, True): "",
        (True, True): "compact",
        (False, False): "required_corpus",
        (True, False): "compact_required_corpus",
    }
)
"""`(compact, corpus_resolves)` -> the variant key; `""` is the catalogue's own object.

`corpus` is promoted to required when the default does NOT resolve (10:525), so `required_corpus`
is the `False` column."""


@dataclass(frozen=True, slots=True)
class Listing:
    """The parsed file. `raw` is the parsed document; the typed fields are what `check()` reads."""

    path: Path
    version: object
    catalogue_sha256: str
    profiles: Mapping[str, Mapping[str, tuple[str, ...]]]
    variants: Mapping[str, Mapping[str, str]]
    """Tool name -> variant key -> the object's JSON text, so a caller cannot mutate the memo."""
    instructions: Mapping[str, Mapping[str, str]]


def listing_path() -> Path:
    """The packaged file, through `importlib.resources` (11 section 2.6 rule 1). It ships in the
    wheel beside this module, so there is no workspace fallback to fall back to."""
    packaged = resources.files("omniweave_serve").joinpath(LISTING_NAME)
    if packaged.is_file():
        return Path(str(packaged))
    raise ConfigError(
        f"omniweave_serve/{LISTING_NAME} is not readable: this install cannot select a profile, "
        f"compact a schema or send the instructions",
        fix=_REFRESH,
    )


def load_listing(path: Path | None = None) -> Listing:
    """Parse the listing. At use time, memoised, never at import (11 section 2.6 rule 2)."""
    return _load(path or listing_path())


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(one) for one in value) if isinstance(value, list) else ()


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


@cache
def _load(path: Path) -> Listing:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"{path} is not a readable MCP listing: {exc}", fix=_REFRESH) from exc
    table = _mapping(document)
    profiles = {
        str(name): MappingProxyType(
            {key: _strings(_mapping(entry).get(key)) for key in ("tools", "unpublished")}
        )
        for name, entry in _mapping(table.get("profiles")).items()
    }
    variants = {
        str(name): MappingProxyType(
            {
                str(key): json.dumps(obj, ensure_ascii=False)
                for key, obj in _mapping(forms).items()
                if isinstance(obj, dict)
            }
        )
        for name, forms in _mapping(table.get("variants")).items()
    }
    prose = {
        str(name): MappingProxyType(
            {str(key): str(text) for key, text in _mapping(pair).items() if isinstance(text, str)}
        )
        for name, pair in _mapping(table.get("instructions")).items()
    }
    return Listing(
        path=path,
        version=table.get("version"),
        catalogue_sha256=str(table.get("catalogue_sha256", "")),
        profiles=MappingProxyType(profiles),
        variants=MappingProxyType(variants),
        instructions=MappingProxyType(prose),
    )


def _digest(path: Path) -> str:
    """`omniweave.gen.listing.catalogue_digest`'s rule, CRLF normalised; bound by a test."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def check(listing: Listing | None = None, catalogue: Catalogue | None = None) -> tuple[str, ...]:
    """Every reason the listing cannot be served over this catalogue. `()` is servable.

    1. the version is this reader's;
    2. `catalogue_sha256` is the loaded catalogue's digest -- the two files are one release;
    3. every profile's tools are in the catalogue, and none is also `unpublished`;
    4. every listed tool has all three variants, each naming itself;
    5. every profile has both instructions variants.
    """
    listing = listing or load_listing()
    catalogue = catalogue or load_catalogue()
    findings: list[str] = []
    if listing.version != VERSION:
        findings.append(
            f"{listing.path}: version {listing.version!r}, and this reader is {VERSION}"
        )
    if listing.catalogue_sha256 != _digest(catalogue.path):
        findings.append(
            f"{listing.path}: pins a catalogue other than {catalogue.path}; the two were emitted "
            f"by different releases, so neither can be trusted to describe the other"
        )
    for profile, entry in listing.profiles.items():
        for name in entry["tools"]:
            if name not in catalogue.by_name:
                findings.append(f"profile {profile}: lists {name}, which the catalogue lacks")
            if name in entry["unpublished"]:
                findings.append(f"profile {profile}: {name} is both listed and unpublished")
            forms = listing.variants.get(name, {})
            missing = [key for key in _VARIANT_KEYS if key not in forms]
            if missing:
                findings.append(f"{name}: no {', '.join(missing)} form")
            for key, text in forms.items():
                if json.loads(text).get("name") != name:
                    findings.append(f"{name}: its {key} form names another tool")
        pair = listing.instructions.get(profile, {})
        for key in ("default_corpus", "no_default_corpus"):
            if not pair.get(key):
                findings.append(f"profile {profile}: no {key} instructions")
    return tuple(findings)


def _profile(listing: Listing, profile: str) -> Mapping[str, tuple[str, ...]]:
    entry = listing.profiles.get(profile)
    if entry is None:
        known = ", ".join(sorted(listing.profiles))
        raise ConfigError(
            f"[serve] profile = {profile!r} is not a profile; the listing has {known}",
            fix=f"set [serve] profile to one of: {known}",
        )
    return entry


def tools_list(
    profile: str,
    *,
    compact: bool,
    corpus_resolves: bool,
    listing: Listing | None = None,
    catalogue: Catalogue | None = None,
) -> tuple[dict[str, Any], ...]:
    """The `tools` array `tools/list` sends, in the catalogue's order. Fresh dictionaries.

    The catalogue is loaded only for the one form the listing does not carry, `(compact=False,
    corpus_resolves=True)`, which is the catalogue's own object. Loading it for the other three
    would make the shipped default -- `compact_schemas = true` -- fail on every install that lacks
    `schema/`, which is every `pip install` (D341), for a file those three forms never read. D509.
    """
    listing = listing or load_listing()
    key = _FORM[(compact, corpus_resolves)]
    names = _profile(listing, profile)["tools"]
    if key:
        return tuple(json.loads(listing.variants[name][key]) for name in names)
    catalogue = catalogue or load_catalogue()
    return tuple(catalogue.by_name[name].wire() for name in names)


def instructions(profile: str, *, corpus_resolves: bool, listing: Listing | None = None) -> str:
    """`initialize.instructions`: 10:871's variant for this profile, A when the corpus resolves."""
    listing = listing or load_listing()
    _profile(listing, profile)
    pair = listing.instructions[profile]
    return pair["default_corpus" if corpus_resolves else "no_default_corpus"]


def unpublished(profile: str, listing: Listing | None = None) -> tuple[str, ...]:
    """The tools `profile` lists and the catalogue does not publish, so `tools/list` cannot send."""
    return _profile(listing or load_listing(), profile)["unpublished"]
