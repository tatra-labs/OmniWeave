"""`toolchain.run()` against a real node: `omniweave-target/1`, both ways. D810.

The app is a few lines of ES module written here, packed as the bundle a register row pins, and run
by whatever node this host has: `OMNIWEAVE_NODE`'s rung is the explicit one, so each test names
the node `shutil.which` finds, and the PATH rung has a test of its own. The app reads `mode.txt`
from its `cwd`, the JobDir, to play each side of the protocol. Skipped where no node is installed,
as section 3.4's parity job has none.
"""

from __future__ import annotations

import ctypes
import hashlib
import io
import os
import shutil
import sys
import tarfile
from pathlib import Path

import pytest
from omniweave_core.clock import SystemClock
from omniweave_core.errors import CapabilityMissing, TargetError
from omniweave_core.toolchain import (
    ENV_ALLOWLIST,
    STDOUT_MAX_BYTES,
    ToolchainContext,
    ToolchainSpec,
    install_dir,
    parse_manifest,
    run,
)

NODE = shutil.which("node")
pytestmark = [
    pytest.mark.conform,
    pytest.mark.skipif(NODE is None, reason="no node on this host (section 3.4's parity job)"),
]
PLATFORM = "win-x64" if sys.platform == "win32" else "linux-x64"
APP = r"""
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createInterface } from "node:readline";
let mode = "ok";
try { mode = readFileSync("mode.txt", "utf8").trim(); } catch {}
if (mode === "exit64") process.exit(64);
writeFileSync("pid.txt", String(process.pid));
const send = (frame) => process.stdout.write(JSON.stringify(frame) + "\n");
process.stderr.write("render.mjs: started in " + mode + "\n");
let verb = "";
let written = false;
const lines = createInterface({ input: process.stdin });
lines.on("line", (line) => {
  const frame = JSON.parse(line);
  if (frame.t === "hello") {
    if (mode === "badframe") { process.stdout.write("not json\n"); return; }
    if (mode === "array") { process.stdout.write("[1]\n"); return; }
    send({ t: "ready", toolchain: mode === "wrongname" ? "video" : "deck", version: "0.4.2",
           proto: frame.proto, verb: frame.verb });
    return;
  }
  if (frame.t === "bye") {
    lines.close();
    const quiet = mode === "noreceipt" || (verb !== "compile" && mode === "ok");
    const one = mode === "receiptexit1" || mode === "validateexit1";
    process.exit(written || quiet ? (one ? 1 : 0) : 1);
  }
  verb = frame.t;
  if (mode === "hang") return;
  if (mode === "flood") {
    const pad = "x".repeat(1 << 16);
    for (let i = 0; i < 20; i++) send({ t: "progress", done: i, total: 20, pad });
  }
  send({ t: "progress", done: 1, total: 2 });
  send({ t: "progress", done: 2, total: 2 });
  if (verb === "compile" && (mode === "ok" || mode === "receiptexit1")) {
    mkdirSync("out", { recursive: true });
    writeFileSync("out/receipt.json", "{}");
    written = true;
  }
  if (mode === "noresult") { send({ t: "done" }); return; }
  const status = mode === "blocked" ? "blocked" : mode === "badstatus" ? "maybe" : "ok";
  send({ t: "result", status, cwd: process.cwd(),
         env: Object.keys(process.env).sort(), echo: frame });
});
"""


def _bundle() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        for name, body in (("dist/render.mjs", APP.encode()), ("package.json", b"{}")):
            info = tarfile.TarInfo(name)
            info.size = len(body)
            bundle.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


BUNDLE = _bundle()


def _spec(node_range: str = ">=18") -> ToolchainSpec:
    spec = parse_manifest(
        "schema = 1\n\n[[toolchain]]\n"
        'name = "deck"\nversion = "0.4.2"\nentry = "dist/render.mjs"\n'
        f'node_range = "{node_range}"\n'
        f'bundle_sha256 = "sha256:{hashlib.sha256(BUNDLE).hexdigest()}"\n'
        'bundle_url = "https://example.invalid/deck.tar.gz"\n',
        source="toolchains.toml",
    ).toolchain("deck")
    assert spec is not None
    return spec


def _ctx(tmp_path: Path, spec: ToolchainSpec, *, explicit: bool = True) -> ToolchainContext:
    ctx = ToolchainContext(
        home=tmp_path / "home",
        env={
            "OMNIWEAVE_NODE": str(NODE) if explicit else "",
            "PATH": str(Path(str(NODE)).parent),
            "SYSTEMROOT": "C:\\Windows",
            "OMNIWEAVE_API_TOKEN": "secret",
            "NODE_OPTIONS": "--inspect",
        },
        nodes=(),
        platform=PLATFORM,
        scratch=tmp_path / "scratch",
        clock=SystemClock(),
    )
    where = install_dir(spec, ctx.home)
    where.mkdir(parents=True, exist_ok=True)
    (where / "bundle.tar.gz").write_bytes(BUNDLE)
    return ctx


def _job(tmp_path: Path, mode: str = "ok") -> Path:
    job = tmp_path / "job"
    job.mkdir()
    (job / "mode.txt").write_text(mode, encoding="utf-8")
    return job


def test_a_compile_writes_its_receipt_exits_zero_and_answers_ok(tmp_path: Path) -> None:
    spec = _spec()
    job = _job(tmp_path)
    done = run(spec, job, timeout_s=30, ctx=_ctx(tmp_path, spec), request={"unit": "u01"})
    assert (done.status, done.exit_code, done.receipt) == ("ok", 0, job / "out" / "receipt.json")
    assert done.progress == ((1, 2), (2, 2))
    assert done.node == Path(str(NODE))
    assert done.result["echo"] == {"unit": "u01", "t": "compile"}, "the request's fields, verbed"
    assert Path(done.result["cwd"]).resolve() == job.resolve(), "ruling 4: cwd is the JobDir"
    # D886: macOS injects `__CF_USER_TEXT_ENCODING` into every process at exec, after any
    # allowlist could act, so it is the OS's and not a leak.
    injected = {"__CF_USER_TEXT_ENCODING"} if sys.platform == "darwin" else set()
    leaked = set(done.result["env"]) - set(ENV_ALLOWLIST) - injected
    assert not leaked, f"no token, no NODE_OPTIONS: {sorted(leaked)}"
    assert "render.mjs: started in ok" in done.stderr_tail, "kept, never parsed"


def test_a_validate_answers_without_a_receipt(tmp_path: Path) -> None:
    spec = _spec()
    done = run(spec, _job(tmp_path), timeout_s=30, ctx=_ctx(tmp_path, spec), verb="validate")
    assert (done.status, done.exit_code, done.receipt) == ("ok", 0, None)


def test_a_blocked_compile_is_an_answer_not_a_failure(tmp_path: Path) -> None:
    spec = _spec()
    done = run(spec, _job(tmp_path, "blocked"), timeout_s=30, ctx=_ctx(tmp_path, spec))
    assert (done.status, done.exit_code, done.receipt) == ("blocked", 1, None)


@pytest.mark.parametrize(
    ("mode", "verb", "said"),
    [
        ("noreceipt", "compile", "exited 0 without out/receipt.json"),
        ("receiptexit1", "compile", "exited 1 with out/receipt.json"),
        ("validateexit1", "validate", "answered validate ok and exited 1"),
        ("badframe", "compile", "a stdout line is not a JSON frame"),
        ("array", "compile", "a stdout frame is not a JSON object"),
        ("badstatus", "compile", "answered compile with"),
        ("wrongname", "compile", "first frame is not its ready"),
        ("noresult", "compile", "answered compile with"),
        ("flood", "compile", f"stdout passed {STDOUT_MAX_BYTES} bytes"),
    ],
)
def test_a_child_that_breaks_the_protocol_is_refused(
    tmp_path: Path, mode: str, verb: str, said: str
) -> None:
    spec = _spec()
    with pytest.raises(TargetError, match=said) as caught:
        run(spec, _job(tmp_path, mode), timeout_s=30, ctx=_ctx(tmp_path, spec), verb=verb)
    assert caught.value.code() == "OW_TARGET_TOOLCHAIN_FAILED"


def _alive(pid: int) -> bool:
    """Whether `pid` still runs, asked without signalling it."""
    if sys.platform != "win32":  # pragma: no cover -- POSIX
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        status = ctypes.c_ulong()
        kernel32.GetExitCodeProcess(handle, ctypes.byref(status))
        return status.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def test_a_child_that_never_answers_is_reaped_at_its_deadline(tmp_path: Path) -> None:
    spec = _spec()
    job = _job(tmp_path, "hang")
    with pytest.raises(TargetError, match="no frame before its deadline"):
        run(spec, job, timeout_s=2, ctx=_ctx(tmp_path, spec))
    assert not _alive(int((job / "pid.txt").read_text(encoding="utf-8"))), "ruling 7"


def test_a_child_whose_own_runtime_is_missing_exits_64(tmp_path: Path) -> None:
    """It exits before its ready, so the pipe closes first and the status says why."""
    spec = _spec()
    with pytest.raises(CapabilityMissing, match="exited 64") as caught:
        run(spec, _job(tmp_path, "exit64"), timeout_s=30, ctx=_ctx(tmp_path, spec))
    assert (caught.value.code(), caught.value.missing) == (
        "OW_TARGET_TOOLCHAIN_MISSING",
        ("toolchain:deck",),
    )


def test_node_on_path_is_the_last_rung_when_the_range_accepts_it(tmp_path: Path) -> None:
    spec = _spec()
    done = run(spec, _job(tmp_path), timeout_s=30, ctx=_ctx(tmp_path, spec, explicit=False))
    assert done.node.resolve() == Path(str(NODE)).resolve()


def test_node_on_path_outside_the_range_is_capability_missing(tmp_path: Path) -> None:
    spec = _spec("<10")
    with pytest.raises(CapabilityMissing, match="no node satisfies deck's node_range '<10'"):
        run(spec, _job(tmp_path), timeout_s=30, ctx=_ctx(tmp_path, spec, explicit=False))
