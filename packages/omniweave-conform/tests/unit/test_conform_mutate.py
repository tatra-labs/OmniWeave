"""`omniweave_conform.mutate` -- the one definition of "malformed" in this repository.

Two mechanisms read it and they are deliberately different: the `fuzz` conformance suite runs it
over a driver author's own fixtures on the author's machine, and `fuzz/targets/` runs it over
`fuzz/seeds/` under `pytest fuzz/` and under atheris in the nightly job 14-security.md:477
specifies. A driver green under one and red under the other would mean one framework holding two
views of what a corrupt input is, which is what INV-21 exists to prevent -- so the last test here
pins the two together rather than trusting the import.

The rest is about what each mutation actually *is*, because the names are the accusation
(04-driver-system.md:2082's "a corpus of malformed inputs") and a `bitflip` that flipped nothing
would be a green suite reporting an exec it never ran. The extraction from `suites/fuzz.py` found
exactly that class of drift: the docstring accused seven things and the generator yielded six.

Specified in 04-driver-system.md section 8.2 row 11, 03-document-model.md P28, 14-security.md
section 2.9 and 13-quality.md:163-168.
"""

from __future__ import annotations

from omniweave_conform.mutate import (
    MUTATION_NAMES,
    NESTING_DEPTH,
    TRUNCATE_FRACTIONS,
    count,
    mutations,
)

DATA = b"0123456789" * 10  # 100 bytes, so a fraction of it is an exact integer


def named(data: bytes) -> dict[str, bytes]:
    return dict(mutations(data))


# ---------------------------------------------------------------------------
# the set
# ---------------------------------------------------------------------------


def test_a_non_empty_input_yields_every_name_in_order() -> None:
    assert tuple(name for name, _ in mutations(DATA)) == MUTATION_NAMES


def test_empty_is_yielded_and_was_the_defect_the_extraction_found() -> None:
    """`suites/fuzz.py`'s docstring accused `empty` of catching "the degenerate case every parser
    forgets" over a generator that never produced it. Both shipped drivers survive it, so the fix
    cost nothing -- but a mutation named and not run is an exec a report counts and never made."""
    assert "empty" in MUTATION_NAMES
    assert named(DATA)["empty"] == b""


def test_a_zero_byte_input_has_no_byte_to_flip() -> None:
    """The one place the yielded count is not `len(MUTATION_NAMES)`, and the reason `count()`
    generates rather than multiplying: a hand-written multiplier is off by one here."""
    assert "bitflip" not in named(b"")
    assert count(b"") == len(MUTATION_NAMES) - 1
    assert count(DATA) == len(MUTATION_NAMES)


def test_the_generator_is_pure_and_ordered() -> None:
    """`random` is banned in this workspace -- "Sampling is blake2b. Determinism is a gate, not a
    habit" -- and a corpus that differed between two runs would make a red build a coin flip."""
    assert list(mutations(DATA)) == list(mutations(DATA))


# ---------------------------------------------------------------------------
# what each one actually does
# ---------------------------------------------------------------------------


def test_truncation_cuts_at_both_fractions() -> None:
    """0.5 lands mid-structure and 0.05 lands inside the header; a parser that survives one
    routinely dies on the other, which is why there are two."""
    assert TRUNCATE_FRACTIONS == (0.5, 0.05)
    out = named(DATA)
    assert out["truncated@0.5"] == DATA[:50]
    assert out["truncated@0.05"] == DATA[:5]


def test_a_bitflip_changes_exactly_one_byte_and_keeps_the_length() -> None:
    """A checksum nobody checks. A flip that changed the length would be caught by a length check
    instead and would never reach the checksum."""
    flipped = named(DATA)["bitflip"]
    assert len(flipped) == len(DATA)
    differ = [i for i, (a, b) in enumerate(zip(DATA, flipped, strict=True)) if a != b]
    assert differ == [len(DATA) // 2]
    assert flipped[differ[0]] == DATA[differ[0]] ^ 0xFF


def test_nul_injects_a_c_string_boundary_into_the_middle() -> None:
    out = named(DATA)["nul"]
    assert len(out) == len(DATA) + 64
    assert out[50:114] == b"\x00" * 64
    assert out.replace(b"\x00", b"") == DATA


def test_nested_is_balanced_and_deep_enough_to_exhaust_a_recursive_parser() -> None:
    out = named(DATA)["nested"]
    assert len(out) == 2 * NESTING_DEPTH
    assert out.count(b"[") == out.count(b"]") == NESTING_DEPTH
    assert out.startswith(b"[[[") and out.endswith(b"]]]")


def test_giant_length_prefixes_a_length_field_worth_trusting_and_not_trusting() -> None:
    """0x7FFFFFFF little-endian: the largest positive signed 32-bit value, which is what a parser
    that reads a length from the input and trusts it will try to allocate."""
    out = named(DATA)["giant_length"]
    assert out[:4] == b"\xff\xff\xff\x7f"
    assert int.from_bytes(out[:4], "little") == 0x7FFFFFFF
    assert out[4:] == DATA


def test_every_mutation_of_an_empty_input_is_still_produced() -> None:
    """A corpus can hold a zero-byte file and the generator must not die on one."""
    out = named(b"")
    assert out["truncated@0.5"] == b""
    assert out["nul"] == b"\x00" * 64
    assert out["giant_length"] == b"\xff\xff\xff\x7f"


# ---------------------------------------------------------------------------
# INV-21: the suite and this module are one definition
# ---------------------------------------------------------------------------


def test_the_fuzz_suite_yields_exactly_what_this_module_yields() -> None:
    """The pin. `suites/fuzz._mutations` is a one-line delegation today and this is what keeps it
    one: a suite that grew its own seventh mutation would be telling a driver author something
    `fuzz/targets/` never told the nightly job."""
    from pathlib import Path  # noqa: PLC0415 -- one test needs it

    from omniweave_conform.harness import Fixture, MemoryBlobStore  # noqa: PLC0415
    from omniweave_conform.suites.fuzz import _mutations  # noqa: PLC0415 -- the pin's subject

    fixture = Fixture(
        path=Path("x.bin").resolve(), data=DATA, digest=MemoryBlobStore.digest_of(DATA)
    )
    assert list(_mutations(fixture)) == list(mutations(DATA))
