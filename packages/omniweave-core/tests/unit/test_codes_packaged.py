"""The error-code register ships in core's wheel, as the root register byte for byte. D897.

An installed release had no `codes.toml`: every error printed its symbol alone and `ow explain`
resolved nothing, because the register's home is the repo root (11-repo-layout.md section 1.1) and
no wheel carries a repo root. `omniweave_core/codes.toml` is a committed copy, so the wheel and its
sdist carry it without reaching outside the distribution (`test_sdist_shape.py`, D12's defect).
"""

from __future__ import annotations

from pathlib import Path

from omniweave_core import errors

REPO = Path(__file__).resolve().parents[4]
ROOT = REPO / "codes.toml"
PACKAGED = REPO / "packages/omniweave-core/src/omniweave_core/codes.toml"


def test_the_packaged_register_is_the_root_register_byte_for_byte() -> None:
    assert PACKAGED.read_bytes() == ROOT.read_bytes(), (
        "codes.toml changed and its packaged copy did not: "
        "cp codes.toml packages/omniweave-core/src/omniweave_core/codes.toml"
    )


def test_the_packaged_copy_is_the_one_an_install_reads() -> None:
    assert errors.register_path().resolve() == PACKAGED.resolve()
