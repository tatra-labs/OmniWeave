"""`DriverBase` — the shape every Port protocol repeats. NOT an ABC: a Protocol.

Every Driver of every Port satisfies exactly this: a class with a `PORT` and
`SCHEMA_VERSION` class variable, a `probe()` classmethod, an `__init__(**config: Scalar)`
that loads nothing, one or more work methods taking a `DriverIO` and returning a
`DriverResult`, and a `driver.toml` beside it. No base class, no registration decorator, and
no import of the framework beyond `omniweave_ports`.

There is no `close()`, no `__enter__` and no explicit teardown on any Port protocol. A
`subproc` worker's lifetime is the host's; an `inproc` driver's resources are released when
the object is dropped. A driver needing a flush point uses `atexit` inside its own process.

Specified in 04-driver-system.md section 1.2 and 18-api-sketch.md section 5.1.
"""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from omniweave_ports.types import ProbeEnv, ProbeVerdict, Scalar


@runtime_checkable
class DriverBase(Protocol):
    """What `activate()` asserts against the card before any work runs.

    `@runtime_checkable` because the host checks a loaded class carries the two class
    variables and a `probe` before it trusts either — `PORT` and `SCHEMA_VERSION` are then
    compared to the card's `port` and `schema_version`, and a mismatch is
    `CARD_CODE_MISMATCH`. The four Port protocols are not runtime-checkable: 04 section 1.4
    prints them as plain `Protocol`s, and structural conformance to a work signature is the
    conform `contract` suite's job, not `isinstance`'s.

    Specified in 04-driver-system.md section 1.2 and 18-api-sketch.md section 5.1.
    """

    PORT: ClassVar[str]
    SCHEMA_VERSION: ClassVar[int]

    @classmethod
    def probe(cls, env: ProbeEnv) -> ProbeVerdict:
        """MAY import the driver's own heavy dependencies; MUST NOT download, spawn or write.

        Runs in a WORKER, never in the host process, and is cached per
        `(driver_id, version, card_sha256, env_digest)` under `$OMNIWEAVE_HOME`
        (04-driver-system.md section 4.7).
        """
        ...

    def __init__(self, **config: Scalar) -> None:
        """STATIC CONFIG ONLY, validated against the card's `[config]` schema BEFORE
        construction. Constructing a driver MUST load no model and open no file: a
        100%-cache-hit run constructs nothing at all, which is why the model load belongs in
        the first work call."""
        ...
