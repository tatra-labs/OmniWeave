#!/usr/bin/env python3
"""Generate `parse.pdf.pdfium`'s seven conformance fixtures, byte for byte. **D843.**

`packages/omniweave-pdf/fixtures/` held seven committed files and no `.meta.toml`, so `Q-G1`
(13-quality.md:92, *"every fixture byte has a manifest row"*) had nothing to read for them.
Four were already `gen_5000p_pdf.py`'s output. Three were hand-written or hand-cut, which section
4.2 would make `authored`, a provenance that needs a contributor and a CLA reference. This
repository takes a DCO and no CLA (11-repo-layout.md section 8.3), so it has no reference to
give. Section 4.2 calls `generated` **preferred**, and all three are synthesisable, so this script
synthesises them:

| file | how |
|---|---|
| `gen01p.pdf` .. `gen08p.pdf` | `gen_5000p_pdf.generate()` at 1, 2, 4 and 8 pages |
| `no_text_layer.pdf` | one A4 page whose content stream is empty, its xref computed here |
| `truncated.pdf` | the first half of `gen02p.pdf`'s bytes |
| `not_a_pdf.bin` | a ZIP local-file signature and one line of text |

Each output is checked against `packages/omniweave-pdf/fixtures/EXPECTED.sha256`, which this script
never writes: the pins came first, so a byte this script changes is a refusal, not a new pin. With
`--sidecars` it also writes each file's `.meta.toml`.

Usage:

    uv run python fixtures/gen/gen_pdf_fixtures.py                 # verify, write nothing
    uv run python fixtures/gen/gen_pdf_fixtures.py --out <dir>     # write the seven files there
    uv run python fixtures/gen/gen_pdf_fixtures.py --sidecars      # (re)write the sidecars in place

Specified in 13-quality.md sections 4.2 to 4.4.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path
from typing import Final

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gen_5000p_pdf  # noqa: E402

REPO: Final = HERE.parent.parent
FIXTURES: Final = REPO / "packages" / "omniweave-pdf" / "fixtures"
GENERATOR: Final = "fixtures/gen/gen_pdf_fixtures.py"
PDF: Final = "application/pdf"


def born_digital(pages: int) -> bytes:
    """`gen_5000p_pdf`'s document at `pages`, through a scratch file: `generate()` writes one."""
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "out.pdf"
        gen_5000p_pdf.generate(out, pages=pages)
        return out.read_bytes()


def no_text_layer() -> bytes:
    """One A4 page with an empty content stream: readable, and holding no character."""
    objects = (
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.276 841.89] /Contents 4 0 R "
        b"/Resources << >> >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    )
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def truncated() -> bytes:
    """`gen02p.pdf` cut in half: the header survives, `sniff()` claims it, `parse()` refuses."""
    whole = born_digital(2)
    return whole[: len(whole) // 2]


def not_a_pdf() -> bytes:
    """A ZIP local-file signature and a line of text: `sniff()` returns `()`, "not mine"."""
    return b"PK\x03\x04this is a zip archive, not a document\n"


BUILDS: Final = {
    "gen01p.pdf": (lambda: born_digital(1), PDF, "born-digital, one page with a real text layer"),
    "gen02p.pdf": (lambda: born_digital(2), PDF, "born-digital, two pages with a real text layer"),
    "gen04p.pdf": (
        lambda: born_digital(4),
        PDF,
        "born-digital, four pages: cost's curve needs spread",
    ),
    "gen08p.pdf": (
        lambda: born_digital(8),
        PDF,
        "born-digital, eight pages: cost's curve needs spread",
    ),
    "no_text_layer.pdf": (no_text_layer, PDF, "zero characters: NEEDS_OCR, not CORRUPT_INPUT"),
    "truncated.pdf": (truncated, PDF, "gen02p.pdf cut in half: sniff() claims it, parse() refuses"),
    "not_a_pdf.bin": (not_a_pdf, None, "a zip header: sniff() returns (), a legitimate not mine"),
}

SLICES: Final[dict[str, tuple[str, ...]]] = {
    "gen01p.pdf": ("pdf/born_digital/gen",),
    "gen02p.pdf": ("pdf/born_digital/gen",),
    "gen04p.pdf": ("pdf/born_digital/gen",),
    "gen08p.pdf": ("pdf/born_digital/gen",),
}
"""D983: `[fixture.tests] slices` for the four labelled fixtures, the corpus vocabulary
13-quality.md:1148-1152 matches a `[[gate]]` row's `slice` glob against. `order_acc`'s row is
`pdf/born_digital/*` verbatim from :1099, and `fnmatchcase` wants a segment under it, so the four
born-digital generated pages declare `pdf/born_digital/gen`. `no_text_layer.pdf` declares none: it
carries no label, and a slice nothing scores names nothing."""

COARSE: Final = "pdf/born_digital/labelled"
"""D1002, a user ruling of 2026-10-28: the coarse slice every fixture in `SLICES` also declares.

`SLICES` is exactly the labelled set, and every metric that reads a slice macro-averages at
`min_slice_n = 30`, which no single extension will ever hold: the per-extension rows report
`unknown` for ever. One coarse slice per family is the set that can reach thirty, and it is
appended here rather than written into each row so that the family has one home. Q-G1 ruling 14
derives the same key from the per-extension ones and holds the pair together in both directions."""

TESTS: Final = """
[fixture.tests]
# 13-quality.md section 4.4's block, and :1150's vocabulary: the corpus declares the slice and a
# `[[gate]]` row's `slice` glob is matched against it, never the router's Slice.
# `{coarse}` is the coarse slice (D1002, a user ruling of 2026-10-28). The
# per-extension key beside it will never hold `min_slice_n = 30` documents, so its row reports
# `unknown` for ever; one slice per family is the set that can reach thirty, and the
# per-extension rows stay visible saying what they are. Q-G1 holds the pair together.
slices = [{slices}]
"""

SIDECAR: Final = """\
# {name}.meta.toml -- 13-quality.md section 4.4's fixture manifest.
#
# {purpose}
[fixture]
sha256 = "{digest}"
bytes = {size}
{media}provenance = "generated"
spdx = "Apache-2.0"
generator = "{generator}"
{tests}"""


def pins() -> dict[str, str]:
    """`EXPECTED.sha256` as `{name: digest}`."""
    out = {}
    for line in (FIXTURES / "EXPECTED.sha256").read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            digest, name = line.split(maxsplit=1)
            out[name.strip()] = digest
    return out


def sidecar(name: str, data: bytes, media_type: str | None, purpose: str) -> str:
    """One `.meta.toml`. `media_type` is omitted, not empty, when nothing would route the bytes."""
    media = f'media_type = "{media_type}"\n' if media_type else ""
    declared = SLICES.get(name)
    tests = ""
    if declared:
        names = ", ".join(f'"{one}"' for one in (*declared, COARSE))
        tests = TESTS.format(slices=names, coarse=COARSE)
    return SIDECAR.format(
        name=name,
        purpose=purpose,
        digest=hashlib.sha256(data).hexdigest(),
        size=len(data),
        media=media,
        generator=GENERATOR,
        tests=tests,
    )


def report(line: str) -> None:
    sys.stdout.write(f"{line}\n")


def main(argv: list[str] | None = None) -> int:
    """0 every output matches its pin, 1 one does not."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--sidecars", action="store_true")
    args = parser.parse_args(argv)
    expected = pins()
    bad = 0
    for name, (build, media_type, purpose) in sorted(BUILDS.items()):
        data = build()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected.get(name):
            report(f"MISMATCH  {name}: {digest} is not the pin {expected.get(name)}")
            bad += 1
            continue
        if args.out is not None:
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / name).write_bytes(data)
        if args.sidecars:
            (FIXTURES / f"{name}.meta.toml").write_bytes(
                sidecar(name, data, media_type, purpose).encode("utf-8")
            )
        report(f"ok        {name}  {digest}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
