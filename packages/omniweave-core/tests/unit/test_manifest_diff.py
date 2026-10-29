"""`tools/manifest_diff.py`, section 7.5's recipe 4 and checklist step 15's fourth command. D1012.

The tool an auditor runs against a downloaded signed asset and a wheel's own copy of the same
manifest. Its rulings are the interesting surface: the comparison is over the parsed document and
not the bytes (two encodings of one mapping are never byte-equal), an absent `vendored` is `false`
because `gen_first_party.py` only writes the key when it is set, and the three exit codes have to
stay distinguishable because a person reads them -- "the recipe is broken" must not look like "the
artefact is wrong".

One test holds ruling 1, that the tool imports nothing from omniweave: a verifier that has to be
installed from the thing it verifies verifies nothing.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest


def _repo_root(start: Path) -> Path:
    """The workspace root, found by walking up rather than by counting `parents[n]`."""
    for candidate in (start, *start.parents):
        if (candidate / "pyproject.toml").is_file() and (candidate / "packages").is_dir():
            return candidate
    message = f"no omniweave workspace root above {start}"
    raise RuntimeError(message)


REPO_ROOT: Final = _repo_root(Path(__file__).resolve())
TOOL_PATH: Final = REPO_ROOT / "tools" / "manifest_diff.py"
GEN_PATH: Final = REPO_ROOT / "tools" / "gen_first_party.py"


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL: Final = _load(TOOL_PATH, "_owtool_manifest_diff")

ASSET: Final[dict[str, Any]] = {
    "schema": 1,
    "release": "0.1.0",
    "dist": {
        "omniweave-ports": {"version": "0.1.0", "dist_sha256": "sha256:aaa"},
        "omniweave-office": {"version": "0.1.0", "dist_sha256": "sha256:bbb", "vendored": True},
    },
}

WHEEL: Final = """schema = 1
release = "0.1.0"

[dist."omniweave-ports"]
version = "0.1.0"
dist_sha256 = "sha256:aaa"

[dist."omniweave-office"]
version = "0.1.0"
dist_sha256 = "sha256:bbb"
vendored = true
"""


def _pair(tmp_path: Path, *, asset: dict[str, Any] | None = None, wheel: str = WHEEL) -> list[str]:
    """The two argv entries for a written pair, the signed asset first."""
    one = tmp_path / "first-party-0.1.0.json"
    two = tmp_path / "first_party.toml"
    one.write_text(json.dumps(ASSET if asset is None else asset), encoding="utf-8")
    two.write_text(wheel, encoding="utf-8")
    return [str(one), str(two)]


def test_a_wheel_that_carries_the_signed_manifest_agrees_with_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert TOOL.main(_pair(tmp_path)) == TOOL.EXIT_OK
    out = capsys.readouterr().out
    assert "manifest_diff ok  2 row(s), release 0.1.0" in out


def test_a_swapped_digest_is_a_finding_naming_the_signed_value_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling 4, and the only difference that matters: a wheel whose manifest was edited."""
    argv = _pair(tmp_path, wheel=WHEEL.replace("sha256:aaa", "sha256:forged"))
    assert TOOL.main(argv) == TOOL.EXIT_FINDING
    out = capsys.readouterr().out
    assert "omniweave-ports.dist_sha256: asset 'sha256:aaa', wheel 'sha256:forged'" in out
    assert "1 difference(s)" in out


def test_a_row_in_only_one_of_them_says_which_side_it_is_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    added = WHEEL + '\n[dist."omniweave-evil"]\nversion = "9.9"\ndist_sha256 = "sha256:ccc"\n'
    assert TOOL.main(_pair(tmp_path, wheel=added)) == TOOL.EXIT_FINDING
    assert "omniweave-evil: in the wheel's manifest, absent from the signed asset" in (
        capsys.readouterr().out
    )

    dropped = WHEEL.split('\n[dist."omniweave-office"]')[0]
    assert TOOL.main(_pair(tmp_path, wheel=dropped)) == TOOL.EXIT_FINDING
    assert "omniweave-office: in the signed asset, absent from the wheel's manifest" in (
        capsys.readouterr().out
    )


def test_an_absent_vendored_key_is_false_on_both_sides(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ruling 3. `render()` writes the line only when the flag is set, so absent is the common row.

    Were absent and `false` different, every unvendored distribution would report as a mismatch --
    noise an auditor learns to skip past, which is how a verification tool stops being read.
    """
    asset = json.loads(json.dumps(ASSET))
    asset["dist"]["omniweave-office"]["vendored"] = False
    plain = WHEEL.replace("vendored = true\n", "")
    assert TOOL.main(_pair(tmp_path, asset=asset, wheel=plain)) == TOOL.EXIT_OK
    assert "agree" in capsys.readouterr().out


def test_a_vendored_row_the_wheel_calls_unvendored_is_still_a_finding(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other direction of ruling 3: the default is symmetric, it is not permissive."""
    plain = WHEEL.replace("vendored = true\n", "")
    assert TOOL.main(_pair(tmp_path, wheel=plain)) == TOOL.EXIT_FINDING
    assert "omniweave-office.vendored: asset True, wheel False" in capsys.readouterr().out


@pytest.mark.parametrize(("key", "value"), [("schema", 2), ("release", "0.2.0")])
def test_the_documents_own_keys_are_compared_too(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], key: str, value: object
) -> None:
    asset = json.loads(json.dumps(ASSET))
    asset[key] = value
    assert TOOL.main(_pair(tmp_path, asset=asset)) == TOOL.EXIT_FINDING
    assert f"{key}: asset {value!r}" in capsys.readouterr().out


def test_the_wheels_copy_can_arrive_on_stdin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Recipe 4 pipes `importlib.resources` straight in, so `-` is the documented form."""
    argv = _pair(tmp_path)

    class _Stdin:
        buffer = __import__("io").BytesIO(WHEEL.encode("utf-8"))

    monkeypatch.setattr(TOOL.sys, "stdin", _Stdin)
    assert TOOL.main([argv[0], "-"]) == TOOL.EXIT_OK
    assert "agree" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(["one.json"], id="one argument"),
        pytest.param(["a.json", "b.toml", "c"], id="three arguments"),
        pytest.param(["--help", "x"], id="help"),
        pytest.param(["-", "-"], id="both on stdin"),
    ],
)
def test_a_usage_error_is_exit_two_and_not_a_finding(argv: list[str]) -> None:
    """Ruling 6: step 15 is run by a person, so a broken recipe must not read as a bad artefact."""
    assert TOOL.main(argv) == TOOL.EXIT_NOT_RUN


@pytest.mark.parametrize(
    ("asset_text", "wheel_text", "why"),
    [
        pytest.param("{not json", WHEEL, "unparsable json", id="json"),
        pytest.param('{"schema": 1}', "schema = [", "unparsable toml", id="toml"),
        pytest.param("[1, 2]", WHEEL, "a list is not a table", id="json not a table"),
        pytest.param('{"dist": 7}', WHEEL, "dist is not a table", id="dist not a table"),
        pytest.param('{"dist": {"a": 7}}', WHEEL, "a row is not a table", id="row not a table"),
    ],
)
def test_an_unreadable_manifest_is_exit_two(
    tmp_path: Path, asset_text: str, wheel_text: str, why: str
) -> None:
    one, two = tmp_path / "a.json", tmp_path / "b.toml"
    one.write_text(asset_text, encoding="utf-8")
    two.write_text(wheel_text, encoding="utf-8")
    assert TOOL.main([str(one), str(two)]) == TOOL.EXIT_NOT_RUN, why


def test_a_missing_file_is_exit_two(tmp_path: Path) -> None:
    argv = _pair(tmp_path)
    assert TOOL.main([str(tmp_path / "absent.json"), argv[1]]) == TOOL.EXIT_NOT_RUN


def test_the_tool_imports_nothing_from_omniweave() -> None:
    """Ruling 1, by reading its own imports: a verifier installed from the thing it verifies
    verifies nothing. An auditor copies this file beside two downloads and runs it."""
    tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert not {one for one in roots if one.startswith("omniweave")}, roots
    assert roots <= set(sys.stdlib_module_names), roots - set(sys.stdlib_module_names)


def test_the_real_generators_output_round_trips_through_the_comparison(tmp_path: Path) -> None:
    """The shapes are `gen_first_party.render()`'s own, not this file's idea of them.

    `render()` is the writer of the in-wheel copy, so the asset is built by reading its TOML back
    and dumping it as JSON -- which is exactly section 7.2's *"the same content in JSON"*.
    """
    gen = _load(GEN_PATH, "_owtool_gen_first_party_for_diff")
    text = gen.render(
        {
            "omniweave-pdf": ("0.1.0", "sha256:1111", False),
            "omniweave-office": ("0.1.0", "sha256:2222", True),
        },
        "0.1.0",
    )
    one, two = tmp_path / "first-party-0.1.0.json", tmp_path / "first_party.toml"
    two.write_text(text, encoding="utf-8")
    one.write_text(json.dumps(__import__("tomllib").loads(text)), encoding="utf-8")
    assert TOOL.main([str(one), str(two)]) == TOOL.EXIT_OK
    assert "vendored = true" in text, "the fixture must exercise ruling 3's flag"
