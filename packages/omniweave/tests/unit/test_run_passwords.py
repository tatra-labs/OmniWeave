"""`[ingest] password_file`: the mapping, the match, the lookup and the report. ADR-15 D15.3.

`Passwords` is given a fake resolver throughout, so no test reads this machine's keystore or its
environment; `test_host_keystore.py` tests the two sources themselves.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from omniweave.run.passwords import Entry, Passwords, read_entries
from omniweave_core.errors import ConfigError
from omniweave_core.host.keystore import Found
from omniweave_core.identity import canonical_uri

SECRET = "hunter2"  # noqa: S105 -- a fixture's


def _file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "passwords.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_file_is_one_glob_per_line_mapping_to_a_name_in_file_order(tmp_path: Path) -> None:
    path = _file(
        tmp_path,
        '"contracts/**/*.pdf" = "legal"\n"c:/scans/payroll.pdf" = "payroll"\n',
    )
    assert read_entries(path) == (
        Entry("contracts/**/*.pdf", "legal"),
        Entry("c:/scans/payroll.pdf", "payroll"),
    )


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ('"a.pdf" = "not a name"', "not a secret name"),
        ('"a.pdf" = 42', "not a secret name"),
        ('[legal]\n"a.pdf" = "x"', "not a secret name"),
        ('" " = "legal"', "an empty glob"),
        ('"a.pdf" = ', "not TOML"),
    ],
)
def test_a_malformed_file_is_refused_naming_the_file_and_the_entry(
    tmp_path: Path, text: str, why: str
) -> None:
    """A file that silently mapped nothing would leave every encrypted file refused with no
    reason given, so a bad line is a startup refusal."""
    path = _file(tmp_path, text)
    with pytest.raises(ConfigError, match=why) as caught:
        read_entries(path)
    assert str(path) in str(caught.value)


def test_a_file_that_is_not_there_is_refused_with_the_fix(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unreadable") as caught:
        read_entries(tmp_path / "missing.toml")
    assert "password_file" in caught.value.fix


def _passwords(
    root: Path, entries: list[Entry], found: dict[str, Found] | None = None
) -> tuple[Passwords, list[str]]:
    asked: list[str] = []

    def resolve(name: str) -> Found:
        asked.append(name)
        return (found or {}).get(name, Found(SECRET, "the environment variable OW_SECRET_X"))

    return Passwords(entries, source_root=root, env={}, resolve=resolve), asked


def test_a_relative_glob_matches_the_path_under_the_source_root(tmp_path: Path) -> None:
    """`[ingest] include`'s matcher, `**/` relaxation and all, against the relative path."""
    root = tmp_path / "src"
    passwords, _ = _passwords(root, [Entry("**/legal/*.pdf", "legal")])
    assert passwords.name_for(canonical_uri(root / "legal" / "nda.pdf")) == "legal"
    assert passwords.name_for(canonical_uri(root / "deep" / "legal" / "nda.pdf")) == "legal"
    assert passwords.name_for(canonical_uri(root / "legal" / "nda.docx")) is None
    assert passwords.name_for(canonical_uri(tmp_path / "elsewhere" / "legal" / "a.pdf")) is None


def test_an_absolute_glob_matches_the_whole_unit_uri_which_gate_9_prints(tmp_path: Path) -> None:
    """D15.5 prints the unit's own path as the line to paste, so that form must match."""
    root = tmp_path / "src"
    uri = canonical_uri(root / "Locked Scan.pdf")
    passwords, _ = _passwords(root, [Entry(uri, "scan")])
    assert passwords.name_for(uri) == "scan"
    assert passwords.name_for(canonical_uri(root / "other.pdf")) is None


@pytest.mark.skipif(sys.platform != "win32", reason="a Windows unit_uri is case-folded")
def test_on_windows_a_glob_is_folded_as_the_unit_uri_is(tmp_path: Path) -> None:
    root = tmp_path / "src"
    passwords, _ = _passwords(root, [Entry("Legal/NDA.pdf", "legal")])
    assert passwords.name_for(canonical_uri(root / "legal" / "nda.pdf")) == "legal"


def test_the_first_line_that_matches_wins(tmp_path: Path) -> None:
    root = tmp_path / "src"
    passwords, _ = _passwords(root, [Entry("a/*.pdf", "first"), Entry("**/*.pdf", "second")])
    assert passwords.name_for(canonical_uri(root / "a" / "x.pdf")) == "first"
    assert passwords.name_for(canonical_uri(root / "b" / "x.pdf")) == "second"


def test_a_name_is_resolved_once_per_run_and_an_unmapped_unit_asks_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "src"
    passwords, asked = _passwords(root, [Entry("*.pdf", "legal")])
    assert passwords.secret_for(canonical_uri(root / "a.pdf")) == SECRET
    assert passwords.secret_for(canonical_uri(root / "b.pdf")) == SECRET
    assert passwords.secret_for(canonical_uri(root / "c.docx")) is None
    assert asked == ["legal"]


def test_only_an_encrypted_unit_whose_name_resolves_is_read_again(tmp_path: Path) -> None:
    """D15.3. A name that resolves nowhere would refuse the file again, so it is not re-read."""
    root = tmp_path / "src"
    passwords, _ = _passwords(
        root,
        [Entry("known.pdf", "known"), Entry("unknown.pdf", "unknown")],
        {"unknown": Found(None, "no such entry")},
    )
    known, unknown = canonical_uri(root / "known.pdf"), canonical_uri(root / "unknown.pdf")
    assert passwords.reopens(known, "encrypted") is True
    assert passwords.reopens(known, "corrupt_input") is False
    assert passwords.reopens(unknown, "encrypted") is False
    assert passwords.reopens(canonical_uri(root / "unmapped.pdf"), "encrypted") is False


def test_the_report_names_where_each_name_came_from_and_never_the_secret(tmp_path: Path) -> None:
    root = tmp_path / "src"
    passwords, _ = _passwords(
        root,
        [Entry("a.pdf", "legal"), Entry("b.pdf", "hr")],
        {"hr": Found(None, "the Secret Service holds no omniweave secret named 'hr'")},
    )
    assert passwords.lines() == ()
    passwords.secret_for(canonical_uri(root / "a.pdf"))
    passwords.secret_for(canonical_uri(root / "b.pdf"))
    lines = passwords.lines()
    assert lines[0] == "  password  1 resolved: legal from the environment variable OW_SECRET_X"
    assert lines[1].startswith(
        "  password  hr not found: the Secret Service holds no omniweave secret named 'hr'; "
        "store it with `"
    )
    assert lines[1].endswith("`, or set OW_SECRET_HR")
    assert all(SECRET not in line for line in lines)


def test_no_password_file_is_no_mapping(tmp_path: Path) -> None:
    assert Passwords.load(None, source_root=tmp_path, env={}) is None
    path = _file(tmp_path, '"*.pdf" = "legal"\n')
    loaded = Passwords.load(path, source_root=tmp_path, env={"OW_SECRET_LEGAL": SECRET})
    assert loaded is not None
    assert loaded.source == str(path)
    assert loaded.secret_for(canonical_uri(tmp_path / "a.pdf")) == SECRET
