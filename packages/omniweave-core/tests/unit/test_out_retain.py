"""`omniweave_core.out.retain`: the IL bundle frozen into CAS, and fetched back verified.

09-generation.md section 3.1 decision 2 (retention, not reconstruction) and section 4.5
(`il_digest`). The bundle is a real `ILBundle` over the html carrier, the CAS is a real
`BlobStore`, and every refusal is driven by changing bytes on disk or in the store.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import tomllib
from pathlib import Path

import pytest
from omniweave_core.blobs import BlobStore
from omniweave_core.errors import StoreError, TargetError, UsageError, explain
from omniweave_core.out import retain as retain_module
from omniweave_core.out.carrier import CarrierDoc
from omniweave_core.out.carrier.html import html_carrier
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.job import ILBundle, read_il_files
from omniweave_core.out.retain import fetch, freeze, manifest

TABLE = """\
schema = "omniweave.out-constructs/1"
carrier = "html"
il = "owtext/1"
version = 1
unknown_construct = "forbidden"

[[construct]]
id = "attr.ow-cite"
selector = "@data-ow-cite"
disposition = "native"
round_trip = "exact"
canonical = "cite tokens"
maps_to = "lower.cites:sidecar"
code = "OW_TARGET_CITE_MALFORMED"
since = "0.1.0"

[[construct]]
id = "attr.ow-el"
selector = "@data-ow-el"
disposition = "native"
round_trip = "exact"
canonical = "u<NN>e<NN>"
maps_to = "lower.ids:passthrough"
code = "OW_TARGET_EL_DUPLICATE"
since = "0.1.0"

[[construct]]
id = "elem.ow-manual"
selector = "html|div[data-ow-manual]"
disposition = "native"
round_trip = "exact"
canonical = "a ManualReason"
maps_to = "lower.manual:placeholder"
code = "OW_TARGET_MANUAL_REASON_UNKNOWN"
since = "0.1.0"
"""
CONSTRUCTS = ConstructTable.parse(tomllib.loads(TABLE), {}, source="constructs.toml")
IL_TOML = (
    'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "sha256:'
    + "7" * 64
    + '"\n\n'
    '[[unit]]\nid = "u01"\nord = 1\nfile = "u01.html"\n\n'
    '[[unit]]\nid = "u02"\nord = 2\nfile = "u02.html"\n'
)
FILES = {
    "il.toml": IL_TOML,
    "u01.html": '<section data-ow-el="u01/e1"><p>short</p></section>',
    "u02.html": "<section><p>tiny</p></section>",
    ".stamp.lock": "a stamper's lock, not IL",
}


def carrier(path: str, text: str) -> CarrierDoc:
    return html_carrier(path, text, strict=True)


def bundle_at(il: Path) -> ILBundle:
    return ILBundle.load(il, carrier=carrier, constructs=CONSTRUCTS)


@pytest.fixture
def il(tmp_path: Path) -> Path:
    root = tmp_path / "job" / "il"
    root.mkdir(parents=True)
    for name, text in FILES.items():
        (root / name).write_text(text, encoding="utf-8", newline="")
    return root


@pytest.fixture
def blobs(tmp_path: Path) -> BlobStore:
    (tmp_path / "cas").mkdir()
    return BlobStore(tmp_path / "cas")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# freeze()
# ---------------------------------------------------------------------------


def test_the_bundles_cas_object_is_il_digests_preimage(il: Path, blobs: BlobStore) -> None:
    """Ruling 1: the reference is `cas://` of `il_digest`, and the object hashes to it."""
    bundle = bundle_at(il)
    retained = freeze(bundle, blobs)
    hexdigest = bundle.il_digest.removeprefix("sha256:")
    assert retained.il_store_ref == f"cas://{hexdigest[:2]}/{hexdigest[2:4]}/{hexdigest}"
    assert retained.il_digest == bundle.il_digest
    with blobs.open(hexdigest) as handle:
        body = handle.read()
    assert body == manifest(bundle.files) == manifest(tuple(reversed(bundle.files)))
    assert body == (
        b"il.toml\x00" + sha(IL_TOML).encode() + b"\n"
        b"u01.html\x00" + sha(FILES["u01.html"]).encode() + b"\n"
        b"u02.html\x00" + sha(FILES["u02.html"]).encode() + b"\n"
    )


def test_every_il_file_is_in_cas_and_each_unit_names_its_own(il: Path, blobs: BlobStore) -> None:
    """Rulings 2 and 4: `il.toml` too; the dot-file never; a unit's digest is its file's."""
    retained = freeze(bundle_at(il), blobs)
    for name in ("il.toml", "u01.html", "u02.html"):
        assert blobs.has(sha(FILES[name]))
    assert not blobs.has(sha(FILES[".stamp.lock"]))
    assert dict(retained.units) == {
        "u01": "sha256:" + sha(FILES["u01.html"]),
        "u02": "sha256:" + sha(FILES["u02.html"]),
    }


def test_retaining_twice_is_one_set_of_objects(il: Path, blobs: BlobStore) -> None:
    first = freeze(bundle_at(il), blobs)
    assert freeze(bundle_at(il), blobs) == first
    assert sum(1 for p in blobs.root.rglob("*") if p.is_file() and len(p.name) == 64) == 4


def test_il_that_moved_after_the_gate_is_refused(il: Path, blobs: BlobStore) -> None:
    """Ruling 3: the compile seals the bytes the gate passed, or nothing."""
    bundle = bundle_at(il)
    (il / "u02.html").write_text("<section><p>edited</p></section>", encoding="utf-8")
    with pytest.raises(TargetError, match="changed after the gate passed it") as caught:
        freeze(bundle, blobs)
    assert caught.value.code() == "OW_TARGET_IL_MOVED"
    assert caught.value.fix == "ow out check --stage final"
    assert explain("OW_TARGET_IL_MOVED").numeric == "OW-T-512"


def test_a_file_past_the_ceiling_is_refused_before_a_byte_is_copied(
    il: Path, blobs: BlobStore
) -> None:
    bundle = bundle_at(il)
    big = dataclasses.replace(bundle.files[1], byte_len=retain_module.MAX_IL_FILE_BYTES + 1)
    files = (bundle.files[0], big, *bundle.files[2:])
    with pytest.raises(TargetError, match="past MAX_IL_FILE_BYTES"):
        freeze(dataclasses.replace(bundle, files=files), blobs)
    assert not blobs.has(sha(IL_TOML))


# ---------------------------------------------------------------------------
# fetch()
# ---------------------------------------------------------------------------


def test_a_fetched_bundle_loads_as_the_one_that_was_retained(
    il: Path, blobs: BlobStore, tmp_path: Path
) -> None:
    bundle = bundle_at(il)
    retained = freeze(bundle, blobs)
    files = fetch(retained.il_store_ref, blobs, tmp_path / "edit" / "il")
    assert files == bundle.files
    again = bundle_at(tmp_path / "edit" / "il")
    assert (again.il_digest, again.il_digest_rt) == (bundle.il_digest, bundle.il_digest_rt)
    assert [u.nsig for u in again.units] == [u.nsig for u in bundle.units]
    assert not (tmp_path / "edit" / "il" / ".stamp.lock").exists()


def test_a_fetch_never_merges_into_an_existing_directory(
    il: Path, blobs: BlobStore, tmp_path: Path
) -> None:
    retained = freeze(bundle_at(il), blobs)
    (tmp_path / "taken").mkdir()
    with pytest.raises(UsageError, match="fetched into a new directory"):
        fetch(retained.il_store_ref, blobs, tmp_path / "taken")


def test_a_corrupt_unit_object_fails_the_fetch_and_leaves_nothing(
    il: Path, blobs: BlobStore, tmp_path: Path
) -> None:
    retained = freeze(bundle_at(il), blobs)
    blobs.path(sha(FILES["u02.html"])).write_bytes(b"<section>swapped</section>")
    dest = tmp_path / "edit"
    with pytest.raises(StoreError, match=r"u02\.html's CAS object does not hash") as caught:
        fetch(retained.il_store_ref, blobs, dest)
    assert caught.value.fix == "ow store fsck --cas"
    assert not dest.exists()


def test_a_corrupt_manifest_fails_the_fetch(il: Path, blobs: BlobStore, tmp_path: Path) -> None:
    retained = freeze(bundle_at(il), blobs)
    hexdigest = retained.il_digest.removeprefix("sha256:")
    blobs.path(hexdigest).write_bytes(manifest(bundle_at(il).files)[:-1] + b"\n\n")
    with pytest.raises(StoreError, match="does not hash to its reference"):
        fetch(retained.il_store_ref, blobs, tmp_path / "edit")
    assert not (tmp_path / "edit").exists()


@pytest.mark.parametrize(
    ("body", "said"),
    [
        (b"", "empty"),
        (b"il.toml\x00" + b"a" * 64, "newline"),
        (b"il.toml " + b"a" * 64 + b"\n", "not name NUL sha256"),
        (b"il.toml\x00" + b"A" * 64 + b"\n", "not name NUL sha256"),
        (b"il.toml\x00" + b"a" * 63 + b"\n", "not name NUL sha256"),
        (b".hidden\x00" + b"a" * 64 + b"\n", "not name NUL sha256"),
        (b"sub/u01.html\x00" + b"a" * 64 + b"\n", "not name NUL sha256"),
        (b"sub\\u01.html\x00" + b"a" * 64 + b"\n", "not name NUL sha256"),
        (b"\xff\x00" + b"a" * 64 + b"\n", "not text"),
        (b"u02.html\x00" + b"a" * 64 + b"\nu01.html\x00" + b"b" * 64 + b"\n", "out of order"),
        (b"u01.html\x00" + b"a" * 64 + b"\nu01.html\x00" + b"b" * 64 + b"\n", "or twice"),
    ],
)
def test_a_malformed_manifest_is_refused_before_a_file_is_written(
    blobs: BlobStore, tmp_path: Path, body: bytes, said: str
) -> None:
    digest = blobs.put(io.BytesIO(body))
    with pytest.raises(StoreError, match=said):
        fetch(blobs.ref(digest), blobs, tmp_path / "edit")
    assert not (tmp_path / "edit").exists()


def test_both_reads_are_bounded(
    il: Path, blobs: BlobStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 5: neither the manifest nor a file is read past the ceiling."""
    (il / "u02.html").write_text(f"<section><p>{'x' * 400}</p></section>", encoding="utf-8")
    retained = freeze(bundle_at(il), blobs)
    body_len = len(manifest(bundle_at(il).files))
    assert (il / "u02.html").stat().st_size > body_len
    monkeypatch.setattr(retain_module, "MAX_IL_FILE_BYTES", body_len - 1)
    with pytest.raises(StoreError, match="manifest runs past"):
        fetch(retained.il_store_ref, blobs, tmp_path / "a")
    monkeypatch.setattr(retain_module, "MAX_IL_FILE_BYTES", body_len)
    with pytest.raises(StoreError, match="runs past MAX_IL_FILE_BYTES"):
        fetch(retained.il_store_ref, blobs, tmp_path / "b")
    assert not (tmp_path / "b").exists()


def test_the_fetched_files_are_the_ones_read_il_files_sees(
    il: Path, blobs: BlobStore, tmp_path: Path
) -> None:
    retained = freeze(bundle_at(il), blobs)
    files = fetch(retained.il_store_ref, blobs, tmp_path / "edit")
    assert files == read_il_files(tmp_path / "edit")
    assert [f.name for f in files] == ["il.toml", "u01.html", "u02.html"]
