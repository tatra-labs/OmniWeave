"""Q-G22, contributor parity: `uv sync && pytest` offline, GPU-free and Node-free. **D842.**

16-roadmap.md:984: `uv run tools/gate_parity.py --offline --no-gpu --no-node  # <= 600 s hard
ceiling`. 13-quality.md:70 runs the `parity` tier, *"`uv sync && pytest`,
offline/GPU-free/Node-free"*, every PR, and Q-G22 (:2006) is *"a clean container: no network,
no GPU, no Node, ≤ 600 s hard"*. :987 says what it is for: *"T2, T3 and the parity job never
make a network call, so the `contributor-parity` claim ... is a real claim about a real container
rather than an aspiration"*.
The container is CI's. This gate holds a run on any machine to the same three constraints and the
same ceiling, and is what that job runs.

## Rulings

1. **The three flags are the gate.** `--offline`, `--no-gpu` and `--no-node` each apply one
   constraint, and a run missing any of them is not Q-G22: the gate refuses before it runs,
   naming the flag. 16:984 prints all three, so a reader of the command sees what the run was held
   to.
2. **Offline is an audit hook in every Python process of the run.**
   - A `sitecustomize` armed on `PYTHONPATH` installs it, so it reaches `uv run`'s interpreter,
     every xdist worker and every Python child a test spawns. That is G15's clause-3 mechanism
     (`tools/gate_egress.py`).
   - It refuses `socket.connect` and `socket.sendto` to an address that is not loopback, and
     `socket.getaddrinfo` for a host that is not `localhost` or a loopback literal. An
     unspecified address (`0.0.0.0`, `::`) is this machine too, so a server that resolves it
     to bind every interface still can.
   - Loopback stays open, unlike G15's blocker, because a container with no network still has
     `lo`.
   - `UV_OFFLINE`, `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE` and `PIP_NO_INDEX` cover the
     processes that are not Python, and `uv sync` runs with `--offline`.
   - **A negative control runs first**: a fresh interpreter under the armed environment must be
     refused a connection to a TEST-NET address. Otherwise the gate did not run. That is G15's
     lesson: an unloaded `sitecustomize` would report the absence of an instrument as the absence
     of egress.
3. **GPU-free sets `CUDA_VISIBLE_DEVICES`, `HIP_VISIBLE_DEVICES` and `ROCR_VISIBLE_DEVICES` to
   the empty string.** 13:268 sends a test that needs a GPU to T4, so nothing on this path should
   look for one.
4. **Node-free removes every `PATH` entry that holds `node`, then holds the new `PATH` to it.** If
   `node` still resolves, the constraint did not hold and the gate did not run.
5. **The run is `uv sync --frozen --all-packages --group dev --offline`, then `pytest -n auto -q
   -m "not conform"`.** That is T1 and T2 as the repository runs them, one invocation. A bare
   `pytest -n auto` puts T3's process-level conformance tests in the same workers and fails for
   reasons that are not parity's, so T3 stays its own job.
6. **The ceiling is `contributor_parity_s`'s `value + tol_abs` in `eval/perf.toml`, 600 s**, over
   both steps' wall time. The run is killed at the ceiling, since a run past it has failed whatever
   it would have printed.
7. **Output goes to a log file, never a pipe.** On Windows a pipe a grandchild holds open keeps a
   timeout from firing. `--log` keeps the file; without it, the tail is printed on failure and the
   file goes with its temporary directory.

## Exit codes

`0` both steps passed within the ceiling under all three constraints. `1` a step failed, or the
ceiling was passed. `2` the gate did not run: a missing flag, no `uv`, `node` still on `PATH`, no
budget row, or a blocker that failed its negative control.

Specified in 13-quality.md sections 2.1, 2.9 and 7, and 16-roadmap.md section 13.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess  # noqa: TID251 - the gate's whole job is to run `uv` and `pytest` as children.
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final

__all__ = [
    "BLOCKER",
    "BUDGET_ID",
    "EXIT_CLEAN",
    "EXIT_FAIL",
    "EXIT_NOT_RUN",
    "GPU_VARS",
    "OFFLINE_VARS",
    "SYNC",
    "TESTS",
    "arm",
    "ceiling",
    "main",
    "no_gpu_env",
    "no_node_env",
    "offline_env",
]

REPO = Path(__file__).resolve().parent.parent

EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2

BUDGET_ID: Final = "contributor_parity_s"
PERF: Final = Path("eval") / "perf.toml"
SYNC: Final = ("sync", "--frozen", "--all-packages", "--group", "dev", "--offline")
TESTS: Final = (
    "run", "--frozen", "--no-sync", "pytest", "-n", "auto", "-q", "-m", "not conform",
    "-p", "no:cacheprovider",
)  # fmt: skip
OFFLINE_VARS: Final[Mapping[str, str]] = {
    "UV_OFFLINE": "1",
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "PIP_NO_INDEX": "1",
}
GPU_VARS: Final = ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES", "ROCR_VISIBLE_DEVICES")
_FLAGS: Final = ("offline", "no_gpu", "no_node")
_STEPS: Final = (("uv sync", SYNC), ("pytest", TESTS))
_TAIL: Final = 20

BLOCKER: Final = '''"""Q-G22: only loopback is reachable here and in every child process.

Loaded as `sitecustomize` from `PYTHONPATH`, which every child inherits. `sys.addaudithook` cannot
be removed once installed. Loopback stays open: a container with no network still has `lo`.

**It imports nothing but `sys`.** It is in every interpreter of the run, and the tests that assert
an import opens no path to a socket, or that core loads neither `asyncio` nor `selectors`, read
`sys.modules` in a fresh one. `socket` imports `selectors`. So `_socket` is read from `sys.modules`
when an event fires, which it always is by then, since `_socket` is what raises the event.
"""

import sys


def _local(host):
    if host is None or host == "" or host == b"":
        return True
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    raw = sys.modules["_socket"]
    host = host.split("%", 1)[0]
    for family, size in ((raw.AF_INET, 4), (raw.AF_INET6, 16)):
        try:
            packed = raw.inet_pton(family, host)
        except (OSError, ValueError):
            continue
        if size == 4:
            return packed[0] == 127 or packed == bytes(4)
        mapped = packed[:12] == bytes(10) + b"\\xff\\xff"
        return packed in (bytes(15) + b"\\x01", bytes(16)) or (mapped and packed[12] == 127)
    return False


def _host(address):
    return address[0] if isinstance(address, tuple) and address else address


def _refuse(what):
    import errno

    return OSError(errno.ENETUNREACH, "Q-G22: the parity run has no network: %s" % what)


def _hook(event, args):
    if event in ("socket.connect", "socket.sendto"):
        raw = sys.modules["_socket"]
        sock, address = args[0], args[1]
        if sock.family in (raw.AF_INET, raw.AF_INET6) and not _local(_host(address)):
            raise _refuse("connect to %r" % (address,))
    elif event == "socket.getaddrinfo":
        if not _local(args[0]):
            raw = sys.modules["_socket"]
            raise raw.gaierror(
                raw.EAI_NONAME, "Q-G22: the parity run resolves no host: %r" % (args[0],)
            )


sys.addaudithook(_hook)
'''
"""Ruling 2's hook, written into the run's `PYTHONPATH` as `sitecustomize.py`."""

_CONTROL: Final = "import socket; socket.create_connection(('192.0.2.1', 9), timeout=5)"
"""The negative control: TEST-NET-1 (RFC 5737), an address that routes nowhere."""

Runner = Callable[[list[str], Mapping[str, str], Path, float], int | None]


def ceiling(perf: Mapping[str, object]) -> float:
    """Ruling 6: `value + tol_abs` of the `contributor_parity_s` row, or `ValueError`."""
    rows = perf.get("budget", [])
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("id") == BUDGET_ID:
            value, tol = row.get("value"), row.get("tol_abs", 0)
            if not all(
                isinstance(n, int | float) and not isinstance(n, bool) for n in (value, tol)
            ):
                break
            return float(value) + float(tol)  # type: ignore[arg-type]
    raise ValueError(f"eval/perf.toml has no numeric [[budget]] row {BUDGET_ID!r}")


def arm(scratch: Path, env: Mapping[str, str]) -> dict[str, str]:
    """Ruling 2: write the blocker into `scratch` and return `env` with it first on `PYTHONPATH`."""
    (scratch / "sitecustomize.py").write_bytes(BLOCKER.encode("utf-8"))
    key = next((name for name in env if name.upper() == "PYTHONPATH"), "PYTHONPATH")
    path = os.pathsep.join(part for part in (str(scratch), env.get(key, "")) if part)
    return {**env, key: path}


def offline_env(env: Mapping[str, str]) -> dict[str, str]:
    """Ruling 2's switches over `env`."""
    return {**env, **OFFLINE_VARS}


def no_gpu_env(env: Mapping[str, str]) -> dict[str, str]:
    """Ruling 3 over `env`."""
    return {**env, **dict.fromkeys(GPU_VARS, "")}


def no_node_env(
    env: Mapping[str, str], which: Callable[..., str | None] = shutil.which
) -> dict[str, str]:
    """Ruling 4 over `env`, or `ValueError` when `node` still resolves on the new `PATH`."""
    key = next((name for name in env if name.upper() == "PATH"), "PATH")
    entries = [entry for entry in env.get(key, "").split(os.pathsep) if entry]
    kept = [entry for entry in entries if which("node", path=entry) is None]
    path = os.pathsep.join(kept)
    found = which("node", path=path)
    if found is not None:
        raise ValueError(f"node still resolves at {found} with every node directory removed")
    return {**env, key: path}


def _run(argv: list[str], env: Mapping[str, str], log: Path, timeout: float) -> int | None:
    """One child, its output appended to `log`; `None` when it outran `timeout` and was killed."""
    with log.open("ab") as sink:
        proc = subprocess.Popen(  # noqa: S603 - argv[0] from `shutil.which`, no shell.
            argv, cwd=REPO, env=dict(env), stdout=sink, stderr=subprocess.STDOUT
        )
        try:
            return proc.wait(timeout=max(timeout, 0.0))
        except subprocess.TimeoutExpired:
            _kill(proc)
            return None


def _kill(proc: subprocess.Popen[bytes]) -> None:
    """The child and everything it spawned: on Windows `taskkill /T`, elsewhere `kill()`."""
    taskkill = shutil.which("taskkill") if os.name == "nt" else None
    if taskkill is not None:
        subprocess.run(  # noqa: S603 - argv[0] from `shutil.which`, a pid, no shell.
            [taskkill, "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        proc.kill()
    proc.wait()


def _blocks(env: Mapping[str, str], log: Path) -> bool:
    """Ruling 2's negative control: a fresh interpreter under `env` is refused the network."""
    code = _run([sys.executable, "-c", _CONTROL], env, log, 60.0)
    return code not in (0, None) and "Q-G22" in log.read_text(encoding="utf-8", errors="replace")


def _say(line: str) -> None:
    sys.stdout.write(line + "\n")


def _tail(log: Path) -> list[str]:
    if not log.is_file():
        return []
    return log.read_text(encoding="utf-8", errors="replace").splitlines()[-_TAIL:]


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    run: Runner = _run,
    clock: Callable[[], float] = time.perf_counter,
    which: Callable[..., str | None] = shutil.which,
    blocks: Callable[[Mapping[str, str], Path], bool] = _blocks,
) -> int:
    """0 parity holds, 1 a step failed or ran past the ceiling, 2 the gate did not run."""
    parser = argparse.ArgumentParser(
        prog="gate_parity.py",
        description="Q-G22: uv sync && pytest, offline, GPU-free and Node-free, within 600 s.",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-gpu", action="store_true")
    parser.add_argument("--no-node", action="store_true")
    parser.add_argument("--perf", type=Path, default=REPO / PERF, metavar="PATH")
    parser.add_argument("--log", type=Path, default=None, metavar="PATH")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_NOT_RUN
    missing = [f"--{name.replace('_', '-')}" for name in _FLAGS if not getattr(args, name)]
    if missing:
        _say(f"Q-G22 DID NOT RUN  {', '.join(missing)} not given: a run without it is not parity")
        return EXIT_NOT_RUN
    try:
        limit = ceiling(tomllib.loads(args.perf.read_text(encoding="utf-8")))
        child = no_node_env(no_gpu_env(offline_env(os.environ if env is None else env)), which)
    except (OSError, ValueError) as exc:
        _say(f"Q-G22 DID NOT RUN  {exc}")
        return EXIT_NOT_RUN
    uv = which("uv", path=next((v for k, v in child.items() if k.upper() == "PATH"), ""))
    if uv is None:
        _say("Q-G22 DID NOT RUN  uv is not on the run's PATH")
        return EXIT_NOT_RUN
    with tempfile.TemporaryDirectory(prefix="ow-parity-") as scratch:
        armed = arm(Path(scratch), child)
        if not blocks(armed, Path(scratch) / "control.log"):
            _say(
                "Q-G22 DID NOT RUN  the blocker did not block: "
                "a fresh interpreter reached the network"
            )
            return EXIT_NOT_RUN
        log = args.log or Path(scratch) / "parity.log"
        return _judge(uv, armed, log=log, limit=limit, run=run, clock=clock)


def _judge(
    uv: str,
    env: Mapping[str, str],
    *,
    log: Path,
    limit: float,
    run: Runner,
    clock: Callable[[], float],
) -> int:
    """Rulings 5 and 6: the two steps, timed together against the ceiling."""
    _say(f"Q-G22  offline (audited), GPU-free, Node-free; ceiling {limit:.0f} s")
    start = clock()
    results = []
    for name, rest in _STEPS:
        code = run([uv, *rest], env, log, limit - (clock() - start))
        results.append((name, code))
        if code != 0:
            break
    elapsed = clock() - start
    for name, code in results:
        verdict = "killed at the ceiling" if code is None else f"exit {code}"
        _say(f"  {name:<8}  {verdict}")
    _say(f"  wall      {elapsed:.1f} s of {limit:.0f} s")
    ran = len(results) == len(_STEPS) and all(code == 0 for _, code in results)
    passed = ran and elapsed <= limit
    for line in _tail(log)[-1:] if passed else _tail(log):
        _say(f"  | {line}")
    _say(f"Q-G22 {'ok' if passed else 'FAIL'}  {elapsed:.1f} s")
    return EXIT_CLEAN if passed else EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
