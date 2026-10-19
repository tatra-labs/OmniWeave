"""`omniweave_conform.leakage`: Q-G26's three clauses over rows. D875."""

from __future__ import annotations

from omniweave_conform.leakage import CODE, Leak, assertion_leaks, golden_leaks, split_leaks
from omniweave_conform.stats import split_of

FIXTURES = {
    "a" * 64: "packages/omniweave-pdf/fixtures/report.pdf",
    "b" * 64: "fixtures/out/golden/docx/il/u01.html",
}


def _other(split: str) -> str:
    return "fit" if split != "fit" else "holdout"


def test_a_split_row_agrees_with_the_recomputed_split() -> None:
    assert split_leaks([("doc-1", split_of("doc-1")), ("doc-2", split_of("doc-2"))]) == []


def test_a_row_the_split_function_disagrees_with_is_a_leak() -> None:
    wrong = _other(split_of("doc-1"))
    assert split_leaks([("doc-1", wrong)]) == [
        Leak("split", "doc-1", f"recorded in {wrong}, recomputed into {split_of('doc-1')}")
    ]


def test_a_doc_key_in_two_splits_is_named_with_the_code() -> None:
    right = split_of("doc-1")
    leaks = split_leaks([("doc-1", right), ("doc-1", _other(right))])
    assert leaks[-1].why == f"in both {' and '.join(sorted({right, _other(right)}))} ({CODE})"
    assert CODE == "OW-Q-015"


def test_a_fixture_digest_in_the_golden_manifest_is_a_leak() -> None:
    assert golden_leaks(FIXTURES, []) == []
    assert golden_leaks(FIXTURES, ["a" * 64, "c" * 64]) == [
        Leak(
            "golden",
            "packages/omniweave-pdf/fixtures/report.pdf",
            f"its sha256 {'a' * 16} is in omniweave-golden's manifest ({CODE})",
        )
    ]


def test_an_assertion_may_derive_only_from_a_fixture_in_its_own_corpus() -> None:
    rows = [
        ("own", "fixtures/out/golden/docx", "b" * 64),
        ("prefix", "fixtures/out/golden/doc", "b" * 64),
        ("foreign", "fixtures/out/golden/docx", "a" * 64),
        ("untracked", "fixtures/out/golden/docx", "f" * 64),
    ]
    assert [leak.names for leak in assertion_leaks(rows, FIXTURES)] == ["prefix", "foreign"]
    assert assertion_leaks(rows[2:3], FIXTURES)[0].why == (
        "derived from packages/omniweave-pdf/fixtures/report.pdf, a fixture outside its corpus "
        f"fixtures/out/golden/docx ({CODE})"
    )
