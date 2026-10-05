"""`fixtures/gen/gen_office200.py` -- F2's 200 office documents, and the pin that holds them. D656.

12-performance.md section 7.2 names `fixtures/office-200` and `ow bench inproc` reads it; D196 found
that nothing generated it. These tests hold the generator to 13-quality.md:586-589's regime (no
clock, no random, one pinned manifest) and to the one property the bench needs from it: anydoc
decodes every document, so a refusal in the bench's table is a fact about anydoc and not about the
corpus.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Final

import anydoc
import pytest

if TYPE_CHECKING:
    from types import ModuleType

REPO: Final = Path(__file__).resolve().parents[4]
GEN_PATH: Final = REPO / "fixtures" / "gen" / "gen_office200.py"
EXPECTED: Final = REPO / "fixtures" / "gen" / "EXPECTED.sha256"
PIN: Final = "fixtures/generated/office-200.manifest"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("omniweave_gen_office200", GEN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


gen = _load()


@pytest.fixture(scope="module")
def corpus(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """The corpus written once for the module: the folder and its manifest's digest."""
    dest = tmp_path_factory.mktemp("office200") / "office-200"
    _manifest, digest = gen.write_corpus(dest)
    return dest, digest


def test_the_pin_is_the_digest_of_a_freshly_generated_corpus(corpus: tuple[Path, str]) -> None:
    """13-quality.md:588: a generator change is a one-line visible diff in EXPECTED.sha256."""
    pins = {
        path: digest
        for digest, _, path in (
            line.partition("  ")
            for line in EXPECTED.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        )
    }
    assert pins[PIN] == corpus[1]


def test_the_mix_is_the_two_tables_exactly() -> None:
    """200 documents, the format and size multisets the module docstring prints, nothing drawn."""
    docs = gen.documents()
    assert len(docs) == gen.COUNT == 200
    assert Counter(doc.fmt for doc in docs) == Counter(dict(gen.MIX))
    assert Counter(doc.bucket for doc in docs) == Counter(dict(gen.BUCKETS))
    assert len({doc.path for doc in docs}) == 200


def test_every_document_is_the_size_its_bucket_names() -> None:
    """Six huge documents among 110 small ones: a corpus of small files would never find the
    peak, and a size outside its bucket would be a bucket the table does not print."""
    for doc in gen.documents():
        low, high = gen.SIZES[doc.bucket][gen._UNIT[doc.fmt]]
        if doc.fmt in gen._SCALED_DOWN:
            low, high = max(1, low // 3), max(1, high // 3)
        assert low <= doc.size <= high, doc.path


def test_the_generator_reads_no_clock_and_draws_no_random(monkeypatch: pytest.MonkeyPatch) -> None:
    """13-quality.md:586-589, run rather than read: the first ten documents' bytes are the same
    with `random`, `secrets`, `uuid4` and `time.time` all raising."""
    plain = [doc.to_bytes() for doc in gen.documents()[:10]]

    def raiser(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("13-quality.md:586-589: a generator may not sample or read a clock")

    for target in ("random.random", "secrets.token_bytes", "uuid.uuid4", "time.time"):
        monkeypatch.setattr(target, raiser)
    assert [doc.to_bytes() for doc in gen.documents()[:10]] == plain


def test_anydoc_decodes_every_document(corpus: tuple[Path, str]) -> None:
    """The bench counts a refusal rather than raising; this is why it should count none."""
    refused = []
    for path in sorted(p for p in corpus[0].rglob("*") if p.is_file()):
        try:
            anydoc.to_document(path.read_bytes(), path.suffix[1:])  # type: ignore[arg-type]
        except Exception as exc:
            refused.append((path.name, repr(exc)[:120]))
    assert refused == []


def test_every_zip_entry_says_windows_so_the_bytes_are_one_on_every_os() -> None:
    """D653's rule: `zipfile` writes `create_system` 3 on POSIX and 0 on Windows."""
    import io  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    for doc in gen.documents()[:20]:
        if doc.fmt in {"rtf", "csv"}:
            continue
        with zipfile.ZipFile(io.BytesIO(doc.to_bytes())) as archive:
            assert {info.create_system for info in archive.infolist()} == {0}, doc.path
