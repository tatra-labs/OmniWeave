"""Q-G25's marker check tested as a program: `tools/gate_placement.py`. D834.

The shipped test tree passes. Every other test builds a small tree under `tmp_path` and plants
one misplacement for each of the rulings in the gate's docstring. The gate is loaded by file
path under a private name, as `test_gate_budgets.py` loads its gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "gate_placement.py"
    spec = importlib.util.spec_from_file_location("_owgate_gate_placement", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load()

MARKED = "import pytest\n\npytestmark = pytest.mark.conform\n\n\ndef test_a() -> None:\n    pass\n"
PLAIN = "def test_a() -> None:\n    pass\n"


def _tree(root: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    return ["--root", str(root)]


def test_the_repository_passes(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main([]) == GATE.EXIT_CLEAN
    out = capsys.readouterr().out
    assert "tests/conform/ " in out
    assert out.endswith("Q-G25 ok  0 misplaced file(s)\n")


@pytest.mark.parametrize(
    ("path", "tier"),
    [
        ("packages/omniweave/tests/conform/test_a.py", "conform"),
        ("packages/omniweave/tests/conform/deep/test_a.py", "conform"),
        ("packages/omniweave/tests/golden/test_a.py", "golden"),
        ("packages/omniweave/tests/unit/test_a.py", None),
        ("packages/omniweave-core/tests/test_a.py", None),
        ("bench/serve/test_a.py", None),
        ("packages/omniweave/tests/unit/conform/test_a.py", None),
        ("packages/omniweave/tests/unit/tests/conform/test_a.py", "conform"),
    ],
)
def test_the_tier_is_the_directory_after_tests(path: str, tier: str | None) -> None:
    assert GATE.tier_of(path) == tier


@pytest.mark.parametrize(
    ("source", "module", "anywhere"),
    [
        (MARKED, {"conform"}, {"conform"}),
        (
            "import pytest\npytestmark = [pytest.mark.golden, pytest.mark.slow]\n",
            {"golden"},
            {"golden"},
        ),
        ("import pytest\npytestmark: object = pytest.mark.conform\n", {"conform"}, {"conform"}),
        ("import pytest\n@pytest.mark.conform\ndef test_a(): pass\n", set(), {"conform"}),
        ("import pytest\nP = [pytest.param(1, marks=pytest.mark.golden)]\n", set(), {"golden"}),
        (
            "import pytest\nfrom pytest import mark\n@mark.conform\ndef test_a(): pass\n",
            set(),
            set(),
        ),
        ("import pytest\npytestmark = pytest.mark.slow\n", set(), set()),
        ("import other\npytestmark = other.mark.conform\n", set(), set()),
    ],
)
def test_marks_reads_the_module_mark_and_every_use(
    source: str, module: set[str], anywhere: set[str]
) -> None:
    assert GATE.marks(source) == (frozenset(module), frozenset(anywhere))


def test_a_tier_marker_outside_its_directory_is_misplaced() -> None:
    decorated = "import pytest\n@pytest.mark.conform\ndef test_a(): pass\n"
    found = GATE.audit(
        {
            "packages/x/tests/unit/test_spawn.py": decorated,
            "bench/serve/test_golden.py": "import pytest\npytestmark = pytest.mark.golden\n",
            "packages/x/tests/conform/test_ok.py": MARKED,
        }
    )
    assert [(m.path, m.marker, m.reason) for m in found] == [
        ("bench/serve/test_golden.py", "golden", "marked 'golden' outside tests/golden/"),
        (
            "packages/x/tests/unit/test_spawn.py",
            "conform",
            "marked 'conform' outside tests/conform/",
        ),
    ]


def test_a_test_file_in_a_tier_directory_must_mark_its_module() -> None:
    decorated_only = "import pytest\n@pytest.mark.conform\ndef test_a(): pass\n"
    found = GATE.audit(
        {
            "packages/x/tests/conform/test_plain.py": PLAIN,
            "packages/x/tests/conform/test_decorated.py": decorated_only,
            "packages/x/tests/conform/conftest.py": PLAIN,
            "packages/x/tests/golden/test_wrong.py": MARKED,
        }
    )
    assert [(m.path, m.reason) for m in found] == [
        (
            "packages/x/tests/conform/test_decorated.py",
            "in tests/conform/ without a module-level pytestmark = pytest.mark.conform",
        ),
        (
            "packages/x/tests/conform/test_plain.py",
            "in tests/conform/ without a module-level pytestmark = pytest.mark.conform",
        ),
        ("packages/x/tests/golden/test_wrong.py", "marked 'conform' outside tests/conform/"),
        (
            "packages/x/tests/golden/test_wrong.py",
            "in tests/golden/ without a module-level pytestmark = pytest.mark.golden",
        ),
    ]


def test_two_tiers_on_one_file_is_one_finding() -> None:
    both = "import pytest\npytestmark = [pytest.mark.conform, pytest.mark.golden]\n"
    found = GATE.audit({"packages/x/tests/conform/test_both.py": both})
    assert [(m.marker, m.reason) for m in found] == [
        ("conform+golden", "marked conform and golden; no directory permits both")
    ]


def test_the_report_names_the_code_the_file_and_the_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _tree(
        tmp_path,
        {
            "packages/x/tests/conform/test_ok.py": MARKED,
            "packages/x/tests/unit/test_bad.py": MARKED,
            "packages/x/tests/unit/helper.py": MARKED,
            "bench/serve/test_b.py": PLAIN,
        },
    )
    assert GATE.main(argv) == GATE.EXIT_FAIL
    assert capsys.readouterr().out.splitlines() == [
        "Q-G25  3 file(s); tests/conform/ 1, tests/golden/ 0",
        "  not checked: a spawning or socket-opening test with no marker (the autouse fixture)",
        "  OW-Q-014 packages/x/tests/unit/test_bad.py: marked 'conform' outside tests/conform/",
        "  fix: move the test, do not move the marker",
        "Q-G25 FAIL  1 misplaced file(s)",
    ]


def test_a_test_file_that_does_not_parse_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = _tree(tmp_path, {"packages/x/tests/unit/test_broken.py": "def test_a(:\n"})
    assert GATE.main(argv) == GATE.EXIT_NOT_RUN
    assert capsys.readouterr().out.startswith("Q-G25 DID NOT RUN  ")


def test_a_bad_argument_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--no-such-flag"]) == GATE.EXIT_NOT_RUN
    capsys.readouterr()
