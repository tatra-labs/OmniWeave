"""ADR-14 D14.1-D14.2: the generated corpora, the catalogue and the answer key, held together."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest
import serve_harness as h
from corpora import GENERATOR, generator
from host_tools import HostTools
from models import ToolUse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EXPECTED = REPO / "fixtures" / "gen" / "EXPECTED.sha256"
CATALOG = h.load_catalog((HERE / "tasks.toml").read_text(encoding="utf-8"))
gen = generator()
SCALES = ("full", "quick")
FORBIDDEN = (
    "random.random", "random.choice", "random.randrange", "uuid.uuid4",
    "time.time", "time.time_ns", "time.monotonic", "secrets.token_bytes",
)  # fmt: skip
"""fixtures/gen/README.md's regime: a generator that reaches one of these is not deterministic."""


def _text(corpus: str, scale: str) -> dict[str, str]:
    """Each document's path and text, casefolded. The path counts: an answer may name a file."""
    return {
        doc.path: "\n".join((doc.path, *doc.lines)).casefold()
        for doc in gen.documents(corpus, scale)
    }


def test_every_reference_corpus_is_its_pin_at_both_scales() -> None:
    pins = {
        path: digest
        for digest, _, path in (
            line.partition("  ")
            for line in EXPECTED.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        )
    }
    for corpus in gen.CORPORA:
        for scale in SCALES:
            digest = hashlib.sha256(gen.manifest_bytes(gen.documents(corpus, scale))).hexdigest()
            key = f"fixtures/generated/reference/{corpus}-{scale}.manifest"
            assert pins[key] == digest, f"{key}: regenerate and re-pin (fixtures/gen/README.md)"


def test_the_generator_samples_nothing_and_reads_no_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    def raiser(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("13-quality.md:586-589: a generator may not sample or read a clock")

    for target in FORBIDDEN:
        monkeypatch.setattr(target, raiser)
    first = gen.manifest_bytes(gen.documents("personal_archive", "quick"))
    assert first == gen.manifest_bytes(gen.documents("personal_archive", "quick"))


@pytest.mark.parametrize(
    ("corpus", "files", "pages"),
    [
        ("legal_matter", {"full": 120, "quick": 12}, {"full": 5_000, "quick": 250}),
        ("data_room", {"full": 137, "quick": 16}, None),
        ("personal_archive", {"full": 60, "quick": 8}, None),
    ],
)
def test_each_corpus_has_f20s_shape_and_quick_cuts_only_the_filler(
    corpus: str, files: dict[str, int], pages: dict[str, int] | None
) -> None:
    for scale in SCALES:
        documents = gen.documents(corpus, scale)
        assert len(documents) == files[scale]
        assert len({doc.path for doc in documents}) == len(documents)
        if pages is not None:
            assert sum(len(doc.pages) for doc in documents) == pages[scale]
        #  One logical page is one PDF page: none overflows the writer's page, so a count above is
        #  the count a reader of the PDF sees.
        for doc in documents:
            for page in doc.pages:
                wrapped = sum(len(gen._wrap(line)) for line in page)
                assert wrapped <= gen.LINES_PER_PAGE, (doc.path, wrapped)
    #  Every quick file is a full file: the fast profile drops filler, and never renames.
    assert {d.path for d in gen.documents(corpus, "quick")} <= {
        d.path for d in gen.documents(corpus, "full")
    }


def test_every_file_in_a_corpus_is_a_distinct_document() -> None:
    """Identical bytes are ONE document to the store, so a corpus of duplicates is smaller than
    its file count says. The full archive once held nine repeated bank statements: 60 files, and
    51 documents in the receipt."""
    for corpus in gen.CORPORA:
        for scale in SCALES:
            digests = [line.split()[0] for line in gen.manifest_lines(gen.documents(corpus, scale))]
            assert len(set(digests)) == len(digests), (corpus, scale)


def test_every_file_is_a_format_the_shipped_roster_parses() -> None:
    for corpus in gen.CORPORA:
        for doc in gen.documents(corpus, "full"):
            assert doc.path.rsplit(".", 1)[-1] in {"pdf", "docx", "xlsx", "pptx", "csv"}, doc.path
            assert all(line.isascii() for line in doc.lines), doc.path


def test_the_catalogue_and_the_answer_key_name_the_same_tasks() -> None:
    ids = {task.id for task in CATALOG.tasks}
    assert ids == set(gen.PLANTED) | set(gen.ABSENT)
    for task in CATALOG.tasks:
        if task.id in gen.PLANTED:
            assert gen.PLANTED[task.id].corpus == task.corpus.value, task.id
        assert (task.task_class is h.TaskClass.ABSENCE) == (task.id in gen.ABSENT), task.id


def test_the_catalogue_is_the_born_digital_twenty_four_and_owes_the_scanned_six() -> None:
    assert len(CATALOG.tasks) == 24
    assert {task.source_kind for task in CATALOG.tasks} == {h.SourceKind.BORN_DIGITAL}
    assert dict(CATALOG.missing()) == {
        h.TaskClass.CITATION: 2,
        h.TaskClass.RETRIEVAL: 1,
        h.TaskClass.ABSENCE: 1,
        h.TaskClass.DAMAGED: 2,
    }


@pytest.mark.parametrize("scale", SCALES)
def test_every_planted_answer_is_in_its_document_at_both_scales(scale: str) -> None:
    for task_id, planted in gen.PLANTED.items():
        texts = _text(planted.corpus, scale)
        assert planted.path in texts, (task_id, planted.path)
        assert planted.text.casefold() in texts[planted.path], task_id


@pytest.mark.parametrize("scale", SCALES)
def test_every_answer_a_task_expects_is_somewhere_in_its_corpus(scale: str) -> None:
    for task in CATALOG.tasks:
        corpus = "\n".join(_text(task.corpus.value, scale).values())
        for needle in task.expect.contains:
            if needle == "not found":
                continue
            assert needle.casefold() in corpus, (task.id, needle)
        for decoy in task.expect.forbids:
            if task.task_class is h.TaskClass.RETRIEVAL and decoy != "not found":
                assert decoy.casefold() in corpus, (task.id, "a decoy nothing could say", decoy)


@pytest.mark.parametrize("scale", SCALES)
def test_a_damaged_tasks_value_is_in_exactly_one_document(scale: str) -> None:
    for task in CATALOG.tasks:
        if task.task_class is not h.TaskClass.DAMAGED:
            continue
        (value,) = task.expect.forbids
        holding = [
            path for path, text in _text(task.corpus.value, scale).items()
            if re.search(rf"(?<![\d.,]){re.escape(value.casefold())}(?![\d])", text)
        ]  # fmt: skip
        assert holding == [gen.PLANTED[task.id].path], (task.id, holding)


@pytest.mark.parametrize("scale", SCALES)
def test_every_absent_term_is_in_no_document_of_its_corpus(scale: str) -> None:
    for task_id, terms in gen.ABSENT.items():
        corpus = next(task.corpus.value for task in CATALOG.tasks if task.id == task_id)
        for path, text in _text(corpus, scale).items():
            for term in terms:
                assert term not in text, (task_id, term, path)


def test_every_planted_fact_is_readable_through_the_control_arms_converters(
    tmp_path: Path,
) -> None:
    """The quick corpora written to disk, and each planted sentence found by `Grep` over them.

    This is the same conversion both arms' `Read` and `Grep` use (ADR-14 D14.3), so a fact that
    this cannot find is a fact no agent could, and the task would be measuring the generator.
    """
    for corpus in gen.CORPORA:
        root = tmp_path / corpus
        gen.write_corpus(root, corpus, "quick")
        tools = HostTools(root)
        for task_id, planted in gen.PLANTED.items():
            if planted.corpus != corpus:
                continue
            probe = re.escape(planted.text.split()[-1].rstrip("."))
            found = tools.call(
                ToolUse(
                    "g", "Grep", {"pattern": probe, "path": planted.path, "output_mode": "content"}
                )
            )
            assert not found.result.is_error, (task_id, found.result.text)
            assert found.result.text != "No matches found", (task_id, probe)


def test_the_generator_is_where_adr_14_says() -> None:
    assert GENERATOR == REPO / "fixtures" / "gen" / "gen_reference_corpora.py"


def test_a_ready_entry_with_the_same_digest_is_reused_and_nothing_is_ingested(
    tmp_path: Path,
) -> None:
    from corpora import prepare  # noqa: PLC0415 -- the cache half, beside the generator's tests

    documents = gen.documents("personal_archive", "quick")
    digest = hashlib.sha256(gen.manifest_bytes(documents)).hexdigest()
    base = tmp_path / f"personal_archive-quick-{digest[:12]}"
    (base / "project").mkdir(parents=True)
    (base / "project" / "omniweave.index.lock").write_text("# schema=1\n", encoding="utf-8")
    (base / ".ready").write_text(digest + "\n", encoding="utf-8")
    stale = tmp_path / "personal_archive-quick-000000000000"
    (stale / "project").mkdir(parents=True)
    (stale / ".ready").write_text("0" * 64 + "\n", encoding="utf-8")

    prepared = prepare(
        "personal_archive", "quick", cache_root=tmp_path, python="no-such-interpreter"
    )
    assert (prepared.cached, prepared.base, prepared.digest) == (True, base, digest)
    assert prepared.docs == base / "project" / "docs"
