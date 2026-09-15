"""`omniweave.route.evidence` against 05-ingest-and-routing.md sections 4.6, 5.1, 5.2 and 5.4.

Three groups of tests, and they exist for three different reasons.

**The ABSENCES are tested by name.** 05:1859-1863 lists what `Evidence` must not have -- no
`__getitem__`, no `keys()`, no `items()`, no `__contains__` -- and an absence is the one kind of
design a later contributor removes without noticing, because adding a dunder makes code that did
not work start working. Each is a line here.

**The day-one registry is tested against the plan's own counts.** 05:2187 says *"Fifty-four
keys"*; `layout.class_hist` has no provider at release 1, so the built registry holds fifty-three,
and the three shipped `signals.toml` files are checked row by row for the columns 05 section 5.1's
table fixes.

**The collisions are tested because they fire at STARTUP.** A per-format collision that fired only
on the corpus containing that format would be a routing bug that appears on one machine.
"""

from __future__ import annotations

from typing import Any

import pytest
from omniweave.route import evidence as ev
from omniweave.route.rung import Rung
from omniweave.route.spend import Spend
from omniweave_core.canonical import sha256_canonical
from omniweave_core.errors import PolicyRefusal, RouteError
from omniweave_ports.types import CostClass

ROUTING = "05-ingest-and-routing.md"
SHA = "a" * 64

# The three shipped files, as (provider, path-from-the-repo-root) pairs. Read from disk rather than
# imported: `omniweave` may not import `omniweave_pdf` (tools/layers.toml), and a test that did
# would pass while the module under test could not.
SHIPPED: tuple[tuple[str, str], ...] = (
    ("builtin", "packages/omniweave/src/omniweave/route/signals.toml"),
    ("pdfium", "packages/omniweave-pdf/src/omniweave_pdf/signals.toml"),
    ("officexml", "packages/omniweave-office/src/omniweave_office/signals.toml"),
)


def _repo_root() -> Any:
    """The workspace root, found by walking up to the directory holding `codes.toml`.

    `Path(__file__).parents[4]` would work today and would break the first time a package moves;
    the marker file is `codes.toml` because it is at the root by 11-repo-layout.md:45 and nowhere
    else. `os.getcwd()` is banned in library code and is avoided here for the same reason -- a test
    that depends on the working directory passes under `pytest` and fails under an IDE runner.
    """
    here = __import__("pathlib").Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "codes.toml").is_file():
            return parent
    raise AssertionError("no codes.toml above this test file")


def _shipped_specs() -> tuple[ev.SignalSpec, ...]:
    root = _repo_root()
    out: list[ev.SignalSpec] = []
    for provider, relative in SHIPPED:
        raw = (root / relative).read_bytes()
        out.extend(ev.load_signals(raw, provider=provider, origin=relative))
    return tuple(out)


def _spec(**over: Any) -> ev.SignalSpec:
    """A minimal valid spec. Every test that wants an invalid one names the one field it breaks."""
    base: dict[str, Any] = {
        "key": "decode.char_count",
        "scope": "part",
        "kind": "count",
        "dtype": "int",
        "domain": (0.0, 2147483647.0),
        "cost_class": CostClass.FREE,
        "est": Spend(cpu_ms=1),
        "provider": "builtin",
        "version": "1.0.0",
        "origin": "a test",
    }
    base.update(over)
    return ev.SignalSpec(**base)


# --------------------------------------------------------------------------------------------
# 1. `Evidence` -- the accessor, the three values, and the four absences.
# --------------------------------------------------------------------------------------------


def test_read_returns_the_value_and_none_for_both_kinds_of_unknown() -> None:
    """05:1869-1873. Uncomputable and not-yet-computed both read `None`; only `computed()` tells
    them apart, which is the distinction `on_unknown` and `deferrals_pending` are built on."""
    e = ev.Evidence(content_sha256=SHA, unit_part="p1")
    e.put("unit.format", "pdf", provider_version="1.0.0")
    e.put("decode.cid_ratio", None, provider_version="1.0.0", unavailable_reason="no provider")

    assert e.read("unit.format") == "pdf"
    assert e.read("decode.cid_ratio") is None
    assert e.read("ink.tiles") is None
    assert e.computed("decode.cid_ratio") is True
    assert e.computed("ink.tiles") is False


def test_evidence_has_no_getitem_no_keys_no_items_and_no_contains() -> None:
    """05:1859-1863, each absence by name.

    A `__contains__` would let a rule branch on whether a key was computed WITHOUT reading it,
    which is the declaration-instead-of-observation that `read_set_digest` exists to rule out.
    `keys()` would let `evaluate()` enumerate the record and behave differently on a machine with
    one more provider installed -- a purity break no semgrep rule could see.
    """
    e = ev.Evidence(content_sha256=SHA)
    for absent in ("__getitem__", "keys", "items", "__contains__", "get", "values"):
        assert not hasattr(e, absent), f"Evidence grew {absent}, which 05:1859 forbids"
    with pytest.raises(TypeError):
        _ = e["unit.format"]  # type: ignore[index]


def test_slots_are_the_plans_three_and_nothing_can_be_stashed_on_an_instance() -> None:
    """05:1865's `__slots__`, which is also what makes the absences hold: a subclass cannot quietly
    add a `__dict__` and park a `RunContext` on it."""
    assert ev.Evidence.__slots__ == ("_read", "_scope", "_v")
    e = ev.Evidence(content_sha256=SHA)
    with pytest.raises(AttributeError):
        e.ledger = object()  # type: ignore[attr-defined]


def test_reading_is_what_puts_a_key_in_the_read_set() -> None:
    """RT3. A value that was PUT and never READ is not in the set; that is the whole point."""
    e = ev.Evidence(content_sha256=SHA)
    e.put("unit.format", "pdf", provider_version="1.0.0")
    e.put("unit.bytes", 1024, provider_version="1.0.0")
    assert e.read_set() == ()

    e.read("unit.format")
    assert e.read_set() == (("unit.format", "1.0.0", "pdf"),)


def test_a_key_read_twice_appears_once_at_its_first_position() -> None:
    """Several rules legitimately read `unit.format`. A log that recorded each would make the
    digest a function of the policy's LAYOUT rather than of the evidence."""
    e = ev.Evidence(content_sha256=SHA)
    e.put("unit.format", "pdf", provider_version="1.0.0")
    e.put("unit.bytes", 7, provider_version="1.0.0")
    e.read("unit.format")
    e.read("unit.bytes")
    e.read("unit.format")
    assert [key for key, _, _ in e.read_set()] == ["unit.format", "unit.bytes"]


def test_a_key_read_but_never_computed_is_in_the_read_set_with_an_empty_version() -> None:
    """The decision DEPENDED on that key being UNKNOWN. A read set that omitted it would give the
    same identity to a decision taken when the key was available -- which is exactly the
    `layout.class_hist` case, where every affected decision records `cause = "layout_unavailable"`.
    """
    e = ev.Evidence(content_sha256=SHA)
    assert e.read("layout.class_hist") is None
    assert e.read_set() == (("layout.class_hist", "", None),)


def test_computed_and_unavailable_reason_are_probes_and_never_enter_the_read_set() -> None:
    """05:1877: *"a planner probe is not a read and may not enter the read set."*"""
    e = ev.Evidence(content_sha256=SHA)
    e.put("ink.tiles", None, provider_version="1.0.0", unavailable_reason="pdfium not installed")
    assert e.computed("ink.tiles") is True
    assert e.unavailable_reason("ink.tiles") == "pdfium not installed"
    assert e.read_set() == ()


def test_read_set_digest_is_the_canonical_digest_of_the_triples() -> None:
    """One of the eight identity columns (05:1885), and it is checked against `sha256_canonical`
    directly so that a change to the rendering is caught rather than absorbed."""
    e = ev.Evidence(content_sha256=SHA)
    e.put("unit.format", "pdf", provider_version="1.0.0")
    e.read("unit.format")
    assert e.read_set_digest() == sha256_canonical([["unit.format", "1.0.0", "pdf"]])


def test_the_digest_distinguishes_true_from_one() -> None:
    """A bool signal and an int signal that happen to agree must not collide: `verify.parse_ok`
    is `True` and `unit.part_count` is `1`, and canonical JSON keeps them apart."""

    def digest_of(value: bool | int) -> str:
        e = ev.Evidence(content_sha256=SHA)
        e.put("k.v", value, provider_version="1.0.0")
        e.read("k.v")
        return e.read_set_digest()

    assert digest_of(True) != digest_of(1)


def test_the_digest_depends_on_the_order_keys_were_read_in() -> None:
    """05:1880 says "IN READ ORDER". Two decisions that read the same keys in different orders
    took different paths through the rule list, and the identity says so."""
    first, second = ev.Evidence(content_sha256=SHA), ev.Evidence(content_sha256=SHA)
    for e in (first, second):
        e.put("unit.format", "pdf", provider_version="1.0.0")
        e.put("unit.bytes", 7, provider_version="1.0.0")
    first.read("unit.format")
    first.read("unit.bytes")
    second.read("unit.bytes")
    second.read("unit.format")
    assert first.read_set_digest() != second.read_set_digest()


def test_clear_read_log_keeps_the_values_and_drops_only_the_log() -> None:
    """The sixth method. Re-computing a `CostClass` group because the digest was reset would be
    the opposite of what the demand plan is for."""
    e = ev.Evidence(content_sha256=SHA)
    e.put("unit.format", "pdf", provider_version="1.0.0")
    e.read("unit.format")
    e.clear_read_log()
    assert e.read_set() == ()
    assert e.computed("unit.format") is True
    assert e.read("unit.format") == "pdf"


def test_the_winning_path_is_the_window_after_the_last_clear() -> None:
    """D197's shape, as a test rather than a claim.

    The demand plan computes FREE, evaluates, computes LOCAL_COMPUTE, evaluates again. Without a
    demarcation the second evaluation's read set carries the first round's reads, so two machines
    whose plans differ by one deferral compute two identities for one decision.
    """
    e = ev.Evidence(content_sha256=SHA)
    e.put("decode.char_count", 0, provider_version="1.0.0")  # the FREE group
    e.read("decode.char_count")
    free_round = e.read_set_digest()

    e.clear_read_log()  # the loop, immediately before the evaluate() whose row is written
    e.put("ink.tiles", 12, provider_version="1.0.0")  # the LOCAL_COMPUTE group
    e.read("ink.tiles")
    assert e.read_set() == (("ink.tiles", "1.0.0", 12),)
    assert e.read_set_digest() != free_round


def test_put_refuses_to_change_a_value_the_window_has_already_read() -> None:
    """The refusal exists because the alternative is a written `route_decision` row whose
    `read_set_digest` describes a state that never existed."""
    e = ev.Evidence(content_sha256=SHA)
    e.put("budget.exhausted", False, provider_version="1.0.0")
    e.read("budget.exhausted")
    with pytest.raises(RouteError, match="describe a state that never was"):
        e.put("budget.exhausted", True, provider_version="1.0.0")


def test_admit_may_write_budget_exhausted_between_two_rungs() -> None:
    """The refusal above is scoped to the WINDOW, and this is why: `admit()` runs after the
    decision row is written and the `DEGRADE` rules read the key at a later rung (RT9, 05:1893)."""
    e = ev.Evidence(content_sha256=SHA)
    e.put("budget.exhausted", False, provider_version="1.0.0")
    e.read("budget.exhausted")
    e.clear_read_log()
    e.put("budget.exhausted", True, provider_version="1.0.0")
    assert e.read("budget.exhausted") is True


def test_reputting_an_identical_value_inside_the_window_is_allowed() -> None:
    """Nothing about the digest changes, so there is nothing to refuse."""
    e = ev.Evidence(content_sha256=SHA)
    e.put("unit.format", "pdf", provider_version="1.0.0")
    e.read("unit.format")
    e.put("unit.format", "pdf", provider_version="1.0.0")
    assert e.read("unit.format") == "pdf"


def test_an_unknown_must_carry_a_reason_and_a_value_must_not() -> None:
    """05:2352 makes the reason a cacheable fact -- otherwise every run re-attempts a signal whose
    provider is not installed, which is the exact cost `route_signal` exists to avoid."""
    e = ev.Evidence(content_sha256=SHA)
    with pytest.raises(RouteError, match="unavailable_reason"):
        e.put("ink.tiles", None, provider_version="1.0.0")
    with pytest.raises(RouteError, match="one or the other"):
        e.put("ink.tiles", 4, provider_version="1.0.0", unavailable_reason="but also fine?")


def test_scope_is_the_content_hash_and_the_part_with_the_empty_string_folding_null() -> None:
    """05:1915: keyed on CONTENT, *"the same PDF in three folders is one decision and one parse"*,
    and `''` for a unit-grain record *"because NULLs are distinct in a UNIQUE index"*."""
    assert ev.Evidence(content_sha256=SHA).scope == (SHA, "")
    assert ev.Evidence(content_sha256=SHA, unit_part="p3").scope == (SHA, "p3")


# --------------------------------------------------------------------------------------------
# 2. `SignalSpec` -- registration refuses a wrong registration, which is a wrong route.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["nogroup", "two.dots.here", "Decode.charCount", "decode.", ".x"])
def test_a_malformed_key_is_refused(bad: str) -> None:
    """05:2093's grammar. A key with two dots would make `[signal.a.b.c]` parse as a NESTED table
    and register nothing, silently -- which is the failure this check exists to make loud."""
    with pytest.raises(RouteError, match="group"):
        _spec(key=bad)


def test_rt5_refuses_a_classifier_whose_domain_is_not_zero_to_one_closed() -> None:
    """05:2101. *"A softmax legitimately returns 0.0 and 1.0."*"""
    ok = _spec(key="garble.score", kind="classifier", dtype="float", domain=(0.0, 1.0))
    assert ok.kind == "classifier"
    with pytest.raises(RouteError, match="RT5"):
        _spec(key="garble.score", kind="classifier", dtype="float", domain=(0.0, 0.99))
    with pytest.raises(RouteError, match="RT5"):
        _spec(key="garble.score", kind="classifier", dtype="float", domain=None)


def test_a_numeric_interval_on_a_string_signal_is_refused() -> None:
    with pytest.raises(RouteError, match="numeric interval"):
        _spec(key="unit.format", dtype="str", domain=(0.0, 1.0))


def test_a_string_set_on_a_numeric_signal_is_refused() -> None:
    with pytest.raises(RouteError, match="string set"):
        _spec(dtype="int", domain=frozenset({"a", "b"}))


def test_an_empty_string_domain_is_refused_because_no_literal_can_satisfy_it() -> None:
    with pytest.raises(RouteError, match="EMPTY"):
        _spec(key="unit.format", dtype="str", domain=frozenset())


def test_an_inverted_interval_is_refused() -> None:
    with pytest.raises(RouteError, match=r"\[1.0, 0.0\]"):
        _spec(domain=(1.0, 0.0))


@pytest.mark.parametrize(
    ("field", "value"),
    [("scope", "page"), ("kind", "guess"), ("dtype", "bytes")],
)
def test_the_three_closed_vocabularies_are_closed(field: str, value: str) -> None:
    with pytest.raises(RouteError, match=field):
        _spec(**{field: value})


def test_a_row_with_no_version_is_refused_because_the_version_enters_the_read_set() -> None:
    """05:2110. A decision must name exactly which code produced each value."""
    with pytest.raises(RouteError, match="read set"):
        _spec(version="")


# --------------------------------------------------------------------------------------------
# 3. The loader, and the per-format resolution it feeds.
# --------------------------------------------------------------------------------------------


def test_load_signals_reads_the_shape_05_2204_prints() -> None:
    """The section 5.2 example, byte for byte, with `scope` added -- the example omits it and the
    type requires it, so this is the shape a provider author actually writes."""
    raw = b"""
[signal."math.part_frac"]
serves  = ["docx", "pptx", "odt", "odp", "epub"]
version = "1.0.0"
scope   = "part"
kind    = "measure"
dtype   = "float"
domain  = [0.0, 1.0]
cost_class = "free"
requires   = ["DECODE"]
nullable   = true
est = { cpu_ms = 1 }
"""
    (spec,) = ev.load_signals(raw, provider="officexml", origin="a test")
    assert spec.key == "math.part_frac"
    assert spec.serves == frozenset({"docx", "pptx", "odt", "odp", "epub"})
    assert spec.requires == (Rung.DECODE,)
    assert spec.cost_class is CostClass.FREE
    assert spec.est == Spend(cpu_ms=1)
    assert spec.nullable is True
    assert spec.provider == "officexml"


def test_a_file_with_no_signal_table_registers_nothing_and_does_not_raise() -> None:
    """`omniweave-vision` *"registers nothing at release 1"* (05:2048) because
    `layout.class_hist` has no licence-clean weights. An empty file is a legal declaration."""
    assert ev.load_signals(b"# nothing here\n", provider="vision", origin="a test") == ()


def test_requires_is_sorted_by_ordinal_and_deduplicated() -> None:
    """Order in the file is the author's; order in the type is the ladder's, because `requires` is
    COMPARED -- it derives a rule's phase and check 7 reads it."""
    raw = b"""
[signal."agree.decode_vs_page"]
scope = "part"
kind = "measure"
dtype = "float"
domain = [0.0, 1.0]
cost_class = "free"
requires = ["PAGE", "DECODE", "PAGE"]
version = "1.0.0"
"""
    (spec,) = ev.load_signals(raw, provider="builtin", origin="a test")
    assert spec.requires == (Rung.DECODE, Rung.PAGE)


def test_an_unknown_rung_in_requires_is_refused_by_name() -> None:
    raw = b"""
[signal."a.b"]
scope = "part"
kind = "fact"
dtype = "bool"
cost_class = "free"
requires = ["OCR"]
version = "1.0.0"
"""
    with pytest.raises(RouteError, match="OCR"):
        ev.load_signals(raw, provider="builtin", origin="a test")


def test_est_refuses_a_dimension_spend_does_not_have() -> None:
    """A budget declared in a unit nothing prices is a budget that declares nothing."""
    raw = b"""
[signal."a.b"]
scope = "part"
kind = "fact"
dtype = "bool"
cost_class = "free"
version = "1.0.0"
est = { cpu_sec = 1 }
"""
    with pytest.raises(RouteError, match="cpu_sec"):
        ev.load_signals(raw, provider="builtin", origin="a test")


def test_a_row_may_not_register_on_another_providers_behalf() -> None:
    """`read_set_digest` would then name a version nothing on the machine can be checked against."""
    raw = b"""
[signal."a.b"]
provider = "pdfium"
scope = "part"
kind = "fact"
dtype = "bool"
cost_class = "free"
version = "1.0.0"
"""
    with pytest.raises(RouteError, match="registers only its own rows"):
        ev.load_signals(raw, provider="builtin", origin="a test")


def test_a_row_may_name_a_reserved_provider_because_budget_exhausted_does() -> None:
    """05 section 5.1's table gives `budget.exhausted` the provider `admit()` -- a function in
    this process, not a package. The key is registered like every other key; only its producer is
    not locatable on disk."""
    raw = b"""
[signal."budget.exhausted"]
provider = "admit"
scope = "part"
kind = "fact"
dtype = "bool"
cost_class = "free"
version = "1.0.0"
"""
    (spec,) = ev.load_signals(raw, provider="builtin", origin="a test")
    assert spec.provider == "admit"
    assert spec.provider in ev.RESERVED_PROVIDERS


def test_unreadable_toml_is_refused_rather_than_skipped() -> None:
    """The opposite of `omniweave_core.discovery`'s rule, and for the opposite reason: a missing
    card removes one driver from a catalog that still routes; a missing key is named by a compiled
    policy, so skipping it reports a lint error on a rule the operator wrote correctly."""
    with pytest.raises(RouteError, match="readable TOML"):
        ev.load_signals(b"[signal.\n", provider="builtin", origin="a test")


def test_signals_relative_path_is_the_card_expression_with_one_filename_changed() -> None:
    assert ev.signals_relative_path("omniweave_pdf") == "omniweave_pdf/signals.toml"
    assert ev.signals_relative_path("a.b.c") == "a/b/c/signals.toml"


# --------------------------------------------------------------------------------------------
# 4. `build_registry` -- OW-P-022, four ways.
# --------------------------------------------------------------------------------------------


def test_two_providers_naming_one_key_and_one_format_is_refused() -> None:
    """05:2219's own case, verbatim: *"not a precedence puzzle"*."""
    a = _spec(provider="pdfium", serves=frozenset({"pdf"}))
    b = _spec(provider="officexml", serves=frozenset({"pdf", "docx"}))
    with pytest.raises(PolicyRefusal, match="OW-P-022") as caught:
        ev.build_registry([a, b])
    assert caught.value.code() == "OW_SIGNAL_PROVIDER_CONFLICT"
    assert "'pdf'" in str(caught.value)


def test_two_fallback_rows_for_one_key_is_refused() -> None:
    """An empty `serves` means every format, so two of them name each other's."""
    with pytest.raises(PolicyRefusal, match="every format"):
        ev.build_registry([_spec(provider="builtin"), _spec(provider="vision")])


def test_one_provider_registering_a_key_twice_is_refused() -> None:
    """`serves` cannot disambiguate it, because both rows are the same provider's."""
    a = _spec(provider="pdfium", serves=frozenset({"pdf"}))
    b = _spec(provider="pdfium", serves=frozenset({"tiff"}))
    with pytest.raises(PolicyRefusal, match="registers it twice"):
        ev.build_registry([a, b])


def test_two_rows_disagreeing_about_a_per_key_column_are_refused() -> None:
    """D199. Without this, a PDF and an XLSX could disagree about whether `unit.part_count` is
    nullable, and `ow route lint` check 4 would pass or fail depending on which file it read."""
    a = _spec(provider="pdfium", serves=frozenset({"pdf"}), nullable=False)
    b = _spec(provider="officexml", serves=frozenset({"docx"}), nullable=True)
    with pytest.raises(PolicyRefusal, match="disagree about nullable"):
        ev.build_registry([a, b])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope", "unit"),
        ("kind", "measure"),
        ("dtype", "float"),
        ("domain", (0.0, 1.0)),
        ("cost_class", CostClass.LOCAL_COMPUTE),
        ("nullable", False),
        ("requires", (Rung.DECODE,)),
    ],
)
def test_every_per_key_column_is_checked_for_agreement(field: str, value: Any) -> None:
    """All seven of `_KEY_FIELDS`, so that adding a column is the only way to add a check.

    The two rows differ in EXACTLY one field -- `other` is built from `over` -- because a fixture
    that changed two would pass on whichever the loop happened to reach first, which is the same
    order-dependence the check exists to remove.
    """
    over: dict[str, Any] = {"provider": "pdfium", "serves": frozenset({"pdf"})}
    if field == "dtype":
        over["domain"] = None  # unbounded, and therefore legal under both int and float
    other: dict[str, Any] = {
        **over,
        "provider": "officexml",
        "serves": frozenset({"docx"}),
        field: value,
    }
    with pytest.raises(PolicyRefusal, match=f"disagree about {field}"):
        ev.build_registry([_spec(**over), _spec(**other)])


def test_est_serves_and_version_may_differ_across_providers() -> None:
    """The per-PROVIDER half. `unit.part_count` costs 6 ms through pdfium and may cost otherwise
    through another provider; that is what `est` being author-declared MEANS."""
    a = _spec(provider="pdfium", serves=frozenset({"pdf"}), est=Spend(cpu_ms=6), version="1.0.0")
    b = _spec(
        provider="officexml", serves=frozenset({"docx"}), est=Spend(cpu_ms=2), version="2.1.0"
    )
    registry = ev.build_registry([a, b])
    assert registry.resolve("decode.char_count", "pdf") is a
    assert registry.resolve("decode.char_count", "docx") is b


def test_resolution_prefers_the_row_that_names_the_format_over_the_fallback() -> None:
    """D198's shipped reading, and it is what makes a `nullable = false` key registerable over a
    domain that is computed and OPEN."""
    named = _spec(provider="pdfium", serves=frozenset({"pdf"}))
    fallback = _spec(provider="builtin")
    registry = ev.build_registry([named, fallback])
    assert registry.resolve("decode.char_count", "pdf") is named
    assert registry.resolve("decode.char_count", "txt") is fallback
    assert registry.resolve("decode.char_count", "a-token-no-card-has-contributed") is fallback


def test_a_format_no_provider_claims_yields_unknown_and_not_an_error() -> None:
    """05:2222. A corpus containing one `mp4` must not fail to route on the grounds that nothing
    computes `decode.cid_ratio` for it."""
    registry = ev.build_registry([_spec(provider="pdfium", serves=frozenset({"pdf"}))])
    assert registry.resolve("decode.char_count", "mp4") is None
    assert registry.resolve("no.such_key", "pdf") is None


# --------------------------------------------------------------------------------------------
# 5. The day-one registry, against 05 section 5.1's table.
# --------------------------------------------------------------------------------------------


def test_the_three_shipped_files_build_one_registry_of_fifty_three_keys() -> None:
    """05:2187 says *"Fifty-four keys"*; `layout.class_hist` has no provider at release 1."""
    registry = ev.build_registry(_shipped_specs())
    assert len(registry.keys()) == 53
    assert registry.providers() == ("admit", "builtin", "officexml", "pdfium")


def test_layout_class_hist_is_registered_by_nobody_and_the_constant_says_so() -> None:
    """05:2323: *"absent at release 1 and every decision that would have read it records
    `cause = "layout_unavailable"`"*. A `SignalSpec` requires a provider and a version, and
    inventing either would claim a value can be computed."""
    registry = ev.build_registry(_shipped_specs())
    registered = set(registry.keys())
    assert set(ev.UNREGISTERED_AT_RELEASE_1) == {"layout.class_hist"}
    for key in ev.UNREGISTERED_AT_RELEASE_1:
        assert key not in registered
        assert registry.resolve(key, "pdf") is None


def test_the_fifty_four_keys_of_the_table_are_the_fifty_three_plus_the_unregistered_one() -> None:
    """The count the plan prints, reconstructed from the two sets this module actually has."""
    registry = ev.build_registry(_shipped_specs())
    assert len(set(registry.keys()) | ev.UNREGISTERED_AT_RELEASE_1) == 54


@pytest.mark.parametrize(
    ("key", "fmt", "provider"),
    [
        # 05 section 5.1's provider column, one case per shape it takes.
        ("unit.format", "pdf", "builtin"),  # builtin alone
        ("decode.cid_ratio", "pdf", "pdfium"),  # pdfium alone
        ("unit.part_count", "pdf", "pdfium"),  # three providers, PDF
        ("unit.part_count", "xlsx", "officexml"),  # three providers, office
        ("unit.part_count", "txt", "builtin"),  # three providers, the fallback
        ("math.part_frac", "docx", "officexml"),  # the OMML half
        ("math.part_frac", "pdf", "builtin"),  # the marker half, via the fallback
        ("math.part_frac", "csv", "builtin"),  # office, but no math element to count
        ("budget.exhausted", "pdf", "admit"),  # the one function-provided key
    ],
)
def test_per_format_resolution_matches_the_tables_provider_column(
    key: str, fmt: str, provider: str
) -> None:
    registry = ev.build_registry(_shipped_specs())
    resolved = registry.resolve(key, fmt)
    assert resolved is not None, f"{key} has no provider for {fmt}"
    assert resolved.provider == provider


def test_block_type_has_no_pdf_row_which_is_why_repair_is_unavailable_on_pdf() -> None:
    """05:852. Block-level repair needs `block.type`; on PDF that needs a layout detector and every
    candidate is licence-blocked, so every PDF block is `not_eligible` for REPAIR. The absence of
    one row in one file IS that consequence, and `ow route lint --explain` prints it (05:2224)."""
    registry = ev.build_registry(_shipped_specs())
    assert registry.resolve("block.type", "pdf") is None
    assert registry.resolve("block.type", "docx") is not None


def test_ink_is_the_only_local_compute_in_the_day_one_registry() -> None:
    """INV-13 and RT4 turn on it: a clean born-digital page computes ZERO `LOCAL_COMPUTE` signals,
    and the three exact counters fail on a deviation of one. A fourth `local_compute` row landing
    unnoticed would move that number without moving any test but this one."""
    local = {s.key for s in _shipped_specs() if s.cost_class is CostClass.LOCAL_COMPUTE}
    assert local == {"ink.tiles", "ink.coverage", "block.has_ink"}


def test_no_day_one_signal_is_billed_api() -> None:
    """05 section 5.1's `cost` column has no `BILLED_API` row, and the demand plan's third group is
    therefore empty at release 1. A signal that cost money to compute would put a price inside
    `evaluate()`'s input, which is the thing INV-14 is about."""
    assert not [s for s in _shipped_specs() if s.cost_class is CostClass.BILLED_API]


def test_block_flagged_frac_is_part_scoped_which_discharges_open_question_3() -> None:
    """05:2055, in the plan's own words: *"registered here, part-scoped, `measure`, FREE, nullable,
    `req = REPAIR`, so the shipped policy passes `ow route lint` check 1 against this table."*"""
    registry = ev.build_registry(_shipped_specs())
    spec = registry.resolve("block.flagged_frac", "pdf")
    assert spec is not None
    assert (spec.scope, spec.kind, spec.cost_class, spec.nullable, spec.requires) == (
        "part",
        "measure",
        CostClass.FREE,
        True,
        (Rung.REPAIR,),
    )


@pytest.mark.parametrize(
    "key",
    [
        "unit.format",
        "unit.format_basis",
        "unit.bytes",
        "unit.part_count",
        "unit.encrypted",
        "unit.corrupt",
        "unit.trust_class",
        "unit.schema_requested",
        "doc.escalated_part_frac",
        "doc.rung_run_length",
        "driver.unavailable",
        "trigger.kind",
        "request.schema_present",
    ],
)
def test_the_thirteen_non_nullable_keys_of_the_table(key: str) -> None:
    """The `null` column, inverted. 05:2119: a key that can never be UNKNOWN at routing time needs
    no `on_unknown`, and lint check 4 (`OW-P-004`) reads exactly this field."""
    registry = ev.build_registry(_shipped_specs())
    for spec in registry.specs_for(key):
        assert spec.nullable is False, f"{key} through {spec.provider} is nullable"


def test_every_classifier_in_the_shipped_registry_passes_rt5() -> None:
    """Two of them -- `corpus.spam_score` and `garble.score` -- and both must be [0.0, 1.0] closed.
    The constructor already refuses otherwise; this asserts the table has exactly those two."""
    classifiers = {s.key for s in _shipped_specs() if s.kind == "classifier"}
    assert classifiers == {"corpus.spam_score", "garble.score"}


def test_the_three_registered_and_unread_keys_are_present() -> None:
    """05:2187: *"Three are registered and read by no shipped rule, deliberately."* They are slice
    axes and hooks, which is the alternative to olmocr's document-level exclusion with a
    `logger.info`; `agree.decode_vs_page` is read by the quality writer and not by `evaluate()`."""
    registered = set(ev.build_registry(_shipped_specs()).keys())
    for key in ("corpus.spam_score", "corpus.dup_of", "agree.decode_vs_page"):
        assert key in registered


def test_agree_decode_vs_page_is_the_only_key_requiring_two_rungs() -> None:
    """When a part escalates you have already paid for two readings of the same pixels, so the
    edit distance costs nothing and lands exactly on the population where the cheap driver is
    suspect (05:2251). Nothing else in the table reads two rungs' output."""
    two = {s.key for s in _shipped_specs() if len(s.requires) > 1}
    assert two == {"agree.decode_vs_page"}


def test_pdfium_and_officexml_never_claim_one_format_for_one_key() -> None:
    """`build_registry` would refuse it; this says WHICH property makes it hold -- the office card
    excludes `application/pdf` although anydoc decodes it, because `parse.pdf.pdfium` owns that
    path. A future `pdf` in the office `serves` list fails here with a readable message."""
    by_provider: dict[str, dict[str, frozenset[str]]] = {}
    for spec in _shipped_specs():
        by_provider.setdefault(spec.provider, {})[spec.key] = spec.serves
    pdf, office = by_provider["pdfium"], by_provider["officexml"]
    for key in set(pdf) & set(office):
        assert not (pdf[key] & office[key]), f"{key}: {sorted(pdf[key] & office[key])}"


def test_every_shipped_row_declares_a_version_that_enters_the_read_set() -> None:
    assert all(spec.version for spec in _shipped_specs())


def test_builtin_specs_reads_the_package_data_beside_this_module() -> None:
    """`builtin` is NOT an entry point -- the framework's own declarations are package data, which
    is `discovery.TOMBSTONE_DIRNAME`'s precedent. An entry point would make registration depend on
    this distribution's metadata being installed, which it is not in a source checkout."""
    assert ev.BUILTIN_SIGNALS.name == "signals.toml"
    assert ev.BUILTIN_SIGNALS.parent.name == "route"
    assert len(ev.builtin_specs()) == 37
    assert {spec.provider for spec in ev.builtin_specs()} == {"builtin", "admit"}


# --------------------------------------------------------------------------------------------
# 6. `installed_specs` -- three failures, and only two of them raise.
# --------------------------------------------------------------------------------------------


class _Entry:
    """The two attributes `_signal_entry_points` reads off an `EntryPoint`, and no `load()`."""

    def __init__(self, group: str, name: str, value: str) -> None:
        self.group, self.name, self.value = group, name, value


class _Dist:
    """A stand-in for `Distribution`: an entry-point list and a `locate_file` that joins a root.

    `importlib.metadata.Distribution` is abstract and its concrete subclass needs a real
    `dist-info` on disk. What `installed_specs()` uses of it is exactly two members, so this is
    the whole surface -- and writing it out is also the assertion that the surface is that small:
    a future edit that reached for `dist.files` or `EntryPoint.load()` would fail here first,
    which is INV-4's rule enforced by the test rather than by a comment.
    """

    def __init__(self, root: Any, entries: list[_Entry]) -> None:
        self._root, self.entry_points = root, entries

    def locate_file(self, path: str) -> Any:
        return self._root / path


def _dist(root: Any, name: str, value: str) -> Any:
    return _Dist(
        root, [_Entry(ev.SIGNAL_GROUP, name, value), _Entry("omniweave.drivers", "d", "p")]
    )


ROW = b"""
[signal."decode.cid_ratio"]
serves = ["pdf"]
scope = "part"
kind = "measure"
dtype = "float"
domain = [0.0, 1.0]
cost_class = "free"
version = "1.0.0"
"""


def test_installed_specs_locates_a_provider_by_name_and_reads_nothing_else(tmp_path: Any) -> None:
    """`Distribution.locate_file(signals_relative_path(value))` -- one path join per provider.

    Never a walk of `Distribution.files`: that scan was measured at **2124 ms** for 328 installed
    distributions against a claimed 1-4 ms, three orders of magnitude wrong (04 section 4.1).
    """
    pkg = tmp_path / "omniweave_pdf"
    pkg.mkdir()
    (pkg / "signals.toml").write_bytes(ROW)
    found = ev.installed_specs([_dist(tmp_path, "pdfium", "omniweave_pdf")])
    assert found.missing == ()
    assert [s.key for s in found.specs] == ["decode.cid_ratio"]
    assert found.specs[0].provider == "pdfium"
    assert "omniweave_pdf" in found.specs[0].origin


def test_an_absent_signals_toml_is_reported_and_does_not_raise(tmp_path: Any) -> None:
    """D128's shape, reaching the signal registry: an editable install writes a `.pth` shim and
    leaves `site-packages` empty, so `locate_file` names a path the package is not at. It is the
    state of THIS repository's own checkout, and `omniweave_core.discovery` makes the same call
    for `driver.toml` and records a `card_missing` fault rather than raising."""
    ok = tmp_path / "good"
    (ok / "omniweave_pdf").mkdir(parents=True)
    (ok / "omniweave_pdf" / "signals.toml").write_bytes(ROW)
    found = ev.installed_specs(
        [
            _dist(ok, "pdfium", "omniweave_pdf"),
            _dist(tmp_path / "nowhere", "officexml", "omniweave_office"),
        ]
    )
    assert len(found.specs) == 1
    assert len(found.missing) == 1
    assert "officexml" in found.missing[0]
    assert "omniweave_office" in found.missing[0]


def test_a_present_but_malformed_signals_toml_raises(tmp_path: Any) -> None:
    """The other side of the split: the author of a file that EXISTS can fix it, and skipping it
    hides the fix behind an `OW-P-001` on a rule the operator wrote correctly."""
    pkg = tmp_path / "omniweave_pdf"
    pkg.mkdir()
    (pkg / "signals.toml").write_bytes(b"[signal.\n")
    with pytest.raises(RouteError, match="readable TOML"):
        ev.installed_specs([_dist(tmp_path, "pdfium", "omniweave_pdf")])


def test_an_entry_point_may_not_claim_a_reserved_provider_name(tmp_path: Any) -> None:
    """`admit` names a function in this process. A distribution claiming it would put a locatable
    package behind a name that has none."""
    with pytest.raises(RouteError, match="reserved provider name"):
        ev.installed_specs([_dist(tmp_path, "admit", "omniweave_pdf")])


@pytest.mark.parametrize("value", ["omniweave_pdf:Driver", "omniweave/pdf", "", ".leading"])
def test_a_malformed_entry_point_value_raises(tmp_path: Any, value: str) -> None:
    """`discovery.PACKAGE_PATH_RE`, and its reasoning: a value with a leading empty segment makes
    `Path(parent) / "//signals.toml"` an ABSOLUTE path and the join escapes the distribution. A
    `:` is the card's `entrypoint` grammar pasted into the wrong field."""
    with pytest.raises(RouteError, match="colon-free dotted package path"):
        ev.installed_specs([_dist(tmp_path, "pdfium", value)])


def test_only_the_signal_group_is_read(tmp_path: Any) -> None:
    """`omniweave.drivers` rows are in every `_dist` above and contribute nothing here. The two
    groups are read by two consumers at two different times, and neither enumerates the other's."""
    drivers_only: Any = _Dist(tmp_path, [_Entry("omniweave.drivers", "d", "omniweave_pdf")])
    assert ev.installed_specs([drivers_only]) == ev.Installed(specs=(), missing=())
