"""G5 (`tools/check_versions.py`) and G2 (`tools/gate_weights.py`) hold against the plan.

Two gate scripts, one test module, because they read the same eighteen files and the same fourteen
distribution names and every interesting failure is a disagreement between them. Both are exercised
against the real workspace **and** against adversarial synthetic trees under `tmp_path`: the real
tree proves the numbers reproduce, and the synthetic trees prove the gates actually refuse — a gate
never seen to fail is a gate nobody has tested.

The transcribed constants below (`CEILINGS`, `PROFILE_SUMS`, `SITE_COUNTS`, `PLAN_WHY`) are the
plan's own tables copied here as literals so that a drift between `tools/*.toml` and 11-repo-layout
fails a test rather than passing silently in both places. That is the project's own hard-won lesson
applied to a declaration file: verify content, not shape.

Loci: 11-repo-layout.md sections 1.2 (the ceiling column), 2.2 (the extras block and G14), 2.3 (the
install-profile ceiling sums), 2.5 (`weights.toml` and its four failure modes), 4.1 (the Port-major
exception), 4.2 (the forty sites), 1.10 (rows 4 and 6); 16-roadmap.md section 4's P1 exit criteria.

These tests live in `omniweave-core`'s tree rather than a workspace-level one because
`[tool.pytest.ini_options] testpaths = ["packages"]` reaches no other tree, which is the same reason
`test_declaration_files.py` sits here.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load(name: str) -> ModuleType:
    """Load one `tools/*.py` script by path.

    `tools/` is not an importable package (11-repo-layout.md section 1.7 lists it as a directory of
    scripts, and G5 must run with nothing installed), so there is no module name to import. A
    `spec_from_file_location` load is neither `importlib.import_module` nor `__import__` — the two
    the framework bans outside `host/` — and it keeps `sys.path` unmutated, which matters because
    `test_purity.py` and `test_g17.py` assert things about the import state of this same session.
    """
    path = REPO / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"omniweave_tools_{name}", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


cv = _load("check_versions")
gw = _load("gate_weights")

DISTS = tuple(sorted(p.parent.name for p in REPO.glob("packages/*/pyproject.toml")))

SITE_COUNTS: tuple[tuple[str, int, bool], ...] = (
    ("dist [project] version", 13, True),
    ("omniweave-ports [project] version", 1, False),
    ("omniweave-core ~= bound", 7, False),
    ("omniweave-office ~= bound", 1, False),
    ("omniweave extras", 13, False),
    ("package.json version", 2, True),
    ("toolchains.toml version", 2, True),
    ("first_party.toml release", 1, True),
)
"""11-repo-layout.md section 4.2's count column and its "rewritten on a PATCH" column, transcribed
independently of `check_versions.SITE_CLASSES` so the two can be compared."""

CEILINGS: dict[str, int | None] = {
    "omniweave-ports": 1,
    "omniweave-core": 3,
    "omniweave": 25,
    "omniweave-office": 15,
    "omniweave-pdf": 30,
    "omniweave-serve": 40,
    "omniweave-graph": 5,
    "omniweave-llm": 2,
    "omniweave-target-pptx": 60,
    "omniweave-target-docx": 20,
    "omniweave-target-deck": 1,
    "omniweave-target-video": 1,
    "omniweave-vision": None,
    "omniweave-conform": 5,
}
"""The `ceiling` column of 11-repo-layout.md section 1.2's fourteen-row table, in its order.
`None` is that table's literal **UNBOUNDED** — the only one, and the only distribution exempt from
the 250 MB aggregate gate."""

PROFILE_SUMS: dict[str, int] = {
    "minimum": 44,
    "recommended": 174,
    "cpu-server": 201,
    "gpu-server": 181,
    "ci": 208,
}
"""Section 2.3's `ceiling sum` column. The **GPU server** row is deliberately smaller than the
**CPU server** row above it: it drops `docx` (20 MB) and adds `vision` (0 MB bounded), which is the
one install profile whose ceiling sum falls while its real installed size rises by an order of
magnitude."""

PLAN_WHY: dict[str, str] = {
    "omniweave-ports": "pure typing, no third party",
    "omniweave-core": "stdlib only; the number is the source tree plus generated data",
    "omniweave-pdf": "pypdfium2 bundles the pdfium binary; defusedxml is negligible",
    "omniweave-vision": (
        "torch + transformers; ow doctor prints the resolved size (the G2 exemption)"
    ),
}
"""The four `why` strings section 2.5's example block prints. The plan fixes no `why` for the other
ten, and `tools/weights.toml`'s header says so; these four must be verbatim."""

ATTACHMENTS = (
    "omniweave-langchain",
    "omniweave-haystack",
    "omniweave-llamaindex",
    "omniweave-adk",
    "omniweave-docling",
)
"""Section 1.2's second table. *"None is `RELEASE`-versioned, none appears in `first_party.toml`,
and none is in the 250 MB aggregate gate."*"""


# ---------------------------------------------------------------------------------------------
# Fixtures: synthetic workspaces
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A copy of the fourteen `pyproject.toml` files, and nothing else, under `tmp_path`.

    Copying the whole tree would take seconds and prove nothing extra: every site G5 owns lives in
    a `pyproject.toml`, a `package.json` or a `.toml` under `tools/`.
    """
    for dist in DISTS:
        target = tmp_path / "packages" / dist
        target.mkdir(parents=True)
        shutil.copy(REPO / "packages" / dist / "pyproject.toml", target / "pyproject.toml")
    (tmp_path / "tools").mkdir()
    return tmp_path


@pytest.fixture
def complete(workspace: Path) -> Path:
    """`workspace` plus the five sites that do not exist at P1, so all forty can be checked."""
    for name in ("deck", "video"):
        path = workspace / "toolchains" / name / "package.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"name": f"@omniweave/{name}", "version": "0.1.0"}), encoding="utf-8"
        )
    # Six-key rows and a `schema` line, transcribed from 11-repo-layout.md section 3.2's printed
    # manifest -- NOT the two keys `check_versions.py` happens to read.
    #
    # One file has two readers: this gate, which checks only that each row's `version` tracks
    # RELEASE, and `omniweave_core.toolchain.read_manifest`, which requires all six keys and
    # refuses an unknown one. A two-key fixture proves G5 against a register the runtime cannot
    # load, so the gate could pass on a file that fails at first use. Whether the *gate* should
    # also enforce the schema is a separate question -- it may import nothing first-party
    # (test_gates_structural.py) and so cannot share the key set -- but the fixture it is proven
    # against has no reason to be unloadable. test_the_fixture_register_is_one_the_runtime_can_read
    # below is what keeps the two in step.
    (workspace / "tools" / "toolchains.toml").write_text(
        "schema = 1\n\n"
        '[[toolchain]]\nname = "deck"\nversion = "0.1.0"\nentry = "dist/render.mjs"\n'
        'node_range = ">=20.11,<23"\n'
        f'bundle_sha256 = "sha256:{"1f0c9a" + "0" * 58}"\n'
        'bundle_url = "https://example.invalid/omniweave-toolchain-deck-0.1.0.tar.gz"\n\n'
        '[[toolchain]]\nname = "video"\nversion = "0.1.0"\nentry = "dist/render.mjs"\n'
        'node_range = ">=20.11,<23"\n'
        f'bundle_sha256 = "sha256:{"2e1d8b" + "0" * 58}"\n'
        'bundle_url = "https://example.invalid/omniweave-toolchain-video-0.1.0.tar.gz"\n',
        encoding="utf-8",
    )
    manifest = workspace / "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('release = "0.1.0"\n', encoding="utf-8")
    return workspace


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, f"{path} does not contain {old!r}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def _where(report: object) -> str:
    """Render every finding as `where -> expected / found`, which is what an assertion reads."""
    return " | ".join(
        f"{f.where} -> expected {f.expected!r}, found {f.found!r}"
        for f in report.findings  # type: ignore[attr-defined]
    )


# ---------------------------------------------------------------------------------------------
# G5 — the site table itself
# ---------------------------------------------------------------------------------------------


def test_the_site_table_is_forty_strings_across_eighteen_files() -> None:
    """Section 4.2's three totals, summed from the table rather than taken on trust."""
    assert cv.TOTAL_SITES == 40
    assert cv.TOTAL_FILES == 18
    assert cv.PATCH_SITES == 18


def test_every_site_class_reproduces_the_plan_row_for_row() -> None:
    assert len(cv.SITE_CLASSES) == len(SITE_COUNTS)
    for site, (_, count, patch) in zip(cv.SITE_CLASSES, SITE_COUNTS, strict=True):
        assert (site.count, site.patch) == (count, patch), site.name


def test_the_repository_has_the_fourteen_distributions_the_plan_names() -> None:
    assert len(DISTS) == cv.DIST_COUNT == 14
    assert set(DISTS) == set(CEILINGS)


def test_bound_derives_the_tilde_equals_constraint() -> None:
    assert cv.bound("0.4.2") == "0.4.0"
    assert cv.bound("1.0.0") == "1.0.0"
    assert cv.bound("12.34.56") == "12.34.0"


def test_extra_name_strips_omniweave_and_a_leading_target() -> None:
    assert cv.extra_name("omniweave-target-pptx") == "pptx"
    assert cv.extra_name("omniweave-vision") == "vision"
    assert {cv.extra_name(d) for d in set(DISTS) - cv.EXTRA_EXEMPT} == {
        "office",
        "pdf",
        "vision",
        "graph",
        "llm",
        "serve",
        "pptx",
        "docx",
        "deck",
        "video",
    }


def test_the_core_bound_seven_are_the_compile_dists_plus_serve_and_the_cli() -> None:
    """Section 4.2's *"the five `compile`-shipping dists plus `omniweave-serve` and `omniweave`"*.

    Re-derived from `tools/layers.toml`'s rule-4 rows — the distributions allowed to import
    `omniweave_core` — rather than trusted from the constant, because that is the same derivation
    G4 makes from entry points and the two must agree.
    """
    layers = tomllib.loads((REPO / "tools" / "layers.toml").read_text(encoding="utf-8"))
    rule_four = {
        name.replace("_", "-").replace("omniweave-target", "omniweave-target")
        for name, roots in layers.items()
        if "omniweave_core" in roots
    }
    assert rule_four == {d.replace("_", "-") for d in cv.CORE_BOUND_DISTS}
    assert len(cv.CORE_BOUND_DISTS) == 7


# ---------------------------------------------------------------------------------------------
# G5 — against the real workspace
# ---------------------------------------------------------------------------------------------


def test_the_real_workspace_passes_and_accounts_for_all_forty_sites() -> None:
    report = cv.check(REPO)
    assert not report.findings, _where(report)
    assert len(report.checked) + report.pending_sites == cv.TOTAL_SITES
    assert report.release == "0.1.0"
    assert report.port_major == 1


def test_the_five_absent_sites_are_reported_as_pending_and_never_skipped() -> None:
    """P1 has four of the eighteen files absent, carrying five of the forty sites.

    `toolchains/{deck,video}/package.json` and `tools/toolchains.toml` land at P9 with the
    `toolchains` job (16-roadmap.md section 3); `first_party.toml` is generated into `src/` by the
    `build` job and is `.gitignore`d, so it never exists in a checkout (section 2.6).
    """
    report = cv.check(REPO)
    assert {p.path for p in report.pending} == {
        "toolchains/deck/package.json",
        "toolchains/video/package.json",
        "tools/toolchains.toml",
        "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml",
    }
    assert report.pending_sites == 5
    assert len(report.checked) == 35
    assert all(p.lands for p in report.pending)
    assert report.ok()
    assert not report.ok(require_all_sites=True)


def test_the_ports_exception_does_not_read_as_a_failure() -> None:
    """Section 4.1's exception to "one `RELEASE`", and the false failure a naive gate reports."""
    report = cv.check(REPO)
    assert "packages/omniweave-ports/pyproject.toml: [project] version = 1.0.0" in report.checked
    assert any("Port major 1.0.0, not by RELEASE" in note for note in report.notes)


def test_a_complete_tree_reaches_forty_of_forty(complete: Path) -> None:
    report = cv.check(complete)
    assert not report.findings, _where(report)
    assert not report.pending
    assert len(report.checked) == cv.TOTAL_SITES
    assert report.ok(require_all_sites=True)


def test_the_git_tag_is_asserted_and_never_written(complete: Path) -> None:
    assert cv.check(complete, tag="v0.1.0").ok()
    bad = cv.check(complete, tag="v0.1.1")
    assert "git tag" in _where(bad)


# ---------------------------------------------------------------------------------------------
# G5 — adversarial: each refusal names the right file and the right key
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("dist", "old", "new", "expect"),
    [
        ("omniweave-pdf", 'version = "0.1.0"', 'version = "0.1.1"', "omniweave-pdf/pyproject.toml"),
        (
            "omniweave-serve",
            '"omniweave-core ~= 0.1.0"',
            '"omniweave-core ~= 0.2.0"',
            "omniweave-core ~=",
        ),
        (
            "omniweave-serve",
            '"omniweave-ports >=1,<2"',
            '"omniweave-ports >=2,<3"',
            "the omniweave-ports floor",
        ),
        ("omniweave", '"omniweave-office ~= 0.1.0",', "", "omniweave-office ~="),
        ("omniweave-ports", 'version = "1.0.0"', 'version = "0.1.0"', "[project] version"),
    ],
)
def test_one_wrong_site_is_one_named_finding(
    workspace: Path, dist: str, old: str, new: str, expect: str
) -> None:
    _edit(workspace / "packages" / dist / "pyproject.toml", old, new)
    report = cv.check(workspace)
    assert report.findings
    assert expect in _where(report), _where(report)


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ('vision = ["omniweave-vision ~= 0.1.0"]', 'all = ["omniweave-vision ~= 0.1.0"]', "[all]"),
        ('vision = ["omniweave-vision ~= 0.1.0"]', 'vision = ["torch>=2"]', "[vision]"),
        ('vision = ["omniweave-vision ~= 0.1.0"]', "", "[vision]"),
        ('llm = ["omniweave-llm ~= 0.1.0"]', 'llm = ["omniweave-graph ~= 0.1.0"]', "injectivity"),
        (
            'pdf = ["omniweave-pdf ~= 0.1.0"]',
            'pdf = ["omniweave-pdf ~= 0.1.0", "pypdfium2"]',
            "[pdf]",
        ),
        (
            'deck = ["omniweave-target-deck ~= 0.1.0"]',
            'deck = ["omniweave-target-deck ~= 0.9.0"]',
            "[deck] ~=",
        ),
    ],
)
def test_the_extras_block_refuses_every_g14_violation(
    workspace: Path, old: str, new: str, expect: str
) -> None:
    """G14's four clauses plus section 2.2's "no extra may name a third-party package"."""
    _edit(workspace / "packages" / "omniweave" / "pyproject.toml", old, new)
    report = cv.check(workspace)
    assert report.findings, "a G14 violation passed"
    assert expect in _where(report), _where(report)


def test_recommended_losing_a_member_is_a_finding(workspace: Path) -> None:
    path = workspace / "packages" / "omniweave" / "pyproject.toml"
    _edit(path, ', "omniweave-target-pptx ~= 0.1.0"]', "]")
    assert "recommended" in _where(cv.check(workspace))


def test_recommended_is_serve_pdf_and_pptx_and_not_docx() -> None:
    """Section 1.2: `omniweave-target-docx` is deliberately not in `[recommended]`."""
    assert cv.RECOMMENDED == ("omniweave-serve", "omniweave-pdf", "omniweave-target-pptx")
    assert "omniweave-target-docx" not in cv.RECOMMENDED
    assert set(gw.read_recommended(REPO)) == set(cv.RECOMMENDED)


def test_a_deleted_distribution_is_a_finding(workspace: Path) -> None:
    shutil.rmtree(workspace / "packages" / "omniweave-llm")
    report = cv.check(workspace)
    assert "14 distributions" in " ".join(f.expected for f in report.findings)


def test_a_toolchain_row_that_exists_and_disagrees_fails(complete: Path) -> None:
    _edit(complete / "tools" / "toolchains.toml", 'version = "0.1.0"', 'version = "0.1.9"')
    assert "toolchains.toml: [[toolchain]][0] version" in _where(cv.check(complete))


def test_a_package_json_that_exists_and_disagrees_fails(complete: Path) -> None:
    _edit(complete / "toolchains" / "deck" / "package.json", '"0.1.0"', '"0.9.9"')
    assert "toolchains/deck/package.json: version" in _where(cv.check(complete))


def test_a_first_party_manifest_that_exists_and_disagrees_fails(complete: Path) -> None:
    manifest = complete / "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml"
    _edit(manifest, '"0.1.0"', '"0.0.9"')
    assert "first_party.toml: release" in _where(cv.check(complete))


def test_a_changelog_whose_heading_names_another_release_fails(complete: Path) -> None:
    (complete / "CHANGELOG.md").write_text("# 0.9.9 - unreleased\n", encoding="utf-8")
    assert "CHANGELOG.md: topmost heading" in _where(cv.check(complete))
    (complete / "CHANGELOG.md").write_text("# 0.1.0 - first\n", encoding="utf-8")
    assert cv.check(complete).ok()


# ---------------------------------------------------------------------------------------------
# G5 — the writer half
# ---------------------------------------------------------------------------------------------


def _count(repo: Path, needle: str) -> int:
    files = [*repo.glob("packages/*/pyproject.toml"), *repo.glob("toolchains/*/package.json")]
    files.append(repo / "tools" / "toolchains.toml")
    return sum(f.read_text(encoding="utf-8").count(needle) for f in files if f.is_file())


def test_set_rewrites_thirty_eight_of_the_forty_on_a_minor(complete: Path) -> None:
    """A MINOR moves every site but two: `omniweave-ports`' Port major, and `first_party.toml`.

    Section 4.2's table gives `first_party.toml`'s writer as the `build` job rather than `--set`,
    and the Port-major row as "written by `--set`: yes / rewritten on a PATCH: no" — `--set`
    normalises it and a `RELEASE` bump does not move it (section 4.1).
    """
    cv.write_release(complete, "9.7.3")
    assert _count(complete, "9.7.3") == 17
    assert _count(complete, "9.7.0") == 21
    assert _count(complete, "9.7.3") + _count(complete, "9.7.0") == 38
    ports = (complete / "packages" / "omniweave-ports" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'version = "1.0.0"' in ports
    manifest = complete / "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml"
    assert 'release = "0.1.0"' in manifest.read_text(encoding="utf-8")


def test_set_rewrites_seventeen_on_a_patch_and_the_eighteenth_is_the_build_job(
    complete: Path,
) -> None:
    """Section 4.2's last column: **18** of the 40 are rewritten on a PATCH.

    Seventeen of those eighteen are `--set`'s: thirteen `[project] version` fields, two
    `package.json` versions and two `toolchains.toml` rows. The eighteenth is
    `first_party.toml`'s `release`, whose writer column reads *"generated in `build` (§7.2)"* — so
    a `--set` that rewrote it would be writing a `.gitignore`d file the build regenerates.
    """
    cv.write_release(complete, "9.7.3")
    before = _count(complete, "9.7.0")
    cv.write_release(complete, "9.7.9")
    assert _count(complete, "9.7.9") == 17
    assert _count(complete, "9.7.0") == before, "a PATCH must not move a ~= bound"


def test_set_leaves_a_tree_that_checks_clean_and_still_parses(complete: Path) -> None:
    """After `--set`, the only disagreement left is the site `--set` deliberately does not write.

    `first_party.toml` still holds the old `RELEASE` because the `build` job regenerates it from
    `dist/` (section 7.2) and `--set` never touches a `.gitignore`d generated file. That the gate
    *reports* it rather than skipping it is the point: a release commit whose manifest was not
    regenerated is exactly the failure the `build.first_party_manifest` job assertion exists for.
    """
    cv.write_release(complete, "9.7.3")
    report = cv.check(complete)
    assert [f.where for f in report.findings] == [
        "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml: release"
    ], _where(report)
    assert len(report.checked) == cv.TOTAL_SITES - 1
    for path in complete.glob("packages/*/pyproject.toml"):
        tomllib.loads(path.read_text(encoding="utf-8"))

    manifest = complete / "packages/omniweave-core/src/omniweave_core/drivers/first_party.toml"
    manifest.write_text('release = "9.7.3"\n', encoding="utf-8")
    assert cv.check(complete).ok(require_all_sites=True)


def test_set_is_idempotent(complete: Path) -> None:
    cv.write_release(complete, "9.7.3")
    snapshot = {p: p.read_bytes() for p in sorted(complete.rglob("*")) if p.is_file()}
    assert cv.write_release(complete, "9.7.3") == []
    assert {p: p.read_bytes() for p in sorted(complete.rglob("*")) if p.is_file()} == snapshot


def test_set_preserves_the_do_not_hand_edit_comment(complete: Path) -> None:
    """The extras block's own comment is the thing telling a human not to do what `--set` does."""
    path = complete / "packages" / "omniweave" / "pyproject.toml"
    cv.write_release(complete, "9.7.3")
    text = path.read_text(encoding="utf-8")
    assert "GENERATED by tools/check_versions.py --set; asserted by G5" in text
    assert "Do not hand-edit a bound." in text


def test_set_writes_lf_even_from_a_crlf_working_tree(workspace: Path) -> None:
    """Section 1.9 rule 2: every generator writes `"\\n"` explicitly, never the platform default."""
    path = workspace / "packages" / "omniweave-pdf" / "pyproject.toml"
    path.write_bytes(path.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8"))
    cv.write_release(workspace, "9.7.3")
    assert b"\r" not in path.read_bytes()


def test_set_refuses_a_release_that_is_not_a_semver(workspace: Path) -> None:
    with pytest.raises(ValueError, match=r"M\.m\.p"):
        cv.write_release(workspace, "0.4")


def test_set_can_move_the_port_major_only_when_asked(workspace: Path) -> None:
    cv.write_release(workspace, "9.7.3", port_major=2)
    ports = (workspace / "packages" / "omniweave-ports" / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'version = "2.0.0"' in ports
    assert "the omniweave-ports floor" in _where(cv.check(workspace, port_major=2))


def test_main_returns_zero_on_the_real_workspace_and_one_when_a_site_is_wrong(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cv.main(["--repo", str(REPO)]) == 0
    assert "G5 PASS" in capsys.readouterr().out
    _edit(workspace / "packages" / "omniweave-graph" / "pyproject.toml", '"0.1.0"', '"0.1.4"')
    assert cv.main(["--repo", str(workspace)]) == 1
    assert "G5 FAIL" in capsys.readouterr().out


def test_require_all_sites_fails_on_a_p1_checkout(capsys: pytest.CaptureFixture[str]) -> None:
    assert cv.main(["--repo", str(REPO), "--require-all-sites"]) == 1
    out = capsys.readouterr().out
    assert "FAIL tools/toolchains.toml" in out
    assert "G5 FAIL" in out


# ---------------------------------------------------------------------------------------------
# G2 — the declaration
# ---------------------------------------------------------------------------------------------


def test_weights_declares_one_row_per_distribution_and_no_attachment() -> None:
    schema, aggregate, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    assert schema == 1
    assert aggregate == 250
    assert set(rows) == set(DISTS) == set(CEILINGS)
    assert len(rows) == 14
    assert not set(rows) & set(ATTACHMENTS)


def test_every_ceiling_is_the_one_the_distribution_table_prints() -> None:
    """Section 1.2's `ceiling` column, transcribed. A raised number is a reviewable act, and this
    test is the review's other half: raising one here without moving section 1.2's row fails."""
    _, _, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    for dist, ceiling in CEILINGS.items():
        row = rows[dist]
        if ceiling is None:
            assert row.unbounded and row.marginal_mb == 0, dist
        else:
            assert not row.unbounded and row.marginal_mb == ceiling, dist


def test_vision_is_the_only_unbounded_row() -> None:
    _, _, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    assert [d for d, r in rows.items() if r.unbounded] == ["omniweave-vision"]


def test_every_row_carries_a_why_and_the_four_the_plan_prints_are_verbatim() -> None:
    _, _, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    for dist, row in rows.items():
        assert row.why.strip(), f"{dist} has no `why` line"
    for dist, why in PLAN_WHY.items():
        assert rows[dist].why == why, dist


def test_the_declaration_gate_passes_on_the_real_workspace() -> None:
    schema, aggregate, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    result = gw.check_declaration(REPO, schema, aggregate, rows)
    assert result.ok, result.findings


def test_every_install_profile_reproduces_its_ceiling_sum() -> None:
    """Section 2.3's `ceiling sum` column, derived from the workspace and compared to the plan."""
    _, _, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    for profile, expected in PROFILE_SUMS.items():
        members = gw.profile_roots(REPO, profile) & set(rows)
        total = sum(rows[d].marginal_mb for d in members if not rows[d].unbounded)
        assert total == expected, f"{profile}: {sorted(members)}"


def test_the_ci_profile_is_the_thirteen_bounded_rows_summed_longhand() -> None:
    """Section 2.3 spells this one out because reading the table wrong is easy."""
    assert PROFILE_SUMS["ci"] == 1 + 3 + 25 + 15 + 30 + 40 + 5 + 2 + 60 + 20 + 1 + 1 + 5
    assert gw.profile_roots(REPO, "ci") == set(DISTS) - {"omniweave-vision"}


def test_the_recommended_closure_is_seven_distributions_with_headroom() -> None:
    members = gw.profile_roots(REPO, "recommended")
    assert members == {
        "omniweave",
        "omniweave-core",
        "omniweave-ports",
        "omniweave-office",
        "omniweave-serve",
        "omniweave-pdf",
        "omniweave-target-pptx",
    }
    _, aggregate, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    assert aggregate - sum(rows[d].marginal_mb for d in members) == 76


def test_the_minimum_profile_is_the_four_a_bare_pip_install_gets() -> None:
    assert gw.profile_roots(REPO, "minimum") == {
        "omniweave",
        "omniweave-core",
        "omniweave-ports",
        "omniweave-office",
    }


@pytest.mark.parametrize(
    ("mutate", "expect"),
    [
        (lambda rows: rows.pop("omniweave-llm"), "fails closed"),
        (
            lambda rows: rows.__setitem__(
                "omniweave-graph", gw.Row("omniweave-graph", 5, False, "")
            ),
            "no `why` line",
        ),
        (
            lambda rows: rows.__setitem__(
                "omniweave-vision", gw.Row("omniweave-vision", 3000, True, "torch")
            ),
            "unbounded rows carry marginal_mb = 0",
        ),
        (
            lambda rows: rows.__setitem__(
                "omniweave-ghost", gw.Row("omniweave-ghost", 1, False, "invented")
            ),
            "no packages/omniweave-ghost/pyproject.toml",
        ),
    ],
)
def test_the_declaration_gate_refuses_each_malformed_row(mutate: object, expect: str) -> None:
    _, aggregate, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    mutate(rows)  # type: ignore[operator]
    result = gw.check_declaration(REPO, 1, aggregate, rows)
    assert result.findings
    assert any(expect in f for f in result.findings), result.findings


def test_a_recommended_sum_above_the_aggregate_is_unsatisfiable_and_refused() -> None:
    _, _, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    result = gw.check_declaration(REPO, 1, 100, rows)
    assert any("unsatisfiable" in f for f in result.findings), result.findings


def test_a_wrong_schema_is_refused() -> None:
    _, aggregate, rows = gw.load_weights(REPO / "tools" / "weights.toml")
    assert any("schema is 2" in f for f in gw.check_declaration(REPO, 2, aggregate, rows).findings)


def test_main_prints_both_numbers_even_with_nothing_measured(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Section 2.5: *"prints both numbers on every run, pass or fail"* — and never invents one."""
    assert gw.main(["--repo", str(REPO)]) == 0
    out = capsys.readouterr().out
    assert "per-row sum        not measured" in out
    assert "deduplicated union not measured" in out
    assert "G2 PASS" in out


# ---------------------------------------------------------------------------------------------
# G2 — the measurement, against a synthetic site-packages
# ---------------------------------------------------------------------------------------------


def _install(
    site: Path, dist: str, version: str, requires: list[str], files: dict[str, int]
) -> None:
    """Write one wheel's worth of installed artefacts: a package tree, a RECORD and a METADATA."""
    info = site / f"{dist.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    rows: list[str] = []
    for name, size in files.items():
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * size)
        rows.append(f"{name},sha256=deadbeef,{size}")
    lines = [f"Name: {dist}", f"Version: {version}"]
    lines += [f"Requires-Dist: {r}" for r in requires]
    (info / "METADATA").write_text("\n".join(lines) + "\n\nsummary body\n", encoding="utf-8")
    # A real wheel lists its own dist-info in RECORD, RECORD's own size column being empty.
    rows.append(f"{info.name}/METADATA,sha256=deadbeef,{(info / 'METADATA').stat().st_size}")
    rows.append(f"{info.name}/RECORD,,")
    (info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")


@pytest.fixture
def site_packages(tmp_path: Path) -> Path:
    """Four first-party distributions and one third-party package shared by two of them."""
    site = tmp_path / "site-packages"
    site.mkdir()
    _install(site, "omniweave-ports", "1.0.0", [], {"omniweave_ports/__init__.py": 1_000})
    _install(
        site, "omniweave-core", "0.1.0", ["omniweave-ports"], {"omniweave_core/__init__.py": 2_000}
    )
    _install(
        site,
        "omniweave-pdf",
        "0.1.0",
        ["omniweave-ports", "shared-lib"],
        {"omniweave_pdf/__init__.py": 3_000},
    )
    _install(
        site,
        "omniweave-serve",
        "0.1.0",
        ["omniweave-core", "omniweave-ports", "shared-lib"],
        {"omniweave_serve/__init__.py": 4_000},
    )
    _install(site, "shared-lib", "1.0", [], {"shared_lib/big.bin": 10_000_000})
    return site


ROWS = {
    "omniweave-ports": gw.Row("omniweave-ports", 1, False, "pure typing, no third party"),
    "omniweave-core": gw.Row("omniweave-core", 3, False, "stdlib only"),
    "omniweave-pdf": gw.Row("omniweave-pdf", 30, False, "pypdfium2"),
    "omniweave-serve": gw.Row("omniweave-serve", 40, False, "mcp"),
}


def test_a_row_excludes_first_party_siblings_and_includes_the_third_party_it_introduces(
    site_packages: Path,
) -> None:
    """Section 2.5's marginal reading, measured.

    `omniweave-serve` depends on `omniweave-core`, so core's bytes belong to core's row and not to
    serve's; `shared-lib` belongs to **both** rows, which is the acknowledged double-count that
    `aggregate_mb` exists to remove by deduplicating on installed path rather than summing rows.
    """
    m = gw.measure(site_packages)
    first_party = frozenset(ROWS)
    assert gw._third_party_closure(m, "omniweave-serve", first_party) == {"shared-lib"}
    assert gw._third_party_closure(m, "omniweave-pdf", first_party) == {"shared-lib"}
    assert gw._third_party_closure(m, "omniweave-ports", first_party) == set()

    result = gw.Result()
    gw._apply_measurement(result, m, ROWS)
    assert result.row_sum_bytes - result.union_bytes == m.dists["shared-lib"].actual_bytes
    assert result.union_bytes > 10_000_000
    assert not result.findings


def test_a_row_over_its_ceiling_fails_and_names_its_largest_files(site_packages: Path) -> None:
    rows = {**ROWS, "omniweave-pdf": gw.Row("omniweave-pdf", 1, False, "deliberately too small")}
    result = gw.Result()
    gw._apply_measurement(result, gw.measure(site_packages), rows)
    assert any(
        "omniweave-pdf: 10.00 MB measured against a 1 MB ceiling" in f for f in result.findings
    )
    assert any("big.bin" in f for f in result.findings)
    assert any(line.startswith("  over   omniweave-pdf") for line in result.table)


def test_an_unbounded_row_reports_its_size_and_never_fails(site_packages: Path) -> None:
    """An `unbounded` row is measured, printed and exempted - never failed, never in the union.

    Section 1.2: `omniweave-vision` is the only `UNBOUNDED` ceiling and the only distribution
    exempt from the 250 MB aggregate gate, because a plan that promises a number for a CUDA wheel
    set is lying. `omniweave-pdf` stands in for it here so the fixture stays small.
    """
    m = gw.measure(site_packages)
    bounded = gw.Result()
    gw._apply_measurement(bounded, m, ROWS)

    exempted = gw.Result()
    rows = {**ROWS, "omniweave-pdf": gw.Row("omniweave-pdf", 0, True, "torch + transformers")}
    gw._apply_measurement(exempted, m, rows)

    assert not exempted.findings
    assert any("exempt omniweave-pdf" in line for line in exempted.table)
    assert exempted.row_sum_bytes == bounded.row_sum_bytes
    dropped = bounded.union_bytes - exempted.union_bytes
    assert dropped == m.dists["omniweave-pdf"].actual_bytes, "only pdf's own files leave the union"
    assert exempted.union_bytes > 10_000_000, "shared-lib stays: serve's row still bounds it"


def test_a_file_outside_every_record_defeats_nothing(site_packages: Path) -> None:
    """Section 2.5 failure mode 3: `RECORD` is a manifest, not a filesystem."""
    rogue = site_packages / "rogue" / "payload.bin"
    rogue.parent.mkdir()
    rogue.write_bytes(b"y" * 4_000_000)
    result = gw.Result()
    gw._apply_measurement(result, gw.measure(site_packages), ROWS)
    assert any("exceeds the RECORD manifest" in f for f in result.findings)
    assert any("rogue" in f and "payload.bin" in f for f in result.findings)


def test_an_environment_measured_before_first_import_says_so(site_packages: Path) -> None:
    """Section 2.5 failure mode 4: `__pycache__` is written on first run, not on install."""
    result = gw.Result()
    gw._apply_measurement(result, gw.measure(site_packages), ROWS)
    assert any("BEFORE first import" in n for n in result.notes)

    cached = site_packages / "omniweave_core" / "__pycache__" / "__init__.cpython-311.pyc"
    cached.parent.mkdir()
    cached.write_bytes(b"z" * 500)
    warmed = gw.Result()
    gw._apply_measurement(warmed, gw.measure(site_packages), ROWS)
    assert not any("BEFORE first import" in n for n in warmed.notes)


def test_an_extras_gated_requirement_is_not_attributed_to_the_row(tmp_path: Path) -> None:
    """A `Requires-Dist: x; extra == "y"` edge is installed only when that extra was asked for, so
    following it unconditionally would charge a row for 9 MB it did not pull in."""
    site = tmp_path / "site-packages"
    site.mkdir()
    _install(
        site,
        "omniweave-pdf",
        "0.1.0",
        ['optional-thing; extra == "extras"'],
        {"omniweave_pdf/__init__.py": 3_000},
    )
    _install(site, "optional-thing", "1.0", [], {"optional_thing/blob.bin": 9_000_000})
    m = gw.measure(site)
    assert gw._third_party_closure(m, "omniweave-pdf", frozenset({"omniweave-pdf"})) == set()
    result = gw.Result()
    gw._apply_measurement(result, m, {"omniweave-pdf": ROWS["omniweave-pdf"]})
    assert result.row_sum_bytes < 1_000_000
    assert result.row_sum_bytes == m.dists["omniweave-pdf"].actual_bytes


def test_the_measured_gate_runs_end_to_end_and_reports_two_real_numbers(
    site_packages: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The synthetic tree holds four of the fourteen rows and none is over, so this passes - and
    prints a per-row sum exceeding the union by exactly the shared dependency's 10 MB."""
    assert gw.main(["--repo", str(REPO), "--measure", str(site_packages)]) == 0
    out = capsys.readouterr().out
    assert re.search(r"per-row sum\s+20\.\d\d MB", out), out
    assert re.search(r"deduplicated union\s+10\.\d\d MB", out), out
    assert "not measured" not in out
    assert "G2 PASS" in out


def test_the_measured_gate_exits_one_when_a_row_is_over(
    site_packages: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = "".join(
        f'[dist."{d}"]\nmarginal_mb = {1 if d == "omniweave-pdf" else 50}\nwhy = "t"\n\n'
        for d in DISTS
    )
    weights = tmp_path / "weights.toml"
    weights.write_text(f"schema = 1\naggregate_mb = 250\n{rows}", encoding="utf-8")
    args = ["--repo", str(REPO), "--weights", str(weights), "--measure", str(site_packages)]
    assert gw.main(args) == 1
    assert "G2 FAIL" in capsys.readouterr().out


def test_the_fixture_register_is_one_the_runtime_can_read(complete: Path) -> None:
    """`tools/toolchains.toml` has two readers, and the fixture must satisfy both.

    G5 checks one column of that file -- each `[[toolchain]]` row's `version` against RELEASE --
    and `omniweave_core.toolchain.read_manifest` checks the whole grammar: all six keys of
    11-repo-layout.md section 3.2's printed manifest, required, with an unknown key a hard error.
    The gate cannot share the key set, because test_gates_structural.py holds every `tools/`
    gate to importing nothing first-party; a gate that imported `omniweave_core` to learn the
    schema would also be a gate that fails to run when core is broken.

    So the agreement is asserted here instead, from a test file, which may import freely. Without
    it the two readers drift silently in the one direction that matters: a fixture the gate
    accepts and the runtime refuses means G5 can pass on a register that fails at first use --
    which is exactly what a two-key fixture did before this test existed.
    """
    # Deferred deliberately, and not merely to satisfy a linter. `toolchain` is one of the nine
    # LAZY names, and this module is imported at collection time by a session in which
    # test_purity.py, test_g17.py and test_config.py all make assertions about what is in
    # `sys.modules`. A module-level import here would put `omniweave_core.toolchain` into the
    # shared session for every one of them; inside the test body it lands only when this test runs.
    from omniweave_core.config import ConfigError  # noqa: PLC0415
    from omniweave_core.toolchain import TOOLCHAIN_KEYS, read_manifest  # noqa: PLC0415

    manifest = read_manifest(complete / "tools" / "toolchains.toml")
    assert sorted(spec.name for spec in manifest.toolchains) == ["deck", "video"]
    # And the six-key set really is what made it loadable: drop one key from the first row and
    # the runtime reader must refuse, so this test cannot pass by reading a laxer grammar.
    path = complete / "tools" / "toolchains.toml"
    text = path.read_text(encoding="utf-8")
    assert "entry" in TOOLCHAIN_KEYS
    path.write_text(text.replace('entry = "dist/render.mjs"\n', "", 1), encoding="utf-8")
    with pytest.raises(ConfigError):
        read_manifest(path)
