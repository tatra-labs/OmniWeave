"""G3 tested as a program: the policy matches the plan, and each surface goes red on cue.

`tools/gate_licences.py` is the only reader of `tools/licences.toml`, and between them they carry
three of 11-repo-layout.md section 9.2's seven segregation layers' worth of build-time evidence. A
licence gate is the kind of program that is green for years and is never once shown a violation, so
four kinds of test here, in the order they matter:

* **the declaration is the plan's.** `[allow] spdx`, `[deny] spdx` and `[deny] prefix` are compared
  element-for-element against the TOML fence 14-security.md section 9.2 prints. That fence is the
  specification; a drifted allowlist would silently change what `pip-licenses --allow-only` is
  given (11-repo-layout.md section 9.4 item 1) as well as what CI enforces.
* **each surface goes red when shown the violation it exists for**, over synthetic trees and
  synthetic distribution metadata. The import-graph tests reproduce the plan's own regression
  fixture: `cairosvg`, LGPL-3.0, imported and undeclared.
* **the detector survives its known false friends.** The GPL-3 text carries "GNU Affero General
  Public License" in section 13 and the PSF text recites the GPL by name in its CNRI history;
  neither is copyleft-licensed and both broke an earlier draft of `TEXT_MARKERS`.
* **the gate runs on HEAD** and returns one of its three documented exit codes.

The gate is loaded by file path with `importlib.util`, never by `importlib.import_module` and
never by putting `tools/` on `sys.path` — the same discipline `test_gates_structural.py` states.

Specified in 16-roadmap.md section 4 (the P1 exit line), 14-security.md section 9.2,
11-repo-layout.md section 9.2 layer 2, 04-driver-system.md section 7.4 and 17-risks.md R-L1.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import textwrap
import tomllib
from email.message import Message
from importlib.metadata import distributions as _installed_distributions
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from conftest import PlanDocs


def _load(repo_root: Path) -> ModuleType:
    """Load `tools/gate_licences.py` under a private name. See `test_gates_structural._load`."""
    path = repo_root / "tools" / "gate_licences.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_licences", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def gate(repo_root: Path) -> ModuleType:
    return _load(repo_root)


@pytest.fixture(scope="session")
def policy(gate: ModuleType) -> Any:
    """`tools/licences.toml`, parsed and validated. Loading it at all is an assertion."""
    return gate.load_policy()


def _dist(**headers: str | list[str]) -> SimpleNamespace:
    """A stand-in for `importlib.metadata.Distribution` carrying only what `spdx_evidence` reads.

    `Distribution.metadata` is an `email.message.Message`, so this is the real type with real
    multi-valued header semantics rather than a dict pretending to be one.
    """
    message = Message()
    for key, value in headers.items():
        header = key.replace("_", "-")
        for item in value if isinstance(value, list) else [value]:
            message[header] = item
    return SimpleNamespace(metadata=message)


# The genuine section 13 heading of GPL-3, which names the AGPL inside a text that is not the AGPL.
GPL3_TEXT = """
                    GNU GENERAL PUBLIC LICENSE
                       Version 3, 29 June 2007

  13. Use with the GNU Affero General Public License.

  Notwithstanding any other provision of this License, you have permission to link or combine any
  covered work with a work licensed under version 3 of the GNU Affero General Public License into
  a single combined work.
"""

AGPL3_TEXT = """
                    GNU AFFERO GENERAL PUBLIC LICENSE
                       Version 3, 19 November 2007

  Copyright (C) 2007 Free Software Foundation, Inc.
"""

# The CNRI history paragraph of the PSF licence, which recites the GPL by name and grants nothing
# under it. It is the text `typing_extensions` ships.
PSF_TEXT = """
PSF LICENSE AGREEMENT FOR PYTHON

This LICENSE AGREEMENT is between the Python Software Foundation and the Individual or
Organization ("Licensee") accessing Python.  ...  those releases based on Python 1.6.1 that
incorporate non-separable material that was previously distributed under the GNU General Public
License (GPL), the law of the Commonwealth of Virginia shall govern this License Agreement.
"""

MIT_TEXT = """
MIT License

Copyright (c) 2022 Example

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction.
"""


# ---------------------------------------------------------------------------
# The declaration is the plan's
# ---------------------------------------------------------------------------


def _plan_fence(plan: PlanDocs) -> dict[str, Any]:
    """The `[allow]`/`[deny]` TOML block 14-security.md section 9.2 prints, parsed."""
    for body in plan.fences("14-security.md", "toml"):
        if "[allow]" in body and "[deny]" in body:
            return tomllib.loads(body)
    pytest.fail("14-security.md section 9.2 no longer prints an [allow]/[deny] toml fence")


def test_the_allowlist_matches_the_plan(plan: PlanDocs, repo_root: Path) -> None:
    """`[allow] spdx` in `tools/licences.toml` is 14-security.md section 9.2's list, in order.

    Element-for-element, not as a set of lowercase strings. The allowlist is also what
    `pip-licenses --allow-only` is handed (11-repo-layout.md section 9.4 item 1), so a row
    silently added here would widen a published, falsifiable claim as well as CI's.
    """
    plan.require()
    expected = _plan_fence(plan)["allow"]["spdx"]
    declared = tomllib.loads((repo_root / "tools" / "licences.toml").read_text(encoding="utf-8"))
    assert declared["allow"]["spdx"] == expected
    assert len(expected) == len(set(expected)), "the plan's allowlist repeats an id"


def test_the_denylist_matches_the_plan(plan: PlanDocs, repo_root: Path) -> None:
    """`[deny] spdx` and `[deny] prefix` are the plan's, in order.

    `prefix` is the only reach this policy has on a `LicenseRef-` id, and both of its rows are
    R-L1's and R-L3's weights families. Losing one would not fail any other test.
    """
    plan.require()
    expected = _plan_fence(plan)["deny"]
    declared = tomllib.loads((repo_root / "tools" / "licences.toml").read_text(encoding="utf-8"))
    assert declared["deny"]["spdx"] == expected["spdx"]
    assert declared["deny"]["prefix"] == expected["prefix"]


def test_the_four_datalab_distributions_are_denied_by_name(policy: Any, gate: ModuleType) -> None:
    """17-risks.md R-L1's detector is "any G3 hit on `marker-pdf`, `surya-ocr`, `texify` or `lift`".

    They are denied by NAME rather than by SPDX because R-L1 states the detector that way, and
    because a distribution's declared licence is a claim: the trap R-L1 names is that
    "the top-level `LICENSE` is Apache-2.0 and mentions weights nowhere".
    """
    for name in ("marker-pdf", "surya-ocr", "texify", "lift"):
        assert gate.pep503(name) in policy.deny_name, name


def test_the_five_names_the_plan_says_will_trip_the_gate_are_denied(policy: Any) -> None:
    """14-security.md section 9.2 names five in advance; `cairosvg` proves the case."""
    for name in ("pymupdf", "mineru", "pypandoc-binary", "ffmpeg-static", "cairosvg"):
        assert name in policy.deny_name, name
    assert "cairosvg" in policy.deny_module


def test_the_allowlist_and_the_denylist_are_disjoint(policy: Any, gate: ModuleType) -> None:
    """An id on both lists makes the verdict depend on evaluation order, which is no policy."""
    for allowed in sorted(policy.allow):
        assert gate.denied_reason(allowed, policy) is None, allowed


def test_every_denied_id_is_denied_by_its_own_row(policy: Any, gate: ModuleType) -> None:
    for denied in policy.deny_spdx:
        assert gate.denied_reason(denied, policy) == denied


def test_the_policy_declares_no_unvalidatable_exception(policy: Any) -> None:
    """`load_policy` raises on a malformed table, so reaching here is the assertion.

    A shipped exception must additionally not already be stale, which `_stale_waivers` fails on.
    """
    today = dt.datetime.now(tz=dt.UTC).date()
    for waiver in policy.waivers.values():
        assert waiver.review_by >= today, waiver


# ---------------------------------------------------------------------------
# SPDX expressions and the denylist's family matching
# ---------------------------------------------------------------------------


def test_or_is_a_choice_and_and_is_a_conjunction(gate: ModuleType) -> None:
    assert gate.expression_alternatives("Apache-2.0 OR BSD-3-Clause") == (
        frozenset({"Apache-2.0"}),
        frozenset({"BSD-3-Clause"}),
    )
    assert gate.expression_alternatives("MPL-2.0 AND MIT") == (frozenset({"MPL-2.0", "MIT"}),)


def test_a_with_exception_is_stripped_and_a_plus_is_or_later(gate: ModuleType) -> None:
    """`Apache-2.0 WITH LLVM-exception` grants more, not less; `GPL-2.0+` is `GPL-2.0-or-later`."""
    assert gate.expression_alternatives("Apache-2.0 WITH LLVM-exception") == (
        frozenset({"Apache-2.0"}),
    )
    assert gate.expression_alternatives("GPL-2.0+") == (frozenset({"GPL-2.0-or-later"}),)


def test_a_parenthesised_expression_is_read_conservatively(gate: ModuleType) -> None:
    """Every id required, because a wrong OR grouping would grant what the expression does not."""
    assert gate.expression_alternatives("(MIT OR GPL-3.0-only) AND BSD-3-Clause") == (
        frozenset({"MIT", "GPL-3.0-only", "BSD-3-Clause"}),
    )


@pytest.mark.parametrize(
    ("spdx_id", "row"),
    [
        ("GPL-3.0", "GPL-3.0-only"),
        ("AGPL-3.0", "AGPL-3.0-only"),
        ("LGPL-2.1", "LGPL-2.1-only"),
        ("GPL-2.0+", "GPL-2.0-or-later"),
        ("CC-BY-NC-4.0", "CC-BY-NC-4.0"),
        ("LicenseRef-AIPubs-OpenRAIL-M", "LicenseRef-AIPubs-OpenRAIL"),
        ("LicenseRef-Tencent-Hunyuan-A", "LicenseRef-Tencent-Hunyuan"),
    ],
)
def test_a_bare_family_trips_its_versioned_rows(
    gate: ModuleType, policy: Any, spdx_id: str, row: str
) -> None:
    """A metadata claim of bare `GPL-3.0` must not slip past a denylist written `-only`/`-or-later`.

    omniparse is the collection's live example: its `LICENSE` is GPL-3.0 and its
    `pyproject.toml:7` says "Apache" (14-security.md section 9.1).
    """
    canonical = next(iter(gate.expression_alternatives(spdx_id)[0]))
    assert gate.denied_reason(canonical, policy) == row


def test_a_bare_cc_by_cannot_be_used_to_dodge_the_two_cc_rows(
    gate: ModuleType, policy: Any
) -> None:
    """11-repo-layout.md section 9.4 item 1's trap, stated as a test."""
    assert gate.denied_reason("CC-BY", policy) is not None


def test_a_permissive_id_is_not_denied_by_a_family_prefix(gate: ModuleType, policy: Any) -> None:
    for allowed in ("MIT", "Apache-2.0", "BSD-3-Clause", "MPL-2.0", "ISC", "0BSD"):
        assert gate.denied_reason(allowed, policy) is None, allowed


# ---------------------------------------------------------------------------
# Licence-text classification, and its known false friends
# ---------------------------------------------------------------------------


def test_a_real_gpl3_text_is_gpl3_even_though_it_names_the_agpl(gate: ModuleType) -> None:
    """GPL-3 section 13 is headed "Use with the GNU Affero General Public License".

    An earlier draft guarded GPL-3.0 against that phrase, which made the detector unable to fire on
    any genuine GPL-3 file at all — the exact shape of defect a licence gate must not have.
    """
    families = gate.classify_licence_text(GPL3_TEXT)
    assert "GPL-3.0" in families
    assert "AGPL-3.0" not in families


def test_a_real_agpl3_text_is_agpl3_and_not_gpl3(gate: ModuleType) -> None:
    families = gate.classify_licence_text(AGPL3_TEXT)
    assert "AGPL-3.0" in families
    assert "GPL-3.0" not in families


def test_the_psf_text_reciting_the_gpl_is_not_classified_as_gpl(gate: ModuleType) -> None:
    """`typing_extensions` ships this text and is not GPL-licensed. A name is not a grant."""
    families = gate.classify_licence_text(PSF_TEXT)
    assert not {f for f in families if f.startswith(("GPL", "AGPL", "LGPL"))}


def test_an_index_of_bundled_filenames_is_not_a_grant(gate: ModuleType) -> None:
    """Pillow's `LICENSE` lists a bundled file called `copying.lgplv2.1`. Pillow is not LGPL."""
    listing = "Licenses are included in the following files:\n"
    listing += "  - COPYING.LGPLv2.1: GNU Lesser General Public License version 2.1\n"
    listing += "  - COPYING.GPLv2: GNU General Public License version 2\n"
    assert gate.classify_licence_text(listing) == frozenset()


def test_the_mit_text_is_mit_and_nothing_copyleft(gate: ModuleType) -> None:
    assert "MIT" in gate.classify_licence_text(MIT_TEXT)


# ---------------------------------------------------------------------------
# Surface 1 — the resolved graph
# ---------------------------------------------------------------------------


def test_the_resolved_graph_holds_the_fourteen_members_at_runtime_scope(
    gate: ModuleType, repo_root: Path
) -> None:
    """And never the workspace root, which is `virtual` and would drag `ruff` into the wheel."""
    graph = gate.resolved_graph()
    members = sorted(p.parent.name for p in (repo_root / "packages").glob("*/pyproject.toml"))
    assert len(members) == 14
    for member in members:
        entry = graph[gate.pep503(member)]
        assert "runtime" in entry.scopes, member
        assert entry.conditional is False, member
    assert "omniweave-monorepo" not in graph


def test_a_dev_only_tool_is_dev_scope_and_not_runtime(gate: ModuleType) -> None:
    """`ruff` ships in no wheel. If it reached runtime scope the scope split would be a lie."""
    entry = gate.resolved_graph()["ruff"]
    assert entry.scopes == frozenset({"dev"})


def test_an_extra_only_package_is_conditional(gate: ModuleType) -> None:
    """`omniweave-core[sqlite]` -> `pysqlite3-binary` is in the lock of every env that lacks it.

    Conditional means "in the graph, name-checked, but this platform cannot supply its metadata",
    which is what stops the gate failing on a package the resolution never asked for.
    """
    assert gate.resolved_graph()["pysqlite3-binary"].conditional is True


def test_a_denied_name_in_the_graph_is_a_blocker(gate: ModuleType, policy: Any) -> None:
    """R-L1's detector, exercised. `surya-ocr` is not installed and must fail anyway."""
    graph = {
        "surya-ocr": gate.Resolved(
            name="surya-ocr", version="0.6.0", scopes=frozenset({"runtime"}), conditional=False
        )
    }
    findings = gate.scan_resolved_graph(graph, policy)
    assert [f.severity for f in findings] == [gate.DENY]
    assert "[deny] name" in findings[0].detail
    assert "surya-ocr" in findings[0].subject


def test_an_unconditional_package_missing_from_the_environment_fails_loudly(
    gate: ModuleType, policy: Any
) -> None:
    """A gate that cannot see the graph must say so rather than report a clean run."""
    graph = {
        "not-installed-anywhere": gate.Resolved(
            name="not-installed-anywhere",
            version="1.0",
            scopes=frozenset({"runtime"}),
            conditional=False,
        )
    }
    findings = gate.scan_resolved_graph(graph, policy)
    assert [f.severity for f in findings] == [gate.DENY]
    assert "uv sync" in findings[0].detail


def test_a_conditional_package_missing_from_the_environment_is_only_a_notice(
    gate: ModuleType, policy: Any
) -> None:
    graph = {
        "not-installed-anywhere": gate.Resolved(
            name="not-installed-anywhere",
            version="1.0",
            scopes=frozenset({"dev"}),
            conditional=True,
        )
    }
    assert [f.severity for f in gate.scan_resolved_graph(graph, policy)] == [gate.NOTICE]


# ---------------------------------------------------------------------------
# Licence evidence, over synthetic distribution metadata
# ---------------------------------------------------------------------------


def test_pep639_expression_is_the_strongest_evidence(gate: ModuleType, policy: Any) -> None:
    evidence = gate.spdx_evidence(_dist(Name="x", License_Expression="MIT"), policy)
    assert evidence.kind == "expression"
    assert evidence.alternatives == (frozenset({"MIT"}),)


def test_prose_license_metadata_is_normalised(gate: ModuleType, policy: Any) -> None:
    evidence = gate.spdx_evidence(_dist(Name="x", License="BSD"), policy)
    assert evidence.kind == "normalised"
    assert evidence.alternatives == (frozenset({"BSD-2-Clause", "BSD-3-Clause"}),)


def test_a_whole_licence_text_in_the_license_field_is_read_as_text(
    gate: ModuleType, policy: Any
) -> None:
    """`tiktoken` puts its MIT text there. No normalisation table can hold a licence."""
    evidence = gate.spdx_evidence(_dist(Name="x", License=MIT_TEXT), policy)
    assert evidence.kind == "text"
    assert evidence.alternatives == (frozenset({"MIT"}),)


def test_a_classifier_is_the_last_resort_and_is_labelled_weak(
    gate: ModuleType, policy: Any
) -> None:
    evidence = gate.spdx_evidence(
        _dist(Name="x", Classifier="License :: OSI Approved :: MIT License"), policy
    )
    assert evidence.kind == "classifier"
    assert evidence.alternatives == (frozenset({"MIT"}),)


def test_a_distribution_with_no_licence_evidence_is_unreviewed_not_clean(
    gate: ModuleType, policy: Any
) -> None:
    """14-security.md section 9.2: "a denylist misses `UNKNOWN`"."""
    evidence = gate.spdx_evidence(_dist(Name="x"), policy)
    assert evidence.kind == "none"
    findings = gate._judge("x", "x==1", evidence, policy)
    assert [f.severity for f in findings] == [gate.UNREVIEWED]


def test_an_or_expression_clears_on_its_permissive_branch(gate: ModuleType, policy: Any) -> None:
    """`cryptography` declares `Apache-2.0 OR BSD-3-Clause`; reading OR as AND would fail it."""
    evidence = gate.spdx_evidence(
        _dist(Name="x", License_Expression="Apache-2.0 OR BSD-3-Clause"), policy
    )
    assert gate._judge("x", "x==1", evidence, policy) == []


def test_an_and_expression_fails_on_its_worst_operand(gate: ModuleType, policy: Any) -> None:
    evidence = gate.spdx_evidence(
        _dist(Name="x", License_Expression="MIT AND AGPL-3.0-only"), policy
    )
    findings = gate._judge("x", "x==1", evidence, policy)
    assert [f.severity for f in findings] == [gate.DENY]
    assert "AGPL-3.0-only" in findings[0].detail


def test_an_or_expression_whose_every_branch_is_denied_is_denied(
    gate: ModuleType, policy: Any
) -> None:
    evidence = gate.spdx_evidence(
        _dist(Name="x", License_Expression="AGPL-3.0-only OR SSPL-1.0"), policy
    )
    assert {f.severity for f in gate._judge("x", "x==1", evidence, policy)} == {gate.DENY}


# ---------------------------------------------------------------------------
# The exception register
# ---------------------------------------------------------------------------


def _table(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "spdx": "LGPL-2.1-or-later",
        "reason": "linked as a separate process, not a derivative work",
        "scope": "bench",
        "review_by": "2099-03-01",
        "approver": "name@example.com",
    }
    base.update(overrides)
    return base


def test_a_valid_exception_waives_exactly_its_own_spdx(gate: ModuleType, policy: Any) -> None:
    waiver = gate._waiver_from("example-pkg", _table(spdx="AGPL-3.0-only"))
    waived = gate.Policy(
        allow=policy.allow,
        deny_spdx=policy.deny_spdx,
        deny_prefix=policy.deny_prefix,
        deny_name=policy.deny_name,
        deny_module=policy.deny_module,
        normalise=policy.normalise,
        classifier=policy.classifier,
        waivers={"example-pkg": waiver},
    )
    cleared = gate.spdx_evidence(_dist(Name="x", License_Expression="AGPL-3.0-only"), waived)
    assert gate._judge("example-pkg", "example-pkg==1", cleared, waived) == []
    other = gate.spdx_evidence(_dist(Name="x", License_Expression="SSPL-1.0"), waived)
    assert gate._judge("example-pkg", "example-pkg==1", other, waived) != []


@pytest.mark.parametrize("missing", sorted(("spdx", "reason", "scope", "review_by", "approver")))
def test_a_missing_key_fails_the_gate(gate: ModuleType, missing: str) -> None:
    """ "ALL FIVE KEYS REQUIRED; a missing key fails the gate" (14-security.md section 9.2)."""
    table = _table()
    del table[missing]
    with pytest.raises(ValueError, match=missing):
        gate._waiver_from("example-pkg", table)


def test_an_unknown_key_fails_the_gate(gate: ModuleType) -> None:
    """A typo'd `reviewby` loses `review_by`; naming the extra key is what makes that legible."""
    with pytest.raises(ValueError, match="unknown"):
        gate._waiver_from("example-pkg", _table(reviewby="2099-01-01"))


def test_a_scope_outside_the_four_fails(gate: ModuleType) -> None:
    with pytest.raises(ValueError, match="scope"):
        gate._waiver_from("example-pkg", _table(scope="production"))


def test_a_runtime_exception_needs_a_named_approver(gate: ModuleType) -> None:
    """The plan's own template address is not an approval, and neither is an empty string."""
    with pytest.raises(ValueError, match="approver"):
        gate._waiver_from("example-pkg", _table(scope="runtime"))
    with pytest.raises(ValueError, match="approver"):
        gate._waiver_from("example-pkg", _table(scope="runtime", approver="   "))
    named = gate._waiver_from("example-pkg", _table(scope="runtime", approver="a@b.example"))
    assert named.scope == "runtime"


def test_an_empty_reason_fails(gate: ModuleType) -> None:
    with pytest.raises(ValueError, match="reason"):
        gate._waiver_from("example-pkg", _table(reason="  "))


def test_an_exception_past_its_review_date_fails_the_build(gate: ModuleType, policy: Any) -> None:
    """ "CI FAILS an exception past its review date, so an exception cannot become permanent by
    silence" (14-security.md section 9.2)."""
    stale = gate._waiver_from("example-pkg", _table(review_by="2020-01-01"))
    findings = gate._stale_waivers({}, _with_waivers(gate, policy, {"example-pkg": stale}))
    assert [f.severity for f in findings] == [gate.DENY]
    assert "2020-01-01" in findings[0].detail


def test_an_exception_naming_nothing_in_the_graph_is_a_notice(
    gate: ModuleType, policy: Any
) -> None:
    fresh = gate._waiver_from("example-pkg", _table())
    findings = gate._stale_waivers({}, _with_waivers(gate, policy, {"example-pkg": fresh}))
    assert [f.severity for f in findings] == [gate.NOTICE]


def _with_waivers(gate: ModuleType, policy: Any, waivers: dict[str, Any]) -> Any:
    return gate.Policy(
        allow=policy.allow,
        deny_spdx=policy.deny_spdx,
        deny_prefix=policy.deny_prefix,
        deny_name=policy.deny_name,
        deny_module=policy.deny_module,
        normalise=policy.normalise,
        classifier=policy.classifier,
        waivers=waivers,
    )


# ---------------------------------------------------------------------------
# Surface 2 — the import graph, over synthetic trees
# ---------------------------------------------------------------------------


def _tree(root: Path, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")


@pytest.fixture
def synthetic(gate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the gate's `REPO` at an empty synthetic workspace."""
    (tmp_path / "tools").mkdir()
    monkeypatch.setattr(gate, "REPO", tmp_path)
    return tmp_path


def test_the_cairosvg_fixture_goes_red(gate: ModuleType, policy: Any, synthetic: Path) -> None:
    """The plan's own regression fixture, in the plan's own words.

    `cairosvg` is LGPL-3.0, is imported by two ppt-master modules and is **absent from its
    `requirements.txt`**, "which is the proof that manifest scanning alone is insufficient"
    (04-driver-system.md section 7.4, DR18). A manifest-only gate passes this file.
    """
    _tree(
        synthetic,
        "packages/omniweave-target-pptx/src/omniweave_target_pptx/media.py",
        """
        from __future__ import annotations

        import cairosvg
        """,
    )
    findings = gate.import_graph(policy, {})
    assert [f.severity for f in findings] == [gate.DENY]
    assert "[deny] module" in findings[0].detail
    assert findings[0].subject.endswith("media.py:3")


def test_an_undeclared_third_party_import_goes_red(
    gate: ModuleType, policy: Any, synthetic: Path
) -> None:
    """The general shape of the same defect: an import no distribution in the environment owns."""
    _tree(
        synthetic,
        "packages/omniweave-pdf/src/omniweave_pdf/reader.py",
        "import a_package_that_is_not_installed\n",
    )
    findings = gate.import_graph(policy, {})
    assert [f.severity for f in findings] == [gate.DENY]
    assert "maps to no installed distribution" in findings[0].detail


def test_a_runtime_module_may_not_import_a_dev_only_distribution(
    gate: ModuleType, policy: Any, synthetic: Path
) -> None:
    """`pytest` is real, installed and in the dev closure. In `src/` it is still a wheel defect."""
    _tree(synthetic, "packages/omniweave-pdf/src/omniweave_pdf/reader.py", "import pytest\n")
    graph = {
        "pytest": gate.Resolved(
            name="pytest", version="9.1.0", scopes=frozenset({"dev"}), conditional=False
        )
    }
    findings = gate.import_graph(policy, graph)
    assert [f.severity for f in findings] == [gate.DENY]
    assert "outside the runtime closure" in findings[0].detail


def test_a_test_module_may_import_a_dev_only_distribution(
    gate: ModuleType, policy: Any, synthetic: Path
) -> None:
    _tree(synthetic, "packages/omniweave-pdf/tests/unit/test_reader.py", "import pytest\n")
    graph = {
        "pytest": gate.Resolved(
            name="pytest", version="9.1.0", scopes=frozenset({"dev"}), conditional=False
        )
    }
    assert gate.import_graph(policy, graph) == []


def test_stdlib_first_party_and_sibling_imports_are_not_licence_questions(
    gate: ModuleType, policy: Any, synthetic: Path
) -> None:
    """`conftest` comes from an ancestor directory and `gate_x` from `tools/`. No wheel."""
    _tree(synthetic, "packages/omniweave-core/tests/conftest.py", "X = 1\n")
    _tree(synthetic, "tools/gate_x.py", "Y = 1\n")
    _tree(synthetic, "packages/omniweave-core/src/omniweave_core/sibling.py", "Z = 1\n")
    _tree(
        synthetic,
        "packages/omniweave-core/tests/unit/test_thing.py",
        """
        import hashlib

        import conftest
        import gate_x
        import omniweave_ports
        """,
    )
    _tree(
        synthetic,
        "packages/omniweave-core/src/omniweave_core/user.py",
        "import sibling\n",
    )
    assert gate.import_graph(policy, {}) == []


def test_a_type_checking_only_import_still_counts(
    gate: ModuleType, policy: Any, synthetic: Path
) -> None:
    """An import only under `TYPE_CHECKING` is still declared, installed and licensed."""
    _tree(
        synthetic,
        "packages/omniweave-pdf/src/omniweave_pdf/reader.py",
        """
        from typing import TYPE_CHECKING

        if TYPE_CHECKING:
            import cairosvg
        """,
    )
    findings = gate.import_graph(policy, {})
    assert [f.severity for f in findings] == [gate.DENY]


# ---------------------------------------------------------------------------
# Surface 3 — the unpacked artifacts
# ---------------------------------------------------------------------------


def test_a_pure_copyleft_text_under_a_permissive_claim_is_a_blocker(
    gate: ModuleType, policy: Any
) -> None:
    """omniparse's shape: `LICENSE` is GPL-3.0 while `pyproject.toml:7` says "Apache".

    14-security.md section 9.2: the gate "takes the **more restrictive** of the two and names both".
    """
    finding = gate._artefact_verdict("omniparse==0.1", "LICENSE", frozenset({"GPL-3.0"}), policy)
    assert finding is not None
    assert finding.severity == gate.DENY
    assert "GPL-3.0" in finding.detail


def test_an_aggregate_notice_is_enumerated_rather_than_failed(
    gate: ModuleType, policy: Any
) -> None:
    """numpy's Windows wheel bundles the GPL-3 gfortran runtime inside a BSD-3 aggregate.

    Failing on that is G12's job over `tools/vendor.toml` and `THIRD_PARTY.md`; enumerating it is
    what 14-security.md section 9.4 asks of G3.
    """
    finding = gate._artefact_verdict(
        "numpy==2.5.2", "LICENSE.txt", frozenset({"GPL-3.0", "BSD-3-Clause"}), policy
    )
    assert finding is not None
    assert finding.severity == gate.NOTICE
    assert "aggregate" in finding.detail


def test_a_permissive_text_produces_no_finding(gate: ModuleType, policy: Any) -> None:
    assert gate._artefact_verdict("x==1", "LICENSE", frozenset({"MIT"}), policy) is None


def test_a_vendored_notice_is_never_read_as_the_distributions_own_claim(
    gate: ModuleType,
) -> None:
    """setuptools' `License-File = "LICENSE"` once matched `_vendor/autocommand-*/LICENSE` too,
    and the gate reported MIT setuptools as an LGPL-3.0 blocker on the strength of it."""
    checked = 0
    for dist in _installed_distributions():
        for path in gate._primary_licence_paths(dist):
            checked += 1
            assert path.count(".dist-info/") == 1, path
            assert "/_vendor/" not in path, path
            assert "/third_party/" not in path, path
    assert checked > 10, "no primary licence file found at all; the fixture cannot have run"


# ---------------------------------------------------------------------------
# The gate as a program
# ---------------------------------------------------------------------------


def test_the_gate_runs_on_head_and_returns_a_documented_exit_code(
    gate: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """All three surfaces, on this checkout.

    The assertion is deliberately NOT `== 0`. At release 1 four distributions in the resolved graph
    carry permissive ids that 14-security.md section 9.2's verbatim allowlist does not name
    (`MIT-0`, `MIT-CMU`, `CNRI-Python`, `BSL-1.0`), and each is an amendment to that list or an
    approved `[exception.<name>]` — a decision with an owner, not something a test may assume.
    """
    code = gate.main([])
    assert code in {gate.EXIT_CLEAN, gate.EXIT_BLOCKED, gate.EXIT_UNREVIEWED}
    out = capsys.readouterr().out
    assert "resolved graph" in out
    assert "import graph" in out
    assert "unpacked artifacts" in out
    assert out.isascii(), "the report must survive a cp1252 console"


def test_all_three_surfaces_do_measurable_work_on_head(gate: ModuleType, policy: Any) -> None:
    """A surface that silently inspects nothing is the failure mode three surfaces exist to prevent.

    A clean surface reports no findings, so "did it run" cannot be read off the findings list.
    What is asserted instead is that each one actually looked at something: a hundred-package
    closure, eighty-odd first-party modules, and a licence text read out of an unpacked tree.
    """
    graph = gate.resolved_graph()
    assert len(graph) > 100

    sources = gate._first_party_sources()
    assert len(sources) > 50
    assert {scope for _, scope in sources} == {"runtime", "test", "dev"}
    assert gate.import_graph(policy, graph) == [], "HEAD has an import-graph violation"

    artefacts = gate.unpacked_artifacts(graph, policy)
    assert {f.severity for f in artefacts} <= {gate.NOTICE, gate.DENY}
    assert any("bundled notice file" in f.detail for f in artefacts)
