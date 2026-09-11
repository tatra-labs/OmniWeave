"""`activate()` — the framework's ONLY importer, and the three refusals it makes first.

04-driver-system.md:1518-1519: refusal happens at four distinct points "and **none of them imports
the driver except the last**". This file is the last one's test, and its shape follows from that
sentence: every assertion is either about a refusal made BEFORE `import_module` runs, or about the
`import_module` call itself being the last thing that happens.

`host/inproc.py:47-49` recorded the gap this module fills — "`activate()` ... does not exist in the
tree yet" — and `DriverGuard.check_code()` now delegates to `check_card_code()`, so the two halves
of step 4 compare the same two fields against the same card through one function.

Specified in 04-driver-system.md section 5.3 step 4 and section 4.6; INV-4, DR19.
"""

from __future__ import annotations

import ast
import hashlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave_core.drivers.card import DriverCard, load_card
from omniweave_core.errors import DriverHostError
from omniweave_core.host.activate import (
    ACTIVATION_FAILED,
    activate,
    check_card_code,
    code_fingerprint,
    entrypoint_parts,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

CARD = """card_schema = 1

[driver]
id = "parse.text.{name}"
port = "{port}"
version = "0.1.0"
schema_version = {schema}
entrypoint = "{entrypoint}"
granularity = "document"
replay_class = "byte_exact"

[capability]
formats = ["text/plain"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"
"""

MODULE = '''"""A driver for {name}."""

class Driver:
    PORT = "{port}"
    SCHEMA_VERSION = {schema}

NotAClass = 7
'''


def _card(
    tmp_path: Path,
    name: str,
    *,
    port: str = "parse/1",
    schema: int = 1,
    module_port: str | None = None,
    module_schema: int | None = None,
    attr: str = "Driver",
) -> DriverCard:
    """Write a real package and a real card, and load the card through the real loader."""
    package = f"owtestdrv_{name}"
    root = tmp_path / package
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text(
        MODULE.format(name=name, port=module_port or port, schema=module_schema or schema),
        encoding="utf-8",
    )
    raw = CARD.format(name=name, port=port, schema=schema, entrypoint=f"{package}:{attr}").encode(
        "utf-8"
    )
    if str(tmp_path) not in sys.path:
        sys.path.insert(0, str(tmp_path))
    loaded = load_card(raw, origin="driver_path", source=str(tmp_path / "driver.toml"))
    assert isinstance(loaded, DriverCard)
    return loaded


@pytest.fixture(autouse=True)
def _clean_modules() -> Iterator[None]:
    """Evict every test driver afterwards, so one test cannot serve another's import.

    A module left in `sys.modules` would make the NEXT test's `activate()` return the PREVIOUS
    test's class -- which is exactly the contamination `purity` exists to detect one layer up, and
    it would make the failure tests here pass for the wrong reason.
    """
    yield
    for name in [key for key in sys.modules if key.startswith("owtestdrv_")]:
        del sys.modules[name]


def test_activate_returns_the_class_the_entrypoint_names(tmp_path: Path) -> None:
    loaded = activate(_card(tmp_path, "ok"))
    assert isinstance(loaded, type)
    assert loaded.__name__ == "Driver"
    assert loaded.PORT == "parse/1"


def test_activate_is_the_only_place_a_driver_module_runs(tmp_path: Path) -> None:
    """The module must be absent from `sys.modules` until `activate()` is called.

    A positive control for INV-4 at this seam: loading a card imports nothing, and the import
    happens on the line that is supposed to perform it.
    """
    card = _card(tmp_path, "lazy")
    assert not [k for k in sys.modules if k.startswith("owtestdrv_lazy")]
    activate(card)
    assert [k for k in sys.modules if k.startswith("owtestdrv_lazy")]


def test_a_port_mismatch_is_card_code_mismatch_and_names_both_sides(tmp_path: Path) -> None:
    """04-driver-system.md:1543: `loaded PORT != card.port -> CARD_CODE_MISMATCH`."""
    card = _card(tmp_path, "portmix", module_port="derive/1")
    with pytest.raises(DriverHostError) as caught:
        activate(card)
    assert caught.value.code() == "OW_CARD_CODE_MISMATCH"
    assert "derive/1" in str(caught.value) and "parse/1" in str(caught.value)


def test_a_schema_version_mismatch_is_card_code_mismatch(tmp_path: Path) -> None:
    card = _card(tmp_path, "schemamix", module_schema=9)
    with pytest.raises(DriverHostError) as caught:
        activate(card)
    assert caught.value.code() == "OW_CARD_CODE_MISMATCH"
    assert "9" in str(caught.value)


def test_a_module_that_will_not_import_is_attributed_to_the_driver_not_to_us(
    tmp_path: Path,
) -> None:
    """An arbitrary `BaseException` out of a module body must not reach a host code path."""
    card = _card(tmp_path, "exploding")
    module = tmp_path / "owtestdrv_exploding" / "__init__.py"
    module.write_text(module.read_text(encoding="utf-8") + "\nraise SystemExit(3)\n", "utf-8")
    with pytest.raises(DriverHostError) as caught:
        activate(card)
    assert caught.value.code() == ACTIVATION_FAILED
    assert "SystemExit" in str(caught.value)


def test_a_missing_attribute_is_activation_failed(tmp_path: Path) -> None:
    card = _card(tmp_path, "noattr", attr="Absent")
    with pytest.raises(DriverHostError) as caught:
        activate(card)
    assert caught.value.code() == ACTIVATION_FAILED
    assert "Absent" in str(caught.value)


def test_an_entrypoint_naming_something_that_is_not_a_class_is_refused(tmp_path: Path) -> None:
    """`activate()` returns a class; a module-level int would fail much later and worse."""
    card = _card(tmp_path, "notaclass", attr="NotAClass")
    with pytest.raises(DriverHostError) as caught:
        activate(card)
    assert caught.value.code() == ACTIVATION_FAILED
    assert "not a class" in str(caught.value)


def test_entrypoint_parts_splits_module_from_attribute(tmp_path: Path) -> None:
    module, attribute = entrypoint_parts(_card(tmp_path, "split"))
    assert module == "owtestdrv_split"
    assert attribute == "Driver"


def test_check_card_code_is_the_one_home_and_driver_guard_delegates_to_it() -> None:
    """INV-21: a guard with its own copy would drift from the card exactly as code drifts.

    Read off the AST rather than by calling, because what is asserted is that there is ONE
    implementation -- a behavioural test would pass for two implementations that agree today.
    """
    source = Path("packages/omniweave-core/src/omniweave_core/host/inproc.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    bodies = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "check_code"
    ]
    assert len(bodies) == 1
    calls = [
        n.func.id
        for n in ast.walk(bodies[0])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "check_card_code" in calls, "DriverGuard.check_code must delegate, not re-implement"
    assert "getattr" not in calls, "a second copy of the PORT/SCHEMA_VERSION read"


def test_check_card_code_accepts_any_object_carrying_the_two_class_variables(
    tmp_path: Path,
) -> None:
    """It takes an object rather than a class: `HELLO_ACK`'s half of step 4 has no class at all."""

    class Shim:
        PORT = "parse/1"
        SCHEMA_VERSION = 1

    check_card_code(_card(tmp_path, "shim"), Shim)


def test_code_fingerprint_is_stable_and_moves_with_a_rename(tmp_path: Path) -> None:
    """04-driver-system.md:1550: the sha256 of the driver package's `*.py` bytes.

    The NAME is hashed alongside the bytes, so a package that renamed `a.py` to `b.py` gets a
    different fingerprint. Without that, a rename is invisible to the value `HELLO_ACK` carries.
    """
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    a.write_text("x = 1\n", encoding="utf-8")
    first = code_fingerprint([a])
    assert len(first) == 64 and int(first, 16) >= 0
    assert first == code_fingerprint([a]), "stable over two reads of the same bytes"
    a.rename(b)
    assert code_fingerprint([b]) != first, "a rename must move the fingerprint"


def test_code_fingerprint_does_not_collide_on_a_shifted_boundary(tmp_path: Path) -> None:
    """The classic length-extension shape: `("ab", "c")` and `("a", "bc")` must differ.

    Costs one `len()` to remove and is unfixable once a value has shipped, which is why it is
    tested rather than reasoned about.
    """
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    (one / "ab.py").write_text("c", encoding="utf-8")
    (two / "a.py").write_text("bc", encoding="utf-8")
    assert code_fingerprint([one / "ab.py"]) != code_fingerprint([two / "a.py"])


def test_code_fingerprint_is_order_independent(tmp_path: Path) -> None:
    """Sorted by path inside the function, so a caller's iteration order cannot move the value."""
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text("a = 1\n", encoding="utf-8")
    second.write_text("b = 2\n", encoding="utf-8")
    assert code_fingerprint([first, second]) == code_fingerprint([second, first])


def test_code_fingerprint_of_nothing_is_the_empty_digest() -> None:
    """An unlocatable distribution yields `()`, and `()` must produce a definite value."""
    assert code_fingerprint([]) == hashlib.sha256(b"").hexdigest()
