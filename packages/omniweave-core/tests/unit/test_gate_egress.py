"""G15 tested as a program: all three clauses, each shown a red.

`tools/gate_egress.py` enforces `14-security.md:776` — *"G15 greps every hostname literal in the
tree against an allowlist **and** runs a socket-blocked conformance pass"* — and the claim it
protects is stated at `14:788`: omniweave has no telemetry, no usage counter, no phone-home licence
check and no update ping, *"not `default off`: **absent**"*.

**An absence is the one property that decays with nobody noticing**, which is why the gate exists
and why this file exists under it. Each clause is shown the violation it was written for, over a
synthetic `packages/*/src/` tree in `tmp_path`:

* a shipped module importing `requests`, and `urllib.request`, and `http.client.HTTPSConnection` —
  with the `urllib.parse` / `urllib.request` split asserted in both directions, because a check
  written against the package rather than the submodule would either refuse `identity.py`'s URI
  joining or admit an HTTP client;
* an unregistered hostname, an IP literal, a URL under a scheme nobody classified, and `0.0.0.0`
  admitted by a `[[literal]]` row and refused anyway by `[[deny]]`;
* a dotted identifier that is NOT a hostname — `parse.pdf.pdfium` is shaped exactly like one, and
  a clause that flagged it would produce several hundred findings and teach everyone to ignore all
  of them;
* the docstring/literal split, asserted against the real `cassette.py`, whose prose contains
  `http://127.0.0.1:0` in a sentence explaining that the code must never fabricate it. A text grep
  flags the file most careful about the rule; this is the test that says so;
* the blocker, shown an unarmed directory, which is the negative control of clause 3 — and the
  clause the gate failed twice while being written, both times for an ordering reason.

Specified in 14-security.md sections 5.1 and 10, 15-observability.md section 9, 11-repo-layout.md
section 6.4, and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REGISTER = """
[allow]
internal_schemes = ["cas", "cassette"]
network_schemes = ["http", "https"]
"""


@pytest.fixture(scope="session")
def gate(repo_root: Path) -> ModuleType:
    """`tools/gate_egress.py`, loaded by path and never put on `sys.path`."""
    path = repo_root / "tools" / "gate_egress.py"
    spec = importlib.util.spec_from_file_location("_owgate_egress", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def register(gate: ModuleType, tmp_path: Path, extra: str = "") -> Any:
    path = tmp_path / "egress.toml"
    path.write_text(REGISTER + extra, encoding="utf-8")
    return gate.Register.load(path)


def shipped(tmp_path: Path, name: str, body: str) -> Path:
    """One file in a synthetic `packages/<dist>/src/` tree, as a wheel would carry it."""
    path = tmp_path / "packages" / "dist" / "src" / "pkg" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def clauses(findings: list[Any]) -> list[str]:
    """The clause of each finding. `Any` because the gate is loaded by path, not imported."""
    return [finding.clause for finding in findings]


# ---------------------------------------------------------------------------
# clause 1 — no network client is linked
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "import requests",
        "import socket",
        "import urllib.request",
        "from http.client import HTTPSConnection",
        "import httpx as h",
        "from smtplib import SMTP",
    ],
)
def test_importing_something_that_can_dial_is_a_finding(
    gate: ModuleType, tmp_path: Path, statement: str
) -> None:
    """A hostname is unreachable without something to dial it with (14:779), so the register of
    things that can dial is shorter and harder to evade than the register of names."""
    path = shipped(tmp_path, "m.py", f"{statement}\n")
    findings = gate.check_clients([path], register(gate, tmp_path))
    assert clauses(findings) == ["client"]
    assert "tools/egress.toml" in findings[0].message


def test_urllib_parse_is_not_a_client_and_urllib_request_is(
    gate: ModuleType, tmp_path: Path
) -> None:
    """THE SPLIT THE CLAUSE TURNS ON. `identity.py` imports `urllib.parse` to join URIs and must
    pass; a check written against `urllib` would either refuse it or admit an HTTP client."""
    ok = shipped(tmp_path, "parse_only.py", "from urllib.parse import urlsplit, urljoin\n")
    bad = shipped(tmp_path, "request_too.py", "from urllib.request import urlopen\n")
    reg = register(gate, tmp_path)
    assert gate.check_clients([ok], reg) == []
    assert clauses(gate.check_clients([bad], reg)) == ["client"]


def test_a_client_row_admits_that_module_at_that_path_and_nowhere_else(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The register holds (module, site) pairs, not blessed modules. `import socket` is correct in
    six files and a finding in a seventh, which is what makes a copy-paste into a new module fail
    rather than inherit somebody else's justification."""
    blessed = shipped(tmp_path, "blessed.py", "import socket\n")
    other = shipped(tmp_path, "other.py", "import socket\n")
    reg = register(
        gate,
        tmp_path,
        f'\n[[client]]\nmodule = "socket"\npath = "{gate.relative(blessed)}"\nwhy = "S4."\n',
    )
    assert gate.check_clients([blessed], reg) == []
    assert clauses(gate.check_clients([other], reg)) == ["client"]


def test_a_function_scope_import_is_seen_too(gate: ModuleType, tmp_path: Path) -> None:
    """`ast.walk` and not a module-scope pass: an import inside a function still links a client,
    and deferring it is exactly how a phone-home avoids an importtime gate."""
    path = shipped(tmp_path, "lazy.py", "def go():\n    import requests\n    return requests\n")
    assert clauses(gate.check_clients([path], register(gate, tmp_path))) == ["client"]


# ---------------------------------------------------------------------------
# clause 2 — every host-shaped literal is registered
# ---------------------------------------------------------------------------


def test_an_unregistered_hostname_is_a_finding(gate: ModuleType, tmp_path: Path) -> None:
    path = shipped(tmp_path, "phone.py", 'ENDPOINT = "https://telemetry.example.com/v1/ingest"\n')
    findings = gate.check_literals([path], register(gate, tmp_path))
    assert clauses(findings) == ["literal"]
    assert "telemetry.example.com" in findings[0].message


def test_an_ip_literal_is_a_finding(gate: ModuleType, tmp_path: Path) -> None:
    path = shipped(tmp_path, "ip.py", 'HOST = "203.0.113.9"\n')
    assert clauses(gate.check_literals([path], register(gate, tmp_path))) == ["literal"]


def test_a_scheme_on_neither_list_is_itself_a_finding(gate: ModuleType, tmp_path: Path) -> None:
    """A scheme is a decision and not a default. This is how an `ssh://` or a `ws://` arrives —
    under a scheme nobody has classified, in a string nobody read."""
    path = shipped(tmp_path, "odd.py", 'URL = "ssh://build@example.com/repo"\n')
    findings = gate.check_literals([path], register(gate, tmp_path))
    assert "ssh://" in findings[0].message
    assert "neither" in findings[0].message


def test_an_internal_scheme_is_not_reported_at_all(gate: ModuleType, tmp_path: Path) -> None:
    """`cas://` addresses a blob and `cassette://` is deliberately undialable. Neither names a
    machine, so neither is a hostname literal."""
    path = shipped(tmp_path, "own.py", 'A = "cas://ab/cd/ef"\nB = "cassette://replay"\n')
    assert gate.check_literals([path], register(gate, tmp_path)) == []


def test_a_dotted_identifier_is_not_a_hostname(gate: ModuleType, tmp_path: Path) -> None:
    """THE FALSE POSITIVE THAT WOULD SINK THE CLAUSE. `parse.pdf.pdfium` is a driver id,
    `serve.packing.cliff_fraction` a config key, `x.ow.unknown` a media-type suffix — all shaped
    exactly like a hostname, and there are several hundred in this repository. A clause that
    flagged them would produce an allowlist nobody reads and a gate everybody skips."""
    path = shipped(
        tmp_path,
        "ids.py",
        'IDS = ["parse.pdf.pdfium", "serve.packing.cliff_fraction", "x.ow.unknown"]\n'
        'MORE = ["cost.model", "derive.segment.spine", "compile.pptx.native"]\n',
    )
    assert gate.check_literals([path], register(gate, tmp_path)) == []


def test_a_registered_literal_passes_at_its_own_path_only(gate: ModuleType, tmp_path: Path) -> None:
    here = shipped(tmp_path, "cfg.py", 'HOSTS = ("localhost", "127.0.0.1")\n')
    elsewhere = shipped(tmp_path, "parser.py", 'HOSTS = ("localhost", "127.0.0.1")\n')
    rows = "".join(
        f'\n[[literal]]\nvalue = "{value}"\npath = "{gate.relative(here)}"\nwhy = "serve."\n'
        for value in ("localhost", "127.0.0.1")
    )
    reg = register(gate, tmp_path, rows)
    assert gate.check_literals([here], reg) == []
    assert clauses(gate.check_literals([elsewhere], reg)) == ["literal", "literal"]


def test_a_denied_value_is_a_finding_even_with_an_allow_row(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The two lists are asymmetrical on purpose. A deny row exists to survive somebody adding the
    matching allow row without reading why it was denied — and `0.0.0.0` is AP-4's own example,
    DataFlow's `--host` default in four places."""
    path = shipped(tmp_path, "bind.py", 'BIND = "0.0.0.0"\n')
    reg = register(
        gate,
        tmp_path,
        f'\n[[literal]]\nvalue = "0.0.0.0"\npath = "{gate.relative(path)}"\nwhy = "I insist."\n'
        '\n[[deny]]\nvalue = "0.0.0.0"\nwhy = "a wildcard bind (AP-4)."\n',
    )
    findings = gate.check_literals([path], reg)
    assert clauses(findings) == ["literal"]
    assert "wildcard bind" in findings[0].message


def test_the_bracketed_loopback_is_reported_once_and_not_twice(
    gate: ModuleType, tmp_path: Path
) -> None:
    """`[::1]` contains `::1`. An unordered pass reports one literal twice and asks for two
    register rows describing the same three bytes."""
    found = gate.host_shaped("[::1]", register(gate, tmp_path))
    assert [value for value, _ in found] == ["[::1]"]


# ---------------------------------------------------------------------------
# prose is not code
# ---------------------------------------------------------------------------


def test_a_hostname_in_a_docstring_is_invisible(gate: ModuleType, tmp_path: Path) -> None:
    """A docstring is prose. This codebase's attribute docstrings are `Expr(Constant(str))` at
    module and class scope, and they are the reason the rule is stated as "the whole value of an
    Expr statement" rather than "the first statement of a scope"."""
    path = shipped(
        tmp_path,
        "prose.py",
        '"""Never fetch from https://evil.example.com — see the note below."""\n\n'
        "VALUE = 1\n"
        '"""Also not https://other.example.com, which we do not contact."""\n'
        "# and not https://commented.example.com either\n",
    )
    assert gate.check_literals([path], register(gate, tmp_path)) == []


def test_a_real_literal_beside_that_docstring_is_still_seen(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The other half. An AST scan that saw nothing would pass this file for the wrong reason."""
    path = shipped(
        tmp_path,
        "both.py",
        '"""We never contact https://evil.example.com."""\n\nURL = "https://real.example.com"\n',
    )
    findings = gate.check_literals([path], register(gate, tmp_path))
    assert clauses(findings) == ["literal"]
    assert "real.example.com" in findings[0].message
    assert "evil" not in findings[0].message


def test_the_live_example_is_cassette_dot_py(gate: ModuleType, repo_root: Path) -> None:
    """THE CASE THIS DISCIPLINE WAS WRITTEN FOR, asserted against the real file.

    `cassette.py:1278` contains the text `http://127.0.0.1:0` inside a docstring explaining that a
    replay handle must NOT fabricate one, because it "would be a lie that looked dialable". A text
    grep flags the file most careful about the rule. The AST scan finds no such literal, because
    there is no such literal.
    """
    path = repo_root / "packages" / "omniweave-core" / "src" / "omniweave_core" / "cassette.py"
    assert "http://127.0.0.1:0" in path.read_text(encoding="utf-8"), "the prose moved"
    assert not any("127.0.0.1" in text for text in gate.scan_strings(path))


# ---------------------------------------------------------------------------
# clause 3 — the amputation, and the control that proves it is armed
# ---------------------------------------------------------------------------


def test_the_blocker_blocks_af_inet_and_leaves_af_unix_alone(
    gate: ModuleType, tmp_path: Path
) -> None:
    """S4's transport is a 0600 unix socket or an owner-only named pipe, and neither can carry a
    byte off the machine. A hook that refused socket creation outright would be asserting the
    driver host is broken rather than that the network is absent."""
    gate.arm(tmp_path)
    assert gate._self_check(tmp_path) == []


def test_the_control_catches_an_unarmed_directory(gate: ModuleType, tmp_path: Path) -> None:
    """Without this, clause 3 passes on a machine where `sitecustomize` never loaded and reports
    the absence of an instrument as the absence of egress. The gate shipped this backwards once —
    the control ran BEFORE the blocker was written, and reported that an empty directory fails to
    block sockets, which is true and says nothing."""
    findings = gate._self_check(tmp_path)
    assert clauses(findings) == ["socket-blocked"]
    assert "measuring nothing" in findings[0].message


def test_the_control_cannot_write_into_the_log_clause_three_reads(
    gate: ModuleType, tmp_path: Path
) -> None:
    """The control DELIBERATELY opens an AF_INET socket. Sharing one directory with the measured
    run made this gate report its own negative control as egress by the driver under test."""
    control, measured = tmp_path / "control", tmp_path / "measured"
    control.mkdir()
    measured.mkdir()
    gate.arm(control)
    measured_log = gate.arm(measured)
    assert gate._self_check(control) == []
    assert not measured_log.exists(), "the control wrote into the measured run's evidence"


# ---------------------------------------------------------------------------
# end to end
# ---------------------------------------------------------------------------


def test_the_static_half_passes_on_this_repository(gate: ModuleType) -> None:
    """The assertion CI makes in the `gates` job."""
    assert gate.main(["--half", "static"]) == 0


def test_the_socket_blocked_half_passes_on_this_repository(gate: ModuleType) -> None:
    """The assertion CI makes in the `conform` job. Spawns a full conformance run with the network
    amputated; it is the most expensive test in the file and the only one that proves the office
    driver parses sixteen fixtures without wanting a socket."""
    assert gate.main(["--half", "conform"]) == 0
