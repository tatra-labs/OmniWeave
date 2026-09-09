"""`Registry[T]` — DR3: a duplicate driver id never wins silently.

The one property this module exists for is negative, and the tests are shaped around the two ways
it has been got wrong in the mined collection rather than around the happy path:

* **first-wins and silent** (DataFlow's plugin registry, keyed on a bare `__name__`): the second
  claim is dropped with no diagnostic, and because registration order follows installation order,
  *which* claim is dropped is not stable across machines.
* **detected and then discarded** (docling's `process_plugin`, which swallows a duplicate as a
  `logger.warning`): the collision is seen and the run continues with an arbitrary winner.

So the assertions are: nothing binds twice without saying so; the refusal names BOTH distributions,
because an operator cannot write `[drivers.resolve] "<id>" = "<dist>"` knowing only the loser; and
the disambiguation is honoured in both directions but never invented.

Specified in 04-driver-system.md section 4.5 and section 12's DR3 row, and 02-architecture.md
section 2 row 11.
"""

from __future__ import annotations

import pytest
from omniweave_core.errors import DriverHostError, explain
from omniweave_core.registry import (
    DUPLICATE_DRIVER_FIX,
    DuplicateDriver,
    Registration,
    Registry,
)

ID = "parse.office.anydoc"
OFFICE = "omniweave-office"
IMPOSTOR = "somebody-elses-office"


def registry(**kwargs: object) -> Registry[str]:
    return Registry(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The collision
# ---------------------------------------------------------------------------


def test_a_duplicate_id_raises_and_names_both_distributions() -> None:
    """DR3's whole content. Naming only the loser is not actionable."""
    reg = registry()
    reg.register(ID, "first", distribution=OFFICE)
    with pytest.raises(DuplicateDriver) as caught:
        reg.register(ID, "second", distribution=IMPOSTOR)
    message = str(caught.value)
    assert OFFICE in message
    assert IMPOSTOR in message
    assert ID in message
    assert caught.value.incumbent == OFFICE
    assert caught.value.challenger == IMPOSTOR
    assert caught.value.key == ID


def test_the_incumbent_still_stands_after_a_refused_duplicate() -> None:
    """The refusal is not a rollback: nothing about the first registration changed.

    A registry that dropped both on a collision would turn one packaging bug into two missing
    drivers, and the operator's disambiguation would then have nothing to choose between.
    """
    reg = registry()
    reg.register(ID, "first", distribution=OFFICE)
    with pytest.raises(DuplicateDriver):
        reg.register(ID, "second", distribution=IMPOSTOR)
    assert reg.get(ID) == "first"
    assert len(reg) == 1


def test_the_second_claim_is_never_silently_dropped() -> None:
    """The DataFlow shape, stated as the thing that must not happen.

    Without the raise this call would return, `reg.get(ID)` would be `"first"`, and nothing in the
    run would record that a second distribution wanted the id.
    """
    reg = registry()
    reg.register(ID, "first", distribution=OFFICE)
    with pytest.raises(DuplicateDriver):
        reg.register(ID, "second", distribution=IMPOSTOR)


def test_the_same_distribution_claiming_one_id_twice_is_still_a_collision() -> None:
    """Two entry points for one id in one wheel is a packaging bug, not a no-op.

    Absorbing it would hide the day the two stop being equal — which is the same defect one
    release later, with no test that would have caught it.
    """
    reg = registry()
    reg.register(ID, "first", distribution=OFFICE)
    with pytest.raises(DuplicateDriver) as caught:
        reg.register(ID, "first", distribution=OFFICE)
    assert caught.value.incumbent == caught.value.challenger == OFFICE


def test_an_unnamed_distribution_is_reported_rather_than_printed_as_an_empty_string() -> None:
    """A `driver_path` card is a file, not a wheel; the message must still read."""
    reg = registry()
    reg.register(ID, "first")
    with pytest.raises(DuplicateDriver) as caught:
        reg.register(ID, "second", distribution=IMPOSTOR)
    assert "<unnamed>" in str(caught.value)
    assert IMPOSTOR in str(caught.value)


def test_distinct_ids_do_not_collide() -> None:
    reg = registry()
    reg.register("parse.pdf.pdfium", "a", distribution="omniweave-pdf")
    reg.register("parse.office.anydoc", "b", distribution=OFFICE)
    assert len(reg) == 2


# ---------------------------------------------------------------------------
# The error itself
# ---------------------------------------------------------------------------


def test_duplicate_driver_is_a_driver_host_error_with_its_register_row() -> None:
    """`OW-D-013` / `OW_DRIVER_DUPLICATE_ID`, resolvable through `codes.toml` both ways."""
    error = DuplicateDriver(ID, OFFICE, IMPOSTOR)
    assert isinstance(error, DriverHostError)
    assert error.code() == "OW_DRIVER_DUPLICATE_ID"
    assert error.numeric() == "OW-D-013"
    assert explain("OW-D-013").symbol == "OW_DRIVER_DUPLICATE_ID"
    assert explain("OW_DRIVER_DUPLICATE_ID").fix == error.fix


def test_the_fix_is_the_drivers_resolve_row_and_nothing_else() -> None:
    """Section 4.5: "only an explicit disambiguation proceeds"."""
    assert "drivers.resolve" in DUPLICATE_DRIVER_FIX
    assert DuplicateDriver(ID, OFFICE, IMPOSTOR).fix == DUPLICATE_DRIVER_FIX


def test_the_subject_is_named_so_the_registry_is_reusable_beyond_drivers() -> None:
    reg: Registry[str] = Registry(subject="target")
    reg.register("pptx", "a", distribution="omniweave-target-pptx")
    with pytest.raises(DuplicateDriver) as caught:
        reg.register("pptx", "b", distribution="somebody-else")
    assert "target id" in str(caught.value)


# ---------------------------------------------------------------------------
# [drivers.resolve] — the only thing that lets a collision proceed
# ---------------------------------------------------------------------------


def test_a_resolve_row_naming_the_challenger_lets_the_challenger_win() -> None:
    reg: Registry[str] = Registry(resolve={ID: IMPOSTOR})
    reg.register(ID, "first", distribution=OFFICE)
    reg.register(ID, "second", distribution=IMPOSTOR)
    assert reg.get(ID) == "second"
    assert reg.distributions()[ID] == IMPOSTOR


def test_a_resolve_row_naming_the_incumbent_lets_the_incumbent_win() -> None:
    """Order-independence: the disambiguation must not depend on enumeration order.

    The same two distributions in the other order must produce the same winner, or the config row
    would only work when the loser happened to be enumerated second.
    """
    reg: Registry[str] = Registry(resolve={ID: OFFICE})
    reg.register(ID, "first", distribution=OFFICE)
    reg.register(ID, "second", distribution=IMPOSTOR)
    assert reg.get(ID) == "first"

    reversed_order: Registry[str] = Registry(resolve={ID: OFFICE})
    reversed_order.register(ID, "second", distribution=IMPOSTOR)
    reversed_order.register(ID, "first", distribution=OFFICE)
    assert reversed_order.get(ID) == "first"


def test_a_resolve_row_naming_a_third_distribution_is_still_a_collision() -> None:
    """The operator disambiguated against something that is not installed.

    Picking one of the two anyway would be the first-wins defect wearing a configuration file as a
    disguise, and the operator would never learn their row did nothing.
    """
    reg: Registry[str] = Registry(resolve={ID: "omniweave-not-installed"})
    reg.register(ID, "first", distribution=OFFICE)
    with pytest.raises(DuplicateDriver):
        reg.register(ID, "second", distribution=IMPOSTOR)


def test_a_resolve_row_for_a_different_id_does_not_disambiguate_this_one() -> None:
    reg: Registry[str] = Registry(resolve={"parse.pdf.pdfium": OFFICE})
    reg.register(ID, "first", distribution=OFFICE)
    with pytest.raises(DuplicateDriver):
        reg.register(ID, "second", distribution=IMPOSTOR)


def test_a_resolve_row_does_not_pre_bind_an_id_nobody_registered() -> None:
    """The row disambiguates a collision; it does not install anything."""
    reg: Registry[str] = Registry(resolve={ID: OFFICE})
    assert reg.get(ID) is None
    assert ID not in reg


def test_the_resolve_mapping_is_copied_so_a_later_config_edit_cannot_move_a_run() -> None:
    live = {ID: OFFICE}
    reg: Registry[str] = Registry(resolve=live)
    live[ID] = IMPOSTOR
    reg.register(ID, "first", distribution=OFFICE)
    reg.register(ID, "second", distribution=IMPOSTOR)
    assert reg.get(ID) == "first"


# ---------------------------------------------------------------------------
# replace=True — the stated intent, and the only other way past the check
# ---------------------------------------------------------------------------


def test_replace_true_rebinds_and_is_the_only_other_way_past_the_check() -> None:
    """02-architecture.md section 2 row 11: "unless `replace=True`"."""
    reg = registry()
    reg.register(ID, "first", distribution=OFFICE)
    reg.register(ID, "second", distribution=IMPOSTOR, replace=True)
    assert reg.get(ID) == "second"
    assert reg.distributions()[ID] == IMPOSTOR


def test_replace_is_keyword_only_so_it_cannot_be_passed_by_accident() -> None:
    """A positional fourth argument would let a caller disable DR3 without writing its name."""
    reg = registry()
    reg.register(ID, "first", distribution=OFFICE)
    with pytest.raises(TypeError):
        reg.register(ID, "second", OFFICE, True)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_items_is_sorted_and_not_insertion_ordered() -> None:
    """Insertion order is `entry_points()` order, which is a property of the machine.

    DR6 states the same rule for `resolve()`'s candidates and for the same reason: a caller that
    accidentally depends on an emergent order gets a different answer elsewhere.
    """
    reg = registry()
    for driver_id in ("parse.web.html", "parse.pdf.pdfium", "acquire.fs.local"):
        reg.register(driver_id, driver_id, distribution="d")
    assert [key for key, _ in reg.items()] == [
        "acquire.fs.local",
        "parse.pdf.pdfium",
        "parse.web.html",
    ]
    assert list(reg) == [key for key, _ in reg.items()]


def test_get_returns_none_rather_than_raising_for_an_unknown_id() -> None:
    """Reading a registry never raises: an absent driver is a resolution outcome, not an error."""
    assert registry().get("parse.pdf.nothing") is None


def test_registration_carries_the_distribution_for_the_qualified_form() -> None:
    """`<id>@<dist>` is the fully qualified `DriverId`: the distribution survives registration."""
    reg = registry()
    reg.register(ID, "value", distribution=OFFICE)
    found = reg.registration(ID)
    assert found == Registration(key=ID, value="value", distribution=OFFICE)
    assert reg.registration("nothing") is None


def test_the_registry_is_not_a_mapping_and_has_no_setitem() -> None:
    """`d[k] = v` overwriting silently is exactly what DR3 forbids, so the spelling is absent."""
    reg = registry()
    assert not hasattr(reg, "__setitem__")
    with pytest.raises(TypeError):
        reg["x"] = "y"  # type: ignore[index]


def test_distributions_is_read_only() -> None:
    reg = registry()
    reg.register(ID, "value", distribution=OFFICE)
    with pytest.raises(TypeError):
        reg.distributions()[ID] = IMPOSTOR  # type: ignore[index]


def test_two_registries_are_independent_so_a_catalog_is_per_run() -> None:
    """A process-global registry makes "which drivers were visible" a fact about an earlier run."""
    one = registry()
    two = registry()
    one.register(ID, "a", distribution=OFFICE)
    assert two.get(ID) is None
    two.register(ID, "b", distribution=IMPOSTOR)
    assert one.get(ID) == "a"


def test_repr_names_the_subject_and_the_count() -> None:
    reg = registry()
    reg.register(ID, "a", distribution=OFFICE)
    assert repr(reg) == "Registry('driver', 1 registered)"


# ---------------------------------------------------------------------------
# The plan says so
# ---------------------------------------------------------------------------


def test_the_plan_binds_duplicate_driver_to_this_module(plan) -> None:
    plan.require()
    hits = plan.grep(r"`omniweave_core/registry\.py` \(`DuplicateDriver`\)")
    assert hits, "04-driver-system.md section 12's DR3 row should name registry.py"


def test_the_plan_prints_the_drivers_resolve_disambiguation(plan) -> None:
    plan.require()
    hits = plan.grep(r"\[drivers\.resolve\] \"parse\.office\.anydoc\" = \"omniweave-office\"")
    assert hits, "04-driver-system.md section 4.5 should print the disambiguation row"


def test_the_dataflow_receipt_is_still_in_the_plan(plan) -> None:
    """A test that the justification the module docstring cites has not been struck."""
    plan.require()
    hits = plan.grep(r"first-wins and silent")
    assert hits, "04-driver-system.md section 4.5's DataFlow receipt should still stand"
