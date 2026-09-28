"""`ow open`: refs resolved over a real seeded store, its exits, and `--render json` by schema.

The store is `conftest.py`'s `seeded_store`, the shape `omniweave-serve`'s query and open tests
seed: one document, `contract.pdf`, whose three blocks are `d1#1` to `d1#3`.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from jsonschema import Draft202012Validator
from omniweave.surface import opening as verb

if TYPE_CHECKING:
    from collections.abc import Sequence

PROJECT = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
TWO = PROJECT + '[corpora.legal]\npath = ".omniweave/legal.owstore"\n'


@pytest.fixture
def project(tmp_path: Path, seeded_store: Any) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    seeded_store(tmp_path / ".omniweave" / "index.owstore")
    return tmp_path


def _run(argv: Sequence[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["open", *argv], env={}, cwd=cwd, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _json(argv: Sequence[str], cwd: Path) -> tuple[int, dict[str, Any]]:
    code, out, _ = _run([*argv, "--render", "json"], cwd)
    return code, json.loads(out)


def _schema() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[4]
    return json.loads((root / "schema" / "open-out-v1.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------------------------


def test_a_cite_is_opened_rendered_and_exits_0(project: Path) -> None:
    code, out, err = _run(["d1#2"], project)
    assert (code, err) == (0, "")
    assert out.startswith("ow/1 ok corpus=handbook")
    assert "terminate this agreement" in out
    assert "resolved           = 1 of 1 refs" in out


def test_render_json_is_the_answer_open_out_v1_publishes(project: Path) -> None:
    code, document = _json(["d1#2", "d1#3"], project)
    assert code == 0
    Draft202012Validator(_schema()).validate(document)
    assert (document["state"], document["surface"]) == ("ok", "open")
    assert [block["cite"] for block in document["evidence"]] == ["d1#2", "d1#3"]


def test_a_stale_ref_is_exit_2_and_the_others_are_still_returned(project: Path) -> None:
    """D616: one ref that does not resolve is 2, and the batch's other refs are still evidence."""
    code, document = _json(["d1#2", "d1#99"], project)
    assert code == 2
    Draft202012Validator(_schema()).validate(document)
    assert document["state"] == "degraded"
    assert [block["cite"] for block in document["evidence"]] == ["d1#2"]
    (blocking,) = document["blocking"]
    assert "d1#99" in blocking
    assert "OW-M-032" in blocking


def test_the_layers_and_context_reach_the_resolver(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniweave_core.store import resolve  # noqa: PLC0415

    seen: list[dict[str, Any]] = []
    real = resolve.fetch

    def spy(reader: Any, refs: Any, **kwargs: Any) -> Any:
        seen.append({"refs": tuple(refs), **kwargs})
        return real(reader, refs, **kwargs)

    monkeypatch.setattr(resolve, "fetch", spy)
    assert _run(["d1#2", "--context", "3", "--layers", "body,note"], project)[0] == 0
    assert _run(["d1#2"], project)[0] == 0
    first, second = seen
    assert (first["refs"], first["context"]) == (("d1#2",), 3)
    assert {layer.value for layer in first["layers"]} == {"body", "note"}
    assert (second["context"], {layer.value for layer in second["layers"]}) == (1, {"body"})


def test_a_qualified_cite_names_its_corpus(project: Path) -> None:
    code, document = _json(["handbook:d1#2"], project)
    assert (code, document["corpus"]) == (0, "handbook")


def test_with_two_corpora_declared_every_cite_is_qualified(project: Path) -> None:
    """`ow_open`'s `qualify=len(self.corpora) > 1`: a cite names its corpus once two exist."""
    (project / "omniweave.toml").write_text(TWO, encoding="utf-8")
    code, document = _json(["d1#2", "--corpus", "handbook"], project)
    assert code == 0
    assert [block["cite"] for block in document["evidence"]] == ["handbook:d1#2"]


# ---------------------------------------------------------------------------------------------
# Not found, and usage
# ---------------------------------------------------------------------------------------------


def test_a_cite_qualified_with_an_undeclared_corpus_is_2_naming_the_ref(project: Path) -> None:
    code, _, err = _run(["legal:d1#2"], project)
    assert code == 2
    assert "a ref is qualified with corpus 'legal'" in err
    assert "--corpus" not in err.splitlines()[0]


def test_refs_naming_two_corpora_are_ow_a_015_exit_6(project: Path) -> None:
    """18:335: a `PolicyRefusal`, *"One `Corpus` addresses one corpus."* 10:1423's 6."""
    (project / "omniweave.toml").write_text(TWO, encoding="utf-8")
    code, _, err = _run(["handbook:d1#2", "legal:d1#1"], project)
    assert code == 6
    assert "OW-A-015" in err
    assert _run(["handbook:d1#2", "--corpus", "legal"], project)[0] == 6


def test_an_undeclared_corpus_or_a_missing_store_is_exit_2(tmp_path: Path) -> None:
    (tmp_path / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    code, _, err = _run(["d1#2"], tmp_path)
    assert code == 2
    assert "ow add --corpus handbook" in err
    assert _run(["d1#2", "--corpus", "nope"], tmp_path)[0] == 2


def test_an_error_under_render_json_is_the_error_object_on_stdout(project: Path) -> None:
    code, out, err = _run(["d1#2", "--corpus", "nope", "--render", "json"], project)
    assert (code, err) == (2, "")
    assert list(json.loads(out)) == ["schema", "error"]


@pytest.mark.parametrize(
    ("flags", "named"),
    [
        (["--raw"], "--raw"),
        (["--want-impact"], "--want-impact"),
        (["--quiet"], "--quiet"),
        (["--render", "jsonl"], "--render jsonl"),
        (["--render", "rows"], "--render rows"),
    ],
)
def test_a_parsed_flag_this_build_cannot_serve_is_refused_by_name(
    project: Path, flags: list[str], named: str
) -> None:
    code, out, err = _run(["d1#2", *flags], project)
    assert (code, out) == (1, "")
    assert named in err


@pytest.mark.parametrize(
    "argv",
    [
        ["d1#2", "--context", "9"],
        ["d1#2", "--context", "-1"],
        ["d1#2", "--layers", "margin"],
        ["d1#2", "--layers", ","],
        ["d1#2", "--max-chars", "10"],
        ["   "],
        [f"d1#{n}" for n in range(65)],
        ["--context", "x", "d1#2"],
        [],
    ],
)
def test_usage_errors_exit_1(project: Path, argv: list[str]) -> None:
    assert _run(argv, project)[0] == 1


def test_help_is_0(project: Path) -> None:
    assert _run(["--help"], project)[0] == 0


def test_python_m_omniweave_dispatches_open(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert "open" in launcher.DISPATCHED
    monkeypatch.chdir(project)
    monkeypatch.setattr("os.environ", {})
    assert launcher.main(["open", "d1#2"]) == 0
    assert "terminate this agreement" in capsys.readouterr().out
