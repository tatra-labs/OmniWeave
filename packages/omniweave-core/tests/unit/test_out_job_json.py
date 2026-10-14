"""`job.json`: `Job`, the JobDir's envelope, closed at every level (09 Q11, closed by D763).

Q11: "printing `job.json` ... with schema `omniweave.out-job/1` and the same hard-error-on-unknown-
key rule `[compile]` has, and stating which keys the S2 child may read". Every refusal below is the
written document of one valid `Job` with one key changed, so each test names exactly one breach.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from omniweave_core.canonical import canonical
from omniweave_core.errors import TargetError
from omniweave_core.events import traceparent
from omniweave_core.model.block import Cite
from omniweave_core.out.brief import BRIEF_SCHEMA, parse_brief
from omniweave_core.out.gate import GateStatus
from omniweave_core.out.job import (
    JOB_JSON,
    JOB_MEDIA_TYPE,
    JOB_SCHEMA,
    Job,
    JobDeterminism,
    job_unit,
)
from omniweave_core.out.plan import ManualReason, OutUnit, Plan

REPO = Path(__file__).resolve().parents[4]

BRIEF = parse_brief(
    f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
    "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
    "- level: static\n## typography\n## rhythm\n## forbidden\n- no clip art (user)\n",
    baseline=(),
)
TRACE = traceparent("4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7")


def _plan(**changes: Any) -> Plan:
    fields: dict[str, Any] = {
        "schema": "omniweave.out-plan/1",
        "target": "owtext",
        "slug": "q3-board",
        "artifact_gen": 2,
        "delivery": "release",
        "units": (
            OutUnit(id="u01", ord=1, il_path="il/u01.html", anchor="intro", nsig="ab12cd34"),
            OutUnit(
                id="u02",
                ord=2,
                il_path="il/u02.html",
                source_part="ppt/slides/slide3.xml",
                source_nsig="0f0f0f0f",
                source_ord=3,
                manual_reason=ManualReason(next(iter(ManualReason)).value),
            ),
        ),
        "unit_count": 2,
        "brief": BRIEF,
        "corpus": "handbook",
        "cites": {Cite("d7#412"): 3, Cite("d2#9"): 1},
        "gate_status": GateStatus.NOT_PROVIDED,
        "il_digest": "sha256:" + "1" * 64,
        "constructs_digest": "sha256:" + "2" * 64,
        "ledger_digest": "sha256:" + "3" * 64,
        "brief_digest": BRIEF.digest(),
        "card_sha256": "sha256:" + "4" * 64,
        "toolchain_digest": None,
        "parent_gen": 1,
    }
    fields.update(changes)
    return Plan(**fields)


def _job(**changes: Any) -> Job:
    fields: dict[str, Any] = {
        "schema": JOB_SCHEMA,
        "plan": _plan(),
        "traceparent": TRACE,
        "determinism": JobDeterminism(1_700_000_000_000_000_000),
    }
    fields.update(changes)
    return Job(**fields)


def _document() -> dict[str, Any]:
    return json.loads(_job().to_bytes())


def _refused(document: object, said: str) -> None:
    with pytest.raises(TargetError, match=said) as caught:
        Job.from_json(document)
    assert caught.value.code() == "OW_TARGET_JOB_INVALID"
    assert caught.value.fix == "ow explain OW-T-518"


# ---------------------------------------------------------------------------------------------
# The round trip
# ---------------------------------------------------------------------------------------------


def test_a_job_survives_its_own_document_field_for_field() -> None:
    job = _job()
    again = Job.from_json(json.loads(job.to_bytes()))
    assert again == job
    assert again.plan.brief.digest() == job.plan.brief_digest
    assert again.plan.units[1].manual_reason is job.plan.units[1].manual_reason


def test_the_bytes_are_stable_lf_and_sorted_cites() -> None:
    """Ruling 20: two writes of one job are one byte string, whatever the platform."""
    body = _job().to_bytes()
    assert body == _job().to_bytes()
    assert b"\r" not in body
    assert body.startswith(b'{\n  "schema": "omniweave.out-job/1",\n  "plan": {\n    "schema"')
    assert body.endswith(b"}\n")
    assert list(json.loads(body)["plan"]["cites"]) == ["d2#9", "d7#412"]


def test_every_key_is_written_and_none_is_null() -> None:
    document = _document()
    assert list(document) == ["schema", "plan", "traceparent", "determinism"]
    assert document["plan"]["toolchain_digest"] is None
    assert document["plan"]["parent_gen"] == 1, "D809: an edit names its parent"
    assert document["plan"]["units"][0]["source_part"] is None
    assert document["plan"]["brief"]["template"] is None
    assert document["plan"]["brief"]["forbidden"] == [{"text": "no clip art", "tier": "user"}]


def test_a_templated_brief_survives_with_its_ref_and_units() -> None:
    text = (
        f"{BRIEF_SCHEMA}\n## canvas\n- format: 16:9\n- unit: slide\n## communication\n"
        "- primary_language: en-GB\n## direction\n## density\n- per_unit: light\n## motion\n"
        f"- level: static\n## typography\n## rhythm\n## template\n- ref: asset-slot:{'a' * 64}\n"
        "- units: u01, u02\n## forbidden\n"
    )
    brief = parse_brief(text, baseline=())
    job = _job(plan=_plan(brief=brief, brief_digest=brief.digest()))
    document = json.loads(job.to_bytes())
    assert document["plan"]["brief"]["template"] == {
        "ref": "asset-slot:" + "a" * 64,
        "units": ["u01", "u02"],
    }
    assert Job.from_json(document).plan.brief.template == brief.template


def test_write_and_load_through_the_job_dir(tmp_path: Path) -> None:
    job = _job()
    path = job.write(tmp_path)
    assert path == tmp_path / JOB_JSON
    assert path.read_bytes() == job.to_bytes()
    assert sorted(p.name for p in tmp_path.iterdir()) == [JOB_JSON]
    assert Job.load(tmp_path) == job


def test_a_job_json_that_does_not_load_is_named(tmp_path: Path) -> None:
    with pytest.raises(TargetError, match=r"job.json does not load: FileNotFoundError"):
        Job.load(tmp_path)
    (tmp_path / JOB_JSON).write_bytes(b"{not json")
    with pytest.raises(TargetError, match=r"job.json does not load: JSONDecodeError"):
        Job.load(tmp_path)


# ---------------------------------------------------------------------------------------------
# Ruling 19: closed at every level
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "said"),
    [
        ((), r"job.json has unknown key\(s\) \['extra'\]"),
        (("plan",), r"plan has unknown key\(s\) \['extra'\]"),
        (("determinism",), r"determinism has unknown key\(s\) \['extra'\]"),
        (("plan", "units", 0), r"plan.units\[0\] has unknown key\(s\) \['extra'\]"),
        (("plan", "brief"), r"plan.brief has unknown key\(s\) \['extra'\]"),
        (("plan", "brief", "forbidden", 0), r"forbidden\[0\] has unknown key\(s\) \['extra'\]"),
    ],
)
def test_an_unknown_key_anywhere_is_refused(path: tuple[Any, ...], said: str) -> None:
    document = _document()
    node: Any = document
    for step in path:
        node = node[step]
    node["extra"] = 1
    _refused(document, said)


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ((), "traceparent"),
        (("plan",), "cites"),
        (("plan",), "toolchain_digest"),
        (("plan",), "parent_gen"),
        (("plan", "units", 1), "manual_reason"),
        (("determinism",), "clock_ns"),
        (("plan", "brief"), "template"),
    ],
)
def test_a_missing_key_anywhere_is_refused_even_a_nullable_one(
    path: tuple[Any, ...], key: str
) -> None:
    """A producer writes every key (schemagen's rule), so an absent `null` is not a `null`."""
    document = _document()
    node: Any = document
    for step in path:
        node = node[step]
    del node[key]
    _refused(document, rf"is missing \['{key}'\]")


# ---------------------------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------------------------


def _with(path: tuple[Any, ...], value: object) -> dict[str, Any]:
    document = copy.deepcopy(_document())
    node: Any = document
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value
    return document


@pytest.mark.parametrize(
    ("path", "value", "said"),
    [
        (("schema",), "omniweave.out-job/2", "schema 'omniweave.out-job/2' is not"),
        (("plan", "schema"), "omniweave.out-plan/2", "plan: plan schema"),
        (("traceparent",), "00-" + "0" * 32 + "-" + "0" * 16 + "-00", "traceparent"),
        (("determinism", "clock_ns"), -1, "clock_ns -1 is not a non-negative integer"),
        (("determinism", "clock_ns"), True, r"clock_ns = True is not an integer"),
        (("plan", "artifact_gen"), "2", "artifact_gen = '2' is not an integer"),
        (("plan", "unit_count"), 3, "plan: unit_count 3 is not the roster's 2"),
        (("plan", "gate_status"), "green", "gate_status 'green' is not one of the ten"),
        (("plan", "cites"), {"7#412": 3}, "'7#412' is not a cite token"),
        (("plan", "cites"), {"d7#412": 0}, "doc_gen 0 is not a positive integer"),
        (("plan", "units", 0, "id"), "unit1", "plan: unit id 'unit1'"),
        (("plan", "units", 1, "manual_reason"), "because", "'because' is not a ManualReason"),
        (("plan", "brief", "forbidden", 0, "tier"), "house", "tier 'house' is baseline or user"),
        (("plan", "brief", "sections"), {"canvas": {"format": 16}}, "sections is not an object"),
        (("plan", "delivery"), "final", "plan: delivery 'final'"),
    ],
)
def test_a_value_out_of_its_grammar_is_refused(
    path: tuple[Any, ...], value: object, said: str
) -> None:
    _refused(_with(path, value), said)


def test_a_brief_that_does_not_digest_to_brief_digest_is_refused() -> None:
    """Ruling 21: the embedded Brief is the frozen one, and its digest binds it."""
    document = _with(("plan", "brief", "forbidden", 0, "text"), "no stock photos")
    _refused(document, "plan.brief digests to sha256:")


def test_a_non_object_is_refused() -> None:
    _refused([], "job.json is not an object")
    _refused(_with(("plan", "units"), {}), "plan.units is not an array")


# ---------------------------------------------------------------------------------------------
# G6: the committed schema is this type's
# ---------------------------------------------------------------------------------------------


def test_the_committed_schema_requires_every_key_the_document_carries() -> None:
    schema = json.loads((REPO / "schema" / "job-v1.json").read_text(encoding="utf-8"))
    document = _document()
    assert set(schema["required"]) == set(document)
    assert schema["additionalProperties"] is False
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(document, schema)
    broken = _with(("plan", "extra"), 1)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, schema)


# ---------------------------------------------------------------------------------------------
# Ruling 27 (D771): the job document a compile worker is invoked over
# ---------------------------------------------------------------------------------------------


def test_the_job_unit_is_the_synthetic_document_09_prints() -> None:
    job = _job()
    data = canonical(job.as_json())
    digest = hashlib.sha256(data).hexdigest()
    unit = job_unit(job)
    assert unit.uri == f"ow-job://handbook/q3-board/{digest}"
    assert (unit.part, unit.content_sha256, unit.byte_len) == ("", digest, len(data))
    assert unit.media_type == JOB_MEDIA_TYPE == "application/vnd.omniweave.job+json"


def test_a_job_that_differs_anywhere_is_another_unit() -> None:
    job = _job()
    later = _job(determinism=JobDeterminism(1_700_000_000_000_000_001))
    assert job_unit(job) == job_unit(Job.from_json(job.as_json()))
    crossed = Job.from_json(json.loads(json.dumps(job.as_json(), sort_keys=True)))
    assert crossed.to_bytes() != job.to_bytes(), "the Brief's sections are not in sorted order"
    assert job_unit(crossed) == job_unit(job), "a frame's sorted keys are the same record"
    assert job_unit(later).content_sha256 != job_unit(job).content_sha256
    assert job_unit(later).uri.rsplit("/", 1)[0] == job_unit(job).uri.rsplit("/", 1)[0]
