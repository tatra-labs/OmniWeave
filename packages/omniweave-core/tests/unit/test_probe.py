"""`env_digest`, the verdict cache and the three-row TTL table of 04-driver-system.md section 4.7.

Four properties carry this suite, and each one is a way the cache can serve a wrong answer rather
than merely a missing one:

* **the digest covers identities, not presences.** The whole reason `_ident` exists is that a bare
  `which()` path and a `find_library(...) is not None` bool both survive the upgrade they are meant
  to catch, so the tests move a binary's `st_size`, its `st_mtime_ns` and its `realpath`
  independently and assert the digest moves for each -- and that an unrelated environment variable
  moves nothing.
* **a torn row is impossible.** The write is an atomic replace from a same-directory temporary, so
  a write that fails mid-flight leaves the previous row whole and leaves no temporary behind, and
  two processes writing an equal verdict converge on equal bytes.
* **each TTL row.** `ok`/`degraded` outlive any clock; `unavailable` is re-probed after
  `PROBE_TTL_S`; a timeout is an `unavailable` and inherits that row rather than getting one of its
  own.
* **DR21.** A missing capability is a verdict with a machine-actionable `missing`, never a raise.

The three probe shapes are 16-roadmap.md W1.6's estimation basis, each **a real operation and not
an import**: a tesseract missing its language pack, a CUDA torch that fails on first kernel launch,
and an Ollama client with no model pulled. They appear here as the fixtures the TTL rows are
exercised over, because the row a verdict lands in is the whole of what this module decides.

The clock is injected everywhere: `time.time()` is banned in library code (G8), and the
`unavailable`-is-re-probed-after-600-s behaviour is untestable against a clock the module reads
itself.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: TID251 -- PYTHONHASHSEED is only observable in a fresh interpreter
import sys
from pathlib import Path

import pytest
from omniweave_core.drivers.card import Capability, DriverCard, DriverIdentity, Hardware
from omniweave_core.errors import ConfigError
from omniweave_core.probe import (
    CACHED_FOR_LIFE_OF_DIGEST,
    PROBE_CACHE_DIRNAME,
    PROBE_EPOCH_ENV,
    PROBE_ROW_SCHEMA,
    PROBE_TTL_S,
    ProbeCache,
    ProbeKey,
    cached_probe,
    env_digest,
    is_fresh,
    key_for,
    probe_cache_root,
    probe_env,
    timeout_verdict,
)
from omniweave_ports.types import ProbeStatus, ProbeVerdict

DIGEST_A = "sha256:" + "ab" * 32
DIGEST_B = "sha256:" + "cd" * 32
ENV_A = "11" * 32
ENV_B = "22" * 32

NO_ENV: dict[str, str] = {}


def _key(**overrides: str) -> ProbeKey:
    """A valid key; every field is overridable so a test can move exactly one component."""
    fields = {
        "driver_id": "parse.pdf.native",
        "driver_version": "1.4.2",
        "card_sha256": DIGEST_A,
        "env_digest": ENV_A,
    }
    fields.update(overrides)
    return ProbeKey(**fields)  # type: ignore[arg-type]


def _absent(_name: str) -> str | None:
    """A `which` that finds nothing -- the P1 default on a machine with no declared binaries."""
    return None


# ---------------------------------------------------------------------------
# The three probe shapes of 16-roadmap.md W1.6, each a real operation and not an import.
# ---------------------------------------------------------------------------

TESSERACT_NO_LANGPACK = ProbeVerdict(
    status=ProbeStatus.UNAVAILABLE,
    detail="tesseract 5.3.4 is installed but has no 'deu' traineddata",
    missing=("tesseract-lang:deu",),
    fix_hint="apt install tesseract-ocr-deu",
)
"""Shape one. `shutil.which("tesseract")` succeeds and the binary runs; the *capability* is absent.

This is the verdict `PROBE_TTL_S` exists for: `apt install tesseract-ocr-deu` moves no component of
`env_digest` -- not the `which()` path, not the binary's size or mtime, not `libcuda`, not the
platform -- so caching it for the life of the digest would make the fix have no effect until the
next release. `missing` is the machine-actionable form DR21 requires.
"""

TORCH_KERNEL_LAUNCH_FAILS = ProbeVerdict(
    status=ProbeStatus.DEGRADED,
    detail="cuda is present but the first kernel launch returned CUDA_ERROR_NO_BINARY_FOR_GPU",
    capabilities_lost=("gpu_batch", "fp16"),
)
"""Shape two. `import torch` succeeds and `torch.cuda.is_available()` is `True`; the first real
kernel launch is what fails, which is why a probe is an operation and never an import.

`degraded`, so `capabilities_lost` lets the router re-filter rather than guess, and it is cached for
the life of the `env_digest` -- the condition is a driver/toolkit mismatch, and fixing it moves
`libcuda`'s identity, which moves the digest, which moves the path.
"""

OLLAMA_NO_MODEL = ProbeVerdict(
    status=ProbeStatus.UNAVAILABLE,
    detail="the ollama endpoint answered but holds no model tagged 'nomic-embed-text'",
    missing=("ollama-model:nomic-embed-text",),
    fix_hint="ollama pull nomic-embed-text",
)
"""Shape three. The client constructs and the endpoint answers; the model is not pulled. Another
`unavailable` a user fixes without moving one byte of the environment digest."""


# ---------------------------------------------------------------------------
# env_digest -- shape and determinism
# ---------------------------------------------------------------------------


def test_env_digest_is_sixty_four_lowercase_hex() -> None:
    """`sha256_canonical`'s form: the bare hex a `*_digest` TEXT column holds, no prefix."""
    digest = env_digest((), environ=NO_ENV, which=_absent, find_library=_absent)
    assert len(digest) == 64
    assert digest == digest.lower()
    assert set(digest) <= set("0123456789abcdef")


def test_env_digest_is_stable_across_process_restarts_and_pythonhashseed() -> None:
    """The key must survive a restart, or the cache never hits and the 26 s first query is every
    query (12-performance.md section 3.2).

    `PYTHONHASHSEED` is the one interpreter setting that silently reorders a `set` or a `dict`, and
    it is only observable in a fresh interpreter -- so this test spawns three of them. The digest is
    taken over an unsorted, duplicated binary list against a real on-disk file, so both the
    `sorted()` in the recipe and the identity triple are under test at once.
    """
    script = (
        "import sys\n"
        "from omniweave_core.probe import env_digest\n"
        "target = sys.argv[1]\n"
        "print(env_digest(\n"
        "    ['zeta', 'alpha', 'zeta'],\n"
        "    environ={'OMNIWEAVE_PROBE_EPOCH': '7'},\n"
        "    which=lambda name: target,\n"
        "    find_library=lambda name: None,\n"
        "))\n"
    )
    digests = {
        subprocess.run(  # noqa: S603
            [sys.executable, "-c", script, sys.executable],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }
    assert len(digests) == 1, f"env_digest moved with PYTHONHASHSEED: {digests}"
    assert len(next(iter(digests))) == 64


def test_env_digest_ignores_the_callers_order_and_duplicates() -> None:
    """`sorted(set(...))` in the recipe: the caller's iteration order must not reach a digest."""
    first = env_digest(["b", "a"], environ=NO_ENV, which=_absent, find_library=_absent)
    second = env_digest(["a", "b", "a"], environ=NO_ENV, which=_absent, find_library=_absent)
    assert first == second


# ---------------------------------------------------------------------------
# env_digest -- identities, not presences
# ---------------------------------------------------------------------------


def _binary(path: Path, content: bytes, mtime_ns: int) -> Path:
    """A real file with an exact size and an exact `st_mtime_ns`."""
    path.write_bytes(content)
    os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def _digest_of(target: Path, *, environ: dict[str, str] | None = None) -> str:
    return env_digest(
        ["tesseract"],
        environ=environ if environ is not None else NO_ENV,
        which=lambda _name: str(target),
        find_library=_absent,
    )


def test_env_digest_moves_when_a_declared_binarys_size_moves(tmp_path: Path) -> None:
    """An in-place `apt upgrade tesseract-ocr` that changes the binary's length.

    The bare path is unchanged, so a digest over presences would serve the cached `ok` forever.
    """
    target = _binary(tmp_path / "tesseract", b"v5.3.4", 1_000_000_000_000_000_000)
    before = _digest_of(target)
    _binary(target, b"v5.3.4-and-then-some", 1_000_000_000_000_000_000)
    assert _digest_of(target) != before


def test_env_digest_moves_when_a_declared_binarys_mtime_ns_moves(tmp_path: Path) -> None:
    """The harder half: an upgrade that replaces the binary with one of the SAME length.

    Size alone would not see it; `st_mtime_ns` does, which is why the identity is a triple.
    """
    target = _binary(tmp_path / "tesseract", b"aaaaaa", 1_000_000_000_000_000_000)
    before = _digest_of(target)
    _binary(target, b"bbbbbb", 1_700_000_000_123_456_789)
    after = _digest_of(target)
    assert after != before
    assert target.stat().st_size == 6, "the size deliberately did not move; only the mtime did"


def test_env_digest_moves_when_the_realpath_moves_even_at_equal_size_and_mtime(
    tmp_path: Path,
) -> None:
    """The `realpath` leg of the triple, isolated.

    This is the leg that carries a CUDA driver version on Linux, where `libcuda.so.1` resolves to
    `libcuda.so.<driver version>`: the NAME is the version. Two files identical in every stat field
    must still produce two digests.
    """
    mtime = 1_600_000_000_000_000_000
    first = _binary(tmp_path / "libcuda.so.550.54.14", b"same", mtime)
    second = _binary(tmp_path / "libcuda.so.560.35.03", b"same", mtime)
    assert first.stat().st_size == second.stat().st_size
    assert first.stat().st_mtime_ns == second.stat().st_mtime_ns
    assert env_digest(
        (), environ=NO_ENV, which=_absent, find_library=lambda _n: str(first)
    ) != env_digest((), environ=NO_ENV, which=_absent, find_library=lambda _n: str(second))


def test_a_cuda_presence_bool_would_not_have_caught_that() -> None:
    """The negative control for the sentence "an identity, never a bool".

    Both branches of a `find_library("cuda") is not None` bool are exercised above; what is asserted
    here is that the bool itself is not what the digest carries -- two present-but-different
    libraries are two digests, so a design that stored `True` would have collided them.
    """
    absent = env_digest((), environ=NO_ENV, which=_absent, find_library=_absent)
    present = env_digest((), environ=NO_ENV, which=_absent, find_library=lambda _n: sys.executable)
    assert absent != present


def test_a_binary_that_cannot_be_stat_ed_reads_as_absent(tmp_path: Path) -> None:
    """`_ident`'s `OSError` guard: a path that vanished between `which()` and `stat()`.

    The honest answer is the one an absent binary gives, and the alternative -- letting the
    `FileNotFoundError` out -- would make a digest recipe fail a whole run over a race.
    """
    vanished = tmp_path / "gone"
    assert not vanished.exists()
    assert env_digest(
        ["tesseract"], environ=NO_ENV, which=lambda _n: str(vanished), find_library=_absent
    ) == env_digest(["tesseract"], environ=NO_ENV, which=_absent, find_library=_absent)


# ---------------------------------------------------------------------------
# env_digest -- the escape hatch
# ---------------------------------------------------------------------------


def test_env_digest_moves_when_the_probe_epoch_moves(tmp_path: Path) -> None:
    """`OMNIWEAVE_PROBE_EPOCH` is the escape hatch for a condition the digest cannot see (E5)."""
    target = _binary(tmp_path / "tesseract", b"x", 1_000_000_000_000_000_000)
    before = _digest_of(target, environ={PROBE_EPOCH_ENV: "0"})
    after = _digest_of(target, environ={PROBE_EPOCH_ENV: "1"})
    assert before != after
    assert before == _digest_of(target, environ={}), "an unset epoch is the documented 0"


def test_env_digest_does_not_move_on_an_unrelated_environment_variable(tmp_path: Path) -> None:
    """The digest's inputs are enumerated, not scraped. A `LANG` or a `PATH` edit is not one.

    Without this, every shell that exports one more variable is a cold probe cache.
    """
    target = _binary(tmp_path / "tesseract", b"x", 1_000_000_000_000_000_000)
    baseline = _digest_of(target, environ={PROBE_EPOCH_ENV: "3"})
    noisy = _digest_of(
        target,
        environ={PROBE_EPOCH_ENV: "3", "LANG": "de_DE.UTF-8", "PATH": "/nowhere", "CI": "1"},
    )
    assert baseline == noisy


def test_a_non_integer_probe_epoch_is_a_named_refusal_carrying_its_fix() -> None:
    """A typo'd escape hatch that silently read as `0` would tell the operator they invalidated
    every verdict on the machine when they had not."""
    with pytest.raises(ConfigError) as caught:
        env_digest((), environ={PROBE_EPOCH_ENV: "yesterday"}, which=_absent, find_library=_absent)
    assert PROBE_EPOCH_ENV in str(caught.value)
    assert caught.value.fix


# ---------------------------------------------------------------------------
# The key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("driver_id", ".."),
        ("driver_id", "../../etc"),
        ("driver_id", "parse/pdf/native"),
        ("driver_id", "parse\\pdf"),
        ("driver_id", ""),
        ("driver_id", "parse.pdf\x00native"),
        ("driver_version", ".."),
        ("driver_version", "1.0.0/../.."),
        ("card_sha256", "ab" * 32),
        ("card_sha256", "sha256:" + "AB" * 32),
        ("card_sha256", "sha256:" + "ab" * 8),
        ("card_sha256", "sha512:" + "ab" * 32),
        ("env_digest", "sha256:" + "11" * 32),
        ("env_digest", "11" * 31),
        ("env_digest", "11" * 32 + "!"),
        ("env_digest", ("ab" * 32).upper()),
        ("env_digest", ""),
    ],
)
def test_a_key_component_that_could_escape_the_cache_root_is_refused(
    field: str, value: str
) -> None:
    """`driver_id` and `driver_version` are card-supplied strings that become directory names.

    Refused at construction rather than sanitised: a sanitised key silently collides with the key it
    was sanitised into, which is a wrong answer where a refusal is a message.
    """
    with pytest.raises(ValueError, match=field):
        _key(**{field: value})


def test_the_cache_path_carries_no_colon_and_strips_the_algorithm_prefix() -> None:
    """The one departure from section 4.7's printed path, and the reason for it.

    A colon is not a legal NTFS path component, so `.../<card_sha256>/...` written literally is
    unwritable on a third of the nine-cell matrix. The prefix carries no information here --
    `ProbeKey` refuses anything but sha256 -- and the full prefixed form is still inside the row.
    """
    relative = _key().relative_path()
    assert ":" not in str(relative)
    assert relative.parts == ("parse.pdf.native", "1.4.2", "ab" * 32, f"{ENV_A}.json")


def test_key_for_reads_exactly_four_facts_off_a_card() -> None:
    """`key_for` is the one place the four components are assembled, and it composes with the card
    types built by `omniweave_core.drivers.card` rather than with a shape invented here."""
    card = DriverCard(
        card_schema=1,
        identity=DriverIdentity(
            id="parse.ocr.tesseract",
            port="parse",  # type: ignore[arg-type]
            port_major=1,
            version="2.1.0",
            schema_version=3,
            granularity="document",
            replay_class="byte_exact",  # type: ignore[arg-type]
        ),
        capability=Capability(),
        origin="entry_point",
        source="omniweave-ocr",
        card_sha256=DIGEST_B,
        hardware=Hardware(needs_binaries=("tesseract",)),
    )
    key = key_for(card, environ=NO_ENV, which=_absent, find_library=_absent)
    assert key.driver_id == "parse.ocr.tesseract"
    assert key.driver_version == "2.1.0"
    assert key.card_sha256 == DIGEST_B
    assert key.env_digest == env_digest(
        ("tesseract",), environ=NO_ENV, which=_absent, find_library=_absent
    )


def test_probe_cache_root_is_the_tree_ow_doctor_deletes(tmp_path: Path) -> None:
    assert probe_cache_root(tmp_path) == tmp_path / PROBE_CACHE_DIRNAME


# ---------------------------------------------------------------------------
# The TTL table, row by row
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(CACHED_FOR_LIFE_OF_DIGEST))
def test_row_one_ok_and_degraded_outlive_any_clock(status: ProbeStatus) -> None:
    """ "Nothing short of an environment change can make a working driver stop working, and an
    environment change moves the digest" -- into the PATH, so it is a different file, not a stale
    row. A decade is used rather than a minute so no accidental TTL could pass this."""
    assert is_fresh(status, recorded_at=0.0, now=10.0 * 365 * 24 * 3600)


def test_row_one_is_the_two_statuses_and_not_merely_not_unavailable() -> None:
    """The set is spelled as a set so a fourth `ProbeStatus` member would land in the TTL'd branch
    rather than silently inherit "cached forever"."""
    assert frozenset({ProbeStatus.OK, ProbeStatus.DEGRADED}) == CACHED_FOR_LIFE_OF_DIGEST
    assert ProbeStatus.UNAVAILABLE not in CACHED_FOR_LIFE_OF_DIGEST


@pytest.mark.parametrize(
    "age,fresh",
    [
        (0.0, True),
        (1.0, True),
        (float(PROBE_TTL_S) - 0.001, True),
        (float(PROBE_TTL_S), False),
        (float(PROBE_TTL_S) + 1.0, False),
        (86_400.0, False),
    ],
)
def test_row_two_unavailable_is_re_probed_after_exactly_probe_ttl_s(
    age: float, fresh: bool
) -> None:
    """`probe_ttl_s = 600`, and the boundary is exclusive: at exactly 600 s the row is stale.

    An inclusive boundary would be defensible; what would not be is leaving it untested, because
    "cached for 600 s" and "cached for 600 s plus one call" differ by a whole probe.
    """
    assert is_fresh(ProbeStatus.UNAVAILABLE, recorded_at=1000.0, now=1000.0 + age) is fresh


def test_a_row_dated_in_the_future_is_stale_rather_than_immortal() -> None:
    """A backwards clock step -- NTP, a VM restore, a dual boot -- would otherwise pin an
    `unavailable` verdict alive for the length of the step. Re-probing early costs one spawn."""
    assert not is_fresh(ProbeStatus.UNAVAILABLE, recorded_at=2000.0, now=1000.0)


def test_row_three_a_timeout_is_the_printed_verdict_and_inherits_row_twos_ttl() -> None:
    """`ProbeVerdict(status="unavailable", detail="probe timed out after 2000 ms")`, verbatim.

    Row three needs no branch of its own precisely because the verdict is an `unavailable`; this is
    the test that would fail if someone gave it one.
    """
    verdict = timeout_verdict(2000)
    assert verdict.status is ProbeStatus.UNAVAILABLE
    assert verdict.detail == "probe timed out after 2000 ms"
    assert verdict.missing == ()
    assert verdict.fix_hint is None
    assert is_fresh(verdict.status, recorded_at=0.0, now=float(PROBE_TTL_S) - 1)
    assert not is_fresh(verdict.status, recorded_at=0.0, now=float(PROBE_TTL_S))


# ---------------------------------------------------------------------------
# The cache: round trip and every fault as a miss
# ---------------------------------------------------------------------------


def test_a_verdict_round_trips_through_the_cache_in_every_field(tmp_path: Path) -> None:
    """All five `ProbeVerdict` fields, because `capabilities_lost` and `missing` are the two the
    router acts on and a serialiser that dropped either would look correct in a status check."""
    cache = ProbeCache(root=tmp_path)
    key = _key()
    cache.write(key, TESSERACT_NO_LANGPACK, now=1000.0)
    assert cache.read(key, now=1000.0) == TESSERACT_NO_LANGPACK
    cache.write(key, TORCH_KERNEL_LAUNCH_FAILS, now=1000.0)
    assert cache.read(key, now=1000.0) == TORCH_KERNEL_LAUNCH_FAILS


def test_the_row_lands_at_the_path_section_4_7_prints(tmp_path: Path) -> None:
    cache = ProbeCache(root=tmp_path)
    key = _key()
    path = cache.write(key, OLLAMA_NO_MODEL, now=1.0)
    assert path == tmp_path / "parse.pdf.native" / "1.4.2" / ("ab" * 32) / f"{ENV_A}.json"
    assert path.is_file()


@pytest.mark.parametrize("moved", ["driver_id", "driver_version", "card_sha256", "env_digest"])
def test_moving_any_one_of_the_four_components_is_a_miss(tmp_path: Path, moved: str) -> None:
    """The key is four components because each one can move alone.

    `card_sha256` is the one a reader queries: a card edited in place under an unchanged
    `[driver] version` moves nothing else, and without this component the stale verdict is served.
    """
    replacement = {
        "driver_id": "parse.pdf.other",
        "driver_version": "1.4.3",
        "card_sha256": DIGEST_B,
        "env_digest": ENV_B,
    }[moved]
    cache = ProbeCache(root=tmp_path)
    cache.write(_key(), TESSERACT_NO_LANGPACK, now=1000.0)
    assert cache.read(_key(**{moved: replacement}), now=1000.0) is None


def test_a_row_moved_under_another_keys_path_is_a_miss(tmp_path: Path) -> None:
    """The stored key inside the row, earning its couple of hundred bytes.

    A `$OMNIWEAVE_HOME` restored from another machine's backup, or a hand-renamed directory, is the
    one shape in which this cache can be *wrong* rather than merely absent.
    """
    cache = ProbeCache(root=tmp_path)
    source = cache.write(_key(), TORCH_KERNEL_LAUNCH_FAILS, now=1000.0)
    other = _key(driver_version="9.9.9")
    target = cache.path_for(other)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    assert cache.read(other, now=1000.0) is None


@pytest.mark.parametrize(
    "corruption",
    [
        b"",
        b"{",
        b"not json at all",
        b"[]",
        b'{"schema": 2, "key": {}, "recorded_at": 0.0, "verdict": {}}',
        b'{"schema": 1, "recorded_at": 0.0, "verdict": {}}',
        b"\xff\xfe\x00\x00",
    ],
)
def test_every_unreadable_row_is_a_miss_and_never_a_raise(
    tmp_path: Path, corruption: bytes
) -> None:
    """A cache that can fail a run is worse than no cache (11-repo-layout.md section 2.6 rule 2).

    A miss costs one probe; a raise costs the run. `read()` catches named exception types only --
    a bare `except` around a cache key is banned by G8's semgrep row.
    """
    cache = ProbeCache(root=tmp_path)
    key = _key()
    path = cache.path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(corruption)
    assert cache.read(key, now=1000.0) is None


def test_a_row_whose_verdict_fields_have_the_wrong_types_is_a_miss(tmp_path: Path) -> None:
    """`ProbeVerdict` is a frozen dataclass with no validation of its own, and the row is a file in
    a user-writable directory: a `missing` that arrived as a bare string would reach the router as
    one entry per character."""
    cache = ProbeCache(root=tmp_path)
    key = _key()
    path = cache.write(key, TESSERACT_NO_LANGPACK, now=1000.0)
    row = json.loads(path.read_bytes())
    row["verdict"]["missing"] = "tesseract-lang:deu"
    path.write_bytes(json.dumps(row).encode("utf-8"))
    assert cache.read(key, now=1000.0) is None


def test_a_row_with_an_unknown_status_word_is_a_miss(tmp_path: Path) -> None:
    """`ProbeStatus` is closed at three; a fourth word on disk is a row from another build."""
    cache = ProbeCache(root=tmp_path)
    key = _key()
    path = cache.write(key, OLLAMA_NO_MODEL, now=1000.0)
    row = json.loads(path.read_bytes())
    row["verdict"]["status"] = "probably"
    path.write_bytes(json.dumps(row).encode("utf-8"))
    assert cache.read(key, now=1000.0) is None


def test_a_missing_file_is_a_miss(tmp_path: Path) -> None:
    """The ordinary case, and the one `resolve()` reads as `unknown` -- which PASSES its filter.

    An unprobed driver is a candidate, not a refusal (section 4.7), so a miss can only ever cost a
    preflight probe.
    """
    assert ProbeCache(root=tmp_path).read(_key(), now=1000.0) is None


# ---------------------------------------------------------------------------
# The write: atomic replace from a same-directory temporary
# ---------------------------------------------------------------------------


def test_the_write_leaves_no_temporary_behind(tmp_path: Path) -> None:
    """The `finally` half. A stale `.tmp` per verdict per run is how a cache directory grows without
    bound in a served process."""
    cache = ProbeCache(root=tmp_path)
    cache.write(_key(), OLLAMA_NO_MODEL, now=1.0)
    assert [p.name for p in tmp_path.rglob("*.tmp")] == []


def test_the_temporary_is_pid_suffixed_and_sits_beside_its_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Section 4.7 says "a `.tmp` in the same directory"; the pid is what makes the sentence true.

    Same directory because a replace is atomic only within a filesystem. Pid-suffixed because a
    single shared `.tmp` name is itself a tearable file -- two processes would interleave into it
    and then both replace a spliced row, which is the failure the atomic replace exists to prevent.
    `os.getpid()` and not a random suffix, because `random` is banned repo-wide.
    """
    seen: list[tuple[Path, Path]] = []
    original = Path.replace

    def spy(self: Path, target: str | Path) -> Path:
        seen.append((self, Path(target)))
        return original(self, target)

    monkeypatch.setattr(Path, "replace", spy)
    monkeypatch.setattr(os, "getpid", lambda: 424242)
    cache = ProbeCache(root=tmp_path)
    final = cache.write(_key(), OLLAMA_NO_MODEL, now=1.0)
    assert len(seen) == 1
    temporary, target = seen[0]
    assert target == final
    assert temporary.parent == final.parent
    assert temporary.name == f"{final.name}.424242.tmp"


def test_a_write_that_fails_mid_flight_leaves_the_previous_row_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A torn write is impossible.** The bytes go to the temporary; only a whole file is replaced.

    The failure is injected at the write of the temporary, which is the only point at which partial
    bytes exist anywhere.
    """
    cache = ProbeCache(root=tmp_path)
    key = _key()
    cache.write(key, TESSERACT_NO_LANGPACK, now=1000.0)
    intact = cache.path_for(key).read_bytes()

    def explode(_self: Path, _data: bytes) -> int:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_bytes", explode)
    with pytest.raises(OSError, match="disk full"):
        cache.write(key, OLLAMA_NO_MODEL, now=2000.0)
    monkeypatch.undo()
    assert cache.path_for(key).read_bytes() == intact
    assert cache.read(key, now=1000.0) == TESSERACT_NO_LANGPACK
    assert [p.name for p in tmp_path.rglob("*.tmp")] == []


def test_two_concurrent_equal_writes_converge_on_equal_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "The loser's write is simply overwritten by an equal value" (section 4.7).

    Modelled as two writers with two pids -- so two distinct temporaries, which is the whole point
    -- recording the same verdict at the same instant. `canonical()` gives the bytes, so equal
    inputs are equal files and whichever replace lands last is byte-identical to the other.
    """
    key = _key()
    rows: list[bytes] = []
    for pid in (1001, 1002):
        monkeypatch.setattr(os, "getpid", lambda pid=pid: pid)
        root = tmp_path / f"home-{pid}"
        ProbeCache(root=root).write(key, TORCH_KERNEL_LAUNCH_FAILS, now=1700.5)
        rows.append((root / key.relative_path()).read_bytes())
    assert rows[0] == rows[1]

    shared = ProbeCache(root=tmp_path / "shared")
    for pid in (1001, 1002):
        monkeypatch.setattr(os, "getpid", lambda pid=pid: pid)
        shared.write(key, TORCH_KERNEL_LAUNCH_FAILS, now=1700.5)
    assert shared.path_for(key).read_bytes() == rows[0]
    assert [p.name for p in (tmp_path / "shared").rglob("*.tmp")] == []


def test_the_row_records_its_schema_its_whole_key_and_the_time(tmp_path: Path) -> None:
    """What is on disk, asserted as content rather than as shape -- a row that parsed but held the
    wrong key would satisfy every structural check and serve another driver's verdict."""
    cache = ProbeCache(root=tmp_path)
    key = _key()
    row = json.loads(cache.write(key, TESSERACT_NO_LANGPACK, now=1234.5).read_bytes())
    assert row["schema"] == PROBE_ROW_SCHEMA
    assert row["recorded_at"] == 1234.5
    assert row["key"] == {
        "driver_id": "parse.pdf.native",
        "driver_version": "1.4.2",
        "card_sha256": DIGEST_A,
        "env_digest": ENV_A,
    }
    assert row["verdict"]["missing"] == ["tesseract-lang:deu"]
    assert row["verdict"]["fix_hint"] == "apt install tesseract-ocr-deu"


def test_clear_deletes_the_tree_and_reports_what_it_removed(tmp_path: Path) -> None:
    """`ow doctor --refresh-probes`. The count is returned so the verb can say what it did."""
    cache = ProbeCache(root=tmp_path / PROBE_CACHE_DIRNAME)
    cache.write(_key(), OLLAMA_NO_MODEL, now=1.0)
    cache.write(_key(driver_id="embed.text.ollama"), OLLAMA_NO_MODEL, now=1.0)
    assert cache.clear() == 2
    assert not cache.root.exists()
    assert cache.clear() == 0, "clearing an absent tree is a no-op, not an error"


# ---------------------------------------------------------------------------
# cached_probe: the seam, the hit, and each TTL row end to end
# ---------------------------------------------------------------------------


class _Prober:
    """A `Prober` test double that counts calls and can be told to hang."""

    def __init__(self, verdict: ProbeVerdict | None, *, times_out: bool = False) -> None:
        self.verdict = verdict
        self.times_out = times_out
        self.calls = 0

    def __call__(self, _env: object) -> ProbeVerdict:
        self.calls += 1
        if self.times_out:
            raise TimeoutError("worker did not answer")
        assert self.verdict is not None
        return self.verdict


def _env() -> object:
    return probe_env((), offline=True, which=_absent, find_library=_absent)


def _run(cache: ProbeCache, prober: object, now: float, key: ProbeKey | None = None) -> object:
    return cached_probe(
        key=key or _key(),
        env=_env(),  # type: ignore[arg-type]
        cache=cache,
        run_probe=prober,  # type: ignore[arg-type]
        clock=lambda: now,
        timeout_ms=2000,
    )


def test_a_miss_runs_the_prober_once_and_persists_what_it_said(tmp_path: Path) -> None:
    cache = ProbeCache(root=tmp_path)
    prober = _Prober(TESSERACT_NO_LANGPACK)
    outcome = _run(cache, prober, 1000.0)
    assert prober.calls == 1
    assert outcome.cached is False  # type: ignore[attr-defined]
    assert outcome.verdict == TESSERACT_NO_LANGPACK  # type: ignore[attr-defined]
    assert cache.read(_key(), now=1000.0) == TESSERACT_NO_LANGPACK


def test_a_hit_does_not_spawn_anything(tmp_path: Path) -> None:
    """ "The second invocation pays 0 ms of probe" (12-performance.md section 3.2).

    The `cached` flag is what lets `ow doctor` report that rather than assert it.
    """
    cache = ProbeCache(root=tmp_path)
    cache.write(_key(), TORCH_KERNEL_LAUNCH_FAILS, now=1000.0)
    prober = _Prober(None)
    outcome = _run(cache, prober, 1000.0)
    assert prober.calls == 0
    assert outcome.cached is True  # type: ignore[attr-defined]
    assert outcome.verdict == TORCH_KERNEL_LAUNCH_FAILS  # type: ignore[attr-defined]


def test_an_unavailable_verdict_is_re_probed_after_six_hundred_seconds(tmp_path: Path) -> None:
    """The headline behaviour of row two, with an injected clock.

    Shape one: `apt install tesseract-ocr-deu` changes neither `shutil.which("tesseract")` nor any
    other `env_digest` input, so the key does not move -- and if the TTL did not exist, the fix
    would have no effect until the next release. Three probes across the timeline, and the count is
    what proves it: one at t=0, none at t=599, one more at t=600.
    """
    cache = ProbeCache(root=tmp_path)
    prober = _Prober(TESSERACT_NO_LANGPACK)
    _run(cache, prober, 0.0)
    assert prober.calls == 1
    assert _run(cache, prober, 599.0).cached is True  # type: ignore[attr-defined]
    assert prober.calls == 1
    prober.verdict = ProbeVerdict(status=ProbeStatus.OK, detail="deu traineddata present")
    assert _run(cache, prober, float(PROBE_TTL_S)).cached is False  # type: ignore[attr-defined]
    assert prober.calls == 2
    assert cache.read(_key(), now=float(PROBE_TTL_S)).status is ProbeStatus.OK  # type: ignore[union-attr]


def test_a_degraded_verdict_is_never_re_probed_under_an_unmoved_digest(tmp_path: Path) -> None:
    """Row one, end to end. Shape two: the CUDA/toolkit mismatch is fixed by a driver upgrade, and a
    driver upgrade moves `libcuda`'s identity, which moves the digest, which moves the path -- so
    there is nothing left for a TTL to do."""
    cache = ProbeCache(root=tmp_path)
    prober = _Prober(TORCH_KERNEL_LAUNCH_FAILS)
    _run(cache, prober, 0.0)
    for later in (600.0, 86_400.0, 10.0 * 365 * 24 * 3600):
        assert _run(cache, prober, later).cached is True  # type: ignore[attr-defined]
    assert prober.calls == 1


def test_a_moved_env_digest_is_a_different_file_and_not_a_stale_row(tmp_path: Path) -> None:
    """The mechanism row one leans on, made visible: the digest is IN THE PATH.

    An `ok` cached under one environment is not reachable from another, so "cached for the life of
    the `env_digest`" needs no expiry logic at all.
    """
    cache = ProbeCache(root=tmp_path)
    prober = _Prober(ProbeVerdict(status=ProbeStatus.OK, detail="ready"))
    _run(cache, prober, 0.0, key=_key())
    _run(cache, prober, 0.0, key=_key(env_digest=ENV_B))
    assert prober.calls == 2
    assert cache.path_for(_key()) != cache.path_for(_key(env_digest=ENV_B))
    assert cache.path_for(_key()).is_file()
    assert cache.path_for(_key(env_digest=ENV_B)).is_file()


def test_a_timed_out_probe_is_recorded_as_the_printed_unavailable_and_re_probed(
    tmp_path: Path,
) -> None:
    """Row three, end to end. "A hung probe is not evidence of a permanent condition."

    The seam raises `TimeoutError` -- `subprocess.TimeoutExpired` is a `SubprocessError` and this
    module may not learn that type's name, so the adapter translates.
    """
    cache = ProbeCache(root=tmp_path)
    prober = _Prober(None, times_out=True)
    outcome = _run(cache, prober, 0.0)
    assert outcome.verdict == timeout_verdict(2000)  # type: ignore[attr-defined]
    assert cache.read(_key(), now=599.0) == timeout_verdict(2000)
    assert cache.read(_key(), now=float(PROBE_TTL_S)) is None
    prober.times_out = False
    prober.verdict = ProbeVerdict(status=ProbeStatus.OK, detail="answered")
    assert _run(cache, prober, float(PROBE_TTL_S)).cached is False  # type: ignore[attr-defined]
    assert prober.calls == 2


def test_the_timeout_detail_names_the_configured_budget_and_not_a_hardcoded_one(
    tmp_path: Path,
) -> None:
    """`drivers.probe_timeout_ms` is a config key; the module holds no default for it."""
    cache = ProbeCache(root=tmp_path)
    outcome = cached_probe(
        key=_key(),
        env=_env(),  # type: ignore[arg-type]
        cache=cache,
        run_probe=_Prober(None, times_out=True),  # type: ignore[arg-type]
        clock=lambda: 0.0,
        timeout_ms=5000,
    )
    assert outcome.verdict.detail == "probe timed out after 5000 ms"


def test_any_other_exception_from_the_seam_propagates(tmp_path: Path) -> None:
    """Not caught, deliberately. Swallowing it would turn a broken host into a permanently
    `unavailable` driver with no diagnosis, and a bare `except` around a probe is banned (G8)."""

    def broken(_env: object) -> ProbeVerdict:
        raise RuntimeError("the worker adapter is misconfigured")

    with pytest.raises(RuntimeError, match="misconfigured"):
        _run(ProbeCache(root=tmp_path), broken, 0.0)


def test_a_missing_capability_is_a_verdict_and_never_a_raise(tmp_path: Path) -> None:
    """DR21: a pruned plan with a report, never an `ImportError`. All three shapes, and the fields
    the router and the printer each read."""
    cache = ProbeCache(root=tmp_path)
    for index, shape in enumerate(
        (TESSERACT_NO_LANGPACK, TORCH_KERNEL_LAUNCH_FAILS, OLLAMA_NO_MODEL)
    ):
        outcome = _run(cache, _Prober(shape), 0.0, key=_key(driver_id=f"parse.shape{index}.x"))
        verdict = outcome.verdict  # type: ignore[attr-defined]
        assert verdict.detail
        if verdict.status is ProbeStatus.UNAVAILABLE:
            assert verdict.missing and verdict.fix_hint, "an unavailable NAMES the missing thing"
        else:
            assert verdict.capabilities_lost, "a degraded lets the router re-filter"


# ---------------------------------------------------------------------------
# ProbeEnv
# ---------------------------------------------------------------------------


def test_probe_env_carries_bare_paths_where_the_digest_carries_identities(tmp_path: Path) -> None:
    """The asymmetry, asserted. The driver is handed a path so it can run the binary; the cache is
    keyed on an identity so an in-place upgrade of that binary moves the key."""
    target = _binary(tmp_path / "tesseract", b"x", 1_000_000_000_000_000_000)
    env = probe_env(
        ["tesseract", "pdftoppm"],
        offline=False,
        which=lambda name: str(target) if name == "tesseract" else None,
        find_library=_absent,
    )
    assert env.which == {"pdftoppm": None, "tesseract": str(target)}
    assert env.offline is False


def test_probe_env_reads_the_gpu_without_importing_a_framework() -> None:
    """`gpu_present` comes from `ctypes.util.find_library("cuda")`, NEVER by importing a framework,
    and `vram_gb` is 0.0 when unknown for the same reason (`ProbeEnv`'s own docstring).

    `libcuda` is never loaded either: calling `cuDriverGetVersion` through ctypes was rejected
    because it `dlopen`s a vendor driver library in the host process and a segfault on load is not
    catchable.
    """
    absent = probe_env((), offline=True, which=_absent, find_library=_absent)
    present = probe_env((), offline=True, which=_absent, find_library=lambda _n: "/usr/lib/libcuda")
    assert absent.gpu_present is False
    assert present.gpu_present is True
    assert absent.vram_gb == 0.0 and present.vram_gb == 0.0
    assert "torch" not in sys.modules


def test_probe_env_reports_the_running_interpreter_rather_than_a_declared_one() -> None:
    env = probe_env((), offline=True, which=_absent, find_library=_absent)
    assert env.platform == sys.platform
    assert env.python == (sys.version_info.major, sys.version_info.minor)
    assert env.machine
