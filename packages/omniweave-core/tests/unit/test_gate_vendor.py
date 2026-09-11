"""G12 tested as a program: all four checks, each shown a red.

`tools/gate_vendor.py` is the enforcer of 11-repo-layout.md:1555's row — *"every vendored artefact:
sha256, parity test, arch assertion, NOTICE row"* — and of 14-security.md:1273's rule for a
vendored artefact. 14-security.md:1244 prices what each of the four is worth by naming what the
mined collection does without them: Unlimited-OCR's install step one is "a 12.4 MB unsigned
prebuilt wheel committed to git, with no hash, no signature and no index"; codegraph "records shas
in comments with a parity test and no NOTICE"; hyperframes "checks architecture with no hash and no
NOTICE".

**A gate nobody has seen fail is a gate nobody has tested**, so each of the four is shown the
violation it exists for, over a synthetic `vendor/` tree in `tmp_path`:

* a changed byte under a recorded digest;
* a file in the tree that the manifest does not cover, and a manifest row for a file that is not
  there — both directions, because a manifest covering only what someone remembered to list is not
  a manifest;
* an `omniweave_core.limits` ceiling BELOW anydoc's for the same vector, which is 14:498's whole
  subject: the Python-side ceiling must never silently be the tighter one;
* `py.detach` gone from the binding, which is the S1 in-process seam's entire warrant (14:502) and
  which would otherwise hold the GIL for every decode with no symptom but latency;
* a missing NOTICE, an SPDX id off the allowlist, and a branch name where a commit SHA belongs;
* a directory under `vendor/` with no row in the register.

Specified in 11-repo-layout.md sections 1.7 and 6.4; 14-security.md sections 2.10, 8 and 9;
16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ARTEFACT = "vendor/anydoc"


@pytest.fixture(scope="session")
def gate(repo_root: Path) -> ModuleType:
    """`tools/gate_vendor.py`, loaded by path and never put on `sys.path`."""
    path = repo_root / "tools" / "gate_vendor.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_vendor", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def artefact(repo_root: Path, tmp_path: Path) -> Path:
    """A copy of `vendor/anydoc` under `tmp_path`, with the gate pointed at it.

    A copy rather than the real tree, because every test below breaks something and a test that
    edited `vendor/` would leave the repository in the state it was asserting about.
    """
    import shutil  # noqa: PLC0415 -- a test helper, not library code.

    source = repo_root / "vendor" / "anydoc"
    target = tmp_path / "vendor" / "anydoc"
    shutil.copytree(source, target)
    return target


def _row(version: str = "0.2.4") -> dict[str, object]:
    return {
        "path": ARTEFACT,
        "version": version,
        "spdx": "MIT",
        "manifest": "anydoc.sha256",
        "notice": "NOTICE",
        "fork_trigger": "FORK-TRIGGER.md",
        "commit": "261fc257d17c3eab0f673be31c408fd9fdc2171a",
        "distribution": "firecrawl-anydoc",
        "arch": "abi3",
        "pinned_by": "packages/omniweave-office/pyproject.toml",
    }


# ---------------------------------------------------------------------------
# green on HEAD
# ---------------------------------------------------------------------------


def test_the_gate_is_green_on_head(gate: ModuleType) -> None:
    """The same statement 16-roadmap.md:514 makes at the shell."""
    assert gate.main([]) == 0


def test_the_gate_refuses_arguments_rather_than_ignoring_them(gate: ModuleType) -> None:
    """Exit 2 is "the gate did not run", which is a different fact from "the property is false"."""
    assert gate.main(["--all"]) == 2


def test_the_gate_imports_nothing_first_party(repo_root: Path) -> None:
    """It must run against a tree whose packages do not import — which is when vendoring breaks."""
    import ast  # noqa: PLC0415

    source = (repo_root / "tools" / "gate_vendor.py").read_text(encoding="utf-8")
    named: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            named.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            named.append(node.module or "")
    assert [name for name in named if name.startswith("omniweave")] == []
    stdlib = frozenset(sys.stdlib_module_names) | {"__future__"}
    assert [name for name in named if name.split(".", 1)[0] not in stdlib] == []


# ---------------------------------------------------------------------------
# check 1 -- sha256
# ---------------------------------------------------------------------------


def test_a_changed_byte_under_a_recorded_digest_is_a_finding(
    gate: ModuleType, artefact: Path
) -> None:
    """The whole point of recording a digest, asserted."""
    target = artefact / "Cargo.toml"
    target.write_bytes(target.read_bytes() + b"\n# tampered\n")
    findings = gate.check_digests("anydoc", artefact, "anydoc.sha256")
    assert [f.check for f in findings] == ["sha256"]
    assert "Cargo.toml" in findings[0].message


def test_a_file_the_manifest_does_not_cover_is_a_finding(gate: ModuleType, artefact: Path) -> None:
    """A manifest covering only what someone remembered to list is not a manifest."""
    (artefact / "src" / "smuggled.rs").write_text("fn main() {}\n", encoding="utf-8")
    findings = gate.check_digests("anydoc", artefact, "anydoc.sha256")
    assert any("smuggled.rs" in f.message and "not in" in f.message for f in findings)


def test_a_manifest_row_with_no_file_is_a_finding(gate: ModuleType, artefact: Path) -> None:
    """The other direction: a row whose file was deleted."""
    (artefact / "rustfmt.toml").unlink()
    findings = gate.check_digests("anydoc", artefact, "anydoc.sha256")
    assert any("rustfmt.toml" in f.message for f in findings)


def test_the_manifest_covers_every_vendored_file(gate: ModuleType, repo_root: Path) -> None:
    """No findings on the real tree, and the count is not zero — a gate over nothing is green."""
    directory = repo_root / "vendor" / "anydoc"
    assert gate.check_digests("anydoc", directory, "anydoc.sha256") == []
    rows = [
        line
        for line in (directory / "anydoc.sha256").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(rows) > 100
    assert all(len(line.split("  ")[0]) == 64 for line in rows)


# ---------------------------------------------------------------------------
# check 2 -- parity
# ---------------------------------------------------------------------------


def test_the_parity_check_is_green_on_head(gate: ModuleType, repo_root: Path) -> None:
    assert gate.check_parity("anydoc", repo_root / "vendor" / "anydoc", _row()) == []


def test_a_version_disagreement_between_source_and_register_is_a_finding(
    gate: ModuleType, artefact: Path
) -> None:
    findings = gate.check_parity("anydoc", artefact, _row(version="9.9.9"))
    assert any("9.9.9" in f.message for f in findings)


def test_a_core_ceiling_below_anydocs_is_a_finding(
    gate: ModuleType, artefact: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """14-security.md:498's assertion, shown its red.

    A Python-side ceiling BELOW the Rust one would be the tighter limit while every message and
    every operator's mental model says the Rust constant is what fires. The bump is meant to be a
    reviewed event; this is what makes it one.
    """
    monkeypatch.setattr(gate, "_core_limits", lambda: {"MAX_XML_DEPTH": 8})
    findings = gate.check_parity("anydoc", artefact, _row())
    assert any("MAX_XML_DEPTH" in f.message and "BELOW" in f.message for f in findings)


def test_an_unmapped_upstream_constant_is_a_finding(gate: ModuleType, artefact: Path) -> None:
    """A twelfth ceiling upstream is a reviewed event, not a silent pass."""
    limits = artefact / "src" / "package" / "limits.rs"
    limits.write_text(
        limits.read_text(encoding="utf-8") + "\npub const MAX_FUTURE_THING: usize = 1;\n",
        encoding="utf-8",
    )
    findings = gate.check_parity("anydoc", artefact, _row())
    assert any("MAX_FUTURE_THING" in f.message for f in findings)


def test_py_detach_disappearing_from_the_binding_is_a_finding(
    gate: ModuleType, artefact: Path
) -> None:
    """The S1 seam's entire warrant. Losing it would hold the GIL with no symptom but latency."""
    binding = artefact / "python" / "src" / "lib.rs"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace(
            "py.detach(|| anydoc::to_document", "(|| anydoc::to_document"
        ),
        encoding="utf-8",
    )
    findings = gate.check_parity("anydoc", artefact, _row())
    assert any("py.detach" in f.message for f in findings)


def test_an_error_class_the_driver_catches_disappearing_is_a_finding(
    gate: ModuleType, artefact: Path
) -> None:
    binding = artefact / "python" / "src" / "lib.rs"
    binding.write_text(
        binding.read_text(encoding="utf-8").replace("EncryptedError", "GoneError"),
        encoding="utf-8",
    )
    findings = gate.check_parity("anydoc", artefact, _row())
    assert any("EncryptedError" in f.message for f in findings)


def test_the_gates_limit_map_agrees_with_the_drivers(gate: ModuleType) -> None:
    """The one duplication INV-21 permits, and the test that makes it a copy rather than a fork.

    The gate may not import `omniweave_office`, so the map exists twice. What INV-21 asks for when
    a fact genuinely must live in two places is exactly this: one home, and a test that the copy
    is a copy.
    """
    from omniweave_office.limits import CEILINGS  # noqa: PLC0415

    assert set(gate.ANYDOC_LIMITS) == {name.upper() for name in CEILINGS}
    for name, ceiling in CEILINGS.items():
        assert gate.ANYDOC_LIMITS[name.upper()] == ceiling.core


# ---------------------------------------------------------------------------
# checks 3 and 4 -- arch and the NOTICE row
# ---------------------------------------------------------------------------


def test_the_arch_assertion_is_green_on_the_installed_wheel(gate: ModuleType) -> None:
    assert gate.check_arch("anydoc", _row()) == []


def test_an_uninstalled_distribution_is_an_arch_finding(gate: ModuleType) -> None:
    """A recorded digest over source says nothing about the binary a user will run."""
    row = _row()
    row["distribution"] = "a-distribution-nobody-published"
    findings = gate.check_arch("anydoc", row)
    assert [f.check for f in findings] == ["arch"]


def test_a_missing_notice_is_a_finding(gate: ModuleType, artefact: Path) -> None:
    (artefact / "NOTICE").unlink()
    findings = gate.check_register("anydoc", artefact, _row(), {"MIT"})
    assert any("NOTICE" in f.message for f in findings)


def test_an_spdx_id_off_the_allowlist_is_a_finding(gate: ModuleType, artefact: Path) -> None:
    row = _row()
    row["spdx"] = "AGPL-3.0-only"
    findings = gate.check_register("anydoc", artefact, row, {"MIT"})
    assert any("AGPL-3.0-only" in f.message for f in findings)


def test_a_branch_name_where_a_commit_belongs_is_a_finding(
    gate: ModuleType, artefact: Path
) -> None:
    """The same rule 04-driver-system.md applies to `[weights] revision = "main"` on a card."""
    row = _row()
    row["commit"] = "main"
    findings = gate.check_register("anydoc", artefact, row, {"MIT"})
    assert any("not a 40-character SHA" in f.message for f in findings)


def test_an_unregistered_directory_under_vendor_is_a_finding(
    gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Source nobody attributed and nobody is checking is the thing G12 exists to prevent."""
    fake = tmp_path / "vendor"
    (fake / "somebody-elses-crate").mkdir(parents=True)
    monkeypatch.setattr(gate, "VENDOR", fake)
    assert gate.main([]) == 1


def test_the_register_covers_every_directory_under_vendor(repo_root: Path) -> None:
    """The register and the tree agree on HEAD, and `vendor/` is not empty."""
    import tomllib  # noqa: PLC0415

    register = tomllib.loads((repo_root / "tools" / "vendor.toml").read_text(encoding="utf-8"))
    registered = {Path(str(row["path"])).name for row in register["artefact"]}
    present = {p.name for p in (repo_root / "vendor").iterdir() if p.is_dir()}
    assert present == registered
    assert present


def test_the_recorded_commit_is_the_one_the_notice_and_the_manifest_name(
    repo_root: Path,
) -> None:
    """Three files carry the SHA; a reader who finds two of them disagreeing cannot proceed."""
    import tomllib  # noqa: PLC0415

    register = tomllib.loads((repo_root / "tools" / "vendor.toml").read_text(encoding="utf-8"))
    row = next(r for r in register["artefact"] if r["path"] == ARTEFACT)
    commit = str(row["commit"])
    directory = repo_root / "vendor" / "anydoc"
    assert commit in (directory / "NOTICE").read_text(encoding="utf-8")
    assert commit in (directory / "anydoc.sha256").read_text(encoding="utf-8")


def test_the_fork_trigger_names_two_clauses_and_a_runnable_command_for_each(
    repo_root: Path,
) -> None:
    """16-roadmap.md:1130: a fork trigger names a **testable** condition.

    Two clauses (16:1137) and a command under each, because a condition nobody can evaluate is a
    paragraph rather than a trigger. Clause 1's command is the test in this repository that fails
    the day anydoc emits a source address; clause 2's is `ow bench inproc`.
    """
    text = (repo_root / "vendor" / "anydoc" / "FORK-TRIGGER.md").read_text(encoding="utf-8")
    clauses = [line for line in text.splitlines() if line.startswith("## Clause ")]
    assert len(clauses) == 2
    assert "uv run pytest" in text
    assert "ow bench inproc" in text
    assert "origin_span_is_none_and_the_reason_is_checkable" in text


def test_clause_one_names_a_test_that_exists(repo_root: Path) -> None:
    """A trigger pointing at a test nobody wrote is the failure mode this test is for."""
    named = repo_root / "packages" / "omniweave-office" / "tests" / "unit" / "test_office_card.py"
    assert named.is_file()
    assert "def test_origin_span_is_none_and_the_reason_is_checkable" in named.read_text(
        encoding="utf-8"
    )


def test_the_digest_manifest_and_the_tree_digest_agree(repo_root: Path) -> None:
    """The manifest's header records a digest OVER the rows, so a reordered manifest is visible."""
    text = (repo_root / "vendor" / "anydoc" / "anydoc.sha256").read_text(encoding="utf-8")
    recorded = next(
        line.split("sha256:", 1)[1].strip() for line in text.splitlines() if "# tree " in line
    )
    rows = "".join(line + "\n" for line in text.splitlines() if line and not line.startswith("#"))
    assert hashlib.sha256(rows.encode("utf-8")).hexdigest() == recorded
