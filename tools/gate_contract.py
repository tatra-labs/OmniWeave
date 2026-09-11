"""G16 — the previous two releases' conformance-template drivers load against HEAD.

`CONTRACT` is *"the driver/target ABI — the only version a third party pins"*
(`11-repo-layout.md:1036`), and the promise attached to it is a number rather than a sentiment:
`04-driver-system.md:1511` — *"**G16** loads the previous **two** releases' conformance-template
drivers against HEAD, so the window in which a third-party driver keeps working without a rebuild is
two minor releases — stated as a number so an author can plan."* `11-repo-layout.md:1124` says what
happens when it does not: *"a failure blocks the merge"*.

**Vacuous at P3, and it must say so out loud.** `16-roadmap.md:516` spells the exit line
`uv run tools/gate_contract.py --releases 2   # G16 (vacuous at P3; wired for later)`. This
repository has no `v*` tag, so there is nothing to load and the gate exits 0. A gate that is
indistinguishable from a gate nobody wired up is worthless, so the vacuous run prints the tag glob
it searched, the count it found, the count it wanted, and the steps it would have taken. The exit
code is the same; the output is not.

**It must not reach the network, and the mechanism is the reason** (`11-repo-layout.md:1130`):

> Building "the previous two releases' template drivers" from PyPI would put an index fetch on the
> PR path, would fail on a fork PR with a restricted token, and would let a yanked release break an
> unrelated merge. G16 instead adds a `git worktree` at each of the last two tags, builds
> `omniweave-conform` from source there with `uv build --package omniweave-conform`, scaffolds the
> template driver from that checkout's own `ow drivers scaffold`, and loads the result against HEAD.

Every clause of that is implemented here except one, and the exception is recorded rather than
papered over: **`ow drivers scaffold` does not exist.** `tools/ow_drivers.py` implements exactly the
four verbs W3.1 carries — `list`, `check`, `verify`, `explain` — and `scaffold` is a fifth named at
five plan sites that no roadmap cell carries. The substitute is exact rather than approximate: the
conformance-template driver ships as package data inside `omniweave-conform`
(`template/driver.toml`, `template/driver.py`, `template/fixtures/`), so the built wheel already
*contains* the artefact `scaffold` would have emitted, at that release's version of it. Ledger D130
is the entry. Nothing is downloaded either way.

**What "loads against HEAD" means, precisely.** Three things are separated on purpose, because they
fail for different reasons and a merge blocked by one wants a different fix from a merge blocked by
another:

1. **the card still parses** — HEAD's `load_card()` accepts the old release's `driver.toml`. This is
   the `card_schema` half: a new required key, a narrowed accepted `card_schema`, or a changed
   meaning shows up here. `04:1499`'s table calls a key added inside `[capability.<port>]` *"the
   safe asymmetry"* — older cores ignore it and record `CARD_CAPABILITY_UNKNOWN` — so degradations
   are reported for the record and are not themselves a failure.
2. **the class still activates** — HEAD's `activate()` imports the old entrypoint and its `PORT` and
   `SCHEMA_VERSION` assertions still hold. This is the Python-ABI half, and it is the clause that
   catches a rename in `omniweave_ports`, which `contract.py:73` lists first among the things that
   move `CONTRACT`.
3. **the old release's `CONTRACT` is still supported** — the tagged `contract.py`'s `CONTRACT` is in
   HEAD's `CONTRACTS_SUPPORTED`. Read out of the tagged source as TEXT, because two builds of
   `omniweave_core` cannot be imported into one interpreter and the gate has to hold both numbers at
   once. Same discipline as `gate_vendor.py`'s `_core_limits()`.

**`--repo` exists so the mechanism is testable before there is a tag**, and that is not a
convenience. Everything above is dead code in this repository until the first release, and a gate
whose real path has never executed is written rather than wired — which is exactly the state
`16-roadmap.md:516` is trying to avoid by asking for it at P3 at all. The gate's own test clones
this repository into `tmp_path` (locally, no network), tags two commits, and runs the whole
worktree-build-load path against them.

Exit 0 clean or vacuous, 1 with one `G16 FAIL` block per finding, 2 when the gate could not run.
Specified in 11-repo-layout.md sections 4.1 and 4.4, 04-driver-system.md section 5.2,
02-architecture.md section 2 row 2, and 16-roadmap.md section 6's P3 exit criteria.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess  # noqa: TID251 -- G16 IS `git worktree` plus `uv build` plus a fresh interpreter.
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "CARD_RELATIVE",
    "CONTRACT_RELATIVE",
    "DEFAULT_GLOB",
    "Finding",
    "Release",
    "check_release",
    "find_tags",
    "main",
    "prepare",
    "tagged_contract",
]

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_GLOB = "v*"
"""`11-repo-layout.md` section 4.2 tags a release `v<RELEASE>`. The glob is a flag because a fork
with a different tag convention should be able to run its own gate rather than skip it."""

CARD_RELATIVE = Path("omniweave_conform/template/driver.toml")
"""Where the template card sits inside the built wheel — which is where `ow drivers scaffold` would
have written it, at that release's version of it. See the module docstring and ledger D130."""

CONTRACT_RELATIVE = Path("packages/omniweave-core/src/omniweave_core/contract.py")
"""Read as TEXT out of the worktree. Two `omniweave_core` builds cannot both be imported."""

_CONTRACT_RE = re.compile(r"^CONTRACT\s*:\s*int\s*=\s*(\d+)", re.MULTILINE)

PROBE = '''"""G16's probe: one tagged template driver, loaded against HEAD's core.

One argument, the path to the tagged release's `driver.toml`. Everything imported here is HEAD's --
`omniweave_core` comes from the interpreter's own environment -- while the module the card names
comes from the extracted wheel, which is first on `PYTHONPATH`. That asymmetry IS the gate.
"""

import json
import sys

card_path = sys.argv[1]

from omniweave_core.contract import CONTRACT, CONTRACTS_SUPPORTED
from omniweave_core.drivers.card import load_card
from omniweave_core.host.activate import activate

out = {
    "ok": False,
    "stage": "read",
    "error": "",
    "id": "",
    "loaded": "",
    "degradations": [],
    "head_contract": CONTRACT,
    "contracts_supported": sorted(CONTRACTS_SUPPORTED),
}
try:
    with open(card_path, "rb") as handle:
        raw = handle.read()
    out["stage"] = "load_card"
    card = load_card(raw, origin="entry_point", source=card_path)
    identity = getattr(card, "identity", None)
    out["id"] = getattr(identity, "id", "") if identity is not None else getattr(card, "id", "")
    out["degradations"] = [str(getattr(note, "kind", note)) for note in
                           getattr(card, "degradations", ())]
    out["stage"] = "activate"
    out["loaded"] = activate(card).__name__
    out["ok"] = True
except BaseException as exc:  # a third-party module body may raise anything at all.
    out["error"] = "%s: %s" % (type(exc).__name__, exc)

sys.stdout.write(json.dumps(out))
'''


@dataclass(frozen=True, slots=True)
class Finding:
    """One violation: which release, which of the three clauses, and what is wrong."""

    tag: str
    clause: str
    message: str

    def block(self) -> str:
        return f"G16 FAIL  {self.tag}  [{self.clause}]\n          {self.message}"


@dataclass(frozen=True, slots=True)
class Release:
    """One tagged release, built and unpacked, ready to be loaded against HEAD."""

    tag: str
    worktree: Path
    site: Path
    """The extracted wheel. Goes first on `PYTHONPATH`, so the tagged `omniweave_conform` wins over
    the one this workspace has installed while `omniweave_core` stays HEAD's."""
    contract: int | None
    notes: list[str] = field(default_factory=list)


def emit(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def _tool(name: str) -> str:
    """`git` or `uv`, resolved on PATH so `argv[0]` is absolute.

    The same discipline `gate_core_pure.py:443` applies to `uv`: a bare name is resolved by the OS
    against a PATH this process does not control, and on Windows against the current directory
    first. `main()` checks both tools before any work starts, so the fallback never runs in
    practice — it exists so this helper has no failure mode of its own.
    """
    return shutil.which(name) or name


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- a fixed argv, no shell, absolute argv[0].
        [_tool("git"), "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def find_tags(repo: Path, glob: str, count: int) -> list[str]:
    """The `count` most recent release tags, newest first.

    `--sort=-v:refname` is git's own semver-aware ordering, so `v0.10.0` sorts above `v0.9.0` —
    which lexicographic ordering gets backwards, and which is the kind of bug that would silently
    test the wrong two releases rather than fail.
    """
    result = _git(repo, "tag", "--list", glob, "--sort=-v:refname")
    if result.returncode != 0:
        return []
    tags = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return tags[:count]


def tagged_contract(worktree: Path) -> int | None:
    """That release's `CONTRACT`, read as text from its own `contract.py`."""
    path = worktree / CONTRACT_RELATIVE
    try:
        match = _CONTRACT_RE.search(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return int(match.group(1)) if match else None


def prepare(repo: Path, tag: str, scratch: Path, *, offline: bool) -> Release | Finding:
    """`git worktree add` at `tag`, `uv build --package omniweave-conform`, unzip the wheel.

    No network for the artefact: the tag is already in the clone, which is why `tools/gates.toml`
    gives this row `fetch_depth = 0` and the `conform` job checks out at full depth. `uv build`
    still resolves its own build backend from the uv cache; `--offline` forces even that to be a
    cache hit, and is off by default because a cold cache should make this gate slow rather than
    red.
    """
    worktree = scratch / "tree" / tag.replace("/", "_")
    added = _git(repo, "worktree", "add", "--detach", str(worktree), tag)
    if added.returncode != 0:
        return Finding(tag, "worktree", f"git worktree add failed: {added.stderr.strip()[:300]}")

    dist = scratch / "dist" / tag.replace("/", "_")
    command = [_tool("uv"), "build", "--package", "omniweave-conform", "--wheel", "-o", str(dist)]
    if offline:
        command.append("--offline")
    built = subprocess.run(  # noqa: S603 -- a fixed argv, no shell.
        command, cwd=worktree, capture_output=True, text=True, check=False, timeout=600
    )
    if built.returncode != 0:
        return Finding(
            tag,
            "build",
            f"uv build --package omniweave-conform failed in the {tag} worktree: "
            f"{(built.stderr or built.stdout).strip()[-300:]}",
        )
    wheels = sorted(dist.glob("omniweave_conform-*.whl"))
    if not wheels:
        return Finding(tag, "build", f"no wheel in {dist}; uv reported success")

    site = scratch / "site" / tag.replace("/", "_")
    with zipfile.ZipFile(wheels[-1]) as archive:
        # Our own wheel, built from our own tag, this run: there is no untrusted member here.
        archive.extractall(site)
    return Release(tag=tag, worktree=worktree, site=site, contract=tagged_contract(worktree))


def check_release(release: Release, *, python: str | None = None) -> list[Finding]:
    """The three clauses, over one built release."""
    card = release.site / CARD_RELATIVE
    if not card.is_file():
        return [
            Finding(
                release.tag,
                "card",
                f"the {release.tag} wheel carries no {CARD_RELATIVE.as_posix()}. Either the "
                f"template moved or that release shipped without one; G16 cannot ask its question "
                f"without the artefact",
            )
        ]

    probe = release.site.parent / f"probe_{release.tag.replace('/', '_')}.py"
    probe.write_text(PROBE, encoding="utf-8")
    import os  # noqa: PLC0415 -- one env copy, at the one site that needs it.

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(release.site), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(  # noqa: S603 -- `sys.executable` and a file just written.
        [python or sys.executable, str(probe), str(card)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
        env=env,
    )
    try:
        seen = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [
            Finding(
                release.tag,
                "card",
                f"the probe printed no JSON (exit {proc.returncode}); HEAD's core could not even "
                f"be asked. stderr:\n          "
                + "\n          ".join(proc.stderr.strip().splitlines()[-6:] or ["<empty>"]),
            )
        ]

    findings: list[Finding] = []
    if not seen["ok"]:
        clause = "card" if seen["stage"] in {"read", "load_card"} else "activate"
        findings.append(
            Finding(
                release.tag,
                clause,
                f"{release.tag}'s template driver does not load against HEAD, at stage "
                f"{seen['stage']!r}: {seen['error']}. A third party's driver from this release "
                f"needs a rebuild, which is a CONTRACT break and an announced product event "
                f"(04-driver-system.md:1511)",
            )
        )
    else:
        release.notes.append(f"{seen['id']} -> {seen['loaded']}")
        if seen["degradations"]:
            # NOT a failure. 04:1499 calls an unknown key inside `[capability.<port>]` "the safe
            # asymmetry": an older core ignores it and records CARD_CAPABILITY_UNKNOWN, because
            # every key there is a floor and an unrecognised one can only make the driver look
            # less capable. Recorded so the report shows the direction of drift.
            release.notes.append(f"degradations: {', '.join(sorted(set(seen['degradations'])))}")

    supported = set(seen["contracts_supported"])
    if release.contract is None:
        findings.append(
            Finding(
                release.tag,
                "contract",
                f"could not read CONTRACT from {CONTRACT_RELATIVE.as_posix()} in the {release.tag} "
                f"worktree; the two numbers this clause compares are not both available",
            )
        )
    elif release.contract not in supported:
        findings.append(
            Finding(
                release.tag,
                "contract",
                f"{release.tag} declares CONTRACT = {release.contract} and HEAD supports "
                f"{sorted(supported)}. Dropping a major from CONTRACTS_SUPPORTED ends the "
                f"two-release window for every driver built against it",
            )
        )
    return findings


def cleanup(repo: Path, worktree: Path) -> None:
    """Remove the worktree and prune the repository's record of it.

    The worktree lives under a `TemporaryDirectory` that is about to vanish, but git keeps its own
    administrative entry under `.git/worktrees/` and a gate that left one behind every run would
    slowly fill the repository it is guarding.
    """
    _git(repo, "worktree", "remove", "--force", str(worktree))
    _git(repo, "worktree", "prune")


def _vacuous(glob: str, found: list[str], wanted: int) -> int:
    """Report a vacuous run in a way nobody can mistake for a wired one.

    16-roadmap.md:516 marks G16 "vacuous at P3; wired for later", so exit 0 is correct and silence
    is not: a gate whose output is indistinguishable from a gate nobody connected is a gate nobody
    will notice has stopped running.
    """
    emit(f"G16 vacuous  {len(found)} release tag(s) matching {glob!r}, {wanted} wanted.")
    if found:
        emit(f"             found: {', '.join(found)}")
    emit("             With enough tags this would, per release:")
    emit("               1. git worktree add --detach <tmp> <tag>        (no network; the tag is")
    emit("                  already in the clone, which is why this row carries fetch_depth = 0)")
    emit("               2. uv build --package omniweave-conform   (from source, in the tree)")
    emit("               3. load that wheel's template driver.toml with HEAD's load_card(),")
    emit("                  activate() it with HEAD's core, and check that release's CONTRACT")
    emit("                  against HEAD's CONTRACTS_SUPPORTED")
    emit("             See 11-repo-layout.md:1130 and 04-driver-system.md:1511.")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run G16. 0 clean or vacuous, 1 with one block per finding, 2 when it could not run."""
    parser = argparse.ArgumentParser(description="G16 — the last N releases load against HEAD.")
    parser.add_argument("--releases", type=int, default=2, help="how many tags back (default 2).")
    parser.add_argument("--repo", type=Path, default=ROOT, help="the repository to read tags from.")
    parser.add_argument("--tag-glob", default=DEFAULT_GLOB)
    parser.add_argument("--offline", action="store_true", help="force `uv build --offline`.")
    args = parser.parse_args(argv)

    if args.releases < 1:
        emit("usage: --releases must be at least 1")
        return 2
    for tool in ("git", "uv"):
        if shutil.which(tool) is None:
            emit(f"G16 CANNOT RUN  no `{tool}` on PATH; G16 is a worktree and a build.")
            return 2
    repo = args.repo.resolve()
    if not (repo / ".git").exists():
        emit(f"G16 ERROR  {repo} is not a git repository.")
        return 2

    tags = find_tags(repo, args.tag_glob, args.releases)
    if len(tags) < args.releases:
        return _vacuous(args.tag_glob, tags, args.releases)

    findings: list[Finding] = []
    loaded: list[Release] = []
    with tempfile.TemporaryDirectory(prefix="ow-g16-") as scratch:
        directory = Path(scratch)
        for tag in tags:
            prepared = prepare(repo, tag, directory, offline=args.offline)
            if isinstance(prepared, Finding):
                findings.append(prepared)
                continue
            try:
                findings.extend(check_release(prepared))
                loaded.append(prepared)
            finally:
                cleanup(repo, prepared.worktree)
        # The worktrees are gone; `shutil.rmtree` on Windows trips over the read-only objects git
        # leaves, and the TemporaryDirectory context is about to try. Best-effort, then let it.
        shutil.rmtree(directory / "tree", ignore_errors=True)

    if findings:
        for finding in findings:
            emit(finding.block())
            emit()
        emit(f"G16 FAIL  {len(findings)} finding(s) over {len(tags)} release(s).")
        return 1

    emit(f"G16 ok  {len(tags)} release(s) load against HEAD: {', '.join(tags)}.")
    for release in loaded:
        for note in release.notes:
            emit(f"        {release.tag}: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
