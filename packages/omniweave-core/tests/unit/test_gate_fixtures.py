"""Q-G1 tested as a program: `tools/gate_fixtures.py`, and the PDF fixtures' generator. D843.

The gate is held to its docstring rule by rule:
- the scope, over listings with no git;
- a row against its file and its provenance;
- the index rendered and read back through `tomllib`;
- `main()` over sidecars written under `tmp_path`, and once over this repository.

`fixtures/gen/gen_pdf_fixtures.py` is held to the pins it checks and to the sidecars it wrote.

Both are loaded by file path under private names and at module scope, as `test_gate_flake.py`
loads its gate.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GATE = _load(REPO / "tools" / "gate_fixtures.py", "_owgate_gate_fixtures")
GEN = _load(REPO / "fixtures" / "gen" / "gen_pdf_fixtures.py", "_owgen_gen_pdf_fixtures")
DATA = b"%PDF-1.7\nfixture\n"
DIGEST = hashlib.sha256(DATA).hexdigest()
GENERATOR = "fixtures/gen/gen_x.py"
COMMITTED = frozenset({GENERATOR, "tools/gen_x.py"})


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sha256": DIGEST,
        "bytes": len(DATA),
        "provenance": "generated",
        "spdx": "Apache-2.0",
        "generator": GENERATOR,
    }
    row.update(over)
    return {key: value for key, value in row.items() if value is not None}


def _check(**over: Any) -> list[str]:
    return GATE.check_row(_row(**over), DATA, COMMITTED)


# --- ruling 1: the scope ---------------------------------------------------------------------


def test_the_scope_is_package_fixtures_and_fixtures_docs_less_their_housekeeping() -> None:
    listed = [
        "packages/omniweave-pdf/fixtures/b.pdf",
        "packages/omniweave-pdf/fixtures/b.pdf.meta.toml",
        "packages/omniweave-pdf/fixtures/a/deep.pdf",
        "packages/omniweave-pdf/fixtures/README.md",
        "packages/omniweave-pdf/fixtures/.gitattributes",
        "packages/omniweave-pdf/fixtures/EXPECTED.sha256",
        "packages/omniweave/src/omniweave/hooks/fixtures/session-start.json",
        "packages/omniweave-pdf/README.md",
        "fixtures/docs/sec.pdf",
        "fixtures/docs/sec.pdf.meta.toml",
        "fixtures/cassettes/agent/00/x.json",
        "fixtures/gen/gen_x.py",
        "fixtures/goldens/DECOMPOSITION.toml",
        "fixtures/out/golden/docx/cites.json",
        "fixtures/index.toml",
    ]
    assert GATE.scope(listed) == (
        [
            "fixtures/docs/sec.pdf",
            "packages/omniweave-pdf/fixtures/a/deep.pdf",
            "packages/omniweave-pdf/fixtures/b.pdf",
        ],
        ["fixtures/docs/sec.pdf.meta.toml", "packages/omniweave-pdf/fixtures/b.pdf.meta.toml"],
    )


# --- rulings 2-4: a row ----------------------------------------------------------------------


def test_a_generated_row_that_matches_its_file_is_clean() -> None:
    assert _check() == []


def test_a_sidecar_with_no_file_names_that_alone() -> None:
    assert GATE.check_row(_row(), None, COMMITTED) == ["the sidecar names no committed file"]


@pytest.mark.parametrize("key", ["sha256", "bytes", "provenance", "spdx"])
def test_each_common_key_is_required(key: str) -> None:
    assert f"no {key}" in _check(**{key: None})


@pytest.mark.parametrize(
    ("provenance", "keys"),
    [
        ("generated", ["generator"]),
        ("public_domain", ["source_url", "retrieved_at", "statutory"]),
        ("cc0", ["source_url", "retrieved_at"]),
        ("cc_by", ["source_url", "retrieved_at", "attribution"]),
        ("authored", ["contributor", "cla"]),
    ],
)
def test_each_provenance_records_what_section_4_2_requires(
    provenance: str, keys: list[str]
) -> None:
    assert _check(provenance=provenance, generator=None) == [f"no {', '.join(keys)}"]


def test_each_provenance_with_its_record_is_clean() -> None:
    record = {
        "source_url": "https://www.sec.gov/x.pdf",
        "retrieved_at": "2026-04-11",
        "statutory": "17 U.S.C. 105",
        "attribution": "Example, CC BY 4.0",
        "contributor": "q@example.org",
        "cla": "DCO",
    }
    for provenance in ("public_domain", "cc0", "cc_by", "authored"):
        assert _check(provenance=provenance, generator=None, **record) == [], provenance


def test_a_fifth_provenance_is_refused() -> None:
    assert _check(provenance="scraped") == [
        "provenance 'scraped' is not one of generated, public_domain, cc0, cc_by, authored"
    ]


def test_the_digest_and_size_are_the_files() -> None:
    assert _check(sha256="0" * 64, bytes=1) == [
        f"sha256 {'0' * 64} is not the file's {DIGEST}",
        f"bytes 1 is not the file's {len(DATA)}",
    ]


@pytest.mark.parametrize("generator", ["tools/gen_x.py", "fixtures/gen/gen_missing.py"])
def test_a_generator_is_a_committed_file_under_fixtures_gen(generator: str) -> None:
    assert _check(generator=generator) == [
        f"generator {generator} is not a committed file under fixtures/gen/"
    ]


def test_retrieved_at_is_a_date() -> None:
    public = {"provenance": "cc0", "generator": None, "source_url": "u"}
    assert _check(**public, retrieved_at="2026-04-11") == []
    assert _check(**public, retrieved_at=dt.date(2026, 4, 11)) == []
    assert _check(**public, retrieved_at="April 2026") == [
        "retrieved_at 'April 2026' is not YYYY-MM-DD"
    ]


def test_a_sidecar_may_not_set_the_indexs_path() -> None:
    assert _check(path="elsewhere.pdf") == [
        "path is the index's own key, and a sidecar may not set it"
    ]


def test_an_empty_value_at_any_depth_is_refused() -> None:
    assert _check(spdx="", note=[], tests={"defect": "", "slices": ["a"]}, extra={}) == [
        "spdx is empty",
        "note is empty",
        "tests.defect is empty",
        "extra is empty",
    ]


# --- ruling 5: the index ---------------------------------------------------------------------


def test_the_index_is_sorted_with_path_first_and_subtables_last() -> None:
    rows = [
        ("z.pdf", {"spdx": "MIT", "bytes": 3}),
        (
            "a.pdf",
            {
                "reductions": {"shape": "frozen"},
                "spdx": "Apache-2.0",
                "bytes": 1,
                "ok": True,
                "ratio": 0.5,
                "seen": dt.date(2026, 4, 11),
                "slices": ["pdf/mixed", "scan"],
                "note": 'a "quote" — and a dash',
                "tests": {"asserts": ["order_acc"], "deep": {"k": 1}},
            },
        ),
    ]
    text = GATE.render(rows)
    assert text.startswith(GATE.HEADER + '\n[[fixture]]\npath = "a.pdf"\nbytes = 1\n')
    assert text.endswith('[[fixture]]\npath = "z.pdf"\nbytes = 3\nspdx = "MIT"\n')
    assert '\n[fixture.reductions]\nshape = "frozen"\n' in text
    assert "\n[fixture.tests.deep]\nk = 1\n" in text
    assert "\r" not in text
    back = tomllib.loads(text)["fixture"]
    assert [row["path"] for row in back] == ["a.pdf", "z.pdf"]
    assert {k: v for k, v in back[0].items() if k != "path"} == rows[1][1]


def test_an_unrenderable_value_is_a_type_error() -> None:
    with pytest.raises(TypeError, match="set has no TOML value here"):
        GATE.render([("a.pdf", {"odd": {1, 2}})])


def test_a_key_that_is_not_bare_is_quoted() -> None:
    assert 'path = "a"\n"two words" = 1\n' in GATE.render([("a", {"two words": 1})])


# --- main(), over a tree under tmp_path -----------------------------------------------------

PDF = "packages/omniweave-x/fixtures/a.pdf"


def _tree(root: Path, sidecar: str | None = None) -> list[str]:
    (root / "fixtures" / "gen").mkdir(parents=True)
    (root / GENERATOR).write_bytes(b"# a generator\n")
    folder = root / "packages" / "omniweave-x" / "fixtures"
    folder.mkdir(parents=True)
    (folder / "a.pdf").write_bytes(DATA)
    text = (
        sidecar
        if sidecar is not None
        else (
            f'[fixture]\nsha256 = "{DIGEST}"\nbytes = {len(DATA)}\nprovenance = "generated"\n'
            f'spdx = "Apache-2.0"\ngenerator = "{GENERATOR}"\n'
        )
    )
    (folder / "a.pdf.meta.toml").write_bytes(text.encode())
    return [GENERATOR, PDF, PDF + ".meta.toml"]


def _main(root: Path, listed: list[str], capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
    code = GATE.main(["--root", str(root), *argv], committed=listed)
    return code, capsys.readouterr().out


def test_write_then_check_is_clean_and_a_stale_index_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = _tree(tmp_path)
    assert _main(tmp_path, listed, capsys, "--write") == (
        0,
        "Q-G1  1 fixture(s), 1 sidecar(s), 1 indexed\n  wrote fixtures/index.toml\n"
        "Q-G1 ok  0 finding(s)\n",
    )
    assert _main(tmp_path, listed, capsys)[0] == 0
    index = tmp_path / "fixtures" / "index.toml"
    index.write_bytes(index.read_bytes().replace(b"Apache-2.0", b"MIT"))
    code, out = _main(tmp_path, listed, capsys)
    assert code == 1
    assert (
        "  FAIL  fixtures/index.toml: differs from what the sidecars generate; "
        "run `uv run tools/gate_fixtures.py --write`" in out
    )


def test_a_missing_index_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _main(tmp_path, _tree(tmp_path), capsys)
    assert code == 1
    assert "  FAIL  fixtures/index.toml: is missing; run" in out


def test_a_fixture_with_no_sidecar_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = _tree(tmp_path)[:2]
    code, out = _main(tmp_path, listed, capsys, "--write")
    assert code == 1
    assert f"  FAIL  {PDF}: no manifest row; write a.pdf.meta.toml beside it" in out
    assert "  fix " not in out


def test_an_uncommitted_fixture_file_is_no_sidecars_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    listed = [path for path in _tree(tmp_path) if path != PDF]
    code, out = _main(tmp_path, listed, capsys, "--write")
    assert code == 1
    assert f"  FAIL  {PDF}.meta.toml: the sidecar names no committed file" in out
    assert "  fix   mend the sidecar, then run `uv run tools/gate_fixtures.py --write`" in out


@pytest.mark.parametrize(
    ("sidecar", "why"),
    [
        ("[fixture\n", "unreadable: "),
        ('[other]\nsha256 = "x"\n', "has no [fixture] table"),
        ('[fixture]\nsha256 = "x"\n', "no bytes, provenance, spdx"),
    ],
)
def test_a_bad_sidecar_fails_and_is_left_out_of_the_index(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], sidecar: str, why: str
) -> None:
    listed = _tree(tmp_path, sidecar)
    code, out = _main(tmp_path, listed, capsys, "--write")
    assert code == 1
    assert f"  FAIL  {PDF}.meta.toml: {why}" in out
    assert "Q-G1  1 fixture(s), 1 sidecar(s), 0 indexed" in out
    assert "[[fixture]]" not in (tmp_path / "fixtures" / "index.toml").read_text(encoding="utf-8")


def test_without_git_the_gate_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GATE.shutil, "which", lambda _name: None)
    assert GATE.main(["--root", str(tmp_path)]) == 2
    assert capsys.readouterr().out == "Q-G1 DID NOT RUN  git is not on PATH\n"


def test_a_directory_git_cannot_list_did_not_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert GATE.main(["--root", str(tmp_path)]) == 2
    assert capsys.readouterr().out.startswith("Q-G1 DID NOT RUN  git ls-files: ")


def test_a_bad_flag_did_not_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main(["--strict"]) == 2
    capsys.readouterr()


# --- the repository --------------------------------------------------------------------------


def test_this_repository_passes_q_g1(capsys: pytest.CaptureFixture[str]) -> None:
    assert GATE.main([]) == 0, capsys.readouterr().out
    rows = tomllib.loads((REPO / "fixtures" / "index.toml").read_text(encoding="utf-8"))["fixture"]
    assert len(rows) == 37
    assert {row["provenance"] for row in rows} == {"generated"}


def test_the_pdf_generator_reproduces_its_seven_pins(capsys: pytest.CaptureFixture[str]) -> None:
    assert GEN.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in lines] == sorted(GEN.BUILDS)
    assert all(line.startswith("ok ") for line in lines)


def test_the_pdf_sidecars_are_the_generators_output() -> None:
    for name, (build, media_type, purpose) in GEN.BUILDS.items():
        sidecar = REPO / "packages" / "omniweave-pdf" / "fixtures" / f"{name}.meta.toml"
        assert sidecar.read_bytes() == GEN.sidecar(name, build(), media_type, purpose).encode()


def test_a_byte_the_generator_changes_is_a_mismatch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    builds = dict(GEN.BUILDS)
    _, media_type, purpose = builds["not_a_pdf.bin"]
    builds["not_a_pdf.bin"] = (lambda: b"PK\x03\x04changed\n", media_type, purpose)
    monkeypatch.setattr(GEN, "BUILDS", builds)
    assert GEN.main([]) == 1
    assert "MISMATCH  not_a_pdf.bin: " in capsys.readouterr().out
