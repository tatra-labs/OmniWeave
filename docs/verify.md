# Verifying an omniweave release

Four recipes, and one paragraph of honesty about what they prove.

Specified by [the repository layout](plan/11-repo-layout.md) §7.5. Checklist step 15 runs all four
from a clean machine against the published wheel, which is the only run that catches a recipe that
has stopped working before a user does.

Throughout, `RELEASE` is the version without its leading `v` — `0.1.0` for tag `v0.1.0` — and the
repository is `tatra-labs/OmniWeave`. Both appear verbatim in each recipe rather than as shell
variables, because a recipe a reader has to assemble is a recipe a reader gets wrong.

## 1. A wheel's build provenance

```bash
gh attestation verify omniweave_core-0.1.0-py3-none-any.whl --repo tatra-labs/OmniWeave
```

This is the GitHub build attestation: the wheel was built by a workflow in this repository, at a
commit this repository contains.

## 2. The SLSA provenance for the whole release

```bash
slsa-verifier verify-artifact omniweave_core-0.1.0-py3-none-any.whl \
  --provenance-path provenance.intoto.jsonl \
  --source-uri github.com/tatra-labs/OmniWeave --source-tag v0.1.0
```

`provenance.intoto.jsonl` covers **all 28 release files** as its subjects — fourteen sdists and
fourteen wheels, every wheel `py3-none-any` — so one statement verifies any of them. Pass whichever
artefact you downloaded.

`slsa-verifier` is the one tool here you may not have; `uvx slsa-verifier` runs it without
installing it.

## 3. An SBOM, or the first-party manifest

```bash
cosign verify-blob --bundle sbom-spdx.json.bundle \
  --certificate-identity-regexp '^https://github\.com/tatra-labs/OmniWeave/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  sbom-spdx.json
```

The same recipe verifies a different blob: there are **six SBOMs** (two formats × three install
profiles) and the signed first-party manifest asset, each with its own `.bundle`. Substitute the
blob and its bundle; the two certificate flags do not change.

The identity is a *regexp against the signing workflow's identity*, which is why it ends in a
slash: it matches any workflow in this repository and not a repository whose name merely starts the
same way. Omitting `--certificate-identity-regexp` or `--certificate-oidc-issuer` makes `cosign`
accept **any** valid Sigstore signature, which verifies that someone signed something.

## 4. The in-wheel first-party manifest against the signed asset

```bash
python -c "import importlib.resources as r, sys; \
  sys.stdout.write(r.files('omniweave_core.drivers').joinpath('first_party.toml').read_text())" \
  | python tools/manifest_diff.py first-party-0.1.0.json -
```

[The driver system](plan/04-driver-system.md) §4.2 computes a driver's trust as `first_party` when
its distribution name is in the release manifest's list **and** its `dist_sha256` matches. That
manifest ships inside the `omniweave-core` wheel, and a manifest carried by the artefact it
describes is not evidence on its own — so it is also published as a `cosign sign-blob`ed asset, and
this recipe compares the two.

`tools/manifest_diff.py` imports only the standard library and takes `-` for stdin, so it runs from
a source checkout or copied beside the two files, with no omniweave installed. A verifier you have
to install from the thing under audit verifies nothing. Exit `0` means they agree, `1` prints every
difference with the signed value first, and `2` means a file could not be read — so a broken recipe
does not read as a bad artefact.

Recipe 4 reads through `importlib.resources` rather than `__path__[0]` for the reason §2.6 gives:
it has to work against whatever layout you installed into, and a path-based read fails on exactly
the installs an auditor is most likely to be inspecting.

**`omniweave-core` has no row in either manifest, and that is the correct answer rather than a
gap.** Core is the module that computes the trust tier, so a row asserting core's own hash would be
a witness testifying to itself. Core's integrity is covered by recipes 1 and 2, which are claims by
the build system instead.

## What these prove, and what they do not

All four prove one thing: **a first-party artefact was built from this repository, at this commit,
by this workflow.**

They prove nothing about a **third-party driver**. A driver's `Attestation` is a hash over its own
card, computed by its own kit run, so an author can run the conformance kit on a clean build and
ship a different wheel carrying the same card. Only `dist_sha256` in `omniweave.lock` catches that,
and only for consumers who installed through an index ([the driver
system](plan/04-driver-system.md) §5.5). This document says so rather than implying a signature.

A developer's checkout has no `first_party.toml` at all — it is generated into `src/` at build time
and git-ignored — so `compute_trust` returns `unpinned` with a `Degradation(kind="pin")` there.
That is the designed answer for an editable install, which has no wheel and therefore no digest to
attest, and recipe 4 has nothing to compare against it.

## Before the first release

Two things in the tree still have to be reconciled, and both are named here rather than left for
whoever runs the checklist to discover:

- **`release.yml`'s `sbom-sign` job exits 1 at the SBOM generation step, deliberately.** The
  workflow's own header states it: the file cannot complete a release today, because
  [the roadmap](plan/16-roadmap.md)'s W10.9 — release engineering — is the item that turns the
  marked steps into commands, and it is not built. Until it is, recipe 3 has no blob to verify for
  a release cut from this tree.
- **The repository slug disagrees with itself.** `release.yml:316` pins the cosign identity regexp
  to `^https://github\.com/omniweave/omniweave/`, and §7.6's step 0 binds the PyPI pending
  publisher to `omniweave/omniweave`, while this repository is `tatra-labs/OmniWeave` and the
  generated `llms.txt` already says so. The recipes above use the real one. A signature issued by
  this repository will not match the regexp the workflow verifies with, so the two sites must agree
  before a tag is pushed — whichever slug wins.
