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

Seven properties, each one a sentence of section 6 made falsifiable:

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
* **the P1 matrix is three cells at 3.11**, which is 16-roadmap.md section 4's non-goal overriding
  section 6.2's nine, and the nine-cell form is named in a comment as P2's.

Specified in 11-repo-layout.md sections 1.1, 6.1, 6.2, 6.3, 6.4, 6.6, 6.7, 6.8, 7.3 and 7.4, and
16-roadmap.md section 4.
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

# Section 6.2's OS axis, and the P1 Python axis. 16-roadmap.md section 4's non-goals: "No CI matrix
# beyond three OSes at 3.11 -- the nine-cell `test` job arrives with P2's determinism work."
P1_OS: tuple[str, ...] = ("ubuntu-latest", "macos-latest", "windows-latest")
P1_PYTHON: tuple[str, ...] = ("3.11",)

# Section 6.6's two-sided budget rule: "Each job carries `timeout-minutes` at **twice** its stated
# budget -- a hard stop that turns a hung `parity` container into a 20-minute failure rather than a
# six-hour one." The parity number is the one the document states out loud, so it is pinned; the
# rest are checked for presence, because a wrong multiple is a review question and a missing
# timeout is a six-hour job.
PARITY_TIMEOUT_MINUTES = 20

_TOP_KEY = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_-]*):")
_JOB_KEY = re.compile(r"^  (?P<name>[a-z][a-z0-9_-]*):\s*(?:#.*)?$")
_STEP_NAME = re.compile(r"^\s{6,8}-?\s*name:\s*(?P<name>.+?)\s*$")
_USES = re.compile(r"^\s*-?\s*uses:\s*(?P<ref>\S+)\s*(?P<rest>.*)$")
_RUN_START = re.compile(r"^\s*-?\s*run:\s*(?P<inline>.*)$")
_FLOW_LIST = re.compile(r"\[(?P<body>[^]]*)\]")
_SHA40 = re.compile(r"@[0-9a-f]{40}$")
_TODO_PIN = re.compile(r"TODO:\s*pin")


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
# 16-roadmap.md section 4 -- the P1 matrix, and what it says about P2
# ---------------------------------------------------------------------------


def test_the_p1_matrix_is_three_cells_at_3_11(ci: Workflow) -> None:
    """16-roadmap.md section 4's non-goals, which override section 6.2's nine cells for now: "No CI
    matrix beyond three OSes at 3.11 -- the nine-cell `test` job arrives with P2's determinism
    work."
    """
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
    assert axes.get("os") == P1_OS, axes
    assert axes.get("py") == P1_PYTHON, axes
    assert len(axes["os"]) * len(axes["py"]) == 3, axes


def test_the_nine_cell_expansion_is_named_as_p2s(ci: Workflow) -> None:
    """The brief the matrix comment has to meet: say which rows are P1 and which land at P2.

    A three-cell matrix with no note reads as a disagreement with section 6.4's "test (9)" column.
    With the note it reads as a phase, which is what it is.
    """
    header = ci.text
    assert "3.12" in header and "3.13" in header, "the P2 axis is not named anywhere"
    assert "P2" in header
    assert "16-roadmap.md" in header


def test_the_matrix_does_not_stop_at_the_first_failing_cell(ci: Workflow) -> None:
    """Nine budgeted cells that stop at the first failure hide eight answers, and section 6.2
    budgets every cell.
    """
    assert "fail-fast: false" in "\n".join(ci.job_blocks()["test"])


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
    """`_plan/` is `.gitignore`d, so a clean clone has no design tree."""
    path = REPO / "_plan" / document
    return path.read_text(encoding="utf-8") if path.is_file() else None


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


def test_the_p1_matrix_non_goal_is_still_what_the_roadmap_says() -> None:
    """The one sentence this whole file's matrix decision rests on. If it is ever amended, the
    three-cell matrix stops being a phase and becomes a divergence, and this test is what notices.
    """
    plan = _plan_text("16-roadmap.md")
    if plan is None:
        pytest.skip("_plan/ is .gitignore'd and absent from this checkout")
    # The sentence wraps in the markdown source, so it is compared against whitespace-flattened
    # text. The clause between the two halves is an em dash, which this ASCII file does not carry.
    flat = " ".join(plan.split())
    assert "No CI matrix beyond three OSes at 3.11" in flat
    assert "the nine-cell `test` job arrives with P2's determinism work" in flat


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
