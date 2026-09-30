"""`omniweave_core.host.keystore`: a secret name, its two sources, and the file it travels in.

ADR-15 D15.3 to D15.5. The macOS and Linux readers are tested against a fake `run_captured`, which
is the one seam they cross; the Windows reader is tested against the real Credential Manager on a
Windows host, with a credential it writes and deletes itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from omniweave_core.host import keystore, subproc
from omniweave_core.host.keystore import (
    PASSWORD_FILENAME,
    Found,
    env_name,
    read_keystore,
    resolve,
    store_command,
    suggested_name,
    write_password,
)
from omniweave_core.host.subproc import Captured

SECRET = "s3cr\u00e9t-horse"  # noqa: S105 -- a fixture's
"""Non-ASCII, for the UTF-16 blob; no space, which `cmdkey /pass:` cannot take on its argv."""


@pytest.mark.parametrize(
    ("name", "variable"),
    [
        ("legal", "OW_SECRET_LEGAL"),
        ("lab-results.2024", "OW_SECRET_LAB_RESULTS_2024"),
        ("Payroll_Q4", "OW_SECRET_PAYROLL_Q4"),
    ],
)
def test_a_name_s_variable_is_upper_cased_with_every_other_character_an_underscore(
    name: str, variable: str
) -> None:
    assert env_name(name) == variable


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("c:/corpus/Lab Results 2024.pdf", "lab-results-2024"),
        ("/srv/docs/nda_northwind.pdf", "nda-northwind"),
        ("c:/corpus/___.pdf", "document"),
    ],
)
def test_the_name_gate_9_offers_is_the_file_s_stem_as_a_secret_name(path: str, name: str) -> None:
    assert suggested_name(path) == name
    assert keystore.NAME_RE.match(suggested_name(path))


def test_the_environment_is_read_first_and_an_empty_value_is_a_secret() -> None:
    """D15.3: `OW_SECRET_<NAME>` before the keystore, so a stale variable shadows an entry; and
    05:2239 allows an empty secret. The keystore is never asked when the variable is set."""

    def never(*_args: object, **_kwargs: object) -> Found:
        raise AssertionError("the keystore is not asked when the variable is set")

    found = resolve("legal", env={"OW_SECRET_LEGAL": ""}, keystore=never)
    assert found == Found("", "the environment variable OW_SECRET_LEGAL")


def test_without_the_variable_the_keystore_answers_for_this_platform() -> None:
    asked: list[tuple[str, str]] = []

    def store(name: str, *, platform: str, env: object) -> Found:
        del env
        asked.append((name, platform))
        return Found(SECRET, "a store")

    assert resolve("legal", env={}, platform="darwin", keystore=store) == Found(SECRET, "a store")
    assert resolve("legal", env={}, keystore=store).secret == SECRET
    assert asked == [("legal", "darwin"), ("legal", sys.platform)]


def _fake(monkeypatch: pytest.MonkeyPatch, answer: Captured) -> list[tuple[str, ...]]:
    ran: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], **_kwargs: object) -> Captured:
        ran.append(tuple(argv))
        return answer

    monkeypatch.setattr(subproc, "run_captured", run)
    return ran


@pytest.mark.parametrize(
    ("platform", "argv", "stdout"),
    [
        (
            "darwin",
            ("security", "find-generic-password", "-s", "omniweave", "-a", "legal", "-w"),
            SECRET.encode() + b"\n",
        ),
        (
            "linux",
            ("secret-tool", "lookup", "service", "omniweave", "name", "legal"),
            SECRET.encode(),
        ),
    ],
)
def test_the_posix_keystores_are_read_by_their_own_lookup_command(
    monkeypatch: pytest.MonkeyPatch, platform: str, argv: tuple[str, ...], stdout: bytes
) -> None:
    """The Keychain's `security` prints the password and a newline; `secret-tool` prints it bare.
    Either way the secret is the text, and `where` names the store and not the secret."""
    ran = _fake(monkeypatch, Captured(returncode=0, stdout=stdout))
    found = read_keystore("legal", platform=platform, env={})
    assert ran == [argv]
    assert found.secret == SECRET
    assert found.where == keystore.KEYSTORES[platform]


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        (Captured(returncode=44), "holds no omniweave secret named 'legal'"),
        (Captured(returncode=None, failed="FileNotFoundError"), "`secret-tool` did not run"),
        (Captured(returncode=None, failed="TimeoutExpired"), "did not answer for 'legal' in 10 s"),
    ],
)
def test_a_keystore_that_does_not_answer_is_a_reason_and_never_a_raise(
    monkeypatch: pytest.MonkeyPatch, answer: Captured, why: str
) -> None:
    _fake(monkeypatch, answer)
    found = read_keystore("legal", platform="linux", env={})
    assert found.secret is None
    assert why in found.where


@pytest.mark.skipif(sys.platform != "win32", reason="the Windows Credential Manager")
def test_the_credential_manager_reads_what_cmdkey_stored(tmp_path: Path) -> None:
    """The real API, against a generic credential this test writes with the command D15.5 prints
    the prompting form of, and deletes. `cmdkey` stores UTF-16, so a non-ASCII password is the
    case that shows the blob is decoded as it was written."""
    name = f"ow-test-{os.getpid()}"
    target = f"omniweave/{name}"
    stored = subproc.run_captured(
        ("cmdkey", f"/generic:{target}", "/user:omniweave", f"/pass:{SECRET}"),
        stdin=b"",
        cwd=str(tmp_path),
        env=dict(os.environ),
        timeout_s=30,
    )
    assert stored.returncode == 0, stored
    try:
        assert read_keystore(name, platform="win32", env={}) == Found(
            SECRET, "the Windows Credential Manager"
        )
    finally:
        subproc.run_captured(
            ("cmdkey", f"/delete:{target}"),
            stdin=b"",
            cwd=str(tmp_path),
            env=dict(os.environ),
            timeout_s=30,
        )
    gone = read_keystore(name, platform="win32", env={})
    assert gone.secret is None
    assert f"holds no generic credential {target!r}" in gone.where


@pytest.mark.parametrize(
    ("platform", "command"),
    [
        ("win32", "cmdkey /generic:omniweave/legal /user:omniweave /pass"),
        ("darwin", "security add-generic-password -s omniweave -a legal -w"),
        ("linux", 'secret-tool store --label="omniweave legal" service omniweave name legal'),
    ],
)
def test_each_store_command_prompts_so_the_password_is_in_no_shell_history(
    platform: str, command: str
) -> None:
    """D15.5. Each OS command, written without the password, asks for it."""
    assert store_command("legal", platform) == command


def test_the_store_command_is_this_machine_s_when_no_platform_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    assert store_command("legal").startswith("security ")


def test_the_password_file_is_written_where_the_driver_reads_it(tmp_path: Path) -> None:
    """D15.4: one file, UTF-8, in the invocation's tmpdir; `omniweave_pdf.driver` reads it."""
    path = write_password(tmp_path / "invoke" / "0", SECRET)
    assert path == tmp_path / "invoke" / "0" / PASSWORD_FILENAME
    assert path.read_bytes() == SECRET.encode("utf-8")
