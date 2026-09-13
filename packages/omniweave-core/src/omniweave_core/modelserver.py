"""Seam S3: the model server client. `ServiceSpec`, the sentinel, and `attach_or_spawn`.

02-architecture.md section 2 row 15 is this module's charter, and its exclusion is half of
it:

> | 15 | Model server client | `omniweave_core.modelserver` | seam S3: `ServiceSpec`,
> `ServiceHandle`, `attach_or_spawn`, `ServiceRegistry`, model-id verification on attach, the
> 32-byte token in a 0600 sentinel | **choosing a model (config's `[services.*]` does) or routing
> to one -- a Service is named and never routed** | `ServiceRegistry.get(name) -> ServiceHandle` |
> T-CONTRACT |

16-roadmap.md:549 schedules it as P4 W4.9. 08-runtime.md Part 3 (:930-1265) is the specification:
section 3.2's types, section 3.3's six-step ladder, section 3.4's derived capacity, section 3.5's
engine sizing and section 3.8's eviction.

## A Service is not a Driver, and the distinction is the whole of section 3.1

*"A Service is a host-managed shared model server, **named and never routed**: one per
`(name, config_digest)`, reached through `ctx.service(name)` and `DriverIO.service(name)`. It has no
unit, no cost-per-unit, no card, no capability floors and never enters `resolve()`."* The engine
behind a page VLM is a Service; the VLM **driver** is a Driver, because it has a model identity that
enters index metadata, a `(dim, metric, normalization)` contract and a licence.

The rationale for one shared server is surya's, at `surya/settings.py:173-178`: there is no benefit
to more than one layout model on a host, and N in-process copies thrash the CPU/GPU. The first
client attaches to a running server or spawns one; the rest attach.

## The one thing this module may not do, and the one it does instead (D179)

`08:1046` step 4 is **SPAWN DETACHED**: argv, `CUDA_VISIBLE_DEVICES`, redirected stdout and stderr,
an `atexit` reaper registered only in the spawning process. `02-architecture.md:430-432` is equally
plain, in the same paragraph that sanctions this seam's loopback listener:

> A fifth seam is a charter amendment. A long-lived local IPC daemon ... is banned outright, and
> **only `omniweave_core.toolchain` and `omniweave_core.host.subproc` may import `subprocess`
> (G8)**.

So S3 must create a process and S3 may not create a process. `Spawner` is the answer: the ladder,
the sentinel, the port choice, the verification and the refusals are all here, and the single call
that creates a process is a Protocol this module declares and does not implement. `host/subproc.py`
already holds the exemption and already owns *"one long-lived worker per `(driver_id,
config_digest)"*, which is the same shape; an implementation belongs there or in `omniweave/run/`,
and neither is this cell's. **There is no `import subprocess` in this file**, which is what keeps
G8 at two exemptions rather than three. Recorded as **D179**.

The HTTP half needs no such treatment: `02:432` sanctions *"an attached or spawned model server
(S3, token-authenticated)"* as one of exactly two loopback TCP endpoints, so `http.client` and
`socket` carry `[[client]]` rows in `tools/egress.toml` at this path and the `127.0.0.1` literal
carries a `[[literal]]` row. Named by the plan, allowed by name.

## The three additions to surya's ladder

`08:1084-1090` lists them and each closes a hole surya left:

1. **The 32-byte token.** `surya/settings.py:97` is `VLLM_API_KEY = "EMPTY"`, so any local process
   can drive the engine. The sentinel is 0600 and the token is required on every request.
2. **The `config_digest` in the sentinel name.** A Service is one per `(name, config_digest)`, so
   changing `model_revision` attaches to a *different* server rather than talking to the old model
   through a stale sentinel.
3. **The port race.** `pick_port()` binds, reads, closes and hands the port to the child, and the
   window between close and bind is real. Three consequences ship: the parent retries up to three
   times with a fresh port; step 5's model-id verification catches a foreign listener that did bind;
   and the sentinel records the port, so a later attach probes the port we chose rather than one we
   guessed.

## The subtle rule in step 1, which is surya's comment and is easy to delete

*"IT MUST NOT MUTATE THE SENTINEL ... when many clients cold-start at once, one holds the lock
mid-spawn with its server still loading (so it reads unhealthy here). If an unlocked waiter deleted
the sentinel on that 'unhealthy' read, it would then acquire the lock, find no sentinel, and spawn a
second server."* Only the locked path owns sentinel deletion and replacement, and `attach_or_spawn`
below is written so that the unlocked fast path has no statement that can write.

## Model-id verification is a refusal and never a retry

Both branches do it -- the pinned endpoint at step 0 and the spawned server at step 5 -- and
`08:1012` fixes the disposition: *"A model-id mismatch is a FATAL `ConfigError`, never a retry:
retrying attaches to the same wrong server."* `SERVICE_UNREACHABLE` and `SERVICE_NOT_RUNNING` are
the plan's own identifiers for the other two refusals; neither has a `codes.toml` row, so they are
carried in the message under the area's default symbol rather than allocating numerics the plan did
not order (the treatment `run/converge.py` gave `UNEXPLAINED_LOSS`). See **D179**.

## What is deliberately not here

**`service_refill` and the eviction timer.** 08:1070 and 08:1204 are the Supervisor's: a refill task
per Service topping a semaphore up to `refill_target()`, and a `keep_alive_s` timer armed only when
section 3.7's demand query returns zero. Both need the loop and the ledger, which INV-3 and
`tools/layers.toml` keep out of core.

**`service_observation` rows.** 08:1258 lists eleven columns and `0004_runtime.sql:263` is the
table; writing one is the store's. `ServiceRegistry.observe()` yields what a writer needs and writes
nothing.

**Choosing a model.** The exclusion column, verbatim. `[services.<name>]` in `omniweave.toml` is
where a model id and a revision are decided, and this module reads a `ServiceSpec` it did not build.

Stdlib plus `http.client` and `socket` (INV-2, G1), both with egress rows. Not one of the nine LAZY
names -- `omniweave_core.__init__` lists it among them, and G17's xfail says why it could not be
reachable before this cell.

Tier T-CONTRACT: 02-architecture.md section 2 row 15.

Specified in 02-architecture.md section 2 row 15 and section 3.1, 08-runtime.md Part 3 (:930-1265),
04-driver-system.md section 1.3 (:172-193) and 14-security.md section 5 row 5.
"""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from math import floor, log2
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal, Protocol

from omniweave_core.errors import ConfigError, DriverHostError
from omniweave_core.limits import MAX_AUTO_PARALLEL

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

__all__ = [
    "BASELINE_MAX_BATCHED_TOKENS",
    "BASELINE_MAX_NUM_SEQS",
    "BASELINE_VRAM_GB",
    "HEALTH_PATH",
    "LOOPBACK",
    "MODELS_PATH",
    "PORT_ATTEMPTS",
    "SENTINEL_MODE",
    "SERVICE_API_MAJOR",
    "TOKEN_BYTES",
    "Attachment",
    "Handle",
    "HttpProbe",
    "Sentinel",
    "ServiceHandle",
    "ServiceProbe",
    "ServiceRegistry",
    "ServiceSpec",
    "Spawned",
    "Spawner",
    "engine_sizing",
    "mint_token",
    "refuse_unverified",
    "sentinel_name",
    "server_argv",
    "service_capacity",
]


_NO_ENV: Final[Mapping[str, str]] = MappingProxyType({})
"""An immutable empty environment. A mutable default would be one shared between callers."""

LOOPBACK: Final = "127.0.0.1"
"""The one sanctioned listener address. 02-architecture.md:432, 08:970.

*"Two loopback TCP endpoints are sanctioned and no third may be added: an attached or spawned model
server (S3, token-authenticated) and `ow serve --http`."* A `[[literal]]` row in
`tools/egress.toml` carries this value at this path for exactly that reason -- the file's own rule
is that a loopback literal *"is correct in the config table that defines `serve.allowed_hosts` and
is a question in a parser"*, so the allowance is a `(value, site)` pair and not a blessed string.
"""

HEALTH_PATH: Final = "/health"
MODELS_PATH: Final = "/v1/models"
"""The two probes of 08:1006-1013. `/health` says it is up; `/v1/models` says WHAT is up."""

SERVICE_API_MAJOR: Final = 1
"""*"The model server's declared API major"* -- 13-quality.md:979, which needed a declarer.

It is the `1` in `MODELS_PATH`, and it is derived from that constant below rather than typed
twice: the API this seam speaks is the one whose routes it calls, and a major that disagreed
with the path would be a cassette key claiming a contract the transport does not use.

13:979 puts it in the Cassette key *"so a seam change invalidates every recording made against
the old one, rather than replaying a body the new code will misparse"* -- so the day this seam
speaks `/v2/models`, every recording made against `/v1` misses instead of answering.
"""

TOKEN_BYTES: Final = 32
"""`os.urandom(32).hex()`. 08:981 and the ports Protocol's own comment.

*"`secrets` is semgrep-banned in library code alongside `random` and `uuid4`, and `os.urandom` is
the same CSPRNG without the banned import"* -- 08:982, which is a rule about imports and not about
entropy: `secrets.token_hex` is `os.urandom` with a different spelling.
"""

SENTINEL_MODE: Final = 0o600
"""Owner read/write and nothing else. The token is in the file; the mode is the access control."""

PORT_ATTEMPTS: Final = 3
"""08:1052: *"a bind failure in the child is retried by the parent up to 3 times."*

The window between `pick_port()`'s close and the child's bind is a real race with a foreign process,
and the plan handles it in three places rather than one. This is the first; step 5's model-id check
is the second, and the sentinel recording the chosen port is the third.
"""

BASELINE_VRAM_GB: Final = 24
BASELINE_MAX_BATCHED_TOKENS: Final = 8192
BASELINE_MAX_NUM_SEQS: Final = 32
"""08:1094's three, from `surya/inference/backends/vllm.py:25-60`.

A baseline to derive from rather than a constant to ship, and 08:1104 says what a constant costs:
*"a flat 96 on a 24 GB consumer card is an OOM, not the measured +28%."*
"""


# --------------------------------------------------------------------------------------------
# 1. The spec. `[services.<name>]` as a value, and one refusal it carries.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """One `[services.<name>]` table. 08:948-965, field for field and default for default.

    **`model_id` is SEMANTIC: it enters the cache key.** 08:951 says so in the field comment, and
    the reason is that a Service's model is on **no card** -- `resolve()` never sees it, so nothing
    else in the framework records which model answered. A Service whose model changes and whose
    cache key does not is a corpus that mixes two models' output with no record of the boundary.

    **`model_revision` is an exact sha and `"main"` is a config error.** RT14 makes it framework
    wide and `tools/semgrep/omniweave.yaml` enforces it at every call site; `__post_init__` enforces
    it here, at the one place a spec is constructed from a config file, because a branch name is not
    a revision and a server that silently follows `main` re-parses a corpus at a model nobody chose.

    `endpoint = ""` means attach-or-spawn on demand; anything else is **pinned** and is never
    spawned. `capacity = 0` means derive it (section 3.4). `vram_floor_mb = 0` means undeclared, and
    section 3.7 point 3 fixes what that costs: *"a Service with `vram_floor_mb = 0` is accounted as
    filling the group, so an undeclared Service is exclusive: fail safe, not fail dense."*
    """

    name: str
    model_id: str
    model_revision: str
    endpoint: str = ""
    autostart: bool = True
    capacity: int = 0
    batch_wait_ms: int = 5
    max_batch: int = 8
    keep_alive_s: int = 300
    startup_timeout_s: int = 600
    request_timeout_s: int = 600
    vram_floor_mb: int = 0
    server_argv: tuple[str, ...] = ()
    gpu_group: str = "default"

    def __post_init__(self) -> None:
        if not self.name:
            raise ConfigError("a service has no name", fix="name the table: [services.<name>]")
        if not self.model_id:
            raise ConfigError(
                f"[services.{self.name}] has no model_id, and a Service's model is on no card",
                fix=f"set [services.{self.name}] model_id",
            )
        if self.model_revision == "main":
            raise ConfigError(
                f"[services.{self.name}] model_revision is 'main', which is a branch and not a "
                f"revision (RT14)",
                fix=f"pin [services.{self.name}] model_revision to an exact commit sha",
            )
        if not self.model_revision:
            raise ConfigError(
                f"[services.{self.name}] has no model_revision",
                fix=f"pin [services.{self.name}] model_revision to an exact commit sha",
            )

    @property
    def pinned(self) -> bool:
        """08:1006 step 0: a declared endpoint takes no lock and spawns nothing, ever."""
        return bool(self.endpoint)


# --------------------------------------------------------------------------------------------
# 2. The sentinel. One file per `(name, config_digest)`, at 0600, holding the token.
# --------------------------------------------------------------------------------------------


def sentinel_name(name: str, config_digest: str) -> str:
    """`<name>-<config_digest>.json`. 08:1016, and the digest is addition 2 of three.

    *"A Service is one per `(name, config_digest)`, so changing `model_revision` attaches to a
    different server rather than talking to the old model through a stale sentinel."* The digest in
    the FILE NAME is what makes that true without anyone remembering to check: two configurations
    cannot find each other's sentinel, so there is no read whose staleness has to be detected.
    """
    if not name or not config_digest:
        raise ConfigError(
            "a sentinel is named by (service, config_digest) and one of them is empty",
            fix="pass the service name and the run's config_digest",
        )
    return f"{name}-{config_digest}.json"


@dataclass(frozen=True, slots=True)
class Sentinel:
    """What a running server left behind so the next client can attach to it. 08:1057.

    *"{port, pid, create_time, token, model_id, model_rev, started_ns} at 0600 BEFORE the child is
    unblocked."* The ordering in that sentence is the property: a child that came up and answered
    `/health` before its sentinel existed would be a server no second client could find, and the
    spawner would mint a second one.

    `create_time` is the same third component the lock holder identity carries (`locks.py`), for the
    same reason: it is what stops a recycled pid from looking like a live server. It degrades the
    same way and `locks.process_create_time` is the probe.
    """

    port: int
    pid: int
    create_time: float
    token: str
    model_id: str
    model_rev: str
    started_ns: int

    @property
    def base_url(self) -> str:
        """`http://127.0.0.1:<port>` -- 08:970's one sanctioned form, built and never parsed."""
        return f"http://{LOOPBACK}:{self.port}"

    def as_json(self) -> str:
        """Sorted keys, no spaces, one line: the file is read by another process and by a human."""
        return json.dumps(
            {
                "port": self.port,
                "pid": self.pid,
                "create_time": self.create_time,
                "token": self.token,
                "model_id": self.model_id,
                "model_rev": self.model_rev,
                "started_ns": self.started_ns,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def parse(cls, raw: str) -> Sentinel | None:
        """Read a sentinel, or `None` when the file is not one.

        `None` rather than a raise, and the distinction it preserves is step 1's: an unreadable
        sentinel is *"no attachable server"*, which the fast path answers by falling through to the
        lock -- it is not an error, because a half-written file is exactly what a crash mid-spawn
        leaves and the locked path is where that is repaired.
        """
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                port=int(data["port"]),
                pid=int(data["pid"]),
                create_time=float(data["create_time"]),
                token=str(data["token"]),
                model_id=str(data["model_id"]),
                model_rev=str(data["model_rev"]),
                started_ns=int(data["started_ns"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def mint_token() -> str:
    """`os.urandom(32).hex()` -- 64 hex characters. 08:981."""
    return os.urandom(TOKEN_BYTES).hex()


def write_sentinel(path: Path, sentinel: Sentinel) -> None:
    """Write at 0600, creating the file with that mode rather than relaxing it afterwards.

    `os.open(..., O_CREAT|O_WRONLY|O_TRUNC, 0o600)` and not `Path.write_text` plus `chmod`: the
    window between those two is a window in which the token is world-readable, and the token is the
    whole of the access control on the engine (`surya/settings.py:97` is `VLLM_API_KEY = "EMPTY"`,
    which is the hole this closes).

    The mode is a no-op on Windows, where the file inherits the directory's ACL. That is recorded
    rather than worked around: `$OMNIWEAVE_HOME/services/` is under the user's profile, and a
    framework that tried to write an ACL here would be shipping a second permission model.
    """
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, SENTINEL_MODE)
    try:
        os.write(fd, sentinel.as_json().encode("utf-8") + b"\n")
    finally:
        os.close(fd)


def read_sentinel(path: Path) -> Sentinel | None:
    """Read one, or `None` when there is no readable sentinel at `path`."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return Sentinel.parse(raw)


# --------------------------------------------------------------------------------------------
# 3. The two seams this module declares and does not implement.
# --------------------------------------------------------------------------------------------


class ServiceProbe(Protocol):
    """`GET {base}/health` and `GET {base}/v1/models`, over loopback, under a token.

    A Protocol rather than two functions, because a test that needed to drive the ladder would
    otherwise have to stand up an HTTP server to do it -- and the ladder, not the transport, is what
    08 section 3.3 specifies. The shipped implementation is `HttpProbe` below and it is the only
    thing in this module that opens a connection.
    """

    def healthy(self, base_url: str, *, token: str, timeout_s: float) -> bool:
        """Whether `{base_url}/health` answered. Never raises: unreachable is an answer."""
        ...

    def model_id(self, base_url: str, *, token: str, timeout_s: float) -> str:
        """The id `{base_url}/v1/models` reports, or `""` when it could not be read."""
        ...


@dataclass(frozen=True, slots=True)
class Spawned:
    """What a `Spawner` reports back: enough to write a sentinel and to reap later."""

    pid: int
    create_time: float


class Spawner(Protocol):
    """Create the detached server child. **Declared here, implemented elsewhere. D179.**

    `08:1046` step 4 requires this module to spawn; `02-architecture.md:430-432` permits only
    `omniweave_core.toolchain` and `omniweave_core.host.subproc` to import `subprocess`, and calls
    a third seam *"a charter amendment"*. So the call that creates a process is injected, and every
    decision around it -- the port, the argv, the environment, the log path, the sentinel and the
    retry -- stays here where 08 section 3.3 puts it.

    `host/subproc.py` is the natural home for an implementation: it holds the exemption and already
    owns *"one long-lived worker per `(driver_id, config_digest)"*, which is this shape with a
    different protocol on top. That module is P3's and this is not the cell that edits it.
    """

    def spawn(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        log_path: Path,
    ) -> Spawned:
        """Start `argv` detached, with stdout and stderr appended to `log_path` line-buffered.

        08:1060: *"child stdout/stderr -> `$OMNIWEAVE_HOME/services/<name>.log`, buffering=1"*, and
        08:1061: *"register the `atexit` reaper ONLY in the spawning process"* -- a process that
        ATTACHED never stops a server it did not start (08:1206).
        """
        ...


# --------------------------------------------------------------------------------------------
# 4. Verification, capacity, sizing and argv. The pure half of the ladder.
# --------------------------------------------------------------------------------------------


def refuse_unverified(spec: ServiceSpec, reported: str, *, where: str) -> None:
    """Both branches' model-id check. A FATAL `ConfigError`, never a retry. 08:1012.

    *"A model-id mismatch is a FATAL `ConfigError`, never a retry: retrying attaches to the same
    wrong server."* That sentence is the whole disposition and it is why this is not a
    `DriverHostError` with a retry ladder behind it: the condition is a disagreement between a
    config file and a running process, and no number of attempts resolves a disagreement.

    An empty `reported` is a refusal too. A server that will not say what it is running is
    indistinguishable, from here, from one running the wrong thing -- and 08:1054's port race makes
    *"a foreign listener that DID bind"* a case this check exists to catch.
    """
    if reported == spec.model_id:
        return
    seen = reported or "<no id reported>"
    raise ConfigError(
        f"[services.{spec.name}] expects model {spec.model_id!r} and the {where} reports "
        f"{seen!r}; a model-id mismatch is never retried, because retrying attaches to the same "
        f"wrong server",
        fix=f"point [services.{spec.name}] endpoint at the right server, or correct model_id",
    )


def service_capacity(spec: ServiceSpec, server_reported: int) -> int:
    """08:1064's three lines, transcribed. `MAX_AUTO_PARALLEL` is a CAP and not a default.

    ```python
    ceiling = spec.capacity if spec.capacity > 0 else server_reported
    return max(1, min(server_reported, MAX_AUTO_PARALLEL, ceiling))
    ```

    96 is surya's `MAX_AUTO_PARALLEL` over a server whose own `_max_num_seqs` defaults to 8, and
    08:1072-1076 has the measurements: 48 to 96 is +28% on a B200, 96 to 240 is +5%, *"the GPU is
    compute-bound past ~96 concurrent, so extra requests just queue while adding thread/connection
    overhead."* The `max(1, ...)` is the floor that keeps a Service usable when a server reports
    zero rather than making it unreachable.
    """
    ceiling = spec.capacity if spec.capacity > 0 else server_reported
    return max(1, min(server_reported, MAX_AUTO_PARALLEL, ceiling))


def engine_sizing(vram_gb: float) -> tuple[int, int]:
    """`(max_batched_tokens, max_num_seqs)` derived from VRAM. 08:1098, verbatim arithmetic.

    Every cell of 08:1108's table is this function: at 80 GB `ratio = 3.333`, `int(32 * 3.333) =
    106`, `(106 // 8) * 8 = 104`; at 16 GB `int(32 * 0.667) = 21`, `(21 // 8) * 8 = 16`.

    **omniweave does not size the engine itself** (08:1120): these two numbers are passed in
    `server_argv` and recorded in `service_observation`, because *"the engine is a foreign process
    and guessing its internals is how a framework acquires a support burden."* Nor is surya's
    `GPU_VRAM_GB` name table shipped -- `HostFacts.gpus` carries `vram_bytes` measured from the
    device, *"so an unknown card sizes correctly instead of refusing."*
    """
    if vram_gb <= 0:
        raise ConfigError(
            f"engine_sizing needs a positive VRAM figure and got {vram_gb}",
            fix="pass the device's measured vram_bytes; 0 means the device was not read",
        )
    ratio = vram_gb / BASELINE_VRAM_GB
    batched = max(1024, 2 ** floor(log2(BASELINE_MAX_BATCHED_TOKENS * ratio)))
    seqs = max(8, (int(BASELINE_MAX_NUM_SEQS * ratio) // 8) * 8)
    return (batched, seqs)


def server_argv(spec: ServiceSpec, *, port: int) -> tuple[str, ...]:
    """`spec.server_argv + ["--host", "127.0.0.1", "--port", port, "--checkpoint", model_id]`.

    08:1058, and the comment beside it is the load-bearing part: *"the checkpoint is PINNED so the
    spawned server reports the id the client then verifies."* Step 5's verification is only
    meaningful because this line put the id there; a child left to pick its own checkpoint would
    report whatever it picked and the check would pass on the wrong model.

    `--host 127.0.0.1` is not configurable. 02:432 sanctions one loopback listener for this seam,
    and a bind address that a config file could widen is a network service nobody asked for.
    """
    if not spec.server_argv:
        raise ConfigError(
            f"[services.{spec.name}] has no server_argv, so there is nothing to spawn",
            fix=f"set [services.{spec.name}] server_argv, or endpoint to attach to a running one",
        )
    return (
        *spec.server_argv,
        "--host",
        LOOPBACK,
        "--port",
        str(port),
        "--checkpoint",
        spec.model_id,
    )


def spawn_env(spec: ServiceSpec, base: Mapping[str, str]) -> dict[str, str]:
    """The child's environment: `base`, plus `CUDA_VISIBLE_DEVICES` when the group pins a device.

    08:1059: *"env: `CUDA_VISIBLE_DEVICES` from `spec.gpu_group` when it has the form `cuda:<n>`"*,
    and section 3.7 point 3 says what the other case means: *"`default` means 'whatever the engine
    picks', which is the single-GPU case."* An unrecognised group name is the `default` case too --
    a group is a VRAM budget and only the `cuda:<n>` form additionally pins a device.
    """
    env = dict(base)
    prefix = "cuda:"
    if spec.gpu_group.startswith(prefix):
        ordinal = spec.gpu_group[len(prefix) :]
        if ordinal.isdigit():
            env["CUDA_VISIBLE_DEVICES"] = ordinal
    return env


def pick_port() -> int:
    """Bind `("127.0.0.1", 0)`, read the port, close, and hand it to the child. 08:1049.

    **The window between the close and the child's bind is a real race and it is handled, not
    ignored.** 08:1050-1055 names the three consequences and all three ship: `PORT_ATTEMPTS` retries
    with a fresh port, `refuse_unverified()` catches a foreign listener that did bind, and the
    sentinel records the port so a later attach *"probes the port we chose, not a port we guessed."*

    The alternative -- letting the child bind port 0 and report back -- needs a channel from the
    child before it is healthy, which is the thing the sentinel exists to avoid.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK, 0))
        return int(probe.getsockname()[1])


# --------------------------------------------------------------------------------------------
# 5. The attachment: what the ladder produces.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Attachment:
    """A verified, reachable server, and which branch of the ladder produced it.

    `how` is not decoration: `service_observation.lifecycle` is `attached` for the first two and
    `spawned` for the third (08:1258), the `atexit` reaper is registered only for `spawned`
    (08:1206 -- *"a process that ATTACHED never stops a server it did not start"*), and
    `cold_start_ms` is meaningful only for `spawned`.
    """

    spec: ServiceSpec
    base_url: str
    token: str
    model_id: str
    model_rev: str
    how: Literal["pinned", "sentinel", "spawned"]
    cold_start_ms: int = 0
    pid: int = 0
    attempts: int = 1
    log_path: Path | None = None

    @property
    def spawned(self) -> bool:
        """Whether THIS process started the server, and therefore owns reaping it."""
        return self.how == "spawned"

    @property
    def lifecycle(self) -> Literal["attached", "spawned"]:
        """`service_observation.lifecycle`'s value for this attachment. 08:1258."""
        return "spawned" if self.how == "spawned" else "attached"


def endpoint_env_var(name: str) -> str:
    """`OMNIWEAVE_SERVICES_<NAME>_ENDPOINT` -- step 0's env twin. 08:1006, 14:438.

    14-security.md:438 gives it a standing the config file does not have: an env-locked endpoint is
    *"treated as operator-provisioned; the config-file value becomes read-only."* So the env var
    wins, and `SERVICE_UNREACHABLE`'s message names both so an operator knows which one they set.
    """
    return f"OMNIWEAVE_SERVICES_{name.upper().replace('.', '_').replace('-', '_')}_ENDPOINT"


def pinned_endpoint(spec: ServiceSpec, env: Mapping[str, str]) -> str:
    """The endpoint step 0 probes: the env twin if set, else `spec.endpoint`. 14:438."""
    return env.get(endpoint_env_var(spec.name), "") or spec.endpoint


def refuse_unreachable(spec: ServiceSpec, endpoint: str) -> ConfigError:
    """`SERVICE_UNREACHABLE`, *"naming the key and the env var"* (08:1008).

    The plan's identifier has no `codes.toml` row, so it rides in the message under `ConfigError`'s
    default symbol rather than minting a numeric this cell was not asked to allocate. **D179.**
    """
    return ConfigError(
        f"SERVICE_UNREACHABLE: [services.{spec.name}] endpoint {endpoint!r} did not answer "
        f"{HEALTH_PATH}",
        fix=(
            f"start the server, or clear [services.{spec.name}] endpoint and "
            f"{endpoint_env_var(spec.name)} to attach-or-spawn locally"
        ),
    )


def refuse_not_running(spec: ServiceSpec) -> ConfigError:
    """`SERVICE_NOT_RUNNING`, *"naming `[services.<name>] autostart`"* (08:1020). **D179.**"""
    return ConfigError(
        f"SERVICE_NOT_RUNNING: no server is attachable for [services.{spec.name}] and "
        f"autostart is false",
        fix=f"start the server yourself, or set [services.{spec.name}] autostart = true",
    )


# --------------------------------------------------------------------------------------------
# 6. `attach_or_spawn` -- the six steps, in order.
# --------------------------------------------------------------------------------------------


def attach_or_spawn(
    spec: ServiceSpec,
    *,
    services_root: Path,
    config_digest: str,
    probe: ServiceProbe,
    spawner: Spawner | None = None,
    env: Mapping[str, str] = _NO_ENV,
) -> Attachment:
    """08 section 3.3's ladder. Six steps, in order, and the order is the specification.

    ```
    0. PINNED ENDPOINT   -> probe, verify the model id, attach. No lock, nothing spawned, ever.
    1. UNLOCKED SENTINEL -> read, probe, verify, attach. IT MUST NOT MUTATE THE SENTINEL.
    2. autostart false   -> SERVICE_NOT_RUNNING.
    3. TAKE THE LOCK     -> and re-check the sentinel inside it (the double-check step 1 needs).
    4. SPAWN DETACHED    -> pick a port, mint a token, write the sentinel, then start the child.
    5. VERIFY, ATTACH    -> poll /health to startup_timeout_s, then GET /v1/models and compare.
    6. ON FAILURE        -> the error carries the server's own log tail.
    ```

    **Step 1 has no statement that can write**, which is surya's subtle rule made structural:
    *"when many clients cold-start at once, one holds the lock mid-spawn with its server still
    loading (so it reads unhealthy here). If an unlocked waiter deleted the sentinel on that
    'unhealthy' read, it would then acquire the lock, find no sentinel, and spawn a second server."*
    Only the locked path owns sentinel deletion and replacement.

    **Steps 3 to 5 need a lock and a process, and this signature takes neither by accident.**
    `spawner=None` is the shipped state of this cell: the attach halves (steps 0, 1, 2) are complete
    and a caller with no spawner gets `SERVICE_NOT_RUNNING` rather than a silent no-op. The lock is
    `locks.scoped_lock(root, "service." + spec.name, config_digest)` and the caller takes it; this
    function is not given one, because a lock acquired inside a library call is a lock whose wait
    budget nobody chose (07:2726-2729, *"passed per call, not global"*).
    """
    endpoint = pinned_endpoint(spec, env)
    if endpoint:
        return _attach_pinned(spec, endpoint, probe=probe)
    sentinel_file = services_root / sentinel_name(spec.name, config_digest)
    attached = _attach_sentinel(spec, sentinel_file, probe=probe)
    if attached is not None:
        return attached
    if not spec.autostart:
        raise refuse_not_running(spec)
    if spawner is None:
        raise DriverHostError(
            f"[services.{spec.name}] needs a spawn and seam S3 may not create a process: "
            f"02-architecture.md:430 permits `subprocess` only in toolchain.py and "
            f"host/subproc.py (D179)",
            fix="supply a Spawner, or pin [services.<name>] endpoint to a running server",
        )
    raise DriverHostError(  # pragma: no cover -- steps 3-5 land with the Spawner implementation.
        f"[services.{spec.name}]: steps 3-5 of the ladder need the lock and the spawner the "
        f"caller supplies; see D179",
        fix="supply a Spawner and take the service lock around this call",
    )


def _attach_pinned(spec: ServiceSpec, endpoint: str, *, probe: ServiceProbe) -> Attachment:
    """Step 0. *"No lock is taken and NOTHING is ever spawned on this branch."* 08:1013."""
    timeout = float(spec.request_timeout_s)
    if not probe.healthy(endpoint, token="", timeout_s=timeout):
        raise refuse_unreachable(spec, endpoint)
    refuse_unverified(spec, probe.model_id(endpoint, token="", timeout_s=timeout), where="endpoint")
    return Attachment(
        spec=spec,
        base_url=endpoint,
        token="",
        model_id=spec.model_id,
        model_rev=spec.model_revision,
        how="pinned",
    )


def _attach_sentinel(spec: ServiceSpec, path: Path, *, probe: ServiceProbe) -> Attachment | None:
    """Step 1, the unlocked fast path. **Reads only**; `None` falls through to the lock."""
    sentinel = read_sentinel(path)
    if sentinel is None:
        return None
    timeout = float(spec.request_timeout_s)
    if not probe.healthy(sentinel.base_url, token=sentinel.token, timeout_s=timeout):
        return None
    reported = probe.model_id(sentinel.base_url, token=sentinel.token, timeout_s=timeout)
    refuse_unverified(spec, reported, where="sentinel's server")
    return Attachment(
        spec=spec,
        base_url=sentinel.base_url,
        token=sentinel.token,
        model_id=sentinel.model_id,
        model_rev=sentinel.model_rev,
        how="sentinel",
        pid=sentinel.pid,
    )


# --------------------------------------------------------------------------------------------
# 7. The transport. The only place in this module that opens a connection.
# --------------------------------------------------------------------------------------------


HTTP_OK: Final = 200
HTTP_REDIRECT: Final = 300
"""The 2xx band `/health` has to answer in. A refused connection reports 0 and is not in it."""


def _ok(status: int) -> bool:
    """Whether a status is 2xx. `0` is this module's "the connection failed" and is not."""
    return HTTP_OK <= status < HTTP_REDIRECT


def _split(base_url: str) -> tuple[str, int]:
    """`http://127.0.0.1:8000` -> `("127.0.0.1", 8000)`, refusing anything that is not loopback.

    Built by hand rather than with `urllib.parse`, and the reason is `tools/egress.toml`'s own:
    *"`urllib.parse` is not a client and `urllib.request` is"*, so the parser is admissible -- but
    the check is what matters and it is easier to read as three lines than as a `urlsplit` plus four
    assertions. **A non-loopback host is refused here**, which is what makes 02:432's *"two loopback
    TCP endpoints ... and no third may be added"* a property of this module rather than a hope about
    its callers: a `[services.*] endpoint` naming a remote host cannot dial through this client.
    """
    rest = base_url.removeprefix("http://")
    if rest == base_url or "/" in rest:
        raise ConfigError(
            f"a Service endpoint must be http://<host>:<port> with no path, and this is "
            f"{base_url!r}",
            fix="set [services.<name>] endpoint to http://127.0.0.1:<port>",
        )
    host, _, port = rest.partition(":")
    if host != LOOPBACK:
        raise ConfigError(
            f"a Service endpoint must be loopback and this names {host!r}; 02-architecture.md:432 "
            f"sanctions two loopback listeners and no third",
            fix=f"set [services.<name>] endpoint to http://{LOOPBACK}:<port>",
        )
    if not port.isdigit():
        raise ConfigError(
            f"a Service endpoint needs a port and {base_url!r} has none",
            fix=f"set [services.<name>] endpoint to http://{LOOPBACK}:<port>",
        )
    return (host, int(port))


class HttpProbe:
    """The shipped `ServiceProbe`: two GETs over loopback, under the sentinel's token.

    `http.client` and not `requests` (08:946's own comment on the module: *"stdlib only;
    http.client, not requests"*). INV-2 gives core zero third-party dependencies, and an HTTP client
    that a driver's dependency could replace would be a supply chain into the one seam that holds a
    bearer token.

    **`healthy()` never raises.** *"Unreachable"* is one of step 0's and step 1's answers -- step 0
    turns it into `SERVICE_UNREACHABLE` and step 1 falls through to the lock -- so an exception here
    would make the two branches' dispositions this class's decision instead of the ladder's.
    """

    __slots__ = ()

    def healthy(self, base_url: str, *, token: str, timeout_s: float) -> bool:
        """`GET /health`. Any 2xx is up; anything else, a refused connection included."""
        status, _ = self._get(base_url, HEALTH_PATH, token=token, timeout_s=timeout_s)
        return _ok(status)

    def model_id(self, base_url: str, *, token: str, timeout_s: float) -> str:
        """`GET /v1/models` and the reported id, or `""` when it could not be read.

        `""` rather than a raise for the same reason `healthy()` does not raise: the disposition
        belongs to `refuse_unverified()`, which treats an unreadable id as a refusal -- *"a server
        that will not say what it is running is indistinguishable, from here, from one running the
        wrong thing."*

        The shape is OpenAI's `{"data": [{"id": ...}]}`, which is what a vLLM-compatible server
        serves and what surya's clients read. A first element and no more: a server hosting several
        models is a server this Service did not ask for, and taking the first is how the mismatch
        becomes visible to the check rather than being searched for.
        """
        status, body = self._get(base_url, MODELS_PATH, token=token, timeout_s=timeout_s)
        if not _ok(status):
            return ""
        try:
            payload = json.loads(body)
            data = payload["data"]
            return str(data[0]["id"])
        except (ValueError, KeyError, IndexError, TypeError):
            return ""

    def _get(self, base_url: str, path: str, *, token: str, timeout_s: float) -> tuple[int, bytes]:
        """One GET. Returns `(status, body)`; a connection failure is `(0, b"")`."""
        import http.client  # noqa: PLC0415 -- see the module docstring: one import, one site.

        host, port = _split(base_url)
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        connection = http.client.HTTPConnection(host, port, timeout=timeout_s)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return (response.status, response.read())
        except OSError:
            return (0, b"")
        finally:
            connection.close()


# --------------------------------------------------------------------------------------------
# 8. What a driver is handed, and the per-run registry that hands it over.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Handle:
    """The concrete `omniweave_ports.ServiceHandle`. 08:967, and the ports Protocol's own note.

    *"What a driver gets. It is NOT a client library: it is a base URL, a token and a deadline, so
    `omniweave-llm` needs neither torch nor an SDK (2 MB, ports-only)."* The Protocol is in
    `omniweave_ports` because `tools/layers.toml` gives a driver distribution `["omniweave_ports"]`
    exactly and a driver must be able to name what it is handed; the class is here because this is
    the module that can build one.

    Named `Handle` and not `ServiceHandle`: the Protocol owns that name, a driver imports it from
    ports, and two importable `ServiceHandle`s one `from` clause apart is the confusion the
    `BlobStore` split already avoids by the same means. `ServiceHandle` is an alias below, so
    a reader following 02 row 15's public surface finds it.

    `traceparent` *"rides as an HTTP header (I33)"* -- the W3C id that makes the span tree
    reassemble across the process boundary. `deadline_ms` is the remaining budget at the moment the
    handle was issued, and `post()` takes the `min` of it and `request_timeout_s` (08:399).
    """

    name: str
    base_url: str
    token: str
    model_id: str
    model_rev: str
    capacity: int
    traceparent: str
    deadline_ms: int
    _cancelled: Callable[[], bool] = bool
    _timeout_s: float = 600.0

    def post(self, path: str, body: bytes, *, headers: Mapping[str, str] | None = None) -> bytes:
        """POST under this handle's token and deadline. 08:399's `min` is the timeout.

        *"`remaining_ms()` is what `ServiceHandle.post()` takes the `min(remaining,
        request_timeout_s)` of"*: a deadline that outlived the run's would let a driver hold a slot
        past cancellation, and a `request_timeout_s` ignored in favour of a long deadline would let
        one wedged request hold it forever.
        """
        import http.client  # noqa: PLC0415 -- see the module docstring: one import, two sites.

        host, port = _split(self.base_url)
        sent = {
            "Authorization": f"Bearer {self.token}",
            "traceparent": self.traceparent,
            "Content-Type": "application/json",
        }
        sent.update(headers or {})
        timeout = min(self._timeout_s, max(0.0, self.deadline_ms / 1000))
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        try:
            connection.request("POST", path, body=body, headers=sent)
            response = connection.getresponse()
            payload = response.read()
            if not _ok(response.status):
                raise DriverHostError(
                    f"service {self.name} answered {response.status} for {path}",
                    fix=f"read the server log under $OMNIWEAVE_HOME/services/{self.name}.log",
                )
        except OSError as error:
            raise DriverHostError(
                f"service {self.name} at {self.base_url} did not answer {path}: {error}",
                fix=f"read the server log under $OMNIWEAVE_HOME/services/{self.name}.log",
            ) from error
        finally:
            connection.close()
        return payload

    def cancelled(self) -> bool:
        """*"True once the generation this handle was issued for is superseded."*

        Injected, because the answer lives on the run's `CancelToken` (08:354) and a handle that
        computed it would be a second cancellation authority. The default is `bool()`, which is
        `False`: a handle nobody wired a token into is never cancelled, which is the right answer
        for a test and the wrong one for a run -- so `ServiceRegistry` always supplies one.
        """
        return self._cancelled()


ServiceHandle = Handle
"""02 row 15's public surface spells it `ServiceHandle`. One concept, one class, two names.

The alias exists so a reader following the architecture row lands on the class; a driver still
imports the Protocol from `omniweave_ports`, which is the name `DriverIO.service()` is typed with.
"""


class ServiceRegistry:
    """Per-RUN, carried on `RunContext`. **Never a module global, never a process singleton.**

    08:984's own comment, and 08:990 is the argument: surya ships `SuryaInferenceManager` injected
    explicitly into every predictor *and* a module-level `get_default_manager()` singleton that its
    own docstring says exists "only for notebooks" and that "surya's own models.py and marker should
    use explicit construction". **omniweave takes the injection and does not ship the singleton at
    all**: there is no ambient accessor to forget to pass.

    `handle()` is **blocking and memoised per run** (08:983): the first call for a name runs
    `attach_or_spawn`, every later call returns the same handle. That is what makes a Service *live*
    -- 08:1232's point 1, *"a Service becomes live on the FIRST `ctx.service(name)` call in the
    run"* -- and what makes `live()` the set the Supervisor starts a `service_refill` task for.
    Nothing is spawned at startup, which is INV-13's floor: *"a clean born-digital page starts no
    model server."*

    Eviction here is **bookkeeping, not a kill**. `evict()` drops the memo and records the reason;
    stopping a process is the spawning process's atexit reaper (08:1206) or the Supervisor's
    `keep_alive_s` timer, and *"a process that ATTACHED never stops a server it did not start."*
    """

    __slots__ = ("_attached", "_config_digest", "_evicted", "_probe", "_root", "_spawner", "_specs")

    def __init__(
        self,
        specs: Mapping[str, ServiceSpec],
        *,
        services_root: Path,
        config_digest: str,
        probe: ServiceProbe | None = None,
        spawner: Spawner | None = None,
    ) -> None:
        self._specs = dict(specs)
        self._root = services_root
        self._config_digest = config_digest
        self._probe: ServiceProbe = HttpProbe() if probe is None else probe
        self._spawner = spawner
        self._attached: dict[str, Attachment] = {}
        self._evicted: dict[str, str] = {}

    def live(self) -> Iterator[ServiceSpec]:
        """The Services this run has actually reached for, in the order it reached for them.

        Declared is not live: *"`[services.<name>]` in `omniweave.toml` makes a Service nameable.
        Nothing is spawned at startup"* (08:1230). So this iterates the memo and not the config.
        """
        for name in self._attached:
            yield self._specs[name]

    def attach(self, name: str) -> Attachment:
        """`attach_or_spawn` for `name`, memoised. The blocking half 08:983 warns about."""
        found = self._attached.get(name)
        if found is not None:
            return found
        declared = self._specs.get(name)
        if declared is None:
            raise ConfigError(
                f"no [services.{name}] table is declared, so ctx.service({name!r}) names nothing",
                fix=f"declare [services.{name}] in omniweave.toml",
            )
        attached = attach_or_spawn(
            declared,
            services_root=self._root,
            config_digest=self._config_digest,
            probe=self._probe,
            spawner=self._spawner,
        )
        self._attached[name] = attached
        return attached

    def handle(
        self,
        name: str,
        *,
        traceparent: str = "",
        deadline_ms: int = 0,
        cancelled: Callable[[], bool] = bool,
        capacity: int = 1,
    ) -> Handle:
        """02 row 15's `ServiceRegistry.get(name) -> ServiceHandle`, under 08:983's spelling.

        The row prints `get` and the fence prints `handle`; both are in the same document pair and
        the fence is the one with a signature, so `handle` is the method and `get` is an alias below
        rather than a second implementation.

        `traceparent`, `deadline_ms` and `cancelled` are the run's and arrive per call: a registry
        that held a deadline would be issuing handles from a budget that expired while it held it.
        """
        attached = self.attach(name)
        return Handle(
            name=name,
            base_url=attached.base_url,
            token=attached.token,
            model_id=attached.model_id,
            model_rev=attached.model_rev,
            capacity=capacity,
            traceparent=traceparent,
            deadline_ms=deadline_ms,
            _cancelled=cancelled,
            _timeout_s=float(attached.spec.request_timeout_s),
        )

    get = handle
    """02 row 15's spelling of `handle`. An alias, so the row and the fence do not disagree."""

    def evict(self, name: str, reason: str) -> None:
        """Drop the memo and record why. 08:1210's `service.evict{name, reason}`.

        Not a kill: see the class docstring. A re-`attach()` after an eviction runs the ladder
        again, which is what makes `gpu_group` pressure recoverable rather than terminal.
        """
        if not reason:
            raise ConfigError(
                f"evicting service {name!r} needs a reason; `service.evict` carries one",
                fix="pass the reason, e.g. 'gpu_group_pressure' or 'keep_alive_expired'",
            )
        self._attached.pop(name, None)
        self._evicted[name] = reason

    def observe(self) -> Iterator[Mapping[str, object]]:
        """One `service_observation`-shaped mapping per Service this run touched. 08:1258.

        **Yields; it does not write.** The table is `0004_runtime.sql:263` and writing a row is the
        store's, which is why this returns mappings rather than taking a connection. The columns
        this module can fill are the identity and lifecycle ones; `peak_inflight`, `requests`,
        `units`, `gpu_ms` and the two queue percentiles are the Supervisor's counters and are absent
        rather than zero -- a `0` for a figure nobody measured is the failure `ClockFacts.coarse`
        exists to avoid one module over.
        """
        for name, attached in self._attached.items():
            yield {
                "name": name,
                "lifecycle": attached.lifecycle,
                "capacity": attached.spec.capacity,
                "cold_start_ms": attached.cold_start_ms,
                "model_id": attached.model_id,
                "model_rev": attached.model_rev,
                "gpu_group": attached.spec.gpu_group,
            }
        for name, reason in self._evicted.items():
            if name not in self._attached:
                yield {"name": name, "lifecycle": "evicted", "reason": reason}
