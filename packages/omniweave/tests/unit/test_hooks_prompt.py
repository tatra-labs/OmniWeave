"""`UserPromptSubmit`: the shapes, the three HIGH triggers, MEDIUM's outline and the two noops.

**No store is opened and none is needed.** 10:1982's table is a function of the shapes in a
prompt and what the store said about them, so every row of it is a test with a fake `Probes` --
the same seam D410 exists to keep open, and the reason this suite runs in milliseconds against a
handler G26 holds to 250 ms.

Two properties get their own assertions because they are rules rather than behaviour: **no counter
this module can emit contains anything the user typed** (10:1990), and **the ledger commit rides
only on the path that actually emits** (10:2004).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from omniweave.hooks.envelope import EVENTS, Outcome, run
from omniweave.hooks.prompt import (
    CITE_RE,
    MEDIUM_MAX_CHARS,
    PROMPT,
    Injection,
    Shapes,
    handler,
    run_prompt,
    shapes_of,
    unpriced,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from conftest import PlanDocs

PROMPT_TEXT = 'about policy.pdf and d7#412 and "the benefits schedule"'


class FakeProbes:
    """A `Probes` whose answers are fixed per construction, and which counts what it was asked.

    `calls` is what makes D413 testable: the cost column prices HIGH at one query, and the only way
    to see whether three verifications happened is to count them.
    """

    def __init__(
        self,
        *,
        cites: bool = False,
        files: bool = False,
        fts: bool = False,
        outline: str = "",
        answer: str | None = "ANSWER",
    ) -> None:
        self._cites, self._files, self._fts = cites, files, fts
        self._outline, self._answer = outline, answer
        self.calls: list[str] = []
        self.committed = False

    def resolve(self, cites: Sequence[str]) -> Sequence[str]:
        self.calls.append("resolve")
        return list(cites) if self._cites else []

    def known(self, filenames: Sequence[str]) -> Sequence[str]:
        self.calls.append("known")
        return list(filenames) if self._files else []

    def search(self, phrases: Sequence[str]) -> Sequence[str]:
        self.calls.append("search")
        return list(phrases) if self._fts else []

    def outline(self, prompt: str) -> str:  # noqa: ARG002
        self.calls.append("outline")
        return self._outline

    def query(self, seed: Sequence[str], trigger: str) -> Injection:
        self.calls.append("query")

        def commit() -> None:
            self.committed = True

        if self._answer is None:
            return Injection()
        return Injection(text=f"{self._answer}:{trigger}:{','.join(seed)}", after_emit=commit)


# ---------------------------------------------------------------------------------------------
# Shapes. 10:1984, decidable without a store.
# ---------------------------------------------------------------------------------------------


def test_the_cite_pattern_is_the_plans_own_regex() -> None:
    assert CITE_RE.pattern == r"\bd\d+#\d+\b"


@pytest.mark.parametrize("text", ["d7#412", "see d31#88.", "(d1#1)", "d7#412 d7#418"])
def test_a_cite_is_recognised(text: str) -> None:
    assert shapes_of(text).cites


@pytest.mark.parametrize("text", ["add7#412", "d7#4123x", "d7#", "#412", "d#1"])
def test_a_near_miss_is_not_a_cite(text: str) -> None:
    """The word boundaries are the whole of the pattern's precision."""
    assert not shapes_of(text).cites


def test_a_filename_is_recognised_and_a_path_is_not() -> None:
    """10:1984 says a *filename*; a corpus addresses documents by name, not by path."""
    shapes = shapes_of("read policy.pdf but not ./docs/inner.md or a/b/c.txt")

    assert shapes.filenames == ("policy.pdf",)


def test_a_quoted_phrase_is_recognised_between_its_bounds() -> None:
    shapes = shapes_of('say "the benefits schedule" and "' + "x" * 300 + '"')

    assert shapes.phrases == ("the benefits schedule",)


def test_a_short_quotation_does_not_desynchronise_the_pairs_after_it() -> None:
    """A length bound inside the pattern makes `" and "` a phrase. It is applied after pairing."""
    shapes = shapes_of('say "x" and "the benefits schedule" ok')

    assert shapes.phrases == ("the benefits schedule",)


def test_an_unterminated_quote_yields_no_phrase() -> None:
    assert shapes_of('he said "something and then stopped').phrases == ()


def test_shapes_are_deduplicated_in_first_seen_order() -> None:
    shapes = shapes_of("d31#88 then d7#412 then d31#88 again")

    assert shapes.cites == ("d31#88", "d7#412")


def test_shapes_are_capped_so_a_pasted_stack_trace_is_not_eighty_probes() -> None:
    prompt = " ".join(f"file{index}.py" for index in range(80))

    assert len(shapes_of(prompt).filenames) == 8


def test_a_prompt_with_nothing_verifiable_has_no_shapes() -> None:
    assert shapes_of("please summarise what we discussed yesterday").empty()


def test_an_empty_shapes_is_empty() -> None:
    assert Shapes().empty()


# ---------------------------------------------------------------------------------------------
# 10:1982's table, row by row.
# ---------------------------------------------------------------------------------------------


def test_a_resolving_cite_is_the_high_cite_tier() -> None:
    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=FakeProbes(cites=True))

    assert advice.counter == "high-cite"
    assert advice.text.startswith("ANSWER:high-cite:d7#412")


def test_a_corpus_verified_filename_is_the_high_token_tier() -> None:
    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=FakeProbes(files=True))

    assert advice.counter == "high-token"
    assert "policy.pdf" in advice.text


def test_a_phrase_with_an_fts_hit_is_the_high_fts_tier() -> None:
    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=FakeProbes(fts=True))

    assert advice.counter == "high-fts"
    assert "the benefits schedule" in advice.text


def test_the_triggers_are_tried_in_the_plans_counter_order_and_the_first_wins() -> None:
    probes = FakeProbes(cites=True, files=True, fts=True)

    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=probes)

    assert advice.counter == "high-cite"
    assert probes.calls == ["resolve", "query"]


def test_the_common_high_prompt_costs_one_verification_and_one_query() -> None:
    """D413: 10:1982 prices HIGH at 'one query' and never counts the verification."""
    probes = FakeProbes(cites=True)

    run_prompt({PROMPT: "about d7#412"}, probes=probes)

    assert probes.calls == ["resolve", "query"]


def test_a_prompt_whose_first_two_triggers_miss_still_reaches_the_third() -> None:
    probes = FakeProbes(fts=True)

    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=probes)

    assert probes.calls == ["resolve", "known", "search", "query"]
    assert advice.counter == "high-fts"


def test_a_shape_the_prompt_lacks_is_not_probed() -> None:
    probes = FakeProbes(fts=True)

    run_prompt({PROMPT: '"the benefits schedule"'}, probes=probes)

    assert probes.calls == ["search", "query"]


def test_prose_that_verifies_nothing_falls_to_the_medium_outline() -> None:
    probes = FakeProbes(outline="- Benefits schedule\n- Leave policy")

    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=probes)

    assert advice.counter == "medium-outline"
    assert advice.text == "- Benefits schedule\n- Leave policy"


def test_the_medium_outline_is_capped_at_four_hundred_characters() -> None:
    probes = FakeProbes(outline="x" * 900)

    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=probes)

    assert len(advice.text) == MEDIUM_MAX_CHARS


def test_the_medium_tier_injects_no_content_and_charges_no_ledger() -> None:
    """10:1982: *the agent writes the query*. Ledgering an outline suppresses that query."""
    probes = FakeProbes(outline="- Benefits schedule")

    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=probes)

    assert advice.after_emit is None
    assert "ANSWER" not in advice.text


def test_a_prompt_with_no_shape_is_silent_without_touching_the_store() -> None:
    probes = FakeProbes()

    advice = run_prompt({PROMPT: "please summarise yesterday"}, probes=probes)

    assert advice.counter == "noop-shape"
    assert advice.text == ""
    assert probes.calls == []


def test_an_empty_prompt_is_silent() -> None:
    assert run_prompt({PROMPT: "   "}, probes=FakeProbes()).counter == "noop-shape"
    assert run_prompt({}, probes=FakeProbes()).counter == "noop-shape"


def test_no_corpus_is_silent_and_is_its_own_counter() -> None:
    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=None)

    assert advice.counter == "noop-no-corpus"


def test_a_shape_that_verifies_nothing_has_a_counter_of_its_own() -> None:
    """D414: 10:1990's seven cover 'no shape' and 'no corpus' and not this, which is the gate's
    false-positive rate and the half of a recall measurement that is missing."""
    advice = run_prompt({PROMPT: PROMPT_TEXT}, probes=FakeProbes())

    assert advice.counter == "noop-unverified"
    assert advice.counter != "noop-shape"


def test_a_probe_returning_something_strange_does_not_become_a_tier() -> None:
    class Odd(FakeProbes):
        def resolve(self, cites: Sequence[str]) -> Sequence[str]:  # noqa: ARG002
            return "d7#412"  # type: ignore[return-value]

    advice = run_prompt({PROMPT: "about d7#412"}, probes=Odd())

    assert advice.counter == "noop-unverified"


def test_a_query_that_renders_nothing_falls_through_rather_than_emitting_empty() -> None:
    probes = FakeProbes(cites=True, answer=None)

    advice = run_prompt({PROMPT: "about d7#412"}, probes=probes)

    assert advice.text == ""
    assert advice.counter == "noop-unverified"


# ---------------------------------------------------------------------------------------------
# The two rules. 10:1990 and 10:2004.
# ---------------------------------------------------------------------------------------------


def test_no_counter_this_module_emits_contains_anything_the_user_typed() -> None:
    """10:1990: *counter names only, never prompt text.*"""
    secret_words = ("zebra", "quux", "hunter2")
    prompt = f'{secret_words[0]} d7#412 "{secret_words[1]} schedule" {secret_words[2]}.pdf'

    for probes in (
        FakeProbes(cites=True),
        FakeProbes(files=True),
        FakeProbes(fts=True),
        FakeProbes(outline="- x"),
        FakeProbes(),
        None,
    ):
        advice = run_prompt({PROMPT: prompt}, probes=probes)
        assert not any(word in advice.counter for word in secret_words)


def test_the_counter_vocabulary_is_a_closed_set_of_constants() -> None:
    source = Path(str(__import__("omniweave.hooks.prompt", fromlist=["_"]).__file__))
    tree = ast.parse(source.read_text(encoding="utf-8"))
    emitted = {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id.startswith(("_HIGH", "_MEDIUM", "_NOOP"))
        and isinstance(node.value, ast.Constant)
    }

    assert emitted == {
        "high-cite",
        "high-token",
        "high-fts",
        "medium-outline",
        "noop-shape",
        "noop-no-corpus",
        "noop-unverified",
    }


def test_six_of_the_seven_counters_are_the_plans_own(plan: PlanDocs) -> None:
    """The seventh, `-noop-deadline`, is the envelope's and D396 records that it is filed here."""
    plan.require()
    text = plan.text("10-interfaces.md")

    for name in ("high-cite", "high-token", "high-fts", "medium-outline", "noop-shape"):
        assert f"-{name}" in text
    assert "noop-unverified" not in text  # D414: this one is ours


def test_the_ledger_commit_rides_only_on_the_path_that_emits() -> None:
    """10:2004 puts the commit after the flush, so a path with no flush must carry no commit."""
    emitting = run_prompt({PROMPT: "about d7#412"}, probes=FakeProbes(cites=True))
    silent = run_prompt({PROMPT: "nothing here"}, probes=FakeProbes())

    assert emitting.after_emit is not None
    assert silent.after_emit is None


def test_the_outcome_carries_the_commit_and_running_it_is_the_callers_act() -> None:
    probes = FakeProbes(cites=True)
    outcome = run(
        "UserPromptSubmit",
        {PROMPT: "about d7#412"},
        handler(probes),
        clock=_Clock(),
        env={},
    )

    assert probes.committed is False  # the envelope must NOT have committed
    assert outcome.settle() is True
    assert probes.committed is True


def test_a_deadline_breach_drops_the_emission_and_the_commit_with_it() -> None:
    """A ledger that recorded a commit here would claim an emission the model never saw."""
    probes = FakeProbes(cites=True)
    outcome = run(
        "UserPromptSubmit",
        {PROMPT: "about d7#412"},
        handler(probes),
        clock=_SlowClock(),
        env={},
        deadline_ms=0,
    )

    assert outcome.breached
    assert outcome.stdout == ""
    assert outcome.settle() is False
    assert probes.committed is False


def test_a_commit_that_raises_is_a_silent_exit_zero() -> None:
    def explodes() -> None:
        raise RuntimeError("the ledger went away")

    assert Outcome(stdout="x", after_emit=explodes).settle() is False


def test_an_outcome_with_no_commit_reports_that_it_committed_nothing() -> None:
    assert Outcome(stdout="x").settle() is False


def test_the_envelope_never_calls_the_commit_itself() -> None:
    """The one call site is the `__main__`, exactly as `stdio.py` asserts for `after_send`."""
    from omniweave.hooks import envelope  # noqa: PLC0415

    tree = ast.parse(Path(str(envelope.__file__)).read_text(encoding="utf-8"))
    inside_committed = {
        node
        for definition in ast.walk(tree)
        if isinstance(definition, ast.FunctionDef) and definition.name == "settle"
        for node in ast.walk(definition)
    }
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "after_emit"
        and node not in inside_committed
    ]

    assert calls == []


class _Clock:
    def monotonic_ns(self) -> int:
        return 0

    def wall_ns(self) -> int:
        return 0


class _SlowClock:
    def __init__(self) -> None:
        self._readings = iter((0, 10_000_000_000))

    def monotonic_ns(self) -> int:
        return next(self._readings, 10_000_000_000)

    def wall_ns(self) -> int:
        return 0


# ---------------------------------------------------------------------------------------------
# What the module says about itself.
# ---------------------------------------------------------------------------------------------


def test_the_high_cap_is_the_plans_eight_thousand() -> None:
    """`HIGH_MAX_CHARS` is read off `EVENTS`, so this asserts the number and not the agreement."""
    from omniweave.hooks.prompt import HIGH_MAX_CHARS  # noqa: PLC0415

    assert HIGH_MAX_CHARS == 8_000
    assert EVENTS["UserPromptSubmit"].cap == HIGH_MAX_CHARS


def test_a_high_injection_longer_than_the_cap_is_cut_before_the_envelope_sees_it() -> None:
    probes = FakeProbes(cites=True, answer="A" * 9_000)

    advice = run_prompt({PROMPT: "about d7#412"}, probes=probes)

    assert len(advice.text) == 8_000


def test_the_module_imports_no_store_and_no_config() -> None:
    """D410: this is the handler G26 measures, so its import list is its budget."""
    import omniweave.hooks.prompt as module  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    names = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert not [name for name in names if name.startswith("omniweave_core")]
    assert {name for name in names if name.startswith("omniweave")} == {"omniweave.hooks.envelope"}


def test_the_unpriced_list_names_the_five_readings_this_gate_runs_against() -> None:
    stated = unpriced()

    assert len(stated) == 5
    assert any("D413" in item for item in stated)
    assert any("D414" in item for item in stated)


def test_every_counter_argument_is_a_module_constant_and_never_an_expression() -> None:
    """10:1990 held structurally: a counter is a `Final` name, so no prompt substring can reach one.

    Asserted over the AST rather than by example, because the rule is about what the code *can*
    emit. A `counter=` taking anything but a bare `_`-prefixed name -- an f-string, a slice of the
    prompt, a `.format` -- is the one shape that would put user text in the register 10:1990 says
    records only that a tier fired.
    """
    import omniweave.hooks.prompt as module  # noqa: PLC0415

    tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
    arguments = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Advice"
        for keyword in node.keywords
        if keyword.arg == "counter"
    ]

    assert arguments
    for value in arguments:
        assert isinstance(value, ast.Name), ast.dump(value)
        assert value.id.startswith(("_HIGH", "_MEDIUM", "_NOOP", "trigger", "medium"))


def test_the_shapes_type_is_the_only_place_prompt_substrings_live() -> None:
    assert set(Shapes.__dataclass_fields__) == {"cites", "filenames", "phrases"}
