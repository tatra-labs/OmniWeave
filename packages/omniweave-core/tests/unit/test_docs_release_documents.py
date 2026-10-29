"""`docs/verify.md` and `docs/TS-SDK-TRIGGER.md`, the two release documents. D1012.

11-repo-layout.md's `docs/` tree names both (lines 436-437) and the charter §D9 names
`TS-SDK-TRIGGER.md` itself, but G27 clause (d)'s walk is section 8.6's own words --
`docs/ARCHITECTURE.md` and `docs/plan/*.md` -- so neither is in it, and widening that walk would
contradict a plan-stated scope rather than fix a gate. These are their checks instead.

The last test is the interesting one. `docs/verify.md`'s recipes name the repository the artefacts
will actually come from, while `release.yml:316` still pins cosign's identity regexp to a different
slug, so the document carries a note saying so. That note is a declared exception, and a declared
exception is checked in BOTH directions: the day the workflow agrees with the shipped homepage, the
note is wrong and this test says so.
"""

from __future__ import annotations

import re
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
RELEASE_YML: Final = REPO_ROOT / ".github" / "workflows" / "release.yml"
LLMS: Final = REPO_ROOT / "packages" / "omniweave" / "src" / "omniweave" / "gen" / "llms.py"

_LINK: Final = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
_SLUG: Final = re.compile(r"github(?:\\)?\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)")

SLUG_NOTE: Final = "The repository slug disagrees with itself."
"""The declared exception in `docs/verify.md`'s "Before the first release" section."""


@pytest.mark.parametrize("document", [VERIFY, TRIGGER], ids=lambda one: one.name)
def test_the_document_the_plan_names_exists_and_is_not_a_stub(document: Path) -> None:
    """11-repo-layout.md:436-437. A named file that is absent is the quiet kind of unbuilt."""
    assert document.is_file(), f"11-repo-layout.md's docs/ tree names {document.name}"
    assert len(document.read_text(encoding="utf-8").split()) > 200, "a placeholder, not a document"


@pytest.mark.parametrize("document", [VERIFY, TRIGGER], ids=lambda one: one.name)
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


def test_verify_md_says_release_yml_cannot_complete_a_release_yet() -> None:
    """The workflow's own header says it; a verification document that omitted it would send a
    reader after a blob no release from this tree produces."""
    text = VERIFY.read_text(encoding="utf-8")
    assert "sbom-sign" in text and "exits 1" in text
    assert "W10.9" in text, "the roadmap item that turns the marked steps into commands"
    workflow = RELEASE_YML.read_text(encoding="utf-8").lower()
    assert "cannot complete a release today" in workflow, (
        "if release.yml no longer says this, docs/verify.md's note is the stale one"
    )


def test_ts_sdk_trigger_states_both_halves_of_the_written_condition() -> None:
    """11-repo-layout.md:1015 gives the trigger verbatim: a first non-toolchain in-tree TS
    consumer, or three external requests. A trigger missing one half is not a trigger."""
    text = TRIGGER.read_text(encoding="utf-8")
    assert "non-toolchain in-tree TypeScript consumer" in text
    assert "Three external requests" in text
    assert "ow surface typescript" in text, "what a consumer gets today instead"


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
