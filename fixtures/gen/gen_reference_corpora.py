"""ADR-14 D14.1's three reference corpora, generated, with every answer planted.

The adoption harness (13-quality.md section 8.8) asks thirty questions of three corpora shaped as
F20 names them: a 5,000-page legal matter, a 137-document data room and a 60-document personal
archive. ADR-14 D14.1 makes the v0.1 corpora generated rather than real. It has three reasons:
- Tier A cannot hold real corpora of this size.
- 13-quality.md:459 prefers `generated` wherever a phenomenon can be synthesised.
- A planted fact is ground truth by construction. `D602`'s objection was that an answer key
  written against documents nobody has would be ground truth by assertion; here the documents
  and the key come from one source.

**Every fact a task asks about is declared once, in `PLANTED`**, beside the document that carries
it. `ABSENT` declares, for each absence task, the terms that appear in no document of its corpus.
`bench/serve/test_corpora.py` holds the catalogue, these two tables and the generated text
together:
- each planted answer is in its document, at both scales;
- a damaged task's value is in exactly one document;
- each absent term is nowhere.

**Two scales, one set of facts** (ADR-14 D14.7). `full` is F20's shapes and the only reportable
scale. `quick` keeps every planted document and cuts the filler: `legal_matter` goes to 250 pages
over 12 files, `data_room` to 16 files and `personal_archive` to 8. It is for iterating locally,
and a `quick` number never gates.

**The regime of `fixtures/gen/`** (its README; 13-quality.md:586-589):
- Deterministic. Every word is picked by a sha256 of its position, and nothing reads `random`,
  a clock or a UUID.
- Output lands in `fixtures/generated/`, which is ignored by git.
- `EXPECTED.sha256` pins each corpus's manifest, one `sha256  relpath` line per file, so a corpus
  change is a one-line visible diff.

**Formats are the ones the shipped roster parses:** PDF (`parse.pdf.pdfium`) and DOCX, XLSX, PPTX
and CSV (`parse.office.anydoc`). A plain-text file is identified and never parsed (D567), which
would make every answer over its corpus degraded and measure a coverage gap instead of retrieval.
Text is ASCII, and it is XML- or PDF-escaped where it is written.

Usage:

    uv run python fixtures/gen/gen_reference_corpora.py --corpus legal_matter --scale quick
    uv run python fixtures/gen/gen_reference_corpora.py --all --print-sha256
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape

ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_OUT: Final = ROOT / "fixtures" / "generated" / "reference"
CORPORA: Final = ("legal_matter", "data_room", "personal_archive")
SCALES: Final = ("full", "quick")
ZIP_DATE: Final = (2026, 1, 1, 0, 0, 0)

LEGAL_PAGES: Final = {"full": 5_000, "quick": 250}
LEGAL_FILES: Final = {"full": 120, "quick": 12}
DATA_FILES: Final = {"full": 137, "quick": 16}
PERSONAL_FILES: Final = {"full": 60, "quick": 8}


# =============================================================================================
# The planted facts and the absent terms: the answer key, in one place
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Planted:
    """One answer, and the one document it is written into."""

    corpus: str
    path: str
    text: str


PLANTED: Final[Mapping[str, Planted]] = {
    # legal_matter
    "legal-cite-termination": Planted(
        "legal_matter",
        "contracts/msa-2019.pdf",
        "4.2 Either party may terminate this Agreement for convenience on ninety (90) days' "
        "written notice to the other party.",
    ),
    "legal-cite-liability-cap": Planted(
        "legal_matter",
        "contracts/msa-2019.pdf",
        "9.1 Each party's aggregate liability under this Agreement is capped at the fees paid "
        "in the twelve (12) months before the claim.",
    ),
    "legal-ret-damages": Planted(
        "legal_matter",
        "pleadings/complaint.pdf",
        "41. Plaintiff seeks damages of $4,850,000, together with interest and costs.",
    ),
    "legal-abs-singapore": Planted(
        "legal_matter",
        "contracts/msa-2019.pdf",
        "14.3 Any dispute shall be finally resolved by arbitration seated in London under the "
        "LCIA Rules.",
    ),
    "legal-dmg-service-credit": Planted(
        "legal_matter",
        "contracts/amendment-1-2021.pdf",
        "2. Amendment No. 1 increases the service credit to 7.5 percent of the monthly fee.",
    ),
    # data_room
    "data-cite-nda-term": Planted(
        "data_room",
        "legal/nda-northwind.docx",
        "Clause 7. Term. The confidentiality obligations survive for five (5) years after "
        "disclosure.",
    ),
    "data-cite-ip-assignment": Planted(
        "data_room",
        "legal/ip-assignment.pdf",
        "2.1 The Assignor assigns to the Company all right, title and interest in the Assigned IP.",
    ),
    "data-ret-indexed-cap": Planted(
        "data_room",
        "suppliers/supplier-agreement-acme.docx",
        "Clause 6. Pricing. Unit prices are subject to an indexed price cap, adjusted annually "
        "by the consumer price index and capped at four percent.",
    ),
    "data-ret-series-b": Planted(
        "data_room", "finance/cap-table-2024.xlsx", "Series B preferred: 1,250,000 shares"
    ),
    "data-ret-q3-revenue": Planted(
        "data_room", "board/board-deck-q3-2024.pptx", "Q3 2024 revenue: $18.4 million"
    ),
    "data-ret-lease-2027": Planted(
        "data_room", "leases/lease-lisbon.docx", "The lease term expires on 30 June 2027."
    ),
    "data-dmg-headcount": Planted(
        "data_room", "hr/headcount-2024.xlsx", "Total headcount at 31 December 2024: 412"
    ),
    "data-dmg-dpa-region": Planted(
        "data_room", "legal/dpa-contoso.docx", "Customer data is hosted in Ireland."
    ),
    "data-dmg-materiality": Planted(
        "data_room",
        "audit/audit-report-2023.pdf",
        "Overall materiality for the 2023 audit was set at $450,000.",
    ),
    # personal_archive
    "home-cite-rent-increase": Planted(
        "personal_archive",
        "letters/oakridge-renewal-2024.docx",
        "3. The monthly rent will increase by 3.5 percent from 1 September 2024.",
    ),
    "home-cite-flood": Planted(
        "personal_archive",
        "insurance/home-policy-2024.pdf",
        "5. Flood. Flood damage is excluded unless the Flood Extension endorsement is purchased.",
    ),
    "home-ret-dental": Planted(
        "personal_archive",
        "receipts/brightline-dental-2024-03.pdf",
        "Amount due: $285.40",
    ),
    "home-ret-harrow": Planted(
        "personal_archive",
        "statements/statement-2024-05.csv",
        "2024-05-14,Transfer to Harrow Savings,-1500.00",
    ),
    "home-dmg-ldl": Planted(
        "personal_archive", "medical/lab-results-2024.pdf", "LDL cholesterol: 118 mg/dL"
    ),
    "home-dmg-refund": Planted(
        "personal_archive", "tax/tax-summary-2023.docx", "Refund due: $1,240"
    ),
}
"""Task id -> the answer's sentence and the one document carrying it. An absence task's entry is
the near miss its question is built around -- arbitration in LONDON, when it asks for Singapore."""

EXTRA_SUPPLIERS: Final = (
    ("suppliers/supplier-agreement-borealis.docx", "Borealis Metals"),
    ("suppliers/supplier-agreement-corvid.docx", "Corvid Plastics"),
)
"""The other two suppliers with an indexed price cap. `data-ret-indexed-cap` names all three."""

ABSENT: Final[Mapping[str, tuple[str, ...]]] = {
    "legal-abs-singapore": ("singapore",),
    "data-abs-mfn": ("most-favoured", "most favoured", "most-favored", "most favored"),
    "data-abs-q4-revenue": ("q4 2024",),
    "home-abs-passport": ("passport",),
    "home-abs-pet": ("pet insurance",),
}
"""Absence task id -> terms that appear in NO document of its corpus, at either scale."""


# =============================================================================================
# Deterministic filler
# =============================================================================================

LEGAL_WORDS: Final = (
    "agreement",
    "party",
    "services",
    "obligation",
    "notice",
    "schedule",
    "provider",
    "customer",
    "performance",
    "deliverables",
    "warranty",
    "remedy",
    "breach",
    "cure",
    "period",
    "clause",
    "exhibit",
    "consent",
    "assignment",
    "subcontractor",
    "confidential",
    "information",
    "records",
    "audit",
    "invoice",
    "payment",
    "dispute",
    "counsel",
    "hearing",
    "motion",
    "discovery",
    "witness",
    "testimony",
    "record",
    "outage",
    "incident",
    "platform",
    "migration",
    "report",
    "review",
    "system",
    "support",
    "response",
    "escalation",
    "timeline",
    "correspondence",
    "meeting",
    "draft",
    "revision",
)
BUSINESS_WORDS: Final = (
    "revenue",
    "margin",
    "forecast",
    "pipeline",
    "customer",
    "supplier",
    "contract",
    "renewal",
    "board",
    "committee",
    "resolution",
    "policy",
    "budget",
    "headcount",
    "hiring",
    "office",
    "product",
    "roadmap",
    "release",
    "operations",
    "logistics",
    "inventory",
    "procurement",
    "compliance",
    "security",
    "privacy",
    "review",
    "approval",
    "quarter",
    "strategy",
    "investment",
    "financing",
    "equity",
    "option",
    "vesting",
    "minutes",
    "agenda",
    "update",
    "risk",
    "controls",
    "audit",
    "facilities",
    "lease",
    "vendor",
    "services",
    "delivery",
)
PERSONAL_WORDS: Final = (
    "account",
    "statement",
    "payment",
    "reminder",
    "appointment",
    "invoice",
    "receipt",
    "policy",
    "renewal",
    "letter",
    "notice",
    "balance",
    "transfer",
    "deposit",
    "utility",
    "electricity",
    "water",
    "internet",
    "phone",
    "subscription",
    "school",
    "visit",
    "clinic",
    "pharmacy",
    "garden",
    "repair",
    "service",
    "delivery",
    "order",
    "booking",
    "travel",
    "holiday",
    "family",
    "household",
    "vehicle",
    "maintenance",
    "record",
    "summary",
    "update",
)


def _pick(seed: str, n: int, words: Sequence[str]) -> list[str]:
    digest = b""
    out: list[str] = []
    counter = 0
    while len(out) < n:
        digest = hashlib.sha256(f"{seed}|{counter}".encode()).digest()
        counter += 1
        out.extend(words[b % len(words)] for b in digest[: n - len(out)])
    return out


def _sentence(seed: str, words: Sequence[str]) -> str:
    count = 10 + hashlib.sha256(seed.encode()).digest()[0] % 9
    picked = _pick(seed, count, words)
    return " ".join(picked).capitalize() + "."


def _paragraph(seed: str, words: Sequence[str], sentences: int = 3) -> str:
    return " ".join(_sentence(f"{seed}.{i}", words) for i in range(sentences))


# =============================================================================================
# Writers
# =============================================================================================

WRAP: Final = 92
LINES_PER_PAGE: Final = 58


def _wrap(text: str, width: int = WRAP) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        lines.append(current)
    return lines or [""]


def _pdf_literal(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("ascii")


def pdf_bytes(pages: Sequence[Sequence[str]], *, title: str) -> bytes:
    """A born-digital PDF: one Helvetica text line per entry, uncompressed, a classic xref table.

    Every line is wrapped at `WRAP` characters, and a page holds at most `LINES_PER_PAGE` lines.
    Nothing varies with the clock: the dates are fixed and the `/ID` is a digest of the content.
    """
    laid: list[list[str]] = []
    for page in pages:
        lines = [wrapped for line in page for wrapped in _wrap(line)]
        laid.extend(
            lines[i : i + LINES_PER_PAGE] for i in range(0, max(len(lines), 1), LINES_PER_PAGE)
        )
    objects: list[bytes] = []
    n_pages = len(laid)
    first_page = 4
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(n_pages))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, lines in enumerate(laid):
        content = io.BytesIO()
        y = 800
        for line in lines:
            content.write(b"BT /F1 10 Tf 56 " + str(y).encode() + b" Td (")
            content.write(_pdf_literal(line))
            content.write(b") Tj ET\n")
            y -= 13
        stream = content.getvalue()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {first_page + 2 * index + 1} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream"
        )
    info_number = len(objects) + 1
    objects.append(
        b"<< /Title (" + _pdf_literal(title) + b") /Producer (omniweave gen_reference_corpora)"
        b" /CreationDate (D:20260101000000Z) >>"
    )
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode())
    out.write(b"0000000000 65535 f \n")
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    doc_id = hashlib.sha256(b"".join(objects)).hexdigest()[:32]
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_number} 0 R "
        f"/ID [<{doc_id}> <{doc_id}>] >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return out.getvalue()


_W: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_P: Final = "http://schemas.openxmlformats.org/presentationml/2006/main"
_A: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
_SS: Final = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_PKG: Final = "http://schemas.openxmlformats.org/package/2006"
_DOCREL: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _zip(entries: Sequence[tuple[str, str]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in entries:
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0  # zipfile writes 3 on POSIX, 0 on Windows: one corpus (D653)
            archive.writestr(info, text.encode("utf-8"))
    return buffer.getvalue()


def _types(*overrides: tuple[str, str]) -> str:
    parts = "".join(
        f'<Override PartName="{name}" ContentType="application/vnd.openxmlformats-officedocument.'
        f'{kind}"/>'
        for name, kind in overrides
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="{_PKG}/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        f"{parts}</Types>"
    )


def _rels(*targets: tuple[str, str, str]) -> str:
    parts = "".join(
        f'<Relationship Id="{rid}" Type="{_DOCREL}/{kind}" Target="{target}"/>'
        for rid, kind, target in targets
    )
    head = f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{_PKG}/relationships">'
    return f"{head}{parts}</Relationships>"


def docx_bytes(lines: Sequence[str]) -> bytes:
    paragraphs = "".join(f"<w:p><w:r><w:t>{escape(line)}</w:t></w:r></w:p>" for line in lines)
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


def pptx_bytes(lines: Sequence[str]) -> bytes:
    title, *body = lines
    runs = "".join(f"<a:p><a:r><a:t>{escape(line)}</a:t></a:r></a:p>" for line in body)

    def shape(number: int, name: str, text: str, placeholder: str = "") -> str:
        ph = f'<p:ph type="{placeholder}"/>' if placeholder else ""
        return (
            f'<p:sp><p:nvSpPr><p:cNvPr id="{number}" name="{name}"/><p:cNvSpPr/>'
            f"<p:nvPr>{ph}</p:nvPr></p:nvSpPr><p:spPr/>"
            f"<p:txBody><a:bodyPr/><a:lstStyle/>{text}</p:txBody></p:sp>"
        )

    slide = (
        f'<p:sld xmlns:p="{_P}" xmlns:a="{_A}"><p:cSld><p:spTree>'
        '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
        + shape(2, "Title 1", f"<a:p><a:r><a:t>{escape(title)}</a:t></a:r></a:p>", "title")
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


def xlsx_bytes(lines: Sequence[str]) -> bytes:
    rows = "".join(
        f'<row r="{n}"><c r="A{n}" t="inlineStr"><is><t>{escape(line)}</t></is></c></row>'
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
                '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>',
            ),
            ("xl/_rels/workbook.xml.rels", _rels(("rId1", "worksheet", "worksheets/sheet1.xml"))),
            (
                "xl/worksheets/sheet1.xml",
                f'<worksheet xmlns="{_SS}"><sheetData>{rows}</sheetData></worksheet>',
            ),
        ]
    )


def csv_bytes(lines: Sequence[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("ascii")


# =============================================================================================
# Documents
# =============================================================================================


@dataclass(frozen=True, slots=True)
class Document:
    """One file: its path under the corpus root, and its text as pages of lines."""

    path: str
    pages: tuple[tuple[str, ...], ...]

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(line for page in self.pages for line in page)

    def to_bytes(self) -> bytes:
        suffix = self.path.rsplit(".", 1)[-1]
        writer: Mapping[str, Callable[[Sequence[str]], bytes]] = {
            "docx": docx_bytes,
            "pptx": pptx_bytes,
            "xlsx": xlsx_bytes,
            "csv": csv_bytes,
        }
        if suffix == "pdf":
            return pdf_bytes(self.pages, title=self.pages[0][0] if self.pages[0] else self.path)
        return writer[suffix](self.lines)


def _doc(path: str, *pages: Iterable[str]) -> Document:
    return Document(path, tuple(tuple(page) for page in pages))


def _filler_pages(seed: str, count: int, words: Sequence[str], heading: str) -> list[list[str]]:
    return [
        [f"{heading} - part {n}" if n else heading]
        + [_paragraph(f"{seed}.{n}.{p}", words) for p in range(6)]
        for n in range(count)
    ]


def _split(total: int, parts: int) -> list[int]:
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


# -- legal_matter ------------------------------------------------------------------------------

MSA_PAGES: Final = 24
COMPLAINT_DAMAGES_PARAGRAPH: Final = 41
NDA_TERM_CLAUSE: Final = 7

MSA_SECTIONS: Final = (
    "Definitions",
    "Services",
    "Service Levels",
    "Term and Termination",
    "Fees",
    "Invoicing",
    "Personnel",
    "Warranties",
    "Limitation of Liability",
    "Indemnities",
    "Confidentiality",
    "Data Protection",
    "Insurance",
    "Governing Law and Disputes",
    "Assignment",
    "General",
)


def _msa() -> Document:
    lines = [
        "Master Services Agreement",
        "Between Harbor Freight Logistics Inc. and Meridian Systems Ltd., dated 14 May 2019.",
    ]
    overrides = {
        (4, 2): PLANTED["legal-cite-termination"].text,
        (9, 1): PLANTED["legal-cite-liability-cap"].text,
        (14, 3): PLANTED["legal-abs-singapore"].text,
    }
    for number, title in enumerate(MSA_SECTIONS, start=1):
        lines.append(f"Section {number}. {title}")
        for sub in range(1, 6):
            lines.append(
                overrides.get((number, sub))
                or f"{number}.{sub} " + _paragraph(f"msa.{number}.{sub}", LEGAL_WORDS, 4)
            )
    per_page = -(-len(lines) // MSA_PAGES)
    return Document(
        "contracts/msa-2019.pdf",
        tuple(tuple(lines[i : i + per_page]) for i in range(0, len(lines), per_page)),
    )


def _legal(scale: str) -> list[Document]:
    core = [
        _msa(),
        _doc(
            "contracts/amendment-1-2021.pdf",
            [
                "Amendment No. 1 to the Master Services Agreement",
                "1. " + _paragraph("am.1", LEGAL_WORDS),
            ],
            [PLANTED["legal-dmg-service-credit"].text, "3. " + _paragraph("am.3", LEGAL_WORDS)],
            ["4. " + _paragraph("am.4", LEGAL_WORDS)],
            ["5. " + _paragraph("am.5", LEGAL_WORDS)],
        ),
        Document(
            "pleadings/complaint.pdf",
            tuple(
                tuple(
                    [f"Complaint - page {page + 1}"]
                    + [
                        PLANTED["legal-ret-damages"].text
                        if number == COMPLAINT_DAMAGES_PARAGRAPH
                        else f"{number}. " + _paragraph(f"cmp.{number}", LEGAL_WORDS, 2)
                        for number in range(page * 4 + 1, page * 4 + 5)
                    ]
                )
                for page in range(30)
            ),
        ),
        Document(
            "pleadings/answer.pdf",
            tuple(tuple(p) for p in _filler_pages("ans", 20, LEGAL_WORDS, "Answer and Defenses")),
        ),
        Document(
            "depositions/deposition-kline.pdf",
            tuple(
                tuple(
                    [f"Deposition of R. Kline - page {page + 1}"]
                    + [
                        f"{'Q' if line % 2 == 0 else 'A'}. "
                        + _sentence(f"dep.{page}.{line}", LEGAL_WORDS)
                        for line in range(12)
                    ]
                )
                for page in range(60)
            ),
        ),
        _doc(
            "correspondence/letter-2022-03-07.pdf",
            ["Letter from counsel, 7 March 2022", _paragraph("let.1", LEGAL_WORDS, 5)],
            [_paragraph("let.2", LEGAL_WORDS, 5)],
        ),
    ]
    used = sum(len(doc.pages) for doc in core)
    exhibits = LEGAL_FILES[scale] - len(core)
    documents = list(core)
    for index, pages in enumerate(_split(LEGAL_PAGES[scale] - used, exhibits), start=1):
        documents.append(
            Document(
                f"exhibits/exhibit-{index:03d}.pdf",
                tuple(
                    tuple(p)
                    for p in _filler_pages(
                        f"exh.{index}", pages, LEGAL_WORDS, f"Exhibit {index:03d}"
                    )
                ),
            )
        )
    return documents


# -- data_room ---------------------------------------------------------------------------------

FILLER_SUPPLIERS: Final = (
    "Aldwych Freight",
    "Brixton Tooling",
    "Calder Chemicals",
    "Derwent Packaging",
    "Eskdale Fabrics",
    "Fenwick Electronics",
    "Glenmore Timber",
    "Hartley Glass",
    "Ingleby Foods",
    "Jarrow Castings",
    "Kielder Paper",
    "Lowther Textiles",
)


def _supplier(path: str, name: str, *, indexed: bool) -> Document:
    pricing = (
        "Clause 6. Pricing. Unit prices are subject to an indexed price cap, adjusted annually "
        "by the consumer price index and capped at four percent."
        if indexed
        else "Clause 6. Pricing. Unit prices are fixed for the term and are not indexed."
    )
    return _doc(
        path,
        [f"Supplier Agreement - {name}"]
        + [f"Clause {n}. " + _paragraph(f"sup.{name}.{n}", BUSINESS_WORDS, 2) for n in range(1, 6)]
        + [pricing]
        + [
            f"Clause {n}. " + _paragraph(f"sup.{name}.{n}", BUSINESS_WORDS, 2) for n in range(7, 11)
        ],
    )


def _data(scale: str) -> list[Document]:
    planted = [
        _supplier("suppliers/supplier-agreement-acme.docx", "Acme Components", indexed=True),
        *(_supplier(path, name, indexed=True) for path, name in EXTRA_SUPPLIERS),
        _supplier("suppliers/supplier-agreement-dunmore.docx", "Dunmore Industrial", indexed=False),
        _doc(
            "finance/cap-table-2024.xlsx",
            [
                "Capitalisation table at 30 September 2024",
                "Common stock: 8,000,000 shares",
                "Series A preferred: 2,000,000 shares",
                PLANTED["data-ret-series-b"].text,
                "Option pool: 900,000 shares",
            ],
        ),
        _doc(
            "board/board-deck-q3-2024.pptx",
            [
                "Board update - Q3 2024",
                PLANTED["data-ret-q3-revenue"].text,
                "Q3 2024 gross margin: 61 percent",
                "Q3 2024 customers: 342",
            ],
        ),
        _doc(
            "legal/nda-northwind.docx",
            ["Mutual Non-Disclosure Agreement - Northwind Traders"]
            + [
                PLANTED["data-cite-nda-term"].text
                if n == NDA_TERM_CLAUSE
                else f"Clause {n}. " + _paragraph(f"nda.{n}", BUSINESS_WORDS, 2)
                for n in range(1, 10)
            ],
        ),
        _doc(
            "legal/ip-assignment.pdf",
            [
                "Intellectual Property Assignment Agreement",
                "1.1 " + _paragraph("ip.1", BUSINESS_WORDS),
            ],
            [PLANTED["data-cite-ip-assignment"].text, "2.2 " + _paragraph("ip.2", BUSINESS_WORDS)],
            ["3.1 " + _paragraph("ip.3", BUSINESS_WORDS)],
        ),
        _doc(
            "leases/lease-lisbon.docx",
            [
                "Office Lease - Lisbon",
                PLANTED["data-ret-lease-2027"].text,
                _paragraph("ls.l", BUSINESS_WORDS),
            ],
        ),
        _doc(
            "leases/lease-madrid.docx",
            [
                "Office Lease - Madrid",
                "The lease term expires on 31 March 2026.",
                _paragraph("ls.m", BUSINESS_WORDS),
            ],
        ),
        _doc(
            "leases/lease-porto.docx",
            [
                "Office Lease - Porto",
                "The lease term expires on 31 October 2029.",
                _paragraph("ls.p", BUSINESS_WORDS),
            ],
        ),
        _doc(
            "hr/headcount-2024.xlsx",
            [
                "Headcount report 2024",
                "Engineering: 188",
                "Sales: 97",
                "Operations: 127",
                PLANTED["data-dmg-headcount"].text,
            ],
        ),
        _doc(
            "legal/dpa-contoso.docx",
            [
                "Data Processing Agreement - Contoso",
                _paragraph("dpa.1", BUSINESS_WORDS),
                PLANTED["data-dmg-dpa-region"].text,
                _paragraph("dpa.2", BUSINESS_WORDS),
            ],
        ),
        _doc(
            "audit/audit-report-2023.pdf",
            ["Independent Auditor's Report 2023", _paragraph("aud.1", BUSINESS_WORDS, 5)],
            [PLANTED["data-dmg-materiality"].text, _paragraph("aud.2", BUSINESS_WORDS, 5)],
        ),
    ]
    documents = list(planted)
    kinds = ("minutes", "policy", "budget", "deck", "supplier")
    index = 0
    while len(documents) < DATA_FILES[scale]:
        kind = kinds[index % len(kinds)]
        index += 1
        if kind == "supplier":
            name = FILLER_SUPPLIERS[(index // len(kinds)) % len(FILLER_SUPPLIERS)]
            documents.append(
                _supplier(
                    f"suppliers/supplier-agreement-{index:03d}.docx",
                    f"{name} {index:03d}",
                    indexed=False,
                )
            )
        elif kind == "minutes":
            documents.append(
                _doc(
                    f"board/minutes-{index:03d}.docx",
                    [f"Board minutes {index:03d}"]
                    + [_paragraph(f"min.{index}.{p}", BUSINESS_WORDS) for p in range(5)],
                )
            )
        elif kind == "policy":
            documents.append(
                Document(
                    f"policies/policy-{index:03d}.pdf",
                    tuple(
                        tuple(p)
                        for p in _filler_pages(
                            f"pol.{index}", 2, BUSINESS_WORDS, f"Policy {index:03d}"
                        )
                    ),
                )
            )
        elif kind == "budget":
            documents.append(
                _doc(
                    f"finance/budget-{index:03d}.xlsx",
                    [f"Budget workbook {index:03d}"]
                    + [_sentence(f"bud.{index}.{p}", BUSINESS_WORDS) for p in range(8)],
                )
            )
        else:
            documents.append(
                _doc(
                    f"board/deck-{index:03d}.pptx",
                    [f"Team update {index:03d}"]
                    + [_sentence(f"deck.{index}.{p}", BUSINESS_WORDS) for p in range(5)],
                )
            )
    return documents


# -- personal_archive --------------------------------------------------------------------------


def _personal(scale: str) -> list[Document]:
    planted = [
        _doc(
            "letters/oakridge-renewal-2024.docx",
            [
                "Oakridge Property - Tenancy renewal, June 2024",
                "1. " + _paragraph("oak.1", PERSONAL_WORDS),
                "2. " + _paragraph("oak.2", PERSONAL_WORDS),
                PLANTED["home-cite-rent-increase"].text,
                "4. " + _paragraph("oak.4", PERSONAL_WORDS),
            ],
        ),
        _doc(
            "insurance/home-policy-2024.pdf",
            [
                "Home insurance policy 2024",
                "1. " + _paragraph("home.1", PERSONAL_WORDS),
                "2. " + _paragraph("home.2", PERSONAL_WORDS),
            ],
            [
                "3. " + _paragraph("home.3", PERSONAL_WORDS),
                "4. " + _paragraph("home.4", PERSONAL_WORDS),
            ],
            [PLANTED["home-cite-flood"].text, "6. " + _paragraph("home.6", PERSONAL_WORDS)],
        ),
        _doc(
            "insurance/car-policy-2024.pdf",
            [
                "Car insurance policy 2024",
                "Policy number: CP-7781-2024",
                _paragraph("car.1", PERSONAL_WORDS),
            ],
        ),
        _doc(
            "receipts/brightline-dental-2024-03.pdf",
            [
                "Brightline Dental - invoice, March 2024",
                "Check-up and cleaning",
                PLANTED["home-ret-dental"].text,
            ],
        ),
        _doc(
            "statements/statement-2024-05.csv",
            [
                "date,description,amount",
                "2024-05-02,Grocery store,-84.20",
                "2024-05-09,Salary,3200.00",
                PLANTED["home-ret-harrow"].text,
                "2024-05-21,Electricity,-61.75",
            ],
        ),
        _doc(
            "medical/lab-results-2024.pdf",
            [
                "Laboratory results, April 2024",
                "Total cholesterol: 196 mg/dL",
                PLANTED["home-dmg-ldl"].text,
                "HDL cholesterol: 54 mg/dL",
            ],
        ),
        _doc(
            "tax/tax-summary-2023.docx",
            [
                "Tax summary 2023",
                "Income reported and allowances claimed.",
                PLANTED["home-dmg-refund"].text,
            ],
        ),
    ]
    documents = list(planted)
    index = 0
    while len(documents) < PERSONAL_FILES[scale]:
        index += 1
        month = (index - 1) % 12 + 1
        year = 2023 + (index - 1) // 12 % 2
        kind = index % 3
        if kind == 0 and not (year == 2024 and month == 5):  # noqa: PLR2004 -- May 2024 is planted
            documents.append(
                _doc(
                    f"statements/statement-{year}-{month:02d}-{index:03d}.csv",
                    [
                        "date,description,amount",
                        f"{year}-{month:02d}-03,Grocery store,-72.10",
                        f"{year}-{month:02d}-10,Salary,3200.00",
                        f"{year}-{month:02d}-22,Water,-28.40",
                        #  The index makes every statement distinct: identical bytes are one
                        #  document to the store, and F20's archive is sixty documents.
                        f"{year}-{month:02d}-28,Statement reference S{index:03d},0.00",
                    ],
                )
            )
        elif kind == 1:
            documents.append(
                _doc(
                    f"letters/letter-{index:03d}.docx",
                    [f"Letter {index:03d}"]
                    + [_paragraph(f"pl.{index}.{p}", PERSONAL_WORDS) for p in range(3)],
                )
            )
        else:
            documents.append(
                _doc(
                    f"receipts/receipt-{index:03d}.pdf",
                    [f"Receipt {index:03d}", _sentence(f"pr.{index}", PERSONAL_WORDS)],
                )
            )
    return documents


BUILDERS: Final[Mapping[str, Callable[[str], list[Document]]]] = {
    "legal_matter": _legal,
    "data_room": _data,
    "personal_archive": _personal,
}


def documents(corpus: str, scale: str) -> tuple[Document, ...]:
    """The corpus's documents at one scale, sorted by path. A pure function of its two arguments."""
    if corpus not in BUILDERS:
        msg = f"unknown corpus {corpus!r}; expected one of {', '.join(CORPORA)}"
        raise ValueError(msg)
    if scale not in SCALES:
        msg = f"unknown scale {scale!r}; expected full or quick"
        raise ValueError(msg)
    return tuple(sorted(BUILDERS[corpus](scale), key=lambda doc: doc.path))


def manifest_lines(docs: Sequence[Document]) -> list[str]:
    """`sha256  relpath` per file, sorted: what `EXPECTED.sha256` pins through `manifest_digest`."""
    return [f"{hashlib.sha256(doc.to_bytes()).hexdigest()}  {doc.path}" for doc in docs]


def manifest_bytes(docs: Sequence[Document]) -> bytes:
    return ("\n".join(manifest_lines(docs)) + "\n").encode("ascii")


def write_corpus(dest: Path, corpus: str, scale: str) -> tuple[Path, str]:
    """Write every file under `dest` and the manifest beside it. Returns the manifest and digest."""
    docs = documents(corpus, scale)
    for doc in docs:
        path = dest / doc.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(doc.to_bytes())
    manifest = dest.parent / f"{dest.name}.manifest"
    raw = manifest_bytes(docs)
    manifest.write_bytes(raw)
    return manifest, hashlib.sha256(raw).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ADR-14's three reference corpora, generated")
    parser.add_argument("--corpus", choices=CORPORA)
    parser.add_argument("--scale", choices=SCALES, default="quick")
    parser.add_argument("--all", action="store_true", help="every corpus at both scales")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--print-sha256", action="store_true", help="print each manifest's pin")
    args = parser.parse_args(argv)
    if not args.all and args.corpus is None:
        parser.error("name a --corpus, or pass --all")
    pairs = [(c, s) for c in CORPORA for s in SCALES] if args.all else [(args.corpus, args.scale)]
    for corpus, scale in pairs:
        manifest, digest = write_corpus(args.out / f"{corpus}-{scale}", corpus, scale)
        rel = (
            manifest.resolve().relative_to(ROOT).as_posix()
            if manifest.resolve().is_relative_to(ROOT)
            else manifest.as_posix()
        )
        sys.stdout.write(f"{digest}  {rel}\n" if args.print_sha256 else f"wrote {rel}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
