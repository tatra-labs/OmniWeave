"""G8/G24 — run the semgrep bank, and run the half of it that `ast` can prove without semgrep.

**Why this file exists at all.** `pyproject.toml`'s dev group declares
`"semgrep; sys_platform != 'win32'"` because semgrep publishes no Windows wheel
(11-repo-layout.md section 6.2 marks it for exactly that reason). A gate that simply *fails* where
it cannot run is worse than no gate: it trains a developer to ignore a red line, and the next red
line is a real one. So this harness does two things. It **skips the semgrep half loudly**, naming
the platform and the dependency marker, and it **runs an `ast` re-implementation** of every ban in
`tools/semgrep/omniweave.yaml` that `ast` can express, so a Windows developer still gets the
property on the file they just edited.

**The two halves are not redundant.** `ast` is exact where the ban is a name — an import, a dotted
call, a keyword argument value, a class-body field — and it is *better* than semgrep for
`return VerdictState.ABSENT`, because SV8 is a **count** ("exactly one site in the framework") and
semgrep has no counting operator; the YAML rule can only confine the return to one file. `ast` is
weaker where the ban is a value flowing into a receiver semgrep can constrain by shape. Every ban
below records which of the two it is in `AstBan.exact`, and `SEMGREP_ONLY_BANS` names the ones the
`ast` half does not attempt. Keep the two halves in step: the bank is the specification, this file
is the Windows shadow of it, and
`packages/omniweave-core/tests/unit/test_semgrep_bank.py` asserts they agree.

The bans themselves are enumerated in 02-architecture.md section 3.3, the semgrep row of the table
at **line 392**, and that row is the complete specification of both halves. Gate ids are G8 (the
45 s `gates`-job budget) and G24, which 11-repo-layout.md section 6.4 records as running inside G8.

`subprocess` is imported here under a `noqa`: 02-architecture.md line 392 scopes that ban to
`packages/*/src/**` — library code — and a gate harness whose whole job is to spawn semgrep is not
library code. `tools/` has no `per-file-ignores` row yet; see the note in the module's return value.
"""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess  # noqa: TID251 - gate harness, not library code; see the module docstring.
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "AST_BANS",
    "BANK_PATH",
    "REPO_ROOT",
    "SEMGREP_ONLY_BANS",
    "AstBan",
    "Finding",
    "ast_findings",
    "check_source",
    "main",
    "path_matches",
    "semgrep_available",
]

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
"""The workspace root — the directory holding `pyproject.toml`, `packages/` and `tools/`.

Derived from this file's own location rather than from the current directory, because `os.getcwd()`
is the very ban this harness enforces and a gate that reads the ambient directory would report a
different answer depending on where it was launched from (02-architecture.md line 392;
08-runtime.md section 1.3's "no ambient cwd", graphify #1774).
"""

BANK_PATH: Path = REPO_ROOT / "tools" / "semgrep" / "omniweave.yaml"
"""The semgrep bank this harness runs. One file, named by 11-repo-layout.md section 1.7's `tools/`
tree and by 02-architecture.md line 392."""

LIBRARY: tuple[str, ...] = ("packages/*/src/**",)
"""What "library code" means for every ban 02-architecture.md line 392 scopes that way.

Tests, `tools/`, `fuzz/`, `eval/`, `fixtures/` and `vendor/` are excluded by construction: a test
that asserts `time.time()` is banned has to be able to write `time.time()`, and a gate script has to
be able to spawn a process. The glob is the same string the bank's `paths.include` carries, so the
two halves scope identically.
"""

ENTRY = "packages/*/src/**/__main__.py"
"""A process entry point, which is executed and never imported, and so is not library code. D435.

02-architecture.md line 392 bans `os.getcwd()` and `sys.exit` *"in library code"* and never says
where library code ends, while this bank's own message for the exit ban tells the reader to *"let
the CLI map it onto one of its twelve exit codes"* -- which presumes a site that may exit. A process
has to read its working directory and set its exit status somewhere. `__main__.py` is the narrowest
place that can be: a module Python runs for `-m` and that nothing imports as a library. Exempted
from exactly those two rules and no others, so the ambient reads of a whole distribution are
visible in one file per distribution.
"""

STORE = "packages/omniweave-core/src/omniweave_core/store/**"
HOST = "packages/omniweave-core/src/omniweave_core/host/**"
DRIVERS = "packages/omniweave-core/src/omniweave_core/drivers/**"
TOOLCHAIN = "packages/omniweave-core/src/omniweave_core/toolchain.py"
SUBPROC = "packages/omniweave-core/src/omniweave_core/host/subproc.py"
OPC = "packages/omniweave-core/src/omniweave_core/out/opc.py"
CLOCK = "packages/omniweave-core/src/omniweave_core/clock.py"
"""The one module entitled to read the machine's clock. **D154**.

`omniweave-no-time-time-in-library-code` prescribes `time.monotonic_ns()` for a duration, and
on Windows that call's resolution is 15.6 ms -- so the number `15-observability.md:434` asks
the manifest for (`observe.serialise_ns_total`, a few microseconds) rounds to zero on six of
the nine test-matrix cells. `clock.py` chooses `time.perf_counter_ns()` there, records the
shortfall in `ClockFacts` rather than claiming it, and substitutes only a clock the
interpreter itself reports as monotonic.

Scoped exactly like `TOOLCHAIN` and `SUBPROC`: one module is entitled to the banned call and
every other module injects. `test_clock.py` asserts this file's own discipline -- it calls
only `time_ns`, `monotonic_ns`, `perf_counter_ns` and `get_clock_info` -- so the path-level
exemption does not become a blanket one.
"""
OWDOC = "packages/omniweave-core/src/omniweave_core/archive/owdoc.py"
"""The SECOND module permitted to open a ZIP for writing, and the reason it had to become two.

02-architecture.md:130, :253 and :392, 09-generation.md:1561, 16-roadmap.md:828, 17-risks.md:259
and README.md:125 all say `out/opc.py` is "the only zipfile-for-write in the framework". Six other
sites require `omniweave_core.archive` to WRITE a `.owdoc`, which is a plain ZIP of `ZIP_DEFLATED`
NDJSON frames: 02-architecture.md:107 and :249, 03-document-model.md:2485-2501 (the member tree),
:2503, 12-performance.md:1129, and 16-roadmap.md:418, whose W2.5 asks for "writer **and** reader"
at P2 -- seven phases before `out/opc.py` exists at all (W9.1). Both cannot hold.

The contradiction is resolved by reading what the ban is FOR rather than by counting sites, and
the rule states its own purpose in two independent voices. The bank message says the point is that
"every entry is built with `ZipInfo(name)` rather than `ZipFile.write`/`writestr`, whose
`date_time` reads the **local clock**" -- a DETERMINISM property, restated generally at
01-principles.md:684. 17-risks.md:259 gives the other: "there is exactly one container writer to
audit", an argument about artefacts a human opens in PowerPoint, where active content and external
relationships are the risk. Neither reason reaches `.owdoc`, which is an internal lossless
projection of the store (02-architecture.md:249) and is never delivered to anyone.

So the ban is not widened, it is MOVED: `owdoc.py` may open the ZIP, and the determinism half --
the actual guarantee -- is carried into that file by two tests in `test_archive_owdoc.py`, an
`ast` assertion that every member write passes a pinned `ZipInfo` and a byte-identical
re-export. A hole in a ban is a hole; a ban replaced by the property it was protecting is not.

IT IS NOT A NEW BANK RULE, and that is deliberate. The bank is a TRANSCRIPTION of
02-architecture.md:392's list, which `test_the_bank_carries_no_rule_the_plan_did_not_order`
enforces: inventing a site ban here and adding it to the register would be claiming the plan
ordered something it did not. A test owned by the archive is the honest home until 02's owner
rules. `_plan/_notes/build-defects.md` D13 is the finding, and it names the amendment owed.
"""
OTLP = "packages/omniweave-serve/src/omniweave_serve/otlp.py"
PIPELINE = "packages/omniweave/src/omniweave/run/pipeline.py"
VERDICT = "packages/omniweave-core/src/omniweave_core/retrieve/verdict.py"
PURITY_ISLANDS: tuple[str, ...] = (
    "packages/omniweave/src/omniweave/route/eval.py",
    "packages/omniweave-core/src/omniweave_core/retrieve/plan.py",
    "packages/omniweave-target-*/src/**",
)
"""The three places 02-architecture.md line 392 says the eight ambient inputs are banned with no
exemption at all: `route/eval.py` (RT1 — `evaluate()` takes no ledger, no clock, no `RunContext`),
`retrieve/plan.py` (16-roadmap.md W6.1 — pure and memoised on a five-part key), and every
`omniweave-target-*` (OUT13/OUT14 — byte comparison across nine OS/python cells)."""

SEMGREP_ONLY_BANS: frozenset[str] = frozenset(
    {
        "omniweave-no-sql-begin-outside-store",
    }
)
"""Rule ids whose ban the `ast` half deliberately does not attempt.

Only one, and it is a judgement rather than a limitation: `BEGIN` is a **string literal**, so an
`ast` matcher over `Constant` nodes fires on prose, on a docstring that quotes the ban, and on any
SQL fragment that happens to start a comment with the word. semgrep's `pattern-regex` runs against
the source with the same weakness, but semgrep findings are reviewed in CI against a 45 s budget
whereas this harness runs in a pre-commit-shaped loop, and a gate that cries wolf locally is a gate
that gets `--no-verify`-ed. The `ast` half therefore reports it as UNCHECKED rather than guessing.
"""

_DESERIALISERS: frozenset[str] = frozenset({"tomllib", "json", "toml", "yaml", "pickle", "marshal"})
"""Receivers whose `.load(...)` is a deserialiser, not an entry point.

`omniweave_core/drivers/card.py` reads `driver.toml` with `tomllib.load`, so a receiver-blind
`.load()` ban under `drivers/` would fire on the card loader itself — the module the ban exists to
protect. 04-driver-system.md section 4.6 bans `EntryPoint.load()`, whose defining property is that
it *imports*; these six never do.
"""

_IDENTITY_CALL = re.compile(
    r"(?i)(digest|cache_key|cachekey|fingerprint|probe|baseline|channel|sha256|blake2|ow128"
    r"|canonical|checksum)"
)
"""Which callee names make a bare `except` an AP-6 violation.

02-architecture.md line 392 names six subjects — a digest, a cache key, a code fingerprint, a probe,
a baseline read, a retrieval channel — and this regex is that list plus the framework's own digest
spellings (`sha256_canonical`, `ow128`, `canonical`, all in `omniweave_core/canonical.py`). It is a
heuristic on the name, which is what semgrep's `metavariable-regex` does too; the bank and this
regex carry the same alternation on purpose.
"""

_AMBIENT_ATTRS: frozenset[str] = frozenset(
    {
        "os.getcwd",
        "os.getcwdb",
        "Path.cwd",
        "pathlib.Path.cwd",
        "time.time",
        "time.time_ns",
        "time.perf_counter",
        "time.perf_counter_ns",
        "time.process_time",
        "time.process_time_ns",
        "uuid.uuid4",
        "uuid.uuid1",
        "datetime.now",
        "datetime.datetime.now",
        "datetime.utcnow",
        "datetime.datetime.utcnow",
        "date.today",
        "datetime.date.today",
        "sys.exit",
    }
)

_AMBIENT_BARE: frozenset[str] = frozenset({"getcwd", "uuid4", "uuid1", "exit", "quit"})


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation: which rule, which file, which line, and what to do about it.

    `rule_id` is the id of the rule in `tools/semgrep/omniweave.yaml` that would report the same
    violation on Linux, so a Windows finding and a CI finding name the same thing and a developer
    can grep the bank for the long message. `exact` records whether the `ast` matcher is exact for
    this ban or a heuristic that semgrep states more precisely — an inexact finding is still a
    finding, but it is the one worth reading twice.
    """

    rule_id: str
    path: str
    line: int
    detail: str
    exact: bool = True

    def render(self) -> str:
        """One line, `path:line: rule-id: detail`, with a trailing `(heuristic)` when inexact."""
        tail = "" if self.exact else "  (heuristic — semgrep states this ban precisely)"
        return f"{self.path}:{self.line}: {self.rule_id}: {self.detail}{tail}"


@dataclass(frozen=True, slots=True)
class AstBan:
    """One ban from 02-architecture.md line 392, in the form the `ast` half can evaluate.

    `include`/`exclude` are the same glob strings the bank's `paths` block carries, so the two
    halves cannot drift in scope without the drift being visible in a diff. `modules` bans an
    import root *and* every `root.attr(...)` call through it; `calls` bans exact dotted callees;
    `bare_calls` bans a callee spelled without its module, which is what `from x import y` leaves
    behind. `exact` is False when the matcher is a name heuristic rather than a shape match.
    """

    rule_id: str
    ban: str
    include: tuple[str, ...]
    exclude: tuple[str, ...] = ()
    modules: frozenset[str] = field(default_factory=frozenset)
    calls: frozenset[str] = field(default_factory=frozenset)
    bare_calls: frozenset[str] = field(default_factory=frozenset)
    exact: bool = True

    def covers(self, rel: str) -> bool:
        """True when this ban applies to the repo-relative POSIX path `rel`."""
        if not any(path_matches(pat, rel) for pat in self.include):
            return False
        return not any(path_matches(pat, rel) for pat in self.exclude)


def path_matches(pattern: str, rel: str) -> bool:
    """Match a repo-relative POSIX path against a semgrep-style glob.

    `*` matches within one segment, `**` crosses segments, and a pattern is anchored at both ends.
    Written rather than borrowed because `fnmatch` lets `*` cross `/`, which would make
    `packages/*/src/**` match `packages/a/b/src/x.py` and quietly widen every rule's scope. This is
    the one piece of the harness that has to agree with semgrep's own glob semantics; the tests
    pin it directly.
    """
    parts = re.split(r"(\*\*/|\*\*|\*|\?)", pattern)
    out = []
    for part in parts:
        if part == "**/":
            out.append(r"(?:.*/)?")
        elif part == "**":
            out.append(r".*")
        elif part == "*":
            out.append(r"[^/]*")
        elif part == "?":
            out.append(r"[^/]")
        else:
            out.append(re.escape(part))
    return re.fullmatch("".join(out), rel) is not None


AST_BANS: tuple[AstBan, ...] = (
    AstBan(
        rule_id="omniweave-no-sqlite3-connect-outside-store",
        ban="sqlite3.connect outside omniweave_core/store/",
        include=LIBRARY,
        exclude=(STORE,),
        calls=frozenset({"sqlite3.connect", "sqlite3.dbapi2.connect"}),
    ),
    AstBan(
        rule_id="omniweave-no-sqlite3-import-outside-store",
        ban="import sqlite3 outside omniweave_core/store/",
        include=LIBRARY,
        exclude=(STORE,),
        modules=frozenset({"sqlite3"}),
    ),
    AstBan(
        rule_id="omniweave-no-subprocess-outside-toolchain-and-host-subproc",
        ban="subprocess outside toolchain.py and host/subproc.py",
        include=LIBRARY,
        exclude=(TOOLCHAIN, SUBPROC),
        modules=frozenset({"subprocess"}),
    ),
    AstBan(
        rule_id="omniweave-no-make-archive-outside-opc",
        ban="shutil.make_archive outside out/opc.py",
        include=LIBRARY,
        exclude=(OPC,),
        calls=frozenset({"shutil.make_archive"}),
        bare_calls=frozenset({"make_archive"}),
    ),
    AstBan(
        rule_id="omniweave-no-opentelemetry-outside-otlp",
        ban="opentelemetry outside omniweave_serve/otlp.py",
        include=LIBRARY,
        exclude=(OTLP,),
        modules=frozenset({"opentelemetry"}),
    ),
    AstBan(
        rule_id="omniweave-no-import-module-outside-host",
        ban="importlib.import_module outside omniweave_core/host/",
        include=LIBRARY,
        exclude=(HOST,),
        calls=frozenset({"importlib.import_module"}),
        bare_calls=frozenset({"import_module"}),
    ),
    AstBan(
        rule_id="omniweave-no-dunder-import-outside-host",
        ban="__import__ outside omniweave_core/host/",
        include=LIBRARY,
        exclude=(HOST,),
        bare_calls=frozenset({"__import__"}),
    ),
    AstBan(
        rule_id="omniweave-no-getcwd-in-library-code",
        ban="os.getcwd() in library code",
        include=LIBRARY,
        exclude=(ENTRY,),
        calls=frozenset({"os.getcwd", "os.getcwdb", "Path.cwd", "pathlib.Path.cwd"}),
        bare_calls=frozenset({"getcwd"}),
    ),
    AstBan(
        rule_id="omniweave-no-time-time-in-library-code",
        ban="time.time() in library code",
        include=LIBRARY,
        exclude=(CLOCK,),
        calls=frozenset(
            {
                "time.time",
                "time.time_ns",
                "time.perf_counter",
                "time.perf_counter_ns",
                "time.process_time",
                "time.process_time_ns",
            }
        ),
    ),
    AstBan(
        rule_id="omniweave-no-random-in-library-code",
        ban="random in library code",
        include=LIBRARY,
        modules=frozenset({"random"}),
    ),
    AstBan(
        rule_id="omniweave-no-secrets-in-library-code",
        ban="secrets in library code",
        include=LIBRARY,
        modules=frozenset({"secrets"}),
    ),
    AstBan(
        rule_id="omniweave-no-uuid4-in-library-code",
        ban="uuid4 in library code",
        include=LIBRARY,
        calls=frozenset({"uuid.uuid4", "uuid.uuid1"}),
        bare_calls=frozenset({"uuid4", "uuid1"}),
    ),
    AstBan(
        rule_id="omniweave-no-datetime-now-in-library-code",
        ban="datetime.now in library code",
        include=LIBRARY,
        calls=frozenset(
            {
                "datetime.now",
                "datetime.datetime.now",
                "datetime.utcnow",
                "datetime.datetime.utcnow",
                "date.today",
                "datetime.date.today",
            }
        ),
    ),
    AstBan(
        rule_id="omniweave-no-sys-exit-in-library-code",
        ban="sys.exit in library code",
        include=LIBRARY,
        exclude=(ENTRY,),
        calls=frozenset({"sys.exit"}),
        bare_calls=frozenset({"exit", "quit"}),
    ),
)
"""The bans expressible as a name lookup. Every other ban has a hand-written matcher below.

Ordering is 02-architecture.md line 392's own, left to right, so a reader can hold the plan row
beside this tuple and check them off. `omniweave-no-sql-begin-outside-store` is absent by design
(`SEMGREP_ONLY_BANS`), and the shape-matched bans — `conn.commit()`, `ZipFile(..., "w")`,
`EntryPoint.load()`, `Path(".")`, the purity islands, the bare `except`, `revision="main"`,
`DriverHost.invoke()`, the `html`/`markdown`/`md` field and the `VerdictState.ABSENT` count — each
have their own function.
"""


def _dotted(node: ast.expr) -> str | None:
    """Render `a.b.c` for a Name/Attribute chain; None for anything else (a call, a subscript)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        head = _dotted(node.value)
        return None if head is None else f"{head}.{node.attr}"
    return None


def _import_roots(node: ast.Import | ast.ImportFrom) -> Iterator[str]:
    """Yield the first dotted segment of every module an import statement names."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name.split(".")[0]
    elif node.module is not None and node.level == 0:
        yield node.module.split(".")[0]


def _str_arg(call: ast.Call, position: int, keyword: str) -> str | None:
    """The string value of a positional-or-keyword argument, or None when it is not a literal."""
    for kw in call.keywords:
        if kw.arg == keyword and isinstance(kw.value, ast.Constant):
            return kw.value.value if isinstance(kw.value.value, str) else None
    if len(call.args) > position and isinstance(call.args[position], ast.Constant):
        value = call.args[position].value
        return value if isinstance(value, str) else None
    return None


def _generic(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """Apply every `AST_BANS` entry: banned import roots, banned dotted calls, banned bare calls."""
    active = [ban for ban in AST_BANS if ban.covers(rel)]
    if not active:
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            roots = set(_import_roots(node))
            for ban in active:
                hit = roots & ban.modules
                if hit:
                    yield Finding(ban.rule_id, rel, node.lineno, f"imports {sorted(hit)[0]}")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name is None:
                continue
            root = name.split(".")[0]
            for ban in active:
                if name in ban.calls or name in ban.bare_calls or root in ban.modules:
                    yield Finding(ban.rule_id, rel, node.lineno, f"calls {name}()")


def _commit(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """`conn.commit()` on any receiver, outside `omniweave_core/store/` (INV-17, ST1).

    Receiver-blind exactly as the bank's rule is: the defect is a `Connection` acquired some other
    way and committed outside the store thread's transaction closure, and the receiver's *name* is
    the one thing that carries no information about that.
    """
    ban = AstBan(
        rule_id="omniweave-no-sqlite3-commit-outside-store",
        ban="conn.commit() outside omniweave_core/store/",
        include=LIBRARY,
        exclude=(STORE,),
    )
    if not ban.covers(rel):
        return
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "commit"
            and not node.args
            and not node.keywords
        ):
            yield Finding(ban.rule_id, rel, node.lineno, "calls .commit()")


def _zip_write(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """`zipfile.ZipFile(..., 'w'|'a'|'x')` outside `omniweave_core/out/opc.py` (OUT15).

    Exact: the mode is the second positional argument or the `mode=` keyword, and both are checked.
    A non-literal mode is not flagged — semgrep would not flag it either, and a computed mode is a
    different (and worse) defect that OUT13's byte comparison catches directly.
    """
    ban = AstBan(
        rule_id="omniweave-no-zipfile-write-outside-opc",
        ban="zipfile.ZipFile(..., 'w'|'a'|'x') outside out/opc.py and archive/owdoc.py",
        include=LIBRARY,
        exclude=(OPC, OWDOC),
    )
    if not ban.covers(rel):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name is None or name.split(".")[-1] != "ZipFile":
            continue
        mode = _str_arg(node, 1, "mode")
        if mode is not None and mode[:1] in {"w", "a", "x"}:
            yield Finding(ban.rule_id, rel, node.lineno, f"opens a ZIP with mode {mode!r}")


def _entrypoint_load(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """`EntryPoint.load()` under `omniweave_core/drivers/` (INV-4, DR1, DR2).

    Heuristic, and the bank says so too: an entry point's receiver can be named anything, so the
    matcher is "any `.load(...)` whose receiver is not one of the six stdlib deserialisers". Without
    that exclusion the rule fires on `tomllib.load` in the card loader — the module the ban exists
    to protect. See 04-driver-system.md section 4.6 and `_DESERIALISERS`.
    """
    ban = AstBan(
        rule_id="omniweave-no-entrypoint-load-under-drivers",
        ban="EntryPoint.load() under omniweave_core/drivers/",
        include=(DRIVERS,),
        exact=False,
    )
    if not ban.covers(rel):
        return
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "load":
            continue
        receiver = _dotted(node.func.value)
        if receiver is not None and receiver.split(".")[0] in _DESERIALISERS:
            continue
        yield Finding(ban.rule_id, rel, node.lineno, "calls .load() under drivers/", exact=False)


def _relative_root(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """`Path(".")` and its spellings, in library code (graphify #1774).

    Exact: a `Path`/`PurePath`/`PurePosixPath` constructor whose single argument is the literal
    `"."` or `""`, or `os.curdir`. A computed relative root is not flagged here — the ban
    02-architecture.md line 392 prints is the literal.
    """
    ban = AstBan(
        rule_id="omniweave-no-relative-path-root-in-library-code",
        ban='Path(".") in library code',
        include=LIBRARY,
    )
    if not ban.covers(rel):
        return
    names = {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name is None or name.split(".")[-1] not in names or len(node.args) != 1:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and arg.value in {".", ""}:
            yield Finding(ban.rule_id, rel, node.lineno, f"builds a path from {arg.value!r}")
        elif _dotted(arg) in {"os.curdir", "curdir"}:
            yield Finding(ban.rule_id, rel, node.lineno, "builds a path from os.curdir")


def _purity_islands(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """All eight ambient inputs, in `route/eval.py`, `retrieve/plan.py` and every target (RT1).

    Stricter than the library-code rules in one respect the plan is explicit about: the whole
    `time.` module is banned in `route/eval.py`, not only `time.time()`, because `evaluate()` takes
    no clock at all. This is the independent second enforcer of the eight rules above — one
    `exclude` edit cannot disable both.
    """
    ban = AstBan(
        rule_id="omniweave-no-ambient-input-in-purity-islands",
        ban="all of them in route/eval.py, retrieve/plan.py and every omniweave-target-*",
        include=PURITY_ISLANDS,
    )
    if not ban.covers(rel):
        return
    modules = {"random", "secrets"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import | ast.ImportFrom):
            hit = set(_import_roots(node)) & modules
            if hit:
                yield Finding(ban.rule_id, rel, node.lineno, f"imports {sorted(hit)[0]}")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name is None:
                continue
            root = name.split(".")[0]
            ambient = root in modules or root == "time" or name in _AMBIENT_ATTRS
            if ambient or name in _AMBIENT_BARE:
                yield Finding(ban.rule_id, rel, node.lineno, f"calls {name}()")
        elif isinstance(node, ast.Raise) and _raises_system_exit(node):
            yield Finding(ban.rule_id, rel, node.lineno, "raises SystemExit")


def _raises_system_exit(node: ast.Raise) -> bool:
    """True for `raise SystemExit` and `raise SystemExit(...)`, in either spelling."""
    exc = node.exc
    if exc is None:
        return False
    target = exc.func if isinstance(exc, ast.Call) else exc
    name = _dotted(target)
    return name is not None and name.split(".")[-1] == "SystemExit"


def _sys_exit_raise(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """`raise SystemExit` in library code — `sys.exit`'s other spelling (DR21)."""
    ban = AstBan(
        rule_id="omniweave-no-sys-exit-in-library-code",
        ban="sys.exit in library code",
        include=LIBRARY,
        exclude=(ENTRY,),
    )
    if not ban.covers(rel):
        return
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and _raises_system_exit(node):
            yield Finding(ban.rule_id, rel, node.lineno, "raises SystemExit")


def _bare_except(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """A bare `except` around a digest, cache key, fingerprint, probe, baseline or channel (AP-6).

    Heuristic on the callee name, which is what the bank's `metavariable-regex` does too — the two
    carry the same alternation. `except:`, `except Exception:` and `except BaseException:` all
    count; a handler naming a specific exception does not, because naming it is the fix.
    """
    ban = AstBan(
        rule_id="omniweave-no-bare-except-around-identity",
        ban=(
            "bare except around a digest, cache key, code fingerprint, probe, baseline read "
            "or retrieval channel"
        ),
        include=LIBRARY,
        exact=False,
    )
    if not ban.covers(rel):
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or not any(_is_bare(h) for h in node.handlers):
            continue
        for called in _identity_calls(node.body):
            yield Finding(
                ban.rule_id, rel, called[1], f"bare except wraps {called[0]}()", exact=False
            )


def _is_bare(handler: ast.ExceptHandler) -> bool:
    """True for `except:`, `except Exception:` and `except BaseException:`."""
    if handler.type is None:
        return True
    name = _dotted(handler.type)
    return name is not None and name.split(".")[-1] in {"Exception", "BaseException"}


def _identity_calls(body: Sequence[ast.stmt]) -> Iterator[tuple[str, int]]:
    """Yield `(callee, line)` for every call in `body` whose name reads as an identity function."""
    for stmt in body:
        for node in ast.walk(stmt):
            if not isinstance(node, ast.Call):
                continue
            name = _dotted(node.func)
            if name is not None and _IDENTITY_CALL.search(name.split(".")[-1]):
                yield (name, node.lineno)


def _revision_main(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """`revision="main"` anywhere in library code (RT14).

    Exact, and it covers both shapes the plan names: the keyword argument at a call site and the
    bare assignment. `model_revision` and `weights_revision` are included because
    04-driver-system.md section 2.4 gives them the same rule for the same hazard.
    """
    ban = AstBan(
        rule_id="omniweave-no-revision-main",
        ban='revision="main"',
        include=LIBRARY,
    )
    if not ban.covers(rel):
        return
    keys = {"revision", "model_revision", "weights_revision"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                literal = isinstance(kw.value, ast.Constant) and kw.value.value == "main"
                if kw.arg in keys and literal:
                    yield Finding(ban.rule_id, rel, node.lineno, f'{kw.arg}="main"')
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            value = node.value
            if not (isinstance(value, ast.Constant) and value.value == "main"):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in keys:
                    yield Finding(ban.rule_id, rel, node.lineno, f'{target.id} = "main"')


def _driverhost_invoke(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """A `DriverHost.invoke()` call outside `omniweave/run/pipeline.py`.

    Heuristic: `ast` cannot type the receiver, so any `.invoke(...)` outside the pipeline and
    outside `omniweave_core/host/` (where it is defined and internally delegated) is reported.
    semgrep's rule has the same shape; the exactness costs nothing because `invoke` is not a common
    method name in this tree.
    """
    ban = AstBan(
        rule_id="omniweave-no-driverhost-invoke-outside-pipeline",
        ban="DriverHost.invoke() call outside run/pipeline.py",
        include=LIBRARY,
        exclude=(PIPELINE, HOST),
        exact=False,
    )
    if not ban.covers(rel):
        return
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "invoke"
        ):
            yield Finding(ban.rule_id, rel, node.lineno, "calls .invoke()", exact=False)


def _second_text_column(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """An `html`, `markdown` or `md` field on any model class (INV-1).

    Exact: a class-body assignment, annotated or not, whose target is one of the three names.
    Methods and properties are not fields and are not flagged — a `def markdown(self)` is a
    projection, which is precisely what INV-1 asks for.
    """
    ban = AstBan(
        rule_id="omniweave-no-second-text-column",
        ban="html/markdown/md field on a model class",
        include=LIBRARY,
    )
    if not ban.covers(rel):
        return
    banned = {"html", "markdown", "md"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            for name, line in _class_field_names(stmt):
                if name in banned:
                    yield Finding(
                        ban.rule_id, rel, line, f"class {node.name} declares a {name!r} field"
                    )


def _class_field_names(stmt: ast.stmt) -> Iterator[tuple[str, int]]:
    """Yield `(field name, line)` for each name a class-body statement binds as a field."""
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        yield (stmt.target.id, stmt.lineno)
    elif isinstance(stmt, ast.Assign):
        for target in stmt.targets:
            if isinstance(target, ast.Name):
                yield (target.id, stmt.lineno)


def _verdict_absent(rel: str, tree: ast.Module) -> Iterator[Finding]:
    """`return VerdictState.ABSENT` outside `omniweave_core/retrieve/verdict.py` (INV-11, SV8).

    The per-file half of SV8, matching the bank exactly. `ast_findings()` adds the half semgrep
    cannot express — the *count* — by rejecting a second site even inside `verdict.py`.
    """
    ban = AstBan(
        rule_id="omniweave-one-verdict-absent-site",
        ban="second return VerdictState.ABSENT site",
        include=LIBRARY,
        exclude=(VERDICT,),
    )
    if not ban.covers(rel):
        return
    for node, line in _absent_returns(tree):
        del node
        yield Finding(ban.rule_id, rel, line, "returns VerdictState.ABSENT")


def _absent_returns(tree: ast.Module) -> Iterator[tuple[ast.Return, int]]:
    """Yield every `return <...>.VerdictState.ABSENT` in the module, with its line."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        name = _dotted(node.value)
        if name is not None and name.endswith("VerdictState.ABSENT"):
            yield (node, node.lineno)


_ABSENT_RULE = "omniweave-one-verdict-absent-site"
"""SV8's rule id, needed by `ast_findings()`'s count pass as well as by `_verdict_absent`."""

_CHECKS = (
    _generic,
    _commit,
    _zip_write,
    _entrypoint_load,
    _relative_root,
    _purity_islands,
    _sys_exit_raise,
    _bare_except,
    _revision_main,
    _driverhost_invoke,
    _second_text_column,
    _verdict_absent,
)


def check_source(rel: str, source: str) -> list[Finding]:
    """Run every `ast`-expressible ban against one file's source, sorted by line then rule id.

    `rel` is the repo-relative POSIX path — it decides which bans apply, so passing the wrong path
    silently changes the answer. A file that does not parse yields no findings: a syntax error is
    `ruff`'s to report, and guessing at a broken tree would produce noise exactly when the developer
    is least able to act on it.
    """
    tree = _parse(rel, source)
    if tree is None:
        return []
    found: list[Finding] = []
    for check in _CHECKS:
        found.extend(check(rel, tree))
    return sorted(found, key=lambda f: (f.line, f.rule_id, f.detail))


def _parse(rel: str, source: str) -> ast.Module | None:
    """Parse, returning None on a syntax error rather than raising into the gate."""
    try:
        return ast.parse(source, filename=rel)
    except SyntaxError:
        return None


def ast_findings(root: Path | None = None) -> list[Finding]:
    """Walk `packages/*/src/**/*.py` and return every violation the `ast` half can prove.

    Adds the one property semgrep has no operator for: SV8's **count**. The bank confines
    `return VerdictState.ABSENT` to `omniweave_core/retrieve/verdict.py`; this function additionally
    rejects a second site inside that file, which is what "exactly one `return VerdictState.ABSENT`
    site in the framework" actually says (01-principles.md INV-11, 07-store-and-retrieval.md).
    """
    base = REPO_ROOT if root is None else root
    found: list[Finding] = []
    absent_sites: list[Finding] = []
    for path in sorted(base.glob("packages/*/src/**/*.py")):
        rel = path.relative_to(base).as_posix()
        source = path.read_text(encoding="utf-8")
        found.extend(check_source(rel, source))
        tree = _parse(rel, source)
        if tree is not None:
            absent_sites.extend(
                Finding(_ABSENT_RULE, rel, line, "returns VerdictState.ABSENT")
                for _, line in _absent_returns(tree)
            )
    if len(absent_sites) > 1:
        found.extend(absent_sites[1:])
    return sorted(set(found), key=lambda f: (f.path, f.line, f.rule_id))


def semgrep_available() -> bool:
    """True when a `semgrep` executable is on PATH — false on Windows, where there is no wheel."""
    return shutil.which("semgrep") is not None


def _say(text: str) -> None:
    """Write one line to stdout.

    `print` is banned repo-wide by ruff's `T20` and `tools/` has no `per-file-ignores` row; writing
    to the stream directly says the same thing without needing the escape.
    """
    sys.stdout.write(text + "\n")


def _run_semgrep(base: Path) -> int:
    """Spawn semgrep over the bank and return its exit code (0 clean, 1 findings, 2 error)."""
    argv = [
        "semgrep",
        "--config",
        str(BANK_PATH),
        "--error",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        str(base / "packages"),
    ]
    completed = subprocess.run(argv, check=False, cwd=str(base))  # noqa: S603
    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """Run both halves and return a process exit code. 0 clean, 1 findings, 2 the bank is missing.

    The `ast` half always runs, on every platform. The semgrep half runs only where a `semgrep`
    executable exists; where it does not, the harness prints a SKIP naming `sys.platform` and the
    `pyproject.toml` marker that put it there, and does not fail. 11-repo-layout.md section 6.2 is
    the locus for the marker; the reasoning for skipping rather than failing is in this module's
    docstring.
    """
    parser = argparse.ArgumentParser(description="G8/G24 — the semgrep bank and its ast shadow.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="workspace root to scan")
    parser.add_argument(
        "--ast-only", action="store_true", help="skip semgrep even where it is installed"
    )
    args = parser.parse_args(argv)
    base: Path = args.root.resolve()

    if not BANK_PATH.is_file():
        _say(f"G8/G24 FAIL: the semgrep bank is missing at {BANK_PATH}")
        return 2

    findings = ast_findings(base)
    for finding in findings:
        _say(finding.render())
    unchecked = ", ".join(sorted(SEMGREP_ONLY_BANS))
    _say(f"G8/G24 ast half: {len(findings)} finding(s); not checked here: {unchecked}")

    if args.ast_only:
        return 1 if findings else 0
    if not semgrep_available():
        _say(
            f"G8/G24 SKIP semgrep on platform {sys.platform!r}: no `semgrep` on PATH. "
            "semgrep publishes no Windows wheel, so pyproject.toml's dev group declares it "
            "\"semgrep; sys_platform != 'win32'\" (11-repo-layout.md section 6.2). The ast half "
            "above still ran. CI runs the full bank on ubuntu; this is not a pass."
        )
        return 1 if findings else 0

    code = _run_semgrep(base)
    return code if code else (1 if findings else 0)


if __name__ == "__main__":
    raise SystemExit(main())
