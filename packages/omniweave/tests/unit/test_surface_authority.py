"""`omniweave.surface.authority` -- 10 section 3.8's four mechanisms, and SV1 over their output.

`assert_sv1()` has had tests since W7.1 and they pass it two hand-written collections. What had
never been tested is where those collections come from, which is where every gap in this file is:
a precedence ladder with four rungs, two spellings per entry, three presets, an additive operator
that shares a character with one of the presets, and an invariant that refuses the whole server
when the two halves disagree.

The centrepiece is `test_following_the_plans_own_fix_breaches_sv1`. 10:797 gives the dispatch
refusal a fix instruction, and carrying it out makes the next start fail. That test is the proof
rather than the assertion, which is why it runs the fix rather than describing it.

**Every test here is pure.** `resolve()` takes the config values and the environment as arguments,
so there is no `monkeypatch.setenv` in this file and no process to start: the environment is a dict
and the config is two parameters.
"""

from __future__ import annotations

import ast
from pathlib import Path

import omniweave.surface.authority as authority_module
import pytest
from omniweave.surface.authority import (
    ADDITIVE,
    ALL,
    ENABLED_ENV,
    ENABLED_KEY,
    LISTED_ENV,
    LISTED_KEY,
    NEAREST,
    PRESETS,
    PROFILE_KEY,
    READ_ONLY,
    READ_ONLY_ADD,
    Resolution,
    agent_reachable,
    entries,
    human_only_named,
    nearest,
    normalise,
    preset,
    refusal,
    resolve,
)
from omniweave.surface.registry import ACTIONS, HUMAN_ONLY, PROFILES, listed
from omniweave_core.config import ENV_OVERRIDES, KEYS
from omniweave_core.errors import UsageError, edit_distance

# The four listed Actions, which every narrow configuration below still has to grant, because
# `read_only+add` is the shipped default and SV1 forbids listing more than is enabled.
FRONT = ("add", "corpora", "open", "query")


def _granting(*names: str) -> list[str]:
    """A `[serve] enabled` value narrow enough that SV1 can be made to bite.

    Needed because the shipped registry makes the invariant invisible: nine Actions, eight of them
    read-only and the ninth `add`, so `read_only+add` happens to equal `all` and no default
    configuration can fail. See `test_the_shipped_registry_masks_sv1` and D380.
    """
    return list(names)


# =============================================================================================
# 1. The precedence ladder
# =============================================================================================


def test_the_default_resolution_is_the_front_door_inside_read_only_plus_add() -> None:
    """Nothing set: `[serve] profile` is `default`, `[serve] enabled` is `read_only+add`, and the
    result is the four listed tools inside an authority that grants the nine addressable Actions.
    This is what an operator who edited nothing is running."""
    resolved = resolve()
    assert resolved.listed == FRONT
    assert resolved.enabled == preset(READ_ONLY_ADD)
    assert resolved.profile == "default"


def test_the_profile_is_the_lowest_rung() -> None:
    """10:780's bottom row. `listed()` owns the roster and this owns only the selection of it."""
    assert resolve(profile="full").listed == tuple(listed("full"))
    assert resolve(profile="default").listed == tuple(listed("default"))


def test_serve_listed_overrides_the_profile() -> None:
    """10:780's middle row: *"an explicit list, overriding the profile"* -- overriding, not adding,
    so a deployment that names two tools gets two and not two plus the profile's four."""
    resolved = resolve(listed_key=["doc.grid"], enabled_key=_granting("doc.grid"))
    assert resolved.listed == ("doc.grid",)
    assert resolved.listed_from == "[serve] listed"


def test_the_env_var_overrides_serve_listed() -> None:
    """The top rung of the listing half. A user debugging one session beats the deployment."""
    resolved = resolve(
        listed_key=["doc.grid"],
        enabled_key=_granting("doc.grid", "doc.diff"),
        env={LISTED_ENV: "doc.diff"},
    )
    assert resolved.listed == ("doc.diff",)
    assert resolved.listed_from == LISTED_ENV


def test_the_env_var_overrides_serve_enabled() -> None:
    """The top rung of the authority half, and the one that matters: an operator granting authority
    beats the file. 10:780 gives both env vars the highest precedence and this is the second."""
    resolved = resolve(enabled_key=_granting("query"), env={ENABLED_ENV: ALL})
    assert resolved.enabled == agent_reachable()
    assert resolved.enabled_from == ENABLED_ENV


def test_every_rung_names_itself() -> None:
    """A server that cannot say which key produced its surface makes every listing question a
    bisection, so the mechanism is carried rather than reconstructed."""
    assert resolve().listed_from == "[serve] profile=default"
    assert resolve(profile="full").listed_from == "[serve] profile=full"
    assert resolve(enabled_key=_granting(*FRONT)).enabled_from == "[serve] enabled"
    assert resolve().enabled_from == "[serve] enabled default"


def test_enabled_resolves_before_listed() -> None:
    """10:785's ordering, observed rather than asserted: a listing that only the env-var authority
    permits resolves cleanly, which it could not if `listed` were computed against the file."""
    resolved = resolve(
        enabled_key=_granting("query"),
        env={ENABLED_ENV: ALL, LISTED_ENV: "doc.grid"},
    )
    assert resolved.listed == ("doc.grid",)
    assert "doc.grid" in resolved.enabled


# =============================================================================================
# 2. Both spellings
# =============================================================================================


@pytest.mark.parametrize("spelling", ["doc.grid", "ow_grid"])
def test_both_spellings_resolve_to_the_action_name(spelling: str) -> None:
    """10:790: *"Both accept the bare Action name (`route.explain`) and the MCP name
    (`ow_route_explain`)"*. `assert_sv1()`'s docstring depends on this happening before it runs."""
    assert normalise(spelling) == "doc.grid"


@pytest.mark.parametrize("variable", [LISTED_ENV, ENABLED_ENV])
def test_both_variables_take_both_spellings(variable: str) -> None:
    """The normalisation is the resolver's and not each variable's, so neither can drift."""
    resolved = resolve(
        enabled_key=_granting("doc.grid", *FRONT),
        env={variable: "ow_grid" if variable == LISTED_ENV else f"ow_grid,{ALL}"},
    )
    assert "doc.grid" in (resolved.listed if variable == LISTED_ENV else resolved.enabled)


def test_an_unknown_name_is_none_rather_than_a_guess() -> None:
    """`normalise()` never guesses. The suggestion is a separate function so a caller cannot get a
    near match where it asked for an identity."""
    assert normalise("ow_nonesuch") is None
    assert normalise("route.explain") is None, "not in this build's registry; nine Actions exist"


# =============================================================================================
# 3. The presets
# =============================================================================================


def test_the_three_presets_are_the_plans_three() -> None:
    """10:780's row, and `KEYS['serve.enabled'].choices` carries the same three. Two homes for
    three strings, bound here rather than left to agree by habit."""
    assert PRESETS == (ALL, READ_ONLY, READ_ONLY_ADD)
    assert set(PRESETS) == set(KEYS[ENABLED_KEY].choices)


def test_all_is_every_addressable_action_and_not_every_action() -> None:
    """Forced by SV1's second clause rather than chosen: an `all` that included `HUMAN_ONLY` would
    make its own preset a startup error, and 10:858 grants `ow_ingest` through `enabled = "all"`."""
    granted = preset(ALL)
    assert granted == agent_reachable()
    assert granted is not None and granted & HUMAN_ONLY == frozenset()


def test_read_only_plus_add_is_read_only_and_add() -> None:
    """10:842: *"the shipped `[serve] enabled = "read_only+add"` grants exactly the read-only
    Actions plus `add`"*. It is the sentence the `full` roster's read-only-ness is forced by."""
    read_only = preset(READ_ONLY)
    assert read_only is not None
    assert preset(READ_ONLY_ADD) == read_only | {"add"}
    assert "add" not in read_only, "add writes; it is in the preset by name, not by its bit"


def test_a_non_preset_is_none_rather_than_an_empty_set() -> None:
    """An empty set would make an unknown preset grant nothing silently, which is the failure a
    named refusal exists to avoid."""
    assert preset("readonly") is None
    assert preset("") is None


def test_the_shipped_registry_masks_sv1() -> None:
    """The reason every narrow test in this file passes `enabled_key` by hand.

    Nine Actions, eight read-only and the ninth `add`, so `read_only+add` and `all` are the same
    set and **no default configuration can breach SV1**. That is a property of an incomplete
    registry and not of the design, and it will stop being true the moment a writer with an
    `mcp_name` lands -- `ow_ingest` is 10:858's named example. D380."""
    assert preset(READ_ONLY_ADD) == preset(ALL)
    assert all(ACTIONS[name].read_only or name == "add" for name in agent_reachable())


# =============================================================================================
# 4. The collision, and the additive operator
# =============================================================================================


def test_the_preset_name_wins_over_the_additive_reading() -> None:
    """`read_only+add` is a preset name containing the additive operator, and `add` is a real
    Action name, so the string parses two ways. Exact preset match is checked first. D377."""
    resolved = resolve(enabled_key=READ_ONLY_ADD)
    assert resolved.enabled == preset(READ_ONLY_ADD)


def test_the_two_roads_to_the_same_set_agree() -> None:
    """`read_only+add` as a preset and `read_only,+add` through the grammar reach one set. They
    agree by arithmetic rather than by rule, which is the only reason the collision is survivable
    and is exactly why it should still be spelled out of existence. D377."""
    by_preset = resolve(env={ENABLED_ENV: READ_ONLY_ADD}).enabled
    by_grammar = resolve(env={ENABLED_ENV: f"{READ_ONLY},add"}).enabled
    assert by_preset == by_grammar


def test_the_additive_form_adds_to_the_profiles_set() -> None:
    """10:781's own words, in the case it describes: nothing else is set, so the base is the
    profile's four and `+doc.grid` makes five."""
    resolved = resolve(env={LISTED_ENV: f"{ADDITIVE}doc.grid"})
    assert resolved.listed == tuple(sorted((*FRONT, "doc.grid")))


def test_the_additive_base_is_the_rung_below_and_not_always_the_profile() -> None:
    """D379. 10:781 says *"adds to the profile's set"*, which would make an explicit `[serve]
    listed` invisible to a single `+` one level up -- an override discarded by one character.

    This asserts the composing reading: with `[serve] listed = ["doc.diff"]`, `+doc.grid` gives two
    and not the profile's four plus one."""
    resolved = resolve(
        listed_key=["doc.diff"],
        enabled_key=_granting("doc.diff", "doc.grid"),
        env={LISTED_ENV: f"{ADDITIVE}doc.grid"},
    )
    assert resolved.listed == ("doc.diff", "doc.grid")
    assert "query" not in resolved.listed, "the profile would have brought it; the override did not"


def test_a_bare_entry_beside_an_additive_one_replaces() -> None:
    """A value that both replaced and added would make the order of two entries significant, and
    nothing declares an order. So a bare name replaces the base and a `+` name joins the result."""
    resolved = resolve(
        enabled_key=_granting("doc.diff", "doc.grid", *FRONT),
        env={LISTED_ENV: f"doc.diff,{ADDITIVE}doc.grid"},
    )
    assert resolved.listed == ("doc.diff", "doc.grid")


def test_the_additive_form_is_not_honoured_by_the_enabled_variable() -> None:
    """D378. 10:780 defines `+name` on the `listed` row as adding *"to the profile's set"*, and
    `enabled` has no profile to add to. The entry is treated as a name, so an operator reaching for
    it is told so rather than being silently granted or silently ignored."""
    with pytest.raises(UsageError, match=r"is not an Action"):
        resolve(env={ENABLED_ENV: f"{ADDITIVE}doc.grid"})


# =============================================================================================
# 5. SV1
# =============================================================================================


def test_listing_more_than_is_enabled_refuses_the_start() -> None:
    """SV1 clause 1. 10:787 forbids a repair-and-continue path, because *"a server that quietly
    narrowed its own listing would disagree with the `llms.txt` it ships"*."""
    with pytest.raises(UsageError, match=r"SV1") as caught:
        resolve(enabled_key=_granting("query"), env={LISTED_ENV: "doc.grid"})
    assert "doc.grid" in str(caught.value)


def test_the_sv1_refusal_names_both_keys() -> None:
    """10:786: *"a startup error naming both keys and the offending Action"*. `assert_sv1()` owns
    the message; this asserts the resolver routes into it rather than pre-empting it."""
    with pytest.raises(UsageError) as caught:
        resolve(enabled_key=_granting("query"), env={LISTED_ENV: "doc.grid"})
    assert "listed" in str(caught.value)
    assert "enabled" in str(caught.value)
    assert ENABLED_ENV in (caught.value.fix or "")


def test_following_the_plans_own_fix_breaches_sv1() -> None:
    """**D376, proved rather than asserted.** 10:797 gives the dispatch refusal this fix:

        `OW-A-003 / OW_TOOL_NOT_LISTED` -- naming the config key *and* the env var that would
        list it

    An Action that is refused is one `enabled` does not grant. Adding it to the **listing** keys,
    which is what that sentence instructs, makes `listed` exceed `enabled`, and the next start
    fails. 10:799 criticises codegraph two lines later for a refusal that is *"a dead end rather
    than a fix instruction"*; this one is worse, because it is a fix instruction that bricks.
    """
    deployment = _granting(*FRONT)
    assert "doc.grid" not in resolve(enabled_key=deployment).enabled

    # The operator does exactly what the plan's refusal tells them to.
    with pytest.raises(UsageError, match=r"SV1"):
        resolve(enabled_key=deployment, env={LISTED_ENV: f"{ADDITIVE}doc.grid"})


def test_the_shipped_refusal_names_the_enabling_pair_instead() -> None:
    """The other half of D376: what `refusal()` says instead, and that following IT works.

    18:1443 requires the message to name *"the config key **and** the env var that would change the
    answer"*, so both are present -- and the answer they change is the one that was wrong."""
    deployment = _granting(*FRONT)
    resolved = resolve(enabled_key=deployment)
    refused = refusal("doc.grid", resolved)

    assert refused.code() == "OW_TOOL_NOT_LISTED", "10:797's symbol is kept"
    assert "enabled" in (refused.fix or "")
    assert ENABLED_ENV in (refused.fix or "")
    assert LISTED_ENV not in (refused.fix or ""), "the listing keys are what D376 is about"

    # Following the shipped fix resolves cleanly and serves the Action.
    after = resolve(enabled_key=deployment, env={ENABLED_ENV: f"{','.join(deployment)},doc.grid"})
    assert after.serves("doc.grid")


def test_listed_all_is_ordinary_in_the_prose_and_a_startup_error_in_the_invariant() -> None:
    """D380. 10:855 presents `OMNIWEAVE_MCP_LISTED=all` as a thing a user does -- *"A user who sets
    `OMNIWEAVE_MCP_LISTED=all` still gets a surface whose narrow Actions point back at the
    composite"* -- and SV1 makes it a startup error under any `enabled` narrower than everything.

    It passes on the shipped registry only because `read_only+add` happens to equal `all` there."""
    assert resolve(env={LISTED_ENV: ALL}).listed == tuple(sorted(agent_reachable()))
    with pytest.raises(UsageError, match=r"SV1"):
        resolve(enabled_key=_granting(*FRONT), env={LISTED_ENV: ALL})


def test_the_human_only_clause_fires_on_the_first_human_only_row() -> None:
    """SV1's second clause could not fire while none of `HUMAN_ONLY`'s five was an Action; this
    test announced the day one landed by failing, and `uninstall` is that day (W7.5h). Naming it
    in an enabled variable is now refused by name, and `query` beside it is not."""
    assert HUMAN_ONLY & set(ACTIONS) == frozenset({"uninstall"})
    assert human_only_named(["uninstall", "query"]) == ("uninstall",)


# =============================================================================================
# 6. Unknown entries
# =============================================================================================


def test_an_unknown_entry_is_refused_with_near_matches() -> None:
    """10:790: *"reports an unknown entry as `OW-A-004 / OW_ACTION_NOT_ENABLED` listing near
    matches by edit distance"*. Both halves are asserted: the symbol and the help."""
    with pytest.raises(UsageError) as caught:
        resolve(env={ENABLED_ENV: "ow_queyr"})
    assert caught.value.code() == "OW_ACTION_NOT_ENABLED"
    assert "ow_query" in str(caught.value)


def test_the_refusal_names_which_of_the_four_mechanisms_carried_it() -> None:
    """An operator holding two variables and a config file needs to know which one to edit, and a
    message that named only the typo would leave three places to look."""
    with pytest.raises(UsageError, match=LISTED_ENV):
        resolve(env={LISTED_ENV: "nonesuch"})
    with pytest.raises(UsageError, match=ENABLED_ENV):
        resolve(env={ENABLED_ENV: "nonesuch"})
    with pytest.raises(UsageError, match=r"\[serve\] listed"):
        resolve(listed_key=["nonesuch"])


def test_the_suggestions_come_back_in_the_spelling_that_was_asked() -> None:
    """Suggesting `doc.grid` to somebody who typed `ow_gird` is a worse answer than `ow_grid`, so
    an `ow_`-shaped entry is ranked against `mcp_name`s and a bare one against Action names."""
    assert all(name.startswith("ow_") for name in nearest("ow_gird"))
    assert not any(name.startswith("ow_") for name in nearest("doc.gird"))


def test_the_suggestions_are_ranked_by_edit_distance_and_not_by_ratio() -> None:
    """One metric, one implementation: `omniweave_core.errors.edit_distance`, which `explain()`
    ranks `codes.toml` with. Two implementations would rank one typo differently in two refusals a
    user can meet in a single session -- `admission.percentile`'s D346 without the layers row that
    forced it."""
    ranked = nearest("ow_gird")
    distances = [edit_distance("ow_gird", name) for name in ranked]
    assert distances == sorted(distances)
    assert len(ranked) == NEAREST


def test_the_near_match_count_is_the_registers_count() -> None:
    """Three, because 18:232 fixes three for `codes.toml` and a second count here would make two
    registers disagree about how much help a typo earns."""
    assert NEAREST == 3


# =============================================================================================
# 7. `entries()`
# =============================================================================================


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a,b", ("a", "b")),
        ("a, b ", ("a", "b")),
        ("a,,b", ("a", "b")),
        ("", ()),
        (["a", "b"], ("a", "b")),
        ([" a "], ("a",)),
        ([], ()),
        (None, ()),
    ],
)
def test_entries_splits_and_strips(value: object, expected: tuple[str, ...]) -> None:
    """One grammar for a scalar and a list, because both spell the same axis and a resolver that
    treated them differently would make a TOML edit and an env var disagree."""
    assert entries(value) == expected  # type: ignore[arg-type]


def test_an_unset_variable_and_an_empty_one_are_different() -> None:
    """`None` falls through to the rung below; an empty value is a deliberate empty listing. A
    resolver that conflated them would make `OMNIWEAVE_MCP_LISTED=` silently restore the profile."""
    assert resolve(env={LISTED_ENV: ""}).listed == ()
    assert resolve().listed == FRONT


# =============================================================================================
# 8. What a `Resolution` answers
# =============================================================================================


def test_an_unlisted_action_is_still_served() -> None:
    """10:795, which is the consequence the whole two-key design exists for: *"an unlisted Action is
    still served, and is never refused for being unlisted."*"""
    resolved = resolve()
    assert resolved.serves("doc.grid")
    assert not resolved.shows("doc.grid")


def test_listed_is_always_a_subset_of_enabled() -> None:
    """SV1 as a property of every resolution that returns at all, rather than of the one call that
    checks it."""
    for kwargs in (
        {},
        {"profile": "full"},
        {"env": {LISTED_ENV: ALL}},
        {"env": {ENABLED_ENV: ALL}},
        {"listed_key": ["query"]},
    ):
        resolved = resolve(**kwargs)  # type: ignore[arg-type]
        assert set(resolved.listed) <= resolved.enabled


def test_the_listing_is_sorted_and_the_resolution_is_frozen() -> None:
    """Sorted because 10:229 bans iteration over an unsorted set anywhere a generated artefact can
    see; frozen because a caller that mutated a resolution would move the surface after SV1."""
    resolved = resolve(profile="full")
    assert list(resolved.listed) == sorted(resolved.listed)
    with pytest.raises(AttributeError):
        resolved.profile = "default"  # type: ignore[misc]


def test_a_bad_profile_is_refused_by_name() -> None:
    """The one rung with a closed vocabulary, refused with both members printed."""
    with pytest.raises(UsageError, match=r"is not a profile"):
        resolve(profile="verbose")


# =============================================================================================
# 9. The bindings
# =============================================================================================


def test_the_two_env_var_names_are_the_config_registrys_two_twins() -> None:
    """D327 is what this prevents: `assert_sv1()`'s own fix string once named a variable the config
    loader did not read. Both spellings now come from one mapping or fail here."""
    assert ENV_OVERRIDES[LISTED_KEY] == LISTED_ENV
    assert ENV_OVERRIDES[ENABLED_KEY] == ENABLED_ENV


def test_the_three_config_keys_exist_in_the_registry() -> None:
    """A resolver naming a key the config registry does not declare would produce a refusal telling
    an operator to edit a line that cannot exist."""
    for key in (PROFILE_KEY, LISTED_KEY, ENABLED_KEY):
        assert key in KEYS


def test_the_profile_vocabulary_is_the_registrys() -> None:
    """`[serve] profile`'s `choices` and `PROFILES` are two homes for two strings."""
    assert set(KEYS[PROFILE_KEY].choices) == set(PROFILES)


def test_all_names_every_public_symbol_and_nothing_else() -> None:
    """Derived from the AST rather than from `vars()`, which would pick up the imports."""
    tree = ast.parse(Path(authority_module.__file__).read_text(encoding="utf-8"))
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
    assert {name for name in defined if not name.startswith("_")} == set(authority_module.__all__)


def test_the_module_holds_no_clock_no_loop_and_no_environment_read() -> None:
    """The shape every module of this phase took: the policy is an object and the ambient state is
    the caller's. `os.environ` read here would make the resolution untestable without a process and
    would make two servers in one interpreter share one surface."""
    source = Path(authority_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "os" not in imported
    assert "environ" not in source.replace("environment", "")


def test_a_resolution_can_be_built_directly_for_a_caller_that_already_has_the_sets() -> None:
    """`Resolution` is a value, so `ow doctor` and a startup log can hold one without re-resolving
    and without the invariant running twice."""
    held = Resolution(
        profile="default",
        enabled=frozenset(FRONT),
        listed=FRONT,
        enabled_from="a test",
        listed_from="a test",
    )
    assert held.serves("query")
    assert held.shows("query")
    assert not held.serves("doc.grid")
