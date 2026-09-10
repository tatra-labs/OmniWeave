"""`tools/gates.toml` against 11-repo-layout.md section 6.4, which is G27 clause d2 itself.

Section 6.4 opens with the whole of this file's justification: *"`tools/gates.toml` is the
register; this table is its rendering, and G27 clause d2 asserts the two agree."*
`tools/gate_docs.py` does not exist yet, so until it lands this file is that clause -- and it is
written to be the same check rather than a rehearsal of it: it reads the table out of
`_plan/11-repo-layout.md` at test time and compares it cell by cell, so a plan edit and a register
edit that disagree fail here.

Five properties, and the middle two are the ones that earn the file:

* **the register parses and its `G` set is dense and unique** -- ADR-2 made the series
  "append-by-ADR and its cardinality lives in the file", so nothing else in the tree can catch a
  gap or a duplicate. Section 1.7 makes the file append-only: a `G<n>` is never renumbered and
  never reused, exactly as an error code is not.
* **every named runner exists, and every `tools/gate_*.py` on disk is named** -- the second half is
  the forcing function. A gate script nobody registered is a blocking check no document can cite
  and `V10-1` cannot see, which is the exact hole `tools/gate_tombstones.py` sat in. The one
  qualification is `QG_SERIES_SCRIPTS`: `tools/gate_budgets.py` is a *`Q-G`* script, and
  11-repo-layout.md:397 forbids `tools/gates.toml` from naming a row `eval/gates.toml` owns, so it
  is registered elsewhere and the sweep asserts that in both directions rather than skipping it.
* **every `runner_planned` path does NOT exist** -- the other direction of the same forcing
  function. When someone writes `tools/gate_egress.py`, this test goes red until G15's row moves
  the path from `runner_planned` to `runner`, so the register cannot quietly keep describing a
  future that arrived.
* **the register agrees with the rendering row for row, in order** -- gate cell, job cell, `s`
  cell, nightly cell, release cell, for all twenty-nine `law` rows.
* **the counted claims section 6.4 states in prose are asserted as numbers** -- twenty-nine
  rendered rows, twenty-eight with a PR job, exactly one without, nine job assertions.

Two deliberate departures from a naive reading, both stated in the register's own header:

1. **A runner may serve more than one row.** `tools/gate_importtime.py` implements G9 and G23 (its
   docstring, and 16-roadmap.md:159's `# G9 + G23`) and `tools/gate_semgrep.py` implements G8 and
   G24 -- which is section 6.4's own reading of G24's `s` cell, "(in G8)". So the assertion is
   "named by at least one row", with the multi-row set pinned to those two: any third script
   serving two gates is a failure, because it would mean one failure message has to mean two
   things, which is what section 6.4 rejected when it declined to absorb G29 into G8.
2. **`G30` is in the register and not in the rendering.** It is `tools/gate_tombstones.py`, which
   blocks today and carries no `G<n>` anywhere in the plan. It is `status = "registered"` with a
   `pending` reason, and the rendering comparison runs over the `law` rows only.

Specified in 11-repo-layout.md sections 6.2, 6.4, 6.8, 8.6 and 8.7, ADR-1 decision 6, ADR-2
decision 4 and ADR-4.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import pytest

REGISTER = "tools/gates.toml"
LAYOUT = "11-repo-layout.md"

# Section 6.2's `ci-ok` needs list, in its own order, plus `ci-ok` itself. This is the whole job
# vocabulary a row may name; section 6.4 uses nine of the eleven (`golden` and `parity` carry no
# numbered row at release 1, which the register records as a comment rather than as an omission).
JOB_NAMES: tuple[str, ...] = (
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
    "ci-ok",
)

# 17-risks.md section 1.3's ten roles, which is the closed owner vocabulary. Section 6.8 requires
# an owner and a review date on every row; the plan assigns none, so the register authors them
# under one stated rule and this tuple is what stops the column drifting into an eleventh name.
OWNER_ROLES: frozenset[str] = frozenset(
    {
        "licence",
        "model",
        "drivers",
        "router",
        "runtime",
        "retrieval",
        "out",
        "surface",
        "quality",
        "release",
    }
)

# The runners that serve more than one gate row, and the only ones. See the module docstring.
SHARED_RUNNERS: dict[str, tuple[str, ...]] = {
    "tools/gate_importtime.py": ("G9", "G23"),
    "tools/gate_semgrep.py": ("G8", "G24"),
    # THE THIRD PAIR, and the one that is not from section 6.4's `s` column. G5 is the script's
    # own subject ("versions <-> tag"); G14's four clauses are ALSO implemented inside it, by
    # name, at tools/check_versions.py:411-460 ("no such extra (G14)", "G14 totality", "G14
    # injectivity"), and ci.yml honours G14's `gates` cell by running that script rather than
    # writing a second implementation inline.
    #
    # This pair does NOT weaken the "one failure message cannot mean two things" rule the
    # docstring cites for refusing a G29-into-G8 merge. That rule is about a gate whose single
    # exit code is ambiguous; `check_versions.py` reports per site class, so a failure names the
    # site it came from and is attributable to G5 or G14 without reading the job it ran in. The
    # two invocations are also in DIFFERENT jobs (`versions` and `gates`), each with its own
    # budget, which is the opposite of merging two gates into one cell.
    #
    # G14's row carried no runner until this was found: a blank field read as "nothing runs this",
    # which was false and let ci.yml execute the script in a job no row named.
    "tools/check_versions.py": ("G5", "G14"),
}

# ---------------------------------------------------------------------------------------------
# THE ONE BOUNDARY THIS REGISTER DOES NOT OWN: the static Q-G series' scripts.
#
# `tools/gate_*.py` is not the same set as "the G series". 11-repo-layout.md:393-397 states the
# split in as many words -- `eval/gates.toml` holds the metric gates and the Q-G series, owned by
# 13-quality.md; `tools/gates.toml` holds the G series, owned by 11-repo-layout.md; and "Neither
# file may name a row the other owns." 11-repo-layout.md:1615-1617 repeats it for exactly the
# rows at issue: the static Q-G series' "budgets, owners and review dates live in
# `eval/gates.toml`; this document only reserves them a job."
#
# So a Q-G script sitting under `tools/` is registered, just not HERE, and the on-disk sweep below
# must know the difference or it asks `tools/gates.toml` to violate its own boundary rule. This
# table is the difference, one row per script, each naming the plan line that assigns it:
#
#   tools/gate_budgets.py  ->  Q-G15.  13-quality.md:354-355 "So `tools/gate_budgets.py`, under
#   `Q-G15`, asserts one arithmetic property"; :368-371 adds the second, `process` clause;
#   13-quality.md:1999 is the Q-G register row ("Q-G15 perf | `G` | `eval/perf.toml` ...");
#   adr/0011-eval-register-reconciliation.md:117 calls it "already the `Q-G15` script".
#
# It is an ALLOW-LIST and not an exemption: the test asserts both directions, so a script named
# here that ALSO gained a `tools/gates.toml` row fails (that is the boundary violation), and a
# script named neither here nor in the register fails exactly as `tools/gate_tombstones.py` did.
# Adding a row here is therefore a deliberate act with a plan citation attached, not a way past a
# red test. `eval/gates.toml` does not exist in the tree yet -- P10 lands it (16-roadmap.md:68) --
# which is why the second column is the plan citation and not a file offset.
QG_SERIES_SCRIPTS: dict[str, str] = {
    "tools/gate_budgets.py": "Q-G15 (13-quality.md:354-355, :368-371, :1999)",
}

# The register keeps TOML values ASCII (house style); section 6.4's cells do not. Exactly this
# table, applied to the markdown side before comparing, and applied nowhere else. An em dash is
# not folded to text at all -- it is an EMPTY cell, and becomes a false boolean or an absent key.
FOLD: dict[str, str] = {"↔": "<->", "≡": "=="}
EMPTY_CELL = "—"


def fold(cell: str) -> str:
    """Section 6.4's cell text in the register's ASCII."""
    for source, target in FOLD.items():
        cell = cell.replace(source, target)
    return cell


# ---------------------------------------------------------------------------
# Reading the two sides
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def register(repo_root: Path) -> dict[str, Any]:
    """`tools/gates.toml`, parsed. The first assertion of this file is that this does not raise."""
    return tomllib.loads((repo_root / REGISTER).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def gates(register: dict[str, Any]) -> list[dict[str, Any]]:
    return list(register["gate"])


@pytest.fixture(scope="module")
def law_gates(gates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows section 6.4 renders. `status = "registered"` rows are appends it does not."""
    return [row for row in gates if row["status"] == "law"]


def _markdown_table(lines: tuple[str, ...], header_first_cell: str) -> list[list[str]]:
    """The rows of the first markdown table whose header's first cell matches, cells stripped.

    Line-oriented on purpose: the table is the rendering, and a parser clever enough to survive a
    reformat is a parser that could survive the table being wrong. The `|---|` separator is
    skipped and the table ends at the first line that is not a row.
    """
    rows: list[list[str]] = []
    inside = False
    for line in lines:
        stripped = line.strip()
        is_row = stripped.startswith("|") and stripped.endswith("|")
        if not inside:
            if is_row:
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                if cells and cells[0] == header_first_cell:
                    inside = True
            continue
        if not is_row:
            break
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        rows.append(cells)
    return rows


@pytest.fixture(scope="module")
def rendered_gates(plan: Any) -> list[list[str]]:
    """Section 6.4's gate table, read out of the plan at test time. This is clause d2's subject."""
    plan.require()
    rows = _markdown_table(plan.lines(LAYOUT), "gate")
    if not rows:
        pytest.fail("section 6.4's gate table did not parse -- every check below would be vacuous")
    return rows


@pytest.fixture(scope="module")
def rendered_assertions(plan: Any) -> list[list[str]]:
    """Section 6.4's `[[job_assertion]]` table."""
    plan.require()
    rows = _markdown_table(plan.lines(LAYOUT), "job assertion")
    if not rows:
        pytest.fail("section 6.4's job-assertion table did not parse")
    return rows


# ---------------------------------------------------------------------------
# Shape: the identifiers, the jobs, the budgets
# ---------------------------------------------------------------------------


def test_schema_version_is_declared(register: dict[str, Any]) -> None:
    """Every register in `tools/` opens with its own schema number, as `weights.toml` does."""
    assert register["schema"] == 1


def test_job_names_are_section_6_2s_needs_list(register: dict[str, Any]) -> None:
    """The register carries the job vocabulary so a workflow author need not re-derive it."""
    assert tuple(register["job_name"]) == JOB_NAMES


def test_g_numbers_are_dense_and_unique(gates: list[dict[str, Any]]) -> None:
    """`G1..Gn` with no gap and no repeat -- the property no document can hold any more.

    ADR-2 moved the cardinality into this file, so a duplicate `G<n>` or a hole is invisible
    everywhere else in the tree. Section 1.7's append-only rule is the same statement over time:
    an identifier a shipped document names can never stop existing.
    """
    numbers = [int(row["id"][1:]) for row in gates]
    assert all(re.fullmatch(r"G\d+", row["id"]) for row in gates)
    assert len(set(numbers)) == len(numbers), f"duplicate G number in {numbers}"
    assert sorted(numbers) == list(range(1, len(numbers) + 1)), f"not dense: {sorted(numbers)}"


def test_the_rendering_holds_twenty_nine_rows(law_gates: list[dict[str, Any]]) -> None:
    """Section 6.4 and `V10-1`:724 both say twenty-nine at release 1; nothing else may."""
    assert len(law_gates) == 29


def test_exactly_one_row_has_no_pr_job(law_gates: list[dict[str, Any]]) -> None:
    """Section 6.4: "Twenty-eight of the twenty-nine have a PR job and therefore block a
    merge. **G22 does not**."
    """
    without = [row["id"] for row in law_gates if not row["pr"]]
    assert without == ["G22"]
    assert sum(1 for row in law_gates if row["pr"]) == 28


def test_pr_agrees_with_having_a_job(gates: list[dict[str, Any]]) -> None:
    """`pr` is not an independent claim: a row with no job cell cannot run on a PR, and back.

    This is what keeps G22's "deliberately absent from `ci-ok`'s required set" from becoming the
    unfalsifiable statement section 6.8 refuses -- `ci-ok` needs jobs, so a gate with no job is
    outside its required set by construction rather than by assertion.
    """
    for row in gates:
        assert row["pr"] == bool(row["jobs"]), row["id"]


def test_every_job_named_is_a_real_job(
    gates: list[dict[str, Any]], register: dict[str, Any]
) -> None:
    """And no gate names `ci-ok`, which is the aggregator, not a place to run a check."""
    for row in gates:
        for job in row["jobs"]:
            assert job in JOB_NAMES, f"{row['id']} names job {job!r}"
            assert job != "ci-ok", f"{row['id']} runs inside the aggregator"
    for entry in register["job_assertion"]:
        assert entry["job"] in JOB_NAMES, entry["name"]


def test_job_assertion_name_carries_its_own_job(register: dict[str, Any]) -> None:
    """All nine are spelled `<job>.<what>` in section 6.4, so the prefix is checkable."""
    for entry in register["job_assertion"]:
        prefix, _, rest = entry["name"].partition(".")
        assert prefix == entry["job"], entry["name"]
        assert rest, entry["name"]


def test_only_g24_borrows_another_rows_budget(gates: list[dict[str, Any]]) -> None:
    """G24's `s` cell reads "(in G8)"; every other row either has a number or has no cell at all.

    Representing it as a `budget_s` would double-count against the `gates` job's 180 s ceiling
    (`V01-14`), which is what section 6.4's own G28/G29 fallback paragraph is measured against.
    """
    borrowers = {row["id"]: row["budget_in"] for row in gates if "budget_in" in row}
    assert borrowers == {"G24": "G8"}
    for row in gates:
        assert not ("budget_s" in row and "budget_in" in row), row["id"]
    # G22 is the only row with neither: section 6.4 prints an em dash in its job and `s` cells.
    neither = [row["id"] for row in gates if "budget_s" not in row and "budget_in" not in row]
    assert neither == ["G22"]


def test_only_the_three_history_readers_pin_fetch_depth(gates: list[dict[str, Any]]) -> None:
    """Section 6.2: "Checkout depth is part of the gate contract, not a performance knob."

    G13 diffs `codes.toml` against the previous tag, G27b diffs the migration set against it, and
    G16 builds template drivers from the previous two tags. Getting this wrong does not produce a
    wrong answer; it produces `fatal: no such ref` in a gate whose failure message is about error
    codes, which is worse than either.
    """
    pinned = {row["id"] for row in gates if row.get("fetch_depth") == 0}
    assert pinned == {"G13", "G16", "G27"}


def test_every_row_carries_an_owner_and_a_review_date(
    gates: list[dict[str, Any]], register: dict[str, Any]
) -> None:
    """Section 6.8: "Every `G<n>` row ... carries an owner and a review date", and there is no
    `--warn-only` for a row that does not.
    """
    for row in [*gates, *register["job_assertion"]]:
        label = row.get("id", row.get("name"))
        assert row["owner"] in OWNER_ROLES, f"{label}: owner {row['owner']!r}"
        reviewed = date.fromisoformat(row["reviewed_at"])
        review_by = date.fromisoformat(row["review_by"])
        assert review_by > reviewed, label


def test_a_row_the_rendering_does_not_carry_says_why(gates: list[dict[str, Any]]) -> None:
    """`status = "registered"` is an append this file made and section 6.4 has not rendered.

    Section 8.7's "add a gate" path is an ADR, then a `tools/gate_*.py`, then a row here, then a
    row in section 6.4's table. A row that has the middle two and not the outer two must say so:
    `pending` is that sentence, and it is why the rendering comparison runs over `law` rows only.
    """
    for row in gates:
        assert row["status"] in {"law", "registered"}, row["id"]
        if row["status"] != "law":
            assert row.get("pending"), row["id"]


def test_no_q_g_row_lives_here(register: dict[str, Any]) -> None:
    """Section 1.7: "Neither file may name a row the other owns."

    The static `Q-G` series' "budgets, owners and review dates live in `eval/gates.toml`; this
    document only reserves them a job" (section 6.4). 17-risks.md:57 lists "a `G<n>` or `Q-G<n>`
    row ... in `tools/gates.toml`" as a resolvable indicator, which contradicts both; the more
    specific statements win.
    """
    ids = {row["id"] for row in register["gate"]}
    assert not any(gate_id.startswith("Q-") for gate_id in ids)


# ---------------------------------------------------------------------------
# The runner columns
# ---------------------------------------------------------------------------


def _runners(row: dict[str, Any]) -> list[str]:
    return list(row.get("runner", ()))


def _planned(row: dict[str, Any]) -> list[str]:
    return list(row.get("runner_planned", ()))


def test_every_row_says_what_runs_it(gates: list[dict[str, Any]], register: dict[str, Any]) -> None:
    """No row points at nothing: a script, a planned script, or a named job step."""
    for row in [*gates, *register["job_assertion"]]:
        label = row.get("id", row.get("name"))
        assert _runners(row) or _planned(row) or row.get("step"), f"{label} names no runner"


def test_every_named_runner_exists(
    gates: list[dict[str, Any]], register: dict[str, Any], repo_root: Path
) -> None:
    """A `runner` path is a claim about the working tree, checked against the working tree."""
    for row in [*gates, *register["job_assertion"]]:
        label = row.get("id", row.get("name"))
        for path in _runners(row):
            assert (repo_root / path).is_file(), f"{label} names missing runner {path}"


def test_every_planned_runner_is_still_absent(
    gates: list[dict[str, Any]], register: dict[str, Any], repo_root: Path
) -> None:
    """The forcing function, in the other direction.

    `runner_planned` is the register saying "the plan names this script and nobody has written
    it". The day it exists, this test is the thing that says so: move the path into `runner` in
    the same commit that lands the script, and the row stops describing a future that arrived.
    """
    for row in [*gates, *register["job_assertion"]]:
        label = row.get("id", row.get("name"))
        for path in _planned(row):
            assert not (repo_root / path).exists(), (
                f"{label}: {path} now exists -- move it from runner_planned to runner"
            )


def test_no_path_is_both_written_and_planned(
    gates: list[dict[str, Any]], register: dict[str, Any]
) -> None:
    for row in [*gates, *register["job_assertion"]]:
        label = row.get("id", row.get("name"))
        assert not set(_runners(row)) & set(_planned(row)), label


def test_every_gate_script_on_disk_is_registered(
    gates: list[dict[str, Any]], register: dict[str, Any], repo_root: Path
) -> None:
    """A `tools/gate_*.py` nobody registered is a blocking check no document can cite.

    That is the hole `tools/gate_tombstones.py` sat in: it runs, it blocks, and `V10-1`'s "every
    `G` row in `tools/gates.toml` green" could not see it because it had no row. This assertion is
    why the next one cannot happen silently.
    """
    on_disk = {f"tools/{path.name}" for path in sorted((repo_root / "tools").glob("gate_*.py"))}
    assert on_disk, "no tools/gate_*.py found -- this check would be vacuous"
    named: set[str] = set()
    for row in [*gates, *register["job_assertion"]]:
        named.update(_runners(row))
        named.update(_planned(row))
    missing = on_disk - named - set(QG_SERIES_SCRIPTS)
    assert not missing, f"unregistered gate scripts: {sorted(missing)}"


def test_the_q_g_scripts_are_registered_in_the_other_register_and_not_this_one(
    gates: list[dict[str, Any]], register: dict[str, Any], repo_root: Path
) -> None:
    """The other direction of `QG_SERIES_SCRIPTS`, which is what keeps it an allow-list.

    11-repo-layout.md:397: "Neither file may name a row the other owns." A Q-G script that gained
    a `tools/gates.toml` row would be that violation, and it would also be invisible as a
    violation -- the sweep above would go green on it, because the row would put the path in
    `named`. So the exclusion is asserted as an equality against the register rather than
    subtracted and forgotten.

    The second assertion is the anti-rot half: a name in this table that is not on disk is a
    stale exemption, and a stale exemption is how the sweep above quietly stops covering a script
    somebody renamed.
    """
    named: set[str] = set()
    for row in [*gates, *register["job_assertion"]]:
        named.update(_runners(row))
        named.update(_planned(row))
    overlap = named & set(QG_SERIES_SCRIPTS)
    assert not overlap, (
        f"11-repo-layout.md:397 -- tools/gates.toml names a row eval/gates.toml owns: "
        f"{sorted(overlap)}"
    )
    absent = {path for path in QG_SERIES_SCRIPTS if not (repo_root / path).is_file()}
    assert not absent, f"stale Q-G exemption for a script that is gone: {sorted(absent)}"


def test_a_runner_serves_two_rows_only_where_the_plan_says_so(gates: list[dict[str, Any]]) -> None:
    """Section 6.4 gives exactly two scripts two gates each; a third would be a failure message
    that has to mean two things.

    `tools/gate_importtime.py` is G9 + G23 (one `-X importtime` trace answers both) and
    `tools/gate_semgrep.py` is G8 + G24 (G24's `s` cell is "(in G8)"). Section 6.4 refused the
    same merge for G29 into G8 for exactly the reason this test guards: "one failure message
    cannot mean both 'a semgrep rule fired' and 'content leaked into an artefact'".
    """
    users: dict[str, list[str]] = {}
    for row in gates:
        for path in _runners(row) + _planned(row):
            users.setdefault(path, []).append(row["id"])
    shared = {path: tuple(ids) for path, ids in users.items() if len(ids) > 1}
    assert shared == SHARED_RUNNERS


# ---------------------------------------------------------------------------
# G27's clauses
# ---------------------------------------------------------------------------


def test_g27_carries_its_six_clauses_and_no_new_numbers(gates: list[dict[str, Any]]) -> None:
    """ADR-4: `G27(a2)` and `G27(a3)` "attach to clause (a) ... neither takes a new `G` number".

    So the clauses are sub-tables of G27's row. A clause promoted to a row would be a new `G<n>`,
    which ADR-4 declined and section 8.7 makes an ADR-only act.
    """
    g27 = next(row for row in gates if row["id"] == "G27")
    assert [clause["id"] for clause in g27["clause"]] == ["a", "a2", "a3", "b", "c", "d"]
    assert {clause["id"] for clause in g27["clause"]}.isdisjoint({row["id"] for row in gates})
    added = {clause["id"]: clause.get("added_by") for clause in g27["clause"]}
    assert added["a2"] == "ADR-4"
    assert added["a3"] == "ADR-4"


def test_g27c_is_registered_and_off_with_the_reason_named(gates: list[dict[str, Any]]) -> None:
    """ADR-1 decision 6: until four conditions hold, `G27(c)` sits here with `enabled = false`
    and a `blocked_by = "ADR-1"` note, "so its absence is visible rather than assumed".

    It is the only clause that is off, and it is not a `--warn-only`: section 6.8 says there is
    none anywhere. A disabled clause still blocks nothing and still names who unblocks it.
    """
    g27 = next(row for row in gates if row["id"] == "G27")
    off = {
        clause["id"]: clause.get("blocked_by") for clause in g27["clause"] if not clause["enabled"]
    }
    assert off == {"c": "ADR-1"}


def test_the_two_numbers_section_8_6_and_adr_1_park_here(gates: list[dict[str, Any]]) -> None:
    """Clause d0's symbol floor and clause c's allowlist ratchet.

    Section 8.6: the floor "lives in `tools/gates.toml` beside G27's row, so raising it is a
    reviewable act and lowering it is visible. It is **520** at release 1". ADR-1 decision 5: the
    `tools/lock_allow.toml` allowlist "is a ratchet: `tools/gates.toml` holds its length and
    `G27(c)` fails on an increase".
    """
    g27 = next(row for row in gates if row["id"] == "G27")
    by_id = {clause["id"]: clause for clause in g27["clause"]}
    assert by_id["d"]["symbol_floor"] == 520
    assert by_id["c"]["lock_allow_max_rows"] == 0


def test_a_clauses_runners_are_its_gates_runners(gates: list[dict[str, Any]]) -> None:
    """A clause may not name a script its own row does not, or the row would understate itself."""
    for row in gates:
        if "clause" not in row:
            continue
        row_paths = set(_runners(row) + _planned(row))
        for clause in row["clause"]:
            assert set(_runners(clause) + _planned(clause)) <= row_paths, (
                f"{row['id']}({clause['id']}) names a runner its row does not"
            )


# ---------------------------------------------------------------------------
# G27 clause d2 itself: the register against the rendering
# ---------------------------------------------------------------------------


def test_the_rendering_lists_the_law_rows_in_order(
    rendered_gates: list[list[str]], law_gates: list[dict[str, Any]]
) -> None:
    """Row for row and in order, so a reader of either can follow the other with a finger."""
    rendered = [cells[0].split(" ", 1)[0] for cells in rendered_gates]
    assert rendered == [row["id"] for row in law_gates]


def test_every_assertion_matches_its_rendered_cell(
    rendered_gates: list[list[str]], law_gates: list[dict[str, Any]]
) -> None:
    """The gate cell is `G<n> ` plus the assertion, verbatim under the ASCII fold."""
    for cells, row in zip(rendered_gates, law_gates, strict=True):
        assert fold(cells[0]) == f"{row['id']} {row['assertion']}", row["id"]


def test_every_job_cell_matches(
    rendered_gates: list[list[str]], law_gates: list[dict[str, Any]]
) -> None:
    """Parsed, not string-compared: backticks come off, `+` splits, and a trailing `(9)` is the
    `test` job's nine OS/Python cells rather than part of a name.

    Section 6.2 fixes `test` at nine cells and every other job at one, so the annotation is a
    property of the job and appears exactly where `test` does.
    """
    for cells, row in zip(rendered_gates, law_gates, strict=True):
        cell = cells[1].strip()
        if cell == EMPTY_CELL:
            assert row["jobs"] == [], row["id"]
            continue
        nine = cell.endswith("(9)")
        cell = cell.removesuffix("(9)").strip()
        names = [part.strip().strip("`") for part in cell.split("+")]
        assert names == row["jobs"], row["id"]
        assert nine == ("test" in row["jobs"]), row["id"]


def test_every_budget_cell_matches(
    rendered_gates: list[list[str]], law_gates: list[dict[str, Any]]
) -> None:
    """A number, `(in G<n>)`, or an empty cell. Nothing is invented for the last two."""
    for cells, row in zip(rendered_gates, law_gates, strict=True):
        cell = cells[2].strip()
        if cell == EMPTY_CELL:
            assert "budget_s" not in row and "budget_in" not in row, row["id"]
        elif cell.startswith("(in "):
            assert row["budget_in"] == cell.removeprefix("(in ").removesuffix(")"), row["id"]
        else:
            assert row["budget_s"] == int(cell), row["id"]


def test_every_nightly_and_release_cell_matches(
    rendered_gates: list[list[str]], law_gates: list[dict[str, Any]]
) -> None:
    """An em dash is false; a bare `yes` is true; anything else is true plus a `_note`.

    The three cells that say more than yes are the three that matter: G5 releases "against the
    tag", G21's nightly is the "full matrix" against the PR job's three random points, and G22 is
    "**nightly only**", which is the whole reason it has no PR cell.
    """
    for cells, row in zip(rendered_gates, law_gates, strict=True):
        for cell_text, flag, note in (
            (cells[3], "nightly", "nightly_note"),
            (cells[4], "release", "release_note"),
        ):
            cell = cell_text.strip()
            if cell == EMPTY_CELL:
                assert row[flag] is False and note not in row, f"{row['id']} {flag}"
            elif cell == "yes":
                assert row[flag] is True and note not in row, f"{row['id']} {flag}"
            else:
                assert row[flag] is True, f"{row['id']} {flag}"
                assert row.get(note) == fold(cell), f"{row['id']} {note}"


def test_the_job_assertion_table_matches_row_for_row(
    rendered_assertions: list[list[str]], register: dict[str, Any]
) -> None:
    """Nine rows, in order, with the name, job and assertion cells verbatim under the fold.

    Section 6.4 makes the count normative in four other places (11-repo-layout.md:2692,
    glossary.md:719, terminology.md:479, 17-risks.md:265 all say nine at release 1), and G27
    clause d2 "resolves a `[[job_assertion]]` name the same way it resolves a `G<n>`" -- so a
    document may name one, and a tenth row would falsify a printed count.
    """
    entries = list(register["job_assertion"])
    assert len(entries) == 9
    for cells, entry in zip(rendered_assertions, entries, strict=True):
        assert cells[0].strip("`") == entry["name"]
        assert cells[1].strip("`") == entry["job"]
        assert fold(cells[2]) == entry["asserts"], entry["name"]


def test_the_job_assertion_section_column_resolves(
    rendered_assertions: list[list[str]], register: dict[str, Any]
) -> None:
    """The `§` column, expanded. A bare `§n.n` is this document; a linked one names its own."""
    for cells, entry in zip(rendered_assertions, register["job_assertion"], strict=True):
        cell = cells[3].strip()
        link = re.search(r"\(([\w./-]+\.md)\)", cell)
        document = link.group(1) if link else LAYOUT
        number = cell.rsplit("§", 1)[1].strip()
        assert entry["section"] == f"{document} section {number}", entry["name"]


def test_a_budget_stated_in_prose_matches_the_key(register: dict[str, Any]) -> None:
    """`gates.invariant_register`'s cell ends "Budget 2 s"; the key must agree with the sentence.

    The two register checks are the only job assertions the plan budgets, both at 2 s
    (17-risks.md:88 sizes the second: "one `tomllib.load`, five set-membership passes over 60 rows
    and ~200 question keys, and one byte-diff").
    """
    budgeted = {
        entry["name"]: entry["budget_s"]
        for entry in register["job_assertion"]
        if "budget_s" in entry
    }
    assert budgeted == {"gates.invariant_register": 2, "gates.risk_register": 2}
    for entry in register["job_assertion"]:
        match = re.search(r"Budget (\d+) s$", entry["asserts"])
        if match:
            assert entry["budget_s"] == int(match.group(1)), entry["name"]


def test_the_wheelhouse_profiles_are_section_2_4s_three(register: dict[str, Any]) -> None:
    """Section 2.4: "Three of the six are built in the `build` job ... The three together are the
    `[[job_assertion]]` `build.wheelhouse_profiles`."
    """
    entry = next(e for e in register["job_assertion"] if e["name"] == "build.wheelhouse_profiles")
    assert entry["profiles"] == ["laptop-minimum", "laptop-working", "all-packages-minus-vision"]
