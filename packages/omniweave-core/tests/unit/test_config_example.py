"""`omniweave.toml.example`: the root artefact G18's coverage assertion is stated over.

11-repo-layout.md section 1.1 commits this file at the repository root, and its line 46 states
what CI does with it: `tomllib.loads` it, hold every inline table to one physical line (a2), and
lint any routing-rule fence through `ow route lint` (a3). ADR-3's Consequences ("What becomes
harder") names the price this file now carries: "adding a config key now costs a pattern AND a
line in `omniweave.toml.example` -- G18's 'exactly' clause is bidirectional and this ADR makes
both directions enforceable for the first time."

Three deliberate choices about HOW this module asserts:

  * The coverage rule has ONE home. `gate_config_axes.check_coverage` is called here rather than
    re-derived, and it in turn imports the matcher from `omniweave_core.config` -- INV-21, "one
    name, one type, one home", whose 01-principles.md:1210 row names "one config key to two
    homes" as the G18-adjacent failure it forbids. A test
    that re-implemented glob arity could pass while the gate failed, which would make it a test
    of a different property than CI enforces.
  * The rows are read from the COMMITTED `tools/config_axes.toml`, not from `KEYS`. Evaluating
    coverage against the registry would make the byte diff and the coverage check one check and
    leave the committed file itself unasserted -- `AxisRow`'s own docstring says so.
  * The file must RESOLVE, not merely parse. `config.load(explicit=...)` is the stronger
    statement, and it is the one that catches an instance stanza missing a key declared REQUIRED
    (`_instantiate_sections` raises `OW_CONFIG_MISSING_KEY` there, and `tomllib` never would).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest
from omniweave_core.config import (
    KEYS,
    REQUIRED,
    ConfigLayer,
    Inherit,
    coerce,
    flatten,
    load,
    resolve_key,
)

REPO = Path(__file__).resolve().parents[4]
EXAMPLE = REPO / "omniweave.toml.example"
AXES = REPO / "tools" / "config_axes.toml"

# `tools/` is a script directory and not a distribution, so it is not importable by installation.
# Prepending it is the same act `uv run tools/gate_config_axes.py` performs implicitly through
# `sys.path[0]`, and it is the sibling suite's precedent (test_config_axes.py).
sys.path.insert(0, str(REPO / "tools"))

import gate_config_axes  # noqa: E402

# The 127 declared patterns instantiate to 127 keys in this file: every glob is given exactly one
# instance, and `[corpora.contracts]` is a COMMENTED illustration rather than a second live
# instance (see `test_the_example_declares_one_instance_per_glob`). Pinned as a number because a
# key added to the registry without a line here, or a line here deleted, must fail LOUDLY rather
# than change a count nobody reads.
EXPECTED_KEYS = 127

# The one key in the example whose value is NOT its declared default, and the locus that puts it
# there. 04-driver-system.md:2779 names this exact stanza as the shipped example's own -- "which
# the charter's own `omniweave.toml` uses: `[drivers."parse.pdf.pdfium"] config = { dpi = 192 }`"
# -- while 18-api-sketch.md section 4 gives an unconfigured driver's table the default `{}`. The
# two are not in conflict: `{}` is what a driver nobody configured resolves to, and this file has
# to instantiate `drivers.*.config` with something or the pattern is dead.
PLAN_PRINTED_INSTANCE: dict[str, object] = {'drivers."parse.pdf.pdfium".config': {"dpi": 192}}

# The four patterns declared with NO default. No default can invent an instance name, so each is
# a value this file chooses; each choice is cited in the example's own comments.
NO_DEFAULT = frozenset(
    {
        "corpora.*.path",
        "drivers.resolve.*",
        "services.*.model_id",
        "services.*.model_revision",
    }
)


def _text() -> str:
    return EXAMPLE.read_text(encoding="utf-8")


def _document() -> dict[str, object]:
    return tomllib.loads(_text())


def _table(*path: str) -> dict[str, object]:
    """One table of the parsed example, by segment path, refusing anything that is not a table.

    Written as a helper because `tomllib` hands back `dict[str, Any]` and a test that indexed into
    it inline would be asserting over `object` -- the `isinstance` is the assertion, not noise.
    """
    node: object = _document()
    for segment in path:
        assert isinstance(node, dict), path
        node = node[segment]
    assert isinstance(node, dict), path
    return node


def _rows() -> tuple[gate_config_axes.AxisRow, ...]:
    """The patterns as the COMMITTED axis file declares them, malformed rows refused loudly."""
    rows, findings = gate_config_axes.read_rows(AXES.read_text(encoding="utf-8"))
    assert findings == (), [f.render() for f in findings]
    return rows


def _keys() -> tuple[str, ...]:
    keys, findings = gate_config_axes.enumerate_keys(_document(), _rows())
    assert findings == (), [f.render() for f in findings]
    return keys


# ---------------------------------------------------------------------------------------------
# The artefact itself
# ---------------------------------------------------------------------------------------------


def test_the_example_is_committed_at_the_repository_root() -> None:
    """11-repo-layout.md section 1.1's tree puts it beside `pyproject.toml` and `codes.toml`.

    Asserted as a path rather than through the gate because the gate's own answer when the file is
    absent is `example-not-committed` -- a named failure, not a crash -- so a suite that only ever
    called the gate could not tell "committed and correct" from "the gate declined to evaluate".
    """
    assert EXAMPLE.is_file(), f"{EXAMPLE} is 11-repo-layout.md section 1.1's committed artefact"


def test_the_example_parses_under_tomllib() -> None:
    """11-repo-layout.md:46: CI `tomllib.loads` this file. G27a reads it in the same corpus."""
    assert isinstance(_document(), dict)


def test_every_inline_table_is_on_one_physical_line() -> None:
    """11-repo-layout.md:46 (a2). A multi-line inline table is illegal TOML outright, so this
    asserts the shape a reader would otherwise reach for -- `[cache.max_bytes]` is a SUB-TABLE for
    exactly this reason, and the file says so at the point of use."""
    unbalanced = [
        (number, line)
        for number, line in enumerate(_text().split("\n"), start=1)
        if line.count("{") != line.count("}")
    ]
    assert unbalanced == [], f"an inline table spans a newline: {unbalanced}"


def test_the_example_ships_no_routing_rule_table() -> None:
    """11-repo-layout.md:46 (a3) lints a rule fence through `ow route lint`; there is none here.

    Two reasons, and the second is the load-bearing one: a routing policy's one home is
    `.omniweave/policy.d/*.toml` (18-api-sketch.md section 4), and a `rule` table in this file
    would be a key no axis pattern matches -- G18's `unclassified-key`.
    """
    assert "rule" not in _document()


def test_the_example_is_lf_ascii_with_one_trailing_newline() -> None:
    """11-repo-layout.md section 1.9: the eol contract is what makes a byte-diff gate portable.

    `.gitattributes` declares `* text=auto eol=lf`, so a CRLF in the working tree here would be a
    checkout that defeats it. ASCII-only because a TOML value is read by tools that are not this
    one, and the house rule keeps the values transportable.
    """
    raw = EXAMPLE.read_bytes()
    assert b"\r\n" not in raw
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw.decode("ascii")


# ---------------------------------------------------------------------------------------------
# G18: the exact-coverage assertion, in both directions, through the gate's own function
# ---------------------------------------------------------------------------------------------


def test_the_axis_union_covers_the_example_exactly() -> None:
    """THE assertion: "the union of the two axis lists covers every key in
    `omniweave.toml.example` EXACTLY -- neither over nor under" (02-architecture.md section 8.3).

    `check_coverage` reports all three of section 8.3's conditions in one pass -- a key no pattern
    matches, a key two globs match, and a pattern no key matches -- so this single call is the
    whole bidirectional statement rather than the "under" half of it.
    """
    findings = gate_config_axes.check_coverage(_document(), _rows())
    assert findings == (), "\n".join(f.render() for f in findings)


def test_exactly_one_pattern_matches_each_key() -> None:
    """ "...with exactly one matching pattern per key" (12-performance.md:1678's G18 row).

    Stronger than `check_coverage`, which reports two matches only when BOTH are globs -- an
    explicit key lawfully beats a glob at runtime (`resolve_key`). This file needs no such
    precedence: no key in it is matched twice at all, which is the state that cannot rot.
    """
    rows = _rows()
    ambiguous = {
        key: [row.name for row in rows if row.matches(key)]
        for key in _keys()
        if sum(1 for row in rows if row.matches(key)) != 1
    }
    assert ambiguous == {}


def test_the_example_instantiates_every_declared_pattern_once() -> None:
    """127 patterns, 127 keys. A count, so a silent drift in either direction fails here too."""
    assert len(_rows()) == EXPECTED_KEYS
    assert len(_keys()) == EXPECTED_KEYS


def test_every_key_in_the_example_is_a_declared_key() -> None:
    """`resolve_key` is the loader's own answer to "is this key declared", and an undeclared key
    raises `OW_CONFIG_UNKNOWN_KEY` there rather than being silently ignored (section 8.2). The
    governing declaration is asserted to be a member of `KEYS` by identity, so a pattern read out
    of the committed axis file cannot stand in for a declaration that no longer exists."""
    for key in _keys():
        spec = resolve_key(key)
        assert KEYS[spec.name] is spec, key


def test_the_gate_enumerator_and_the_loader_agree_on_the_leaves() -> None:
    """Two independent implementations of ADR-3 decision 3's enumeration rule, one file.

    `gate_config_axes.enumerate_keys` walks the document against the committed PATTERNS;
    `config.flatten` walks it against the DECLARATIONS. They must agree, because a file where they
    disagreed would be a file whose digest covered a different key set than CI checked.
    """
    assert set(flatten(_document())) == set(_keys())


# ---------------------------------------------------------------------------------------------
# The values: the shipped defaults written out, not numbers that merely parse
# ---------------------------------------------------------------------------------------------


def test_every_value_round_trips_through_its_declared_coercion_to_its_default() -> None:
    """The file is "the shipped defaults", so every value must equal the value zero configuration
    would have produced -- through the DECLARED coercion, because `coerce` is what turns a TOML
    list into the tuple a default is written as (02-architecture.md section 8.4).

    Three shapes have no literal default to compare against, and each is checked by its own test
    below rather than skipped as a class: `REQUIRED`, `Inherit`, and the one glob instance the
    plan prints a concrete value for.
    """
    flat = flatten(_document())
    mismatched: dict[str, tuple[object, object]] = {}
    for key, raw in flat.items():
        spec = resolve_key(key)
        value = coerce(spec, raw, key=key)
        if spec.default is REQUIRED or isinstance(spec.default, Inherit):
            continue
        if key in PLAN_PRINTED_INSTANCE:
            continue
        if value != spec.default:
            mismatched[key] = (value, spec.default)
    assert mismatched == {}


def test_the_four_patterns_with_no_default_are_live_values_and_not_comments() -> None:
    """A commented illustration cannot satisfy G18: `tomllib` does not see it, so the pattern is
    dead. These four are declared `REQUIRED` -- no default can invent an instance name -- so each
    is a value this file chooses, and each choice is cited where it appears."""
    assert {name for name in NO_DEFAULT if KEYS[name].default is REQUIRED} == NO_DEFAULT
    rows = {row.name: row for row in _rows()}
    keys = _keys()
    for name in NO_DEFAULT:
        assert any(rows[name].matches(key) for key in keys), name


def test_the_inherited_default_is_the_value_it_inherits() -> None:
    """`corpora.*.source` is declared `Inherit("roots.source")` -- 18-api-sketch.md section 4
    prints that cell as `roots.source` rather than a literal. Writing the inherited value out is
    what keeps the line a default rather than a new number, so the two must be equal."""
    spec = KEYS["corpora.*.source"]
    assert isinstance(spec.default, Inherit)
    flat = flatten(_document())
    inherited_from = flat[spec.default.from_key]
    written = [value for key, value in flat.items() if spec.matches(key)]
    assert written, "corpora.*.source is a pattern with no key in the example"
    assert all(value == inherited_from for value in written)


def test_the_one_non_default_value_is_the_stanza_the_plan_prints() -> None:
    """`drivers.*.config` must be instantiated or the pattern is dead, and its declared default is
    the empty table -- which would illustrate nothing. 04-driver-system.md:2779 prints
    `[drivers."parse.pdf.pdfium"] config = { dpi = 192 }` as the shipped example's own stanza, so
    that is the value here. Asserted with the default beside it, so the divergence is a decision a
    reader can see rather than a value that drifted."""
    assert KEYS["drivers.*.config"].default == {}
    flat = flatten(_document())
    for key, expected in PLAN_PRINTED_INSTANCE.items():
        assert coerce(resolve_key(key), flat[key], key=key) == expected


def test_the_example_declares_one_instance_per_glob() -> None:
    """One instance per glob pattern, named for a reason the file states.

    `handbook` is `[serve] default_corpus`' shipped value and default_corpus MUST name a
    `[corpora]` entry; `vlm` is the Service name 08-runtime.md:2615 and 15-observability.md:1656
    both print; `parse.pdf.pdfium` and `parse.office.anydoc` are ADR-3's own two. A SECOND corpus
    is deliberately commented out: coverage needs one instance, and an entry naming a sibling
    checkout that does not exist would be an edit before the first `ow query` -- R-A8's first
    trigger (17-risks.md:272).
    """
    assert _table("corpora").keys() == {"handbook"}
    assert _table("services").keys() == {"vlm"}
    assert _table("drivers", "resolve").keys() == {"parse.office.anydoc"}
    drivers = _table("drivers")
    configured = [name for name, value in drivers.items() if isinstance(value, dict)]
    assert [name for name in configured if "config" in _table("drivers", name)] == [
        "parse.pdf.pdfium"
    ]


# ---------------------------------------------------------------------------------------------
# The file resolves, which is a stronger statement than "it parses"
# ---------------------------------------------------------------------------------------------


def test_the_example_resolves_through_the_loader_with_nothing_left_to_a_default(
    tmp_path: Path,
) -> None:
    """Every resolved value's source is THIS FILE, and there are exactly 127 of them.

    That is the coverage assertion restated from the loader's side, and it is bidirectional for
    the same reason: a key this file omitted would resolve from `ConfigLayer.BUILTIN` instead, and
    a key it declared twice or under a name no glob instantiates would not resolve at all.
    `_instantiate_sections` is the half `tomllib` cannot reach -- a `[services.<name>]` stanza
    missing `model_id` raises `OW_CONFIG_MISSING_KEY` here and parses fine there.
    """
    config = load(cwd=tmp_path, env={}, explicit=EXAMPLE)
    assert len(config.values) == EXPECTED_KEYS
    assert {source.layer for source in config.sources.values()} == {ConfigLayer.EXPLICIT_FILE}
    assert len(config.config_digest) == 64
    assert len(config.semantic_digest) == 64


def test_the_gate_passes_over_the_committed_example(capsys: pytest.CaptureFixture[str]) -> None:
    """G18's exit code over the committed pair, which is the acceptance criterion ADR-3
    consequence 3 states. Run through `main` rather than `check` so the byte diff, the twin
    register and the coverage assertion are all in the one answer CI reads."""
    assert gate_config_axes.main([]) == 0
    assert "G18 ok" in capsys.readouterr().out
