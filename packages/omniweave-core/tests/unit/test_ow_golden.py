"""`tools/ow_golden.py`: the Tier-A goldens checked, or blessed with their row. D848.

The ingest is a real `ow add` child, so it is replaced here: the tool is held to its docstring over
trees under `tmp_path`, built from the goldens this repository commits. `test_golden_process.py`,
in the conform tier, runs the real ingest once and asks that the committed goldens match it.

Loaded by file path under a private name and at module scope, as `test_gate_flake.py` loads its
gate.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "ow_golden.py"
    spec = importlib.util.spec_from_file_location("_owtool_ow_golden", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load()
REASON = "pdfium 6721 merges ligature runs; shape counters move"
CORPUS = TOOL.CORPUS
PDF = f"{CORPUS}/parse.pdf.pdfium@1/gen01p.pdf"
EARLIER = (
    "2026-10-01\tq@example.org\tfixtures/goldens/core@2026.10/*\t"
    "incidental=1,structural=0,unexplained=0\tan earlier bless, kept as it was written\n"
)


def _committed() -> dict[str, str]:
    from omniweave_conform.golden import read_tree  # noqa: PLC0415

    return read_tree(REPO)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    goldens = tmp_path / "fixtures" / "goldens"
    goldens.mkdir(parents=True)
    shutil.copy(
        REPO / "fixtures" / "goldens" / "DECOMPOSITION.toml", goldens / "DECOMPOSITION.toml"
    )
    for path, text in _committed().items():
        (goldens / path).parent.mkdir(parents=True, exist_ok=True)
        (goldens / path).write_bytes(text.encode())
    return tmp_path


def _main(
    root: Path, capsys: pytest.CaptureFixture[str], fresh: dict[str, str], *argv: str
) -> tuple[int, str]:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(TOOL, "ingest", lambda _root: dict(fresh))
        code = TOOL.main(["--root", str(root), *argv])
    return code, capsys.readouterr().out


def _author(monkeypatch: pytest.MonkeyPatch, email: str = "bless@example.org") -> None:
    """A git author through git's own environment, whatever this machine's config says."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.email")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", email)


def test_a_matching_ingest_checks_clean(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(root, capsys, _committed())
    assert code == 0
    assert out.splitlines() == [
        f"golden  {CORPUS}: 78 file(s) from the ingest, 78 committed",
        "golden ok  0 document(s) changed",
    ]


def test_a_moved_document_fails_the_check_and_names_its_class(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fresh = _committed()
    fresh[f"{PDF}.shape"] = fresh[f"{PDF}.shape"].replace(
        "achieved.marks false", "achieved.marks true"
    )
    code, out = _main(root, capsys, fresh)
    assert code == 1
    assert f"  structural   {PDF}: achieved.marks" in out
    assert out.splitlines()[-1] == "golden FAIL  1 document(s) changed"


def _marked() -> dict[str, str]:
    fresh = _committed()
    fresh[f"{PDF}.shape"] = fresh[f"{PDF}.shape"].replace(
        "achieved.marks false", "achieved.marks true"
    )
    return fresh


def test_diff_prints_the_change_between_its_class_and_the_verdict(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling 4: section 5.3's comment, after the class lines and before the last line."""
    code, out = _main(root, capsys, _marked(), "--diff")
    assert code == 1
    assert out.splitlines()[1:] == [
        f"  structural   {PDF}: achieved.marks",
        f"document {PDF}:",
        "shape delta (1 counters):",
        "  achieved.marks false -> true",
        "golden FAIL  1 document(s) changed",
    ]


def test_without_diff_no_document_is_diffed(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(root, capsys, _marked())
    assert code == 1
    assert "document " not in out
    assert "shape delta" not in out


def test_diff_with_nothing_changed_adds_nothing(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _main(root, capsys, _committed(), "--diff")
    assert code == 0
    assert out.splitlines() == [
        f"golden  {CORPUS}: 78 file(s) from the ingest, 78 committed",
        "golden ok  0 document(s) changed",
    ]


def test_diff_shows_a_lost_and_a_new_document_against_nothing(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    renamed = PDF.replace("gen01p.pdf", "gen01q.pdf")
    fresh = {k.replace(PDF, renamed): v for k, v in _committed().items()}
    code, out = _main(root, capsys, fresh, "--diff")
    assert code == 1
    lines = out.splitlines()
    lost, new = lines.index(f"document {PDF}:"), lines.index(f"document {renamed}:")
    assert lost < new
    assert lines[lost + 1].startswith("shape delta (")
    assert "  achieved.marks false -> -" in lines[lost:new]
    assert "  achieved.marks - -> false" in lines[new:]
    assert lines[-1] == "golden FAIL  2 document(s) changed"


def test_diff_beside_a_bless_shows_what_it_blessed(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch)
    code, out = _main(root, capsys, _marked(), "--bless", "--reason", REASON, "--diff")
    assert code == 0, out
    lines = out.splitlines()
    assert lines.index(f"document {PDF}:") < len(lines) - 1
    assert "  achieved.marks false -> true" in lines
    assert lines[-1].startswith("golden blessed  1 document(s)")
    assert _main(root, capsys, _marked())[0] == 0


def _contradicted() -> dict[str, str]:
    """The PDF's first page claims nine more blocks than its `shape` counts."""
    fresh = _committed()
    fresh[f"{PDF}.pages"] = fresh[f"{PDF}.pages"].replace(" n=", " n=9", 1)
    return fresh


def test_explain_prints_the_arithmetic_for_one_document(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling 5: OW-Q-012's fix, the class line, then shape against pages, then the verdict."""
    code, out = _main(root, capsys, _contradicted(), "--explain", PDF)
    assert code == 1
    lines = out.splitlines()
    assert lines[1].startswith(f"  unexplained  {PDF}: ")
    [total] = [line for line in lines if line.startswith("  explain  blocks.total ")]
    assert total.endswith(": DISAGREES by +" + total.split("(+")[2].split(")")[0])
    assert lines[-2] == "  explain  1 page-wise counter(s) disagree between shape and pages"
    assert lines[-1] == "golden FAIL  1 document(s) changed"


def test_explain_narrows_the_check_to_its_document(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = next(k for k in _committed() if not k.startswith(PDF)).rsplit(".", 1)[0]
    fresh = _contradicted()
    fresh[f"{other}.shape"] = fresh[f"{other}.shape"] + "diag.OW_EXTRA 1\n"
    assert "2 document(s) changed" in _main(root, capsys, fresh)[1]
    code, out = _main(root, capsys, fresh, "--explain", other)
    assert code == 1
    assert PDF not in out
    assert out.splitlines()[-1] == "golden FAIL  1 document(s) changed"


@pytest.mark.parametrize(
    "name",
    [
        f"{PDF}.pages",
        f"{PDF}.shape",
        f"fixtures/goldens/{PDF}.outline",
        f"fixtures\\goldens\\{PDF}",
    ],
)
def test_explain_takes_a_document_or_any_of_its_files(
    root: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    want = _main(root, capsys, _contradicted(), "--explain", PDF)
    assert _main(root, capsys, _contradicted(), "--explain", name) == want


def test_explain_of_an_unchanged_document_passes(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _main(root, capsys, _committed(), "--explain", PDF)
    assert code == 0
    assert out.splitlines()[1:] == [
        "  explain  no page-wise counter moved in shape or over pages",
        "golden ok  0 document(s) changed",
    ]


def test_explain_of_no_document_did_not_run(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(root, capsys, _committed(), "--explain", "core@2026.10/nope@1/x.pdf")
    assert code == 2
    assert out.splitlines()[-1] == (
        "golden DID NOT RUN  core@2026.10/nope@1/x.pdf is no document in fixtures/goldens/"
        " or the ingest"
    )


def test_explain_is_a_check_and_never_a_bless(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(TOOL, "ingest", lambda _root: _marked())
        code = TOOL.main(["--root", str(root), "--bless", "--reason", REASON, "--explain", PDF])
    assert code == 2
    assert "not allowed with argument --bless" in capsys.readouterr().err
    assert (root / "fixtures" / "goldens" / f"{PDF}.shape").read_text(
        encoding="utf-8"
    ) == _committed()[f"{PDF}.shape"]


def test_explain_beside_diff_diffs_its_document_alone(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    other = next(k for k in _committed() if not k.startswith(PDF)).rsplit(".", 1)[0]
    fresh = _marked()
    fresh[f"{other}.shape"] = fresh[f"{other}.shape"] + "diag.OW_EXTRA 1\n"
    code, out = _main(root, capsys, fresh, "--explain", PDF, "--diff")
    assert code == 1
    lines = out.splitlines()
    assert f"document {PDF}:" in lines
    assert f"document {other}:" not in lines
    assert lines.index("  explain  no page-wise counter moved in shape or over pages") < (
        lines.index(f"document {PDF}:")
    )


def _bumped(tree: dict[str, str], new: str = "schema_v=2") -> dict[str, str]:
    """Section 5.6's event: every header's `schema_v` moved, and nothing else."""
    return {path: text.replace("schema_v=1", new, 1) for path, text in tree.items()}


def test_a_schema_bump_fails_the_check(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """D852: header-only moves were `unchanged`, so this passed with every byte different."""
    code, out = _main(root, capsys, _bumped(_committed()))
    assert code == 1
    assert f"  structural   {PDF}: shape header moved: schema_v 1 -> 2; pages header" in out
    assert out.splitlines()[-1] == "golden FAIL  26 document(s) changed"


def test_a_schema_bump_blesses_in_one_row_without_a_second_reviewer(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch)
    fresh = _bumped(_committed())
    code, out = _main(root, capsys, fresh, "--bless", "--schema-bump", "1->2", "--reason", REASON)
    assert code == 0, out
    assert "a second reviewer is required" not in out
    assert "  note  no second reviewer: masking schema_v leaves every diff empty" in out
    [row] = (root / "eval" / "BLESS.log").read_text(encoding="utf-8").splitlines()
    assert row.split("\t")[3:] == [
        "incidental=0,structural=26,unexplained=0",
        f"{REASON} (schema bump 1->2)",
    ]
    assert (root / "fixtures" / "goldens" / f"{PDF}.pages").read_text(encoding="utf-8") == (
        fresh[f"{PDF}.pages"]
    )
    assert _main(root, capsys, fresh)[0] == 0


def test_the_ordinary_bless_of_a_schema_bump_asks_for_a_second_reviewer(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch)
    code, out = _main(root, capsys, _bumped(_committed()), "--bless", "--reason", REASON)
    assert code == 0, out
    assert "a second reviewer is required: 26/26 structural is above 20%" in out
    assert "(schema bump" not in (root / "eval" / "BLESS.log").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("fresh", "says"),
    [
        (lambda: _bumped(_marked()), f"  {PDF}.shape: more than schema_v moved"),
        (
            lambda: _bumped(_committed(), "schema_v=3"),
            f"  {min(_committed()).rsplit('.', 1)[0]}.shape: schema_v 1->3",
        ),
        (
            lambda: {k: v for k, v in _bumped(_committed()).items() if not k.startswith(PDF)},
            f"  {PDF}.shape is new or gone",
        ),
    ],
    ids=["a-counter-too", "another-version", "a-lost-document"],
)
def test_a_schema_bump_that_is_more_than_one_is_refused(
    root: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    fresh: Any,
    says: str,
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch)
    code, out = _main(root, capsys, fresh(), "--bless", "--schema-bump", "1->2", "--reason", REASON)
    assert code == 1
    assert says in out.splitlines()
    assert "golden FAIL  the schema bump is refused: " in out
    assert out.splitlines()[-1] == (
        "  fix   bless it without --schema-bump; --diff shows what else moved"
    )
    assert not (root / "eval" / "BLESS.log").exists()
    assert _main(root, capsys, _committed())[0] == 0


def test_a_refused_schema_bump_names_ten_files_at_most(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch)
    fresh = _bumped(_committed(), "schema_v=3")
    code, out = _main(root, capsys, fresh, "--bless", "--schema-bump", "1->2", "--reason", REASON)
    assert code == 1
    assert "78 file(s) moved by more than schema_v 1->2" in out
    assert sum(1 for line in out.splitlines() if line.endswith(": schema_v 1->3")) == 10


@pytest.mark.parametrize(
    "argv",
    [
        ["--bless", "--schema-bump", "1-2"],
        ["--bless", "--schema-bump", "1->1"],
        ["--bless", "--schema-bump=->2"],
        ["--bless", "--schema-bump", "1->"],
        ["--bless", "--schema-bump", "1 ->2"],
        ["--schema-bump", "1->2"],
    ],
    ids=["no-arrow", "same", "no-old", "no-new", "a-space", "without-bless"],
)
def test_a_schema_bump_that_does_not_read_did_not_run(
    root: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    code, out = _main(root, capsys, _bumped(_committed()), *argv, "--reason", REASON)
    assert code == 2
    value = argv[-1].removeprefix("--schema-bump=")
    assert out.splitlines() == [
        f"golden DID NOT RUN  --schema-bump {value!r}: it is OLD->NEW, two different"
        " versions, and it is given with --bless"
    ]


def test_a_bless_needs_the_flag(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OMNIWEAVE_BLESS", raising=False)
    _author(monkeypatch, "")  # the flag is requirement 1, so it is refused before the author
    fresh = {k: v for k, v in _committed().items() if not k.startswith(PDF)}
    code, out = _main(root, capsys, fresh, "--bless", "--reason", REASON)
    assert code == 1
    assert "the bless is refused: OMNIWEAVE_BLESS=1 is not in the environment" in out
    assert (root / "fixtures" / "goldens" / f"{PDF}.shape").is_file()
    assert not (root / "eval" / "BLESS.log").exists()


def test_a_bless_writes_the_tree_and_one_row(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch)
    (root / "eval").mkdir()
    (root / "eval" / "BLESS.log").write_bytes(EARLIER.encode())
    fresh = {k: v for k, v in _committed().items() if not k.startswith(PDF)}
    code, out = _main(root, capsys, fresh, "--bless", "--reason", REASON)
    assert code == 0, out
    assert not (root / "fixtures" / "goldens" / f"{PDF}.shape").exists()
    log = (root / "eval" / "BLESS.log").read_text(encoding="utf-8")
    assert log.startswith(EARLIER)
    [row] = log[len(EARLIER) :].splitlines()
    fields = row.split("\t")
    assert fields[1] == "bless@example.org"
    assert fields[2:] == [
        f"fixtures/goldens/{CORPUS}/*",
        "incidental=0,structural=1,unexplained=0",
        REASON,
    ]
    assert "a second reviewer is required: 1/1 structural is above 20%" in out
    assert _main(root, capsys, fresh)[0] == 0


def test_a_bless_with_no_author_is_refused(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch, "")
    fresh = {k: v for k, v in _committed().items() if not k.startswith(PDF)}
    code, out = _main(root, capsys, fresh, "--bless", "--reason", REASON)
    assert code == 1
    assert "`git config user.email` names no author" in out
    assert "  fix   git config user.email <your address>" in out
    assert not (root / "eval" / "BLESS.log").exists()


def test_a_malformed_log_refuses_the_bless_before_anything_is_written(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    _author(monkeypatch)
    (root / "eval").mkdir()
    (root / "eval" / "BLESS.log").write_bytes(b"not a row\n")
    fresh = {k: v for k, v in _committed().items() if not k.startswith(PDF)}
    code, out = _main(root, capsys, fresh, "--bless", "--reason", REASON)
    assert code == 1
    assert "BLESS.log:1 has 1 fields, not 5" in out
    assert (root / "fixtures" / "goldens" / f"{PDF}.shape").is_file()
    assert (root / "eval" / "BLESS.log").read_bytes() == b"not a row\n"


def test_nothing_to_bless_writes_nothing(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    code, out = _main(root, capsys, _committed(), "--bless", "--reason", REASON)
    assert code == 0
    assert "nothing to bless" in out
    assert not (root / "eval" / "BLESS.log").exists()


def test_an_unexplained_change_is_never_blessed(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OMNIWEAVE_BLESS", "1")
    fresh = _committed()
    fresh[f"{PDF}.pages"] = fresh[f"{PDF}.pages"].replace(" n=", " n=9", 1)
    code, out = _main(root, capsys, fresh, "--bless", "--reason", REASON)
    assert code == 1
    assert "unexplained" in out
    assert (root / "fixtures" / "goldens" / f"{PDF}.pages").read_text(
        encoding="utf-8"
    ) == _committed()[f"{PDF}.pages"]


def test_a_failed_ingest_did_not_run(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def broken(_root: Path) -> dict[str, str]:
        raise OSError("ow add exited 70: boom")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(TOOL, "ingest", broken)
        code = TOOL.main(["--root", str(root)])
    assert code == 2
    assert capsys.readouterr().out == "golden DID NOT RUN  ow add exited 70: boom\n"


def test_an_ingest_whose_child_fails_raises_with_its_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 3, without a real child: `ow add` exiting anything but 0 is the gate not running."""
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "index.toml").write_bytes(b"")

    def fails(_argv: object, *, stdout: Any, **_: object) -> int:
        stdout.write(b"route  started\nboom: the store is locked\n")
        return 1

    monkeypatch.setattr(TOOL.subprocess, "call", fails)
    with pytest.raises(
        OSError, match=r"ow add exited 1: route  started \| boom: the store is locked"
    ):
        TOOL.ingest(tmp_path)


def test_a_bad_flag_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert TOOL.main(["--strict"]) == 2
    capsys.readouterr()
