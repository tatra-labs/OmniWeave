"""`canonical_uri`, `content_digest`, `config_digest` and `semantic_digest`.

`canonical_uri` is asserted idempotent on every locator form, because a `unit_uri` is the
roster's primary key and the join key for every downstream row: two spellings of one locator
must not make two units. The digests are asserted from a second interpreter for the same reason
`core/canonical`'s are.

Specified in 05-ingest-and-routing.md section 1.2, 03-document-model.md section 6.4 and
02-architecture.md sections 8.3 and 8.4.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess  # noqa: TID251 - a second interpreter is the only witness for PYTHONHASHSEED.
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from omniweave_core.canonical import ow128, sha256_canonical
from omniweave_core.identity import (
    canonical_uri,
    config_digest,
    content_digest,
    semantic_digest,
)

WINDOWS = sys.platform == "win32"


@dataclass(frozen=True, slots=True)
class FakeLocator:
    """The two fields `canonical_uri` reads off `omniweave_ports.ports.Locator`
    (04-driver-system.md section 1.3). Standing in for it keeps this test independent of the
    Ports module's own build order."""

    scheme: str
    target: str
    cursor: str | None = None
    since_ns: int | None = None


# --------------------------------------------------------------------------------------------
# canonical_uri -- the file / dir form
# --------------------------------------------------------------------------------------------


def test_the_file_form_is_a_path_and_carries_no_scheme(tmp_path: Path) -> None:
    """05-ingest-and-routing.md section 1.1's `Locator.target` row: "`canonical_uri()`'s PATH
    form of `ref`" -- realpath, normcase, forward slashes."""
    uri = canonical_uri(tmp_path / "docs" / "q3-10k.pdf")
    assert not uri.startswith("file:")
    assert "\\" not in uri
    assert uri.endswith("/docs/q3-10k.pdf")


def test_the_file_form_is_idempotent(tmp_path: Path) -> None:
    once = canonical_uri(tmp_path / "a" / "b.pdf")
    assert canonical_uri(once) == once
    assert canonical_uri(canonical_uri(once)) == once


def test_a_str_a_path_and_a_file_locator_agree(tmp_path: Path) -> None:
    target = tmp_path / "a.pdf"
    assert (
        canonical_uri(target)
        == canonical_uri(str(target))
        == canonical_uri(FakeLocator("file", str(target)))
    )


def test_the_locator_target_and_the_connector_local_id_are_joined(tmp_path: Path) -> None:
    """05 section 1.1: `id` is "a path relative to `Locator.target`", and the host mints
    `unit_uri = canonical_uri(locator, id)`."""
    locator = FakeLocator("file", str(tmp_path))
    assert canonical_uri(locator, "docs/q3-10k.pdf") == canonical_uri(
        tmp_path / "docs" / "q3-10k.pdf"
    )


def test_an_absolute_id_cannot_re_root_the_locator(tmp_path: Path) -> None:
    """`Path(root) / "/abs"` silently yields `/abs` -- an escape from `[roots] source` before
    `confine()` ever runs."""
    locator = FakeLocator("file", str(tmp_path))
    for escape in ("/etc/passwd", "\\windows\\system32", "C:/windows"):
        with pytest.raises(ValueError, match="not relative"):
            canonical_uri(locator, escape)


def test_a_relative_path_is_refused(tmp_path: Path) -> None:
    """An identity that reads the process working directory is the bug 08-runtime.md section
    1.3 bans `os.getcwd()` for. The plan is silent here; refusing is the conservative reading."""
    del tmp_path
    with pytest.raises(ValueError, match="relative"):
        canonical_uri("docs/q3-10k.pdf")


def test_an_empty_path_is_refused() -> None:
    with pytest.raises(ValueError, match="empty"):
        canonical_uri("")


def test_dot_segments_are_resolved(tmp_path: Path) -> None:
    assert canonical_uri(tmp_path / "a" / ".." / "b.pdf") == canonical_uri(tmp_path / "b.pdf")


@pytest.mark.skipif(not WINDOWS, reason="normcase is identity outside Windows")
def test_normcase_makes_two_windows_spellings_one_row(tmp_path: Path) -> None:
    """05 section 1.2: "`normcase` is what makes `C:\\A\\B.PDF` and `c:/a/b.pdf` one row"."""
    upper = str(tmp_path / "A" / "B.PDF")
    lower = str(tmp_path / "A" / "B.PDF").lower().replace("\\", "/")
    assert canonical_uri(upper) == canonical_uri(lower)
    assert canonical_uri(upper) == canonical_uri(upper).lower()


@pytest.mark.skipif(WINDOWS, reason="a POSIX path is case-sensitive")
def test_case_is_preserved_where_the_filesystem_is_case_sensitive(tmp_path: Path) -> None:
    assert canonical_uri(tmp_path / "A.PDF") != canonical_uri(tmp_path / "a.pdf")


@pytest.mark.skipif(not WINDOWS, reason="the extended-length prefix is a Windows spelling")
def test_the_extended_length_prefix_is_stripped(tmp_path: Path) -> None:
    plain = str(tmp_path / "a.pdf")
    assert canonical_uri("\\\\?\\" + plain) == canonical_uri(plain)
    assert "?" not in canonical_uri("\\\\?\\" + plain)


# --------------------------------------------------------------------------------------------
# canonical_uri -- the url form
# --------------------------------------------------------------------------------------------

URL_LOCATOR = FakeLocator("https", "https://example.com/")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("HTTPS://Example.COM/a", "https://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("https://example.com", "https://example.com/"),
        ("https://example.com/a#frag", "https://example.com/a"),
        ("https://example.com/%7Euser", "https://example.com/~user"),
        ("https://example.com/a%2fb", "https://example.com/a%2Fb"),
        ("https://example.com/a b", "https://example.com/a%20b"),
        ("https://example.com/?b=2&a=1", "https://example.com/?a=1&b=2"),
        ("https://example.com/?z&a=1", "https://example.com/?a=1&z"),
        ("https://example.com/ü", "https://example.com/%C3%BC"),
    ],
)
def test_the_url_row_of_the_identity_table(raw: str, expected: str) -> None:
    """05 section 1.2: scheme+host lower-cased, default port dropped, path percent-normalised,
    fragment dropped, query kept and sorted by key."""
    assert canonical_uri(FakeLocator("https", raw)) == expected


def test_a_non_default_port_is_kept() -> None:
    assert canonical_uri(FakeLocator("https", "https://example.com:8443/a")) == (
        "https://example.com:8443/a"
    )
    assert canonical_uri(FakeLocator("http", "http://example.com:80/a")) == "http://example.com/a"
    assert canonical_uri(FakeLocator("http", "http://example.com:443/a")) == (
        "http://example.com:443/a"
    )


def test_a_fragment_never_changes_the_bytes_but_a_query_usually_does() -> None:
    base = canonical_uri(FakeLocator("https", "https://example.com/a"))
    assert canonical_uri(FakeLocator("https", "https://example.com/a#one")) == base
    assert canonical_uri(FakeLocator("https", "https://example.com/a#two")) == base
    assert canonical_uri(FakeLocator("https", "https://example.com/a?q=1")) != base


def test_repeated_query_keys_keep_their_given_order() -> None:
    assert canonical_uri(FakeLocator("https", "https://example.com/?a=2&a=1")) == (
        "https://example.com/?a=2&a=1"
    )


def test_an_encoded_slash_stays_distinct_from_a_real_one() -> None:
    assert canonical_uri(FakeLocator("https", "https://example.com/a%2Fb")) != canonical_uri(
        FakeLocator("https", "https://example.com/a/b")
    )


@pytest.mark.parametrize(
    "raw",
    [
        "https://example.com/a b?z=1&a=%7e#frag",
        "HTTPS://EXAMPLE.com:443/%41/ü?b=%2f&a=1",
        "https://user:pw@example.com/a",
        "https://[2001:db8::1]:443/a",
    ],
)
def test_the_url_form_is_idempotent(raw: str) -> None:
    once = canonical_uri(FakeLocator("https", raw))
    assert canonical_uri(FakeLocator("https", once)) == once


def test_userinfo_is_preserved_rather_than_silently_merged() -> None:
    """The plan is silent on userinfo. Dropping it would merge two units a server may answer
    differently; keeping credentials out of a locator is `resolve_locator()`'s job."""
    assert canonical_uri(FakeLocator("https", "https://u:p@example.com/a")) == (
        "https://u:p@example.com/a"
    )
    assert canonical_uri(FakeLocator("https", "https://u:p@example.com/a")) != canonical_uri(
        FakeLocator("https", "https://v:p@example.com/a")
    )


def test_an_ipv6_host_keeps_its_brackets() -> None:
    assert canonical_uri(FakeLocator("https", "https://[2001:DB8::1]/a")) == (
        "https://[2001:db8::1]/a"
    )


def test_a_url_with_no_host_is_refused() -> None:
    with pytest.raises(ValueError, match="no host"):
        canonical_uri(FakeLocator("https", "https:///a"))


def test_a_url_whose_scheme_contradicts_the_locator_is_refused() -> None:
    with pytest.raises(ValueError, match="not a https URL"):
        canonical_uri(FakeLocator("https", "http://example.com/a"))


def test_a_relative_ref_resolves_against_the_locator_target() -> None:
    assert canonical_uri(URL_LOCATOR, "docs/a.pdf") == "https://example.com/docs/a.pdf"


# --------------------------------------------------------------------------------------------
# canonical_uri -- the connector and stream forms
# --------------------------------------------------------------------------------------------


def test_the_connector_form_is_connector_then_stable_id() -> None:
    """05 section 1.2: `<connector>://<stable connector id>`. A title or a folder path is not
    an identity; both move."""
    assert canonical_uri(FakeLocator("drive", ""), "1a2B3c") == "drive://1a2B3c"
    assert canonical_uri(FakeLocator("slack", ""), "C024BE7LR/1757030400.000200") == (
        "slack://C024BE7LR/1757030400.000200"
    )
    assert canonical_uri(FakeLocator("imessage", "chat42")) == "imessage://chat42"


def test_the_connector_local_half_is_recoverable_by_inspection() -> None:
    """05 section 1.1: a connector recovers its own id from `UnitRef.uri` by inspection, which
    is possible BECAUSE the connector form is `<connector>://<id>`."""
    uri = canonical_uri(FakeLocator("drive", ""), "1a2B3c")
    connector, _, ident = uri.partition("://")
    assert (connector, ident) == ("drive", "1a2B3c")


def test_a_connector_id_cannot_forge_a_container_child_fragment() -> None:
    forged = canonical_uri(FakeLocator("drive", ""), "abc#zip/evil")
    assert "#" not in forged
    assert forged == "drive://abc%23zip/evil"


def test_the_connector_form_is_idempotent() -> None:
    once = canonical_uri(FakeLocator("drive", ""), "a b#c")
    connector, _, ident = once.partition("://")
    assert canonical_uri(FakeLocator(connector, ""), ident) == once


def test_the_stream_form_is_its_own_content() -> None:
    digest = "9f" * 32
    assert canonical_uri(FakeLocator("stream", ""), digest) == f"stream://sha256/{digest}"
    assert canonical_uri(FakeLocator("stream", digest)) == f"stream://sha256/{digest}"


@pytest.mark.parametrize("bad", ["", "9F" * 32, "9f" * 31, "z" * 64])
def test_a_stream_uri_needs_a_real_sha256(bad: str) -> None:
    with pytest.raises(ValueError, match="lowercase sha256"):
        canonical_uri(FakeLocator("stream", bad))


def test_an_empty_scheme_is_refused() -> None:
    with pytest.raises(ValueError, match="no scheme"):
        canonical_uri(FakeLocator("", "x"))


def test_an_object_that_is_neither_a_path_nor_a_locator_is_refused() -> None:
    with pytest.raises(TypeError, match="neither a path nor a Locator"):
        canonical_uri(object())  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# canonical_uri -- the container-child fragment
# --------------------------------------------------------------------------------------------


def test_the_container_child_appends_a_fragment(tmp_path: Path) -> None:
    parent = canonical_uri(tmp_path / "mail.mbox")
    child = canonical_uri(tmp_path / "mail.mbox", child_kind="att", child_path="report.pdf")
    assert child == f"{parent}#att/report.pdf"


def test_a_member_named_a_hash_b_slash_c_cannot_forge_a_sibling(tmp_path: Path) -> None:
    """05 section 1.2, verbatim: `/` `#` `?` `%` and every byte outside `[A-Za-z0-9._~-]` are
    escaped, "so a member named `a#b/c` cannot forge a sibling's identity"."""
    forged = canonical_uri(tmp_path / "x.zip", child_kind="zip", child_path="a#b/c")
    honest = canonical_uri(tmp_path / "x.zip", child_kind="zip", child_path="a")
    assert forged.count("#") == 1
    assert forged.endswith("#zip/a%23b%2Fc")
    # An unescaped implementation would emit `<parent>#zip/a#b/c`, whose FIRST fragment reads
    # as `zip/a` -- the sibling's whole identity.
    assert forged.split("#", 1)[1] != honest.split("#", 1)[1]
    assert forged != honest


def test_a_non_utf8_member_name_is_representable(tmp_path: Path) -> None:
    child = canonical_uri(tmp_path / "x.zip", child_kind="zip", child_path=b"\xff\xfe.txt")
    assert child.endswith("#zip/%FF%FE.txt")


def test_two_member_names_never_collide_after_encoding(tmp_path: Path) -> None:
    names = ["a/b", "a%2Fb", "a b", "a+b", "a", "A"]
    encoded = {
        canonical_uri(tmp_path / "x.zip", child_kind="zip", child_path=name) for name in names
    }
    assert len(encoded) == len(names)


def test_a_long_fragment_is_truncated_and_stays_distinct(tmp_path: Path) -> None:
    """05 section 1.2: over 512 bytes, the first 400 encoded bytes plus
    `~<sha256(full path)[:16]>` -- which bounds `unit_uri` AND keeps two long members
    distinct."""
    parent = canonical_uri(tmp_path / "x.zip")
    long_a = "deep/" * 200 + "a.txt"
    long_b = "deep/" * 200 + "b.txt"
    uri_a = canonical_uri(tmp_path / "x.zip", child_kind="zip", child_path=long_a)
    uri_b = canonical_uri(tmp_path / "x.zip", child_kind="zip", child_path=long_b)
    frag_a = uri_a[len(parent) + 1 :]
    assert len(frag_a) == 400 + 1 + 16
    assert frag_a[400] == "~"
    assert uri_a != uri_b
    assert not frag_a[:400].endswith("%")


def test_the_truncation_never_cuts_a_percent_escape(tmp_path: Path) -> None:
    # 'ü' encodes to two escapes (six characters); the cut lands mid-escape for some lengths.
    for extra in range(6):
        path = "ü" * 100 + "x" * extra
        uri = canonical_uri(tmp_path / "x.zip", child_kind="zip", child_path=path)
        head = uri.rsplit("#", 1)[1].split("~")[0]
        assert "%" not in head[-2:] or head[-3] == "%"


@pytest.mark.parametrize("kind", ["att", "zip", "msg", "part"])
def test_the_four_container_child_kinds(kind: str, tmp_path: Path) -> None:
    uri = canonical_uri(tmp_path / "x", child_kind=kind, child_path="m")
    assert uri.endswith(f"#{kind}/m")


def test_an_unknown_child_kind_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not one of"):
        canonical_uri(tmp_path / "x", child_kind="evil", child_path="m")


def test_child_kind_and_child_path_are_given_together(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="together"):
        canonical_uri(tmp_path / "x", child_kind="zip")
    with pytest.raises(ValueError, match="together"):
        canonical_uri(tmp_path / "x", child_path="m")


def test_an_empty_child_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        canonical_uri(tmp_path / "x", child_kind="zip", child_path="")


# --------------------------------------------------------------------------------------------
# content_digest
# --------------------------------------------------------------------------------------------


def test_content_digest_is_a_sixteen_byte_ow128() -> None:
    digest = content_digest(3, 1, "hello", {"level": 2})
    assert isinstance(digest, bytes)
    assert len(digest) == 16


def test_content_digest_is_deterministic_within_a_process() -> None:
    args = (3, 1, "hello", {"b": 1, "a": 2})
    assert content_digest(*args) == content_digest(3, 1, "hello", {"a": 2, "b": 1})


def test_none_text_and_empty_text_are_not_the_same_content() -> None:
    """03-document-model.md section 6.4's own annotation: `None != ""`. A container has
    `text IS NULL`; a leaf with no characters does not."""
    assert content_digest(3, 1, None) != content_digest(3, 1, "")


def test_text_is_nfc_normalised_so_a_decomposition_is_not_a_new_block() -> None:
    composed = "\u00e9"  # é
    decomposed = "e\u0301"  # e + COMBINING ACUTE
    assert composed != decomposed
    assert content_digest(3, 1, composed) == content_digest(3, 1, decomposed)


def test_children_are_a_merkle_in_ord_order() -> None:
    """A reordering of siblings changes the PARENT's digest and not the children's."""
    a = content_digest(3, 1, "a")
    b = content_digest(3, 1, "b")
    assert content_digest(9, 1, None, None, [a, b]) != content_digest(9, 1, None, None, [b, a])
    assert content_digest(9, 1, None, None, [a]) != content_digest(9, 1, None, None, [a, b])
    assert content_digest(9, 1, None, None, []) != content_digest(9, 1, None, None, [a])


def test_a_child_that_is_not_a_sixteen_byte_digest_is_refused() -> None:
    for bad in (b"", b"short", b"x" * 17, "sixteen-bytes!!!"):
        with pytest.raises(ValueError, match="16-byte ow128"):
            content_digest(9, 1, None, None, [bad])  # type: ignore[list-item]


def test_kind_and_layer_are_both_digest_inputs() -> None:
    assert content_digest(3, 1, "t") != content_digest(4, 1, "t")
    assert content_digest(3, 1, "t") != content_digest(3, 2, "t")


def test_the_payload_participates_and_absent_is_not_empty() -> None:
    assert content_digest(3, 1, "t", None) != content_digest(3, 1, "t", {})
    assert content_digest(3, 1, "t", {"a": 1}) != content_digest(3, 1, "t", {"a": 2})


def test_content_digest_takes_no_geometry() -> None:
    """03 section 6.4: GEOMETRY IS NOT AN INPUT, so a driver upgrade's bbox jitter cannot
    orphan a document. Asserted on the signature, because a parameter that does not exist is
    the only version of that promise that cannot rot."""
    names = set(inspect.signature(content_digest).parameters)
    assert names == {"kind", "layer", "text", "payload", "children"}
    assert not names & {"quad", "page", "geometry", "bbox", "ord", "block_id", "cite", "addr"}


def test_the_domain_separates_content_from_a_sibling_recipe() -> None:
    same_inputs = [3, 1, "t", "null", []]
    assert content_digest(3, 1, "t") == ow128(b"ow.content.1", same_inputs)
    assert content_digest(3, 1, "t") != ow128(b"ow.layout.1", same_inputs)


# --------------------------------------------------------------------------------------------
# config_digest / semantic_digest and the axis between them
# --------------------------------------------------------------------------------------------

VALUES: dict[str, object] = {
    "limits.max_unit_bytes": 268_435_456,
    "graph.segment_target_tokens": 1200,
    "drivers.enabled": ["parse.pdf.pdfium"],
    "roots.source": "/srv/corpus",
    "runtime.max_workers": 4,
    "observe.otlp_endpoint": None,
}
AXES: dict[str, str] = {
    "limits.max_unit_bytes": "semantic",
    "graph.segment_target_tokens": "semantic",
    "drivers.enabled": "operational",
    "roots.source": "operational",
    "runtime.max_workers": "operational",
    "observe.otlp_endpoint": "operational",
}


def test_config_digest_is_sha256_canonical_over_the_full_config() -> None:
    assert config_digest(VALUES) == sha256_canonical(VALUES)  # type: ignore[arg-type]
    assert len(config_digest(VALUES)) == 64  # type: ignore[arg-type]


def test_config_digest_and_semantic_digest_are_two_different_statements() -> None:
    assert config_digest(VALUES) != semantic_digest(VALUES, AXES)  # type: ignore[arg-type]


def test_semantic_digest_is_the_projection_and_nothing_else() -> None:
    projection = {k: v for k, v in VALUES.items() if AXES[k] == "semantic"}
    assert semantic_digest(VALUES, AXES) == sha256_canonical(projection)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "key", ["drivers.enabled", "roots.source", "runtime.max_workers", "observe.otlp_endpoint"]
)
def test_mutating_every_operational_key_leaves_semantic_digest_byte_identical(key: str) -> None:
    """I26's shape: raising `max_workers` or enabling an unrelated driver must not re-bill the
    corpus (02-architecture.md section 8.3's worked example)."""
    before = semantic_digest(VALUES, AXES)  # type: ignore[arg-type]
    mutated = dict(VALUES) | {key: "MOVED"}
    assert semantic_digest(mutated, AXES) == before  # type: ignore[arg-type]
    assert config_digest(mutated) != config_digest(VALUES)  # type: ignore[arg-type]


@pytest.mark.parametrize("key", ["limits.max_unit_bytes", "graph.segment_target_tokens"])
def test_mutating_a_semantic_key_moves_both_digests(key: str) -> None:
    mutated = dict(VALUES) | {key: 7}
    assert semantic_digest(mutated, AXES) != semantic_digest(VALUES, AXES)  # type: ignore[arg-type]
    assert config_digest(mutated) != config_digest(VALUES)  # type: ignore[arg-type]


def test_an_unclassified_key_is_treated_as_semantic() -> None:
    """02-architecture.md section 8.3: an unclassified key fails CI and is treated at runtime
    as `semantic` -- fail expensive, never wrong."""
    values = dict(VALUES) | {"brand.new.key": 1}
    assert semantic_digest(values, AXES) != semantic_digest(VALUES, AXES)  # type: ignore[arg-type]
    with_axis = dict(AXES) | {"brand.new.key": "operational"}
    assert semantic_digest(values, with_axis) == semantic_digest(VALUES, AXES)  # type: ignore[arg-type]


def test_a_third_axis_state_is_refused() -> None:
    """G18's exact-coverage assertion admits no third state, so a typo must not silently drop
    a key out of every cache key in the corpus."""
    with pytest.raises(ValueError, match="neither 'semantic' nor 'operational'"):
        semantic_digest({"a": 1}, {"a": "sematnic"})  # type: ignore[dict-item]


def test_config_digest_has_no_axis_parameter() -> None:
    """02-architecture.md section 8.4(d): "an operational key entered a cache key" is a call
    that does not type-check rather than a rule to remember."""
    assert set(inspect.signature(config_digest).parameters) == {"values"}
    assert set(inspect.signature(semantic_digest).parameters) == {"values", "axes"}


# --------------------------------------------------------------------------------------------
# determinism across processes
# --------------------------------------------------------------------------------------------

_PROBE = """
import json
from omniweave_core.identity import (
    canonical_uri, config_digest, content_digest, semantic_digest,
)
values = {"a.b": 1, "c.d": "x", "e.f": None, "g.h": ""}
axes = {"a.b": "semantic", "c.d": "operational"}
print(json.dumps({
    "content": content_digest(3, 1, "h\\u00e9llo", {"z": 1, "a": [None, ""]}).hex(),
    "config": config_digest(values),
    "semantic": semantic_digest(values, axes),
    "uri": canonical_uri("HTTPS://EX.com:443/%41/b?z=1&a=2#f".replace("HTTPS", "https")),
}))
"""


def _probe(seed: str) -> dict[str, str]:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    code = _PROBE.replace(
        'canonical_uri("HTTPS://EX.com:443/%41/b?z=1&a=2#f".replace("HTTPS", "https"))',
        'canonical_uri(_L("https", "HTTPS://EX.com:443/%41/b?z=1&a=2#f"))',
    )
    code = (
        "from dataclasses import dataclass\n"
        "@dataclass(frozen=True)\n"
        "class _L:\n"
        "    scheme: str\n"
        "    target: str\n"
    ) + code
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_every_identity_is_identical_across_processes_and_hash_seeds() -> None:
    first = _probe("0")
    assert first == _probe("12345") == _probe("98765")
    values = {"a.b": 1, "c.d": "x", "e.f": None, "g.h": ""}
    axes = {"a.b": "semantic", "c.d": "operational"}
    assert first["config"] == config_digest(values)  # type: ignore[arg-type]
    assert first["semantic"] == semantic_digest(values, axes)  # type: ignore[arg-type]
    assert first["content"] == content_digest(3, 1, "héllo", {"z": 1, "a": [None, ""]}).hex()
    assert first["uri"] == "https://ex.com/A/b?a=2&z=1"
