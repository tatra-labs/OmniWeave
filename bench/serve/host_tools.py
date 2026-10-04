"""The host tools both arms get: `Read`, `Grep` and a read-only `Bash` (ADR-14 D14.3).

Emulated in-process, rooted at the corpus directory: read-only, no network and no real shell.
The names are the ones `serve_harness` counts (`HOST_READ`, `HOST_GREP`, `HOST_SHELL`, D601),
because Claude Code is the first `AgentTarget`, and the behaviour follows that host where it
matters to the measurement:

* **`Read`** returns at most 2,000 numbered lines per call, with `offset` and `limit`.
* **Converters, the best available per format and the same for both arms.** A PDF is its text
  layer per page via pypdfium2, the engine `parse.pdf.pdfium` uses. A page with no text layer
  comes back as its page image, as a host's `Read` renders a PDF page. DOCX, XLSX and PPTX are
  anydoc's markdown, the engine `parse.office.anydoc` uses. So the control arm converts with what
  omniweave itself trusts, and cannot be the straw man RK-Q4 warns about (17:966-972).
* **`Bash`** runs only the readers in `SHELL_READERS`, plus `ls`, `find` and `wc`, which list and
  count but do not read. A pipe, redirect or substitution is refused. A reader sees the raw
  bytes, as a real `cat` of a PDF would.

Every path is confined to the root. A call records the paths it touched as absolute POSIX paths,
because that is how `serve_harness.reads_source` compares them with the receipt.
"""

from __future__ import annotations

import base64
import fnmatch
import io
import re
import shlex
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from models import Image, ToolResult, ToolSpec, ToolUse
from serve_harness import HOST_GREP, HOST_READ, HOST_SHELL, SHELL_READERS, ToolCall

__all__ = ["BASH_COMMANDS", "READ_WINDOW", "HostTools", "Invocation"]

READ_WINDOW: Final[int] = 2_000
LINE_CAP: Final[int] = 2_000
GREP_CAP: Final[int] = 250
BASH_OUTPUT_CAP: Final[int] = 30_000
IMAGES_PER_READ: Final[int] = 4
IMAGE_WIDTH: Final[int] = 1_000

OFFICE: Final[Mapping[str, str]] = {
    ".docx": "docx",
    ".doc": "doc",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".ppt": "ppt",
    ".odt": "odt",
    ".ods": "ods",
    ".odp": "odp",
    ".rtf": "rtf",
    ".epub": "epub",
}
TEXT: Final[frozenset[str]] = frozenset(
    {".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".eml", ".log", ".toml", ".yaml"}
)
BASH_COMMANDS: Final[frozenset[str]] = frozenset(
    {"cat", "head", "tail", "grep", "rg", "ls", "find", "wc"}
)
"""What `Bash` runs: the `SHELL_READERS` implemented here, plus three that list or count."""

_SHELL_META: Final = re.compile(r"[|&;<>`$(){}]")


@dataclass(frozen=True, slots=True)
class Invocation:
    """One executed host call: what the model gets back, and what the transcript records."""

    result: ToolResult
    call: ToolCall


@dataclass(frozen=True, slots=True)
class _Converted:
    lines: tuple[str, ...]
    images: Mapping[int, Image] = field(default_factory=dict)
    """0-based line index of a page marker -> that page's image, for pages with no text layer."""


class HostTools:
    """The three host tools over one corpus root. Conversions are cached per file."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._cache: dict[Path, _Converted] = {}

    # -- the schemas the model sees ------------------------------------------------------------

    def specs(self) -> tuple[ToolSpec, ...]:
        return (
            ToolSpec(
                HOST_READ,
                "Read a file under the documents folder. Returns numbered lines (at most 2000 per "
                "call; use offset and limit for more). PDFs are text per page; a page with no text "
                "layer is returned as an image. Office documents are converted to markdown.",
                {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "absolute or folder-relative path",
                        },
                        "offset": {"type": "integer", "description": "1-based first line"},
                        "limit": {"type": "integer", "description": "lines to return"},
                    },
                    "required": ["file_path"],
                },
            ),
            ToolSpec(
                HOST_GREP,
                "Search file contents with a regular expression under a path in the documents "
                "folder. output_mode is files_with_matches (default) or content.",
                {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {
                            "type": "string",
                            "description": "file or directory; default the folder",
                        },
                        "glob": {"type": "string", "description": "filename filter, e.g. *.pdf"},
                        "case_insensitive": {"type": "boolean"},
                        "output_mode": {
                            "type": "string",
                            "enum": ["files_with_matches", "content"],
                        },
                    },
                    "required": ["pattern"],
                },
            ),
            ToolSpec(
                HOST_SHELL,
                "Run a read-only shell command in the documents folder: "
                + ", ".join(sorted(BASH_COMMANDS))
                + ". No pipes, redirects or substitutions.",
                {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            ),
        )

    # -- dispatch ------------------------------------------------------------------------------

    def call(self, use: ToolUse) -> Invocation:
        """Execute one host call. Never raises: a refusal is an error result the model reads."""
        handler = {HOST_READ: self._read, HOST_GREP: self._grep, HOST_SHELL: self._bash}.get(
            use.name
        )
        if handler is None:
            return self._error(use, f"unknown tool {use.name}", {})
        try:
            return handler(use)
        except _RefusedError as exc:
            return self._error(use, str(exc), exc.recorded)

    def _error(self, use: ToolUse, text: str, recorded: Mapping[str, str]) -> Invocation:
        return Invocation(
            ToolResult(use.id, text, is_error=True), ToolCall(use.name, dict(recorded))
        )

    # -- paths ---------------------------------------------------------------------------------

    def _resolve(self, raw: object, *, default_root: bool = False) -> Path:
        text = str(raw or "")
        if not text:
            if default_root:
                return self.root
            raise _RefusedError("a path is required")
        path = Path(text)
        path = (path if path.is_absolute() else self.root / path).resolve()
        if path != self.root and not path.is_relative_to(self.root):
            raise _RefusedError(f"{text} is outside the documents folder {self.root.as_posix()}")
        return path

    # -- Read ----------------------------------------------------------------------------------

    def _read(self, use: ToolUse) -> Invocation:
        path = self._resolve(use.arguments.get("file_path"))
        recorded = {"file_path": path.as_posix()}
        if not path.is_file():
            raise _RefusedError(f"{path.as_posix()} is not a file", recorded)
        converted = self._convert(path)
        offset = max(1, _int(use.arguments.get("offset"), 1))
        limit = max(1, min(READ_WINDOW, _int(use.arguments.get("limit"), READ_WINDOW)))
        start, stop = offset - 1, min(len(converted.lines), offset - 1 + limit)
        shown = [
            f"{number:6}\t{line[:LINE_CAP]}"
            for number, line in enumerate(converted.lines[start:stop], start=offset)
        ]
        images = tuple(
            image for index, image in sorted(converted.images.items()) if start <= index < stop
        )[:IMAGES_PER_READ]
        text = "\n".join(shown) if shown else "(no lines in that range)"
        if stop < len(converted.lines):
            text += (
                f"\n... {len(converted.lines) - stop} more lines; read on with offset={stop + 1}"
            )
        return Invocation(ToolResult(use.id, text, images=images), ToolCall(HOST_READ, recorded))

    def _convert(self, path: Path) -> _Converted:
        cached = self._cache.get(path)
        if cached is None:
            cached = self._cache[path] = _convert(path)
        return cached

    # -- Grep ----------------------------------------------------------------------------------

    def _grep(self, use: ToolUse) -> Invocation:
        base = self._resolve(use.arguments.get("path"), default_root=True)
        recorded = {"path": base.as_posix(), "pattern": str(use.arguments.get("pattern", ""))}
        flags = re.IGNORECASE if use.arguments.get("case_insensitive") else 0
        try:
            pattern = re.compile(str(use.arguments.get("pattern", "")), flags)
        except re.error as exc:
            raise _RefusedError(f"bad pattern: {exc}", recorded) from exc
        glob = str(use.arguments.get("glob") or "")
        content = use.arguments.get("output_mode") == "content"
        out: list[str] = []
        for path in self._files(base):
            if glob and not fnmatch.fnmatch(path.name, glob):
                continue
            hits = [
                (number, line)
                for number, line in enumerate(self._convert(path).lines, start=1)
                if pattern.search(line)
            ]
            if not hits:
                continue
            if content:
                out.extend(f"{path.as_posix()}:{n}:{line[:LINE_CAP]}" for n, line in hits)
            else:
                out.append(path.as_posix())
            if len(out) >= GREP_CAP:
                break
        text = "\n".join(out[:GREP_CAP]) if out else "No matches found"
        if len(out) > GREP_CAP:
            text += f"\n... truncated at {GREP_CAP}"
        return Invocation(ToolResult(use.id, text), ToolCall(HOST_GREP, recorded))

    def _files(self, base: Path) -> Iterator[Path]:
        if base.is_file():
            yield base
            return
        yield from sorted(p for p in base.rglob("*") if p.is_file())

    # -- Bash ----------------------------------------------------------------------------------

    def _bash(self, use: ToolUse) -> Invocation:
        command = str(use.arguments.get("command", ""))
        if _SHELL_META.search(command):
            raise _RefusedError(
                "pipes, redirects, substitutions and command lists are not available; run one "
                "command",
                {"command": command},
            )
        try:
            words = shlex.split(command, posix=True)
        except ValueError as exc:
            raise _RefusedError(f"cannot parse the command: {exc}", {"command": command}) from exc
        if not words:
            raise _RefusedError("an empty command", {"command": command})
        name = words[0]
        if name not in BASH_COMMANDS:
            raise _RefusedError(
                f"{name}: not available here; available: {', '.join(sorted(BASH_COMMANDS))}",
                {"command": command},
            )
        # Every word naming a path under the root is recorded absolute, so `reads_source` sees it.
        spelled = [name]
        for word in words[1:]:
            candidate = (self.root / word) if not Path(word).is_absolute() else Path(word)
            if not word.startswith("-") and candidate.exists():
                spelled.append(self._resolve(word).as_posix())
            else:
                spelled.append(word)
        recorded = {"command": " ".join(shlex.quote(word) for word in spelled)}
        output = self._capped(_run(name, spelled[1:], self))
        return Invocation(ToolResult(use.id, output), ToolCall(HOST_SHELL, recorded))

    def _capped(self, output: str) -> str:
        """`output` cut at `BASH_OUTPUT_CAP`, counting each spelling of the root as one character.
        **D653.**

        The emulated shell prints absolute paths, so a raw count cut a long listing at a line that
        depended on how long the machine's corpus folder is: the recording machine's 130-character
        scratch path left 140 lines, a Linux runner's 20-character one about 145, and every
        conversation that listed the corpus replayed as a miss. Counted this way the cut falls on
        the same character of the same line on any machine.
        """
        root = self.root.as_posix()
        neutral = output.replace(root, _ROOT_MARK)
        if len(neutral) <= BASH_OUTPUT_CAP:
            return output
        kept = neutral[:BASH_OUTPUT_CAP].replace(_ROOT_MARK, root)
        return kept + f"\n... output truncated at {BASH_OUTPUT_CAP} characters"


_ROOT_MARK: Final[str] = "\x00"
"""The one character the root counts as in `_capped`: never in a path, never in converted text."""


class _RefusedError(Exception):
    def __init__(self, message: str, recorded: Mapping[str, str] | None = None) -> None:
        super().__init__(message)
        self.recorded = dict(recorded or {})


def _int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default


# =============================================================================================
# Converters
# =============================================================================================


def _convert(path: Path) -> _Converted:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _pdf(path)
    if suffix in OFFICE:
        return _office(path, OFFICE[suffix])
    if suffix in TEXT:
        return _Converted(tuple(path.read_text(encoding="utf-8", errors="replace").splitlines()))
    raise _RefusedError(
        f"{path.as_posix()} is a binary file with no converter ({suffix or 'no suffix'})"
    )


def _pdf(path: Path) -> _Converted:
    import pypdfium2  # noqa: PLC0415 -- only a PDF read pays for the import

    lines: list[str] = []
    images: dict[int, Image] = {}
    try:
        document = pypdfium2.PdfDocument(str(path))
    except pypdfium2.PdfiumError as exc:
        raise _RefusedError(f"{path.as_posix()} could not be opened as a PDF: {exc}") from exc
    try:
        for number, page in enumerate(document, start=1):
            text = page.get_textpage().get_text_range().replace("\r\n", "\n").strip()
            if text:
                lines.append(f"--- page {number} ---")
                lines.extend(text.split("\n"))
            else:
                images[len(lines)] = _render(page)
                lines.append(f"--- page {number}: no text layer; returned as an image ---")
    finally:
        document.close()
    return _Converted(tuple(lines), images)


def _render(page: Any) -> Image:
    width = page.get_width() or IMAGE_WIDTH
    picture = page.render(scale=min(2.0, IMAGE_WIDTH / width)).to_pil()
    buffer = io.BytesIO()
    picture.save(buffer, format="PNG")
    return Image("image/png", base64.b64encode(buffer.getvalue()).decode("ascii"))


def _office(path: Path, fmt: str) -> _Converted:
    import anydoc  # noqa: PLC0415 -- only an office read pays for the import

    try:
        markdown = anydoc.to_markdown_bytes(path.read_bytes(), cast("anydoc.Format", fmt))
    except (anydoc.ConvertError, ValueError) as exc:
        raise _RefusedError(f"{path.as_posix()} could not be converted: {exc}") from exc
    return _Converted(tuple(markdown.splitlines()))


# =============================================================================================
# The Bash readers
# =============================================================================================


def _run(name: str, args: list[str], tools: HostTools) -> str:
    try:
        if name in {"cat", "head", "tail"}:
            return _cat(name, args, tools)
        if name in {"grep", "rg"}:
            return _shell_grep(args, tools)
        if name == "wc":
            return _wc(args, tools)
        return _list(name, args, tools)
    except _RefusedError as exc:
        return f"{name}: {exc}"


def _raw(path_text: str, tools: HostTools) -> str:
    path = tools._resolve(path_text)
    if not path.is_file():
        raise _RefusedError(f"{path_text}: No such file")
    return path.read_bytes().decode("utf-8", errors="replace")


def _count(args: list[str]) -> tuple[int, list[str]]:
    count, rest, it = 10, [], iter(args)
    for word in it:
        if word == "-n":
            count = _int(next(it, "10"), 10)
        elif re.fullmatch(r"-\d+", word):
            count = int(word[1:])
        else:
            rest.append(word)
    return count, rest


def _cat(name: str, args: list[str], tools: HostTools) -> str:
    count, paths = (
        _count(args) if name != "cat" else (0, [a for a in args if not a.startswith("-")])
    )
    if not paths:
        raise _RefusedError("a file operand is required")
    out: list[str] = []
    for one in paths:
        lines = _raw(one, tools).splitlines()
        out.extend(lines if name == "cat" else lines[:count] if name == "head" else lines[-count:])
    return "\n".join(out)


def _shell_grep(args: list[str], tools: HostTools) -> str:
    flags, list_only, number, rest = 0, False, False, []
    for word in args:
        if word.startswith("-") and len(word) > 1 and not rest:
            flags |= re.IGNORECASE if "i" in word else 0
            list_only = list_only or "l" in word
            number = number or "n" in word
        else:
            rest.append(word)
    if not rest:
        raise _RefusedError("a pattern is required")
    pattern, paths = rest[0], rest[1:] or [tools.root.as_posix()]
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise _RefusedError(f"bad pattern: {exc}") from exc
    out: list[str] = []
    for one in paths:
        for path in tools._files(tools._resolve(one)):
            text = path.read_bytes().decode("utf-8", errors="replace").splitlines()
            hits = [(n, line) for n, line in enumerate(text, start=1) if compiled.search(line)]
            if list_only and hits:
                out.append(path.as_posix())
            else:
                out.extend(
                    f"{path.as_posix()}:{f'{n}:' if number else ''}{line}" for n, line in hits
                )
    return "\n".join(out)


def _wc(args: list[str], tools: HostTools) -> str:
    paths = [a for a in args if not a.startswith("-")]
    rows = []
    for one in paths:
        text = _raw(one, tools)
        rows.append(f"{len(text.splitlines()):8} {len(text.split()):8} {len(text):8} {one}")
    return "\n".join(rows)


def _list(name: str, args: list[str], tools: HostTools) -> str:
    if name == "find":
        start = args[0] if args and not args[0].startswith("-") else tools.root.as_posix()
        base = tools._resolve(start)
        pattern = args[args.index("-name") + 1] if "-name" in args[:-1] else "*"
        return "\n".join(
            p.as_posix() for p in sorted(base.rglob("*")) if fnmatch.fnmatch(p.name, pattern)
        )
    targets = [a for a in args if not a.startswith("-")] or [tools.root.as_posix()]
    recursive = any(a.startswith("-") and "R" in a for a in args)
    out: list[str] = []
    for one in targets:
        base = tools._resolve(one)
        entries = (
            sorted(base.rglob("*") if recursive else base.iterdir()) if base.is_dir() else [base]
        )
        out.extend(
            (p.relative_to(base).as_posix() if base.is_dir() else p.name)
            + ("/" if p.is_dir() else "")
            for p in entries
        )
    return "\n".join(out)


assert {"cat", "head", "tail", "grep", "rg"} <= SHELL_READERS  # noqa: S101 -- the counted set covers ours
