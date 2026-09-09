"""The Capability probe's cache, its environment digest and its TTL policy.

**A probe verdict is an INPUT to `resolve()`, not an action it takes.** That sentence is the
resolution of the sharpest unforced contradiction in the driver spec: `resolve()` is declared pure
-- no imports, no network, no clock -- while its filter order contains `probe status != unavailable`
(04-driver-system.md section 4.7, charter erratum E5). `probe()` may import the driver's heavy
dependencies, so calling it inside `resolve()` would import torch into the process INV-3 and G17
exist to keep at 80 ms. Both statements are load-bearing, so the verdict is carried on the
`Catalog` and `resolve()` reads it; preflight refreshes it out of process, after the fact.

**The host process never runs a probe.** Section 4.7: a probe runs in the same `subproc` worker
that would run the driver, and the worker is then discarded, because probing in the host would
import the driver's dependencies into core -- the whole thing INV-4 forbids. A driver granted
`inproc` is probed in a worker too. `host/subproc.py` does not exist at P1, so **the execution seam
is an explicit injected callable** (`Prober`): `cached_probe()` owns the key, the cache, the TTL and
the timeout row, and P3 wires the real worker in as `run_probe`. Nothing in this module spawns,
imports or loads anything.

Three things this module owns and nothing else may restate (INV-21):

* `env_digest()` -- section 4.7 is its **sole home** and the only place an executable recipe for it
  is printed. There is no `host_fingerprint`; a second name for one key is the collision section 5
  X14 forbids.
* the cache key `(driver_id, driver_version, card_sha256, env_digest)` and its one-file-per-key
  path, written by an atomic replace from a same-directory temporary.
* the three-row TTL table: `ok`/`degraded` for the life of the `env_digest`, `unavailable` for
  `PROBE_TTL_S`, and a timeout as an `unavailable` carrying the printed detail string.

DR21 holds throughout: a missing capability is a pruned plan with a report, never an `ImportError`.
`ProbeVerdict.missing` is machine-actionable (`("tesseract-lang:deu",)`), `fix_hint` is printed, and
`capabilities_lost` on a `degraded` verdict lets the router re-filter rather than guess. `sys.exit`
is banned in library code, and nothing here raises on a cache fault.

Tier T-PUBLIC, and eager: 11-repo-layout.md section 1.3 puts this module on the
`errors.py limits.py config.py probe.py` line. It therefore imports no lazy subpackage and no card
code at run time -- `DriverCard` is reachable only under `TYPE_CHECKING`, so a caller pays for the
card grammar only if it already holds a card.

Specified in 04-driver-system.md section 4.7 (the whole of it), glossary.md (`env_digest`,
`probe_ttl_s`) and 11-repo-layout.md section 1.3.
"""

from __future__ import annotations

import ctypes.util
import json
import os
import platform
import re
import shutil
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeAlias

from omniweave_ports.types import ProbeEnv, ProbeStatus, ProbeVerdict

from omniweave_core.canonical import canonical, sha256_canonical
from omniweave_core.errors import ConfigError

if TYPE_CHECKING:  # a card is an argument, never an import cost on the eager path
    from omniweave_core.drivers.card import DriverCard

__all__ = [
    "CACHED_FOR_LIFE_OF_DIGEST",
    "PROBE_CACHE_DIRNAME",
    "PROBE_EPOCH_ENV",
    "PROBE_ROW_SCHEMA",
    "PROBE_TTL_S",
    "ProbeCache",
    "ProbeKey",
    "ProbeOutcome",
    "Prober",
    "cached_probe",
    "env_digest",
    "is_fresh",
    "key_for",
    "probe_cache_root",
    "probe_env",
    "timeout_verdict",
]


# --------------------------------------------------------------------------------------------
# 1. The constants. Each is a number the plan prints, and none of them is re-declared elsewhere.
# --------------------------------------------------------------------------------------------

PROBE_TTL_S: Final[int] = 600
"""How long an `unavailable` verdict is cached before it is re-probed. 04 section 4.7's table.

`unavailable` is **the verdict a user fixes**, and its inputs are not all in `env_digest`: caching
it for the life of the digest would mean `apt install tesseract-ocr-deu` had no effect until the
next release, because installing a language pack changes neither `shutil.which("tesseract")` nor
any other digest input. `ok` and `degraded` get no TTL at all -- nothing short of an environment
change can make a working driver stop working, and an environment change moves the digest.

Not in `omniweave_core.limits`: that module carries ceilings whose breach is a `ResourceLimit`, and
a cache lifetime is neither a ceiling nor breachable. Not in `omniweave_core.config` either --
section 4.7 and glossary.md both spell it `probe_ttl_s` and call it a **constant**, where
`drivers.probe_timeout_ms` is a config key (18-api-sketch.md section 4) and is passed into
`cached_probe()` rather than re-declared here.
"""

PROBE_EPOCH_ENV: Final[str] = "OMNIWEAVE_PROBE_EPOCH"
"""The escape hatch for a condition the digest cannot see (E5, 04 section 4.7).

Bumping it moves every `env_digest` on the machine and so invalidates every cached verdict without
deleting a file. `ow doctor --refresh-probes` is the other lever and deletes the tree
(15-observability.md section 9.2); this one is the lever available to a user who cannot run it.

It is an `OMNIWEAVE_*` name that is **not** a config-key twin, like `OMNIWEAVE_HOME`,
`OMNIWEAVE_ENFORCE`, `OMNIWEAVE_HOOK_TTL` and `OMNIWEAVE_API_KEY`. It is not yet a member of
`omniweave_core.config.NON_KEY_ENV_VARS`, which is reported as a gap rather than fixed here --
`config.py` is another cluster's file.
"""

PROBE_CACHE_DIRNAME: Final[str] = "probe"
"""`$OMNIWEAVE_HOME/probe/` -- the tree `ow doctor --refresh-probes` deletes.

Its name is fixed by 15-observability.md section 9.2, which prints the path the flag removes, and by
section 4.7's cache path.
"""

PROBE_ROW_SCHEMA: Final[int] = 1
"""The version of the on-disk verdict row, carried in the row itself.

A row whose `schema` is not this one is a **miss**, never an error: the cache is an optimisation and
a format change must cost one probe, not a failed run. `card_schema` cannot serve here -- it
versions the card grammar, and this row's shape is `ProbeVerdict`'s.
"""

CACHED_FOR_LIFE_OF_DIGEST: Final[frozenset[ProbeStatus]] = frozenset(
    {ProbeStatus.OK, ProbeStatus.DEGRADED}
)
"""The two verdicts row 1 of section 4.7's table caches without a TTL.

Written as a set rather than as `status != UNAVAILABLE` so that a fourth `ProbeStatus` member --
were one ever added -- would default to the TTL'd branch rather than silently inherit "cached
forever", which is the failure direction that serves a stale `ok`.
"""


# --------------------------------------------------------------------------------------------
# 2. `env_digest` -- the recipe 04 section 4.7 prints, transcribed.
# --------------------------------------------------------------------------------------------


def _ident(path: str | None) -> tuple[str, int, int] | None:
    """`(realpath, st_size, st_mtime_ns)` for `path`, or `None` when there is nothing there.

    **The digest covers identities, not presences**, and this function is why. A bare
    `shutil.which()` path and a `find_library("cuda") is not None` boolean both survive the upgrade
    they exist to catch: a CUDA 12.4 -> 12.6 bump moves neither, and a cached `ok` outlives it.
    `os.path.realpath` resolves `libcuda.so.1` to `libcuda.so.<driver version>`, so on Linux the
    driver version enters the digest as a **name**; `(st_size, st_mtime_ns)` catches the platforms
    where the name does not move (`nvcuda.dll`) and catches an in-place `apt upgrade tesseract-ocr`
    on every platform.

    Cost is one `stat` per declared binary plus one. Section 4.4 step 2 prices `os.scandir` +
    `stat` over 328 distributions at 1.01 ms, so a per-card handful is under 50 microseconds.

    An unstattable path degrades to `None`, which is the same value an absent one produces and is
    the honest answer: a binary deleted between the `which()` and the `stat()` is not present. The
    plan's printed `_ident` carries no guard; catching `OSError` here is a departure recorded in
    this docstring, and it is narrow -- `OSError` only, never a bare `except`, because a bare
    `except` around a digest is banned (02-architecture.md section 3.3's semgrep row).
    """
    if path is None:
        return None
    try:
        # `os.path.realpath` and `os.stat` are 4.7's printed recipe, kept verbatim: this is a
        # digest, and a substituted call is a substituted digest.
        resolved = os.path.realpath(path)
        stat = os.stat(resolved)  # noqa: PTH116 -- see above; the recipe names this call
    except OSError:
        return None
    return (resolved, stat.st_size, stat.st_mtime_ns)


def _epoch(environ: Mapping[str, str]) -> int:
    """`int(environ.get("OMNIWEAVE_PROBE_EPOCH", "0"))`, with the malformed case named.

    A typo'd escape hatch that silently reads as `0` is worse than a refusal: the operator believes
    they invalidated every verdict on the machine and they did not, which is the exact failure the
    hatch exists to prevent. `ConfigError`'s class-default symbol is used because the plan binds no
    `codes.toml` row to this condition -- the same choice `errors.register_path()` makes for an
    unreadable `codes.toml`.
    """
    raw = environ.get(PROBE_EPOCH_ENV, "0")
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(
            f"{PROBE_EPOCH_ENV}={raw!r} is not an integer, so no probe verdict can be keyed",
            fix=f"unset {PROBE_EPOCH_ENV}, or set it to an integer",
        ) from exc


def env_digest(
    needs_binaries: Iterable[str],
    *,
    environ: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    find_library: Callable[[str], str | None] = ctypes.util.find_library,
) -> str:
    """The environment half of a cached verdict's key: 64 lowercase hex.

    04-driver-system.md section 4.7 prints the recipe as executable Python and this is that recipe,
    over `canonical()` -- section 2.8's one canonicaliser, with no second spelling::

        env_digest = sha256(canonical({
            "platform": sys.platform,
            "machine":  platform.machine(),
            "python":   f"{sys.version_info.major}.{sys.version_info.minor}",
            "which":    {n: _ident(shutil.which(n)) for n in sorted(card.hardware.needs_binaries)},
            "cuda":     _ident(ctypes.util.find_library("cuda")),
            "epoch":    int(os.environ.get("OMNIWEAVE_PROBE_EPOCH", "0")),
        })).hexdigest()

    **`libcuda` is never loaded and no framework is imported.** `ProbeEnv.gpu_present`'s "NOT torch"
    constraint holds unchanged, and calling `cuDriverGetVersion` through `ctypes` was rejected
    because it `dlopen`s a vendor driver library in the host process and a segfault on load is not
    catchable.

    `needs_binaries` rather than a `DriverCard` keeps this module off the card grammar's import
    path; the caller passes `card.hardware.needs_binaries`, and `key_for()` does exactly that.
    `sorted()` is load-bearing: the caller's order must not reach the digest. `environ`, `which` and
    `find_library` are injected because reading `os.environ` in library code is semgrep-banned (G8)
    and because a digest whose inputs cannot be substituted cannot be tested for movement.

    Raises `ConfigError` when `OMNIWEAVE_PROBE_EPOCH` is set to a non-integer.
    """
    return sha256_canonical(
        {
            "platform": sys.platform,
            "machine": platform.machine(),
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "which": {name: _ident(which(name)) for name in sorted(set(needs_binaries))},
            "cuda": _ident(find_library("cuda")),
            "epoch": _epoch(environ),
        }
    )


def probe_env(
    needs_binaries: Iterable[str],
    *,
    offline: bool,
    which: Callable[[str], str | None] = shutil.which,
    find_library: Callable[[str], str | None] = ctypes.util.find_library,
) -> ProbeEnv:
    """Build the `ProbeEnv` the worker hands to a driver's `probe()`.

    `ProbeEnv.which` carries **bare paths** where `env_digest()` carries identities, and the
    asymmetry is deliberate: the driver is given a path so it can run the binary, and the cache is
    keyed on an identity so an in-place upgrade of that binary moves the key. Handing the driver a
    `(realpath, size, mtime_ns)` triple would be handing it a cache key it has no use for.

    `gpu_present` is `find_library("cuda") is not None` and **never** an import of torch
    (`ProbeEnv`'s own docstring, 04 section 1.3). `vram_gb` is `0.0` -- "unknown" -- for the same
    reason: the only ways to read it are loading the vendor driver library or importing a framework,
    and both are refused. A driver needing a VRAM number reads it inside its own worker, where
    importing its own dependencies is what the worker is for.

    No writable path, no network handle and no config: those are the three things `ProbeEnv` is
    defined as not carrying.
    """
    return ProbeEnv(
        platform=sys.platform,
        machine=platform.machine(),
        python=(sys.version_info.major, sys.version_info.minor),
        which={name: which(name) for name in sorted(set(needs_binaries))},
        gpu_present=find_library("cuda") is not None,
        vram_gb=0.0,
        offline=offline,
    )


# --------------------------------------------------------------------------------------------
# 3. The key, and the path it names.
# --------------------------------------------------------------------------------------------

_CARD_SHA256_RE: Final = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
"""`card_sha256`'s exact form -- `drivers.card.card_sha256()` returns `"sha256:" + hexdigest`."""

_ENV_DIGEST_RE: Final = re.compile(r"\A[0-9a-f]{64}\Z")
"""`env_digest`'s exact form: a bare 64-hex `sha256_canonical()` result, no algorithm prefix."""

_SEGMENT_RE: Final = re.compile(r"\A[A-Za-z0-9._+@-]{1,128}\Z")
"""What may become one component of a path under `$OMNIWEAVE_HOME/probe/`.

This is **not** the driver-id grammar -- `omniweave_core.drivers.card.DRIVER_ID_RE` owns that, and
restating it here would be INV-21's second home for one fact. It is the weaker property this module
needs and nothing else checks: `driver_id` and `driver_version` are card-supplied strings that
become directory names, so a `..`, a separator or a NUL would let a card write outside the cache
root. A key is refused at construction rather than sanitised, because a sanitised key silently
collides with the key it was sanitised into.
"""

_RESERVED_SEGMENTS: Final[frozenset[str]] = frozenset({".", ".."})

_ALGORITHM_PREFIX: Final[str] = "sha256:"


def _segment(value: str, field: str) -> str:
    """Refuse a key component that cannot be a directory name under the cache root."""
    if value in _RESERVED_SEGMENTS or _SEGMENT_RE.fullmatch(value) is None:
        raise ValueError(f"{field}={value!r} is not usable as a probe-cache path component")
    return value


@dataclass(frozen=True, slots=True)
class ProbeKey:
    """`(driver_id, driver_version, card_sha256, env_digest)` -- the whole of the cache key.

    **Four components, and `card_sha256` is the one a reader asks about.** It is in the key for the
    reason section 4.4's wholesale validity key has a blind spot -- the developer's own workflow: a
    card edited in place under an unchanged `[driver] version` moves `[hardware] needs_binaries`,
    `[config]` and every other probe-relevant declaration while every other component of the key
    holds still. Without it, the edit is invisible and the stale verdict is served.

    `driver_version` is `[driver] version`, the semver for humans and `omniweave.lock`. It is not
    `schema_version`: `schema_version` is the only driver version that enters an *output* cache key
    (section 5.1), and a probe verdict is a fact about the environment rather than about output.

    Specified in 04-driver-system.md section 4.7 and glossary.md (`env_digest`).
    """

    driver_id: str
    driver_version: str
    card_sha256: str
    env_digest: str

    def __post_init__(self) -> None:
        """Refuse a key that cannot be written, at construction rather than at write time.

        A key is built once and used three times (read, probe, write); validating at the write
        would let a read silently miss on a malformed key and re-probe forever, which presents as a
        slow run and never as an error.
        """
        _segment(self.driver_id, "driver_id")
        _segment(self.driver_version, "driver_version")
        if _CARD_SHA256_RE.fullmatch(self.card_sha256) is None:
            raise ValueError(f"card_sha256={self.card_sha256!r} is not 'sha256:<64 lowercase hex>'")
        if _ENV_DIGEST_RE.fullmatch(self.env_digest) is None:
            raise ValueError(f"env_digest={self.env_digest!r} is not 64 lowercase hex")

    @property
    def card_segment(self) -> str:
        """`card_sha256` with the `sha256:` prefix stripped, for use as a directory name.

        **A departure from the printed path, forced by the filesystem.** Section 4.7 writes
        `.../<card_sha256>/<env_digest>.json`, and `card_sha256` carries a `:`. A colon is not a
        legal NTFS path component -- on Windows a path segment `sha256:ab...` addresses an alternate
        data stream on the parent directory rather than naming a file -- so the literal path is
        unwritable on a third of the nine-cell CI matrix. The algorithm prefix is dropped rather
        than substituted because it carries no information here: `card_sha256` is sha256 by
        construction, `ProbeKey.__post_init__` refuses anything else, and the full prefixed form is
        still stored inside the row, so nothing is lost and no second spelling is invented.
        """
        return self.card_sha256.removeprefix(_ALGORITHM_PREFIX)

    def relative_path(self) -> Path:
        """`<driver_id>/<version>/<card digest>/<env_digest>.json` -- **one file per key**.

        One file per key, rather than one file per driver holding many keys, is what makes the write
        atomic without a lock: a whole-file replace of a single row cannot tear a sibling row, and
        two processes probing two drivers never touch the same path.
        """
        return (
            Path(self.driver_id)
            / self.driver_version
            / self.card_segment
            / f"{self.env_digest}.json"
        )


def key_for(
    card: DriverCard,
    *,
    environ: Mapping[str, str],
    which: Callable[[str], str | None] = shutil.which,
    find_library: Callable[[str], str | None] = ctypes.util.find_library,
) -> ProbeKey:
    """The `ProbeKey` for `card` in this environment: the one place the four are assembled.

    A convenience over `env_digest()`, and the only function here that names a `DriverCard` -- the
    annotation resolves under `TYPE_CHECKING`, so importing this module still costs no card code.
    """
    return ProbeKey(
        driver_id=card.identity.id,
        driver_version=card.identity.version,
        card_sha256=card.card_sha256,
        env_digest=env_digest(
            card.hardware.needs_binaries,
            environ=environ,
            which=which,
            find_library=find_library,
        ),
    )


# --------------------------------------------------------------------------------------------
# 4. The TTL table, as a total function.
# --------------------------------------------------------------------------------------------


def is_fresh(status: ProbeStatus, *, recorded_at: float, now: float) -> bool:
    """Section 4.7's three-row TTL table, and there is no fourth row.

    Row 1, `ok` and `degraded`, cached for the life of the `env_digest`: nothing short of an
    environment change can make a working driver stop working, and an environment change moves the
    digest -- into the path, so a moved digest is a different file and never a stale row.

    Row 2, `unavailable`, cached for `PROBE_TTL_S` and then re-probed: this is the verdict a user
    *fixes*, and installing a language pack changes neither `shutil.which("tesseract")` nor any
    other digest input.

    Row 3, a probe timeout, cached for `PROBE_TTL_S`: recorded as an `unavailable` carrying
    `"probe timed out after <n> ms"`, because a hung probe is not evidence of a permanent condition.
    **Row three needs no branch here, and that is the design rather than an omission**:
    `timeout_verdict()` returns an `UNAVAILABLE`, so a timeout inherits row two's TTL by
    construction, and a separate branch would be a second place for one number to drift.

    `now` is a parameter because `time.time()` is banned in library code (G8's semgrep row) -- and
    because the row this function implements is untestable against a clock it reads itself.

    A row dated in the future is **stale**. A backwards clock step (an NTP correction, a VM restore,
    a dual boot) would otherwise pin an `unavailable` verdict alive for the length of the step, and
    re-probing early costs one worker spawn where serving early costs a wrong answer.
    """
    if status in CACHED_FOR_LIFE_OF_DIGEST:
        return True
    age = now - recorded_at
    return 0.0 <= age < PROBE_TTL_S


def timeout_verdict(timeout_ms: int) -> ProbeVerdict:
    """The verdict a probe that ran past `[drivers] probe_timeout_ms` is recorded as.

    `ProbeVerdict(status="unavailable", detail="probe timed out after 2000 ms")`, printed verbatim
    in section 4.7's TTL table. `missing` and `fix_hint` stay empty on purpose: a timeout knows
    nothing about what is absent, and inventing a `missing[]` entry here would put an unfalsifiable
    string into the one field DR21 makes machine-actionable.

    `timeout_ms` is passed in rather than defaulted: `drivers.probe_timeout_ms = 2000` is a config
    key whose home is `omniweave_core.config` (18-api-sketch.md section 4), and a default here would
    be a second declaration of it.
    """
    return ProbeVerdict(
        status=ProbeStatus.UNAVAILABLE,
        detail=f"probe timed out after {timeout_ms} ms",
    )


# --------------------------------------------------------------------------------------------
# 5. The cache.
# --------------------------------------------------------------------------------------------


def probe_cache_root(home: Path) -> Path:
    """`$OMNIWEAVE_HOME/probe` -- the tree, given the home.

    `home` is a parameter and not read from the environment here. `omniweave_core.config` already
    resolves `$OMNIWEAVE_HOME` (defaulting to `~/.omniweave`) for the user config file, and a
    second resolver would be INV-21's second home for one fact. That core exposes no public
    `omniweave_home()` yet is a real gap, reported rather than papered over.
    """
    return home / PROBE_CACHE_DIRNAME


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """What `cached_probe()` returns: the verdict, whether it was cached, and where it lives.

    `cached` is not decoration. 12-performance.md section 3.2 prices the cache at "thirteen drivers
    x `probe_timeout_ms = 2000` is a 26 s first query without it", and `ow doctor` is where a first
    run pays that -- so a caller that cannot tell a hit from a spawn cannot report the number the
    whole cache exists to move.
    """

    verdict: ProbeVerdict
    cached: bool
    path: Path


Prober: TypeAlias = Callable[[ProbeEnv], ProbeVerdict]
"""The execution seam. **The host process never runs a probe** (04 section 4.7).

Its contract, which `host/subproc.py` implements at P3 and which nothing in core implements today:

* it runs `probe()` in the same `subproc` worker that would run the driver, and discards the worker;
* it raises `TimeoutError` -- and only `TimeoutError` -- when the worker outlives
  `[drivers] probe_timeout_ms`. `subprocess.TimeoutExpired` is a `SubprocessError` and not a
  `TimeoutError`, so the adapter translates; this module may not import `subprocess` and must not
  learn that type's name;
* every other exception is a defect in the adapter and propagates. `cached_probe()` catches
  `TimeoutError` alone, because swallowing the rest would turn a broken host into a permanently
  `unavailable` driver with no diagnosis, and because a bare `except` around a probe is banned
  (02-architecture.md section 3.3's semgrep row).
"""


@dataclass(frozen=True, slots=True)
class ProbeCache:
    """One verdict per `(driver_id, driver_version, card_sha256, env_digest)`, under `root`.

    Persisted because a probe costs a ~200-800 ms worker spawn: "a probe is never run more than once
    per key per machine, so the spawn it costs is amortised across every run on that machine --
    which is the reason the cache exists at all" (section 4.7).

    **Every fault is a miss.** An unreadable, truncated, hand-edited, foreign-schema or
    wrong-key row returns `None` from `read()` and costs one probe. A cache that can fail a run
    is worse than no cache, and 11-repo-layout.md section 2.6 rule 2 states the general form: a
    corrupt file must degrade one operation, not brick the caller. The `except` clauses are
    named types, never bare.
    """

    root: Path

    def path_for(self, key: ProbeKey) -> Path:
        """`root/<driver_id>/<version>/<card digest>/<env_digest>.json`."""
        return self.root / key.relative_path()

    def read(self, key: ProbeKey, *, now: float) -> ProbeVerdict | None:
        """The cached verdict for `key`, or `None` for a miss, a stale row or an unreadable one.

        `None` is what `Catalog.probe_status` records as `"unknown"`, and `resolve()` treats
        `unknown` as **passing** the filter -- an unprobed driver is a candidate, not a refusal
        (section 4.7). So a miss here can only cost a preflight probe; it can never prune a driver.
        """
        try:
            row = json.loads(self.path_for(key).read_bytes())
        except (OSError, ValueError):  # ValueError covers JSONDecodeError and a bad UTF-8 decode
            return None
        try:
            recorded_at, verdict = _row_verdict(row, key)
        except (KeyError, TypeError, ValueError):
            return None
        return verdict if is_fresh(verdict.status, recorded_at=recorded_at, now=now) else None

    def write(self, key: ProbeKey, verdict: ProbeVerdict, *, now: float) -> Path:
        """Persist `verdict` for `key` and return the file it landed in.

        **Written by an atomic replace from a `.tmp` in the same directory** (section 4.7), so two
        concurrent processes cannot tear a row and the loser's write is simply overwritten by an
        equal value. Same directory because a replace is atomic only within a filesystem, and
        `$OMNIWEAVE_HOME` may sit on a different mount than the platform temp directory.

        The temporary carries the writer's pid. Section 4.7 says only "a `.tmp` in the same
        directory", and a single shared `.tmp` name is itself a tearable file: two processes would
        interleave their writes into it and then both replace a spliced row, which is precisely the
        failure the atomic replace exists to make impossible. `os.getpid()` and not a random suffix
        -- `random` is banned repo-wide (determinism is a gate, not a habit) and two live processes
        cannot share a pid.

        The bytes are `canonical()`'s, so two processes recording the same verdict at the same `now`
        write byte-identical files. `recorded_at` is the only field that can differ between two
        racing writers, and the replace is atomic, so whichever row survives is a whole row whose
        every consulted field is equal.
        """
        target = self.path_for(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f"{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(canonical(_verdict_row(key, verdict, now)))
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return target

    def clear(self) -> int:
        """Delete the whole tree and return how many verdict rows went with it.

        This is `ow doctor --refresh-probes` (15-observability.md section 9.2), and it is the blunt
        lever: `OMNIWEAVE_PROBE_EPOCH` is the other one, for a user who cannot delete the tree. The
        count is returned so `ow doctor` can say what it did rather than claim it silently.
        """
        if not self.root.is_dir():
            return 0
        removed = sum(1 for _ in self.root.rglob("*.json"))
        shutil.rmtree(self.root)
        return removed


def _key_row(key: ProbeKey) -> dict[str, str]:
    """The four components as they are stored inside a row. One serialiser, used by both sides."""
    return {
        "driver_id": key.driver_id,
        "driver_version": key.driver_version,
        "card_sha256": key.card_sha256,
        "env_digest": key.env_digest,
    }


def _verdict_row(key: ProbeKey, verdict: ProbeVerdict, now: float) -> dict[str, object]:
    """The on-disk row: the schema, the whole key, the timestamp and the verdict.

    **The key is stored inside the row as well as spelled by the path.** A tree copied between
    machines, a `$OMNIWEAVE_HOME` restored from a backup or a hand-edited directory name would
    otherwise let one key's verdict be served under another's; `read()` compares and calls the
    mismatch a miss. It costs a couple of hundred bytes per row and closes the one way this cache
    can be wrong rather than merely absent.
    """
    return {
        "schema": PROBE_ROW_SCHEMA,
        "key": _key_row(key),
        "recorded_at": float(now),
        "verdict": {
            "status": verdict.status.value,
            "detail": verdict.detail,
            "missing": list(verdict.missing),
            "fix_hint": verdict.fix_hint,
            "capabilities_lost": list(verdict.capabilities_lost),
        },
    }


def _row_verdict(row: object, key: ProbeKey) -> tuple[float, ProbeVerdict]:
    """`(recorded_at, verdict)` from a parsed row, or an exception `read()` turns into a miss.

    Every field is type-checked rather than trusted: the row is a file in a user-writable directory
    and `ProbeVerdict` is a frozen dataclass with no validation of its own, so a `missing` that
    arrived as a bare string would reach the router as one entry per character.
    """
    if not isinstance(row, dict) or row.get("schema") != PROBE_ROW_SCHEMA:
        raise ValueError("not a probe row of this schema")
    if row["key"] != _key_row(key):
        raise ValueError("row belongs to a different key")
    recorded_at = row["recorded_at"]
    if isinstance(recorded_at, bool) or not isinstance(recorded_at, (int, float)):
        raise TypeError("recorded_at is not a number")
    verdict = row["verdict"]
    if not isinstance(verdict, dict):
        raise TypeError("verdict is not a table")
    fix_hint = verdict["fix_hint"]
    return float(recorded_at), ProbeVerdict(
        status=ProbeStatus(verdict["status"]),
        detail=_text(verdict["detail"]),
        missing=_texts(verdict["missing"]),
        fix_hint=None if fix_hint is None else _text(fix_hint),
        capabilities_lost=_texts(verdict["capabilities_lost"]),
    )


def _text(value: object) -> str:
    """A string, or a `TypeError` that `read()` turns into a miss."""
    if not isinstance(value, str):
        raise TypeError(f"expected a string, found {type(value).__name__}")
    return value


def _texts(value: object) -> tuple[str, ...]:
    """A tuple of strings, or a `TypeError` that `read()` turns into a miss."""
    if not isinstance(value, list):
        raise TypeError(f"expected a list of strings, found {type(value).__name__}")
    return tuple(_text(item) for item in value)


# --------------------------------------------------------------------------------------------
# 6. The one orchestrator.
# --------------------------------------------------------------------------------------------


def cached_probe(
    *,
    key: ProbeKey,
    env: ProbeEnv,
    cache: ProbeCache,
    run_probe: Prober,
    clock: Callable[[], float],
    timeout_ms: int,
) -> ProbeOutcome:
    """Read the cache; on a miss run the injected prober once and persist what it said.

    This is preflight's inner step. Section 4.7's loop is outside it: after `resolve()` returns, the
    runtime probes every candidate whose status is `unknown`, and if any verdict comes back
    `unavailable` it re-resolves **once** against the refreshed catalog. The second pass has no
    `unknown` status for those ids, so there is no loop and the bound is two resolutions per
    requirement per run.

    `clock` is called **once**, and the same instant stamps the row that a hit was tested against.
    Recording the probe's start rather than its finish is conservative by at most `timeout_ms` out
    of `PROBE_TTL_S` -- 2 s in 600 -- and it is what makes a fixed clock a sufficient test double.

    Raises nothing on a missing capability: DR21 makes that a pruned plan with a report, and the
    report is the returned `ProbeVerdict`'s `missing` and `fix_hint`. `sys.exit` is banned in
    library code.
    """
    now = clock()
    hit = cache.read(key, now=now)
    if hit is not None:
        return ProbeOutcome(verdict=hit, cached=True, path=cache.path_for(key))
    try:
        verdict = run_probe(env)
    except TimeoutError:
        verdict = timeout_verdict(timeout_ms)
    return ProbeOutcome(
        verdict=verdict,
        cached=False,
        path=cache.write(key, verdict, now=now),
    )
