"""The golden Reductions of a store: one `shape`, `pages` and `outline` per document. **D848.**

13-quality.md section 5.1 commits Reductions, *"deterministic, sorted, LF-normalised,
line-oriented projections"*, one set per `(corpus, driver, doc)` under `fixtures/goldens/`
(:644's path, `fixtures/goldens/core@2026.09/parse.office.anydoc@3/eu-annual-report-2019.shape`).
`omniweave_conform.reduce` writes one document's three (D817, D818), and `churn` classifies a
change (D819). Nothing yet ran them over the corpus, so `fixtures/goldens/` held only
`DECOMPOSITION.toml`, and Q-G3, Q-G4 and Q-G2's Reduction cap had nothing to read. This module
reduces every document a store holds and compares a fresh set with a committed one.
`tools/ow_golden.py` ingests the Tier-A fixtures and drives it.

## Rulings

1. **A Reduction's path is `<corpus>/<driver>@<n>/<file>.<kind>`.**
   - `<driver>` is the blocks' `origin_driver`, and `<n>` is their `driver_schema_v`, the version
     the store records. A package semver is not in the store, and a golden cannot read what the
     store did not keep.
   - `<file>` is the source's file name with its extension. Stems collide within one driver, as
     `deck.odp` and `deck.pptx` are both anydoc's.
   - The header carries the same `driver=` string.
2. **`CORPUS` is `core@2026.10`**: the Tier-A fixtures, and the month their goldens were first
   blessed. A new version moves every path, so changing it is a bless of every document, which is
   what it is.
3. **A document with no blocks has no Reductions.** A fixture a driver refuses produces no
   document, so it has no golden, and its refusal is the conformance suites' to hold.
4. **A change is judged per document, by `churn.classify()` over its three files.** A document
   that appears or disappears is `structural`: a new frozen `shape` is a new claim about the
   corpus, and a lost one is a claim withdrawn. `unchanged` documents are not changes.

Specified in 13-quality.md sections 5.1 to 5.5, and 16-roadmap.md W10.2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.store.export_source import StoreExportSource

from omniweave_conform.churn import Churn, Decomposition, Reductions, classify
from omniweave_conform.reduce import reduce_outline, reduce_pages, reduce_shape

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

__all__ = [
    "CORPUS",
    "GOLDENS",
    "KINDS",
    "Change",
    "changes",
    "document_paths",
    "read_tree",
    "reductions",
]

GOLDENS: Final = "fixtures/goldens"
CORPUS: Final = "core@2026.10"
KINDS: Final = ("shape", "pages", "outline")


@dataclass(frozen=True, slots=True)
class Change:
    """One document's change: its path without the kind, its class, and why."""

    doc: str
    churn: Churn


def reductions(connection: Any, cas: Path, *, corpus: str = CORPUS) -> dict[str, str]:
    """Rulings 1 and 3: `{relative path: text}` for every document in the store, every kind."""
    out: dict[str, str] = {}
    ords = [int(row[0]) for row in connection.execute("SELECT doc_ord FROM doc ORDER BY doc_ord")]
    for doc_ord in ords:
        source = StoreExportSource(connection, cas, doc_ord)
        first = next(iter(source.blocks()), None)
        if first is None:
            continue
        driver = f"{first.block.origin_driver}@{first.block.driver_schema_v}"
        name = str(source.header().source["uri"]).replace("\\", "/").rsplit("/", 1)[-1]
        base = f"{corpus}/{driver}/{name}"
        texts = (
            reduce_shape(source, corpus=corpus, driver=driver),
            reduce_pages(source, corpus=corpus, driver=driver),
            reduce_outline(source, corpus=corpus, driver=driver),
        )
        for kind, text in zip(KINDS, texts, strict=True):
            out[f"{base}.{kind}"] = text
    return out


def read_tree(root: Path, corpus: str = CORPUS) -> dict[str, str]:
    """The committed Reductions under `root/fixtures/goldens/<corpus>/`, by relative path."""
    base = root / GOLDENS
    folder = base / corpus
    if not folder.is_dir():
        return {}
    return {
        path.relative_to(base).as_posix(): path.read_bytes().decode("utf-8")
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.suffix.lstrip(".") in KINDS
    }


def document_paths(tree: Mapping[str, str]) -> dict[str, Reductions]:
    """Group a tree's files by document, `<corpus>/<driver>/<file>`, into `Reductions`."""
    grouped: dict[str, dict[str, str]] = {}
    for path, text in tree.items():
        doc, _, kind = path.rpartition(".")
        grouped.setdefault(doc, {})[kind] = text
    return {
        doc: Reductions(kinds.get("shape", ""), kinds.get("pages", ""), kinds.get("outline", ""))
        for doc, kinds in grouped.items()
    }


def changes(
    committed: Mapping[str, str], fresh: Mapping[str, str], decomposition: Decomposition
) -> list[Change]:
    """Ruling 4: each document that moved, appeared or vanished, in path order."""
    before, after = document_paths(committed), document_paths(fresh)
    out = []
    for doc in sorted(set(before) | set(after)):
        if doc not in before:
            out.append(Change(doc, Churn("structural", (), ("a new document",))))
        elif doc not in after:
            out.append(Change(doc, Churn("structural", (), ("the document is gone",))))
        else:
            churn = classify(before[doc], after[doc], decomposition)
            if churn.cls != "unchanged":
                out.append(Change(doc, churn))
    return out
