"""G19 through the product: both stores built by real `ow add` children. The builder. **D908.**

`tools/incremental_index.py` builds G19's two stores through `tools/p2_stub_parse.py` and a
`DocSink`, which is what P2 could run. D905 made a document its place in the corpus, so an edit
through `ow add` is its document's next generation and the gate can now ask its question of the
product itself: does a store kept current by `ow add` export what a fresh `ow add` of the same
files exports? This module is that builder; `tools/gate_incremental.py` is still the harness and
the comparator, and loads it by path as it loads the other.

## Rulings

1. **The corpus and the script are `fixtures/gen/gen_incremental.py`'s.** A document is written as
   its uri's last segment plus `.pdf` (`doc-000017.pdf`, renamed `doc-000017-r1.pdf`), so an edit
   keeps the file's name and a rename moves it. `pdfium` parses them, as a user's `ow add` would.
   Its bytes are the fixture's for the document as it was before any rename (`_bytes`): the
   fixture seeds a PDF's `/ID` from the uri, so its renamed document is other bytes, where a user's
   rename moves the same bytes, which is what D905's move detection exists to recognise.
2. **Each scripted mutation is what a user does to the folder, then `ow add docs`.**
   - `edit` rewrites the file's bytes, and `add` writes a new file.
   - `delete` removes the file and runs the explicit retirement `ow store rm --doc` will issue
     (`discover.retire_document`), as GR8's harness does: deletion is never inferred.
   - `rename` moves the file; D905's move detection keeps its document.
   - `touch` moves the mtime and not the bytes.
   - `driver_version` raises `parse.pdf.pdfium`'s `min_chars` by one, a semantic config change
     that re-parses every document (D679), as GR8 bumps anydoc's.
3. **A full rebuild is a fresh project holding the step's roster and the same config**, added
   once. Both projects are exported with `store.portable.export_portable`, one archive per
   document named by its `doc_key`. A location key is relative to the project, so the two sides
   name a document alike. A retired document's archive is removed from the export: retirement keeps
   the rows so a shipped cite still resolves, a full rebuild never had them, and G19 compares the
   live corpus. Each side's project root is returned with its exports, so the
   comparator can relocate the one field that prints it, `manifest.json`'s `source.uri`.
4. **A child that exits non-zero is `RuntimeError`**, which the harness reports as DID NOT RUN.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sqlite3  # noqa: TID251 -- the explicit retirement runs on the store the add wrote.
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parent.parent

for _dist in sorted((REPO / "packages").iterdir()) if (REPO / "packages").is_dir() else []:
    _src = _dist / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from omniweave.run.discover import retire_document  # noqa: E402
from omniweave_core.blobs import BlobStore  # noqa: E402
from omniweave_core.host.subproc import run_captured  # noqa: E402
from omniweave_core.identity import canonical_uri  # noqa: E402
from omniweave_core.store import sqlite as ow  # noqa: E402
from omniweave_core.store.fragment import RETIRED_X  # noqa: E402
from omniweave_core.store.portable import export_portable  # noqa: E402

__all__ = ["PROJECT", "Built", "build", "file_name", "fixture"]

PROJECT: Final = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
"""The project file both sides run under, as the conform tests' and GR8's (D576)."""
PARSE_DRIVER: Final = "parse.pdf.pdfium"
STORE: Final = Path(".omniweave") / "docs.owstore"
CAS: Final = Path(".omniweave") / "cas"
ADD_TIMEOUT_S: Final = 1800


@dataclass(frozen=True, slots=True)
class Built:
    """One checkpoint: both export directories and both project roots, in canonical form."""

    step: int
    incremental: Path
    full: Path
    roots: tuple[str, str]


def fixture() -> ModuleType:
    """`fixtures/gen/gen_incremental.py`, loaded by path."""
    path = REPO / "fixtures" / "gen" / "gen_incremental.py"
    spec = importlib.util.spec_from_file_location("omniweave_gen_incremental_add", path)
    if spec is None or spec.loader is None:  # pragma: no cover -- a broken checkout.
        message = f"cannot load {path}"
        raise ValueError(message)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def file_name(document: Any) -> str:
    """Ruling 1: the uri's last segment, as a PDF."""
    return str(document.uri).rsplit("/", 1)[-1] + ".pdf"


def _config(bumps: int) -> str:
    """Ruling 2's project file after `bumps` driver-version steps."""
    if not bumps:
        return PROJECT
    return PROJECT + f'[drivers."{PARSE_DRIVER}".config]\nmin_chars = {1 + bumps}\n'


def _environment(root: Path) -> dict[str, str]:
    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    return {**keep, "HOME": str(home), "USERPROFILE": str(home), "OMNIWEAVE_HOME": str(root / "ow")}


def _add(project: Path, env: Mapping[str, str]) -> None:
    """Ruling 4: `ow add docs` in `project`, or `RuntimeError` with what it printed."""
    done = run_captured(
        (sys.executable, "-m", "omniweave", "add", "docs"),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=ADD_TIMEOUT_S,
    )
    if done.returncode != 0:
        shown = (done.stdout + done.stderr).decode("utf-8", "replace")
        message = f"ow add in {project.name} exited {done.returncode}: {shown[-2000:]}"
        raise RuntimeError(message)


def _bytes(corpus: ModuleType, document: Any) -> bytes:
    """Ruling 1: the PDF as it was before any rename, so a rename moves the same bytes."""
    return bytes(corpus.document_bytes(replace(document, renames=0)))


def _project(root: Path, documents: Sequence[Any], corpus: ModuleType, bumps: int) -> Path:
    """A fresh project under `root` holding `documents` and the config after `bumps`."""
    (root / "docs").mkdir(parents=True)
    (root / "omniweave.toml").write_bytes(_config(bumps).encode("utf-8"))
    for document in documents:
        (root / "docs" / file_name(document)).write_bytes(_bytes(corpus, document))
    return root


def _retire(project: Path, name: str) -> None:
    """Ruling 2's delete: the explicit retirement of the one live document at `docs/<name>`."""
    connection = sqlite3.connect(project / STORE, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        live = connection.execute(
            "SELECT doc_ord, gen, uri FROM doc WHERE json_extract(x, ?) IS NULL",
            (f'$."{RETIRED_X}"',),
        ).fetchall()
        found = [(int(o), int(g)) for o, g, uri in live if str(uri).endswith(f"/docs/{name}")]
        if len(found) != 1:
            connection.execute("ROLLBACK")
            message = f"{name}: {len(found)} live documents, expected exactly one"
            raise RuntimeError(message)
        retire_document(connection, *found[0])  # type: ignore[arg-type]
        connection.execute("COMMIT")
    finally:
        connection.close()


def _export(project: Path, directory: Path) -> Path:
    """Ruling 3: every live document of `project` into a fresh `directory`."""
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    connection = ow.connect_readonly(project / STORE)
    try:
        result = export_portable(connection, directory, blobs=BlobStore(project / CAS))
        retired = [
            bytes(row[0]).hex()
            for row in connection.execute(
                "SELECT doc_key FROM doc WHERE json_extract(x, ?) IS NOT NULL",
                (f'$."{RETIRED_X}"',),
            )
        ]
    finally:
        connection.close()
    for key in retired:
        (directory / f"{key}.owdoc").unlink(missing_ok=True)
    if result.skipped:  # pragma: no cover -- a document with no root block.
        message = f"export skipped {len(result.skipped)} document(s): {result.skipped[:3]}"
        raise RuntimeError(message)
    return directory


def _apply(
    project: Path,
    mutation: Any,
    before: Mapping[int, Any],
    after: Mapping[int, Any],
    corpus: ModuleType,
) -> None:
    """Ruling 2: one scripted mutation, done to the incremental project's folder."""
    docs = project / "docs"
    if mutation.kind in {"edit", "add"}:
        document = after[mutation.slot]
        (docs / file_name(document)).write_bytes(_bytes(corpus, document))
    elif mutation.kind == "delete":
        name = file_name(before[mutation.slot])
        (docs / name).unlink()
        _retire(project, name)
    elif mutation.kind == "rename":
        (docs / file_name(before[mutation.slot])).rename(docs / file_name(after[mutation.slot]))
    elif mutation.kind == "touch":
        os.utime(docs / file_name(before[mutation.slot]))


def build(
    root: Path,
    steps: Sequence[int],
    *,
    documents: int,
    mutations: Sequence[Any],
    corpus: ModuleType | None = None,
) -> Iterator[Built]:
    """The incremental project carried through `mutations`, and a full rebuild at each step asked.

    `steps` are 1-based mutation counts, as `gate_incremental.checkpoint_steps()` returns them.
    """
    corpus = fixture() if corpus is None else corpus
    env = _environment(root)
    roster = {d.slot: d for d in corpus.corpus_for(documents, mutations, 0)}
    incremental = _project(root / "incremental", list(roster.values()), corpus, 0)
    _add(incremental, env)
    bumps = 0
    wanted = sorted(steps)
    for step in range(1, (wanted[-1] if wanted else 0) + 1):
        mutation = mutations[step - 1]
        after = {d.slot: d for d in corpus.corpus_for(documents, mutations, step)}
        if mutation.kind == "driver_version":
            bumps += 1
            (incremental / "omniweave.toml").write_bytes(_config(bumps).encode("utf-8"))
        else:
            _apply(incremental, mutation, roster, after, corpus)
        _add(incremental, env)
        roster = after
        if step in wanted:
            full = _project(root / f"full-{step}", list(roster.values()), corpus, bumps)
            _add(full, env)
            yield Built(
                step=step,
                incremental=_export(incremental, root / f"incremental-exports-{step}"),
                full=_export(full, root / f"full-exports-{step}"),
                roots=(canonical_uri(incremental), canonical_uri(full)),
            )
