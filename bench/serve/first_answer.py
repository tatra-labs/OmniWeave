"""`first_answer_seconds`: `ow install` -> `ow add <folder>` -> `ow query`, timed. V01-15 (00:716).

00:716 is the criterion: *"`first_answer_seconds` <= 600 s: on a clean 4-core machine with no GPU,
offline after install, the sequence `ow install` -> `ow add ~/docs` -> `ow query "<question>"`
returns an Answer with at least one `cite` carrying a page, over a folder of 100 born-digital
office documents"*, measured by *"a scripted acceptance test in `bench/serve/`"*. The glossary's
row (00:894) starts the clock at `ow install` and stops it when the Answer returns. P7's demo
(16:734-737) is the same sequence.

## What this script does

1. **Writes the folder.** `office_folder()` writes N born-digital office documents, a third each
   DOCX, PPTX and XLSX, from XML and ZIP bytes here with fixed timestamps, as
   `fixtures/gen/gen_office_fixtures.py` does, so the folder is a function of this file and N.
   Each document is one supplier agreement with its own number, renewal date and notice period.
   One of them, the needle, is the agreement the question asks about.
2. **Runs the three verbs as children**, from a project directory, under a `HOME` and an
   `OMNIWEAVE_HOME` of their own, so nothing of the user's is read or written:
   - `ow install --target claude-code --location global --hooks context --skills core --yes`;
   - `ow add docs`;
   - `ow query "<question>" --render json`;
   - and, after the clock stops, `ow uninstall` with the same target, then a byte-identity diff of
     every file under the run's home against the state before `ow install` (P7's demo, 16:736-737).
3. **Judges the Answer**, and reads the store only to learn each cited block's `page_kind`:
   - `cited`: at least one `cite`;
   - `needle_cited`: a cite into the needle's document;
   - `answered`: the needle's notice period is in a cited block's text;
   - `paged`: a cited block sits on a page whose kind is not `stream`.

## What it cannot say

- **Not a clean machine.** It runs wherever it is started, with the workspace's interpreter and
  packages already installed. The criterion's "offline after install" starts after that install.
  The machine's cores, platform and Python are printed beside the number so it is not read as the
  criterion's.
- **`paged` is false for every office document in this build.** `parse.office.anydoc` writes one
  page of kind `stream`, because anydoc flattens a PPTX's slides into one block stream and a DOCX
  has no page boxes (`omniweave_office/driver.py`, `_page_record`). 03 section 12.5 says a
  `stream` document *"has no pages"*. So the criterion's cite *"carrying a page"* cannot hold over
  its own corpus, which D615 item 7 already owes to the plan. `paged` is reported, and it is not
  part of the exit.
- **The project declares the three `[drivers]` opt-ins** a checkout needs before any first-party
  driver resolves (D576). A clean machine would need them too until `omniweave.lock` has a writer.

Usage:

    uv run python bench/serve/first_answer.py                 # 100 documents, a scratch directory
    uv run python bench/serve/first_answer.py --docs 12 --json
    uv run python bench/serve/first_answer.py --work <dir>    # keep the project for inspection

Exit 0 when the Answer came back within `BUDGET_S` citing the needle and the uninstall left the
home byte-identical; 1 when either did not; 2 when a verb failed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import shutil
import sqlite3  # noqa: TID251 -- the judge reads the page kind of each cited block.
import sys
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from omniweave_core.host.subproc import Captured, run_captured

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "BUDGET_S",
    "DOCS",
    "Folder",
    "Judgement",
    "Measurement",
    "judge",
    "main",
    "measure",
    "office_folder",
]

BUDGET_S: Final[float] = 600.0
"""00:716's `first_answer_seconds <= 600`."""

DOCS: Final[int] = 100
"""00:716's *"a folder of 100 born-digital office documents"*."""

VERB_TIMEOUT_S: Final[float] = BUDGET_S
"""No one verb may take the whole budget; a verb that does has failed the criterion anyway."""

PROJECT: Final[str] = (
    '[corpora.docs]\npath = ".omniweave/docs.owstore"\n'
    '[serve]\ndefault_corpus = "docs"\n'
    "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
)
"""One corpus, the default, and D576's three opt-ins."""

INSTALL: Final[tuple[str, ...]] = (
    "install",
    "--target",
    "claude-code",
    "--location",
    "global",
    "--hooks",
    "context",
    "--skills",
    "core",
    "--yes",
)

UNINSTALL: Final[tuple[str, ...]] = (
    "uninstall",
    "--target",
    "claude-code",
    "--location",
    "global",
    "--yes",
)
"""16:736-737: *"Then `ow uninstall` and a byte-identity diff of every path the receipt names."*"""

_ZIP_DATE: Final = (2026, 1, 1, 0, 0, 0)
_XML: Final[str] = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
_W: Final[str] = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R: Final[str] = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A: Final[str] = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P: Final[str] = "http://schemas.openxmlformats.org/presentationml/2006/main"
_SS: Final[str] = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_MONTHS: Final[tuple[str, ...]] = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
_CITE: Final = re.compile(r"(?:^|:)d(\d+)#\d+$")
_PAGE_KIND_SQL: Final[str] = """
SELECT ev.name FROM block b
  JOIN page p ON p.doc_ord = b.doc_ord AND p.gen = b.gen AND p.page = b.page
  JOIN enum_val ev ON ev.domain = 'page_kind' AND ev.ord = p.page_kind
 WHERE b.doc_ord = :doc_ord AND b.page = :page
 LIMIT 1
"""


# =============================================================================================
# 1. The folder
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Folder:
    """What `office_folder()` wrote, and the one fact the question asks about."""

    files: tuple[Path, ...]
    needle: Path
    question: str
    expected: str
    """The needle's notice period, as its text states it: what a right answer contains."""


def _notice_days(index: int) -> int:
    return 10 + (index * 37) % 80


def _facts(index: int) -> list[str]:
    """One agreement's sentences. The number, the date and the period are this document's own."""
    number = f"{index:03d}"
    month = _MONTHS[index % 12]
    return [
        f"Supplier agreement {number}",
        f"This supplier agreement {number} is made between the buyer and supplier {number}.",
        f"Agreement {number} renews on {month} {1 + index % 28} each year.",
        f"The notice period under agreement {number} is {_notice_days(index)} days.",
        f"Invoices under agreement {number} are payable within {15 + index % 45} days.",
        f"Agreement {number} is governed by the law of region {1 + index % 9}.",
    ]


def _zip(entries: Sequence[tuple[str, str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for name, text in entries:
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.external_attr = 0o600 << 16
            archive.writestr(info, (_XML + text).encode("utf-8"))
    return buffer.getvalue()


def _types(*overrides: tuple[str, str]) -> str:
    body = "".join(
        f'<Override PartName="{part}" ContentType="application/vnd.openxmlformats-officedocument.'
        f'{kind}"/>'
        for part, kind in overrides
    )
    return (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>' + body + "</Types>"
    )


def _rels(*targets: tuple[str, str, str]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{_R}/{kind}" Target="{target}"/>'
        for rid, kind, target in targets
    )
    return (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + body
        + "</Relationships>"
    )


def _docx(lines: Sequence[str]) -> bytes:
    paragraphs = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    return _zip(
        [
            (
                "[Content_Types].xml",
                _types(("/word/document.xml", "wordprocessingml.document.main+xml")),
            ),
            ("_rels/.rels", _rels(("rId1", "officeDocument", "word/document.xml"))),
            (
                "word/document.xml",
                f'<w:document xmlns:w="{_W}"><w:body>{paragraphs}</w:body></w:document>',
            ),
        ]
    )


def _pptx(lines: Sequence[str]) -> bytes:
    title, *body = lines
    runs = "".join(f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in body)

    def shape(number: int, name: str, text: str, placeholder: str = "") -> str:
        ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{number}" name="{name}"/><p:cNvSpPr/>'
            f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr/>"
            f"<p:txBody><a:bodyPr/><a:lstStyle/>{text}</p:txBody></p:sp>"
        )

    slide = (
        f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        "<p:grpSpPr/>"
        + shape(2, "Title 1", f"<a:p><a:r><a:t>{title}</a:t></a:r></a:p>", "title")
        + shape(3, "Content 2", runs)
        + "</p:spTree></p:cSld></p:sld>"
    )
    return _zip(
        [
            (
                "[Content_Types].xml",
                _types(
                    ("/ppt/presentation.xml", "presentationml.presentation.main+xml"),
                    ("/ppt/slides/slide1.xml", "presentationml.slide+xml"),
                ),
            ),
            ("_rels/.rels", _rels(("rId1", "officeDocument", "ppt/presentation.xml"))),
            (
                "ppt/presentation.xml",
                f'<p:presentation xmlns:p="{_P}" xmlns:r="{_R}">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst></p:presentation>',
            ),
            ("ppt/_rels/presentation.xml.rels", _rels(("rId2", "slide", "slides/slide1.xml"))),
            ("ppt/slides/slide1.xml", slide),
        ]
    )


def _xlsx(lines: Sequence[str]) -> bytes:
    rows = "".join(
        f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>{line}</t></is></c></row>'
        for n, line in enumerate(lines, 1)
    )
    return _zip(
        [
            (
                "[Content_Types].xml",
                _types(
                    ("/xl/workbook.xml", "spreadsheetml.sheet.main+xml"),
                    ("/xl/worksheets/sheet1.xml", "spreadsheetml.worksheet+xml"),
                ),
            ),
            ("_rels/.rels", _rels(("rId1", "officeDocument", "xl/workbook.xml"))),
            (
                "xl/workbook.xml",
                f'<workbook xmlns="{_SS}" xmlns:r="{_R}"><sheets>'
                '<sheet name="Terms" sheetId="1" r:id="rId1"/></sheets></workbook>',
            ),
            ("xl/_rels/workbook.xml.rels", _rels(("rId1", "worksheet", "worksheets/sheet1.xml"))),
            (
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{_SS}"><sheetData>{rows}</sheetData></worksheet>',
            ),
        ]
    )


_WRITERS: Final = (("docx", _docx), ("pptx", _pptx), ("xlsx", _xlsx))


def office_folder(dest: Path, n: int = DOCS) -> Folder:
    """Write `n` agreements under `dest`, cycling DOCX, PPTX and XLSX. The needle is a DOCX."""
    if n < 1:
        msg = f"a folder needs at least one document, not {n}"
        raise ValueError(msg)
    dest.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for index in range(n):
        suffix, write = _WRITERS[index % len(_WRITERS)]
        path = dest / f"agreement-{index:03d}.{suffix}"
        path.write_bytes(write(_facts(index)))
        files.append(path)
    needle = min(n - 1, 42) // len(_WRITERS) * len(_WRITERS)
    return Folder(
        files=tuple(files),
        needle=files[needle],
        question=f"What is the notice period under agreement {needle:03d}?",
        expected=f"{_notice_days(needle)} days",
    )


# =============================================================================================
# 2. The judge
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Judgement:
    """What the Answer shows, each as its own fact."""

    cited: int
    needle_cited: bool
    answered: bool
    paged: bool
    page_kinds: tuple[str, ...]


def _names(path: Path, doc_uri: str) -> bool:
    """Whether `doc_uri` names `path`. The Answer's `doc_uri` is relative to the corpus's source
    (`agreement-042.docx`), so it is compared as a trailing path, never as the whole of one."""
    uri = doc_uri.replace("\\", "/").strip("/").lower()
    full = path.as_posix().lower()
    return bool(uri) and (full == uri or full.endswith("/" + uri))


def judge(answer: Mapping[str, Any], *, store: Path, needle: Path, expected: str) -> Judgement:
    """The four facts, from the Answer's evidence and each cited block's page row in `store`."""
    evidence = [one for one in answer.get("evidence", []) if one.get("cite")]
    on_needle = [one for one in evidence if _names(needle, str(one.get("doc_uri", "")))]
    kinds: list[str] = []
    connection = sqlite3.connect(f"file:{store.as_posix()}?mode=ro", uri=True)
    try:
        for one in evidence:
            found = _CITE.search(str(one["cite"]))
            if found is None:
                continue
            row = connection.execute(
                _PAGE_KIND_SQL, {"doc_ord": int(found.group(1)), "page": int(one.get("page", 0))}
            ).fetchone()
            kinds.append(str(row[0]) if row else "unknown")
    finally:
        connection.close()
    return Judgement(
        cited=len(evidence),
        needle_cited=bool(on_needle),
        answered=any(expected in str(one.get("text", "")) for one in on_needle),
        paged=any(kind not in ("stream", "unknown") for kind in kinds),
        page_kinds=tuple(sorted(set(kinds))),
    )


# =============================================================================================
# 3. The run
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Measurement:
    """One run: the seconds, what the Answer showed, and the machine it ran on."""

    first_answer_seconds: float
    phases: dict[str, float]
    docs: int
    question: str
    judgement: Judgement | None
    machine: dict[str, object]
    failed: str = ""
    """The verb that did not exit 0, with its exit and the tail of its stderr; empty when none."""
    budget_s: float = BUDGET_S
    notes: tuple[str, ...] = field(default_factory=tuple)
    reversed: bool | None = None
    """16:736-737's second half: after `ow uninstall`, every file under the run's home is
    byte-identical to before `ow install`. Outside the clock. `None` when the run stopped first."""
    residue: tuple[str, ...] = field(default_factory=tuple)
    """The home's paths that differ after the uninstall, when `reversed` is false."""

    @property
    def passed(self) -> bool:
        """Within the budget, citing the needle, and reversed. `paged` is reported, not required."""
        return (
            not self.failed
            and self.first_answer_seconds <= self.budget_s
            and self.judgement is not None
            and self.judgement.needle_cited
            and self.reversed is True
        )


def _env(work: Path) -> dict[str, str]:
    """The caller's environment for the interpreter to start, with the homes moved into `work`."""
    kept = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    home = work / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        **kept,
        "HOME": str(home),
        "USERPROFILE": str(home),
        "OMNIWEAVE_HOME": str(work / "owhome"),
    }


def _machine() -> dict[str, object]:
    return {
        "cpus": os.cpu_count(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "clean": False,
    }


def _snapshot(home: Path) -> dict[str, str]:
    """Every file under `home`, by its relative path, to its sha256: 10 section 7.4's byte state."""
    return {
        path.relative_to(home).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(home.rglob("*"))
        if path.is_file()
    }


def _verb(python: str, argv: Sequence[str], *, cwd: Path, env: Mapping[str, str]) -> Captured:
    return run_captured(
        (python, "-m", "omniweave", *argv),
        stdin=b"",
        cwd=str(cwd),
        env=env,
        timeout_s=VERB_TIMEOUT_S,
    )


def _failure(name: str, done: Captured) -> str:
    tail = done.stderr.decode("utf-8", "replace").strip()[-400:]
    return f"ow {name}: {done.failed or f'exit {done.returncode}'}: {tail}"


def measure(n: int, *, work: Path, python: str = sys.executable) -> Measurement:
    """Write the folder under `work/project/docs`, time the three verbs as children, then reverse.

    The clock runs from the start of `ow install` to the return of `ow query` (00:894). `ow
    uninstall` runs after it, and its byte-identity check is 16:736-737's, not 00:716's.
    """
    project = work / "project"
    project.mkdir(parents=True, exist_ok=True)
    (project / "omniweave.toml").write_text(PROJECT, encoding="utf-8")
    folder = office_folder(project / "docs", n)
    env = _env(work)
    home = Path(env["HOME"])
    before = _snapshot(home)
    phases: dict[str, float] = {}
    answer: Captured | None = None
    started = time.perf_counter()
    for name, argv in (
        ("install", INSTALL),
        ("add", ("add", "docs")),
        ("query", ("query", folder.question, "--render", "json")),
    ):
        begun = time.perf_counter()
        done = _verb(python, argv, cwd=project, env=env)
        phases[name] = round(time.perf_counter() - begun, 3)
        if done.failed or done.returncode != 0:
            return Measurement(
                first_answer_seconds=round(time.perf_counter() - started, 3),
                phases=phases,
                docs=n,
                question=folder.question,
                judgement=None,
                machine=_machine(),
                failed=_failure(name, done),
            )
        answer = done
    total = round(time.perf_counter() - started, 3)
    assert answer is not None  # noqa: S101 -- three phases ran, the last is the query
    undone = _verb(python, UNINSTALL, cwd=project, env=env)
    after = _snapshot(home)
    residue = tuple(
        sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
    )
    judged = judge(
        json.loads(answer.stdout),
        store=project / ".omniweave" / "docs.owstore",
        needle=folder.needle,
        expected=folder.expected,
    )
    notes = (
        ()
        if judged.paged
        else ("no cited block is on a page: office documents are `stream` (D615)",)
    )
    return Measurement(
        first_answer_seconds=total,
        phases=phases,
        docs=n,
        question=folder.question,
        judgement=judged,
        machine=_machine(),
        failed=""
        if undone.returncode == 0 and not undone.failed
        else _failure("uninstall", undone),
        notes=notes,
        reversed=not residue,
        residue=residue,
    )


def _lines(result: Measurement) -> list[str]:
    out = [
        f"first_answer_seconds {result.first_answer_seconds:.1f} s against {result.budget_s:.0f} s"
        f"  ({', '.join(f'{k} {v:.1f} s' for k, v in result.phases.items())})",
        f"folder  {result.docs} office documents; question: {result.question}",
    ]
    if result.failed:
        out.append(f"FAILED  {result.failed}")
    if result.judgement is not None:
        j = result.judgement
        out.append(
            f"answer  {j.cited} cite(s); needle cited {j.needle_cited}; answered {j.answered}; "
            f"on a page {j.paged} (page kinds: {', '.join(j.page_kinds) or 'none'})"
        )
    if result.reversed is not None:
        shown = "byte-identical" if result.reversed else f"differs at {', '.join(result.residue)}"
        out.append(f"reverse ow uninstall: the home is {shown}")
    machine = result.machine
    out.append(
        f"machine {machine['cpus']} cpus, {machine['platform']}, Python {machine['python']}; "
        "not a clean machine"
    )
    out.extend(f"note    {note}" for note in result.notes)
    out.append("PASS" if result.passed else "FAIL")
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="first_answer_seconds: ow install -> ow add -> ow query, timed (V01-15)"
    )
    parser.add_argument("--docs", type=int, default=DOCS, help="documents in the folder")
    parser.add_argument("--work", type=Path, help="keep the project here instead of a scratch dir")
    parser.add_argument("--json", action="store_true", help="print the measurement as JSON")
    args = parser.parse_args(argv)
    scratch = args.work is None
    work = Path(tempfile.mkdtemp(prefix="ow-first-answer-")) if scratch else args.work
    try:
        result = measure(args.docs, work=work)
    finally:
        if scratch:
            shutil.rmtree(work, ignore_errors=True)
    if args.json:
        sys.stdout.write(json.dumps({**asdict(result), "passed": result.passed}, indent=2) + "\n")
    else:
        sys.stdout.write("\n".join(_lines(result)) + "\n")
    if result.failed:
        return 2
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
