"""`omniweave_core.host.signals`: a signal provider's computer in a child, both halves (D628).

The child's half, `answer()`, runs here in-process against a provider package written into
`tmp_path`, so every refusal it can make is one test. The parent's half, `compute_in_child()`, is
tested against `run_captured` replaced by a recorder, because what it owns is the reading of a
finished child -- exit, timeout, garbage -- and none of that needs an interpreter to start. The
real child over a real PDF is `test_signals_child.py` in `tests/conform`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.host import signals, subproc
from omniweave_core.host.signals import SignalAnswer, answer, compute_in_child

KEYS = ("unit.part_count", "decode.char_count")

PROVIDER = """
import math

def compute(raw, keys):
    if raw.startswith(b"RAISE"):
        raise RuntimeError("the provider could not read it")
    out = {"unit.part_count": len(raw), "decode.char_count": raw.count(b"x")}
    if raw.startswith(b"ODD"):
        out["decode.char_count"] = [1, 2]
    if raw.startswith(b"NAN"):
        out["decode.char_count"] = math.nan
    return {key: out[key] for key in keys if key in out}
"""


@pytest.fixture
def provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """`ow_fake_provider` with a `signals.py` beside where its `signals.toml` would be."""
    package = tmp_path / "site" / "ow_fake_provider"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "signals.py").write_text(PROVIDER, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    for name in [name for name in sys.modules if name.startswith("ow_fake_provider")]:
        monkeypatch.delitem(sys.modules, name)
    return "ow_fake_provider"


def _request(tmp_path: Path, body: bytes, package: str, **over: Any) -> dict[str, Any]:
    source = tmp_path / "unit.bin"
    source.write_bytes(body)
    request = {
        "package": package,
        "source": str(source),
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "keys": list(KEYS),
    }
    request.update(over)
    return request


# ---------------------------------------------------------------------------------------------
# The child's half
# ---------------------------------------------------------------------------------------------


def test_every_asked_key_the_provider_computes_is_a_value(tmp_path: Path, provider: str) -> None:
    found = answer(_request(tmp_path, b"xxx", provider))
    assert found == SignalAnswer(
        values={"unit.part_count": 3, "decode.char_count": 3}, unavailable={}
    )


def test_a_key_the_provider_does_not_compute_is_unavailable_by_name(
    tmp_path: Path, provider: str
) -> None:
    found = answer(_request(tmp_path, b"x", provider, keys=["unit.part_count", "ink.tiles"]))
    assert found.values == {"unit.part_count": 1}
    assert found.unavailable == {"ink.tiles": "ow_fake_provider.signals does not compute ink.tiles"}


@pytest.mark.parametrize("head", [b"ODD", b"NAN"])
def test_a_value_that_is_not_a_finite_scalar_is_refused(
    tmp_path: Path, provider: str, head: bytes
) -> None:
    found = answer(_request(tmp_path, head, provider))
    assert "decode.char_count" not in found.values
    assert "which is not a finite scalar" in found.unavailable["decode.char_count"]
    assert found.values["unit.part_count"] == len(head)


def test_a_provider_that_raises_answers_every_key_with_its_exception(
    tmp_path: Path, provider: str
) -> None:
    found = answer(_request(tmp_path, b"RAISE", provider))
    assert found.values == {}
    reason = "ow_fake_provider.signals: RuntimeError: the provider could not read it"
    assert found.unavailable == dict.fromkeys(KEYS, reason)


def test_bytes_that_no_longer_hash_to_the_identified_digest_are_not_computed(
    tmp_path: Path, provider: str
) -> None:
    """A value computed over other bytes would enter a read set keyed on the recorded digest."""
    found = answer(_request(tmp_path, b"xxx", provider, content_sha256="0" * 64))
    assert found.values == {}
    assert all("no longer hash" in reason for reason in found.unavailable.values())


def test_an_unreadable_source_and_a_package_that_is_not_a_path_are_refused(
    tmp_path: Path, provider: str
) -> None:
    gone = answer(_request(tmp_path, b"x", provider, source=str(tmp_path / "absent")))
    assert all(
        reason.startswith("the source is unreadable") for reason in gone.unavailable.values()
    )
    bad = answer(_request(tmp_path, b"x", "../escape"))
    assert set(bad.unavailable) == set(KEYS)
    assert all("not a dotted package path" in reason for reason in bad.unavailable.values())


def test_a_package_with_no_computer_is_every_key_s_reason(tmp_path: Path) -> None:
    found = answer(_request(tmp_path, b"x", "json"))
    assert found.values == {}
    assert all("ModuleNotFoundError" in reason for reason in found.unavailable.values())


LOCKED = """
def compute(raw, keys, *, password=None):
    return {"unit.encrypted": password != "right"}
"""


def test_a_password_reaches_a_compute_that_takes_one_and_no_other(
    tmp_path: Path, provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-15 D15.4. `password` in the request is passed as `compute(..., password=)` to a provider
    that takes it; `ow_fake_provider`'s `compute(raw, keys)` takes none and is called as before,
    so a unit a password maps is not refused by a provider that cannot use it."""
    package = tmp_path / "site" / "ow_fake_locked"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "signals.py").write_text(LOCKED, encoding="utf-8")
    for name in [name for name in sys.modules if name.startswith("ow_fake_locked")]:
        monkeypatch.delitem(sys.modules, name)
    keys = ["unit.encrypted"]
    right = answer(_request(tmp_path, b"x", "ow_fake_locked", keys=keys, password="right"))  # noqa: S106 -- a fixture's
    wrong = answer(_request(tmp_path, b"x", "ow_fake_locked", keys=keys, password="wrong"))  # noqa: S106 -- a fixture's
    none = answer(_request(tmp_path, b"x", "ow_fake_locked", keys=keys))
    assert (right.values, wrong.values, none.values) == (
        {"unit.encrypted": False},
        {"unit.encrypted": True},
        {"unit.encrypted": True},
    )
    blind = answer(_request(tmp_path, b"xx", provider, password="right"))  # noqa: S106 -- a fixture's
    assert blind.values == {"unit.part_count": 2, "decode.char_count": 2}


def test_a_reason_is_bounded() -> None:
    long = SignalAnswer.refused(("k.k",), "x" * 5000)
    assert len(long.unavailable["k.k"]) == signals.REASON_MAX_CHARS


# ---------------------------------------------------------------------------------------------
# The parent's half
# ---------------------------------------------------------------------------------------------


class _Recorder:
    def __init__(self, captured: subproc.Captured) -> None:
        self.captured = captured
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: Any, **kwargs: Any) -> subproc.Captured:
        self.calls.append({"argv": tuple(argv), **kwargs})
        return self.captured


def _ask(monkeypatch: pytest.MonkeyPatch, captured: subproc.Captured) -> tuple[SignalAnswer, Any]:
    recorder = _Recorder(captured)
    monkeypatch.setattr(subproc, "run_captured", recorder)
    found = compute_in_child(
        "omniweave_pdf",
        source="/corpus/a.pdf",
        content_sha256="ab" * 32,
        keys=KEYS,
        executable="python",
        cwd="/scratch",
        env={"PATH": "/bin"},
        timeout_s=7.0,
    )
    return found, recorder


def _stdout(values: dict[str, Any], unavailable: dict[str, str]) -> bytes:
    return json.dumps({"values": values, "unavailable": unavailable}).encode()


def test_the_child_is_isolated_python_with_the_request_on_stdin_and_nothing_ambient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`-I`: the first run of this child imported a `struct.py` from the `%TEMP%` it started in."""
    _found, recorder = _ask(monkeypatch, subproc.Captured(0, _stdout({}, {}), b""))
    (call,) = recorder.calls
    assert call["argv"] == ("python", "-I", "-m", signals.SIGNALS_MODULE)
    assert (call["cwd"], call["env"], call["timeout_s"]) == ("/scratch", {"PATH": "/bin"}, 7.0)
    assert json.loads(call["stdin"]) == {
        "package": "omniweave_pdf",
        "source": "/corpus/a.pdf",
        "content_sha256": "ab" * 32,
        "keys": list(KEYS),
    }


def test_a_password_rides_in_the_request_on_stdin_and_nowhere_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D15.4: *"a field of the request on the child's stdin, never argv and never environment"*."""
    recorder = _Recorder(subproc.Captured(0, _stdout({}, {}), b""))
    monkeypatch.setattr(subproc, "run_captured", recorder)
    compute_in_child(
        "omniweave_pdf",
        source="/corpus/a.pdf",
        content_sha256="ab" * 32,
        keys=KEYS,
        executable="python",
        cwd="/scratch",
        env={"PATH": "/bin"},
        password="hunter2",  # noqa: S106 -- a fixture's
    )
    (call,) = recorder.calls
    assert json.loads(call["stdin"])["password"] == "hunter2"  # noqa: S105 -- a fixture's
    assert all("hunter2" not in part for part in call["argv"])
    assert "hunter2" not in json.dumps(call["env"])


def test_the_answer_is_total_over_the_asked_keys_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _stdout({"unit.part_count": 4, "stray.key": 1}, {})
    found, _ = _ask(monkeypatch, subproc.Captured(0, body, b""))
    assert found.values == {"unit.part_count": 4}
    assert found.unavailable == {
        "decode.char_count": "the omniweave_pdf provider's child did not answer for this key"
    }


@pytest.mark.parametrize(
    ("captured", "said"),
    [
        (subproc.Captured(None, failed="TimeoutExpired"), "did not answer in 7 s"),
        (subproc.Captured(None, failed="OSError"), "did not start: OSError"),
        (subproc.Captured(3, b"", b"Traceback\nSegfault-ish\n"), "exited 3: Traceback"),
        (subproc.Captured(0, b"not json", b""), "answered no answer"),
    ],
)
def test_a_child_that_did_not_answer_leaves_every_key_unavailable_with_why(
    monkeypatch: pytest.MonkeyPatch, captured: subproc.Captured, said: str
) -> None:
    found, _ = _ask(monkeypatch, captured)
    assert found.values == {}
    assert set(found.unavailable) == set(KEYS)
    assert all(said in reason for reason in found.unavailable.values())


def test_a_non_scalar_on_the_wire_is_dropped_and_the_key_reported_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    found, _ = _ask(
        monkeypatch, subproc.Captured(0, _stdout({"unit.part_count": {"x": 1}}, {}), b"")
    )
    assert "unit.part_count" in found.unavailable


def test_the_computer_filename_is_the_module_the_child_imports() -> None:
    """The router finds `signals.py` by path and the child imports `<package>.signals`: one fact.

    Read from the source rather than imported, because `omniweave` may not be imported by a core
    test (`tools/layers.toml`), and the constant is a literal either way.
    """
    evidence = Path(__file__).resolve().parents[3] / "omniweave/src/omniweave/route/evidence.py"
    assert f'COMPUTER_FILENAME: Final[str] = "{signals.COMPUTER_MODULE}.py"' in evidence.read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------------------------
# A refusal is marked, so `route_signal` keeps only what a computer answered (D632)
# ---------------------------------------------------------------------------------------------


def test_a_computed_answer_is_no_refusal_and_every_request_failure_is_one(
    tmp_path: Path, provider: str
) -> None:
    """Only the first is a pure function of the content, the key and the provider's version."""
    assert answer(_request(tmp_path, b"xxx", provider)).refusal is None
    assert answer(_request(tmp_path, b"x", provider, keys=["ink.tiles"])).refusal is None
    failed = [
        answer(_request(tmp_path, b"RAISE", provider)),
        answer(_request(tmp_path, b"xxx", provider, content_sha256="0" * 64)),
        answer(_request(tmp_path, b"x", provider, source=str(tmp_path / "absent"))),
        answer(_request(tmp_path, b"x", "../escape")),
    ]
    assert all(one.refusal and set(one.unavailable.values()) == {one.refusal} for one in failed)


@pytest.mark.parametrize(
    "captured",
    [
        subproc.Captured(None, failed="TimeoutExpired"),
        subproc.Captured(None, failed="OSError"),
        subproc.Captured(3, b"", b"Traceback\n"),
        subproc.Captured(0, b"not json", b""),
        subproc.Captured(0, b'{"values": {}, "unavailable": {}, "refused": "gone"}', b""),
    ],
)
def test_a_child_that_did_not_compute_is_a_refusal_on_the_parent_side(
    monkeypatch: pytest.MonkeyPatch, captured: subproc.Captured
) -> None:
    found, _ = _ask(monkeypatch, captured)
    assert found.refusal is not None
    assert set(found.unavailable) == set(KEYS)


def test_a_child_that_computed_is_no_refusal_even_with_keys_it_could_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = json.dumps(
        {
            "values": {"unit.part_count": 4},
            "unavailable": {"decode.char_count": "no"},
            "refused": None,
        }
    ).encode()
    found, _ = _ask(monkeypatch, subproc.Captured(0, body, b""))
    assert found.refusal is None
    assert found.unavailable == {"decode.char_count": "no"}


def test_the_refusal_crosses_the_real_childs_stdout(tmp_path: Path) -> None:
    """`main()` writes `refused` and the parent reads it back: a missing source, a real child."""
    found = compute_in_child(
        "omniweave_pdf",
        source=str(tmp_path / "absent.pdf"),
        content_sha256="ab" * 32,
        keys=KEYS,
        executable=sys.executable,
        cwd=str(tmp_path),
        env={"SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PATH": os.environ.get("PATH", "")},
    )
    assert found.refusal is not None
    assert found.refusal.startswith("the source is unreadable")


def test_narrowing_an_answer_to_the_asked_keys_keeps_its_refusal() -> None:
    refused = SignalAnswer.refused(KEYS, "gone").total(KEYS[:1], missing="unasked")
    assert (refused.refusal, dict(refused.unavailable)) == ("gone", {KEYS[0]: "gone"})
    computed = SignalAnswer(values={KEYS[0]: 1}, unavailable={})
    assert computed.total(KEYS, missing="m").refusal is None
