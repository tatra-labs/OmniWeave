"""`omniweave_core.cache` against 08-runtime.md Part 4, which calls itself a specification.

08:1263: *"A reviewer may reject a PR that adds a key input, removes one, or reorders the canonical
groups without amending section 4.2's table."* So `cache_key()`'s body is compared against the
plan's own printed function with `ast` -- group names, group order and the eleven leaf inputs -- and
the **absences** get their own test, because a cache key's deletions are as load-bearing as its
inclusions and nothing else in the file would notice one coming back.

The cards are real. `load_card()` parses the same TOML a driver ships, so `schema_version`,
`cost_model.cost_class` and `deps.digest` reach `cache_key()` through the type the runner will hand
it rather than through a stub that agrees with the test by construction.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest
from omniweave_core import cache
from omniweave_core.archive.manifest import DIGEST_RECIPE
from omniweave_core.cache import (
    AGE_SWEEP_SQL,
    CACHE_INDEX_COLUMNS,
    CONSUMES_BLOCKS,
    DEFAULT_CACHE_RECIPE,
    GC_DEFAULT_DAYS,
    GROWTH_BOUND_WORDS,
    MAX_BYTES_UNBOUNDED,
    MISS_VERDICTS,
    NEVER_SWEEP_DAYS,
    SIZE_SWEEP_SQL,
    UPSERT_SQL,
    CacheEntry,
    CacheLayer,
    CacheVerdict,
    cache_key,
    cache_ns,
    consumes_blocks,
    read_verdict,
    reject_unallowed,
    unit_salt,
)
from omniweave_core.drivers.card import load_card
from omniweave_core.operator import CACHE_KEY_HEX_LEN, OperatorIdentity
from omniweave_ports.types import UnitRef

RUNTIME = "08-runtime.md"

DDL = (
    Path(inspect.getfile(cache)).parent / "store" / "schema" / "migrations" / "0004_runtime.sql"
).read_text(encoding="utf-8")
TABLE = DDL[DDL.index("CREATE TABLE cache_index (") : DDL.index("CREATE INDEX cache_gc")]

CARD_TOML = """card_schema = 1

[driver]
id = "parse.page.olmocr"
port = "parse/1"
version = "0.1.0"
schema_version = 7
entrypoint = "pkg.driver:Cls"
granularity = "part"
replay_class = "byte_exact"

[capability]
formats = ["application/pdf"]
consumes = ["raw_bytes"]
produces = ["doc_fragment"]

[licence.code]
spdx = "Apache-2.0"

[deps]
pins = ["pdfium==1.2.3"]

[cost.model]
class = "{cost_class}"
shape = "constant"
unit = "part"
"""

UNIT = UnitRef(uri="file:///corpus/a.pdf", part="p3", content_sha256="c0ffee", byte_len=99)
IDENTITY = OperatorIdentity(
    operator="parse.pdf", op_version=7, code_fingerprint="abcdef123456", options_digest=b"\x01\x02"
)


class FakeRunContext:
    """Everything `cache_key()` reads off a `RunContext`, which is one field."""

    def __init__(self, semantic_digest: str = "s" * 64) -> None:
        self.semantic_digest = semantic_digest


def card(cost_class: str = "billed_api"):
    """A real `DriverCard`, parsed from a real card."""
    return load_card(
        CARD_TOML.format(cost_class=cost_class).encode("utf-8"),
        origin="entry_point",
        source="driver.toml",
    )


def key(*, cost_class: str = "billed_api", salt: str = "a.pdf", **over: object) -> str:
    fields = {
        "unit": UNIT,
        "ident": IDENTITY,
        "card": card(cost_class),
        "ctx": FakeRunContext(),
    }
    fields.update(over)
    return cache_key(**fields, salt=salt)  # type: ignore[arg-type]


def _printed_cache_key(plan) -> ast.FunctionDef:
    """08:1316-1332's own `def cache_key`, parsed out of its fence."""
    plan.require()
    for body in plan.fences(RUNTIME, "python"):
        if "def cache_key(" not in body:
            continue
        for node in ast.parse(body).body:
            if isinstance(node, ast.FunctionDef) and node.name == "cache_key":
                return node
    pytest.fail("08 prints no def cache_key")


def _printed_body(node: ast.FunctionDef) -> ast.Dict:
    """The `sha256_canonical({...})` literal the plan's function returns."""
    ret = next(child for child in node.body if isinstance(child, ast.Return))
    assert isinstance(ret.value, ast.Call)
    argument = ret.value.args[0]
    assert isinstance(argument, ast.Dict)
    return argument


# ---------------------------------------------------------------------------------------------
# 1. The layers and the columns
# ---------------------------------------------------------------------------------------------


def test_the_five_layers_are_the_ddls_check_in_the_ddls_order() -> None:
    """0004_runtime.sql:158. Five, and the DDL's comment says why the name is not `Layer`."""
    body = TABLE[TABLE.index("layer        TEXT NOT NULL CHECK (layer IN (") :]
    body = body[: body.index("))")]
    assert tuple(re.findall(r"'([a-z]+)'", body)) == tuple(member.value for member in CacheLayer)
    assert "`CacheLayer`, never `Layer`" in TABLE


def test_there_is_no_parse_layer_and_no_derive_layer() -> None:
    """INV-1, stated by the DDL itself: *"if it is a row in the .owstore it is NEVER also a blob"*.

    The parse memo is three facts already in the store, and the absence is what stops a fourth.
    """
    assert "parse" not in {member.value for member in CacheLayer}
    assert "derive" not in {member.value for member in CacheLayer}
    assert "THERE IS NO `parse` OR `derive` LAYER" in DDL


def test_the_column_tuple_is_the_tables_columns_in_order() -> None:
    """`CACHE_INDEX_COLUMNS` builds the store's projection, so it must be the DDL's own order."""
    columns: list[str] = []
    for line in TABLE.splitlines()[1:]:
        if line.startswith(")") or line.strip().startswith("--"):
            continue
        columns.extend(re.findall(r"(?:^\s*|,\s*)(\w+)\s+(?:TEXT|INTEGER)", line))
    assert tuple(columns) == CACHE_INDEX_COLUMNS


def test_the_seven_verdicts_are_the_plans_seven(plan) -> None:
    """08:1441 names them in one prose line and prints no type. **D145**."""
    plan.require()
    found = plan.grep(r"`CacheVerdict` is `hit", documents=[RUNTIME])
    assert len(found) == 1
    # The sentence wraps, so the members come from that line and the one after it.
    text = " ".join(plan.lines(RUNTIME)[found[0].line - 1 : found[0].line + 1])
    named = tuple(dict.fromkeys(re.findall(r"\b(?:hit|miss)[a-z_]*", text)))
    assert named == tuple(member.value for member in CacheVerdict)
    assert len(MISS_VERDICTS) == 5, "08:1454: the five distinct miss shapes"


# ---------------------------------------------------------------------------------------------
# 2. `cache_key()` -- against the plan's own printed function
# ---------------------------------------------------------------------------------------------


def test_the_three_canonical_groups_are_the_plans_own_in_order(plan) -> None:
    """08:1263 makes reordering the groups a rejectable PR, so the order is asserted."""
    printed = _printed_body(_printed_cache_key(plan))
    groups = [node.value for node in printed.keys if isinstance(node, ast.Constant)]
    assert groups == ["k", "content", "producer", "config"]


def test_every_leaf_input_is_the_plans_own(plan) -> None:
    """The eleven rows of 08:1334-1348, read off the printed dict rather than off the table.

    A leaf added here without a row in that table, or a row dropped without a leaf, is what 08:1263
    calls rejectable. This is the half a reviewer cannot do by eye.
    """
    printed = _printed_body(_printed_cache_key(plan))
    leaves: dict[str, list[str]] = {}
    for group, value in zip(printed.keys, printed.values, strict=True):
        if isinstance(group, ast.Constant) and isinstance(value, ast.Dict):
            leaves[str(group.value)] = [
                str(k.value) for k in value.keys if isinstance(k, ast.Constant)
            ]

    assert leaves == {
        "content": ["digest", "salt", "part"],
        "producer": ["operator", "schema_version", "code_fingerprint", "deps_digest"],
        "config": ["driver", "run", "digest_recipe"],
    }

    source = ast.parse(Path(inspect.getfile(cache)).read_text(encoding="utf-8"))
    ours = next(
        node
        for node in ast.walk(source)
        if isinstance(node, ast.FunctionDef) and node.name == "cache_key"
    )
    mine: dict[str, list[str]] = {}
    for node in ast.walk(ours):
        if isinstance(node, ast.Dict) and any(
            isinstance(k, ast.Constant) and k.value == "content" for k in node.keys
        ):
            for group, value in zip(node.keys, node.values, strict=True):
                if isinstance(group, ast.Constant) and isinstance(value, ast.Dict):
                    mine[str(group.value)] = [
                        str(k.value) for k in value.keys if isinstance(k, ast.Constant)
                    ]
    assert mine == leaves


@pytest.mark.parametrize(
    "absent",
    ["policy_digest", "pricebook_digest", "config_digest", "run_id", "generation", "hostname"],
)
def test_the_deliberate_absences_stay_absent(plan, absent: str) -> None:
    """08:1367-1374's list, each with a consequence.

    `policy_digest` and `pricebook_digest` are decision-key inputs, *"repricing must not re-bill"*.
    `config_digest` holds `runtime.**`, so raising `max_workers` would re-bill the corpus (I26).
    The run id, the generation and the hostname would make every key unique, which is a cache that
    never hits and never says so.
    """
    plan.require()
    body = ast.unparse(_printed_body(_printed_cache_key(plan)))
    assert absent not in body

    ours = Path(inspect.getfile(cache)).read_text(encoding="utf-8")
    ours_body = ours[ours.index("body: dict[str, JsonValue] = {") : ours.index("return sha256_can")]
    assert absent not in ours_body


def test_a_key_is_sixty_four_hex_characters() -> None:
    """Every `cache_key` column in the framework holds this output, `derive_run.cache_key` too."""
    value = key()
    assert re.fullmatch(r"[0-9a-f]{64}", value)
    assert len(value) == CACHE_KEY_HEX_LEN


def test_the_private_width_constant_agrees_with_the_runners() -> None:
    """The one duplicated number in this module, checked rather than trusted."""
    assert cache._CACHE_KEY_HEX_LEN == CACHE_KEY_HEX_LEN


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("salt", "b.pdf"),
        ("unit", UnitRef(uri=UNIT.uri, part="p4", content_sha256="c0ffee", byte_len=99)),
        ("unit", UnitRef(uri=UNIT.uri, part="p3", content_sha256="beef", byte_len=99)),
        ("ident", OperatorIdentity(operator="derive.entity", op_version=7, code_fingerprint="x")),
        ("ctx", FakeRunContext("t" * 64)),
    ],
)
def test_every_input_that_should_move_the_key_moves_it(field: str, value: object) -> None:
    """One changed input, one different key. The five that are unconditional."""
    assert key(**{field: value}) != key()


def test_a_bug_fix_release_does_not_move_the_key() -> None:
    """08:1343: *"`driver_version` (semver) in the key means a bug-fix release re-bills a corpus."*

    `schema_version` is the only driver version in the key, and it is why 08:1590 calls it the most
    expensive integer in the framework.
    """
    bumped = load_card(
        CARD_TOML.format(cost_class="billed_api")
        .replace('version = "0.1.0"', 'version = "0.9.9"')
        .encode("utf-8"),
        origin="entry_point",
        source="driver.toml",
    )
    assert key(card=bumped) == key()

    reshaped = load_card(
        CARD_TOML.format(cost_class="billed_api")
        .replace("schema_version = 7", "schema_version = 8")
        .encode("utf-8"),
        origin="entry_point",
        source="driver.toml",
    )
    assert key(card=reshaped) != key()


def test_code_fingerprint_is_in_the_key_only_when_the_driver_is_not_billed() -> None:
    """08:1344. Including it for `billed_api` re-bills a corpus on every refactor.

    Excluding it for free work is graphify's `_EXTRACTOR_VERSION = "unknown"`, where a developer
    editing an extractor shares one namespace with every version of it.
    """
    other = OperatorIdentity(
        operator=IDENTITY.operator,
        op_version=7,
        code_fingerprint="zzzzzz",
        options_digest=b"\x01\x02",
    )
    assert key(ident=other) == key(), "a refactor must not re-bill"
    assert key(ident=other, cost_class="free") != key(cost_class="free")
    assert key(ident=other, cost_class="local_compute") != key(cost_class="local_compute")


def test_the_deps_digest_is_in_the_key_only_when_the_driver_is_free() -> None:
    """08:1345. The lockfile digest would invalidate the whole free tier on every bump (F26)."""
    bumped = CARD_TOML.replace('pins = ["pdfium==1.2.3"]', 'pins = ["pdfium==1.2.4"]')

    def with_pins(cost_class: str):
        return load_card(
            bumped.format(cost_class=cost_class).encode("utf-8"),
            origin="entry_point",
            source="driver.toml",
        )

    assert key(card=with_pins("free"), cost_class="free") != key(cost_class="free")
    assert key(card=with_pins("local_compute"), cost_class="local_compute") == key(
        cost_class="local_compute"
    )
    assert key(card=with_pins("billed_api")) == key()


def test_the_digest_recipe_is_in_the_key_only_for_an_operator_that_reads_blocks() -> None:
    """08:1347. **D144**: `consumes_blocks()` is called once in the plan and defined nowhere.

    Including it unconditionally *"makes a recipe bump invalidate parse `call` entries that never
    saw a digest"* -- the entries that cost the most to lose.
    """
    assert consumes_blocks("derive.entity") is True
    assert consumes_blocks("parse.pdf") is False
    assert consumes_blocks("op.cluster") is True
    assert consumes_blocks("op.identify") is False
    with pytest.raises(ValueError, match="undeclared"):
        consumes_blocks("sideload.thing")

    parse_key = key()
    derive = OperatorIdentity(operator="derive.entity", op_version=7, code_fingerprint="abcdef")
    assert DIGEST_RECIPE == 1
    assert key(ident=derive) != parse_key


def test_the_ports_and_the_op_steps_are_all_declared() -> None:
    """Five Ports and five `op.*` steps, which is the whole domain an Operator can have."""
    assert set(CONSUMES_BLOCKS) == {
        "acquire",
        "parse",
        "derive",
        "embed",
        "compile",
        "op.identify",
        "op.converge",
        "op.lexicon",
        "op.resolve",
        "op.cluster",
    }


# ---------------------------------------------------------------------------------------------
# 3. The salt, and the namespaces
# ---------------------------------------------------------------------------------------------


def test_the_fs_salt_is_relative_and_posix_separated() -> None:
    """08:1353-1356. An absolute path would destroy portability across checkouts."""
    assert unit_salt("fs", walked_path="/corpus/a/b.pdf", source_root="/corpus") == "a/b.pdf"
    assert unit_salt("fs", walked_path=r"C:\corpus\a\b.pdf", source_root="C:/corpus") == "a/b.pdf"


def test_a_connector_without_a_filesystem_still_gets_a_salt() -> None:
    """08:1358-1360: *"stable across machines by construction and never a local path"*."""
    assert unit_salt("s3", locator="bucket/key.pdf") == "s3/bucket/key.pdf"
    with pytest.raises(ValueError, match="locator is empty"):
        unit_salt("s3")
    with pytest.raises(ValueError, match="walked path"):
        unit_salt("fs", source_root="/corpus")


def test_two_symlink_aliases_are_two_salts(plan) -> None:
    """08:1364, which is also the sharpest statement of D143.

    *"Two symlink aliases of one file are two units with two salts and two cache entries, because a
    corpus that lists a document twice under two names has two documents as far as citation is
    concerned."* The walked path is the input precisely because `canonical_uri()` has already
    applied realpath -- so the distinction cannot be recovered from `unit_uri`, and the roster
    stores no other path.
    """
    plan.require()
    assert unit_salt("fs", walked_path="/c/a.pdf", source_root="/c") != unit_salt(
        "fs", walked_path="/c/link-to-a.pdf", source_root="/c"
    )
    assert plan.grep(r"symlink aliases of one file are two units", documents=[RUNTIME])


def test_the_three_namespace_shapes_are_the_plans_own() -> None:
    """08:1422-1424, and the asymmetry is the point: a billed namespace is keyed on config alone."""
    common = {
        "operator": "parse.pdf",
        "op_version": 7,
        "code_fingerprint": "abc",
        "config_digest": "cd",
    }
    assert cache_ns("free", **common) == "op/parse.pdf/v7-cabc/"
    assert cache_ns("local_compute", **common) == "op/parse.pdf/v7-cabc/cfg/cd/"
    assert cache_ns("billed_api", **common) == "cfg/cd/"
    with pytest.raises(ValueError, match="CostClass"):
        cache_ns("cheap", **common)


def test_a_billed_namespace_ignores_the_code_fingerprint() -> None:
    """graphify `cache.py:1179`'s correction: two hosts with different prompts must not each
    delete the other's entries and re-bill extraction on every alternation."""
    a = cache_ns(
        "billed_api", operator="p", op_version=1, code_fingerprint="aaa", config_digest="cd"
    )
    b = cache_ns(
        "billed_api", operator="q", op_version=2, code_fingerprint="bbb", config_digest="cd"
    )
    assert a == b


def test_i27_is_the_partial_index_and_not_a_policy() -> None:
    """The automatic sweep's query cannot see a billed row, because the index it scans has none."""
    assert "WHERE cost_class='free'" in DDL
    assert "I27 IS THIS PARTIAL PREDICATE, not a policy" in DDL


def test_the_growth_bound_is_printed_in_the_plans_own_words(plan) -> None:
    """08:1426 says `ow cache stat` prints it **in these words**, and 16:544 repeats the demand."""
    plan.require()
    assert GROWTH_BOUND_WORDS == "live units x configurations seen"
    assert plan.grep(r"live units x configurations seen", documents=[RUNTIME])


# ---------------------------------------------------------------------------------------------
# 4. The read policy
# ---------------------------------------------------------------------------------------------


def entry(**over: object) -> CacheEntry:
    fields: dict[str, object] = {
        "cache_key": "a" * 64,
        "layer": CacheLayer.CALL,
        "cost_class": "billed_api",
        "ref": "cas://ab/cd/ef",
        "bytes": 10,
        "unit_uri": UNIT.uri,
        "unit_part": UNIT.part,
        "driver": "parse.page.olmocr",
        "driver_schema_v": 7,
        "config_digest": "cd",
        "origin_operator": "parse.pdf",
        "spend_json": "{}",
        "micros": 853,
    }
    fields.update(over)
    return CacheEntry(**fields)  # type: ignore[arg-type]


ASKED = (UNIT.uri, UNIT.part)


@pytest.mark.parametrize(
    ("kwargs", "verdict"),
    [
        ({"entry": None}, CacheVerdict.MISS),
        ({"blob_ok": False}, CacheVerdict.MISS_CORRUPT),
        ({"entry": "partial"}, CacheVerdict.MISS_PARTIAL),
        ({"nonempty": False}, CacheVerdict.MISS_EMPTY),
        ({"asked_for": (UNIT.uri, "p9")}, CacheVerdict.MISS_UNIT_MISMATCH),
        ({"in_current_namespace": False, "allow_legacy": True}, CacheVerdict.HIT_LEGACY),
        ({"in_current_namespace": False}, CacheVerdict.MISS),
        ({}, CacheVerdict.HIT),
    ],
)
def test_each_clause_returns_its_own_verdict(kwargs: dict, verdict: CacheVerdict) -> None:
    """08:1443-1451's table, row by row. *"A hit is a policy, not a lookup."*"""
    call = {"entry": entry(), "asked_for": ASKED}
    if kwargs.get("entry") == "partial":
        kwargs = {**kwargs, "entry": entry(partial=True)}
    call.update(kwargs)
    assert read_verdict(**call) == verdict  # type: ignore[arg-type]


def test_a_partial_entry_is_a_hit_when_the_caller_asked_for_one() -> None:
    """Clause 3 is conditional on the caller, which is what makes `ok_partial` reusable."""
    assert (
        read_verdict(entry(partial=True), asked_for=ASKED, allow_partial=True) == CacheVerdict.HIT
    )


def test_the_clause_order_is_the_specification() -> None:
    """Three orderings the table fixes, each with a consequence if reversed.

    Clause 2 before 4: an artefact that does not parse cannot be asked whether it is empty.
    Clause 3 before 4: a partial-and-empty entry is refused for the reason the caller can act on.
    Clause 5 before 6: a unit mismatch is a **bug report** and must not be reported as a vintage.
    """
    corrupt_and_empty = read_verdict(entry(), asked_for=ASKED, blob_ok=False, nonempty=False)
    assert corrupt_and_empty == CacheVerdict.MISS_CORRUPT

    partial_and_empty = read_verdict(entry(partial=True), asked_for=ASKED, nonempty=False)
    assert partial_and_empty == CacheVerdict.MISS_PARTIAL

    mismatch_and_legacy = read_verdict(
        entry(), asked_for=(UNIT.uri, "p9"), in_current_namespace=False, allow_legacy=True
    )
    assert mismatch_and_legacy == CacheVerdict.MISS_UNIT_MISMATCH


def test_the_allowlist_returns_what_it_rejects() -> None:
    """08:1465-1478. Runner-supplied, never driver-supplied, and rejects are recorded not raised."""
    mine = entry()
    theirs = entry(unit_uri="file:///corpus/b.pdf", unit_part="p1")
    allowed = frozenset({ASKED})

    assert reject_unallowed([mine], allowed) == ()
    assert reject_unallowed([mine, theirs], allowed) == (theirs,)
    assert reject_unallowed([mine, theirs], frozenset()) == (mine, theirs)


def test_an_entry_refuses_a_layer_a_cost_class_and_a_width_the_column_would_take() -> None:
    """The DDL's two CHECKs report a constraint name; a value type names the offence."""
    with pytest.raises(ValueError, match="CacheLayer"):
        entry(layer="parse")
    with pytest.raises(ValueError, match="CostClass"):
        entry(cost_class="cheap")
    with pytest.raises(ValueError, match="64-char hex"):
        entry(cache_key="short")


# ---------------------------------------------------------------------------------------------
# 5. The sweeps
# ---------------------------------------------------------------------------------------------


def test_the_size_sweep_is_the_plans_own_statement(plan) -> None:
    """08:1510-1519, with whitespace normalised so only the SQL is compared."""
    plan.require()
    fences = [
        body
        for body in plan.fences(RUNTIME, "sql")
        if "WITH ordered" in body and "cache_index" in body
    ]
    assert len(fences) == 1
    printed = " ".join(line for line in fences[0].splitlines() if not line.strip().startswith("--"))
    assert " ".join(printed.split()).rstrip(";") == " ".join(SIZE_SWEEP_SQL.split())


def test_the_age_sweep_is_the_plans_statement_with_its_two_literals_bound(plan) -> None:
    """08:1493-1499 prints the **free** instance of a query it calls *"one query per layer"*.

    The printed statement hard-codes `cost_class = 'free'` and `:free_after_days`; there are three
    cost classes and three `[cache] gc` keys, and 08:1502 gives each its own number. Binding the
    two is what turns one printed instance into the one query the same sentence asks for -- and
    this test asserts the substitution is exactly that and nothing else, by making it in reverse
    and comparing character for character.
    """
    plan.require()
    fences = [
        body
        for body in plan.fences(RUNTIME, "sql")
        if "DELETE FROM cache_index" in body and "WITH ordered" not in body
    ]
    assert len(fences) == 1
    printed = " ".join(line for line in fences[0].splitlines() if not line.strip().startswith("--"))
    ours = " ".join(AGE_SWEEP_SQL.split())
    rebound = ours.replace(":cost_class", "'free'").replace(":after_days", ":free_after_days")
    assert " ".join(printed.split()).rstrip(";") == rebound


@pytest.mark.parametrize("sql", [AGE_SWEEP_SQL, SIZE_SWEEP_SQL])
def test_neither_sweep_can_take_a_live_work_rows_memo(sql: str) -> None:
    """08:1536's concurrency answer, carried by both statements rather than by a lock."""
    assert (
        "cache_key NOT IN (SELECT cache_key FROM work WHERE status IN ('pending','claimed'))"
        in (" ".join(sql.split()))
    )


def test_the_size_sweep_never_re_bills() -> None:
    """I27 in the statement as well as in the index: *"an automatic sweep NEVER re-bills."*"""
    assert "cost_class <> 'billed_api'" in " ".join(SIZE_SWEEP_SQL.split())
    assert "last_hit_ns DESC" in SIZE_SWEEP_SQL, "LRU, newest first, delete past the bound"


def test_zero_means_never_and_unbounded_and_they_are_different_zeros() -> None:
    """08:1502 and 08:1521. One number, two meanings, in two different tables."""
    assert NEVER_SWEEP_DAYS == 0
    assert MAX_BYTES_UNBOUNDED == 0
    assert GC_DEFAULT_DAYS["billed_after_days"] == NEVER_SWEEP_DAYS
    assert GC_DEFAULT_DAYS["free_after_days"] == 7
    assert GC_DEFAULT_DAYS["local_after_days"] == 90


def test_the_gc_defaults_are_the_shipped_configs() -> None:
    """`omniweave.toml.example`'s `[cache] gc`, which is the file G18 gates."""
    example = (Path(inspect.getfile(cache)).parents[4] / "omniweave.toml.example").read_text(
        encoding="utf-8"
    )
    for key_name, value in GC_DEFAULT_DAYS.items():
        assert f"{key_name} = {value}" in example
    assert f"recipe = {DEFAULT_CACHE_RECIPE}" in example


def test_the_upsert_overwrites_because_two_read_clauses_require_it() -> None:
    """Clauses 2 and 4 both say *"overwritten on the next success"* -- self-healing with no flag."""
    assert "ON CONFLICT(cache_key) DO UPDATE SET" in UPSERT_SQL
    updated = UPSERT_SQL[UPSERT_SQL.index("DO UPDATE SET") :]
    assert "created_ns" not in updated, "an overwrite keeps the age the GC sweeps on"
    assert "hits" not in updated, "a self-heal does not reset a popular entry's history"
