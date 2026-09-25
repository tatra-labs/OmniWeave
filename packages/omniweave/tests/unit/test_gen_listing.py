"""`omniweave.gen.listing`: the file D340 route 2 adds, and the binding across the layers row.

**The sharpest test is the server-selection one**,
`test_the_server_selects_exactly_what_the_owners_of_the_transforms_produce`. `omniweave_serve` may
not import `omniweave` (02:361), so nothing in the server can check that the objects it sends are
`omniweave.surface.schema`'s. A test can import both, because G4 scans source and not tests, and
this one compares every profile under all four switch settings.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from omniweave.gen import listing
from omniweave.gen.instructions import instructions as owner_instructions
from omniweave.gen.mcp_tools import tools as catalogue_tools
from omniweave.surface.registry import ACTIONS, PROFILES, listed
from omniweave.surface.schema import compact, with_required_corpus
from omniweave_serve import listing as served

REPO = Path(__file__).resolve().parents[4]


def test_the_committed_listing_is_the_render() -> None:
    assert listing.check(REPO) == ()


def test_a_hand_edit_and_a_missing_file_are_named(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "schema").mkdir(parents=True)
    shutil.copy(REPO / listing.CATALOGUE, root / listing.CATALOGUE)
    target = root / listing.LISTING
    target.parent.mkdir(parents=True)
    assert listing.check(root) == (
        f"{listing.LISTING} is missing: run omniweave.gen.listing.emit()",
    )
    assert listing.emit(root)
    assert not listing.emit(root)
    target.write_bytes(target.read_bytes().replace(b'"version": 1', b'"version": 2'))
    assert "differs from the render" in listing.check(root)[0]


def test_the_digest_rule_is_the_servers() -> None:
    raw = (REPO / listing.CATALOGUE).read_bytes()
    assert listing.catalogue_digest(raw) == served._digest(REPO / listing.CATALOGUE)
    assert listing.catalogue_digest(b"a\r\nb") == listing.catalogue_digest(b"a\nb")


def test_the_profiles_are_the_registrys_listings_split_by_what_is_published() -> None:
    document = json.loads((REPO / listing.LISTING).read_text(encoding="utf-8"))
    published = {tool["name"] for tool in catalogue_tools()}
    for profile in PROFILES:
        names = {ACTIONS[one].mcp_name for one in listed(profile)}
        entry = document["profiles"][profile]
        assert set(entry["tools"]) == names & published, profile
        assert set(entry["unpublished"]) == names - published, profile


def _owner(tool: dict[str, object], *, small: bool, resolves: bool) -> dict[str, object]:
    out = compact(tool) if small else dict(tool)
    return out if resolves else with_required_corpus(out)


def test_the_server_selects_exactly_what_the_owners_of_the_transforms_produce() -> None:
    by_name = {str(tool["name"]): tool for tool in catalogue_tools()}
    for profile in PROFILES:
        for small in (True, False):
            for resolves in (True, False):
                sent = served.tools_list(profile, compact=small, corpus_resolves=resolves)
                expected = [
                    _owner(by_name[str(tool["name"])], small=small, resolves=resolves)
                    for tool in sent
                ]
                assert list(sent) == expected, (profile, small, resolves)
            for resolves in (True, False):
                assert served.instructions(profile, corpus_resolves=resolves) == (
                    owner_instructions(profile=profile, default_corpus=resolves)
                ), (profile, resolves)
