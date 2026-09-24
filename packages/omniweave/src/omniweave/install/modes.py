"""Four of 10:1665's five write modes, each as an install and its exact inverse.

`json-key` puts one value at a dotted key (the MCP entry, 10:1667), `json-array-add` adds values to
an array (the permission wildcard, 10:1668), and `marker-section` keeps one block in a Markdown file
(`CLAUDE.md`, 10:1669). Each install returns the `FileAction` 10:1645 reports and the receipt row
10:1739 appends right after the write; each uninstall takes that row back and says what it did.
`json-hook-rules` (10:1670) is here too, over `hookrules.py`'s parse and convergence; `dir` is the
skill bundle's.

## WHAT A ROW MUST CARRY ACROSS A RE-INSTALL

D449 made a re-install replace its row rather than append a second. That loses provenance unless the
new row inherits it. Install once into a `settings.json` with no `mcpServers`: the row says
`created_parents: ["mcpServers"]`. Install again: `mcpServers` exists now -- omniweave made it -- so
the second write creates nothing, and a row built from the second write alone says
`created_parents: []`. Uninstall then removes the key and leaves `"mcpServers": {}`. The same
happens to `created_file`, to `created_dirs`, and to an array's values: the second install finds
`mcp__omniweave__*` present and adds nothing. So every install takes the **previous** row, and
the new row is the union of what either write created or added. D454.

**And an array row records the values it added, not the values it wanted.** 10:1712's row is
`"values":["mcp__omniweave__*"]`, the mode's input. If the user's `settings.json` already granted
that value before the first install, a row recording the input makes uninstall revoke the user's
own grant. The row holds only values this install -- or an earlier one, carried forward -- put
there. D454.

## WHAT UNINSTALL REMOVES

10:1756: *"a `sha256` match removes exactly that key, section, array value or directory and reports
`removed`; a mismatch reports `kept -- modified since install`"*. With D448's two digests the
reading shipped is: `untouched` and `owned-untouched` remove, because both say omniweave's part is
as written; `modified` keeps. An array value has no content to modify -- it is present or it is not
-- so for `json-array-add` the ones still present are removed and the ones already gone are named.
What install created is removed only if it is empty afterwards: a container, the file (when it would
be left as `{}` or as nothing), the directories. **A missing row** falls back to re-derivation
(10:1758): the key, the values or the section are removed by name, and nothing the row would have
said was created is touched, because without the row nothing says it was. That keeps a lost receipt
from stranding a user and costs it the byte-identity. D455.

## NOTHING HERE READS BY WRITING

`--dry-run` prints *"plan (nothing written)"* (18:2974) and `print_config` *"MUST NOT touch the
filesystem"* (10:1641); an uninstall leaves an unparseable file alone. `read_json` backs up what it
cannot parse, and a backup is a write, so every read here that is not immediately followed by the
install's own write passes `back_up=False`. D453.
"""

from __future__ import annotations

import copy
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.canonical import sha256_canonical

from omniweave.install.hookrules import Converged, Desired, converge, owned_pairs, strip
from omniweave.install.primitives import (
    BEGIN,
    ReadJson,
    atomic_write,
    decode_text,
    encode_text,
    json_deep_equal,
    read_json,
    remove_empty_dirs,
    remove_marked_section,
    section_span,
    upsert_marked_section,
    write_json,
)
from omniweave.install.receipt import (
    Entry,
    expand,
    file_sha256,
    owned_key,
    owned_section,
    tildify,
    verdict,
    written_at,
)
from omniweave.install.types import FileAction

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from omniweave_core.clock import Clock

    from omniweave.install.types import Action, Kind, Location, Mode, TargetId

__all__ = [
    "Applied",
    "Site",
    "add_values",
    "remove_section",
    "remove_values",
    "set_hooks",
    "set_key",
    "unbuilt",
    "unset_hooks",
    "unset_key",
    "upsert_section",
]

_WINDOWS: Final = sys.platform == "win32"
_NOT_ROUND_TRIP: Final = (
    "this file does not re-render in its own style, so uninstall cannot restore it byte for byte "
    "(D441)"
)
_OTHER_CHANGES: Final = (
    "the rest of the file changed since install; only omniweave's part was removed"
)
_REDERIVED: Final = (
    "no receipt row: removed by re-derivation, and nothing it created is known (D455)"
)
_MODIFIED: Final = "kept -- modified since install"


@dataclass(frozen=True, slots=True)
class Site:
    """One file one target writes at one location: the facts every row needs.

    `path` is absolute; `shown` is how the row and the plan spell it -- tildified for a global row
    (10:1707, 18:2975), absolute for a local one (10:1725).
    """

    target: TargetId
    location: Location
    path: Path
    user_home: Path
    scope_root: str | None = None

    @property
    def shown(self) -> str:
        if self.location == "global":
            return tildify(self.path, self.user_home)
        return self.path.as_posix()

    def spell(self, path: Path) -> str:
        return tildify(path, self.user_home) if self.location == "global" else path.as_posix()

    def row(self, kind: Kind, mode: Mode, clock: Clock, **fields: Any) -> Entry:
        return Entry(
            target=self.target,
            location=self.location,
            scope_root=self.scope_root,
            written_at=written_at(clock.wall_ns()),
            kind=kind,
            path=self.shown,
            mode=mode,
            **fields,
        )

    def act(
        self, action: Action, kind: Kind, mode: Mode, note: str = "", **rest: str
    ) -> FileAction:
        return FileAction(path=self.shown, action=action, kind=kind, mode=mode, note=note, **rest)


@dataclass(frozen=True, slots=True)
class Applied:
    """What one mode did: the reported action, the row to record, and the row to forget.

    An install sets `record` when it wrote. An uninstall sets `forget` when the row's artefact is
    gone -- removed, or already absent -- and leaves it unset when the artefact was kept, so the
    row survives to say so next time.
    """

    action: FileAction
    record: Entry | None = None
    forget: Entry | None = None


def _union(first: Sequence[str], second: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*first, *second)))


def _notes(*parts: str) -> str:
    return "; ".join(part for part in parts if part)


# ---------------------------------------------------------------------------------------------
# JSON documents: descending to a container, and pruning what install created.
# ---------------------------------------------------------------------------------------------


def _descend(
    document: dict[str, Any], segments: Sequence[str]
) -> tuple[dict[str, Any], list[str]] | str:
    """The object at `segments`, creating missing ones; the dotted paths created, or a refusal."""
    node = document
    created: list[str] = []
    for depth, part in enumerate(segments):
        if part not in node:
            node[part] = {}
            created.append(".".join(segments[: depth + 1]))
        child = node[part]
        if not isinstance(child, dict):
            where = ".".join(segments[: depth + 1])
            return f"{where} is {type(child).__name__}, not an object; not writing into it"
        node = child
    return node, created


def _find(document: dict[str, Any], segments: Sequence[str]) -> dict[str, Any] | None:
    node: object = document
    for part in segments:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node if isinstance(node, dict) else None


def _prune(document: dict[str, Any], created: Sequence[str]) -> None:
    """Remove each created container that is now empty, deepest first."""
    for dotted_path in sorted(created, key=lambda one: one.count("."), reverse=True):
        *parents, last = dotted_path.split(".")
        holder = _find(document, parents)
        if holder is not None and last in holder and holder[last] in ({}, []):
            del holder[last]


def _read_for_uninstall(site: Site, pid: int) -> ReadJson | FileAction:
    """The document, or the `not-found`/`kept` action that ends the uninstall before it starts."""
    before = read_json(site.path, pid=pid, back_up=False)
    if before.state == "missing":
        return FileAction(path=site.shown, action="not-found", note="no file")
    if before.state != "parsed":
        return FileAction(path=site.shown, action="kept", note=before.reason or before.state)
    return before


def _finish_json(
    site: Site,
    kind: Kind,
    mode: Mode,
    *,
    document: dict[str, Any],
    before: ReadJson,
    entry: Entry | None,
    note: str,
    pid: int,
    dry_run: bool,
    sleep: Callable[[float], None],
) -> Applied:
    """Write the uninstalled document back -- or delete the file install created, if now empty."""
    if entry is not None and entry.created_file and json_deep_equal(document, {}):
        return _delete(site, kind, mode, entry, note=note, dry_run=dry_run)
    if dry_run:
        return Applied(site.act("removed", kind, mode, note), forget=entry)
    action, _, written = write_json(site.path, document, before, pid=pid, sleep=sleep)
    if action == "kept":
        return Applied(site.act("kept", kind, mode, _notes(written, note)))
    if not before.round_trips:
        note = _notes(note, _NOT_ROUND_TRIP)
    return Applied(site.act("removed", kind, mode, note), forget=entry)


def _delete(
    site: Site, kind: Kind, mode: Mode, entry: Entry, *, note: str, dry_run: bool
) -> Applied:
    """Unlink a file install created, then the directories it created. 10:1763's leftovers."""
    if dry_run:
        return Applied(site.act("removed", kind, mode, note), forget=entry)
    try:
        site.path.unlink(missing_ok=True)
    except OSError:
        later = " after this window closes" if _WINDOWS else ""
        leftover = f"Could not remove {site.shown} -- delete it manually{later}"
        return Applied(site.act("kept", kind, mode, _notes(leftover, note)))
    left = remove_empty_dirs([expand(one, site.user_home) for one in entry.created_dirs])
    for directory in left:
        note = _notes(note, f"Could not remove {site.spell(directory)} -- it is not empty")
    return Applied(site.act("removed", kind, mode, note), forget=entry)


def _dirs(site: Site, created: Sequence[Path]) -> tuple[str, ...]:
    return tuple(site.spell(one) for one in created)


# ---------------------------------------------------------------------------------------------
# json-key. 10:1667: `mcpServers.omniweave`.
# ---------------------------------------------------------------------------------------------


def set_key(
    site: Site,
    kind: Kind,
    key: str,
    value: Any,
    *,
    previous: Entry | None,
    clock: Clock,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Applied:
    """Put `value` at `key`. `previous` is this site's row from an earlier install, or `None`."""
    before = read_json(site.path, pid=pid, back_up=not dry_run)
    if before.state == "unreadable":
        return Applied(site.act("kept", kind, "json-key", before.reason))
    document = copy.deepcopy(before.value)
    *parents, last = key.split(".")
    found = _descend(document, parents)
    if isinstance(found, str):
        return Applied(site.act("kept", kind, "json-key", found))
    container, created = found
    container[last] = copy.deepcopy(value)
    if dry_run:
        return Applied(site.act(_would(before, document), kind, "json-key", before.reason))
    action, wrote, note = write_json(site.path, document, before, pid=pid, sleep=sleep)
    if action in {"unchanged", "kept"} or wrote is None:
        return Applied(site.act(action, kind, "json-key", note, code=before.code))
    fields = _provenance(site, previous, before, created, wrote.created_dirs)
    row = site.row(
        kind,
        "json-key",
        clock,
        key=key,
        sha256_after=wrote.sha256,
        owned_sha256=sha256_canonical(value),
        **fields,
    )
    return Applied(
        _reported(
            site, kind, "json-key", action=action, before=before, note=note, written=wrote.path
        ),
        record=row,
    )


def unset_key(
    site: Site,
    kind: Kind,
    key: str,
    *,
    entry: Entry | None,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Applied:
    """Remove the key `entry` recorded, or `key` by re-derivation when there is no row."""
    key = entry.key if entry is not None and entry.key else key
    before = _read_for_uninstall(site, pid)
    if isinstance(before, FileAction):
        return _ended(site, kind, "json-key", before, entry)
    document = copy.deepcopy(before.value)
    *parents, last = key.split(".")
    holder = _find(document, parents)
    if holder is None or last not in holder:
        return Applied(site.act("not-found", kind, "json-key", "not configured"), forget=entry)
    judged = _judge(site, entry, owned_key(document, key))
    if judged == "modified":
        return Applied(site.act("kept", kind, "json-key", _MODIFIED))
    del holder[last]
    if entry is not None:
        _prune(document, entry.created_parents)
    note = _REDERIVED if entry is None else (_OTHER_CHANGES if judged == "owned-untouched" else "")
    return _finish_json(
        site, kind, "json-key", document=document, before=before, entry=entry,
        note=note, pid=pid, dry_run=dry_run, sleep=sleep,
    )  # fmt: skip


# ---------------------------------------------------------------------------------------------
# json-array-add. 10:1668: `permissions.allow += mcp__omniweave__*`.
# ---------------------------------------------------------------------------------------------


def add_values(
    site: Site,
    kind: Kind,
    key: str,
    values: Sequence[str],
    *,
    previous: Entry | None,
    clock: Clock,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Applied:
    """Append each of `values` not already in the array at `key`, creating what is missing."""
    before = read_json(site.path, pid=pid, back_up=not dry_run)
    edited = _with_values(before, key, values)
    if isinstance(edited, str):
        return Applied(site.act("kept", kind, "json-array-add", edited))
    document, array, created, added = edited
    if dry_run:
        return Applied(site.act(_would(before, document), kind, "json-array-add", before.reason))
    action, wrote, note = write_json(site.path, document, before, pid=pid, sleep=sleep)
    if action == "unchanged" and previous is None:
        return Applied(
            site.act("unchanged", kind, "json-array-add", "already granted; recorded as not ours"),
            record=_nothing_added(site, kind, key, clock),
        )
    if action in {"unchanged", "kept"} or wrote is None:
        return Applied(site.act(action, kind, "json-array-add", note, code=before.code))
    kept_before = [one for one in (previous.values if previous else ()) if one in array]
    ours = _union(kept_before, added)
    fields = _provenance(site, previous, before, created, wrote.created_dirs)
    row = site.row(
        kind,
        "json-array-add",
        clock,
        key=key,
        values=ours,
        sha256_after=wrote.sha256,
        owned_sha256=sha256_canonical(list(ours)),
        **fields,
    )
    return Applied(
        _reported(
            site,
            kind,
            "json-array-add",
            action=action,
            before=before,
            note=note,
            written=wrote.path,
        ),
        record=row,
    )


def _with_values(
    before: ReadJson, key: str, values: Sequence[str]
) -> tuple[dict[str, Any], list[Any], list[str], list[str]] | str:
    """`(document, array, created, added)` with `values` appended at `key`, or why not."""
    if before.state == "unreadable":
        return before.reason
    document = copy.deepcopy(before.value)
    *parents, last = key.split(".")
    found = _descend(document, parents)
    if isinstance(found, str):
        return found
    container, created = found
    if last not in container:
        container[last] = []
        created.append(key)
    array = container[last]
    if not isinstance(array, list):
        return f"{key} is {type(array).__name__}, not an array; not writing into it"
    added = [value for value in dict.fromkeys(values) if value not in array]
    array.extend(added)
    return document, array, created, added


def _nothing_added(site: Site, kind: Kind, key: str, clock: Clock) -> Entry:
    """A row that says this install added no value: every one was already there. D454.

    Without it there is no row, and a re-derived uninstall (D455) removes the user's own grant.
    """
    return site.row(
        kind,
        "json-array-add",
        clock,
        key=key,
        values=(),
        sha256_after=file_sha256(site.path) or "",
        owned_sha256=sha256_canonical([]),
    )


def remove_values(
    site: Site,
    kind: Kind,
    key: str,
    values: Sequence[str],
    *,
    entry: Entry | None,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Applied:
    """Remove the values `entry` recorded -- the ones install added -- or `values` with no row."""
    if entry is not None:
        #  A row read back from a receipt 10:1712's way names no array; the caller's key does. D462.
        key, values = entry.key or key, entry.values
    before = _read_for_uninstall(site, pid)
    if isinstance(before, FileAction):
        return _ended(site, kind, "json-array-add", before, entry)
    document = copy.deepcopy(before.value)
    *parents, last = key.split(".")
    holder = _find(document, parents)
    array = holder.get(last) if holder is not None else None
    if entry is not None and not entry.values:
        note = "install added nothing here; the values were already the user's"
        return Applied(site.act("not-found", kind, "json-array-add", note), forget=entry)
    present = [value for value in values if isinstance(array, list) and value in array]
    if not present or not isinstance(array, list):
        return Applied(
            site.act("not-found", kind, "json-array-add", "not configured"), forget=entry
        )
    for value in present:
        array.remove(value)
    gone = [value for value in values if value not in present]
    note = _notes(
        _REDERIVED if entry is None else "",
        f"already removed: {', '.join(gone)}" if gone else "",
    )
    if entry is not None:
        _prune(document, entry.created_parents)
    return _finish_json(
        site, kind, "json-array-add", document=document, before=before, entry=entry,
        note=note, pid=pid, dry_run=dry_run, sleep=sleep,
    )  # fmt: skip


# ---------------------------------------------------------------------------------------------
# json-hook-rules. 10:1670, 10:1683-1698: the rules themselves are `hookrules.py`'s.
# ---------------------------------------------------------------------------------------------


def set_hooks(
    site: Site,
    wanted: Sequence[Desired],
    *,
    previous: Entry | None,
    clock: Clock,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Applied:
    """Converge the file's hook rules to `wanted`. An empty `wanted` is `--hooks none`: ours go."""
    before = read_json(site.path, pid=pid, back_up=not dry_run)
    document = copy.deepcopy(before.value)
    result = converge(document, wanted)
    if not wanted and previous is not None:
        #  The row is forgotten below, and with it what it created: prune that now. D463.
        _prune(document, previous.created_parents)
    refusal = before.reason if before.state == "unreadable" else result.refusal
    if refusal:
        return Applied(site.act("kept", "hooks", "json-hook-rules", refusal))
    note = _hook_note(result)
    if dry_run:
        return Applied(site.act(_would(before, document), "hooks", "json-hook-rules", note))
    action, wrote, written = write_json(site.path, document, before, pid=pid, sleep=sleep)
    if action == "kept":
        return Applied(site.act("kept", "hooks", "json-hook-rules", _notes(written, note)))
    if not wanted:
        gone: Action = "removed" if result.pruned else "unchanged"
        return Applied(site.act(gone, "hooks", "json-hook-rules", note), forget=previous)
    if action == "unchanged" or wrote is None:
        return Applied(site.act("unchanged", "hooks", "json-hook-rules", note))
    fields = _provenance(site, previous, before, result.created, wrote.created_dirs)
    row = site.row(
        "hooks",
        "json-hook-rules",
        clock,
        events=tuple(one.event for one in wanted),
        sha256_after=wrote.sha256,
        owned_sha256=sha256_canonical(owned_pairs(document)),
        **fields,
    )
    reported = _reported(
        site, "hooks", "json-hook-rules",
        action=action, before=before, note=_notes(written, note), written=wrote.path,
    )  # fmt: skip
    return Applied(reported, record=row)


def unset_hooks(
    site: Site,
    *,
    entry: Entry | None,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
) -> Applied:
    """Remove every hook of ours, by 10:1690's ownership parse, from every event in the file."""
    before = _read_for_uninstall(site, pid)
    if isinstance(before, FileAction):
        return _ended(site, "hooks", "json-hook-rules", before, entry)
    document = copy.deepcopy(before.value)
    pairs = owned_pairs(document)
    if not pairs:
        return Applied(
            site.act("not-found", "hooks", "json-hook-rules", "not configured"), forget=entry
        )
    judged = _judge(site, entry, sha256_canonical(pairs))
    if judged == "modified":
        return Applied(site.act("kept", "hooks", "json-hook-rules", _MODIFIED))
    strip(document, drop_emptied=entry is None)
    if entry is not None:
        _prune(document, entry.created_parents)
    note = _REDERIVED if entry is None else (_OTHER_CHANGES if judged == "owned-untouched" else "")
    return _finish_json(
        site, "hooks", "json-hook-rules", document=document, before=before, entry=entry,
        note=note, pid=pid, dry_run=dry_run, sleep=sleep,
    )  # fmt: skip


def _hook_note(result: Converged) -> str:
    parts = (
        ("converged", result.converged),
        ("pruned", result.pruned),
        ("matcher converged", result.matchers),
    )
    return "; ".join(
        f"{label} {' '.join(dict.fromkeys(events))}" for label, events in parts if events
    )


# ---------------------------------------------------------------------------------------------
# marker-section. 10:1669: `CLAUDE.md`.
# ---------------------------------------------------------------------------------------------


def _read_text(path: Path) -> tuple[str, bool, bool] | str:
    """`(text, bom, existed)`, or why the file cannot be edited as text."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return "", False, False
    except OSError as error:
        return f"{path}: {type(error).__name__}"
    try:
        text, bom = decode_text(raw)
    except UnicodeDecodeError:
        return f"{path} is not UTF-8; not editing it"
    return text, bom, True


def upsert_section(
    site: Site,
    kind: Kind,
    body: str,
    *,
    previous: Entry | None,
    clock: Clock,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    head: str = "",
) -> Applied:
    """Insert or replace omniweave's block in a Markdown file, creating the file if need be.

    `head` is what a file this creates starts with, before the block: a Cursor rule is read only
    if its frontmatter opens the file, and the block's first line is a comment (D477). A file that
    exists is never given one -- its first lines are the user's.
    """
    read = _read_text(site.path)
    if isinstance(read, str):
        return Applied(site.act("kept", kind, "marker-section", read))
    text, bom, existed = read
    section = upsert_marked_section(text if existed else head, body)
    if section.text is None:
        return Applied(site.act("kept", kind, "marker-section", section.reason))
    if section.action == "unchanged":
        return Applied(site.act("unchanged", kind, "marker-section"))
    action: Action = "updated" if existed else "created"
    if dry_run:
        return Applied(site.act(action, kind, "marker-section"))
    wrote = atomic_write(site.path, encode_text(section.text, bom=bom), pid=pid, sleep=sleep)
    if not wrote.ok:
        return Applied(site.act("kept", kind, "marker-section", wrote.reason))
    created_file = not existed or bool(previous and previous.created_file)
    dirs = _union(previous.created_dirs if previous else (), _dirs(site, wrote.created_dirs))
    row = site.row(
        kind,
        "marker-section",
        clock,
        marker=BEGIN,
        sha256_after=wrote.sha256,
        owned_sha256=owned_section(section.text) or "",
        created_file=created_file,
        created_dirs=dirs,
    )
    written = str(wrote.path) if wrote.path != site.path else ""
    return Applied(site.act(action, kind, "marker-section", written=written), record=row)


def remove_section(
    site: Site,
    kind: Kind,
    *,
    entry: Entry | None,
    pid: int,
    dry_run: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    head: str = "",
) -> Applied:
    """Remove omniweave's block, and the file too when install created it and nothing is left.

    *Nothing* includes the `head` install created the file with (D477): what is left is then
    only what omniweave wrote. A head the user edited is theirs, and the file stays.
    """
    planned = _section_removal(site, kind, entry)
    if isinstance(planned, Applied):
        return planned
    text, bom, note = planned
    left = text.strip()
    if entry is not None and entry.created_file and (not left or left == head.strip()):
        return _delete(site, kind, "marker-section", entry, note=note, dry_run=dry_run)
    if dry_run:
        return Applied(site.act("removed", kind, "marker-section", note), forget=entry)
    wrote = atomic_write(site.path, encode_text(text, bom=bom), pid=pid, sleep=sleep)
    if not wrote.ok:
        return Applied(site.act("kept", kind, "marker-section", _notes(wrote.reason, note)))
    return Applied(site.act("removed", kind, "marker-section", note), forget=entry)


def _section_removal(
    site: Site, kind: Kind, entry: Entry | None
) -> tuple[str, bool, str] | Applied:
    """The text without the block, its BOM and a note -- or the action that ends it early."""
    read = _read_text(site.path)
    if isinstance(read, str):
        return Applied(site.act("kept", kind, "marker-section", read))
    text, bom, existed = read
    if not existed or section_span(text) is None:
        why = "no file" if not existed else "not configured"
        return Applied(site.act("not-found", kind, "marker-section", why), forget=entry)
    judged = _judge(site, entry, owned_section(text))
    if judged == "modified":
        return Applied(site.act("kept", kind, "marker-section", _MODIFIED))
    section = remove_marked_section(text)
    if section.text is None:
        return Applied(site.act("kept", kind, "marker-section", section.reason))
    note = _REDERIVED if entry is None else (_OTHER_CHANGES if judged == "owned-untouched" else "")
    return section.text, bom, note


# ---------------------------------------------------------------------------------------------
# Shared.
# ---------------------------------------------------------------------------------------------


def _would(before: ReadJson, document: dict[str, Any]) -> Action:
    if before.state == "missing":
        return "created"
    if before.state == "parsed" and json_deep_equal(before.value, document):
        return "unchanged"
    return "updated"


def _provenance(
    site: Site,
    previous: Entry | None,
    before: ReadJson,
    created: Sequence[str],
    dirs: Sequence[Path],
) -> dict[str, Any]:
    """What this write created, unioned with what `previous` said an earlier one did. D454."""
    return {
        "created_file": before.state == "missing" or bool(previous and previous.created_file),
        "created_parents": _union(previous.created_parents if previous else (), created),
        "created_dirs": _union(previous.created_dirs if previous else (), _dirs(site, dirs)),
    }


def _reported(
    site: Site,
    kind: Kind,
    mode: Mode,
    *,
    action: Action,
    before: ReadJson,
    note: str,
    written: Path,
) -> FileAction:
    extra = _NOT_ROUND_TRIP if before.state == "parsed" and not before.round_trips else ""
    return site.act(
        action,
        kind,
        mode,
        _notes(note, extra),
        code=before.code,
        written=str(written) if written != site.path else "",
    )


def _judge(site: Site, entry: Entry | None, owned_now: str | None) -> str:
    """The row's verdict against the file now, or `rederived` when there is no row."""
    if entry is None:
        return "rederived"
    current = file_sha256(site.path)
    return verdict(entry, exists=current is not None, current_sha256=current, owned_now=owned_now)


def _ended(site: Site, kind: Kind, mode: Mode, action: FileAction, entry: Entry | None) -> Applied:
    reported = site.act(action.action, kind, mode, action.note)
    return Applied(reported, forget=entry if action.action == "not-found" else None)


def unbuilt() -> tuple[str, ...]:
    """What 10:1665's table leaves open here. `dir` (10:1671) is `skilldir.py`'s."""
    return (
        "what install does with a file that will not round-trip (D441) or would not parse (D443). "
        "It writes, as the plan's text does, and the action's note says what that costs",
    )
