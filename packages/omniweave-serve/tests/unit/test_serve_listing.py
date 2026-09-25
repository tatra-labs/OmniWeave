"""`omniweave_serve.listing`: selecting what `tools/list` and `initialize` send. D340 route 2.

**The sharpest test is `test_a_listing_pinned_to_another_catalogue_is_refused`.** The two files
are emitted from one registry and read separately, so the digest is the only thing stopping a
server from mixing one release's tool objects with another's.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from omniweave_core.errors import ConfigError
from omniweave_serve import listing as module
from omniweave_serve.catalog import load_catalogue
from omniweave_serve.listing import (
    LISTING_NAME,
    check,
    instructions,
    listing_path,
    load_listing,
    tools_list,
    unpublished,
)

if TYPE_CHECKING:
    from pathlib import Path


def _copy(tmp_path: Path, **change: object) -> Path:
    document = json.loads(listing_path().read_text(encoding="utf-8"))
    document.update(change)
    target = tmp_path / LISTING_NAME
    target.write_text(json.dumps(document), encoding="utf-8")
    return target


def test_the_shipped_listing_is_servable_over_the_shipped_catalogue() -> None:
    assert check() == ()


def test_the_listing_ships_inside_the_package() -> None:
    """Not D341's shape: `resources.files` finds it beside the modules, which the wheel carries."""
    assert listing_path().parent.name == "omniweave_serve"


def test_the_default_profile_lists_the_front_door_in_the_catalogues_order() -> None:
    names = [tool["name"] for tool in tools_list("default", compact=True, corpus_resolves=True)]
    assert names == ["ow_add", "ow_corpora", "ow_open", "ow_query"]
    assert names == [tool.name for tool in load_catalogue().tools]


def test_uncompacted_with_a_resolving_corpus_is_the_catalogues_own_bytes() -> None:
    sent = tools_list("default", compact=False, corpus_resolves=True)
    assert list(sent) == [tool.wire() for tool in load_catalogue().tools]


def test_compaction_removes_parameters_and_never_closes_the_schema() -> None:
    full = {t["name"]: t for t in tools_list("default", compact=False, corpus_resolves=True)}
    small = {t["name"]: t for t in tools_list("default", compact=True, corpus_resolves=True)}
    for name, tool in small.items():
        kept = set(tool["inputSchema"]["properties"])
        assert kept <= set(full[name]["inputSchema"]["properties"]), name
        assert tool["inputSchema"]["additionalProperties"] is False, name
    assert small["ow_corpora"] == full["ow_corpora"], "10:353's one unchanged tool"
    assert len(json.dumps(small["ow_query"])) < len(json.dumps(full["ow_query"]))


def test_corpus_is_required_exactly_when_the_default_does_not_resolve() -> None:
    """10:525: every corpus-scoped listed tool. `ow_corpora`'s corpus is optional by design, and
    the promotion is keyed on the property, so it is promoted too."""
    for compact in (True, False):
        for tool in tools_list("default", compact=compact, corpus_resolves=False):
            assert "corpus" in tool["inputSchema"].get("required", []), tool["name"]
        for tool in tools_list("default", compact=compact, corpus_resolves=True):
            if tool["name"] != "ow_add":
                assert "corpus" not in tool["inputSchema"].get("required", []), tool["name"]


def test_what_is_returned_is_a_copy() -> None:
    first = tools_list("default", compact=True, corpus_resolves=True)
    first[0]["name"] = "ow_nonesuch"
    assert tools_list("default", compact=True, corpus_resolves=True)[0]["name"] == "ow_add"


def test_the_full_profile_says_which_listed_tools_it_cannot_send() -> None:
    """D507: nine listed, four published."""
    sent = [tool["name"] for tool in tools_list("full", compact=True, corpus_resolves=True)]
    assert sent == ["ow_add", "ow_corpora", "ow_open", "ow_query"]
    assert unpublished("full") == ("ow_coverage", "ow_diff", "ow_doctor", "ow_explain", "ow_grid")
    assert unpublished("default") == ()


def test_the_instructions_are_10_871s_two_variants() -> None:
    """977 and 996 characters under `default` (10:2596's frozen baseline)."""
    assert len(instructions("default", corpus_resolves=True)) == 977
    assert len(instructions("default", corpus_resolves=False)) == 996
    assert "NO DEFAULT CORPUS" in instructions("default", corpus_resolves=False)
    assert "If deferred: " in instructions("full", corpus_resolves=True)


def test_an_unknown_profile_is_refused_with_the_known_ones() -> None:
    with pytest.raises(ConfigError, match="default, full"):
        tools_list("everything", compact=True, corpus_resolves=True)


def test_a_listing_pinned_to_another_catalogue_is_refused(tmp_path: Path) -> None:
    stale = load_listing(_copy(tmp_path, catalogue_sha256="0" * 64))
    (finding,) = check(stale)
    assert "pins a catalogue other than" in finding


def test_a_listing_missing_a_variant_or_a_version_is_named(tmp_path: Path) -> None:
    document = json.loads(listing_path().read_text(encoding="utf-8"))
    del document["variants"]["ow_open"]["compact"]
    target = tmp_path / LISTING_NAME
    target.write_text(json.dumps(document), encoding="utf-8")
    assert "ow_open: no compact form" in check(load_listing(target))
    #  Its own directory: `load_listing` is memoised by path, one read per process (11 section
    #  2.6 rule 2), so a second document at the first one's path would be the first one.
    (tmp_path / "newer").mkdir()
    newer = load_listing(_copy(tmp_path / "newer", version=2))
    assert any("version 2" in one for one in check(newer))


def test_an_unreadable_listing_is_a_named_config_error(tmp_path: Path) -> None:
    broken = tmp_path / LISTING_NAME
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError, match="not a readable MCP listing"):
        load_listing(broken)


def test_the_module_imports_nothing_from_omniweave() -> None:
    import ast  # noqa: PLC0415 -- this test's only use
    from pathlib import Path  # noqa: PLC0415

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    roots = {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    } | {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
         for alias in node.names}  # fmt: skip
    assert "omniweave" not in roots
