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
5. **`ingest()` is the Tier-A ingest, a child `ow add`** (D903, moved here from
   `tools/ow_golden.py` so the portability suite reaches it). Every fixture `fixtures/index.toml`
   lists is copied into a scratch project with the three `[drivers]` opt-ins a checkout needs
   (D576), `python -m omniweave add docs` runs through `host.subproc.run_captured()`, and the store
   is reduced. A child that exits anything but 0 is `OSError` with its last lines, so the caller
   reports that it did not run. `ow add` exits 0 with refused fixtures, which are recorded per
   unit as `partial`: this corpus's normal state.

Specified in 13-quality.md sections 5.1 to 5.5, and 16-roadmap.md W10.2.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.host.subproc import run_captured
from omniweave_core.store import sqlite as ow
from omniweave_core.store.export_source import StoreExportSource

from omniweave_conform.churn import Churn, Decomposition, Reductions, classify
from omniweave_conform.reduce import reduce_outline, reduce_pages, reduce_shape

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "CORPUS",
    "GOLDENS",
    "INGEST_TIMEOUT_S",
    "KINDS",
    "PROJECT",
    "Change",
    "changes",
    "document_paths",
    "ingest",
    "read_tree",
    "reductions",
]

GOLDENS: Final = "fixtures/goldens"
CORPUS: Final = "core@2026.10"
KINDS: Final = ("shape", "pages", "outline")
PROJECT: Final = (
    '[corpora.handbook]\npath = ".omniweave/index.owstore"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
"""Ruling 5: the project file a scratch ingest runs under, as the conform tests' (D576)."""
INGEST_TIMEOUT_S: Final = 1800.0


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


def ingest(root: Path, corpus: str = CORPUS) -> dict[str, str]:
    """Rulings 5 and 1: every `fixtures/index.toml` fixture ingested and reduced, or `OSError`."""
    rows = tomllib.loads((root / "fixtures" / "index.toml").read_text(encoding="utf-8"))
    scratch = Path(tempfile.mkdtemp(prefix="ow-golden-"))
    try:
        for row in rows.get("fixture", []):
            source = root / row["path"]
            parts = Path(row["path"]).parts
            target = scratch / "docs" / Path(*parts[1:2], *parts[3:])
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, target)
        (scratch / "omniweave.toml").write_bytes(PROJECT.encode("utf-8"))
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
        env["OMNIWEAVE_HOME"] = str(scratch / "owhome")
        done = run_captured(
            (sys.executable, "-m", "omniweave", "add", "docs"),
            stdin=b"",
            cwd=str(scratch),
            env=env,
            timeout_s=INGEST_TIMEOUT_S,
        )
        if done.returncode != 0:
            shown = (done.stdout + done.stderr).decode("utf-8", errors="replace")
            status = done.returncode if done.returncode is not None else done.failed
            message = f"ow add exited {status}: " + " | ".join(shown.splitlines()[-5:])
            raise OSError(message)
        connection = ow.connect_readonly(scratch / ".omniweave" / "index.owstore")
        try:
            return reductions(connection, scratch / ".omniweave" / "cas", corpus=corpus)
        finally:
            connection.close()
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


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
