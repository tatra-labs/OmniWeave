# The condition that creates an npm package

omniweave publishes no npm package. `ow surface typescript` **generates** a TypeScript client from
the gated schemas, and a generator is not a release rota: nothing in this repository consumes that
output, so there is no version to bump, no changelog to write and no deprecation window to honour.

This file exists so that the absence is a decision with a condition attached, rather than an
omission someone re-argues from scratch. It is named by the charter §D9 and specified by
[the repository layout](plan/11-repo-layout.md) §3.5.

## The trigger

An npm package is created when **either** of these becomes true:

1. **A first non-toolchain in-tree TypeScript consumer.** Code under `toolchains/` does not count:
   it is the build-time TypeScript the deck target needs, it is not a Python dependency, and it
   consumes no omniweave API. A TypeScript consumer anywhere else in this repository would be
   importing the generated client, and a client two trees depend on is a package.
2. **Three external requests.** Three, and not one, because one request is answered by pointing at
   `ow surface typescript`; three is a pattern that generating-on-demand is not serving.

Either condition is sufficient. Neither is a judgement call about momentum.

## What happens when it fires

The package is a published artefact of this repository, so it joins everything that follows from
that, and none of it is optional:

- a release rota and a version, which means `CONTRACT`-style compatibility promises for a second
  ecosystem;
- `pnpm` is already the package manager and `pnpm-lock.yaml` is already committed (§3.1), so the
  tooling exists; the cost is the rota, not the plumbing;
- the generated client stays generated. A hand-edited TypeScript SDK would be a second
  specification of the same surface, which is the duplication [the interfaces
  document](plan/10-interfaces.md) refuses everywhere else.

## What this is not

It is not a statement that TypeScript consumers are unsupported. `ow surface typescript` is a
shipped verb, its output is generated from the same gated schemas the Python SDK is, and a consumer
who runs it gets a client that cannot drift from the server. What they do not get is a version
number maintained by this project.

The two other deliberate non-publications — crates.io and platform-tagged wheels — are recorded in
§3.5 beside this one, each with its own trigger. Only this one needed a file of its own, because
the charter named it.
