"""Property tests for `omniweave_core.config`.

Covers what 13-quality.md section 2 and 02-architecture.md sections 8.1-8.4 make checkable: the
ten-kind coercion table round-trips, the six-rung precedence chain resolves in layer order,
`source_of` is correct for a value set at each rung, the `OMNIWEAVE_*` twin derives both ways, the
shipped configuration loads, a two-glob collision raises (G18), and a key with no axis cannot be
constructed.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import math
import subprocess  # noqa: TID251 -- a fresh interpreter is the only honest witness for G17.
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest
from omniweave_core.config import (
    CONFIG_AXES,
    CONFIG_KINDS,
    CONFIG_SCHEMA,
    ENV_PREFIX,
    KEYS,
    NON_KEY_ENV_VARS,
    REQUIRED,
    SHIPPED_DRIVERS,
    Config,
    ConfigError,
    ConfigKey,
    ConfigLayer,
    ConfigSource,
    Inherit,
    coerce,
    default_env_name,
    env_name_of,
    flatten,
    join_key,
    key_of_env_name,
    load,
    resolve_key,
    scan_lines,
    split_key,
)

FIXTURES = Path(__file__).parent
SHIPPED = FIXTURES / "shipped_config_example.toml"

CONCRETE = tuple(
    spec for spec in KEYS.values() if not isinstance(spec.default, (type(REQUIRED), Inherit))
)


def _raw(value: object) -> object:
    """A declared default rendered back into the shape tomllib would hand the loader."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, tuple):
        return [_raw(v) for v in value]
    return value


def _env_text(spec: ConfigKey, value: object) -> str:
    """The same default rendered into its `OMNIWEAVE_*` string form."""
    match spec.kind:
        case "bool":
            return "true" if value else "false"
        case "int":
            return str(value)
        case "float":
            return repr(value)
        case "str" | "path" | "enum":
            assert isinstance(value, str)
            return value
        case "str_or_list":
            return value if isinstance(value, str) else json.dumps(_raw(value))
        case _:
            return json.dumps(_raw(value))


# ---------------------------------------------------------------------------------------------
# The axis: required, with no default (02-architecture.md section 8.4 decision (a))
# ---------------------------------------------------------------------------------------------


def test_every_declared_key_carries_an_axis() -> None:
    assert KEYS, "the registry is not empty"
    for name, spec in KEYS.items():
        assert spec.axis in CONFIG_AXES, name


def test_axis_has_no_default_on_the_dataclass() -> None:
    axis = {f.name: f for f in dataclasses.fields(ConfigKey)}["axis"]
    assert axis.default is dataclasses.MISSING
    assert axis.default_factory is dataclasses.MISSING


def test_a_key_with_no_axis_cannot_be_constructed() -> None:
    with pytest.raises(TypeError):
        ConfigKey(name="x.y", kind="int", default=1, env="OMNIWEAVE_X_Y")  # type: ignore[call-arg]


def test_a_key_with_an_unclassified_axis_is_rejected() -> None:
    with pytest.raises(TypeError, match="axis must be"):
        ConfigKey(name="x.y", kind="int", default=1, axis="", env="OMNIWEAVE_X_Y")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="axis must be"):
        ConfigKey(name="x.y", kind="int", default=1, axis="maybe", env="OMNIWEAVE_X_Y")  # type: ignore[arg-type]


def test_the_semantic_keys_are_the_charter_axis_list() -> None:
    """charter.md's `tools/config_axes.toml` `[semantic]` block, one pattern per line."""
    semantic = {name for name, spec in KEYS.items() if spec.axis == "semantic"}
    assert semantic == {
        "limits.max_entry_bytes",
        "cache.recipe",
        "drivers.*.config",
        "targets.video.ffmpeg",
        "targets.video.codec",
        "graph.etypes",
        "graph.segment_target_tokens",
        "graph.llm_coverage_floor",
        "graph.max_items_per_segment",
        "services.*.model_id",
        "services.*.model_revision",
        "retrieval.vec.model_key",
        "store.retain_parts",
    }


# ---------------------------------------------------------------------------------------------
# Coercion: ten kinds, every one exercised, and no `str()` fallback (I12)
# ---------------------------------------------------------------------------------------------


def test_all_ten_config_kinds_are_declared_by_some_key() -> None:
    declared = {spec.kind for spec in KEYS.values()}
    assert declared == set(CONFIG_KINDS)


@pytest.mark.parametrize("spec", CONCRETE, ids=lambda s: s.name)
def test_every_default_round_trips_through_its_coercer(spec: ConfigKey) -> None:
    assert coerce(spec, _raw(spec.default)) == spec.default


@pytest.mark.parametrize("spec", CONCRETE, ids=lambda s: s.name)
def test_every_default_round_trips_through_its_env_twin(spec: ConfigKey) -> None:
    from omniweave_core.config import _from_env_text

    text = _env_text(spec, spec.default)
    assert _from_env_text(spec, text, key=spec.name, var=spec.env) == spec.default


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("runtime.plan_batch", "512"),  # a str is never an int
        ("runtime.plan_batch", 1.5),  # a float is never an int
        ("runtime.plan_batch", True),  # a bool is never an int
        ("store.bulk_windows", 1),  # an int is never a bool
        ("serve.tool_prefix", 3),  # an int is never a str
        ("retrieval.weights.exact", "1.2"),  # a str is never a float
        ("retrieval.weights.exact", float("nan")),  # allow_nan=False
        ("retrieval.weights.exact", float("inf")),
        ("drivers.enabled", "parse.pdf.pdfium"),  # a str is never a list
        ("drivers.max_workers", [1, 2]),  # a list is never a table
        ("store.backend", "duckdb"),  # not one of the choices
        ("observe.sinks", ["console", "smoke"]),  # not one of the item choices
    ],
)
def test_no_str_fallback_exists_to_reach(key: str, bad: object) -> None:
    with pytest.raises(ConfigError):
        coerce(resolve_key(key), bad, key=key)


def test_a_path_leaf_is_a_normalised_string_not_a_Path() -> None:
    value = coerce(resolve_key("roots.output"), ".omniweave\\out")
    assert value == ".omniweave/out"
    assert isinstance(value, str)


def test_a_drivers_own_config_table_is_preserved_verbatim() -> None:
    raw = {"dpi": 192, "mode": "fast", "strict": False, "ratio": 0.5, "unset": None}
    assert coerce(resolve_key('drivers."parse.pdf.pdfium".config'), raw) == raw


def test_the_matrix_shape_is_a_tuple_of_tuples() -> None:
    tier = KEYS["serve.packing.tier"].default
    assert isinstance(tier, tuple)
    assert all(isinstance(row, tuple) for row in tier)
    assert len(tier) == 5


# ---------------------------------------------------------------------------------------------
# The OMNIWEAVE_* twin, derived both ways
# ---------------------------------------------------------------------------------------------


def test_every_twin_is_prefixed_and_unique() -> None:
    seen: dict[str, str] = {}
    for name, spec in KEYS.items():
        assert spec.env.startswith(ENV_PREFIX), name
        assert spec.env not in NON_KEY_ENV_VARS, name
        assert spec.env not in seen, f"{name} and {seen.get(spec.env)} share {spec.env}"
        seen[spec.env] = name


def test_the_twin_derives_both_ways_for_every_literal_key() -> None:
    for name, spec in KEYS.items():
        if spec.is_glob:
            continue
        assert env_name_of(name) == spec.env
        assert key_of_env_name(spec.env) == name


def test_the_twin_derives_both_ways_for_a_glob_instance() -> None:
    assert env_name_of("corpora.handbook.path") == "OMNIWEAVE_CORPORA_HANDBOOK_PATH"
    assert key_of_env_name("OMNIWEAVE_CORPORA_HANDBOOK_PATH") == "corpora.handbook.path"
    assert env_name_of("services.vlm.model_id") == "OMNIWEAVE_SERVICES_VLM_MODEL_ID"
    assert key_of_env_name("OMNIWEAVE_SERVICES_VLM_MODEL_ID") == "services.vlm.model_id"


def test_the_one_twin_no_mechanical_rule_produces_is_declared() -> None:
    """02-architecture.md section 8.2: `[serve] listed` -> `OMNIWEAVE_MCP_LISTED`."""
    assert KEYS["serve.listed"].env == "OMNIWEAVE_MCP_LISTED"
    assert default_env_name("serve.listed") == "OMNIWEAVE_SERVE_LISTED"
    assert key_of_env_name("OMNIWEAVE_SERVE_LISTED") is None
    assert key_of_env_name("OMNIWEAVE_MCP_LISTED") == "serve.listed"


def test_the_four_non_key_env_vars_are_not_twins() -> None:
    for var in NON_KEY_ENV_VARS:
        assert key_of_env_name(var) is None
    assert key_of_env_name("PATH") is None


# ---------------------------------------------------------------------------------------------
# Glob arity: two globs matching one key is a G18 FAILURE, not a precedence puzzle
# ---------------------------------------------------------------------------------------------


def _synthetic(name: str, axis: str = "operational") -> ConfigKey:
    return ConfigKey(
        name=name,
        kind="int",
        default=0,
        axis=axis,  # type: ignore[arg-type]
        env=default_env_name(name),
    )


def test_two_globs_matching_one_key_raises() -> None:
    registry = (_synthetic("a.*.c"), _synthetic("a.b.*"))
    with pytest.raises(ConfigError, match="G18 failure"):
        resolve_key("a.b.c", keys=registry)


def test_an_explicit_key_beats_a_glob() -> None:
    registry = (_synthetic("a.*.c"), _synthetic("a.b.*"), _synthetic("a.b.c"))
    assert resolve_key("a.b.c", keys=registry).name == "a.b.c"


def test_star_matches_exactly_one_segment_and_doublestar_one_or_more() -> None:
    registry = (_synthetic("a.*.c"),)
    assert resolve_key("a.b.c", keys=registry).name == "a.*.c"
    with pytest.raises(ConfigError, match="unknown config key"):
        resolve_key("a.b.x.c", keys=registry)
    deep = (_synthetic("a.**"),)
    assert resolve_key("a.b.x.c", keys=deep).name == "a.**"
    with pytest.raises(ConfigError, match="unknown config key"):
        resolve_key("a", keys=deep)


def test_the_shipped_registry_has_exactly_one_reachable_two_glob_state() -> None:
    """ADR-3 decision 3's `drivers.resolve.*` overlaps the pre-existing `drivers.*.config`.

    Only on the key `drivers.resolve.config`, which needs a single-segment driver id spelled
    `resolve`; every real id is dotted. Reported as a deviation -- the assertion pins it so a
    later widening of either pattern fails here rather than in G18.
    """
    with pytest.raises(ConfigError, match="G18 failure"):
        resolve_key("drivers.resolve.config")


def test_no_two_declared_globs_collide_on_any_shipped_key() -> None:
    document = SHIPPED.read_text(encoding="utf-8")
    for key in scan_lines(document):
        resolve_key(key)  # raises on a two-glob state or an unknown key


# ---------------------------------------------------------------------------------------------
# Dotted keys and the raw line scan
# ---------------------------------------------------------------------------------------------


def test_a_quoted_segment_holding_dots_is_one_segment() -> None:
    assert split_key('drivers."parse.pdf.pdfium".config') == (
        "drivers",
        "parse.pdf.pdfium",
        "config",
    )
    assert (
        join_key(("drivers", "parse.pdf.pdfium", "config")) == 'drivers."parse.pdf.pdfium".config'
    )
    assert resolve_key('drivers."parse.pdf.pdfium".config').name == "drivers.*.config"


def test_the_line_scan_records_the_line_each_key_was_written_on() -> None:
    text = "\n".join(
        [
            "schema = 1",
            "",
            "[roots]  # a comment with an = sign",
            'source = "."',
            "",
            "[serve.packing]",
            "tier = [[1, 2],",
            "        [3, 4]]",
            "min_chars = 600",
        ]
    )
    lines = scan_lines(text)
    assert lines["schema"] == 1
    assert lines["roots.source"] == 4
    assert lines["serve.packing.tier"] == 7
    assert lines["serve.packing.min_chars"] == 9


def test_an_inline_table_is_one_key_and_a_subtable_is_not() -> None:
    """ADR-3 decision 3's key-enumeration rule, made decidable by the registry."""
    document = {
        "drivers": {"max_workers": {"free": 1, "local_compute": 2, "billed_api": 3}},
        "cache": {"max_bytes": {"blob": 1, "render": 2}},
    }
    flat = flatten(document)
    assert set(flat) == {"drivers.max_workers", "cache.max_bytes.blob", "cache.max_bytes.render"}


def test_an_unknown_key_is_a_startup_error_naming_the_nearest_known_one() -> None:
    with pytest.raises(ConfigError, match=r"did you mean roots\.source"):
        flatten({"roots": {"sources": "."}})


# ---------------------------------------------------------------------------------------------
# The precedence chain and source_of
# ---------------------------------------------------------------------------------------------


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


def test_the_precedence_chain_resolves_in_layer_order(tmp_path: Path) -> None:
    """Five of the six rungs at once; PYPROJECT is exercised separately because rung 3 applies
    ONLY when no `omniweave.toml` was found (02-architecture.md section 8.1)."""
    root = _project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.toml").write_text(
        "\n".join(
            [
                "[store]",
                "wal_heal_mb = 11",  # only here      -> USER_FILE
                "wal_valve_mb = 11",
                "[serve]",
                "tool_prefix = 'user_'",
                "[runtime]",
                "plan_batch = 11",
            ]
        ),
        encoding="utf-8",
    )
    (root / "omniweave.toml").write_text(
        "\n".join(
            [
                "[store]",
                "wal_valve_mb = 33",  # beats USER_FILE -> PROJECT_FILE
                "[serve]",
                "tool_prefix = 'project_'",
                "[runtime]",
                "plan_batch = 33",
            ]
        ),
        encoding="utf-8",
    )
    explicit = tmp_path / "explicit.toml"
    explicit.write_text(
        "[serve]\ntool_prefix = 'explicit_'\n[runtime]\nplan_batch = 44\n", encoding="utf-8"
    )
    env = {"OMNIWEAVE_HOME": str(home), "OMNIWEAVE_RUNTIME_PLAN_BATCH": "55"}

    cfg = load(cwd=root, env=env, explicit=explicit)

    assert cfg.get("runtime.lease_ms") == 120000  # 0 BUILTIN
    assert cfg.get("store.wal_heal_mb") == 11  # 1 USER_FILE
    assert cfg.get("store.wal_valve_mb") == 33  # 3 PROJECT_FILE
    assert cfg.get("serve.tool_prefix") == "explicit_"  # 4 EXPLICIT_FILE
    assert cfg.get("runtime.plan_batch") == 55  # 5 ENV, over every file

    assert cfg.source_of("runtime.lease_ms").layer is ConfigLayer.BUILTIN
    assert cfg.source_of("store.wal_heal_mb").layer is ConfigLayer.USER_FILE
    assert cfg.source_of("store.wal_valve_mb").layer is ConfigLayer.PROJECT_FILE
    assert cfg.source_of("serve.tool_prefix").layer is ConfigLayer.EXPLICIT_FILE
    assert cfg.source_of("runtime.plan_batch").layer is ConfigLayer.ENV

    assert cfg.source_of("runtime.lease_ms").render() == "(built-in)"
    assert cfg.source_of("runtime.plan_batch").render() == "OMNIWEAVE_RUNTIME_PLAN_BATCH"
    assert (
        cfg.source_of("store.wal_valve_mb").render() == f"{(root / 'omniweave.toml').as_posix()}:2"
    )
    # `[store]` is line 1 of the user file and `wal_heal_mb` is line 2 -- the same shape the
    # PROJECT_FILE assertion above checks with `:2`.
    assert cfg.source_of("store.wal_heal_mb").line == 2


def test_pyproject_applies_only_when_no_omniweave_toml_was_found(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'x'\n[tool.omniweave.runtime]\nplan_batch = 22\n", encoding="utf-8"
    )
    cfg = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    assert cfg.get("runtime.plan_batch") == 22  # 2 PYPROJECT
    assert cfg.source_of("runtime.plan_batch").layer is ConfigLayer.PYPROJECT
    assert cfg.source_of("runtime.plan_batch").line == 4

    (root / "omniweave.toml").write_text("[runtime]\nplan_batch = 33\n", encoding="utf-8")
    beaten = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    assert beaten.get("runtime.plan_batch") == 33
    assert beaten.source_of("runtime.plan_batch").layer is ConfigLayer.PROJECT_FILE


def test_every_layer_of_the_enum_is_reachable_and_ordered() -> None:
    assert [layer.value for layer in ConfigLayer] == [0, 1, 2, 3, 4, 5]
    assert ConfigLayer.BUILTIN < ConfigLayer.USER_FILE < ConfigLayer.PYPROJECT
    assert ConfigLayer.PYPROJECT < ConfigLayer.PROJECT_FILE < ConfigLayer.EXPLICIT_FILE
    assert ConfigLayer.EXPLICIT_FILE < ConfigLayer.ENV


def test_the_project_file_search_walks_up_and_stops_at_git(tmp_path: Path) -> None:
    root = _project(tmp_path)
    deep = root / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (root / "omniweave.toml").write_text("[runtime]\nplan_batch = 77\n", encoding="utf-8")
    cfg = load(cwd=deep, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    assert cfg.get("runtime.plan_batch") == 77

    # A file ABOVE the .git boundary is not reached.
    (tmp_path / "omniweave.toml").write_text("[runtime]\nplan_batch = 88\n", encoding="utf-8")
    (root / "omniweave.toml").unlink()
    stopped = load(cwd=deep, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    assert stopped.get("runtime.plan_batch") == 512
    assert stopped.source_of("runtime.plan_batch").layer is ConfigLayer.BUILTIN


def test_an_env_twin_cannot_invent_a_corpus(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "omniweave.toml").write_text(
        "[corpora.handbook]\npath = '.omniweave/index.owstore'\n", encoding="utf-8"
    )
    env = {
        "OMNIWEAVE_HOME": str(tmp_path / "absent"),
        "OMNIWEAVE_CORPORA_HANDBOOK_PATH": "elsewhere/index.owstore",
        "OMNIWEAVE_CORPORA_GHOST_PATH": "never/index.owstore",
    }
    cfg = load(cwd=root, env=env)
    assert cfg.get("corpora.handbook.path") == "elsewhere/index.owstore"
    assert cfg.source_of("corpora.handbook.path").layer is ConfigLayer.ENV
    assert "corpora.ghost.path" not in cfg.values


# ---------------------------------------------------------------------------------------------
# The resolved object
# ---------------------------------------------------------------------------------------------


def _load_shipped(tmp_path: Path) -> Config:
    root = _project(tmp_path)
    (root / "omniweave.toml").write_text(SHIPPED.read_text(encoding="utf-8"), encoding="utf-8")
    return load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})


def _override(text: str, table: str, key: str, literal: str) -> str:
    """Return `text` with `[table] key` set to `literal`, substituted in place.

    A mutation test cannot APPEND `[table]\\nkey = v` to a document that already declares
    `[table]` -- TOML forbids declaring a table twice, and every table these tests mutate is
    already present in the shipped example. So the value is replaced where it stands, which is
    also what an operator editing the file would do.
    """

    def code(line: str) -> str:
        """The line without its trailing comment. The shipped example puts a comment after most
        table headers and many values, so a naive `endswith(']')` never sees `[roots]`."""
        cut = len(line)
        quote: str | None = None
        for i, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == "#":
                cut = i
                break
        return line[:cut].strip()

    out: list[str] = []
    in_table = False
    replaced = False
    skip_until_balanced = 0
    for line in text.splitlines():
        c = code(line)
        if skip_until_balanced:  # inside a multi-line value we are replacing
            skip_until_balanced += c.count("[") + c.count("{") - c.count("]") - c.count("}")
            continue
        if c.startswith("[") and c.endswith("]") and "=" not in c:
            if in_table and not replaced:  # the table ended without declaring the key
                out.append(f"{key} = {literal}")
                replaced = True
            in_table = c == f"[{table}]"
        elif in_table and not replaced and "=" in c and c.split("=", 1)[0].strip() == key:
            out.append(f"{key} = {literal}")
            replaced = True
            # A value may run over several lines (`enabled = [` ... `]`); drop the rest of it.
            rest = c.split("=", 1)[1]
            skip_until_balanced = (
                rest.count("[") + rest.count("{") - rest.count("]") - rest.count("}")
            )
            continue
        out.append(line)
    if not replaced:
        declared = any(code(row) == f"[{table}]" for row in text.splitlines())
        if not declared:
            out.append(f"[{table}]")
        out.append(f"{key} = {literal}")
    return "\n".join(out) + "\n"


def test_the_shipped_example_is_valid_toml_and_loads(tmp_path: Path) -> None:
    cfg = _load_shipped(tmp_path)
    assert cfg.get("schema") == CONFIG_SCHEMA
    assert cfg.get("serve.default_corpus") == "handbook"
    assert cfg.get("store.retain_parts") == "when_citable"
    assert cfg.get("retrieval.vec.max_segments") == 250000
    assert cfg.get("serve.packing.tier") == KEYS["serve.packing.tier"].default


def test_the_shipped_drivers_enabled_is_thirteen_ids(tmp_path: Path) -> None:
    """ADR-3 decision 1 -- the list `ow doctor` checks a named driver against."""
    cfg = _load_shipped(tmp_path)
    enabled = cfg.get("drivers.enabled")
    assert isinstance(enabled, tuple)
    assert len(enabled) == 13
    assert set(enabled) == set(SHIPPED_DRIVERS)
    assert set(cfg.get("graph.passes.enable")) <= set(enabled)
    assert cfg.axis_of("drivers.enabled") == "operational"


def test_ow_doctor_can_reach_its_three_inputs(tmp_path: Path) -> None:
    """ADR-3 decision 2 scopes the activation check to policy, graph passes and targets."""
    cfg = _load_shipped(tmp_path)
    assert isinstance(cfg.get("drivers.enabled"), tuple)
    assert isinstance(cfg.get("graph.passes.enable"), tuple)
    assert isinstance(cfg.get("targets.enabled"), tuple)
    assert cfg.subkeys("corpora") == ("contracts", "handbook")
    assert cfg.subkeys("services") == ("vlm",)
    assert cfg.driver_config("parse.pdf.pdfium") == {"dpi": 192}
    assert cfg.driver_config("parse.office.anydoc") == {}


def test_a_corpus_source_inherits_roots_source_and_keeps_its_origin(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "omniweave.toml").write_text(
        "[roots]\nsource = 'docs'\n[corpora.handbook]\npath = 'a.owstore'\n", encoding="utf-8"
    )
    cfg = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    assert cfg.get("corpora.handbook.source") == "docs"
    assert cfg.source_of("corpora.handbook.source") == cfg.source_of("roots.source")


def test_a_corpus_with_no_path_is_a_startup_error(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "omniweave.toml").write_text("[corpora.handbook]\nsource = '.'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"corpora\.handbook\.path has no default"):
        load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})


def test_values_and_sources_share_one_key_set(tmp_path: Path) -> None:
    cfg = _load_shipped(tmp_path)
    assert set(cfg.values) == set(cfg.sources)
    for name in cfg.values:
        assert isinstance(cfg.source_of(name), ConfigSource)


def test_get_takes_no_caller_supplied_default(tmp_path: Path) -> None:
    """Section 8.4 decision (b): a mistyped key must not resolve to a caller's fallback."""
    cfg = _load_shipped(tmp_path)
    with pytest.raises(TypeError):
        cfg.get("runtime.plan_batch", 0)  # type: ignore[call-arg]
    with pytest.raises(ConfigError, match="unknown config key"):
        cfg.get("runtime.plan_batches")


def test_the_config_object_has_no_mutator(tmp_path: Path) -> None:
    """Section 8.4 decision (c): no `set`, no `replace`, no `copy(update=...)`."""
    cfg = _load_shipped(tmp_path)
    assert not {"set", "replace", "copy", "update"} & set(dir(cfg))
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.config_digest = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------------------------
# The two digests (02-architecture.md section 8.3)
# ---------------------------------------------------------------------------------------------


def _hex64(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def test_both_digests_are_64_char_hex_and_deterministic(tmp_path: Path) -> None:
    a = _load_shipped(tmp_path)
    b = _load_shipped(tmp_path / "again")
    assert _hex64(a.config_digest) and _hex64(a.semantic_digest)
    assert a.config_digest == b.config_digest
    assert a.semantic_digest == b.semantic_digest
    assert a.config_digest != a.semantic_digest


def test_the_semantic_projection_is_exactly_the_semantic_keys(tmp_path: Path) -> None:
    cfg = _load_shipped(tmp_path)
    projection = cfg.semantic_projection()
    assert set(projection) == {k for k in cfg.values if cfg.axis_of(k) == "semantic"}
    assert projection
    assert set(projection) < set(cfg.values)


@pytest.mark.parametrize(
    ("key", "table", "field", "literal"),
    [
        ("runtime.plan_batch", "runtime", "plan_batch", "999"),  # operational
        ("drivers.enabled", "drivers", "enabled", "['parse.pdf.pdfium']"),  # operational
        ("roots.output", "roots", "output", "'other/out'"),  # operational
    ],
)
def test_mutating_an_operational_key_leaves_semantic_digest_byte_identical(
    tmp_path: Path, key: str, table: str, field: str, literal: str
) -> None:
    """The shape of I26, over the keys this module owns."""
    base = _load_shipped(tmp_path)
    root = _project(tmp_path / "mutated")
    (root / "omniweave.toml").write_text(
        _override(SHIPPED.read_text(encoding="utf-8"), table, field, literal), encoding="utf-8"
    )
    mutated = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    assert mutated.get(key) != base.get(key)
    assert mutated.semantic_digest == base.semantic_digest
    assert mutated.config_digest != base.config_digest


def test_mutating_a_semantic_key_moves_both_digests(tmp_path: Path) -> None:
    base = _load_shipped(tmp_path)
    root = _project(tmp_path / "mutated")
    (root / "omniweave.toml").write_text(
        _override(SHIPPED.read_text(encoding="utf-8"), "graph", "segment_target_tokens", "900"),
        encoding="utf-8",
    )
    mutated = load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})
    assert mutated.semantic_digest != base.semantic_digest
    assert mutated.config_digest != base.config_digest


# ---------------------------------------------------------------------------------------------
# The two startup checks 02-architecture.md section 5.3 row 2 gives the config step
# ---------------------------------------------------------------------------------------------


def test_a_cache_root_inside_source_is_a_startup_error(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "omniweave.toml").write_text(
        "[roots]\nsource = 'docs'\ncache = 'docs/cache'\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="is inside source"):
        load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})


def test_the_shipped_control_directory_is_not_a_cache_inside_source(tmp_path: Path) -> None:
    """`source = "."` with `cache = ".omniweave/cache"` is the shipped default and must load."""
    cfg = _load_shipped(tmp_path)
    assert cfg.get("roots.source") == "."
    assert cfg.get("roots.cache") == ".omniweave/cache"


def test_a_newer_schema_refuses_at_startup(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "omniweave.toml").write_text("schema = 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="schema = 2"):
        load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})


def test_an_unparseable_file_is_a_startup_error(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "omniweave.toml").write_text("[roots\nsource = '.'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load(cwd=root, env={"OMNIWEAVE_HOME": str(tmp_path / "absent")})


# ---------------------------------------------------------------------------------------------
# G17 and D1: the module is stdlib-only and drags in none of the nine lazy subpackages
# ---------------------------------------------------------------------------------------------


def test_importing_config_loads_none_of_the_nine_lazy_subpackages() -> None:
    """`import omniweave_core.config` drags in none of the nine. MEASURED IN A FRESH INTERPRETER.

    RE-INSTRUMENTED, because the in-process form was wrong twice and would go wrong again.
    It read the pytest session's SHARED `sys.modules`, and pytest imports every test module during
    collection before any test runs -- so it did not assert anything about `config.py`. It asserted
    that NO test anywhere in the suite may import any lazy subpackage. That is not the property, and
    it is a property the project cannot satisfy: P2 IS `omniweave_core.model` and
    `omniweave_core.store`, and both must be unit-tested.

    It broke first on `omniweave_core.drivers.card` and was narrowed by dropping `drivers` from the
    tuple -- treating the symptom. It then broke on `omniweave_core.model` the moment P2's first
    module landed. Narrowing again would have removed the name the assertion most needs to cover,
    since `model` is the pivot every later phase imports.

    The subject here is `config.py` specifically, which is why this is NOT redundant with
    `tests/test_g17.py`: that one imports `omniweave_core` and this one imports
    `omniweave_core.config`, a module on the `ow hook prompt` path that is free to import a lazy
    subpackage by accident in a way the bare package never could. Both matter; only the instrument
    was shared.
    """
    code = (
        "import omniweave_core.config, json, sys;"
        "print(json.dumps(sorted(m for m in sys.modules if m.startswith('omniweave_core.'))))"
    )
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    loaded = json.loads(proc.stdout.strip().splitlines()[-1])
    # All nine, including the two the in-process form had to omit because a sibling test imports
    # them: `toolchain` (W1.6, on disk) and `modelserver` (P4 W4.9, not yet written).
    lazy = (
        "model",
        "store",
        "archive",
        "retrieve",
        "answer",
        "out",
        "host",
        "toolchain",
        "modelserver",
    )
    leaked = sorted(m for m in loaded for n in lazy if m.startswith(f"omniweave_core.{n}"))
    assert leaked == [], f"import omniweave_core.config pulled in {leaked}"


def test_the_module_imports_only_the_standard_library() -> None:
    # D1: `omniweave_core` carries ZERO third-party runtime dependencies. Inspecting `vars()` is
    # the wrong instrument -- a module-level `Path` constant has no `__module__` and reads as
    # foreign -- so the imports themselves are walked, which is what the claim is about.
    import omniweave_core.config as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])

    foreign = roots - set(sys.stdlib_module_names) - {"omniweave_core", "omniweave_ports"}
    assert not foreign, f"config.py imports outside the stdlib: {sorted(foreign)}"
    assert math.isfinite(1.0)  # the one third-party-looking import is stdlib `math`
