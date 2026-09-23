"""`PreToolUse`: the five gates, the four deny guards, and two strings checked against the plan.

**The load-bearing test is `test_both_shipped_strings_are_the_plans_own_words`.** 10:2034 asks for
*"two shipped strings, from one constant so a deny and a nudge always name the same alternatives"*,
and the plan prints both in full. This suite parses them out of `10-interfaces.md` and compares them
word for word, so a rewording of the advice is a failing test rather than a drift -- the same
treatment `test_hooks_precompact.py` gives the briefing.

The only difference allowed is the example page: the plan writes `#p14` of a 22-page document, which
is illustrative, and this module writes `#p1`, which is the page every indexed document has.

Nothing here opens a store or a filesystem except `tmp_path`, because `decide()` is a pure function
of the gates and the guards -- which is what makes all twelve table rows cheap to assert.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from omniweave.hooks.envelope import DECISION_CHANNEL, DECISION_REASON, DENY, EVENTS, emission
from omniweave.hooks.pretool import (
    CLAIM_SUFFIX,
    DEFAULT_TTL_S,
    ENFORCE,
    ENFORCE_ADVISORY,
    ENFORCE_OFF,
    ENFORCE_STEER,
    HOOK_TTL,
    MIN_SIZE_BYTES,
    OPAQUE_DOC_EXTS,
    Indexed,
    Target,
    advisory_text,
    decide,
    deny_text,
    enforce_mode,
    failing_gate,
    run_pretool,
    ttl_seconds,
    unguarded,
)
from omniweave.hooks.session import CONTROL_DIR, SESSIONS_DIR

if TYPE_CHECKING:
    from collections.abc import Mapping

    from conftest import PlanDocs

FOUND = Indexed(corpus="handbook", version="41", pages=22, blocks=511)
OPAQUE = Target(name="policy.pdf", size=2_100_000, extension="pdf", inside_source=True)


class FakeLookup:
    """Gate 5, as a value. `raises=True` is 10:2030's store hiccup."""

    def __init__(self, result: Indexed | None = FOUND, *, raises: bool = False) -> None:
        self._result, self._raises = result, raises
        self.calls = 0

    def indexed(self, name: str) -> Indexed | None:  # noqa: ARG002
        self.calls += 1
        if self._raises:
            raise RuntimeError("the store is busy")
        return self._result


def _store(tmp_path: Path) -> Path:
    root = tmp_path / CONTROL_DIR / SESSIONS_DIR
    root.mkdir(parents=True)
    return root


def _squash(text: str) -> str:
    return " ".join(text.split())


def _normalise(text: str) -> str:
    """The example page is the one difference this suite allows. See the module docstring."""
    return (
        _squash(text)
        .replace("#p14", "#pN")
        .replace("#p1", "#pN")
        .replace("page 14 exactly", "page N exactly")
        .replace("page 1 exactly", "page N exactly")
    )


# ---------------------------------------------------------------------------------------------
# The two strings, against the plan.
# ---------------------------------------------------------------------------------------------


def test_both_shipped_strings_are_the_plans_own_words(plan: PlanDocs) -> None:
    """10:2036 and 10:2040, parsed out of the document and compared word for word."""
    advisory, deny = _plan_strings(plan)

    assert _normalise(advisory_text(OPAQUE, FOUND)) == _normalise(advisory)
    assert _normalise(deny_text(OPAQUE, FOUND)) == _normalise(deny)


def _plan_strings(plan: PlanDocs) -> tuple[str, str]:
    plan.require()
    text = plan.text("10-interfaces.md")
    block = text[text.index("advisory: omniweave hint:") :]
    block = block[: block.index("```")]
    advisory = block[: block.index("deny:")].replace("advisory:", "", 1)
    return advisory, block[block.index("deny:") :].replace("deny:", "", 1)


def test_the_two_strings_name_the_same_alternatives() -> None:
    """10:2034's reason for one constant: two policies wearing one name would be worse than none."""
    advisory, deny = advisory_text(OPAQUE, FOUND), deny_text(OPAQUE, FOUND)

    for tool in ("ow_query", "ow_open", 'ref="policy.pdf#p1"'):
        assert tool in advisory
        assert tool in deny


def test_the_advisory_opens_as_advice_and_not_as_an_instruction() -> None:
    """10:2032: text that opens with an imperative and then permits trains the agent to discount."""
    advisory = advisory_text(OPAQUE, FOUND)

    assert advisory.startswith("omniweave hint:")
    assert "MANDATORY" not in advisory
    assert not any(glyph in advisory for glyph in ("⚠", "❗", "!!"))
    assert advisory.upper() != advisory


def test_the_deny_says_how_to_turn_itself_off() -> None:
    deny = deny_text(OPAQUE, FOUND)

    assert "OMNIWEAVE_ENFORCE=advisory" in deny
    assert "=off to disable" in deny
    assert "offset/limit" in deny


def test_the_advisory_names_the_size_in_the_plans_own_units() -> None:
    """10:2036 writes *2.1 MB* for 2,100,000 bytes, which is decimal and not binary."""
    assert "2.1 MB" in advisory_text(OPAQUE, FOUND)


def test_both_strings_fit_the_events_cap() -> None:
    assert len(advisory_text(OPAQUE, FOUND)) <= EVENTS["PreToolUse"].cap
    assert len(deny_text(OPAQUE, FOUND)) <= EVENTS["PreToolUse"].cap


# ---------------------------------------------------------------------------------------------
# The five gates. 10:2011.
# ---------------------------------------------------------------------------------------------


def test_all_five_holding_is_the_only_way_to_a_word() -> None:
    assert failing_gate(OPAQUE, FOUND) == ""


@pytest.mark.parametrize(
    ("target", "gate"),
    [
        (Target(name="a.pdf", size=99_999, extension="pdf"), "outside-source"),
        (Target(name="a.md", size=99_999, extension="md", inside_source=True), "readable-ext"),
        (Target(name="a.pdf", size=10, extension="pdf", inside_source=True), "small"),
        (
            Target(name="a.pdf", size=99_999, extension="pdf", inside_source=True, targeted=True),
            "targeted-read",
        ),
    ],
)
def test_each_gate_names_itself_when_it_fails(target: Target, gate: str) -> None:
    assert failing_gate(target, FOUND) == gate


def test_a_document_no_corpus_holds_fails_the_fifth_gate() -> None:
    assert failing_gate(OPAQUE, None) == "not-indexed"


@pytest.mark.parametrize("extension", sorted(OPAQUE_DOC_EXTS))
def test_every_opaque_extension_passes_the_second_gate(extension: str) -> None:
    target = Target(name=f"a.{extension}", size=99_999, extension=extension, inside_source=True)

    assert failing_gate(target, FOUND) == ""


@pytest.mark.parametrize("extension", ["md", "txt", "html", "csv"])
def test_the_four_readable_extensions_are_deliberately_absent(extension: str) -> None:
    """10:2015: *the agent can genuinely read those and denying is wrong.*"""
    assert extension not in OPAQUE_DOC_EXTS


def test_the_extension_set_is_the_plans_twelve(plan: PlanDocs) -> None:
    plan.require()
    line = next(
        row for row in plan.text("10-interfaces.md").split("\n") if "_OPAQUE_DOC_EXTS" in row
    )
    printed = set(line[line.index("{") + 1 : line.index("}")].split())

    assert printed == OPAQUE_DOC_EXTS


def test_the_extension_check_ignores_case_and_a_leading_dot() -> None:
    target = Target(name="A.PDF", size=99_999, extension=".PDF", inside_source=True)

    assert failing_gate(target, FOUND) == ""


def test_the_size_floor_is_the_plans_number() -> None:
    assert MIN_SIZE_BYTES == 4_096
    assert failing_gate(Target("a.pdf", 4_096, "pdf", inside_source=True), FOUND) == ""
    assert failing_gate(Target("a.pdf", 4_095, "pdf", inside_source=True), FOUND) == "small"


def test_a_targeted_read_is_allowed_silently() -> None:
    """10:2017: *a targeted read is pre-Edit -- always allow, silently.*"""
    target = Target("a.pdf", 99_999, "pdf", inside_source=True, targeted=True)

    advice = decide(target, FOUND, mode=ENFORCE_STEER)

    assert advice.text == ""
    assert advice.deny is False


def test_the_gates_are_ordered_so_the_store_read_is_last(tmp_path: Path) -> None:
    """Gate 5 is the only expensive one, so a payload that fails a cheap gate must not reach it."""
    lookup = FakeLookup()

    run_pretool(
        {},
        target=Target("a.md", 99_999, "md", inside_source=True),
        lookup=lookup,
        env={},
        root=_store(tmp_path),
        key="k",
    )

    assert lookup.calls == 0


def test_a_qualifying_read_takes_exactly_one_lookup(tmp_path: Path) -> None:
    lookup = FakeLookup()

    run_pretool({}, target=OPAQUE, lookup=lookup, env={}, root=_store(tmp_path), key="k")

    assert lookup.calls == 1


def test_a_store_hiccup_allows_rather_than_blocks(tmp_path: Path) -> None:
    """10:2030: *any failure yields "not indexed" so the hook allows rather than blocks.*"""
    advice = run_pretool(
        {},
        target=OPAQUE,
        lookup=FakeLookup(raises=True),
        env={ENFORCE: ENFORCE_STEER},
        root=_store(tmp_path),
        key="k",
    )

    assert advice.deny is False
    assert advice.text == ""
    assert advice.counter == "noop-not-indexed"


# ---------------------------------------------------------------------------------------------
# The mode. 18:1748 and 10:2024.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["off", "advisory", "steer", "STEER", " steer "])
def test_a_known_mode_is_taken(value: str) -> None:
    assert enforce_mode({ENFORCE: value}) == value.strip().lower()


@pytest.mark.parametrize("value", ["", "warn", "strict", "1", "true", "STEERR"])
def test_an_unknown_mode_falls_back_to_advisory(value: str) -> None:
    """10:2024: *a typo must never hard-block a tool.*"""
    assert enforce_mode({ENFORCE: value}) == ENFORCE_ADVISORY


def test_an_unset_mode_is_advisory() -> None:
    assert enforce_mode({}) == ENFORCE_ADVISORY


def test_off_says_nothing_at_all() -> None:
    advice = decide(OPAQUE, FOUND, mode=ENFORCE_OFF)

    assert advice.text == ""
    assert advice.counter == "noop-off"


def test_advisory_nudges_and_never_denies() -> None:
    advice = decide(OPAQUE, FOUND, mode=ENFORCE_ADVISORY, may_claim=lambda: True)

    assert advice.deny is False
    assert advice.counter == "nudge"


def test_the_ttl_defaults_to_the_plans_eighteen_hundred() -> None:
    assert DEFAULT_TTL_S == 1_800
    assert ttl_seconds({}) == 1_800
    assert ttl_seconds({HOOK_TTL: "60"}) == 60


@pytest.mark.parametrize("value", ["", "soon", "1.5", "0x10"])
def test_a_bad_ttl_is_the_default(value: str) -> None:
    assert ttl_seconds({HOOK_TTL: value}) == DEFAULT_TTL_S


def test_a_negative_ttl_is_zero_rather_than_a_refusal() -> None:
    assert ttl_seconds({HOOK_TTL: "-5"}) == 0


# ---------------------------------------------------------------------------------------------
# The four deny guards. 10:2020.
# ---------------------------------------------------------------------------------------------


def test_steer_denies_when_all_four_guards_allow_it() -> None:
    advice = decide(OPAQUE, FOUND, mode=ENFORCE_STEER, may_claim=lambda: True)

    assert advice.deny is True
    assert advice.counter == "deny"
    assert advice.text.startswith("omniweave: policy.pdf is indexed")


def test_a_corpus_served_recently_stands_the_steer_down_to_a_nudge() -> None:
    advice = decide(OPAQUE, FOUND, mode=ENFORCE_STEER, may_claim=lambda: True, served_recently=True)

    assert advice.deny is False
    assert advice.counter == "nudge-stood-down"
    assert advice.text == advisory_text(OPAQUE, FOUND)


def test_a_stale_corpus_softens_to_a_nudge() -> None:
    """10:2022, and the reason: the passages we would send are the ones the user has changed."""
    stale = Indexed(corpus="handbook", version="41", pages=22, blocks=511, stale=True)

    advice = decide(OPAQUE, stale, mode=ENFORCE_STEER, may_claim=lambda: True)

    assert advice.deny is False
    assert advice.counter == "nudge-stale"


def test_a_lost_claim_softens_to_a_nudge() -> None:
    advice = decide(OPAQUE, FOUND, mode=ENFORCE_STEER, may_claim=lambda: False)

    assert advice.deny is False
    assert advice.counter == "nudge-unclaimed"


def test_the_claim_is_not_taken_when_an_earlier_guard_already_refused() -> None:
    """The claim is the one guard with a side effect, so it must run last."""
    taken = []

    decide(
        OPAQUE,
        FOUND,
        mode=ENFORCE_STEER,
        may_claim=lambda: taken.append(1) is None,
        served_recently=True,
    )

    assert taken == []


def test_the_deny_happens_once_per_session_and_the_second_read_is_a_nudge(
    tmp_path: Path,
) -> None:
    """10:2020's *once per session*, as an `O_EXCL` file that the second call cannot create."""
    root = _store(tmp_path)
    env: Mapping[str, str] = {ENFORCE: ENFORCE_STEER}

    first = run_pretool({}, target=OPAQUE, lookup=FakeLookup(), env=env, root=root, key="k")
    second = run_pretool({}, target=OPAQUE, lookup=FakeLookup(), env=env, root=root, key="k")

    assert first.deny is True
    assert second.deny is False
    assert second.counter == "nudge-unclaimed"
    assert (root / f"k{CLAIM_SUFFIX}").is_file()


def test_two_sessions_each_get_their_own_refusal(tmp_path: Path) -> None:
    root = _store(tmp_path)
    env: Mapping[str, str] = {ENFORCE: ENFORCE_STEER}

    first = run_pretool({}, target=OPAQUE, lookup=FakeLookup(), env=env, root=root, key="a")
    second = run_pretool({}, target=OPAQUE, lookup=FakeLookup(), env=env, root=root, key="b")

    assert first.deny is True
    assert second.deny is True


def test_a_deployment_with_nowhere_to_claim_nudges_rather_than_denying() -> None:
    """D403 again: advice with no memory is still advice; a refusal with none would repeat."""
    advice = run_pretool(
        {},
        target=OPAQUE,
        lookup=FakeLookup(),
        env={ENFORCE: ENFORCE_STEER},
        root=None,
    )

    assert advice.deny is False
    assert advice.counter == "nudge-unclaimed"
    assert advice.text != ""


# ---------------------------------------------------------------------------------------------
# The channel. 10:2047.
# ---------------------------------------------------------------------------------------------


def test_the_deny_travels_in_the_decision_channel_and_exits_zero() -> None:
    """10:2047: *the deny is emitted in the JSON decision channel with exit code 0.*"""
    import json  # noqa: PLC0415

    advice = decide(OPAQUE, FOUND, mode=ENFORCE_STEER, may_claim=lambda: True)
    body: Any = json.loads(emission("PreToolUse", advice))["hookSpecificOutput"]

    assert body[DECISION_CHANNEL] == DENY
    assert body[DECISION_REASON].startswith("omniweave: policy.pdf")
    assert "additionalContext" not in body


def test_a_nudge_travels_in_the_context_channel() -> None:
    import json  # noqa: PLC0415

    advice = decide(OPAQUE, FOUND, mode=ENFORCE_ADVISORY)
    body: Any = json.loads(emission("PreToolUse", advice))["hookSpecificOutput"]

    assert body["additionalContext"].startswith("omniweave hint:")
    assert DECISION_CHANNEL not in body


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_module_imports_no_store_and_no_config() -> None:
    import ast  # noqa: PLC0415

    import omniweave.hooks.pretool as module  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    names = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }

    assert not [name for name in names if name.startswith("omniweave_core")]
    assert {name for name in names if name.startswith("omniweave")} == {
        "omniweave.hooks.envelope",
        "omniweave.hooks.session",
    }


def test_the_unguarded_list_names_the_five_readings_this_gate_runs_against() -> None:
    stated = unguarded()

    assert len(stated) == 5
    assert any("D417" in item for item in stated)
    assert any("D418" in item for item in stated)
