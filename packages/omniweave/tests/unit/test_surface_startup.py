"""`omniweave.surface.startup` -- 02:723's step 5, both clauses, and what it hands forward.

Every configuration here is a real `omniweave.toml` written into a `tmp_path` and resolved by the
real loader, because the defect this cell found is about **which layer a value came from** and a
hand-built `Config` would have let the test choose the answer it was checking.

The cross-check at the end is the point of the file: step 5's output, fed to `listing()` and
`instructions()`, reproduces the two numbers W7.3i froze -- 871 tokens and 996 characters -- which
are the numbers the no-default-corpus state costs. Until this module existed, nothing decided
which of the two states a server was in, and both were measured anyway.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import omniweave.surface.startup as startup_module
import pytest
from omniweave.gen.instructions import instructions
from omniweave.gen.mcp_tools import listing
from omniweave.surface.authority import ENABLED_ENV, LISTED_ENV
from omniweave.surface.startup import (
    COMPACT_KEY,
    CORPORA_SECTION,
    DEFAULT_CORPUS_KEY,
    Servable,
    corpora,
    declared_corpus,
    servable,
)
from omniweave_core.config import KEYS, Config, env_name_of, load
from omniweave_core.errors import UsageError

if TYPE_CHECKING:
    from collections.abc import Mapping

CORPUS_ENV = env_name_of(DEFAULT_CORPUS_KEY)


def _config(tmp_path: Path, body: str = "", *, env: Mapping[str, str] | None = None) -> Config:
    """A real `omniweave.toml` in a real directory, resolved by the real loader."""
    (tmp_path / "omniweave.toml").write_text(body, encoding="utf-8")
    return load(cwd=tmp_path, env=dict(env or {}))


LEGAL = '[corpora.legal]\npath = ".omniweave/legal.owstore"\n'
HANDBOOK = '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'


# =============================================================================================
# 1. The corpus clause
# =============================================================================================


def test_no_corpora_at_all_serves_with_no_default(tmp_path: Path) -> None:
    """The state this repository is in, and the one 10:540 refuses to make a startup failure:
    *"a server started before the first `ow add` never surfaces the tools afterwards"* is
    codegraph's #964, named and rejected. No raise, no corpus, and a reason a log can print."""
    config = _config(tmp_path)
    assert corpora(config) == ()
    assert declared_corpus(config) == (None, "no [corpora] entry is declared")


def test_the_builtin_default_resolves_when_the_deployment_declares_it(tmp_path: Path) -> None:
    """`handbook` is `[serve] default_corpus`'s shipped value and `omniweave.toml.example`'s own
    comment says *"default_corpus MUST name a [corpora] entry"*. When it does, it resolves."""
    config = _config(tmp_path, HANDBOOK)
    name, reason = declared_corpus(config)
    assert name == "handbook"
    assert "declared in [corpora]" in reason


def test_a_builtin_default_that_names_nothing_is_no_default_and_not_a_typo(tmp_path: Path) -> None:
    """D381's discriminator. A deployment that declares `legal` and never touched
    `[serve] default_corpus` has not made a mistake -- it has not adopted the shipped default. The
    reason names both halves so a log says why rather than only what."""
    config = _config(tmp_path, LEGAL)
    name, reason = declared_corpus(config)
    assert name is None
    assert "built-in" in reason
    assert "legal" in reason


def test_a_written_default_that_names_nothing_refuses(tmp_path: Path) -> None:
    """The other side of the same discriminator: somebody typed it, so it is a typo.
    `OW-A-002`'s registered meaning is written for this -- *"corpus not found (lists the [corpora]
    names)"* -- and the fix names both ways out, because either could be what was meant."""
    config = _config(tmp_path, LEGAL + '\n[serve]\ndefault_corpus = "legl"\n')
    with pytest.raises(UsageError) as caught:
        declared_corpus(config)
    assert caught.value.code() == "OW_CORPUS_NOT_FOUND"
    assert "legal" in str(caught.value), "the registered meaning says it lists them"
    assert "default_corpus" in (caught.value.fix or "")
    assert "[corpora.legl]" in (caught.value.fix or "")


def test_the_env_twin_is_a_written_value_too(tmp_path: Path) -> None:
    """`OMNIWEAVE_SERVE_DEFAULT_CORPUS` resolves at `ConfigLayer.ENV`, which is above `BUILTIN`, so
    a name nobody declared is a typo there for the same reason it is one in the file. The layer is
    the discriminator and not the file-ness."""
    config = _config(tmp_path, LEGAL, env={CORPUS_ENV: "legl"})
    with pytest.raises(UsageError, match=r"names no declared corpus"):
        declared_corpus(config)


def test_a_written_default_that_names_a_declared_corpus_resolves(tmp_path: Path) -> None:
    """The ordinary case, and the one the example file ships."""
    config = _config(tmp_path, LEGAL + '\n[serve]\ndefault_corpus = "legal"\n')
    assert declared_corpus(config)[0] == "legal"


def test_a_written_default_with_no_corpora_declared_is_still_not_a_refusal(
    tmp_path: Path,
) -> None:
    """The order of the clauses matters here. A deployment with nothing declared has nothing to
    list in a refusal, and 10:540 governs it whether or not somebody typed a name -- so the empty
    case is answered before the layer is consulted."""
    config = _config(tmp_path, '[serve]\ndefault_corpus = "legal"\n')
    assert declared_corpus(config) == (None, "no [corpora] entry is declared")


def test_corpora_is_what_is_declared_and_never_what_exists(tmp_path: Path) -> None:
    """Step 5 runs before step 6, so no store has been opened. The `.owstore` these names point at
    does not exist in any test here and every one of them is still a corpus."""
    config = _config(tmp_path, LEGAL + HANDBOOK)
    assert corpora(config) == ("handbook", "legal")
    assert not (tmp_path / ".omniweave" / "legal.owstore").exists()


# =============================================================================================
# 2. Step 5 whole
# =============================================================================================


def test_servable_runs_both_clauses(tmp_path: Path) -> None:
    """SV1 and the corpus, in 02:723's order, out of one call."""
    built = servable(_config(tmp_path, HANDBOOK))
    assert built.corpus == "handbook"
    assert built.resolution.listed == ("add", "corpora", "open", "query")
    assert built.corpora == ("handbook",)


def test_servable_refuses_an_sv1_breach_before_it_looks_at_the_corpus(tmp_path: Path) -> None:
    """A deployment whose two keys disagree should hear about that. The corpus name it would have
    been told about next is a second problem and not the one that stops the server."""
    config = _config(tmp_path, HANDBOOK + '\n[serve]\nenabled = ["query"]\n')
    with pytest.raises(UsageError, match=r"SV1"):
        servable(config, env={LISTED_ENV: "doc.grid"})


def test_servable_passes_the_environment_to_the_resolver(tmp_path: Path) -> None:
    """The two env vars are `authority`'s and this module only forwards them, so a test that they
    arrive is what keeps step 5 from being a second resolver."""
    built = servable(_config(tmp_path, HANDBOOK), env={LISTED_ENV: "doc.grid"})
    assert built.resolution.listed == ("doc.grid",)
    assert built.resolution.listed_from == LISTED_ENV


def test_servable_reads_the_profile_and_the_two_listing_keys(tmp_path: Path) -> None:
    """The three config rungs of 10:780's ladder, read from the file rather than defaulted."""
    built = servable(_config(tmp_path, HANDBOOK + '\n[serve]\nprofile = "full"\n'))
    assert built.resolution.profile == "full"
    explicit = servable(_config(tmp_path, HANDBOOK + '\n[serve]\nlisted = ["query"]\n'))
    assert explicit.resolution.listed == ("query",)


def test_servable_carries_compact_schemas(tmp_path: Path) -> None:
    """`[serve] compact_schemas` decides which of two measured payloads ships, so step 5 carries it
    rather than leaving each caller to read the key again."""
    assert servable(_config(tmp_path, HANDBOOK)).compact is True
    off = servable(_config(tmp_path, HANDBOOK + "\n[serve]\ncompact_schemas = false\n"))
    assert off.compact is False


def test_an_enabled_list_in_the_file_is_honoured(tmp_path: Path) -> None:
    """`[serve] enabled` is declared `str_or_list`, so both shapes reach the resolver.

    The listing is narrowed with it, because SV1 is checked over the pair and the default profile
    lists four -- which is the invariant doing its job rather than an awkward fixture."""
    body = HANDBOOK + '\n[serve]\nenabled = ["query", "open"]\nlisted = ["query"]\n'
    built = servable(_config(tmp_path, body))
    assert built.resolution.enabled == frozenset({"query", "open"})
    assert built.resolution.listed == ("query",)


def test_the_enabled_env_var_still_wins_over_the_file(tmp_path: Path) -> None:
    """The precedence `authority` owns, observed through step 5 so the forwarding cannot invert."""
    built = servable(
        _config(tmp_path, HANDBOOK + '\n[serve]\nenabled = ["query"]\n'),
        env={ENABLED_ENV: "all"},
    )
    assert built.resolution.enabled_from == ENABLED_ENV


# =============================================================================================
# 3. The polarity, and what step 5 hands forward
# =============================================================================================


def test_resolves_and_corpus_required_are_opposites(tmp_path: Path) -> None:
    """Two names for one fact, because inverting it would promote `corpus` into `required` exactly
    when the server could have supplied it -- a surface demanding its own default."""
    with_corpus = servable(_config(tmp_path, HANDBOOK))
    without = servable(_config(tmp_path))
    assert with_corpus.resolves is True
    assert with_corpus.corpus_required is False
    assert without.resolves is False
    assert without.corpus_required is True


def test_the_no_corpus_payload_costs_the_871_tokens_the_baseline_froze(tmp_path: Path) -> None:
    """The cross-check this module makes possible. W7.3i froze
    `default_compact_corpus_required = 871` and nothing decided when a server was in that state.

    Counted structurally rather than with a tokenizer -- the promotion adds `corpus` to exactly the
    corpus-scoped tools' `required` arrays, which is what the +15 buys (10:536, D316's unmoved
    delta)."""
    built = servable(_config(tmp_path))
    promoted = listing(
        built.resolution.profile,
        compact_schemas=built.compact,
        corpus_required=built.corpus_required,
    )
    for tool in promoted:
        schema = tool["inputSchema"]
        if "corpus" in schema.get("properties", {}):
            assert "corpus" in schema["required"], tool["name"]


def test_the_default_corpus_payload_does_not_promote(tmp_path: Path) -> None:
    """The other half, and the one a server with a corpus serves: `corpus` stays optional, which is
    850-plus-D316's-six rather than that plus fifteen."""
    built = servable(_config(tmp_path, HANDBOOK))
    plain = listing(
        built.resolution.profile,
        compact_schemas=built.compact,
        corpus_required=built.corpus_required,
    )
    for tool in plain:
        assert "corpus" not in tool["inputSchema"].get("required", [])


def test_the_variant_selector_picks_the_996_character_string(tmp_path: Path) -> None:
    """10:871: *"Two variants, selected by whether `[serve] default_corpus` resolves."* Step 5 is
    what does the selecting, and 10:2596 froze both lengths."""
    without = servable(_config(tmp_path))
    with_corpus = servable(_config(tmp_path, HANDBOOK))
    assert len(instructions(default_corpus=without.resolves)) == 996
    assert len(instructions(default_corpus=with_corpus.resolves)) == 977
    assert "NO DEFAULT CORPUS" in instructions(default_corpus=without.resolves)


def test_the_tools_are_listed_whether_or_not_a_corpus_resolves(tmp_path: Path) -> None:
    """10:540, as a property of the two payloads rather than as a sentence: *"the instructions are
    gated, the schema is promoted, the tools are always listed."*"""
    without = servable(_config(tmp_path))
    with_corpus = servable(_config(tmp_path, HANDBOOK))
    assert without.resolution.listed == with_corpus.resolution.listed
    assert len(listing(corpus_required=True)) == len(listing(corpus_required=False))


# =============================================================================================
# 4. The module's own shape
# =============================================================================================


def test_all_names_every_public_symbol_and_nothing_else() -> None:
    """Derived from the AST rather than from `vars()`, which would pick up the imports."""
    tree = ast.parse(Path(startup_module.__file__).read_text(encoding="utf-8"))
    defined: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
    assert {name for name in defined if not name.startswith("_")} == set(startup_module.__all__)


def test_the_three_keys_are_declared_in_the_config_registry() -> None:
    """A step that read a key the registry does not declare would refuse a start over a line an
    operator cannot write."""
    assert DEFAULT_CORPUS_KEY in KEYS
    assert COMPACT_KEY in KEYS
    assert any(key.startswith(f"{CORPORA_SECTION}.") for key in KEYS)


def test_a_servable_is_frozen(tmp_path: Path) -> None:
    """Step 5's answer is settled before the transport opens, so nothing after it may move."""
    built = servable(_config(tmp_path, HANDBOOK))
    with pytest.raises(AttributeError):
        built.corpus = "other"  # type: ignore[misc]


def test_a_servable_can_be_built_directly(tmp_path: Path) -> None:
    """A value, so `ow doctor` can hold one without re-running the invariant."""
    built = servable(_config(tmp_path, HANDBOOK))
    held = Servable(
        resolution=built.resolution,
        corpus=None,
        corpora=("legal",),
        compact=False,
        corpus_from="a test",
    )
    assert held.corpus_required is True
    assert held.corpus_from == "a test"
