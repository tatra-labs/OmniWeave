"""`NOTICE`, `LICENSES/` and `THIRD_PARTY.md`, generated per project directory. G3's second half.

11-repo-layout.md section 1.5 rule 2: *"`NOTICE`, `LICENSES/` and `THIRD_PARTY.md` are generated,
per distribution, and `--check` gated. Attribution drift is the single most common licence defect
in the mined collection."* Section 9.1 gives the reason there are many copies rather than one: PEP
639 resolves `license-files` globs relative to the project directory and rejects a pattern that
escapes it with `..`, so `packages/omniweave-core/` cannot reference the repository root's
`LICENSE`. Section 7.6 step 5 is the release checklist line this script is, and `tools/gates.toml`
carries it as G3's second half -- *"the sixteen `gen_notice.py --check` trees"*.

The mined collection is why: codegraph vendors 27 tree-sitter grammars at pinned revisions with a
node-kind parity test -- careful supply-chain work -- and ships three `LICENSE` files among the 27,
no top-level `NOTICE` and no `THIRD_PARTY`, leaving it plausibly out of compliance with ~24 upstream
MIT licences whose text MIT requires be shipped. hyperframes packs ~212 MB of third-party binaries
into a Lambda zip, asserts the ffmpeg binary's architecture and not its hash, and carries no ffmpeg
attribution anywhere -- while demonstrably knowing the practice elsewhere in the same repository.
Generating the files is the only defence that survives a rush.

## Rulings

1. **A tree is a project directory**: every `packages/*/pyproject.toml`'s parent, plus the
   repository root. That is **sixteen** today, and since D999 (a user ruling of 2026-10-27) so is
   section 9.1: "the fifteen `packages/<dist>/` directories plus the repository root". The number
   is not read here and the set is not hard-coded: it is `glob("packages/*/pyproject.toml")`, so it
   was fifteen when the plan was written, became sixteen when `omniweave-langchain` arrived (an
   attachment, section 1.2's second table), and will move again with the next distribution. That
   independence is why the erratum cost nothing: the script emitted sixteen trees throughout the
   period the plan said fifteen, so no distribution ever shipped without a notice, and what D999
   amended was four numbers in the prose rather than any behaviour here. `test_gen_notice.py` reads
   section 9.1's sentence back and compares the number it spells with `len(trees())`, which is the
   only form in which an amended count can be said to hold.
2. **`THIRD_PARTY.md` lists what the distribution DECLARES, not its resolved closure.** The
   closure is a property of an environment -- `uv.lock` reaches 68 packages from `omniweave` and 89
   from `omniweave-langchain`, almost all of them behind an extra -- while the artefact introduces
   exactly the third-party requirements its own `pyproject.toml` states. Section 9.1's own examples
   are the declaration: *"`omniweave-pdf`'s lists pdfium's BSD-3-Clause, `omniweave-target-pptx`'s
   lists five packages, and `omniweave-core`'s lists nothing at all"* -- and core's closure is NOT
   empty (it reaches `pysqlite3-binary` through the `[sqlite]` extra), so the sentence can only be
   true of the declaration. An extra's requirement is listed and labelled with the extra that
   brings it, because installing it is the reader's choice and the attribution is still owed.
3. **A version comes from `uv.lock`**, the resolution this repository commits, so the file is a
   function of the tree and not of the machine that ran the script.
4. **A licence text is captured once, into every tree that needs it, and digested.**
   `--refresh` reads each distribution's own licence files out of the installed environment (its
   `License-File` metadata, else its `.dist-info` licence files) and writes
   `<tree>/LICENSES/<name>.txt`; `tools/licences_captured.toml` records the version, the source
   path and the sha256 of every text. `--check` never reads the environment: it holds the committed
   trees to the index and to each other, which is the half CI can run on a machine that installs
   only the dev group. The one thing it cannot see -- whether a text really is what upstream ships
   -- is what the digest is for, exactly as `tools/vendor.toml` does it for vendored code.
5. **A dependency whose text cannot be captured is named, never omitted.** `firecrawl-anydoc`
   ships no licence file in its wheel at all (a finding, and the reason `vendor/anydoc/` carries
   LICENSE and NOTICE at a pinned SHA), and `pysqlite3-binary` is behind an extra nobody installed
   here. Each gets a row saying so and pointing at where the licence is, so a reviewer reads a
   gap rather than a silence.
6. **`LICENSE` and `LICENSES/Apache-2.0.txt` are the project's own licence**, byte-identical to the
   repository root's `LICENSE` in every tree. Sixteen copies of the Apache-2.0 text is about 176 KB
   and is the price of the licence actually shipping (section 9.1).

Usage:

    uv run tools/gen_notice.py                 # emit every tree
    uv run tools/gen_notice.py --check         # exit 1 on any drift, reading no environment
    uv run tools/gen_notice.py --refresh       # re-capture the licence texts from the install

Exit codes: `0` clean, `1` a finding, `2` the run could not be made (no `uv.lock`, no `LICENSE`).

Specified in 11-repo-layout.md sections 1.5, 7.6 and 9.1, and `tools/gates.toml`'s G3 row.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
from dataclasses import dataclass
from importlib.metadata import Distribution, distributions
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[1]
LOCK: Final = REPO / "uv.lock"
LICENCE: Final = REPO / "LICENSE"
INDEX: Final = REPO / "tools" / "licences_captured.toml"
VENDOR: Final = REPO / "tools" / "vendor.toml"
OWN: Final = "Apache-2.0"
EXIT_CLEAN: Final = 0
EXIT_FAIL: Final = 1
EXIT_NOT_RUN: Final = 2
_NAME: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
_DEPTH: Final = 2
"""How deep inside a distribution a licence file may sit to count as its primary one:
`<dist>-<version>.dist-info/licenses/LICENSE` is two separators. Deeper is a bundled
third-party notice, which is `gate_licences.py --deep`'s business and not attribution for
the package itself."""
_HEADER: Final = (
    "<!-- GENERATED by tools/gen_notice.py. Do not edit: G3 runs `--check` and this file is a\n"
    "     function of the pyproject declarations, uv.lock and tools/licences_captured.toml. -->\n"
)


@dataclass(frozen=True, slots=True)
class Requirement:
    """One declared third-party requirement of one distribution (ruling 2)."""

    name: str
    extra: str
    """The extra that brings it, or `""` when it is required."""

    @property
    def key(self) -> str:
        return pep503(self.name)


@dataclass(frozen=True, slots=True)
class Captured:
    """One licence text in the index (ruling 4)."""

    name: str
    version: str
    source: str
    sha256: str
    spdx: str
    note: str = ""


@dataclass(frozen=True, slots=True)
class Tree:
    """One project directory and what it must carry."""

    path: Path
    dist: str
    requires: tuple[Requirement, ...]

    @property
    def relative(self) -> str:
        return self.path.relative_to(REPO).as_posix() or "."


def pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def trees() -> list[Tree]:
    """Ruling 1: every project directory, from the glob rather than from a count."""
    out = []
    for path in sorted((REPO / "packages").glob("*/pyproject.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))["project"]
        out.append(Tree(path.parent, data["name"], _requirements(data, first_party())))
    root = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    name = root.get("project", {}).get("name", "omniweave-monorepo")
    out.append(Tree(REPO, name, ()))
    return out


def first_party() -> frozenset[str]:
    """Every workspace member, so a first-party edge is never an attribution row."""
    return frozenset(
        pep503(tomllib.loads(path.read_text(encoding="utf-8"))["project"]["name"])
        for path in (REPO / "packages").glob("*/pyproject.toml")
    )


def _requirements(project: dict[str, object], ours: frozenset[str]) -> tuple[Requirement, ...]:
    """Ruling 2: the declared third-party requirements, required first then by extra."""
    found: dict[str, Requirement] = {}
    required = project.get("dependencies", [])
    optional = project.get("optional-dependencies") or {}
    groups: list[tuple[str, object]] = [("", required)]
    if isinstance(optional, dict):
        groups.extend(sorted(optional.items()))
    for extra, entries in groups:
        if not isinstance(entries, list):
            continue
        for raw in entries:
            matched = _NAME.match(str(raw).strip())
            if matched is None:
                continue
            name = matched.group(0)
            if pep503(name) in ours or pep503(name) in found:
                continue
            found[pep503(name)] = Requirement(name, extra)
    return tuple(found[key] for key in sorted(found))


def versions() -> dict[str, str]:
    """Ruling 3: `uv.lock`'s resolved version per package."""
    lock = tomllib.loads(LOCK.read_text(encoding="utf-8"))
    return {pep503(str(p["name"])): str(p.get("version", "?")) for p in lock["package"]}


def index() -> dict[str, Captured]:
    """Ruling 4: `tools/licences_captured.toml`, or an empty index before the first refresh."""
    if not INDEX.is_file():
        return {}
    raw = tomllib.loads(INDEX.read_text(encoding="utf-8"))
    rows = raw.get("licence", [])
    out = {}
    for row in rows if isinstance(rows, list) else []:
        captured = Captured(
            name=str(row["name"]),
            version=str(row["version"]),
            source=str(row["source"]),
            sha256=str(row["sha256"]),
            spdx=str(row.get("spdx", "")),
            note=str(row.get("note", "")),
        )
        out[pep503(captured.name)] = captured
    return out


def notice(tree: Tree, rows: list[tuple[Requirement, Captured | None]]) -> str:
    """The `NOTICE` text: the project, its licence, and what travels with it."""
    third = [one for one, _ in rows]
    lines = [
        f"{tree.dist}",
        "Copyright The omniweave authors",
        "",
        "This product includes software developed as part of the omniweave project",
        f"(https://github.com/tatra-labs/OmniWeave), licensed under {OWN}. The licence text",
        "is in LICENSE and in LICENSES/Apache-2.0.txt.",
        "",
    ]
    if third:
        lines += [
            "This distribution declares the third-party requirements listed in THIRD_PARTY.md.",
            "Each one's licence text is in LICENSES/, named for the package, and the versions",
            "are the ones uv.lock resolves.",
        ]
    else:
        lines += [
            "This distribution declares no third-party requirement. THIRD_PARTY.md says so and",
            "is generated from the same declaration, so it cannot drift from the packaging.",
        ]
    lines += ["", "Generated by tools/gen_notice.py. Do not edit.", ""]
    return "\n".join(lines)


def third_party(
    tree: Tree, rows: list[tuple[Requirement, Captured | None]], lock: dict[str, object]
) -> str:
    """The `THIRD_PARTY.md` text: one row per declared requirement (rulings 2, 3 and 5)."""
    out = [_HEADER, f"# Third-party software in {tree.dist}", ""]
    if not rows:
        out += [
            "**None.** This distribution declares no third-party requirement, which for",
            "`omniweave-core` and `omniweave-ports` is INV-2 and is the property that makes a",
            "third-party driver able to depend on the type surface alone.",
            "",
            "Its own licence is Apache-2.0: see LICENSE and LICENSES/Apache-2.0.txt.",
            "",
        ]
        return "\n".join(out)
    if not [one for one, _ in rows if not one.extra]:
        #  The INV-2 sentence section 9.1 wants this file to carry, which an extras-only table
        #  would otherwise bury: a reader checking the no-third-party rule reads the first line.
        out += [
            "**No required third-party dependency.** Everything below is behind an extra and",
            "arrives only when someone asks for it, so an install of this distribution alone",
            "brings no third-party code -- which for `omniweave-core` and `omniweave-ports` is",
            "INV-2 and is the property a third-party driver depends on.",
            "",
        ]
    out += [
        "Each row is a requirement this distribution's `pyproject.toml` declares. The version is",
        "the one `uv.lock` resolves; the licence text is in `LICENSES/`, byte-identical to the",
        "copy in every other tree that declares the same package.",
        "",
        "| package | version | licence | text | brought by |",
        "|---|---|---|---|---|",
    ]
    for requirement, captured in rows:
        version = lock.get(requirement.key, "?")
        spdx = captured.spdx if captured else "not captured"
        text = f"`LICENSES/{requirement.key}.txt`" if captured and not captured.note else "--"
        brought = f"the `{requirement.extra}` extra" if requirement.extra else "required"
        out.append(f"| `{requirement.name}` | {version} | {spdx} | {text} | {brought} |")
    gaps = [(one, c) for one, c in rows if c is None or c.note]
    if gaps:
        out += ["", "## Where a text is not here", ""]
        for requirement, captured in gaps:
            why = captured.note if captured else "no licence text has been captured for it yet"
            out.append(f"- **`{requirement.name}`**: {why}")
    out.append("")
    return "\n".join(out)


def _wanted(tree: Tree, captured: dict[str, Captured]) -> dict[str, str]:
    """Every file this tree must carry, as `relative path -> content`."""
    own = LICENCE.read_text(encoding="utf-8")
    rows = [(one, captured.get(one.key)) for one in tree.requires]
    files = {
        "LICENSE": own,
        "LICENSES/Apache-2.0.txt": own,
        "NOTICE": notice(tree, rows),
        "THIRD_PARTY.md": third_party(tree, rows, versions()),
    }
    for requirement, one in rows:
        if one is not None and not one.note:
            source = REPO / "tools" / "licence-texts" / f"{requirement.key}.txt"
            if source.is_file():
                files[f"LICENSES/{requirement.key}.txt"] = source.read_text(encoding="utf-8")
    return files


def check() -> list[str]:
    """Ruling 4's check half: the committed trees against the index and each other."""
    captured = index()
    findings = []
    for tree in trees():
        for relative, content in _wanted(tree, captured).items():
            path = tree.path / relative
            if not path.is_file():
                findings.append(f"{tree.relative}/{relative}: missing")
            elif path.read_text(encoding="utf-8") != content:
                findings.append(f"{tree.relative}/{relative}: differs from what this script emits")
    for key, one in sorted(captured.items()):
        text = REPO / "tools" / "licence-texts" / f"{key}.txt"
        if one.note:
            continue
        if not text.is_file():
            findings.append(f"tools/licence-texts/{key}.txt: in the index and not on disk")
        elif hashlib.sha256(text.read_bytes()).hexdigest() != one.sha256:
            findings.append(f"tools/licence-texts/{key}.txt: sha256 is not the index's")
    return findings


def emit() -> int:
    """Write every tree's four artefacts (rulings 1 and 6)."""
    captured = index()
    written = 0
    for tree in trees():
        for relative, content in _wanted(tree, captured).items():
            path = tree.path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content.encode("utf-8"))
            written += 1
    _emit(f"gen_notice  {written} file(s) over {len(trees())} tree(s)")
    return written


def _installed() -> dict[str, Distribution]:
    out = {}
    for dist in distributions():
        name = dist.metadata["Name"]
        if name:
            out[pep503(name)] = dist
    return out


def _licence_files(dist: Distribution) -> list[str]:
    """Every licence file this distribution DECLARES, else the ones its tree looks like.

    `License-File` is the package's own statement of what its licence files are, and it is the
    authority: `pypdfium2` declares nineteen -- its own three SPDX texts plus the sixteen
    BUILD_LICENSES of the pdfium binary it bundles (FreeType, libjpeg-turbo, lcms2, zlib,
    libopenjpeg and the rest, the set 14-security.md section 9.4 asks be enumerated) -- and a
    depth heuristic found none of them because they sit three separators deep. The heuristic
    stays for the wheels that declare nothing, like `defusedxml`.
    """
    declared = [one for one in dist.metadata.get_all("License-File") or [] if one]
    if declared:
        return list(declared)
    found = []
    for one in dist.files or []:
        name = str(one).replace("\\", "/")
        if ("licen" in name.lower() or "COPYING" in name) and name.count("/") <= _DEPTH:
            found.append(name)
    #  The shortest path first, so lxml's own `LICENSE.txt` wins over its bundled `LICENSES.txt`.
    return sorted(found, key=lambda one: (one.count("/"), len(one), one))


def _read_relative(dist: Distribution, relative: str) -> str | None:
    """One declared licence file's text. A `License-File` is relative to the `.dist-info`, to its
    `licenses/` subdirectory under PEP 639, or already site-packages-relative when it came from
    `dist.files` -- so all three are tried and the first that is a file wins."""
    located = getattr(dist, "_path", None)
    inside = located.name if located is not None else ""
    for attempt in (
        f"{inside}/licenses/{relative}" if inside else relative,
        f"{inside}/{relative}" if inside else relative,
        relative,
    ):
        path = Path(str(dist.locate_file(attempt)))
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if text.strip():
            return text
    return None


def _licence_text(dist: Distribution) -> tuple[str, str] | None:
    """Every declared licence text as ONE document, each block under the path it came from.

    One file per package keeps `LICENSES/` readable and keeps the emitted trees a flat set, and
    the per-block header is what makes a concatenation reviewable: a reader sees which upstream
    file each byte came from. Every byte is upstream's; nothing is paraphrased or summarised.
    """
    blocks: list[str] = []
    sources: list[str] = []
    for relative in _licence_files(dist):
        text = _read_relative(dist, relative)
        if text is None:
            continue
        sources.append(relative)
        blocks.append(text.rstrip() + "\n")
    if not blocks:
        return None
    if len(blocks) == 1:
        return blocks[0], sources[0]
    marked = [
        f"===== {relative} =====\n\n{block}"
        for relative, block in zip(sources, blocks, strict=True)
    ]
    head = (
        f"This file holds the {len(blocks)} licence files {dist.metadata['Name']} declares, each\n"
        "under the path it ships at. Captured by tools/gen_notice.py --refresh; every byte below\n"
        "is upstream's.\n\n"
    )
    return head + "\n".join(marked), ", ".join(sources)


def refresh() -> int:
    """Ruling 4: capture each declared dependency's licence text from the installed environment."""
    installed = _installed()
    lock = versions()
    wanted: dict[str, Requirement] = {}
    for tree in trees():
        for one in tree.requires:
            wanted.setdefault(one.key, one)
    out = REPO / "tools" / "licence-texts"
    out.mkdir(parents=True, exist_ok=True)
    rows: list[Captured] = []
    for key, requirement in sorted(wanted.items()):
        dist = installed.get(key)
        if dist is None:
            rows.append(
                Captured(
                    name=requirement.name,
                    version=lock.get(key, "?"),
                    source="",
                    sha256="",
                    spdx="",
                    note=(
                        "not installed in the environment this was refreshed from, so no text "
                        "has been captured; it is behind an extra nobody installed here"
                    ),
                )
            )
            continue
        found = _licence_text(dist)
        if found is None:
            rows.append(
                Captured(
                    name=requirement.name,
                    version=lock.get(key, "?"),
                    source="",
                    sha256="",
                    spdx=str(dist.metadata.get("License-Expression") or ""),
                    note=(
                        "its wheel ships no licence file at all, which is a finding about the "
                        "package; this repository carries the text under vendor/ at a pinned SHA "
                        "and tools/vendor.toml digests it"
                    ),
                )
            )
            continue
        text, source = found
        path = out / f"{key}.txt"
        path.write_bytes(text.encode("utf-8"))
        installed_version = str(dist.metadata["Version"] or "?")
        locked = lock.get(key, "?")
        skew = (
            ""
            if installed_version == locked
            else (
                f"captured from {installed_version}, which is not the {locked} uv.lock resolves: "
                "re-refresh on a synced environment before a release"
            )
        )
        rows.append(
            Captured(
                name=requirement.name,
                version=locked,
                source=source,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                spdx=str(
                    dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
                ).splitlines()[0][:64],
                note=skew,
            )
        )
    INDEX.write_bytes(_index_text(rows).encode("utf-8"))
    captured = [row for row in rows if not row.note]
    _emit(
        f"gen_notice --refresh  {len(captured)} text(s) captured, {len(rows) - len(captured)} named"
    )
    return len(rows)


def _index_text(rows: list[Captured]) -> str:
    out = [
        "# tools/licences_captured.toml -- GENERATED by tools/gen_notice.py --refresh.",
        "#",
        "# One row per third-party package any distribution DECLARES (gen_notice ruling 2), with",
        "# the version uv.lock resolves, where its licence text was read from in the installed",
        "# environment, and the sha256 of the copy under tools/licence-texts/. `--check` reads",
        "# this",
        "# file and never the environment, so G3's second half runs on a machine that installs the",
        "# dev group alone; the digest is what makes a silent edit to a captured text a finding.",
        "#",
        "# A row with a `note` and no digest is ruling 5: a package whose text could not be",
        "# captured, named here and in every THIRD_PARTY.md that declares it.",
        "",
        "schema = 1",
        "",
    ]
    for row in rows:
        out.append("[[licence]]")
        out.append(f'name = "{row.name}"')
        out.append(f'version = "{row.version}"')
        out.append(f'source = "{row.source}"')
        out.append(f'sha256 = "{row.sha256}"')
        out.append(f'spdx = "{row.spdx}"')
        if row.note:
            out.append(f'note = "{row.note}"')
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_notice", description="NOTICE, LICENSES/ and THIRD_PARTY.md, per project directory"
    )
    parser.add_argument(
        "--check", action="store_true", help="exit 1 on drift; reads no environment"
    )
    parser.add_argument("--refresh", action="store_true", help="re-capture texts from the install")
    args = parser.parse_args(argv)
    if not LOCK.is_file() or not LICENCE.is_file():
        _emit("gen_notice NOT RUN: uv.lock or LICENSE is missing")
        return EXIT_NOT_RUN
    if args.refresh:
        refresh()
        emit()
        return EXIT_CLEAN
    if args.check:
        findings = check()
        for one in findings:
            _emit(f"  {one}")
        count = len(trees())
        if findings:
            _emit(f"G3 second half FAIL  {len(findings)} finding(s) over {count} tree(s)")
            return EXIT_FAIL
        _emit(f"G3 second half ok  {count} tree(s): NOTICE, LICENSES/, THIRD_PARTY.md, LICENSE")
        return EXIT_CLEAN
    emit()
    return EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
