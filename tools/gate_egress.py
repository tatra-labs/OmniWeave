"""G15 — no egress compiled in: the client ban, the hostname grep, and a socket-blocked run.

`14-security.md:776` states the gate in one sentence — *"G15 greps every hostname literal in the
tree against an allowlist **and** runs a socket-blocked conformance pass"* — and
`15-observability.md:2018` repeats it as the first of the five mechanisms by which an operator
verifies that nothing leaves the machine. `01-principles.md:1091` (AP-4) names the three precedents
it exists for, and they are not hypothetical: marker's `--use_llm` ships page images to Gemini **by
default**; DataFlow's `--host` defaults to `0.0.0.0` in four places; jcodemunch ships default-on
telemetry to a vendor endpoint *and* a phone-home licence gate inside the library it asks you to
import. `14-security.md:788` says what omniweave's counter-claim rests on: *"omniweave has no
equivalent code to disable, and G15's hostname allowlist is what keeps that true across releases."*

**The claim is an absence, and an absence decays silently.** That is the whole reason this is a gate
and not a review habit.

**This is the one register row with two jobs** (`tools/gates.toml`): the static half is a source
scan and runs in `gates`, the socket-blocked half needs the twelve conformance suites and runs in
`conform`. `--half` selects; the default runs both.

**What it reads.** Every file a wheel would carry — `packages/*/src/**` — plus `tools/egress.toml`,
the register. `tools/` is deliberately NOT scanned: nothing there is in any
distribution, and this file's own socket-blocking `sitecustomize` would be the first thing a scan
of it tripped over.

**What it asserts**, three clauses:

1. **no network client is linked** — no shipped module imports a network-capable module unless
   `tools/egress.toml` carries a `[[client]]` row for that exact (module, path) pair. This clause
   is the strongest of the three and it is the one the plan argues from rather than about:
   `14:779` justifies `omniweave-office` by saying anydoc is *"a Rust core with eight crates and no
   HTTP client of any kind — no `reqwest`, no `hyper`, no `ureq` — so it structurally cannot SSRF,
   exfiltrate, fetch a remote entity or phone home"*. That argument is available on the Python side
   too, and nothing was checking it. A hostname is unreachable without something to dial it with.
   `urllib.parse` is not a client and `urllib.request` is, so the check is per submodule and not
   per package — `identity.py` imports the first and must pass.
2. **every host-shaped literal is registered** — a URL with a network scheme, an IP literal, or a
   bare name whose last label is a TLD, must have a `[[literal]]` row naming the file it sits in
   and why. A value on `[[deny]]` is a finding whatever else the register says.
3. **a conformance pass with the network amputated** — `ow conform` runs under an audit hook that
   refuses `AF_INET`/`AF_INET6` sockets and `getaddrinfo`, in the driver process *and every child
   it spawns*, and must still pass. `AF_UNIX` is left alone on purpose: S4's transport is a 0600
   unix socket or an owner-only named pipe, and a unix socket cannot leave the machine. A hook that
   blocked socket creation outright would be asserting that the worker is broken.

**Why a grep is the weakest of the three, stated rather than hidden.** A hostname can be spelled
`"".join(["ev", "il.com"])`, assembled from a config value, or read from a file, and no scanner
sees it. That is not a reason to skip clause 2 — it is the reason clauses 1 and 3 exist. Clause 1
removes the means and clause 3 removes the opportunity; clause 2 catches the careless case, which
is also the only case any of the three cited precedents actually is.

**A docstring is prose and a string literal is code.** `.py` files are read with `ast`, and a
`Constant` that is the entire value of an `Expr` statement is skipped — that covers module, class
and function docstrings *and* this codebase's pervasive attribute docstrings. The discipline is
copied from `test_discovery_never_imports.py`'s AST clause, which records why: a naive `in source`
check fails on exactly the file most careful about the rule. The live example here is
`cassette.py:1278`, whose docstring explains that a replay handle must NOT fabricate a dialable
`http://127.0.0.1:0`. A text grep flags that line. An AST scan sees that there is no such literal,
because there isn't one.

Exit 0 clean, 1 with one `G15 FAIL` block per finding, 2 when the gate itself could not run.
Specified in 14-security.md sections 5.1 and 10, 15-observability.md section 9,
11-repo-layout.md section 6.4, and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess  # noqa: TID251 -- clause 3 IS a subprocess with an audit hook in it.
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "NETWORK_MODULES",
    "TLDS",
    "Finding",
    "Register",
    "check_clients",
    "check_literals",
    "check_socket_blocked",
    "host_shaped",
    "main",
    "scan_strings",
    "shipped_files",
]

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "tools" / "egress.toml"
PACKAGES = ROOT / "packages"

NETWORK_MODULES: frozenset[str] = frozenset(
    {
        # stdlib -- anything that can open or speak over a network socket.
        "asyncio",
        "ftplib",
        "http",
        "http.client",
        "imaplib",
        "nntplib",
        "poplib",
        "selectors",
        "smtplib",
        "socket",
        "socketserver",
        "ssl",
        "telnetlib",
        "urllib.request",
        "webbrowser",
        "xmlrpc.client",
        # third party -- the ones a phone-home is actually written with.
        "aiohttp",
        "boto3",
        "botocore",
        "grpc",
        "httpcore",
        "httpx",
        "opentelemetry",
        "requests",
        "urllib3",
        "websockets",
    }
)
"""Modules that can reach a network, named per SUBMODULE where the package splits.

`urllib.parse` is a string parser and `urllib.request` opens a connection, so a check written
against `urllib` would either refuse `identity.py`'s URI joining or admit an HTTP client. Two names
here are already banned by a different rule and are listed anyway, because a gate that passes by
relying on another gate is a gate with a dependency nobody recorded: `asyncio` is INV-3's
(`omniweave/run/` only) and `opentelemetry` is `omniweave_serve.otlp`'s.

The plan's own strongest egress argument is of exactly this shape and about a different language:
14:779 clears `omniweave-office` by observing that anydoc links "eight crates and no HTTP client of
any kind". This is that argument, made checkable for the Python side."""

TLDS: frozenset[str] = frozenset(
    {
        "ai", "app", "cloud", "co", "com", "dev", "edu", "eu", "gov", "im", "info", "io", "me",
        "net", "org", "sh", "so", "tech", "to", "tv", "uk", "us", "xyz", "ws",
    }
)  # fmt: skip
"""Last labels that make a dotted string a plausible hostname rather than an identifier.

**A heuristic, and the gate says so rather than implying completeness.** A dotted literal is the
single most ambiguous thing in this codebase: `parse.pdf.pdfium` is a driver id,
`serve.packing.cliff_fraction` is a config key, `x.ow.unknown` is a media-type suffix and
`cost.model` is a card table -- all four are shaped exactly like a hostname, and there are several
hundred of them. Matching "two or more dot-separated labels" would produce hundreds of findings and
one enormous allowlist, which is a gate nobody reads.

So the discriminator is the last label, and the set is small and common rather than the IANA list:
a public-suffix table is 1,400 entries that would need updating, and would be a second home for a
fact this repository has no other use for. The gap -- a hostname under an exotic TLD -- is what
clauses 1 and 3 are for, and it is named in this module's docstring rather than left to be
discovered."""

_SCHEME_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]{1,31})://([^/\s\"'<>)]*)")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOTTED_RE = re.compile(r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+([a-z]{2,24})\b", re.I)
_LOOPBACK = frozenset({"localhost", "::1", "[::1]", "ip6-localhost"})

SKIP_SUFFIXES = frozenset({".bin", ".pyc", ".pyo", ".so", ".pyd", ".dylib"})
"""Binary package data. A byte scan of a fixture designed to be invalid UTF-8 reports noise."""


# ---------------------------------------------------------------------------
# the register
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Register:
    """`tools/egress.toml`, parsed. Every row is a decision somebody wrote down."""

    internal_schemes: frozenset[str]
    network_schemes: frozenset[str]
    literals: tuple[tuple[str, str], ...]
    """(value, path) pairs. The path is load-bearing: a loopback literal is fine in the config
    table that defines `serve.allowed_hosts` and is a question anywhere else."""
    clients: tuple[tuple[str, str], ...]
    """(module, path) pairs, same reasoning. `import socket` is correct in exactly six files."""
    denied: tuple[tuple[str, str], ...]
    """(value, why). A denied value is a finding even if a `[[literal]]` row admits it — the two
    lists are not symmetrical on purpose, because a deny row exists to survive someone adding the
    matching allow row without reading why it was denied."""

    @classmethod
    def load(cls, path: Path) -> Register:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
        allow = table.get("allow", {})
        return cls(
            internal_schemes=frozenset(allow.get("internal_schemes", [])),
            network_schemes=frozenset(allow.get("network_schemes", [])),
            literals=tuple(
                (str(row.get("value", "")), str(row.get("path", "")))
                for row in table.get("literal", [])
            ),
            clients=tuple(
                (str(row.get("module", "")), str(row.get("path", "")))
                for row in table.get("client", [])
            ),
            denied=tuple(
                (str(row.get("value", "")), str(row.get("why", "")))
                for row in table.get("deny", [])
            ),
        )

    def allows_literal(self, value: str, relative: str) -> bool:
        return any(v == value and p == relative for v, p in self.literals)

    def allows_client(self, module: str, relative: str) -> bool:
        return any(m == module and p == relative for m, p in self.clients)

    def denial(self, value: str) -> str | None:
        for denied, why in self.denied:
            if denied == value:
                return why
        return None


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation: which clause, where, and what is wrong."""

    clause: str
    where: str
    message: str

    def block(self) -> str:
        return f"G15 FAIL  [{self.clause}]  {self.where}\n          {self.message}"


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


# ---------------------------------------------------------------------------
# what ships
# ---------------------------------------------------------------------------


def shipped_files(root: Path = PACKAGES) -> list[Path]:
    """Every file a wheel would carry, in a stable order.

    `packages/*/src/**` and nothing else. `tests/`, `fixtures/` at the distribution root and
    `tools/` are all outside a wheel — and `tools/` is where this gate's own socket-blocking
    `sitecustomize` is written, which a scan of it would report as compiled-in egress.
    """
    found: list[Path] = []
    for src in sorted(root.glob("*/src")):
        for path in sorted(src.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in SKIP_SUFFIXES:
                continue
            found.append(path)
    return found


def relative(path: Path) -> str:
    """Repo-relative POSIX, or the path itself when it is not under the repository.

    The fallback is what lets this gate's own tests point `check_clients` and `check_literals` at a
    synthetic tree in `tmp_path`. A `relative_to` that raised would leave every clause testable
    only against the repository it guards — which is the one tree where they must all already
    pass, so every test would be a tautology.
    """
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# clause 1 -- no network client is linked
# ---------------------------------------------------------------------------


def _imported_modules(tree: ast.AST) -> set[str]:
    """Every module name imported at any scope, dotted and un-aliased.

    `from urllib.parse import urlsplit` yields `urllib.parse` and not `urllib`, which is the
    distinction the whole clause turns on. `from . import x` has no module name and is skipped:
    a relative import cannot reach the standard library.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _network_name(module: str) -> str | None:
    """The registered name a module matches, or `None`.

    An exact hit wins; otherwise the LONGEST registered prefix does, so
    `http.client.HTTPSConnection` matches `http.client` and not `http` — both are registered, and
    an arbitrary-order scan over a `frozenset` picked whichever came out first, which made one
    import statement report under two different names and ask for two register rows. `urllib.parse`
    matches nothing, which is the whole point of naming submodules.
    """
    if module in NETWORK_MODULES:
        return module
    candidates = [name for name in NETWORK_MODULES if module.startswith(name + ".")]
    return max(candidates, key=len) if candidates else None


def check_clients(files: list[Path], register: Register) -> list[Finding]:
    """No shipped module imports something that can dial, without a row saying why."""
    findings: list[Finding] = []
    for path in files:
        if path.suffix != ".py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            findings.append(Finding("client", relative(path), f"unparseable: {error}"))
            continue
        # One finding per REGISTERED NAME, not per imported name. `from urllib.request import
        # urlopen` yields both `urllib.request` and `urllib.request.urlopen`, and both match the
        # same row -- so an undeduplicated pass reports one import statement twice and asks for one
        # row to be added twice. The shortest spelling that matched is the one quoted back, which
        # is the one the register row will carry.
        hits: dict[str, str] = {}
        for module in sorted(_imported_modules(tree)):
            hit = _network_name(module)
            if hit is not None and hit not in hits:
                hits[hit] = module
        for hit, module in sorted(hits.items()):
            if register.allows_client(hit, relative(path)):
                continue
            findings.append(
                Finding(
                    "client",
                    relative(path),
                    f"imports {module!r}, which can open a network connection, and "
                    f"tools/egress.toml has no [[client]] row for "
                    f'module = "{hit}" at this path. A hostname is unreachable without '
                    f"something to dial it with (14:779)",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# clause 2 -- every host-shaped literal is registered
# ---------------------------------------------------------------------------


def scan_strings(path: Path) -> list[str]:
    """Every string this file states as DATA, with prose excluded where that is knowable.

    Three readers, because the three formats admit different amounts of certainty:

    * `.py` — `ast`. A `Constant` that is the whole value of an `Expr` statement is a docstring
      (module, class, function) or one of this codebase's attribute docstrings, and is prose. A
      comment is invisible to `ast` for free. This is the reader that makes the clause honest.
    * `.toml` — `tomllib`, walking keys and values. A `#` comment is invisible for the same reason.
    * everything else (`.sql`, `.txt`, `.gitattributes`) — the raw text, because there is no
      parser here that can tell a statement from a comment, and over-reporting is the safe
      direction for a clause whose remedy is one line in a register.
    """
    if path.suffix == ".py":
        return _python_strings(path)
    if path.suffix == ".toml":
        return _toml_strings(path)
    try:
        return [path.read_text(encoding="utf-8", errors="replace")]
    except OSError:
        return []


def _python_strings(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    prose: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            prose.add(id(node.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose
    ]


def _toml_strings(path: Path) -> list[str]:
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    found: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, str):
            found.append(value)
        elif isinstance(value, dict):
            for key, item in value.items():
                found.append(str(key))
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(table)
    return found


def host_shaped(text: str, register: Register) -> list[tuple[str, str]]:
    """Every `(value, why)` in one string that addresses, or could address, a machine.

    Order matters: a URL is matched first and its authority is reported rather than the whole URL,
    so `http://127.0.0.1:0` and a bare `127.0.0.1` produce the same registrable value and one row
    covers both. An unknown scheme is reported rather than ignored, which is what makes the two
    scheme lists a decision instead of a default.
    """
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    def record(value: str, why: str) -> None:
        if value and value not in seen:
            seen.add(value)
            found.append((value, why))

    consumed = []
    for match in _SCHEME_RE.finditer(text):
        scheme, authority = match.group(1).lower(), match.group(2)
        consumed.append(match.group(0))
        if scheme in register.internal_schemes:
            continue
        host = authority.rsplit("@", 1)[-1].rsplit(":", 1)[0] if authority else ""
        if scheme not in register.network_schemes:
            record(
                f"{scheme}://",
                f"scheme {scheme!r} is on neither [allow] internal_schemes nor "
                f"[allow] network_schemes; a scheme is a decision, not a default",
            )
            continue
        record(host or f"{scheme}://", f"a {scheme} URL names {host or '<empty>'}")

    rest = text
    for url in consumed:
        rest = rest.replace(url, " ")

    # Longest first, masking what each one consumes. `[::1]` contains `::1`, so an unordered pass
    # reports one literal twice and asks for two register rows describing the same three bytes.
    for token in sorted(_LOOPBACK, key=len, reverse=True):
        pattern = re.compile(rf"(?<![\w.\-\[]){re.escape(token)}(?![\w.\-\]])", re.I)
        if pattern.search(rest):
            record(token, "a loopback name")
            rest = pattern.sub(" ", rest)

    for match in _IPV4_RE.finditer(rest):
        record(match.group(0), "an IPv4 literal")
    for match in _DOTTED_RE.finditer(rest):
        if match.group(1).lower() in TLDS:
            record(match.group(0), f"a dotted name ending in .{match.group(1).lower()}")
    return found


def check_literals(files: list[Path], register: Register) -> list[Finding]:
    """Every host-shaped literal has a row; nothing sits on `[[deny]]`."""
    findings: list[Finding] = []
    for path in files:
        where = relative(path)
        for text in scan_strings(path):
            for value, why in host_shaped(text, register):
                denial = register.denial(value)
                if denial is not None:
                    findings.append(Finding("literal", where, f"{value!r}: {denial}"))
                elif not register.allows_literal(value, where):
                    findings.append(
                        Finding(
                            "literal",
                            where,
                            f"{value!r} — {why} — has no [[literal]] row in tools/egress.toml "
                            f"for this path. Add one saying why it is here and what reads it, "
                            f"or remove it (14:788)",
                        )
                    )
    return findings


# ---------------------------------------------------------------------------
# clause 3 -- a conformance pass with the network amputated
# ---------------------------------------------------------------------------

BLOCKER = '''"""G15's amputation: AF_INET and AF_INET6 are unreachable here and in every child.

Loaded as `sitecustomize`, so it is armed before anything a conformance run imports -- including
inside every subprocess the run spawns, because `PYTHONPATH` is inherited. `sys.addaudithook`
cannot be removed once installed, which is the property that makes this a control rather than a
convention.

`AF_UNIX` is deliberately left alone. S4's transport is a 0600 unix socket or an owner-only named
pipe (04-driver-system.md section 1.3), and neither can carry a byte off the machine; a hook that
refused socket creation outright would be asserting that the driver host is broken rather than that
the network is absent.
"""

import socket
import sys

_BLOCKED = {int(socket.AF_INET), int(socket.AF_INET6)}
_LOG = __OW_LOG__


def _record(what):
    try:
        with open(_LOG, "a", encoding="utf-8") as handle:
            handle.write(what + "\\n")
    except OSError:
        pass


def _hook(event, args):
    if event == "socket.__new__":
        family = int(args[1]) if len(args) > 1 else -1
        if family in _BLOCKED:
            _record("socket.__new__ family=%d" % family)
            raise OSError("G15: this process may not open an AF_INET socket")
    elif event == "socket.getaddrinfo":
        _record("socket.getaddrinfo %r" % (args[:1],))
        raise OSError("G15: this process may not resolve a hostname")
    elif event == "socket.connect":
        _record("socket.connect %r" % (args[1:2],))
        raise OSError("G15: this process may not connect")


sys.addaudithook(_hook)
'''


def arm(scratch: Path) -> Path:
    """Write the blocker into `scratch` and return the path it records attempts to.

    Separate from both callers because ORDER is the thing this gate got wrong once: the negative
    control below has to run against an armed directory, and when it ran first it was reporting
    that an empty directory fails to block sockets — which is true, and says nothing.
    """
    log = scratch / "attempts.log"
    (scratch / "sitecustomize.py").write_text(
        BLOCKER.replace("__OW_LOG__", repr(str(log))), encoding="utf-8"
    )
    return log


def _armed_env(scratch: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(scratch), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    return env


def check_socket_blocked(card: Path, fixtures: Path, scratch: Path, log: Path) -> list[Finding]:
    """`ow conform` with the network amputated. It must pass, and nothing may have tried.

    Two assertions and not one. "The run passed" alone would also be true of a run that never
    reached the code that egresses; "nothing was attempted" alone would also be true of a run that
    crashed on its first fixture. Together they say the suites did their work with no network and
    did not want one.
    """
    env = _armed_env(scratch)
    proc = subprocess.run(  # noqa: S603 -- `sys.executable` and a repository path.
        [
            sys.executable,
            str(ROOT / "tools" / "ow_conform.py"),
            "--card",
            str(card),
            "--fixtures",
            str(fixtures),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
        env=env,
    )
    findings: list[Finding] = []
    if proc.returncode != 0:
        tail = "\n          ".join(
            (proc.stdout + proc.stderr).strip().splitlines()[-10:] or ["<empty>"]
        )
        findings.append(
            Finding(
                "socket-blocked",
                relative(card),
                f"the conformance pass exited {proc.returncode} with the network amputated. "
                f"A driver that needs a socket to parse a local file is the finding, not the "
                f"gate:\n          {tail}",
            )
        )
    if log.is_file():
        attempts = [line for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
        if attempts:
            findings.append(
                Finding(
                    "socket-blocked",
                    relative(card),
                    f"{len(attempts)} network attempt(s) during the run: "
                    f"{'; '.join(sorted(set(attempts))[:5])}",
                )
            )
    return findings


def _self_check(scratch: Path) -> list[Finding]:
    """The negative control: the blocker must actually block.

    Without it, clause 3 passes on a machine where `sitecustomize` never loaded — a `PYTHONPATH`
    the venv overrode, `-S` in the child, an import error swallowed at startup — and reports the
    absence of an instrument as the absence of egress. The same argument G11's clause 5 makes.

    It must run AFTER `arm()`. It did not, once, and said so.
    """
    open_af_inet = "import socket; socket.socket(socket.AF_INET, socket.SOCK_STREAM)"
    proc = subprocess.run(  # noqa: S603 -- `sys.executable` and a literal statement.
        [sys.executable, "-c", open_af_inet],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=_armed_env(scratch),
    )
    if proc.returncode == 0:
        return [
            Finding(
                "socket-blocked",
                "sitecustomize",
                "the blocker did not block: a fresh interpreter opened an AF_INET socket with it "
                "on PYTHONPATH. Clause 3 above was measuring nothing",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# plumbing
# ---------------------------------------------------------------------------


def run_static(register: Register) -> tuple[list[Finding], int]:
    files = shipped_files()
    findings = check_clients(files, register)
    findings.extend(check_literals(files, register))
    return findings, len(files)


def run_conform(card: Path, fixtures: Path) -> list[Finding]:
    with tempfile.TemporaryDirectory(prefix="ow-g15-") as scratch:
        root = Path(scratch)
        # TWO armed directories and not one. The control DELIBERATELY opens an AF_INET socket,
        # and it must not be able to write that attempt into the log clause 3 reads. Sharing one
        # directory made this gate report its own negative control as egress by the driver under
        # test -- the same shape of mistake as running G11's control before its discovery pass,
        # and the reason both gates now say out loud which order they need.
        control, measured = root / "control", root / "measured"
        control.mkdir()
        measured.mkdir()
        arm(control)
        findings = _self_check(control)
        findings.extend(check_socket_blocked(card, fixtures, measured, arm(measured)))
    return findings


def main(argv: list[str] | None = None) -> int:
    """Run G15. 0 clean, 1 with one block per finding, 2 when the gate could not run."""
    parser = argparse.ArgumentParser(description="G15 — no egress compiled in.")
    parser.add_argument("--half", choices=("static", "conform", "both"), default="both")
    parser.add_argument(
        "--card",
        default="packages/omniweave-office/src/omniweave_office/driver.toml",
        help="the driver clause 3 runs the suites against.",
    )
    parser.add_argument("--fixtures", default="packages/omniweave-office/fixtures")
    parser.add_argument("--json", action="store_true", help="findings as JSON, for a report.")
    args = parser.parse_args(argv)

    if not REGISTER.is_file():
        emit(f"G15 ERROR  no register at {REGISTER.relative_to(ROOT)}")
        return 2
    register = Register.load(REGISTER)

    findings: list[Finding] = []
    scanned = 0
    if args.half in ("static", "both"):
        static, scanned = run_static(register)
        findings.extend(static)
    if args.half in ("conform", "both"):
        try:
            findings.extend(run_conform(ROOT / args.card, ROOT / args.fixtures))
        except subprocess.TimeoutExpired:
            emit("G15 ERROR  the socket-blocked conformance pass did not finish.")
            return 2

    if args.json:
        emit(json.dumps([f.__dict__ for f in findings], indent=2))
        return 1 if findings else 0

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G15 FAIL  {len(findings)} finding(s).")
        return 1

    parts = []
    if args.half in ("static", "both"):
        parts.append(
            f"{scanned} shipped files, {len(register.clients)} client row(s), "
            f"{len(register.literals)} literal row(s)"
        )
    if args.half in ("conform", "both"):
        parts.append("conformance passed with AF_INET amputated, zero attempts")
    emit(f"G15 ok  {'; '.join(parts)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
