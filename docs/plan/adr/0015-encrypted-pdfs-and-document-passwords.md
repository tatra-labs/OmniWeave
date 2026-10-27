# ADR-15 — Encrypted PDFs and document passwords: a PDF that opens is read, one that does not is named, and a password has two sources and one route

**Status:** Accepted (2026-09-29, the maintainer's choice of "the plan plus usability fixes") · **Priority:** 15 of 15 · **Price:** 4.0 ed
**Deadline:** before Q-G7's `encrypt` Injector lands (13 §8.6). `degradation_detection` is a hard gate at 1.000 over the thirteen, and `encrypt` cannot pass its fourth clause, *"the `DegradeCause.fix` string is a command that ... produces an undamaged run"* (13:1297), while no command can supply a password.
**Discharges:** four statements the build could not implement as printed, re-verified against the current plan (Items 1-4). None is one of the fifty-two audit rows, so `charter_defects_open` does not move.
**Charter errata claimed:** none (block `E108`-`E113`, all six unused). The charter's `gate.encrypted` rule and its FREE `unit.encrypted` row stand as written.
**Supersedes:** none
**Blocks / unblocks:** unblocks the `encrypt` Injector (Q-G7's third) and the bench's two `encrypt` tasks (ADR-14 D14.2 part 4). D15.1, D15.2 and D15.6 landed with this ADR (ledger D642); D15.3 to D15.5 and the Injector in D643.

## Context

Q-G7's first two cells (ledger D640, D641) built gate 9's store read, `unit.corrupt`, and the `mask_format` and `chaos` Injectors. `encrypt` is the third, and the first whose plan text does not survive being built.

### Item 1 — 05:2239 refuses a PDF the build has always read

05:2239, the `unit.encrypted` row, verbatim in its false-positive column: *"a PDF with `/Encrypt` and an empty owner password is technically encrypted and practically readable, and would be refused. That is why `[ingest] password_file` accepts an empty secret"*.

- An owner-password-only PDF is the ordinary permission-restricted document: print or copy denied, and readable with no password. pdfium opens it, and the build has always parsed it.
- Built as printed, the trailer scan refuses every such file at `gate.encrypted` until its owner writes a password file mapping it to an empty secret. That is a regression for every existing user with one, repaired by configuration they have no reason to know exists.
- The same row already names the mechanism that avoids it: *"a successful open **recomputes the key as `false`**"*. The printed order puts the scan first and the open second; the scan alone never sees that the file opens.

### Item 2 — the password's source is one sentence, and it names no way to put a password there

05:472-474: *"`[ingest] password_file` points at a TOML file mapping a `unit_uri` glob to a secret *name*; the name resolves through the OS keystore, never through the file. `--password-file <path>` overrides it for one invocation."*

- It names no keystore: Windows' Credential Manager, macOS's Keychain and Linux's Secret Service are three APIs with three naming schemes.
- It names no way for a user to store the secret, and no `ow` verb does (10 and 18 list no `--password-file` and no secret command).
- A headless host, a container or a CI runner often has no keystore at all. 05:311 already gives a connector credential a second source, *"the OS keystore or an env var named by the card"*; a document password has none.

### Item 3 — "`DriverIO` config" is a field `DriverIO` does not have

05:474: *"The secret reaches the driver as `DriverIO` config"*. `omniweave_ports.types.DriverIO` has four fields, and its docstring is INV-6: *"NOT EXTENSIBLE: adding a field here amends the charter (INV-6), whose audit question is literally 'count `DriverIO`'s fields'"*. 14:1060 reads the same sentence more exactly: *"A document password reaches the driver as `DriverIO` config for one invocation, and the tmpdir is host-deleted."* The second clause is the mechanism the first does not name.

### Item 4 — the `encrypt` Injector's damage is one the build would read

13:1283: *"`encrypt` | `OW_ENCRYPTED` | applies owner-password encryption to n pages"*. Under Item 1's resolution an owner-password-only file is read, so this Injector would measure nothing: its counterfactual clause (D640) fails, as 13:1320 says an Injector whose gate passes vacuously *"tests nothing"*. And PDF encryption is a property of the document; there is no per-page key, so *"n pages"* has no form.

## Decision

**D15.1 — detection scans a PDF's trailer for `/Encrypt`, as 05:2239 specifies.** `route.detect.pdf_encrypted()` reads the last 4 KiB, where a classic trailer sits, and the same at the offset `startxref` names, where an XRef stream keeps its dictionary. It sets `Detection.encrypted` after the format is decided, because an encrypted PDF is still a PDF (an encrypted OOXML becomes `unknown` because its inner format is unknowable, 05:3034; that is not this case). The value is the builtin provider's `unit.encrypted`, and replaces the "not built" UNAVAILABLE the router recorded.

**D15.2 — for a PDF, `unit.encrypted` is whether pdfium opens it, and an owner-password-only PDF is read with no setup.**
- `omniweave_pdf/signals.toml` gains a `unit.encrypted` row, `serves = ["pdf"]`, whose per-key columns are the builtin row's (D199). Resolution then prefers it for a PDF, as it does `unit.part_count` (05:2135), and detection's scan is the fallback where the provider is not installed.
- The child that already opens the file for `unit.part_count` answers it: `false` when pdfium opens the bytes, `true` when pdfium refuses them for want of a password.
- The second is a **value**, not a raise. A raise refuses the whole group, which D579 holds for ever under gate 5; a document that needs a password is an answer.
- So `gate.encrypted` refuses exactly the PDFs that cannot be read without a password, and gate 9 names them `OW_ENCRYPTED`. The owner-password-only PDF is read as it always was.
- 05:2239's *"recomputes the key as `false`"*, applied at the first open, with the empty password.
- Cost: none. The child runs for `unit.part_count` anyway.

**D15.3 — a password has two sources, the OS keystore and an environment variable, and a secret name maps to both.** *(Built, D643; a glob may also be absolute, the form D15.5 prints.)*
- `[ingest] password_file` is 05:450's TOML, one glob per line relative to `roots.source` as `[ingest] include` is, mapping to a secret **name**, never a secret.
- A name resolves from `OW_SECRET_<NAME>` first (the name upper-cased, every other character `_`), then from the OS keystore:
  - Windows' Credential Manager: a generic credential with target `omniweave/<name>`;
  - macOS's Keychain: service `omniweave`, account `<name>`;
  - Linux's Secret Service: `service omniweave name <name>`.
- The environment is 05:311's second channel, given to a document password for the host with no keystore: a CI runner, a container, a server.
- An empty secret is a secret, as 05:2239 allows, though D15.2 makes it unnecessary for an owner-only file.
- `--password-file <path>` is on `ow ingest`, beside D641's `--accept-partial`, and not on `ow add`, whose MCP listing budget is frozen (V01-12).
- A failed `encrypted` unit is re-opened by the next run under a password mapping that matches it, as D641 re-opens a `corrupt_input` one under `--accept-partial`.

**D15.4 — the secret travels in the invocation's tmpdir, and nowhere else.** *(Built, D643.)*
- **To the driver:** the host writes it to a file in the one invocation's `DriverIO.tmpdir`, which the host deletes (14:1060), and the driver reads it there. `DriverIO` keeps its four fields (INV-6).
- **To the signal child:** it is a field of the request on the child's stdin, never argv and never environment.
- **Where it never is:** in `config_digest`, `options_digest`, the work row, the cache key, an event, a `Diag` or the run manifest (05:474-476).
- **A successful open with a password** records `Diag(OW_DOC_DECRYPTED)` and `doc.x.ow.decrypted = true` (05:476).

**D15.5 — the refusal says how to fix it on this machine.** *(Built, D643.)*
- Gate 9's detail for an `encrypted` unit prints the one command that stores a secret on this OS, the environment-variable alternative, and the `password_file` line that maps the file.
- Its `fix` is then the re-read, `ow add <path>`, as for D640's refusals; `ow add` queues the unchanged file once a line maps it (D643).
- **Until D15.3 landed** (D642 to D643), the detail said the build reads no password yet, and the `fix` was empty: 07:1989 allows that *"only where no command does"*.

**D15.6 — the `encrypt` Injector applies a user password to the whole document.**
- `omniweave_conform.pdfcrypt` writes ISO 32000-1 §7.6.3's standard security handler, revision 3, RC4-128, with nothing but `hashlib`. pypdfium2 writes no encryption, and pypdf and pikepdf are not dependencies.
- It encrypts every stream and every string, and refuses by name any PDF with an object stream or a cross-reference stream.
- 13:1283's *"owner-password encryption to n pages"* becomes *"user-password encryption to the document"*, for Item 4's two reasons.
- The owner-only form is kept as the proof of D15.2.

## Alternatives rejected

### D15.2: refuse at the scan, as printed, and let an empty secret unlock the file
The plan's own design. It turns every permission-restricted PDF a user already has into a gate 9 gap until they configure a password file they have no reason to know about, and it repairs a false positive the build can see is false: the child opens the file in the same group.

### D15.2: try the empty password in the host
Cheaper by one child, and wrong: pdfium is *"the largest memory-unsafe surface in the shipped set"* (14:466), and a file that is refused as encrypted is exactly the untrusted input the child exists to hold.

### D15.3: the OS keystore only
Literal, and a dead end on every machine without one, which is most CI runners and containers. The environment variable is the plan's own second channel for credentials (05:311).

### D15.3: an `ow secret set` verb
Friendlier, and a new CLI root that 10 does not have, writing to three keystores this build has not built readers for. The OS's own command, printed by D15.5, does the same with nothing new to secure.

### D15.4: a `password` field on `DriverIO`
The shortest route to the driver, and an amendment to INV-6, whose whole audit question is the field count.

## Consequences

| obligation | document and locus | price |
|---|---|---|
| D15.1: the trailer and XRef-stream scan | `omniweave/route/detect.py` | 0.3 ed |
| D15.2: the `pdfium` row and computer; routing's fallback | `omniweave_pdf/signals.py`, `signals.toml`; `omniweave/run/routing.py` | 0.4 ed |
| D15.6: the encryptor | `omniweave_conform/pdfcrypt.py` | 0.5 ed |
| D15.3: the password file, the two sources, `--password-file`, the re-open | `omniweave/run/`, `omniweave/surface/ingest.py` | 1.2 ed |
| D15.4: the tmpdir route, the stdin field, `OW_DOC_DECRYPTED`, `doc.x.ow.decrypted` | `omniweave_core/host/`, `omniweave_pdf/driver.py`, `codes.toml` | 0.8 ed |
| D15.5: the refusal's store commands | `omniweave_core/store/reader.py` | 0.2 ed |
| the `encrypt` Injector, its fixtures, the bench's two tasks | `omniweave_conform/damage.py`, `tools/ow_damage.py`, `bench/serve/` | 0.4 ed |
| 05's provider column, :2239's false-positive cell, :472-477's pointer, :3031; 13:1283 | [05](../05-ingest-and-routing.md), [13](../13-quality.md) | 0.1 ed |
| the index row | this directory's README | 0.1 ed |
| **total** | | **4.0 ed** |

All plan edits keep their line counts, as ADR-13's and ADR-14's did.

**What becomes harder.**
- **A PDF's `unit.encrypted` needs the pdfium child.** Where `omniweave-pdf` is not installed, the scan decides, and an owner-only PDF is refused, as 05:2239 printed. That install has no PDF driver to read it with anyway.
- **Two secret sources are two places to look.** The environment wins, so a stale `OW_SECRET_*` shadows a keystore entry. D15.5's message names both.

**What a future reader must not do.**
- Must not put a password, or anything derived from one, into a digest, a key, a row, an event, a `Diag` or a manifest.
- Must not add a field to `DriverIO` to carry one.
- Must not refuse a PDF at the scan alone when the pdfium provider is installed to open it.

## Open

**Whether AES handlers need their own Injector fixture.** Revision 4 to 6 (AES-128 and AES-256) are what current producers write. pdfium opens them, and D15.2 asks pdfium, so the build handles them. The encryptor writes revision 3 because the standard library has no AES.
- **Closes:** a real AES-encrypted fixture among Tier A's public-domain documents.
- **Fallback:** revision 3 exercises the same path, the one question pdfium answers.
