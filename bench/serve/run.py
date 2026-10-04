"""`uv run python bench/serve/run.py`: the adoption harness in one command (ADR-14 D14.7).

1. **Configure.** `agent.toml`, each key's `OW_BENCH_<KEY>` twin, and the flags below, resolved
   flag > environment > file > default. Every value is printed with its source.
2. **Select.** `--tasks` takes `all`, or a comma list of ids, classes (`citation`, `retrieval`,
   `absence`, `damaged`) and corpora (`legal_matter`, `data_room`, `personal_archive`).
3. **Hold back what cannot be measured yet, and say why.** A `damaged` task needs its Injector,
   which is P6's absence suite (`omniweave_conform.damage`); one whose Injector is not built yet
   is held back. The catalogue's missing scanned tasks wait on the public-domain scans (ADR-14
   D14.1 part 3).
4. **Prepare** each corpus once per content digest (`corpora.prepare`, cached). A damaged task
   gets its corpus with its answer's file damaged by its Injector, cached apart (D640).
5. **Run** every task on each arm, `workers` at a time, each on its own agent. The omniweave arm
   also gets its own `ow serve --mcp` child.
6. **Grade and report.** `serve_harness` turns transcripts into `source_reread_rate` paired with
   `task_accuracy`, sliced, and the `Control guard` when both arms ran.

**The default needs nothing.** `cassette = required` replays `fixtures/cassettes/agent/` and calls
no provider. With no recording yet, the run stops before any corpus is built and says how to
record. A local model needs no key:

    uv run python bench/serve/run.py --record --provider openai \\
        --base-url http://localhost:11434/v1 --model qwen3:8b --scale quick

Exit 0: every measured task ran, and the guard held (or only one arm ran). Exit 1: a task
failed, or the guard failed. Exit 2: the run could not start (configuration, provider or
corpus), with the fix.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import anyio
from agent import AgentRun, LoopSettings, OwServer, ToolServer, TurnFn, run_task
from agent_cassette import CASSETTE_ROOT, SERVICE, AgentCassette, CassetteMissError, audit
from agent_config import BenchConfigError, Config, resolve
from corpora import CorpusError, Prepared, damage_of, default_cache, key_of, prepare
from host_tools import HostTools
from models import ModelClient, ModelError, client_for
from omniweave_conform.damage import INJECTORS, TABLE
from omniweave_core.cassette import CassetteMode
from serve_harness import (
    Arm,
    Catalog,
    ControlGuard,
    Corpus,
    Task,
    TaskClass,
    TaskOutcome,
    load_catalog,
    outcome,
    report,
)

__all__ = [
    "Failure",
    "Graded",
    "Unmeasured",
    "corpus_key",
    "main",
    "partition",
    "run_all",
    "select",
    "summarize",
]

HERE: Final[Path] = Path(__file__).resolve().parent
TASKS_TOML: Final[Path] = HERE / "tasks.toml"


@dataclass(frozen=True, slots=True)
class Unmeasured:
    task_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Failure:
    task_id: str
    arm: Arm
    message: str


@dataclass(frozen=True, slots=True)
class Graded:
    task: Task
    run: AgentRun
    outcome: TaskOutcome


ServerFactory = Callable[[Prepared], AbstractAsyncContextManager[ToolServer]]


def select(catalog: Catalog, spec: str) -> tuple[Task, ...]:
    """`all`, or a comma list of task ids, classes and corpora. An unknown word is refused."""
    if spec.strip() == "all":
        return catalog.tasks
    ids = {task.id for task in catalog.tasks}
    classes = {one.value for one in TaskClass}
    corpora = {one.value for one in Corpus}
    words = [word.strip() for word in spec.split(",") if word.strip()]
    unknown = [word for word in words if word not in ids | classes | corpora]
    if unknown:
        msg = (
            f"--tasks names {unknown}, which are neither task ids nor classes nor corpora. "
            f"Classes: {', '.join(sorted(classes))}; corpora: {', '.join(sorted(corpora))}; "
            "`--list` prints the ids"
        )
        raise BenchConfigError(msg)
    return tuple(
        task
        for task in catalog.tasks
        if task.id in words or task.task_class.value in words or task.corpus.value in words
    )


def partition(tasks: Sequence[Task]) -> tuple[tuple[Task, ...], tuple[Unmeasured, ...]]:
    """Split off what cannot be measured on this build, each with its reason."""
    runnable: list[Task] = []
    held: list[Unmeasured] = []
    built = ", ".join(INJECTORS)
    for task in tasks:
        if task.injector is not None and task.injector not in INJECTORS:
            held.append(
                Unmeasured(
                    task.id,
                    f"needs the {task.injector} Injector, which is P6's absence suite "
                    f"(13-quality.md section 8.6) and not built yet; built: {built} "
                    f"({len(INJECTORS)} of {len(TABLE)})",
                )
            )
        else:
            runnable.append(task)
    return tuple(runnable), tuple(held)


def corpus_key(task: Task) -> str:
    """Which prepared corpus `task` runs over: its own damaged one, if it is a damaged task."""
    return key_of(task.corpus.value, damage_of(task.id, task.injector))


def default_server(prepared: Prepared) -> AbstractAsyncContextManager[ToolServer]:
    return OwServer(cwd=prepared.project, env=prepared.env)


async def run_all(
    tasks: Sequence[Task],
    arms: Sequence[Arm],
    prepared: Mapping[str, Prepared],
    *,
    turn: TurnFn,
    settings: LoopSettings,
    workers: int,
    server_factory: ServerFactory = default_server,
    log: Callable[[str], None] = lambda _line: None,
) -> tuple[list[Graded], list[Failure]]:
    """Every task on every arm, `workers` at a time. A failed task is recorded, never fatal."""
    graded: list[Graded] = []
    failures: list[Failure] = []
    limiter = anyio.CapacityLimiter(workers)
    indexed = {key: one.indexed() for key, one in prepared.items()}

    async def one(task: Task, arm: Arm) -> None:
        corpus = prepared[corpus_key(task)]
        async with limiter:
            try:
                if arm is Arm.OMNIWEAVE:
                    async with server_factory(corpus) as server:
                        done = await run_task(
                            task.id, task.prompt, arm, host=HostTools(corpus.docs), turn=turn,
                            settings=settings, server=server,
                        )  # fmt: skip
                else:
                    done = await run_task(
                        task.id, task.prompt, arm, host=HostTools(corpus.docs), turn=turn,
                        settings=settings,
                    )  # fmt: skip
            except (CassetteMissError, ModelError, OSError, RuntimeError) as exc:
                failures.append(Failure(task.id, arm, str(exc)))
                log(f"  FAILED    {arm.value:9} {task.id}: {str(exc)[:160]}")
                return
        graded.append(Graded(task, done, outcome(task, done.transcript, indexed[corpus_key(task)])))
        mark = "right" if graded[-1].outcome.correct else "WRONG"
        log(f"  task      {arm.value:9} {task.id:28} {mark}  {done.tool_calls} calls")

    async with anyio.create_task_group() as group:
        for task in tasks:
            for arm in arms:
                group.start_soon(one, task, arm)
    order = {task.id: index for index, task in enumerate(tasks)}
    graded.sort(key=lambda g: (order[g.task.id], g.outcome.arm.value))
    return graded, failures


def summarize(
    config: Config,
    graded: Sequence[Graded],
    failures: Sequence[Failure],
    unmeasured: Sequence[Unmeasured],
    owed: Mapping[TaskClass, int],
) -> tuple[list[str], bool, dict[str, Any]]:
    """The report's lines, whether the run passed, and the same facts as JSON."""
    lines: list[str] = []
    by_arm = {arm: [g.outcome for g in graded if g.outcome.arm is arm] for arm in Arm}
    for arm in (Arm(one) for one in config.arms):
        if by_arm[arm]:
            lines.extend(report(arm, by_arm[arm]).lines())
    guard: ControlGuard | None = None
    both = {Arm(one) for one in config.arms} == set(Arm)
    if both and by_arm[Arm.OMNIWEAVE] and by_arm[Arm.CONTROL]:
        paired = {o.task_id for o in by_arm[Arm.OMNIWEAVE]} & {
            o.task_id for o in by_arm[Arm.CONTROL]
        }
        guard = ControlGuard.judge(
            [o for o in by_arm[Arm.OMNIWEAVE] if o.task_id in paired],
            [o for o in by_arm[Arm.CONTROL] if o.task_id in paired],
        )
        lines.append(guard.lines()[-1] + f"  (n = {len(paired)} paired tasks)")
    exhausted = sorted(
        f"{g.outcome.arm.value}:{g.task.id}" for g in graded if g.run.budget_exhausted
    )
    if exhausted:
        lines.append(f"budget_exhausted  {len(exhausted)}: {', '.join(exhausted)}")
    for held in unmeasured:
        lines.append(f"UNMEASURED  {held.task_id}: {held.reason}")
    if owed:
        missing = ", ".join(f"{n} {cls.value}" for cls, n in owed.items())
        lines.append(
            f"OWED        the catalogue lacks {missing} task(s): the scanned slice, which lands "
            "with its public-domain scans (ADR-14 D14.1 part 3)"
        )
    for failure in failures:
        lines.append(f"FAILED      {failure.arm.value}:{failure.task_id}: {failure.message}")
    if config.scale.value == "quick":
        lines.append("WATERMARK   scale: quick -- a local iteration number; it gates nothing")
    passed = not failures and (guard is None or guard.ok)
    result = {
        "passed": passed,
        "scale": config.scale.value,
        "model_key": config.model_key,
        "cassette": config.cassette,
        "config": {key: str(setting.value) for key, setting in config.settings.items()},
        "outcomes": [
            {
                "task": g.task.id,
                "arm": g.outcome.arm.value,
                "correct": g.outcome.correct,
                "reread": g.outcome.reread,
                "mis_pick": g.outcome.mis_pick,
                "tool_calls": g.run.tool_calls,
                "budget_exhausted": g.run.budget_exhausted,
                "answer": g.run.transcript.answer,
            }
            for g in graded
        ],
        "control_guard": None
        if guard is None
        else {"ok": guard.ok, "p_worse": guard.p_worse, "gamed": guard.gamed},
        "unmeasured": [{"task": u.task_id, "reason": u.reason} for u in unmeasured],
        "owed": {cls.value: n for cls, n in owed.items()},
        "failures": [
            {"task": f.task_id, "arm": f.arm.value, "message": f.message} for f in failures
        ],
    }
    return lines, passed, result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="bench/serve's adoption harness: both arms, graded and paired (ADR-14)",
        epilog="Every knob also has an OW_BENCH_<KEY> environment twin and a line in agent.toml.",
    )
    knob = parser.add_argument_group("knobs (agent.toml)")
    knob.add_argument("--tasks", help="all | comma list of ids, classes, corpora")
    knob.add_argument("--arms", help="omniweave,control (default both)")
    knob.add_argument("--scale", choices=("full", "quick"))
    knob.add_argument("--workers", type=int)
    knob.add_argument("--cassette", choices=("required", "allow", "off"))
    knob.add_argument("--provider", choices=("anthropic", "openai"))
    knob.add_argument("--model")
    knob.add_argument("--base-url", dest="base_url")
    knob.add_argument("--api-key-env", dest="api_key_env")
    knob.add_argument("--temperature", help='"default" (send none) or 0.0-2.0')
    knob.add_argument("--max-tokens", dest="max_tokens", type=int)
    knob.add_argument("--tool-budget", dest="tool_budget", type=int)
    knob.add_argument("--timeout-s", dest="timeout_s", type=int)
    run = parser.add_argument_group("run")
    run.add_argument("--record", action="store_true", help="shorthand for --cassette allow")
    run.add_argument("--list", action="store_true", help="print the selected tasks and stop")
    run.add_argument(
        "--audit-cassettes",
        action="store_true",
        help="check every committed recording offline (key, place, size, spelling) and stop",
    )
    run.add_argument("--prepare-only", action="store_true", help="build the corpora and stop")
    run.add_argument(
        "--cache", type=Path, help="corpus cache (default $OMNIWEAVE_HOME/bench-cache)"
    )
    run.add_argument("--cassettes", type=Path, default=CASSETTE_ROOT, help="recordings root")
    run.add_argument("--json", type=Path, help="also write the report as JSON here")
    return parser


KNOBS: Final = (
    "tasks", "arms", "scale", "workers", "cassette", "provider", "model", "base_url",
    "api_key_env", "temperature", "max_tokens", "tool_budget", "timeout_s",
)  # fmt: skip


_NO_RECORDINGS: Final = (
    "no recordings under {root} to replay. Record them first, which needs a model: a local one "
    "needs no key -- --record --provider openai --base-url http://localhost:11434/v1 --model "
    "<model> (Ollama; vLLM, llama.cpp and LM Studio work the same) -- or --record with "
    "ANTHROPIC_API_KEY set. Add --scale quick to iterate faster"
)


@dataclass(frozen=True, slots=True)
class Started:
    """Everything a run needs before its first model turn."""

    config: Config
    catalog: Catalog
    runnable: tuple[Task, ...]
    unmeasured: tuple[Unmeasured, ...]
    cassette: AgentCassette
    client: ModelClient | None
    prepared: dict[str, Prepared]


def _emit(line: str) -> None:
    sys.stdout.write(line + "\n")


def _start(args: argparse.Namespace, emit: Callable[[str], None]) -> Started | None:
    """Configure, select, check the recordings and the provider, prepare the corpora.

    `None` when the run stops early by request (`--list`, `--prepare-only`). Raises
    `BenchConfigError`, `ModelError` or `CorpusError`, each already worded as its fix.
    """
    flags = {key: getattr(args, key) for key in KNOBS}
    if args.record:
        flags["cassette"] = "allow"
    config = resolve(flags=flags)
    catalog = load_catalog(TASKS_TOML.read_text(encoding="utf-8"))
    chosen = select(catalog, config.tasks)
    runnable, unmeasured = partition(chosen)
    emit("bench/serve: configuration (value, and where it came from)")
    for line in config.report_lines():
        emit(f"  {line}")
    if args.list:
        for task in chosen:
            held = next((u.reason for u in unmeasured if u.task_id == task.id), "")
            emit(f"  {task.id:28} {task.task_class.value:9} {task.corpus.value:16}"
                 + (f" UNMEASURED: {held}" if held else ""))  # fmt: skip
        return None
    mode = CassetteMode(config.cassette)
    root = args.cassettes / SERVICE
    #  D650: `--prepare-only` builds the corpora and calls no model, so it needs neither a
    #  recording to replay nor a provider to record with.
    if not args.prepare_only and mode is CassetteMode.REQUIRED and not any(root.rglob("*.json")):
        raise BenchConfigError(_NO_RECORDINGS.format(root=root.as_posix()))
    client = None
    if mode is not CassetteMode.REQUIRED and not args.prepare_only:
        client = client_for(
            config.provider, key_env=config.key_env, base_url=config.base_url,
            timeout_s=config.timeout_s,
        )  # fmt: skip
    cache_root = args.cache or default_cache()
    wanted = {corpus_key(task): task for task in runnable}
    prepared = {
        key: prepare(
            task.corpus.value,
            config.scale.value,
            cache_root=cache_root,
            damage=damage_of(task.id, task.injector),
            log=emit,
        )
        for key, task in sorted(wanted.items())
    }
    if args.prepare_only:
        return None
    return Started(
        config,
        catalog,
        runnable,
        unmeasured,
        AgentCassette(mode, args.cassettes, corpora=cache_root),
        client,
        prepared,
    )


def _audit(root: Path, out: Callable[[str], None]) -> int:
    """`--audit-cassettes`: the `golden` job's Cassette step. 0 clean, 1 with each problem named."""
    count, total, problems = audit(root)
    for problem in problems:
        out(f"  FAILED    {problem}")
    verdict = "FAILED" if problems else "passed"
    out(f"bench/serve: cassette audit {verdict}: {count} recordings, {total} bytes")
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None, *, out: Callable[[str], None] = _emit) -> int:
    args = _parser().parse_args(argv)
    if args.audit_cassettes:
        return _audit(args.cassettes, out)
    try:
        started = _start(args, out)
    except (BenchConfigError, ModelError, CorpusError) as exc:
        out(f"bench/serve: {exc}")
        return 2
    if started is None:
        return 0
    config, cassette = started.config, started.cassette
    live = started.client.complete if started.client is not None else None
    settings = LoopSettings(config.model, config.temperature, config.max_tokens, config.tool_budget)
    graded, failures = anyio.run(
        lambda: run_all(
            started.runnable,
            [Arm(one) for one in config.arms],
            started.prepared,
            turn=lambda request: cassette.turn(request, model_key=config.model_key, live=live),
            settings=settings,
            workers=config.workers,
            log=out,
        )
    )
    lines, passed, result = summarize(
        config, graded, failures, started.unmeasured, started.catalog.missing()
    )
    result["cassette_ledger"] = {
        "hits": len(cassette.hits),
        "recorded": len(cassette.recorded),
        "live_calls": cassette.live_calls,
    }
    out("bench/serve: report")
    for line in lines:
        out(f"  {line}")
    out(
        f"  cassette    {cassette.mode.value}: {len(cassette.hits)} replayed, "
        f"{len(cassette.recorded)} recorded, {cassette.live_calls} live calls"
    )
    out(f"bench/serve: {'passed' if passed else 'FAILED'}")
    if args.json is not None:
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
