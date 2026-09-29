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

from first_answer import PROJECT, _env
from omniweave_core.host.subproc import run_captured
from serve_harness import indexed_sources

__all__ = ["GENERATOR", "CorpusError", "Prepared", "default_cache", "generator", "prepare"]

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
        return indexed_sources(self.receipt.read_text(encoding="utf-8"), self.project.as_posix())


def default_cache() -> Path:
    home = os.environ.get("OMNIWEAVE_HOME")
    return (Path(home) if home else Path.home() / ".omniweave") / "bench-cache"


def prepare(
    corpus: str,
    scale: str,
    *,
    cache_root: Path,
    python: str = sys.executable,
    log: Callable[[str], None] = lambda _line: None,
) -> Prepared:
    """Generate and ingest `corpus` at `scale`, or reuse the cached entry with the same digest."""
    gen = generator()
    documents = gen.documents(corpus, scale)
    digest = hashlib.sha256(gen.manifest_bytes(documents)).hexdigest()
    base = cache_root / f"{corpus}-{scale}-{digest[:12]}"
    ready = base / ".ready"
    project = base / "project"
    if ready.is_file() and (project / "omniweave.index.lock").is_file():
        log(f"  corpus    {corpus} ({scale}): cached, {len(documents)} files, {base.as_posix()}")
        return Prepared(corpus, scale, digest, base, cached=True, add_seconds=None, env=_env(base))
    if base.exists():
        shutil.rmtree(base)
    (project / "docs").mkdir(parents=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    for document in documents:
        path = project / "docs" / document.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(document.to_bytes())
    env = _env(base)
    log(f"  corpus    {corpus} ({scale}): generated {len(documents)} files; running ow add")
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
            f"ow add over {corpus} ({scale}) exited {added.returncode} after {seconds} s. "
            f"The project is kept at {project.as_posix()} to inspect; its stderr ends:\n{tail}"
        )
        raise CorpusError(msg)
    ready.write_text(digest + "\n", encoding="utf-8")
    log(f"  corpus    {corpus} ({scale}): ingested in {seconds} s, {base.as_posix()}")
    return Prepared(corpus, scale, digest, base, cached=False, add_seconds=seconds, env=env)
