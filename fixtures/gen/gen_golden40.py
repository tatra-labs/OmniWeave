#!/usr/bin/env python3
"""Generate the 40-unit golden OUT fixture: a forty-slide owsvg/1 deck for `compile.pptx.native`.

00-vision.md V10-10 and 09-generation.md Q1 (charter F16) close `part` determinism by *"compiling
the 40-unit golden fixture on all nine platform cells and diffing `part_digest` member by member"*,
and 16-roadmap.md W9.8 lists it beside `fixtures/out/{golden, foreign, expected}`. The committed
`fixtures/out/golden/pptx/` carries two hand-written units, each a dense case of the table. This is
the other kind of fixture: a whole deck, long enough that a nondeterminism in member ordering,
relationship ids or media numbering has forty chances to show.

## What it is

A quarterly business review, forty slides, cycling through seven layouts built only from
constructs the two-unit golden already exercises, so every row this deck uses is one the target's
own tests hold:
- **cover**: a gradient band, a title, a subtitle with a `tspan`;
- **section**: a full-bleed rect and a numbered heading;
- **bullets**: a heading and four short lines;
- **chart**: four bars as rects, an axis `line`, value labels;
- **quote**: a heading and a cited quotation with a drop shadow (`filter`). Its `data-ow-cite`
  resolves through `cites.json`, verbatim, span over the whole text;
- **diagram**: circles, an ellipse, a `polyline`, a `polygon`, a `path` and an arrowed `line`;
- **figure**: the frozen image, clipped round, with a caption and an `a` link to the next slide.

No slide carries an `ow:manual` region, so the gate can pass and the compile is a release, which
is the case a determinism promise is about.

## Determinism

Every byte is a function of this file and of `omniweave_target_pptx`'s ConstructTable, whose digest
`il.toml` must carry (`ILBundle.load()` refuses a stale one). No clock, no RNG: the text cycles
fixed word lists by slide number. Output lands in `fixtures/generated/out/golden40/pptx/`, which is
`.gitignore`d, and `fixtures/gen/EXPECTED.sha256` pins its MANIFEST (`sha256  relpath` per file),
as the reference corpora are (13-quality.md:586-589).

Usage:

    uv run python fixtures/gen/gen_golden40.py                    # write the fixture
    uv run python fixtures/gen/gen_golden40.py --print-sha256     # ... and print the pin line

Specified in 16-roadmap.md W9.8, 09-generation.md section 5.4 and Q1, and 13-quality.md section 4.6.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS = 40
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1280 720" data-ow-el="{u}/e1">'
FACE = 'font-family="Probe Sans"'
CHART_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAECAIAAAA8r+mnAAAAEUlEQVR42mNQSFiAFTFQTwIA+L4kARXKiiwAAAAASUVORK5CYII="
)
"""`fixtures/out/golden/pptx/assets/chart.png`, the golden's one frozen image, carried as bytes."""
SLOT = "asset-slot:" + hashlib.sha256(CHART_PNG).hexdigest()
LAYOUTS = ("section", "bullets", "chart", "quote", "diagram", "figure")
TOPICS = (
    "Revenue",
    "Margins",
    "Customers",
    "Pipeline",
    "Hiring",
    "Product",
    "Support",
    "Costs",
    "Outlook",
)
WORDS = ("steady", "rising", "ahead", "on plan", "recovering", "flat", "strong", "mixed")
PALETTE = ("#1F4E79", "#2E75B6", "#70AD47", "#C55A11", "#7030A0", "#404040")


def _n(slide: int) -> str:
    return f"u{slide:02d}"


def _text(el: str, x: int, y: int, size: int, body: str, *, extra: str = "") -> str:
    return f'<text data-ow-el="{el}" x="{x}" y="{y}" {FACE} font-size="{size}"{extra}>{body}</text>'


def _cover(u: str) -> list[str]:
    return [
        '<defs><linearGradient id="band" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#1F4E79"/><stop offset="1" stop-color="#9DC3E6"/>'
        "</linearGradient></defs>",
        f'<rect data-ow-el="{u}/e2" x="0" y="200" width="1280" height="240" fill="url(#band)"/>',
        _text(f"{u}/e3", 80, 300, 48, "Quarterly business review", extra=' fill="#FFFFFF"'),
        f'<text data-ow-el="{u}/e4" x="80" y="380" {FACE} font-size="24" fill="#FFFFFF">'
        f'Q3 <tspan data-ow-el="{u}/e5" font-weight="bold">results and outlook</tspan></text>',
    ]


def _section(u: str, slide: int) -> list[str]:
    topic = TOPICS[(slide // 6) % len(TOPICS)]
    colour = PALETTE[slide % len(PALETTE)]
    return [
        f'<rect data-ow-el="{u}/e2" x="0" y="0" width="1280" height="720" fill="{colour}"/>',
        _text(f"{u}/e3", 80, 360, 48, f"{slide // 6 + 1}. {topic}", extra=' fill="#FFFFFF"'),
    ]


def _bullets(u: str, slide: int) -> list[str]:
    topic = TOPICS[slide % len(TOPICS)]
    out = [_text(f"{u}/e2", 80, 120, 36, f"{topic}: the quarter")]
    for line in range(4):
        word = WORDS[(slide + line) % len(WORDS)]
        out.append(
            _text(f"{u}/e{line + 3}", 100, 220 + 70 * line, 24, f"Item {line + 1} is {word}")
        )
    return out


def _chart(u: str, slide: int) -> list[str]:
    out = [
        _text(f"{u}/e2", 80, 120, 36, f"{TOPICS[slide % len(TOPICS)]} by month"),
        f'<line data-ow-el="{u}/e3" x1="120" y1="600" x2="1000" y2="600" stroke="#404040" '
        'stroke-width="2"/>',
    ]
    for bar in range(4):
        height = 80 + 40 * ((slide + 3 * bar) % 9)
        x = 160 + 200 * bar
        out.append(
            f'<rect data-ow-el="{u}/e{4 + 2 * bar}" x="{x}" y="{600 - height}" width="120" '
            f'height="{height}" fill="{PALETTE[bar]}"/>'
        )
        out.append(_text(f"{u}/e{5 + 2 * bar}", x + 30, 590 - height, 20, f"{height // 4}"))
    return out


def quote_text(slide: int) -> str:
    """The quotation slide `slide` cites, which `cites.json` holds verbatim."""
    topic = TOPICS[slide % len(TOPICS)]
    return f"{topic} grew {slide % 9 + 3}% on the prior quarter."


def cite_of(slide: int) -> str:
    return f"d7#{slide}"


def _quote(u: str, slide: int) -> list[str]:
    said = quote_text(slide)
    return [
        '<defs><filter id="lift" primitiveUnits="userSpaceOnUse"><feDropShadow dx="3" dy="3" '
        'stdDeviation="2" flood-color="#000000" flood-opacity="0.4"/></filter></defs>',
        _text(f"{u}/e2", 80, 120, 36, "In the words of the report"),
        f'<rect data-ow-el="{u}/e3" x="80" y="200" width="1120" height="200" fill="#DEEBF7" '
        'filter="url(#lift)"/>',
        _text(
            f"{u}/e4",
            120,
            320,
            28,
            said,
            extra=f' data-ow-cite="{cite_of(slide)}" data-ow-cite-kind="quote" '
            f'data-ow-cite-span="0:{len(said)}"',
        ),
    ]


def _diagram(u: str, slide: int) -> list[str]:
    colour = PALETTE[slide % len(PALETTE)]
    return [
        '<defs><marker id="arrow" orient="auto" markerWidth="6" markerHeight="6" '
        'markerUnits="strokeWidth" refX="3" refY="3"><path d="M0 0 L6 3 L0 6 Z"/></marker></defs>',
        _text(f"{u}/e2", 80, 120, 36, "How the work flows"),
        f'<circle data-ow-el="{u}/e3" cx="240" cy="360" r="80" fill="{colour}"/>',
        f'<ellipse data-ow-el="{u}/e4" cx="640" cy="360" rx="120" ry="70" fill="#9DC3E6"/>',
        f'<polygon data-ow-el="{u}/e5" points="980,300 1060,420 900,420" fill="#70AD47"/>',
        f'<line data-ow-el="{u}/e6" x1="330" y1="360" x2="510" y2="360" stroke="#404040" '
        'stroke-width="3" marker-end="url(#arrow)"/>',
        f'<polyline data-ow-el="{u}/e7" points="770,360 840,330 890,360" fill="none" '
        'stroke="#404040"/>',
        f'<path data-ow-el="{u}/e8" d="M240 460 L640 560 L980 460" fill="none" stroke="#404040" '
        'stroke-width="2"/>',
    ]


def _figure(u: str, slide: int) -> list[str]:
    following = _n(slide + 1) if slide < UNITS else _n(1)
    return [
        '<defs><clipPath id="round" clipPathUnits="userSpaceOnUse">'
        '<circle cx="640" cy="330" r="150"/></clipPath></defs>',
        _text(f"{u}/e2", 80, 120, 36, "The quarter in one picture"),
        f'<image data-ow-el="{u}/e3" href="{SLOT}" x="490" y="180" width="300" height="300" '
        'preserveAspectRatio="xMidYMid slice" clip-path="url(#round)"/>',
        _text(f"{u}/e4", 490, 540, 20, f"Figure {slide}: the dashboard"),
        f'<a data-ow-el="{u}/e5" href="#{following}">'
        + _text(f"{u}/e6", 490, 600, 20, "Next slide", extra=' fill="#1F4E79"')
        + "</a>",
    ]


def layout_of(slide: int) -> str:
    """The cover first, then the six layouts in turn."""
    return "cover" if slide == 1 else LAYOUTS[(slide - 2) % len(LAYOUTS)]


def unit_svg(slide: int) -> str:
    """Slide `slide` (1-based) as owsvg/1 text, LF line endings, one trailing newline."""
    u = _n(slide)
    kind = layout_of(slide)
    body = {
        "cover": lambda: _cover(u),
        "section": lambda: _section(u, slide),
        "bullets": lambda: _bullets(u, slide),
        "chart": lambda: _chart(u, slide),
        "quote": lambda: _quote(u, slide),
        "diagram": lambda: _diagram(u, slide),
        "figure": lambda: _figure(u, slide),
    }[kind]()
    return "\n".join([SVG.format(u=u), *(f"  {line}" for line in body), "</svg>"]) + "\n"


def cites() -> dict[str, dict[str, object]]:
    """`cites.json`: each quote slide's cite, its text verbatim, as the golden's one cite is."""
    out: dict[str, dict[str, object]] = {}
    for slide in range(1, UNITS + 1):
        if layout_of(slide) == "quote":
            out[cite_of(slide)] = {
                "block_id": 100 + slide,
                "doc_gen": 3,
                "doc_ord": 7,
                "quote": "verbatim",
                "restriction_bits": 0,
                "text": quote_text(slide),
            }
    return out


def il_toml(constructs_digest: str) -> str:
    head = (
        'schema = "omniweave.out-il/1"\nil = "owsvg/1"\n'
        f'constructs_digest = "{constructs_digest}"\n'
    )
    rows = "".join(
        f'\n[[unit]]\nid = "{_n(s)}"\nord = {s}\nfile = "{_n(s)}.svg"\n'
        for s in range(1, UNITS + 1)
    )
    return head + rows


def constructs_digest() -> str:
    """`compile.pptx.native`'s ConstructTable digest, which `il.toml` must carry."""
    for dist in sorted((ROOT / "packages").iterdir()):
        src = dist / "src"
        if src.is_dir() and str(src) not in sys.path:
            sys.path.insert(0, str(src))
    from omniweave_target_pptx.driver import table  # noqa: PLC0415 -- the one product import.

    return str(table().digest())


def files(digest: str) -> Iterator[tuple[str, bytes]]:
    """Every file of the fixture as `(relpath, bytes)`, in relpath order."""
    out = {
        "assets/chart.png": CHART_PNG,
        "cites.json": (json.dumps(cites(), indent=1, sort_keys=True) + "\n").encode("utf-8"),
        "il/il.toml": il_toml(digest).encode("utf-8"),
        **{f"il/{_n(s)}.svg": unit_svg(s).encode("utf-8") for s in range(1, UNITS + 1)},
    }
    yield from sorted(out.items())


def manifest_bytes(digest: str) -> bytes:
    """`sha256  relpath` per file, LF, what `EXPECTED.sha256` pins."""
    return "".join(
        f"{hashlib.sha256(data).hexdigest()}  {path}\n" for path, data in files(digest)
    ).encode("ascii")


def write(out: Path, digest: str | None = None) -> Path:
    """Write the fixture under `out` and its MANIFEST beside it; return the MANIFEST's path."""
    chosen = digest if digest is not None else constructs_digest()
    for path, data in files(chosen):
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = out.parent / f"{out.name}.manifest"
    manifest.write_bytes(manifest_bytes(chosen))
    return manifest


def default_out() -> Path:
    return ROOT / "fixtures" / "generated" / "out" / "golden40" / "pptx"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_golden40", description="the 40-unit golden OUT fixture"
    )
    parser.add_argument("--out", type=Path, default=None, help="default: fixtures/generated/...")
    parser.add_argument("--print-sha256", action="store_true", help="print the pin line")
    args = parser.parse_args(argv)
    out: Path = args.out if args.out is not None else default_out()
    manifest = write(out)
    sys.stdout.write(f"units      {UNITS}\nout        {out}\nmanifest   {manifest}\n")
    if args.print_sha256:
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        try:
            relative = manifest.resolve().relative_to(ROOT).as_posix()
        except ValueError:  # pragma: no cover -- an --out outside the workspace.
            relative = manifest.as_posix()
        sys.stdout.write(f"{digest}  {relative}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover -- the script path.
    raise SystemExit(main())
