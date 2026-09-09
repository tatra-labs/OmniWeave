"""`Registry[T]`: one id, one value, and a duplicate that is a NAMED refusal rather than a winner.

DR3, and it is one invariant with one mechanism: **a duplicate driver id never wins silently.**
`register()` raises `DuplicateDriver` naming both distributions; `resolve()` emits
`ID_COLLISION_UNQUALIFIED`; and only an explicit `[drivers.resolve] "<id>" = "<distribution>"`
disambiguation lets a colliding id proceed. Nothing here guesses, and nothing here is ordered by
whichever distribution `entry_points()` happened to enumerate first.

**The receipt is DataFlow's.** Its plugin registry is keyed on a bare `__name__`, first-wins and
silent, so two plugins sharing one class name means one of them vanishes with no diagnostic --
and, because registration order follows installation order, *which* one vanishes is not stable
across machines. docling's is the same defect one layer up: `process_plugin` swallows a duplicate
as a `logger.warning`. Both failures share a shape worth naming, because it is the shape this
module exists to make unreachable: **the collision is detected and then discarded.** A registry
that knows two things claim one name and does not say so has converted a configuration error the
operator could fix into a behaviour difference they cannot reproduce.

**Generic, and a per-run instance rather than a module-level singleton.** `Registry[T]` is
02-architecture.md section 2 row 11's `T-INTERNAL` component -- it registers, it does not resolve,
rank or activate. It is instantiated per run and dropped at run end, for the same reason `Catalog`
is: a process-global registry that outlives a run makes "which drivers were visible" a function of
what some earlier run happened to install.

Specified in 04-driver-system.md section 4.5 ("Two distributions declare the same id") and section
12's DR3 row, and 02-architecture.md section 2 row 11.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Generic, TypeVar

from omniweave_core.errors import DriverHostError

__all__ = [
    "DUPLICATE_DRIVER_FIX",
    "DuplicateDriver",
    "Registration",
    "Registry",
]

T = TypeVar("T")

DUPLICATE_DRIVER_FIX: Final = 'ow config set drivers.resolve."<id>" <distribution>'
"""The exact command that clears a `DuplicateDriver`, and the ONLY thing that clears it.

`[drivers.resolve] "parse.office.anydoc" = "omniweave-office"` maps a colliding id to the
distribution that wins (04-driver-system.md section 4.5). `drivers.resolve.*` is a declared
`operational` config key with the twin `OMNIWEAVE_DRIVERS_RESOLVE_*`, so the disambiguation is a
reviewable line in the operator's own configuration rather than a flag on a command -- which is
what makes it survive to the next run and to the next machine.
"""

_NO_RESOLVE: Final[Mapping[str, str]] = MappingProxyType({})


class DuplicateDriver(DriverHostError):  # noqa: N818 -- 04-driver-system.md section 4.5 names it.
    """Two distributions declare one id and no `[drivers.resolve]` row says which wins.

    Carries **both** distributions, because naming only the loser reproduces the defect this class
    exists to catch: the operator cannot write the disambiguation row without knowing both
    candidates, and "duplicate id" alone tells them nothing they can act on.

    `OW-D-013` / `OW_DRIVER_DUPLICATE_ID`. A `DriverHostError` and not a `ConfigError` because the
    collision is a property of what is INSTALLED, which the operator's configuration then resolves;
    the file is where the fix goes, not where the fault is.
    """

    SYMBOL = "OW_DRIVER_DUPLICATE_ID"

    def __init__(
        self,
        key: str,
        incumbent: str,
        challenger: str,
        *,
        subject: str = "driver",
        fix: str = DUPLICATE_DRIVER_FIX,
    ) -> None:
        super().__init__(
            f"two distributions declare {subject} id {key!r}: {incumbent or '<unnamed>'} and "
            f"{challenger or '<unnamed>'}; neither wins by default",
            fix=fix,
        )
        self.key = key
        self.incumbent = incumbent
        self.challenger = challenger


@dataclass(frozen=True, slots=True)
class Registration(Generic[T]):
    """One registered value and the distribution that supplied it.

    `distribution` is carried beside the value rather than derived from it because the value is
    whatever `T` is -- a `DriverCard`, an `ActionSpec`, a factory -- and only the caller that
    enumerated the entry points knows which wheel it came out of. It is also the half of a
    collision report that makes the report actionable, so it is not optional in practice even
    though it defaults to the empty string for a registration that has no distribution at all
    (a `driver_path` or `project` card is a file, not a wheel).
    """

    key: str
    value: T
    distribution: str = ""


class Registry(Generic[T]):
    """`register` / `get` / `items`, plus the collision rule that is the whole point.

    Deliberately NOT a `Mapping` subclass and deliberately without `__setitem__`: `d[k] = v`
    overwriting silently is exactly the behaviour DR3 forbids, and a registry that also spells
    itself as a dict invites a caller to reach for the spelling that has no collision check.
    Reading is spelled `get()` / `items()` / `in`, and writing is spelled `register()`.

    `resolve` is `[drivers.resolve]`: `{id -> distribution}`. It is passed at construction because
    it is configuration loaded once at startup, and a per-call argument would let two call sites
    disagree about which distribution wins for one id.
    """

    __slots__ = ("_by_key", "_resolve", "_subject")

    def __init__(
        self,
        *,
        subject: str = "driver",
        resolve: Mapping[str, str] = _NO_RESOLVE,
    ) -> None:
        self._by_key: dict[str, Registration[T]] = {}
        self._resolve = dict(resolve)
        self._subject = subject

    def register(
        self,
        key: str,
        value: T,
        *,
        distribution: str = "",
        replace: bool = False,
    ) -> Registration[T]:
        """Bind `key`. Raise `DuplicateDriver` on a second claim that nothing disambiguates.

        The four cases, in the order they are decided:

        1. `key` is free -- it binds, and the registration is returned.
        2. `replace=True` -- the caller has stated the intent, so the incumbent is replaced. This
           is 02-architecture.md section 2 row 11's own escape hatch, and it exists for the cases
           where one authority deliberately rebinds a name (a test harness, a `--pin`), never for
           discovery, which passes it nowhere.
        3. A `[drivers.resolve]` row names a winner -- the named distribution's registration stands
           whether it is the incumbent or the challenger, and the other is dropped. A row naming a
           distribution that is NEITHER is still a collision: the operator disambiguated an id
           against something that is not installed, and silently picking one of the two would be
           the first-wins defect wearing a configuration file as a disguise.
        4. Otherwise `DuplicateDriver`, naming both.

        Registering the same `(key, value, distribution)` twice is case 4 as well, not a no-op: two
        entry points for one id in one distribution is a packaging bug, and a registry that
        absorbed it would hide the day the two stop being equal.
        """
        challenger: Registration[T] = Registration(key=key, value=value, distribution=distribution)
        incumbent = self._by_key.get(key)
        if incumbent is None or replace:
            self._by_key[key] = challenger
            return challenger

        winner = self._resolve.get(key)
        if winner is not None and winner == challenger.distribution != incumbent.distribution:
            self._by_key[key] = challenger
            return challenger
        if winner is not None and winner == incumbent.distribution != challenger.distribution:
            return incumbent

        raise DuplicateDriver(
            key,
            incumbent.distribution,
            challenger.distribution,
            subject=self._subject,
        )

    def get(self, key: str) -> T | None:
        """The registered value, or `None`. Reading a registry never raises."""
        found = self._by_key.get(key)
        return None if found is None else found.value

    def registration(self, key: str) -> Registration[T] | None:
        """The value AND the distribution that supplied it, or `None`.

        The distribution is what `ow drivers list` prints as `<id>@<dist>` -- the fully qualified
        form of a `DriverId` -- and what a collision report would have named, so it is reachable
        after registration and not only inside the exception.
        """
        return self._by_key.get(key)

    def items(self) -> tuple[tuple[str, T], ...]:
        """Every binding, **sorted by key**, as a tuple.

        Sorted and materialised rather than a live view, for one reason: an iteration order that
        follows insertion order is an iteration order that follows whichever distribution
        `entry_points()` enumerated first, and a caller that accidentally depends on it gets a
        different answer on a different machine. That is the same class of defect as first-wins
        registration, one step further downstream, and `resolve()` sorting its candidates
        lexically before return (DR6) is the same rule stated for the same reason.
        """
        return tuple((key, entry.value) for key, entry in sorted(self._by_key.items()))

    def distributions(self) -> Mapping[str, str]:
        """`{key -> distribution}` for every binding, sorted. `""` where there is no wheel."""
        return MappingProxyType(
            {key: entry.distribution for key, entry in sorted(self._by_key.items())}
        )

    def __contains__(self, key: object) -> bool:
        return key in self._by_key

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._by_key))

    def __len__(self) -> int:
        return len(self._by_key)

    def __repr__(self) -> str:
        return f"Registry({self._subject!r}, {len(self._by_key)} registered)"
