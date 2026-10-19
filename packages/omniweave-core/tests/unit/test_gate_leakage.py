"""Q-G26 tested as a program: `tools/gate_leakage.py`. D875.

The clauses are `omniweave_conform.leakage`'s, which `test_conform_leakage.py` holds. This file
holds the gate to its docstring: the inputs it reads, each clause it reports as not run, and its
exits. Tier A is passed as a `committed` list over a tree under `tmp_path`, so no test reads git.
Loaded by file path under a private name and at module scope, as `test_gate_flake.py` loads its
gate.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omniweave_core.store.oweval import Assertion, Batch, Corpus, open_oweval, write

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_leakage.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_leakage", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()
FIXTURE = "fixtures/out/golden/docx/il/u01.html"
FOREIGN = "packages/omniweave-pdf/fixtures/report.pdf"


def _tree(root: Path) -> list[str]:
    for path, body in ((FIXTURE, b"<p data-ow-el='u01/e1'>Hi</p>"), (FOREIGN, b"%PDF-1.7")):
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(body)
    return [FIXTURE, FOREIGN, "README.md"]


def _sha(root: Path, path: str) -> str:
    return hashlib.sha256((root / path).read_bytes()).hexdigest()


def _oweval(root: Path, derived: str) -> Path:
    store = root / "eval" / "omniweave.oweval"
    store.parent.mkdir(parents=True, exist_ok=True)
    corpus = Corpus(
        corpus_id="fixtures/out/golden/docx",
        version="v1",
        corpus_digest="0" * 64,
        tier="A",
        n_docs=1,
        n_assertions=1,
        n_checked=0,
        document_redistributable=True,
        assertions_redistributable=True,
        publishable=False,
    )
    assertion = Assertion(
        assertion_id="roundtrip/docx@v1/u01/e1",
        corpus_id=corpus.corpus_id,
        corpus_version="v1",
        doc="il/u01.html",
        page=None,
        type="roundtrip",
        spec={"law": "r2"},
        addr="u01/e1",
        evaluable_in="owdoc",
        checked=None,
        derived_from_sha256=derived,
    )
    connection = open_oweval(store)
    try:
        write(connection, Batch(corpora=(corpus,), assertions=(assertion,)))
    finally:
        connection.close()
    return store


def test_with_no_oweval_and_no_golden_both_clauses_say_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = _tree(tmp_path)
    assert GATE.main([], committed=committed, root=tmp_path) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Q-G26  Tier A: 2 distinct fixture digest(s)",
        "  split      not run: nothing records a split; every use recomputes stats.split_of()",
        "  golden     not run: no omniweave-golden manifest (ow eval fetch is not built)",
        f"  assertion  not run: no .oweval at {tmp_path / 'eval' / 'omniweave.oweval'}",
        "Q-G26 ok  0 leak(s)",
    ]


def test_an_assertion_from_its_own_corpus_is_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = _tree(tmp_path)
    _oweval(tmp_path, _sha(tmp_path, FIXTURE))
    assert GATE.main([], committed=committed, root=tmp_path) == 0
    assert "  assertion  1 assertion(s) checked" in capsys.readouterr().out


def test_an_assertion_from_another_fixture_exits_1_naming_the_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = _tree(tmp_path)
    store = _oweval(tmp_path, _sha(tmp_path, FOREIGN))
    assert GATE.main(["--oweval", str(store)], committed=committed, root=tmp_path) == 1
    out = capsys.readouterr().out
    assert f"derived from {FOREIGN}, a fixture outside its corpus" in out
    assert "OW-Q-015" in out
    assert out.splitlines()[-1] == "Q-G26 FAILED  1 leak(s)"


def test_a_fixture_the_golden_manifest_lists_is_a_leak(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = _tree(tmp_path)
    manifest = tmp_path / "manifest.toml"
    manifest.write_text(
        f'[[document]]\npath = "a.pdf"\nsha256 = "{_sha(tmp_path, FOREIGN)}"\n', encoding="utf-8"
    )
    assert GATE.main(["--golden", str(manifest)], committed=committed, root=tmp_path) == 1
    out = capsys.readouterr().out
    assert "  golden     1 manifest digest(s) checked" in out
    assert f"LEAK golden     {FOREIGN}:" in out


def test_an_unreadable_manifest_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    committed = _tree(tmp_path)
    broken = tmp_path / "manifest.toml"
    broken.write_text("not = [toml", encoding="utf-8")
    assert GATE.main(["--golden", str(broken)], committed=committed, root=tmp_path) == 2
    assert capsys.readouterr().out.startswith("Q-G26 did not run: TOMLDecodeError")


def test_a_named_oweval_that_is_missing_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    committed = _tree(tmp_path)
    missing = tmp_path / "absent.oweval"
    assert GATE.main(["--oweval", str(missing)], committed=committed, root=tmp_path) == 2
    assert capsys.readouterr().out.startswith("Q-G26 did not run: FileNotFoundError")


def test_only_tier_a_paths_are_fixtures(tmp_path: Path) -> None:
    committed = _tree(tmp_path)
    tier_a = GATE._fixtures_gate().tier_a(committed)
    assert GATE.digests_of(tmp_path, tier_a) == {
        _sha(tmp_path, FIXTURE): FIXTURE,
        _sha(tmp_path, FOREIGN): FOREIGN,
    }
