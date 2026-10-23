"""Three `ow doctor` rows that read what the project declares: D-06, D-13 and D-17. D956.

15-observability.md:1514-1540 is the table. Each row here asks a question the project's own files
answer, through the code a run uses, and each failing row names the command that clears it:

- **D-06** (fail): every driver the compiled routing policy or `[graph.passes] enable` names is
  in `[drivers] enabled` (INV-5). The policy is compiled as a run compiles it
  (`route_layers` and `compile_policy`, the project's `policy.d` included). A rule that declares
  `expect_unavailable` names a driver absent on purpose: the builtin `fields.extract` names
  `parse.fields.lift`, whose licence tier the shipped `allow_tiers` refuses, and 05:1622-1625
  says *"without it `ow doctor` exits 1 on a fresh install; with it the absence is a warning
  naming this rule"*. So that absence warns, and every other one fails. 15:1519's `[[pin]]` is
  not a configuration key in this build, so no pin is read.
- **D-13** (warn): each declared corpus's `.omniweave/pricebook.toml` (`run.ingest.pricebook`,
  05:2386) parses through `PriceBook.loads`, which refuses a missing `version` or `currency`
  with its own fix, and its `effective_from` is not after today. An absent pricebook is reported,
  not warned: every attempt is then unpriced, and nothing in this build admits `billed_api`
  against it.
- **D-17** (warn): the installed skill bundles match the hashes `skills-lock.json` recorded,
  which is `ow skills verify`'s own check (`install.skillcheck.verify`), with `ow skills update`,
  15:1532's fix, for a mismatch.

Today's date is read once, from the caller, so a test hands in a date.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from omniweave.sdk.reports import DoctorFinding

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_core.config import Config

__all__ = ["PROJECT", "check_named_drivers", "check_pricebooks", "check_skills"]

PROJECT: Final[tuple[str, ...]] = ("D-06", "D-13", "D-17")
"""The rows this module checks."""

_PASSES_KEY: Final = "graph.passes.enable"


def check_named_drivers(config: Config, *, project_root: Path | None) -> tuple[DoctorFinding, ...]:
    """D-06 (15:1519): the drivers the policy and the passes name are enabled."""
    from omniweave_core.errors import OwError  # noqa: PLC0415

    from omniweave.route.policy import POLICY_D, compile_policy  # noqa: PLC0415 -- the verb pays
    from omniweave.run.routing import route_layers  # noqa: PLC0415

    policy_dir = None if project_root is None else project_root / POLICY_D
    try:
        policy = compile_policy(route_layers(config, policy_dir=policy_dir))
    except OwError as error:
        return (DoctorFinding("D-06", f"{error.code()}: {error}", "error", error.fix),)
    enabled = {str(one) for one in config.get("drivers.enabled")}  # type: ignore[union-attr]
    named: dict[str, list[tuple[str, bool]]] = {}
    for rule in policy.rules:
        if rule.then.driver:
            named.setdefault(rule.then.driver, []).append(
                (f"rule {rule.id}", rule.expect_unavailable)
            )
    for one in config.get(_PASSES_KEY):  # type: ignore[union-attr]
        named.setdefault(str(one), []).append(("[graph.passes] enable", False))
    findings: list[DoctorFinding] = []
    for driver in sorted(set(named) - enabled):
        where = ", ".join(place for place, _expected in named[driver])
        if all(expected for _place, expected in named[driver]):
            findings.append(
                DoctorFinding(
                    "D-06",
                    f"{driver} is named by {where}, which expects it absent "
                    "(expect_unavailable), and is not in [drivers] enabled",
                    "warning",
                    f"add {driver} to [drivers] enabled to serve that rule's lane",
                )
            )
            continue
        findings.append(
            DoctorFinding(
                "D-06",
                f"{driver} is named by {where} and is not in [drivers] enabled (INV-5)",
                "error",
                f"add {driver} to [drivers] enabled, or remove what names it",
            )
        )
    if not findings:
        findings.append(
            DoctorFinding(
                "D-06",
                f"every one of the {len(named)} driver(s) the policy and [graph.passes] name is "
                "enabled",
                "ok",
                "",
            )
        )
    return tuple(findings)


def check_pricebooks(config: Config, *, cwd: Path, today: str) -> tuple[DoctorFinding, ...]:
    """D-13 (15:1526). `today` is an ISO date, `YYYY-MM-DD`."""
    from omniweave_core.errors import OwError  # noqa: PLC0415

    from omniweave.route.spend import PriceBook  # noqa: PLC0415 -- the verb pays
    from omniweave.run.ingest import PRICEBOOK_FILE  # noqa: PLC0415
    from omniweave.surface.serve import stores  # noqa: PLC0415
    from omniweave.surface.startup import corpora  # noqa: PLC0415

    declared = corpora(config)
    if not declared:
        return (DoctorFinding("D-13", "no corpus is declared, so no pricebook is read", "ok", ""),)
    found = stores(config, declared, cwd=cwd).values()
    paths = sorted({str(Path(store).parent / PRICEBOOK_FILE) for store in found})
    findings: list[DoctorFinding] = []
    for raw in paths:
        path = Path(raw)
        shown = path.as_posix()
        if not path.is_file():
            findings.append(
                DoctorFinding(
                    "D-13",
                    f"no pricebook at {shown}: every attempt is unpriced, and billed_api cannot "
                    "be admitted",
                    "ok",
                    "",
                )
            )
            continue
        try:
            book = PriceBook.load(path)
        except OwError as error:
            findings.append(DoctorFinding("D-13", f"{shown}: {error}", "warning", error.fix))
            continue
        if book.effective_from and book.effective_from > today:
            findings.append(
                DoctorFinding(
                    "D-13",
                    f"{shown}: effective_from {book.effective_from} is after today, {today}, so "
                    "its rates do not apply yet",
                    "warning",
                    f"set effective_from to {today} or earlier in {shown}",
                )
            )
            continue
        findings.append(
            DoctorFinding(
                "D-13", f"{shown}: version {book.version}, currency {book.currency}", "ok", ""
            )
        )
    return tuple(findings)


def check_skills(env: Mapping[str, str], *, cwd: Path) -> DoctorFinding:
    """D-17 (15:1532), through `ow skills verify`'s own check."""
    from omniweave.install.run import host_env  # noqa: PLC0415 -- the verb pays
    from omniweave.install.skillcheck import MISMATCH_SYMBOL, verify  # noqa: PLC0415
    from omniweave.install.verbs import OK  # noqa: PLC0415

    host = host_env(env, cwd)
    if isinstance(host, str):
        return DoctorFinding("D-17", f"not run: {host}", "warning", "set HOME or USERPROFILE")
    outcome = verify(host)
    lines = [line.strip() for line in outcome.lines if line.strip()]
    if outcome.exit_code == OK:
        detail = "; ".join(lines) if lines else "every installed skill bundle matches its hash"
        return DoctorFinding("D-17", detail, "ok", "")
    bad = [line for line in lines if MISMATCH_SYMBOL in line or "MISSING" in line] or lines
    return DoctorFinding("D-17", "; ".join(bad), "warning", "ow skills update")
