"""The twelve conformance suites, the driver testkit, and the reference target's home.

02-architecture.md section 2 row 47 and 13-quality.md give this distribution its contents:
"the twelve suites, the testkit, the eval harness, the reducers, the Cassette codec, the
calibrator, the scoreboard generator, and the reference target `compile.text.owtext`"
(11-repo-layout.md:123). W3.6 (16-roadmap.md:486) delivers the first three of those plus
`ow conform`, the conformance-template driver and the `Attestation`; the eval harness, the
reducers and the scoreboard generator are 13's `ow eval` group at P10, and
`compile.text.owtext` needs `CompileV1`, which lives in `omniweave_core.out.compile` and
arrives at P5 (04-driver-system.md:379-383).

## The public surface, and the order to read it in

* `Subject` -- one card, its fixtures and a workdir. Built once, shared by all twelve.
* `run` -- the twelve in `SUITES` order, returning a `ConformReport`.
* `badge` / `sentence` -- the two strings a passing run entitles an author to, generated.
* `publish.check` / `publish.write_results` -- DR13's gate and the one writer of the three
  kit-written regions of a card.
* `harness` -- the testkit's engine: a `BlobStore`, a `DriverIO`, a fixture, a fragment reader.

`omniweave_conform.testkit` is `T-PUBLIC` (18-api-sketch.md:3134) and a driver author
dev-depends on this distribution; nothing here may be imported by `omniweave` itself
(11-repo-layout.md:614-618 -- there is deliberately no `omniweave[conform]` extra, because that
is exactly how test-only weight lands in a production install).

## `import omniweave_conform` imports no driver

Nothing in this module's import graph calls `importlib.import_module`, and it may not:
`tools/semgrep/omniweave.yaml`'s `omniweave-no-import-module-outside-host` covers
`packages/*/src/**`. The one sanctioned importer is `omniweave_core.host.activate.activate`,
which `Subject.activate()` delegates to -- and `card` and `purity`, the first two suites, never
call it. That ordering is what makes `purity`'s claim observable at all.
"""

from omniweave_conform.badge import badge, kit_version, sentence
from omniweave_conform.result import (
    MANDATORY,
    SUITES,
    Assertion,
    ConformReport,
    SuiteResult,
    Verdict,
)
from omniweave_conform.runner import report_lines, run, verdict_line
from omniweave_conform.subject import Subject

__all__ = [
    "MANDATORY",
    "SUITES",
    "Assertion",
    "ConformReport",
    "Subject",
    "SuiteResult",
    "Verdict",
    "badge",
    "kit_version",
    "report_lines",
    "run",
    "sentence",
    "verdict_line",
]
