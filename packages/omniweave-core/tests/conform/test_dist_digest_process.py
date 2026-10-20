"""D894: a real first-party wheel and its real install have one `dist_sha256`.

The unit tests pin each `RECORD` rule over synthetic rows. This is the claim D576's first ruling
rests on, made over the bytes an installer actually leaves: `omniweave-pdf` is built into a wheel,
installed into a fresh environment by `uv pip` (no dependencies, from the file, so no index), and
the digest of the wheel's `RECORD` must equal the digest of the installed one, with every kept
file still matching its row.
"""

from __future__ import annotations

import json
import shutil
import subprocess  # noqa: TID251 -- building and installing a wheel is the subject of this file.
import sys
from pathlib import Path

import pytest
from omniweave_core.drivers import digest

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]
DIGEST_PY = Path(digest.__file__)
TIMEOUT_S = 600
CHILD = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("digest", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps({
    "installed": module.installed_digest("omniweave-pdf"),
    "drift": list(module.verify_installed("omniweave-pdf")),
}))
"""


def _run(*argv: str, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- argv is built here, from literals and paths.
        list(argv),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
        timeout=TIMEOUT_S,
    )


def test_a_built_wheel_and_its_uv_install_have_one_digest(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    assert uv is not None, "the test environment is a uv workspace"
    built = _run(uv, "build", "--package", "omniweave-pdf", "--wheel", "--out-dir", str(tmp_path))
    assert built.returncode == 0, built.stderr[-800:]
    (wheel,) = tmp_path.glob("omniweave_pdf-*.whl")
    venv = tmp_path / "venv"
    made = _run(uv, "venv", "--quiet", "--python", sys.executable, str(venv))
    assert made.returncode == 0, made.stderr[-800:]
    python = venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    installed = _run(uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel))
    assert installed.returncode == 0, installed.stderr[-800:]
    child = _run(str(python), "-I", "-c", CHILD, str(DIGEST_PY), cwd=tmp_path)
    assert child.returncode == 0, child.stderr[-800:]
    report = json.loads(child.stdout.strip().splitlines()[-1])
    assert report["installed"] == digest.wheel_digest(wheel)
    assert report["drift"] == []
