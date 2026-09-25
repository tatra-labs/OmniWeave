"""The payload `tools/list` sends, and the seam it arrives across. 10:206 row 1; 11 section 2.6.

Three properties, and the second is the one that makes this module worth having.

**The server loads the artefact; it does not rebuild it.** A second assembler would be two homes
for one payload, which is INV-20's defect with the server on the wrong side of it. The binding test
below imports `omniweave.gen.mcp_tools` and demands the loaded objects equal the generated ones,
key order included.

**A test may cross the layers row the source may not.** `omniweave_serve`'s row is
`["omniweave_core", "omniweave_ports"]` and G4 enforces it over `packages/*/src/**/*.py` -- source
text only. So the binding above is available to this file and forbidden to the module it checks,
which is exactly the asymmetry that makes the binding worth writing: the two distributions are held
equal by something neither of them can import.

**A payload that is not servable is refused before it reaches an agent.** `check()`'s red cases run
against temporary files, because the property under test is what the function says about bytes and
the only bytes this process may not write are the committed ones.
"""

from __future__ import annotations

import ast
import json
import tomllib
from itertools import count
from pathlib import Path
from typing import Any

import omniweave_serve.catalog as catalog_module
import pytest
from omniweave.gen.mcp_tools import ANNOTATIONS
from omniweave.gen.mcp_tools import tools as generated_tools
from omniweave.surface.registry import MCP_NAME_RE as REGISTRY_MCP_NAME_RE
from omniweave_core.config import KEYS
from omniweave_core.errors import ConfigError
from omniweave_serve.catalog import (
    ANNOTATION_KEYS,
    CATALOGUE_NAME,
    MCP_NAME_RE,
    SCHEMA_DIR,
    catalogue_path,
    check,
    layers_row,
    load_catalogue,
    payload,
    unservable,
)

DIST_ROOT = Path(__file__).resolve().parents[2]
REPO = DIST_ROOT.parents[1]
COMMITTED = REPO / SCHEMA_DIR / CATALOGUE_NAME

FOUR = ("ow_add", "ow_corpora", "ow_open", "ow_query")
"""The names the committed payload carries today, transcribed so the loader is compared against
the artefact rather than against itself."""


def _one(**over: object) -> dict[str, Any]:
    """A minimal servable tool object, for the red cases to break one field at a time."""
    base: dict[str, Any] = {
        "name": "ow_thing",
        "description": "does a thing",
        "annotations": dict.fromkeys(ANNOTATION_KEYS, False),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    }
    base.update(over)
    return base


_WRITTEN = count()


def _written(tmp_path: Path, entries: object) -> Path:
    """A fixture payload at a path no other call uses.

    A fresh directory per call, because `_load_catalogue` is memoised ON THE PATH: within one
    process a file is read once and a rewrite in place is not seen. That is
    `errors._load_register`'s behaviour too and it is right for a server -- the payload does not
    change under a running process -- but it makes a test that reuses a path assert the previous
    file's findings.
    """
    directory = tmp_path / f"payload-{next(_WRITTEN)}"
    directory.mkdir()
    path = directory / CATALOGUE_NAME
    path.write_text(json.dumps(entries), encoding="utf-8", newline="\n")
    return path


# ---------------------------------------------------------------------------------------------
# The artefact that ships
# ---------------------------------------------------------------------------------------------


def test_the_loader_finds_the_committed_artefact() -> None:
    assert catalogue_path() == COMMITTED
    assert COMMITTED.is_file()


def test_the_shipped_payload_is_servable() -> None:
    """`check()` green on the bytes as they ship. Six clauses, and `()` is all six passing."""
    assert check() == ()


def test_the_payload_is_the_four_tools_in_the_files_order() -> None:
    assert tuple(tool["name"] for tool in payload()) == FOUR
    assert sorted(load_catalogue().by_name) == sorted(FOUR)


def test_every_object_is_the_one_the_generator_produced() -> None:
    """The binding this module exists for, and the reason a test may import across the row.

    Equal as objects AND in order, so a server that re-sorted, re-keyed or rebuilt the payload
    fails here rather than shipping a `tools/list` nobody measured. 10:336 counts four tool
    objects at 411, 258, 189 and 173 tokens, and those counts are of these bytes.
    """
    assert list(payload()) == [dict(tool) for tool in generated_tools()]
    for loaded, built in zip(payload(), generated_tools(), strict=True):
        assert list(loaded) == list(built), "key order reaches the wire and the token count"


def test_the_loaded_fields_agree_with_the_object_they_came_from() -> None:
    for tool in load_catalogue().tools:
        wire = tool.wire()
        assert wire["name"] == tool.name
        assert wire["description"] == tool.description
        assert wire["annotations"] == dict(tool.annotations)
        assert wire["inputSchema"] == dict(tool.input_schema)
        assert (wire.get("outputSchema", {}) or {}).get("$ref") == tool.output_schema


def test_a_caller_cannot_reach_the_memoised_catalogue_through_what_it_received() -> None:
    """`payload()` parses `raw` per call, so a mutation lands on a copy. A memoised loader that
    handed out its own nested dictionaries would let one request edit the next one's schema."""
    first = payload()[0]
    first["description"] = "mutated"
    first["inputSchema"]["properties"]["injected"] = True
    assert payload()[0]["description"] != "mutated"
    assert "injected" not in payload()[0]["inputSchema"]["properties"]


# ---------------------------------------------------------------------------------------------
# The two constants this distribution may not import
# ---------------------------------------------------------------------------------------------


def test_the_annotation_keys_are_the_generators_four_in_its_order() -> None:
    """`MAX_RUNG_MEMBERS`' pattern across a layers row: the constant is spelled in the module
    that may not import its source, and the test does the import."""
    assert tuple(key for key, _field in ANNOTATIONS) == ANNOTATION_KEYS


def test_the_name_grammar_is_the_registrys_grammar() -> None:
    """Two trust boundaries, one grammar. The registry enforces it on the way in (check 3) and
    this enforces it on the way out, because the payload is the end an agent meets."""
    assert MCP_NAME_RE.pattern == REGISTRY_MCP_NAME_RE.pattern
    for name in FOUR:
        assert MCP_NAME_RE.match(name)


# ---------------------------------------------------------------------------------------------
# `check()`'s six clauses, against a temporary file
# ---------------------------------------------------------------------------------------------


def test_clause_1_an_empty_payload_is_leanns_manifest_at_its_limit(tmp_path: Path) -> None:
    assert any("no tools at all" in line for line in check(_written(tmp_path, [])))


def test_clause_2_a_name_no_host_can_address_fails(tmp_path: Path) -> None:
    path = _written(tmp_path, [_one(name="Query")])
    assert any("no host can call it" in line for line in check(path))


def test_clause_3_a_duplicated_name_fails(tmp_path: Path) -> None:
    path = _written(tmp_path, [_one(), _one()])
    assert any("appears twice" in line for line in check(path))


def test_clause_4_a_missing_annotation_key_is_a_declaration(tmp_path: Path) -> None:
    """10:216, and the reason it is not pedantry: MCP reads an absent `destructiveHint` as
    `true`, so a key lost in transit ships the protocol's most alarming annotation."""
    thin = dict.fromkeys(ANNOTATION_KEYS, False)
    del thin["destructiveHint"]
    path = _written(tmp_path, [_one(annotations=thin)])
    findings = check(path)
    assert any("destructiveHint" in line and "absent" in line for line in findings), findings


def test_clause_4b_a_non_boolean_annotation_is_not_an_annotation(tmp_path: Path) -> None:
    """`_tool()` keeps only the boolean members, so a string reads as an absent key -- which is
    the same finding, and the right one: MCP has no third state for a hint."""
    typed = {**dict.fromkeys(ANNOTATION_KEYS, False), "destructiveHint": "no"}
    path = _written(tmp_path, [_one(annotations=typed)])
    assert any("destructiveHint" in line for line in check(path))


def test_clause_5_a_tool_with_no_description_or_no_schema_fails(tmp_path: Path) -> None:
    assert any("description" in line for line in check(_written(tmp_path, [_one(description="")])))
    assert any("inputSchema" in line for line in check(_written(tmp_path, [_one(inputSchema={})])))


def test_clause_6_an_open_input_object_fails(tmp_path: Path) -> None:
    """10:516: `additionalProperties: false` survives compaction, so a payload without it is one
    a host cannot validate against."""
    open_object = {"type": "object", "properties": {}}
    path = _written(tmp_path, [_one(inputSchema=open_object)])
    assert any("closed object" in line for line in check(path))


def test_a_clean_fixture_payload_reports_nothing(tmp_path: Path) -> None:
    assert check(_written(tmp_path, [_one()])) == ()


# ---------------------------------------------------------------------------------------------
# 11 section 2.6's three rules
# ---------------------------------------------------------------------------------------------


def test_an_unreadable_payload_raises_a_named_error_with_a_fix(tmp_path: Path) -> None:
    """Rule 3: never a `KeyError`, a `FileNotFoundError` or a silent empty default."""
    broken = tmp_path / CATALOGUE_NAME
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_catalogue(broken)
    assert caught.value.fix
    with pytest.raises(ConfigError):
        load_catalogue(tmp_path / "absent" / CATALOGUE_NAME)


def test_a_malformed_entry_becomes_a_finding_and_never_a_raise(tmp_path: Path) -> None:
    """Rule 3 at field granularity: a payload with three defects costs one edit cycle."""
    path = _written(tmp_path, ["not an object", {"name": "ow_x"}])
    findings = check(path)
    assert len(findings) >= 3, findings


def test_the_payload_is_read_at_use_time_and_memoised() -> None:
    """Rule 2. The module body opens nothing, so a corrupt file degrades `tools/list` rather
    than bricking every import of this distribution -- `ow doctor` included.

    The module level is asserted structurally: every statement in it is an import, a constant
    binding, a dataclass or a function, so there is no expression for a read to hide in. That is
    stronger than grepping for `open`, which would miss a helper called at import.
    """
    assert load_catalogue() is load_catalogue()
    allowed = (
        ast.Import,
        ast.ImportFrom,
        ast.Assign,
        ast.AnnAssign,
        ast.FunctionDef,
        ast.ClassDef,
        ast.If,  # `if TYPE_CHECKING:` only, which the clause below proves
    )
    tree = ast.parse(Path(catalog_module.__file__).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Expr):
            assert isinstance(node.value, ast.Constant), "a docstring is the only bare expression"
            continue
        assert isinstance(node, allowed), f"module-level {type(node).__name__}"
        if isinstance(node, ast.If):
            assert isinstance(node.test, ast.Name)
            assert node.test.id == "TYPE_CHECKING"


def test_a_payload_is_read_once_per_path_and_a_rewrite_is_not_seen(tmp_path: Path) -> None:
    """The memoisation, stated rather than discovered. `errors._load_register` does the same.

    Right for a server: the committed payload does not change under a running process, and a
    per-call read would put a stat on the path of every `tools/list`.
    """
    path = _written(tmp_path, [_one()])
    assert check(path) == ()
    path.write_text(json.dumps([]), encoding="utf-8", newline="\n")
    assert check(path) == (), "the rewrite is not seen within this process"


def test_the_loader_reaches_its_file_through_importlib_resources_and_not_dunder_file() -> None:
    """Rule 1. `__file__` and `__path__[0]` are wrong under a zipapp, a `--target` layout and any
    `zipimport`er, which is why 11 section 2.6 bans them for package data.

    Over the AST and not the text, because both names appear in the prose that explains the ban
    and a grep would fail on the docstring that states the rule.
    """
    tree = ast.parse(Path(catalog_module.__file__).read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert "__file__" not in names
    assert "__path__" not in names
    locators = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "files"
    ]
    assert len(locators) == 1, "one locator, and it is importlib.resources.files()"


# ---------------------------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------------------------


def test_this_distribution_may_not_import_the_one_that_holds_the_rest() -> None:
    """02:350's row, read from the file G4 reads it from."""
    assert layers_row(REPO) == ("omniweave_core", "omniweave_ports")
    assert "omniweave" not in layers_row(REPO), "the CLI distribution is not in the row"


def test_no_module_in_this_distribution_imports_omniweave() -> None:
    """02:361: *inside a function body and behind a `TYPE_CHECKING` guard included.* G4 is the
    gate; this is the same property asserted where the module under test lives."""
    for source in (DIST_ROOT / "src").rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".")[0]}
            else:
                continue
            assert "omniweave" not in roots, f"{source.name} imports omniweave"


def test_unservable_names_only_the_input_d340_left_owed() -> None:
    """D340 route 2: the three transforms are read from the listing, and one input is left."""
    (row,) = unservable()
    assert "serve.default_corpus" in row
    assert "omniweave.surface.startup.servable().resolves" in row
    assert "corpus_resolves" in row


def test_every_symbol_unservable_names_lives_where_it_says_it_does() -> None:
    """A claim about another distribution, checked rather than asserted -- the entry is only
    worth reading if the three symbols are really there."""
    registry = (
        REPO / "packages" / "omniweave" / "src" / "omniweave" / "surface" / "registry.py"
    ).read_text(encoding="utf-8")
    schema = (
        REPO / "packages" / "omniweave" / "src" / "omniweave" / "surface" / "schema.py"
    ).read_text(encoding="utf-8")
    assert "listed_in:" in registry
    assert "_ADVANCED" in schema
    assert "def with_required_corpus" in schema


def test_the_shipped_defaults_are_the_ones_unservable_reports() -> None:
    """If a deployment's defaults changed so that no transform were needed, the entry would be
    stale. They have not: the shipped profile is a selection and compaction is on."""
    assert KEYS["serve.profile"].default == "default"
    assert KEYS["serve.compact_schemas"].default is True


# ---------------------------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------------------------


def test_the_payload_ships_in_no_wheel_and_the_loader_says_so() -> None:
    """D341. `schema/` is a repository directory and no `pyproject.toml` includes it, so every
    resolution here is the workspace fallback and a `pip install omniweave-serve` has no payload
    at all. The test that would fail on the day it ships is the first assertion."""
    included = tomllib.loads((DIST_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sdist = included["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert SCHEMA_DIR not in sdist, "the payload is now packaged; D341 is closed and this changes"
    assert not (DIST_ROOT / "src" / "omniweave_serve" / CATALOGUE_NAME).exists()
    assert catalogue_path() == COMMITTED, "so the only copy is the repository's"
