"""Q-G26, split and corpus leakage: the three clauses as pure functions over rows. **D875.**

13-quality.md:1831: *"No `doc_key` appears in two splits under the recomputed
`blake2b(doc_key‖"ow-split-1") % 100`; no Tier-A fixture sha256 appears in `omniweave-golden`'s
manifest; no `eval_assertion.derived_from_sha256` points at a fixture outside its own corpus
(`OW-Q-015`)."* The failure it prevents: *"a fixture used to debug a parser becoming part of the
corpus that scores it, which inflates every number and is invisible in every report"*.
`tools/gate_leakage.py` reads the inputs and prints; this module decides.

## Rulings

1. **A split row is `(doc_key, split)`, and the split is recomputed, never trusted.** A row whose
   split is not `stats.split_of(doc_key)`, or a `doc_key` named in two splits, is a finding. The
   split function is the one 13:1431 says three uses share.
2. **Fixture-into-golden is a digest intersection.** Every Tier-A fixture's sha256 (D844: every
   committed byte under `fixtures/` or a `packages/<dist>/fixtures/` tree) against every sha256 the
   golden's manifest lists. Any common digest is a fixture the corpus would score.
3. **An assertion's derivation must stay in its corpus.** `derived_from_sha256` is *"the licence
   chain FOR THE ASSERTION ITSELF"* (the `eval_assertion` DDL), the source bytes it was written
   from. When that digest is a Tier-A fixture's, the fixture's path must lie under the assertion's
   corpus, whose `corpus_id` is then its directory. A digest no fixture has is outside Tier A, which
   this clause does not judge.

Specified in 13-quality.md sections 9.1 and 15 (Q-G26) and the `eval_assertion` DDL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from omniweave_conform.stats import split_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

__all__ = ["CODE", "Leak", "assertion_leaks", "golden_leaks", "split_leaks"]

CODE: Final = "OW-Q-015"


@dataclass(frozen=True, slots=True)
class Leak:
    """One way a corpus can see what scores it: the clause, what it names, and why."""

    clause: str
    names: str
    why: str


def split_leaks(rows: Iterable[tuple[str, str]]) -> list[Leak]:
    """Ruling 1: each `(doc_key, split)` against the recomputed split, and against the others."""
    seen: dict[str, set[str]] = {}
    leaks: list[Leak] = []
    for doc_key, split in rows:
        seen.setdefault(doc_key, set()).add(split)
        recomputed = split_of(doc_key)
        if split != recomputed:
            leaks.append(
                Leak("split", doc_key, f"recorded in {split}, recomputed into {recomputed}")
            )
    leaks += [
        Leak("split", doc_key, f"in both {' and '.join(sorted(splits))} ({CODE})")
        for doc_key, splits in sorted(seen.items())
        if len(splits) > 1
    ]
    return leaks


def golden_leaks(fixtures: Mapping[str, str], manifest: Iterable[str]) -> list[Leak]:
    """Ruling 2: every Tier-A fixture whose sha256 the golden manifest also lists."""
    listed = set(manifest)
    return [
        Leak("golden", path, f"its sha256 {digest[:16]} is in omniweave-golden's manifest ({CODE})")
        for digest, path in sorted(fixtures.items(), key=lambda item: item[1])
        if digest in listed
    ]


def assertion_leaks(
    assertions: Iterable[tuple[str, str, str]], fixtures: Mapping[str, str]
) -> list[Leak]:
    """Ruling 3: each `(assertion_id, corpus_id, derived_from_sha256)` against Tier A's digests.

    `fixtures` maps a sha256 to the Tier-A path holding those bytes.
    """
    leaks = []
    for assertion_id, corpus_id, derived in assertions:
        path = fixtures.get(derived)
        if path is None:
            continue
        own = corpus_id.rstrip("/") + "/"
        if not path.startswith(own):
            leaks.append(
                Leak(
                    "assertion",
                    assertion_id,
                    f"derived from {path}, a fixture outside its corpus {corpus_id} ({CODE})",
                )
            )
    return leaks
