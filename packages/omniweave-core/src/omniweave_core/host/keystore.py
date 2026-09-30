"""Document passwords: a secret's NAME, the two places it resolves, and the one file it travels in.

ADR-15 D15.3 to D15.5. 05:472-474 says `[ingest] password_file` maps a unit glob to a secret *name*,
and that the name *"resolves through the OS keystore, never through the file"*. It names no
keystore, no way to put a secret in one, and nothing for a machine without one. This module is the
half of that path which touches the operating system; `omniweave.run.passwords` is the half that
reads the mapping.

```text
name     "legal"                     [A-Za-z0-9][A-Za-z0-9._-]{0,63}, chosen by the user
env      OW_SECRET_LEGAL             read FIRST: a CI runner, a container, a server (05:311)
win32    Credential Manager          a generic credential, target "omniweave/legal", CredReadW
darwin   Keychain                    service "omniweave", account "legal", `security`
linux    Secret Service              attributes service=omniweave name=legal, `secret-tool`
```

**The environment wins, and a stale variable shadows a keystore entry.** ADR-15's *"What becomes
harder"* names that cost; `Found.where` names the source that answered, so a report can say which.

**No command here is a writer.** Storing a secret is the operating system's own command, and
`store_command()` prints it: `cmdkey`, `security add-generic-password`, `secret-tool store`. Each
prompts for the password when it is not on the command line, so the secret never reaches a shell's
history. ADR-15 rejected an `ow secret set` verb for this reason: the OS's command does the same
with nothing new to secure.

**What never holds a secret:** `Found.where`, every message this module writes, and anything a
caller logs from it. A secret is returned as `Found.secret` and nowhere else.

## The one file it travels in

D15.4: *"the host writes it to a file in the one invocation's `DriverIO.tmpdir`, which the host
deletes (14:1060), and the driver reads it there. `DriverIO` keeps its four fields (INV-6)."*
`PASSWORD_FILENAME` is that file's name. The driver cannot import this module (a `parse/1`
distribution imports `omniweave_ports` alone, `tools/layers.toml`), and `omniweave_ports`' export
list is a T-CONTRACT surface that moves only with `CONTRACT`, so the name is written twice, here and
in `omniweave_pdf.driver`, and a test holds the two equal.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = [
    "ENV_PREFIX",
    "KEYSTORES",
    "NAME_RE",
    "PASSWORD_FILENAME",
    "SERVICE",
    "Found",
    "env_name",
    "read_keystore",
    "resolve",
    "store_command",
    "suggested_name",
    "write_password",
]

SERVICE: Final[str] = "omniweave"
"""The keystore service every secret is filed under: the Windows target prefix, the Keychain
service, and the Secret Service `service` attribute (D15.3)."""

ENV_PREFIX: Final[str] = "OW_SECRET_"

NAME_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
"""A secret name: what the password file writes and the keystore files it under. A word, not a
path, so `omniweave/<name>` is one Windows target and `OW_SECRET_<NAME>` is one variable."""

PASSWORD_FILENAME: Final[str] = ".omniweave-password"  # noqa: S105 -- a file name
"""The file in `DriverIO.tmpdir` that holds one unit's password, UTF-8, for one invocation (D15.4).
`omniweave_pdf.driver.PASSWORD_FILE` is the driver's copy of this name."""

KEYSTORES: Final[Mapping[str, str]] = {
    "win32": "the Windows Credential Manager",
    "darwin": "the macOS Keychain",
    "linux": "the Secret Service",
}

KEYSTORE_TIMEOUT_S: Final[float] = 10.0
"""A keystore read's ceiling. A locked Secret Service collection can prompt to unlock, and a run
that waited on a dialog nobody sees would hang where it should name the name it could not read."""

_ERROR_NOT_FOUND: Final[int] = 1168
_CRED_TYPE_GENERIC: Final[int] = 1


@dataclass(frozen=True, slots=True)
class Found:
    """One name's resolution: the secret, or `None`, and where it came from or why it did not.

    `where` never holds the secret. It is printed on the ingest report.
    """

    secret: str | None
    where: str


def env_name(name: str) -> str:
    """`OW_SECRET_<NAME>`: the name upper-cased, every character but a letter or digit `_`."""
    return ENV_PREFIX + re.sub(r"[^A-Z0-9]", "_", name.upper())


def suggested_name(path: str) -> str:
    """A secret name for one file, from its stem: what gate 9's message offers (D15.5)."""
    stem = Path(path.rstrip("/")).stem.lower()
    word = re.sub(r"[^a-z0-9]+", "-", stem).strip("-")[:64]
    return word if word and NAME_RE.match(word) else "document"


def resolve(
    name: str,
    *,
    env: Mapping[str, str],
    platform: str | None = None,
    keystore: Callable[..., Found] | None = None,
) -> Found:
    """`name`'s secret: `OW_SECRET_<NAME>` first, then this platform's keystore (D15.3).

    An empty variable is a secret, as 05:2239 allows an empty one. `keystore` replaces
    `read_keystore`, so a test resolves a name without touching the machine's store.
    """
    var = env_name(name)
    if var in env:
        return Found(env[var], f"the environment variable {var}")
    reader = read_keystore if keystore is None else keystore
    return reader(name, platform=sys.platform if platform is None else platform, env=env)


def read_keystore(name: str, *, platform: str, env: Mapping[str, str]) -> Found:
    """`name` from this platform's keystore. Never raises: a failure is `Found(None, why)`."""
    if platform == "win32":
        return _credential_manager(name)
    if platform == "darwin":
        argv: tuple[str, ...] = ("security", "find-generic-password", "-s", SERVICE, "-a", name)
        return _captured((*argv, "-w"), env=env, store=KEYSTORES["darwin"], name=name)
    argv = ("secret-tool", "lookup", "service", SERVICE, "name", name)
    return _captured(argv, env=env, store=KEYSTORES["linux"], name=name)


def _captured(argv: Sequence[str], *, env: Mapping[str, str], store: str, name: str) -> Found:
    """A keystore's own lookup command, run with no shell; its stdout is the secret."""
    from omniweave_core.host import subproc  # noqa: PLC0415 -- the reader imports this module

    done = subproc.run_captured(
        argv, stdin=b"", cwd=str(Path.home()), env=dict(env), timeout_s=KEYSTORE_TIMEOUT_S
    )
    if done.failed == "TimeoutExpired":
        return Found(None, f"{store} did not answer for {name!r} in {KEYSTORE_TIMEOUT_S:g} s")
    if done.failed:
        return Found(None, f"{store} is unreachable: `{argv[0]}` did not run ({done.failed})")
    if done.returncode != 0:
        return Found(None, f"{store} holds no {SERVICE} secret named {name!r}")
    text = done.stdout.decode("utf-8", "replace")
    return Found(text.removesuffix("\n"), store)


def _credential_manager(name: str) -> Found:
    """`CredReadW` for the generic credential `omniweave/<name>`, in this process.

    `cmdkey`, the command `store_command` prints, writes the blob as UTF-16LE, as the Credential
    Manager's own dialog does, so an even-length blob is read that way and any other as UTF-8.
    """
    import ctypes  # noqa: PLC0415 -- win32 only
    from ctypes import wintypes  # noqa: PLC0415

    class _Filetime(ctypes.Structure):
        _fields_ = (("low", wintypes.DWORD), ("high", wintypes.DWORD))

    class _Credential(ctypes.Structure):
        _fields_ = (
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", _Filetime),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        )

    store = KEYSTORES["win32"]
    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    except OSError as missing:
        return Found(None, f"{store} is unreachable: {missing}")
    read = advapi.CredReadW
    read.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    )
    read.restype = wintypes.BOOL
    free = advapi.CredFree
    free.argtypes = (ctypes.c_void_p,)
    free.restype = None
    found = ctypes.POINTER(_Credential)()
    target = f"{SERVICE}/{name}"
    if not read(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(found)):
        code = ctypes.get_last_error()  # type: ignore[attr-defined]
        if code == _ERROR_NOT_FOUND:
            return Found(None, f"{store} holds no generic credential {target!r}")
        return Found(None, f"{store} refused to read {target!r}: error {code}")
    try:
        credential = found.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
    finally:
        free(found)
    try:
        text = blob.decode("utf-16-le") if len(blob) % 2 == 0 else blob.decode("utf-8")
    except UnicodeDecodeError:
        return Found(None, f"{store}'s {target!r} is neither UTF-16 nor UTF-8 text")
    return Found(text, store)


def store_command(name: str, platform: str | None = None) -> str:
    """The one command that stores `name`'s secret on `platform`, prompting for it (D15.5).

    `platform` is `sys.platform` when omitted, read at the call: the machine gate 9 answers on."""
    platform = sys.platform if platform is None else platform
    if platform == "win32":
        return f"cmdkey /generic:{SERVICE}/{name} /user:{SERVICE} /pass"
    if platform == "darwin":
        return f"security add-generic-password -s {SERVICE} -a {name} -w"
    return f'secret-tool store --label="{SERVICE} {name}" service {SERVICE} name {name}'


def write_password(tmpdir: Path, secret: str) -> Path:
    """`secret` into `tmpdir/PASSWORD_FILENAME`, for one invocation. The host deletes `tmpdir`."""
    tmpdir.mkdir(parents=True, exist_ok=True)
    path = tmpdir / PASSWORD_FILENAME
    path.write_bytes(secret.encode("utf-8"))
    return path
