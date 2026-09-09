"""G27(b)'s own tests: every failure it exists to catch, driven over synthetic migration sets.

The gate is `tools/gate_migrations.py` and its subject is a *directory*, so these tests build
directories in `tmp_path` and point the gate at them with `--migrations`. The real
`omniweave_core/store/schema/migrations/` is **read and never written**: it is asserted to PASS in
one test of its own, which is what stops every other test here from being a proof about synthetic
SQL and nothing else.

Six shapes must be proven red, because each is a failure the gate is the only witness for and a
gate that cannot fail is worse than no gate:

* two files numbered `0004` — 11-repo-layout.md section 5.2's concurrent-PR collision, asserted
  against the **specified output shape** at 11-repo-layout.md:1272-1278 line for line, because
  that block is normative and not illustrative;
* a gap (`0004` and `0006`, no `0005`) — the quieter and worse case, which raises nothing at apply
  time (11:1235-1239) and which the `migration` primary key cannot see (11:1246-1247);
* a mis-named file (`4_init.sql`, `0004init.sql`) — 11:1188's four digits;
* an index on a table a later file creates — 11:1190-1191's recorded defect, where the migration
  aborts and neither file applies;
* `index_state` holding two `schema` rows, and `meta` holding a `schema` key — the two directions
  of the end-of-run single-home assertion (11:1196-1202, ADR-9).

Plus a **green synthetic control**. Without it, a bug that made the gate fail on everything would
leave the six red tests passing and only the one real-set test red, which is the least informative
possible arrangement of the same evidence.

`view` is injected as a tagless `TagView` in every synthetic test, so nothing here runs `git`: the
tag boundary has its own tests, which drive `check_append_only` over canned `git diff` output
rather than over this repository's history.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from io import StringIO
from pathlib import Path

import pytest
from omniweave_core.contract import SCHEMA_STRING
from omniweave_core.limits import MIN_SQLITE


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "gate_migrations.py"

# The gate is a script in `tools/`, not a distribution, so there is no package to import it from.
# `spec_from_file_location` loads it by path -- not `importlib.import_module`, which is banned
# outside `host/`, and not a `sys.path` mutation, which would leak into every later test. The
# module is registered before execution because `@dataclass(slots=True)` resolves annotations
# through `sys.modules[cls.__module__].__dict__`.
_SPEC = importlib.util.spec_from_file_location("omniweave_gate_migrations", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - the file is in this repository
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


# ---------------------------------------------------------------------------
# Building a synthetic migration set
# ---------------------------------------------------------------------------

# The two homes, reduced to the two columns the single-home assertion reads. `meta` is
# `0001_init.sql:61` and `index_state` is `0003_index.sql:406`; a synthetic set carries both in one
# file because these tests are about the migration SET's shape and never about which layer a table
# belongs to, which is `tools/gate_schema_lint.py`'s question.
HOMES = """\
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE index_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

# `index_state` WITHOUT the primary key, which is the only way a set can present two `schema` rows
# at once. With `k TEXT PRIMARY KEY` the second INSERT aborts inside the migration and the gate
# reports an apply failure instead -- a true report, but of a different check than the one under
# test, so the fixture drops the constraint to isolate the assertion.
TWO_HOMES = """\
CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE index_state (k TEXT NOT NULL, v TEXT NOT NULL);
INSERT INTO index_state (k, v) VALUES ('schema', '1.0');
INSERT INTO index_state (k, v) VALUES ('schema', '2.0');
"""

# S608 reads an INSERT built by concatenation as an injection vector. These two are migration
# FILE CONTENT, with every value literal in the text and no interpolation anywhere: the gate
# writes them to disk and SQLite reads them from there, so there is no query being built and no
# parameter that could be bound. The rule's subject is a query assembled from a caller's data.
SCHEMA_KEY_IN_META = HOMES + "INSERT INTO meta (k, v) VALUES ('schema', '1.0');\n"  # noqa: S608

WRONG_SCHEMA_VALUE = HOMES + "INSERT INTO index_state (k, v) VALUES ('schema', '9.9');\n"  # noqa: S608


def _set(tmp_path: Path, files: dict[str, str]) -> Path:
    """`files` written into `<tmp_path>/schema/migrations/`, whose path is returned.

    The last two components are `schema/migrations` on purpose: the gate names a directory in a
    failure message by its own last two components (`gate.label`), so a synthetic set laid out
    this way produces the specimen output at 11-repo-layout.md:1272 verbatim rather than an
    approximation of it.
    """
    root = tmp_path / "schema" / "migrations"
    root.mkdir(parents=True)
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def _no_tag() -> object:
    """A tagless boundary, so a synthetic test never reads this repository's git history."""
    return gate.TagView(tag=None, files=frozenset(), reason="no previous tag")


def _run(
    root: Path, *, view: object | None = None, argv: list[str] | None = None
) -> tuple[int, str]:
    """The gate over `root`, returning its exit code and everything it wrote."""
    buffer = StringIO()
    arguments = ["--migrations", str(root), *(argv or [])]
    code = gate.main(arguments, out=buffer, view=view if view is not None else _no_tag())
    return code, buffer.getvalue()


def _fail_headlines(output: str) -> list[str]:
    """Every `G27b FAIL  <headline>` line, prefix stripped, summary line excluded."""
    return [
        line.removeprefix(gate.FAIL_PREFIX)
        for line in output.splitlines()
        if line.startswith(gate.FAIL_PREFIX) and "finding(s) over" not in line
    ]


# ---------------------------------------------------------------------------
# The shipped set, and a green synthetic control
# ---------------------------------------------------------------------------


def test_the_shipped_migration_set_passes() -> None:
    """The non-vacuity test: every red test below is a proof about synthetic SQL until this passes.

    It also pins the location settled by `_plan/_notes/build-defects.md` D12 -- the DDL is
    `omniweave-core` package data under `omniweave_core/store/`, not a repo-root `schema/` -- and
    it asserts the count so an accidentally-empty directory reads as a failure rather than as four
    checks that had nothing to check.
    """
    assert gate.MIGRATIONS.is_dir(), f"no migration set at {gate.MIGRATIONS}"
    files = gate.migration_files(gate.MIGRATIONS)
    assert len(files) >= 4, f"expected the four shipped migrations, found {len(files)}"
    code, output = _run(gate.MIGRATIONS)
    assert code == gate.EXIT_CLEAN, output
    assert "G27b ok" in output


def test_the_shipped_set_is_applied_to_a_real_file_in_wal_mode() -> None:
    """An empty FILE and not `:memory:`, which is the premise the apply check rests on.

    `journal_mode = WAL` and its `-wal`/`-shm` sidecars exist only for a file-backed database
    (07-store-and-retrieval.md:168-176), and `:memory:` silently reports `journal_mode = memory`
    instead of refusing -- so the mode is asserted rather than assumed.
    """
    _, output = _run(gate.MIGRATIONS)
    assert "  file        a real file, journal_mode = wal" in output


def test_the_shipped_set_reports_the_end_of_run_single_home(tmp_path: Path) -> None:
    """The anchor is the END of the run, and the report says which of the two homes wrote the row.

    `0003_index.sql:37-38` states that the tables ship empty and the RUNNER writes
    `index_state.schema`, so the shipped set reaches this check with the key unset and the gate
    performs the runner's one write. The line names that, because a reader who assumed the DDL
    seeded it would be reading a stronger claim than the gate makes.
    """
    _, output = _run(gate.MIGRATIONS)
    assert f'index_state.schema = "{SCHEMA_STRING}" (written here, as the runner does)' in output
    assert "meta holds no schema key" in output
    # And the same check, on a set that seeds the row itself, reports the other origin.
    root = _set(
        tmp_path,
        {
            "0001_init.sql": HOMES.replace(
                "CREATE TABLE index_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);",
                "CREATE TABLE index_state (k TEXT PRIMARY KEY, v TEXT NOT NULL);\n"
                f"INSERT INTO index_state (k, v) VALUES ('schema', '{SCHEMA_STRING}');",
            )
        },
    )
    code, output = _run(root)
    assert code == gate.EXIT_CLEAN, output
    assert "(seeded by the migration set)" in output


def test_a_minimal_synthetic_set_passes(tmp_path: Path) -> None:
    """The green control. Without it, a gate that failed on everything would look well tested."""
    root = _set(tmp_path, {"0001_init.sql": HOMES, "0002_more.sql": "CREATE TABLE t (a TEXT);\n"})
    code, output = _run(root)
    assert code == gate.EXIT_CLEAN, output
    assert "  density     0001..0002, no duplicate and no gap" in output


# ---------------------------------------------------------------------------
# Check 2: the section 5.2 collision, in section 5.2's own output shape
# ---------------------------------------------------------------------------


def test_two_files_numbered_0004_fail(tmp_path: Path) -> None:
    """The collision each PR passes in isolation (11-repo-layout.md:1232-1239).

    Both files apply cleanly to an empty file on their own, which is exactly why applicability
    cannot be the whole of G27(b); the failure names BOTH files, because "one of your migrations
    is duplicated" is not a message anyone can act on.
    """
    root = _set(
        tmp_path,
        {
            "0001_init.sql": HOMES,
            "0004_anchor_akind.sql": "CREATE TABLE anchor_a (a TEXT);\n",
            "0004_segment_cover.sql": "CREATE TABLE segment_c (a TEXT);\n",
        },
    )
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    headlines = _fail_headlines(output)
    assert "schema/migrations/ has two files numbered 0004:" in headlines
    assert "0004_anchor_akind.sql" in output
    assert "0004_segment_cover.sql" in output
    assert "migration.version is an INTEGER PRIMARY KEY" in output


def test_the_collision_report_matches_the_specified_output_shape(tmp_path: Path) -> None:
    """11-repo-layout.md:1270-1279 is a specification of the output, not an illustration of it.

    So this test asserts the block line for line, with the tag boundary injected as the specimen's
    own `v0.4.1`: the published file is annotated `PUBLISHED -- never renumber`, the branch file is
    annotated `new on this branch`, the fix names the NEW file's next free number, and the last
    line forbids touching the shipped one. Column alignment is part of the shape and is asserted
    with it -- the two annotations begin in the same column, which is what makes the pair readable
    at a glance in a CI log.
    """
    root = _set(
        tmp_path,
        {
            "0001_init.sql": HOMES,
            "0002_two.sql": "CREATE TABLE t2 (a TEXT);\n",
            "0003_three.sql": "CREATE TABLE t3 (a TEXT);\n",
            "0004_anchor_akind.sql": "CREATE TABLE anchor_a (a TEXT);\n",
            "0004_segment_cover.sql": "CREATE TABLE segment_c (a TEXT);\n",
        },
    )
    view = gate.TagView(tag="v0.4.1", files=frozenset({"0004_anchor_akind.sql"}))
    code, output = _run(root, view=view)
    assert code == gate.EXIT_FAIL
    lines = output.splitlines()
    start = lines.index("G27b FAIL  schema/migrations/ has two files numbered 0004:")
    assert lines[start : start + 7] == [
        "G27b FAIL  schema/migrations/ has two files numbered 0004:",
        "             0004_anchor_akind.sql   (in v0.4.1, PUBLISHED — never renumber)",
        "             0004_segment_cover.sql  (new on this branch)",
        "           migration.version is an INTEGER PRIMARY KEY, so both would insert version 4 "
        "and the",
        "           second would abort on every store that applied the first.",
        "           fix: rebase on the default branch and rename the NEW file to "
        "0005_segment_cover.sql.",
        "           Do not touch 0004_anchor_akind.sql: v0.4.1 shipped it.",
    ]


def test_a_collision_with_no_previous_tag_says_publication_is_unknown(tmp_path: Path) -> None:
    """This repository has no tag, so the annotation may not claim either file is published.

    The specimen's `(in v0.4.1, PUBLISHED)` / `(new on this branch)` pair is a *derived* fact about
    the tag, and deriving it from nothing would be the silent guess rule 7 of this project's own
    build discipline forbids. The gate says `publication unknown` and still fails.
    """
    root = _set(
        tmp_path,
        {
            "0001_init.sql": HOMES,
            "0002_a.sql": "CREATE TABLE a (x TEXT);\n",
            "0002_b.sql": "CREATE TABLE b (x TEXT);\n",
        },
    )
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert output.count("(no previous tag — publication unknown)") == 2
    assert "renumber the file that is new on this branch to 0003_<its slug>.sql" in output


# ---------------------------------------------------------------------------
# Check 3: density
# ---------------------------------------------------------------------------


def test_a_gap_in_the_numbering_fails(tmp_path: Path) -> None:
    """`0004` and `0006` with no `0005`: the case the `migration` primary key cannot see.

    11-repo-layout.md:1246-1247 is the whole argument for this check existing separately -- "a
    pleasing redundancy and not a substitute, because a gap raises nothing". The set below applies
    cleanly in numeric order and is still wrong, so nothing but a static density check finds it.
    """
    root = _set(
        tmp_path,
        {
            "0001_init.sql": HOMES,
            "0002_two.sql": "CREATE TABLE t2 (a TEXT);\n",
            "0003_three.sql": "CREATE TABLE t3 (a TEXT);\n",
            "0004_four.sql": "CREATE TABLE t4 (a TEXT);\n",
            "0006_six.sql": "CREATE TABLE t6 (a TEXT);\n",
        },
    )
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert "schema/migrations/ is not dense: 0005 is missing." in _fail_headlines(output)
    assert "present  0001, 0002, 0003, 0004, 0006" in output
    assert "OUT OF INTENDED ORDER" in output


def test_a_set_that_does_not_start_at_0001_fails_as_a_missing_0001(tmp_path: Path) -> None:
    """Density is `1..N`, so "starts at 0002" and "0001 is missing" are the same defect.

    One check rather than two, because two would have to agree about a set numbered `0003, 0004`
    and the honest report there names both absences.
    """
    root = _set(tmp_path, {"0002_two.sql": HOMES, "0003_three.sql": "CREATE TABLE t3 (a TEXT);\n"})
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert "schema/migrations/ is not dense: 0001 is missing." in _fail_headlines(output)


def test_a_structural_failure_does_not_silently_drop_the_tag_boundary(tmp_path: Path) -> None:
    """A red density check must not take check 6's line with it.

    Checks 1-3 gate the apply (11:1245, "and only then applies them in order"), but check 6 reads
    git and never the database, so it runs either way. A run that printed neither an append-only
    line nor a SKIP would leave a reader unable to tell which.
    """
    root = _set(tmp_path, {"0002_two.sql": HOMES})
    _, output = _run(root)
    assert "  append-only SKIP (no previous tag)" in output
    assert "  order       NOT ESTABLISHED" in output


# ---------------------------------------------------------------------------
# Check 1: naming
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["4_init.sql", "0004init.sql", "004_init.sql", "0004_Init.sql"])
def test_a_misnamed_migration_fails(tmp_path: Path, name: str) -> None:
    """`NNNN_<slug>.sql`, four digits (11-repo-layout.md:1188).

    `4_init.sql` has a prefix that is not four digits; `0004init.sql` has no separator, so the
    prefix is not delimited at all; `004_init.sql` is three digits, which sorts wrongly against
    `0010_*`; `0004_Init.sql` would make the slug's alphabet unbounded, and the prefix stops being
    the only thing before the first underscore the moment case is free.
    """
    root = _set(tmp_path, {"0001_init.sql": HOMES, name: "CREATE TABLE t (a TEXT);\n"})
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert f"schema/migrations/{name} is not NNNN_<slug>.sql." in _fail_headlines(output)


# ---------------------------------------------------------------------------
# Check 4: applicability, and the recorded forward-reference defect
# ---------------------------------------------------------------------------


def test_an_index_on_a_table_a_later_file_creates_aborts_the_run(tmp_path: Path) -> None:
    """11-repo-layout.md:1190-1191's recorded defect, reproduced.

    An index resolves its table at `CREATE INDEX`, so `0002` naming a table `0003` creates aborts,
    its transaction rolls back and NEITHER FILE APPLIES. This is the failure the whole apply half
    of G27(b) exists for, and it is invisible to any check that reads the `.sql` text: the SQL is
    valid, every identifier is spelled correctly, and only the ORDER is wrong.
    """
    root = _set(
        tmp_path,
        {
            "0001_init.sql": HOMES,
            "0002_index.sql": "CREATE INDEX thing_name_ix ON thing(name);\n",
            "0003_table.sql": "CREATE TABLE thing (name TEXT);\n",
        },
    )
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    headlines = _fail_headlines(output)
    assert any(line.startswith("0002_index.sql did not apply: no such table") for line in headlines)
    assert "applied before it  0001_init.sql" in output
    assert "NEITHER FILE APPLIES" in output


def test_a_view_with_a_forward_reference_survives_lazily(tmp_path: Path) -> None:
    """The other half of 07-store-and-retrieval.md:250-256's three-way rule, asserted as a PASS.

    "A view survives a forward reference lazily; an index and a foreign key do not." A gate that
    failed on the view too would be enforcing a rule the plan does not state, and would reject
    `ow_block_head`-shaped DDL that the shipped set is entitled to write.
    """
    root = _set(
        tmp_path,
        {
            "0001_init.sql": HOMES,
            "0002_view.sql": "CREATE VIEW thing_v AS SELECT name FROM thing;\n",
            "0003_table.sql": "CREATE TABLE thing (name TEXT);\n",
        },
    )
    code, output = _run(root)
    assert code == gate.EXIT_CLEAN, output


# ---------------------------------------------------------------------------
# Check 5: the end-of-run single home
# ---------------------------------------------------------------------------


def test_index_state_seeded_with_two_schema_rows_fails(tmp_path: Path) -> None:
    """ "Exactly one `schema` row" (11-repo-layout.md:1197-1199, ADR-9).

    Two rows are two answers to `<major>.<minor>` and a reader has no way to pick, which is the
    whole content of the single-home rule. Asserted at the END of the run, because `index_state`
    is `0003_index.sql`'s and an assertion anchored on `0001` could not run at all.
    """
    root = _set(tmp_path, {"0001_init.sql": TWO_HOMES})
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert "index_state holds 2 rows keyed `schema`." in _fail_headlines(output)
    assert "v = '1.0'" in output
    assert "v = '2.0'" in output


def test_a_schema_key_in_meta_fails(tmp_path: Path) -> None:
    """ "`meta` holds no `schema` key at all" -- the other direction, and the one ADR-9 exists for.

    `0001_init.sql:64-66`: "`meta` NEVER gains a `schema` key: the sole disk home for SCHEMA is
    `index_state.schema`". This half has teeth against the DDL in a way the row's value does not:
    nothing in this gate writes to `meta`, so a `schema` key there came from a migration.
    """
    root = _set(tmp_path, {"0001_init.sql": SCHEMA_KEY_IN_META})
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert "meta holds a `schema` key ('1.0')." in _fail_headlines(output)
    assert "ADR-9 decision 3" in output


def test_a_seeded_schema_row_that_disagrees_with_contract_fails(tmp_path: Path) -> None:
    """The value equals `f"{SCHEMA}.{SCHEMA_MINOR}"` read from `omniweave_core.contract` (11:1198).

    Read from `contract`, never transcribed: `SCHEMA_STRING` is the one site that formats the pair
    (`0003_index.sql:409-412`), so this assertion cannot drift from the constant it checks.
    """
    root = _set(tmp_path, {"0001_init.sql": WRONG_SCHEMA_VALUE})
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert f"index_state.schema is '9.9', not '{SCHEMA_STRING}'." in _fail_headlines(output)


def test_a_set_that_creates_neither_home_fails(tmp_path: Path) -> None:
    """No `index_state` means no home for SCHEMA, which is a failure and not an absent check."""
    root = _set(tmp_path, {"0001_init.sql": "CREATE TABLE t (a TEXT);\n"})
    code, output = _run(root)
    assert code == gate.EXIT_FAIL
    assert "meta does not exist after the last migration." in _fail_headlines(output)
    assert "index_state does not exist after the last migration." in _fail_headlines(output)


# ---------------------------------------------------------------------------
# Check 6: append-only against the previous tag
# ---------------------------------------------------------------------------


def test_the_append_only_check_skips_on_its_own_line_with_no_previous_tag() -> None:
    """A workflow that bounds its coverage says what it dropped, so the SKIP is on its own line.

    This repository holds no tag, so there is nothing to diff against and check 6 cannot run. It
    reports `SKIP (no previous tag)` and the gate still exits 0 -- a silent pass would read as an
    assertion that held, which is the one outcome this line exists to prevent.
    """
    report, failures = gate.check_append_only(_no_tag())
    assert report == ["  append-only SKIP (no previous tag)"]
    assert failures == []


def test_the_real_repository_currently_has_no_previous_tag() -> None:
    """The premise of the test above, asserted rather than assumed.

    The day this repository is tagged, this test goes red and the SKIP stops being the expected
    path -- which is the right moment for someone to read `check_append_only` against a real tag.
    """
    view = gate.previous_tag()
    assert view.tag is None, f"the repository now has tag {view.tag}: exercise check 6 for real"
    assert view.reason == "no previous tag"


@pytest.mark.parametrize(
    ("diff", "expected"),
    [
        (
            "M\tpackages/omniweave-core/src/omniweave_core/store/schema/migrations/0001_init.sql\n",
            "0001_init.sql was edited in place, and v0.4.1 published it.",
        ),
        (
            "D\tpackages/omniweave-core/src/omniweave_core/store/schema/migrations/0001_init.sql\n",
            "0001_init.sql was deleted, and v0.4.1 published it.",
        ),
        (
            "R100\tpackages/omniweave-core/src/omniweave_core/store/schema/migrations/"
            "0001_init.sql\tpackages/omniweave-core/src/omniweave_core/store/schema/migrations/"
            "0002_init.sql\n",
            "0001_init.sql was renamed to 0002_init.sql, and v0.4.1 published it.",
        ),
    ],
)
def test_a_published_migration_may_not_be_edited_renamed_or_deleted(
    monkeypatch: pytest.MonkeyPatch, diff: str, expected: str
) -> None:
    """The boundary is the tag, not the merge (11-repo-layout.md:1261-1268).

    Driven over canned `git diff --name-status` output rather than over a scratch repository: the
    subject is how the gate READS a diff, and building a real tag would test git instead. The
    three statuses are the three ways a shipped file can stop being what it was, and each names
    the tag, because "a migration was edited" without the tag is not actionable.
    """
    monkeypatch.setattr(gate, "_git", lambda *_arguments: (0, diff))
    view = gate.TagView(tag="v0.4.1", files=frozenset({"0001_init.sql"}))
    _report, failures = gate.check_append_only(view)
    assert [failure.headline for failure in failures] == [expected]


def test_a_migration_added_since_the_tag_is_legal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Append-only means appending is the one legal move, and the report counts it.

    A file that has only ever existed on a branch is renumbered freely, because no store has
    applied it (11:1262-1264) -- so an `A` status is not a finding and must not be reported as
    one, or the rule would forbid the only thing it permits.
    """
    added = "A\tpackages/omniweave-core/src/omniweave_core/store/schema/migrations/0005_out.sql\n"
    monkeypatch.setattr(gate, "_git", lambda *_arguments: (0, added))
    view = gate.TagView(tag="v0.4.1", files=frozenset({"0001_init.sql"}))
    report, failures = gate.check_append_only(view)
    assert failures == []
    assert report == ["  append-only v0.4.1: 1 appended, 1 published"]


def test_the_git_pathspec_is_derived_from_the_migration_directory() -> None:
    """Not a second copy of the path, which is the bug this test was written after finding.

    `_plan/_notes/build-defects.md` D12 moved the DDL from a repo-root `schema/` into
    `omniweave_core/store/`, and a hard-coded `schema/migrations` pathspec would then have diffed
    a directory that no longer exists -- reporting "0 appended, 0 published" rather than an error,
    which is the silent pass check 6's SKIP line exists to make impossible.
    """
    assert gate.MIGRATIONS.relative_to(gate.REPO).as_posix() == gate.MIGRATIONS_PATHSPEC
    assert gate.MIGRATIONS_PATHSPEC.endswith("store/schema/migrations")
    assert "\\" not in gate.MIGRATIONS_PATHSPEC, "git takes a POSIX pathspec on every platform"


def test_an_unreadable_tag_skips_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """A shallow clone cannot see the tag, and an unrunnable check reports SKIP rather than pass.

    `fetch_depth = 0` on G27's row in `tools/gates.toml` is what makes the tag reachable in CI;
    this is what a local checkout without it looks like, and it is not a failure of the migration
    set.
    """
    monkeypatch.setattr(gate, "_git", lambda *_arguments: (128, "bad revision"))
    view = gate.TagView(tag="v0.4.1", files=frozenset({"0001_init.sql"}))
    report, failures = gate.check_append_only(view)
    assert failures == []
    assert report == ["  append-only SKIP (cannot diff v0.4.1: bad revision)"]


# ---------------------------------------------------------------------------
# The floor, and the arguments
# ---------------------------------------------------------------------------


def test_the_floor_defaults_to_min_sqlite_and_is_not_a_second_copy_of_it() -> None:
    """`--min-sqlite` overrides a default read from `omniweave_core.limits` (07:196).

    The gate imports the constant rather than transcribing it, so this test asserts the report
    names the imported value: a second copy of `(3, 42, 0)` in `tools/` is exactly the drift the
    single declared floor exists to prevent.
    """
    assert gate.MIN_SQLITE == MIN_SQLITE
    _, output = _run(gate.MIGRATIONS)
    spelled = ".".join(str(part) for part in MIN_SQLITE)
    assert f"(floor {spelled} from omniweave_core.limits.MIN_SQLITE)" in output


def test_an_interpreter_below_the_floor_is_refused_and_named_the_extra() -> None:
    """Refuse, do not fail: exit 2, because "the gate did not run" is not "the set is broken".

    The floor is three features deep -- STRICT tables 3.37.0, `unixepoch()` 3.38.0,
    `unixepoch('subsec')` 3.42.0 (07-store-and-retrieval.md:196-200) -- so a run below it reports
    syntax errors rather than defects, and the refusal names the extra that fixes it.
    """
    buffer = StringIO()
    code = gate.main(
        ["--min-sqlite", "99.0", "--migrations", str(gate.MIGRATIONS)],
        out=buffer,
        view=_no_tag(),
    )
    assert code == gate.EXIT_NOT_RUN
    output = buffer.getvalue()
    assert "G27b DID NOT RUN" in output
    assert "below the declared floor 99.0.0" in output
    assert "pip install omniweave-core[sqlite]" in output


@pytest.mark.parametrize(
    ("text", "expected"),
    [("3.42", (3, 42, 0)), ("3.42.0", (3, 42, 0)), ("3", (3, 0, 0)), ("3.45.1", (3, 45, 1))],
)
def test_a_version_parses_in_the_spelling_the_roadmap_uses(
    text: str, expected: tuple[int, int, int]
) -> None:
    """16-roadmap.md:441 invokes the gate as `--min-sqlite 3.42`, so two components is specified."""
    assert gate.parse_version(text) == expected


@pytest.mark.parametrize("text", ["", "3.x", "3.42.0.1", "v3.42", "3..0"])
def test_an_unusable_version_is_an_argument_error(text: str) -> None:
    with pytest.raises(ValueError, match="not a SQLite version"):
        gate.parse_version(text)


def test_a_missing_or_empty_directory_is_a_did_not_run(tmp_path: Path) -> None:
    """Exit 2 and not 1: CI treats both as failure and a human needs to know which."""
    buffer = StringIO()
    assert (
        gate.main(["--migrations", str(tmp_path / "absent")], out=buffer, view=_no_tag())
        == gate.EXIT_NOT_RUN
    )
    assert "no such directory" in buffer.getvalue()

    empty = tmp_path / "schema" / "migrations"
    empty.mkdir(parents=True)
    buffer = StringIO()
    assert gate.main(["--migrations", str(empty)], out=buffer, view=_no_tag()) == gate.EXIT_NOT_RUN
    assert "no *.sql in" in buffer.getvalue()


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------


def test_gates_toml_names_this_gate_as_a_live_runner() -> None:
    """The forcing function `tools/gates.toml` documents, satisfied in the commit that lands this.

    A path under `runner_planned` is the register saying "the plan names this script and nobody
    has written it", and `test_gates_register.py` asserts such a path does not exist. This gate
    exists, so its row carries it under `runner` -- and clause `b`, which already named it, is now
    naming a file rather than a future.
    """
    register = tomllib.loads((REPO_ROOT / "tools" / "gates.toml").read_text(encoding="utf-8"))
    row = next(gate_row for gate_row in register["gate"] if gate_row["id"] == "G27")
    assert "tools/gate_migrations.py" in row.get("runner", [])
    assert "tools/gate_migrations.py" not in row.get("runner_planned", [])
    clause = next(item for item in row["clause"] if item["id"] == "b")
    assert clause["runner"] == ["tools/gate_migrations.py"]
    assert clause["enabled"] is True
