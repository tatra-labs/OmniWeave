"""`docs/verify.md`, `docs/TS-SDK-TRIGGER.md` and `docs/driver-authors.md`. D1012, D1013.

11-repo-layout.md's `docs/` tree names all three (lines 436-438) and the charter §D9 names
`TS-SDK-TRIGGER.md` itself, but G27 clause (d)'s walk is section 8.6's own words --
`docs/ARCHITECTURE.md` and `docs/plan/*.md` -- so none of them is in it, and widening that walk
would contradict a plan-stated scope rather than fix a gate. These are their checks instead.

The last test is the interesting one. `docs/verify.md`'s recipes name the repository the artefacts
will actually come from, while `release.yml:316` still pins cosign's identity regexp to a different
slug, so the document carries a note saying so. That note is a declared exception, and a declared
exception is checked in BOTH directions: the day the workflow agrees with the shipped homepage, the
note is wrong and this test says so.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Final

import pytest


def _repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT: Final = _repo_root(Path(__file__).resolve())
DOCS: Final = REPO_ROOT / "docs"
VERIFY: Final = DOCS / "verify.md"
TRIGGER: Final = DOCS / "TS-SDK-TRIGGER.md"
AUTHORS: Final = DOCS / "driver-authors.md"
RELEASE_YML: Final = REPO_ROOT / ".github" / "workflows" / "release.yml"
LLMS: Final = REPO_ROOT / "packages" / "omniweave" / "src" / "omniweave" / "gen" / "llms.py"

_LINK: Final = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_SLUG: Final = re.compile(r"github(?:\\)?\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")

SLUG_NOTE: Final = "The repository slug disagrees with itself."
"""The declared exception in `docs/verify.md`'s "Before the first release" section."""

_SEMVER: Final = re.compile(r"(?<![\w.])v?(\d+\.\d+\.\d+)(?![\w.])")
"""Every version in these documents, with an optional `v` prefix stripped by the capture.

The prefix is why this is not `\\b\\d+\\.\\d+\\.\\d+\\b`. That was the first spelling here, and it
cannot match `v0.1.0` AT ALL: `v` is a word character, so there is no word boundary between it and
the `0`, and every tag in every recipe was invisible to it. Reverting `--source-tag v1.0.0` to
`v0.1.0` left the test below PASSING, which is clause d0's lesson -- a regex that silently matches
nothing turns the assertion above it into a pass -- and it was caught by driving the mutation
rather than by reading the pattern.
"""

RELEASE: Final[str] = tomllib.loads(
    (REPO_ROOT / "packages" / "omniweave-core" / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
"""`RELEASE`, read from the one site that declares it."""

NOT_THE_RELEASE: Final[frozenset[str]] = frozenset({"4.30.1"})
"""Versions in these documents that are deliberately NOT `RELEASE`, each with its reason.

`4.30.1` is `pypdfium2`'s, in `driver-authors.md`'s worked `dependencies = ["pypdfium2>=4.30,
!=4.30.1"]` -- a third party's yanked patch, which has nothing to do with ours and must not move
when ours does.
"""


@pytest.mark.parametrize("document", [VERIFY, TRIGGER, AUTHORS], ids=lambda one: one.name)
def test_the_document_the_plan_names_exists_and_is_not_a_stub(document: Path) -> None:
    """11-repo-layout.md:436-438. A named file that is absent is the quiet kind of unbuilt."""
    assert document.is_file(), f"11-repo-layout.md's docs/ tree names {document.name}"
    assert len(document.read_text(encoding="utf-8").split()) > 200, "a placeholder, not a document"


@pytest.mark.parametrize("document", [VERIFY, TRIGGER, AUTHORS], ids=lambda one: one.name)
def test_every_relative_link_resolves(document: Path) -> None:
    """What G27 clause (d3) does for the plan, done here, because (d)'s walk excludes these two."""
    missing = [
        target
        for target in _LINK.findall(document.read_text(encoding="utf-8"))
        if not target.startswith(("http://", "https://", "#"))
        and not (document.parent / target.split("#")[0]).is_file()
    ]
    assert not missing, missing


def test_verify_md_carries_section_7_5s_four_recipes_and_its_honest_paragraph() -> None:
    """11-repo-layout.md:2077: *"four recipes and one paragraph of honesty"*. Both halves."""
    text = VERIFY.read_text(encoding="utf-8")
    for tool in ("gh attestation verify", "slsa-verifier verify-artifact", "cosign verify-blob"):
        assert tool in text, tool
    assert "tools/manifest_diff.py" in text, "recipe 4 is the one this repository had to build"
    assert len(re.findall(r"^## \d\. ", text, re.MULTILINE)) == 4, "four numbered recipes"
    # Section 7.5's paragraph, by the claim it makes rather than by its wording.
    assert "They prove nothing about a **third-party driver**" in text
    assert "omniweave.lock" in text, "the one thing that does catch a swapped driver wheel"


def test_verify_md_says_which_recipes_a_v1_0_tag_can_actually_satisfy() -> None:
    """D1016 changed what this document owes a reader. The publish half of `release.yml` is gated
    off, so recipes 1 and 2 verify artefacts a `v*` tag really produces -- the 28 reproducible
    files and `provenance.intoto.jsonl` -- while recipe 3 has no SBOM to verify and recipe 4 no
    signed asset. A verification document that listed four recipes without saying which two work
    today would send a reader after a blob no release from this tree produces.

    The condition is asserted as the literal that `release.yml` carries, so the document cannot
    describe a gate the workflow has stopped applying.
    """
    text = VERIFY.read_text(encoding="utf-8")
    assert "vars.OMNIWEAVE_RELEASE_PUBLISH == 'true'" in text, "the gate, as the workflow spells it"
    assert text.count("sbom-sign") >= 1 and "W10.9" in text
    assert "the `release` environment is not needed for v1.0" in text, (
        "the consequence a reader would otherwise have to derive from how environments scope"
    )
    workflow = RELEASE_YML.read_text(encoding="utf-8")
    assert "if: vars.OMNIWEAVE_RELEASE_PUBLISH == 'true'" in workflow, (
        "if release.yml no longer gates the publish half, docs/verify.md's note is the stale one"
    )
    assert "cannot complete a release" in workflow.lower()


def test_ts_sdk_trigger_states_both_halves_of_the_written_condition() -> None:
    """11-repo-layout.md:1015 gives the trigger verbatim: a first non-toolchain in-tree TS
    consumer, or three external requests. A trigger missing one half is not a trigger."""
    text = TRIGGER.read_text(encoding="utf-8")
    assert "non-toolchain in-tree TypeScript consumer" in text
    assert "Three external requests" in text
    assert "ow surface typescript" in text, "what a consumer gets today instead"


def test_driver_authors_names_the_runner_that_exists_and_not_the_verb_that_does_not() -> None:
    """`ow conform` is not a shipped CLI verb, though the plan writes it that way in several
    places: `omniweave-conform` has no console script and no `__main__`. A document that told an
    author to run it would be a recipe that fails on its first command.
    """
    text = AUTHORS.read_text(encoding="utf-8")
    assert "tools/ow_conform.py" in text, "the runner that exists"
    assert "`ow conform` is **not** a shipped CLI verb" in text, "and the document says so"
    # Every mention of the verb must be the disclaimer itself. An "is it used as a command"
    # test would pass vacuously here -- the document has no line-initial `ow` command at all --
    # so the check is over occurrences, which there are, and the count is asserted with them.
    mentions = [line for line in text.splitlines() if "ow conform" in line]
    assert len(mentions) == 1, mentions
    assert "not** a shipped CLI verb" in mentions[0], mentions[0]


def test_driver_authors_states_what_the_kit_run_measured() -> None:
    """The two numbers in the run section are a measurement, and the 8 is the interesting one:
    a bare `run(subject)` leaves the three cross-process suites failing for harness reasons, which
    is exactly the failure D923 and D967 record. A document that printed only the 11 would send an
    author to debug their driver."""
    text = AUTHORS.read_text(encoding="utf-8")
    assert "11 of 11 through the script, 8 of 11 through a bare" in text
    for suite in ("idempotence", "determinism", "fuzz"):
        assert suite in text, suite
    assert "tools/ow_conform.py" in text


def test_driver_authors_keeps_the_two_grammars_apart() -> None:
    """The one thing in 11-repo-layout.md section 1.5 worth reading twice: the entry-point value is
    a colon-free dotted package and the card's `entrypoint` is `module:attr`."""
    text = AUTHORS.read_text(encoding="utf-8")
    assert "subrip_cues.driver:SubRipParser" in text, "the card's module:attr form"
    assert "^[a-z_][a-z0-9_]*(\\.[a-z_][a-z0-9_]*)*$" in text, "G4's own pattern"
    assert "no ':' and no '/'" in text.replace("`", "'"), "the colon-free rule, stated"


def test_driver_authors_carries_both_honest_limitations() -> None:
    """Both are already in CHANGELOG.md's known limitations; an author reading only this document
    has to meet them too, because each one changes what they build."""
    text = AUTHORS.read_text(encoding="utf-8")
    assert "cannot be routed yet" in text and "sniff" in text
    assert "inherits no `PYTHONPATH`" in text


def _slug(text: str) -> str | None:
    found = _SLUG.search(text)
    return found.group(1).lower() if found else None


def test_the_slug_note_is_present_exactly_while_the_workflow_disagrees() -> None:
    """The declared exception, checked in both directions.

    `release.yml` verifies its own signature against an identity regexp, and a signature issued by
    this repository has to match it. The shipped `llms.txt` homepage is the other statement of who
    this repository is. While the two disagree, `docs/verify.md` must say so; when they agree, the
    note must go, or the document is carrying a warning about a problem that was fixed.
    """
    workflow = _SLUG.search(
        next(
            line
            for line in RELEASE_YML.read_text(encoding="utf-8").splitlines()
            if "certificate-identity-regexp" in line
        )
    )
    assert workflow is not None, "release.yml's cosign identity no longer names a repository"
    homepage = _slug(LLMS.read_text(encoding="utf-8"))
    assert homepage is not None, "llms.py no longer carries a HOMEPAGE naming a repository"
    note = SLUG_NOTE in VERIFY.read_text(encoding="utf-8")
    if workflow.group(1).lower() == homepage:
        assert not note, (
            f"release.yml and llms.py now agree on {homepage}; "
            "drop the slug note from docs/verify.md's 'Before the first release'"
        )
    else:
        assert note, (
            f"release.yml verifies against {workflow.group(1)} and llms.py publishes {homepage}; "
            "docs/verify.md must say so until they agree"
        )


@pytest.mark.parametrize("document", [VERIFY, TRIGGER, AUTHORS], ids=lambda one: one.name)
def test_every_version_a_reader_would_type_is_this_release(document: Path) -> None:
    """D1022's lesson, held so it cannot happen twice.

    `docs/verify.md` prints `RELEASE` and the repository slug VERBATIM in each recipe, on purpose:
    *"a recipe a reader has to assemble is a recipe a reader gets wrong."* The cost of that choice
    is that a release bump rots every recipe at once, and nothing noticed -- after `--set 1.0.0`
    all four still named `omniweave_core-0.1.0-py3-none-any.whl` and `--source-tag v0.1.0`, so
    checklist step 15, whose whole job is *"a recipe that no longer works, discovered by a user"*,
    would have been the thing that discovered it.

    So every semver in these documents is `RELEASE` unless it is a declared exception with a
    reason. The exception set is held in both directions below.
    """
    found = set(_SEMVER.findall(document.read_text(encoding="utf-8")))
    stale = found - {RELEASE} - NOT_THE_RELEASE
    assert not stale, (
        f"{document.name} names {sorted(stale)}, which is neither {RELEASE} nor declared"
    )


def test_the_not_the_release_set_is_used_and_is_not_a_blanket() -> None:
    """The exception, checked the other way. A version listed here that no document carries is an
    exemption nobody needs, and one that happens to equal `RELEASE` would silently excuse the thing
    the test above exists to catch."""
    carried = set()
    for document in (VERIFY, TRIGGER, AUTHORS):
        carried |= set(_SEMVER.findall(document.read_text(encoding="utf-8")))
    assert carried >= NOT_THE_RELEASE, (
        f"declared but absent: {sorted(NOT_THE_RELEASE - carried)}; drop it from NOT_THE_RELEASE"
    )
    assert RELEASE not in NOT_THE_RELEASE, "the release cannot be its own exception"


def test_verify_mds_recipes_name_the_wheel_and_the_tag_this_release_builds() -> None:
    """Not just "a version appears" -- the two spellings a reader copies: the wheel filename that
    `build` actually writes, and the `v`-prefixed tag that `release.yml` triggers on."""
    text = VERIFY.read_text(encoding="utf-8")
    assert f"omniweave_core-{RELEASE}-py3-none-any.whl" in text
    assert f"--source-tag v{RELEASE}" in text
    assert f"first-party-{RELEASE}.json" in text
