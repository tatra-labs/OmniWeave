"""`ci-ok`, the one required status check: every job succeeded, or was `toolchains` and skipped.

11-repo-layout.md section 6.2: *"A conditional job that does not run reports `skipped`, and GitHub
cannot require a check that may never report -- a required `toolchains` would block every PR that
does not touch TypeScript, forever. So there is exactly one required check, `ci-ok`, and it runs
`if: always()` and inspects the `needs` context rather than relying on the implicit `success()`."*
The register carries it as the `[[job_assertion]]` `ci-ok.skips_declared`, whose step reads
`python3 tools/ci_ok.py with NEEDS=${{ toJSON(needs) }}; SKIPPABLE = {"toolchains"}`.

Until this script landed, `ci.yml` carried a `jq` filter with the same three properties inline --
the one guarded step in that file whose fallback was a full implementation rather than a NOT
ENFORCED line, because *"a required check that reports green when a job failed is the one defect
this whole design exists to prevent"*. The filter is deleted in the commit that adds this file.

## Rulings

1. **A cancelled job is a failure.** `if: always()` fires on cancellation too, so a truthiness
   check over the results would read an aborted matrix as green. Only the literal string
   `success` passes, which is also why this never tests for `failure` by name: a result nobody
   anticipated -- today GitHub also emits `cancelled`, and tomorrow something else -- fails.
2. **`SKIPPABLE` is a literal set and never a wildcard.** Admitting a second conditional job is a
   reviewable diff here, not a silent widening of a pattern. `toolchains` is in it because section
   6.2 names it: it is the TypeScript cell and it is the only job in the workflow with an `if:`.
3. **An absent or empty `needs` context is a failure, not a vacuous pass.** This is the whole
   failure mode of a required check: a step that found nothing to judge and said "ok" is worse
   than no check. `EXPECTED` is the ten jobs the workflow declares, so a job added to `needs` and
   not here -- or here and not in the workflow -- is a finding, and `test_ci_ok.py` holds this
   tuple to `ci.yml`'s own `needs` list rather than trusting either copy.
4. **Stdlib only, and the environment is the input.** `NEEDS` is what the step passes; a run with
   no `NEEDS` at all is ruling 3's case and exits 1. Reading the workflow file here would mean
   parsing YAML, which is not in the standard library and would make the required check depend on
   an installed package.

Usage, as `ci.yml`'s step runs it:

    NEEDS='{"gates": {"result": "success"}, ...}' python3 tools/ci_ok.py

Exit codes: `0` every job succeeded (or was `toolchains`, skipped); `1` anything else.

Specified in 11-repo-layout.md section 6.2 and `tools/gates.toml`'s `ci-ok.skips_declared`.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Final

SUCCESS: Final = "success"
SKIPPED: Final = "skipped"
SKIPPABLE: Final = frozenset({"toolchains"})
"""Ruling 2: section 6.2's one conditional job, as a set so a second one is a reviewed diff."""

EXPECTED: Final = (
    "versions",
    "gates",
    "test",
    "golden",
    "conform",
    "incremental",
    "crash",
    "parity",
    "toolchains",
    "build",
)
"""Ruling 3: `ci.yml`'s own `needs` list for this job, in its order. `test_ci_ok.py` asserts the
two agree, so this tuple cannot drift from the workflow without the suite going red."""


def _emit(line: str) -> None:
    sys.stdout.write(line + "\n")


def findings(needs: dict[str, object]) -> list[str]:
    """Rulings 1, 2 and 3: every reason this run is not green, in the jobs' declared order."""
    out = []
    missing = [job for job in EXPECTED if job not in needs]
    if missing:
        out.append(f"no result reported for {', '.join(missing)}")
    unknown = sorted(set(needs) - set(EXPECTED))
    if unknown:
        out.append(f"a result for {', '.join(unknown)}, which this check does not know about")
    for job in EXPECTED:
        if job in missing:
            continue  # already named once; a per-job `=None` beside it is noise
        result = _result(needs, job)
        if result == SUCCESS:
            continue
        if job in SKIPPABLE and result == SKIPPED:
            continue
        out.append(f"{job}={result}")
    return out


def parse(raw: str | None) -> dict[str, object]:
    """The `needs` context as a mapping. Ruling 3: anything else is an empty one, which fails."""
    if not raw or not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def main(argv: list[str] | None = None) -> int:
    del argv
    needs = parse(os.environ.get("NEEDS"))
    bad = findings(needs)
    if bad:
        _emit(f"ci-ok FAILED: {'; '.join(bad)}")
        _emit(
            "SKIPPABLE is {toolchains} and nothing else; cancelled is a failure, not a pass, and "
            "an empty needs context is not a pass either (section 6.2)."
        )
        return 1
    skipped = [job for job in EXPECTED if job in SKIPPABLE and _result(needs, job) == SKIPPED]
    said = f", {', '.join(skipped)} skipped" if skipped else ""
    _emit(f"ci-ok: {len(EXPECTED)} job(s) succeeded{said}")
    return 0


def _result(needs: dict[str, object], job: str) -> str | None:
    raw = needs.get(job)
    return raw.get("result") if isinstance(raw, dict) else None


if __name__ == "__main__":
    raise SystemExit(main())
