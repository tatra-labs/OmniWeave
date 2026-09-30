"""The paired-damage suite's library half: the table, the Injectors, `split_fix` and `assess`.

The run itself, which builds fixtures and executes the fixes, is `tools/ow_damage.py`, and the
conform tier runs it end to end (`packages/omniweave/tests/conform/test_damage_suite.py`). These
are the parts that need no process: the population, the damage, the split, and the four clauses,
each of which is shown failing on the run it exists to catch.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave_conform import damage
from omniweave_conform.damage import (
    DAMAGE_PASSWORD,
    INFLATE_MAX_PARTS,
    INJECTORS,
    MASK,
    PASSWORD_FILE,
    TABLE,
    Cause,
    FixRefusedError,
    Observed,
    assess,
    chaos,
    encrypt,
    inflate,
    mask_format,
    raise_limit,
    split_fix,
    supply_password,
)
from omniweave_conform.pdfpages import page_count
from omniweave_core.retrieve.types import ABSENCE_GATES
from omniweave_core.retrieve.verdict import ABSENCE_BLOCKING_DIAGS

# ---------------------------------------------------------------------------------------------
# the population
# ---------------------------------------------------------------------------------------------


def test_the_table_is_one_injector_per_blocking_diag_in_its_order() -> None:
    """13:2118: *"one per `Diag` code in `ABSENCE_BLOCKING_DIAGS`"*. A fourteenth code cannot
    join that tuple without a row here, and `degradation_detection` is a claim about this set."""
    assert tuple(row.diag for row in TABLE) == ABSENCE_BLOCKING_DIAGS
    assert len({row.name for row in TABLE}) == len(TABLE) == 13


def test_each_row_names_the_gate_07_says_its_injector_reaches() -> None:
    """07:2218-2232: six gates are `Diag`-driven, and gate 9 takes eight of the thirteen."""
    by_gate: dict[str, list[str]] = {}
    for row in TABLE:
        assert row.gate in ABSENCE_GATES, row
        by_gate.setdefault(row.gate, []).append(row.name)
    assert sorted(by_gate["parse_gap_in_scope"]) == sorted(
        [
            "encrypt",
            "strip_text_layer",
            "chaos",
            "downgrade_origin_span",
            "mask_format",
            "inflate",
            "strip_integrity",
            "synopsize",
        ]
    )
    assert {gate: names for gate, names in by_gate.items() if gate != "parse_gap_in_scope"} == {
        "timed_out": ["stall"],
        "channel_unavailable": ["deny_probe"],
        "coverage_incomplete": ["drop_part"],
        "pending_work_in_scope": ["budget"],
        "space_mismatch": ["rotate_embedder"],
    }


def test_every_built_injector_is_a_row_of_the_table() -> None:
    assert set(INJECTORS) <= {row.name for row in TABLE}
    for name, injector in INJECTORS.items():
        assert injector.row in TABLE
        assert injector.name == name


# ---------------------------------------------------------------------------------------------
# mask_format
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pristine",
    [b"PK\x03\x04" + b"\x14\x00" * 40, b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\n"],
    ids=["zip", "pdf"],
)
def test_mask_format_rewrites_the_magic_and_nothing_else(pristine: bytes) -> None:
    """13:1292: the leading magic, so no enabled driver accepts the unit. Every later byte is the
    pristine file's, so the damage is the one named thing."""
    masked = mask_format(pristine)
    assert len(masked) == len(pristine)
    assert masked.startswith(MASK)
    assert masked[len(MASK) :] == pristine[len(MASK) :]
    assert not masked.startswith((b"PK", b"%PDF"))
    assert b"\x00" in masked[: len(MASK)]


def test_mask_format_refuses_a_file_it_could_only_erase() -> None:
    with pytest.raises(ValueError, match="more than 8 bytes"):
        mask_format(b"PK\x03\x04")


def test_chaos_cuts_a_part_at_its_midpoint() -> None:
    """13:1285: *"truncates a part mid-stream at a fixed byte offset"*: the first half, kept."""
    pristine = bytes(range(256)) * 4
    cut = chaos(pristine)
    assert cut == pristine[: len(pristine) // 2]
    assert chaos(b"ab") == b"a"
    with pytest.raises(ValueError, match="at least 2 bytes"):
        chaos(b"a")


PDF = Path(__file__).resolve().parents[3] / "omniweave-pdf" / "fixtures" / "gen01p.pdf"


def test_encrypt_applies_a_user_password_to_the_whole_document() -> None:
    """ADR-15 D15.6: RC4-128 under `DAMAGE_PASSWORD` (`test_pdfcrypt.py` has pdfium refuse it and
    read it back). A PDF it cannot write is refused by name, never damaged some other way."""
    pristine = PDF.read_bytes()
    locked = encrypt(pristine)
    assert b"/Encrypt" in locked
    assert b"/Filter /Standard /V 2 /R 3" in locked
    assert encrypt(pristine) == locked, "deterministic, so a fixture is one set of bytes"
    with pytest.raises(ValueError, match="already"):
        encrypt(locked)


def test_the_encrypt_injector_repairs_rather_than_restores() -> None:
    injector = INJECTORS["encrypt"]
    assert injector.row.diag == "OW_ENCRYPTED"
    assert injector.applies_to == frozenset({".pdf"})
    assert (injector.restores_source, injector.repair) == (False, supply_password)


def test_the_password_is_supplied_the_way_gate_9_s_refusal_says() -> None:
    """D15.5's detail, as `store.reader` writes it, is the only thing `supply_password` reads: the
    `password_file` line and the `OW_SECRET_*` variable. The secret goes to the environment, and
    the files hold the mapping and the key that names it."""
    from omniweave_core.store.reader import _password_remedy  # noqa: PLC0415 -- real text

    uri = "c:/corpus/medical/lab-results-2024.pdf"
    detail = f"{uri}: refused as encrypted, so no document was written{_password_remedy(uri)}"
    repair = supply_password(detail)
    assert repair.env == {"OW_SECRET_LAB_RESULTS_2024": DAMAGE_PASSWORD}
    assert repair.append == {
        PASSWORD_FILE: f'"{uri}" = "lab-results-2024"\n',
        "omniweave.toml": f'\n[ingest]\npassword_file = "{PASSWORD_FILE}"\n',
    }


@pytest.mark.parametrize(
    ("detail", "why"),
    [
        ("c:/a.pdf: refused as encrypted; set OW_SECRET_A", "names no password_file line"),
        ('add the line `"c:/a.pdf" = "a"` to the password file', "names no OW_SECRET_ variable"),
    ],
)
def test_a_refusal_that_does_not_say_how_fails_the_fourth_clause_by_name(
    detail: str, why: str
) -> None:
    with pytest.raises(FixRefusedError, match=why):
        supply_password(detail)


@pytest.mark.parametrize("name", ["gen01p.pdf", "gen02p.pdf"])
def test_inflate_pads_a_pdf_to_exactly_one_page_above_the_cap(name: str) -> None:
    """D644, 13:1294: *"exactly one row above a `[limits]` value"*. The row is a page, and the value
    is the `[ingest] max_parts` the Injector's own `config` builds the fixture under."""
    pristine = (PDF.parent / name).read_bytes()
    inflated = inflate(pristine)
    assert page_count(inflated) == INFLATE_MAX_PARTS + 1
    assert inflated.startswith(pristine)
    assert inflate(pristine) == inflated, "deterministic, so a fixture is one set of bytes"


def test_the_inflate_injector_builds_under_its_cap_and_repairs_rather_than_restores() -> None:
    injector = INJECTORS["inflate"]
    assert injector.row.diag == "OW_RESOURCE_LIMIT"
    assert injector.applies_to == frozenset({".pdf"})
    assert (injector.restores_source, injector.repair) == (False, raise_limit)
    assert injector.config == f"\n[ingest]\nmax_parts = {INFLATE_MAX_PARTS}\n"
    assert all(not other.config for name, other in INJECTORS.items() if name != "inflate")


def test_the_limit_is_raised_the_way_gate_9_s_refusal_says() -> None:
    """D644's detail, as `store.reader` writes it, is the only thing `raise_limit` reads: the
    `OMNIWEAVE_INGEST_MAX_PARTS` value that admits the file, into the fix child's environment."""
    from omniweave_core.store.reader import PartsRefused, _parts_remedy  # noqa: PLC0415

    detail = "c:/corpus/long.pdf: refused as resource_limit" + _parts_remedy(PartsRefused(4, 3))
    repair = raise_limit(detail)
    assert repair.env == {"OMNIWEAVE_INGEST_MAX_PARTS": "4"}
    assert repair.append == {}


def test_a_limit_refusal_that_names_no_value_fails_the_fourth_clause_by_name() -> None:
    with pytest.raises(FixRefusedError, match="names no OMNIWEAVE_INGEST_MAX_PARTS value"):
        raise_limit("c:/corpus/huge.pdf: refused as resource_limit (detection sniffed pdf)")


def test_the_built_injectors_are_in_the_table_s_order() -> None:
    """The report reads as 13:1281-1295 does, whatever order they landed in."""
    order = [row.name for row in TABLE]
    assert list(INJECTORS) == sorted(INJECTORS, key=order.index)


# ---------------------------------------------------------------------------------------------
# split_fix
# ---------------------------------------------------------------------------------------------


def test_a_fix_splits_posix_style_and_keeps_a_quoted_path_whole() -> None:
    assert split_fix("ow add 'e:/my docs/tax summary.docx'") == (
        "ow",
        "add",
        "e:/my docs/tax summary.docx",
    )


@pytest.mark.parametrize(
    ("fix", "why"),
    [
        ("", "no fix"),
        ("   ", "no fix"),
        ("rm -rf /", "not an `ow` command"),
        ("ow add 'unterminated", "does not split"),
    ],
)
def test_a_fix_the_harness_will_not_run_is_refused_with_its_reason(fix: str, why: str) -> None:
    """13:1308: an empty or unparseable fix is *"a failure of `degradation_detection`, not an
    exemption from it"*."""
    with pytest.raises(FixRefusedError, match=why):
        split_fix(fix)


def test_a_shell_operator_is_a_character_and_never_an_operator() -> None:
    """There is no shell, so `;` separates nothing. What it spells is left to the registry."""
    assert split_fix("ow add a.pdf; rm -rf x") == ("ow", "add", "a.pdf;", "rm", "-rf", "x")


# ---------------------------------------------------------------------------------------------
# assess: four clauses, each shown failing
# ---------------------------------------------------------------------------------------------

MASK_INJECTOR = INJECTORS["mask_format"]
CLEAN = Observed(state="low_confidence", gates=(), causes=())
NAMED = Observed(
    state="degraded",
    gates=("parse_gap_in_scope",),
    causes=(Cause("parse_gap_in_scope", ("OW_UNSUPPORTED_FORMAT",), "ow add x.docx"),),
)


def _clauses(**runs: object) -> dict[str, bool]:
    kwargs: dict[str, object] = {"pristine": CLEAN, "damaged": NAMED, "fixed": CLEAN, **runs}
    result = assess(MASK_INJECTOR, "fixture", **kwargs)  # type: ignore[arg-type]
    return {clause.name: clause.ok for clause in result.clauses}


def test_a_pair_that_degrades_names_its_cause_and_is_fixed_passes() -> None:
    result = assess(MASK_INJECTOR, "fixture", pristine=CLEAN, damaged=NAMED, fixed=CLEAN)
    assert result.ok
    assert [clause.name for clause in result.clauses] == [
        "counterfactual",
        "degraded",
        "named cause",
        "fix fixes",
    ]


def test_a_fixture_whose_pristine_run_already_fires_the_gate_is_vacuous() -> None:
    """13:1320: *"an injector whose gate passes vacuously is an injector that tests nothing"*."""
    assert _clauses(pristine=NAMED)["counterfactual"] is False


@pytest.mark.parametrize("state", ["ok", "absent", "low_confidence"])
def test_a_damaged_run_that_is_not_degraded_fails(state: str) -> None:
    """13:1297: *"`degraded` (never `ok`, never `absent`)"*."""
    assert _clauses(damaged=Observed(state, NAMED.gates, NAMED.causes))["degraded"] is False


def test_the_right_gate_with_the_wrong_code_is_not_the_named_cause() -> None:
    """Gate 9 is eight Injectors' gate, so the gate alone does not say which damage it saw."""
    other = Observed(
        "degraded",
        ("parse_gap_in_scope",),
        (Cause("parse_gap_in_scope", ("OW_MALFORMED",), "ow add x.docx"),),
    )
    assert _clauses(damaged=other)["named cause"] is False


def test_the_gates_must_come_in_precedence_order() -> None:
    """13:1297: *"the expected gate **in precedence order**"*. Gate 8 ranks above gate 9."""
    shuffled = Observed(
        "degraded",
        ("parse_gap_in_scope", "inputs_unreadable"),
        (*NAMED.causes, Cause("inputs_unreadable", (), "ow doctor")),
    )
    assert _clauses(damaged=shuffled)["named cause"] is False
    ordered = Observed("degraded", ("inputs_unreadable", "parse_gap_in_scope"), shuffled.causes)
    assert _clauses(damaged=ordered)["named cause"] is True


def test_a_fix_that_leaves_the_run_different_from_the_pristine_one_fails() -> None:
    """13:1297: *"a fix instruction that does not fix is a lie with a shell prompt in front of
    it"*. This is the clause that caught D640's stranded unit."""
    assert _clauses(fixed=NAMED)["fix fixes"] is False


def test_a_fix_that_could_not_run_fails_and_says_why() -> None:
    result = assess(
        MASK_INJECTOR,
        "fixture",
        pristine=CLEAN,
        damaged=NAMED,
        fixed=None,
        fix_refusal="`ow frobnicate` resolves as no-such-root, not as an Action",
    )
    last = result.clauses[-1]
    assert (last.name, last.ok) == ("fix fixes", False)
    assert "no-such-root" in last.why
    assert not result.ok


def test_the_module_says_what_it_is() -> None:
    assert damage.__doc__ is not None
    assert "13-quality.md section 8.6" in damage.__doc__
