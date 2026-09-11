# `parse.office.anydoc`'s conformance fixtures

Sixteen files across twelve media types, each one a case the driver has to answer differently. Run
the twelve suites over them with:

```console
$ uv run python tools/ow_conform.py \
    --card packages/omniweave-office/src/omniweave_office/driver.toml \
    --fixtures packages/omniweave-office/fixtures
```

## The corpus

| file | what it is for |
|---|---|
| `rich.docx` | every non-trivial `[capability.parse]` row at once: two heading levels, bold/italic/strike runs, a hyperlink, a bookmark, a merged-cell table, displayed **and** inline OMML, an embedded PNG with an `origin_part`, and a footnote with its reference site. One file rather than seven, because `capability` asserts `achieved <= declared` **per fixture** and a corpus of single-feature documents would never once exercise the card as a whole |
| `book.epub` | the four `Block` variants no office format above reaches — `rule`, `code_block`, `block_quote` — plus a link whose target kind is `anchor`. With `rich.docx` it completes all eight |
| `sheet.xlsx` `sheet.ods` `sheet.xls` | one merged cell in three encodings: OOXML `mergeCell`, ODF `table:number-columns-spanned` with an explicit `covered-table-cell`, and BIFF8. Three spellings, one exactly-once grid |
| `deck.pptx` | a speaker note, which anydoc emits as `Block::BlockQuote` — **indistinguishable from a real quotation** in the Python model. `Kind.SPEAKER_NOTE` therefore has no producer on this path, and `test_office_blocks.py` asserts the blockquote rather than leaving the claim in a docstring |
| `deck.odp` `notes.odt` `memo.rtf` `rows.csv` | the remaining served formats, each minimal. `rows.csv` is the one with **no signature at all**: it decodes only because its sidecar names `text/csv`, which is the whole reason `UnitRef` carries a media type |
| `deck.ppt` | a valid but **empty** PowerPoint 97 stream. The driver returns `ok` with zero blocks and `is_valid_nonempty()` is what turns that into `FAILED_PERMANENT(EMPTY_RESULT)` host-side rather than caching a parse of nothing |
| `deepxml.docx` | 400 nested elements, past anydoc's compiled-in `max_xml_depth = 256`. The one way a limit that lives in someone else's crate becomes observable from Python: 11 KB in, a refusal out, no allocation |
| `encrypted.odt` | an ODF manifest declaring `encryption-data`. `FailureClass.ENCRYPTED`, decided from the manifest **before** any attempt to decode the content |
| `truncated.docx` | `rich.docx` cut in half. The ZIP central directory is gone, so `MalformedError` -> `CORRUPT_INPUT` |
| `memo.doc` | a `WordDocument` stream with no valid FIB: recognised as `doc` by `sniff()` and refused as `CORRUPT_INPUT` by `parse()`. Two different answers, both checked |
| `not_a_document.bin` | an ELF header. `sniff()` returns `()`, a legitimate "not mine" |

## What this corpus does not have, said plainly

**No positive `.doc` case, and no `.ppt` case with content.** Both are hand-written compound files
and both stop at the container. Word 97's FIB indexes a piece table in a second stream, and
PowerPoint 97's record tree (`UserEditAtom`, the persist-pointer blocks, `DocumentContainer`,
`SlideListWithText`) is a graph of offsets into itself; assembling either would be writing a second
implementation of the format whose reader is the thing under test. BIFF8 is flat — every record is
`(id, length, payload)` — which is why `sheet.xls` *is* a real workbook and the other two are not.

The consequence is exact and worth stating rather than leaving for a reader to notice: the
`capability` suite's per-document assertions never run on a `.doc`, and `deck.ppt` contributes a
zero-block document rather than a parsed presentation. `sniff()` is covered for all twelve tokens;
`parse()` is covered for ten.

## Provenance

All sixteen come from this repository's own generator:

```console
$ uv run python fixtures/gen/gen_office_fixtures.py
```

`generated` is [13-quality.md](../../../_plan/13-quality.md) §4.2's **preferred** provenance and
requires two things — the generator path under `fixtures/gen/` and the expected output sha256 —
and each file's `.meta.toml` sidecar carries both. The generator is deterministic (fixed ZIP
timestamps, `ZIP_STORED`, no library beyond `zipfile` and `struct`), so `EXPECTED.sha256` is a real
check rather than a snapshot of whichever machine ran last.

## The sidecars are not decoration

`<file>.meta.toml` is §4.4's fixture manifest, and the kit reads one key out of it:
`[fixture] media_type`, which becomes `UnitRef.media_type`. Without it every fixture reached
`parse()` with no routed media type — strictly harder than a real invocation, where routing has
already decided the format before `INVOKE` — and `rows.csv` could not decode at all, because CSV
carries no signature for anyone to detect.

`not_a_document.bin` deliberately has **no** `media_type` key. An absent key and an empty string
are different claims: the first says no host would have decided a type for these bytes, and that is
the case the driver must also handle.

## They are bytes

`.gitattributes` in this directory sets `* -text`. The repository root's `* text=auto eol=lf`
([11-repo-layout.md](../../../_plan/11-repo-layout.md) §1.9) would otherwise rewrite the ones that
contain no NUL — `rows.csv`, `memo.rtf` and every XML part inside a stored ZIP — which would
invalidate `EXPECTED.sha256`, break the CRC of every ZIP entry, and change the byte offsets a
compound file's FAT points at.
