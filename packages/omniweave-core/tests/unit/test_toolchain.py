"""The `tools/toolchains.toml` reader: two tables, six-plus-four keys, and every refusal named.

The register exists because the digest has to be in-tree and in the wheel -- "if the digest were
fetched alongside the bundle, verifying it would prove only that the bundle matches itself"
(11-repo-layout.md section 1.7). Everything asserted here follows from that sentence: a row that
parses but carries no digest, a truncated digest, a digest under a mistyped key, or a URL the
register itself could redirect are each a way the file stops being evidence.

The manifest under test is section 3.2's, transcribed byte for byte with its two elided digests
filled out to sixty-four hex, because a reader validated only against a manifest the test wrote
itself is a reader validated against nothing.

`toolchain` is LAZY (G17). Nothing here imports it from an eager module, and nothing here spawns:
W1.6 scopes this module to the manifest reader, so `run()`, node resolution and the process-group
reap have no tests because they have no code.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave_core.errors import ConfigError
from omniweave_core.toolchain import (
    MANIFEST_NAME,
    NODE_KEYS,
    NODE_PLATFORMS,
    RANGE_OPERATORS,
    TOOLCHAIN_KEYS,
    TOOLCHAIN_MANIFEST_SCHEMAS,
    NodeRange,
    parse_manifest,
    read_manifest,
)

BUNDLE_SHA = "sha256:" + "1f0c9a" + "0" * 58
NODE_SHA = "sha256:" + "4b8e11" + "0" * 58

PLAN_MANIFEST = f"""\
# tools/toolchains.toml -- read by omniweave_core.toolchain. It NEVER reads the network.
schema = 1

[[toolchain]]
name = "deck"
version = "0.4.2"
entry = "dist/render.mjs"
node_range = ">=20.11,<23"
bundle_sha256 = "{BUNDLE_SHA}"
bundle_url = "https://github.com/omniweave/omniweave/releases/download/v0.4.2/omniweave-toolchain-deck-0.4.2.tar.gz"

[[node]]
version = "20.18.1"
platform = "linux-x64"
sha256 = "{NODE_SHA}"
url = "https://nodejs.org/dist/v20.18.1/node-v20.18.1-linux-x64.tar.xz"
"""
"""11-repo-layout.md section 3.2's printed manifest, with `1f0c9a...` and `4b8e11...` completed."""

TOOLCHAIN_ROW = {
    "name": "deck",
    "version": "0.4.2",
    "entry": "dist/render.mjs",
    "node_range": ">=20.11,<23",
    "bundle_sha256": BUNDLE_SHA,
    "bundle_url": "https://example.invalid/deck.tar.gz",
}

NODE_ROW = {
    "version": "20.18.1",
    "platform": "linux-x64",
    "sha256": NODE_SHA,
    "url": "https://nodejs.org/dist/v20.18.1/node-v20.18.1-linux-x64.tar.xz",
}


def _render(table: str, row: dict[str, object]) -> str:
    """One TOML table, with backslashes escaped so a value survives the basic-string grammar.

    Without it, a TOML basic string decodes a backslash-r pair into a carriage return, so the
    one spelling a Windows author is most likely to type arrives as a path with a control
    character in it and never as a backslash -- and the test would be asserting about a value
    it never wrote, which is how a validation test passes vacuously.
    """
    escaped = {key: str(value).replace("\\", "\\\\") for key, value in row.items()}
    body = "\n".join(f'{key} = "{value}"' for key, value in escaped.items())
    return f"[[{table}]]\n{body}\n"


def _manifest(
    *,
    toolchain: dict[str, object] | None = None,
    node: dict[str, object] | None = None,
    schema: str = "schema = 1\n",
) -> str:
    """A minimal register with one row per table, either of which a test may perturb."""
    return (
        schema
        + _render("toolchain", {**TOOLCHAIN_ROW, **(toolchain or {})})
        + _render("node", {**NODE_ROW, **(node or {})})
    )


def _parse(text: str) -> object:
    return parse_manifest(text, source="tools/toolchains.toml")


def _refusal(text: str) -> str:
    with pytest.raises(ConfigError) as caught:
        _parse(text)
    assert caught.value.fix, "every OwError names the exact command that clears it"
    return str(caught.value)


# ---------------------------------------------------------------------------
# The manifest the plan prints
# ---------------------------------------------------------------------------


def test_the_manifest_11_section_3_2_prints_parses_into_both_tables() -> None:
    """Content, not shape: every field of both rows is checked against the printed source.

    The two tables exist because the app is ours and the runtime is not -- one platform-independent
    `[[toolchain]]` row because esbuild emits one file and the bundle carries no binary, and one
    `[[node]]` row per platform because omniweave never repackages Node.
    """
    manifest = parse_manifest(PLAN_MANIFEST, source="tools/toolchains.toml")
    assert manifest.schema == 1
    assert len(manifest.toolchains) == 1
    assert len(manifest.nodes) == 1

    deck = manifest.toolchain("deck")
    assert deck is not None
    assert deck.version == "0.4.2"
    assert deck.entry == "dist/render.mjs"
    assert deck.node_range.text == ">=20.11,<23"
    assert deck.bundle_sha256 == BUNDLE_SHA
    assert deck.bundle_url.endswith("omniweave-toolchain-deck-0.4.2.tar.gz")

    node = manifest.node("20.18.1", "linux-x64")
    assert node is not None
    assert node.sha256 == NODE_SHA
    assert node.url.startswith("https://nodejs.org/dist/v20.18.1/")
    assert manifest.nodes_for("linux-x64") == (node,)
    assert manifest.nodes_for("win-x64") == ()
    assert manifest.toolchain("video") is None
    assert manifest.node("20.18.1", "win-x64") is None


def test_read_manifest_reads_a_file_and_names_it_in_every_message(tmp_path: Path) -> None:
    path = tmp_path / MANIFEST_NAME
    path.write_text(PLAN_MANIFEST, encoding="utf-8")
    manifest = read_manifest(path)
    assert manifest.source == str(path)
    assert manifest.toolchain("deck") is not None


def test_an_unreadable_register_is_a_named_refusal_and_never_an_oserror(tmp_path: Path) -> None:
    """11-repo-layout.md section 2.6 rule 3, the rule `errors.load_register` already follows for
    `codes.toml`: an unparseable in-tree register is a named `OwError` carrying the command that
    clears it, never a `KeyError`, a `FileNotFoundError` or a silent empty default."""
    with pytest.raises(ConfigError) as caught:
        read_manifest(tmp_path / "absent.toml")
    assert caught.value.fix


def test_invalid_toml_is_a_refusal_that_quotes_the_parser(tmp_path: Path) -> None:
    path = tmp_path / MANIFEST_NAME
    path.write_text("schema = 1\n[[toolchain]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        read_manifest(path)


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------


def test_the_schema_key_is_required() -> None:
    assert "schema" in _refusal(_manifest(schema=""))


@pytest.mark.parametrize("value", ["schema = true\n", 'schema = "1"\n', "schema = 1.0\n"])
def test_a_non_integer_schema_is_refused(value: str) -> None:
    """`true` is an `int` subclass in Python and would otherwise read as `schema = 1`."""
    assert "schema" in _refusal(_manifest(schema=value))


def test_a_newer_schema_is_refused_with_an_upgrade_as_the_fix() -> None:
    """Read before any row, for the reason `card_schema` is read first (04 section 5.3): a register
    from a newer grammar has the opposite fix from a malformed one -- upgrade, don't edit."""
    with pytest.raises(ConfigError) as caught:
        _parse(_manifest(schema="schema = 2\n"))
    assert "schema = 2" in str(caught.value)
    assert "upgrade" in caught.value.fix
    assert frozenset({1}) == TOOLCHAIN_MANIFEST_SCHEMAS


def test_an_unknown_top_level_key_is_refused() -> None:
    """`tools/` files may not be edited to make a gate pass (section 1.7); a stray table is an edit
    nobody reviewed."""
    assert "registry" in _refusal(_manifest() + '\n[registry]\nurl = "https://x.invalid"\n')


# ---------------------------------------------------------------------------
# [[toolchain]] rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", sorted(TOOLCHAIN_KEYS))
def test_every_toolchain_key_is_required_and_its_absence_is_named(missing: str) -> None:
    """All six, one test each. A row that parsed with `bundle_sha256` absent would be a Toolchain
    with no digest, which is the one thing this file exists to prevent."""
    row = {key: value for key, value in TOOLCHAIN_ROW.items() if key != missing}
    text = "schema = 1\n" + _render("toolchain", row)
    message = _refusal(text)
    assert missing in message
    assert "[[toolchain]][0]" in message


def test_an_unknown_toolchain_key_is_a_hard_error_naming_it() -> None:
    """The typo case, and the reason the rule is "hard error" rather than "ignore": a mistyped
    `bundle_sha_256` under an ignoring reader reads as "no digest declared"."""
    message = _refusal(_manifest(toolchain={"bundle_sha_256": BUNDLE_SHA}))
    assert "bundle_sha_256" in message


@pytest.mark.parametrize(
    "name", ["Deck", "deck-2", "deck/../etc", "1deck", "", "_shared", "a" * 33]
)
def test_a_toolchain_name_must_be_a_lower_case_bare_identifier(name: str) -> None:
    """A directory name under `toolchains/`, and the suffix of `io.service("toolchain:<name>")`.

    `_shared` is refused deliberately: section 1.6's tree has it as a directory of shared
    source, not as a Toolchain, and it is never a `[[toolchain]]` row.
    """
    assert _refusal(_manifest(toolchain={"name": name}))


@pytest.mark.parametrize(
    "entry",
    [
        "/etc/passwd",
        "../../../etc/passwd",
        "dist/../../render.mjs",
        "dist\\render.mjs",
        "dist//render.mjs",
        "./render.mjs",
        "",
    ],
)
def test_an_entry_that_escapes_the_verified_bundle_is_refused(entry: str) -> None:
    """The entry is joined onto a digest-pinned install root and handed to `node`.

    A `..` or a leading `/` names a file outside the bundle whose sha256 was just verified, which is
    the digest being checked and then not used. A backslash is refused because Windows invokes
    `node.exe` against the entry **directly, never a `.cmd`/`.bat` shim** (section 3.2's record of
    codegraph's `EINVAL` scar), so the ladder resolves a POSIX path or nothing.
    """
    assert _refusal(_manifest(toolchain={"entry": entry}))


def test_a_nested_but_contained_entry_is_accepted() -> None:
    manifest = _parse(_manifest(toolchain={"entry": "dist/bundles/render.mjs"}))
    assert manifest.toolchain("deck").entry == "dist/bundles/render.mjs"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "digest",
    [
        "1f0c9a" + "0" * 58,
        "sha256:1f0c9a",
        "sha256:" + "1F0C9A" + "0" * 58,
        "sha256:" + "0" * 63,
        "sha256:" + "0" * 65,
        "sha512:" + "0" * 64,
        "sha256:" + "g" * 64,
    ],
)
def test_a_digest_that_is_not_the_full_lower_case_sha256_is_refused(digest: str) -> None:
    """ "The digest is the *full* sha256, not a 16-hex prefix. 64 bits is weak against intent."

    The length check is that sentence mechanised. A truncated digest is refused where a reviewer is
    looking rather than compared against a truncation of the real one at spawn time.
    """
    assert _refusal(_manifest(toolchain={"bundle_sha256": digest}))
    assert _refusal(_manifest(node={"sha256": digest}))


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/omniweave/deck.tar.gz",
        "file:///tmp/deck.tar.gz",
        "ftp://example.invalid/deck.tar.gz",
        "github.com/omniweave/deck.tar.gz",
    ],
)
def test_only_an_https_url_is_accepted(url: str) -> None:
    """`$OMNIWEAVE_HOME/toolchains/` is a user-writable directory holding executable code and the
    digest is the only thing between a compromised home directory and arbitrary execution.

    Refusing a non-https URL costs nothing -- both printed URLs are https -- and removes the shape
    where a register edit alone redirects an install. Not printed in the plan; a filled silence.
    """
    assert _refusal(_manifest(toolchain={"bundle_url": url}))
    assert _refusal(_manifest(node={"url": url}))


def test_two_toolchain_rows_with_one_name_are_refused() -> None:
    """Two rows named `deck` make "the digest" ambiguous, and an ambiguous digest is the same defect
    as an absent one."""
    text = (
        "schema = 1\n" + _render("toolchain", TOOLCHAIN_ROW) + _render("toolchain", TOOLCHAIN_ROW)
    )
    assert "deck" in _refusal(text)


# ---------------------------------------------------------------------------
# [[node]] rows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("missing", sorted(NODE_KEYS))
def test_every_node_key_is_required(missing: str) -> None:
    row = {key: value for key, value in NODE_ROW.items() if key != missing}
    text = "schema = 1\n" + _render("node", row)
    message = _refusal(text)
    assert missing in message
    assert "[[node]][0]" in message


def test_a_node_row_carries_no_entry_and_no_range() -> None:
    """A `[[node]]` row is a download to verify, not a program to run. The asymmetry with
    `TOOLCHAIN_KEYS` is the two-owner split, mechanised."""
    assert frozenset({"version", "platform", "sha256", "url"}) == NODE_KEYS
    assert "entry" not in NODE_KEYS
    assert "node_range" not in NODE_KEYS
    assert _refusal(_manifest(node={"entry": "dist/render.mjs"}))


def test_the_six_platform_tags_are_the_six_the_charter_priced() -> None:
    """Derived, not printed: vendoring Node as platform-tagged wheels was rejected at "multiplies
    the release matrix by six", where "recording six upstream digests costs six lines".

    Six rows means six platforms. The tags themselves are nodejs.org's own asset names. Recorded as
    a filled silence in `NODE_PLATFORMS`' docstring, and asserted here so a seventh cannot arrive
    without someone reading that paragraph.
    """
    assert len(NODE_PLATFORMS) == 6
    assert tuple(sorted(NODE_PLATFORMS)) == NODE_PLATFORMS
    assert set(NODE_PLATFORMS) == {
        "linux-x64",
        "linux-arm64",
        "darwin-x64",
        "darwin-arm64",
        "win-x64",
        "win-arm64",
    }


@pytest.mark.parametrize("platform", sorted(NODE_PLATFORMS))
def test_each_declared_platform_tag_is_accepted(platform: str) -> None:
    manifest = _parse(_manifest(node={"platform": platform}))
    assert manifest.node("20.18.1", platform) is not None  # type: ignore[union-attr]


@pytest.mark.parametrize("platform", ["linux-armv7l", "windows-x64", "linux_x64", "LINUX-X64"])
def test_an_undeclared_platform_tag_is_refused_and_the_message_lists_the_six(
    platform: str,
) -> None:
    """`linux-armv7l` is the one an author would plausibly reach for, and it is the seventh tag
    the charter's six-row pricing does not admit.
    """
    message = _refusal(_manifest(node={"platform": platform}))
    assert platform in message
    assert "linux-x64" in message


def test_an_empty_platform_tag_is_refused_as_an_empty_string_and_not_as_an_unknown_tag() -> None:
    """The required-and-non-empty check runs first, so the message names the key, not the domain."""
    assert "platform is not a non-empty string" in _refusal(_manifest(node={"platform": ""}))


def test_two_node_rows_for_one_version_and_platform_are_refused() -> None:
    """`ow doctor --runtime` re-verifies an installed node against its row; two rows for one pair
    would let it verify against whichever the reader reached first."""
    text = "schema = 1\n" + _render("node", NODE_ROW) + _render("node", NODE_ROW)
    assert "20.18.1 linux-x64" in _refusal(text)


def test_two_node_rows_differing_only_in_platform_are_both_kept() -> None:
    """The register's whole shape: one runtime per platform, six lines, no matrix in the wheel."""
    other = {**NODE_ROW, "platform": "darwin-arm64"}
    manifest = _parse("schema = 1\n" + _render("node", NODE_ROW) + _render("node", other))
    assert len(manifest.nodes) == 2  # type: ignore[union-attr]
    assert manifest.nodes_for("darwin-arm64")[0].platform == "darwin-arm64"  # type: ignore[union-attr]


def test_an_empty_register_is_legal() -> None:
    """`toolchains/video/` ships **no bundle** at release 1, and at P1 neither ships. A register
    with a schema and no rows is a register that pins nothing, which is a true statement about a
    tree with no built bundles -- not a fault. `tools/check_versions.py` owns the roster count."""
    manifest = _parse("schema = 1\n")
    assert manifest.toolchains == ()  # type: ignore[union-attr]
    assert manifest.nodes == ()  # type: ignore[union-attr]


@pytest.mark.parametrize(
    "text",
    [
        'schema = 1\ntoolchain = "deck"\n',
        'schema = 1\n[toolchain]\nname = "deck"\n',
        'schema = 1\nnode = ["20.18.1"]\n',
    ],
)
def test_a_table_that_is_not_an_array_of_tables_is_refused(text: str) -> None:
    """`[toolchain]` and `[[toolchain]]` are one character apart in TOML and mean different things;
    the second reads as a single table rather than a one-element array."""
    assert _refusal(text)


# ---------------------------------------------------------------------------
# node_range
# ---------------------------------------------------------------------------


def test_the_printed_range_admits_exactly_the_node_versions_it_names() -> None:
    """`">=20.11,<23"`, the one range the plan prints, as a truth table over real Node releases.

    `20.11.0` is the boundary case that a naive tuple comparison gets wrong: `(20, 11, 0)` against
    `(20, 11)` makes the shorter one smaller, so `>=20.11` would reject the very release it was
    written to admit. Both sides are zero-padded for that reason.
    """
    parsed = NodeRange(text=">=20.11,<23", clauses=())
    parsed = _parse(_manifest()).toolchain("deck").node_range  # type: ignore[union-attr]
    for version in ("20.11", "20.11.0", "20.18.1", "22.9.0", "22.99.99"):
        assert parsed.accepts(version), version
    for version in ("18.20.4", "20.10.9", "20.9", "23.0.0", "24.1.0"):
        assert not parsed.accepts(version), version


def test_a_range_accepts_the_v_prefixed_form_node_version_actually_prints() -> None:
    """`node --version` prints `v20.18.1`. The ladder compares what the binary said."""
    parsed = _parse(_manifest()).toolchain("deck").node_range  # type: ignore[union-attr]
    assert parsed.accepts("v20.18.1")
    assert not parsed.accepts("v23.1.0")


@pytest.mark.parametrize("junk", ["", "not-a-version", "20.x", "v", "20.11.1.4", "latest"])
def test_an_unparseable_candidate_version_is_false_rather_than_an_exception(junk: str) -> None:
    """The input is whatever an unknown `node` binary printed. An unrecognisable answer is a reason
    not to use that binary, not a reason to fail the run -- section 3.2's ladder falls through to
    "the target is PRUNED FROM THE PLAN with a report. Never an ImportError"."""
    parsed = _parse(_manifest()).toolchain("deck").node_range  # type: ignore[union-attr]
    assert parsed.accepts(junk) is False


@pytest.mark.parametrize("operator", sorted(RANGE_OPERATORS))
def test_each_declared_operator_parses_and_compares(operator: str) -> None:
    parsed = _parse(_manifest(toolchain={"node_range": f"{operator}20.11"}))
    clause = parsed.toolchain("deck").node_range.clauses[0]  # type: ignore[union-attr]
    assert clause.operator == operator
    assert clause.version == (20, 11)


def test_the_operator_table_is_matched_longest_first() -> None:
    """`>=` before `>`, or `>=20.11` parses as `>` applied to `=20.11` and fails with the wrong
    message. The tuple's order is the mechanism, so it is asserted rather than assumed."""
    assert RANGE_OPERATORS.index(">=") < RANGE_OPERATORS.index(">")
    assert RANGE_OPERATORS.index("<=") < RANGE_OPERATORS.index("<")
    parsed = _parse(_manifest(toolchain={"node_range": ">=20.11"}))
    clause = parsed.toolchain("deck").node_range.clauses[0]  # type: ignore[union-attr]
    assert clause.operator == ">="
    assert clause.accepts((20, 11, 0))


def test_a_range_is_a_conjunction_of_every_clause() -> None:
    parsed = _parse(_manifest(toolchain={"node_range": ">=20.11,<23,!=21.0.0"}))
    node_range = parsed.toolchain("deck").node_range  # type: ignore[union-attr]
    assert len(node_range.clauses) == 3
    assert node_range.accepts("22.0.0")
    assert not node_range.accepts("21.0.0")
    assert not node_range.accepts("23.0.0")


@pytest.mark.parametrize(
    "text",
    [
        "20.11",
        "^20.11",
        "~20.11",
        ">=20.11 || >=22",
        ">=20.11 - 22",
        ">=20.x",
        ">=",
        ">=20.11,",
        ",",
        " ",
        ">=20.11,<23,",
        "=>20.11",
    ],
)
def test_a_range_outside_the_printed_grammar_is_refused_at_read_time(text: str) -> None:
    """npm's semver dialect is deliberately not implemented: none of `^`, `~`, `||`, `x` or hyphen
    ranges appears anywhere in the plan, and a range this reader accepts but `run()` misreads would
    resolve a Node the bundle was never built against.

    Refused at read time, where a human is looking at a hand-written register, rather than at spawn
    time on a user's machine.
    """
    assert _refusal(_manifest(toolchain={"node_range": text}))


@pytest.mark.parametrize("version", ["20.11.1-rc.1", "20.011", "v20.11", "20.11.1+build", "20."])
def test_a_declared_version_outside_the_plain_dotted_form_is_refused(version: str) -> None:
    """`[[toolchain]] version` is checked against `RELEASE` by `tools/check_versions.py`, which is a
    plain semver, and a `[[node]] version` names an asset on nodejs.org. Neither is a range."""
    assert _refusal(_manifest(toolchain={"version": version}))
    assert _refusal(_manifest(node={"version": version}))


# ---------------------------------------------------------------------------
# The module's own shape
# ---------------------------------------------------------------------------


def test_the_key_sets_are_the_ones_section_3_2_prints() -> None:
    """Transcribed, and asserted so a later edit has to disagree with the plan out loud."""
    assert (
        frozenset({"name", "version", "entry", "node_range", "bundle_sha256", "bundle_url"})
        == TOOLCHAIN_KEYS
    )
    assert MANIFEST_NAME == "toolchains.toml"


def test_the_reader_imports_no_subprocess_and_opens_no_socket() -> None:
    """ "It NEVER reads the network" (section 3.2's manifest header), and W1.6 is the reader only.

    `toolchain.py` is one of two modules `pyproject.toml` permits `subprocess` in; the allowance is
    unused until `run()` lands, and the module source is the witness. A grep rather than an import
    trace because `subprocess` is stdlib and may already be in `sys.modules` for another reason.
    """
    source = (
        Path(__file__).resolve().parents[2] / "src" / "omniweave_core" / "toolchain.py"
    ).read_text(encoding="utf-8")
    for banned in ("import subprocess", "import socket", "import urllib", "import http"):
        assert banned not in source, f"toolchain.py carries `{banned}` at W1.6"
