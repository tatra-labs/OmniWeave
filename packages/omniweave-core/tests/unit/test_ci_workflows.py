"""`.github/workflows/` against 11-repo-layout.md section 6 and `tools/gates.toml`.

Section 6.1 is the whole premise: *"`.github/workflows/` holds exactly two files: `ci.yml` and
`release.yml`. `release.yml` invokes `ci.yml` through `workflow_call`, so **the release gate *is*
CI** and the two cannot diverge."* Two files can only fail to diverge if something checks, and at
release 1 nothing does -- `zizmor` is unpinnable (section 6.7 rule (b) wants
`uvx <name>==<exact version>` and the plan names no version) and the
`gates.workflow_tools_pinned` job assertion is therefore unarmed. This file is the in-repo half
until it arms.

**IT PARSES YAML WITH `re`, LINE BY LINE, AND THAT IS THE HONEST CHOICE HERE RATHER THAN A
SHORTCUT.** PyYAML is not in `pyproject.toml`'s `[dependency-groups] dev` -- section 6.2 fixes that
group at exactly the ten packages the charter prints and 02-architecture.md section 3.3 gives the
reason -- so a test that imported `yaml` would either add an eleventh package or skip itself on a
clean checkout, and a gate that skips is section 6.8's "check that cannot yet fail". The cost is
real and is stated: this parser knows about indentation and nothing about YAML semantics. It cannot
see an anchor, a merge key, a flow mapping spread over lines, or a `run:` body that happens to
contain a line shaped like a step. Every assertion below is written to survive that -- and
`test_the_parser_found_what_it_should_have_found` is the guard section 6.8 demands of "every gate
here that discovers its own inputs ... an assertion on the count of things it found", adopted from
graphify's `test_the_table_was_actually_parsed`: *"a regex that silently matches nothing would make
every parametrized test below vacuous."*

**MENTIONS ARE NOT DEFINITION SITES, and two assertions here would be false if they forgot it.**
`ci.yml`'s header explains at length why `G22` is absent and why there is no `continue-on-error`
anywhere, so a bare substring search for either finds the documentation and fails the file for
documenting itself. So `G22`-is-absent is asserted over step *names* and `run:` bodies, and
`continue-on-error: true` over non-comment lines. Both are stated at their assertion.

Fifteen properties, each one a sentence of section 6 made falsifiable. The last six were
written after a mutation wave: each of them names, at its own docstring, the edit that stayed
green before it existed.

* **exactly two files** under `.github/workflows/` (section 6.1), which is also the assertion
  section 1.1 fact 1 needs: a `release.yml` rename silently revokes PyPI publish rights, and the
  failure otherwise appears "only at the publish step of a tagged release".
* **`release.yml` calls `./.github/workflows/ci.yml`** and `ci.yml` carries the `workflow_call`
  trigger that makes the call legal. One definition of passing.
* **every job name in `tools/gates.toml` is a job in `ci.yml`, and no job in `ci.yml` is outside
  that array** -- both directions, because the register's `job_name` list is section 6.2's `needs`
  list plus the aggregator and is therefore closed.
* **every `[[gate]]` row with a PR job is invoked in the job its row names**, and `G22` -- the one
  row with `pr = false` -- is invoked nowhere. Section 6.4: it "blocks the *release* (checklist
  step 11) and is deliberately absent from `ci-ok`'s required set."
* **no step can pass for the wrong reason**: no `continue-on-error: true`, no `|| true`, no
  `--warn-only`. Section 6.8: "There is no `--warn-only` anywhere. A check that cannot yet fail is
  either quarantined as `informational` with an issue number ... or it is not in CI."
* **every `uses:` is a local path, a 40-hex SHA, or carries a `TODO: pin` marker.** Section 7.3
  rule 2 requires the SHA; the plan prints `@<40-hex>` and no actual SHA anywhere, so the marker is
  what stands in until an owner pins them, and this test is what stops the marker being forgotten.
* **the matrix is nine cells**, section 6.2's full `{3 OS} x {3 Python}` cross product, landed by
  P2 because 16-roadmap.md:340 makes `test (9 cells)` first green there. Each Python axis value is
  carried in `PYTHON_AXIS_BY_PHASE` next to the phase that landed it, and a second test refuses a
  row that is a placeholder -- see `test_the_matrix_is_nine_cells_landed_by_p2` for why the
  allow-list exists rather than a bare three-value tuple.
* **no "has not landed unwired" tripwire is already firing.** Four steps are shaped `if the path
  exists: exit 1`, which is section 6.8's instrument for a check whose input has not arrived. P2
  found the failure mode: G28's condition tested the whole `fixtures/` directory, `fixtures/gen/`
  landed under 13-quality.md:586-589, and a real gate would have gone red for a reason unrelated
  to what it guards. `CI_TRIPWIRE_PATHS` transcribes the paths and the test asks the runner's own
  question against the working tree.
* **P2's demo and measurement are wired as a MECHANISM and never as a budget verdict.**
  12-performance.md:1966 makes `ow-bench-1` the only machine a Budget may live on, this repository
  has no nightly job on it, and 11-repo-layout.md:1360 forbids a third workflow file -- so the
  substitute is a 64-page smoke that must invoke `tools/measure_store.py` WITHOUT `--gate` and
  must state the gap at the point a reader meets it.
* **both matrix axes are CONSUMED and not merely declared.** `runs-on` must read `matrix.os` and
  `UV_PYTHON` must read `matrix.py`; without that, nine cells are a nine-name label on a job that
  runs one configuration nine times, and the nine-cells-by-name assertion above cannot see it.
* **each cell keys its `uv` cache on its own Python version**, 11-repo-layout.md:1715-1716, which
  states it as arithmetic: sharing one key makes eight cells restore an environment resolved for
  another interpreter.
* **the steps that do the work run the work.** The `[[gate]]` rows' runners were already covered;
  the nine cells' `uv run pytest -q` and `G28`'s round trip were not, and an `echo` in either
  place is a required status check reporting on nothing.
* **no checkout persists the token.** 11-repo-layout.md:1772 puts `persist-credentials` on
  `zizmor`'s list, and `zizmor` is unarmed, so this is the only side of that fence with a check
  on it.
* **`versions` is a predecessor of every other job**, 11-repo-layout.md:1415-1416.
* **the tripwires are asked the runner's question about the paths THEY test**, extracted from
  each step's own shell rather than read off `CI_TRIPWIRE_PATHS` -- because a table cannot see a
  path the workflow tests and the table does not list, which is how the P2 regression comes back
  under a different spelling.

A note on the plan readers below. `_plan_text` distinguishes "there is no design tree" (skip,
honest on a CI checkout) from "the design tree is here and the document I name is not" (fail).
Collapsing those two is how a rename turns three gates off while printing a reason that did not
happen, which is section 6.8's "check that cannot yet fail" arriving through the back door.

Specified in 11-repo-layout.md sections 1.1, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 7.3 and 7.4,
13-quality.md sections 2.9 and 14, and 16-roadmap.md sections 4 and 5.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

WORKFLOW_DIR = ".github/workflows"
REGISTER = "tools/gates.toml"

# Section 6.2's `ci-ok` needs list, in its own order. Transcribed rather than parsed out of the
# plan for the same reason test_gates_packaging.py transcribes its ceiling tables: a drift between
# the workflow and the document should fail a test, and it cannot if both sides come from one side.
CI_OK_NEEDS: tuple[str, ...] = (
    "versions",
    "gates",
    "test",
    "golden",
    "conform",
    "incremental",
    "crash",
    "parity",
    "toolchains",
    "build",
)

# Section 6.2's axis table, 11-repo-layout.md:1464-1471: OS over three values in `test` (9 cells)
# and `nightly`, Python over 3.11/3.12/3.13 in `test` (9 cells). Transcribed, not parsed out of
# either the plan or the workflow, so a drift between the three has somewhere to fail.
MATRIX_OS: tuple[str, ...] = ("ubuntu-latest", "macos-latest", "windows-latest")

# THE PYTHON AXIS, BY THE PHASE THAT LANDED EACH VALUE, and the allow-list shape is the point.
# Adopted from `test_core_eager_surface.py`'s `FILLED_HOMES`, which met the identical problem when
# P2 filled `model/` and `store/`: an assertion written against one phase's world either goes false
# or goes vacuous when the next phase lands, and relaxing it picks the second. A value cannot enter
# the matrix by someone widening a tuple; it enters by someone adding a row here and naming the
# phase, and `test_every_python_axis_value_names_the_phase_that_landed_it` refuses a row whose
# phase has not landed.
PYTHON_AXIS_BY_PHASE: dict[str, str] = {
    "3.11": "P1 -- the single value 16-roadmap.md section 4's non-goal allowed",
    "3.12": "P2 -- 16-roadmap.md:340, `test` (9 cells) is first green in P2",
    "3.13": "P2 -- 16-roadmap.md:340, the third value of section 6.2's axis table",
}
MATRIX_PYTHON: tuple[str, ...] = ("3.11", "3.12", "3.13")

# Section 6.2's job graph prints the number out loud: "`test` -- {ubuntu, macos, windows} x
# {3.11,3.12,3.13} = 9 cells". A literal, so the product below is checked against the plan's
# arithmetic rather than against itself.
MATRIX_CELLS = 9

# The phases that have landed. A `PYTHON_AXIS_BY_PHASE` row naming anything else is an axis value
# smuggled in ahead of the work that justifies it, which is the placeholder case the allow-list
# has to be able to reject.
LANDED_PHASES: tuple[str, ...] = ("P1", "P2")

# THE "HAS NOT LANDED UNWIRED" TRIPWIRES, and why they need a test of their own.
#
# Four steps in `ci.yml` are shaped `if the path exists: echo "wire me"; exit 1`. They are the
# instrument section 6.8 asks for in place of a silent stub: a check that cannot yet run says so
# and, on the day its input arrives, FAILS the PR that brought it rather than staying green for
# another release. That design has one failure mode, and P2 hit it: a tripwire whose condition is
# broader than the thing it is waiting for fires on something else and turns a real gate red for
# the wrong reason. G28's condition was a bare test on the `fixtures/` directory;
# 13-quality.md:586-589 landed `fixtures/gen/` for the deterministic generator, which is a member
# of the `fixtures/` tree (11-repo-layout.md:383-384) and is not the licensed CORPUS G28's second
# half means.
#
# So the table is the paths, transcribed from the four steps, and the test asserts BOTH that none
# of them exists on this checkout (the tripwire is not already firing) and that each one is
# actually written in `ci.yml` (the table is not describing a step somebody deleted). Keys are the
# step the path belongs to, so a failure names the step to wire.
CI_TRIPWIRE_PATHS: dict[str, tuple[str, ...]] = {
    # ADR-2 decision 4's corpus half. `fixtures/index.toml` is Q-G1's generated manifest
    # (13-quality.md:92, :1985); the three directories are the corpus members of
    # 11-repo-layout.md:383-384 that hold documents. `fixtures/gen/` is deliberately NOT here.
    "G28": (
        "fixtures/index.toml",
        "fixtures/docs",
        "fixtures/office-200",
        "fixtures/regressions",
    ),
    # The `golden` job: the Tier-B corpus digest and the committed Cassettes (sections 6.2, 6.6).
    "golden": ("eval/corpora.toml", "fixtures/cassettes"),
    # 17-risks.md section 1.1's register, which sizes the check and names no script.
    "gates.risk_register": ("tools/risks.toml",),
    # 13-quality.md's metric-gate register. Its arrival is what wires the static Q-G series into
    # the `gates` job (11-repo-layout.md:1615-1617).
    "the static Q-G series": ("eval/gates.toml",),
}

# The step that owns each tripwire, by the `name:` `ci.yml` gives it and the job it sits in. A
# fifth tripwire added with no row in `CI_TRIPWIRE_PATHS` is invisible to the two tests above, so
# the four steps are pinned by name here rather than counted out of the file.
CI_TRIPWIRE_STEPS: dict[str, tuple[str, str]] = {
    "G28": ("gates", "G28 -- import(export(store)) == store over the fixture corpus"),
    "golden": ("golden", "the Tier-B corpus and the Cassettes have not landed unwired"),
    "gates.risk_register": (
        "gates",
        "gates.risk_register -- the same five rules over risks.toml's sixty rows",
    ),
    "the static Q-G series": ("gates", "the static Q-G series"),
}

# Section 6.6's two-sided budget rule: "Each job carries `timeout-minutes` at **twice** its stated
# budget -- a hard stop that turns a hung `parity` container into a 20-minute failure rather than a
# six-hour one." The parity number is the one the document states out loud, so it is pinned; the
# rest are checked for presence, because a wrong multiple is a review question and a missing
# timeout is a six-hour job.
PARITY_TIMEOUT_MINUTES = 20

# THE TWO SITES THAT TURN A MATRIX AXIS FROM A LABEL INTO A CELL, and the reason they are pinned
# as literals rather than counted.
#
# FOUND BY MUTATION, and it is the flagship assertion of this file that it defeats.
# `test_the_matrix_is_nine_cells_landed_by_p2` spells the nine cells out by name precisely so
# that it cannot be satisfied by "three cells of entirely the wrong kind" -- its own words. But
# it reads the axis DECLARATION and never asks whether anything consumes it. Replacing
# `runs-on: ${{ matrix.os }}` with `runs-on: ubuntu-latest` left all forty-three tests green
# while collapsing the OS axis to one value: nine cells still ran, all of them on Linux, and the
# cross-cell determinism 16-roadmap.md:340 dates to P2 was no longer being tested at all.
# Replacing `UV_PYTHON: ${{ matrix.py }}` with `UV_PYTHON: "3.11"` did the same to the other
# axis. A declared axis nothing reads is a nine-name label on a one-cell job.
#
# Counting `${{ matrix.<axis> }}` occurrences would not close it: the job's `name:` interpolates
# both axes for the check-run title, so each axis survives a collapse with one reference intact.
# Only the semantic site can be asserted, so the semantic site is written down. `os` is real
# because `runs-on` reads it -- that is the definition of an OS axis on GitHub Actions. `py` is
# real because `UV_PYTHON` reads it, `uv python install "$UV_PYTHON"` acts on it, and section
# 6.6's cache key is keyed on it.
MATRIX_AXIS_CONSUMERS: dict[str, str] = {
    "os": "runs-on: ${{ matrix.os }}",
    "py": "UV_PYTHON: ${{ matrix.py }}",
}

# SECTION 6.6'S PER-PYTHON CACHE KEY, transcribed. 11-repo-layout.md:1715-1716 states the rule as
# an arithmetic consequence and not as a preference: "The nine `test` cells are 747 s of that,
# which is why they get their own key per Python version rather than sharing one", and :1701
# sizes the store at "nine `uv` keys (3 OS x 3 Python)". Dropping `py${{ matrix.py }}` from the
# key leaves nine cells racing to write one entry and eight of them restoring an environment
# built for another interpreter -- which is not a slow build, it is a wrong one.
TEST_CACHE_KEY = "uv-${{ runner.os }}-py${{ matrix.py }}-${{ hashFiles('uv.lock') }}"
TEST_CACHE_RESTORE_KEY = "uv-${{ runner.os }}-py${{ matrix.py }}-"

# THE COMMANDS THAT DO THE WORK, by the job that must run them.
#
# `test_every_named_runner_is_actually_invoked_in_the_job_its_row_names` closed this hole for the
# fourteen `[[gate]]` rows that name a `runner`, after a wave found that `run: echo "G3 passes"`
# kept the suite green. It closed it only for those rows, and the most expensive steps in this
# file are not among them: nothing in `tools/gates.toml` names `uv run pytest -q`, so the nine
# `test` cells -- the job 16-roadmap.md:340 makes P2's headline first-green -- could be replaced
# by an `echo` with every required check still passing. So could `G28`'s round trip, whose own
# step comment says the MECHANISM half is the half P2 landed and is therefore the half that must
# actually run. Same defect, one job to the left of where it was found.
CI_WORK_COMMANDS: dict[str, tuple[str, ...]] = {
    "test": ("uv sync --frozen --all-packages --group dev", "uv run pytest -q"),
    "gates": ("uv run pytest packages/omniweave-core/tests/unit/test_owdoc_roundtrip.py -q",),
    "build": ("uv build",),
}

# Number words, for reading a cell-count claim out of a comment written in prose.
COUNT_WORDS: dict[str, int] = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Adjectives that make the number after them an INCREMENT rather than a total. The matrix comment
# says "what made the extra six cells assert something rather than merely run", which is a true
# sentence about six of the nine and not a claim that the matrix has six. Without this the
# stale-comment check below would fail the correct comment, and a check that fails the correct
# artefact gets deleted by the next person rather than fixed.
INCREMENT_QUALIFIERS: frozenset[str] = frozenset(
    {"extra", "additional", "further", "more", "new", "other", "remaining", "six"}
)

_TOP_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):")
_JOB_KEY = re.compile(r"^  (?P<name>[a-z][a-z0-9_-]*):\s*(?:#.*)?$")
_STEP_NAME = re.compile(r"^\s{6,8}-?\s*name:\s*(?P<name>.+?)\s*$")
_USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)\s*(?P<rest>.*)$")
_RUN_START = re.compile(r"^\s*-?\s*run:\s*(?P<inline>.*)$")
_FLOW_LIST = re.compile(r"\[(?P<body>[^]]*)\]")
_SHA40 = re.compile(r"@[0-9a-f]{40}$")
_TODO_PIN = re.compile(r"TODO:\s*pin")
# `for path in a b c` and `[ -f a ]` / `[ -e a ]` / `[ -d a ]`, the two shapes the tripwire steps
# use to name a path. The path class excludes `$`, a quote and `]` so that `[ -e "$path" ]` -- the
# loop's own body, which names no literal -- contributes nothing.
_SHELL_FOR_LIST = re.compile(r"^\s*for\s+\w+\s+in\s+(?P<items>.+?)\s*$")
_SHELL_FILE_TEST = re.compile(r"\[\s+-[a-z]+\s+(?P<path>[^\s\]\"$']+)\s+\]")
_CELL_COUNT_CLAIM = re.compile(
    r"(?:(?P<qualifier>[A-Za-z]+)\s+)?(?P<count>\d+|" + "|".join(COUNT_WORDS) + r")[- ]cells?\b",
    re.IGNORECASE,
)


def _repo_root() -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "tools").is_dir():
            return candidate
    message = f"no omniweave workspace root above {Path(__file__).resolve()}"
    raise RuntimeError(message)


REPO = _repo_root()


@dataclass(frozen=True, slots=True)
class Workflow:
    """One workflow file, seen as indented lines. See the module docstring for the limits."""

    name: str
    text: str

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(self.text.splitlines())

    @staticmethod
    def is_comment(line: str) -> bool:
        return line.lstrip().startswith("#")

    def code_lines(self) -> tuple[str, ...]:
        """Every line that is not wholly a comment -- YAML comment or `run:`-body shell comment.

        Both kinds are stripped by the same rule on purpose: a `#`-led line inside a `run: |` block
        is a shell comment, and prose in either place must not be able to trip an assertion about
        what the workflow *does*.
        """
        return tuple(line for line in self.lines if line.strip() and not self.is_comment(line))

    def top_level_keys(self) -> tuple[str, ...]:
        return tuple(
            match.group("key")
            for line in self.lines
            if not self.is_comment(line) and (match := _TOP_KEY.match(line))
        )

    def job_blocks(self) -> dict[str, tuple[str, ...]]:
        """Job name -> its lines, for the block under the top-level `jobs:` key.

        A job starts at a two-space key and ends at the next two-space key or at the next
        column-zero key. Nothing inside a step reaches column two except a comment, which
        `_JOB_KEY` cannot match because it requires a lowercase letter first.
        """
        blocks: dict[str, list[str]] = {}
        current: str | None = None
        in_jobs = False
        for line in self.lines:
            if self.is_comment(line):
                continue
            top = _TOP_KEY.match(line)
            if top is not None:
                in_jobs = top.group("key") == "jobs"
                current = None
                continue
            if not in_jobs:
                continue
            job = _JOB_KEY.match(line)
            if job is not None:
                current = job.group("name")
                blocks[current] = []
                continue
            if current is not None:
                blocks[current].append(line)
        return {name: tuple(body) for name, body in blocks.items()}

    def step_names(self, job: str) -> tuple[str, ...]:
        """The `name:` values of one job's steps, quotes stripped."""
        found: list[str] = []
        for line in self.job_blocks()[job]:
            if self.is_comment(line):
                continue
            match = _STEP_NAME.match(line)
            if match is not None:
                found.append(match.group("name").strip().strip('"'))
        return tuple(found)

    def run_bodies(self, job: str) -> str:
        """One job's `run:` text, as one blob. Enough for "is this gate invoked here".

        A block scalar's body is indented deeper than its key, so "everything from a `run:` to the
        next line at the key's own indentation or shallower" is the body. Shell comments inside it
        are dropped, so a comment naming a gate does not read as an invocation.
        """
        body: list[str] = []
        depth: int | None = None
        for line in self.job_blocks()[job]:
            if depth is not None:
                if line.strip() and (len(line) - len(line.lstrip())) <= depth:
                    depth = None
                elif not self.is_comment(line):
                    body.append(line)
                    continue
            match = _RUN_START.match(line)
            if match is not None and not self.is_comment(line):
                body.append(match.group("inline"))
                depth = len(line) - len(line.lstrip())
        return "\n".join(body)

    def step_run_bodies(self, job: str) -> dict[str, str]:
        """Step name -> that ONE step's `run:` text, for a job whose steps all carry a `name:`.

        `run_bodies()` welds a whole job into one blob, which is the right instrument for "is this
        gate invoked in this job" and the wrong one for "what does THIS step test". A tripwire is a
        property of its own step: a path tested in the `G28` step and a path tested three steps
        later are different claims, and a job-wide blob cannot tell them apart. Steps with no
        `name:` are dropped rather than merged into their predecessor, because attributing an
        anonymous step's shell to the named step above it is exactly the misattribution this
        exists to avoid.
        """
        bodies: dict[str, list[str]] = {}
        current: str | None = None
        depth: int | None = None
        for line in self.job_blocks()[job]:
            if depth is not None:
                if line.strip() and (len(line) - len(line.lstrip())) <= depth:
                    depth = None
                else:
                    if current is not None:
                        bodies[current].append(line)
                    continue
            name = _STEP_NAME.match(line)
            if name is not None:
                current = name.group("name").strip().strip('"')
                bodies.setdefault(current, [])
                continue
            if re.match(r"^\s{6}- ", line):
                # A new step that carries no `name:`; its shell belongs to nobody.
                current = None
            run = _RUN_START.match(line)
            if run is not None:
                if current is not None:
                    bodies[current].append(run.group("inline"))
                depth = len(line) - len(line.lstrip())
        return {name: "\n".join(body) for name, body in bodies.items()}

    def uses(self) -> tuple[tuple[int, str, str], ...]:
        """Every `uses:` as (line number, ref, the marker text that may license it).

        The marker text is the rest of the `uses:` line plus the contiguous comment lines directly
        above it, because one action's `TODO: pin` cannot fit on its own line under the 100-column
        rule and sits in the comment above instead.
        """
        found: list[tuple[int, str, str]] = []
        for index, line in enumerate(self.lines):
            if self.is_comment(line):
                continue
            match = _USES.match(line)
            if match is None:
                continue
            context = [match.group("rest")]
            back = index - 1
            while back >= 0 and self.is_comment(self.lines[back]):
                context.append(self.lines[back])
                back -= 1
            found.append((index + 1, match.group("ref"), " ".join(context)))
        return tuple(found)


def _load(name: str) -> Workflow:
    path = REPO / WORKFLOW_DIR / name
    return Workflow(name=name, text=path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def register() -> dict[str, object]:
    """`tools/gates.toml`, the closed vocabulary of job names and the source of the PR set."""
    return tomllib.loads((REPO / REGISTER).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ci() -> Workflow:
    return _load("ci.yml")


@pytest.fixture(scope="module")
def release() -> Workflow:
    return _load("release.yml")


# ---------------------------------------------------------------------------
# The guard on the parser itself
# ---------------------------------------------------------------------------


def test_the_parser_found_what_it_should_have_found(ci: Workflow, release: Workflow) -> None:
    """Section 6.8's rule for a gate that discovers its own inputs, applied to this file.

    Without this, a regex that silently matched nothing would make every assertion below vacuous --
    an empty job map trivially satisfies "every job is in the register", and an empty `uses:` list
    trivially satisfies "every action is pinned".
    """
    jobs = ci.job_blocks()
    assert len(jobs) == 11, sorted(jobs)
    assert set(ci.top_level_keys()) >= {"name", "on", "concurrency", "permissions", "jobs"}
    assert len(release.job_blocks()) == 6, sorted(release.job_blocks())
    assert len(ci.uses()) >= 15, ci.uses()
    assert len(release.uses()) >= 10, release.uses()
    # Every job has at least one step name and at least one job has a multi-line `run:` body.
    for job in jobs:
        assert ci.step_names(job) or ci.run_bodies(job), job
    assert "gate_core_pure.py" in ci.run_bodies("gates")
    assert "uv build" in ci.run_bodies("build")


# ---------------------------------------------------------------------------
# Section 6.1 -- two files, and one definition of passing
# ---------------------------------------------------------------------------


def test_the_workflow_directory_holds_exactly_two_files() -> None:
    """Section 6.1, and the mechanism behind section 1.1 fact 1's un-renameable filename."""
    directory = REPO / WORKFLOW_DIR
    assert directory.is_dir(), f"{WORKFLOW_DIR} is missing"
    found = sorted(path.name for path in directory.iterdir() if path.is_file())
    assert found == ["ci.yml", "release.yml"], found
    assert not [path for path in directory.iterdir() if path.is_dir()], "no subdirectories"


def test_release_calls_ci_through_workflow_call(ci: Workflow, release: Workflow) -> None:
    """ "THE RELEASE GATE IS CI. One definition." (section 7.3's own comment on the line.)"""
    refs = [ref for _, ref, _ in release.uses()]
    assert "./.github/workflows/ci.yml" in refs, refs
    # The call is only legal if the callee declares the trigger, and the trigger is what section
    # 6.1 says makes the two files unable to diverge.
    assert any(re.match(r"^\s+workflow_call:\s*$", line) for line in ci.code_lines())


def test_no_publisher_lives_inside_the_reusable_workflow(ci: Workflow) -> None:
    """Section 7.3 rule 6, which is why `publish` is top-level in `release.yml`.

    Trusted Publishing matches the OIDC `workflow_ref` claim and that claim names the CALLER, so a
    `pypa/gh-action-pypi-publish` step inside a `workflow_call`-invoked workflow gets
    `invalid-publisher`. Asserted over `uses:` refs, not over the file text: `ci.yml`'s header
    explains this rule and names the action while doing so.
    """
    assert not [ref for _, ref, _ in ci.uses() if ref.startswith("pypa/gh-action-pypi-publish")]


def test_release_has_no_concurrency_and_ci_has_section_6_3s(
    ci: Workflow, release: Workflow
) -> None:
    """Section 6.3: concurrency "is set on `ci.yml` and **not** on `release.yml`"."""
    assert "concurrency" in ci.top_level_keys()
    assert "concurrency" not in release.top_level_keys()
    body = "\n".join(ci.code_lines())
    assert 'group: "ci-${{ github.ref }}"' in body
    assert "cancel-in-progress: true" in body


def test_both_files_start_from_no_permissions(ci: Workflow, release: Workflow) -> None:
    """Section 7.3's first line, "minimal at the top level", applied to both.

    A job that needs a scope re-grants it; a new job therefore starts with nothing rather than with
    whatever the caller's token happened to carry.
    """
    for workflow in (ci, release):
        assert "permissions: {}" in workflow.code_lines(), workflow.name


# ---------------------------------------------------------------------------
# Section 6.2 -- the job graph, and the register's closed job vocabulary
# ---------------------------------------------------------------------------


def test_cis_jobs_are_exactly_the_registers_job_names(
    ci: Workflow, register: dict[str, object]
) -> None:
    """Both directions. `tools/gates.toml`'s `job_name` is section 6.2's `needs` list plus `ci-ok`,
    and a `[[gate]]` row may name nothing else -- so a job in one and not the other is a row that
    cannot be invoked or a job no row can reach.
    """
    declared = {str(name) for name in register["job_name"]}  # type: ignore[union-attr]
    assert set(ci.job_blocks()) == declared, {
        "only in ci.yml": sorted(set(ci.job_blocks()) - declared),
        "only in the register": sorted(declared - set(ci.job_blocks())),
    }


def test_ci_ok_needs_every_job_but_itself(ci: Workflow) -> None:
    """Section 6.2: `ci-ok` is "the one required status check" and reads `needs`, not `success()`.

    "`if: always()`" is half of it and the `needs` list is the other half: a job absent from `needs`
    is a job whose failure `ci-ok` cannot see, and a required check that cannot see a failure is
    the defect the single-required-check design exists to prevent.
    """
    block = "\n".join(ci.job_blocks()["ci-ok"])
    match = _FLOW_LIST.search(block)
    assert match is not None, block
    needs = tuple(item.strip() for item in match.group("body").split(",") if item.strip())
    assert needs == CI_OK_NEEDS, needs
    assert "if: always()" in block


def test_toolchains_is_the_only_job_that_may_not_run(ci: Workflow) -> None:
    """Section 6.2: "`toolchains` is conditional on the paths a PR touches" and is the only job
    `ci-ok` may see as `skipped`. A second conditional job would silently widen `ci-ok`'s
    allowlist, which the register's `ci-ok.skips_declared` row calls out by name.

    TWO JOBS CARRY AN `if:` AND ONLY ONE OF THEM IS CONDITIONAL. `ci-ok`'s is `always()`, which is
    the opposite of a condition: section 6.2 requires it, because "`if: always()` also fires on
    cancellation" is exactly how that job gets to see a cancelled matrix and call it a failure. So
    the assertion is on the expressions and not on the presence of the key.
    """
    conditions = {
        job: match.group("expr").strip()
        for job, body in ci.job_blocks().items()
        for line in body
        if (match := re.match(r"^    if:\s*(?P<expr>.+?)\s*$", line))
    }
    assert set(conditions) == {"toolchains", "ci-ok"}, conditions
    assert conditions["ci-ok"] == "always()", conditions["ci-ok"]
    assert "toolchains" in conditions["toolchains"], conditions["toolchains"]


def test_every_job_carries_a_timeout(ci: Workflow) -> None:
    """Section 6.6: "Each job carries `timeout-minutes` at **twice** its stated budget"."""
    missing = [
        job
        for job, body in ci.job_blocks().items()
        if not any(line.strip().startswith("timeout-minutes:") for line in body)
    ]
    assert not missing, missing
    parity = "\n".join(ci.job_blocks()["parity"])
    assert f"timeout-minutes: {PARITY_TIMEOUT_MINUTES}" in parity


def test_fetch_depth_zero_is_exactly_the_registers_history_readers(
    ci: Workflow, register: dict[str, object]
) -> None:
    """Section 6.2: "Checkout depth is part of the gate contract, not a performance knob."

    Three gates read history -- G13, G16 and G27 -- and the register carries `fetch_depth = 0` on
    exactly those rows. The jobs they name are therefore the jobs that may check out at depth 0,
    and "Every other job uses `fetch-depth: 1`". Getting this wrong "produces `fatal: no such ref`
    in a gate whose failure message is about error codes, which is worse than either."
    """
    rows = register["gate"]
    assert isinstance(rows, list)
    expected = {job for row in rows if row.get("fetch_depth") == 0 for job in row["jobs"]}
    assert expected == {"gates", "conform"}, expected
    deep = {
        job
        for job, body in ci.job_blocks().items()
        if any("fetch-depth: 0" in line for line in body)
    }
    assert deep == expected, {"in ci.yml": sorted(deep), "in the register": sorted(expected)}


# ---------------------------------------------------------------------------
# Section 6.4 -- every PR-blocking row is invoked, and G22 is not
# ---------------------------------------------------------------------------


def _gate_rows(register: dict[str, object]) -> tuple[dict[str, object], ...]:
    rows = register["gate"]
    assert isinstance(rows, list)
    return tuple(rows)


def test_every_pr_blocking_row_is_invoked_in_the_job_its_row_names(
    ci: Workflow, register: dict[str, object]
) -> None:
    """Section 6.4: twenty-eight of the twenty-nine "have a PR job and therefore block a merge".

    The register also carries `G30`, an append section 6.4 does not yet render, so the count is
    read off the register rather than transcribed. The assertion is per job, not per file: a `G4`
    step sitting in `build` would satisfy a file-wide search and would run without the `gates`
    job's budget, its checkout depth or its 180 s ceiling.
    """
    missing: list[str] = []
    for row in _gate_rows(register):
        if not row["pr"]:
            continue
        identifier = str(row["id"])
        for job in row["jobs"]:  # type: ignore[union-attr]
            names = " | ".join(ci.step_names(str(job)))
            if not re.search(rf"\b{identifier}\b", names):
                missing.append(f"{identifier} in {job}")
    assert not missing, missing


def test_g22_is_invoked_nowhere(ci: Workflow, register: dict[str, object]) -> None:
    """Section 6.4: `G22` "is a nightly 100k-roster scale run with no PR cell, so it blocks the
    *release* (checklist step 11) and is deliberately absent from `ci-ok`'s required set."

    ASSERTED OVER STEP NAMES AND `run:` BODIES, NOT OVER THE FILE TEXT. `ci.yml`'s header states
    that `G22` is deliberately absent and quotes section 6.4 while doing so; a substring search
    would find the explanation and fail the file for explaining itself. The invocation is what must
    not exist, so the invocation is what is checked -- along with the runner the register names for
    it, which is the other way the row could arrive here by accident.
    """
    absent = [row for row in _gate_rows(register) if not row["pr"]]
    assert [str(row["id"]) for row in absent] == ["G22"], absent
    for job in ci.job_blocks():
        names = " | ".join(ci.step_names(job))
        assert not re.search(r"\bG22\b", names), f"G22 named in a {job} step"
        assert not re.search(r"\bG22\b", ci.run_bodies(job)), f"G22 invoked in {job}"
    assert "gate_scale.py" not in ci.text


def test_every_job_assertions_job_is_a_job_and_its_name_is_written_down(
    ci: Workflow, register: dict[str, object]
) -> None:
    """The nine `[[job_assertion]]` rows of section 6.4's second table.

    Two different strengths on purpose. The `job` must be a real job -- that is structural, and a
    row claiming `build.` while running in `gates` is exactly what the register's own name rule
    exists to stop. The `name` only has to appear somewhere in `ci.yml`, because three of the nine
    (`build.reproducible`, `toolchains.reproducible`, `ci-ok.skips_declared`) are properties of a
    job rather than a step, and section 6.4 numbers none of them.
    """
    rows = register["job_assertion"]
    assert isinstance(rows, list)
    assert len(rows) == 9, len(rows)
    jobs = set(ci.job_blocks())
    for row in rows:
        assert str(row["job"]) in jobs, row["name"]
        assert str(row["name"]) in ci.text, row["name"]


# ---------------------------------------------------------------------------
# Section 6.8 -- nothing may pass for the wrong reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workflow_name", ["ci.yml", "release.yml"])
def test_no_step_can_pass_for_the_wrong_reason(workflow_name: str) -> None:
    """Section 6.8: "There is no `--warn-only` anywhere."

    `continue-on-error: true` is the Actions spelling of it, `|| true` is the shell spelling, and
    `--warn-only` is the flag itself. Checked over non-comment lines only, because `ci.yml`'s
    header names all three while promising not to use them.
    """
    workflow = _load(workflow_name)
    for line in workflow.code_lines():
        assert not re.search(r"continue-on-error:\s*true", line), line
        assert "|| true" not in line, line
        assert "--warn-only" not in line, line


# ---------------------------------------------------------------------------
# Section 7.3 rule 2 -- every action pinned, or visibly not
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workflow_name", ["ci.yml", "release.yml"])
def test_every_uses_is_local_pinned_or_visibly_unpinned(workflow_name: str) -> None:
    """Section 7.3 rule 2: "Every third-party action is pinned by full 40-hex commit SHA with the
    version in a trailing comment. A tag is mutable."

    The plan prints `@<40-hex>` for every action it names and no actual SHA anywhere in nineteen
    documents, so nothing here can be pinned without fabricating forty hex characters -- which
    would be a supply-chain claim that is false, and strictly worse than a visibly unpinned ref.
    The third arm of this assertion is therefore a `TODO: pin` marker, and this test is what stops
    the marker being quietly dropped along with the pin it stands for.
    """
    workflow = _load(workflow_name)
    unaccounted = [
        (number, ref)
        for number, ref, context in workflow.uses()
        if not ref.startswith("./")
        and _SHA40.search(ref) is None
        and _TODO_PIN.search(context) is None
    ]
    assert not unaccounted, unaccounted


def test_the_slsa_generator_is_referenced_at_the_version_section_7_4_verified(
    release: Workflow,
) -> None:
    """Section 7.4 rule 2 is the reason this reference is singled out.

    The generator "uploads `provenance.intoto.jsonl` with a hardcoded `retention-days: 5` and
    exposes no caller input -- verified by local-deep-research at their pinned v2.1.0 commit. So
    the **effective approval window is 5 days**, not 7." The window is a number `CONTRIBUTING.md`
    and checklist step 14 both state, and it is a property of *this version*: a bump can move it,
    so the version may not drift silently.
    """
    generator = [ref for _, ref, _ in release.uses() if "slsa-github-generator" in ref]
    assert len(generator) == 1, generator
    assert generator[0].endswith("@v2.1.0") or _SHA40.search(generator[0]), generator[0]
    assert "generator_generic_slsa3.yml" in generator[0]


def test_the_pre_approval_uploads_never_take_the_default_retention(release: Workflow) -> None:
    """Section 7.4 rule 1, and it is "the scar with the largest blast radius in the mined
    collection": at `retention-days: 1` an artefact expired 24 h after the build while the approval
    arrived ~30 h later, and the release was unrecoverable in place *because the signed SBOM bytes
    named as subjects in the SLSA provenance no longer existed*.
    """
    uploads = [ref for _, ref, _ in release.uses() if ref.startswith("actions/upload-artifact@")]
    assert uploads, "release.yml uploads nothing"
    retentions = [
        line.strip() for line in release.code_lines() if line.strip().startswith("retention-days:")
    ]
    assert retentions, "no retention-days is set anywhere"
    assert all(value == "retention-days: 7" for value in retentions), retentions
    assert len(retentions) == len(uploads), (retentions, uploads)


def test_cosign_is_pinned_to_the_version_that_signs_and_verifies(release: Workflow) -> None:
    """Section 7.3 rule 1: `cosign` is pinned to `v2.6.3`, not to the installer's default.

    "installer v4.1.2 ships cosign v3 by default, and v3's `new-bundle-format` changes the
    signature/attestation on-wire format so that a v3 producer and a v2 consumer cannot
    interoperate." The version that signs and the version in `docs/verify.md`'s recipe move
    together, in one commit.
    """
    body = "\n".join(release.code_lines())
    pinned = 'cosign-release: "v2.6.3"' in body or "cosign-release: 'v2.6.3'" in body
    assert pinned, "release.yml does not pin cosign-release to v2.6.3 (section 7.3 rule 1)"
    # Rule 3: signed AND verified in the same job, because "cosign signs above but never verifies,
    # so a sigstore/cert-chain regression would silently break downstream verification".
    sbom = "\n".join(release.job_blocks()["sbom-sign"])
    assert "cosign sign-blob" in sbom
    assert "cosign verify-blob" in sbom


def test_publish_is_the_only_job_behind_the_approval_pause(release: Workflow) -> None:
    """Section 7.3 rule 7: "`environment: release` gates exactly the jobs that declare it".

    An environment is per-job, not per-run. The GHCR promote job would be the second one to declare
    it and does not exist yet (section 7.1's container row, 16-roadmap.md W10.9), so at release 1
    there is exactly one -- and it is the job that calls `pypa/gh-action-pypi-publish`, which is
    what makes the pause unable to move `github.sha`.
    """
    gated = [
        job
        for job, body in release.job_blocks().items()
        if any(line.strip() == "environment: release" for line in body)
    ]
    assert gated == ["publish"], gated
    publish = "\n".join(release.job_blocks()["publish"])
    assert publish.count("pypa/gh-action-pypi-publish@") == 4, publish.count("pypa/")


# ---------------------------------------------------------------------------
# 16-roadmap.md section 4 and :340 -- the matrix, and the phase that landed each axis value
# ---------------------------------------------------------------------------

# The nine cells, written out rather than computed from the two axes. A product of two parsed
# tuples would agree with itself whatever either tuple said; nine names cannot.
NINE_CELLS: frozenset[str] = frozenset(
    {
        "ubuntu-latest py3.11",
        "ubuntu-latest py3.12",
        "ubuntu-latest py3.13",
        "macos-latest py3.11",
        "macos-latest py3.12",
        "macos-latest py3.13",
        "windows-latest py3.11",
        "windows-latest py3.12",
        "windows-latest py3.13",
    }
)


def _matrix_axes(ci: Workflow) -> dict[str, tuple[str, ...]]:
    """The `test` job's `os` and `py` flow lists, comments excluded."""
    axes: dict[str, tuple[str, ...]] = {}
    for line in ci.job_blocks()["test"]:
        if ci.is_comment(line):
            continue
        match = re.match(r"^\s*(?P<axis>os|py):\s*(?P<value>\[.*\])\s*$", line)
        if match is not None:
            body = _FLOW_LIST.search(match.group("value"))
            assert body is not None, line
            axes[match.group("axis")] = tuple(
                item.strip().strip('"') for item in body.group("body").split(",") if item.strip()
            )
    return axes


def _matrix_comment(ci: Workflow) -> str:
    """The contiguous comment block directly above the `os:` axis line.

    Scoped to that block rather than to the whole file on purpose. The assertion this feeds used
    to read `ci.text` and look for "3.12" and "3.13", which was a real check while the matrix said
    `py: ["3.11"]` -- the only place those strings could appear was a comment naming the future.
    The moment P2 widened the axis the same search started matching the axis line itself, and the
    test would have gone on passing while asserting nothing. Reading the comment alone is what
    keeps it a statement about the prose.
    """
    lines = ci.lines
    axis = [index for index, line in enumerate(lines) if re.match(r"^\s*os:\s*\[", line)]
    assert len(axis) == 1, f"expected one os axis line, found {axis}"
    start = axis[0]
    while start > 0 and Workflow.is_comment(lines[start - 1]):
        start -= 1
    assert start < axis[0], "the matrix carries no comment above its os axis"
    return "\n".join(lines[start : axis[0]])


def _unwrapped(comment: str) -> str:
    """A comment block as one flat sentence: `#` markers gone, newlines gone, backticks gone.

    Two assertions read the matrix comment as prose and both need this. The sentences involved
    are longer than the 100-column limit and therefore wrap across comment lines, so a substring
    search over the raw block fails on a correct transcription. Backticks go too: the plan writes
    ``test`` in markdown and a workflow comment carries none.
    """
    return " ".join(
        " ".join(line.lstrip().lstrip("#").split()) for line in comment.splitlines()
    ).replace("`", "")


def test_the_matrix_is_nine_cells_landed_by_p2(ci: Workflow) -> None:
    """Section 6.2's cross product, in full: `{ubuntu, macos, windows} x {3.11, 3.12, 3.13}`.

    16-roadmap.md:340 is the row that dates it -- `test` (9 cells) is first green in P2, "cross-
    cell determinism is meaningless before `canonical()` and the DDL exist" -- and P2's W2.1 model
    plus W2.3/W2.4 store are what made the six new cells assert something rather than merely run.
    The axis table this is checked against is 11-repo-layout.md:1464-1471.

    ASSERTED BY NAME, and that is not decoration. The predecessor of this test asserted
    `len(os) * len(py) == 3`, which is a shape and not a value: it would have been just as green
    against `{ubuntu} x {3.11, 3.12, 3.13}`, three cells of entirely the wrong kind. So the nine
    cells are spelled out in `NINE_CELLS`, the product is compared against that set, and the count
    is compared against `MATRIX_CELLS`, the literal 9 section 6.2's job graph prints.
    """
    axes = _matrix_axes(ci)
    assert axes.get("os") == MATRIX_OS, axes
    assert axes.get("py") == MATRIX_PYTHON, axes
    assert axes["py"] == tuple(PYTHON_AXIS_BY_PHASE), (
        "the shipped Python axis and the by-phase allow-list disagree"
    )
    cells = {f"{system} py{python}" for system in axes["os"] for python in axes["py"]}
    assert cells == NINE_CELLS, sorted(cells ^ NINE_CELLS)
    assert len(cells) == MATRIX_CELLS, sorted(cells)


def test_every_python_axis_value_names_the_phase_that_landed_it() -> None:
    """`PYTHON_AXIS_BY_PHASE` carries no row that is a placeholder, in either direction.

    Without this the allow-list is a way to switch the matrix assertion off: a row added here with
    no phase behind it would license an axis value while proving nothing, and a value dropped from
    the workflow but left here would keep the tuple looking right after a revert. It is the
    counterpart of `test_the_filled_homes_are_really_filled` in `test_core_eager_surface.py`,
    written for the same reason -- an allow-list nothing audits is a relaxation with extra steps.

    A row's phase must be one that has LANDED. "P3" here would be an axis value shipped ahead of
    the work that justifies it, which is what 16-roadmap.md:340's "why not earlier" column exists
    to refuse: a first-green claim is only worth anything with that column filled in. And every
    row must name 16-roadmap.md, because a phase assertion with no locus is an opinion.
    """
    assert tuple(PYTHON_AXIS_BY_PHASE) == MATRIX_PYTHON, tuple(PYTHON_AXIS_BY_PHASE)
    for value, phase in PYTHON_AXIS_BY_PHASE.items():
        assert phase.startswith(LANDED_PHASES), f"{value} is landed by unlanded phase {phase!r}"
        assert "16-roadmap.md" in phase, f"{value}'s row names no locus: {phase!r}"


def test_the_matrix_comment_records_that_p2_landed_the_nine_cells(ci: Workflow) -> None:
    """The brief the matrix comment has to meet, now that the expansion has happened.

    Before P2 the brief was "name the rows that land later". A comment that still said that would
    now be an instruction someone has already carried out, sitting next to the result and reading
    as though it were outstanding -- which is how a reader concludes the file is mid-edit. So the
    brief inverts: record that P2 landed it, and cite the row that says P2 is where it lands.

    The `At P2 this becomes` assertion is the negative half and is deliberately literal. It is the
    exact phrase the P1 comment used, and its absence is the only mechanical evidence that the
    comment was rewritten rather than merely appended to.
    """
    comment = _matrix_comment(ci)
    assert "P2" in comment
    assert "16-roadmap.md:340" in comment, "the first-green row is not cited"
    assert "11-repo-layout.md:1464-1471" in comment, "the axis table is not cited"
    assert "9 cells" in comment
    assert "At P2 this becomes" not in comment, (
        "the P1 instruction is still in the comment after being carried out"
    )
    # THE TWO ARMS BELOW WERE ADDED BY MUTATION, and the mutation that forced them is the reason
    # the arm above is not enough. `At P2 this becomes` is one spelling of a stale comment. The
    # paraphrase
    #
    #     THE MATRIX IS THREE CELLS FOR NOW ... P2 will widen the py axis to 3.11, 3.12, 3.13
    #
    # kept every citation this test asks for, avoided that one literal, sat directly above a
    # nine-cell axis, and left the whole file green -- which is precisely the "instruction someone
    # has already carried out, sitting next to the result" this test's brief says it refuses. A
    # negative assertion on one string is a check on a habit, not on a claim.
    #
    # So the first arm is POSITIVE and states the shipped product, built from this module's own
    # pinned literals rather than from anything read out of `ci.yml` -- both sides of a derived
    # comparison would come out of the workflow and would agree with each other whatever the
    # workflow said.
    unwrapped = _unwrapped(comment)
    product = f"{len(MATRIX_OS)} x {len(MATRIX_PYTHON)} = {MATRIX_CELLS} cells"
    assert product in unwrapped, (
        f"the comment does not state the shipped product {product!r}, so it is not a record of "
        f"what landed"
    )
    # The second arm generalises the negative: no count claim in the comment may name a total
    # other than the shipped one. "the extra six cells" is a claim about an increment and is
    # exempted by `INCREMENT_QUALIFIERS`, which is why the exemption is a named table and not a
    # special case buried here.
    stale = [
        match.group(0)
        for match in _CELL_COUNT_CLAIM.finditer(unwrapped)
        if (match.group("qualifier") or "").lower() not in INCREMENT_QUALIFIERS
        and COUNT_WORDS.get(match.group("count").lower(), -1) != MATRIX_CELLS
        and match.group("count") != str(MATRIX_CELLS)
    ]
    assert not stale, (
        f"the comment claims the matrix has a cell count other than {MATRIX_CELLS}: {stale}. A "
        f"comment describing a smaller matrix than the one below it reads as a pending edit."
    )


def test_the_p1_non_goal_sentence_is_transcribed_at_the_matrix(ci: Workflow) -> None:
    """The workflow quotes 16-roadmap.md section 4's non-goal where the matrix departs from it.

    THIS TEST EXISTS BECAUSE ITS SIBLING SKIPS.
    `test_the_p1_matrix_non_goal_is_still_what_the_roadmap_says` reads `_plan/`, and `_plan/` is
    `.gitignore`d, so on a CI checkout it is absent and that test skips -- which leaves the one
    sentence the nine-cell matrix has to be reconciled against unchecked in exactly the place the
    matrix runs. This half never skips: it asserts the transcription in `ci.yml` against a literal
    written here, and the plan-reading half then checks that literal against its source wherever
    the design tree exists.

    Compared against the comment UNWRAPPED -- `#` markers stripped and whitespace flattened --
    for the same reason the plan-reading half flattens the markdown: the sentence is longer than
    the 100-column limit and wraps across comment lines, so a raw substring search would fail on
    a correct transcription. Backticks are stripped too: the plan writes `` `test` `` and a
    workflow comment carries no markdown.
    """
    unwrapped = _unwrapped(_matrix_comment(ci))
    assert "No CI matrix beyond three OSes at 3.11" in unwrapped
    assert "the nine-cell test job arrives with P2's determinism work" in unwrapped


def test_the_matrix_does_not_stop_at_the_first_failing_cell(ci: Workflow) -> None:
    """Nine budgeted cells that stop at the first failure hide eight answers, and section 6.2
    budgets every cell.
    """
    assert "fail-fast: false" in "\n".join(ci.job_blocks()["test"])


# ---------------------------------------------------------------------------
# The "has not landed unwired" tripwires
# ---------------------------------------------------------------------------


def _job_region(workflow: Workflow, job: str) -> str:
    """One job's raw lines INCLUDING its comments, which `job_blocks()` drops by design.

    `job_blocks()` strips comments so that prose about a gate cannot be mistaken for the gate
    running -- the module docstring's "mentions are not definition sites" rule, and it is the
    right default. Three assertions below need the opposite: they are about what a step SAYS,
    because the thing being asserted is that a reader who meets the substitute also meets the
    sentence explaining what it does not cover. Those use this, and each says so.
    """
    lines = workflow.lines
    start = next(index for index, line in enumerate(lines) if line.rstrip() == f"  {job}:")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.lstrip().startswith("#") and not line.startswith("   "):
            end = index
            break
    return "\n".join(lines[start:end])


def test_no_tripwire_is_already_firing_on_this_checkout() -> None:
    """A tripwire whose path exists is a `gates` job that is red right now, for a reason no one
    reading the PR would connect to their change.

    This is the test P2 needed and did not have. `fixtures/gen/gen_5000p_pdf.py` landed under
    13-quality.md:586-589, `fixtures/` therefore existed, and G28's bare-directory condition would
    have failed every PR from that commit on -- while the round trip it guards was passing and the
    corpus it waits for had not moved. Nothing in the tree could see it, because the condition only
    runs on a GitHub runner.

    The assertion is deliberately over the FILESYSTEM and not over `ci.yml`: it is the same
    question the runner asks, asked here. A path that legitimately lands takes the tripwire's own
    instruction -- wire the step -- and then comes out of `CI_TRIPWIRE_PATHS`, which is a
    deliberate act with a step to write attached, not a tuple edit.
    """
    firing = {
        step: [path for path in paths if (REPO / path).exists()]
        for step, paths in CI_TRIPWIRE_PATHS.items()
    }
    firing = {step: paths for step, paths in firing.items() if paths}
    assert not firing, (
        f"a ci.yml tripwire is already firing: {firing}. Wire the step it names, then remove the "
        f"path from CI_TRIPWIRE_PATHS -- do not widen the condition."
    )


def test_every_tripwire_path_is_written_in_the_workflow(ci: Workflow) -> None:
    """The anti-vacuity half. A table of paths nothing in `ci.yml` tests is a table that will go
    on passing after the step it describes has been deleted or rewritten.

    Both directions matter and only one of them is cheap. This is the cheap one: every path in
    `CI_TRIPWIRE_PATHS` appears in the `run:` body of the job that owns it -- the `run:` body and
    not the file text, because a path named only in a comment is a path nothing tests.
    """
    for step, paths in CI_TRIPWIRE_PATHS.items():
        job, _ = CI_TRIPWIRE_STEPS[step]
        body = ci.run_bodies(job)
        for path in paths:
            assert path in body, f"{step}: {path} is in the table and not in {job}'s run: bodies"


def test_the_four_tripwire_steps_are_still_the_four(ci: Workflow) -> None:
    """`CI_TRIPWIRE_STEPS`, against the step names `ci.yml` actually declares."""
    for step, (job, name) in CI_TRIPWIRE_STEPS.items():
        assert name in ci.step_names(job), f"{step}: no step named {name!r} in job {job}"
    assert CI_TRIPWIRE_STEPS.keys() == CI_TRIPWIRE_PATHS.keys()
    assert len(CI_TRIPWIRE_PATHS) == 4


def test_g28s_tripwire_does_not_fire_on_the_generator_directory(ci: Workflow) -> None:
    """The specific regression, pinned on both sides.

    `fixtures/gen/` is one of the seven members 11-repo-layout.md:383-384 lists under `fixtures/`
    and it is a GENERATOR, not the licensed corpus Q-G1 manifests. The old condition could not
    tell them apart. So: the shell must not test the bare directory again (asserted over the
    `run:` bodies, where a shell condition lives), and the step must say why the exemption is
    principled (asserted over the block including comments, because a condition that is merely
    narrower with no sentence saying why is one refactor away from being widened back).
    """
    body = ci.run_bodies("gates")
    assert "-d fixtures ]" not in body, "G28's tripwire is back to the whole fixtures/ tree"
    assert "G28 mechanism enforced" in body
    region = _job_region(ci, "gates")
    assert "13-quality.md:586-589 puts the deterministic generator" in region, (
        "the step no longer says why fixtures/gen/ is not the corpus"
    )


# ---------------------------------------------------------------------------
# P2's demo and measurement, wired as MECHANISM and not as a budget
# ---------------------------------------------------------------------------


def test_the_budget_register_linter_runs_in_the_gates_job(ci: Workflow) -> None:
    """Q-G15's static half, in the job 11-repo-layout.md:1613-1617 reserves for the static Q-G
    series.

    13-quality.md:354-355 names `tools/gate_budgets.py` and :368-371 gives it its second clause.
    Both read `eval/perf.toml` as a declaration file, which is what makes `gates` -- the job of
    linters that open no database -- the right home and `ow-bench-1` beside the point.
    """
    assert "uv run tools/gate_budgets.py" in ci.run_bodies("gates")
    assert any(name.startswith("Q-G15") for name in ci.step_names("gates")), (
        "no gates step is named for Q-G15"
    )
    assert "13-quality.md:354-371" in ci.run_bodies("gates"), (
        "the step does not name the plan lines its two clauses come from"
    )


def test_the_p2_measurement_is_wired_as_a_mechanism_and_never_as_a_budget_verdict(
    ci: Workflow,
) -> None:
    """12-performance.md:1966 makes `ow-bench-1` the only machine a Budget may live on, and every
    runner in this file is GitHub-hosted.

    So the two P2 steps must invoke the measurement WITHOUT `--gate`, which is the flag
    `tools/measure_store.py` puts its exit-1 behind. A `--gate` here would be a budget verdict
    rendered on the wrong machine -- the precise thing :1966 forbids -- and it would also be
    rendered at 64 pages, where the empty store's fixed floor is about half the number. The
    `--gate` assertion runs over the `run:` bodies for that reason: the comment above the step
    explains the flag, and a file-text search would match its own explanation.

    The step must also SAY which half it is. A mechanism smoke that does not label itself is
    indistinguishable from a budget check that happens to be passing, which is the confusion
    ruling D26 had to resolve for `rss.gen5000p_peak_bytes`.
    """
    body = ci.run_bodies("gates")
    assert "uv run python tools/measure_store.py --pages 64" in body
    assert "uv run python tools/p2_demo.py --pages 64" in body
    assert "uv run python fixtures/gen/gen_5000p_pdf.py --pages 64" in body
    assert "--gate" not in body, "a Budget verdict may only be rendered on ow-bench-1 (12:1966)"
    assert "NOT a budget verdict" in body
    assert "12-performance.md:1966" in body


def test_the_absence_of_a_nightly_job_is_recorded_where_the_smoke_replaces_it(
    ci: Workflow,
) -> None:
    """16-roadmap.md:343 puts `store.bytes_per_block` and `rss.gen5000p_peak_bytes` on a nightly
    `ow-bench-1` job that is first green in P2, and this repository has no such job.

    It cannot be a third workflow file -- 11-repo-layout.md:1360 fixes `.github/workflows/` at two
    and the `gates` job fails a third -- so it would have to be a `schedule:`-triggered job in
    this file with a `runs-on: ow-bench-1` label. Neither exists. That is a gap, and a PR-path
    smoke that quietly stood in for it would be the worst outcome available: it would look like
    the budget was being checked.

    So the test asserts the gap is stated at the place a reader meets the substitute, and it
    fails the day a `schedule:` trigger lands -- at which point section 6.5's three nightly cells
    are the thing to write and this test is the thing to rewrite.
    """
    region = _job_region(ci, "gates")
    assert "NO NIGHTLY WORKFLOW" in region
    assert "16-roadmap.md:343" in region
    assert "ow-bench-1" in region
    header = ci.text.split("\njobs:", 1)[0]
    assert "schedule:" not in header, (
        "a schedule: trigger landed -- wire section 6.5's nightly cells and rewrite this test"
    )
    # `code_lines()` and not `ci.text`: the comment above the P2 steps names the label it is
    # explaining the absence of, and a file-text search would match that explanation. Mentions
    # are not definition sites -- the module docstring's own rule, applied to a comment this
    # test's own subject wrote.
    assert "runs-on: ow-bench-1" not in "\n".join(ci.code_lines())


# ---------------------------------------------------------------------------
# House style -- 11-repo-layout.md sections 1.9 and 8.1
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workflow_name", ["ci.yml", "release.yml"])
def test_house_style(workflow_name: str) -> None:
    """LF, UTF-8, one trailing newline, 100 columns, ASCII values, no em dash.

    Section 1.9 is why the newline half is a gate rather than a preference: `.gitattributes`
    declares `* text=auto eol=lf` and "without it, G6 and G25 fail on the Windows cells". A CRLF
    workflow file is the same class of defect in the one directory `zizmor` reads.
    """
    raw = (REPO / WORKFLOW_DIR / workflow_name).read_bytes()
    text = raw.decode("utf-8")
    assert b"\r" not in raw, f"{workflow_name} carries CR bytes"
    assert text.endswith("\n") and not text.endswith("\n\n"), "exactly one trailing newline"
    assert raw.isascii(), f"{workflow_name} carries non-ASCII bytes"
    # Spelled as an escape rather than as the character, so this file is itself ASCII.
    assert "\u2014" not in text, "em dash: house style writes --"
    long_lines = [
        (number, line) for number, line in enumerate(text.splitlines(), start=1) if len(line) > 100
    ]
    assert not long_lines, long_lines


@pytest.mark.parametrize("workflow_name", ["ci.yml", "release.yml"])
def test_the_file_opens_with_the_locus_it_implements(workflow_name: str) -> None:
    """House style: every file names the plan section it implements in its first lines."""
    head = "\n".join(_load(workflow_name).lines[:6])
    assert workflow_name in head
    assert "11-repo-layout.md" in head


# ---------------------------------------------------------------------------
# Against the plan itself, where the plan prints the line
# ---------------------------------------------------------------------------


def _plan_text(document: str) -> str | None:
    """`_plan/` is `.gitignore`d, so a clean clone has no design tree -- and that is the ONLY
    thing this is allowed to be quiet about.

    THE HOLE THIS SHAPE USED TO HAVE, found by mutation. The predecessor was
    `return path.read_text() if path.is_file() else None`, which cannot distinguish "there is no
    design tree" from "the design tree is here and the document I name is not in it". Renaming
    `16-roadmap.md` -- which a renumbering wave does on purpose -- therefore turned three gates
    off and printed `_plan/ is .gitignore'd and absent from this checkout`, a sentence that was
    false at the moment it was printed. A skip whose stated reason did not happen is section
    6.8's "check that cannot yet fail" arriving through the back door.

    So the two cases are separated at the only place that can see both. No tree -> `None`, and
    the caller skips, which is honest on a CI checkout. A tree with a hole in it -> an assertion
    failure naming the document, because a plan document this file reads by name is a dependency
    and a missing dependency is a red test.
    """
    tree = REPO / "_plan"
    if not tree.is_dir():
        return None
    path = tree / document
    assert path.is_file(), (
        f"_plan/ exists but _plan/{document} does not. This test reads that document by name; a "
        f"rename is a red test here, not a skip -- update the name or say why it is gone."
    )
    return path.read_text(encoding="utf-8")


def test_a_missing_plan_document_is_a_failure_and_never_a_silent_skip() -> None:
    """The three tests below skip when there is no design tree. This is what stops that skip
    being available for any other reason.

    FOUND BY MUTATION, and the mutation is a thing that happens on purpose: renaming
    `_plan/16-roadmap.md`. The previous `_plan_text` returned `None` for BOTH "no `_plan/`" and
    "a `_plan/` with no such document", so a renumbering wave turned three gates off and the
    suite printed `_plan/ is .gitignore'd and absent from this checkout` -- a sentence that was
    false at the moment it was printed, next to a design tree that was sitting right there.
    Section 6.8 calls a check that cannot fail a defect; a check that switches itself off and
    reports a reason that did not happen is worse, because the report is what a reader trusts.

    So the two cases are separated in `_plan_text` and this asserts the separation from both
    sides: a document that is not there is an AssertionError naming it, and the three documents
    this file reads by name are all there. The second half is the anti-vacuity guard -- without
    it, renaming all three would satisfy the first half trivially.
    """
    if not (REPO / "_plan").is_dir():
        pytest.skip("_plan/ is .gitignore'd and absent from this checkout")
    with pytest.raises(AssertionError, match=re.escape("16-roadmap-no-such-document.md")):
        _plan_text("16-roadmap-no-such-document.md")
    for document in ("11-repo-layout.md", "16-roadmap.md"):
        assert _plan_text(document), document


def test_the_concurrency_line_is_the_one_section_6_3_prints() -> None:
    """Section 6.3 prints the whole setting inline, so it can be compared and not paraphrased."""
    plan = _plan_text("11-repo-layout.md")
    if plan is None:
        pytest.skip("_plan/ is .gitignore'd and absent from this checkout")
    printed = [line for line in plan.splitlines() if "concurrency: { group: ci-" in line]
    assert len(printed) == 1, printed
    assert "cancel-in-progress: true" in printed[0]
    assert "is set on `ci.yml`" in printed[0]
    ci = _load("ci.yml")
    body = "\n".join(ci.code_lines())
    assert 'group: "ci-${{ github.ref }}"' in body
    assert "cancel-in-progress: true" in body


def _plan_section(plan: str, heading_prefix: str) -> str:
    """One `## `-delimited section of a plan document, whitespace-flattened.

    Sectioning matters here and not in this file's other plan readers: the assertion below is
    about WHERE a sentence lives, not only that it exists, and a whole-document search cannot
    tell a P1 non-goal from a P2 one.
    """
    body: list[str] = []
    inside = False
    for line in plan.splitlines():
        if line.startswith("## "):
            inside = line.startswith(heading_prefix)
            continue
        if inside:
            body.append(line)
    return " ".join(" ".join(body).split())


def test_the_p1_matrix_non_goal_is_still_what_the_roadmap_says() -> None:
    """The P1 non-goal is still on the page, still scoped to P1, and still names P2 as its lift.

    WHY A TRUE NON-GOAL COEXISTS WITH A NINE-CELL MATRIX, because the two read as a contradiction
    otherwise and the next person will have to work this out from scratch if it is not written
    down. The sentence -- "No CI matrix beyond three OSes at 3.11 -- the nine-cell `test` job
    arrives with P2's determinism work" -- lives under 16-roadmap.md section 4's `#### Non-goals`,
    which is P1's section. A non-goal is a statement of what a NAMED PHASE will not contain, not a
    standing prohibition: it bounds P1's scope and expires with P1, exactly as "No
    `omniweave_core.model`" in the same list expired when W2.1 landed the model. Its second clause
    is not a caveat either, it is a forward reference: it names P2 as the phase that expands the
    matrix. So the nine cells are what the sentence PREDICTED, and P1 having ended is what makes
    both true at once.

    That is also why the test stays rather than being deleted with the three-cell matrix. What it
    guards is no longer "the matrix must not exceed three cells" -- P2 discharged that -- but the
    provenance of the nine: if the sentence were ever amended to drop "arrives with P2's
    determinism work", the matrix would lose the only line in the plan that dates its expansion,
    and 16-roadmap.md:340's "first green in P2" row would be the sole surviving witness. Hence the
    second assertion here, on :340 itself, which is the load-bearing citation now.

    THE SCOPING ASSERTION IS THE OTHER HALF. Reading the sentence out of the whole document would
    keep passing if someone moved it into section 5's non-goals, where it would forbid the matrix
    this file just asserted. Read out of section 4 alone, that move fails the test.
    """
    plan = _plan_text("16-roadmap.md")
    if plan is None:
        pytest.skip("_plan/ is .gitignore'd and absent from this checkout")
    # The sentence wraps in the markdown source, so it is compared against whitespace-flattened
    # text. The clause between the two halves is an em dash, which this ASCII file does not carry.
    p1_section = _plan_section(plan, "## 4. P1")
    assert p1_section, "16-roadmap.md has no section 4"
    assert "No CI matrix beyond three OSes at 3.11" in p1_section
    assert "the nine-cell `test` job arrives with P2's determinism work" in p1_section
    # Not in P2's, which is where the same words would be a prohibition on the matrix above.
    p2_section = _plan_section(plan, "## 5. P2")
    assert p2_section, "16-roadmap.md has no section 5"
    assert "No CI matrix beyond three OSes" not in p2_section, "the P1 non-goal moved into P2"
    # 16-roadmap.md:340: the row that makes nine cells P2's rather than an unbudgeted widening.
    flat = " ".join(plan.split())
    assert "| `test` (9 cells) | P2 |" in flat, "the first-green-in-P2 row is not where it was"


def test_section_6_1_still_says_exactly_two_files() -> None:
    """The premise of `test_the_workflow_directory_holds_exactly_two_files`, read at its home."""
    plan = _plan_text("11-repo-layout.md")
    if plan is None:
        pytest.skip("_plan/ is .gitignore'd and absent from this checkout")
    flat = " ".join(plan.split())
    assert "holds exactly two files" in flat
    assert "`release.yml` invokes `ci.yml` through `workflow_call`" in flat


def test_every_named_runner_is_actually_invoked_in_the_job_its_row_names(
    ci: Workflow, register: dict[str, object]
) -> None:
    """A gate step must RUN its register's runner, not merely be named after it.

    THE HOLE THIS CLOSES, found by mutation rather than by reading. Replacing
    `run: uv run tools/gate_licences.py` in the `G3` step with `run: echo "G3 passes"` left the
    entire suite green: `test_every_pr_blocking_row_is_invoked_in_the_job_its_row_names` matches on
    step NAMES, and `test_no_step_can_pass_for_the_wrong_reason` looks for `continue-on-error`,
    `|| true` and `--warn-only`, none of which an `echo` trips. So all fourteen rows carrying a
    runner could be silently disabled while every required check stayed green -- which is the exact
    failure mode section 6.8 refuses and the one a required status check exists to prevent.

    Asserted per job, like its sibling: a runner invoked in `build` would satisfy a file-wide
    search while running outside the `gates` job's budget and checkout depth. Both directions are
    checked, because a command in the wrong job is a gate nobody is measuring -- but the second
    direction is asserted PER PATH, not per row, and the difference is load-bearing.

    `tools/check_versions.py` discharges two rows whose jobs differ: G5 in `versions` and G14 in
    `gates`, because the script implements both (its own G14 clauses live at :411-460). A per-row
    reading of "must not run in a job my row does not name" makes each of those two rows fail on
    the other's job, which is not a defect -- it is the register correctly describing one script
    serving two gates. So the allowed job set for a path is the union over every row that names it.
    """
    jobs = tuple(ci.job_blocks())
    rows = [row for row in _gate_rows(register) if (row.get("runner") or []) and row["pr"]]

    # Where each runner is allowed to appear: the union of the jobs named by every row citing it.
    allowed: dict[str, set[str]] = {}
    for row in rows:
        for runner in row["runner"]:  # type: ignore[union-attr]
            allowed.setdefault(str(runner), set()).update(
                str(job)
                for job in row["jobs"]  # type: ignore[union-attr]
            )

    unrun: list[str] = []
    for row in rows:
        named = {str(job) for job in row["jobs"]}  # type: ignore[union-attr]
        for runner in row["runner"]:  # type: ignore[union-attr]
            path = str(runner)
            where = {job for job in jobs if path in ci.run_bodies(job)}
            if not (where & named):
                unrun.append(f"{row['id']}: {path} is invoked in {sorted(where) or 'no job'}")
    assert not unrun, unrun

    stray = [
        f"{path} runs in {job}, which no gate row naming it lists"
        for path, permitted in allowed.items()
        for job in {j for j in jobs if path in ci.run_bodies(j)} - permitted
    ]
    assert not stray, stray


def test_the_ci_ok_filter_treats_anything_but_success_as_a_failure(ci: Workflow) -> None:
    """`ci-ok` is the single required status check, so its jq filter IS the merge contract.

    THE SECOND HOLE FOUND BY MUTATION. Changing `.value.result != "success"` to
    `.value.result == "failure"` made a cancelled, timed-out or unexpectedly skipped job report
    GREEN on the one required check, and all 2,525 tests stayed green -- nothing read the filter's
    body. The polarity is the whole point: GitHub's `needs.*.result` is one of `success`,
    `failure`, `cancelled` or `skipped`, so an allow-list of `success` refuses three bad outcomes
    while a deny-list of `failure` refuses one and waves two through.

    A line-oriented assertion over a shell heredoc containing jq is crude, and it is the honest
    instrument available: there is no jq and no YAML parser in the dependency set (checked -- see
    the module docstring), so the alternative is not a better test but no test.
    """
    body = ci.run_bodies("ci-ok")
    assert '.value.result != "success"' in body, (
        'ci-ok must select on NOT success. A filter selecting `== "failure"` passes `cancelled` '
        "and `skipped`, which is how a cancelled run becomes a green required check."
    )
    assert '.value.result == "failure"' not in body
    # The skip exemption must stay scoped to the one job section 6.4 permits to skip. An
    # unscoped `!= "skipped"` arm would let any job skip itself into a pass.
    assert '.key != "toolchains"' in body, "the skipped-job exemption must name toolchains"
    exempted = re.findall(r'\.key\s*!=\s*"([a-z-]+)"', body)
    assert exempted == ["toolchains"], f"only toolchains may skip; found {exempted}"


# ---------------------------------------------------------------------------
# Found by mutation: the axes, the key, the credentials, the graph, the work
# ---------------------------------------------------------------------------


def test_the_nine_cells_actually_consume_both_matrix_axes(ci: Workflow) -> None:
    """A declared axis nothing reads is a nine-name label on a one-cell job.

    THE HOLE THIS CLOSES, and it is this file's own flagship assertion that it defeats.
    `test_the_matrix_is_nine_cells_landed_by_p2` writes the nine cells out by name rather than
    multiplying two tuples, on the stated ground that a shape check "would have been just as green
    against `{ubuntu} x {3.11, 3.12, 3.13}`, three cells of entirely the wrong kind". It is still
    just as green against that, because it reads the axis DECLARATION and never asks whether the
    job reads it. Two independent mutations proved it:

    * `runs-on: ${{ matrix.os }}` -> `runs-on: ubuntu-latest`. Nine cells, all on Linux. The
      cross-cell determinism 16-roadmap.md:340 dates to P2 -- the whole reason the six new cells
      "assert something rather than merely run" -- is not being tested on macOS or Windows at all,
      and section 1.9's CRLF class of defect, which only appears on the Windows cells, cannot be
      reached. Forty-three tests green.
    * `UV_PYTHON: ${{ matrix.py }}` -> `UV_PYTHON: "3.11"`. Nine cells, all on 3.11. Forty-three
      tests green.

    Both survive a reference count, because the job's `name:` interpolates both axes to title the
    check run and that reference survives either collapse. So `MATRIX_AXIS_CONSUMERS` names the
    SEMANTIC site for each axis and the assertion is on those: `runs-on` is what makes an OS axis
    an OS axis on GitHub Actions, and `UV_PYTHON` -- read by the install step and by section 6.6's
    cache key -- is what makes the Python axis select an interpreter.
    """
    block = ci.job_blocks()["test"]
    body = "\n".join(block)
    declared = set(_matrix_axes(ci))
    assert declared == set(MATRIX_AXIS_CONSUMERS), {
        "declared in ci.yml": sorted(declared),
        "with a consumer written down here": sorted(MATRIX_AXIS_CONSUMERS),
    }
    for axis, consumer in MATRIX_AXIS_CONSUMERS.items():
        assert any(line.strip() == consumer for line in block), (
            f"the {axis} axis is declared and never consumed: no line of the test job reads "
            f"{consumer!r}, so all {MATRIX_CELLS} cells share one {axis} value"
        )
    # The install step must act on the variable the axis feeds, or `UV_PYTHON` is a name nothing
    # resolves and every cell takes whatever interpreter the runner image ships.
    assert 'uv python install "$UV_PYTHON"' in body


def test_each_test_cell_keys_its_cache_on_its_own_python_version(ci: Workflow) -> None:
    """11-repo-layout.md:1715-1716 states this as arithmetic, not preference: "The nine `test`
    cells are 747 s of that, which is why they get their own key per Python version rather than
    sharing one." :1701 sizes the result -- "nine `uv` keys (3 OS x 3 Python)".

    FOUND BY MUTATION. Collapsing `key` and `restore-keys` to `uv-${{ runner.os }}-...`, dropping
    the `py${{ matrix.py }}` segment from both, left all forty-three tests green -- while the
    workflow carried section 6.6's sentence verbatim in the comment directly above the key it had
    just contradicted. The consequence is not a slower build: nine cells race to write three
    entries and the losers restore a `uv` cache populated for a different interpreter, so a
    3.13-only resolution failure is masked by a 3.11 cache hit on the cell that was supposed to
    find it.

    Pinned as two literals here rather than derived from the workflow, because both halves of a
    derived comparison would come out of `ci.yml` and would agree with each other whatever they
    said.
    """
    block = ci.job_blocks()["test"]
    assert any(line.strip() == f'key: "{TEST_CACHE_KEY}"' for line in block), (
        f"the test job's cache key is not {TEST_CACHE_KEY!r} (11-repo-layout.md:1715-1716)"
    )
    assert any(line.strip() == f'restore-keys: "{TEST_CACHE_RESTORE_KEY}"' for line in block), (
        f"the test job's restore-keys prefix is not {TEST_CACHE_RESTORE_KEY!r}"
    )
    # Both halves must carry the axis, since a prefix that drops it re-shares the cache on the
    # fallback path even when the exact key does not.
    for value in (TEST_CACHE_KEY, TEST_CACHE_RESTORE_KEY):
        assert "${{ matrix.py }}" in value, value


def test_the_steps_that_do_the_work_run_the_work(ci: Workflow) -> None:
    """The `echo "G3 passes"` hole, one job to the left of where the last wave found it.

    `test_every_named_runner_is_actually_invoked_in_the_job_its_row_names` closed it for the
    fourteen `[[gate]]` rows carrying a `runner` path. Nothing in `tools/gates.toml` names
    `uv run pytest -q`, so the nine `test` cells were outside that net entirely: replacing the
    suite invocation with `run: echo "the test suite passed"` left all forty-three tests green
    and turned the job 16-roadmap.md:340 makes P2's headline first-green into nine no-ops behind
    a green required check. `G28`'s round trip is the same story -- the step's own comment says
    the MECHANISM half is the half P2 landed, so an `echo` there is a claim about `INV-1` that
    nothing is checking.

    Asserted per job, like both of its siblings: a `uv build` in `gates` would satisfy a
    file-wide search while running outside `build`'s budget and its two-pass reproducibility
    check.
    """
    missing = [
        f"{job}: {command}"
        for job, commands in CI_WORK_COMMANDS.items()
        for command in commands
        if command not in ci.run_bodies(job)
    ]
    assert not missing, (
        f"a step that does the work no longer runs it: {missing}. A gate replaced by an echo is "
        f"section 6.8's check that cannot fail, and a required status check cannot see it."
    )


def test_every_checkout_refuses_to_persist_the_token(ci: Workflow, release: Workflow) -> None:
    """`actions/checkout` writes the job's `GITHUB_TOKEN` into `.git/config` unless told not to,
    and it is told not to eleven times in `ci.yml` and three times in `release.yml`.

    FOUND BY MUTATION: flipping all eleven to `persist-credentials: true` left every test green.
    11-repo-layout.md:1772 puts credential persistence on `zizmor`'s list -- "unpinned `uses:`,
    `persist-credentials`, template-injection sinks" -- and the module docstring above records
    that `zizmor` is unpinnable at release 1 and therefore unarmed, so there was no check on
    either side of the fence. A persisted token is readable by every later step in the job,
    including anything a PR author can influence, which is what makes this a supply-chain
    property and not a hygiene preference.

    Asserted as a COUNT against the checkouts rather than as "at least one", because the defect
    that matters is the twelfth checkout added without the line -- which "at least one" cannot
    see.
    """
    for workflow in (ci, release):
        checkouts = [ref for _, ref, _ in workflow.uses() if ref.startswith("actions/checkout@")]
        refusals = [
            line for line in workflow.code_lines() if line.strip() == "persist-credentials: false"
        ]
        assert checkouts, f"{workflow.name} checks out nothing"
        assert len(refusals) == len(checkouts), {
            "file": workflow.name,
            "checkouts": len(checkouts),
            "persist-credentials: false": len(refusals),
        }


def test_versions_is_a_predecessor_of_every_other_job(ci: Workflow) -> None:
    """11-repo-layout.md:1415-1416 states the graph's two invariants in one line: "`versions` is a
    predecessor of all of them and `ci-ok` a successor."

    FOUND BY MUTATION: deleting `needs: [versions]` from the `test` job left every test green.
    Section 6.2 makes `versions` the fan-out root because it is the ~20 s job that fails fast on a
    lockfile or interpreter mismatch; a job that does not wait for it burns its whole budget on
    nine runners before the cheap answer arrives, and `ci-ok` -- which reads `needs` results and
    not `success()` -- still reports on it, so the failure is late rather than absent. That is
    exactly the shape a graph assertion exists to catch and exactly the shape no other assertion
    in this file can see.

    `ci-ok` is exempt because it is the successor, and its own `needs` is pinned by
    `test_ci_ok_needs_every_job_but_itself` against `CI_OK_NEEDS`.
    """
    blocks = ci.job_blocks()
    assert "versions" in blocks and "ci-ok" in blocks, sorted(blocks)
    assert not any(line.strip().startswith("needs:") for line in blocks["versions"]), (
        "versions is the fan-out root and may wait on nothing"
    )
    orphans = [
        job
        for job, body in blocks.items()
        if job not in {"versions", "ci-ok"}
        and not any(line.strip() == "needs: [versions]" for line in body)
    ]
    assert not orphans, (
        f"{orphans} do not wait on versions (11-repo-layout.md:1415-1416). A job that skips the "
        f"fan-out root spends its budget before the ~20 s answer arrives."
    )


def test_the_tripwires_test_no_path_that_exists_on_this_checkout(ci: Workflow) -> None:
    """The runner's question, asked of the paths `ci.yml` ACTUALLY TESTS rather than of a table.

    THE HOLE THIS CLOSES. `test_no_tripwire_is_already_firing_on_this_checkout` iterates
    `CI_TRIPWIRE_PATHS`, so a path the workflow tests and the table does not list is invisible to
    it, and `test_g28s_tripwire_does_not_fire_on_the_generator_directory` refuses exactly one
    spelling of the P2 regression -- the substring `-d fixtures ]`. Adding

        if [ -d fixtures/ ]
        then echo "the fixture corpus landed: widen G28"; exit 1
        fi

    to the `G28` step reinstated that regression in full -- `fixtures/` exists on this checkout,
    so the `gates` job would be red on every PR for a reason no reader would connect to their
    change -- and left all forty-three tests green, because a trailing slash is not the spelling
    the table-driven check knows. A negative assertion on one substring is not a check on a
    condition; it is a check on a habit.

    So the paths are EXTRACTED from each tripwire step's own shell and then asked two questions:
    none of them may exist on this checkout, and the extracted set must equal the table. The
    second half is what keeps `CI_TRIPWIRE_PATHS` honest in the other direction -- a path removed
    from the shell and left in the table is a row describing a step that no longer tests it.
    """
    for step, (job, name) in CI_TRIPWIRE_STEPS.items():
        bodies = ci.step_run_bodies(job)
        assert name in bodies, f"{step}: no step named {name!r} in job {job}"
        tested: set[str] = set()
        for line in bodies[name].splitlines():
            listed = _SHELL_FOR_LIST.match(line)
            if listed is not None:
                tested.update(listed.group("items").split())
            tested.update(_SHELL_FILE_TEST.findall(line))
        assert tested == set(CI_TRIPWIRE_PATHS[step]), {
            "step": step,
            "tested by the shell": sorted(tested),
            "in CI_TRIPWIRE_PATHS": sorted(CI_TRIPWIRE_PATHS[step]),
        }
        firing = sorted(path for path in tested if (REPO / path).exists())
        assert not firing, (
            f"the {step} tripwire tests {firing}, which exist on this checkout, so the {job} job "
            f"is red on every PR. Wire the step, then narrow the condition -- do not widen it."
        )
