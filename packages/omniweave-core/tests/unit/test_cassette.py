"""The Cassette codec: the key both ways, `required` with no live path, and reproducible bytes.

W3.7 (16-roadmap.md:487). Four things this file is built around, in the order they matter:

1. **`required` never makes a live call, and the proof is not "assert the mode is required".**
   `_exploding_live` is a live channel that raises `LiveCallReached`; every `required` test that
   supplies a live channel at all supplies that one, so a miss that fell through to the live path
   would fail with that class and not with `QualityError`. (The tests that expect a HIT pass
   `live=None` instead, which is the stronger shape: there is no live path in existence to fall
   through to.) The pairing that makes it non-vacuous is
   `test_the_exploding_live_channel_is_entered_under_off_and_raises`: without a test proving the
   fixture really explodes when reached, "it did not explode" proves nothing.
2. **The key is tested in both directions, and the miss is attributed to the right mechanism.**
   A request differing only in JSON key order must HIT; a request differing in any of
   13-quality.md:978's six fields, or in the request path or the prompt version, must MISS. A key
   test that only ever asserts hits proves the key is wide enough and never that it is narrow
   enough. But a MISS is also not proof that a field is in the key: `service` is a directory in
   :980's layout and `contract` is recorded and re-checked on load, so varying either misses
   even with that field out of the digest entirely --
   `test_the_key_changes_when_the_service_or_the_contract_changes` asserts the key inequality
   that :978 actually claims, and
   `test_the_key_is_this_literal_and_the_same_in_a_fresh_interpreter` pins the digest itself so
   a per-process input in the recipe cannot hide behind a same-process record-then-replay.
3. **`allow` writes byte-reproducible bytes.** Identical on a second run, identical under a
   different store root, and identical across two fresh interpreters with different hash seeds
   and different dict insertion orders. `canonical()` and not `json.dumps` is pinned by
   `test_encode_refuses_the_values_canonical_refuses`, because for an in-grammar record the two
   emit the same bytes and only an out-of-grammar one separates them.
4. **The modelserver seam is a tested absence.** `omniweave_core.modelserver` has no spec,
   `intercept_modelserver()` raises, and `seam_coverage()` reports one of two channels enforced.
   The module docstring says which half is enforced; these tests say the same thing in
   assertions, so the claim cannot rot into prose.

Every literal asserted below is written out here rather than imported from
`omniweave_core.cassette`: a constant a test imports from its subject pins agreement, not value.
The plan-document assertions go the other way on purpose -- they pin the subject's literals
against the specification line that owns them.

Four names ARE imported from the subject -- `CASSETTE_ROOT`, `SEAMS`, `SEAMS_ENFORCED` and
`SEAMS_PENDING` -- and that is not a violation of the paragraph above but its
application: each one is a value the module states and no test used to read, so each is asserted
here against a literal or against the plan line that owns it. An imported constant is a defect
when it stands on BOTH sides of an equality; on one side, with a literal on the other, it is the
only way to pin it at all. `CONTRACT` comes from `omniweave_core.contract`, which ADR-9 makes its
sole home, and 13-quality.md:979 makes the cassette's `contract_major` literally that value --
so that assertion pins two modules against each other and neither against itself.
"""

from __future__ import annotations

import hashlib
import json
import socket
import time
import tomllib
from collections.abc import Mapping
from pathlib import Path

import pytest
from conftest import Interpreter, PlanDocs, SourceIndex
from omniweave_core.cassette import (
    CASSETTE_ROOT,
    SEAMS,
    SEAMS_ENFORCED,
    SEAMS_PENDING,
    UNTRUSTED_WRAPPER_APPLIED,
    BodyEncoding,
    Cassette,
    CassetteHandle,
    CassetteMode,
    CassetteStore,
    ContractIdentity,
    Interaction,
    LiveResponse,
    Request,
    Seam,
    ServiceFacts,
    encode_body,
    intercept_service,
    payload_digest,
    prompt_digest,
    redact_headers,
    redact_payload,
    replay_handle,
    seam_coverage,
)
from omniweave_core.contract import CONTRACT
from omniweave_core.errors import QualityError
from omniweave_core.modelserver import MODELS_PATH, SERVICE_API_MAJOR

# ---------------------------------------------------------------------------
# The live channel that must never be entered
# ---------------------------------------------------------------------------


class LiveCallReached(AssertionError):  # noqa: N818 -- names an EVENT, not an error kind.
    """The live channel was entered. Under `required` that is the whole failure this item prevents.

    An `AssertionError` subclass rather than a bespoke exception so a test that accidentally
    swallows it into `pytest.raises(QualityError)` still fails loudly rather than passing.
    """


def _exploding_live() -> LiveResponse:
    """A live channel whose only behaviour is to fail. 12-performance.md:1550's 64x amplifier."""
    message = "the live channel was entered: a cassette miss reached the network"
    raise LiveCallReached(message)


def _canned_live(
    body: bytes = b'{"choices":[{"text":"ok"}]}', *, latency_ms: int = 41
) -> LiveResponse:
    """A deterministic live response. `latency_ms` is an INPUT here, never a measurement."""
    return LiveResponse(
        status=200, headers={"content-type": "application/json"}, body=body, latency_ms=latency_ms
    )


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

SERVICE = "olmocr"
MODEL_KEY = "9f2c1ab4de5670f1"
PROMPT = "transcribe this page"
PROMPT_VERSION = "v3"
PATH = "/v1/chat/completions"
SAMPLING: dict[str, object] = {"temperature": 0.0, "top_p": 1.0}
BODY = b'{"model":"olmocr","pages":[1,2],"stream":false}'


def _store(root: Path, *, name: str = "cassettes") -> CassetteStore:
    return CassetteStore(root=root / name)


def _request(
    *,
    service: str = SERVICE,
    model_key: str = MODEL_KEY,
    prompt: str = PROMPT,
    sampling: dict[str, object] | None = None,
    body: bytes = BODY,
    contract: ContractIdentity | None = None,
) -> Request:
    return Request(
        service=service,
        model_key=model_key,
        prompt_digest=prompt_digest(prompt),
        sampling=SAMPLING if sampling is None else sampling,
        payload_digest=payload_digest(body),
        contract=contract or ContractIdentity.for_driver_io(),
    )


def _record_one(
    store: CassetteStore,
    *,
    body: bytes = BODY,
    response: bytes = b'{"choices":[{"text":"ok"}]}',
    path: str = PATH,
    prompt_version: str = PROMPT_VERSION,
    headers: dict[str, str] | None = None,
    latency_ms: int = 41,
) -> Cassette:
    """Record one interaction under `allow` and hand back the cassette that did it."""
    cassette = Cassette(mode=CassetteMode.ALLOW, store=store)
    cassette.replay(
        _request(body=body),
        path=path,
        prompt_version=prompt_version,
        request_headers=headers or {},
        request_body=body,
        live=lambda: _canned_live(response, latency_ms=latency_ms),
    )
    return cassette


# ---------------------------------------------------------------------------
# 1. `required` never makes a live call
# ---------------------------------------------------------------------------


def test_the_exploding_live_channel_is_entered_under_off_and_raises(tmp_path: Path) -> None:
    """The negative control for every `required` test below.

    13-quality.md:982 makes `off` "no interception", so the live channel IS the answer there.
    Without this test, `test_required_...` proves only that nothing happened, which is also what
    a broken fixture proves.
    """
    cassette = Cassette(mode=CassetteMode.OFF, store=_store(tmp_path))
    with pytest.raises(LiveCallReached):
        cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION, live=_exploding_live)
    assert cassette.live_calls == 1


def test_required_raises_on_a_miss_and_never_enters_the_live_channel(tmp_path: Path) -> None:
    """13-quality.md:982: a miss under `required` is OW-Q-004 "and never a live call".

    The live channel handed over is `_exploding_live`, so a fall-through would surface as
    `LiveCallReached` rather than `QualityError` and this test would fail on the exception class.
    """
    store = _store(tmp_path)
    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    with pytest.raises(QualityError) as caught:
        cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION, live=_exploding_live)
    assert "OW-Q-004" in str(caught.value)
    assert cassette.live_calls == 0
    assert cassette.recorded == ()
    assert store.keys() == ()


def test_required_replays_a_committed_recording_with_no_live_channel_in_existence(
    tmp_path: Path,
) -> None:
    """The strongest form of "never a live call": `live=None` is a complete `required` run."""
    store = _store(tmp_path)
    _record_one(store, response=b'{"text":"recorded"}')

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    recording = cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION, live=None)
    assert recording.hit is True
    assert recording.live is False
    assert recording.interaction.response_bytes() == b'{"text":"recorded"}'
    assert cassette.live_calls == 0


def test_the_miss_error_carries_the_numeric_and_the_fix_command_the_plan_prints(
    tmp_path: Path,
) -> None:
    """`_notes/charter.md:7673`: `OW-Q-004 cassette miss for {service} key {key}`, fix
    `ow eval record --service {service}`. Both literals are written here, not imported.
    """
    cassette = Cassette(mode=CassetteMode.REQUIRED, store=_store(tmp_path))
    with pytest.raises(QualityError) as caught:
        cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION, live=_exploding_live)
    error = caught.value
    assert str(error).startswith("OW-Q-004 cassette miss for olmocr key ")
    assert error.fix == "ow eval record --service olmocr"
    assert error.code() == "OW_QUALITY"
    assert error.numeric() == ""


def test_a_replay_handle_carries_no_upstream_handle_and_returns_recorded_bytes(
    tmp_path: Path,
) -> None:
    """`replay_handle()` is the CI shape: a `ServiceHandle` with no live channel at all."""
    store = _store(tmp_path)
    _record_one(store, response=b'{"text":"from the cassette"}')

    handle = replay_handle(
        name=SERVICE,
        cassette=Cassette(mode=CassetteMode.REQUIRED, store=store),
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
        sampling=SAMPLING,
    )
    assert handle.live is None
    assert handle.post(PATH, BODY) == b'{"text":"from the cassette"}'


def _exploding_service(_name: str) -> object:
    """A `DriverIO.service` that fails if entered. The seam's own negative control.

    `DriverIO.service(name)` is `ServiceRegistry.handle(name)` -- `attach_or_spawn`, BLOCKING
    (08-runtime.md:982-986) -- so entering it spawns a model server or dials a pinned endpoint.
    Under `required` neither may happen, and this is what proves it did not.
    """
    message = "DriverIO.service() was entered: a required run reached attach_or_spawn"
    raise LiveCallReached(message)


def test_required_never_enters_the_service_seam_at_all_and_so_cannot_spawn(
    tmp_path: Path,
) -> None:
    """The strongest reading of 13-quality.md:971's "recorded AT `DriverIO.service()`".

    A `post()`-only interception would satisfy 13-quality.md:982's letter -- no model call -- and
    still start a GPU process inside the `parity` cell 15-observability.md:1703 specifies as "2
    cores, 7 GB, no GPU, no network" under `--cassette required`. `_exploding_service` is the
    assertion: a `required` run that touched the seam fails with `LiveCallReached`, and the
    negative control proving the fixture really explodes is
    `test_off_and_allow_do_enter_the_service_seam`.
    """
    store = _store(tmp_path)
    _record_one(store, response=b'{"text":"replayed"}')
    wrapped = intercept_service(
        _exploding_service,  # type: ignore[arg-type]
        cassette=Cassette(mode=CassetteMode.REQUIRED, store=store),
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
        sampling=SAMPLING,
    )

    handle = wrapped(SERVICE)
    assert isinstance(handle, CassetteHandle)
    assert handle.live is None
    assert handle.post(PATH, BODY) == b'{"text":"replayed"}'


def test_off_and_allow_do_enter_the_service_seam(tmp_path: Path) -> None:
    """The negative control for the test above: the two modes that MAY reach the service, do.

    Without this, "the seam was not entered" is also what a wrapper that ignores its argument
    proves, and what a fixture that never raises proves.
    """
    for mode in (CassetteMode.OFF, CassetteMode.ALLOW):
        wrapped = intercept_service(
            _exploding_service,  # type: ignore[arg-type]
            cassette=Cassette(mode=mode, store=_store(tmp_path, name=f"s-{mode.value}")),
            model_key=MODEL_KEY,
            prompt_digest=prompt_digest(PROMPT),
            prompt_version=PROMPT_VERSION,
        )
        with pytest.raises(LiveCallReached):
            wrapped(SERVICE)


def test_intercept_service_drops_the_upstream_handle_under_required_and_keeps_it_otherwise(
    tmp_path: Path,
) -> None:
    """The seam wrapper. 13-quality.md:971's "recorded at `DriverIO.service()`", concretely.

    Under `required` the wrapped handle must hold no upstream, so no `post()` can reach it;
    under `allow` it must hold one, or nothing could ever be recorded.
    """
    upstream = _StubUpstream(b'{"text":"live"}')

    for mode, expect_live in ((CassetteMode.REQUIRED, False), (CassetteMode.ALLOW, True)):
        wrapped = intercept_service(
            lambda _name: upstream,  # type: ignore[arg-type,return-value]
            cassette=Cassette(mode=mode, store=_store(tmp_path, name=f"c-{mode.value}")),
            model_key=MODEL_KEY,
            prompt_digest=prompt_digest(PROMPT),
            prompt_version=PROMPT_VERSION,
        )
        handle = wrapped(SERVICE)
        assert isinstance(handle, CassetteHandle)
        assert (handle.live is not None) is expect_live, mode


def test_a_required_handle_carries_declared_facts_and_empty_defaults_when_none_are_declared(
    tmp_path: Path,
) -> None:
    """The stated COST of never spawning under `required`: the five facts must be declared.

    Both halves are asserted, because the declared half alone would not show what a caller who
    declares nothing actually gets -- and what they get is `ServiceFacts()`'s defaults and not
    the `_StubUpstream`'s real `model_id`, which is the whole point.
    """
    declared = ServiceFacts(
        model_id="allenai/olmOCR-7B", model_rev="r7", capacity=2, deadline_ms=30_000
    )
    cassette = Cassette(mode=CassetteMode.REQUIRED, store=_store(tmp_path))
    with_facts = intercept_service(
        _exploding_service,  # type: ignore[arg-type]
        cassette=cassette,
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
        declared=declared,
    )(SERVICE)
    assert (with_facts.model_id, with_facts.model_rev) == ("allenai/olmOCR-7B", "r7")
    assert (with_facts.capacity, with_facts.deadline_ms) == (2, 30_000)

    bare = intercept_service(
        _exploding_service,  # type: ignore[arg-type]
        cassette=cassette,
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
    )(SERVICE)
    assert (bare.model_id, bare.model_rev, bare.traceparent) == ("", "", "")
    assert (bare.capacity, bare.deadline_ms) == (1, 0)


def test_allow_reads_the_five_facts_off_the_real_handle_and_ignores_the_declared_ones(
    tmp_path: Path,
) -> None:
    """`allow` HAS a live handle, so the host's own facts win over anything a caller declared."""
    upstream = _StubUpstream(b'{"text":"live"}')
    handle = intercept_service(
        lambda _name: upstream,  # type: ignore[arg-type,return-value]
        cassette=Cassette(mode=CassetteMode.ALLOW, store=_store(tmp_path)),
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
        declared=ServiceFacts(model_id="wrong", capacity=99),
    )(SERVICE)
    assert handle.model_id == "allenai/olmOCR-7B"
    assert handle.capacity == 2
    assert handle.deadline_ms == 30_000


# ---------------------------------------------------------------------------
# 2. The key: narrow enough AND wide enough
# ---------------------------------------------------------------------------


def test_the_key_inputs_are_exactly_the_six_fields_the_plan_names() -> None:
    """13-quality.md:978: `sha256_canonical({service, model_key, prompt_digest, sampling,
    payload_digest, contract})`. Six, written out here as literals.
    """
    assert sorted(_request().key_inputs()) == [
        "contract",
        "model_key",
        "payload_digest",
        "prompt_digest",
        "sampling",
        "service",
    ]


def test_the_plan_line_that_owns_the_key_names_those_six_and_no_seventh(plan: PlanDocs) -> None:
    """The subject's field set, checked against the specification line rather than itself."""
    plan.require()
    hits = plan.grep(r"sha256_canonical\(\{service, model_key", documents=["13-quality.md"])
    assert len(hits) == 1, hits
    assert hits[0].line == 978
    braced = hits[0].text.split("{", 1)[1].split("}", 1)[0]
    assert [name.strip() for name in braced.split(",")] == [
        "service",
        "model_key",
        "prompt_digest",
        "sampling",
        "payload_digest",
        "contract",
    ]


def test_a_request_differing_only_in_json_key_order_hits(tmp_path: Path) -> None:
    """13-quality.md:978: "two logically identical calls differing in JSON key order must hit"."""
    store = _store(tmp_path)
    _record_one(store, body=b'{"a":1,"b":2}', response=b'{"ok":true}')

    reordered = b'{"b":2, "a":1}'
    assert reordered != b'{"a":1,"b":2}'
    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    recording = cassette.replay(
        _request(body=reordered),
        path=PATH,
        prompt_version=PROMPT_VERSION,
        live=_exploding_live,
    )
    assert recording.hit is True
    assert cassette.usage_rows() == (_request(body=reordered).key,)


def test_a_request_differing_only_in_whitespace_hits(tmp_path: Path) -> None:
    """The same property from the other side: the request BYTES are not the key (:978)."""
    store = _store(tmp_path)
    _record_one(store, body=b'{"a":1,"b":2}')

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    spaced = b'{\n  "a": 1,\n  "b": 2\n}\n'
    assert cassette.replay(
        _request(body=spaced), path=PATH, prompt_version=PROMPT_VERSION, live=_exploding_live
    ).hit


@pytest.mark.parametrize(
    ("what", "kwargs"),
    [
        ("service", {"service": "olmocr-v2"}),
        ("model_key", {"model_key": "0000000000000000"}),
        ("prompt_digest", {"prompt": "transcribe this page, carefully"}),
        ("sampling", {"sampling": {"temperature": 0.7, "top_p": 1.0}}),
        ("payload_digest", {"body": b'{"model":"olmocr","pages":[1,3],"stream":false}'}),
        (
            "contract",
            {"contract": ContractIdentity(seam=Seam.DRIVER_IO_SERVICE, contract_major=2)},
        ),
    ],
)
def test_a_request_differing_in_any_one_keyed_field_misses(
    tmp_path: Path, what: str, kwargs: dict[str, object]
) -> None:
    """All six of :978's fields, one at a time: every variation must refuse to replay.

    A key test that only asserts hits proves the key is wide enough and never that it is narrow
    enough, so every one of the six is varied here.

    WHAT THIS TEST DOES **NOT** PROVE, because a miss is not evidence of a cause: that any
    particular field is in the KEY. Two of the six miss for another reason -- `service` is a
    directory in :980's layout, so a different service reads a different directory whatever the
    digest says, and `contract` is also recorded and re-checked by `_stale_reason`. Both survive
    being removed from the digest with this test green.
    `test_the_key_changes_when_the_service_or_the_contract_changes` is where the key inequality
    :978 actually claims is asserted.
    """
    store = _store(tmp_path)
    _record_one(store)

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    with pytest.raises(QualityError) as caught:
        cassette.replay(
            _request(**kwargs),  # type: ignore[arg-type]
            path=PATH,
            prompt_version=PROMPT_VERSION,
            live=_exploding_live,
        )
    assert "OW-Q-004" in str(caught.value), what
    assert cassette.live_calls == 0, what


def test_a_changed_prompt_version_is_a_miss_and_not_a_hit(tmp_path: Path) -> None:
    """13-quality.md:984, verbatim: a cassette whose `prompt_version` no longer matches the code
    is "a **miss**, not a hit. A stale cassette that silently answers is the worst of both
    worlds." `prompt_version` is NOT among :978's six, so only this check catches it.
    """
    store = _store(tmp_path)
    _record_one(store, prompt_version="v3")

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    with pytest.raises(QualityError) as caught:
        cassette.replay(_request(), path=PATH, prompt_version="v4", live=_exploding_live)
    assert "prompt_version" in str(caught.value)


def test_a_changed_request_path_is_a_miss(tmp_path: Path) -> None:
    """The module's one stated extension past :978, and the reason it is there.

    The six keyed fields carry no path, so two endpoints with the same canonical payload share a
    key. The path is recorded and checked in :984's idiom instead of widening the key recipe.
    """
    store = _store(tmp_path)
    _record_one(store, path="/v1/chat/completions")

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    with pytest.raises(QualityError) as caught:
        cassette.replay(
            _request(), path="/v1/embeddings", prompt_version=PROMPT_VERSION, live=_exploding_live
        )
    assert "path" in str(caught.value)


def test_an_unreadable_committed_file_is_a_miss_and_never_a_crash(tmp_path: Path) -> None:
    """A corrupt fixture degrades to OW-Q-004, which names the file, rather than to a traceback."""
    store = _store(tmp_path)
    _record_one(store)
    committed = store.path_for(SERVICE, _request().key)
    committed.write_bytes(b"{ this is not json")

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    with pytest.raises(QualityError) as caught:
        cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION, live=_exploding_live)
    assert "unreadable record" in str(caught.value)


def test_a_non_json_payload_digests_in_a_different_namespace_from_a_json_one() -> None:
    """Three example pairs that do not collide -- and three examples are all this proves.

    `canonical.py`'s docstring records the failure this prevents: graphrag's `gen_sha512_hash`
    concatenates without a separator, so two different inputs digest the same. A list of pairs
    that happen to differ is a positive example list: it cannot show that no pair collides, and
    all three below still differ with the `encoding` domain separator deleted.
    `test_a_json_body_cannot_collide_with_the_opaque_body_whose_digest_it_spells` carries the
    real claim, with the constructed witness.
    """
    text = b'"abc"'
    assert payload_digest(text) != payload_digest(b"\xff\xfe\x00abc")
    assert payload_digest(b"\xff\xfe\x00abc") == payload_digest(b"\xff\xfe\x00abc")
    assert payload_digest(b"not json at all") != payload_digest(b"not json at all!")


# ---------------------------------------------------------------------------
# 3. `allow` records, and what it records is reproducible
# ---------------------------------------------------------------------------


def test_allow_records_on_a_miss_at_the_path_the_plan_prints(tmp_path: Path) -> None:
    """13-quality.md:980: `fixtures/cassettes/<service>/<key[:2]>/<key>.json`, one per interaction.

    The layout is asserted as path SEGMENTS against the literal from :980, not against
    `path_for()`'s own composition.
    """
    store = _store(tmp_path)
    cassette = _record_one(store)
    key = _request().key

    assert cassette.recorded == (key,)
    assert cassette.live_calls == 1
    written = store.root / SERVICE / key[:2] / f"{key}.json"
    assert written.is_file()
    assert store.keys() == (key,)


def test_the_same_interaction_records_byte_identical_bytes_on_a_second_run(
    tmp_path: Path,
) -> None:
    """INV-24: a committed artefact is byte-reproducible from inputs it names.

    Two stores under different roots, so the record cannot be carrying its own location.
    """
    first = _store(tmp_path, name="run-one")
    second = _store(tmp_path, name="a-much-longer-second-root-name")
    _record_one(first)
    _record_one(second)

    key = _request().key
    left = (first.root / SERVICE / key[:2] / f"{key}.json").read_bytes()
    right = (second.root / SERVICE / key[:2] / f"{key}.json").read_bytes()
    assert left == right
    assert left.endswith(b"\n")


def test_the_recorded_bytes_carry_no_filesystem_path_and_no_windows_separator(
    tmp_path: Path,
) -> None:
    """The "different machine" axis, as far as one machine can observe it.

    A record that embedded its own root would be reproducible on one machine and not on the
    next, so the absence of this run's root is what is asserted -- in its native spelling, in
    its POSIX spelling, and (where the platform has one) as the bare drive letter. On Windows
    the native spelling carries the backslashes, which is the only sense in which a separator is
    checked: NO assertion here looks for a stray `\\` on its own, because a JSON-escaped
    backslash inside a legitimately recorded body is indistinguishable from a leaked one at the
    byte level. A genuinely different machine is CI's to check.
    """
    store = _store(tmp_path)
    _record_one(store)
    key = _request().key
    raw = (store.root / SERVICE / key[:2] / f"{key}.json").read_bytes()

    assert bytes(str(tmp_path), "utf-8") not in raw
    assert bytes(tmp_path.as_posix(), "utf-8") not in raw
    # The Windows-only half, asserted only where it can be observed: a leaked root shows up as a
    # drive letter. On POSIX `.drive` is "" and `b"" not in raw` would be vacuously false, which
    # is the shape that passes for the wrong reason -- so it is guarded rather than written flat.
    if tmp_path.drive:
        assert bytes(tmp_path.drive, "utf-8") not in raw


def test_the_record_is_identical_across_two_fresh_interpreters_with_shuffled_inputs(
    interpreter: Interpreter,
) -> None:
    """The PYTHONHASHSEED axis, with the only instrument that can answer it.

    Hash randomisation is per-process and on by default at 3.11, so two fresh interpreters have
    two different seeds; the two programs below additionally build the same record from mappings
    inserted in OPPOSITE orders, which is the in-process shape a seed would perturb. `canonical()`
    sorts keys, so both must print the same digest. A same-process comparison could not
    distinguish "sorted" from "happened to agree".
    """
    program = """
import hashlib
from omniweave_core.cassette import Interaction, BodyEncoding, Seam
pairs = [("temperature", 0.0), ("top_p", 1.0), ("seed", 7)]
{shuffle}
record = Interaction(
    key="0" * 64, record_version=1, service="olmocr", model_key="k",
    prompt_digest="p", prompt_version="v3", sampling=dict(pairs),
    payload_digest="d", seam=Seam.DRIVER_IO_SERVICE, contract_major=1,
    path="/v1/chat", status=200,
    request_headers={{"b": "2", "a": "1"}}, request_encoding=BodyEncoding.TEXT,
    request_body="{{}}", response_headers={{"z": "9"}},
    response_encoding=BodyEncoding.TEXT, response_body="ok", latency_ms=41,
)
print(hashlib.sha256(record.encode()).hexdigest())
"""
    forward = interpreter.run(program.format(shuffle="# insertion order as written"))
    reversed_ = interpreter.run(program.format(shuffle="pairs.reverse()"))
    assert forward.strip() == reversed_.strip()
    assert len(forward.strip()) == 64


def test_a_recording_over_the_per_file_cap_is_refused_at_record_time_and_writes_nothing(
    tmp_path: Path,
) -> None:
    """13-quality.md:614-617: over `MAX_CASSETTE_BYTES` is refused AT RECORD TIME with OW-Q-017,
    and "the fix is a smaller fixture, not a bigger cap". 262,144 is written here as a literal.
    """
    store = _store(tmp_path)
    cassette = Cassette(mode=CassetteMode.ALLOW, store=store)
    huge = b'{"text":"' + b"x" * 300_000 + b'"}'
    assert len(huge) > 262_144

    with pytest.raises(QualityError) as caught:
        cassette.replay(
            _request(),
            path=PATH,
            prompt_version=PROMPT_VERSION,
            request_body=BODY,
            live=lambda: _canned_live(huge),
        )
    assert "OW-Q-017" in str(caught.value)
    assert caught.value.fix == "re-record against a smaller fixture"
    assert cassette.recorded == ()
    assert store.keys() == ()
    assert store.total_bytes() == 0


def test_a_response_that_is_not_utf8_round_trips_byte_exactly(tmp_path: Path) -> None:
    """A driver that hashes its response must receive what was recorded, byte for byte."""
    store = _store(tmp_path)
    blob = b"\x89PNG\r\n\x1a\n\xff\x00\xfe"
    _record_one(store, response=blob)

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    recording = cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION)
    assert recording.interaction.response_bytes() == blob
    assert recording.interaction.response_encoding.value == "base64"


def test_a_record_survives_an_encode_decode_round_trip(tmp_path: Path) -> None:
    """The codec's own algebra: `decode(encode(x)) == x` over a real recording."""
    store = _store(tmp_path)
    _record_one(store)
    committed = store.path_for(SERVICE, _request().key)
    once = Interaction.decode(committed.read_bytes())
    assert Interaction.decode(once.encode()) == once
    assert once.encode() == committed.read_bytes()


def test_the_codec_touches_no_clock_no_socket_and_no_subprocess(
    tmp_path: Path, pure_unit: None
) -> None:
    """13-quality.md section 2.7's T1 guard, armed over a full record-then-replay cycle.

    `pure_unit` makes `time.time`, `socket.socket` and `subprocess.Popen`/`run` raise. A codec
    that reached for a wall clock to stamp `latency_ms` would fail here, which is the assertion
    behind "clocks are parameters".

    TWO THINGS ARE SAID EXACTLY, because "nothing happened" is also what a disarmed fixture
    proves. First the guard is shown to fire -- for `time.time` and `socket.socket`, the two of
    the three this file may name; TID251 bans the word `subprocess` outside S2 and S4, so the
    third guard's arming is asserted by `tools/gate_core_pure.py`'s corpus and not here -- so
    the clean run below means the codec did not reach any of them rather than that the
    monkeypatch missed. Second the shortfall: the
    fixture's fourth guard, `builtins.open`, does NOT reach this codec at all. Every read and
    write here goes through `pathlib`, and `Path.open` calls `io.open` -- a module attribute
    that is a second reference to the same builtin and is untouched by a patch of
    `builtins.open`. So the "no file outside `tmp_path`" half of section 2.7 is asserted on no
    platform by this test; the codec's filesystem reach is instead bounded structurally, by
    `CassetteStore.root` being the only path it composes and `_check_service`/`_check_key`
    refusing every escape from it (the traversal test above).
    """
    assert pure_unit is None
    with pytest.raises(AssertionError, match=r"reached time\.time"):
        time.time()
    with pytest.raises(AssertionError, match=r"reached socket\.socket"):
        socket.socket()

    store = _store(tmp_path)
    _record_one(store)
    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    assert cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION).hit


# ---------------------------------------------------------------------------
# 4. The modelserver seam: a named, tested absence
# ---------------------------------------------------------------------------


def test_the_modelserver_module_exists_and_the_second_seam_is_wired(
    sources: SourceIndex,
) -> None:
    """The tripwire, inverted. It fired at P4 W4.9b and this is what it asked for.

    It read: *"This is a tripwire: when W4.9 lands the module, this test goes red and the person
    landing it is the person who must wire the second seam."* The module landed;
    `intercept_modelserver()` wraps `ServiceRegistry.handle`; `ContractIdentity.for_modelserver()`
    returns `modelserver.SERVICE_API_MAJOR` instead of raising; and `seam_coverage()` reports both
    channels enforced, which is 13-quality.md:972's *"coverage is complete by construction"*
    becoming a fact rather than an aspiration.

    Still read off the source tree rather than with `importlib.util.find_spec`, because `find_spec`
    imports the parent package and `omniweave_core`'s nine lazy names (G17) are exactly what a test
    must not disturb.
    """
    core = sources.distribution("omniweave-core").src / "omniweave_core"
    assert (core / "modelserver.py").is_file()
    assert (core / "cassette.py").is_file()
    assert all(row.enforced for row in seam_coverage())


def test_the_second_seams_contract_major_is_declared_and_not_invented() -> None:
    """13-quality.md:979: *"the model server's declared API major."* `modelserver` declares it.

    It raised until W4.9b because *"a placeholder integer here would be a fabricated contract
    identity inside a cache key, which is the worst place for one"* -- so the test that it is NOT a
    placeholder is that it is derived from the route the transport actually calls.
    """
    identity = ContractIdentity.for_modelserver()
    assert identity.seam is Seam.MODELSERVER
    assert identity.contract_major == SERVICE_API_MAJOR
    assert MODELS_PATH.startswith(f"/v{SERVICE_API_MAJOR}/")


def test_the_two_seams_carry_two_different_contract_identities() -> None:
    """*"It is in the key so a seam change invalidates every recording made against it."*"""
    assert ContractIdentity.for_driver_io() != ContractIdentity.for_modelserver()
    assert ContractIdentity.for_driver_io().seam is Seam.DRIVER_IO_SERVICE


def test_coverage_is_two_of_two_channels_and_says_which() -> None:
    """The claim the work item's estimation basis rests on, asserted as it actually stands.

    16-roadmap.md:487 prices W3.7 at 2 ew on "two interception points, so coverage is complete by
    construction". **At P3 one of the two existed**, and this test asserted `all(enforced)` was
    FALSE with the modelserver row named as the uncovered one -- a closed set pinned in both
    directions rather than a single row checked. W4.9b landed `omniweave_core.modelserver` and
    wired `intercept_modelserver()`, so the claim is now a fact and this is the assertion that it
    is: both rows, both enforced, and the row order still the plan's.
    """
    rows = seam_coverage()
    assert [row.seam.value for row in rows] == ["driver_io.service", "modelserver"]
    assert [row.enforced for row in rows] == [True, True]
    assert all(row.enforced for row in rows)
    assert [row for row in rows if not row.enforced] == []
    assert rows[1].note == "intercept_modelserver() wraps ServiceRegistry.handle"


def test_the_two_seam_spellings_come_from_the_plan_line_that_defines_them(
    plan: PlanDocs,
) -> None:
    """13-quality.md:979: `seam in {"driver_io.service", "modelserver"}`. Both, and no third."""
    plan.require()
    hits = plan.grep(r'seam ∈ \{"driver_io\.service", "modelserver"\}', documents=["13-quality.md"])
    assert len(hits) == 1, hits
    assert hits[0].line == 979
    assert sorted(member.value for member in Seam) == ["driver_io.service", "modelserver"]


# ---------------------------------------------------------------------------
# The three modes, the store layout, and redaction
# ---------------------------------------------------------------------------


def test_the_three_modes_are_exactly_the_plan_s_three(plan: PlanDocs) -> None:
    """13-quality.md:982 and 16-roadmap.md:487's `--cassette off|allow|required`. Three."""
    assert sorted(member.value for member in CassetteMode) == ["allow", "off", "required"]
    plan.require()
    hits = plan.grep(r"--cassette off\\\|allow\\\|required", documents=["16-roadmap.md"])
    assert len(hits) == 1, hits
    assert hits[0].line == 487


def test_off_does_not_read_or_write_a_store_that_holds_the_very_recording_asked_for(
    tmp_path: Path,
) -> None:
    """13-quality.md:982: `off` is "no interception". Nothing is consulted and nothing is left.

    THE STORE IS POPULATED FIRST, AND WITH THIS EXACT KEY. Run against an empty store the whole
    assertion is over empty collections: a codec that consulted the cassette under `off` would
    find nothing there and fall through to the live channel anyway, so `hits == ()` and
    `keys() == ()` would hold for a mode that read the store on every call. Here the committed
    recording says `"recorded"` and the live channel says `"live"`, so which bytes come back is
    the observation, and the committed file's bytes are compared before and after to see that
    `off` also wrote nothing over them.
    """
    store = _store(tmp_path)
    _record_one(store, response=b'{"text":"recorded"}')
    committed = store.path_for(SERVICE, _request().key)
    before = committed.read_bytes()

    cassette = Cassette(mode=CassetteMode.OFF, store=store)
    recording = cassette.replay(
        _request(),
        path=PATH,
        prompt_version=PROMPT_VERSION,
        request_body=BODY,
        live=lambda: _canned_live(b'{"text":"live"}'),
    )
    assert recording.interaction.response_bytes() == b'{"text":"live"}'
    assert recording.live is True
    assert recording.hit is False
    assert recording.recorded is False
    assert cassette.live_calls == 1
    assert cassette.recorded == ()
    assert cassette.hits == ()
    assert cassette.usage_rows() == ()
    assert store.keys() == (_request().key,)
    assert committed.read_bytes() == before


def test_the_hit_ledger_is_sorted_unique_and_names_the_orphans(tmp_path: Path) -> None:
    """13-quality.md:622: the jobs write every cassette key that was HIT, "generated, sorted".

    A runner is the rows it leaves behind. Two recordings and one replayed key means exactly one
    usage row and exactly one orphan -- the assertion is over a non-empty collection in both
    directions, because an assertion over an empty one passes and proves nothing.
    """
    store = _store(tmp_path)
    _record_one(store, body=b'{"a":1}')
    _record_one(store, body=b'{"a":2}')
    assert len(store.keys()) == 2

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    for _ in range(3):
        cassette.replay(_request(body=b'{"a":1}'), path=PATH, prompt_version=PROMPT_VERSION)

    hit = _request(body=b'{"a":1}').key
    missed = _request(body=b'{"a":2}').key
    assert cassette.usage_rows() == (hit,)
    assert cassette.orphans() == (missed,)
    assert sorted(cassette.usage_rows() + cassette.orphans()) == sorted(store.keys())


@pytest.mark.parametrize(
    "service",
    ["../../etc", "a/b", "a\\b", "..", ".", "", "Olmocr", "OLMOCR", "a" * 65],
)
def test_an_unsafe_or_uppercase_service_name_is_refused_before_a_path_is_composed(
    tmp_path: Path, service: str
) -> None:
    """The one place a caller-supplied string becomes a filesystem path.

    The traversal cases are security; the two capitalised cases are the Windows shortfall the
    module docstring states -- a repository shared between a case-sensitive and a
    case-insensitive filesystem cannot hold both `olmocr/` and `Olmocr/`, so the ambiguity is
    refused at record time rather than resolved differently per developer.
    """
    with pytest.raises(ValueError, match="safe lowercase path segment"):
        _store(tmp_path).path_for(service, "0" * 64)


def test_a_key_that_is_not_sixty_four_lowercase_hex_is_refused(tmp_path: Path) -> None:
    """A key is `sha256_canonical`'s output and never a caller-chosen name."""
    store = _store(tmp_path)
    for bad in ("0" * 63, "0" * 65, "A" * 64, "../" + "0" * 61, "g" * 64):
        with pytest.raises(ValueError, match="64 lowercase hex"):
            store.path_for(SERVICE, bad)


def test_credential_headers_are_digested_and_ordinary_headers_are_not() -> None:
    """13-quality.md:981: "API keys, `Authorization` headers ... replaced by their sha256".

    The `content-type` row is the negative control: a redactor that digested everything would
    pass a positive-only assertion and destroy the diff the recording exists to make reviewable.
    """
    redacted = redact_headers(
        {
            "Authorization": "Bearer sk-live-secret",
            "X-Api-Key": "sk-another-secret",
            "x-session-token": "opaque",
            "content-type": "application/json",
            "accept": "*/*",
        }
    )
    assert set(redacted) == {
        "Authorization",
        "X-Api-Key",
        "x-session-token",
        "content-type",
        "accept",
    }
    for name in ("Authorization", "X-Api-Key", "x-session-token"):
        assert redacted[name].startswith("sha256:")
        assert len(redacted[name]) == len("sha256:") + 64
        assert "secret" not in redacted[name]
        assert "opaque" not in redacted[name]
    assert redacted["content-type"] == "application/json"
    assert redacted["accept"] == "*/*"


def test_a_dpa_ref_is_digested_at_any_depth_and_nothing_else_is() -> None:
    """13-quality.md:981's third clause. `licence.py:1150` owns the other side of the line."""
    before = {
        "grant": {"dpa_ref": "DPA-2026-0001", "holder": "acme"},
        "parts": [{"dpa_ref": "DPA-2026-0002"}, {"note": "keep me"}],
        "dpa_ref_note": "not the key",
    }
    after = redact_payload(before)
    assert isinstance(after, dict)
    assert after["grant"]["dpa_ref"].startswith("sha256:")
    assert after["grant"]["holder"] == "acme"
    assert after["parts"][0]["dpa_ref"].startswith("sha256:")
    assert after["parts"][1] == {"note": "keep me"}
    assert after["dpa_ref_note"] == "not the key"
    assert "DPA-2026-0001" not in json.dumps(after)
    assert "DPA-2026-0002" not in json.dumps(after)


def test_a_recorded_request_body_carries_the_digest_and_not_the_dpa_ref(tmp_path: Path) -> None:
    """Redaction reaches the committed bytes, which is the only place it matters."""
    store = _store(tmp_path)
    body = b'{"grant":{"dpa_ref":"DPA-2026-0001"},"pages":[1]}'
    _record_one(store, body=body, headers={"Authorization": "Bearer sk-secret"})
    raw = store.path_for(SERVICE, _request(body=body).key).read_bytes()
    assert b"DPA-2026-0001" not in raw
    assert b"sk-secret" not in raw
    assert b"sha256:" in raw


def test_a_replay_handle_offers_no_token_and_no_dialable_base_url(tmp_path: Path) -> None:
    """A replay has no 0600 sentinel, so it has no token; `cassette://` is not `http://`.

    A fabricated `http://127.0.0.1:0` would be a lie that looked dialable, and INV-7's "a driver
    never forges provenance" reads the same way for its recorder.
    """
    handle = replay_handle(
        name=SERVICE,
        cassette=Cassette(mode=CassetteMode.REQUIRED, store=_store(tmp_path)),
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
    )
    assert handle.token == ""
    assert handle.base_url == "cassette://olmocr"
    assert not handle.base_url.startswith("http")
    assert handle.cancelled() is False


def test_the_handle_carries_every_attribute_a_service_handle_protocol_declares() -> None:
    """`omniweave_ports/types.py:293`'s surface, written out here rather than reflected.

    A driver is handed this object in place of the host's, so a missing member is an
    `AttributeError` inside third-party code. Counted off the Protocol body: **eight
    attributes** (`name` at :305 through `deadline_ms` at :312) and **two methods** (`post` at
    :314, `cancelled` at :318) -- ten members, of which the eight attributes are asserted by
    name below and the two callables after them.
    """
    handle = replay_handle(
        name=SERVICE,
        cassette=Cassette(mode=CassetteMode.REQUIRED, store=CassetteStore(root=Path())),
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
    )
    for member in (
        "name",
        "base_url",
        "token",
        "model_id",
        "model_rev",
        "capacity",
        "traceparent",
        "deadline_ms",
    ):
        assert hasattr(handle, member), member
    assert callable(handle.post)
    assert callable(handle.cancelled)


def test_encode_body_and_decode_body_are_inverses_over_both_encodings() -> None:
    """Two encodings, both exact. `text` is what makes a prompt diff readable at all."""
    from omniweave_core.cassette import decode_body  # noqa: PLC0415 -- see the module docstring.

    for body, expected in (
        (b'{"a":1}', "text"),
        ("café — über".encode(), "text"),
        (b"\xff\xfe\x00", "base64"),
        (b"", "text"),
    ):
        encoding, payload = encode_body(body)
        assert encoding.value == expected, body
        assert decode_body(encoding, payload) == body


# ---------------------------------------------------------------------------
# The register gap
# ---------------------------------------------------------------------------


def test_codes_toml_still_carries_no_ow_q_row_which_is_the_gap_this_module_reports(
    repo_root: Path,
) -> None:
    """A TRIPWIRE on a register gap, and it is meant to go red when the gap is closed.

    `codes.toml` declares an `[area.Q]` table (`error_class = "QualityError"`, `covers =
    "quality, cassette, eval"`) and not one `OW-Q-*` row, so `OW-Q-004` and `OW-Q-017` have
    nothing to resolve against. NOBODY here may append to that register (rule 4), so the codec
    raises `QualityError` with the class default symbol and puts the numeric in the message.

    When the integration agent appends the two rows named in this module's report, this test must
    be replaced by one that asserts the symbol resolves -- which is the point of failing rather
    than of tolerating both states.
    """
    register = tomllib.loads((repo_root / "codes.toml").read_text(encoding="utf-8"))
    areas = register["area"]
    numerics = [str(row["numeric"]) for row in register["code"]]

    assert "Q" in areas
    assert areas["Q"]["error_class"] == "QualityError"
    assert [n for n in numerics if n.startswith("OW-Q-")] == []
    assert len(numerics) == len(set(numerics))


def test_the_untrusted_wrapper_clause_of_the_redaction_rule_is_a_stated_shortfall(
    plan: PlanDocs, tmp_path: Path
) -> None:
    """13-quality.md:981's FIRST clause is not implemented, and this pins it as a fact.

    :981 reads "recorded through the same `<ow:untrusted>` wrapper the runtime uses, with API
    keys, `Authorization` headers and any `Grant` `dpa_ref` replaced by their sha256 before
    write." The three sha256 replacements are done (the two tests above). The wrapper is not, and
    cannot be: 14-security.md:597 puts `<ow:untrusted>` in `omniweave_core.answer.untrusted`,
    which is one of G17's nine LAZY names, and wrapping a recorded body would stop
    `response_bytes()` returning what the service sent.

    Three assertions, because the shortfall has three parts: the plan clause exists, the codec
    says it is unimplemented, and the observable consequence is that recorded bytes carry no
    wrapper while still round-tripping exactly. A test asserting only the constant would pin a
    boolean against itself.
    """
    plan.require()
    hits = plan.grep(
        r"recorded through the same `<ow:untrusted>` wrapper", documents=["13-quality.md"]
    )
    assert len(hits) == 1, hits
    assert hits[0].line == 981

    assert UNTRUSTED_WRAPPER_APPLIED is False

    store = _store(tmp_path)
    body = b'{"grant":{"dpa_ref":"DPA-2026-0001"},"prompt":"x"}'
    _record_one(store, body=body, response=b'{"text":"plain bytes"}')
    raw = store.path_for(SERVICE, _request(body=body).key).read_bytes()
    assert b"ow:untrusted" not in raw
    assert b"DPA-2026-0001" not in raw
    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    replayed = cassette.replay(_request(body=body), path=PATH, prompt_version=PROMPT_VERSION)
    assert replayed.interaction.response_bytes() == b'{"text":"plain bytes"}'


def test_the_plan_allocates_eighteen_ow_q_numerics_and_gives_none_of_them_a_symbol(
    plan: PlanDocs, repo_root: Path
) -> None:
    """WHY the two rows this module needs cannot be transcribed. The blocking half is `symbol`.

    `codes.toml` requires every row to carry an `OW_SCREAMING_SNAKE` symbol -- "the stored and
    wire form" (`codes.toml:3-4`) -- and all 113 seeded rows have one. The plan allocates
    eighteen `OW-Q-*` numerics, eleven in `_notes/charter.md`'s block and seven in
    13-quality.md's, each with a meaning and a fix and NONE with a symbol. So an integration
    agent appending `OW-Q-004` must invent the one column that is load-bearing, which is a plan
    gap of D9's shape rather than a transcription.

    The count is derived from the two blocks here, not asserted from this docstring: 13-quality's
    own heading says "Seven new `OW-Q-*` codes" and its block prints seven, which agrees.
    """
    plan.require()
    numerics = {
        hit.text.split("OW-Q-")[1][:3]
        for hit in plan.grep(r"^# OW-Q-\d\d\d ", documents=["_notes/charter.md", "13-quality.md"])
    }
    assert len(numerics) == 18, sorted(numerics)
    assert sorted(numerics)[0] == "001"
    assert sorted(numerics)[-1] == "018"

    heading = plan.grep(r"^### 13\.2 Seven new `OW-Q-\*` codes$", documents=["13-quality.md"])
    assert len(heading) == 1
    in_quality = {
        hit.text.split("OW-Q-")[1][:3]
        for hit in plan.grep(r"^# OW-Q-\d\d\d ", documents=["13-quality.md"])
    }
    assert len(in_quality) == 7, sorted(in_quality)

    symbol_bearing = plan.grep(
        r"OW-Q-\d\d\d.*OW_[A-Z][A-Z_]+", documents=["_notes/charter.md", "13-quality.md"]
    )
    assert symbol_bearing == (), symbol_bearing

    register = tomllib.loads((repo_root / "codes.toml").read_text(encoding="utf-8"))
    assert len(register["code"]) == 113
    assert all(str(row["symbol"]).isupper() for row in register["code"])


def test_the_module_imports_nothing_a_gate_forbids_and_no_lazy_core_name(
    sources: SourceIndex,
) -> None:
    """The import set as a pinned literal -- the assertion that catches a future edit.

    INV-2 (stdlib only), G23 (no `asyncio`, no `selectors`), INV-17 (`sqlite3` under `store/`
    only), G8/S2/S4 (`subprocess` in two named homes), the ban on `time.time` and `random` in
    library code, and G17 are ALL one assertion here: this set and no other.

    **`omniweave_core.modelserver` is in the set at P4 W4.9b, and only at function scope.** It is
    one of the nine lazy names, so an eager module may not name it at module scope -- a bare
    `import omniweave_core.cassette` must not load the model server client. The second assertion
    below is that rule, checked against the import SITE rather than trusted: `for_modelserver()`
    imports it inside the method, which is why the module-scope set is unchanged from P3.
    """
    path = sources.distribution("omniweave-core").src / "omniweave_core" / "cassette.py"
    sites = sources.imports(path)
    modules = {site.module for site in sites}
    lazy = [site for site in sites if site.module.startswith("omniweave_core.modelserver")]
    assert len(lazy) == 1, "one site, and it is ContractIdentity.for_modelserver()"
    indented = (
        (sources.distribution("omniweave-core").src / "omniweave_core" / "cassette.py")
        .read_text(encoding="utf-8")
        .splitlines()[lazy[0].line - 1]
    )
    assert indented.startswith(" "), "a module-scope import would load a lazy name at import time"
    modules.discard("omniweave_core.modelserver")
    assert modules == {
        "__future__",
        "base64",
        "binascii",
        "collections.abc",
        "dataclasses",
        "enum",
        "hashlib",
        "json",
        "omniweave_core.canonical",
        "omniweave_core.contract",
        "omniweave_core.errors",
        "omniweave_core.limits",
        "omniweave_ports.types",
        "pathlib",
        "re",
        "types",
        "typing",
    }


def test_core_s_eager_init_does_not_reach_this_module(sources: SourceIndex) -> None:
    """G17's premise. `cassette.py` is eager-safe only because nothing eager imports it.

    11-repo-layout.md:187 draws `__init__.py` as "EAGER, and it imports nine subpackages: NONE of
    them", and this module is a tenth thing it must also not import: `import omniweave_core` on
    the per-turn hook path pays for every module it touches (G26's 250 ms p95).
    """
    init = sources.distribution("omniweave-core").src / "omniweave_core" / "__init__.py"
    assert "cassette" not in init.read_text(encoding="utf-8")


class _StubUpstream:
    """A minimal live `ServiceHandle` stand-in: eight attributes, `post` and `cancelled`.

    Not a `DriverIO` and not a subclass of anything -- `ServiceHandle` is a Protocol
    (`omniweave_ports/types.py:293`), so the stand-in is structural, which is also the only way
    a test can supply a live channel without a listener.
    """

    name = SERVICE
    base_url = "http://127.0.0.1:9999"
    token = "deadbeef"  # noqa: S105 -- a stand-in for the 0600 sentinel token, not a secret.
    model_id = "allenai/olmOCR-7B"
    model_rev = "r7"
    capacity = 2
    traceparent = "00-0af7-0000-01"
    deadline_ms = 30_000

    def __init__(self, body: bytes, *, cancelled: bool = False) -> None:
        self.body = body
        self.calls: list[tuple[str, bytes]] = []
        self._cancelled = cancelled

    def post(self, path: str, body: bytes, *, headers: Mapping[str, str] | None = None) -> bytes:
        self.calls.append((path, body))
        assert headers is not None or headers is None
        return self.body

    def cancelled(self) -> bool:
        return self._cancelled


def test_allow_through_the_seam_wrapper_records_once_and_replays_thereafter(
    tmp_path: Path,
) -> None:
    """The end-to-end `allow` path: `intercept_service` -> `CassetteHandle.post` -> record.

    The second `post()` must NOT reach the upstream: that is the whole economic argument, and
    `upstream.calls` counts it rather than trusting the mode. `status` is `0` in the record and
    not a fabricated `200`, because `ServiceHandle.post` reports no status
    (`omniweave_ports/types.py:314`) and INV-7's "never forges provenance" reads the same way for
    a recorder.
    """
    store = _store(tmp_path)
    upstream = _StubUpstream(b'{"text":"live once"}')
    cassette = Cassette(mode=CassetteMode.ALLOW, store=store)
    wrapped = intercept_service(
        lambda _name: upstream,  # type: ignore[arg-type,return-value]
        cassette=cassette,
        model_key=MODEL_KEY,
        prompt_digest=prompt_digest(PROMPT),
        prompt_version=PROMPT_VERSION,
        sampling=SAMPLING,
    )

    handle = wrapped(SERVICE)
    assert handle.model_id == "allenai/olmOCR-7B"
    assert handle.deadline_ms == 30_000
    live_bytes = handle.post(PATH, BODY, headers={"Authorization": "Bearer sk-x"})
    assert live_bytes == b'{"text":"live once"}'
    assert len(upstream.calls) == 1
    assert cassette.recorded == (_request().key,)

    assert wrapped(SERVICE).post(PATH, BODY) == b'{"text":"live once"}'
    assert len(upstream.calls) == 1
    assert cassette.live_calls == 1

    raw = store.path_for(SERVICE, _request().key).read_bytes()
    assert b'"status":0' in raw
    assert b"sk-x" not in raw


# ---------------------------------------------------------------------------
# Added by the adversarial verification pass: fifteen properties that were
# asserted by no test, each one found by breaking the codec and watching the
# file stay green. The mutation each kills is named in its docstring.
# ---------------------------------------------------------------------------


def test_the_key_changes_when_the_service_or_the_contract_changes(tmp_path: Path) -> None:
    """`service` and `contract` are IN THE KEY (13-quality.md:978), which no miss can show.

    Both survive deletion from the digest with the whole file green, because both have a second
    mechanism that produces a miss on its own: `service` is a directory in :980's layout, so a
    request for another service reads another directory whatever the digest says, and `contract`
    is recorded in the file and re-checked by `_stale_reason`. The claim :978 makes is that the
    KEY differs, so the key is what is compared.

    The `contract` half is the one that matters, and the reason is in :979: the pair is in the
    key *"so a seam change invalidates every recording made against the old one"*. Out of the
    key, a `driver_io.service` recording and a `modelserver` recording of the same other five
    fields share ONE filename -- so the store cannot hold both, and under `allow` each
    re-record silently overwrites the other. That is asserted here as distinct paths, which is
    the form the damage takes on disk.
    """
    baseline = _request()
    other_service = _request(service="olmocr-v2")
    other_seam = _request(contract=ContractIdentity(seam=Seam.MODELSERVER, contract_major=1))
    other_major = _request(contract=ContractIdentity(seam=Seam.DRIVER_IO_SERVICE, contract_major=2))

    assert baseline.key != other_service.key
    assert baseline.key != other_seam.key
    assert baseline.key != other_major.key
    assert len({baseline.key, other_service.key, other_seam.key, other_major.key}) == 4

    store = _store(tmp_path)
    assert store.path_for(SERVICE, baseline.key) != store.path_for(SERVICE, other_seam.key)
    assert store.path_for(SERVICE, baseline.key) != store.path_for(SERVICE, other_major.key)


def test_the_key_is_this_literal_and_the_same_in_a_fresh_interpreter(
    interpreter: Interpreter,
) -> None:
    """The digest itself, pinned as a literal, computed twice in two processes.

    A record-then-replay test cannot see a per-process input in the key recipe: both sides
    compute the key in the same interpreter, so they agree on whatever value that process
    produced. A salt as ordinary as `hash("cassette")` -- PYTHONHASHSEED-randomised, needing no
    import a gate would notice -- leaves every test in this file green while making every
    committed cassette in `fixtures/cassettes/` miss on every CI run. Under `required` that is
    `OW-Q-004` for the entire corpus.

    So the key is pinned twice against ONE written-out literal: once in this process, and once
    in a fresh interpreter with its own hash seed. `contract_major` is written as `1` rather
        than taken from `CONTRACT` so the literal pins the recipe and not the contract; the
    separate assertion below is what ties `for_driver_io()` to :979's `omniweave_core.contract.
    CONTRACT`, and a contract bump is meant to change the key -- that is :979's whole reason for
    putting the pair in it.
    """
    expected = "84247095870033ead295f1e6aac78347463f3cf234f2face98a695a50b8e19f5"
    request = Request(
        service="olmocr",
        model_key="9f2c1ab4de5670f1",
        prompt_digest=prompt_digest("transcribe this page"),
        sampling={"temperature": 0.0, "top_p": 1.0},
        payload_digest=payload_digest(b'{"model":"olmocr","pages":[1,2],"stream":false}'),
        contract=ContractIdentity(seam=Seam.DRIVER_IO_SERVICE, contract_major=1),
    )
    assert request.key == expected

    program = """
from omniweave_core.cassette import (
    ContractIdentity, Request, Seam, payload_digest, prompt_digest,
)
print(
    Request(
        service="olmocr",
        model_key="9f2c1ab4de5670f1",
        prompt_digest=prompt_digest("transcribe this page"),
        sampling={"temperature": 0.0, "top_p": 1.0},
        payload_digest=payload_digest(b'{"model":"olmocr","pages":[1,2],"stream":false}'),
        contract=ContractIdentity(seam=Seam.DRIVER_IO_SERVICE, contract_major=1),
    ).key
)
"""
    assert interpreter.run(program).strip() == expected

    assert ContractIdentity.for_driver_io() == (Seam.DRIVER_IO_SERVICE, CONTRACT)


def test_the_seam_constants_say_which_half_is_enforced_and_which_is_pending(
    plan: PlanDocs,
) -> None:
    """`SEAMS`, `SEAMS_ENFORCED` and `SEAMS_PENDING` -- the coverage claim AS DATA, and unpinned.

    `test_coverage_is_two_of_two_channels_and_says_which` asserts `seam_coverage()`'s rows and
    nothing else, so all three constants can be wrong -- `SEAMS_ENFORCED` can name
    `MODELSERVER`, `SEAMS_PENDING` can be empty, `SEAMS` can be reversed -- with the file green.
    They are the machine-readable form of the module's central claim, which makes them the form
    a report or a later gate will read.

    Pinned in both directions, because a closed set pinned against one excluded member is
    pinned against nothing: each set is compared for equality, the two are asserted disjoint,
    and their union is asserted to be exactly `SEAMS`. The ORDER of `SEAMS` is pinned against
    13-quality.md:979's own printed order rather than against itself, since ours would otherwise
    be an order we chose and nothing checked.
    """
    plan.require()
    hits = plan.grep(r'seam ∈ \{"driver_io\.service", "modelserver"\}', documents=["13-quality.md"])
    assert len(hits) == 1, hits
    printed = hits[0].text
    assert printed.index('"driver_io.service"') < printed.index('"modelserver"')

    assert [member.value for member in SEAMS] == ["driver_io.service", "modelserver"]
    assert sorted(member.value for member in SEAMS_ENFORCED) == [
        "driver_io.service",
        "modelserver",
    ]
    assert frozenset() == SEAMS_PENDING, "W4.9b wired the second seam; nothing is pending"
    assert not SEAMS_ENFORCED & SEAMS_PENDING
    assert sorted(member.value for member in SEAMS_ENFORCED | SEAMS_PENDING) == sorted(
        member.value for member in SEAMS
    )

    rows = {row.seam: row.enforced for row in seam_coverage()}
    assert {seam for seam, enforced in rows.items() if enforced} == set(SEAMS_ENFORCED)
    assert {seam for seam, enforced in rows.items() if not enforced} == set(SEAMS_PENDING)


def test_the_committed_store_root_is_the_directory_the_plan_prints(plan: PlanDocs) -> None:
    """`CASSETTE_ROOT` is a transcription of 13-quality.md:980, and it was read by no test.

    Nothing in this file used the constant, so `fixtures/cassette` -- one character out, and the
    directory `Q-G1`'s manifest sweep and `Q-G2`'s orphan sweep both read -- was green.
    Asserted against the plan line that owns the layout, and against 11-repo-layout.md:385's
    tree row, rather than against the module's own composition.
    """
    plan.require()
    hits = plan.grep(
        r"`fixtures/cassettes/<service>/<key\[:2\]>/<key>\.json`", documents=["13-quality.md"]
    )
    assert len(hits) == 1, hits
    assert hits[0].line == 980
    assert CASSETTE_ROOT == "fixtures/cassettes"
    assert f"`{CASSETTE_ROOT}/<service>/<key[:2]>/<key>.json`" in hits[0].text

    tree = plan.grep(r"^├── docs/  office-200/  cassettes/", documents=["11-repo-layout.md"])
    assert len(tree) == 1, tree
    assert tree[0].line == 385


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("key", "f" * 64, "stored key"),
        ("record_version", 2, "record_version"),
        ("prompt_version", "v99", "prompt_version"),
        ("seam", "modelserver", "seam"),
        ("contract_major", 99, "contract_major"),
        ("path", "/v1/embeddings", "path"),
    ],
)
def test_a_hand_edited_field_in_a_committed_record_is_a_miss_that_names_it(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    """All six of `_stale_reason`'s checks, each edited AT ITS COMMITTED FILENAME.

    13-quality.md:984: a cassette that no longer matches the code is *"a **miss**, not a hit. A
    stale cassette that silently answers is the worst of both worlds"*. Four of the six checks
    were unasserted, and each could be deleted with the file green:

    * `record_version` and `seam` -- no test ever wrote a record carrying a foreign value, so
      neither check had an input.
    * `contract_major` -- masked by the key, which also carries the contract. Note the mutual
      masking: deleting the key's `contract` field is caught by this check and deleting this
      check is caught by the key, so the pair was pinned and neither member was.
    * `key` -- this one was not a test gap but a missing check, and the failure it now catches
      is silent. The lookup is by PATH, so a file's name is all that says it belongs to a key;
      a file whose CONTENTS came from another key's record (a hand-copied fixture, a bad merge)
      replayed the wrong recorded response for the right request, with `hit=True`, under
      `required`.

    Editing the JSON in place is what makes the test honest: the filename stays the requested
    key's, so no variation can be caught by the store layout or by the key, and the check under
    test is the only thing that can produce the miss. The reason substring is asserted so a miss
    for the wrong reason is not a pass.
    """
    store = _store(tmp_path)
    _record_one(store)
    committed = store.path_for(SERVICE, _request().key)
    record = json.loads(committed.read_text(encoding="utf-8"))
    assert record[field] != value, field
    record[field] = value
    committed.write_text(json.dumps(record), encoding="utf-8")

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    with pytest.raises(QualityError) as caught:
        cassette.replay(_request(), path=PATH, prompt_version=PROMPT_VERSION, live=_exploding_live)
    assert "OW-Q-004" in str(caught.value), field
    assert reason in str(caught.value), field
    assert cassette.live_calls == 0, field
    assert cassette.hits == (), field


def test_a_committed_record_carries_these_nineteen_fields_and_every_one_is_required(
    tmp_path: Path,
) -> None:
    """The envelope's field set as literals, and `decode` refusing each absence in turn.

    `RECORD_VERSION` exists so *"a file this codec cannot read is a MISS, never a guess"*, and
    the only unreadable file any test offered was `b"{ this is not json"`. A well-formed JSON
    object missing a field was never tried, so `parsed["x"]` could soften to
    `parsed.get("x", <default>)` on any field with the file green -- and a default is exactly the
    guess the envelope version exists to prevent.

    Nineteen, counted off the record written below rather than off this docstring, and each name
    written out here. Deleting any one must make the record unreadable, which `Cassette.replay`
    reports as a miss naming the file rather than as a traceback (13-quality.md:984 covers an
    unparseable cassette too).
    """
    store = _store(tmp_path)
    _record_one(store)
    committed = store.path_for(SERVICE, _request().key)
    record = json.loads(committed.read_text(encoding="utf-8"))

    assert sorted(record) == [
        "contract_major",
        "key",
        "latency_ms",
        "model_key",
        "path",
        "payload_digest",
        "prompt_digest",
        "prompt_version",
        "record_version",
        "request_body",
        "request_encoding",
        "request_headers",
        "response_body",
        "response_encoding",
        "response_headers",
        "sampling",
        "seam",
        "service",
        "status",
    ]
    assert len(record) == 19
    assert record["record_version"] == 1

    for missing in sorted(record):
        without = {name: item for name, item in record.items() if name != missing}
        committed.write_text(json.dumps(without), encoding="utf-8")
        with pytest.raises(ValueError, match="not a record this codec can read"):
            Interaction.decode(committed.read_bytes())
        cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
        with pytest.raises(QualityError) as caught:
            cassette.replay(
                _request(), path=PATH, prompt_version=PROMPT_VERSION, live=_exploding_live
            )
        assert "unreadable record" in str(caught.value), missing


def test_the_per_file_cap_is_measured_on_the_encoded_file_and_not_on_the_response_body(
    tmp_path: Path,
) -> None:
    """13-quality.md:1896 makes `MAX_CASSETTE_BYTES` bound *one committed Cassette*, not a body.

    `CassetteStore.save`'s docstring argues exactly this -- *"a 250 KiB response inside a 260
    KiB file is over the cap the reviewer actually pays"* -- and that case was asserted nowhere:
    the existing cap test uses a 300,000-byte response, which is over the cap by either
    measurement, so measuring the response body instead of the encoded file left the file green.

    The witness is the case the docstring names. The response body is 262,008 bytes, UNDER the
    262,144 literal; the record it goes into is over it, and the size the error reports is the
    file's. Both numbers are asserted so the test states which one the cap is on.
    """
    store = _store(tmp_path)
    cassette = Cassette(mode=CassetteMode.ALLOW, store=store)
    body = b'{"t":"' + b"y" * 262_000 + b'"}'
    assert len(body) == 262_008
    assert len(body) < 262_144

    with pytest.raises(QualityError) as caught:
        cassette.replay(
            _request(),
            path=PATH,
            prompt_version=PROMPT_VERSION,
            request_body=BODY,
            live=lambda: _canned_live(body),
        )
    message = str(caught.value)
    assert "OW-Q-017" in message
    reported = int(message.split(" is ", maxsplit=1)[1].split(" bytes", maxsplit=1)[0])
    assert reported > 262_144
    assert reported > len(body)
    assert cassette.recorded == ()
    assert store.keys() == ()


def test_a_required_miss_leaves_no_row_in_the_hit_ledger(tmp_path: Path) -> None:
    """13-quality.md:622 makes the T2/T3 jobs write *"every cassette key that was HIT"*.

    The ledger was written before the hit was known: recording the requested key on every
    lookup, hit or miss, left every test in this file green, because no test asked what the
    ledger held after a miss. The consequence is `Q-G2`'s: `eval/cassette-usage.toml` would list
    a key that never replayed, so 13-quality.md:624's asymmetry -- *"an unused one would
    otherwise never fail at all"* -- stops working and an orphan reads as used.

    Both collections are non-empty in both directions: one key hits, one key misses, and the one
    that missed must appear in `orphans()` and not in `usage_rows()`.
    """
    store = _store(tmp_path)
    _record_one(store, body=b'{"a":1}')
    _record_one(store, body=b'{"a":2}', prompt_version="v-old")
    hit = _request(body=b'{"a":1}').key
    missed = _request(body=b'{"a":2}').key
    assert len(store.keys()) == 2

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    assert cassette.replay(_request(body=b'{"a":1}'), path=PATH, prompt_version=PROMPT_VERSION).hit
    with pytest.raises(QualityError):
        cassette.replay(
            _request(body=b'{"a":2}'),
            path=PATH,
            prompt_version=PROMPT_VERSION,
            live=_exploding_live,
        )

    assert cassette.hits == (hit,)
    assert cassette.usage_rows() == (hit,)
    assert cassette.orphans() == (missed,)
    assert missed not in cassette.usage_rows()


def test_the_usage_rows_are_sorted_when_the_hits_arrive_in_descending_order(
    tmp_path: Path,
) -> None:
    """*"generated, sorted, byte-diff gated"* (13-quality.md:622) -- and sorted was unobservable.

    `hits` is first-hit order and `usage_rows()` sorts. Every existing assertion on
    `usage_rows()` holds exactly one key, and a one-element tuple is sorted whatever the code
    does, so dropping the `sorted()` left the file green. Two keys, replayed in the order that
    is WRONG for the committed file, is the smallest input that can tell the two apart -- and
    `hits` is asserted in the opposite order at the same time, because the two properties are
    different and each would otherwise be free.
    """
    store = _store(tmp_path)
    _record_one(store, body=b'{"a":1}')
    _record_one(store, body=b'{"a":2}')
    lower = _request(body=b'{"a":1}').key
    higher = _request(body=b'{"a":2}').key
    assert lower == "166ff47c216e892d69b9ec549c42f4e298ca83ccb74ca01a257b1ff7fec82c83"
    assert higher == "c88d8d8e1f8b5b7f71372fb75897750920875f1d4589c2ca33720291fdb2b545"
    assert lower < higher

    cassette = Cassette(mode=CassetteMode.REQUIRED, store=store)
    for body in (b'{"a":2}', b'{"a":1}'):
        assert cassette.replay(_request(body=body), path=PATH, prompt_version=PROMPT_VERSION).hit

    assert cassette.hits == (higher, lower)
    assert cassette.usage_rows() == (lower, higher)
    assert cassette.orphans() == ()


def test_a_live_backed_handle_reports_its_upstream_cancellation(tmp_path: Path) -> None:
    """`ServiceHandle.cancelled()` is *"True once the generation ... is superseded"* (:318).

    `CassetteHandle.cancelled()` returns False for a replay and delegates for a live-backed
    handle, and only the replay half was asserted -- on `replay_handle()`, whose `live` is
    always None. So `return False` unconditionally was green, and a driver in an `allow` run
    would never learn its generation had been superseded: it would keep posting into a
    cancelled generation and every one of those calls would be recorded.

    All three states are asserted, since a delegation that inverted its answer would satisfy
    any one of them alone.
    """
    superseded = _StubUpstream(b'{"text":"live"}', cancelled=True)
    current = _StubUpstream(b'{"text":"live"}', cancelled=False)

    def handle_over(upstream: _StubUpstream) -> CassetteHandle:
        wrapped = intercept_service(
            lambda _name: upstream,  # type: ignore[arg-type,return-value]
            cassette=Cassette(mode=CassetteMode.ALLOW, store=_store(tmp_path)),
            model_key=MODEL_KEY,
            prompt_digest=prompt_digest(PROMPT),
            prompt_version=PROMPT_VERSION,
        )(SERVICE)
        assert isinstance(wrapped, CassetteHandle)
        return wrapped

    assert handle_over(superseded).cancelled() is True
    assert handle_over(current).cancelled() is False
    assert (
        replay_handle(
            name=SERVICE,
            cassette=Cassette(mode=CassetteMode.REQUIRED, store=_store(tmp_path)),
            model_key=MODEL_KEY,
            prompt_digest=prompt_digest(PROMPT),
            prompt_version=PROMPT_VERSION,
        ).cancelled()
        is False
    )


def test_a_json_body_cannot_collide_with_the_opaque_body_whose_digest_it_spells() -> None:
    """The `encoding` tag in `payload_digest` is a DOMAIN SEPARATOR, and here is the witness.

    Delete the tag and `payload_digest` becomes `sha256_canonical({"body": <parsed>})` for JSON
    and `sha256_canonical({"body": <hex of the bytes>})` for anything else -- so any JSON body
    that parses to the string spelling of another body's sha256 digests identically to that
    body. The three example pairs the older test checks all still differ under that deletion,
    which is what a positive example list can and cannot do.

    So the collision is constructed rather than sampled: `opaque` is not UTF-8, its sha256 is
    written out as a literal below, and `witness` is that hex as a JSON string. Under the
    deletion the two digests are equal; with the tag they are not. Nothing here recomputes the
    subject's answer -- the digest of the input is the test's own arithmetic, and the two values
    compared are the subject's.
    """
    opaque = b"\xff\xfe\x00abc"
    digest_of_opaque = "9de1d6e9599b924cf8498d929d436bc33841915d74741b63212f5f3de1fa513c"
    assert hashlib.sha256(opaque).hexdigest() == digest_of_opaque

    witness = b'"' + digest_of_opaque.encode("ascii") + b'"'
    assert json.loads(witness) == digest_of_opaque
    assert payload_digest(witness) != payload_digest(opaque)


def test_total_bytes_is_the_sum_of_the_committed_files(tmp_path: Path) -> None:
    """13-quality.md:614's 32 MiB store budget is measured here and enforced by `Q-G2`.

    The only assertion on `total_bytes()` was `== 0` on an empty store, which is what
    `return 0` also produces -- so the number the budget gate compares was pinned at the one
    value that proves nothing. Two committed records, and the total is compared against the two
    files' own lengths read back by their plan-shaped paths, not against a second `rglob` with
    the same recipe as the subject's.
    """
    store = _store(tmp_path)
    assert store.total_bytes() == 0
    _record_one(store, body=b'{"a":1}', response=b'{"first":true}')
    _record_one(store, body=b'{"a":2}', response=b'{"second":"a longer response body"}')

    first = _request(body=b'{"a":1}').key
    second = _request(body=b'{"a":2}').key
    sizes = [
        len((store.root / SERVICE / key[:2] / f"{key}.json").read_bytes())
        for key in (first, second)
    ]
    assert all(size > 0 for size in sizes)
    assert sizes[0] != sizes[1]
    assert store.total_bytes() == sum(sizes)


def test_encode_refuses_the_values_canonical_refuses(tmp_path: Path) -> None:
    """`Interaction.encode()` writes through `canonical()`, and only these inputs can show it.

    For a record inside the JSON grammar, `canonical()` and `json.dumps(record, sort_keys=True,
    separators=(",", ":"), ensure_ascii=False)` emit the SAME BYTES -- so every reproducibility
    assertion in this file, the cross-interpreter one included, passes with a second serialiser
    bolted in beside the framework's one canonicaliser. What separates them is a value outside
    the grammar, which `canonical()` refuses and `json.dumps` invents an encoding for:

    * a NaN in `sampling` becomes the bare token `NaN` -- not JSON, though `json.loads` accepts
      it, so the file would round-trip here and be rejected by every other reader;
    * a non-string mapping key becomes its `str()`, so `{1: "a"}` and `{"1": "a"}` commit to the
      same bytes -- `canonical.py`'s own reason for checking the grammar before dumping.

    A refusal at `encode()` is a refusal at record time, so neither reaches a committed file.
    """
    store = _store(tmp_path)

    def record(sampling: Mapping[object, object]) -> Interaction:
        return Interaction(
            key="0" * 64,
            record_version=1,
            service=SERVICE,
            model_key=MODEL_KEY,
            prompt_digest=prompt_digest(PROMPT),
            prompt_version=PROMPT_VERSION,
            sampling=sampling,  # type: ignore[arg-type]
            payload_digest=payload_digest(BODY),
            seam=Seam.DRIVER_IO_SERVICE,
            contract_major=1,
            path=PATH,
            status=0,
            request_headers={},
            request_encoding=BodyEncoding.TEXT,
            request_body="{}",
            response_headers={},
            response_encoding=BodyEncoding.TEXT,
            response_body="ok",
            latency_ms=0,
        )

    with pytest.raises(ValueError, match="no JSON encoding"):
        record({"temperature": float("nan")}).encode()
    with pytest.raises(TypeError, match="mapping key"):
        record({1: "a"}).encode()

    with pytest.raises(ValueError, match="no JSON encoding"):
        store.save(record({"temperature": float("inf")}))
    assert store.keys() == ()
