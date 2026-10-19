"""`omniweave_conform.out_determinism`: OUT13's members, diff and judgement, in process. D878.

Nothing here spawns: the three fresh-process compiles are `tests/conform/`'s (Q-G25), and a
child's failure is a faked `run_captured`. The
in-process compile runs over the register's real docx target.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import tomllib
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from omniweave_conform import out_determinism
from omniweave_conform.out_determinism import (
    WHOLE,
    Compile,
    compile_here,
    judge,
    member_diff,
    members,
)
from omniweave_conform.roundtrip import Target, targets
from omniweave_core.errors import QualityError, TargetError
from omniweave_core.host.subproc import Captured

REPO = Path(__file__).resolve().parents[4]


def _register_target(name: str) -> Target:
    register = tomllib.loads((REPO / "eval" / "gates.toml").read_text(encoding="utf-8"))
    [target] = [t for t in targets(register, REPO) if t.target == name]
    return target


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_an_artefact_that_is_not_a_package_is_one_member() -> None:
    assert members(b"== u01 ==\nhi\n") == {WHOLE: _sha(b"== u01 ==\nhi\n")}


def test_a_package_that_is_not_well_formed_is_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("word/document.xml", b"<w:document/>")
    with pytest.raises(TargetError):
        members(buffer.getvalue())


def test_a_member_diff_names_what_differs_is_missing_and_is_extra() -> None:
    first = {"a.xml": "1" * 64, "b.xml": "2" * 64, "c.xml": "3" * 64}
    other = {"a.xml": "1" * 64, "b.xml": "9" * 64, "d.xml": "4" * 64}
    assert member_diff(first, other) == (
        f"b.xml: {'2' * 12} -> {'9' * 12}",
        "c.xml: missing",
        "d.xml: extra",
    )
    assert member_diff(first, first) == ()


def _compile(label: str, part: str, byte: str, **parts: str) -> Compile:
    return Compile(label, part, byte, parts or {"x.xml": part})


def test_part_is_always_judged_and_names_the_members() -> None:
    a = _compile("a", "1" * 64, "5" * 64, **{"x.xml": "7" * 64})
    b = _compile("b", "2" * 64, "5" * 64, **{"x.xml": "8" * 64})
    got = judge("pptx", ("part",), [a, a, b])
    assert not got.held
    assert got.failures == (
        f"part: b is sha256:{'2' * 12}, a sha256:{'1' * 12} (x.xml: {'7' * 12} -> {'8' * 12})",
    )
    assert (got.agree("part_digest"), got.agree("byte_digest")) == (2, 3)


def test_byte_is_judged_only_when_the_card_declares_it() -> None:
    a = _compile("a", "1" * 64, "5" * 64)
    b = _compile("b", "1" * 64, "6" * 64)
    assert judge("docx", ("part",), [a, b]).held
    [failure] = judge("docx", ("part", "byte"), [a, b]).failures
    assert failure.startswith("byte: b is sha256:666666666666") and "declares byte" in failure


def test_two_in_process_compiles_of_the_docx_golden_agree(tmp_path: Path) -> None:
    target = _register_target("docx")
    first = compile_here(target, tmp_path / "a", label="a")
    second = compile_here(target, tmp_path / "b", label="b")
    assert (first.part_digest, first.members) == (second.part_digest, second.members)
    assert "word/document.xml" in first.members
    assert judge("docx", ("part", "byte"), [first, second]).held


def test_a_golden_that_fails_its_gate_is_not_compiled(tmp_path: Path) -> None:
    """Ruling 5, and the suite's ruling 17: OUT23's gate stands before `lower()`."""
    target = _register_target("docx")
    golden = tmp_path / "golden"
    shutil.copytree(target.golden, golden)
    unit = golden / "il" / "u01.html"
    unit.write_text(
        unit.read_text(encoding="utf-8").replace("</section>", "<script>1</script></section>", 1),
        encoding="utf-8",
    )
    with pytest.raises(QualityError, match=r"gate is failed; lower\(\) is unreachable"):
        compile_here(replace(target, golden=golden), tmp_path / "work", label="a")


def test_a_child_that_exits_non_zero_is_refused_whatever_it_printed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling 5: the exit status is read before the output, so a crash after printing is no row."""
    printed = b'{"label": "x", "part_digest": "1", "byte_digest": "2", "members": {}}\n'
    monkeypatch.setattr(
        out_determinism, "run_captured", lambda *_a, **_k: Captured(3, printed, b"boom")
    )
    with pytest.raises(QualityError, match="exited 3: boom"):
        out_determinism.compile_fresh(
            "docx", root=REPO, register=REPO / "eval" / "gates.toml", workdir=tmp_path, seed="0"
        )
