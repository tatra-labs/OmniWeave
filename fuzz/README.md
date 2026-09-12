# `fuzz/`

Two halves over one property, because one of them cannot run on two thirds of this project's CI.

```
fuzz/
├── targets/    the atheris targets. One per format handler, plus wire framing
├── seeds/      the starting corpus. Mirrored from vendor/anydoc, plus wire/, which is ours
└── corpus/     the fuzzer's working directory. GITIGNORED; libFuzzer writes here
```

## Running it

**The replay**, which is what `16-roadmap.md:520` runs and what nine CI cells run:

```bash
uv run pytest fuzz/ -q                    # all three targets, in child processes
uv run python fuzz/targets/wire.py --replay   # one target, directly
```

Every seed, plus `omniweave_conform.mutate`'s seven mutations of it, through the target's
property. No fuzzer, no clang, every platform. Exit `0` clean, `1` a finding, `3` a hang,
`4` the target could not run here.

**The search**, which is `14-security.md:477`'s nightly and needs Linux:

```bash
uv sync --frozen --all-packages --group dev    # atheris installs on linux only
mkdir -p fuzz/corpus/office
uv run python fuzz/targets/office.py fuzz/corpus/office fuzz/seeds/xlsx fuzz/seeds/xls \
    -max_total_time=3600 -timeout=5
```

**The first directory is the writable one** and every later one is read-only, which is
`vendor/anydoc/fuzz/README.md`'s convention and the reason `fuzz/corpus/` exists at all. Never
pass a path under `vendor/` to a fuzzer: those bytes are the artefact `vendor/anydoc/anydoc.sha256`
digests and `tools/gate_vendor.py` (G12) checks, and a fuzzer that writes one new input there
fails the build for a reason that has nothing to do with the code.

## The property, in one line

**A crash is allowed, a hang is not** — `04-driver-system.md:2082`, and `03-document-model.md`'s
P28 at the row grain: "a corrupt fixture yields `status='partial'` with `Diag` rows, or a typed
`DriverError` from the closed `FailureClass`; a crash is allowed (one unit), a hang is not."

So each target declares `allowed`, the exception types that are the code *working*, and everything
outside it is a finding. `wire` allows `DriverHostError` alone — a framing fault is **ours**, never
a driver's (`02-architecture.md:1060`) — so a `RecursionError` out of a JSON scanner is a finding,
which is exactly what `omniweave_core.host.wire`'s own docstring says the fuzz property forbids.
The two driver targets allow `DriverError`, `RecursionError` and `MemoryError`, the last two
standing in for the crash a real host contains as one row.

## The three targets

| target | property | corpus |
|---|---|---|
| `wire` | `omniweave-driver/1` framing: a byte string is a frame or a named `WireFault`, and what decodes re-encodes | `seeds/wire/`, authored here by `--write-seeds` |
| `office` | `parse.office.anydoc`: whatever the Rust side does, what crosses back into Python is typed | `seeds/xls`, `seeds/xlsb`, `seeds/xlsx` + the driver's own fixtures |
| `pdf` | `parse.pdf.pdfium`, same property | the driver's own fixtures; anydoc ships a `pdf.rs` target and no pdf seeds |

`wire` is `16-roadmap.md:482`'s — W3.2 owes "80 lines of framing plus an atheris target". The
other two are `14-security.md:477`'s "one target per format handler", and at P3 this repository
has exactly two format handlers.

## Two corpora, two homes, and they are not the same discipline

`13-quality.md:163-168`, which is worth reading before adding a file to either:

> `fixtures/regressions/` holds minimized hypothesis counterexamples, one file per property, read
> only by the property that produced it. `fuzz/seeds/` holds the atheris corpus, mirrored from
> `vendor/anydoc` […] A hypothesis counterexample never lands in `fuzz/seeds/` and a fuzz crash
> never lands in `fixtures/regressions/`: the first is an input a property rejected, the second is
> an input that killed a process, and merging them loses which is which.

`fuzz/seeds/` is **generated**, both halves. The mirrored half is written and checked by
`tools/mirror_fuzz_seeds.py` against `vendor/anydoc/fuzz/seeds/`; the authored half is written by
`fuzz/targets/wire.py --write-seeds` and checked by `fuzz/test_targets.py`. Editing a seed by hand
will fail CI, and that is the point — the thing it would drift away from is the upstream commit
G12 pins.
