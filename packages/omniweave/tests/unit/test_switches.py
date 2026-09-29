"""18:887's eight global flags on every root the tree parses: served, or refused by name (D631).

Every refusal here goes through `omniweave.__main__.main`, the console script's own entry, so a
root that forgot to call `switches.check()` fails its row. The refusal comes before a root reads
anything, so no row needs a project, a store or an installed server.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import omniweave.__main__ as launcher
import pytest
from omniweave.cli import COMMANDS, GLOBAL_FLAGS, build_parser
from omniweave.run import ingest as ingest_module
from omniweave.run.routing import resolve_policy
from omniweave.surface import add as add_verb
from omniweave.surface import switches
from omniweave_core.config import load
from omniweave_core.errors import NotFoundError, UsageError

from omniweave import doctor

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOTS = sorted({command.words[0] for command in COMMANDS})

MINIMAL: dict[str, list[str]] = {
    "add": ["add", "x.txt"],
    "corpora": ["corpora"],
    "doc": ["doc", "grid", "d#1"],
    "doctor": ["doctor"],
    "explain": ["explain", "OW-A-002"],
    "hooks": ["hooks", "check"],
    "install": ["install"],
    "open": ["open", "d#1"],
    "query": ["query", "fees"],
    "serve": ["serve", "--mcp"],
    "skills": ["skills", "ls"],
    "surface": ["surface", "emit", "--check"],
    "uninstall": ["uninstall"],
}
"""The shortest command line each root parses. None of them is run past the refusal."""

GIVEN: dict[str, list[str]] = {
    "config": ["--config", "other.toml"],
    "corpus": ["--corpus", "handbook"],
    "render": ["--render", "json"],
    "quiet": ["--quiet"],
    "verbose": ["-v"],
    "no_color": ["--no-color"],
    "offline": ["--offline"],
    "json_errors": ["--json-errors"],
}
"""Each flag away from its default."""

REFUSED = [
    (root, name)
    for root in ROOTS
    for name in switches.DEFAULTS
    if name not in switches.READS[root] and name not in switches.INERT[root]
]

JSON_ERROR_KEYS = ["code", "numeric", "message", "fix", "exit"]


def _main(argv: Sequence[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = launcher.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.fixture
def empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory with no project, and a home that is not the user's."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OMNIWEAVE_HOME", str(tmp_path / "owhome"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    return tmp_path


# ---------------------------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------------------------


def test_the_eight_are_the_trees_own_flags_in_18_889s_order_with_its_defaults() -> None:
    spellings = [flag.spelling[0] for flag in GLOBAL_FLAGS]
    assert spellings == list(switches.SPELLING.values())
    parsed = vars(build_parser().parse_args(["doctor"]))
    assert {name: parsed[name] for name in switches.DEFAULTS} == dict(switches.DEFAULTS)


def test_every_root_the_tree_parses_has_a_row_and_no_other_does() -> None:
    assert sorted(switches.READS) == ROOTS
    assert sorted(switches.INERT) == ROOTS
    assert sorted(MINIMAL) == ROOTS
    assert set(ROOTS) <= launcher.DISPATCHED


@pytest.mark.parametrize("root", ROOTS)
def test_a_flag_is_read_or_inert_never_both_and_every_inert_one_says_why(root: str) -> None:
    assert not switches.READS[root] & set(switches.INERT[root])
    assert set(switches.READS[root]) | set(switches.INERT[root]) <= set(switches.DEFAULTS)
    assert all(reason.strip() for reason in switches.INERT[root].values())
    #  Every root writes its refusal through `report()`, which reads `--json-errors`.
    assert "json_errors" in switches.READS[root]


def test_the_refused_set_is_what_the_audit_found() -> None:
    """The matrix D631 records. A pair moving out of it is a flag served; into it, one dropped."""
    by_root: dict[str, list[str]] = {}
    for root, name in REFUSED:
        by_root.setdefault(root, []).append(name)
    reader = ["verbose"]
    installer = ["config", "corpus", "render", "quiet", "verbose"]
    assert by_root == {
        "add": reader,
        "corpora": reader,
        "doc": reader,
        "open": reader,
        "query": reader,
        "explain": reader,
        "doctor": ["corpus", "render", "verbose"],
        "serve": ["corpus", "render", "quiet", "verbose"],
        "surface": ["render", "quiet", "verbose"],
        "install": installer,
        "uninstall": installer,
        "hooks": installer,
        "skills": installer,
    }


# ---------------------------------------------------------------------------------------------
# Refused by name, through the console script
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("root", "name"), REFUSED, ids=[f"{r}-{n}" for r, n in REFUSED])
def test_a_flag_a_root_does_not_serve_is_refused_by_name_before_anything_is_read(
    root: str, name: str, empty: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _main([*MINIMAL[root], *GIVEN[name]], capsys)
    assert code == UsageError.EXIT
    #  Refused before the root read anything: no store, no project file, no home written.
    assert sorted(path.name for path in empty.iterdir()) == []
    if name == "render" and root != "serve":
        #  10:1539: under `--render json` the error is the object on stdout, and only there.
        message = json.loads(out)["error"]["message"]
        assert err == ""
    else:
        message = err
        assert out == ""
    assert switches.SPELLING[name] in message
    assert f"not served by ow {root}" in message


@pytest.mark.usefixtures("empty")
def test_a_global_flag_before_the_root_is_refused_by_the_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """W7.8q routes `ow -v query ...` to `query` with the command line unchanged."""
    code, out, err = _main(["-v", "query", "fees"], capsys)
    assert code == UsageError.EXIT
    assert "--verbose is parsed and not served by ow query" in err
    assert out == ""


@pytest.mark.usefixtures("empty")
def test_several_flags_are_refused_together_in_18_889s_order(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, _, err = _main(["install", "-v", "--quiet", "--corpus", "x", "--config", "c"], capsys)
    assert code == UsageError.EXIT
    assert err.startswith("ow: ")
    assert "--config, --corpus, --quiet, --verbose is parsed and not served by ow install" in err


def test_a_flag_at_its_default_is_never_refused() -> None:
    for root in ROOTS:
        parsed = build_parser().parse_args(MINIMAL[root])
        assert switches.unserved(root, parsed) == ()


def test_a_refusal_never_repeats_a_value_the_user_typed() -> None:
    """The value may be any text, and the refusal is printed to a cp1252 pipe (D431)."""
    parsed = build_parser().parse_args(["doctor", "--corpus", "règles"])
    assert switches.unserved("doctor", parsed) == ("--corpus",)


# ---------------------------------------------------------------------------------------------
# --json-errors: 18:898's object, on every root
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("root", ROOTS)
@pytest.mark.usefixtures("empty")
def test_json_errors_prints_18_898s_object_on_stderr_and_nothing_else(
    root: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = _main([*MINIMAL[root], "-v", "--json-errors"], capsys)
    assert code == UsageError.EXIT
    assert out == ""
    [line] = err.splitlines()
    document = json.loads(line)
    assert list(document) == JSON_ERROR_KEYS
    assert document["exit"] == UsageError.EXIT
    assert document["code"] == UsageError("x", fix="y").code()
    assert "--verbose" in document["message"]
    assert document["fix"] == "omit it"
    assert line.isascii()


def test_json_errors_carries_a_real_errors_code_numeric_and_exit(
    empty: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Not only the refusal: `ow query`'s own not-found, exit 2, with its register numeric."""
    (empty / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    code, out, err = _main(["query", "fees", "--corpus", "nope", "--json-errors"], capsys)
    assert code == NotFoundError.EXIT
    assert out == ""
    document = json.loads(err)
    assert document["code"] == "OW_CORPUS_NOT_FOUND"
    assert re.fullmatch(r"OW-[A-Z]-\d{3}", document["numeric"])
    assert document["exit"] == NotFoundError.EXIT
    assert "nope" in document["message"]


@pytest.mark.usefixtures("empty")
def test_json_errors_beside_render_json_writes_both_contracts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """10:1539's object on stdout, 18:898's on stderr: two flags, and each is kept."""
    code, out, err = _main(["explain", "OW-Z-999", "--render", "json", "--json-errors"], capsys)
    assert code == NotFoundError.EXIT
    stdout_object, stderr_object = json.loads(out), json.loads(err)
    assert list(stdout_object) == ["schema", "error"]
    #  One vocabulary on both flags (ADR-13 D13.5): `code` the symbol, `numeric` the human form.
    assert list(stdout_object["error"]) == ["code", "numeric", "message", "fix"]
    assert stdout_object["error"]["code"] == stderr_object["code"]
    assert stdout_object["error"]["numeric"] == stderr_object["numeric"]
    assert stderr_object["exit"] == NotFoundError.EXIT


@pytest.mark.usefixtures("empty")
def test_without_json_errors_the_prose_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _main(["explain", "OW-Z-999"], capsys)
    assert code == NotFoundError.EXIT
    assert out == ""
    assert err.startswith("ow: ")
    assert "\n  fix: " in err


@pytest.mark.usefixtures("empty")
def test_serve_never_writes_stdout_even_under_render_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Stdout is the protocol channel from the moment the server binds it."""
    code, out, err = _main(["serve", "--mcp", "--render", "json"], capsys)
    assert code == UsageError.EXIT
    assert out == ""
    assert "--render json is parsed and not served by ow serve" in err
    assert err.startswith("ow: ") and err.count("\n") == 1


def test_report_writes_prose_json_or_both_as_the_flags_ask() -> None:
    error = UsageError("bad", fix="do the other thing")
    cases: list[tuple[list[str], bool, bool, bool]] = [
        ([], False, False, True),
        (["--json-errors"], False, True, False),
        (["--render", "json"], True, False, False),
        (["--render", "json", "--json-errors"], True, True, False),
    ]
    for flags, on_stdout, as_json, as_prose in cases:
        parsed = build_parser().parse_args(["doctor", *flags])
        out, err = io.StringIO(), io.StringIO()
        assert switches.report(error, parsed, stdout=out, stderr=err) == UsageError.EXIT
        assert bool(out.getvalue()) is on_stdout, flags
        if as_json:
            assert json.loads(err.getvalue())["message"] == "bad"
        assert (err.getvalue() == switches.prose(error)) is as_prose, flags


# ---------------------------------------------------------------------------------------------
# What is served that was not
# ---------------------------------------------------------------------------------------------


ATTESTED = {doctor.ALLOW_UNATTESTED: "true"}
"""So D-08 passes over this workspace's two unattested first-party cards (D576)."""


def _doctor(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = doctor.main(["doctor", *argv], cwd=cwd, env=ATTESTED, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_doctor_loads_the_config_it_is_given_rather_than_the_one_the_walk_finds(
    tmp_path: Path,
) -> None:
    """18:891: `--config` *"skips the upward walk"*. Before D631 the verb dropped it."""
    other = tmp_path / "elsewhere" / "other.toml"
    other.parent.mkdir()
    other.write_text("[drivers\n", encoding="utf-8")
    walked_code, walked, _ = _doctor([], tmp_path)
    code, given, _ = _doctor(["--config", str(other)], tmp_path)
    assert "FAIL config" not in walked
    assert walked_code == doctor.OK
    assert code == doctor.FAILED
    assert "FAIL config" in given
    assert "not run: the configuration did not resolve" in given


def test_doctor_run_passes_explicit_to_the_loader(tmp_path: Path) -> None:
    other = tmp_path / "other.toml"
    other.write_text('[serve]\ndefault_corpus = "handbook"\n', encoding="utf-8")
    report = doctor.run(cwd=tmp_path, env={}, explicit=other)
    assert (
        report.config_sources["serve.default_corpus"]
        == load(cwd=tmp_path, env={}, explicit=other).source_of("serve.default_corpus").render()
    )


def test_doctor_quiet_prints_nothing_and_keeps_the_exit(tmp_path: Path) -> None:
    """10:1543: *"`ow doctor --quiet` prints nothing and speaks only through its exit code"*."""
    bad = tmp_path / "bad.toml"
    bad.write_text("[drivers\n", encoding="utf-8")
    for argv, exit_code in (([], doctor.OK), (["--config", str(bad)], doctor.FAILED)):
        code, out, err = _doctor([*argv, "--quiet"], tmp_path)
        assert (code, out, err) == (exit_code, "", "")


def test_offline_reaches_routings_probe_env(tmp_path: Path) -> None:
    """04:150's `ProbeEnv.offline`, which `resolve()` reads for `needs_network` (18:897)."""
    config = load(cwd=tmp_path, env={})
    online, offline = resolve_policy(config).host_env, resolve_policy(config, offline=True).host_env
    assert online is not None and offline is not None
    assert (online.offline, offline.offline) == (False, True)


def test_ow_add_offline_is_carried_into_the_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[bool] = []
    real = ingest_module.resolve_policy

    def spy(config: Any, **kwargs: Any) -> Any:
        seen.append(bool(kwargs.get("offline")))
        return real(config, **kwargs)

    monkeypatch.setattr(ingest_module, "resolve_policy", spy)
    (tmp_path / ".git").mkdir()
    (tmp_path / "omniweave.toml").write_text(
        '[corpora.handbook]\npath = ".omniweave/index.owstore"\n', encoding="utf-8"
    )
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.txt").write_text("Fees are payable monthly.", encoding="utf-8")
    env = {"OMNIWEAVE_HOME": str(tmp_path / "owhome")}
    for flags, expected in (([], False), (["--offline"], True)):
        (tmp_path / "docs" / "a.txt").write_text(f"Fees {expected}.", encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        code = add_verb.main(
            ["add", "docs", *flags], env=env, cwd=tmp_path, stdout=out, stderr=err, sweep_ms=20
        )
        assert code == 0, err.getvalue()
        assert seen[-1] is expected


# ---------------------------------------------------------------------------------------------
# --no-color holds because nothing writes colour
# ---------------------------------------------------------------------------------------------

_ESCAPE = re.compile(r"\x1b|\\x1b|\\033|\\u001b|\\N\{ESCAPE\}", re.IGNORECASE)


def test_no_distribution_a_root_imports_writes_an_ansi_escape() -> None:
    """10:1529 allows ANSI only on a TTY; `--no-color` is `INERT` because none is ever written.

    A colour writer landing anywhere a root can import makes `--no-color` a flag that must be
    read, and this test is where that is found out.
    """
    root = Path(__file__).resolve().parents[4] / "packages"
    found = [
        f"{path.relative_to(root)}:{number}"
        for path in sorted(root.glob("*/src/**/*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _ESCAPE.search(line)
    ]
    assert found == []
