"""A signal provider's computer, run in a child process: both halves of that one conversation.

05-ingest-and-routing.md registers a provider as *"an `omniweave.signals` entry point plus a
`signals.toml`"* (05:2044) and 02:882 says a signal is *"computed in the host"*. Neither says how a
provider's code is reached, and D579 recorded the consequence: `decode.pdf-text-layer` defers on
`decode.char_count`, nothing computes it, and no PDF has ever been routed. This module is the
contract that was missing (D628).

```text
python -m omniweave_core.host.signals
  stdin    {"package", "source", "content_sha256", "keys"}      one request, then EOF
  guard    install_egress_guard(armed=True)                     before any provider code runs
  bytes    read `source`; sha256 must equal `content_sha256`    else every key is unavailable
  import   <package>.signals                                    the fixed module beside signals.toml
  compute  compute(raw, keys) -> {key: scalar}                  keys it does not compute are absent
  stdout   {"values": {...}, "unavailable": {key: reason},      every asked key in exactly one;
            "refused": reason | null}                            non-null when the request failed
```

## Why a child, when 02:882 says "in the host"

**`host` is this package, not the supervisor's address space.** The one provider that computes
anything today is `pdfium`, and 14-security.md:466-469 is unambiguous about the library it calls:
*"pdfium is ... the largest memory-unsafe surface in the shipped set"*, and *"`subproc` is the floor
for the PDF path"*. A routing signal is read from exactly the bytes the driver is isolated from, and
before the driver ever runs. Computed in the supervisor, a hostile PDF would crash the run at
routing, and the unit -- still `identified` -- would crash the next run at the same place. In a
child, a crash, a hang or a refusal costs that one unit its signals and nothing else: the rule that
deferred on them degrades to `skip` (05:1130) and the report says why.

**One child per request, and the reason is containment rather than simplicity.** A long-lived child
would serve every unit of a routing pass from one address space, so one hostile document could
leave the next one's answer wrong without crashing anything. A request is one unit and one
`CostClass` group, which is what 05:1090's loop asks for at a time; the price is interpreter start
per request (measured in D628), and `route_signal` is the cache 05 section 5.4 prices against that.
The router reads it before asking and writes back what a computer answered, never a refusal
(`SignalAnswer.refusal`, D632).

## What the child does not have

- **No memory cap.** `subproc.JobObject` and `setrlimit` bound an S4 worker to its card's
  `memory_mb`, and a provider has no card. `run_captured` has no pid to assign before the child
  runs, so the cap is not applied here (D628, not built).
- **No store handle**, as for a worker (INV-6): the answer crosses stdout and the router writes it.
- **No network.** The egress guard is armed unconditionally: no shipped provider declares a network
  need, and a provider has no card to declare one on.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.discovery import PACKAGE_PATH_RE
from omniweave_core.host import subproc

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from omniweave_ports.types import Scalar

__all__ = [
    "COMPUTER_MODULE",
    "SIGNALS_MODULE",
    "TIMEOUT_S",
    "SignalAnswer",
    "answer",
    "compute_in_child",
    "main",
]

SIGNALS_MODULE: Final[str] = "omniweave_core.host.signals"
"""What `python -I -m` runs. The child's argv is the interpreter, `-I`, `-m` and this.

`-I` because `-m` alone puts the working directory first on `sys.path`: a `struct.py` in the
directory a child is started from shadows the standard library before any of this module runs,
which is how the first measurement of this child failed, from a `%TEMP%` holding one (D628). A
child reading untrusted bytes does not get to import whatever sits beside it; isolated mode also
drops `PYTHON*` variables and the user site, which the named environment does not carry anyway."""

COMPUTER_MODULE: Final[str] = "signals"
"""The fixed module inside a provider's package: `omniweave_pdf.signals`, beside `signals.toml`.

`omniweave.route.evidence.SIGNALS_FILENAME`'s rule applied to code: the entry-point VALUE names a
package, and what the framework reads from it is at a fixed name inside it. A provider whose
package has no `signals.py` computes nothing, and the router knows that from the file's absence
without importing anything (`evidence.installed_specs`)."""

TIMEOUT_S: Final[float] = 120.0
"""One request's wall ceiling. 14:480's rule for a parser is that *"a crash is allowed and a hang is
not"*, and this is the hang half. `decode.char_count` walks every page, and on
`fixtures/gen/gen_5000p_pdf.py`'s output that is seconds, not the 1.1 ms 05:2146 estimates for a
part; the ceiling is set well above the measured walk (D628)."""

REASON_MAX_CHARS: Final[int] = 512
"""An unavailable reason's ceiling. It lands in a `Degradation` and on the route report, and a
provider's `str(exc)` is its own text of any length."""

_STDERR_TAIL: Final[int] = 400


# =============================================================================================
# 1. The answer, which both halves share
# =============================================================================================


@dataclass(frozen=True, slots=True)
class SignalAnswer:
    """Every asked key, in exactly one of the two mappings. The router `put`s each as it stands.

    `refusal` is the reason when the REQUEST failed -- the child timed out, crashed, found the
    bytes changed, or the provider raised -- and `None` when the computer ran and answered each
    key. Only the second is a pure function of the content, the key and the provider's version,
    so only the second is what `route_signal` may keep (05 section 5.4, D632). A refusal is
    re-attempted by the next run, as it was before the cache existed.
    """

    values: Mapping[str, Scalar]
    unavailable: Mapping[str, str]
    refusal: str | None = None

    @classmethod
    def refused(cls, keys: Sequence[str], reason: str) -> SignalAnswer:
        """Every key unavailable, for one reason: the request never reached a value."""
        why = _bounded(reason)
        return cls(values={}, unavailable=dict.fromkeys(keys, why), refusal=why)

    def total(self, keys: Sequence[str], *, missing: str) -> SignalAnswer:
        """Only the asked keys, and each of them: a key nobody answered gets `missing`."""
        values = {key: self.values[key] for key in keys if key in self.values}
        unavailable = {key: self.unavailable.get(key, missing) for key in keys if key not in values}
        return SignalAnswer(values=values, unavailable=unavailable, refusal=self.refusal)


def _bounded(text: str) -> str:
    return text if len(text) <= REASON_MAX_CHARS else text[: REASON_MAX_CHARS - 3] + "..."


def _scalar(value: object) -> bool:
    """A value a rule can compare and JSON can carry: 05:1856's *"flat, namespaced, scalar-valued"*.

    `None` is not one: UNKNOWN is carried by leaving the key out, never as a value. A non-finite
    float is refused because `canonical()` refuses it in the read set it would land in.
    """
    if isinstance(value, bool | int | str):
        return True
    return isinstance(value, float) and math.isfinite(value)


# =============================================================================================
# 2. The child's half
# =============================================================================================


def answer(request: Mapping[str, Any]) -> SignalAnswer:
    """One request, computed. Runs in the child, after the egress guard; never raises.

    Every refusal is a reason on every asked key rather than an exception, because the parent reads
    one JSON object and an exception here would reach it as a traceback on stderr and exit 1 --
    which it reports too, but naming the process rather than the cause.
    """
    keys = [str(key) for key in request.get("keys", [])]
    package = str(request.get("package", ""))
    if not PACKAGE_PATH_RE.match(package):
        return SignalAnswer.refused(keys, f"{package!r} is not a dotted package path")
    try:
        raw = Path(str(request.get("source", ""))).read_bytes()
    except OSError as gone:
        return SignalAnswer.refused(keys, f"the source is unreadable: {gone}")
    if hashlib.sha256(raw).hexdigest() != str(request.get("content_sha256", "")):
        return SignalAnswer.refused(
            keys,
            "the source's bytes no longer hash to the digest it was identified under; the next "
            "ow ingest re-acquires it",
        )
    try:
        module = importlib.import_module(f"{package}.{COMPUTER_MODULE}")
        computed = module.compute(raw, tuple(keys))
    except Exception as exc:  # a provider's failure is its keys' reason, never the child's
        return SignalAnswer.refused(
            keys, f"{package}.{COMPUTER_MODULE}: {type(exc).__name__}: {exc}"
        )
    values: dict[str, Scalar] = {}
    unavailable: dict[str, str] = {}
    for key in keys:
        if key not in computed:
            unavailable[key] = f"{package}.{COMPUTER_MODULE} does not compute {key}"
        elif not _scalar(computed[key]):
            unavailable[key] = _bounded(
                f"{package}.{COMPUTER_MODULE} returned {type(computed[key]).__name__} for {key}, "
                "which is not a finite scalar"
            )
        else:
            values[key] = computed[key]
    return SignalAnswer(values=values, unavailable=unavailable)


def main() -> int:
    """`python -m omniweave_core.host.signals`: one request on stdin, one answer on stdout."""
    from omniweave_core.host.worker import install_egress_guard  # noqa: PLC0415 -- the child only

    install_egress_guard(armed=True)
    try:
        request = json.loads(sys.stdin.buffer.read() or b"{}")
    except ValueError as bad:
        sys.stderr.write(f"the request is not JSON: {bad}\n")
        return 2
    if not isinstance(request, dict):
        sys.stderr.write("the request is not a JSON object\n")
        return 2
    found = answer(request)
    sys.stdout.write(
        json.dumps(
            {
                "values": dict(found.values),
                "unavailable": dict(found.unavailable),
                "refused": found.refusal,
            },
            allow_nan=False,
            separators=(",", ":"),
        )
    )
    sys.stdout.flush()
    return 0


# =============================================================================================
# 3. The parent's half
# =============================================================================================


def compute_in_child(
    package: str,
    *,
    source: str,
    content_sha256: str,
    keys: Sequence[str],
    executable: str,
    cwd: str,
    env: Mapping[str, str],
    timeout_s: float = TIMEOUT_S,
) -> SignalAnswer:
    """Ask one provider for `keys` of one unit, in a child. Never raises; every key is answered.

    The child is `run_captured`'s -- the framework's one synchronous run-and-capture, and one of
    the two files `TID251` lets import `subprocess` -- with the environment named by the caller,
    never inherited (`SpawnRequest`'s rule), and a working directory the caller chose.
    """
    request = json.dumps(
        {"package": package, "source": source, "content_sha256": content_sha256, "keys": list(keys)}
    ).encode("utf-8")
    done = subproc.run_captured(
        (executable, "-I", "-m", SIGNALS_MODULE),
        stdin=request,
        cwd=cwd,
        env=env,
        timeout_s=timeout_s,
    )
    missing = f"the {package} provider's child did not answer for this key"
    if done.failed == "TimeoutExpired":
        return SignalAnswer.refused(
            keys, f"the {package} provider did not answer in {timeout_s:g} s"
        )
    if done.failed:
        return SignalAnswer.refused(
            keys, f"the {package} provider's child did not start: {done.failed}"
        )
    if done.returncode != 0:
        tail = done.stderr.decode("utf-8", "replace").strip()[-_STDERR_TAIL:]
        return SignalAnswer.refused(
            keys, f"the {package} provider's child exited {done.returncode}: {tail}"
        )
    try:
        body = json.loads(done.stdout)
        values = {str(k): v for k, v in dict(body["values"]).items() if _scalar(v)}
        unavailable = {str(k): _bounded(str(v)) for k, v in dict(body["unavailable"]).items()}
        refusal = body.get("refused")
    except (ValueError, KeyError, TypeError, AttributeError) as bad:
        return SignalAnswer.refused(keys, f"the {package} provider answered no answer: {bad}")
    if refusal is not None:
        return SignalAnswer.refused(keys, str(refusal))
    return SignalAnswer(values=values, unavailable=unavailable).total(keys, missing=missing)
