"""G9 + G23 — what `import omniweave_core` actually executes, read off `-X importtime`.

**What it reads.** Nothing on disk. It spawns fresh interpreters:
`python -X importtime -c "import omniweave_core"`, the same for `omniweave_ports`, and an empty
`-c ""` baseline.

**What it asserts.**

* **G9** — the modules `-X importtime` attributes to each import are stdlib or first-party and
  nothing else. Zero third-party modules, measured as a **difference against the bare-interpreter
  baseline**, because a virtualenv injects `_virtualenv`, `_distutils_hack`, `sitecustomize` and —
  on Windows — `pywin32_bootstrap` under `site` before any user code runs. Read absolutely those
  are third-party modules in the trace; read as a difference they cancel, and what is left is what
  the import actually cost.
* **G23** — neither `asyncio` nor `selectors`, named explicitly rather than left to the
  third-party check, because both are stdlib and nothing else would catch them. The single event
  loop in the framework lives in `omniweave/run/`, in the CLI distribution, precisely so core pays
  no loop-import tax (INV-3); ruff's `banned-api` block bans `asyncio` repo-wide with the
  per-file-ignore scoped to `packages/omniweave/src/omniweave/run/*.py`, and this is the runtime
  half of that ban.

**Two instruments, and they must agree.** `-X importtime` reports what was *executed*, so a module
already in `sys.modules` for another reason never appears; `sys.modules` reports what is
*reachable*, so a re-export that is free on a warm interpreter and expensive on a cold one shows up
there and not in the trace. Both are read here and a disagreement is itself the finding.

**The negative control.** A gate that has never seen a red is a gate nobody has tested, so before
asserting anything this script writes a one-line module into a temporary directory, imports it in a
fresh interpreter with that directory on `sys.path`, and requires the trace instrument to classify
it as third party. Synthesised rather than borrowed from the dev group: the control must work in
the same bare environment G9 is supposed to run in, where no third-party package is installed.

**Why a subprocess is not an optimisation here.** It is the only witness. Once this process has
imported anything, its own `sys.modules` can no longer answer "what does a bare
`import omniweave_core` load".

The same two properties are asserted from the test tree by
`packages/omniweave-core/tests/test_purity.py`, whose header names this script as the CI half.
Exit 0 clean, 1 with one `G9/G23 FAIL` block per finding.
Specified in 02-architecture.md section 3.3 and 16-roadmap.md sections 2.4 and 4.
"""

from __future__ import annotations

import json
import re
import subprocess  # noqa: TID251 — a fresh interpreter is the only witness for G9 and G23.
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FORBIDDEN_EAGER_MODULES",
    "SUBJECTS",
    "Finding",
    "Interpreter",
    "check_negative_control",
    "check_no_event_loop",
    "check_no_third_party",
    "emit",
    "main",
    "third_party",
]

SUBJECTS: tuple[str, ...] = ("omniweave_core", "omniweave_ports")
"""The two distributions INV-2 makes a claim about. Both are walked, not just core.

`omniweave_ports` is stdlib-only by row as well as by declaration, so a third-party module there
would be unspellable twice over — which is exactly why leaving it unchecked would be the cheap
place for one to appear.
"""

FORBIDDEN_EAGER_MODULES: tuple[str, ...] = ("asyncio", "selectors")
"""G23's two names, verbatim from charter D1's gate row.

`selectors` is listed beside `asyncio` because it is what an event loop pulls in first and is the
name that survives a refactor that replaces the loop with a hand-rolled poll.
"""

_IMPORTTIME_LINE = re.compile(r"^import time:\s+[\d-]+\s*\|\s+[\d-]+\s*\|\s*(?P<module>\S+)\s*$")
"""`-X importtime` writes `self [us] | cumulative | imported package` to **stderr**.

Matched rather than split on `|` so the header row and any interleaved warning are skipped by
construction.
"""

_MODULES_PROGRAM = """
{statement}
import json as _json, sys as _sys
print(_json.dumps(sorted(_sys.modules)))
"""

_CONTROL_MODULE = "owgate_importtime_control"

_TIMEOUT_S = 300.0


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation, with the instrument that saw it."""

    instrument: str
    subject: str
    why: str
    fix: str

    def block(self) -> str:
        pad = " " * 13
        body = "\n".join(f"{pad}{line}" for line in (self.subject, *self.why.splitlines()))
        return f"G9/G23 FAIL  {self.instrument}\n{body}\n{pad}fix: {self.fix}"


@dataclass(frozen=True, slots=True)
class Interpreter:
    """Runs a statement in a fresh interpreter and reports what it imported.

    `executable` is `sys.executable` in normal use, which is why `sys.stdlib_module_names` of this
    process is the right membership test for the child's modules: they are the same interpreter.
    """

    executable: str

    def _run(self, flags: tuple[str, ...], source: str) -> tuple[str, str]:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell, argv[0] is sys.executable
            [self.executable, *flags, "-c", source],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
        if completed.returncode != 0:
            message = (
                f"fresh interpreter exited {completed.returncode}\n"
                f"--- source ---\n{source}\n--- stderr ---\n{completed.stderr}"
            )
            raise RuntimeError(message)
        return completed.stdout, completed.stderr

    def trace(self, statement: str) -> frozenset[str]:
        """Every module name `-X importtime` reports while running `statement`."""
        _, stderr = self._run(("-X", "importtime"), statement)
        found = {
            matched.group("module")
            for line in stderr.splitlines()
            if (matched := _IMPORTTIME_LINE.match(line)) is not None
        }
        return frozenset(found)

    def attributed(self, statement: str) -> frozenset[str]:
        """`trace(statement)` minus the bare-interpreter baseline — what the import cost."""
        return self.trace(statement) - self.trace("")

    def modules_after(self, statement: str) -> frozenset[str]:
        """`sys.modules` once `statement` has run, as the complementary instrument."""
        stdout, _ = self._run((), _MODULES_PROGRAM.format(statement=statement))
        names: list[str] = json.loads(stdout.strip().splitlines()[-1])
        return frozenset(names)


def third_party(names: frozenset[str]) -> tuple[str, ...]:
    """`names` minus the standard library minus every first-party root.

    Private `_`-prefixed names are dropped for the same reason
    `packages/omniweave-core/tests/test_purity.py` drops them: they are the virtualenv's own
    bootstrap machinery (`_virtualenv`, `_distutils_hack`), which the baseline subtraction usually
    cancels and which is never a declared dependency of anything. The two instruments must agree
    with the test tree or the disagreement is a false finding on one side.
    """
    stdlib = frozenset(sys.stdlib_module_names) | {"__future__", "__main__"}
    return tuple(
        sorted(
            name
            for name in names
            if not name.startswith("_")
            and name.split(".", 1)[0] not in stdlib
            and not (
                name.split(".", 1)[0] == "omniweave"
                or name.split(".", 1)[0].startswith("omniweave_")
            )
        )
    )


def check_negative_control(interpreter: Interpreter) -> list[Finding]:
    """Prove the trace instrument classifies a third-party module as one, before trusting it.

    The module is synthesised into a temporary directory rather than borrowed from the dev group,
    because the environment this gate is designed for is the one with nothing installed.
    """
    with tempfile.TemporaryDirectory(prefix="ow-g9-") as directory:
        home = Path(directory)
        (home / f"{_CONTROL_MODULE}.py").write_text(
            "MARKER = 'the G9 instrument must see this module as third party'\n",
            encoding="utf-8",
            newline="\n",
        )
        statement = f"import sys; sys.path.insert(0, {str(home)!r}); import {_CONTROL_MODULE}"
        seen = third_party(interpreter.attributed(statement))
    if _CONTROL_MODULE in seen:
        return []
    return [
        Finding(
            instrument="the negative control",
            subject=f"-X importtime did not attribute {_CONTROL_MODULE} to its own import",
            why=(
                "the instrument cannot see a third-party module, so every assertion below it is "
                "vacuous. A gate whose instrument is silently broken reports green forever."
            ),
            fix="check the -X importtime line grammar in _IMPORTTIME_LINE against this Python.",
        )
    ]


def check_no_third_party(interpreter: Interpreter) -> list[Finding]:
    """G9, over both pure distributions and through both instruments."""
    findings: list[Finding] = []
    for subject in SUBJECTS:
        statement = f"import {subject}"
        executed = third_party(interpreter.attributed(statement))
        if executed:
            findings.append(
                Finding(
                    instrument=f"-X importtime -c {statement!r}",
                    subject=f"executed third-party modules: {list(executed)}",
                    why=(
                        f"{subject} has ZERO third-party runtime dependencies (INV-2, gate G9). "
                        "docling's DOCX reader costs ~2.5-3.5 GB installed because torch is a "
                        "BASE requirement; this is the gate that keeps that from happening here."
                    ),
                    fix="import it inside the driver distribution that needs it, behind a Port.",
                )
            )
        reachable = third_party(
            interpreter.modules_after(statement) - interpreter.modules_after("")
        )
        if reachable and reachable != executed:
            findings.append(
                Finding(
                    instrument=f"sys.modules after {statement!r}",
                    subject=f"reachable third-party modules: {list(reachable)}",
                    why=(
                        "the two instruments disagree, which is itself the finding: -X importtime "
                        "sees what was executed and sys.modules sees what is reachable, so a "
                        "module here and not in the trace was pulled in by a re-export."
                    ),
                    fix="defer the re-export; INV-3 is about the cold interpreter, not the warm.",
                )
            )
    return findings


def check_no_event_loop(interpreter: Interpreter) -> list[Finding]:
    """G23 — `asyncio` and `selectors` by name, absolutely rather than as a difference.

    Absolutely, because the difference would cancel a baseline that had already loaded them: if the
    bare interpreter in this environment imports `asyncio` at startup then G23 cannot be measured
    here at all, and saying so is more honest than reporting a green that means nothing.
    """
    findings: list[Finding] = []
    baseline = interpreter.modules_after("")
    contaminated = tuple(name for name in FORBIDDEN_EAGER_MODULES if name in baseline)
    if contaminated:
        return [
            Finding(
                instrument="the baseline interpreter",
                subject=f"a bare `python -c ''` already loaded {list(contaminated)}",
                why=(
                    "G23 is unmeasurable in this environment: something in site-packages or a "
                    ".pth file imports an event loop before user code runs."
                ),
                fix="run the gate in a clean virtualenv (uv run --isolated).",
            )
        ]
    statement = f"import {SUBJECTS[0]}"
    for instrument, loaded in (
        (f"sys.modules after {statement!r}", interpreter.modules_after(statement)),
        (f"-X importtime -c {statement!r}", interpreter.trace(statement)),
    ):
        present = tuple(name for name in FORBIDDEN_EAGER_MODULES if name in loaded)
        if present:
            findings.append(
                Finding(
                    instrument=instrument,
                    subject=f"{statement} loaded {list(present)}",
                    why=(
                        "G23: core must not import an event loop. The one loop in the framework "
                        "lives in omniweave/run/, in the CLI distribution, so that `ow hook "
                        "prompt` — a 250 ms warm p95 budget whose every failure is a silent exit "
                        "0 — pays nothing for it (INV-3)."
                    ),
                    fix="move the loop-using code into packages/omniweave/src/omniweave/run/.",
                )
            )
    return findings


def emit(line: str = "") -> None:
    """Write one line to stdout; ruff's `T20` bans `print` repo-wide and `tools/` has no ignore."""
    sys.stdout.write(line + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run G9 and G23. 0 clean, 1 with one block per finding, 2 when the gate could not run."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        emit(f"usage: {Path(__file__).name}   (no arguments; it spawns fresh interpreters)")
        return 2

    interpreter = Interpreter(executable=sys.executable)
    try:
        findings = check_negative_control(interpreter)
        findings.extend(check_no_third_party(interpreter))
        findings.extend(check_no_event_loop(interpreter))
    except RuntimeError as error:
        emit("G9/G23 CANNOT RUN  a probe interpreter failed:")
        for line in str(error).splitlines():
            emit(f"                   {line}")
        emit("                   fix: `uv sync`, then re-run.")
        return 2

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G9/G23 FAIL  {len(findings)} finding(s).")
        return 1

    emit(
        f"G9/G23 ok  {list(SUBJECTS)} execute zero third-party modules and load neither "
        f"{FORBIDDEN_EAGER_MODULES[0]} nor {FORBIDDEN_EAGER_MODULES[1]}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
