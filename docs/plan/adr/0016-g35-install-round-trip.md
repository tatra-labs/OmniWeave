# ADR-16 — G35: `ow install` then `ow uninstall` is byte-identical, and the receipt proves every write

**Status:** Accepted (2026-10-23, the maintainer's approval of Claude's draft, a user ruling of that day). Drafted under item 12 of the first set of rulings; D971 makes the gate law, adds §6.4's row and moves the four printed counts from twenty-nine to thirty (11:12, 11:397, 11:1537 and 00:596) · **Priority:** 16 · **Price:** 0.5 ed
**Deadline:** before the v1.0 tag. V10-15 (00:738) asks that `ow install` record every written path with its post-write sha256 in an install receipt, and that `ow uninstall` restore byte-identity; and `tools/acceptance_v10.py` reads G35 as its instrument.
**Discharges:** `tools/gates.toml`'s G35 `pending` text: *"an ADR allocating the number (section 8.7 'add a gate') and a row in section 6.4's table"*.
**Charter errata claimed:** none.
**Supersedes:** none
**Blocks / unblocks:** turns G35 from `registered` into `law`; V10-15's remaining gap.

## Context

11 §8.7 sets the price of a gate: *"an ADR — not because a count is quoted anywhere, but because a `G<n>` is a numbered promise a document may cite — then a `tools/gate_*.py`, a row in `tools/gates.toml` with an owner and a review date, a row in §6.4's table, and a fixture that fails without it"*.

Everything but the ADR and the table row exists:

- **The promise is already in the plan.** 10:1775 names the gate *G-install*, and 16:719 makes it W7.5's exit.
- **The runner is `tools/gate_install.py`** (D920). Over a fixture home, for every built host, it runs `ow install`, then `ow uninstall`. Every file must come back byte-identical, and every path the install wrote must have a receipt row whose newest `sha256_after` matches its bytes.
- **The register row** has an owner (`surface`), a review date and a 120 s budget. The module runs in 5-9 s on Linux, macOS and the build machine, and 43-51 s on hosted Windows (#178).
- **The job.** The `test` job runs it on all nine cells.
- **Fixtures that fail without it:** `test_install_receipt.py`, `test_install_verbs.py` and the conform half `test_install_verbs_process.py`.

The number G35 was taken in sequence after G34. No document cites a different meaning for it.

## Decision

**D16.1 — G35 is allocated to the install round trip, and its assertion is the register's.** *"`ow install` then `ow uninstall` leaves every built host's files byte-identical, and the receipt names every written path with its post-write sha256."*

**D16.2 — it runs in the `test` job, on every cell, blocking on every PR, nightly and at release.** The 120 s budget stays. An install writes into host-specific config paths, and the hosts differ by OS. A Linux-only gate would leave the two OSes where `%APPDATA%` and `~/Library` live untested.

**D16.3 — the fixture home is the measurement, and a real host's config is never touched.** The gate runs `ow install` with `HOME` and `USERPROFILE` pointed at a temporary directory. This is the only safe way a CI runner can exercise a write into a person's agent configuration. V10-15's note says *"never a real host's config"*, and this ADR makes that the gate's definition, not its gap.

**D16.4 — §6.4's table gains G35's row** (11-repo-layout.md, appended under the no-insert rule as a build note on the table's last row):

| G35 `ow install` then `ow uninstall` is byte-identical; the receipt names every written path with its post-write sha256 | `test` (every cell) | 120 | — | yes |

## Consequences

- `tools/gates.toml`'s G35 moves to `status = "law"` and drops `pending`, once the maintainer approves this ADR.
- V10-15's row in `tools/acceptance_v10.py` loses the "registered and not law" clause. What remains of its gap is D16.3's scoping, which then reads as the definition.
- G30-G34 are also `registered` without §6.4 rows. Each needs its own ADR, and this one does not decide them.
