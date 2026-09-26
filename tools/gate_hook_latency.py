"""G26 - `ow hook prompt` p95 <= 250 ms warm / 1 s cold, split the way 11 section 6.4 splits it.

`tools/gates.toml`'s G26 row names this script as its planned runner, and 16-roadmap.md:742 runs
it as a P7 exit criterion. 10:1844 gives the reason the gate exists: *"a silent exit-0 deadline
breach turns the adoption lever off with no symptom"* -- every failure of a hook is exit 0 and
nothing the user sees, so a hook that got slow is a hook that stopped working and said nothing.

## Three assertions, and which ones may fail CI where

11-repo-layout.md:1646-1652 makes G10 and G26 split timing gates, and this is G10's split for G26:

1. **The warm budget is absolute.** p95 over the warm runs <= the warm budget. Both budgets are
   READ from G26's `assertion` in `tools/gates.toml`, the register that is *"THE authority"* on
   gates, and the warm one is cross-checked against the D1 row `gate_coldstart.py` transcribes, so
   the two copies cannot drift apart unnoticed. The cold budget is read and REPORTED, and fails
   nothing -- see "What cold is here" (D607).
2. **The module count is the hard regression check.** It is what 11:1647-1649 calls *"the module
   count on the hook path"*: a deterministic number that does not vary with runner load and is
   what actually regresses, one new eager import at a time. More modules than the baseline fails,
   naming them.
3. **The wall clock is a 25% band against this OS's baseline** (11:1650). It answers "did this
   change make it slower here", never "is it fast enough", which is (1)'s job.

A machine with no recorded baseline passes (2) and (3) as UNMEASURED and says so. It is never
silently green: the report prints which rows ran.

## The witness, because D432 is the easiest way for this gate to lie

An event word the hook does not know is an exit 0 and a counter (`hooks.main`'s ruling under
10:1843-1844's *"every failure path is a silent exit 0"*, D605), which is the cheapest path in
the program. A gate timing `ow hook prompt` against a
build that no longer routed `prompt` would time the no-op and pass. So before any timing, a child
calls `omniweave.hooks.main.main()` for `prompt` and for a word no build knows, and the prompt's
counters must be the UserPromptSubmit handler's (`ow-hook-ups-*`) while the control's are the
unknown event's. The handlers are imported eagerly, so the module trace cannot tell the two
paths apart; the counters can.

**What it times today is the handler's whole wired path, and that path is short.** The three
store-backed seams are `None` (`hooks.main.unwired()`), so the prompt handler parses the payload,
finds a cite-shaped prompt and returns `noop-no-corpus` at the probe. D432 records the consequence:
the timing grows by the store-open cost on the day the probes land, which is the day G26 starts to
matter. The witness's counter will move then too, and the report prints it so a reader can see
which path was timed.

## What "cold" is here

A hook is a fresh process on every event, and the cold budget is the first invocation after the
host starts. That is an OS file-cache state this script cannot produce. What it produces is
stricter: each cold run gets an empty `PYTHONPYCACHEPREFIX`, so every module is compiled from
source. An upper bound on the real cold case, not a measurement of it. A pass here implies the
real case passes; a breach here does not imply the real case breaches.

**So the cold figure fails nothing (D607).** On this machine it measured 486 ms and then 1,310 ms an
hour apart on the same code -- compiling every module from source, with the virus scanner looking
at a fresh cache directory each time, varies with the machine and not with the change. A gate that
failed on it would fail for a state no real install is in. It is printed with `OVER BUDGET` when it
exceeds the budget, which is information a reviewer can act on and a verdict it cannot support.

**The self-deadline is reported beside the cold budget, because D394 is real on this machine.** The
handler's self-deadline is 400 ms (`hooks.envelope.SELF_DEADLINE_MS`) and G26's cold budget is
1,000 ms, so a cold run between the two is one the gate calls healthy while the hook answers with
silence. The count of cold runs over the self-deadline is printed on every run and fails nothing.

Run it:

    uv run tools/gate_hook_latency.py                    # check: budgets, module count, band
    uv run tools/gate_hook_latency.py --record-baseline  # measure and write this OS's baseline
    uv run tools/gate_hook_latency.py --json             # the report, machine-readable

Exit codes: `0` pass (an absent baseline is a pass that says so), `1` a budget breach, a
module-count regression, a band regression or a witness failure, `2` a usage error from argparse.

Specified in 10-interfaces.md section 8.1 (:1842-1846), 11-repo-layout.md section 6.4
(:1646-1652), 02-architecture.md section 2 row 34, and 16-roadmap.md:742.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import subprocess  # noqa: TID251 - G26's subject is a fresh hook process; a spawn is the witness.
import sys
import tempfile
import time
import tomllib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "BAND_PCT",
    "BASELINE_SCHEMA",
    "COLD_RUNS",
    "WARMUP_RUNS",
    "WARM_RUNS",
    "Baseline",
    "Budgets",
    "Report",
    "baseline_path",
    "budgets",
    "judge",
    "main",
    "modules_of",
    "p95",
]

REPO_ROOT = Path(__file__).resolve().parents[1]
GATES_TOML = REPO_ROOT / "tools" / "gates.toml"
COLDSTART = REPO_ROOT / "tools" / "gate_coldstart.py"
BASELINES = REPO_ROOT / "eval" / "baselines"
PAYLOAD = (
    REPO_ROOT / "packages" / "omniweave" / "src" / "omniweave" / "hooks" / "fixtures"
    / "user-prompt-submit.json"
)  # fmt: skip
"""The probe payload `ow hooks check` already sends: a cite-shaped prompt, which is the shape that
reaches the probe rather than stopping at the shape check."""

BASELINE_SCHEMA = 1
WARMUP_RUNS = 2
WARM_RUNS = 30
COLD_RUNS = 10
BAND_PCT = 25.0
"""11:1650's *"25% band"*. OQ-4 records it as inherited rather than measured, and so does this."""

CONTROL_WORD = "g26-control-no-such-event"
UPS_PREFIX = "ow-hook-ups-"
UNKNOWN_PREFIX = "ow-hook-unknown-"
PROJECT_TOML = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
"""A project with a corpus declared, as a real one has, so the handler is not stopped by config."""

_ASSERTION_RE = re.compile(r"p95\s*<=\s*(\d+)\s*ms\s+warm\s*/\s*(\d+(?:\.\d+)?)\s*s\s+cold")


# ---------------------------------------------------------------------------
# The budgets, read from their homes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Budgets:
    warm_ms: float
    cold_ms: float
    self_deadline_ms: float


def budgets() -> Budgets:
    """Warm and cold from G26's assertion, cross-checked against the D1 row; the self-deadline
    from the hook envelope. Three homes read, none restated."""
    rows = tomllib.loads(GATES_TOML.read_text(encoding="utf-8"))["gate"]
    (row,) = (one for one in rows if one["id"] == "G26")
    found = _ASSERTION_RE.search(row["assertion"])
    if found is None:
        msg = f"G26's assertion no longer reads 'p95 <= N ms warm / N s cold': {row['assertion']!r}"
        raise SystemExit(msg)
    warm, cold = float(found.group(1)), float(found.group(2)) * 1000
    d1 = _coldstart_warm_row()
    if d1 is not None and d1 != warm:
        msg = f"G26 says {warm} ms warm and gate_coldstart.py's D1 row says {d1} ms"
        raise SystemExit(msg)
    from omniweave.hooks.envelope import SELF_DEADLINE_MS  # noqa: PLC0415

    return Budgets(warm_ms=warm, cold_ms=cold, self_deadline_ms=float(SELF_DEADLINE_MS))


def _coldstart_warm_row() -> float | None:
    spec = importlib.util.spec_from_file_location("gate_coldstart_for_g26", COLDSTART)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    rows = [one for one in module.COLD_START_CEILINGS if one.subject == "ow hook prompt, warm"]
    return rows[0].ceiling_ms if rows else None


# ---------------------------------------------------------------------------
# The subject, the witness, the trace
# ---------------------------------------------------------------------------


def _env(root: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["OMNIWEAVE_HOME"] = str(root / "owhome")
    env.update(extra or {})
    return env


def _spawn(root: Path, argv: list[str], extra: dict[str, str] | None = None) -> tuple[float, bytes]:
    started = time.perf_counter_ns()
    done = subprocess.run(  # noqa: S603 -- fixed argv, argv[0] is sys.executable, no shell
        argv,
        input=PAYLOAD.read_bytes(),
        cwd=root,
        env=_env(root, extra),
        capture_output=True,
        check=False,
        timeout=60,
    )
    return (time.perf_counter_ns() - started) / 1e6, done.stderr


HOOK = [sys.executable, "-m", "omniweave", "hook", "prompt"]

_WITNESS = """
import io, json, os, sys
from pathlib import Path
from omniweave.hooks.main import main
from omniweave_core.clock import SystemClock
payload = sys.stdin.buffer.read()
out = {}
for word in ("prompt", sys.argv[1]):
    got = main([word], stdin=io.BytesIO(payload), stdout=io.BytesIO(), env=dict(os.environ),
               clock=SystemClock(), cwd=Path.cwd(), tty=False, pid=os.getpid(), argv0="ow")
    out[word] = list(got.counters)
print(json.dumps(out))
"""


def witness(root: Path) -> tuple[bool, dict[str, list[str]]]:
    """The prompt reaches the UserPromptSubmit handler and the control word does not (D432)."""
    done = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _WITNESS, CONTROL_WORD],
        input=PAYLOAD.read_bytes(),
        cwd=root,
        env=_env(root),
        capture_output=True,
        check=False,
        timeout=60,
    )
    try:
        counters: dict[str, list[str]] = json.loads(done.stdout.decode("utf-8").strip() or "{}")
    except ValueError:
        return False, {}
    return discriminates(counters), counters


def discriminates(counters: dict[str, list[str]]) -> bool:
    """The witness's rule, pure: `prompt` counted by the UserPromptSubmit handler and the control
    word counted as an unknown event. Both halves, because a witness that checked only the first
    could not tell a handler from a build that answered every word the same way."""
    prompt, control = counters.get("prompt", []), counters.get(CONTROL_WORD, [])
    return (
        bool(prompt)
        and all(one.startswith(UPS_PREFIX) for one in prompt)
        and bool(control)
        and all(one.startswith(UNKNOWN_PREFIX) for one in control)
    )


def modules_of(trace: str) -> frozenset[str]:
    """Module names from `-X importtime` stderr: the last `|` column of each `import time:` row."""
    return frozenset(
        line.rsplit("|", 1)[1].strip()
        for line in trace.splitlines()
        if line.startswith("import time:") and "|" in line and "cumulative" not in line
    )


def hook_modules(root: Path) -> tuple[str, ...]:
    """The modules the hook path adds over a bare interpreter, sorted. `gate_importtime`'s
    difference method: a virtualenv injects site modules that cancel out."""
    _, traced = _spawn(root, [sys.executable, "-X", "importtime", *HOOK[1:]])
    bare = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "pass"],
        capture_output=True,
        check=False,
        cwd=root,
        env=_env(root),
        timeout=60,
    )
    added = modules_of(traced.decode("utf-8", "replace")) - modules_of(
        bare.stderr.decode("utf-8", "replace")
    )
    return tuple(sorted(added))


def p95(values: list[float]) -> float:
    """Nearest-rank p95: the smallest value with at least 95% of the runs at or under it."""
    ordered = sorted(values)
    rank = max(1, -(-95 * len(ordered) // 100))
    return ordered[rank - 1]


# ---------------------------------------------------------------------------
# The baseline, and the verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Baseline:
    baseline_schema: int
    os: str
    python: str
    machine: str
    module_count: int
    modules: tuple[str, ...]
    warm_p95_ms: float
    cold_p95_ms: float
    recorded_at: str
    runner: str


def baseline_path() -> Path:
    """`eval/baselines/hook-latency-<os>-<py>.json`, `coldstart-<os>-<py>.json`'s shape."""
    major, minor = sys.version_info[:2]
    return BASELINES / f"hook-latency-{platform.system().lower()}-{major}.{minor}.json"


def _load_baseline() -> Baseline | None:
    path = baseline_path()
    if not path.is_file():
        return None
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    raw["modules"] = tuple(raw["modules"])
    return Baseline(**raw)


@dataclass(frozen=True, slots=True)
class Report:
    budgets: Budgets
    witnessed: bool
    counters: dict[str, list[str]]
    warm_ms: list[float]
    cold_ms: list[float]
    modules: tuple[str, ...]
    baseline: Baseline | None
    failures: tuple[str, ...]

    @property
    def warm_p95(self) -> float:
        return p95(self.warm_ms)

    @property
    def cold_p95(self) -> float:
        return p95(self.cold_ms)

    def lines(self) -> tuple[str, ...]:
        b = self.budgets
        over = sum(1 for one in self.cold_ms if one > b.self_deadline_ms)
        out = [
            f"G26  witness   prompt -> {self.counters.get('prompt')}  control -> "
            f"{self.counters.get(CONTROL_WORD)}  {'ok' if self.witnessed else 'FAIL'}",
            f"G26  warm      p95 {self.warm_p95:.0f} ms over {len(self.warm_ms)} runs "
            f"(budget {b.warm_ms:.0f})",
            f"G26  cold      p95 {self.cold_p95:.0f} ms over {len(self.cold_ms)} runs "
            f"(budget {b.cold_ms:.0f}"
            + ("; OVER BUDGET" if self.cold_p95 > b.cold_ms else "")
            + "; an empty pycache, an upper bound on the real cold case; reported, fails nothing"
            + " -- D607)",
            f"G26  deadline  {over} of {len(self.cold_ms)} cold runs over the "
            f"{b.self_deadline_ms:.0f} ms self-deadline (D394; reported, fails nothing)",
            f"G26  modules   {len(self.modules)} on the hook path",
        ]
        if self.baseline is None:
            out.append(
                f"G26  baseline  UNMEASURED: no {baseline_path().name}; band and count not run"
            )
        else:
            out.append(
                f"G26  baseline  {self.baseline.module_count} modules, warm p95 "
                f"{self.baseline.warm_p95_ms:.0f} ms (+{BAND_PCT:.0f}% band), recorded "
                f"{self.baseline.recorded_at} on {self.baseline.runner}"
            )
        out.extend(f"G26 FAIL  {one}" for one in self.failures)
        out.append("G26  " + ("FAIL" if self.failures else "ok"))
        return tuple(out)


def judge(
    budgets: Budgets,
    *,
    witnessed: bool,
    warm_ms: list[float],
    modules: tuple[str, ...],
    baseline: Baseline | None,
) -> tuple[str, ...]:
    """Every failure, in the order the module docstring gives the assertions. Pure."""
    failures: list[str] = []
    if not witnessed:
        failures.append(
            "the prompt did not reach the UserPromptSubmit handler: timing it would "
            "time the no-op path (D432)"
        )
    if p95(warm_ms) > budgets.warm_ms:
        failures.append(f"warm p95 {p95(warm_ms):.0f} ms > {budgets.warm_ms:.0f} ms")
    #  No cold clause, on purpose (D607): the cold figure is an upper bound on a state a real
    #  install never has, measured at 486 and 1,310 ms on one machine an hour apart, so failing on
    #  it would fail the gate for a condition that is not the real case. It is REPORTED.
    if baseline is not None:
        new = sorted(set(modules) - set(baseline.modules))
        if len(modules) > baseline.module_count:
            failures.append(
                f"{len(modules)} modules on the hook path against the baseline's "
                f"{baseline.module_count}; new: {', '.join(new) or '(renamed)'}"
            )
        ceiling = baseline.warm_p95_ms * (1 + BAND_PCT / 100)
        if p95(warm_ms) > ceiling:
            failures.append(
                f"warm p95 {p95(warm_ms):.0f} ms > the baseline's {baseline.warm_p95_ms:.0f} ms "
                f"+ {BAND_PCT:.0f}% = {ceiling:.0f} ms"
            )
    return tuple(failures)


def measure(
    root: Path,
) -> tuple[bool, dict[str, list[str]], list[float], list[float], tuple[str, ...]]:
    (root / "omniweave.toml").write_text(PROJECT_TOML, encoding="utf-8")
    witnessed, counters = witness(root)
    for _ in range(WARMUP_RUNS):
        _spawn(root, HOOK)
    warm = [_spawn(root, HOOK)[0] for _ in range(WARM_RUNS)]
    cold: list[float] = []
    for _ in range(COLD_RUNS):
        with tempfile.TemporaryDirectory() as prefix:
            cold.append(_spawn(root, HOOK, {"PYTHONPYCACHEPREFIX": prefix})[0])
    return witnessed, counters, warm, cold, hook_modules(root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gate_hook_latency", description=(__doc__ or "G26").split("\n", 1)[0]
    )
    parser.add_argument("--record-baseline", action="store_true", help="write this OS's baseline")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--runner", default=platform.node(), help="the runner label to record")
    args = parser.parse_args(argv)
    limits = budgets()
    with tempfile.TemporaryDirectory() as scratch:
        witnessed, counters, warm, cold, modules = measure(Path(scratch))
    baseline = None if args.record_baseline else _load_baseline()
    failures = judge(limits, witnessed=witnessed, warm_ms=warm, modules=modules, baseline=baseline)
    report = Report(limits, witnessed, counters, warm, cold, modules, baseline, failures)
    if args.record_baseline and not failures:
        recorded = Baseline(
            baseline_schema=BASELINE_SCHEMA,
            os=platform.system().lower(),
            python=platform.python_version(),
            machine=platform.machine(),
            module_count=len(modules),
            modules=modules,
            warm_p95_ms=round(report.warm_p95, 1),
            cold_p95_ms=round(report.cold_p95, 1),
            recorded_at=datetime.now(UTC).strftime("%Y-%m-%d"),
            runner=args.runner,
        )
        payload = json.dumps(asdict(recorded), indent=2, sort_keys=True) + "\n"
        baseline_path().write_bytes(payload.encode("utf-8"))
    #  `sys.stdout.write`, not `print`: the repository lints with ruff's T20 (gate_coldstart).
    if args.json:
        extra = {"warm_p95_ms": report.warm_p95, "cold_p95_ms": report.cold_p95}
        sys.stdout.write(json.dumps({**asdict(report), **extra}, indent=2) + "\n")
    else:
        sys.stdout.write("\n".join(report.lines()) + "\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
