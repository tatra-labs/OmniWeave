"""`ow out assets --slug S [--gen N] [--explain] | --slot SHA`: one ledger, or one slot's users.

owtext freezes no asset, so each test seals an artefact into the project's store through
`SqliteArtifactStore.seal()` itself, over two seeded `asset` rows. The store readers' own rulings
are `test_store_artifact.py`'s; this file asks what the verb resolves, prints and refuses.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.surface import out as verb
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.artifact import (
    ArtifactDraft,
    AssetJoin,
    PureKey,
    SqliteArtifactStore,
    UnitRow,
)
from omniweave_ports import Restriction

if TYPE_CHECKING:
    from collections.abc import Sequence

SHA_A = "a" * 64
SHA_B = "b" * 64
BITS_B = Restriction.OUTPUT_SHARE_ALIKE.bit | Restriction.FIELD_OF_USE_EXCLUDED.bit


def d(n: int) -> str:
    return f"sha256:{n:064x}"


class _Clock:
    def monotonic_ns(self) -> int:  # pragma: no cover -- the seal reads wall time only
        return 0

    def wall_ns(self) -> int:
        return 1_757_400_000_000_000_000


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO producer(producer_id, operator, op_version, code_fingerprint,"
            " options_digest) VALUES (1, 'compile.text.owtext', 1, '', x'00')"
        )
        for doc_ord, uri in ((7, "file:///c/brand.pdf"), (8, "file:///c/logo.png")):
            connection.execute(
                "INSERT INTO doc(doc_ord, doc_key, source_sha256, uri, media_type, format,"
                " format_evidence, source_bytes, status, model_version, declared, achieved)"
                " VALUES (?, ?, ?, ?, 'application/pdf', 'pdf', '{}', 10, 'ok', '1.1', '{}',"
                " '{}')",
                (doc_ord, bytes([doc_ord]) * 16, b"\x00" * 32, uri),
            )
        for asset_id, doc_ord, sha, bits, spdx in (
            (201, 7, SHA_A, 0, "CC-BY-4.0"),
            (202, 7, SHA_B, BITS_B, None),
            (203, 8, SHA_A, 0, None),
        ):
            connection.execute(
                "INSERT INTO asset(asset_id, doc_ord, media_type, sha256, byte_len, store_ref,"
                " spdx, restriction_bits) VALUES (?, ?, 'image/png', ?, 5, 'cas://x', ?, ?)",
                (asset_id, doc_ord, bytes.fromhex(sha), spdx, bits),
            )
        connection.execute("COMMIT")
    finally:
        connection.close()
    return tmp_path


def _seal(project: Path, slug: str, assets: tuple[AssetJoin, ...]) -> None:
    store = project / ".omniweave" / "index.owstore"
    draft = ArtifactDraft(
        key=PureKey(
            target="owtext", slug=slug, delivery="release", il_digest=d(1),
            constructs_digest=d(2), ledger_digest=d(3), card_sha256=d(4), brief_digest=d(5),
            toolchain_digest=None,
        ),
        artifact_gen=1, origin="authored", compile_driver="compile.text.owtext",
        media_type="text/plain", path=f"{slug}@1/{slug}.txt", sha256=d(10), byte_len=12,
        part_digest=d(11), il_store_ref="cas://00/00/" + "0" * 64, determinism=("part", "byte"),
        gate_status=GateStatus.PASSED, report_sha256=d(12), receipt_sha256=d(13), producer_id=1,
        units=tuple(
            UnitRow(f"u0{n}", n, UnitOutcome.NATIVE, f"il/u0{n}.html", d(100 + n), f"{n:08x}")
            for n in (1, 2)
        ),
        assets=assets,
        cites=(),
    )  # fmt: skip
    with store_sqlite.StoreThread(lambda: store_sqlite.connect(store)) as thread:
        SqliteArtifactStore(thread, clock=_Clock()).seal(draft)  # type: ignore[arg-type]


def _sealed(project: Path) -> None:
    _seal(
        project,
        "q3",
        (
            AssetJoin(201, "asset-slot:" + SHA_A, "image", ("u01", "u02")),
            AssetJoin(202, "asset-slot:" + SHA_B, "image", ("u02",)),
        ),
    )


def _env(home: Path) -> dict[str, str]:
    return {
        "OMNIWEAVE_HOME": str(home / "owhome"),
        "HOME": str(home / "home"),
        "USERPROFILE": str(home / "home"),
    }


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", "assets", *argv], cwd=cwd, env=_env(cwd), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _json(project: Path, *argv: str) -> dict[str, Any]:
    code, out, err = _run([*argv, "--render", "json"], project)
    assert (code, err) == (0, "")
    document: dict[str, Any] = json.loads(out)
    return document


# ---------------------------------------------------------------------------------------------
# --slug: one artefact's ledger
# ---------------------------------------------------------------------------------------------


def test_a_slug_lists_its_frozen_assets_with_their_named_restrictions(project: Path) -> None:
    _sealed(project)
    document = _json(project, "--slug", "q3")
    assert (document["slug"], document["artifact_gen"], document["slot"]) == ("q3", 1, None)
    first, second = document["assets"]
    assert first == {
        "asset_id": 201, "sha256": SHA_A, "slot": "asset-slot:" + SHA_A, "role": "image",
        "units": ["u01", "u02"], "media_type": "image/png", "byte_len": 5, "doc_ord": 7,
        "licence": None, "spdx": "CC-BY-4.0", "restriction_bits": 0, "restrictions": [],
    }  # fmt: skip
    assert second["restrictions"] == ["output_share_alike", "field_of_use_excluded"]
    assert (document["users"], document["owners"]) == ([], [])


def test_the_text_form_and_explain(project: Path) -> None:
    _sealed(project)
    code, out, err = _run(["--slug", "q3"], project)
    assert (code, err) == (0, "")
    assert out.splitlines() == [
        "q3@1: 2 frozen asset(s)",
        f"  asset-slot:{SHA_A}  image  u01,u02  image/png  5 bytes  d7",
        f"  asset-slot:{SHA_B}  image  u02  image/png  5 bytes  d7",
    ]
    code, out, err = _run(["--slug", "q3", "--explain"], project)
    assert (code, err) == (0, "")
    assert out.splitlines()[2] == "    licence: CC-BY-4.0; restrictions: none"
    assert out.splitlines()[4] == (
        "    licence: no licence recorded; restrictions: output_share_alike, field_of_use_excluded"
    )


def test_an_artefact_with_no_asset_says_so(project: Path) -> None:
    _seal(project, "bare", ())
    code, out, _err = _run(["--slug", "bare"], project)
    assert (code, out) == (0, "bare@1: no frozen asset\n")


def test_gen_names_a_generation_and_one_never_sealed_is_not_found(project: Path) -> None:
    _sealed(project)
    assert _json(project, "--slug", "q3", "--gen", "1")["artifact_gen"] == 1
    code, out, err = _run(["--slug", "q3", "--gen", "9"], project)
    assert (code, out) == (2, "")
    assert "no artefact q3@9" in err
    code, out, err = _run(["--slug", "q9"], project)
    assert (code, out) == (2, "")
    assert "no artefact 'q9' is sealed in corpus 'handbook'" in err


def test_an_unallocated_restriction_bit_is_named_by_its_position() -> None:
    bits = Restriction.OUTPUT_SHARE_ALIKE.bit | 1 << 12
    assert verb._restrictions(bits) == ("output_share_alike", "bit_12")
    assert verb._restrictions(0) == ()


# ---------------------------------------------------------------------------------------------
# --slot: 09 section 7.2's reuse query
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("slot", [f"asset-slot:{SHA_A}", SHA_A])
def test_a_slot_lists_every_artefact_and_every_owning_document(project: Path, slot: str) -> None:
    _sealed(project)
    _seal(project, "q4", (AssetJoin(203, "asset-slot:" + SHA_A, "thumbnail", ("u02",)),))
    document = _json(project, "--slot", slot)
    assert (document["slug"], document["slot"]) == (None, f"asset-slot:{SHA_A}")
    assert document["users"] == [
        {"slug": "q3", "artifact_gen": 1, "role": "image", "units": ["u01", "u02"]},
        {"slug": "q4", "artifact_gen": 1, "role": "thumbnail", "units": ["u02"]},
    ]
    assert document["owners"] == [
        {"doc_ord": 7, "uri": "file:///c/brand.pdf", "asset_id": 201},
        {"doc_ord": 8, "uri": "file:///c/logo.png", "asset_id": 203},
    ]
    code, out, _err = _run(["--slot", slot], project)
    assert code == 0
    assert out.splitlines() == [
        f"asset-slot:{SHA_A}: 2 artefact generation(s), 2 corpus document(s)",
        "  artefact q3@1  image  u01,u02",
        "  artefact q4@1  thumbnail  u02",
        "  document d7  file:///c/brand.pdf  (asset 201)",
        "  document d8  file:///c/logo.png  (asset 203)",
    ]


def test_bytes_nobody_holds_are_an_empty_answer(project: Path) -> None:
    document = _json(project, "--slot", "c" * 64)
    assert (document["users"], document["owners"]) == ([], [])


# ---------------------------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        ([], "--slug or --slot, exactly one"),
        (["--slug", "q3", "--slot", SHA_A], "--slug or --slot, exactly one"),
        (["--slot", SHA_A, "--gen", "1"], "they go with --slug"),
        (["--slot", SHA_A, "--explain"], "they go with --slug"),
        (["--slot", "asset-slot:abc"], "is not asset-slot:<sha256>"),
        (["--slot", SHA_A.upper()], "is not asset-slot:<sha256>"),
        (["--slug", "q3", "--quiet"], "--quiet is parsed and not served by ow out assets"),
    ],
)
def test_usage_is_refused_by_name(argv: list[str], named: str, project: Path) -> None:
    code, out, err = _run(argv, project)
    assert (code, out) == (1, "")
    assert named in err
