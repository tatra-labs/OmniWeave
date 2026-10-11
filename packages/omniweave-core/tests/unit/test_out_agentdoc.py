"""`omniweave_core.out.agentdoc`: a table found from its card, and 09 section 3.3's agent doc.

The budget half is 09 section 3.5 item 5's CI gate: every implemented compile card this checkout
ships, rendered with `--format md` and counted in `cl100k_base` tokens, whole and per group, against
its own `agent_doc_tokens_max`. It skips rather than fails without the tokenizer, for SV2's reason
(`test_gen_budget.py`): `tiktoken` is a dev-only dependency and resolving its table can reach the
network.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import omniweave_conform.suites.target as target_suites
import pytest
from omniweave_core.discovery import discover
from omniweave_core.drivers.card import DriverCard
from omniweave_core.errors import DriverHostError, NotFoundError, TargetError, load_register
from omniweave_core.out.agentdoc import agent_doc, group_of, groups, load_table, select
from omniweave_core.out.card import CompileCard
from omniweave_core.out.constructs import Disposition

SUITES = Path(target_suites.__file__).parent
OWTEXT = SUITES / "owtext"
ENV = {"OMNIWEAVE_DRIVER_PATH": str(SUITES)}


def _compile_cards() -> list[tuple[DriverCard, CompileCard]]:
    return [
        (card, CompileCard.of(card))
        for card in discover(env=ENV).cards
        if str(card.identity.port) == "compile"
    ]


def _owtext() -> tuple[Path, CompileCard]:
    [(card, compiled)] = [(d, c) for d, c in _compile_cards() if c.target == "owtext"]
    return Path(card.source), compiled


def _copy(tmp_path: Path) -> Path:
    """owtext's directory, to edit: the card, the table and `normalizers.py`."""
    here = tmp_path / "owtext"
    shutil.copytree(OWTEXT, here, ignore=shutil.ignore_patterns("__pycache__"))
    return here


def _card_at(here: Path) -> CompileCard:
    env = {"OMNIWEAVE_DRIVER_PATH": str(here.parent)}
    [card] = [c for c in discover(env=env).cards if str(c.identity.port) == "compile"
              and CompileCard.of(c).target == "owtext"]  # fmt: skip
    return CompileCard.of(card)


# ---------------------------------------------------------------------------------------------
# Rulings 1-3: the table beside its card
# ---------------------------------------------------------------------------------------------


def test_the_table_is_the_one_beside_the_card_and_matches_its_digest() -> None:
    path, card = _owtext()
    table = load_table(path, card)
    assert table.digest() == card.constructs_digest
    assert len(table.rows) == 10
    assert table.row("attr.class.upper").normalizer == "lower_ascii"


def test_documenting_a_table_imports_nothing_from_the_target() -> None:
    """Ruling 1: the normalizer is a name read with `ast`, and calling it is refused."""
    path, card = _owtext()
    table = load_table(path, card)
    assert table.row("attr.class.upper").disposition is Disposition.NORMALIZE
    import omniweave_core.out.agentdoc as module  # noqa: PLC0415

    with pytest.raises(TargetError, match="while a construct table was being documented"):
        module._documented_only("X")


def test_a_normalizer_the_target_does_not_define_still_refuses_the_table(tmp_path: Path) -> None:
    here = _copy(tmp_path)
    (here / "normalizers.py").write_text("def other(value):\n    return value\n", encoding="utf-8")
    with pytest.raises(
        TargetError, match=re.escape("normalizer 'lower_ascii' is not in normalizers.py")
    ):
        load_table(here / "driver.toml", _card_at(here))
    (here / "normalizers.py").unlink()
    with pytest.raises(
        TargetError, match=re.escape("normalizer 'lower_ascii' is not in normalizers.py")
    ):
        load_table(here / "driver.toml", _card_at(here))


def test_a_normalizers_file_that_does_not_parse_is_named(tmp_path: Path) -> None:
    here = _copy(tmp_path)
    (here / "normalizers.py").write_text("def lower_ascii(:\n", encoding="utf-8")
    with pytest.raises(TargetError, match=r"normalizers.py does not parse") as caught:
        load_table(here / "driver.toml", _card_at(here))
    assert caught.value.code() == "OW_TARGET_CONSTRUCTS_INVALID"


def test_a_nested_or_imported_name_is_not_a_normalizer(tmp_path: Path) -> None:
    """Only a top-level `def` is a function the module ships under that name."""
    here = _copy(tmp_path)
    (here / "normalizers.py").write_text(
        "from string import ascii_lowercase as lower_ascii\n"
        "class C:\n    def lower_ascii(self, v):\n        return v\n",
        encoding="utf-8",
    )
    with pytest.raises(TargetError, match=re.escape("'lower_ascii' is not in normalizers.py")):
        load_table(here / "driver.toml", _card_at(here))


def test_a_table_the_card_does_not_vouch_for_is_the_cards_error(tmp_path: Path) -> None:
    """Ruling 2: an edited table no longer digests to `constructs_digest`."""
    here = _copy(tmp_path)
    table = here / "constructs.toml"
    table.write_text(
        table.read_text(encoding="utf-8").replace('"lower-case ASCII"', '"lower-case"'),
        encoding="utf-8",
    )
    with pytest.raises(DriverHostError, match="constructs_digest is sha256:") as caught:
        load_table(here / "driver.toml", _card_at(here))
    assert caught.value.code() == "OW_CARD_INVALID"


def test_a_target_not_yet_implemented_may_name_its_table(tmp_path: Path) -> None:
    """Ruling 3, narrowed by D781: an unimplemented card that names a table has it read, held
    to its digest. docx was that card from D781 to D783; owtext's, marked so, stands in."""
    here = _copy(tmp_path)
    card_path = here / "driver.toml"
    text = card_path.read_text(encoding="utf-8")
    card_path.write_text(
        text.replace("implemented = true\n", 'implemented = false\nreason = "not yet"\n'),
        encoding="utf-8",
    )
    compiled = _card_at(here)
    assert not compiled.implemented
    table = load_table(card_path, compiled)
    assert table.digest() == compiled.constructs_digest


def test_an_unimplemented_target_has_no_table() -> None:
    """Ruling 3: video, which names none, with its reason."""
    [(card, compiled)] = [(d, c) for d, c in _compile_cards() if c.target == "video"]
    with pytest.raises(
        TargetError, match=r"implemented = false, because the hyperframes"
    ) as caught:
        load_table(Path(card.source), compiled)
    assert caught.value.code() == "OW_TARGET_NOT_IMPLEMENTED"


# ---------------------------------------------------------------------------------------------
# Ruling 4 and 7: groups and selections
# ---------------------------------------------------------------------------------------------


def test_a_group_is_the_ids_first_segment_in_first_use_order() -> None:
    path, card = _owtext()
    table = load_table(path, card)
    assert group_of("attr.class.upper") == "attr"
    assert groups(table.rows) == ("attr", "elem", "style")
    assert [r.id for r in select(table, "owtext", group="style")] == ["style.text-shadow"]
    assert [r.id for r in select(table, "owtext", construct="elem.script")] == ["elem.script"]
    assert select(table, "owtext") == table.rows


@pytest.mark.parametrize(
    ("given", "named"),
    [
        ({"group": "font"}, "its groups are attr, elem, style"),
        ({"construct": "elem.div"}, "its rows are attr.ow-cite"),
    ],
)
def test_an_unknown_group_or_construct_names_what_the_table_has(
    given: dict[str, Any], named: str
) -> None:
    path, card = _owtext()
    with pytest.raises(NotFoundError, match=named) as caught:
        select(load_table(path, card), "owtext", **given)
    assert caught.value.code() == "OW_CONSTRUCT_UNKNOWN"
    assert caught.value.fix == "ow out constructs owtext"


# ---------------------------------------------------------------------------------------------
# Ruling 5: one line a row
# ---------------------------------------------------------------------------------------------


def test_every_row_is_documented_once_and_nothing_else_is() -> None:
    """09 section 3.3: no row in the table goes undocumented, and nothing outside it is."""
    path, card = _owtext()
    table = load_table(path, card)
    doc = agent_doc(card, table)
    bullets = [line for line in doc.splitlines() if line.startswith("- ")]
    assert [line.split("`")[1] for line in bullets] == [
        row.id for group in groups(table.rows) for row in table.rows if group_of(row.id) == group
    ]
    assert doc.startswith("# owtext/1 constructs, target owtext\n")
    assert "Ignored: `html|head`, `html|meta`." in doc


def test_each_disposition_has_its_clause_and_the_registers_numeric() -> None:
    path, card = _owtext()
    lines = {
        line.split("`")[1]: line
        for line in agent_doc(card, load_table(path, card)).splitlines()
        if line.startswith("- ")
    }
    by_symbol = load_register().by_symbol
    assert lines["attr.class"] == "- `attr.class` `@class` native: lower-case ASCII (OW-T-406)"
    assert lines["attr.id"].endswith(
        ": unique within the unit, lower-case ASCII; forbidden when `html|style` is present "
        f"({by_symbol['OW_TARGET_ID_WITH_STYLE'].numeric})"
    )
    assert lines["attr.class.upper"] == (
        "- `attr.class.upper` normalize to `attr.class`: lower-case ASCII class names (OW-T-211)"
    )
    assert lines["style.text-shadow"] == (
        "- `style.text-shadow` `@style|text-shadow` bake at 192 dpi: this target cannot bake, "
        "so it is an error (OW-T-312)"
    )
    assert lines["elem.script"] == (
        "- `elem.script` `html|script` forbidden: executable content in an authored artefact; no "
        f"text mapping exists ({by_symbol['OW_TARGET_SCRIPT_FORBIDDEN'].numeric})"
    )


def test_a_symbol_the_register_does_not_have_is_printed_as_the_symbol() -> None:
    path, card = _owtext()
    doc = agent_doc(card, load_table(path, card), numeric=lambda symbol: symbol)
    assert "(OW_TARGET_CLASS_INVALID)" in doc
    assert "(OW-T-406)" not in doc


def test_a_group_renders_only_its_rows_under_the_same_preamble() -> None:
    path, card = _owtext()
    table = load_table(path, card)
    doc = agent_doc(card, table, select(table, "owtext", group="elem"))
    assert "## elem" in doc
    assert "## attr" not in doc
    assert doc.count("\n- ") == 4
    assert "native: write it as shown." in doc
    assert "Ignored: `html|head`, `html|meta`." in doc


def test_groups_follow_first_use_and_not_the_alphabet() -> None:
    """Ruling 4: owtext's table happens to use its groups alphabetically, so reorder it."""
    path, card = _owtext()
    table = load_table(path, card)
    rows = tuple(table.row(i) for i in ("style.text-shadow", "elem.p", "attr.id", "elem.script"))
    assert groups(rows) == ("style", "elem", "attr")
    doc = agent_doc(card, table, rows)
    assert doc.index("## style") < doc.index("## elem") < doc.index("## attr")
    assert doc.index("`elem.p`") < doc.index("`elem.script`")


# ---------------------------------------------------------------------------------------------
# Ruling 6: the CI gate, 09 section 3.5 item 5
# ---------------------------------------------------------------------------------------------


def _encoder() -> Any:
    tiktoken = pytest.importorskip("tiktoken", reason="tiktoken is a dev-only dependency (10:2585)")
    try:
        return tiktoken.get_encoding("cl100k_base").encode
    except Exception as exc:  # any failure here means "no table", which is not a defect
        pytest.skip(f"cl100k_base could not be resolved offline: {exc}")


def test_every_tabled_targets_agent_doc_is_under_its_budget_whole_and_per_group() -> None:
    """Every card that names a table, implemented or not (D781): docx is gated before it lowers."""
    encode = _encoder()
    tabled = [(d, c) for d, c in _compile_cards() if c.constructs]
    assert {c.target for _, c in tabled} >= {"owtext", "docx"}
    for driver_card, card in tabled:
        table = load_table(Path(driver_card.source), card)
        assert card.agent_doc_tokens_max > 0
        whole = len(encode(agent_doc(card, table)))
        assert whole <= card.agent_doc_tokens_max, (card.target, whole)
        for group in groups(table.rows):
            rows = select(table, card.target, group=group)
            assert len(encode(agent_doc(card, table, rows))) <= card.agent_doc_tokens_max
