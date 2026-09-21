"""The five refusals, and the one order they may happen in. 10-interfaces.md section 10.

**Every red case here is an attack or an operator mistake, not a schema violation.** A DNS-rebound
origin, a duplicated `Host`, a bearer token that differs in its last byte, a bind to `0.0.0.0` with
no key: each is a request or an argument that a server without this module would serve.

**Two properties are asserted about what a refusal SAYS, not only about its status.** A body that
echoed the rejected origin, or named `allowed_hosts`, would hand an unauthenticated caller the
configuration it just failed -- which is the inventory 10:2325 shapes `/healthz` and `/readyz` to
withhold, leaking through the error path instead.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import omniweave_serve.guard as guard_module
import pytest
from omniweave_core.config import KEYS
from omniweave_core.errors import PolicyRefusal, UsageError
from omniweave_core.host import wire
from omniweave_ports import Restriction
from omniweave_serve.guard import (
    BEARER,
    HEADER_API_KEY,
    HEADER_AUTHORIZATION,
    HEADER_CONTENT_LENGTH,
    HEADER_CONTENT_TYPE,
    HEADER_HOST,
    HEADER_ORIGIN,
    MAX_REQUEST_BYTES,
    MEDIA_TYPE,
    OPEN_ROUTES,
    EnabledDriver,
    Rejection,
    auth_rejection,
    copyleft_refusal,
    gate,
    headers_of,
    is_loopback,
    listener_refusal,
    payload_rejection,
    rebinding_rejection,
)

KEY = "s3cret-key-value"
"""One key, long enough that a prefix comparison would pass where a digest comparison does not."""


def _headers(**named: str | list[str]) -> dict[str, tuple[str, ...]]:
    """A header table from keyword arguments; a list value is a DUPLICATED header."""
    out: dict[str, tuple[str, ...]] = {}
    for name, value in named.items():
        wire_name = name.replace("_", "-")
        out[wire_name] = tuple(value) if isinstance(value, list) else (value,)
    return out


def _driver(**over: object) -> EnabledDriver:
    base: dict[str, object] = {
        "driver_id": "parse.pdf.pdfium",
        "spdx": "Apache-2.0",
        "licence_sha256": "sha256:37a680",
        "restriction_bits": 0,
    }
    base.update(over)
    return EnabledDriver(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------
# What counts as this machine
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "authority",
    ["127.0.0.1", "127.0.0.1:8000", "127.1.2.3", "localhost", "localhost:8000", "::1", "[::1]:800"],
)
def test_these_authorities_name_this_machine(authority: str) -> None:
    assert is_loopback(authority) is True


@pytest.mark.parametrize(
    "authority",
    # S104 flags the literal as a bind to all interfaces. It IS one, written down so the guard
    # can be shown to refuse it: this list is the red half of `OW-A-040`, not a configuration.
    ["0.0.0.0", "0.0.0.0:8000", "::", "[::]:8000", "192.168.1.4", "example.com", "", "[bad"],  # noqa: S104
)
def test_these_do_not(authority: str) -> None:
    """`0.0.0.0` and `::` are every interface. They are the bind an operator makes by habit and
    the whole reason `OW-A-040` exists."""
    assert is_loopback(authority) is False


def test_the_shipped_allowed_hosts_are_all_loopback_names() -> None:
    """The default `{"localhost", "127.0.0.1", "[::1]"}` adds nothing the literal check misses,
    which is what makes it a safe default rather than a widening."""
    declared = KEYS["serve.allowed_hosts"].default
    assert isinstance(declared, tuple)
    assert all(is_loopback(str(host)) for host in declared)


# ---------------------------------------------------------------------------------------------
# The listener, which may refuse to open at all
# ---------------------------------------------------------------------------------------------


def test_a_non_loopback_bind_without_a_key_refuses_to_start() -> None:
    error = listener_refusal(bind="0.0.0.0:8000", api_key="")
    assert isinstance(error, UsageError)
    assert error.code() == "OW_HTTP_BIND_UNAUTHENTICATED"
    assert error.numeric() == "OW-A-040"
    assert error.EXIT == 1, "10:2338 fixes the exit at 1"
    assert "--api-key" in error.fix
    assert "OMNIWEAVE_API_KEY" in error.fix, "the message names the flag AND the env var"


def test_a_loopback_bind_without_a_key_is_the_sanctioned_case() -> None:
    assert listener_refusal(bind="127.0.0.1:8000", api_key="") is None


def test_a_non_loopback_bind_with_a_key_opens() -> None:
    assert listener_refusal(bind="0.0.0.0:8000", api_key=KEY) is None


def test_the_refusal_does_not_print_the_key_that_was_missing() -> None:
    """There is nothing to print, and the assertion is here so that a later edit adding a
    `got {api_key!r}` cannot pass."""
    error = listener_refusal(bind="10.0.0.5", api_key="")
    assert error is not None
    assert KEY not in str(error)


# ---------------------------------------------------------------------------------------------
# The licence conjunct, checked where the listener is opened
# ---------------------------------------------------------------------------------------------


def test_a_network_copyleft_driver_refuses_the_listener() -> None:
    offender = _driver(
        driver_id="parse.page.olmocr",
        spdx="AGPL-3.0-only",
        licence_sha256="sha256:9c1e77",
        restriction_bits=1 << Restriction.COPYLEFT_NETWORK,
    )
    error = copyleft_refusal([_driver(), offender])
    assert isinstance(error, PolicyRefusal)
    assert error.code() == "OW_SERVE_COPYLEFT_NETWORK"
    assert error.numeric() == "OW-A-043"
    assert error.EXIT == 6, "a licence refusal is a grant, not an edit"


def test_the_refusal_names_the_driver_the_expression_and_the_digest() -> None:
    """An operator cannot act on "a licence problem" and can act on those three."""
    offender = _driver(
        driver_id="parse.page.olmocr",
        spdx="AGPL-3.0-only",
        licence_sha256="sha256:9c1e77",
        restriction_bits=1 << Restriction.COPYLEFT_NETWORK,
    )
    message = str(copyleft_refusal([offender]))
    assert "parse.page.olmocr" in message
    assert "AGPL-3.0-only" in message
    assert "sha256:9c1e77" in message


def test_every_offender_is_named_and_not_only_the_first() -> None:
    """A roster with two would otherwise cost two restarts to discover."""
    bits = 1 << Restriction.COPYLEFT_NETWORK
    rows = [
        _driver(driver_id="a", restriction_bits=bits),
        _driver(driver_id="b", restriction_bits=bits),
    ]
    message = str(copyleft_refusal(rows))
    assert "a (" in message
    assert "b (" in message


def test_the_offer_of_a_way_out_names_both() -> None:
    """10:2349's two: remove the driver, or serve over stdio, which is not a network transport."""
    error = copyleft_refusal([_driver(restriction_bits=1 << Restriction.COPYLEFT_NETWORK)])
    assert error is not None
    assert "drivers.enabled" in error.fix
    assert "stdio" in error.fix


@pytest.mark.parametrize(
    "restriction",
    [r for r in Restriction if r is not Restriction.COPYLEFT_NETWORK],
)
def test_no_other_restriction_closes_the_listener(restriction: Restriction) -> None:
    """Eleven of the twelve codes are accepted here. `copyleft_strong` included: section 13 is the
    NETWORK clause and a listening transport is what engages it."""
    assert copyleft_refusal([_driver(restriction_bits=1 << restriction)]) is None


def test_an_empty_roster_opens() -> None:
    assert copyleft_refusal([]) is None


# ---------------------------------------------------------------------------------------------
# The rebinding guard
# ---------------------------------------------------------------------------------------------


def _rebinding(headers: dict[str, tuple[str, ...]], **over: object) -> Rejection | None:
    settings: dict[str, object] = {"allowed_origins": (), "allowed_hosts": ("localhost",)}
    settings.update(over)
    return rebinding_rejection(headers, **settings)  # type: ignore[arg-type]


def test_any_origin_at_all_is_rejected_under_the_shipped_default() -> None:
    """`allowed_origins` ships EMPTY, and that is the DNS-rebinding guard: an MCP client is not a
    browser and sends none, so a request carrying one came from a page."""
    assert KEYS["serve.allowed_origins"].default == ()
    rejection = _rebinding(_headers(origin="https://evil.example", host="127.0.0.1"))
    assert rejection is not None
    assert rejection.status == 403
    assert rejection.symbol == "OW_HTTP_ORIGIN_REJECTED"


def test_a_request_with_no_origin_passes() -> None:
    assert _rebinding(_headers(host="127.0.0.1:8000")) is None


def test_an_allowed_origin_passes() -> None:
    headers = _headers(origin="https://app.example", host="localhost")
    assert _rebinding(headers, allowed_origins=("https://app.example",)) is None


def test_a_rebound_host_is_rejected_even_when_it_resolves_to_loopback() -> None:
    """The attack: a DNS-rebound name whose A record is 127.0.0.1. The browser sends the NAME."""
    rejection = _rebinding(_headers(host="rebind.attacker.example"))
    assert rejection is not None
    assert rejection.status == 403


def test_a_host_in_allowed_hosts_passes_and_its_port_is_ignored() -> None:
    assert _rebinding(_headers(host="omni.internal:8443"), allowed_hosts=("omni.internal",)) is None


@pytest.mark.parametrize("header", [HEADER_ORIGIN, HEADER_HOST])
def test_a_duplicated_gate_header_is_rejected(header: str) -> None:
    """ASGI hands the middleware a LIST of pairs. A guard reading the first while something
    downstream reads the last would be checking a different request from the one served."""
    headers: dict[str, tuple[str, ...]] = {HEADER_HOST: ("127.0.0.1",)}
    headers[header] = ("127.0.0.1", "evil.example")
    rejection = _rebinding(headers)
    assert rejection is not None
    assert rejection.status == 403


def test_the_rejection_does_not_echo_what_it_rejected() -> None:
    """The error path is not a channel for the configuration the caller just failed."""
    headers = _headers(origin="https://evil.example", host="rebind.attacker.example")
    rejection = _rebinding(headers, allowed_origins=("https://app.example",))
    assert rejection is not None
    text = rejection.body().decode("ascii")
    assert "evil.example" not in text
    assert "app.example" not in text
    assert "attacker" not in text
    assert "OW_HTTP" not in text, "the symbol is for the log, never for the wire"
    assert json.loads(text) == {"error": "forbidden"}


# ---------------------------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------------------------


def test_the_api_key_header_is_accepted() -> None:
    assert auth_rejection(_headers(x_api_key=KEY), api_key=KEY) is None


def test_a_bearer_token_is_accepted_and_the_scheme_is_case_insensitive() -> None:
    """RFC 6750 compares the scheme case-insensitively, and a client that sends `BEARER` is not
    making a mistake this server gets to punish."""
    for scheme in ("Bearer", "bearer", "BEARER", "BeArEr"):
        assert auth_rejection(_headers(authorization=f"{scheme} {KEY}"), api_key=KEY) is None


def test_the_scheme_constant_is_the_one_being_compared() -> None:
    assert BEARER == "bearer"


def test_the_header_names_are_the_lowercase_wire_spellings() -> None:
    """`headers_of()` lowercases, so a constant carrying `X-Api-Key` would match nothing and the
    guard would fail open on the header it exists to read."""
    for name in (
        HEADER_ORIGIN,
        HEADER_HOST,
        HEADER_API_KEY,
        HEADER_AUTHORIZATION,
        HEADER_CONTENT_TYPE,
        HEADER_CONTENT_LENGTH,
    ):
        assert name == name.lower()
        assert " " not in name
    table = headers_of([(b"Authorization", b"Bearer x"), (b"X-Api-Key", b"y")])
    assert set(table) == {HEADER_AUTHORIZATION, HEADER_API_KEY}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        _headers(x_api_key=""),
        _headers(x_api_key=KEY + "x"),
        _headers(x_api_key=KEY[:-1]),
        _headers(authorization=KEY),
        _headers(authorization=f"Basic {KEY}"),
        _headers(authorization=f"Bearer {KEY}x"),
        _headers(authorization="Bearer"),
        _headers(x_api_key=[KEY, KEY]),
        _headers(authorization=[f"Bearer {KEY}", f"Bearer {KEY}"]),
    ],
)
def test_everything_else_is_401(headers: dict[str, tuple[str, ...]]) -> None:
    rejection = auth_rejection(headers, api_key=KEY)
    assert rejection is not None
    assert rejection.status == 401
    assert rejection.symbol == "", "the plan allocates no OW-* code to a 401"


def test_a_prefix_of_the_key_does_not_pass() -> None:
    """The property `hmac.compare_digest` is here for: a comparison that stopped early would make
    the key discoverable one byte at a time."""
    for length in range(1, len(KEY)):
        assert auth_rejection(_headers(x_api_key=KEY[:length]), api_key=KEY) is not None


def test_a_server_with_no_key_accepts_everything() -> None:
    """The loopback case `listener_refusal()` already gated. A key is the SERVER's requirement."""
    assert auth_rejection({}, api_key="") is None
    assert auth_rejection(_headers(x_api_key="anything"), api_key="") is None


def test_the_401_body_is_the_one_the_plan_prints() -> None:
    """10:2333: `401 {"error":"unauthorized"}`, verbatim."""
    rejection = auth_rejection({}, api_key=KEY)
    assert rejection is not None
    assert rejection.body() == b'{"error":"unauthorized"}'


# ---------------------------------------------------------------------------------------------
# The payload, bounded before anything is parsed
# ---------------------------------------------------------------------------------------------


def test_a_body_over_the_cap_is_413() -> None:
    rejection = payload_rejection(
        _headers(content_type=MEDIA_TYPE, content_length=str(MAX_REQUEST_BYTES + 1))
    )
    assert rejection is not None
    assert rejection.status == 413


def test_a_body_at_the_cap_is_served() -> None:
    headers = _headers(content_type=MEDIA_TYPE, content_length=str(MAX_REQUEST_BYTES))
    assert payload_rejection(headers) is None


def test_a_charset_parameter_does_not_make_json_unsupported() -> None:
    assert payload_rejection(_headers(content_type="application/json; charset=utf-8")) is None
    assert payload_rejection(_headers(content_type="APPLICATION/JSON")) is None


@pytest.mark.parametrize("media", ["text/plain", "application/xml", "", "application/json-seq"])
def test_anything_that_is_not_json_is_415(media: str) -> None:
    rejection = payload_rejection(_headers(content_type=media))
    assert rejection is not None
    assert rejection.status == 415


def test_an_absent_or_unparseable_content_length_is_not_rejected_here() -> None:
    """A chunked body has none, and bounding what actually arrives is the reader's job rather
    than this table's -- a guard that refused an absent length would refuse a legal request."""
    assert payload_rejection(_headers(content_type=MEDIA_TYPE)) is None
    assert payload_rejection(_headers(content_type=MEDIA_TYPE, content_length="chunked")) is None


@pytest.mark.parametrize("header", [HEADER_CONTENT_TYPE, HEADER_CONTENT_LENGTH])
def test_a_duplicated_payload_header_is_refused(header: str) -> None:
    """Two `content-length` values is request smuggling's whole shape."""
    headers = {header: (MEDIA_TYPE if header == HEADER_CONTENT_TYPE else "10",) * 2}
    assert payload_rejection(headers) is not None


def test_the_cap_is_the_plans_number_and_not_the_seam_s4_one() -> None:
    """D348. `omniweave_core.host.wire.MAX_BODY_BYTES` is a DIFFERENT constant with a DIFFERENT
    value, and the plan spells this one with that name. Two names for two things is the rule."""
    assert MAX_REQUEST_BYTES == 1_048_576
    assert wire.MAX_BODY_BYTES == 262_144
    assert MAX_REQUEST_BYTES != wire.MAX_BODY_BYTES


# ---------------------------------------------------------------------------------------------
# The order, which is the point of `gate()`
# ---------------------------------------------------------------------------------------------


def _gate(headers: dict[str, tuple[str, ...]], **over: object) -> Rejection | None:
    settings: dict[str, object] = {
        "path": "/mcp",
        "api_key": KEY,
        "allowed_origins": (),
        "allowed_hosts": ("localhost",),
    }
    settings.update(over)
    return gate(headers, **settings)  # type: ignore[arg-type]


def test_origin_is_checked_before_the_key() -> None:
    """10:2355, and the assertion is a request that fails BOTH: it must answer 403."""
    headers = _headers(origin="https://evil.example", host="127.0.0.1")
    rejection = _gate(headers)
    assert rejection is not None
    assert rejection.status == 403


def test_the_key_is_checked_before_the_media_type() -> None:
    headers = _headers(host="127.0.0.1", content_type="text/plain")
    rejection = _gate(headers)
    assert rejection is not None
    assert rejection.status == 401


def test_the_key_is_checked_before_the_size_so_the_cap_is_not_discoverable() -> None:
    """The whole reason the cheapest check is last: a caller who could tell 413 from 401 would
    learn `MAX_REQUEST_BYTES` by bisection without ever holding a key."""
    headers = _headers(
        host="127.0.0.1",
        content_type=MEDIA_TYPE,
        content_length=str(MAX_REQUEST_BYTES * 64),
    )
    rejection = _gate(headers)
    assert rejection is not None
    assert rejection.status == 401


def test_the_media_type_is_checked_before_the_size() -> None:
    headers = _headers(
        host="127.0.0.1",
        x_api_key=KEY,
        content_type="text/plain",
        content_length=str(MAX_REQUEST_BYTES + 1),
    )
    rejection = _gate(headers)
    assert rejection is not None
    assert rejection.status == 415


def test_a_well_formed_authenticated_request_passes() -> None:
    headers = _headers(
        host="127.0.0.1:8000",
        x_api_key=KEY,
        content_type=MEDIA_TYPE,
        content_length="512",
    )
    assert _gate(headers) is None


@pytest.mark.parametrize("path", OPEN_ROUTES)
def test_the_health_routes_need_no_key(path: str) -> None:
    """10:2317 gives both `auth: none`. A load balancer needs a boolean, not a credential."""
    assert _gate(_headers(host="127.0.0.1"), path=path) is None


@pytest.mark.parametrize("path", OPEN_ROUTES)
def test_the_health_routes_are_still_behind_the_rebinding_guard(path: str) -> None:
    """D349. The plan gives them `auth: none` and says nothing about `Origin`; this is the
    conservative of the two readings, and it is asserted so the choice is visible if it changes."""
    rejection = _gate(_headers(origin="https://evil.example", host="127.0.0.1"), path=path)
    assert rejection is not None
    assert rejection.status == 403


def test_the_open_routes_are_exactly_the_two_the_table_lists() -> None:
    assert OPEN_ROUTES == ("/healthz", "/readyz")


# ---------------------------------------------------------------------------------------------
# The header table ASGI actually hands over
# ---------------------------------------------------------------------------------------------


def test_raw_asgi_headers_become_a_table_with_duplicates_kept() -> None:
    raw = [(b"Host", b" 127.0.0.1 "), (b"host", b"evil.example"), (b"X-Api-Key", b"k")]
    table = headers_of(raw)
    assert table[HEADER_HOST] == ("127.0.0.1", "evil.example")
    assert table[HEADER_API_KEY] == ("k",)


def test_a_non_ascii_header_byte_does_not_raise() -> None:
    """Latin-1 is what a header is on the wire. A UTF-8 decode would raise on a byte an attacker
    chooses, which turns a header into a crash."""
    table = headers_of([(b"origin", b"https://\xff.example")])
    assert len(table[HEADER_ORIGIN]) == 1
    assert _rebinding({**table, HEADER_HOST: ("127.0.0.1",)}) is not None


def test_an_empty_header_list_is_an_empty_table() -> None:
    assert headers_of([]) == {}


# ---------------------------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------------------------


def _module_tree() -> ast.Module:
    return ast.parse(Path(guard_module.__file__).read_text(encoding="utf-8"))


def test_every_refusal_body_is_one_word_from_a_closed_set() -> None:
    """A body is the only thing that crosses the boundary, so the vocabulary is enumerated rather
    than formatted: nothing here can interpolate a value from the request."""
    for status in (401, 403, 413, 415):
        parsed = json.loads(Rejection(status).body())
        assert set(parsed) == {"error"}
        assert parsed["error"].replace("_", "").isalpha()


def test_the_guard_awaits_nothing_and_opens_no_socket() -> None:
    """The ASGI middleware around this decides nothing, which is why it can be three lines. A
    `socket` or an `asyncio` here would also breach `pyproject.toml`'s banned-api block."""
    tree = _module_tree()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots.isdisjoint({"asyncio", "selectors", "socket", "ssl", "http", "urllib"})
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.Await | ast.AsyncFor | ast.AsyncWith)
    ]


def test_all_names_every_public_symbol_this_module_defines() -> None:
    defined: set[str] = set()
    for node in _module_tree().body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {name for name in defined if not name.startswith("_")} == set(guard_module.__all__)
