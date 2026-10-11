"""`ow out constructs <target>`: a ConstructTable as lines, one row, JSON or agent Markdown.

The table is owtext's, found through the conformance suite's directory on `OMNIWEAVE_DRIVER_PATH`.
Every expectation that a card or the table states is read back from them, so what is under test is
that the verb prints what they say.
"""

from __future__ import annotations

import io
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import omniweave_conform.suites.target as target_suites
import pytest
from omniweave.surface import out as verb
from omniweave_core.errors import ConfigError, NotFoundError, TargetError, UsageError
from omniweave_core.out.agentdoc import agent_doc, load_table

if TYPE_CHECKING:
    from collections.abc import Sequence

SUITES = Path(target_suites.__file__).parent

ROW_KEYS = [
    "id", "group", "disposition", "round_trip", "code", "numeric", "since", "selector",
    "canonical", "maps_to", "normalizes_to", "normalizer", "bake", "forbidden_when", "msg",
    "severity", "visible",
]  # fmt: skip


def _env(home: Path, *paths: Path) -> dict[str, str]:
    env = {
        "OMNIWEAVE_HOME": str(home / "owhome"),
        "HOME": str(home / "home"),
        "USERPROFILE": str(home / "home"),
    }
    if paths:
        env["OMNIWEAVE_DRIVER_PATH"] = os.pathsep.join(str(p) for p in paths)
    return env


def _run(argv: Sequence[str], cwd: Path, env: dict[str, str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = verb.main(["out", "constructs", *argv], cwd=cwd, env=env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def _json(argv: Sequence[str], tmp_path: Path) -> dict[str, Any]:
    code, out, err = _run(["owtext", *argv, "--render", "json"], tmp_path, _env(tmp_path, SUITES))
    assert (code, err) == (0, "")
    document: dict[str, Any] = json.loads(out)
    return document


def _owtext() -> tuple[Any, Any]:
    from omniweave_core.discovery import discover  # noqa: PLC0415
    from omniweave_core.out.card import CompileCard  # noqa: PLC0415

    for card in discover(env={"OMNIWEAVE_DRIVER_PATH": str(SUITES)}).cards:
        if str(card.identity.port) == "compile" and CompileCard.of(card).target == "owtext":
            compiled = CompileCard.of(card)
            return compiled, load_table(Path(card.source), compiled)
    raise AssertionError("owtext")


# ---------------------------------------------------------------------------------------------
# The four forms
# ---------------------------------------------------------------------------------------------


def test_the_text_form_is_a_header_and_a_line_a_row(tmp_path: Path) -> None:
    card, table = _owtext()
    code, out, err = _run(["owtext"], tmp_path, _env(tmp_path, SUITES))
    assert (code, err) == (0, "")
    header, *lines = out.splitlines()
    assert header.startswith("owtext compile.text.owtext html/owtext/1 table v1  10 row(s)")
    assert header.endswith(f"agent doc budget {card.agent_doc_tokens_max} tokens")
    assert [line.split()[0] for line in lines] == [row.id for row in table.rows]
    assert lines[-1].split() == [
        "style.text-shadow",
        "bake",
        "lossy",
        "@style|text-shadow",
        "OW-T-312",
    ]


def test_format_md_prints_the_agent_document_the_ci_gate_counts(tmp_path: Path) -> None:
    """The verb and the gate render one document: `agentdoc.agent_doc()`."""
    card, table = _owtext()
    code, out, err = _run(["owtext", "--format", "md"], tmp_path, _env(tmp_path, SUITES))
    assert (code, err) == (0, "")
    assert out == agent_doc(card, table)
    code, out, _ = _run(
        ["owtext", "--format", "md", "--group", "style"], tmp_path, _env(tmp_path, SUITES)
    )
    assert code == 0
    assert "## style\n- `style.text-shadow`" in out
    assert "## attr" not in out


def test_render_json_is_the_report_with_every_row_and_its_numeric(tmp_path: Path) -> None:
    card, table = _owtext()
    document = _json([], tmp_path)
    assert list(document) == [
        "target", "driver", "il", "carrier", "version", "digest", "agent_doc_tokens_max",
        "ignore", "rows",
    ]  # fmt: skip
    assert document["digest"] == card.constructs_digest == table.digest()
    assert document["ignore"] == ["html|head", "html|meta"]
    rows = {row["id"]: row for row in document["rows"]}
    assert [row["id"] for row in document["rows"]] == [row.id for row in table.rows]
    assert all(list(row) == ROW_KEYS for row in document["rows"])
    assert rows["style.text-shadow"]["bake"] == {"renderer": "raster", "dpi": 192, "role": "bake"}
    assert rows["attr.class.upper"]["selector"] == "@class"
    assert (rows["attr.class.upper"]["numeric"], rows["attr.class.upper"]["group"]) == (
        "OW-T-211",
        "attr",
    )
    assert rows["attr.id"]["forbidden_when"] == "html|style"


def test_group_and_construct_select_rows(tmp_path: Path) -> None:
    assert [row["id"] for row in _json(["--group", "elem"], tmp_path)["rows"]] == [
        "elem.ow-manual", "elem.section", "elem.p", "elem.script",
    ]  # fmt: skip
    assert [row["id"] for row in _json(["--construct", "attr.id"], tmp_path)["rows"]] == ["attr.id"]


def test_construct_in_text_is_every_key_the_row_carries(tmp_path: Path) -> None:
    """`OW-T-009`'s fix: the row and the key."""
    code, out, err = _run(
        ["owtext", "--construct", "elem.script"], tmp_path, _env(tmp_path, SUITES)
    )
    assert (code, err) == (0, "")
    keys = [line.split()[0] for line in out.splitlines()]
    assert keys == ["id", "group", "disposition", "round_trip", "code", "numeric", "since",
                    "selector", "msg", "visible"]  # fmt: skip
    assert "msg             executable content in an authored artefact" in out


# ---------------------------------------------------------------------------------------------
# Ruling 6: the one card that declares the target
# ---------------------------------------------------------------------------------------------


def test_documentation_does_not_need_the_target_enabled(tmp_path: Path) -> None:
    """The default `[targets] enabled` is `["pptx"]`; owtext is documented all the same."""
    assert _json([], tmp_path)["target"] == "owtext"


def test_a_target_no_card_declares_is_not_found_and_names_the_kinds(tmp_path: Path) -> None:
    code, out, err = _run(["pptx"], tmp_path, _env(tmp_path, SUITES))
    assert (code, out) == (NotFoundError.EXIT, "")
    assert "no compile card declares target 'pptx'; the cards found declare owtext, video" in err
    assert "OW-T-515" in err
    assert "fix: ow out targets" in err


def test_two_cards_for_one_target_is_a_configuration_error_naming_both(tmp_path: Path) -> None:
    second = tmp_path / "second" / "owtext2"
    shutil.copytree(SUITES / "owtext", second, ignore=shutil.ignore_patterns("__pycache__"))
    card = second / "driver.toml"
    card.write_text(
        card.read_text(encoding="utf-8").replace(
            'id = "compile.text.owtext"', 'id = "compile.text.owtext2"'
        ),
        encoding="utf-8",
    )
    env = _env(tmp_path, SUITES, tmp_path / "second")
    code, _, err = _run(["owtext"], tmp_path, env)
    assert code == ConfigError.EXIT
    assert (
        "2 compile cards declare target 'owtext': compile.text.owtext, compile.text.owtext2" in err
    )


def test_an_unimplemented_target_refuses_with_its_reason(tmp_path: Path) -> None:
    code, _, err = _run(["video"], tmp_path, _env(tmp_path, SUITES))
    assert code == TargetError.EXIT
    assert "OW-T-514" in err
    assert "implemented = false, because the hyperframes" in err


def test_an_unknown_construct_names_the_rows(tmp_path: Path) -> None:
    code, _, err = _run(["owtext", "--construct", "elem.div"], tmp_path, _env(tmp_path, SUITES))
    assert code == NotFoundError.EXIT
    assert "OW-T-516" in err
    assert "owtext/1 has no construct 'elem.div'; its rows are attr.ow-cite" in err


# ---------------------------------------------------------------------------------------------
# Ruling 7 and ruling 4: what is refused by name
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "named"),
    [
        (["--format", "html"], "--format html is not one of text, md"),
        (
            ["--format", "md", "--render", "json"],
            "--format md and --render json ask for two documents",
        ),
        (
            ["--group", "attr", "--construct", "attr.id"],
            "--group and --construct are two selections",
        ),
        (["--quiet"], "--quiet is parsed and not served by ow out constructs"),
        (["--render", "rows"], "--render rows is parsed and not served by ow out constructs"),
    ],
)
def test_each_refusal_is_a_usage_error_naming_the_flag(
    argv: list[str], named: str, tmp_path: Path
) -> None:
    code, out, err = _run(["owtext", *argv], tmp_path, _env(tmp_path, SUITES))
    assert code == UsageError.EXIT
    #  Under `--render json` the refusal is 10:1539's object on stdout, and only there.
    assert named in (json.loads(out)["error"]["message"] if "json" in argv else err)


def test_the_console_script_routes_constructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for key, value in _env(tmp_path, SUITES).items():
        monkeypatch.setenv(key, value)
    code = launcher.main(["out", "constructs", "owtext", "--format", "md"])
    captured = capsys.readouterr()
    assert (code, captured.err) == (0, "")
    assert captured.out.startswith("# owtext/1 constructs, target owtext\n")
