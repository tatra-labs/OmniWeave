"""The semgrep bank is complete against the plan, and its `ast` shadow proves what it can.

Three jobs, and the middle one is the valuable one.

1. **Shape.** Every rule in `tools/semgrep/omniweave.yaml` carries `id`, `message`, `languages`,
   `severity` and `patterns`, plus the `metadata.ban` and `metadata.plan` this repository adds so a
   rule can be traced back to the sentence that ordered it. A rule missing `patterns` is a rule
   semgrep loads and never fires.

2. **Coverage against the plan.** `_plan/02-architecture.md` **line 392** — the semgrep row of
   section 3.3's table — is the bank's complete specification, and `BAN_TOKENS` below maps every
   backticked token on that line to the rule that implements it. The test asserts the mapping's key
   set equals the token set the line actually carries, in both directions. That is what fails when
   someone adds a ban to the plan and forgets the rule, and equally when someone adds a rule the
   plan never asked for. It is the one test here that would have caught the failure this project
   has already lived through: a document that passed every structural check while missing two
   thirds of its content.

3. **Behaviour, without semgrep.** semgrep publishes no Windows wheel, so `tools/gate_semgrep.py`
   re-implements in `ast` every ban `ast` can express. Those matchers are exercised below over
   adversarial sources: the ban's own shape in a covered path (must fire), the same shape in the
   exempted path (must not), and the near-miss that a naive matcher would flag — `tomllib.load` in
   the card loader, a `markdown()` *method* rather than a field, `except ValueError` around a
   digest, `ZipFile(p, "r")`, `model_revision="5617a9f6…"`. A gate whose false-positive rate is
   nonzero is a gate that gets suppressed.

`_plan/` is `.gitignore`d, so the coverage test asks `plan.require()` first and skips with a reason
when the design tree is absent. The shape and behaviour tests need no plan and always run.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]
BANK = REPO / "tools" / "semgrep" / "omniweave.yaml"
HARNESS = REPO / "tools" / "gate_semgrep.py"


def _load_harness() -> ModuleType:
    """Load `tools/gate_semgrep.py` by path — it is a script, not an installed module.

    The module is registered in `sys.modules` *before* it executes because `dataclasses` resolves a
    field's annotation through `sys.modules[cls.__module__]`, and a module that is not there yet
    makes every `@dataclass` in the file raise on definition.
    """
    spec = importlib.util.spec_from_file_location("omniweave_gate_semgrep", HARNESS)
    assert spec is not None and spec.loader is not None, f"cannot load {HARNESS}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gate = _load_harness()


# ---------------------------------------------------------------------------
# A minimal structural reader for the bank
# ---------------------------------------------------------------------------
#
# There is no YAML reader in the standard library and `omniweave-core` has zero third-party runtime
# dependencies (INV-2, D1, G1); pyyaml is not in D1's dev group either. So the bank is read with an
# indentation scanner rather than parsed. That is enough for what this file asserts — which keys a
# rule declares and what text they contain — and it is honest about being a scanner: it never claims
# to have understood a value.

_RULE_START = re.compile(r"^  - id: (?P<rule_id>\S+)\s*$")
_RULE_KEY = re.compile(r"^    (?P<key>[a-z-]+):(?P<rest>.*)$")


def _rules() -> dict[str, dict[str, str]]:
    """Every rule in the bank, as `{rule id: {top-level key: raw block text}}`."""
    found: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    key: str | None = None
    for line in BANK.read_text(encoding="utf-8").splitlines():
        start = _RULE_START.match(line)
        if start is not None:
            current = {"id": start.group("rule_id")}
            found[start.group("rule_id")] = current
            key = None
            continue
        if current is None:
            continue
        match = _RULE_KEY.match(line)
        if match is not None:
            key = match.group("key")
            current[key] = match.group("rest").strip()
        elif key is not None and line.strip():
            current[key] = f"{current[key]}\n{line.strip()}"
    return found


RULES = _rules()

REQUIRED_KEYS = ("id", "message", "languages", "severity", "patterns")


# ---------------------------------------------------------------------------
# 02-architecture.md line 392, token by token
# ---------------------------------------------------------------------------

STORE_RULES = (
    "omniweave-no-sqlite3-connect-outside-store",
    "omniweave-no-sqlite3-commit-outside-store",
    "omniweave-no-sql-begin-outside-store",
    "omniweave-no-sqlite3-import-outside-store",
)
SUBPROCESS_RULE = "omniweave-no-subprocess-outside-toolchain-and-host-subproc"
ZIP_RULE = "omniweave-no-zipfile-write-outside-opc"
ARCHIVE_RULE = "omniweave-no-make-archive-outside-opc"
OTEL_RULE = "omniweave-no-opentelemetry-outside-otlp"
LOAD_RULE = "omniweave-no-entrypoint-load-under-drivers"
IMPORT_MODULE_RULE = "omniweave-no-import-module-outside-host"
DUNDER_IMPORT_RULE = "omniweave-no-dunder-import-outside-host"
ISLANDS_RULE = "omniweave-no-ambient-input-in-purity-islands"
EXCEPT_RULE = "omniweave-no-bare-except-around-identity"
REVISION_RULE = "omniweave-no-revision-main"
INVOKE_RULE = "omniweave-no-driverhost-invoke-outside-pipeline"
TEXT_COLUMN_RULE = "omniweave-no-second-text-column"
ABSENT_RULE = "omniweave-one-verdict-absent-site"

BAN_TOKENS: dict[str, tuple[str, ...]] = {
    # The bank's own path. Not a ban — the row names the file it is specifying.
    "tools/semgrep/omniweave.yaml": (),
    # `sqlite3.connect` / `conn.commit()` / `BEGIN` / `import sqlite3` outside
    # `omniweave_core/store/`
    "sqlite3.connect": (STORE_RULES[0],),
    "conn.commit()": (STORE_RULES[1],),
    "BEGIN": (STORE_RULES[2],),
    "import sqlite3": (STORE_RULES[3],),
    "omniweave_core/store/": STORE_RULES,
    # `subprocess` outside `toolchain.py` and `host/subproc.py`
    "subprocess": (SUBPROCESS_RULE,),
    "toolchain.py": (SUBPROCESS_RULE,),
    "host/subproc.py": (SUBPROCESS_RULE,),
    # `zipfile.ZipFile(..., 'w'|'a'|'x')` and `shutil.make_archive` outside `out/opc.py`
    "zipfile.ZipFile(..., 'w'\\|'a'\\|'x')": (ZIP_RULE,),
    "shutil.make_archive": (ARCHIVE_RULE,),
    "out/opc.py": (ZIP_RULE, ARCHIVE_RULE),
    # `opentelemetry` outside `omniweave_serve/otlp.py`
    "opentelemetry": (OTEL_RULE,),
    "omniweave_serve/otlp.py": (OTEL_RULE,),
    # `EntryPoint.load()` under `core/drivers/`
    "EntryPoint.load()": (LOAD_RULE,),
    "core/drivers/": (LOAD_RULE,),
    # `importlib.import_module` / `__import__` outside `host/`
    "importlib.import_module": (IMPORT_MODULE_RULE,),
    "__import__": (DUNDER_IMPORT_RULE,),
    "host/": (IMPORT_MODULE_RULE, DUNDER_IMPORT_RULE),
    # the eight ambient inputs, in library code
    "os.getcwd()": ("omniweave-no-getcwd-in-library-code",),
    'Path(".")': ("omniweave-no-relative-path-root-in-library-code",),
    "time.time()": ("omniweave-no-time-time-in-library-code",),
    "random": ("omniweave-no-random-in-library-code",),
    "secrets": ("omniweave-no-secrets-in-library-code",),
    "uuid4": ("omniweave-no-uuid4-in-library-code",),
    "datetime.now": ("omniweave-no-datetime-now-in-library-code",),
    "sys.exit": ("omniweave-no-sys-exit-in-library-code",),
    # "...and all of them in `route/eval.py`, `retrieve/plan.py` and every `omniweave-target-*`"
    "route/eval.py": (ISLANDS_RULE,),
    "retrieve/plan.py": (ISLANDS_RULE,),
    "omniweave-target-*": (ISLANDS_RULE,),
    # the rest of the row
    "except": (EXCEPT_RULE,),
    'revision="main"': (REVISION_RULE,),
    "DriverHost.invoke()": (INVOKE_RULE,),
    "run/pipeline.py": (INVOKE_RULE,),
    "html": (TEXT_COLUMN_RULE,),
    "markdown": (TEXT_COLUMN_RULE,),
    "md": (TEXT_COLUMN_RULE,),
    "return VerdictState.ABSENT": (ABSENT_RULE,),
}
"""Every backticked token of 02-architecture.md line 392, mapped to the rule(s) it orders.

A token may be a ban (`sqlite3.connect`), the scope of one (`omniweave_core/store/`) or the
exemption from one (`toolchain.py`); all three map to the rule that carries them, so the mapping is
total over the line. `tools/semgrep/omniweave.yaml` maps to nothing: the row names the file it is
specifying, which is this bank.
"""


def _plan_line_392(plan) -> str:
    """Line 392 of 02-architecture.md, 0-indexed as 391."""
    return plan.lines("02-architecture.md")[391]


# ---------------------------------------------------------------------------
# 1. Shape
# ---------------------------------------------------------------------------


def test_the_bank_exists_and_declares_rules() -> None:
    assert BANK.is_file(), f"the semgrep bank is missing at {BANK}"
    assert RULES, "the indentation scanner found no `- id:` rule in the bank"


@pytest.mark.parametrize("rule_id", sorted(RULES))
@pytest.mark.parametrize("key", REQUIRED_KEYS)
def test_every_rule_declares_the_required_keys(rule_id: str, key: str) -> None:
    assert key in RULES[rule_id], f"{rule_id} has no `{key}:` block"
    assert RULES[rule_id][key].strip(), f"{rule_id}'s `{key}:` block is empty"


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_is_a_python_error_rule(rule_id: str) -> None:
    rule = RULES[rule_id]
    assert rule["languages"] == "[python]", f"{rule_id} languages is {rule['languages']!r}"
    assert rule["severity"] == "ERROR", f"{rule_id} severity is {rule['severity']!r}"


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_id_is_namespaced_and_kebab_case(rule_id: str) -> None:
    assert re.fullmatch(r"omniweave(-[a-z0-9]+)+", rule_id), rule_id


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_message_names_a_plan_locus(rule_id: str) -> None:
    """A message a developer cannot act on is a rule that gets `# nosemgrep`-ed.

    The bank's own header says so, and the house style makes the locus load-bearing: the message has
    to say WHERE the ban is written down, not only what it forbids.
    """
    message = RULES[rule_id]["message"]
    assert "02-architecture.md" in message, f"{rule_id}'s message cites no 02-architecture locus"
    assert "line 392" in message, f"{rule_id}'s message does not cite line 392"
    assert len(message) > 200, f"{rule_id}'s message is too short to carry a reason"


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_carries_its_ban_and_plan_metadata(rule_id: str) -> None:
    metadata = RULES[rule_id]["metadata"]
    assert "ban:" in metadata, f"{rule_id} has no metadata.ban"
    assert "plan:" in metadata, f"{rule_id} has no metadata.plan"


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_names_a_gate(rule_id: str) -> None:
    """G8 and G24 are the two gate ids 02-architecture.md line 392 assigns this bank."""
    metadata = RULES[rule_id]["metadata"]
    assert "G8" in metadata or "G24" in metadata, f"{rule_id} names neither G8 nor G24"


# ---------------------------------------------------------------------------
# 2. Coverage against the plan — the valuable test
# ---------------------------------------------------------------------------


def test_the_mapping_covers_exactly_the_tokens_line_392_carries(plan) -> None:
    """`BAN_TOKENS` and 02-architecture.md line 392 name the same set of things.

    Both directions matter. A token on the line with no mapping entry is a ban the plan ordered and
    the bank does not carry. A mapping entry with no token on the line is a rule enforcing something
    the plan no longer says — which is how a bank drifts into being its own authority.
    """
    plan.require()
    line = _plan_line_392(plan)
    assert "| semgrep |" in line, (
        "02-architecture.md line 392 is no longer the semgrep row of section 3.3's table; "
        f"it reads: {line[:120]!r}"
    )
    tokens = set(re.findall(r"`([^`]+)`", line))
    assert tokens == set(BAN_TOKENS), (
        f"only on the line: {sorted(tokens - set(BAN_TOKENS))}; "
        f"only in the mapping: {sorted(set(BAN_TOKENS) - tokens)}"
    )


def test_every_ban_the_plan_names_has_a_rule_in_the_bank() -> None:
    missing = {
        token: [rule for rule in rules if rule not in RULES]
        for token, rules in BAN_TOKENS.items()
        if any(rule not in RULES for rule in rules)
    }
    assert not missing, f"bans with no rule in the bank: {missing}"


def test_the_bank_carries_no_rule_the_plan_did_not_order() -> None:
    mapped = {rule for rules in BAN_TOKENS.values() for rule in rules}
    assert set(RULES) == mapped, (
        f"in the bank but unmapped: {sorted(set(RULES) - mapped)}; "
        f"mapped but absent from the bank: {sorted(mapped - set(RULES))}"
    )


def test_each_rule_scopes_itself_on_the_paths_the_plan_names(plan) -> None:
    """A scope token from line 392 appears in the `paths` block of the rule it scopes.

    `omniweave_core/store/` has to be in the four store rules' `paths`, `toolchain.py` in the
    subprocess rule's, and so on. Without this a rule can be correct and universally excluded.
    """
    plan.require()
    scopes = {
        "omniweave_core/store/": STORE_RULES,
        "toolchain.py": (SUBPROCESS_RULE,),
        "host/subproc.py": (SUBPROCESS_RULE,),
        "out/opc.py": (ZIP_RULE, ARCHIVE_RULE),
        "omniweave_serve/otlp.py": (OTEL_RULE,),
        "drivers/": (LOAD_RULE,),
        "host/": (IMPORT_MODULE_RULE, DUNDER_IMPORT_RULE),
        "route/eval.py": (ISLANDS_RULE,),
        "retrieve/plan.py": (ISLANDS_RULE,),
        "omniweave-target-": (ISLANDS_RULE,),
        "run/pipeline.py": (INVOKE_RULE,),
        "retrieve/verdict.py": (ABSENT_RULE,),
    }
    for fragment, rule_ids in scopes.items():
        for rule_id in rule_ids:
            assert fragment in RULES[rule_id]["paths"], (
                f"{rule_id}'s paths block does not mention {fragment!r}"
            )


def test_the_two_docling_receipts_are_quoted_where_the_plan_puts_them(plan) -> None:
    """The `EntryPoint.load()` and `revision="main"` messages carry their mined defect.

    04-driver-system.md section 4.6 gives the first (`base_factory.py:96`, with the
    `allow_external_plugins` test one loop later at `:98-105`) and section 2.4 the second (six
    `layout_model_specs.py` declaration sites against the field's own annotation at `:44`). A
    message that states a ban without its receipt is a message a developer argues with.
    """
    plan.require()
    driver_doc = plan.text("04-driver-system.md")
    load_message = RULES[LOAD_RULE]["message"]
    for fragment in ("base_factory.py:96", "load_setuptools_entrypoints", ":98-105"):
        assert fragment in driver_doc, f"{fragment!r} is not in 04-driver-system.md any more"
        assert fragment in load_message, f"{LOAD_RULE}'s message omits {fragment!r}"
    revision_message = RULES[REVISION_RULE]["message"]
    for fragment in ("layout_model_specs.py:87,94,101,108,115,122", ":44"):
        assert fragment in driver_doc, f"{fragment!r} is not in 04-driver-system.md any more"
        assert fragment in revision_message, f"{REVISION_RULE}'s message omits {fragment!r}"


# ---------------------------------------------------------------------------
# 3. The `ast` half — glob semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "rel", "expected"),
    [
        ("packages/*/src/**", "packages/omniweave-core/src/omniweave_core/x.py", True),
        ("packages/*/src/**", "packages/omniweave-core/src/a/b/c/x.py", True),
        # `*` must not cross a separator, or every rule's scope silently widens.
        ("packages/*/src/**", "packages/a/b/src/x.py", False),
        ("packages/*/src/**", "packages/omniweave-core/tests/unit/x.py", False),
        ("packages/*/src/**", "tools/gate_semgrep.py", False),
        # A pattern is anchored at both ends: a prefix match is not a match.
        ("packages/omniweave-core/src/omniweave_core/store/**", "packages/x.py", False),
        (
            "packages/omniweave-core/src/omniweave_core/store/**",
            "packages/omniweave-core/src/omniweave_core/store/sqlite.py",
            True,
        ),
        (
            "packages/omniweave-core/src/omniweave_core/store/**",
            "packages/omniweave-core/src/omniweave_core/store_helpers.py",
            False,
        ),
        ("packages/omniweave-target-*/src/**", "packages/omniweave-target-deck/src/a.py", True),
        ("packages/omniweave-target-*/src/**", "packages/omniweave-core/src/a.py", False),
        ("packages/omniweave/src/omniweave/route/eval.py", "packages/omniweave/src/x.py", False),
    ],
)
def test_path_matches_agrees_with_semgrep_glob_semantics(
    pattern: str, rel: str, expected: bool
) -> None:
    assert gate.path_matches(pattern, rel) is expected


# ---------------------------------------------------------------------------
# 3b. The `ast` half — every ban fires where it should and nowhere else
# ---------------------------------------------------------------------------

CORE = "packages/omniweave-core/src/omniweave_core"
STORE_FILE = f"{CORE}/store/sqlite.py"
HOST_FILE = f"{CORE}/host/inproc.py"
DRIVERS_FILE = f"{CORE}/drivers/card.py"
OPC_FILE = f"{CORE}/out/opc.py"
OTLP_FILE = "packages/omniweave-serve/src/omniweave_serve/otlp.py"
TOOLCHAIN_FILE = f"{CORE}/toolchain.py"
SUBPROC_FILE = f"{CORE}/host/subproc.py"
PIPELINE_FILE = "packages/omniweave/src/omniweave/run/pipeline.py"
VERDICT_FILE = f"{CORE}/retrieve/verdict.py"
PLAIN = f"{CORE}/model/block.py"
ISLAND = "packages/omniweave/src/omniweave/route/eval.py"
TARGET = "packages/omniweave-target-deck/src/omniweave_target_deck/lower.py"
TEST_TREE = "packages/omniweave-core/tests/unit/test_determinism.py"
#  D435: a process entry point is exempt from the cwd and exit bans, and from nothing else.
ENTRY_FILE = "packages/omniweave/src/omniweave/__main__.py"

# (rule id, source that must fire, path where it fires, path where the same source is exempt)
POSITIVE: tuple[tuple[str, str, str, str | None], ...] = (
    (STORE_RULES[0], "import sqlite3\nc = sqlite3.connect('x')\n", PLAIN, STORE_FILE),
    (STORE_RULES[1], "def f(conn):\n    conn.commit()\n", PLAIN, STORE_FILE),
    (STORE_RULES[3], "import sqlite3\n", PLAIN, STORE_FILE),
    (SUBPROCESS_RULE, "import subprocess\n", PLAIN, TOOLCHAIN_FILE),
    (SUBPROCESS_RULE, "import subprocess\n", PLAIN, SUBPROC_FILE),
    (SUBPROCESS_RULE, "from subprocess import run\n", PLAIN, TOOLCHAIN_FILE),
    (ZIP_RULE, "import zipfile\nz = zipfile.ZipFile(p, 'w')\n", PLAIN, OPC_FILE),
    (ZIP_RULE, "import zipfile\nz = zipfile.ZipFile(p, mode='a')\n", PLAIN, OPC_FILE),
    (ARCHIVE_RULE, "import shutil\nshutil.make_archive(a, 'zip', b)\n", PLAIN, OPC_FILE),
    (OTEL_RULE, "from opentelemetry import trace\n", PLAIN, OTLP_FILE),
    (LOAD_RULE, "def f(ep):\n    return ep.load()\n", DRIVERS_FILE, None),
    (IMPORT_MODULE_RULE, "import importlib\nimportlib.import_module('x')\n", PLAIN, HOST_FILE),
    (DUNDER_IMPORT_RULE, "m = __import__('x')\n", PLAIN, HOST_FILE),
    ("omniweave-no-getcwd-in-library-code", "import os\nd = os.getcwd()\n", PLAIN, ENTRY_FILE),
    (
        "omniweave-no-getcwd-in-library-code",
        "from pathlib import Path\nd = Path.cwd()\n",
        PLAIN,
        ENTRY_FILE,
    ),
    (
        "omniweave-no-relative-path-root-in-library-code",
        "from pathlib import Path\nr = Path('.')\n",
        PLAIN,
        None,
    ),
    ("omniweave-no-time-time-in-library-code", "import time\nt = time.time()\n", PLAIN, None),
    ("omniweave-no-random-in-library-code", "import random\n", PLAIN, None),
    ("omniweave-no-secrets-in-library-code", "import secrets\nsecrets.token_hex()\n", PLAIN, None),
    ("omniweave-no-uuid4-in-library-code", "import uuid\ni = uuid.uuid4()\n", PLAIN, None),
    (
        "omniweave-no-datetime-now-in-library-code",
        "import datetime\nn = datetime.datetime.now()\n",
        PLAIN,
        None,
    ),
    ("omniweave-no-sys-exit-in-library-code", "import sys\nsys.exit(1)\n", PLAIN, ENTRY_FILE),
    ("omniweave-no-sys-exit-in-library-code", "raise SystemExit(2)\n", PLAIN, ENTRY_FILE),
    (ISLANDS_RULE, "import time\nd = time.monotonic()\n", ISLAND, PLAIN),
    (ISLANDS_RULE, "import random\n", TARGET, None),
    (
        EXCEPT_RULE,
        "def f(b):\n    try:\n        return compute_digest(b)\n    except Exception:\n"
        "        return None\n",
        PLAIN,
        None,
    ),
    (REVISION_RULE, "load_model(name, revision='main')\n", PLAIN, None),
    (REVISION_RULE, "model_revision = 'main'\n", PLAIN, None),
    (INVOKE_RULE, "def f(host, b):\n    return host.invoke(b)\n", PLAIN, PIPELINE_FILE),
    (
        TEXT_COLUMN_RULE,
        "class Block:\n    text: str\n    markdown: str\n",
        PLAIN,
        None,
    ),
    (ABSENT_RULE, "def f():\n    return VerdictState.ABSENT\n", PLAIN, VERDICT_FILE),
)


@pytest.mark.parametrize(("rule_id", "source", "where", "exempt"), POSITIVE)
def test_the_ast_half_fires_where_the_ban_applies(
    rule_id: str, source: str, where: str, exempt: str | None
) -> None:
    del exempt
    fired = {f.rule_id for f in gate.check_source(where, source)}
    assert rule_id in fired, f"{rule_id} did not fire on {where}:\n{source}"


@pytest.mark.parametrize(("rule_id", "source", "where", "exempt"), POSITIVE)
def test_the_ast_half_is_silent_in_the_exempted_home(
    rule_id: str, source: str, where: str, exempt: str | None
) -> None:
    """The exemption is half the ban: a rule firing in `store/` too is one nobody can obey.

    Where 02-architecture.md line 392 grants no exempted home — the eight ambient inputs, the bare
    `except`, `revision="main"`, the `html`/`markdown`/`md` field — the scope boundary itself is the
    exemption, so the row is checked against a test path instead. Both are the same assertion: the
    ban has an edge, and the matcher respects it.
    """
    del where
    home = exempt if exempt is not None else TEST_TREE
    fired = {f.rule_id for f in gate.check_source(home, source)}
    assert rule_id not in fired, f"{rule_id} fired outside its own scope, in {home}:\n{source}"


# Sources a naive matcher flags and this one must not. Each is a real shape from the plan.
DECOYS: tuple[tuple[str, str, str], ...] = (
    (
        LOAD_RULE,
        DRIVERS_FILE,
        "import tomllib\n\ndef read(f):\n    return tomllib.load(f)\n",
    ),
    (
        TEXT_COLUMN_RULE,
        PLAIN,
        "class Doc:\n    def markdown(self) -> str:\n        return serialize(self, 'md')[0]\n",
    ),
    (
        EXCEPT_RULE,
        PLAIN,
        "def f(b):\n    try:\n        return compute_digest(b)\n    except ValueError as exc:\n"
        "        raise DigestError(str(exc)) from exc\n",
    ),
    (
        EXCEPT_RULE,
        PLAIN,
        "def f(b):\n    try:\n        return render(b)\n    except Exception:\n        return ''\n",
    ),
    (ZIP_RULE, PLAIN, "import zipfile\nz = zipfile.ZipFile(p, 'r')\n"),
    (ZIP_RULE, PLAIN, "import zipfile\nz = zipfile.ZipFile(p)\n"),
    (
        REVISION_RULE,
        PLAIN,
        "load_model(name, revision='5617a9f61b028005a4858fdac845db406aefb181')\n",
    ),
    (
        "omniweave-no-relative-path-root-in-library-code",
        PLAIN,
        "from pathlib import Path\nr = Path('/var/lib') / 'ow'\n",
    ),
    ("omniweave-no-time-time-in-library-code", PLAIN, "import time\nd = time.monotonic_ns()\n"),
    (STORE_RULES[1], PLAIN, "def f(tx):\n    tx.commit(force=True)\n"),
    (INVOKE_RULE, PIPELINE_FILE, "def f(host, b):\n    return host.invoke(b)\n"),
    (ABSENT_RULE, VERDICT_FILE, "def f():\n    return VerdictState.ABSENT\n"),
)


@pytest.mark.parametrize(("rule_id", "where", "source"), DECOYS)
def test_the_ast_half_does_not_fire_on_a_near_miss(rule_id: str, where: str, source: str) -> None:
    fired = {f.rule_id for f in gate.check_source(where, source)}
    assert rule_id not in fired, f"{rule_id} false-positived on {where}:\n{source}"


def test_a_test_tree_is_not_library_code() -> None:
    """Every library-code ban stops at `src/`. A test has to be able to write the banned shape."""
    source = "import random\nimport time\n\ndef test_x():\n    assert time.time() > 0\n"
    rel = "packages/omniweave-core/tests/unit/test_determinism.py"
    assert gate.check_source(rel, source) == []


def test_a_syntax_error_yields_no_findings_rather_than_raising() -> None:
    """A broken tree is `ruff`'s to report; guessing at it produces noise, not a gate."""
    assert gate.check_source(PLAIN, "def f(:\n") == []


# ---------------------------------------------------------------------------
# 3c. SV8's count — the half semgrep has no operator for
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_one_verdict_absent_site_inside_verdict_py_is_allowed(tmp_path: Path) -> None:
    _write(tmp_path, VERDICT_FILE, "def build():\n    return VerdictState.ABSENT\n")
    assert gate.ast_findings(tmp_path) == []


def test_a_second_verdict_absent_site_is_rejected_even_inside_verdict_py(tmp_path: Path) -> None:
    """INV-11/SV8 is a **count**, and the bank cannot express one — this is why the harness exists.

    The YAML rule confines the return to `omniweave_core/retrieve/verdict.py`; two returns inside
    that one file still satisfy it, and two returns are two citability rules.
    """
    _write(
        tmp_path,
        VERDICT_FILE,
        "def build(hits, gates):\n"
        "    if not hits:\n"
        "        return VerdictState.ABSENT\n"
        "    if gates.all_passed:\n"
        "        return VerdictState.ABSENT\n"
        "    return VerdictState.PRESENT\n",
    )
    findings = gate.ast_findings(tmp_path)
    assert [f.rule_id for f in findings] == [ABSENT_RULE], findings
    assert findings[0].line == 5, findings


def test_a_verdict_absent_site_outside_verdict_py_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, PLAIN, "def f():\n    return VerdictState.ABSENT\n")
    assert [f.rule_id for f in gate.ast_findings(tmp_path)] == [ABSENT_RULE]


# ---------------------------------------------------------------------------
# 3d. The two halves agree, and the live tree is clean
# ---------------------------------------------------------------------------


def test_every_bank_rule_is_implemented_or_declared_semgrep_only() -> None:
    """No rule may fall between the two halves without saying so.

    `SEMGREP_ONLY_BANS` is the declared gap. Anything else in the bank must appear as a `rule_id` in
    the harness, or a Windows developer gets a green gate for a ban nothing checked.
    """
    implemented = set(re.findall(r'rule_id="([^"]+)"', HARNESS.read_text(encoding="utf-8")))
    unimplemented = set(RULES) - implemented - set(gate.SEMGREP_ONLY_BANS)
    assert not unimplemented, f"in the bank, checked by neither half: {sorted(unimplemented)}"
    assert set(gate.SEMGREP_ONLY_BANS) <= set(RULES), "SEMGREP_ONLY_BANS names a rule that is gone"
    assert not (implemented & set(gate.SEMGREP_ONLY_BANS)), (
        "a rule is both declared semgrep-only and implemented in ast — pick one"
    )


def test_the_ast_half_and_the_bank_scope_library_code_identically() -> None:
    """Both halves say `packages/*/src/**`. A drift here is a silently narrowed ban."""
    assert gate.LIBRARY == ("packages/*/src/**",)
    for rule_id in RULES:
        paths = RULES[rule_id].get("paths", "")
        assert "packages/" in paths, f"{rule_id} declares no paths scope at all"


def test_the_committed_tree_passes_the_ast_half() -> None:
    """The gate's own subject: `packages/*/src/**` as committed carries no violation."""
    findings = gate.ast_findings(REPO)
    assert findings == [], "\n".join(f.render() for f in findings)


def test_the_harness_reports_semgrep_absence_rather_than_failing() -> None:
    """An unrunnable gate that reports failure trains people to ignore it (this file's premise)."""
    code = gate.main(["--ast-only", "--root", str(REPO)])
    assert code == 0
    assert isinstance(gate.semgrep_available(), bool)


def test_the_bank_is_valid_yaml_where_a_yaml_reader_is_available() -> None:
    """Opportunistic: parse the bank properly when a YAML reader happens to be importable.

    `pyyaml` is not in charter D1's dev group and `omniweave-core` may not depend on it, so this
    test skips rather than requiring it — but where semgrep's own environment has pulled one in, a
    real parse catches the failure the indentation scanner above cannot see: a YAML syntax error
    that makes semgrep load zero rules and report a clean run.
    """
    yaml = pytest.importorskip("yaml", reason="no YAML reader in this environment (not in D1)")
    parsed = yaml.safe_load(BANK.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict) and "rules" in parsed
    ids = [rule["id"] for rule in parsed["rules"]]
    assert len(ids) == len(set(ids)), "the bank declares a duplicate rule id"
    assert set(ids) == set(RULES), "the scanner and a real YAML parse disagree about the rule set"
    for rule in parsed["rules"]:
        for key in REQUIRED_KEYS:
            assert key in rule, f"{rule['id']} has no `{key}`"
        assert isinstance(rule["patterns"], list) and rule["patterns"], rule["id"]
        assert rule["languages"] == ["python"], rule["id"]
        assert rule["severity"] == "ERROR", rule["id"]
        assert set(rule.get("paths", {})) <= {"include", "exclude"}, rule["id"]
        assert {"ban", "plan"} <= set(rule["metadata"]), rule["id"]
