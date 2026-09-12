"""`uv run pytest ... fuzz/ -q` -- the last of 16-roadmap.md:520's eight P3 exit commands.

This file is the *replay* half of `fuzz/`. The search half is atheris, which the root
`pyproject.toml` marks `atheris; sys_platform == 'linux'` because it "requires clang and publishes
no Windows wheel" (11-repo-layout.md:1480) -- so on six of the nine `test` cells it cannot be
installed at all, and a `fuzz/` that only worked under it would be a directory three quarters of
this project's CI never executes. What runs everywhere is the committed corpus, replayed through
every target with `omniweave_conform.mutate`'s seven mutations applied to each seed.

## The three things it asserts, in the order they matter

1. **Every target replays clean in a child process.** That is the gate. It is a child and not an
   in-process call because 04-driver-system.md:2082's rule -- *a crash is allowed, a hang is not*
   -- only means anything from outside the crashing thing: a segfault in pdfium does not reach its
   own reporting code, and `--journal` plus a dead child is how the input that caused it gets
   named. Both halves of that mechanism have a negative control below.

2. **The corpus is generated and checked, not maintained.** `fuzz/seeds/`'s mirrored half must be
   byte-identical to `vendor/anydoc/fuzz/seeds/` (`tools/mirror_fuzz_seeds.py --check`) and its
   authored half must be byte-identical to what `fuzz/targets/wire.py --write-seeds` writes today.
   A hand-edited seed corpus drifts silently, and the thing it drifts away from is the upstream
   commit G12 pins.

3. **The replay can fail.** Every clause has a red: a probe that escapes is a finding, a probe over
   budget is slow, a child that dies is named by its journal. 11-repo-layout.md section 6.8 calls
   the alternative "a check that cannot yet fail", and a fuzz harness that has never reported
   anything is exactly that shape -- three targets reporting `0 finding(s)` is only evidence if
   something proves a finding would have been reported.

## What a failure here means

`exit 1` is a **finding**: an exception escaped that is outside the target's `allowed` set, which
for a driver means an untyped failure `omniweave/run/dispatch.py` would have to guess a
`FailureClass` for, and for `wire` means a framing fault that is not a named `WireFault`.

`exit 3` or a timeout is a **hang**, and it is the one outcome the plan is absolute about.

An abnormal exit is a **crash**, and this file is stricter than 04-driver-system.md:2082 on
purpose. That line allows a crash because the `fuzz` conformance suite judges a *third-party*
driver and a host contains one. `fuzz/` runs over the two *first-party* drivers, and
02-architecture.md:1061 gates `inproc` to "a fuzz-green first-party driver" -- so a crash here is
evidence against DR9's own condition rather than a permitted outcome, and the assertion message
says so at the point a reader meets it.

Specified in 16-roadmap.md:520 and :482, 14-security.md:477-481, 04-driver-system.md section 8.2,
13-quality.md:133 and :163-168, and 11-repo-layout.md:390.
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess  # noqa: TID251 -- a child IS the mechanism; see the module docstring, clause 1
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

FUZZ = Path(__file__).resolve().parent
REPO = FUZZ.parent
TARGETS = FUZZ / "targets"
SEEDS = FUZZ / "seeds"

REPLAY_TIMEOUT_S = 300.0
"""The parent's stopping half. Generous against replays that take under a second here, because a
timeout that is close to the measured time turns a loaded CI runner into a red build -- and the
in-child per-input budget (`_harness.BUDGET_S`) is the one that catches a real hang precisely."""

EXPECTED_TARGETS = {"office", "pdf", "wire"}
"""The three, pinned. A fourth is a decision and not an accident.

`wire` is 16-roadmap.md:482's -- W3.2 owes "80 lines of framing plus an atheris target". `office`
and `pdf` are 14-security.md:477's "one target per format handler", and at P3 this repository has
exactly two format handlers. The day a third lands -- `parse.text.builtin` is the named candidate,
04-driver-system.md section 10.1, carried by no W-cell -- this set is where that shows up."""


def load(path: Path) -> ModuleType:
    """A target module, by path, under a name that cannot collide with a package."""
    spec = importlib.util.spec_from_file_location(f"_fuzz_target_{path.stem}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def target_paths() -> list[Path]:
    """Every public target file. `_harness.py` and `_parse.py` are shared halves, not targets."""
    return sorted(p for p in TARGETS.glob("*.py") if not p.name.startswith("_"))


@pytest.fixture(scope="session")
def harness() -> ModuleType:
    """`_harness`, under the name the targets themselves import it by.

    Loading it a second time by path would produce a second module object with a second `Target`
    class, and `isinstance(module.TARGET, Target)` would then be false for every target in the
    directory -- a failure about module identity wearing the costume of a failure about the
    targets. `sys.path` is what the targets prepend on import and this joins them there.
    """
    if str(TARGETS) not in sys.path:
        sys.path.insert(0, str(TARGETS))
    return importlib.import_module("_harness")


@pytest.fixture(scope="session")
def mirror() -> ModuleType:
    return load(REPO / "tools" / "mirror_fuzz_seeds.py")


# ---------------------------------------------------------------------------
# the register
# ---------------------------------------------------------------------------


def test_the_three_targets_are_the_three() -> None:
    assert {path.stem for path in target_paths()} == EXPECTED_TARGETS


@pytest.mark.parametrize("path", target_paths(), ids=lambda p: p.stem)
def test_every_target_declares_itself(path: Path, harness: ModuleType) -> None:
    """A target file exposes exactly one `TARGET`, named after itself.

    The name is what a finding is reported under and what a corpus directory is called, so a
    target whose `name` and filename disagree produces a report nobody can trace back to a file.
    """
    target = harness.declared(load(path))
    assert target.name == path.stem
    assert target.allowed, f"{path.stem} allows nothing, so every refusal it is specified to make"
    assert callable(target.probe)


@pytest.mark.parametrize("path", target_paths(), ids=lambda p: p.stem)
def test_every_declared_corpus_exists_and_holds_bytes(path: Path, harness: ModuleType) -> None:
    """An absent corpus is a target that fuzzes nothing while reporting `0 finding(s)`."""
    target = harness.declared(load(path))
    assert target.corpora, f"{path.stem} declares no corpus"
    for label, directory in target.corpora:
        assert directory.is_dir(), f"{label} -> {directory}"
        assert any(p.is_file() for p in directory.rglob("*")), label


def test_the_mirror_is_identical_to_the_vendored_corpus(mirror: ModuleType) -> None:
    """`fuzz/seeds/` is generated from `vendor/anydoc/fuzz/seeds/` and drift is a failure.

    The vendored tree is the artefact `vendor/anydoc/anydoc.sha256` digests and G12 checks, so a
    mirror that drifted would be a corpus nobody could trace to an upstream commit.
    """
    row = mirror.artefact_row()
    assert row is not None, "tools/vendor.toml has no vendor/anydoc row"
    assert mirror.check(row) == mirror.EXIT_OK


def test_the_wire_seeds_are_what_write_seeds_writes_today(tmp_path: Path) -> None:
    """The authored half of the corpus, checked the same way the mirrored half is.

    `wire` is the one target whose format this repository owns, so its seeds are written rather
    than mirrored -- and a written corpus needs the same guarantee a mirrored one gets, or the
    two halves of `fuzz/seeds/` are held to two different standards.
    """
    module = load(TARGETS / "wire.py")
    written = module.write_seeds(tmp_path / "wire")
    committed = sorted(p for p in (SEEDS / "wire").iterdir() if p.is_file())
    assert [p.name for p in written] == [p.name for p in committed]
    for fresh, old in zip(written, committed, strict=True):
        assert fresh.read_bytes() == old.read_bytes(), old.name


def test_the_readers_table_names_targets_that_exist() -> None:
    """`MIRROR.toml`'s `[readers]` is a claim about this directory and must stay true."""
    import tomllib  # noqa: PLC0415 -- one test needs it

    manifest = tomllib.loads((SEEDS / "MIRROR.toml").read_text(encoding="utf-8"))
    for corpus, reader in manifest["readers"].items():
        assert (SEEDS / corpus).is_dir(), corpus
        if reader:
            assert (REPO / reader).is_file(), reader


def test_a_corpus_with_a_reader_is_actually_read_by_it(harness: ModuleType) -> None:
    """`MIRROR.toml`'s `[readers]` must agree with what the target declares.

    Without this the table is prose: it could name `office.py` as `xlsb`'s reader while
    `office.py` declared only `xlsx`, and the ten `numfmt` seeds' honest `""` would read exactly
    the same as three corpora nobody had noticed were unwired.
    """
    import tomllib  # noqa: PLC0415 -- one test needs it

    manifest = tomllib.loads((SEEDS / "MIRROR.toml").read_text(encoding="utf-8"))
    for corpus_name, reader in manifest["readers"].items():
        if not reader:
            continue
        target = harness.declared(load(REPO / reader))
        declared = {directory.resolve() for _, directory in target.corpora}
        assert (SEEDS / corpus_name).resolve() in declared, f"{reader} does not read {corpus_name}"


# ---------------------------------------------------------------------------
# the corpus, expanded
# ---------------------------------------------------------------------------


def test_a_seed_yields_itself_and_then_its_mutations(harness: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "one").write_bytes(b"hello")
    items = list(harness.corpus((("c", tmp_path / "c"),)))
    assert items[0].mutation == "seed"
    assert items[0].data == b"hello"
    assert {item.mutation for item in items[1:]} == {
        "truncated@0.5",
        "truncated@0.05",
        "bitflip",
        "nul",
        "nested",
        "giant_length",
        "empty",
    }
    assert items[3].label == "c/one:bitflip"


def test_the_corpus_bookkeeping_is_never_fed_to_a_target(harness: ModuleType) -> None:
    """`MIRROR.toml` and `.gitattributes` are `fuzz/seeds/`'s paperwork, not inputs.

    The same defect the `harness.NOT_INPUTS` set was added for, one directory over: a target that
    parsed its own provenance record would record a refusal, and a refusal count that carries
    noise is a count nobody can scan for a real one.
    """
    names = {item.seed for item in harness.corpus((("seeds", SEEDS),))}
    assert "MIRROR.toml" not in names
    assert not any(name.endswith(".gitattributes") for name in names)
    assert "xlsx/sheet.xlsx" in names


# ---------------------------------------------------------------------------
# the negative controls -- the replay must be able to fail
# ---------------------------------------------------------------------------


def one(harness: ModuleType, data: bytes = b"x") -> tuple[Any, ...]:
    """One synthetic input, so a control needs no corpus on disk."""
    return (harness.Input("c", "s", "seed", data),)


def test_an_escape_outside_allowed_is_a_finding(harness: ModuleType) -> None:
    def probe(_data: bytes) -> None:
        raise ValueError("untyped")

    target = harness.Target(name="synthetic", probe=probe, allowed=(KeyError,), extras=one(harness))
    report = harness.replay(target)
    assert report.execs == 1
    assert len(report.findings) == 1
    assert report.findings[0].kind == "ValueError"
    assert report.exit_code == harness.EXIT_FINDING


def test_an_allowed_exception_is_a_refusal_and_not_a_finding(harness: ModuleType) -> None:
    def probe(_data: bytes) -> None:
        raise KeyError("typed")

    target = harness.Target(name="synthetic", probe=probe, allowed=(KeyError,), extras=one(harness))
    report = harness.replay(target)
    assert (report.refused, report.clean, report.findings) == (1, 0, ())
    assert report.exit_code == harness.EXIT_OK


def test_a_recursion_error_is_a_finding_where_it_is_not_allowed(harness: ModuleType) -> None:
    """The exact escape `omniweave_core.host.wire`'s docstring says the fuzz property forbids:
    "`RecursionError` is not a NAMED protocol error, which is exactly what the fuzz property
    forbids". A harness that caught `Exception` would have reported this as a refusal."""

    def probe(_data: bytes) -> None:
        raise RecursionError

    target = harness.Target(name="synthetic", probe=probe, allowed=(KeyError,), extras=one(harness))
    assert harness.replay(target).findings[0].kind == "RecursionError"


def test_an_input_over_the_budget_is_reported_as_slow(harness: ModuleType) -> None:
    def probe(_data: bytes) -> None:
        time.sleep(0.05)

    target = harness.Target(name="synthetic", probe=probe, allowed=(), extras=one(harness))
    report = harness.replay(target, budget_s=0.01)
    assert report.slow == ("c/s:seed",)
    assert report.exit_code == harness.EXIT_HANG


def test_the_journal_holds_the_input_the_probe_is_on(harness: ModuleType, tmp_path: Path) -> None:
    """The crash-naming mechanism, checked without a crash.

    The journal is written and flushed BEFORE each call, so a parent that finds a dead child reads
    the input that killed it. Here the child does not die, so the journal holds the last input --
    which is the same guarantee observed from the surviving side.
    """
    seen: list[str] = []
    journal = tmp_path / "j.txt"

    def probe(_data: bytes) -> None:
        seen.append(journal.read_text(encoding="utf-8").strip())

    target = harness.Target(
        name="synthetic",
        probe=probe,
        allowed=(),
        extras=(harness.Input("c", "a", "seed", b"1"), harness.Input("c", "b", "seed", b"2")),
    )
    harness.replay(target, journal=journal)
    assert seen == ["c/a:seed", "c/b:seed"]


# ---------------------------------------------------------------------------
# wire: each malformed seed reaches the fault it is named for
# ---------------------------------------------------------------------------

SEED_FAULTS = {
    # A corpus whose seeds all die at the first gate fuzzes one branch. Each row asserts the seed
    # reaches the check it was written for, which is the difference between a corpus and a pile.
    "empty": "short_prefix",
    "short-prefix": "short_prefix",
    "zero-lengths": "header_absent",
    "four-gib-prefix": "header_too_large",
    "header-over-cap": "header_too_large",
    "body-over-cap": "body_too_large",
    "header-truncated": "header_truncated",
    "header-not-utf8": "header_not_utf8",
    "header-not-json": "header_not_json",
    "header-not-object": "header_not_object",
    "kind-absent": "kind_absent",
    "kind-unknown": "kind_unknown",
    "header-too-deep": "header_too_deep",
}


@pytest.mark.parametrize(("seed", "fault"), sorted(SEED_FAULTS.items()))
def test_each_malformed_wire_seed_reaches_its_own_fault(seed: str, fault: str) -> None:
    module = load(TARGETS / "wire.py")
    from omniweave_core.errors import DriverHostError  # noqa: PLC0415 -- after the target loads

    with pytest.raises(DriverHostError) as caught:
        module.probe((SEEDS / "wire" / seed).read_bytes())
    assert fault in str(caught.value), f"{seed} did not reach {fault}"


def test_every_valid_wire_seed_decodes_and_round_trips() -> None:
    """The eleven kinds, through `probe` -- which is decode, re-encode and decode again."""
    module = load(TARGETS / "wire.py")
    valid = sorted((SEEDS / "wire").glob("valid-*"))
    assert len(valid) == 11, [p.name for p in valid]
    for path in valid:
        module.probe(path.read_bytes())


# ---------------------------------------------------------------------------
# THE EXIT LINE
# ---------------------------------------------------------------------------


def run_target(path: Path, tmp_path: Path, *extra: str) -> tuple[Any, str]:
    journal = tmp_path / f"{path.stem}.journal"
    done = subprocess.run(  # noqa: S603 -- sys.executable and a file in this repository
        [sys.executable, str(path), "--replay", "--journal", str(journal), *extra],
        capture_output=True,
        text=True,
        timeout=REPLAY_TIMEOUT_S,
        cwd=REPO,
        check=False,
    )
    last = journal.read_text(encoding="utf-8").strip() if journal.is_file() else "<no journal>"
    return done, last


@pytest.mark.parametrize("path", target_paths(), ids=lambda p: p.stem)
def test_the_target_replays_clean(path: Path, tmp_path: Path) -> None:
    """THE EXIT LINE. Every seed and every mutation of it, through the driver, in a child."""
    done, last = run_target(path, tmp_path)
    assert done.returncode == 0, (
        f"{path.stem} exited {done.returncode} on {last!r}.\n"
        f"  1 = a finding: an exception outside the target's `allowed` set escaped, which is an\n"
        f"      untyped failure omniweave/run/dispatch.py would have to guess a FailureClass for.\n"
        f"  3 = a hang: an input took longer than _harness.BUDGET_S. 04-driver-system.md:2082 is\n"
        f"      absolute about this one -- a crash is one row, a hang holds a worker.\n"
        f"  4 = the target could not run here at all.\n"
        f"  anything else = the child died. 04:2082 permits a crash from a THIRD-PARTY driver\n"
        f"      under the conformance suite, because a host contains one; these are the two\n"
        f"      first-party drivers and 02-architecture.md:1061 gates `inproc` to a fuzz-green\n"
        f"      first-party driver, so a crash here is evidence against DR9's own condition.\n"
        f"{done.stdout}{done.stderr[:2000]}"
    )
    assert "finding(s)" in done.stdout


def test_a_child_that_dies_is_named_by_its_journal(tmp_path: Path) -> None:
    """The negative control for the crash half, and it has to be a real crash.

    `ctypes.string_at(1)` dereferences address 1: a real access violation on Windows and a real
    SIGSEGV elsewhere -- not `sys.exit`, not an exception, and not something the child can be
    talked out of. `tools/ow_conform.py:202` uses the same technique for the same reason. Without
    this test, `--journal` is a mechanism that has never been observed doing its job.
    """
    journal = tmp_path / "j.txt"
    script = tmp_path / "dies.py"
    script.write_text(
        "import ctypes, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text('corpus/seed:bitflip\\n', encoding='utf-8')\n"
        "sys.stdout.flush()\n"
        "ctypes.string_at(1)\n",
        encoding="utf-8",
    )
    done = subprocess.run(  # noqa: S603 -- sys.executable and a file this test just wrote
        [sys.executable, str(script), str(journal)],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert done.returncode != 0, "the child was supposed to die and did not"
    assert journal.read_text(encoding="utf-8").strip() == "corpus/seed:bitflip"


# ---------------------------------------------------------------------------
# the atheris half
# ---------------------------------------------------------------------------


def test_the_fuzzing_half_says_it_cannot_run_rather_than_pretending() -> None:
    """No atheris means exit 4 and a sentence, never a silent exit 0.

    A target that returned 0 on a machine where no fuzzing happened would make the nightly job
    green on every platform that cannot fuzz, which is 11-repo-layout.md section 6.8's "a check
    that cannot yet fail" with the sign flipped.

    Where atheris IS importable this asserts nothing about a run, and that is a stated gap rather
    than an oversight: `atheris.Fuzz()` does not return, the nightly job 14-security.md:477
    specifies does not exist in `.github/workflows/ci.yml` (there is no `schedule:` in `on:`, the
    same gap ci.yml already records for `ow-bench-1`), and spawning a real fuzzing run from a unit
    test would be a PR gate with no bound on its wall clock.
    """
    if importlib.util.find_spec("atheris") is not None:
        pytest.skip("atheris is installed; the search half is the nightly job's, not a PR gate's")
    done = subprocess.run(  # noqa: S603 -- sys.executable and a file in this repository
        [sys.executable, str(TARGETS / "wire.py")],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=REPO,
        check=False,
    )
    assert done.returncode == 4, done.stdout + done.stderr
    assert "atheris" in done.stdout
    assert "--replay" in done.stdout
