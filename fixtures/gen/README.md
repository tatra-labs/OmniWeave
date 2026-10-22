# `fixtures/gen/` — generated fixtures

Anything synthesisable is a generator here, never bytes in git. 13-quality.md section 4.6
(:576-592) is the ruling: no git-lfs, no submodule, no fetch-at-test-time, because the
`contributor-parity` job runs with **no network** and INV-24 requires a committed artefact to be
byte-reproducible from inputs it names.

## The regime every file here obeys — 13-quality.md:586-589

1. **Deterministic** under `SOURCE_DATE_EPOCH=0` with `random`, `secrets`, `uuid4`, `time.time`
   and `datetime.now` monkeypatched to raise. The tests install those five patches and run the
   generator under them; absence of a call today is not the same as inability to call.
2. **Output lands in `fixtures/generated/`**, which is `.gitignore`d.
3. **`EXPECTED.sha256` pins each output**, "so a generator change is a one-line visible diff
   rather than a silent corpus change". Standard `sha256sum` format, paths relative to the
   workspace root. That file records which line each test checks.

## `gen_5000p_pdf.py`

The 5,000-page PDF. Built at P2 stage C although **no work item in the plan is assigned to it**
(W4.10 builds `fixtures/incremental/`, W9.8 builds `fixtures/out/`, and 13-quality.md section 4.6
owns the regime but names no phase); P2 needs it for the demo at 16-roadmap.md:442 and for two of
the eight exit commands at 16-roadmap.md:459-460.

```bash
uv run python fixtures/gen/gen_5000p_pdf.py                        # 5,000 pages, ~29 MB, ~1.2 s
uv run python fixtures/gen/gen_5000p_pdf.py --pages 8 --print-sha256
uv run pytest packages/omniweave-core/tests/unit/test_fixture_gen.py -q
```

Every object is uncompressed, every content stream carries an explicit `/Length` and no
`/Filter`, and the cross-reference section is a classic xref **table**. That is not nostalgia: the
P2 stub `parse/1` driver (`tools/p2_stub_parse.py`) finds each text literal at a byte offset in
the FILE and turns it into an `OriginBytes`, which is what lets `ow store verify` re-derive
`content_sha256` from stored bytes. No byte in the output is a carriage return, so a Windows
checkout cannot shift an offset.

A page is 87 text runs — one heading, 8 paragraphs × 4 lines of ~75 characters, and a 9 × 6 table
of ~10-character cells — which the stub coalesces into **64 blocks per page** (heading, eight
paragraphs, one table, fifty-four cells; the page-root block is the sink's). That 64 is **a
property of this fixture, not a measurement of any corpus** (ruling D27): it is chosen only to sit
inside the plan's stated 60-120 blocks/page envelope (00-vision.md:474). F1's blocks-per-page half
closes in P3 against ten real 200-page documents (03-document-model.md:3086); what closes off this
corpus at P2 is the *store* variable, `store.bytes_per_block` (12-performance.md:244).

**Do not tune the constants to a budget.** `store.bytes_per_block = 660` is measured over this
fixture; a fixture shaped to make 660 come out true would make the nightly ratchet measure its own
input.

## `gen_reference_corpora.py`

ADR-14 D14.1's three reference corpora for `bench/serve/`, at two scales:

| corpus | `full` | `quick` |
|---|---|---|
| `legal_matter` | 5,000 pages over 120 PDFs | 250 pages over 12 |
| `data_room` | 137 files | 16 |
| `personal_archive` | 60 files | 8 |

```bash
uv run python fixtures/gen/gen_reference_corpora.py --all --print-sha256   # all six, ~1.5 s
```

- **Every answer the harness asks for is planted here.** `PLANTED` names each task's sentence and
  its one document, and `ABSENT` names the terms no document holds.
- **Formats are the ones the shipped roster parses**: PDF, DOCX, XLSX, PPTX and CSV. A plain-text
  file is identified and never parsed (D567).
- **Each corpus is pinned through its manifest**, one `sha256  relpath` line per file, as the
  incremental roster is. `bench/serve/test_corpora.py` checks the six pins.

## `gen_golden40.py`

V10-10's *"40-unit golden"* OUT fixture (D881): a forty-slide owsvg/1 deck for
`compile.pptx.native`, a quarterly review cycling seven layouts built only from constructs the
two-unit `fixtures/out/golden/pptx/` already exercises. It passes the pptx gate as a release, and
`tools/check_out_determinism.py --target pptx --golden fixtures/generated/out/golden40/pptx`
compiles it five ways.

```bash
uv run python fixtures/gen/gen_golden40.py --print-sha256
uv run pytest packages/omniweave-target-pptx/tests/unit/test_golden40.py -q
```

- **The one product import** is the pptx ConstructTable, whose digest `il.toml` must carry, so a
  table change moves the pin. That is the honest coupling: the deck is IL written against it.
- **Pinned through its manifest**, `fixtures/generated/out/golden40/pptx.manifest`.

## `gen_4m_cell_sheet.py`

12-performance.md section 4.3's *"merge-free 4M-cell spreadsheet"* (D929): one sheet, 200,000 rows
of 20 cells, no merged region, a text label in column A and integers that are a pure function of
the row and column. It is the fixture of `rss.merged4mcell_peak_bytes` and F29's cell-count sweep.

```bash
uv run python fixtures/gen/gen_4m_cell_sheet.py --print-sha256              # 4M cells, ~6 s, ~16 MB
uv run python fixtures/gen/gen_4m_cell_sheet.py --cells 2000 --print-sha256 # the cheap pin
```

- **Deflated, because stored it is ~120 MB** and the office card's `max_input_bytes` is 64 MiB.
- **Pinned through a manifest** over the members' uncompressed bytes, since deflate's bytes differ
  across zlib builds; `test_fixture_sheet.py` checks both pins.
- **What it measured on first use (D929)**, through a real `ow add` with the office driver in a
  worker: peak worker RSS 214 MB at 50k cells, 390 MB at 100k and 757 MB at 200k, about 3.7 KB a
  cell, so the card's `memory_mb = 1024` refuses from ~280k cells; at 4M cells anydoc refuses
  first, on its own `max_xml_nodes = 2,000,000`, in 12 s. F2 and F29 are where those numbers go.
