"""`activate()` — step 4 of 04-driver-system.md:1543-1546, and the one site that imports a driver.

04-driver-system.md:1518-1519 states the property this module exists to keep true: refusal happens
at four distinct points "and **none of them imports the driver except the last**". Discovery reads
`tomllib` and validates; `resolve()` is pure over `Requirement x Catalog x Policy`; preflight runs
the probe in a worker. This file is the fourth point, and it is the only file in `packages/*/src/**`
outside this package that `tools/semgrep/omniweave.yaml`'s `omniweave-no-import-module-outside-host`
permits to call `importlib.import_module` at all.

`host/inproc.py:47-49` recorded the hole this fills in as many words: "the `activate()` that
resolves `card.entrypoint` is a separate function the plan files under `host/` ... and it does not
exist in the tree yet". It does now, and `DriverGuard.check_code()` delegates here rather than
keeping a second copy of the comparison (INV-21).

## The three refusals, and the one report

`activate()` refuses three things and reports a fourth:

* **an `exec` driver** — `card.py:2974-2989` already states why, and it is not a policy choice:
  "`activate()` imports nothing for such a driver — the `PORT` and `SCHEMA_VERSION` assertions come
  from `HELLO_ACK` alone, which is exactly why `HELLO_ACK` carries them". There is no in-process
  object to return, so returning `None` or a stub would be inventing one.
* **a module that will not import** — as `OW_DRIVER_ACTIVATION_FAILED`, never as the driver's own
  exception. A driver whose module body raises is a driver bug and it is attributed as one; letting
  an arbitrary `BaseException` out of here would put a third party's traceback in a host code path,
  which is the same attribution failure 02-architecture.md:1061 fixes one seam over.
* **a card/code mismatch** — `PORT` or `SCHEMA_VERSION` disagreeing with the card, as
  `OW_CARD_CODE_MISMATCH` "BEFORE any work" (`codes.toml` `OW-D-073`).

And it *reports*, rather than refuses, the fourth: `code_fingerprint()`. 04-driver-system.md:1553
is explicit — a mismatch against the value the kit recorded "is **reported, not refused**, because
attestation is tamper-evidence and not authentication". So the fingerprint is a function you may
call and compare; nothing here compares it for you, because a function that refused on it would
have quietly turned tamper-evidence into authentication.

## Why the import is the last thing that happens

The order in `activate()` is the specification. The `exec` refusal and the entrypoint split are
both decidable from the card alone, so they happen before `import_module`, and a malformed or
inapplicable card therefore never executes a line of third-party code. That is the same ordering
discipline `04 section 4.6` applies to discovery, one rung later: the cheapest refusal that can be
made is made first, and *execute* is always the last rung.

Specified in 04-driver-system.md section 5.3 step 4 and section 4.6; INV-4, DR19.
"""

from __future__ import annotations

import hashlib
import importlib
from typing import TYPE_CHECKING, Final

from omniweave_core.drivers.resolve import RejectCode
from omniweave_core.errors import DriverHostError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from omniweave_core.drivers.card import DriverCard

__all__ = [
    "ACTIVATION_FAILED",
    "activate",
    "check_card_code",
    "code_fingerprint",
    "construct",
    "entrypoint_parts",
]


ACTIVATION_FAILED: Final = "OW_DRIVER_ACTIVATION_FAILED"
"""The symbol for a module that would not import or an attribute that was not there.

Deliberately NOT one of the twenty-five `RejectCode` members (04-driver-system.md:1558-1570).
Those are *rejections* — reasons a driver was not selected, produced by discovery, `resolve()`,
preflight and activate's card/code check, every one of them decidable before the driver runs. An
`ImportError` out of a module body is the driver already running and failing, which is a driver
bug rather than a filter result, and giving it a `RejectCode` would put a twenty-sixth member in a
set whose size several tests pin."""


def entrypoint_parts(card: DriverCard) -> tuple[str, str]:
    """`("pkg.module", "Attr")` from `card.entrypoint`. Imports nothing.

    `card.ENTRYPOINT_RE` — `^[^:/]+:[^:/]+$` — already refused anything without exactly one colon
    or with a slash at load time, as `CARD_ENTRYPOINT_MALFORMED` (04-driver-system.md:1524), so
    the split here cannot fail on a card that `load_card()` produced. The check is repeated anyway
    because this function's contract is "a card in, two names out" and a caller that built a
    `DriverCard` some other way must not get a silent `ValueError` from `str.split`.
    """
    entrypoint = card.identity.entrypoint
    if entrypoint is None:
        raise DriverHostError(
            f"{card.identity.id}: the card declares [driver] exec and has no entrypoint to import",
            symbol=RejectCode.CARD_CODE_MISMATCH.symbol,
            fix=f"ow drivers verify {card.identity.id}",
        )
    module, _, attribute = entrypoint.partition(":")
    if not module or not attribute or ":" in attribute:
        raise DriverHostError(
            f"{card.identity.id}: entrypoint {entrypoint!r} is not 'module:Attr'",
            symbol="OW_CARD_ENTRYPOINT_MALFORMED",
            fix="ow drivers verify " + card.identity.id,
        )
    return module, attribute


def check_card_code(card: DriverCard, loaded: object) -> None:
    """`PORT` and `SCHEMA_VERSION` on the loaded object against the card. **The one home.**

    04-driver-system.md:1543-1545 checks step 4 twice on purpose — once here against the imported
    class and once against the worker's `HELLO_ACK` — "because an `inproc` driver has no
    `HELLO_ACK`, an `exec` driver has no importable class, and a `subproc` worker may be a
    different build than the card the host read from disk". This is the first of the two;
    `host/subproc.py`'s `HelloAck` handling is the second, and they compare the same two fields
    against the same card because they are checking the same claim through two windows.

    `DriverGuard.check_code()` delegates here. A guard that kept its own copy would be a second
    home for one fact (INV-21), and the two copies would drift in exactly the way a card and its
    code drift — which is the defect this function exists to catch.
    """
    identity = card.identity
    wanted = (f"{identity.port.value}/{identity.port_major}", identity.schema_version)
    got = (getattr(loaded, "PORT", None), getattr(loaded, "SCHEMA_VERSION", None))
    if got != wanted:
        raise DriverHostError(
            f"{identity.id}: the loaded class declares PORT={got[0]!r} "
            f"SCHEMA_VERSION={got[1]!r} and the card says {wanted[0]!r} / {wanted[1]!r}",
            symbol=RejectCode.CARD_CODE_MISMATCH.symbol,
            fix=f"ow drivers verify {identity.id}",
        )


def activate(card: DriverCard) -> type[object]:
    """Import `card.entrypoint` and return the class, after asserting it matches the card.

    Args:
        card: a loaded `DriverCard`. `resolve()` has normally already cleared it; this function
            deliberately does not require a `Candidate`, because the conformance kit activates a
            driver that no `Requirement` asked for and `ow drivers verify` activates one to check
            its installed bytes. Clearance to *run in process* is `DriverGuard`'s check and it is
            a different question from whether the class can be loaded at all.

    Returns:
        The class named by the entrypoint's attribute half. Not an instance: `__init__` takes the
        driver's `[config]` and the `contract` suite asserts what it may do, so constructing one
        is the caller's decision and its cost is the caller's to pay.

    Raises:
        DriverHostError: `OW_CARD_CODE_MISMATCH` for an `exec` card or a `PORT`/`SCHEMA_VERSION`
            disagreement, `OW_CARD_ENTRYPOINT_MALFORMED` for an entrypoint that is not
            `module:Attr`, `OW_DRIVER_ACTIVATION_FAILED` for a module that would not import or an
            attribute that was not there.

    **This line is the framework's only `import_module`**, and everything above it in the function
    body is there so that a card which cannot possibly work never reaches it.
    """
    module_name, attribute = entrypoint_parts(card)
    try:
        module = importlib.import_module(module_name)
    except BaseException as exc:  # a driver's module body may raise literally anything.
        raise DriverHostError(
            f"{card.identity.id}: importing {module_name!r} raised {type(exc).__name__}: {exc}",
            symbol=ACTIVATION_FAILED,
            fix=f"ow drivers verify {card.identity.id}",
        ) from exc
    loaded = getattr(module, attribute, None)
    if loaded is None:
        raise DriverHostError(
            f"{card.identity.id}: {module_name!r} has no attribute {attribute!r}",
            symbol=ACTIVATION_FAILED,
            fix=f"ow drivers verify {card.identity.id}",
        )
    # BEFORE `check_card_code`, and the order is the message. An entrypoint naming an integer is
    # a structural problem with the entrypoint; running the card/code comparison first would
    # answer it with `CARD_CODE_MISMATCH`, which sends the author to compare `PORT` strings on an
    # object that has none. Two refusals, and each one names the thing that is actually wrong.
    if not isinstance(loaded, type):
        raise DriverHostError(
            f"{card.identity.id}: {card.identity.entrypoint} named a "
            f"{type(loaded).__name__}, not a class",
            symbol=ACTIVATION_FAILED,
            fix=f"ow drivers verify {card.identity.id}",
        )
    check_card_code(card, loaded)
    return loaded


def construct(card: DriverCard, config: Mapping[str, object]) -> object:
    """`activate()` then `__init__(**config)`: the driver object both seams call methods on.

    `activate()` returns a class on purpose -- constructing one *"is the caller's decision"* -- and
    the two callers that decide to are the S4 worker, in its own interpreter after the egress
    hook, and the S1 parse Operator, in the host's. Both run the driver's `__init__`, so both must
    attribute a raise from it the same way: `OW_DRIVER_ACTIVATION_FAILED`, the symbol a module
    that will not import already carries, because a constructor that raises is the driver failing
    before its first unit, not a unit failing. One home for that ruling (INV-21).

    `config` is the effective `[config]` -- the card's defaults under the operator's overrides,
    whose digest the row's `dispatch_key` was minted over.
    """
    loaded = activate(card)
    try:
        return loaded(**dict(config))
    except Exception as exc:
        raise DriverHostError(
            f"{card.identity.id}.__init__ raised {type(exc).__name__}: {exc}",
            symbol=ACTIVATION_FAILED,
            fix=f"ow drivers verify {card.identity.id}",
        ) from exc


def code_fingerprint(files: Iterable[Path]) -> str:
    """`sha256` over the driver package's `*.py` bytes, in sorted-name order. 64 bare hex chars.

    04-driver-system.md:1550-1553: "`code_fingerprint` in `HELLO_ACK` is the sha256 of the driver
    package's `RECORD`-listed `*.py` bytes for a Python driver and of the executable for an `exec`
    one". The caller supplies the file list because *which* files are in `RECORD` is an
    installation fact, and reading `RECORD` here would make this function depend on the driver
    being pip-installed — which it is not, in the two cases that matter most: an editable install
    during `ow conform`, and a driver under test from a source tree.

    The name is hashed alongside the bytes, and length-prefixed. Hashing bytes alone would give a
    package that renamed `a.py` to `b.py` the same fingerprint, and concatenating name and content
    without a delimiter would let `("ab", "c")` and `("a", "bc")` collide — the classic length-
    extension shape, which costs one `len()` to remove and is unfixable once a value has shipped.

    Returns bare hex, not `sha256:`-prefixed: this is a cache-and-compare digest carried on a wire
    frame, and `card.py:1284-1290` reserves the prefixed form for a digest a human diffs in version
    control.
    """
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.as_posix()):
        name = path.as_posix().encode("utf-8")
        body = path.read_bytes()
        digest.update(len(name).to_bytes(8, "little"))
        digest.update(name)
        digest.update(len(body).to_bytes(8, "little"))
        digest.update(body)
    return digest.hexdigest()
