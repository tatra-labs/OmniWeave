"""G7 tested as a program: the classification is the plan's, and the linter goes red on cue.

`tools/gate_pins.py` is the enforcer of 11-repo-layout.md section 8.5's pin policy -- *"a
constraint tighter than `>=` carries a comment"* (`tools/gates.toml` G7, rendered at
11-repo-layout.md:1550, stated at 00-vision.md:585, 14-security.md:1275 and 17-risks.md:227). It is
W1.7, 16-roadmap.md:363, and it was owed from P1. This file is what makes it a gate rather than a
script, in five parts:

* **the classification is the plan's.** Every operator, requirement string and verdict below is a
  literal written out here, never read from `tools/gate_pins.py` and never read from a
  `pyproject.toml`. The three operators come from G7's own `step` (*"a `==`, `~=` or `<` bound"*);
  `>=` is exempt because section 8.5's first role is *"floor with a CVE comment, no ceiling"*; `!=`
  is exempt because the same paragraph calls docling's `pypdfium2 (>=4.30.0,!=4.30.1,<6.0.0)` *"the
  habit worth copying"*. `CLASSIFICATION` does read `TIGHTENING_OPERATORS`, but only as the FILTER
  it applies to `operators_in`'s output; the EXPECTED column beside every row is a literal, and the
  table carries exempt rows (`pkg>1.0`) as well as tightened ones, so a set that lost `<` and a set
  that gained `>` are both caught. Reading the constant AND deriving the expectation from it would
  be pinning agreement and not value -- the same defect as reading an expectation out of the
  database -- and the difference is which side of the assertion the constant sits on.
* **the linter goes red when it is shown a bad bound.** A gate nobody has seen fail is a gate
  nobody has tested. Each of the four shapes the brief for this wave names -- an unjustified `==`,
  a bare `<`, a `~=`, and `>=1.2,<2`, the one a careless implementation passes because it reads
  only the first operator -- is written into a temporary workspace as a real file and asserted to
  exit non-zero with the bound named in the report. So are the three accepted comment forms, in the
  other direction.
* **the two passes are reconciled, and the failure to reconcile is exit 2.** `tomllib` discards
  comments, so the gate reads the file as TEXT for the comment and as TOML for the bound. A bound
  the text pass cannot locate is the one way a one-pass implementation goes quietly green, and
  `test_a_bound_the_text_pass_cannot_see_does_not_pass_quietly` is the assertion that it does not.
* **the shipped fourteen are covered, and what the gate finds in them is not smoothed away.** The
  workspace has fourteen `pyproject.toml` files (16-roadmap.md:363, *"The workspace: 14
  `pyproject.toml`"*), and the COUNT of them is asserted -- but no test here pins how many of
  their bounds are justified today, and that omission is deliberate. Whether a given bound carries
  a comment is a fact about the tree that any `pyproject.toml` edit changes; a test that pinned
  "seven files red over twenty-five bounds" would be red the afternoon someone wrote the comments,
  which is the outcome the gate exists to produce. So the tree-facing tests pin only what the plan
  itself rules on: `packages/omniweave-office/pyproject.toml`'s `firecrawl-anydoc == 0.2.4` is
  asserted to PASS, because 11-repo-layout.md:2337-2339 states it *"carries its justification in
  the `pyproject.toml` comment"*; `hatchling>=1.27` and `>=3.11` are asserted to be parsed and to
  be no finding, because they are floors; and `omniweave-ports >=1,<2` is asserted to be a
  tightened bound, because section 8.5 grants a first-party sibling no exemption. Everything else
  the fourteen files happen to say is checked on a FIXTURE, in a `tmp_path` workspace this file
  writes itself.
* **the claims that had no test at all, found by mutation.** The last section of this file was
  written by breaking `tools/gate_pins.py` on purpose, one edit at a time, and watching the suite
  above stay green. Ten mutations survived it -- among them `REPO` pointed one directory too
  shallow, which is the only root CI's `uv run --no-project tools/gate_pins.py` invocation ever
  uses; `--glob` parsed and then ignored; three of the four `[tool.uv]` requirement arrays deleted
  from the scope; and `_WHY`, the remediation the whole gate exists to deliver, blanked to the
  empty string. Each has a test now, and each test names the mutation it kills so the next reader
  does not delete it as redundant.

The gate is loaded by file path with `importlib.util`, never by `importlib.import_module` and never
by putting `tools/` on `sys.path` -- the discipline `test_gates_structural.py` states.

Specified in 11-repo-layout.md section 8.5 (the policy and its role table), `tools/gates.toml`'s G7
row (the assertion, the scope and the operator list), 16-roadmap.md:363 (W1.7) and
14-security.md:1275-1279 (why the comment is the auditability floor).
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import NamedTuple

import pytest


def _load(repo_root: Path) -> ModuleType:
    """Load `tools/gate_pins.py` under a private name. See `test_gates_structural._load`."""
    path = repo_root / "tools" / "gate_pins.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_pins", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gate(repo_root: Path) -> ModuleType:
    return _load(repo_root)


# ---------------------------------------------------------------------------
# Helpers: a temporary workspace shaped like the real one
# ---------------------------------------------------------------------------

_HEAD = """\
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.11"
"""


def _workspace(tmp_path: Path, body: str, *, name: str = "demo") -> Path:
    """A one-member workspace whose single `pyproject.toml` is `_HEAD` plus `body`.

    The head is deliberately not minimal: it carries `hatchling>=1.27` in `[build-system] requires`
    and `requires-python = ">=3.11"` with no comment on either, which are the two bounds the whole
    tree carries and which G7 must never fail. Every red below therefore proves the gate fired on
    the body and not on the boilerplate.
    """
    package = tmp_path / "packages" / name
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(_HEAD.format(name=name) + body, encoding="utf-8")
    return tmp_path


def _run(gate: ModuleType, root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = gate.main(["--root", str(root)])
    return code, capsys.readouterr().out


# ---------------------------------------------------------------------------
# The classification is the plan's, written out as literals
# ---------------------------------------------------------------------------

# (requirement, the specifier the gate should read, the operators tighter than `>=` in it).
#
# Nothing here is imported from the gate. The operator verdicts are G7's own step -- "a `==`, `~=`
# or `<` bound" -- widened to the two spellings of the same two families (`===`, `<=`), and the
# three exemptions are section 8.5's: `>=` is the policy's default shape, `>` is still a floor,
# and `!=` is the exclusion section 8.5 prescribes.
CLASSIFICATION: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # --- exempt: a floor, which is what section 8.5's first role prescribes -----------------
    ("hatchling>=1.27", ">=1.27", ()),
    ("defusedxml>=0.7.1", ">=0.7.1", ()),
    ("pysqlite3-binary>=0.5", ">=0.5", ()),
    ("torch", "", ()),
    ("pytest", "", ()),
    ("pkg>1.0", ">1.0", ()),
    # 11-repo-layout.md section 8.5 on this exact string: "the habit worth copying".
    ("pypdfium2>=4.30,!=4.30.1", ">=4.30,!=4.30.1", ()),
    ("pypdfium2 (>=4.30.0,!=4.30.1)", ">=4.30.0,!=4.30.1", ()),
    # --- tightened -------------------------------------------------------------------------
    ("firecrawl-anydoc == 0.2.4", "== 0.2.4", ("==",)),
    ("omniweave-core ~= 0.1.0", "~= 0.1.0", ("~=",)),
    ("nltk~=3.9.0", "~=3.9.0", ("~=",)),
    ("litellm==1.97.0", "==1.97.0", ("==",)),
    ("pkg===1.0", "===1.0", ("===",)),
    ("pkg<2", "<2", ("<",)),
    ("pkg<=1.9", "<=1.9", ("<=",)),
    # THE ONE A CARELESS IMPLEMENTATION PASSES: the first operator is `>=` and the bound is not.
    ("pkg>=1.2,<2", ">=1.2,<2", ("<",)),
    ("omniweave-ports >=1,<2", ">=1,<2", ("<",)),
    ("graspologic-native>=1.2,<1.3", ">=1.2,<1.3", ("<",)),
    ("pypdfium2 (>=4.30.0,!=4.30.1,<6.0.0)", ">=4.30.0,!=4.30.1,<6.0.0", ("<",)),
    # --- extras and markers ----------------------------------------------------------------
    ("pkg[extra1,extra2]==1.0", "==1.0", ("==",)),
    ("pkg[extra] >=1", ">=1", ()),
)


@pytest.mark.parametrize(("requirement", "specifier", "tightening"), CLASSIFICATION)
def test_a_requirement_is_classified_by_the_operators_its_specifier_carries(
    gate: ModuleType, requirement: str, specifier: str, tightening: tuple[str, ...]
) -> None:
    read = gate.specifier_of(requirement)
    assert (read or "") == specifier, requirement
    operators = gate.operators_in(read or "")
    assert tuple(op for op in operators if op in gate.TIGHTENING_OPERATORS) == tightening


def test_an_environment_marker_is_not_a_version_bound(gate: ModuleType) -> None:
    """A marker decides WHETHER a requirement applies, not which versions satisfy it.

    The workspace root's dev group carries `semgrep; sys_platform != 'win32'` and
    `atheris; sys_platform == 'linux'`, whose markers hold a `!=` and a `==`; a `<` marker
    (`python_version < "3.12"`) is the same shape. Reading any of them as a bound would fail the
    two-marker rule 11-repo-layout.md section 6.2 requires, on a gate about pins.
    """
    for requirement in (
        "semgrep; sys_platform != 'win32'",
        "atheris; sys_platform == 'linux'",
        'pkg; python_version < "3.12"',
        'pkg >=1; python_version < "3.12"',
    ):
        specifier = gate.specifier_of(requirement) or ""
        assert not [op for op in gate.operators_in(specifier) if op in gate.TIGHTENING_OPERATORS], (
            requirement
        )


def test_a_direct_url_reference_carries_no_specifier_set(gate: ModuleType) -> None:
    """PEP 508 forbids a specifier set beside a `@ url`, so there is no bound to comment on.

    A URL dependency is a real defect -- it is unpinned supply chain and G12's business -- and it
    is not this gate's, because reporting it here would give one exit code two meanings.
    """
    assert gate.specifier_of("pkg @ https://example.invalid/pkg-1.0.whl") is None
    assert gate.specifier_of("pkg[extra] @ file:///tmp/pkg") is None


def test_the_operator_table_is_ordered_longest_first(gate: ModuleType) -> None:
    """`operators_in` reads a clause's operator by first match, so the order is load-bearing.

    `>=1` read as `>` and `===1.0` read as `==` are both misreports, and both are what a table
    sorted any other way produces.
    """
    lengths = [len(op) for op in gate.OPERATORS]
    assert lengths == sorted(lengths, reverse=True), gate.OPERATORS
    assert set(gate.OPERATORS) == {"===", "==", "~=", "!=", "<=", ">=", "<", ">"}


# ---------------------------------------------------------------------------
# The comment forms: three accepted, and what breaks a run
# ---------------------------------------------------------------------------

JUSTIFIED = """\
dependencies = [
  "pkg==1.0",  # exact: golden tokeniser, owner model, refresh in #412, review 2026-12-03
]
"""

JUSTIFIED_ABOVE = """\
dependencies = [
  # Exact: golden tokeniser. Owner model, refresh procedure in docs/adr/0002, issue #412.
  "pkg==1.0",
]
"""

JUSTIFIED_BELOW = """\
dependencies = [
  "pkg==1.0",
  # Exact: golden tokeniser. Owner model, refresh procedure in docs/adr/0002, issue #412.
]
"""


@pytest.mark.parametrize(
    ("form", "body"),
    (
        ("trailing on its own line", JUSTIFIED),
        ("the block above", JUSTIFIED_ABOVE),
        ("the block below", JUSTIFIED_BELOW),
    ),
)
def test_a_comment_beside_the_bound_justifies_it_in_all_three_accepted_forms(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], form: str, body: str
) -> None:
    """Form 3 is forced by the plan, not chosen for convenience.

    11-repo-layout.md:2337-2339 says `firecrawl-anydoc == 0.2.4` *"carries its justification in the
    `pyproject.toml` comment"*, and in `packages/omniweave-office/pyproject.toml` that comment sits
    on the two lines BELOW the bound. A gate accepting only forms 1 and 2 would fail the one file
    section 8.5 holds up as compliant.
    """
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 0, f"{form}: {out}"
    assert "1 tightened bound(s), 1 carrying an adjacent comment, 0 not" in out


def test_a_blank_line_breaks_the_comment_run(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Adjacency is the whole of what a text gate can honestly claim, so it must be adjacency.

    A comment two lines up with a blank between is a comment about something else, and crediting
    it would make any file with a header comment vacuously compliant.
    """
    body = 'dependencies = [\n  # A reason about something else.\n\n  "pkg==1.0",\n]\n'
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 1, out
    assert "'pkg==1.0' carries == and no adjacent comment" in out


def test_a_table_header_breaks_the_comment_run_so_a_generated_block_is_not_a_justification(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The shape `packages/omniweave/pyproject.toml:25-45` is in, and the reason it reds.

    The extras block there carries a seven-line comment above `[project.optional-dependencies]`.
    The header line is code, so the run stops there and reaches none of the eleven keys under it.
    Crediting a comment across a header would mean one comment justifying an unbounded number of
    bounds -- which is the difference between an auditable pin and a decorated table.
    """
    body = (
        "# GENERATED by tools/check_versions.py --set; asserted by G5. Do not hand-edit a bound.\n"
        "[project.optional-dependencies]\n"
        'office = ["other ~= 0.1.0"]\n'
        'pdf = ["another ~= 0.1.0"]\n'
    )
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 1, out
    assert "'other ~= 0.1.0' carries ~= and no adjacent comment" in out
    assert "'another ~= 0.1.0' carries ~= and no adjacent comment" in out


def test_a_bare_hash_is_a_comment_that_carries_no_justification(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Otherwise the gate is satisfiable by one keystroke, which is worse than no gate."""
    code, out = _run(gate, _workspace(tmp_path, 'dependencies = ["pkg==1.0"]  #\n'), capsys)
    assert code == 1, out
    assert "'pkg==1.0' carries == and no adjacent comment" in out


def test_a_hash_inside_a_string_is_not_a_comment(gate: ModuleType) -> None:
    """`scan` has to know TOML string state or every URL fragment is a justification."""
    lines = gate.scan('a = "x # y"  # the real comment\nb = "u#v"\nc = 1\n')
    assert (lines[0].code, lines[0].comment) == ('a = "x # y"  ', " the real comment")
    assert lines[1].comment is None
    assert lines[2].comment is None


def test_a_hash_inside_a_multi_line_string_is_not_a_comment(gate: ModuleType) -> None:
    """The `step` values in `tools/gates.toml` are multi-line strings holding `#`, and a splitter
    that forgot the state carried across lines would read the rest of the file as commented."""
    lines = gate.scan('s = """\nnot # a comment\n"""\nd = 1  # a comment\n')
    assert lines[1].comment is None
    assert lines[1].code == "not # a comment"
    assert lines[3].comment == " a comment"


# ---------------------------------------------------------------------------
# Non-vacuity: every shape the brief names, shown to the gate
# ---------------------------------------------------------------------------


class RedCase(NamedTuple):
    """One `pyproject.toml` body that must red, and the fragment the report must name.

    A NamedTuple rather than six positional parameters: the case is one value, and `label` exists
    so a failure reads "a floor with a ceiling passed" rather than "case 4 passed".
    """

    label: str
    body: str
    fragment: str


RED_BODIES: tuple[RedCase, ...] = (
    RedCase(
        "an unjustified exact pin",
        'dependencies = ["firecrawl-anydoc == 0.2.4"]\n',
        "'firecrawl-anydoc == 0.2.4' carries ==",
    ),
    RedCase(
        "a bare ceiling",
        'dependencies = ["pkg<2.0"]\n',
        "'pkg<2.0' carries <",
    ),
    RedCase(
        "a compatible-release pin",
        'dependencies = ["nltk~=3.9.0"]\n',
        "'nltk~=3.9.0' carries ~=",
    ),
    RedCase(
        "a floor with a ceiling -- the one a careless implementation passes",
        'dependencies = ["graspologic-native>=1.2,<1.3"]\n',
        "'graspologic-native>=1.2,<1.3' carries <",
    ),
    RedCase(
        "an arbitrary-equality pin",
        'dependencies = ["pkg===1.0+local"]\n',
        "'pkg===1.0+local' carries ===",
    ),
    RedCase(
        "an inclusive ceiling, which is the same ceiling one character wider",
        'dependencies = ["pkg<=1.9"]\n',
        "'pkg<=1.9' carries <=",
    ),
)


@pytest.mark.parametrize("case", RED_BODIES, ids=[case.label for case in RED_BODIES])
def test_the_gate_reds_on_a_tightened_bound_with_no_comment(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str], case: RedCase
) -> None:
    code, out = _run(gate, _workspace(tmp_path, case.body), capsys)
    assert code == 1, f"{case.label} passed: {out}"
    assert case.fragment in out, f"{case.label}: the report does not name the bound\n{out}"
    assert "1 tightened bound(s), 0 carrying an adjacent comment, 1 not" in out


def test_a_bound_in_every_covered_site_is_checked_and_none_is_silently_skipped(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate that silently checks one table is worse than no gate.

    An extra is where 00-vision.md:585 records DataFlow's *"four incompatible vLLM pins"*, and a
    `[tool.uv] constraint-dependencies` row bounds the resolution of the whole workspace. So each
    of the six site shapes gets an unjustified bound here and each must appear in the report by
    its site path, not merely be counted.
    """
    package = tmp_path / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling==1.27"]\n'
        'build-backend = "hatchling.build"\n\n'
        "[project]\n"
        'name = "demo"\nversion = "0.1.0"\n'
        'requires-python = ">=3.11,<3.14"\n'
        'dependencies = ["a==1"]\n\n'
        "[project.optional-dependencies]\n"
        'extra = ["b~=1.0"]\n\n'
        "[dependency-groups]\n"
        'dev = ["c<2"]\n\n'
        "[tool.uv]\n"
        'constraint-dependencies = ["d<=3"]\n',
        encoding="utf-8",
    )
    code, out = _run(gate, tmp_path, capsys)
    assert code == 1, out
    for site in (
        "build-system.requires[0]",
        "project.requires-python",
        "project.dependencies[0]",
        "project.optional-dependencies.extra[0]",
        "dependency-groups.dev[0]",
        "tool.uv.constraint-dependencies[0]",
    ):
        assert site in out, f"{site} was not reported\n{out}"
    assert "6 tightened bound(s), 0 carrying an adjacent comment, 6 not" in out


def test_several_bounds_on_one_physical_line_are_each_checked(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """There is no "one key per physical line" rule over `pyproject.toml`, so this must work.

    11-repo-layout.md:1570 scopes G27 clause (a2) to ` ```toml ` fences in the plan DOCUMENTS, and
    11-repo-layout.md:274 prints `packages/omniweave-pdf`'s three requirements on one physical
    line. `packages/omniweave/pyproject.toml:45` is the shipped case: `recommended` holds three
    `~=` bounds on one line, and the gate reports three findings there.
    """
    body = 'dependencies = ["a==1", "b~=2", "c>=3", "d>=1,<2"]\n'
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 1, out
    assert "3 tightened bound(s), 0 carrying an adjacent comment, 3 not" in out
    for fragment in ("'a==1' carries ==", "'b~=2' carries ~=", "'d>=1,<2' carries <"):
        assert fragment in out, out
    assert "'c>=3'" not in out


def test_one_comment_on_a_shared_line_credits_every_bound_on_it(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stated false-negative direction, asserted so it cannot drift into a false positive.

    A trailing comment on a line holding three bounds cannot be attributed to one of them, and a
    gate that guessed would be reporting its guess. Section 8.4's PR field is what catches the
    comment that only justifies one of the three; this gate accepts and says so.
    """
    body = 'dependencies = ["a==1", "b~=2"]  # both are goldens: owner model, issue #412\n'
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 0, out
    assert "2 tightened bound(s), 2 carrying an adjacent comment, 0 not" in out


# ---------------------------------------------------------------------------
# Exit 2: the gate did not run
# ---------------------------------------------------------------------------


def test_a_bound_the_text_pass_cannot_see_does_not_pass_quietly(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole reason the two passes are reconciled rather than merely both run.

    A requirement written across a multi-line basic string parses to a string the text pass cannot
    match to any single-line literal, so no comment can be attributed to it. A one-pass text gate
    reports the same green here as on a clean file; this one exits 2 and names the bound.
    """
    body = 'dependencies = [\n  """pkg==1.0\n""",\n]\n'
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 2, out
    assert "G7 DID NOT RUN" in out
    assert "could not locate as a string literal" in out
    assert "pkg==1.0" in out


def test_a_file_that_is_not_toml_is_not_a_finding(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A finding says "this bound is unjustified", which is no claim about an unparseable file."""
    package = tmp_path / "packages" / "demo"
    package.mkdir(parents=True)
    (package / "pyproject.toml").write_text("this is not = = toml\n", encoding="utf-8")
    code, out = _run(gate, tmp_path, capsys)
    assert code == 2, out
    assert "G7 DID NOT RUN" in out
    assert "not parseable TOML" in out


def test_a_glob_that_matches_nothing_is_the_gate_not_running(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A green over zero files is the failure mode 13-quality.md's C-series is named for.

    `budget_s = 2` makes this gate cheap enough that nobody looks at its log, so an empty checkout,
    a renamed directory or a wrong `--root` has to be exit 2 and not exit 0.
    """
    code, out = _run(gate, tmp_path, capsys)
    assert code == 2, out
    assert "G7 DID NOT RUN" in out
    assert "packages/*/pyproject.toml" in out


def test_a_bad_argument_is_the_gate_not_running(
    gate: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert gate.main(["--no-such-flag"]) == 2
    capsys.readouterr()


# ---------------------------------------------------------------------------
# The shipped fourteen
# ---------------------------------------------------------------------------

# 16-roadmap.md:363 (W1.7): "The workspace: 14 `pyproject.toml`, `uv.lock`, hatchling, the 1:1
# extra alias map, and gates G2, G3, G4, G5, G7, G13, G14". The count is a plan literal.
WORKSPACE_MEMBERS = 14


def test_the_gate_reads_all_fourteen_shipped_pyproject_files(
    gate: ModuleType, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The scope of a green -- or a red -- is fourteen files, and it says so on every run."""
    gate.main(["--root", str(repo_root)])
    out = capsys.readouterr().out
    assert f"{WORKSPACE_MEMBERS} pyproject.toml file(s)" in out
    assert "glob(s): packages/*/pyproject.toml" in out
    assert out.isascii(), "the report must survive a cp1252 console"


def test_every_shipped_pyproject_parses_and_carries_constraints(
    gate: ModuleType, repo_root: Path
) -> None:
    """Non-vacuity per file. A file the gate found and read zero constraints out of would make
    its green a green about nothing, and `omniweave-ports` -- the one distribution with an empty
    `dependencies` list (11-repo-layout.md:126) -- still carries `requires-python` and
    `hatchling>=1.27`, so the floor is two and not zero everywhere."""
    paths = sorted((repo_root / "packages").glob("*/pyproject.toml"))
    assert len(paths) == WORKSPACE_MEMBERS, paths
    for path in paths:
        report = gate.check_file(path)
        assert len(report.constraints) >= 2, path
        assert report.uncovered == (), f"{path} carries a constraint site the gate does not read"


def test_the_floors_the_whole_tree_carries_are_never_a_finding(
    gate: ModuleType, repo_root: Path
) -> None:
    """`hatchling>=1.27` and `requires-python = ">=3.11"` are in all fourteen, and both are floors.

    11-repo-layout.md:225 reads *"`hatchling>=1.27` is a floor with a reason, which G7 requires"* --
    which would make a bare `>=` line a G7 finding and fail all fourteen files at once. Every other
    statement of the assertion scopes it to a constraint TIGHTER than `>=`, and this test pins the
    narrow reading: see the report of this wave, where the wide one is filed as a defect.
    """
    for path in sorted((repo_root / "packages").glob("*/pyproject.toml")):
        report = gate.check_file(path)
        parsed = {constraint.raw for constraint in report.constraints}
        # The non-vacuity half, and it is not decoration. The two assertions below are
        # `not in`, and a `not in` over an EMPTY set passes while proving nothing: a tree that
        # stopped carrying `hatchling>=1.27`, or a `collect` that stopped reading
        # `build-system.requires`, would leave this test green and the floor rule untested.
        # So the floors are asserted PRESENT among the parsed constraints first.
        assert "hatchling>=1.27" in parsed, path
        assert ">=3.11" in parsed, path
        raws = {occurrence.raw for occurrence in report.occurrences}
        assert "hatchling>=1.27" not in raws, path
        assert ">=3.11" not in raws, path


def test_the_plans_own_exact_pin_carries_its_justification(
    gate: ModuleType, repo_root: Path
) -> None:
    """The one file the plan rules on, and the gate must agree with the plan about it.

    11-repo-layout.md:2337-2339: *"`firecrawl-anydoc == 0.2.4` is an exact pin under the second
    role and carries its justification in the `pyproject.toml` comment"*. In
    `packages/omniweave-office/pyproject.toml` that comment sits BELOW the bound, which is why
    form 3 is accepted; if this assertion ever fails, the gate has stopped agreeing with the
    plan's own worked example and the gate is what is wrong.
    """
    report = gate.check_file(repo_root / "packages" / "omniweave-office" / "pyproject.toml")
    pins = [
        occurrence
        for occurrence in report.occurrences
        if occurrence.raw == "firecrawl-anydoc == 0.2.4"
    ]
    assert len(pins) == 1, report.occurrences
    assert pins[0].operators == ("==",)
    assert pins[0].justified, "section 8.5 states this pin carries its justification"


def test_the_port_major_ceiling_is_a_tightened_bound_like_any_other(
    gate: ModuleType, repo_root: Path
) -> None:
    """`omniweave-ports >=1,<2` carries a `<` and G7 states no exemption for it.

    This is the wave's substantive judgement and it is pinned rather than left to the reader.
    11-repo-layout.md:1126 gives the ceiling its reason -- *"Port major | `omniweave-ports >=1,<2`
    for the life of Port 1 | a Port 2 is a new distribution version"* -- which is precisely the
    sentence a one-line comment beside the bound should cite. Section 8.5 grants no role exemption
    to a first-party sibling, and inventing one would be inventing a register row.
    """
    report = gate.check_file(repo_root / "packages" / "omniweave-pdf" / "pyproject.toml")
    ports = [
        occurrence
        for occurrence in report.occurrences
        if occurrence.raw == "omniweave-ports >=1,<2"
    ]
    assert len(ports) == 1, report.occurrences
    assert ports[0].operators == ("<",)


# ---------------------------------------------------------------------------
# Structural
# ---------------------------------------------------------------------------


def test_the_gate_imports_nothing_that_could_cost_it_its_two_second_budget(
    repo_root: Path,
) -> None:
    """`budget_s = 2` in `tools/gates.toml` is a requirement, and this is its enforcement.

    The gate reads fourteen small files twice. Nothing else. `subprocess`, `urllib`, `socket`,
    `http`, `importlib` and anything first-party are absent, and absent by test: the day someone
    resolves a requirement to check whether the pin is current is the day a policy lint starts
    needing a network, and a `gates` job step that needs a network is a flake with an exit code.
    """
    source = (repo_root / "tools" / "gate_pins.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    assert roots == {
        "__future__",
        "argparse",
        "collections",
        "dataclasses",
        "pathlib",
        "sys",
        "tomllib",
        "typing",
    }


def test_the_report_names_its_scope_and_its_operator_policy_on_every_run(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A gate whose subject silently shrank reports the same green as one that checked everything.

    So the file count, the constraint count, the tightened count, the operator policy and the list
    of covered sites are part of the output contract, printed on a pass as well as a fail --
    `tools/gate_budgets.py` prints its two counts unconditionally for the same reason.
    """
    code, out = _run(gate, _workspace(tmp_path, 'dependencies = ["pkg>=1"]\n'), capsys)
    assert code == 0, out
    assert "1 pyproject.toml file(s), 3 version constraint(s) parsed" in out
    assert "0 tightened bound(s), 0 carrying an adjacent comment, 0 not" in out
    # A WHOLE line, newline to newline, and not a leading fragment. `"tightening: === == ~= <= <"`
    # is a substring of `"tightening: === == ~= <= < >"`, so a fragment assertion passes an
    # operator set that grew a spelling -- `>` promoted to tightening would fail every floor in
    # the tree and this assertion would not notice. Adversarial verification found exactly that.
    assert "\n  tightening: === == ~= <= <\n" in out
    assert (
        "\n  not tightening: >= > != (a floor, and section 8.5's sanctioned `!=` exclusion)\n"
    ) in out
    for site in (
        "project.requires-python",
        "project.dependencies",
        "project.optional-dependencies.<extra>",
        "build-system.requires",
        "dependency-groups.<group>",
        "tool.uv.constraint-dependencies",
    ):
        assert site in out, out


def test_a_constraint_shaped_key_at_an_uncovered_path_is_named_rather_than_ignored(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The anti-rot half of the scope: "complete over the fourteen files today" expires.

    A `[tool.poetry] dependencies` table, or a future `[tool.uv]` array this gate has not learned,
    would otherwise sit unexamined behind a green. It is a `NOTE` and not a finding because the
    gate has no basis for a verdict on a site it does not read -- but silence would be a verdict.
    """
    body = '[tool.poetry]\ndependencies = { pkg = "^1.0" }\n'
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 0, out
    assert "NOTE" in out
    assert "tool.poetry.dependencies" in out


# ---------------------------------------------------------------------------
# Adversarial verification: the eight claims that had no test at all
#
# Everything below this line was written after mutating `tools/gate_pins.py` and watching the
# suite above stay GREEN. Each test names the mutation it kills, because a test whose motive is
# lost is a test the next reader deletes as redundant.
# ---------------------------------------------------------------------------


def test_the_no_argument_invocation_is_the_one_ci_uses_and_it_reaches_the_workspace(
    gate: ModuleType, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`REPO` had no test, and `REPO` is the only root CI ever uses.

    `tools/gates.toml`'s G7 row sets `runner = ["tools/gate_pins.py"]` and
    `.github/workflows/ci.yml` runs it as `uv run --no-project tools/gate_pins.py` -- no
    `--root`, no `--glob`. Every other test in this file injects `--root`, so
    `REPO = Path(__file__).resolve().parents[1]` was asserted by nothing: changing it to
    `parents[0]` left all fifty-three tests green while the CI invocation exited 2 forever.

    `main([])` and not `main(None)`: `main(None)` hands `parse_args` `sys.argv[1:]`, which under
    pytest is pytest's own argv. `[]` is what CI's `argv[1:]` actually is, and it takes the same
    default-root and default-glob branches.

    The exit code is deliberately NOT pinned to 0 or 1 -- that is a fact about today's fourteen
    files and belongs to whoever writes a bound. What is pinned is that the gate RAN: exit 2 and
    the words "DID NOT RUN" are the failure this test exists to catch. `repo_root` comes from
    `conftest._find_repo_root`, which walks up from the conftest, so the two sides of the root
    equality are derived independently and it pins a value rather than agreement.
    """
    code = gate.main([])
    out = capsys.readouterr().out
    assert code != 2, f"the default root did not resolve to a workspace\n{out}"
    assert "G7 DID NOT RUN" not in out, out
    assert f"G7 gate_pins: {repo_root}" in out, out
    assert f"{WORKSPACE_MEMBERS} pyproject.toml file(s)" in out, out
    assert "glob(s): packages/*/pyproject.toml" in out, out


def test_the_glob_flag_reaches_the_root_pyproject_the_registered_scope_leaves_out(
    gate: ModuleType, repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--glob` was accepted, parsed, and then had no test that it was OBEYED.

    `globs = tuple(args.glob) if args.glob else DEFAULT_GLOBS` could be replaced by
    `globs = DEFAULT_GLOBS` with the whole suite green. That matters beyond tidiness: the module
    docstring's answer to "why is the workspace root out of scope" is *"it is reachable with
    `--glob pyproject.toml`"*, which is the escape hatch for the finding this wave filed about
    the root's own `[dependency-groups] dev`. An escape hatch nothing exercises is a sentence.

    The root's exit code is not pinned here, for the same reason as above; the file COUNT is,
    and one is not fourteen.
    """
    code = gate.main(["--root", str(repo_root), "--glob", "pyproject.toml"])
    out = capsys.readouterr().out
    assert code != 2, out
    assert "glob(s): pyproject.toml" in out, out
    assert "1 pyproject.toml file(s)" in out, out


def test_the_same_file_named_by_two_globs_is_checked_once(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_targets` de-duplicates, and dropping the de-duplication left the suite green.

    A doubled file doubles every count the report prints and prints every finding twice. The
    counts are the output contract -- `_report`'s own docstring says a linter whose subject
    silently changed size reports the same green as one that checked the right set -- so a
    doubled subject is a corrupted contract and not a cosmetic repeat.
    """
    root = _workspace(tmp_path, 'dependencies = ["pkg==1.0"]\n')
    code = gate.main(
        [
            "--root",
            str(root),
            "--glob",
            "packages/*/pyproject.toml",
            "--glob",
            "packages/demo/pyproject.toml",
        ]
    )
    out = capsys.readouterr().out
    assert code == 1, out
    assert "1 pyproject.toml file(s), 3 version constraint(s) parsed" in out, out
    assert "1 tightened bound(s), 0 carrying an adjacent comment, 1 not" in out, out
    assert out.count("'pkg==1.0' carries ==") == 1, out


def test_a_directory_named_pyproject_toml_is_not_read_as_a_file(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_targets`'s `is_file()` guard had no test either, and it is the difference between a
    gate that checks the readable files and a gate that exits 2 for everyone.

    A `pyproject.toml` DIRECTORY is what a half-finished checkout, a stale build tree or a
    case-insensitive filesystem collision leaves behind. Without the guard the glob matches it,
    `_load` fails to read it, and the whole run becomes exit 2 -- so one piece of filesystem
    debris suppresses the verdict on every other package.
    """
    root = _workspace(tmp_path, 'dependencies = ["pkg==1.0"]\n')
    (root / "packages" / "debris" / "pyproject.toml").mkdir(parents=True)
    code = gate.main(["--root", str(root)])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "G7 DID NOT RUN" not in out, out
    assert "1 pyproject.toml file(s)" in out, out
    assert "'pkg==1.0' carries ==" in out, out


def test_a_bound_in_each_of_the_four_uv_requirement_arrays_is_checked(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Three of `UV_ARRAY_KEYS`'s four entries were covered by nothing but a docstring.

    `test_a_bound_in_every_covered_site_is_checked_and_none_is_silently_skipped` reaches
    `tool.uv.constraint-dependencies` and stops there, so `UV_ARRAY_KEYS` could be cut to that
    one key with the suite green. The docstring's claim is *"None is used in the fourteen files
    today, and all four are covered anyway"*, and a claim about a site no file exercises is
    exactly the assertion-over-an-empty-collection shape: it has to be shown a bound, or it is
    not a claim.

    `override-dependencies` is the consequential one -- it rewrites another distribution's
    declared bound, which is the one place a ceiling can appear that no package author wrote.
    """
    body = (
        "[tool.uv]\n"
        'constraint-dependencies = ["a<1"]\n'
        'override-dependencies = ["b==2"]\n'
        'dev-dependencies = ["c~=3.0"]\n'
        'build-constraint-dependencies = ["d<=4"]\n'
    )
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 1, out
    assert "4 tightened bound(s), 0 carrying an adjacent comment, 4 not" in out, out
    for site, bound, operator in (
        ("tool.uv.constraint-dependencies[0]", "a<1", "<"),
        ("tool.uv.override-dependencies[0]", "b==2", "=="),
        ("tool.uv.dev-dependencies[0]", "c~=3.0", "~="),
        ("tool.uv.build-constraint-dependencies[0]", "d<=4", "<="),
    ):
        expected = f"'{bound}' carries {operator} and no adjacent comment (a bound at {site})"
        assert expected in out, f"{site} was not checked\n{out}"


def test_a_finding_names_the_remediation_and_not_only_the_offending_bound(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`_WHY` could be blanked to the empty string with all fifty-three tests green.

    Every red test above asserted the middle line of the finding -- which bound, which operator
    -- and none asserted the third. That is the line telling the reader what to do, and
    14-security.md:1275-1276 is why it is not optional: *"**G7** enforces the rule that makes the
    policy auditable"*. A gate that says "this is wrong" without saying "against this rule, and
    here is what the comment must contain" is a gate whose output a developer routes around, and
    section 8.5's role table plus 11-repo-layout.md:2283-2284's PR field are the two things the
    line has to point at.
    """
    code, out = _run(gate, _workspace(tmp_path, 'dependencies = ["pkg==1.0"]\n'), capsys)
    assert code == 1, out
    assert "11-repo-layout.md section 8.5" in out, out
    assert "tools/gates.toml G7" in out, out
    assert "on the line above or below" in out, out
    assert "the owner, the refresh procedure, the review date and the issue link" in out, out


def test_a_constraint_shaped_key_of_every_family_at_an_uncovered_path_is_named(
    gate: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`CONSTRAINT_KEY_NAMES` could be cut from five families to one with the suite green.

    The existing NOTE test shows the sweep a `tool.poetry.dependencies` table and nothing else,
    so `requires`, `requires-python`, `optional-dependencies` and all four `[tool.uv]` array
    names could be deleted from the sweep without a single red. The sweep is the anti-rot half of
    the scope -- the half that answers "what did this green NOT cover" -- and a sweep that
    recognises one of the five spellings reports silence as coverage.
    """
    body = (
        "[tool.poetry]\n"
        'requires-python = "^3.11"\n'
        'requires = ["x==1"]\n'
        'dependencies = { pkg = "^1.0" }\n'
        'dev-dependencies = ["y==2"]\n'
        'optional-dependencies = { extra = ["z==3"] }\n'
    )
    code, out = _run(gate, _workspace(tmp_path, body), capsys)
    assert code == 0, out
    assert "0 tightened bound(s), 0 carrying an adjacent comment, 0 not" in out, out
    for path in (
        "tool.poetry.requires-python",
        "tool.poetry.requires",
        "tool.poetry.dependencies",
        "tool.poetry.dev-dependencies",
        "tool.poetry.optional-dependencies",
    ):
        note = f"carries {path}, a constraint-shaped key at a path this gate does not read"
        assert note in out, f"{path} not swept\n{out}"


# ---------------------------------------------------------------------------
# `_split_line`'s three string-state guards, none of which had a test
# ---------------------------------------------------------------------------


def test_a_literal_string_ending_in_a_backslash_does_not_swallow_the_comment_beside_it(
    gate: ModuleType,
) -> None:
    """TOML literal strings have NO escapes, and `_split_line` tests the delimiter before it
    consumes one. Deleting that test of the delimiter left the suite green.

    `p = 'C:\'` is a valid TOML literal string holding one backslash. Treat the backslash as an
    escape and the closing quote is skipped, the scanner stays inside a string for the rest of
    the line, and the trailing comment vanishes -- a justification silently downgraded to no
    comment at all, which is the false POSITIVE direction of this gate and the one that makes a
    developer stop believing it.
    """
    lines = gate.scan("p = 'C:\\'  # a justification that must survive\n")
    assert lines[0].comment == " a justification that must survive"
    assert lines[0].code == "p = 'C:\\'  "


def test_an_escaped_quote_in_a_basic_string_does_not_end_it(gate: ModuleType) -> None:
    """The other half of the same guard: basic strings DO honour escapes, and dropping the
    escape branch altogether also left the suite green.

    `a = "x\"# y"` is one basic string holding a quote and a `#`. Read the escaped quote as the
    terminator and the `#` inside the string becomes the start of a comment, so the scanner
    reports a comment that is really string content -- the false NEGATIVE direction: text that
    was never a justification, credited as one.
    """
    lines = gate.scan('a = "x\\"# y"  # the real comment\n')
    assert lines[0].comment == " the real comment"
    assert lines[0].code == 'a = "x\\"# y"  '


def test_an_unterminated_single_line_string_does_not_leak_into_the_next_line(
    gate: ModuleType,
) -> None:
    """Only the triple delimiters carry string state across a line break, and the guard that
    says so -- `delimiter if delimiter in _MULTILINE_DELIMITERS else None` -- had no test.

    Return the bare quote instead and one unterminated string turns every following line of the
    file into string content: no comment is seen anywhere below it, so every tightened bound in
    the file becomes an unjustified finding. `scan` is exported in `__all__` and is the gate's
    public text pass, so the guard is asserted here directly rather than left to the TOML parser
    to catch by accident.
    """
    lines = gate.scan("a = 'x\nb = 1  # after\n")
    assert lines[0].comment is None
    assert lines[1].comment == " after", "the unterminated quote leaked across the line break"
    assert lines[1].code == "b = 1  "
