"""Startup step 5, whole: SV1 over the two keys, and `default_corpus` against `[corpora]`.

02:723 is one row with two clauses:

> | 5 | surface | serve only: assert SV1 -- `set(listed) ⊆ set(enabled)` and
> `HUMAN_ONLY ∩ enabled = {}`; assert `default_corpus` names a `[corpora]` entry |
> `SurfaceError` (`OW-A-*`), **exit 1**, before the transport opens |

`authority.resolve()` is the first clause. This is the second, and the pair, because what a caller
needs out of step 5 is not two booleans but the four facts that decide what it serves: which
Actions are granted, which are shown, whether a default corpus resolves, and whether schemas are
compacted. `Servable` is those four, and `omniweave_core.config._check_startup_invariants()` names
this module's half by exclusion -- *"`default_corpus` naming a `[corpora]` entry ... is startup
step 5's surface invariants ... and is deliberately NOT here"*.

## THE SECOND CLAUSE CANNOT BE AN ASSERTION, AND 10:540 IS WHY

Read literally, *"assert `default_corpus` names a `[corpora]` entry"* refuses to start whenever it
does not. Three shipped things become unreachable at once:

* 10:871's **variant B** of the `instructions` string exists *"selected by whether `[serve]
  default_corpus` resolves"*, and carries `NO DEFAULT CORPUS: call ow_corpora first`;
* 10:525's **`corpus` promotion into `required`** exists for the same condition, and 10:536 prices
  it at +15 tokens;
* 10:540 forbids the consequence by name -- *"**Tool availability is never gated on index
  presence.** codegraph's #964 is exactly that bug -- it breaks a deployment where only some
  corpora are built, and a server started before the first `ow add` never surfaces the tools
  afterwards."*

**This repository is that deployment.** `[serve] default_corpus` resolves to `handbook` from
`ConfigLayer.BUILTIN` and `subkeys("corpora")` is empty, so a literal reading refuses to start here.

The register already draws the line the two documents need, which is why the reconciliation below
is a reading rather than an invention: `OW-A-001 / OW_NO_CORPUS_CONFIGURED` is *"no corpus
configured"* and `OW-A-002 / OW_CORPUS_NOT_FOUND` is *"corpus not found (lists the `[corpora]`
names)"*. Two conditions, two codes, already registered.

So: **a value an operator wrote that names nothing is a typo and refuses; a value nobody wrote that
names nothing is no default corpus and serves.** `ConfigSource.layer` is what tells them apart, and
`Config.source_of()`'s own docstring calls that *"the point of the module"*. D381 is the entry.

## WHAT STEP 5 HANDS FORWARD

`Servable.resolves` selects the `instructions` variant and `Servable.corpus_required` selects the
schema promotion, and the two are opposites of one fact. They are spelled as two named properties
rather than left to each caller's `not`, because getting the polarity backwards makes `corpus`
required exactly when a default exists -- a surface that demands the one argument it could supply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_core.config import ConfigLayer
from omniweave_core.errors import UsageError

from omniweave.surface.authority import Resolution, resolve

if TYPE_CHECKING:
    from collections.abc import Mapping

    from omniweave_core.config import Config

__all__ = [
    "COMPACT_KEY",
    "CORPORA_SECTION",
    "DEFAULT_CORPUS_KEY",
    "Servable",
    "corpora",
    "declared_corpus",
    "servable",
]


DEFAULT_CORPUS_KEY: Final[str] = "serve.default_corpus"
COMPACT_KEY: Final[str] = "serve.compact_schemas"
CORPORA_SECTION: Final[str] = "corpora"
"""The three keys step 5 reads beyond `authority`'s five. `[corpora]` is a section rather than a
key, and `Config.subkeys()` is the declared way to enumerate one -- its docstring names
``subkeys("corpora")`` as *"the set `ow_corpora` enumerates"*, so this module and that tool read
one list."""


@dataclass(frozen=True, slots=True)
class Servable:
    """Everything step 5 decides, and nothing it does not.

    Four facts and two derived properties. No store has been opened at this point (02:717: *"the
    first five steps touch no store"*), so `corpora` is what the configuration declares and never
    what exists on disk -- which is 10:540's rule stated as a data dependency rather than as a
    warning.
    """

    resolution: Resolution
    corpus: str | None
    corpora: tuple[str, ...]
    compact: bool
    corpus_from: str
    """Why `corpus` is what it is, in words, for `ow doctor` and the startup log."""

    @property
    def resolves(self) -> bool:
        """Whether `[serve] default_corpus` resolves. 10:871's variant selector.

        `instructions(default_corpus=servable.resolves)` is the whole of its use.
        """
        return self.corpus is not None

    @property
    def corpus_required(self) -> bool:
        """Whether `corpus` is promoted into `required`. 10:525, and the opposite of `resolves`.

        `listing(corpus_required=servable.corpus_required)` is the whole of its use. Named rather
        than left as a `not` at each call site: inverted, it would require the one argument the
        server could have supplied itself.
        """
        return self.corpus is None


def corpora(config: Config) -> tuple[str, ...]:
    """The `[corpora]` entry names this configuration declares, sorted.

    Declared and not opened. Step 6 is where a store is touched and step 5 runs before it, so a
    corpus whose `.owstore` is missing is still a corpus here -- 10:540 again: *"a server started
    before the first `ow add`"* must still list its tools.
    """
    return config.subkeys(CORPORA_SECTION)


def declared_corpus(config: Config) -> tuple[str | None, str]:
    """`[serve] default_corpus` resolved against `[corpora]`, and why.

    Returns `(name, reason)`. `None` is *no default corpus*, which is a served state and not a
    failure. Raises `UsageError` only for the one case that is a mistake rather than a state: a
    value an operator wrote that names no declared corpus.

    The layer is the discriminator, and `ConfigSource.layer` exists for exactly this kind of
    question. A `BUILTIN` `handbook` in a configuration that declares no `handbook` is the shipped
    default meeting a deployment that never adopted it; the same string in `omniweave.toml` is a
    typo, and `OW-A-002`'s registered meaning -- *"corpus not found (lists the `[corpora]` names)"*
    -- is written for it.
    """
    declared = corpora(config)
    wanted = config.get(DEFAULT_CORPUS_KEY)
    name = wanted if isinstance(wanted, str) else ""
    layer = config.source_of(DEFAULT_CORPUS_KEY).layer

    if name and name in declared:
        return name, f"{DEFAULT_CORPUS_KEY} = {name!r}, declared in [corpora]"
    if not declared:
        return None, "no [corpora] entry is declared"
    if layer is ConfigLayer.BUILTIN:
        return None, (
            f"{DEFAULT_CORPUS_KEY} is the built-in {name!r} and this deployment declares "
            f"{', '.join(declared)}"
        )
    raise UsageError(
        f"[serve] default_corpus = {name!r} names no declared corpus; "
        f"[corpora] declares {', '.join(declared)}",
        symbol="OW_CORPUS_NOT_FOUND",
        fix=(
            f"set [serve] default_corpus to one of: {', '.join(declared)}, "
            f"or declare [corpora.{name}] in omniweave.toml"
        ),
    )


def servable(config: Config, *, env: Mapping[str, str] | None = None) -> Servable:
    """Startup step 5, both clauses, in the order 02:723 writes them.

    SV1 first, because it is the authority check and 10:785 already fixes `enabled` as resolving
    before `listed`; the corpus second, because a deployment whose two keys disagree should hear
    about that rather than about a corpus name. Neither has a repair-and-continue path.

    `config` and `env` are arguments and nothing here reads the ambient environment, so a test
    exercises every combination without a process and two servers in one interpreter do not share
    a surface.
    """
    profile = config.get("serve.profile")
    listed_key = config.get("serve.listed")
    enabled_key = config.get("serve.enabled")
    resolution = resolve(
        profile=profile if isinstance(profile, str) else "default",
        listed_key=_listed(listed_key),
        enabled_key=_enabled(enabled_key),
        env=env,
    )
    corpus, reason = declared_corpus(config)
    compact = config.get(COMPACT_KEY)
    return Servable(
        resolution=resolution,
        corpus=corpus,
        corpora=corpora(config),
        compact=bool(compact),
        corpus_from=reason,
    )


def _listed(value: object) -> list[str] | None:
    """`[serve] listed`'s declared shape, narrowed. A `list` of `str` with no `choices`.

    An empty list is `None` -- *not set* -- because the key's declared default IS the empty list,
    so an empty resolution cannot be distinguished from nobody having written one, and falling
    through to the profile is what the precedence ladder does with a rung nobody set.
    """
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value] or None
    return None


def _enabled(value: object) -> str | list[str] | None:
    """`[serve] enabled`'s two shapes, narrowed. `str_or_list` is the key's declared kind.

    An empty list is `None` -- *not set* -- rather than *enable nothing*: the key's declared default
    is `read_only+add`, so a resolved empty list can only be a layer that wrote one, and a server
    that enabled nothing would refuse every call while starting cleanly. `authority.entries()` draws
    the same line one axis over for the env vars, where the opposite answer is right because there
    the operator typed the emptiness.
    """
    if isinstance(value, str):
        return value or None
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value] or None
    return None
