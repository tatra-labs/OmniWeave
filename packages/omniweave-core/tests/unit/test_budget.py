"""`omniweave_core.budget` against 08-runtime.md Part 7, 05 section 6.4 and the shipped DDL.

Three witnesses, and the order is deliberate. The **DDL** is what the store actually creates, so the
three closed domains are read out of `0004_runtime.sql`'s CHECK clauses rather than compared to a
copy of themselves. The **plan** is where the statements and the dimension/scope table are printed,
so `HEADROOM_SQL` is compared against 08:2226-2233's own fence with whitespace normalised, and
`DIM_SCOPES` against 08:2186's markdown table cell by cell. The **code** is only asked about the
things neither of those can express -- an identity recipe, a rounding direction, and the one pairing
rule SQLite's two independent CHECKs cannot enforce.
"""

from __future__ import annotations

import ast
import inspect
import re
from dataclasses import fields, replace
from pathlib import Path

import pytest
from omniweave_core import budget, work
from omniweave_core.budget import (
    COMMIT_SQL,
    DIM_SCOPES,
    DIMS,
    HEADROOM_SQL,
    INPUT_PROPORTIONAL,
    OUTPUT_PROPORTIONAL,
    RELEASE_SQL,
    RESERVATION_ID_BODY_LEN,
    RESERVATION_ID_PREFIX,
    RESERVATION_REAP,
    RESERVATION_STATES,
    RESERVE_SQL,
    SCOPES,
    UNCAPPED,
    BudgetLedger,
    Reservation,
    reservation_id,
    reserved_amount,
    scope_key_for,
)

RUNTIME = "08-runtime.md"
ROUTING = "05-ingest-and-routing.md"

DDL = (
    Path(inspect.getfile(budget)).parent / "store" / "schema" / "migrations" / "0004_runtime.sql"
).read_text(encoding="utf-8")

TABLE = DDL[DDL.index("CREATE TABLE budget_reservation (") : DDL.index("CREATE INDEX res_open")]

P95_MULTIPLE = 3.2
"""`tokens_out_p95_multiple` in the shipped `[cost.model]` example (05:2452) and in 08:2254."""


def _check_domain(column: str) -> tuple[str, ...]:
    """The literals in one column's `CHECK (<column> IN (...))`, in the DDL's order."""
    body = TABLE[TABLE.index(f"{column} TEXT NOT NULL CHECK ({column} IN (") :]
    body = body[: body.index("))")]
    return tuple(re.findall(r"'([a-z_]+)'", body))


def _reservation() -> Reservation:
    return Reservation(
        reservation_id=reservation_id(7, "dec_p3", 1, "micros"),
        run_id="r_01HF",
        work_id=7,
        decision_id="dec_p3",
        dim="micros",
        amount=2_732,
        scope="part",
        scope_key="file:///a.pdf#p3",
        claimed_gen=1,
        expires_ms=1_757_400_120_000,
    )


# ---------------------------------------------------------------------------------------------
# 1. The three domains, read out of the shipped DDL
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "declared"),
    [("dim", DIMS), ("scope", SCOPES), ("state", RESERVATION_STATES)],
)
def test_each_domain_is_the_ddls_own_check_in_the_ddls_own_order(
    column: str, declared: tuple[str, ...]
) -> None:
    """The CHECK is the domain, so the tuple is a transcription and this is the diff.

    Order as well as membership: `DIMS` documents itself as *"verbatim and in the DDL's order"*,
    and a set comparison would let the two drift into different orders while both stayed true.
    """
    assert _check_domain(column) == declared


def test_the_dims_are_spends_seven_plus_micros() -> None:
    """The whole cost model as a set difference. 05:2366-2374 against 0004_runtime.sql:227.

    A driver reports seven physical units; a budget is declared in eight, and the extra one is
    money. INV-15 is that difference: nothing a driver can report is denominated in currency.
    """
    physical = ("wall_ms", "cpu_ms", "gpu_ms", "tokens_in", "tokens_out", "calls", "bytes_egress")
    assert set(DIMS) - set(physical) == {"micros"}
    assert set(physical) - set(DIMS) == set()


def _printed_table(plan) -> dict[str, tuple[str, ...]]:
    """08:2186-2200's *"scopes it is declared at"* column, found by its header and read to the end.

    By header, and not by grepping for rows that start with a dimension name: 08 has a second table
    keyed on the same names -- section 7.4's exhaustion behaviours -- and a grep wide enough to find
    this one finds that one too, which is how a transcription test ends up concluding that
    `bytes_egress` is declared at a scope called `ow`.
    """
    lines = plan.lines(RUNTIME)
    header = next(
        index
        for index, line in enumerate(lines)
        if line.startswith("| `dim` |") and "scopes it is declared at" in line
    )
    rows: dict[str, tuple[str, ...]] = {}
    for line in lines[header + 2 :]:
        if not line.startswith("|"):
            break
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        scopes = tuple(re.findall(r"`([a-z_]+)`", cells[-1]))
        for name in re.findall(r"`([a-z_]+)`", cells[0]):
            rows[name] = scopes
    return rows


def _shipped_policy_scopes(plan) -> dict[str, set[str]]:
    """The scopes 05:1279-1291's shipped `[budget.per_part]` / `[budget.per_unit]` block declares.

    `per_unit`'s `micros` is spelled `micros_base` / `micros_per_part` / `micros_max` because
    05:2522 scales it by `part_count`; all three are one cap on one dimension, so the prefix is
    what this reads.
    """
    lines = plan.lines(ROUTING)
    start = next(i for i, line in enumerate(lines) if line.startswith("[budget.per_part]"))
    out: dict[str, set[str]] = {}
    scope = ""
    for line in lines[start:]:
        if line.startswith("[budget.per_part]"):
            scope = "part"
        elif line.startswith("[budget.per_unit]"):
            scope = "unit"
        elif line.startswith("["):
            break
        elif "=" in line and scope:
            key = line.split("=", 1)[0].strip()
            for dim in DIMS:
                if key == dim or key.startswith(f"{dim}_"):
                    out.setdefault(dim, set()).add(scope)
    return out


def test_the_dimension_scope_table_is_the_plans_table_unioned_with_the_shipped_policy(
    plan,
) -> None:
    """**D142**: 08:2186's column and 05:1279's shipped policy disagree about four dimensions.

    Neither source is guessed at -- both are read here -- and `DIM_SCOPES` is asserted to be exactly
    their union, with the four additions named. A defect resolved by widening a table is one line
    away from a defect resolved by inventing one, and this is the test that keeps them apart: no
    scope reaches `DIM_SCOPES` unless one of the two documents puts it there.
    """
    plan.require()
    printed = _printed_table(plan)
    shipped = _shipped_policy_scopes(plan)

    assert set(printed) == set(DIMS), "the plan's table covers all eight"
    assert printed["tokens_out"] == printed["tokens_in"], "08:2192 pairs them on one row"
    assert shipped == {
        "micros": {"part", "unit"},
        "tokens_out": {"part"},
        "calls": {"part"},
        "gpu_ms": {"part"},
        "wall_ms": {"unit"},
        "bytes_egress": {"unit"},
    }

    for dim in DIMS:
        assert set(DIM_SCOPES[dim]) == set(printed[dim]) | shipped.get(dim, set()), dim

    additions = {
        dim: set(DIM_SCOPES[dim]) - set(printed[dim])
        for dim in DIMS
        if set(DIM_SCOPES[dim]) != set(printed[dim])
    }
    assert additions == {
        "calls": {"part"},
        "gpu_ms": {"part"},
        "wall_ms": {"unit"},
        "bytes_egress": {"unit"},
    }


def test_the_two_sites_that_depend_on_calls_being_a_per_part_cap(plan) -> None:
    """D142's evidence beyond the policy file: two worked passages are false without it.

    02:563's admission trace reserves `calls` and `gpu_ms` against `[budget.per_part]` beside
    `micros` at `scope='part'`, and 05:2489 concludes that *"what binds first on this pricebook is
    `[budget.per_part] calls = 3`"*. Both are sentences about a per-part `calls` reservation.
    """
    plan.require()
    trace = plan.grep(r"`\[budget\.per_part\]` `micros = 6_000`", documents=["02-architecture.md"])
    assert trace, "02:563's admission trace reserves four dimensions against [budget.per_part]"
    assert "scope='part'" in trace[0].text
    assert "dim='calls'" in trace[0].text
    assert "dim='gpu_ms'" in trace[0].text

    binds = plan.grep(r"`\[budget\.per_part\] calls = 3`", documents=[ROUTING])
    assert binds, "05 names the per-part calls cap in prose as well as in the shipped policy"

    assert "part" in DIM_SCOPES["calls"]
    assert "part" in DIM_SCOPES["gpu_ms"]


def test_every_declared_scope_is_one_of_the_six() -> None:
    """`DIM_SCOPES` may narrow the DDL's domain and may never widen it."""
    for dim, scopes in DIM_SCOPES.items():
        assert dim in DIMS
        assert set(scopes) <= set(SCOPES), dim
        assert scopes, f"{dim} is declared at no scope at all"


def test_calls_is_declared_at_provider_first() -> None:
    """08:2196 -- *"a held `(dim='calls', scope='provider')` sum IS the cross-process in-flight
    count"*. It is the only dimension whose first scope is not `run`, because at `provider` it is a
    concurrency limit rather than a cost limit, and 08:700 says why that cannot be a semaphore:
    *"two scheduler processes each holding an in-memory semaphore of 2 show the provider 4."*
    """
    assert DIM_SCOPES["calls"][0] == "provider"
    assert "provider" not in {
        scope for dim, scopes in DIM_SCOPES.items() if dim != "calls" for scope in scopes
    }


def test_the_p95_multiple_applies_to_two_dimensions_and_the_plan_names_both(plan) -> None:
    """05:2470-2473. `gpu_ms` is the subtle member and the plan argues for it explicitly."""
    plan.require()
    assert OUTPUT_PROPORTIONAL == ("tokens_out", "gpu_ms")
    assert plan.grep(
        r"p95 multiple applies to `gpu_ms` as well as `tokens_out`", documents=[ROUTING]
    )
    assert set(INPUT_PROPORTIONAL) == {"tokens_in", "calls", "bytes_egress"}
    assert set(OUTPUT_PROPORTIONAL).isdisjoint(INPUT_PROPORTIONAL)


def test_uncapped_is_not_zero_because_zero_is_a_real_cap() -> None:
    """`bytes_egress` defaults to **0** (08:2202), so "no cap" needs a value 0 is not."""
    assert UNCAPPED < 0
    assert UNCAPPED != 0


# ---------------------------------------------------------------------------------------------
# 2. `reservation_id` -- content-addressed over four values, and all four matter
# ---------------------------------------------------------------------------------------------


def test_a_reservation_id_is_the_prefix_plus_twenty_four_hex() -> None:
    """08:2236 -- `'res_' || sha256_canonical(identity)[:24]`."""
    value = reservation_id(7, "dec_p3", 1, "micros")
    assert value.startswith(RESERVATION_ID_PREFIX)
    assert len(value) == len(RESERVATION_ID_PREFIX) + RESERVATION_ID_BODY_LEN
    assert re.fullmatch(r"res_[0-9a-f]{24}", value)


def test_four_dimensions_of_one_attempt_are_four_distinct_rows() -> None:
    """08:2248 -- without `dim` in the identity, *"four dimensions would collide on one id and
    three of them would silently not be reserved"*. The failure is silent because `INSERT OR
    IGNORE` is what makes a retried reserve idempotent: three collisions would be three no-ops.
    """
    ids = {
        reservation_id(7, "dec_p3", 1, dim)
        for dim in ("micros", "tokens_in", "tokens_out", "calls")
    }
    assert len(ids) == 4


def test_a_retried_reserve_is_the_same_id_and_a_second_attempt_is_not() -> None:
    """Both halves of 08:2238, which pull in opposite directions."""
    assert reservation_id(7, "d", 1, "micros") == reservation_id(7, "d", 1, "micros")
    assert reservation_id(7, "d", 2, "micros") != reservation_id(7, "d", 1, "micros")
    assert reservation_id(8, "d", 1, "micros") != reservation_id(7, "d", 1, "micros")
    assert reservation_id(7, "e", 1, "micros") != reservation_id(7, "d", 1, "micros")


def test_an_id_refuses_a_dim_outside_the_domain_and_a_zero_attempt() -> None:
    """An id minted for `'gpu'` would insert a row the CHECK then rejects mid-transaction."""
    with pytest.raises(ValueError, match="eight dims"):
        reservation_id(7, "d", 1, "gpu")
    with pytest.raises(ValueError, match="1-based"):
        reservation_id(7, "d", 0, "micros")


# ---------------------------------------------------------------------------------------------
# 3. The p95 ceiling and the scope key
# ---------------------------------------------------------------------------------------------


def test_only_the_output_proportional_dimensions_are_scaled() -> None:
    """05:2461-2473. An input-proportional dimension is *"known before the call"*, so it is flat."""
    assert reserved_amount(1_100, "tokens_out", P95_MULTIPLE) == 3_520
    assert reserved_amount(2_400, "gpu_ms", P95_MULTIPLE) == 7_680
    for dim in INPUT_PROPORTIONAL:
        assert reserved_amount(1_000, dim, P95_MULTIPLE) == 1_000
    assert reserved_amount(6_000, "micros", P95_MULTIPLE) == 6_000


def test_the_ceiling_rounds_up_and_never_down() -> None:
    """08:2251 -- *"a reservation that under-estimates admits work the budget cannot pay for."*"""
    assert reserved_amount(1, "tokens_out", 1.5) == 2
    assert reserved_amount(3, "tokens_out", 1.1) == 4
    assert reserved_amount(0, "tokens_out", 9.0) == 0
    for declared in range(1, 40):
        assert reserved_amount(declared, "gpu_ms", P95_MULTIPLE) >= declared * P95_MULTIPLE


def test_a_multiple_below_one_is_refused_rather_than_clamped() -> None:
    """A `[cost.model]` that declared 0.8 would reserve less than its own estimate."""
    with pytest.raises(ValueError, match=r"below 1\.0"):
        reserved_amount(100, "tokens_out", 0.8)
    assert reserved_amount(100, "tokens_out", 1.0) == 100


def test_the_part_scope_key_carries_the_unit_so_two_documents_do_not_share_a_budget() -> None:
    """05:2523's grain, executed: a bare `'p3'` would pool page 3 of every document."""
    assert scope_key_for("part", unit_uri="file:///a.pdf", unit_part="p3") == "file:///a.pdf#p3"
    assert scope_key_for("part", unit_uri="file:///b.pdf", unit_part="p3") != scope_key_for(
        "part", unit_uri="file:///a.pdf", unit_part="p3"
    )
    assert scope_key_for("unit", unit_uri="file:///a.pdf") == "file:///a.pdf"
    assert scope_key_for("provider", provider="parasail") == "parasail"


def test_two_lanes_on_one_part_have_two_budgets() -> None:
    """05:2523, the other half of the same sentence: *"per-part dimensions are charged per
    `(unit_part, lane)`: two lanes on one part have two budgets."*

    Without the lane the `text` and `table` passes over page 3 share one cap, so the lane that ran
    second is denied against headroom the first is still holding -- on a policy that declared a
    budget per lane. The un-laned key is unchanged, because a `part`-scoped reservation for work
    that has no lane is legitimate.
    """
    text = scope_key_for("part", unit_uri="file:///a.pdf", unit_part="p3", lane="text")
    table = scope_key_for("part", unit_uri="file:///a.pdf", unit_part="p3", lane="table")
    assert text == "file:///a.pdf#p3/text"
    assert text != table
    assert scope_key_for("part", unit_uri="file:///a.pdf", unit_part="p3") == "file:///a.pdf#p3"
    assert scope_key_for("unit", unit_uri="file:///a.pdf", lane="text") == "file:///a.pdf"


def test_an_empty_scope_key_is_refused_because_it_pools_every_scope() -> None:
    """The column is `TEXT NOT NULL DEFAULT ''`, so the database would take it happily."""
    with pytest.raises(ValueError, match="shares headroom"):
        scope_key_for("run", run_id="")
    with pytest.raises(ValueError, match="six scopes"):
        scope_key_for("session", run_id="r_1")


# ---------------------------------------------------------------------------------------------
# 4. `Reservation` -- the row, and the one rule the DDL cannot express
# ---------------------------------------------------------------------------------------------


def test_a_reservation_is_the_tables_columns_in_the_tables_order() -> None:
    """0004_runtime.sql:222-235, read out of the shipped migration."""
    columns = tuple(re.findall(r"^\s{2}(\w+)", TABLE, flags=re.M))
    assert columns == tuple(field.name for field in fields(Reservation))


def test_an_undeclared_dimension_scope_pair_is_refused_here_because_sqlite_cannot() -> None:
    """The two CHECKs are independent, so `(dim='wall_ms', scope='part')` is valid SQL.

    08:2194 declares `wall_ms` at `run` and nowhere smaller. A row at an undeclared pair holds
    headroom against a limit nothing will ever configure, and -- because the reaper reaches only
    reservations whose work row is still `claimed` -- nothing releases it after the row settles.
    """
    with pytest.raises(ValueError, match="declares 'wall_ms'"):
        Reservation(
            reservation_id="res_x",
            run_id="r",
            work_id=1,
            decision_id="d",
            dim="wall_ms",
            amount=1,
            scope="part",
            scope_key="file:///a#p1",
            claimed_gen=1,
            expires_ms=1,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("dim", "gpu", "not one of"),
        ("scope", "session", "not one of"),
        ("state", "pending", "not one of"),
        ("amount", -1, "not a quantity"),
        ("scope_key", "", "scope_key is what"),
    ],
)
def test_the_constructor_refuses_what_the_column_would_take(
    field: str, value: object, match: str
) -> None:
    """Each of the five is a value SQLite accepts or a CHECK reports without naming the offence."""
    with pytest.raises(ValueError, match=match):
        replace(_reservation(), **{field: value})


def test_a_reservation_starts_held_and_its_params_are_the_statements_binds() -> None:
    """One mapping, so `RESERVE_SQL`'s named parameters and the row cannot drift apart."""
    row = _reservation()
    assert row.state == "held"
    bound = set(re.findall(r":(\w+)", RESERVE_SQL))
    assert bound == set(row.as_params())


# ---------------------------------------------------------------------------------------------
# 5. The statements
# ---------------------------------------------------------------------------------------------


def test_the_headroom_statement_is_the_plans_own(plan) -> None:
    """08:2226-2233, compared with whitespace normalised so only the SQL is asserted.

    The plan prints it inside a ```sql fence with a comment line above it; this strips the comment
    and collapses runs of whitespace, which leaves exactly the statement. A test that compared
    character for character would fail on an indentation change that means nothing.
    """
    plan.require()
    fences = [
        body
        for body in plan.fences(RUNTIME, "sql")
        if "COALESCE" in body and "SELECT :limit" in body
    ]
    assert len(fences) == 1, "08 prints the headroom statement once"
    printed = " ".join(line for line in fences[0].split("\n") if not line.strip().startswith("--"))
    assert " ".join(printed.split()).rstrip(";") == " ".join(HEADROOM_SQL.split())


def test_headroom_subtracts_both_held_and_committed() -> None:
    """I29's arithmetic. A committed row has been spent and still consumes the cap."""
    assert HEADROOM_SQL.count("state='held'") == 1
    assert HEADROOM_SQL.count("state='committed'") == 1
    assert HEADROOM_SQL.count("COALESCE") == 2, "SUM over no rows is NULL, and NULL admits"


def test_the_reserve_statement_is_insert_or_ignore() -> None:
    """08:2238's *"a retried reserve is idempotent"* needs more than a content-addressed key.

    A bare `INSERT` on a duplicate primary key raises; idempotence is `OR IGNORE`. 08:428's
    mechanism 2 states the converse trap -- *"`INSERT OR IGNORE` with no UNIQUE index to conflict
    on is a plain `INSERT`"* -- and `reservation_id` is the PRIMARY KEY, so there is one.
    """
    assert "INSERT OR IGNORE INTO budget_reservation" in RESERVE_SQL
    assert "reservation_id TEXT PRIMARY KEY" in TABLE


@pytest.mark.parametrize("sql", [COMMIT_SQL, RELEASE_SQL])
def test_a_transition_only_moves_a_held_row(sql: str) -> None:
    """`AND state='held'` is the same shape as the work transition's commit predicate.

    Without it a late result from a superseded generation could rewrite a settled amount, and a
    double-commit would double-count. With it, both update zero rows and the caller reads which.
    """
    assert "state='held'" in sql
    assert "WHERE reservation_id=:reservation_id" in sql


def test_the_commit_sets_the_actual_amount_which_is_how_the_gap_is_released() -> None:
    """05:2537. Headroom is `limit - held - committed`, so lowering `amount` IS the release.

    There is no second statement for the over-reservation, and a test that asserted one existed
    would be asking for the double-release that would lift a denial twice.
    """
    assert "SET state='committed', amount=:amount" in COMMIT_SQL
    assert "amount" not in RELEASE_SQL


def test_the_reap_is_not_here_and_the_pointer_names_something_real() -> None:
    """08:2244's fifth statement lives in `work.py`, inside the reap's own transaction.

    A second reap keyed on `expires_ms` would be a second home for one rule, and the two would
    disagree the first time a lease was extended.
    """
    assert RESERVATION_REAP == "omniweave_core.work.REAP_RESERVATIONS_SQL"
    module, _, name = RESERVATION_REAP.rpartition(".")
    assert module == "omniweave_core.work"
    assert hasattr(work, name)
    assert "budget_reservation" in getattr(work, name)
    statements = [
        value
        for name, value in vars(budget).items()
        if name.endswith("_SQL") and isinstance(value, str)
    ]
    assert statements
    assert not [sql for sql in statements if "expires_ms <" in sql], (
        "the expiry predicate has one home and it is work.py's"
    )


# ---------------------------------------------------------------------------------------------
# 6. The boundary
# ---------------------------------------------------------------------------------------------


def test_the_ledger_has_the_four_calls_the_module_table_names(plan) -> None:
    """02-architecture.md row 19's *"typical call"* column, read out of the plan.

    The row prints `BudgetLedger.reserve/commit/release/headroom`, which is four names and no
    fifth: a ledger that grew a `sweep()` or a `limits()` would be doing something the module's
    exclusion column gives to someone else.
    """
    plan.require()
    row = plan.grep(r"`BudgetLedger\.reserve", documents=["02-architecture.md"])
    assert len(row) == 1
    named = set(re.findall(r"reserve/commit/release/headroom", row[0].text))
    assert named, "02 row 19 names the four calls"

    declared = {
        name
        for name, value in vars(BudgetLedger).items()
        if callable(value) and not name.startswith("_")
    }
    assert declared == {"reserve", "commit", "release", "headroom"}


def test_the_ledger_is_synchronous_because_run_context_lives_in_core() -> None:
    """08:315-317's third reason. An `async def` here would move `RunContext` out of core."""
    source = Path(inspect.getfile(budget)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef)]
    assert "asyncio" not in source.split('"""')[-1]


def test_this_module_executes_nothing() -> None:
    """`work.py`'s boundary, one module over: statements and decisions, never a connection."""
    source = Path(inspect.getfile(budget)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "sqlite3" not in imported
    assert imported <= {
        "collections",
        "dataclasses",
        "types",
        "typing",
        "omniweave_core",
        "__future__",
    }
