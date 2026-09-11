"""What a conformance run is run *against*: one card, one distribution, one fixture set.

`ow conform --card <path> --fixtures <dir>` (18-api-sketch.md:937) names two things, and every
suite needs some part of both plus somewhere to write. `Subject` is that bundle, built once by the
runner and handed to each of the twelve unchanged.

## It does not import the driver, and the order is why

`Subject.of()` loads the card and stops. The driver is imported by `Subject.activate()`, which the
`card` and `purity` suites never call -- and they are the first two in `SUITES`. That ordering is
load-bearing rather than tidy: the `purity` suite's whole claim is "fails if any module of the
driver's distribution was imported while building the catalog" (04-driver-system.md:2074), and a
`Subject` constructor that imported the driver would make that claim untestable from inside the
same process, in exactly the way docling's load-then-gate order makes its own gate untestable.

So the invariant is: **nothing in this module imports driver code, and the one function that does
is named `activate` and delegates to `omniweave_core.host.activate`.** The kit may not call
`import_module` itself at all -- `tools/semgrep/omniweave.yaml`'s
`omniweave-no-import-module-outside-host` covers `packages/*/src/**` and excludes only
`omniweave_core/host/` -- which is the rule turning an architectural preference into a build
failure.

## `import_root` versus `dist_root`, which are different questions

`import_root` is the first dotted segment of the card's `entrypoint`: the name `purity` watches
`sys.modules` for. `dist_root` is the directory holding the `pyproject.toml` that builds the
driver: what `licence` scans and what `code_fingerprint()` hashes. A source checkout has both; a
wheel install has the first and may not have the second, which is why `dist_root` is `None`-able
and every suite that wants it says what it cannot check without it rather than failing.

Specified in 04-driver-system.md section 8 and 18-api-sketch.md section 8.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from omniweave_core.drivers.card import DriverCard, Tombstone, load_card, read_card_bytes
from omniweave_core.host.activate import activate as _activate
from omniweave_core.host.activate import entrypoint_parts

from omniweave_conform.harness import Fixture, load_fixtures

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["Subject"]

_PYPROJECT = "pyproject.toml"
_MAX_ROOT_WALK = 6


@dataclass(frozen=True, slots=True)
class Subject:
    """One card, its fixtures, its distribution on disk, and a scratch directory.

    Frozen, and `activate()` is therefore uncached. That is deliberate and costs nothing:
    `import_module` answers from `sys.modules` after the first call, and `check_card_code` is two
    `getattr`s. A cache here would be a mutable field on a value the twelve suites share.
    """

    card_path: Path
    raw: bytes
    card: DriverCard
    fixtures: tuple[Fixture, ...]
    workdir: Path
    fixtures_dir: Path | None = None
    dist_root: Path | None = None
    config: Mapping[str, Any] = field(default_factory=dict)
    """The DRIVER's `[config]` values, validated against its own schema by `instantiate()`.

    Anything the kit wants to tell a suite goes in `measurements`, NOT here. The card's
    `[config]` carries `additionalProperties = false` (04 section 2.7), so a kit that smuggled
    its own bookkeeping through this field would hand every driver four keys its schema is
    obliged to reject -- and it did, once, which is why the two are now named separately."""

    measurements: Mapping[str, Any] = field(default_factory=dict)
    """What `tools/ow_conform.py` measured in a child process, keyed by the suite that reads it.

    Caller-supplied and therefore exactly as trustworthy as the caller, which is why every
    suite that reads a key here treats it as corroboration of its own observation rather than
    as a substitute for one. Never reaches the driver."""

    @classmethod
    def of(
        cls,
        card_path: Path,
        *,
        fixtures_dir: Path | None = None,
        workdir: Path,
        config: Mapping[str, Any] | None = None,
        measurements: Mapping[str, Any] | None = None,
    ) -> Subject:
        """Load the card, gather the fixtures, and find the distribution root. Imports nothing.

        Raises:
            DriverHostError: any refusal `load_card()` makes -- `OW_CARD_INVALID`,
                `OW_CARD_ENTRYPOINT_MALFORMED`, `OW_CARD_SCHEMA_TOO_NEW`. These are NOT converted
                into a failing `card` suite result, because a card that will not load has no
                `[driver] id` to report a result *for*: the `card` suite's subject is a card that
                parsed, and `ow conform` on a card that did not is a usage error.
            TypeError: the card is a `[tombstone]`. A tombstone is a framework refusal with no
                entrypoint, no schema_version and no code; running the twelve against one would be
                asking a refusal to prove it parses documents.
        """
        card_path = card_path.resolve()
        raw = read_card_bytes(card_path)
        loaded = load_card(raw, origin="driver_path", source=str(card_path))
        if isinstance(loaded, Tombstone):
            msg = (
                f"{card_path}: this is a [tombstone] -- a framework refusal naming "
                f"{loaded.replaced_by or 'no replacement'} -- and has no code to conform"
            )
            raise TypeError(msg)
        resolved_fixtures = fixtures_dir.resolve() if fixtures_dir is not None else None
        return cls(
            card_path=card_path,
            raw=raw,
            card=loaded,
            fixtures=load_fixtures(resolved_fixtures) if resolved_fixtures else (),
            workdir=workdir,
            fixtures_dir=resolved_fixtures,
            dist_root=_find_dist_root(card_path),
            config=dict(config or {}),
            measurements=dict(measurements or {}),
        )

    @property
    def driver_id(self) -> str:
        return self.card.identity.id

    @property
    def import_root(self) -> str:
        """The first dotted segment of the entrypoint's module half, or `""` for an `exec` card.

        `""` rather than a raise: `purity` runs against every card including an `exec` one, and
        for that card the honest answer is "there is no module to watch for", which the suite
        states as an assertion rather than meeting as an exception.
        """
        if self.card.identity.entrypoint is None:
            return ""
        module, _ = entrypoint_parts(self.card)
        return module.partition(".")[0]

    def activate(self) -> type[object]:
        """Import the entrypoint through the one sanctioned importer, and assert it matches.

        Every suite that needs the class calls this rather than caching one between them, so a
        suite that runs after `purity` cannot accidentally be the thing that imported the driver.
        """
        return _activate(self.card)

    def instantiate(self, **overrides: Any) -> object:
        """Construct the driver under the card's own `[config]` defaults.

        `ConfigSchema.effective()` fills the defaults, which is what makes this the configuration
        the card *declares* rather than the configuration the kit happens to pass. A suite that
        constructed with `{}` would be testing a code path no operator can reach, because the host
        fills defaults the same way before it ever calls `__init__`.
        """
        cls = self.activate()
        values = {**self.config, **overrides}
        return cls(**dict(self.card.config.effective(values)))

    def scratch(self, name: str) -> Path:
        """A fresh directory under `workdir`, named for the suite that asked.

        Per-suite rather than per-run, so `sandbox`'s "0 writes outside tmp" count is over a
        directory only `sandbox` used and a stray file has exactly one possible author.
        """
        target = self.workdir / name
        target.mkdir(parents=True, exist_ok=True)
        return target

    def source_files(self) -> tuple[Path, ...]:
        """The driver distribution's `*.py`, for `code_fingerprint()`. `()` when unlocatable.

        Sorted by `code_fingerprint` itself; returned in `rglob` order here so the caller sees the
        set rather than a promise about the sequence.
        """
        root = self.source_root()
        if root is None:
            return ()
        return tuple(
            path
            for path in sorted(root.rglob("*.py"))
            if "__pycache__" not in path.parts and ".venv" not in path.parts
        )

    def source_root(self) -> Path | None:
        """The directory holding the DRIVER code, which is not always the distribution root.

        The card sits beside the driver package by construction -- `gate_layers.py:598` builds
        an entry point card path as `packages/<dist>/src/<package>/driver.toml` -- so the
        card parent directory is the driver package, and that is what is returned.

        For a driver shipped as its own distribution the two coincide. For the
        conformance-template driver, which ships INSIDE `omniweave_conform` so that
        `ow drivers scaffold` has something to copy, they do not: the distribution root is
        the whole kit, and scanning it would report the kit imports as the driver imports.
        The `licence` suite reads this, and reading the wider set made it report
        `omniweave_core` as an undeclared dependency of a driver that never imported it.
        """
        if self.card_path.parent.is_dir():
            return self.card_path.parent
        return self.dist_root


def _find_dist_root(card_path: Path) -> Path | None:
    """Walk up from the card looking for a `pyproject.toml`, at most six levels.

    Six because `<root>/src/<pkg>/<sub>/driver.toml` is four and a driver with two more nesting
    levels than the plan's own worked example is already unusual; an unbounded walk would find the
    *repository's* `pyproject.toml` for any card placed anywhere under a monorepo and then report
    that repository's licences as the driver's, which is a wrong answer rather than no answer.
    """
    for parent in list(card_path.parents)[:_MAX_ROOT_WALK]:
        if (parent / _PYPROJECT).is_file():
            return parent
    return None
