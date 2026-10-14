"""`toolchain.run()`'s refusals before a child starts: the node ladder and the bundle. D810.

Every case here is decided before a process is spawned, so the tier is T1. What a child says over
`omniweave-target/1` is `tests/conform/test_toolchain_process.py`'s, which spawns node.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

import pytest
from omniweave_core import toolchain
from omniweave_core.clock import SystemClock
from omniweave_core.errors import CapabilityMissing, TargetError
from omniweave_core.toolchain import (
    ENV_ALLOWLIST,
    ToolchainContext,
    ToolchainSpec,
    install_dir,
    parse_manifest,
    resolve_node,
    run,
)

PLATFORM = "win-x64"


def _tarball(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            bundle.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def _spec(data: bytes, node_range: str = ">=18") -> ToolchainSpec:
    manifest = parse_manifest(
        "schema = 1\n\n[[toolchain]]\n"
        'name = "deck"\nversion = "0.4.2"\nentry = "dist/render.mjs"\n'
        f'node_range = "{node_range}"\n'
        f'bundle_sha256 = "sha256:{hashlib.sha256(data).hexdigest()}"\n'
        'bundle_url = "https://example.invalid/deck.tar.gz"\n\n'
        "[[node]]\n"
        'version = "20.18.1"\nplatform = "win-x64"\n'
        f'sha256 = "sha256:{"1" * 64}"\nurl = "https://example.invalid/node.zip"\n\n'
        "[[node]]\n"
        'version = "16.20.2"\nplatform = "win-x64"\n'
        f'sha256 = "sha256:{"2" * 64}"\nurl = "https://example.invalid/node16.zip"\n',
        source="toolchains.toml",
    )
    spec = manifest.toolchain("deck")
    assert spec is not None
    return spec


def _ctx(tmp_path: Path, **env: str) -> ToolchainContext:
    manifest_nodes = parse_manifest(
        "schema = 1\n\n[[node]]\n"
        'version = "22.1.0"\nplatform = "linux-x64"\n'
        f'sha256 = "sha256:{"3" * 64}"\nurl = "https://example.invalid/node22.tar.xz"\n\n'
        "[[node]]\n"
        'version = "16.20.2"\nplatform = "win-x64"\n'
        f'sha256 = "sha256:{"2" * 64}"\nurl = "https://example.invalid/node16.zip"\n\n'
        "[[node]]\n"
        'version = "20.18.1"\nplatform = "win-x64"\n'
        f'sha256 = "sha256:{"1" * 64}"\nurl = "https://example.invalid/node.zip"\n',
        source="toolchains.toml",
    ).nodes
    return ToolchainContext(
        home=tmp_path / "home",
        env={"PATH": str(tmp_path / "empty"), **env},
        nodes=manifest_nodes,
        platform=PLATFORM,
        scratch=tmp_path / "scratch",
        clock=SystemClock(),
    )


def _installed(ctx: ToolchainContext, spec: ToolchainSpec, data: bytes) -> Path:
    where = install_dir(spec, ctx.home)
    where.mkdir(parents=True)
    (where / "bundle.tar.gz").write_bytes(data)
    return where


def _runtime(ctx: ToolchainContext, version: str, platform: str = PLATFORM) -> Path:
    node = ctx.home / "node" / f"{version}-{platform}" / "bin" / "node.exe"
    node.parent.mkdir(parents=True)
    node.write_bytes(b"not a real node")
    return node


BUNDLE = _tarball({"dist/render.mjs": b"// the app\n", "package.json": b"{}"})


def test_the_digest_is_in_the_install_path(tmp_path: Path) -> None:
    spec = _spec(BUNDLE)
    digest = spec.bundle_sha256.removeprefix("sha256:")
    assert install_dir(spec, tmp_path) == tmp_path / "toolchains" / f"deck@0.4.2-{digest}"


# ---------------------------------------------------------------------------------------------
# Ruling 2: the node ladder
# ---------------------------------------------------------------------------------------------


def test_omniweave_node_is_taken_as_named(tmp_path: Path) -> None:
    named = tmp_path / "custom" / "node.exe"
    named.parent.mkdir()
    named.write_bytes(b"")
    ctx = _ctx(tmp_path, OMNIWEAVE_NODE=str(named))
    _runtime(ctx, "20.18.1")
    assert resolve_node(_spec(BUNDLE), ctx) == named, "before any installed runtime"


def test_omniweave_node_naming_nothing_is_refused_by_name(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, OMNIWEAVE_NODE=str(tmp_path / "gone.exe"))
    with pytest.raises(CapabilityMissing, match=r"gone.exe, which is not a file") as caught:
        resolve_node(_spec(BUNDLE), ctx)
    assert caught.value.code() == "OW_TARGET_TOOLCHAIN_MISSING"


def test_an_installed_runtime_the_range_accepts_is_the_second_rung(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _runtime(ctx, "16.20.2")
    _runtime(ctx, "22.1.0", platform="linux-x64")
    wanted = _runtime(ctx, "20.18.1")
    assert resolve_node(_spec(BUNDLE), ctx) == wanted, "16 is out of range, 22 another platform"


def test_no_rung_is_capability_missing_naming_the_install(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    _runtime(ctx, "16.20.2")
    with pytest.raises(CapabilityMissing, match="no node satisfies deck's node_range") as caught:
        resolve_node(_spec(BUNDLE), ctx)
    assert (caught.value.code(), caught.value.fix, caught.value.missing) == (
        "OW_TARGET_TOOLCHAIN_MISSING",
        "ow targets install deck",
        ("node",),
    )
    assert caught.value.EXIT == 64


# ---------------------------------------------------------------------------------------------
# Ruling 3: the bundle, verified on every invocation
# ---------------------------------------------------------------------------------------------


def _ready(tmp_path: Path) -> ToolchainContext:
    """A context whose node rung resolves to a file that is not a program: the refusals below
    all come before any spawn, or the spawn would fail as `OW_TARGET_TOOLCHAIN_FAILED`."""
    ctx = _ctx(tmp_path)
    _runtime(ctx, "20.18.1")
    return ctx


def test_a_bundle_not_installed_is_capability_missing(tmp_path: Path) -> None:
    with pytest.raises(CapabilityMissing, match=r"deck@0\.4\.2 is not installed") as caught:
        run(_spec(BUNDLE), tmp_path, timeout_s=5, ctx=_ready(tmp_path))
    assert caught.value.missing == ("toolchain:deck",)


def test_a_bundle_that_fails_its_digest_is_never_run(tmp_path: Path) -> None:
    ctx = _ready(tmp_path)
    spec = _spec(BUNDLE)
    _installed(ctx, spec, BUNDLE + b"tampered")
    with pytest.raises(TargetError, match="fails its digest") as caught:
        run(spec, tmp_path, timeout_s=5, ctx=ctx)
    assert caught.value.code() == "OW_TARGET_TOOLCHAIN_DIGEST"
    assert "nothing is fetched" in str(caught.value)
    assert not (ctx.scratch / "deck@0.4.2").exists(), "no entry written from unverified bytes"


def test_a_bundle_without_its_entry_is_refused(tmp_path: Path) -> None:
    ctx = _ready(tmp_path)
    other = _tarball({"dist/other.mjs": b""})
    spec = _spec(other)
    _installed(ctx, spec, other)
    with pytest.raises(TargetError, match=r"holds no file dist/render\.mjs") as caught:
        run(spec, tmp_path, timeout_s=5, ctx=ctx)
    assert caught.value.code() == "OW_TARGET_TOOLCHAIN_FAILED"


def test_the_verified_entry_is_written_out_and_a_non_program_will_not_start(
    tmp_path: Path,
) -> None:
    ctx = _ready(tmp_path)
    spec = _spec(BUNDLE)
    _installed(ctx, spec, BUNDLE)
    with pytest.raises(TargetError, match="would not start") as caught:
        run(spec, tmp_path, timeout_s=5, ctx=ctx)
    assert caught.value.code() == "OW_TARGET_TOOLCHAIN_FAILED"
    entry = ctx.scratch / "deck@0.4.2" / "dist" / "render.mjs"
    assert entry.read_bytes() == b"// the app\n", "the bytes just verified, not an extracted copy"


def test_a_bundle_too_large_to_verify_is_refused_unread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ready(tmp_path)
    spec = _spec(BUNDLE)
    _installed(ctx, spec, BUNDLE)
    monkeypatch.setattr(toolchain, "BUNDLE_MAX_BYTES", 10)
    with pytest.raises(TargetError, match="is over 10 bytes") as caught:
        run(spec, tmp_path, timeout_s=5, ctx=ctx)
    assert caught.value.code() == "OW_TARGET_TOOLCHAIN_DIGEST"


def test_an_entry_that_is_not_a_file_is_refused(tmp_path: Path) -> None:
    ctx = _ready(tmp_path)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        folder = tarfile.TarInfo("dist/render.mjs")
        folder.type = tarfile.DIRTYPE
        bundle.addfile(folder)
    data = buffer.getvalue()
    spec = _spec(data)
    _installed(ctx, spec, data)
    with pytest.raises(TargetError, match=r"dist/render\.mjs is not a file"):
        run(spec, tmp_path, timeout_s=5, ctx=ctx)


def test_an_unknown_verb_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="verb 'render'"):
        run(_spec(BUNDLE), tmp_path, timeout_s=5, ctx=_ready(tmp_path), verb="render")


def test_the_allowlist_names_the_os_and_the_temp_directory_only() -> None:
    assert ENV_ALLOWLIST == ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR")
