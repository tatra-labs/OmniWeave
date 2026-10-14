"""`out.compile.lower_job()`, `artefact()` and the refusal encoding: a compile worker's half (D771).

The worker runs the target's `carrier()`, `lower()` and `postflight()` over a JobDir the host has
gated, and nothing else. The target is owtext and the JobDir is a real scaffold holding the golden
IL, so the bytes, the receipt and every digest are the shipped ones.
"""

from __future__ import annotations

import functools
import hashlib
import io
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import omniweave_conform.suites.target as target_suites
import pytest
from omniweave_conform.harness import MemoryBlobStore, make_io
from omniweave_conform.suites.target.owtext.driver import OwTextCompiler
from omniweave_core.blobs import BlobStore, format_ref
from omniweave_core.discovery import discover
from omniweave_core.errors import OwError, TargetError
from omniweave_core.events import traceparent
from omniweave_core.out.agentdoc import load_table
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.card import CompileCard
from omniweave_core.out.compile import artefact, lower_job, refusal_message, refusal_of
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import ILBundle, Job, scaffold
from omniweave_core.out.ledger import LedgerRow, slot, write_index
from omniweave_core.out.plan import UnitOutcome
from omniweave_core.out.receipt import Receipt
from omniweave_ports import ArtifactRef, DriverResult

SUITES = Path(target_suites.__file__).parent
GOLDEN = Path(__file__).resolve().parents[4] / "fixtures" / "out" / "golden" / "owtext" / "il"
TRACE = traceparent("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7")
BRIEF = (
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: section\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n- u01: { anchor: cover }\n"
    "- u02: { anchor: content }\n## forbidden\n"
)
TEXT = b"== u01 ==\nRevenue rose 12% in Q3.\n== u02 ==\nMargins held.\n"


@functools.cache
def _owtext() -> tuple[CompileCard, str, Any]:
    for card in discover(env={"OMNIWEAVE_DRIVER_PATH": str(SUITES)}).cards:
        if str(card.identity.port) == "compile" and CompileCard.of(card).target == "owtext":
            compiled = CompileCard.of(card)
            return compiled, card.card_sha256, load_table(Path(card.source), compiled)
    raise AssertionError("owtext is in the conformance suite's directory")


def _gated(tmp_path: Path, *, u01: str | None = None) -> tuple[Path, Job]:
    """A scaffolded JobDir with the golden IL authored, and the Job a host sends after its gate."""
    card, sha, table = _owtext()
    job_dir = tmp_path / "job"
    job = scaffold(
        job_dir,
        card=card,
        card_sha256=sha,
        table=table,
        brief_text=BRIEF,
        brief=parse_brief(BRIEF, baseline=()),
        slug="q3",
        artifact_gen=1,
        corpus="handbook",
        traceparent=TRACE,
        clock_ns=1_700_000_000_000_000_000,
    )
    for name in ("il.toml", "u01.html", "u02.html"):
        shutil.copyfile(GOLDEN / name, job_dir / "il" / name)
    if u01 is not None:
        (job_dir / "il" / "u01.html").write_text(u01, encoding="utf-8", newline="")
    bundle = ILBundle.load(job_dir / "il", carrier=OwTextCompiler().carrier, constructs=table)
    plan = replace(
        job.plan,
        il_digest=bundle.il_digest,
        gate_status=GateStatus.PASSED,
        units=tuple(
            replace(mine, nsig=theirs.nsig, manual_reason=theirs.manual_reason)
            for mine, theirs in zip(job.plan.units, bundle.units, strict=True)
        ),
    )
    return job_dir, replace(job, plan=plan)


def _lower(
    tmp_path: Path, job_dir: Path, job: Job, compiler: Any = None
) -> tuple[DriverResult, MemoryBlobStore]:
    blobs = MemoryBlobStore(tmp_path / "cas")
    io_obj = make_io(blobs, tmp_path / "scratch")
    result = lower_job(
        compiler or OwTextCompiler(),
        job,
        job_dir,
        constructs=_owtext()[2],
        suffix=".txt",
        io=io_obj,
    )
    return result, blobs


class _NeverLowers(OwTextCompiler):
    def lower(self, *args: Any, **kwargs: Any) -> DriverResult:
        del args, kwargs
        raise AssertionError("lower() ran over a JobDir the host did not gate")


# ---------------------------------------------------------------------------------------------
# Ruling 10: lower(), the staged artefact, postflight()
# ---------------------------------------------------------------------------------------------


def test_the_worker_lowers_stages_and_postflights_the_gated_job(tmp_path: Path) -> None:
    job_dir, job = _gated(tmp_path)
    result, blobs = _lower(tmp_path, job_dir, job)
    assert result.outcome == "ok"
    assert [ref.kind for ref in result.produced] == ["artifact", "receipt"]
    _, body = artefact(result, blobs)
    assert body == TEXT
    staged = tmp_path / "scratch" / "q3.txt"
    assert staged.read_bytes() == TEXT
    raw = result.produced[1].inline
    assert raw is not None
    receipt = Receipt.from_json(json.loads(raw))
    assert receipt.to_bytes() == raw
    assert receipt.output == {
        "path": str(staged),
        "bytes": len(TEXT),
        "sha256": hashlib.sha256(TEXT).hexdigest(),
    }
    assert (receipt.slug, receipt.artifact_gen, receipt.gate_status) == ("q3", 1, "passed")
    assert receipt.units == {"u01": UnitOutcome.NATIVE, "u02": UnitOutcome.MANUAL_REQUIRED}
    #  The golden u02 holds an ow:manual region, and the receipt reports the classifier (D777).


def test_the_artefact_ref_is_lowers_own(tmp_path: Path) -> None:
    """The meter counted `lower()`'s ref once; the worker passes that ref on, not a copy."""
    job_dir, job = _gated(tmp_path)
    seen: list[ArtifactRef] = []

    class Recording(OwTextCompiler):
        def lower(self, *args: Any, **kwargs: Any) -> DriverResult:
            result = super().lower(*args, **kwargs)
            seen.extend(result.produced)
            return result

    result, _ = _lower(tmp_path, job_dir, job, Recording())
    assert result.produced[0] is seen[0]


def test_the_targets_own_refusal_reaches_the_caller(tmp_path: Path) -> None:
    shadowed = (
        (GOLDEN / "u01.html")
        .read_text(encoding="utf-8")
        .replace('class="lead"', 'class="lead" style="text-shadow: 1px 1px red"')
    )
    job_dir, job = _gated(tmp_path, u01=shadowed)
    with pytest.raises(TargetError) as caught:
        _lower(tmp_path, job_dir, job)
    assert caught.value.code() == "OW_TARGET_BAKE_UNAVAILABLE"


# ---------------------------------------------------------------------------------------------
# Ruling 11: only the JobDir the host gated
# ---------------------------------------------------------------------------------------------


def _changed(tmp_path: Path, job_dir: Path, job: Job) -> str:
    with pytest.raises(TargetError) as caught:
        _lower(tmp_path, job_dir, job, _NeverLowers())
    assert caught.value.code() == "OW_TARGET_JOB_CHANGED"
    assert caught.value.fix == "ow out check --stage final"
    return str(caught.value)


def test_il_edited_after_the_gate_is_refused_before_lower(tmp_path: Path) -> None:
    job_dir, job = _gated(tmp_path)
    (job_dir / "il" / "u02.html").write_text("<section><p>Margins fell.</p></section>\n")
    message = _changed(tmp_path, job_dir, job)
    assert "il_digest" in message
    assert "ledger_digest" not in message


@pytest.mark.parametrize("field", ["constructs_digest", "ledger_digest", "il_digest"])
def test_a_plan_made_against_other_inputs_is_refused(tmp_path: Path, field: str) -> None:
    job_dir, job = _gated(tmp_path)
    other = replace(job, plan=replace(job.plan, **{field: "sha256:" + "0" * 64}))
    message = _changed(tmp_path, job_dir, other)
    assert f"{field} is sha256:" in message
    assert f"the plan says sha256:{'0' * 64}" in message
    assert message.count(" is sha256:") == 1


def test_an_asset_frozen_after_the_gate_is_refused(tmp_path: Path) -> None:
    job_dir, job = _gated(tmp_path)
    sha = "c" * 64
    write_index(
        job_dir, [LedgerRow(asset_id=1, sha256=sha, slot=slot(sha), role="image", unit="u01")]
    )
    assert "ledger_digest" in _changed(tmp_path, job_dir, job)


# ---------------------------------------------------------------------------------------------
# artefact(): exactly one artifact ref, inline or from the CAS
# ---------------------------------------------------------------------------------------------


def _io(tmp_path: Path) -> tuple[Any, MemoryBlobStore]:
    blobs = MemoryBlobStore(tmp_path / "cas")
    return make_io(blobs, tmp_path / "scratch"), blobs


@pytest.mark.parametrize("count", [0, 2])
def test_anything_but_one_artifact_ref_is_refused(tmp_path: Path, count: int) -> None:
    io_obj, blobs = _io(tmp_path)
    refs = tuple(ArtifactRef.of("artifact", b"x", io_obj) for _ in range(count))
    with pytest.raises(TargetError, match=f"returned {count} artifact refs") as caught:
        artefact(DriverResult("ok", (*refs, ArtifactRef.of("diag", b"d", io_obj))), blobs)
    assert caught.value.code() == "OW_TARGET_PACKAGE_CORRUPT"


def test_an_artifact_above_inline_max_is_read_from_the_cas(tmp_path: Path) -> None:
    io_obj, blobs = _io(tmp_path)
    big = b"a" * 300_000
    ref = ArtifactRef.of("artifact", big, io_obj)
    assert ref.inline is None
    assert artefact(DriverResult("ok", (ref,)), blobs) == (ref, big)


def test_a_sharded_ref_is_read_by_its_digest(tmp_path: Path) -> None:
    """A worker's `put()` returns `cas://bb/18/<hex>`; the digest is the ref's last segment."""
    (tmp_path / "cas").mkdir()
    cas = BlobStore(tmp_path / "cas")
    digest = cas.put(io.BytesIO(b"sharded"))
    ref = ArtifactRef(kind="artifact", byte_len=7, blob=format_ref(digest))
    assert ref.blob is not None
    assert ref.blob.count("/") == 4
    assert artefact(DriverResult("ok", (ref,)), cas) == (ref, b"sharded")


# ---------------------------------------------------------------------------------------------
# Ruling 12: a refusal crosses with its symbol
# ---------------------------------------------------------------------------------------------


def test_a_refusal_reads_back_with_its_symbol_fix_and_text() -> None:
    sent = TargetError(
        "two lines\nof text", symbol="OW_TARGET_JOB_CHANGED", fix="ow out check\n  --stage final"
    )
    message = refusal_message(sent)
    assert message == "OW_TARGET_JOB_CHANGED\now out check --stage final\ntwo lines\nof text"
    back = refusal_of(message)
    assert back is not None
    assert (back.code(), back.fix, str(back)) == (
        "OW_TARGET_JOB_CHANGED",
        "ow out check --stage final",
        "two lines\nof text",
    )


def test_a_cut_message_keeps_its_symbol_and_fix() -> None:
    """The worker bounds a message; the symbol and fix lead, so a cut takes only the text."""
    message = refusal_message(TargetError("x" * 5000, symbol="OW_TARGET_IL_MALFORMED", fix="f"))
    back = refusal_of(message[:2048])
    assert back is not None
    assert (back.code(), back.fix, len(str(back))) == ("OW_TARGET_IL_MALFORMED", "f", 2048 - 25)


class _BareError(OwError):
    """An `OwError` with no symbol: nothing names it, so nothing reads it back."""


@pytest.mark.parametrize(
    "message",
    [
        "ValueError: the driver failed",
        "OW_TARGET_X\n\ntext",
        "OW_TARGET_X\n   \ntext",
        "OW_TARGET_X\nfix",
        "ow_target_x\nfix\ntext",
        "OW_TARGET X\nfix\ntext",
        refusal_message(_BareError("text", fix="f")),
        "",
    ],
)
def test_a_message_in_another_shape_is_no_refusal(message: str) -> None:
    assert refusal_of(message) is None
