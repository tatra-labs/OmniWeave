"""`[ingest] password_file`: which unit needs which secret, and the secret, for one run.

ADR-15 D15.3.

05:472: *"`[ingest] password_file` points at a TOML file mapping a `unit_uri` glob to a secret
*name*; the name resolves through the OS keystore, never through the file. `--password-file
<path>` overrides it for one invocation."* The file is one line per glob:

```toml
"contracts/**/*.pdf"            = "legal"      # relative to roots.source, as [ingest] include is
"e:/scans/payroll-2024.pdf"     = "payroll"    # or absolute: gate 9 prints this form
```

- **Relative globs** are `[ingest] include`'s: `acquire.matches_glob` against the path relative to
  the corpus's source root, so the two cannot disagree about a path.
- **Absolute globs** are matched against the whole `unit_uri`, which is the form gate 9's refusal
  prints (D15.5), so the line it prints can be pasted as it stands. On Windows a `unit_uri` is
  case-folded (`canonical_uri`'s `normcase`), and so is every glob.
- **The first line that matches wins**, as a reader of the file would expect from its order.
- **A name is looked up once per run** (`omniweave_core.host.keystore.resolve`: `OW_SECRET_<NAME>`,
  then the keystore) and kept in this process's memory for the run, never on disk and never in a
  row. The report names each name that resolved nowhere, and why, which is the one thing a user
  whose file did not open needs to be told.

A malformed file is a `ConfigError` naming the file and the entry, at startup: a password file
that silently mapped nothing would leave every encrypted file refused with no reason given.
"""

from __future__ import annotations

import sys
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final

from omniweave_core.acquire import matches_glob
from omniweave_core.errors import ConfigError
from omniweave_core.host import keystore
from omniweave_core.identity import canonical_uri

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

__all__ = ["ENCRYPTED", "Entry", "Passwords", "read_entries"]

ENCRYPTED: Final[str] = "encrypted"
"""The failure class a password can clear: `gate.encrypted`'s (05:1352)."""

_FIX: Final[str] = (
    'write one `"<glob>" = "<secret name>"` line per file, the glob relative to roots.source or '
    "absolute"
)


@dataclass(frozen=True, slots=True)
class Entry:
    """One line of the password file: a glob and the secret name it maps to."""

    glob: str
    name: str

    @property
    def absolute(self) -> bool:
        return PurePosixPath(self.glob).is_absolute() or PureWindowsPath(self.glob).is_absolute()


def read_entries(path: Path) -> tuple[Entry, ...]:
    """The password file's lines, in order. Raises `ConfigError` naming what is wrong and where."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as gone:
        raise ConfigError(
            f"the password file {path} is unreadable: {gone}",
            fix=f"create {path}, or point [ingest] password_file at the file that exists",
        ) from gone
    try:
        table = tomllib.loads(text)
    except tomllib.TOMLDecodeError as bad:
        raise ConfigError(f"the password file {path} is not TOML: {bad}", fix=_FIX) from bad
    entries: list[Entry] = []
    for glob, name in table.items():
        if not isinstance(name, str) or not keystore.NAME_RE.match(name):
            raise ConfigError(
                f"{path}: {glob!r} maps to {name!r}, which is not a secret name "
                f"({keystore.NAME_RE.pattern}); the file holds names, never passwords",
                fix=_FIX,
            )
        if not glob.strip():
            raise ConfigError(f"{path}: an empty glob maps to {name!r}", fix=_FIX)
        entries.append(Entry(glob=glob, name=name))
    return tuple(entries)


class Passwords:
    """One run's password mapping, and the secrets it has resolved so far. Thread-safe.

    `secret_for` is called by routing (the signal child's request) and by the parse Operator (the
    invocation's password file), which runs on the Supervisor's worker threads.
    """

    __slots__ = ("_entries", "_found", "_lock", "_resolve", "_root", "_source")

    def __init__(
        self,
        entries: Sequence[Entry],
        *,
        source_root: Path,
        env: Mapping[str, str],
        source: str = "",
        resolve: Callable[[str], keystore.Found] | None = None,
    ) -> None:
        self._entries = tuple(entries)
        self._root = _folded(canonical_uri(source_root))
        self._source = source
        self._resolve = resolve or (lambda name: keystore.resolve(name, env=env))
        self._found: dict[str, keystore.Found] = {}
        self._lock = threading.Lock()

    @classmethod
    def load(
        cls, path: Path | None, *, source_root: Path, env: Mapping[str, str]
    ) -> Passwords | None:
        """The mapping in `path`, or `None` when no password file is configured."""
        if path is None:
            return None
        return cls(read_entries(path), source_root=source_root, env=env, source=str(path))

    @property
    def source(self) -> str:
        """The file the mapping was read from, for the report."""
        return self._source

    def name_for(self, unit_uri: str) -> str | None:
        """The secret name the first matching line gives this unit, or `None`."""
        uri = _folded(unit_uri)
        relative = uri[len(self._root) + 1 :] if uri.startswith(self._root + "/") else None
        for entry in self._entries:
            glob = _folded(entry.glob.replace("\\", "/"))
            if entry.absolute:
                if matches_glob(uri, glob):
                    return entry.name
            elif relative is not None and matches_glob(relative, glob):
                return entry.name
        return None

    def secret_for(self, unit_uri: str) -> str | None:
        """This unit's password, resolved once per name per run, or `None`."""
        name = self.name_for(unit_uri)
        if name is None:
            return None
        with self._lock:
            found = self._found.get(name)
            if found is None:
                found = self._resolve(name)
                self._found[name] = found
        return found.secret

    def reopens(self, unit_uri: str, failure_class: str | None) -> bool:
        """Whether a failed unit is read again: an `encrypted` one a line maps to a name that
        resolves (D15.3). A name that resolves nowhere would refuse the file again, so it is not
        read again; the report says why the name did not resolve."""
        return failure_class == ENCRYPTED and self.secret_for(unit_uri) is not None

    def lines(self) -> tuple[str, ...]:
        """The report's password lines: each name looked up, where it came from, or why not.

        Never a secret. A name that resolved is shown with its source; one that did not, with the
        reason `keystore.resolve` gave, so a user can see a stale `OW_SECRET_*` or a missing entry.
        """
        with self._lock:
            found = dict(self._found)
        if not found:
            return ()
        resolved = sorted(name for name, one in found.items() if one.secret is not None)
        out = []
        if resolved:
            shown = ", ".join(f"{name} from {found[name].where}" for name in resolved)
            out.append(f"  password  {len(resolved)} resolved: {shown}")
        for name in sorted(name for name, one in found.items() if one.secret is None):
            out.append(
                f"  password  {name} not found: {found[name].where}; store it with "
                f"`{keystore.store_command(name)}`, or set {keystore.env_name(name)}"
            )
        return tuple(out)


def _folded(text: str) -> str:
    """`text` folded as `canonical_uri` folds a Windows path, so a glob meets the uri it names."""
    return text.lower() if sys.platform == "win32" else text
