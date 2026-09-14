"""G19's harness, and the two things a harness for an absent fixture has to get right.

The gate is `tools/gate_incremental.py`. `16-roadmap.md:458` runs it as
`uv run tools/gate_incremental.py --smoke` at the **P2** exit with the annotation *"G19's harness
exists; its fixture lands in P4"*, and `:575` runs it unflagged at the P4 exit. So exactly two
claims are testable now and both are tested here:

1. **The comparator works.** `diff_exports()` is the whole of G19's comparison
   (07-store-and-retrieval.md:2971, 08-runtime.md:1858: diff the `.owdoc` **exports**, not the
   tables). It is driven over real archives written by the shipped writer -- two equal ones and
   pairs that differ by exactly one field, one absent record and one absent member -- and it is
   required to find each. A comparator that returned nothing would satisfy "two equal exports
   diff to nothing" and nothing else, which is why every red case here is a separate test.
2. **The absence is reported, never passed over.** `--smoke` exits 0 and prints a NOT CHECKED
   block naming P4 for the fixture, the mutation script, the indexer and the rebuilder. The
   default (full) mode exits **2** while any of them is missing, including -- and this is the
   case worth writing down -- when the fixture has landed and the builder has not. 11-repo-
   layout.md section 6.8 refuses "a check that cannot yet fail"; a gate that printed `ok` over an
   empty corpus would be one.

**The register is the specification and this file re-reads it.** `01-principles.md:506` says the
G19 row owns the fixture size and the mutation count, so `check_register()` asserts the harness's
`DOCUMENTS`/`MUTATIONS` against `tools/gates.toml` at run time, and
`test_a_register_that_shrank_the_corpus_is_a_complaint` proves that check fires -- against a
synthetic register, so nothing here rewrites the real one.

Specified in `tools/gates.toml`'s G19 row, 01-principles.md:506, 07-store-and-retrieval.md:2971,
08-runtime.md:1858, 11-repo-layout.md sections 6.2, 6.4, 6.8 and OQ-6, and 16-roadmap.md:458,
:550 and :575.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
import tomllib
import zipfile
from collections.abc import Iterator, Sequence
from io import StringIO
from pathlib import Path

import pytest


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "tools" / "layers.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT = _repo_root(Path(__file__).resolve())
TOOL_PATH = REPO_ROOT / "tools" / "gate_incremental.py"
REGISTER = REPO_ROOT / "tools" / "gates.toml"

# The gate is a script in `tools/`, not a distribution, so there is no package to import it from.
# `spec_from_file_location` loads it by path -- the same mechanism `test_gate_migrations.py` uses
# and for the same reasons: not `importlib.import_module`, which is banned outside `host/`, and
# not a `sys.path` mutation, which would leak into every later test.
_SPEC = importlib.util.spec_from_file_location("omniweave_gate_incremental", TOOL_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - the file is in this repository
    message = f"cannot load {TOOL_PATH}"
    raise RuntimeError(message)
gate = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    argv: list[str],
    workdir: Path | None = None,
    *,
    build: object | None = None,
) -> tuple[int, str]:
    """The gate, with its report captured. Nothing here writes to the real stdout.

    `build` is the same seam `run_full` takes. **No test in this file runs the real builder**: a
    300-document build measures ~130 s, and a unit suite that paid that would be a unit suite
    people skip. The real builder's own end-to-end behaviour is `test_fixture_incremental.py`'s,
    over a corpus small enough to run in a second.
    """
    buffer = StringIO()
    code = gate.main(argv, out=buffer, workdir=workdir, build=build)  # type: ignore[arg-type]
    return code, buffer.getvalue()


def _archive(
    path: Path, *, producers: list[dict[str, object]], blocks: list[dict[str, object]]
) -> Path:
    """A minimal `.owdoc` carrying just a manifest and one block member. For the two resolvers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as package:
        package.writestr("manifest.json", json.dumps({"gen": 1, "producers": producers}))
        package.writestr("blocks/000000.ndjson", "\n".join(json.dumps(block) for block in blocks))
    return path


@pytest.fixture
def archives(tmp_path: Path) -> tuple[Path, Path, Path]:
    """`(incremental, full, diverged)` -- two byte-identical exports and one with an edited block.

    Built by the gate's own `_smoke_archives`, so these tests and the smoke mode are looking at
    the same three files and a change to one is a change to both.
    """
    return gate._smoke_archives(tmp_path)


def _plan(directory: Path, *, documents: int, mutations: int) -> Path:
    """A synthetic `fixtures/incremental/plan.toml`. The real corpus is W4.10's and is absent."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = [f"documents = {documents}", "mutations = ["]
    lines += [f'  "edit-{n:02d}",' for n in range(mutations)]
    lines.append("]")
    (directory / "plan.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return directory


def _synthetic_register(path: Path, *, assertion: str, jobs: str = '["incremental"]') -> Path:
    path.write_text(
        f'[[gate]]\nid = "G19"\nassertion = {assertion!r}\njobs = {jobs}\nbudget_s = 420\n',
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# 1. The comparator, red case by red case
# ---------------------------------------------------------------------------


def test_two_exports_of_one_generation_diff_to_nothing(
    archives: tuple[Path, Path, Path],
) -> None:
    """The green control. Without it a comparator that reported everything would look sound."""
    incremental, full, _ = archives
    assert incremental.read_bytes() == full.read_bytes(), "the writer is not byte-stable"
    assert gate.diff_exports(incremental, full) == ()


def test_a_single_changed_block_text_is_found_at_its_addr(
    archives: tuple[Path, Path, Path],
) -> None:
    """One edited block, and the difference names the `addr` and the wire key -- never an id.

    07:2973 is the reason the diff is over exports: *"an archive contains no `block_id`, so the
    allocation-order normalisation that could hide a bug is not needed at all"*. So the subject
    of a `Difference` has to be an `addr`, and this asserts it is.
    """
    _, full, diverged = archives
    differences = gate.diff_exports(diverged, full)
    text = [d for d in differences if d.field == "t"]
    assert len(text) == 1, differences
    assert text[0].subject == "p0/1"
    assert text[0].where == "blocks/000000.ndjson"
    assert text[0].incremental == "the second paragraph, edited"
    assert text[0].full == "the second paragraph"
    assert all(not d.subject.isdigit() for d in differences), "a difference named a bare id"


def test_the_edit_also_moves_the_frame_digest(archives: tuple[Path, Path, Path]) -> None:
    """`frames.json`'s per-frame `sha256` is over the UNCOMPRESSED member bytes (03:2537).

    It is the version-independent identity the plan puts there precisely so that a changed block
    changes a recorded digest, so an edit that did NOT move it would mean the frame index and the
    frame had come apart.
    """
    _, full, diverged = archives
    members = {d.where for d in gate.diff_exports(diverged, full)}
    assert "frames.json" in members
    assert "blocks/000000.ndjson" in members


def test_a_record_present_on_one_side_only_is_a_difference(tmp_path: Path) -> None:
    """The failure an incremental run actually produces: a block that should have been retired,
    or one that should have been added and was not.

    Built by rewriting one archive's block member with a record removed, so the two archives
    differ in record COUNT and not in any field -- the case a naive zip of two lists misses.
    """
    incremental, full, _ = gate._smoke_archives(tmp_path)
    short = _drop_last_block(full, tmp_path / "short.owdoc")
    differences = gate.diff_exports(incremental, short)
    missing = [d for d in differences if d.field == "<record>"]
    assert len(missing) == 1, differences
    assert missing[0].subject == "p0/1"
    assert (missing[0].incremental, missing[0].full) == ("present", "absent")


def test_a_member_present_on_one_side_only_is_a_difference(tmp_path: Path) -> None:
    """A whole member gone -- no `grids.ndjson` on one side -- is not a field difference."""
    incremental, full, _ = gate._smoke_archives(tmp_path)
    with zipfile.ZipFile(full) as source:
        names = source.namelist()
        payloads = {name: source.read(name) for name in names}
    extra = tmp_path / "extra.owdoc"
    with zipfile.ZipFile(extra, "w") as target:
        for name, payload in payloads.items():
            target.writestr(name, payload)
        target.writestr("grids.ndjson", b"")
    differences = gate.diff_exports(incremental, extra)
    assert [(d.where, d.incremental, d.full) for d in differences] == [
        ("grids.ndjson", "absent", "present")
    ]


def _drop_last_block(archive: Path, target: Path) -> Path:
    """Rewrite an archive with its last block record removed. A hand-built ZIP, not `export()`."""
    with zipfile.ZipFile(archive) as source:
        payloads = {name: source.read(name) for name in source.namelist()}
    member = next(name for name in payloads if name.startswith("blocks/"))
    lines = payloads[member].splitlines()
    payloads[member] = b"\n".join(lines[:-1]) + b"\n"
    with zipfile.ZipFile(target, "w") as out:
        for name, payload in payloads.items():
            out.writestr(name, payload)
    return target


def test_an_unreadable_archive_is_not_a_divergence(tmp_path: Path) -> None:
    """ "They differ" and "I could not read one of them" are different answers.

    Reporting the second as the first is how a gate turns a broken checkout into a code review.
    `read_archive` raises and `--diff` maps it to `DID NOT RUN` with exit 2.
    """
    bad = tmp_path / "bad.owdoc"
    bad.write_bytes(b"this is not a zip file")
    with pytest.raises(ValueError, match=r"not a readable \.owdoc"):
        gate.read_archive(bad)


def test_an_archive_whose_ndjson_does_not_parse_is_not_a_divergence(tmp_path: Path) -> None:
    """The subtler unreadable: a real ZIP whose block member is not JSON."""
    broken = tmp_path / "broken.owdoc"
    with zipfile.ZipFile(broken, "w") as out:
        out.writestr("manifest.json", b"{}")
        out.writestr("blocks/000000.ndjson", b"{not json}\n")
    with pytest.raises(ValueError, match="not valid JSON"):
        gate.read_archive(broken)


# ---------------------------------------------------------------------------
# 2. `--smoke`: P2's mode
# ---------------------------------------------------------------------------


def test_smoke_exits_zero_and_names_the_mode_that_checks_what_it_cannot(
    tmp_path: Path,
) -> None:
    """16-roadmap.md:458's exit criterion, and the "never a silent pass" half of it.

    **This test named P4 and four absences until W4.10.** The four were absences of the FIXTURE --
    the corpus, the mutation script, the indexer and the rebuilder -- and every one of them now
    exists. What `--smoke` still cannot check is the convergence itself, because it builds its own
    two archives rather than a corpus, so the rows it prints now name the MODE that does.

    Exit 0 is what P2 asks for and what a mode with no corpus can honestly return.
    """
    code, output = _run(["--smoke"], tmp_path)
    assert code == gate.EXIT_CLEAN, output
    assert "G19 ok" in output
    assert "NOT CHECKED" in output
    assert output.count("owner: the full mode") == len(gate.NOT_CHECKED_BY_SMOKE)
    assert "tools/incremental_index.py" in output
    for expected in ("300-document corpus", "full rebuild", "40 mutations"):
        assert expected in output, expected


def test_smoke_proves_the_comparator_can_fail_before_it_reports_a_pass(tmp_path: Path) -> None:
    """The smoke run's own second self-check, read out of its report.

    "Two equal exports diff to nothing" is satisfied by a comparator that always returns nothing.
    The smoke mode therefore plants a change and requires the comparator to find it, and the
    report says so out loud -- which is the line this test pins, because a smoke mode that
    quietly dropped the planted check would still print `G19 ok`.
    """
    _, output = _run(["--smoke"], tmp_path)
    assert "a planted change to one block's `t` is found at p0/1" in output


def test_smoke_reports_the_pre_committed_fallback_rather_than_implementing_it(
    tmp_path: Path,
) -> None:
    """11-repo-layout.md OQ-6. The 60-document/8-mutation subset is a fallback with a TRIGGER.

    Implementing it now would give the PR path a weaker gate before anyone had measured the run
    that justifies the weakening, so the harness records it and does not run it. The record is
    the deliverable; this asserts it is present and legible.
    """
    _, output = _run(["--smoke"], tmp_path)
    assert "OQ-6" in output
    assert "60-document/8-mutation" in output
    assert "blake2b(commit_sha)" in output
    assert "Not implemented" in output


def test_smoke_leaves_its_three_archives_where_a_reader_can_see_them(tmp_path: Path) -> None:
    """`workdir` is injectable, which is what makes the smoke mode debuggable at all.

    Without it the three archives live in a temporary directory the run deletes, and a smoke
    failure would report a difference nobody could open.
    """
    _run(["--smoke"], tmp_path)
    written = sorted(path.name for path in tmp_path.glob("*.owdoc"))
    assert written == ["smoke-diverged.owdoc", "smoke-full.owdoc", "smoke-incremental.owdoc"]


# ---------------------------------------------------------------------------
# 3. The full mode never passes while its subject is absent
# ---------------------------------------------------------------------------


def test_the_full_mode_did_not_run_without_a_fixture(tmp_path: Path) -> None:
    """Exit 2, and the message names the directory and the roadmap line that owns it."""
    code, output = _run(["--fixture", str(tmp_path / "absent")])
    assert code == gate.EXIT_NOT_RUN
    assert "DID NOT RUN" in output
    assert "fixtures/incremental/plan.toml" in output
    assert "16-roadmap.md:550" in output
    assert "G19 ok" not in output


def test_the_full_mode_did_not_run_on_a_fixture_directory_with_no_plan(tmp_path: Path) -> None:
    """A half-landed fixture is `DID NOT RUN`, not a pass: an empty corpus is not an equal one."""
    (tmp_path / "corpus").mkdir()
    code, output = _run(["--fixture", str(tmp_path / "corpus")])
    assert code == gate.EXIT_NOT_RUN
    assert "no plan.toml" in output


def test_a_fixture_with_the_wrong_counts_is_a_failure_and_not_merely_a_note(
    tmp_path: Path,
) -> None:
    """The gate owns its two numbers (01-principles.md:506), so a smaller corpus is a FAILURE.

    Exit 1, not 2: the fixture is there and it is wrong, which is a different fact from the
    fixture being absent, and section 6.2's note is explicit that shrinking it "would change a
    gate the charter says owns its two numbers".
    """
    fixture = _plan(tmp_path / "corpus", documents=60, mutations=8)
    code, output = _run(["--fixture", str(fixture)])
    assert code == gate.EXIT_FAIL
    assert "60 documents, not 300" in output
    assert "8 mutations, not 40" in output


def test_a_builder_that_yields_no_checkpoint_still_does_not_pass(tmp_path: Path) -> None:
    """THE CASE THIS HARNESS EXISTS TO GET RIGHT, inverted by W4.10.

    It used to read: a correct fixture with no builder must not pass, because *"a harness that
    read the plan, found the numbers correct and returned 0 would report G19 green over a gate
    that had never run -- and G19 is `pr = true`, so that green would be a required check passing
    on nothing."* The builder landed, so the shape of that mistake moved: it is now a builder that
    runs and produces nothing. The answer is the same one. Exit 2.
    """
    fixture = _plan(tmp_path / "corpus", documents=300, mutations=40)

    def yields_nothing(root: Path, steps: Sequence[int]) -> Iterator[object]:
        assert root is not None and steps
        return iter(())

    code, output = _run(["--fixture", str(fixture)], build=yields_nothing)
    assert code == gate.EXIT_NOT_RUN
    assert "produced no checkpoints" in output
    assert "G19 ok" not in output


# ---------------------------------------------------------------------------
# 4. `--diff`: the comparator as a command
# ---------------------------------------------------------------------------


def test_diff_exits_zero_on_two_equal_exports(archives: tuple[Path, Path, Path]) -> None:
    incremental, full, _ = archives
    code, output = _run(["--diff", str(incremental), str(full)])
    assert code == gate.EXIT_CLEAN, output
    assert "G19 ok" in output


def test_diff_exits_one_on_a_divergence_and_prints_the_field(
    archives: tuple[Path, Path, Path],
) -> None:
    _, full, diverged = archives
    code, output = _run(["--diff", str(diverged), str(full)])
    assert code == gate.EXIT_FAIL
    assert "THE EXPORTS DIFFER" in output
    assert "blocks/000000.ndjson :: p0/1 :: t" in output
    assert "the second paragraph, edited" in output


def test_diff_exits_two_on_a_corrupted_archive(tmp_path: Path) -> None:
    """A corrupted input is `DID NOT RUN`, which is the exit code that means "ask a human"."""
    good, _, _ = gate._smoke_archives(tmp_path)
    bad = tmp_path / "bad.owdoc"
    bad.write_bytes(b"\x00\x01\x02 not a zip")
    code, output = _run(["--diff", str(bad), str(good)])
    assert code == gate.EXIT_NOT_RUN
    assert "not a readable .owdoc" in output


def test_diff_exits_two_on_a_missing_archive(tmp_path: Path) -> None:
    code, output = _run(["--diff", str(tmp_path / "nope.owdoc"), str(tmp_path / "nope.owdoc")])
    assert code == gate.EXIT_NOT_RUN
    assert "no such archive" in output


def test_diff_and_smoke_together_are_refused_rather_than_silently_ordered(
    tmp_path: Path,
) -> None:
    """Two modes in one invocation would make the exit code mean whichever ran second."""
    code, output = _run(["--smoke", "--diff", "a.owdoc", "b.owdoc"], tmp_path)
    assert code == gate.EXIT_NOT_RUN
    assert "pick one" in output


# ---------------------------------------------------------------------------
# 5. The register owns the two numbers
# ---------------------------------------------------------------------------


def test_the_harness_agrees_with_the_real_register() -> None:
    """`check_register()` over `tools/gates.toml` itself. The transcription is asserted, not
    assumed -- which is the whole point of 01-principles.md:506 naming the row as the owner."""
    assert gate.check_register(REGISTER) == ()


def test_the_registers_g19_row_says_what_this_harness_transcribes() -> None:
    """The other direction, read off the file rather than through the gate's own helper.

    `check_register()` could be wrong in the same way the constants are; this reads the row.
    """
    rows = tomllib.loads(REGISTER.read_text(encoding="utf-8"))["gate"]
    row = next(r for r in rows if r["id"] == "G19")
    assert row["assertion"] == ("incremental == full: 300 docs, 40 mutations, `.owdoc` export diff")
    assert row["jobs"] == ["incremental"]
    assert row["budget_s"] == 420
    assert row["pr"] is True and row["nightly"] is True and row["release"] is True
    assert row["runner"] == ["tools/gate_incremental.py"], (
        "the row must name this script under `runner` and not `runner_planned`: "
        "test_gates_register.py asserts a planned path does NOT exist"
    )


def test_a_register_that_shrank_the_corpus_is_a_complaint(tmp_path: Path) -> None:
    """The drift guard, fired. A harness carrying its own numbers could weaken itself silently."""
    register = _synthetic_register(
        tmp_path / "gates.toml",
        assertion="incremental == full: 60 docs, 8 mutations, `.owdoc` export diff",
    )
    complaints = gate.check_register(register)
    assert len(complaints) == 2, complaints
    assert any("300 docs" in complaint for complaint in complaints)
    assert any("40 mutations" in complaint for complaint in complaints)


def test_a_register_that_moved_g19_out_of_its_own_job_is_a_complaint(tmp_path: Path) -> None:
    """Section 6.2 gives G19 its own job because the corpus does not fit inside `golden`'s 4 min.

    OQ-6's fallback moves the row to `nightly`, which keeps the job name; moving it INTO another
    PR job would put a 420 s gate inside a 240 s budget, so the harness says so.
    """
    register = _synthetic_register(
        tmp_path / "gates.toml",
        assertion="incremental == full: 300 docs, 40 mutations, `.owdoc` export diff",
        jobs='["golden"]',
    )
    assert gate.check_register(register) == ("G19's row does not name the 'incremental' job",)


def test_a_missing_register_is_a_complaint_and_not_a_pass(tmp_path: Path) -> None:
    assert gate.check_register(tmp_path / "nothing.toml") == (
        f"no register at {tmp_path / 'nothing.toml'}",
    )


def test_the_smoke_mode_fails_when_the_register_disagrees(tmp_path: Path) -> None:
    """End to end: a drifted register turns the P2 exit criterion red rather than green."""
    register = _synthetic_register(
        tmp_path / "gates.toml",
        assertion="incremental == full: 60 docs, 8 mutations, `.owdoc` export diff",
    )
    code, output = _run(["--smoke", "--register", str(register)], tmp_path)
    assert code == gate.EXIT_FAIL
    assert "G19 FAIL" in output


# ---------------------------------------------------------------------------
# 6. House shape
# ---------------------------------------------------------------------------


def test_the_gate_writes_nothing_to_stdout_of_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`main(argv, *, out)` and no `print`: T20 is enabled repo-wide and a gate that needed an
    exemption to report its own result would carry that exemption past its reason."""
    _run(["--smoke"], tmp_path)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_the_three_exit_codes_are_the_ones_the_docstring_promises() -> None:
    """A gate's exit codes are its contract with CI, so they are pinned as values."""
    assert (gate.EXIT_CLEAN, gate.EXIT_FAIL, gate.EXIT_NOT_RUN) == (0, 1, 2)
    assert gate.exit_code(gate.Report(mode="x")) == 0
    assert gate.exit_code(gate.Report(mode="x", not_run="no fixture")) == 2
    assert gate.exit_code(gate.Report(mode="x", complaints=("wrong",))) == 1
    assert (
        gate.exit_code(
            gate.Report(
                mode="x",
                differences=(gate.Difference("blocks", "doc", "t", "a", "b"),),
            )
        )
        == 1
    )


def test_a_did_not_run_report_outranks_a_difference() -> None:
    """Both at once means the run was invalid, so the code must be 2 and not 1: a divergence
    computed from an archive that would not read is not a divergence."""
    report = gate.Report(
        mode="x",
        not_run="unreadable",
        differences=(gate.Difference("blocks", "doc", "t", "a", "b"),),
    )
    assert gate.exit_code(report) == gate.EXIT_NOT_RUN


def test_a_long_difference_list_is_truncated_with_its_own_count() -> None:
    """A structurally diverged 300-document corpus produces one difference per block, and a
    report that printed all of them would be unreadable in the run where reading it matters."""
    many = tuple(
        gate.Difference("blocks/000000.ndjson", f"p0/{n}", "t", "a", "b") for n in range(25)
    )
    buffer = StringIO()
    gate.render(gate.Report(mode="diff", differences=many), buffer)
    output = buffer.getvalue()
    assert "... and 5 more" in output
    assert output.count(":: t") == gate._MAX_REPORTED_DIFFERENCES


# ---------------------------------------------------------------------------
# 7. W4.10: the provenance pass, the two resolvers, and the checkpoint cadence
# ---------------------------------------------------------------------------


def test_the_provenance_set_is_closed_and_every_entry_is_parse_history() -> None:
    """Three members, six fields, and a reader can check each one against its own argument.

    Pinned as a literal because `PROVENANCE` is the one place this gate stops comparing something:
    a field added here is a field the gate no longer checks, and that must be a visible diff in
    this test rather than a line in a dict nobody reads.
    """
    assert dict(gate.PROVENANCE) == {
        "manifest.json": frozenset({"gen", "producers", "doc_ord"}),
        "frames.json": frozenset({"sha256", "bytes"}),
        "blocks/": frozenset({"rm", "c"}),
    }


def test_a_field_outside_the_set_is_a_divergence_even_in_a_provenance_member() -> None:
    """The match is on the member AND the field. `t` in a manifest is not `gen` in a manifest."""
    divergences, provenance = gate.classify(
        (
            gate.Difference("manifest.json", "<manifest>", "gen", 2, 1),
            gate.Difference("manifest.json", "<manifest>", "status", "ok", "partial"),
            gate.Difference("blocks/000000.ndjson", "p0/1", "rm", 2, 0),
            gate.Difference("blocks/000000.ndjson", "p0/1", "t", "a", "b"),
        )
    )
    assert [d.field for d in provenance] == ["gen", "rm"]
    assert [d.field for d in divergences] == ["status", "t"]


def test_pd_is_resolved_to_the_producer_it_names_before_anything_is_compared(
    tmp_path: Path,
) -> None:
    """The same producer at two indexes must not be a difference; a different one must be.

    `store/portable.py` fills `manifest.producers[]` from every `producer` row in the exporting
    store, so a store that has parsed at three driver versions puts the same producer at index 2
    where a rebuild puts it at 0. Comparing the index reports every block of every document; this
    asserts the resolution instead, in both directions.
    """
    old = {"operator": "parse.pdf", "op_version": 1, "code_fingerprint": "aa"}
    new = {"operator": "parse.pdf", "op_version": 2, "code_fingerprint": "bb"}
    left = _archive(
        tmp_path / "a.owdoc",
        producers=[old, new],
        blocks=[{"i": "p0/0", "pd": 1, "c": "d1#1"}],
    )
    right = _archive(
        tmp_path / "b.owdoc",
        producers=[new],
        blocks=[{"i": "p0/0", "pd": 0, "c": "d1#1"}],
    )
    assert [d.field for d in gate.diff_exports(left, right)] == ["producers"]

    stale = _archive(
        tmp_path / "c.owdoc",
        producers=[old, new],
        blocks=[{"i": "p0/0", "pd": 0, "c": "d1#1"}],
    )
    fields = [d.field for d in gate.diff_exports(stale, right)]
    assert "pd" in fields, "a block still stamped with the old driver IS a divergence"


def test_a_producer_index_past_the_end_of_its_own_manifest_is_a_value_and_not_a_raise(
    tmp_path: Path,
) -> None:
    """A malformed archive is `DID NOT RUN`'s business; an out-of-range index is a difference."""
    left = _archive(tmp_path / "a.owdoc", producers=[], blocks=[{"i": "p0/0", "pd": 7}])
    right = _archive(
        tmp_path / "b.owdoc",
        producers=[{"operator": "parse.pdf"}],
        blocks=[{"i": "p0/0", "pd": 0}],
    )
    differences = gate.diff_exports(left, right)
    assert any(d.field == "pd" for d in differences)
    assert any("outside a list of 0" in str(d.incremental) for d in differences)


def test_the_cite_ordinal_is_reported_once_and_the_counter_is_still_compared(
    tmp_path: Path,
) -> None:
    """`d309#1` against `d299#1` is ONE fact about the document, not one per block.

    `doc_ord` is assigned on first sight, so two stores that met the same document at different
    times number it differently -- and it rides inside every block's cite. The counter is the half
    that does converge and stays compared.
    """
    left = _archive(
        tmp_path / "a.owdoc",
        producers=[],
        blocks=[{"i": f"p0/{n}", "c": f"d309#{n}"} for n in range(5)],
    )
    right = _archive(
        tmp_path / "b.owdoc",
        producers=[],
        blocks=[{"i": f"p0/{n}", "c": f"d299#{n}"} for n in range(5)],
    )
    differences = gate.diff_exports(left, right)
    assert [(d.field, d.incremental, d.full) for d in differences] == [("doc_ord", "d309", "d299")]

    moved = _archive(
        tmp_path / "c.owdoc",
        producers=[],
        blocks=[{"i": f"p0/{n}", "c": f"d299#{n + 100}"} for n in range(5)],
    )
    counters = [d.field for d in gate.diff_exports(moved, right)]
    assert counters == ["c"] * 5, "a carried counter that differs is still reported"


def test_the_checkpoint_steps_always_include_the_last_and_never_the_first() -> None:
    """Step 0 is the same single ingest on both sides, so a rebuild of it cannot fail."""
    assert gate.checkpoint_steps(40, 10) == (10, 20, 30, 40)
    assert gate.checkpoint_steps(40, 40) == (40,)
    assert gate.checkpoint_steps(40, 1) == tuple(range(1, 41))
    assert gate.checkpoint_steps(40, 12) == (12, 24, 36, 40), "the last, whatever it divides into"
    assert 0 not in gate.checkpoint_steps(40, 10)


def test_a_cadence_of_zero_is_refused_rather_than_looping() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        gate.checkpoint_steps(40, 0)


def _checkpoint(tmp_path: Path, *, left: dict[str, object], right: dict[str, object]) -> object:
    incremental, full = tmp_path / "inc", tmp_path / "full"
    _archive(incremental / "k.owdoc", producers=[], blocks=[left])
    _archive(full / "k.owdoc", producers=[], blocks=[right])
    return gate.Checkpoint(step=7, incremental=incremental, full=full)


def test_a_divergence_at_a_checkpoint_names_the_step_it_was_found_at(tmp_path: Path) -> None:
    """A report that says "they differ" without saying WHEN sends a reader back through 40 steps."""
    checkpoint = _checkpoint(
        tmp_path,
        left={"i": "p0/0", "t": "before"},
        right={"i": "p0/0", "t": "after"},
    )

    def one(root: Path, steps: Sequence[int]) -> Iterator[object]:
        assert root is not None and steps
        yield checkpoint

    fixture = _plan(tmp_path / "corpus", documents=300, mutations=40)
    code, output = _run(["--fixture", str(fixture)], build=one)
    assert code == gate.EXIT_FAIL
    assert "step 7 ::" in output
    assert "before" in output and "after" in output


def test_an_archive_on_one_side_only_is_a_divergence_before_any_field_is_read(
    tmp_path: Path,
) -> None:
    """A deleted document that survived, or a new one that never arrived. The likeliest bug."""
    incremental, full = tmp_path / "inc", tmp_path / "full"
    _archive(incremental / "kept.owdoc", producers=[], blocks=[{"i": "p0/0"}])
    _archive(incremental / "stale.owdoc", producers=[], blocks=[{"i": "p0/0"}])
    _archive(full / "kept.owdoc", producers=[], blocks=[{"i": "p0/0"}])
    divergences, provenance, archives, _ = gate._diff_checkpoint(
        gate.Checkpoint(step=3, incremental=incremental, full=full)
    )
    assert archives == 2
    assert provenance == []
    assert [(d.field, d.incremental, d.full) for d in divergences] == [
        ("<archive>", "present", "absent")
    ]


def test_strict_folds_the_provenance_pass_back_into_the_failures(tmp_path: Path) -> None:
    """V10-8's literal reading, kept runnable so the concession is measured, not assumed."""
    checkpoint = _checkpoint(
        tmp_path,
        left={"i": "p0/0", "rm": 2},
        right={"i": "p0/0", "rm": 0},
    )

    def one(root: Path, steps: Sequence[int]) -> Iterator[object]:
        assert root is not None and steps
        yield checkpoint

    fixture = _plan(tmp_path / "corpus", documents=300, mutations=40)
    relaxed, relaxed_out = _run(["--fixture", str(fixture)], build=one)
    strict, strict_out = _run(["--fixture", str(fixture), "--strict"], build=one)

    assert relaxed == gate.EXIT_CLEAN, relaxed_out
    assert "PROVENANCE" in relaxed_out
    assert strict == gate.EXIT_FAIL, strict_out
    assert "THE EXPORTS DIFFER" in strict_out


def test_the_default_builder_is_the_indexer_and_is_named_exactly_once() -> None:
    """`build_with_index` is the only bridge from this harness to `tools/incremental_index.py`.

    Asserted by reading this file rather than by importing the indexer, which would pull a store,
    a parser and a fixture into a test about the harness. The claim in the module docstring is
    that the harness is not the indexer; this is that claim, checked.
    """
    path = _repo_root(Path(__file__)) / "tools" / "gate_incremental.py"
    source = path.read_text("utf-8")
    assert source.count('"incremental_index.py"') == 1, "one literal, in _load_index"
    assert source.count("spec_from_file_location") == 1, "one loader, at that one site"

    eager = {
        node.module
        for node in ast.parse(source, filename=str(path)).body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(module.startswith("omniweave") for module in eager), (
        "a gate that imported a distribution at module scope would be a gate that cannot run "
        "in a checkout where the distribution does not build"
    )
