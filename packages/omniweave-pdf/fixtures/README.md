# `parse.pdf.pdfium`'s conformance fixtures

Seven files, each one a case the driver has to answer differently. Run the twelve suites over them
with:

```console
$ uv run python tools/ow_conform.py \
    --card packages/omniweave-pdf/src/omniweave_pdf/driver.toml \
    --fixtures packages/omniweave-pdf/fixtures
```

| file | what it is for |
|---|---|
| `gen01p.pdf` `gen02p.pdf` `gen04p.pdf` `gen08p.pdf` | born-digital pages with a real text layer. Four sizes, because `cost`'s curve fit needs spread and `capability`'s P7 wants more than one page's worth of glyph offsets — a one-page fixture cannot tell "the running total works" from "page 2 happens to start where a bug would put it" |
| `no_text_layer.pdf` | one page, one empty content stream. pdfium opens it and reports zero characters, which is `NEEDS_OCR` rather than `CORRUPT_INPUT`: the document is readable and this driver is not the one that can read it |
| `truncated.pdf` | `gen02p.pdf` cut in half. The header survives, so `sniff()` still claims it and `parse()` refuses it — which is the division of labour those two methods are for |
| `not_a_pdf.bin` | a zip header. `sniff()` returns `()`, a legitimate "not mine" |

## Provenance

The four `gen*.pdf` come from this repository's own generator, which writes PDF by hand with no
library, every object uncompressed and a classic xref table:

```console
$ uv run python fixtures/gen/gen_5000p_pdf.py --pages <N> --out packages/omniweave-pdf/fixtures/gen<NN>p.pdf
```

It is deterministic, so `EXPECTED.sha256` is checkable and the generator is the record of how to
rebuild them. `no_text_layer.pdf` and `not_a_pdf.bin` are hand-written; `truncated.pdf` is the
first half of `gen02p.pdf`'s bytes.

## They are bytes

`.gitattributes` in this directory sets `* -text`. The repository root's `* text=auto eol=lf`
(11-repo-layout.md section 1.9) would otherwise rewrite the ones that contain no NUL, which would
silently invalidate `EXPECTED.sha256` **and every glyph offset any test records against them** --
a line-ending rewrite moves characters in pdfium's index space.
