"""ADR-14 D14.1-D14.2: the generated corpora, the catalogue and the answer key, held together."""

from __future__ import annotations

import hashlib
import io
import re
import sys
import tomllib
import zipfile
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


def _recompressed(raw: bytes, kind: int) -> bytes:
    """The same container's parts, same names and metadata, written at `kind`. D1031's lever."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(buffer, "w", kind) as out:
        for info in source.infolist():
            fresh = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            fresh.compress_type = kind
            fresh.create_system = info.create_system
            out.writestr(fresh, source.read(info.filename))
    return buffer.getvalue()


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
            digest = hashlib.sha256(
                gen.pin_manifest_bytes(gen.documents(corpus, scale))
            ).hexdigest()
            key = f"fixtures/generated/reference/{corpus}-{scale}.content"
            assert pins[key] == digest, f"{key}: regenerate and re-pin (fixtures/gen/README.md)"


def test_the_pin_is_what_the_generator_decides_and_not_what_the_compressor_decides() -> None:
    """D1031. `zlib` is not one implementation, so a pin over compressed bytes is not one pin.

    CPython 3.14 on Windows bundles zlib-ng -- `zlib.ZLIB_RUNTIME_VERSION` reads `1.3.1.zlib-ng`
    against `1.3.1` on 3.13 -- and it emits a different, entirely valid deflate stream for the
    same input at the same level. Every `.docx`, `.pptx` and `.xlsx` in `data_room` and
    `personal_archive` moved under it and four pins with them; `legal_matter` has no OOXML part
    and did not move. D1030 made `bench/serve` run in CI and `windows-latest py3.14` was the one
    cell of nine that disagreed.

    Asserted without a second interpreter, by building each container BOTH WAYS here: the written
    bytes differ across compress types and the pin does not. A pin that had quietly gone back to
    digesting `to_bytes()`, or that had dropped a field, fails on that. Asserted separately, and
    not implied by it, that the generator still DEFLATES: the corpus the 545 cassettes were
    recorded against is the deflated one, so storing the parts is not a free improvement but a
    change to every ingested byte.
    """
    seen = 0
    for corpus in gen.CORPORA:
        for doc in gen.documents(corpus, "quick"):
            raw = doc.to_bytes()
            if raw[:2] != b"PK":
                continue
            seen += 1
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                kinds = {info.compress_type for info in archive.infolist()}
            #  The corpus the 545 cassettes were recorded against is the DEFLATED one. Storing the
            #  parts would make it the same corpus on every machine and is the fix this is not --
            #  it changes every ingested byte, so it orphans 17 of the 30 tasks' recordings.
            assert kinds == {zipfile.ZIP_DEFLATED}, (doc.path, kinds)
            stored = _recompressed(raw, zipfile.ZIP_STORED)
            deflated = _recompressed(raw, zipfile.ZIP_DEFLATED)
            assert stored != deflated, doc.path
            pins = {gen.pin_of_bytes(one) for one in (raw, stored, deflated)}
            assert len(pins) == 1, doc.path
    #  Section 6.8's count: a walk that found no container would make every assertion above
    #  vacuous. Sixteen at quick scale -- 13 in data_room, 3 in personal_archive, and none at all
    #  in legal_matter, which is why legal_matter's two pins did not move under zlib-ng.
    assert seen == 16, f"{seen} OOXML containers at quick scale, not 16; re-derive this count"


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
    from corpora import KEYED_D653, ORDINALS, build_identity, prepare  # noqa: PLC0415

    documents = gen.documents("personal_archive", "quick")
    keyed = gen.manifest_bytes(documents) + KEYED_D653 + ORDINALS
    digest = hashlib.sha256(keyed).hexdigest()
    base = tmp_path / f"personal_archive-quick-{digest[:12]}"
    (base / "project").mkdir(parents=True)
    (base / "project" / "omniweave.index.lock").write_text("# schema=1\n", encoding="utf-8")
    #  D1028: the build line is what makes this a hit. Without it the entry is one whose builder
    #  is unknown, and the test below is that such an entry rebuilds.
    (base / ".ready").write_text(f"{digest}\nbuild {build_identity()}\n", encoding="utf-8")
    stale = tmp_path / "personal_archive-quick-000000000000"
    (stale / "project").mkdir(parents=True)
    (stale / ".ready").write_text("0" * 64 + "\n", encoding="utf-8")

    prepared = prepare(
        "personal_archive", "quick", cache_root=tmp_path, python="no-such-interpreter"
    )
    assert (prepared.cached, prepared.base, prepared.digest) == (True, base, digest)
    assert prepared.docs == base / "project" / "docs"
    #  D650: a cache made before the bench's budget answers with it all the same.
    written = (base / "project" / "omniweave.toml").read_text(encoding="utf-8")
    budget = tomllib.loads(written)["retrieval"]["budget"]
    assert budget["channel_ms"]["lexical"] > 50
    assert sum(budget["channel_ms"].values()) <= budget["query_ms"] - budget["hydration_reserve_ms"]


def test_an_entry_another_build_ingested_is_rebuilt_under_the_same_key(tmp_path: Path) -> None:
    """D1028. The key covers the DOCUMENTS; the entry is a store this build's `ow add` wrote.

    What this prevents shipped, and it did not read as a cache problem at all: a `data_room` entry
    made by an older build was reused under its own key, `ow_query` answered differently out of it,
    and the only thing that surfaced was one cassette key -- 83acce23... on this machine against
    CI's 814b11e8... for `data-cite-nda-term`. That read as a key that was not machine-stable. A
    fresh ingest on the same machine computed CI's key exactly, which is what named the real cause.

    Rebuilt UNDER THE SAME KEY, which is the half that matters: the folder name is in every
    recorded path, so moving the key would orphan 200 committed recordings (see `KEYED_D653`).
    Here the ingest cannot run -- the interpreter does not exist -- so the refusal is the proof
    that reuse was refused, and the log line is the proof it was refused for this reason.
    """
    from corpora import KEYED_D653, ORDINALS, CorpusError, prepare  # noqa: PLC0415

    documents = gen.documents("personal_archive", "quick")
    digest = hashlib.sha256(gen.manifest_bytes(documents) + KEYED_D653 + ORDINALS).hexdigest()
    base = tmp_path / f"personal_archive-quick-{digest[:12]}"
    (base / "project").mkdir(parents=True)
    (base / "project" / "omniweave.index.lock").write_text("# schema=1\n", encoding="utf-8")
    (base / ".ready").write_text(f"{digest}\nbuild {'a' * 64}\n", encoding="utf-8")
    lines: list[str] = []

    with pytest.raises(CorpusError):
        prepare(
            "personal_archive",
            "quick",
            cache_root=tmp_path,
            python="no-such-interpreter",
            log=lines.append,
        )

    said = "\n".join(lines)
    assert "ingested by another build (aaaaaaaaaaaa)" in said, said
    assert "cached," not in said, "the entry was reused after all"


def test_an_entry_that_records_no_builder_is_rebuilt(tmp_path: Path) -> None:
    """Every entry written before D1028, and every half-built one. An entry whose builder is
    unknown cannot be shown to be this build's, so it is not reused -- and it rebuilds QUIETLY,
    because `None` is not another build, it is no claim either way."""
    from corpora import KEYED_D653, ORDINALS, CorpusError, prepare  # noqa: PLC0415

    documents = gen.documents("personal_archive", "quick")
    digest = hashlib.sha256(gen.manifest_bytes(documents) + KEYED_D653 + ORDINALS).hexdigest()
    base = tmp_path / f"personal_archive-quick-{digest[:12]}"
    (base / "project").mkdir(parents=True)
    (base / "project" / "omniweave.index.lock").write_text("# schema=1\n", encoding="utf-8")
    (base / ".ready").write_text(digest + "\n", encoding="utf-8")
    lines: list[str] = []

    with pytest.raises(CorpusError):
        prepare(
            "personal_archive",
            "quick",
            cache_root=tmp_path,
            python="no-such-interpreter",
            log=lines.append,
        )

    said = "\n".join(lines)
    assert "cached," not in said, said
    assert "another build" not in said, "no claim is not a conflicting claim"


def test_the_build_identity_moves_with_a_shipped_source_and_not_with_anything_else(
    tmp_path: Path,
) -> None:
    """`BUILD_SOURCES` is `packages/*/src/**/*.py`, and the identity is over path AND bytes.

    The path half is what a rename has to move: two trees whose files hold the same bytes under
    different names are different builds, and a digest over bytes alone would call them one.
    """
    from corpora import build_identity  # noqa: PLC0415

    def tree(name: str, body: str, where: Path) -> str:
        src = where / "packages" / "omniweave-x" / "src" / "omniweave_x"
        src.mkdir(parents=True)
        (src / name).write_text(body, encoding="utf-8")
        (where / "README.md").write_text("not a shipped source\n", encoding="utf-8")
        return build_identity(where)

    one = tree("a.py", "x = 1\n", tmp_path / "one")
    same = tree("a.py", "x = 1\n", tmp_path / "same")
    body = tree("a.py", "x = 2\n", tmp_path / "body")
    renamed = tree("b.py", "x = 1\n", tmp_path / "renamed")

    assert one == same, "the identity is of the sources, not of where the tree happens to sit"
    assert one != body, "a changed shipped source is a different build"
    assert one != renamed, "a renamed shipped source is a different build"
    #  And the non-source file is not in it: all four trees carry the same README, and `same`
    #  equalling `one` above would hold either way, so this is the assertion that pins it.
    (tmp_path / "same" / "README.md").write_text("edited\n", encoding="utf-8")
    build_identity.cache_clear()
    assert build_identity(tmp_path / "same") == one, "a file outside BUILD_SOURCES moved it"


def test_a_tree_with_no_shipped_sources_falls_back_to_the_installed_version(
    tmp_path: Path,
) -> None:
    """A wheel-only checkout has no `packages/*/src`. The fallback is coarser than a digest and
    honest about it; what it must not be is an identity every build shares, which is what an
    empty digest would have been."""
    from importlib.metadata import version  # noqa: PLC0415

    from corpora import build_identity  # noqa: PLC0415

    assert build_identity(tmp_path) == "version:" + version("omniweave")


def test_a_damaged_corpus_is_its_own_entry_with_its_answer_s_file_damaged(tmp_path: Path) -> None:
    """D640. A damaged task's corpus is the pristine one with one file through its Injector: its
    digest covers the damage, its entry is named for the Injector, and the pristine entry's key
    is untouched. The interpreter is missing, so `ow add` cannot run and the files stay to look at.
    """
    from corpora import CorpusError, damage_of, prepare  # noqa: PLC0415
    from omniweave_conform.damage import MASK  # noqa: PLC0415

    damage = damage_of("home-dmg-refund", "mask_format")
    assert damage == (("tax/tax-summary-2023.docx", "mask_format"),)
    with pytest.raises(CorpusError, match="mask_format"):
        prepare(
            "personal_archive",
            "quick",
            cache_root=tmp_path,
            damage=damage,
            python="no-such-interpreter",
        )
    (entry,) = tmp_path.iterdir()
    pristine = hashlib.sha256(gen.manifest_bytes(gen.documents("personal_archive", "quick")))
    assert entry.name.startswith("personal_archive-quick-mask_format-")
    assert not entry.name.endswith(pristine.hexdigest()[:12])
    docs = entry / "project" / "docs"
    assert (docs / "tax" / "tax-summary-2023.docx").read_bytes().startswith(MASK)
    assert (docs / "letters" / "oakridge-renewal-2024.docx").read_bytes().startswith(b"PK")


def test_damage_naming_a_file_or_an_injector_that_does_not_exist_is_refused(
    tmp_path: Path,
) -> None:
    from corpora import CorpusError, prepare  # noqa: PLC0415

    with pytest.raises(CorpusError, match="not a built Injector"):
        prepare("personal_archive", "quick", cache_root=tmp_path, damage=(("x.pdf", "stall"),))
    with pytest.raises(CorpusError, match=r"no \['nowhere.pdf'\] to damage"):
        prepare(
            "personal_archive",
            "quick",
            cache_root=tmp_path,
            damage=(("nowhere.pdf", "mask_format"),),
        )


def test_every_zip_either_generator_writes_records_the_same_os(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D653: `zipfile` records `create_system` 0 on Windows and 3 on POSIX, so a generator that
    left it alone wrote other bytes on Linux, and another corpus digest. Both pin it to 0."""
    import importlib.util  # noqa: PLC0415
    import io  # noqa: PLC0415
    import zipfile  # noqa: PLC0415

    #  Generated as on POSIX, where `ZipInfo` defaults to 3: on Windows the default is already 0,
    #  and a test run there could not tell a pinned generator from one that left it alone.
    monkeypatch.setattr(zipfile.sys, "platform", "linux")
    office = [d for d in gen.documents("data_room", "quick") if d.path.endswith((".docx", ".xlsx"))]
    assert office
    for document in office:
        with zipfile.ZipFile(io.BytesIO(document.to_bytes())) as archive:
            assert {info.create_system for info in archive.infolist()} == {0}, document.path

    path = REPO / "fixtures" / "gen" / "gen_office_fixtures.py"
    spec = importlib.util.spec_from_file_location("omniweave_gen_office_fixtures", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(sys, "argv", ["gen_office_fixtures.py", "--out", str(tmp_path)])
    assert module.main() == 0
    zips = [p for p in tmp_path.iterdir() if zipfile.is_zipfile(p)]
    assert len(zips) >= 8
    for one in zips:
        with zipfile.ZipFile(one) as archive:
            assert {info.create_system for info in archive.infolist()} == {0}, one.name


@pytest.mark.parametrize(
    ("printed", "unparsed"),
    [
        (b"completed 38   pending 22 (22 not_parsed)   deadline_reached false\n", 22),
        (b"completed 136   pending 1 (1 failed)   deadline_reached false\n", 0),
        (b"completed 60   pending 0   deadline_reached false\n", 0),
        (b"completed 1   pending 3 (1 failed, 2 not_parsed)   deadline_reached false\n", 2),
        (b"no summary at all\n", None),
    ],
)
def test_a_corpus_ow_add_left_unparsed_is_refused_and_a_damaged_file_is_not(
    printed: bytes, unparsed: int | None
) -> None:
    """D653: `ow add` exits 0 as `partial` when it never parsed some units, and the corpus is
    then missing them. A unit pending for its own reason (`failed`) is the damaged corpus's."""
    from corpora import _not_parsed  # noqa: PLC0415

    assert _not_parsed(printed) == unparsed


def test_every_generated_file_carries_the_fixed_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D654: `ow add` does not trust a file modified within 2 s of its index, so a corpus written
    the moment before its ingest was "changed" on a fast machine and not on a slow one, and the
    agent's `ow_add` printed `queued` on Linux where the recording printed `unchanged`."""
    import corpora  # noqa: PLC0415
    from omniweave_core.host.subproc import Captured  # noqa: PLC0415

    def added(_argv: object, *, cwd: str, **_kw: object) -> Captured:
        (Path(cwd) / "omniweave.index.lock").write_text("# schema=1\n", encoding="utf-8")
        return Captured(0, b"completed 1   pending 0   deadline_reached false\n", b"", None)

    monkeypatch.setattr(corpora, "run_captured", added)
    prepared = corpora.prepare("personal_archive", "quick", cache_root=tmp_path)
    files = [one for one in prepared.docs.rglob("*") if one.is_file()]
    assert files
    assert {one.stat().st_mtime_ns for one in files} == {corpora.FILE_MTIME_NS}


def test_the_bench_ingests_on_the_workers_a_user_gets() -> None:
    """D655: nothing an agent reads depends on the worker count any more, so the bench's project
    sets none and `ow add` runs on `[drivers] max_workers`' defaults."""
    from corpora import PROJECT  # noqa: PLC0415

    assert "max_workers" not in tomllib.loads(PROJECT).get("drivers", {})
