# Writing an omniweave driver

The claim is that a driver is an afternoon's work. This is the packaging half of that claim —
[the repository layout](plan/11-repo-layout.md) §1.5 — and it ends with a driver that passes the
conformance kit's mandatory tier.

There is a worked example in this repository that is not one of ours:
`packages/omniweave-core/tests/unit/external_driver_subrip/`, a SubRip subtitle parser that shares
no code with the template. It is **two source files and eight fixtures**, and it passes **11 of 11
mandatory suites in 3.11 s**. Read it alongside this document; it is the shortest honest answer to
every question below.

## The whole surface you depend on

```toml
dependencies = ["omniweave-ports >=1,<2"]
[dependency-groups]
dev = ["omniweave-conform"]          # the testkit is DEV-ONLY
```

`omniweave-ports` is **the one distribution in this project with an empty `dependencies` list** —
five modules, standard library only. That is the entire runtime contract. `omniweave-conform` is
the conformance kit and belongs in a dev group, because a driver that ships its own test harness
ships a dependency its users did not ask for.

**Do not depend on `omniweave_core`.** For a non-`compile` driver that is a G4 failure, and the
message names the fix. None of `omniweave-office`, `-pdf`, `-vision`, `-graph` or `-llm` declares a
version-bearing dependency on anything first-party except `omniweave-ports`, which is why a
`RELEASE` bump rewrites no constraint in five of the fourteen `pyproject.toml` files — and it is the
same property you get for free.

## The shape

```text
my-driver/
├── pyproject.toml
│     dependencies = ["omniweave-ports >=1,<2", ...]
│     [project.entry-points."omniweave.drivers"]
│     "parse.subtitle.subrip" = "subrip_cues"      # A DOTTED PACKAGE. No ':', no path.
├── LICENSE  NOTICE  THIRD_PARTY.md  LICENSES/
├── src/subrip_cues/
│   ├── driver.toml          THE CARD. Read by tomllib, never imported.
│   ├── driver.py            the class the card's `entrypoint` names
│   └── __init__.py
└── tests/
```

### The two grammars that look alike and are not

This is the one thing worth reading twice, because the two values sit a few lines apart and only
one of them may contain a colon:

| where | grammar | example |
|---|---|---|
| the **entry-point value** in `pyproject.toml` | a colon-free dotted **package** path | `subrip_cues` |
| the card's **`entrypoint`** key | `module:attr` | `subrip_cues.driver:SubRipParser` |

The card's key is the one place a colon is legal, because `activate()` has to assert the loaded
class's `PORT` and `SCHEMA_VERSION` against the card *before any work happens*. [The driver
system](plan/04-driver-system.md) §4.1 owns both grammars.

If you build with **setuptools**, a path-shaped entry-point value is rejected at build time by
`setuptools._entry_points.validate`. If you build with **hatchling** — as all fourteen
distributions here do — nothing validates it, and a malformed value ships and fails on a user's
machine as a discovery-time refusal. So the shape is asserted twice over: G4 asserts it for this
repository, and the kit's `card` suite asserts it for yours. Each value must match
`^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$`, contain no `:` and no `/`, and name a package that
exists in your `src/`.

### The card is data

`driver.toml` is read with `tomllib` and **never imported**. That is INV-4, and it is what lets the
host read every installed driver's capabilities without executing any of their code — which is also
why the `purity` suite checks that *zero* driver modules were imported during discovery.

## Running the kit

```bash
PYTHONPATH=src python <omniweave>/tools/ow_conform.py \
  --card src/subrip_cues/driver.toml --fixtures fixtures
```

`tools/ow_conform.py` is the supported runner and it is **not** a thin wrapper around the API.
Three of the suites spawn children — `idempotence` compares across processes, `determinism` varies
`TMPDIR`, `LC_ALL` and `TZ` in a child with a different cwd, and `fuzz` runs execs — and the script
is what builds those children's environment, keeping your `PYTHONPATH` after the repository's own
entries and making each entry absolute, because the child runs somewhere else and a relative
`src` would name a directory that is not there. Both of those are recorded scars, D923 and D967.

Measured on the SubRip driver: **11 of 11 through the script, 8 of 11 through a bare
`run(subject)`**, with `idempotence`, `determinism` and `fuzz` failing for harness reasons rather
than driver ones. So embed the API if you want the report object —

```python
from omniweave_conform import MANDATORY, Subject, Verdict, run

subject = Subject.of(card_path, fixtures_dir=fixtures, workdir=scratch)
report = run(subject)
failed = [r.suite for r in report.results if r.suite in MANDATORY and r.verdict is not Verdict.PASS]
```

— but let the script be what tells you whether you pass. (`report.results`, not `report.suites`;
and `Verdict` is a `StrEnum`, so compare against the member and not against `.name`.)

Note that `ow conform` is **not** a shipped CLI verb, though the plan writes it that way in several
places: the kit has no console script and no `__main__`, so the path above is the invocation.

Twelve suites run. **Eleven are mandatory**: `card`, `purity`, `contract`, `capability`,
`idempotence`, `determinism`, `limits`, `sandbox`, `cost`, `licence`, `fuzz`. The twelfth,
`quality`, needs a registered corpus, and leaving it `unknown` is the designed answer:

> a driver that declines to produce a number is honest rather than deficient

Passing the mandatory tier prints a badge string and the sentence you may use:

```text
omniweave-conform 1.0.0 · mandatory 11/11 pass · quality unknown · card sha256:…
and the sentence: "passes the omniweave conformance kit 1.0.0, mandatory suites"
```

What the suites actually hold you to is worth skimming before you write code, because two of them
catch design decisions rather than bugs: `purity` means discovery must not import you, and
`determinism` means your output cannot vary with `TMPDIR`, `LC_ALL` or `TZ`.

## Two honest limitations

**A new file format cannot be routed yet.** Format detection does not ask drivers to sniff their
own formats — step 4 of the detection ladder is deferred past 1.0. A driver for a format the host
does not already recognise installs correctly and passes conformance, but `ow add` will not route
files to it. If your format is one the host detects, everything works today.

**A worker inherits no `PYTHONPATH`, by design.** Running the kit with `PYTHONPATH=src` is fine, but
ingesting through `ow add` needs the driver *installed in the environment*. This is deliberate: a
worker that picked up code from an ambient path would make the set of loaded drivers depend on how
the process was launched.

## One packaging habit worth copying

```toml
dependencies = ["pypdfium2>=4.30,!=4.30.1"]
```

A specific known-bad release excluded by exact version is more honest than a raised floor, because
a floor also forbids the releases *below* the bad one that were fine. Adopted deliberately from
docling.
