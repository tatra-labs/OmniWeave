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
obvious one round-trips one of this machine's five host configs (D441). The receipt (10 section
7.3), the write modes, the hosts and the verbs come next.
"""

from __future__ import annotations

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
    "END",
    "HOOK_SETS",
    "LOCATIONS",
    "TARGET_IDS",
    "AgentTarget",
    "DetectionResult",
    "FileAction",
    "HookSet",
    "InstallOptions",
    "JsonStyle",
    "Location",
    "ReadJson",
    "Section",
    "SkillSet",
    "TargetId",
    "WriteResult",
    "Wrote",
    "atomic_write",
    "json_deep_equal",
    "read_json",
    "remove_marked_section",
    "render_json",
    "upsert_marked_section",
    "write_json",
]
