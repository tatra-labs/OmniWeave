"""`ow out list` / `ow_artifacts`: one corpus's sealed artefact rows, as lines or a bare array.

`artifact_rows()` itself is `test_store_artifact.py`'s, over real seals. Here the store is real and
migrated: empty for the empty case, and with `artifact_rows` answering fixed rows where the test is
about what the verb prints of them.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave.surface import out as verb
from omniweave.surface.registry import ACTIONS
from omniweave_core.errors import NotFoundError, UsageError
from omniweave_core.out.gate import GateStatus
from omniweave_core.store import artifact as store_artifact
from omniweave_core.store import migrate
from omniweave_core.store import sqlite as store_sqlite
from omniweave_core.store.artifact import ArtifactRow

if TYPE_CHECKING:
    from collections.abc import Sequence

KEYS = [
    "slug", "artifact_gen", "parent_artifact_gen", "origin", "target", "compile_driver",
    "delivery", "gate_status", "media_type", "path", "byte_len", "restriction_bits",
    "read_back_doc_ord", "sealed_at_ns",
]  # fmt: skip


def _row(slug: str, gen: int, **over: Any) -> ArtifactRow:
    fields: dict[str, Any] = {
        "artifact_id": gen,
        "slug": slug,
        "artifact_gen": gen,
        "parent_artifact_gen": None,
        "origin": "authored",
        "target": "owtext",
        "compile_driver": "compile.text.owtext",
        "media_type": "text/plain",
        "path": f"{slug}@{gen}/{slug}.txt",
        "sha256": "sha256:" + "1" * 64,
        "byte_len": 42,
        "part_digest": "sha256:" + "2" * 64,
        "il_digest": "sha256:" + "3" * 64,
        "il_store_ref": "cas://00/00/" + "0" * 64,
        "constructs_digest": "sha256:" + "4" * 64,
        "ledger_digest": "sha256:" + "5" * 64,
        "brief_digest": None,
        "card_sha256": "sha256:" + "6" * 64,
        "toolchain_digest": None,
        "determinism": ("part",),
        "gate_status": GateStatus.PASSED,
        "delivery": "release",
        "report_sha256": "sha256:" + "7" * 64,
        "receipt_sha256": "sha256:" + "8" * 64,
        "restriction_bits": 0,
        "producer_id": 1,
        "degradations": (),
        "read_back_doc_ord": None,
        "sealed_at_ns": 1_700_000_000_000_000_000 + gen,
    }
    fields.update(over)
    return ArtifactRow(**fields)


ROWS = (
    _row("q3-board", 1),
    _row("q3-board", 2, parent_artifact_gen=1, read_back_doc_ord=7),
    _row("q4-memo", 1, delivery="draft", gate_status=GateStatus.MANUAL_REQUIRED),
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / ".omniweave").mkdir()
    connection = store_sqlite.connect(tmp_path / ".omniweave" / "index.owstore")
    try:
        migrate.apply_pending(connection, now_ns=1)
    finally:
        connection.close()
    return tmp_path


@pytest.fixture
def sealed(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """`artifact_rows` answering `ROWS`, filtered by slug as the store does; returns the asks."""
    asked: list[str | None] = []

    def rows(_connection: object, slug: str | None = None) -> tuple[ArtifactRow, ...]:
        asked.append(slug)
        return tuple(r for r in ROWS if slug is None or r.slug == slug)

    monkeypatch.setattr(store_artifact, "artifact_rows", rows)
    return asked


def _env(home: Path) -> dict[str, str]:
    return {"OMNIWEAVE_HOME": str(home / "owhome"), "HOME": str(home), "USERPROFILE": str(home)}


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", "list", *argv], cwd=cwd, env=_env(cwd), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_an_empty_corpus_lists_nothing_and_says_where(project: Path) -> None:
    assert _run([], project) == (0, "no artefact has been sealed in corpus handbook\n", "")
    assert _run(["--render", "json"], project) == (0, "[]\n", "")


def test_render_json_is_the_bare_array_of_rows(project: Path, sealed: list[str | None]) -> None:
    code, out, err = _run(["--render", "json"], project)
    assert (code, err) == (0, "")
    document = json.loads(out)
    assert [list(row) for row in document] == [KEYS] * 3
    assert [(r["slug"], r["artifact_gen"]) for r in document] == [
        ("q3-board", 1), ("q3-board", 2), ("q4-memo", 1),
    ]  # fmt: skip
    assert document[1]["read_back_doc_ord"] == 7
    assert document[1]["parent_artifact_gen"] == 1
    assert (document[2]["delivery"], document[2]["gate_status"]) == ("draft", "manual-required")
    assert sealed == [None]


def test_slug_narrows_the_list_in_the_store(project: Path, sealed: list[str | None]) -> None:
    code, out, _ = _run(["--slug", "q4-memo", "--render", "json"], project)
    assert code == 0
    assert [r["slug"] for r in json.loads(out)] == ["q4-memo"]
    assert sealed == ["q4-memo"]
    assert _run(["--slug", "q9"], project)[1] == (
        "no artefact 'q9' has been sealed in corpus handbook\n"
    )


@pytest.mark.usefixtures("sealed")
def test_the_text_form_is_a_line_a_generation(project: Path) -> None:
    code, out, _ = _run([], project)
    assert code == 0
    assert out.splitlines() == [
        "q3-board@1  owtext   release passed          q3-board@1/q3-board.txt  read_back -",
        "q3-board@2  owtext   release passed          q3-board@2/q3-board.txt  read_back d7",
        "q4-memo@1  owtext   draft   manual-required q4-memo@1/q4-memo.txt  read_back -",
    ]


def test_corpus_names_the_store(project: Path) -> None:
    code, out, _ = _run(["--corpus", "atlas", "--render", "json"], project)
    assert code == NotFoundError.EXIT
    assert "atlas" in json.loads(out)["error"]["message"]


def test_a_corpus_with_no_store_is_not_found(project: Path) -> None:
    (project / ".omniweave" / "index.owstore").unlink()
    code, _, err = _run([], project)
    assert code == NotFoundError.EXIT
    assert "has no store" in err


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--quiet"], "--quiet is parsed and not served by ow out list"),
        (["--render", "jsonl"], "--render jsonl is parsed and not served by ow out list"),
    ],
)
def test_usage_is_refused_by_name(argv: list[str], named: str, project: Path) -> None:
    code, _, err = _run(argv, project)
    assert code == UsageError.EXIT
    assert named in err


def test_the_action_is_ow_artifacts_in_the_full_roster() -> None:
    spec = ACTIONS["out.list"]
    assert (spec.mcp_name, spec.read_only, spec.idempotent) == ("ow_artifacts", True, True)
    assert {str(p) for p in spec.listed_in} == {"full"}


def test_the_console_script_routes_list(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(project)
    for key, value in _env(project).items():
        monkeypatch.setenv(key, value)
    code = launcher.main(["out", "list", "--render", "json"])
    captured = capsys.readouterr()
    assert (code, captured.out, captured.err) == (0, "[]\n", "")
