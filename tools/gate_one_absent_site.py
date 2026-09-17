"""P6's exit criterion: exactly one `return VerdictState.ABSENT` site in the framework.

16-roadmap.md:693 names this script by path in P6's exit block -- `uv run
tools/gate_one_absent_site.py  # semgrep: exactly one ABSENT return` -- so the criterion is a
COMMAND, and a command that cannot be run is not a criterion. This file is that command.

## It re-implements nothing

The property already has one implementation and this file does not add a second. SV8 is enforced in
two halves that `tools/gate_semgrep.py` owns:

* the bank's `omniweave-one-verdict-absent-site` confines the return to
  `omniweave_core/retrieve/verdict.py`, which is all a pattern matcher can say -- its own message
  records the limit, that semgrep cannot count occurrences so the rule enforces the single
  file;
* `gate_semgrep.ast_findings()` adds the count, rejecting a second site even INSIDE that file.

This script calls the second and reports only SV8's findings. INV-21 allows a fact one home, and a
runner that imports is not a home -- a runner that re-walked the tree would be, and would be the
defect the invariant exists to prevent: two counts that can disagree.

## Why P6 gets its own runner when G8 already runs both halves

Because the two answer different questions at different times. `tools/gate_semgrep.py` is the
whole bank, twenty-five bans, and it is a CI gate whose failure means "something in the repository
broke a ban". This is a phase exit check, and what a reviewer needs at a phase boundary is one
line about one invariant: is `absent` still a claim with one constructor? A run of the full bank
answers that only by not failing, which is the weakest possible form of the answer.

INV-11 is why the count matters rather than the confinement. `absent` is a claim about the CORPUS
and not a description of the search: it requires all fifteen absence gates to have passed, in
precedence order, and 16:661 makes this gate's purpose exact -- *"The semgrep assertion
that there is exactly one `ABSENT` site is what stops a sixteenth hazard from becoming a second
citability rule"*. A second site inside `build_verdict()`'s own file is exactly that sixteenth
hazard, and it is the case the bank cannot see.

Exit codes: 0 green, 1 a second site, 2 the checker could not run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

_BANK: Final[Path] = Path(__file__).resolve().parent / "gate_semgrep.py"
"""The sibling that owns both halves of SV8. This file has no implementation of its own."""


def _load_bank() -> Any:
    """Load `tools/gate_semgrep.py` by path.

    `spec_from_file_location` and not a `sys.path` insertion: `tools/` is a directory of scripts
    and not a package, and a gate that put it on the path would change what every module imported
    after it resolves to -- including inside a test process that loads both gates. Not
    `importlib.import_module` either, which INV-17's neighbours confine to `host/`.
    """
    spec = importlib.util.spec_from_file_location("omniweave_gate_semgrep", _BANK)
    if spec is None or spec.loader is None:  # pragma: no cover - the file is in this repository
        message = f"cannot load {_BANK}"
        raise RuntimeError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_bank = _load_bank()

RULE: Final[str] = _bank._ABSENT_RULE
"""`omniweave-one-verdict-absent-site`, read off the bank's own module rather than retyped."""

HOME: Final[str] = _bank.VERDICT
"""The one file the bank confines the return to, read off the same module for the same reason."""

REPO_ROOT: Final[Path] = _bank.REPO_ROOT
"""The workspace root, also the bank's, so both gates scan one tree."""


def _say(text: str) -> None:
    """One line to stdout. `print` is banned repo-wide by ruff's T20 and `tools/` has no ignore."""
    sys.stdout.write(text + "\n")


def sites(root: Path | None = None) -> list[tuple[str, int]]:
    """Every `return VerdictState.ABSENT` in `packages/*/src/**`, as `(path, line)`.

    Reported rather than merely counted, because a failure whose message is a number sends the
    reader looking for the second site by hand. The walk is `_absent_returns`, the same generator
    both halves of `gate_semgrep` use.
    """
    base = REPO_ROOT if root is None else root
    found: list[tuple[str, int]] = []
    for path in sorted(base.glob("packages/*/src/**/*.py")):
        rel = path.relative_to(base).as_posix()
        tree = _bank._parse(rel, path.read_text(encoding="utf-8"))
        if tree is not None:
            found.extend((rel, line) for _, line in _bank._absent_returns(tree))
    return found


def _sv8(root: Path | None = None) -> list[Any]:
    """SV8's findings, filtered out of the bank's `ast` half.

    The delegation this file exists for: one call, no second walk.
    """
    return [finding for finding in _bank.ast_findings(root) if finding.rule_id == RULE]


def main(argv: Sequence[str] | None = None) -> int:
    """Report the site count, and fail on anything other than one."""
    del argv
    found = sites()
    findings = _sv8()

    if not found:
        _say("SV8 FAIL  no `return VerdictState.ABSENT` anywhere in packages/*/src/**.")
        _say(f"          INV-11 gives `absent` one constructor and it lives in {HOME}.")
        _say("          fix: this is a build defect, not a lint -- `build_verdict()` is missing")
        _say("          its one return, so nothing in the framework can claim an absence.")
        return 1

    if findings:
        _say(f"SV8 FAIL  {len(found)} `return VerdictState.ABSENT` sites; INV-11 allows one.")
        for rel, line in found:
            marker = "  <- the one site" if rel == HOME and (rel, line) == found[0] else ""
            _say(f"          {rel}:{line}{marker}")
        _say("          fix: return a `DegradeCause` carrying the `diag` code and the exact")
        _say("          clearing command instead. A second site is a second citability rule.")
        return 1

    rel, line = found[0]
    _say(f"SV8 ok  exactly one `return VerdictState.ABSENT`, at {rel}:{line}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
