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
