"""Every refusal that happens before an HTTP request reaches the dispatcher. 10 section 10.

Two of them stop the listener from opening at all and three of them answer a request without
spending anything. All five are pure functions over a bind address, a header table and a driver
roster, which is what lets the ASGI middleware around them be three lines that decide nothing.

## THE ORDER, WHICH IS A SECURITY PROPERTY AND NOT A CONVENTION

10:2355 fixes the first step: *"`Origin` and `Host` are validated **before auth**, and a loopback
bind is exactly why."* The rest follows from what each check can be told without being trusted:

| # | check | code | status | what a caller learns by failing it |
|---|---|---|---|---|
| 1 | `Origin` / `Host` | `OW-A-041` | 403 | that something on this port refuses browsers |
| 2 | the API key | -- | 401 | that a key is required |
| 3 | the media type | -- | 415 | that JSON is expected |
| 4 | the body size | -- | 413 | the cap, which is why it is last |

**Why the size check is last rather than first.** It is the cheapest of the four -- one header read
-- and cheapness is the usual argument for putting a check early. It is last anyway, because it is
the only one of the four whose failure discloses a number. An unauthenticated caller who can
distinguish "too big" from "unauthorized" learns `MAX_REQUEST_BYTES` by bisection; one who gets a
401 either way learns that a key is required and nothing else. Nothing is buffered to reach the
check, because `content-length` is a header, so the ordering costs nothing to hold.

## WHAT A REFUSAL IS ALLOWED TO SAY

Nothing the caller did not already know. 10:2325 sets the standard for the two unauthenticated
routes -- *"`/healthz` and `/readyz` reveal nothing an unauthenticated caller could use: no release
string, no corpus list, no document counts. A load balancer needs a boolean, not an inventory"* --
and a refusal is the same surface with a different status code. So a `Rejection`'s body is one word
from a closed set, an `Origin` rejection never echoes the rejected origin back, and nothing prints
`allowed_origins` or `allowed_hosts` to the party that just failed them. The symbol travels on the
object for the log, and never in the response.

## THE DNS-REBINDING GUARD, AND THE ONE ATTACK A LOOPBACK BIND IS OPEN TO

10:2353 states it exactly: *"A page in the user's browser can reach `http://127.0.0.1:<port>` and,
without a check, a DNS-rebound name resolves to loopback and the browser sends the request with the
attacker's origin."* Hence two clauses, both refusing rather than warning:

* an `Origin` header that is present and not in `[serve] allowed_origins`, whose default is EMPTY,
  so **any** `Origin` is rejected -- an MCP client is not a browser and sends none;
* a `Host` whose name is neither a literal loopback address nor a member of
  `[serve] allowed_hosts` (default `{"localhost", "127.0.0.1", "[::1]"}`).

A **duplicated** `Origin` or `Host` is refused by the same clause and is this module's addition:
ASGI hands the middleware a list of pairs rather than a mapping, so two `Host` headers arrive
intact, and a guard that read the first while something downstream read the last would be checking
a different request from the one that gets served. There is no legitimate second `Host`.

## THE TWO LISTENER REFUSALS

`listener_refusal()` is `OW-A-040 / OW_HTTP_BIND_UNAUTHENTICATED`, and 10:2340 says why it refuses
instead of warning: *"a warning on a line nobody reads is how an unauthenticated corpus reaches the
network."* `UsageError`, because it is a combination of arguments failing validation before any
store read, and because 10:2338 fixes the exit at 1.

`copyleft_refusal()` is `OW-A-043 / OW_SERVE_COPYLEFT_NETWORK`. A `copyleft_network` restriction is
accepted for a local run under an acknowledged licence; a **listening** transport engages the very
clause the acknowledgement disclaims, so the conjunct is checked where the listener is opened.
`PolicyRefusal`, which `errors.py` defines as *"a licence tier, a missing grant"* at exit 6, and
10:1510 confirms that a licence refusal outranks the gate code for the same reason: *"the fix is a
grant and not an edit."* The roster is passed in rather than discovered here, because which drivers
are enabled is the caller's fact and `restriction_bits` is already stamped by the runner (INV-16).

## WHAT THIS MODULE DOES NOT DECIDE

Whether the rebinding guard applies to `/healthz` and `/readyz`. 10:2317's table gives both routes
`auth: none` and says nothing about `Origin`; the two readings differ for exactly the
load-balanced deployment `--stateless` exists to serve. `gate()` applies it to every route and
exempts only auth, which is the conservative reading and is stated rather than assumed. D349.
"""

from __future__ import annotations

import hmac
import ipaddress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.errors import PolicyRefusal, UsageError
from omniweave_ports import Restriction

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

__all__ = [
    "BEARER",
    "HEADER_API_KEY",
    "HEADER_AUTHORIZATION",
    "HEADER_CONTENT_LENGTH",
    "HEADER_CONTENT_TYPE",
    "HEADER_HOST",
    "HEADER_ORIGIN",
    "MAX_REQUEST_BYTES",
    "MEDIA_TYPE",
    "OPEN_ROUTES",
    "EnabledDriver",
    "Rejection",
    "auth_rejection",
    "copyleft_refusal",
    "gate",
    "headers_of",
    "is_loopback",
    "listener_refusal",
    "payload_rejection",
    "rebinding_rejection",
]

MAX_REQUEST_BYTES: Final = 1_048_576
"""The ASGI body cap, enforced from `content-length` before anything is parsed.

10:2367 spells this `MAX_BODY_BYTES` and gives the arithmetic: *"a JSON-RPC call whose arguments
are capped at 4,096-character queries and 256 sources cannot legally approach it."*

**The spelling is this module's and the number is the plan's.** `omniweave_core.host.wire` already
owns a `MAX_BODY_BYTES`, at `INLINE_MAX` = 262,144 bytes, for seam S4's frame body. Two constants
with one name and two values, both answering "how large may a body be", is precisely the collision
charter section 5 X20 rules on when it insists the framing module is `wire.py` and not `frames.py`
-- *"two names for two things is the rule"*. D348 records that the plan reuses a name it has
already spent, and a test below holds the two values apart so the divergence cannot be mistaken
for a drift.
"""

MEDIA_TYPE: Final = "application/json"
"""The one content type this transport parses. Anything else is a 415 before parsing."""

HEADER_ORIGIN: Final = "origin"
HEADER_HOST: Final = "host"
HEADER_API_KEY: Final = "x-api-key"
HEADER_AUTHORIZATION: Final = "authorization"
HEADER_CONTENT_TYPE: Final = "content-type"
HEADER_CONTENT_LENGTH: Final = "content-length"

BEARER: Final = "bearer"
"""`Authorization: Bearer <token>`, the scheme compared case-insensitively per RFC 6750."""

OPEN_ROUTES: Final = ("/healthz", "/readyz")
"""10:2317's two unauthenticated routes. Liveness and readiness, and no inventory."""

_REASONS: Final = {
    403: "forbidden",
    401: "unauthorized",
    415: "unsupported_media_type",
    413: "payload_too_large",
}
"""The whole vocabulary a refusal may use. 10:2333 fixes `401 {"error":"unauthorized"}` and the
other three follow it rather than inventing a body shape per status."""


@dataclass(frozen=True, slots=True)
class Rejection:
    """One HTTP refusal: the status the caller sees and the symbol the log records.

    `symbol` is `""` for the three statuses the plan allocates no `OW-*` code to. It is carried on
    the object and never rendered, because the body is what crosses the boundary and an error code
    in it would tell an unauthenticated caller which check it failed.
    """

    status: int
    symbol: str = ""

    def reason(self) -> str:
        """The single word this status is allowed to say."""
        return _REASONS[self.status]

    def body(self) -> bytes:
        """The whole response body. `{"error":"unauthorized"}` is 10:2333's, verbatim."""
        return b'{"error":"' + self.reason().encode("ascii") + b'"}'


@dataclass(frozen=True, slots=True)
class EnabledDriver:
    """One row of `[drivers] enabled`, as much of it as the listener conjunct reads.

    `restriction_bits` rather than a `LicenceFacts`: 04:1873 makes stamping the bits the runner's
    job under INV-16, so by the time a listener opens they are computed and this module has no
    business recomputing them from a card it would have to load.
    """

    driver_id: str
    spdx: str
    licence_sha256: str
    restriction_bits: int

    def network_copyleft(self) -> bool:
        """Whether this driver's tier carries `copyleft_network`."""
        return bool(self.restriction_bits & (1 << Restriction.COPYLEFT_NETWORK))


def headers_of(raw: Iterable[tuple[bytes, bytes]]) -> dict[str, tuple[str, ...]]:
    """ASGI's raw header list as a table, with duplicates KEPT.

    ASGI guarantees lowercase names, and this lowercases anyway: a guard that trusted a promise
    the client half of it never made would be checking a header that is not the one present. Values
    are decoded as latin-1, which is what a header is on the wire and never UTF-8; a non-ASCII byte
    therefore round-trips to something that matches no allowlist entry rather than raising.
    """
    table: dict[str, list[str]] = {}
    for name, value in raw:
        table.setdefault(name.decode("latin-1").strip().lower(), []).append(
            value.decode("latin-1").strip()
        )
    return {name: tuple(values) for name, values in table.items()}


def is_loopback(authority: str) -> bool:
    """Whether an authority names this machine and only this machine.

    Takes a `Host` header or a bind address: `127.0.0.1`, `127.0.0.1:8000`, `[::1]:8000`,
    `localhost`. `0.0.0.0` and `::` are NOT loopback and that is the case the whole rule exists
    for -- they are every interface, which is the bind an operator makes by habit and the one that
    puts a corpus on the network.
    """
    host = _authority_name(authority)
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def listener_refusal(*, bind: str, api_key: str) -> UsageError | None:
    """`OW-A-040` when a non-loopback bind carries no key. `None` means the listener may open.

    A loopback bind with no key is the sanctioned case and 01:1099 counts it: `ow serve --http` is
    one of exactly two loopback TCP endpoints the framework sanctions, and a third needs a charter
    amendment.
    """
    if is_loopback(bind) or api_key:
        return None
    return UsageError(
        f"refusing to bind {bind}: a non-loopback listener serves the corpus to the network and "
        f"no API key was given",
        symbol="OW_HTTP_BIND_UNAUTHENTICATED",
        fix="ow serve --http --api-key <key>   # or set OMNIWEAVE_API_KEY, or bind 127.0.0.1",
    )


def copyleft_refusal(drivers: Sequence[EnabledDriver]) -> PolicyRefusal | None:
    """`OW-A-043` when any enabled driver's tier carries `copyleft_network`.

    The refusal names the driver, the SPDX expression and the `licence_sha256` the acknowledgement
    is bound to, because an operator cannot act on "a licence problem" and can act on those three.
    Every offending driver is named rather than the first: a roster with two of them would
    otherwise cost two restarts to discover.
    """
    offenders = [row for row in drivers if row.network_copyleft()]
    if not offenders:
        return None
    named = "; ".join(f"{row.driver_id} ({row.spdx}, {row.licence_sha256})" for row in offenders)
    return PolicyRefusal(
        f"ow serve --http engages the network clause the shipped acknowledgement disclaims: "
        f"{named}",
        symbol="OW_SERVE_COPYLEFT_NETWORK",
        fix="ow config set drivers.enabled <the roster without it>   # or serve over stdio",
    )


def rebinding_rejection(
    headers: Mapping[str, tuple[str, ...]],
    *,
    allowed_origins: Sequence[str],
    allowed_hosts: Sequence[str],
) -> Rejection | None:
    """`OW-A-041`, 403, before the API-key comparison. Three clauses, one status.

    An empty `allowed_origins` rejects every request carrying an `Origin` at all, which is the
    shipped default and is deliberate: an MCP client is not a browser and sends none, so a request
    that has one came from a page.
    """
    origins = headers.get(HEADER_ORIGIN, ())
    hosts = headers.get(HEADER_HOST, ())
    if len(origins) > 1 or len(hosts) > 1:
        return Rejection(403, "OW_HTTP_ORIGIN_REJECTED")
    if origins and origins[0] not in allowed_origins:
        return Rejection(403, "OW_HTTP_ORIGIN_REJECTED")
    if hosts:
        name = _authority_name(hosts[0])
        if not is_loopback(name) and name not in {_authority_name(h) for h in allowed_hosts}:
            return Rejection(403, "OW_HTTP_ORIGIN_REJECTED")
    return None


def auth_rejection(headers: Mapping[str, tuple[str, ...]], *, api_key: str) -> Rejection | None:
    """401 unless exactly one of the two accepted headers carries the key.

    `hmac.compare_digest` on both paths, because a `==` over a secret is a timing oracle and the
    cost of not having one is one function call. A server running without a key accepts everything
    -- that is the loopback case `listener_refusal()` already gated -- and a request that offers a
    key to a server that has none is accepted rather than refused, because the key is the server's
    requirement and never the client's assertion.
    """
    if not api_key:
        return None
    expected = api_key.encode("utf-8")
    presented = headers.get(HEADER_API_KEY, ())
    if len(presented) == 1 and hmac.compare_digest(presented[0].encode("utf-8"), expected):
        return None
    authorization = headers.get(HEADER_AUTHORIZATION, ())
    if len(authorization) == 1:
        scheme, _, token = authorization[0].partition(" ")
        if scheme.lower() == BEARER and hmac.compare_digest(token.encode("utf-8"), expected):
            return None
    return Rejection(401)


def payload_rejection(headers: Mapping[str, tuple[str, ...]]) -> Rejection | None:
    """415 for anything that is not JSON, then 413 above `MAX_REQUEST_BYTES`.

    The media type is matched on the type alone, so `application/json; charset=utf-8` is accepted;
    a `content-length` that is absent or unparseable is NOT rejected here, because a chunked body
    has none and bounding what actually arrives is the reader's job rather than this table's.
    """
    content_type = headers.get(HEADER_CONTENT_TYPE, ())
    if len(content_type) > 1:
        return Rejection(415)
    if content_type and content_type[0].partition(";")[0].strip().lower() != MEDIA_TYPE:
        return Rejection(415)
    lengths = headers.get(HEADER_CONTENT_LENGTH, ())
    if len(lengths) > 1:
        return Rejection(413)
    if lengths and lengths[0].isdigit() and int(lengths[0]) > MAX_REQUEST_BYTES:
        return Rejection(413)
    return None


def gate(
    headers: Mapping[str, tuple[str, ...]],
    *,
    path: str,
    api_key: str,
    allowed_origins: Sequence[str],
    allowed_hosts: Sequence[str],
) -> Rejection | None:
    """The four checks in the one order that is defensible. `None` means the request may proceed.

    `path` exempts `/healthz` and `/readyz` from the key and from nothing else: 10:2317 gives them
    `auth: none` and a load balancer needs a boolean. The rebinding guard still applies to them,
    which is the conservative of the two readings the plan leaves open (D349).
    """
    rejection = rebinding_rejection(
        headers, allowed_origins=allowed_origins, allowed_hosts=allowed_hosts
    )
    if rejection is not None:
        return rejection
    if path not in OPEN_ROUTES:
        rejection = auth_rejection(headers, api_key=api_key)
        if rejection is not None:
            return rejection
    return payload_rejection(headers)


def _authority_name(authority: str) -> str:
    """The name out of `host[:port]`, `[v6]:port` or a bare address. Lowercased, port dropped."""
    text = authority.strip().lower()
    if text.startswith("["):
        return text[1 : text.index("]")] if "]" in text else ""
    if text.count(":") == 1:
        return text.rpartition(":")[0]
    return text
