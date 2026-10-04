"""The reference corpora, generated and ingested once per content digest (ADR-14 D14.1, D14.7).

`fixtures/gen/gen_reference_corpora.py` generates a corpus in about a second. `ow add` is what
costs: minutes for the 5,000-page matter. So a prepared corpus is cached under
`<cache>/<corpus>-<scale>-<digest[:12]>/`, keyed by the sha256 of the corpus MANIFEST, and a
second run reuses it.
- A generator change changes the digest, so a stale cache is never reused.
- A half-built entry lacks `.ready`, and is rebuilt.

Each entry is a project of its own, laid out as `first_answer.py` lays out V01-15's folder:
- `project/omniweave.toml`: one corpus, the default, and D576's three `[drivers]` opt-ins;
- `project/docs/`: the generated files;
- the receipt `project/omniweave.index.lock`, which is what "indexed" means to the re-read rule;
- a `HOME` and an `OMNIWEAVE_HOME` of its own, so nothing of the user's is read or written.

The default cache is `$OMNIWEAVE_HOME/bench-cache/`, or `~/.omniweave/bench-cache/` without it.

**A damaged task gets a damaged corpus of its own** (ADR-14 D14.2 part 4, D640). `damage` names
the file and the Injector (`omniweave_conform.damage.INJECTORS`), the digest covers both, and the
entry is named for the Injector, so a damaged corpus is never the pristine one's cache entry. The
Injector damages the source bytes, so both arms face the same unreadable file.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Final

from first_answer import PROJECT as FIRST_ANSWER_PROJECT
from first_answer import _env
from omniweave_conform.damage import INJECTORS
from omniweave_core.host.subproc import run_captured
from serve_harness import indexed_sources

__all__ = [
    "GENERATOR",
    "CorpusError",
    "Prepared",
    "damage_of",
    "default_cache",
    "generator",
    "key_of",
    "prepare",
]

PROJECT: Final[str] = FIRST_ANSWER_PROJECT + (
    "[retrieval.budget]\nquery_ms = 5000\nhydration_reserve_ms = 500\n"
    "channel_ms = { identity = 150, exact = 250, lexical = 2000, structural = 400,"
    " semantic = 800 }\n"
)
"""first_answer's project, with budgets far above 07's. **D650.** The bench measures what the
agent reads, not how fast a laptop answers: at the shipped `channel_ms.lexical = 50` a nine-word
question over a full-scale corpus took about 51 ms, so whether it timed out depended on the
machine's load, and a recording replayed on another machine, or the same one busier, missed."""

GENERATOR: Final[Path] = (
    Path(__file__).resolve().parents[2] / "fixtures" / "gen" / "gen_reference_corpora.py"
)
ADD_TIMEOUT_S: Final[Mapping[str, float]] = {"quick": 600, "full": 3_600}


class CorpusError(RuntimeError):
    """A corpus that could not be prepared. The message names what failed and how to look."""


@cache
def generator() -> ModuleType:
    """The generator module, loaded by path: `fixtures/gen/` is not a package."""
    spec = importlib.util.spec_from_file_location("omniweave_gen_reference_corpora", GENERATOR)
    if spec is None or spec.loader is None:  # pragma: no cover -- the file is in this repo
        msg = f"cannot load {GENERATOR}"
        raise CorpusError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True, slots=True)
class Prepared:
    """One ingested corpus, ready for both arms."""

    corpus: str
    scale: str
    digest: str
    base: Path
    cached: bool
    add_seconds: float | None
    env: Mapping[str, str] = field(repr=False)
    damage: tuple[tuple[str, str], ...] = ()
    """`(path, injector)` for each damaged file, or empty for the pristine corpus."""

    @property
    def project(self) -> Path:
        return self.base / "project"

    @property
    def docs(self) -> Path:
        return self.project / "docs"

    @property
    def receipt(self) -> Path:
        return self.project / "omniweave.index.lock"

    def indexed(self) -> frozenset[str]:
        """The indexed sources, off the receipt `ow add` wrote (D601's meaning of "indexed")."""
        #  Resolved, as `HostTools` resolves what it records: a symlinked temp folder (macOS's
        #  `/var`) or a spelling that differs by case would otherwise never compare equal. D650.
        root = self.project.resolve().as_posix()
        return indexed_sources(self.receipt.read_text(encoding="utf-8"), root)


def damage_of(task_id: str, injector: str | None) -> tuple[tuple[str, str], ...]:
    """A damaged task's damage: its Injector over the one file `PLANTED` wrote its answer into.

    13-quality.md section 8.8's damaged class asks *"does the agent act on `degraded` rather than
    answering anyway"*, so the file the Injector damages is the one that holds the answer.
    """
    if injector is None:
        return ()
    return ((generator().PLANTED[task_id].path, injector),)


def key_of(corpus: str, damage: tuple[tuple[str, str], ...]) -> str:
    """The name a prepared corpus is looked up by: the corpus, then each damaged file."""
    return corpus + "".join(f"+{name}:{path}" for path, name in damage)


def default_cache() -> Path:
    home = os.environ.get("OMNIWEAVE_HOME")
    return (Path(home) if home else Path.home() / ".omniweave") / "bench-cache"


def prepare(
    corpus: str,
    scale: str,
    *,
    cache_root: Path,
    damage: tuple[tuple[str, str], ...] = (),
    python: str = sys.executable,
    log: Callable[[str], None] = lambda _line: None,
) -> Prepared:
    """Generate and ingest `corpus` at `scale`, or reuse the cached entry with the same digest.

    `damage` applies each named Injector to its file before `ow add` reads it.
    """
    gen = generator()
    documents = gen.documents(corpus, scale)
    digest = hashlib.sha256(gen.manifest_bytes(documents) + _damage_bytes(damage)).hexdigest()
    label = "-".join(name for _path, name in damage)
    base = cache_root / f"{corpus}-{scale}-{label + '-' if label else ''}{digest[:12]}"
    ready = base / ".ready"
    project = base / "project"
    shown = f"{corpus} ({scale}{', ' + label if label else ''})"
    if ready.is_file() and (project / "omniweave.index.lock").is_file():
        #  Rewritten on a hit too: the budget is read per query, not at ingest, and a cache made
        #  before it would otherwise answer with the shipped one.
        (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
        log(f"  corpus    {shown}: cached, {len(documents)} files, {base.as_posix()}")
        return Prepared(
            corpus, scale, digest, base, cached=True, add_seconds=None, env=_env(base),
            damage=damage,
        )  # fmt: skip
    if base.exists():
        shutil.rmtree(base)
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    damaged = dict(damage)
    unknown = sorted(set(damaged) - {document.path for document in documents})
    if unknown:
        msg = f"{corpus} ({scale}) has no {unknown} to damage"
        raise CorpusError(msg)
    for document in documents:
        path = project / "docs" / document.path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = document.to_bytes()
        if document.path in damaged:
            data = INJECTORS[damaged[document.path]].transform(data)
        path.write_bytes(data)
    env = _env(base)
    log(f"  corpus    {shown}: generated {len(documents)} files; running ow add")
    started = time.perf_counter()
    added = run_captured(
        (python, "-m", "omniweave", "add", "docs"),
        stdin=b"",
        cwd=str(project),
        env=env,
        timeout_s=ADD_TIMEOUT_S[scale],
    )
    seconds = round(time.perf_counter() - started, 1)
    if added.returncode != 0 or not (project / "omniweave.index.lock").is_file():
        tail = added.stderr.decode("utf-8", "replace")[-1500:]
        msg = (
            f"ow add over {shown} exited {added.returncode} after {seconds} s. "
            f"The project is kept at {project.as_posix()} to inspect; its stderr ends:\n{tail}"
        )
        raise CorpusError(msg)
    ready.write_text(digest + "\n", encoding="utf-8")
    log(f"  corpus    {shown}: ingested in {seconds} s, {base.as_posix()}")
    return Prepared(
        corpus, scale, digest, base, cached=False, add_seconds=seconds, env=env, damage=damage
    )


def _damage_bytes(damage: tuple[tuple[str, str], ...]) -> bytes:
    """What a damage spec adds to the digest: nothing for the pristine corpus, so its key holds."""
    if not damage:
        return b""
    for _path, name in damage:
        if name not in INJECTORS:
            msg = f"{name!r} is not a built Injector; built: {sorted(INJECTORS)}"
            raise CorpusError(msg)
    return b"".join(f"damage {name} {path}\n".encode() for path, name in damage)
