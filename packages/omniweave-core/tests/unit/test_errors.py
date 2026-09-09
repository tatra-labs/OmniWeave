"""The `OwError` tree, the exit map and the `codes.toml` register.

Four properties, and the third is the one this project has already failed twice: two numerics
reached two symbols each and survived three verification passes (`OW-A-023` and `OW-A-041`,
18-api-sketch.md section 9 item 7). `check_register()` is the register half of
`ow explain --check`, and the fixture tests below prove it catches a third.

Specified in 02-architecture.md section 7.2, 18-api-sketch.md sections 0.3, 1.1 and 9 item 7,
10-interfaces.md section 9.3, 08-runtime.md section 1.6 and 05-ingest-and-routing.md section 4.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest
from omniweave_core import errors
from omniweave_core.errors import (
    AREA_CLASSES,
    AREA_LETTERS,
    FAILURE_CLASS_IS_FATAL,
    NUMERIC_RE,
    SYMBOL_RE,
    BudgetExhausted,
    CapabilityMissing,
    CodeRow,
    ConfigError,
    DriverHostError,
    GraphError,
    InternalError,
    ModelError,
    NotFoundError,
    OwError,
    PolicyRefusal,
    QualityError,
    ResourceLimit,
    RouteError,
    StoreBusy,
    StoreError,
    SurfaceError,
    TargetError,
    UsageError,
    check_register,
    explain,
    is_fatal_failure,
    load_register,
    register_path,
)

# The thirteen members of `omniweave_ports.FailureClass`, verbatim from charter.md line 1973.
# The test below prefers the real enum when the ports agent has landed it and falls back to
# these, so this file states the contract rather than merely echoing whatever ports happens to
# define today.
CHARTER_FAILURE_CLASSES = (
    "encrypted",
    "needs_ocr",
    "unsupported_format",
    "corrupt_input",
    "resource_limit",
    "too_large",
    "timeout",
    "upstream_unavailable",
    "rate_limited",
    "auth",
    "empty_result",
    "driver_crashed",
    "driver_bug",
)

# 08-runtime.md section 1.6: the classes whose ladder verdict is transient. Fatality is a
# DIFFERENT axis and the test below asserts they do not collapse into one another.
TRANSIENT_CLASSES = ("rate_limited", "upstream_unavailable", "timeout", "resource_limit")

# 10-interfaces.md section 9.3: seven of the twelve exit codes are a pure function of the class.
EXIT_MAP = (
    (UsageError, 1),
    (NotFoundError, 2),
    (BudgetExhausted, 5),
    (PolicyRefusal, 6),
    (StoreBusy, 7),
    (CapabilityMissing, 64),
    (InternalError, 70),
)

# 02-architecture.md section 7.2: level 1, one class per area letter, plus ResourceLimit.
LEVEL_ONE = (
    (ConfigError, "OW_CONFIG"),
    (ModelError, "OW_MODEL"),
    (DriverHostError, "OW_DRIVER_HOST"),
    (RouteError, "OW_ROUTE"),
    (StoreError, "OW_STORE"),
    (GraphError, "OW_GRAPH"),
    (TargetError, "OW_TARGET"),
    (SurfaceError, "OW_SURFACE"),
    (PolicyRefusal, "OW_POLICY"),
    (QualityError, "OW_QUALITY"),
    (ResourceLimit, "OW_RESOURCE_LIMIT"),
)


def _fixture_register(tmp_path: Path, body: str) -> Path:
    """A register carrying the ten area tables plus whatever rows the caller wants."""
    areas = "\n".join(
        f'[area.{letter}]\nerror_class = "{AREA_CLASSES[letter].__name__}"\n'
        for letter in AREA_LETTERS
    )
    path = tmp_path / "codes.toml"
    path.write_text(areas + "\n" + body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


def test_every_owerror_names_the_command_that_clears_it() -> None:
    """charter.md section 6.4 makes `fix` non-empty a constructor invariant, which is what the
    refusal to ship a `--force` rests on (02-architecture.md section 7.2)."""
    with pytest.raises(ValueError, match="exact command that clears it"):
        OwError("no fix", fix="")


def test_code_returns_the_symbol_and_an_instance_may_override_it() -> None:
    """The class picks the exit code; the instance's symbol picks the register row and therefore
    the area letter (18-api-sketch.md section 0.3)."""
    assert ConfigError("boom", fix="ow doctor").code() == "OW_CONFIG"
    retired = NotFoundError("retired cite", symbol="OW_ADDR_NOT_FOUND", fix="ow doc verify")
    assert retired.code() == "OW_ADDR_NOT_FOUND"
    assert retired.EXIT == 2, "the CLASS gives the exit code"
    assert retired.numeric().startswith("OW-M-"), "the SYMBOL gives the area letter"


def test_the_exit_code_is_a_pure_function_of_the_exception_class() -> None:
    """10-interfaces.md section 9.3. Seven leaves, and no raise site passes an exit as an arg."""
    for cls, exit_code in EXIT_MAP:
        assert exit_code == cls.EXIT, cls.__name__
    assert OwError.EXIT == 70, "the floor (18-api-sketch.md section 0.3)"
    assert ConfigError.EXIT == 1
    assert ResourceLimit.EXIT == 1, "its .limit names the knob, so it is a configuration error"


def test_level_two_subclasses_level_one_so_isinstance_answers_on_both_axes() -> None:
    """18-api-sketch.md section 0.3: nothing needs multiple inheritance."""
    assert issubclass(UsageError, SurfaceError)
    assert issubclass(NotFoundError, SurfaceError)
    assert issubclass(BudgetExhausted, RouteError)
    assert issubclass(StoreBusy, StoreError)
    assert issubclass(CapabilityMissing, DriverHostError)
    assert issubclass(InternalError, OwError)
    for cls, _ in EXIT_MAP:
        assert issubclass(cls, OwError)


def test_the_eleven_level_one_classes_carry_their_area_symbol() -> None:
    """02-architecture.md section 7.2. The eleventh is cross-area."""
    for cls, symbol in LEVEL_ONE:
        assert symbol == cls.SYMBOL, cls.__name__
    assert len(AREA_CLASSES) == len(AREA_LETTERS) == 10


def test_a_resource_limit_names_which_knob_would_need_raising() -> None:
    """The ONE error required to name a knob (02-architecture.md section 7.2)."""
    with pytest.raises(ValueError, match="WHICH knob"):
        ResourceLimit("too big", limit="", fix="raise [limits] max_xml_nodes")
    breach = ResourceLimit("too big", limit="max_xml_nodes", fix="raise [limits] max_xml_nodes")
    assert breach.limit == "max_xml_nodes"
    assert breach.is_fatal()


def test_the_level_two_leaves_carry_their_machine_actionable_field() -> None:
    """10-interfaces.md section 9.3 names one extra field on three of the six leaves."""
    denied = BudgetExhausted("over budget", approve_command="ow add x --allow-cost 5000")
    assert denied.approve_command == "ow add x --allow-cost 5000"
    assert denied.fix == denied.approve_command, "the approving command IS the fix"

    busy = StoreBusy("held", holder=("hostA", 4142, 12.5), fix="wait, or ow store unlock")
    assert busy.holder == ("hostA", 4142, 12.5)

    missing = CapabilityMissing("no soffice", missing=("soffice",), fix="ow targets install")
    assert missing.missing == ("soffice",)
    with pytest.raises(ValueError, match="NAMES the missing thing"):
        CapabilityMissing("nothing named", missing=(), fix="ow targets install")


def test_numeric_degrades_to_empty_for_a_symbol_with_no_register_row() -> None:
    """A class default symbol names an AREA, not a condition, so it has no row -- and resolving
    a numeric must never be able to fail on top of the error being reported."""
    assert ConfigError("boom", fix="ow doctor").numeric() == ""
    assert SurfaceError("boom", symbol="OW_BAD_SCOPE_FORM", fix="ow query --help").numeric() == (
        "OW-A-023"
    )


# ---------------------------------------------------------------------------
# is_fatal
# ---------------------------------------------------------------------------


def test_a_raised_owerror_is_always_fatal() -> None:
    """anydoc's `is_fatal()`: a limit breach is never swallowed (02-architecture.md 7.2)."""
    assert OwError("x", fix="f").is_fatal()
    for cls, _ in EXIT_MAP:
        assert cls("x", fix="f", **_extra_kwargs(cls)).is_fatal(), cls.__name__


def _extra_kwargs(cls: type[OwError]) -> dict[str, object]:
    if cls is BudgetExhausted:
        return {"approve_command": "ow add x --allow-cost 1"}
    if cls is StoreBusy:
        return {"holder": ("h", 1, 0.0)}
    if cls is CapabilityMissing:
        return {"missing": ("soffice",)}
    return {}


def test_the_fatality_table_covers_every_failure_class() -> None:
    """Every `FailureClass` member has a decision, from the real enum when ports has landed it."""
    members = _failure_class_values()
    assert set(FAILURE_CLASS_IS_FATAL) == set(members), (
        "a FailureClass member with no fatality decision, or a decision with no member"
    )
    for value in members:
        assert isinstance(is_fatal_failure(value), bool)


def _failure_class_values() -> tuple[str, ...]:
    try:
        from omniweave_ports import FailureClass  # noqa: PLC0415 -- ports may not have landed.
    except (ImportError, AttributeError):
        return CHARTER_FAILURE_CLASSES
    values = tuple(str(member) for member in FailureClass)
    assert set(values) == set(CHARTER_FAILURE_CLASSES), (
        "omniweave_ports.FailureClass no longer matches charter.md line 1973"
    )
    return values


def test_exactly_three_failure_classes_are_not_fatal() -> None:
    """05-ingest-and-routing.md section 4 rule 3 lets the container walker's per-member `except`
    catch UNSUPPORTED_FORMAT and CORRUPT_INPUT and nothing else; 02-architecture.md section 7.1
    makes `needs_ocr` not a failure at all."""
    swallowable = sorted(k for k, fatal in FAILURE_CLASS_IS_FATAL.items() if not fatal)
    assert swallowable == ["corrupt_input", "needs_ocr", "unsupported_format"]
    assert is_fatal_failure("resource_limit"), "rule 3: a bomb refusal is never swallowed"
    assert is_fatal_failure("too_large")


def test_fatality_is_not_retryability() -> None:
    """08-runtime.md section 1.6's ladder calls four classes transient; all four are fatal here,
    because a helper that swallows a transient failure never gets to the retry at all."""
    for cls in TRANSIENT_CLASSES:
        assert is_fatal_failure(cls), f"{cls} is transient in the ladder AND fatal here"


def test_an_unknown_failure_class_is_our_bug_and_never_a_guess() -> None:
    """02-architecture.md section 7.5: an unknown wire kind is a DriverHostError (OW-D-*)."""
    with pytest.raises(DriverHostError) as caught:
        is_fatal_failure("needs_coffee")
    assert caught.value.code() == "OW_DRIVER_HOST"
    assert caught.value.fix, "every OwError names the command that clears it"


# ---------------------------------------------------------------------------
# The register
# ---------------------------------------------------------------------------


def test_the_shipped_register_is_locatable_and_parses() -> None:
    register = load_register()
    assert register.path == register_path()
    assert register.path.name == "codes.toml"
    assert len(register.rows) >= 40, "one register file plus ~40 codes at the P1 boundary (W1.3)"


def test_every_row_parses_and_every_numeric_is_unique() -> None:
    """The property `codes-unique` exists to hold, checked in both directions."""
    assert check_register() == (), "the shipped codes.toml fails ow explain --check"
    register = load_register()
    numerics = [row.numeric for row in register.rows]
    symbols = [row.symbol for row in register.rows]
    assert len(set(numerics)) == len(numerics)
    assert len(set(symbols)) == len(symbols)
    for row in register.rows:
        assert NUMERIC_RE.match(row.numeric), row.numeric
        assert SYMBOL_RE.match(row.symbol), row.symbol
        assert row.numeric[3] in AREA_LETTERS, row.numeric


def test_the_registers_ten_areas_are_the_ten_level_one_classes() -> None:
    """02-architecture.md section 7.2: the ten area letters are exactly the areas of
    codes.toml, and every one names its error class."""
    register = load_register()
    assert sorted(register.areas) == sorted(AREA_LETTERS)
    for letter, declared in register.areas.items():
        assert declared == AREA_CLASSES[letter].__name__


def test_every_raised_by_in_the_register_names_a_class_in_this_tree() -> None:
    """A register row that names an exception the tree does not define is a dangling promise."""
    raw = tomllib.loads(register_path().read_text(encoding="utf-8"))
    known = {cls.__name__ for cls, _ in EXIT_MAP} | {cls.__name__ for cls, _ in LEVEL_ONE}
    named = {str(row["raised_by"]) for row in raw["code"] if "raised_by" in row}
    assert named <= known, f"codes.toml names {sorted(named - known)}, which errors.py has not"


def test_explain_accepts_either_spelling_and_returns_the_same_row() -> None:
    """18-api-sketch.md section 1.1's worked transcript, both lines of it."""
    by_numeric = explain("OW-A-013")
    by_symbol = explain("OW_PARSE_GAP_IN_SCOPE")
    assert by_numeric == by_symbol
    assert isinstance(by_numeric, CodeRow)
    assert by_numeric.numeric == "OW-A-013"
    assert by_numeric.symbol == "OW_PARSE_GAP_IN_SCOPE"
    assert by_numeric.meaning, "a seeded row carries its one-line meaning"
    assert by_numeric.owner_doc.endswith(".md"), "the owning document"


def test_explain_returns_the_registers_text_not_a_hard_coded_string() -> None:
    """The reader is a reader: every field comes off the row."""
    row = explain("OW-C-043")
    raw = tomllib.loads(register_path().read_text(encoding="utf-8"))
    stored = next(r for r in raw["code"] if r["numeric"] == "OW-C-043")
    assert row.symbol == stored["symbol"] == "OW_SQLITE_TOO_OLD"
    assert row.meaning == stored.get("meaning", "")
    assert row.fix == stored.get("fix", ""), "W1.3 fills fix; the reader never invents one"


def test_explain_raises_a_specific_error_for_an_unregistered_code() -> None:
    """`NotFoundError(OW_UNKNOWN_CODE, OW-A-026)` listing the nearest three by edit distance."""
    with pytest.raises(NotFoundError) as caught:
        explain("OW-A-999")
    err = caught.value
    assert err.code() == "OW_UNKNOWN_CODE"
    assert err.numeric() == "OW-A-026"
    assert err.EXIT == 2, "`ow explain` exits 2 on an unknown code"
    assert err.fix
    message = str(err)
    assert "OW-A-999 is not in codes.toml" in message
    assert message.count("OW-A-0") >= 3, "the nearest three"


def test_explain_lists_the_nearest_symbols_when_given_a_symbol() -> None:
    with pytest.raises(NotFoundError) as caught:
        explain("OW_PARSE_GAP_IN_SCOP")
    assert "OW_PARSE_GAP_IN_SCOPE" in str(caught.value), "one edit away, so it ranks first"


def test_explain_ignores_surrounding_whitespace_and_case() -> None:
    assert explain("  ow-a-013  ") == explain("OW-A-013")


# ---------------------------------------------------------------------------
# check_register catches the collision that reading missed twice
# ---------------------------------------------------------------------------


def test_the_collision_check_catches_a_duplicated_numeric(tmp_path: Path) -> None:
    """One numeric binds to exactly one condition. This is the failure that survived three
    verification passes (18-api-sketch.md section 9 item 7)."""
    path = _fixture_register(
        tmp_path,
        """
[[code]]
numeric = "OW-A-023"
symbol  = "OW_BAD_SCOPE_FORM"

[[code]]
numeric = "OW-A-023"
symbol  = "OW_SERVE_COPYLEFT_NETWORK"
""",
    )
    failures = check_register(path)
    assert any("OW-A-023 binds 2 symbols" in line for line in failures), failures
    assert any(
        "OW_BAD_SCOPE_FORM" in line and "OW_SERVE_COPYLEFT_NETWORK" in line for line in failures
    ), "the report names every binding, so the fix is a sed"


def test_the_collision_check_catches_a_symbol_on_two_numerics(tmp_path: Path) -> None:
    """Both directions: a symbol that drifted onto a second numeric is the same build failure
    seen from the other end. This is the real `OW-A-041` history."""
    path = _fixture_register(
        tmp_path,
        """
[[code]]
numeric = "OW-A-041"
symbol  = "OW_HTTP_ORIGIN_REJECTED"

[[code]]
numeric = "OW-A-045"
symbol  = "OW_HTTP_ORIGIN_REJECTED"
""",
    )
    failures = check_register(path)
    assert any("OW_HTTP_ORIGIN_REJECTED binds 2 numerics" in line for line in failures), failures


def test_the_collision_check_catches_a_malformed_token(tmp_path: Path) -> None:
    path = _fixture_register(
        tmp_path,
        """
[[code]]
numeric = "OW-A-13"
symbol  = "ow_lower_case"
""",
    )
    failures = check_register(path)
    assert any("not shaped OW-<AREA>-nnn" in line for line in failures), failures
    assert any("not shaped OW_SCREAMING_SNAKE" in line for line in failures), failures


def test_the_collision_check_catches_an_undeclared_area_letter(tmp_path: Path) -> None:
    """A new area letter is a charter amendment, not a row (02-architecture.md section 7.2)."""
    path = _fixture_register(
        tmp_path,
        """
[[code]]
numeric = "OW-Z-001"
symbol  = "OW_INVENTED_AREA"
""",
    )
    assert any("has no table" in line for line in check_register(path)), check_register(path)


def test_the_collision_check_catches_an_area_that_names_the_wrong_class(tmp_path: Path) -> None:
    path = tmp_path / "codes.toml"
    path.write_text('[area.C]\nerror_class = "ConfigurationError"\n', encoding="utf-8")
    failures = check_register(path)
    assert any("declares error_class 'ConfigurationError'" in line for line in failures), failures
    assert any("[area.M] is missing" in line for line in failures), "all ten, or it is not ten"


def test_a_clean_fixture_register_reports_nothing(tmp_path: Path) -> None:
    path = _fixture_register(
        tmp_path,
        """
[[code]]
numeric = "OW-A-001"
symbol  = "OW_NO_CORPUS_CONFIGURED"
meaning = "no corpus configured"
fix     = "ow init"
sites   = ["18-api-sketch.md:166"]
""",
    )
    assert check_register(path) == ()
    row = load_register(path).by_symbol["OW_NO_CORPUS_CONFIGURED"]
    assert row == CodeRow(
        "OW-A-001", "OW_NO_CORPUS_CONFIGURED", "no corpus configured", "ow init", "18-api-sketch.md"
    )


# ---------------------------------------------------------------------------
# Package-data discipline (11-repo-layout.md section 2.6)
# ---------------------------------------------------------------------------


def test_an_unparseable_register_raises_a_named_owerror_with_a_fix(tmp_path: Path) -> None:
    """Rule 3: never a KeyError, a FileNotFoundError or a silent empty default."""
    broken = tmp_path / "codes.toml"
    broken.write_text("this is not = = toml\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_register(broken)
    assert caught.value.fix, "the command that clears it"
    with pytest.raises(ConfigError):
        load_register(tmp_path / "absent" / "codes.toml")


def test_the_register_is_read_at_use_time_and_memoised() -> None:
    """Rule 2: a missing or corrupt packaged file must degrade one operation, not brick import.

    A reloaded module holds nothing until something asks, and two asks share one read -- so
    `ow explain` costs one parse per process rather than one per call, and a corrupt register
    cannot fail `ow --version`.
    """
    importlib.reload(errors)
    assert errors._load_register.cache_info().currsize == 0, "the register was read at import"
    first = errors.load_register()
    assert errors._load_register.cache_info().currsize == 1
    assert errors.load_register() is first, "read once, memoised"
