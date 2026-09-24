"""`ow install | uninstall | --check`: wire an agent host to omniweave, and take it back exactly.

02-architecture.md row 39 gives this package *"MCP config, permissions, instructions, hooks and the
core skill"* and forbids it one thing: *"deciding what a host permits"*. 10-interfaces.md section 7
is its specification and 16:719 its work item, whose closing clause is the claim to keep true --
*"a new host is one file and one registry row"*.

`types.py` is the vocabulary: 10:1630's `AgentTarget` verbatim, and the five types it names that
no document defines, each defined from where it is used. `primitives.py` is four of 10:1648's five
shared write primitives -- `atomic_write`, `json_deep_equal`, the backing-up `read_json`, and the
marked-section pair -- and the measurement that decided what they had to be: the byte-identity
reversal gate (10:1775) is a claim about a JSON serialiser the plan never specifies, and the
obvious one round-trips one of this machine's five host configs (D441). `receipt.py` is 10
section 7.3's receipt and the lock it is written under: rows with two digests, because a whole-file
hash goes stale the moment a second row's write or the host itself touches the file (D448), and
the house lock, because an age cannot tell a dead holder from one waiting at its own prompt (D450).
`modes.py` is three of 10:1665's five write modes -- `json-key`, `json-array-add`,
`marker-section` -- each an install and its inverse, with a row that inherits what an earlier
install created (D454), and the fourth, `json-hook-rules`, whose command, five spellings of
ownership and convergence are `hookrules.py`'s (D456-D457). `engine.py` is what makes a host one
file: the lock, a row recorded after each write, and an uninstall that undoes in reverse step order
with each file's creator flag merged, then sweeps the directories once (D459). `claude_code.py` is
the first host and `registry.py` its row. `skilldir.py` is the fifth mode, `dir`: a bundle staged,
verified against its `sha256-bundle-1` digest (`omniweave.skills.hash`, D464) and renamed into
place, and removed only on its row's digest. `verbs.py` is `ow install | uninstall | --check` as
functions returning an exit code and lines: `--target`'s four resolutions, the plan printed first,
0 and 9, uninstall's seven steps and `refresh_targets()`. The `ow` command that parses into them
waits for their `ACTIONS` rows (D467).
"""

from __future__ import annotations

from omniweave.install.engine import HostEnv, Step
from omniweave.install.primitives import (
    BEGIN,
    END,
    JsonStyle,
    ReadJson,
    Section,
    Wrote,
    atomic_write,
    json_deep_equal,
    read_json,
    remove_marked_section,
    render_json,
    upsert_marked_section,
    write_json,
)
from omniweave.install.receipt import (
    Entry,
    Receipt,
    forget,
    load,
    record,
    take_lock,
    verdict,
)
from omniweave.install.registry import BUILT, TARGETS, build
from omniweave.install.types import (
    ACTIONS,
    HOOK_SETS,
    LOCATIONS,
    TARGET_IDS,
    AgentTarget,
    DetectionResult,
    FileAction,
    HookSet,
    InstallOptions,
    Location,
    SkillSet,
    TargetId,
    WriteResult,
)

__all__ = [
    "ACTIONS",
    "BEGIN",
    "BUILT",
    "END",
    "HOOK_SETS",
    "LOCATIONS",
    "TARGETS",
    "TARGET_IDS",
    "AgentTarget",
    "DetectionResult",
    "Entry",
    "FileAction",
    "HookSet",
    "HostEnv",
    "InstallOptions",
    "JsonStyle",
    "Location",
    "ReadJson",
    "Receipt",
    "Section",
    "SkillSet",
    "Step",
    "TargetId",
    "WriteResult",
    "Wrote",
    "atomic_write",
    "build",
    "forget",
    "json_deep_equal",
    "load",
    "read_json",
    "record",
    "remove_marked_section",
    "render_json",
    "take_lock",
    "upsert_marked_section",
    "verdict",
    "write_json",
]
