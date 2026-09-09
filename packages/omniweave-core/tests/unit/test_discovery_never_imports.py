"""INV-4 layer 3 — discovery discovers thirty cards and imports none of them.

04-driver-system.md section 4.6 is "the one decision here that cannot be reversed", and it is
enforced three times over. Layer 1 is `tools/semgrep/omniweave.yaml`, which bans `EntryPoint.load()`
under `omniweave_core/drivers/` alongside `importlib.import_module` and `__import__` outside
`host/`. Layer 2 is G11, which installs a rogue driver whose module body writes a file and raises
`SystemExit` and asserts `ow doctor` succeeds and the file is absent. **Layer 3 is this file**: a
core test discovers thirty cards and asserts `sys.modules` gains no `omniweave_driver_*` key
(01-principles.md INV-4, "Enforced by ... `X`").

**A `sys.modules` assertion that can only pass is not a gate**, which is why the last test here is a
negative control: the same thirty fixture distributions, the same instrument, and one real import,
which the instrument must see. Without it, a typo in the module prefix, a fixture site that was
never on `sys.path`, or a `discover()` that silently found nothing would all read as a pass.

The instrument is deliberately doubled. Each fixture module body **writes a sentinel file** as its
very first statement, so an import leaves evidence on disk that survives even if the module is later
evicted from `sys.modules`; and `sys.modules` is read for `omniweave_driver_*` keys, which is the
assertion the plan prints. The fresh interpreter is the only place either is observable — once a
test process has imported one of these for its own reasons, `sys.modules` can no longer tell you
whether discovery did it.

The charter records exactly what the alternative costs.
`docling/docling/models/factories/base_factory.py:96` calls
`plugin_manager.load_setuptools_entrypoints(plugin_name)`, and the `allow_external_plugins` test
sits in the **next** loop over `list_name_plugin()` at `:98-105` — so that gate suppresses
*registration* by code which has already *executed*, and `process_plugin` then swallows a duplicate
as a `logger.warning`. Four consequences omniweave cannot accept: no licence gate before execution,
no cost evidence without paying the import, no catalog without importing everything, and
order-dependent registration.

Specified in 04-driver-system.md section 4.6 clause 3 and 01-principles.md INV-4. Discipline copied
from `packages/omniweave-core/tests/test_g17.py`, which is the same instrument for the same class
of claim.
"""

from __future__ import annotations

import json
import subprocess  # noqa: TID251 — a fresh interpreter is the only witness for INV-4 layer 3.
import sys
from pathlib import Path

import pytest

# Thirty, because that is the number 04-driver-system.md section 4.6 clause 3 and
# 01-principles.md's INV-4 enforcement note both print: "a core test discovers 30 cards".
CARD_COUNT = 30

MODULE_PREFIX = "omniweave_driver_"

CARD = """card_schema = 1

[driver]
id = "parse.notebook.n{n:02d}"
port = "parse/1"
version = "0.1.0"
schema_version = 1
entrypoint = "omniweave_driver_n{n:02d}.driver:Cls"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["application/x-ipynb+json"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""

# The module body that makes an import OBSERVABLE. It is the first statement in the file, before
# any other import, so a partial import still leaves the sentinel: an import that raised halfway
# is an import, and INV-4 forbids the execution rather than the completion.
MODULE_BODY = '''"""A fixture driver whose module body is evidence."""
import pathlib as _p

_p.Path(__file__).parent.parent.joinpath("sentinels", "{name}.imported").write_text("yes")
import os as _os

_os.environ["OMNIWEAVE_TEST_DRIVER_IMPORTED"] = "{name}"
'''

# The program the fresh interpreter runs. It reports three things: what discovery found, which
# `omniweave_driver_*` modules ended up in `sys.modules`, and which sentinel files exist. The
# `EXTRA` slot is where the negative control puts its real import.
PROGRAM = """
import json, sys
from importlib.metadata import Distribution
from pathlib import Path

SITE = {site!r}
sys.path.insert(0, SITE)

from omniweave_core.discovery import discover

result = discover(
    search_path=[SITE],
    distributions=list(Distribution.discover(path=[SITE])),
    tombstone_dir=Path(SITE) / "no-tombstones",
)
{extra}
print(json.dumps({{
    "cards": sorted(f.card.identity.id for f in result.found),
    "faults": [f.detail for f in result.faults],
    "modules": sorted(m for m in sys.modules if m.startswith({prefix!r})),
    "sentinels": sorted(p.name for p in (Path(SITE) / "sentinels").iterdir()),
}}))
"""


def build_site(root: Path, count: int = CARD_COUNT) -> Path:
    """`count` installed distributions, each one a package whose import would be visible.

    A real `*.dist-info` with a real `entry_points.txt`, a real package directory with a real
    `driver.toml` and a real `__init__.py` — `importlib.metadata` enumerates these exactly as it
    enumerates a wheel, and `Distribution.locate_file` resolves the card out of them exactly as
    it does for one.
    """
    site = root / "site"
    (site / "sentinels").mkdir(parents=True)
    for n in range(count):
        name = f"{MODULE_PREFIX}n{n:02d}"
        pkg = site / name
        pkg.mkdir()
        (pkg / "__init__.py").write_text(MODULE_BODY.format(name=name), encoding="utf-8")
        (pkg / "driver.toml").write_text(CARD.format(n=n), encoding="utf-8")
        info = site / f"{name}-1.0.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name.replace('_', '-')}\nVersion: 1.0.0\n",
            encoding="utf-8",
        )
        (info / "entry_points.txt").write_text(
            f"[omniweave.drivers]\nparse.notebook.n{n:02d} = {name}\n", encoding="utf-8"
        )
    return site


def observe(site: Path, *, extra: str = "") -> dict[str, list[str]]:
    """Run the program in a fresh interpreter and return what it saw."""
    source = PROGRAM.format(site=str(site), extra=extra, prefix=MODULE_PREFIX)
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """One fixture site for the module. Building thirty distributions is not free, and every
    test here wants the identical tree — a difference between them would make the negative
    control prove something about a different site than the positive one."""
    return build_site(tmp_path_factory.mktemp("never_imports"))


def test_discovering_thirty_cards_adds_no_omniweave_driver_module_to_sys_modules(
    site: Path,
) -> None:
    """INV-4, stated exactly as 04-driver-system.md section 4.6 clause 3 states it.

    Thirty cards discovered, `sys.modules` gains no `omniweave_driver_*` key, and not one of the
    thirty sentinel files exists. The card set is asserted first and by name: an assertion that
    nothing was imported is worthless if nothing was read either, and "discovery found no cards"
    is the failure mode most likely to make this test green for the wrong reason.
    """
    seen = observe(site)
    assert seen["cards"] == [f"parse.notebook.n{n:02d}" for n in range(CARD_COUNT)]
    assert seen["faults"] == []
    assert seen["modules"] == [], "discovery imported a driver package"
    assert seen["sentinels"] == [], "a driver module body ran during discovery"


def test_the_instrument_sees_an_import_when_one_really_happens(site: Path) -> None:
    """THE NEGATIVE CONTROL. Without it the test above can only pass.

    The same site, the same thirty distributions, the same two instruments — plus one real
    `import omniweave_driver_n00`. Both instruments must fire: the module appears in
    `sys.modules` and its sentinel file appears on disk. If this test ever goes green with an
    empty `modules` or `sentinels`, the gate above is measuring nothing and the failure is
    *here*, not there.

    Only one of the thirty is imported, so the control also proves the instruments are specific:
    they report the module that ran and not the twenty-nine that did not.
    """
    seen = observe(site, extra=f"import {MODULE_PREFIX}n00")
    assert seen["cards"] == [f"parse.notebook.n{n:02d}" for n in range(CARD_COUNT)]
    assert seen["modules"] == [f"{MODULE_PREFIX}n00"]
    assert seen["sentinels"] == [f"{MODULE_PREFIX}n00.imported"]


def test_discovery_reads_the_card_of_a_package_whose_import_would_raise(tmp_path: Path) -> None:
    """G11's shape, in-process: a rogue driver whose module body raises `SystemExit`.

    `sys.exit` is banned in library code, but a *driver* is third-party code and may do anything
    at all — which is the whole reason the card is read rather than the module imported. If
    discovery touched the module, this call would not return a card; it would take the process
    down, and `ow doctor` would exit non-zero on a machine where one installed wheel is hostile.
    """
    site = tmp_path / "site"
    (site / "sentinels").mkdir(parents=True)
    pkg = site / f"{MODULE_PREFIX}rogue"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        'raise SystemExit("a hostile driver module body")\n', encoding="utf-8"
    )
    (pkg / "driver.toml").write_text(CARD.format(n=0), encoding="utf-8")
    info = site / f"{MODULE_PREFIX}rogue-1.0.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: omniweave-driver-rogue\nVersion: 1.0.0\n", encoding="utf-8"
    )
    (info / "entry_points.txt").write_text(
        f"[omniweave.drivers]\nparse.notebook.n00 = {MODULE_PREFIX}rogue\n", encoding="utf-8"
    )

    from importlib.metadata import Distribution  # noqa: PLC0415 - scoped to the fixture site

    from omniweave_core.discovery import discover  # noqa: PLC0415 - after the fixture exists

    result = discover(
        search_path=[str(site)],
        distributions=list(Distribution.discover(path=[str(site)])),
        tombstone_dir=site / "no-tombstones",
    )
    assert [f.card.identity.id for f in result.found] == ["parse.notebook.n00"]
    assert f"{MODULE_PREFIX}rogue" not in sys.modules


def test_the_discovery_module_calls_no_importer_anywhere_in_its_ast() -> None:
    """Layer 1's assertion, read off the parse tree rather than off a grep.

    `EntryPoint.load()`, `importlib.import_module` and `__import__` are banned by
    `tools/semgrep/omniweave.yaml`, and semgrep publishes no Windows wheel — so on a third of the
    nine-cell CI matrix this check is the only one of the two that runs. It is not a substitute
    for the rule; it is the rule's witness on the platform the rule cannot reach.

    **It counts call sites, not mentions.** `discovery.py`'s own module docstring names all three
    importers, in the sentence explaining that it does not use them, and a naive `in source`
    check would fail on exactly the file that is most careful about the rule. `ast` sees a
    `Call`, so prose is invisible to it and a call is not.

    `.load(` is matched on the attribute name without a receiver, because an entry point's
    receiver can be named anything and the semgrep rule flags `$EP.load(...)` for that reason;
    the stdlib deserialisers the rule exempts (`tomllib`, `json`, `toml`, `yaml`, `pickle`,
    `marshal`) are exempted here identically, and `json.loads` is a different attribute again.
    """
    import ast  # noqa: PLC0415

    import omniweave_core.discovery as discovery_module  # noqa: PLC0415

    exempt = {"tomllib", "json", "toml", "yaml", "pickle", "marshal"}
    tree = ast.parse(Path(discovery_module.__file__).read_text(encoding="utf-8"))
    offences: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in {"__import__", "import_module"}:
                offences.append(f"{func.id}() at line {node.lineno}")
            if isinstance(func, ast.Attribute) and func.attr in {"load", "import_module"}:
                receiver = ast.unparse(func.value)
                if receiver.split(".")[0] not in exempt:
                    offences.append(f"{receiver}.{func.attr}() at line {node.lineno}")
        if isinstance(node, ast.Import):
            offences.extend(
                f"import {alias.name} at line {node.lineno}"
                for alias in node.names
                if alias.name == "importlib"
            )
        if isinstance(node, ast.ImportFrom) and node.module == "importlib":
            offences.extend(
                f"from importlib import {alias.name} at line {node.lineno}"
                for alias in node.names
                if alias.name == "import_module"
            )
    assert offences == [], f"discovery.py reaches for an importer: {offences}"
