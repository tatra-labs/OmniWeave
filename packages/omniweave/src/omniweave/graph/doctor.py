"""`ow graph doctor`: the graph's operability, one check at a time. D702.

06:2519 prints the verb -- *"Pass-level operability: the five §2.4 residue signals, the trust-clamp
rate, the share of entities excluded at funnel stage [3], per-`akind` anchor counts, stale-report
count, `entity.summary` producer status"* -- and 06:889-895 the signals and their thresholds.
15:1561 makes it a subsystem doctor that `ow doctor` names rather than re-runs. Its answer is
`DoctorReport`'s three tuples (`sdk.reports.GraphDoctorReport`): `failed` is the exit 1, and a
warning never fails (10:1436).

## Rulings (the ledger's D702)

1. **Eleven checks, each one `DoctorFinding` named as `--check` takes it** (16:805 spells
   `--check dangling_tmp,trust_clamped,ungrounded`). They run in `CHECKS` order whatever order
   they were asked in, and a name outside it is refused, naming the eleven.
2. **A signal with nothing under it is `ok` and says so** -- no reference sites, nothing admitted,
   no billed pass -- because a rate over zero items is not a measurement.
3. **Thresholds are 06:891-895's and strict**: *"warns above"* is `>`.
4. **Admitted items are what the sink was handed**: `n_items + n_quarantined` over `derive_run`;
   billed items are the same over `cost_class = 'billed_api'` runs, and the billed signals count
   only quarantine rows those runs wrote.
5. **`trust_clamped` is printed and never thresholded, except at exactly zero over billed items**:
   *"Exactly 0.00 means the clamp is not running, and that is a release blocker"* (06:899-901),
   the one check that fails.
6. **`entropy` is funnel stage [3] exactly**: the live entities of a `fuzzy` etype whose key is
   below `fuzzy.ENTROPY_MIN` bits, as a share of the live entities of `fuzzy` etypes (06:1873).
7. **`anchors` names all fourteen kinds, a zero included** (06:1031), at each document's head
   generation, as the reference views read them.
8. **`candidate_pairs` is an upper bound off the persisted bands**: a pair is counted once per band
   bucket it shares. It names the etype that makes the most, and above `MAX_CANDIDATE_PAIRS` it
   warns with the command 06:1803 names -- a warning, since the bound can pass the ceiling while
   the distinct pairs do not.
9. **`stale_reports` counts live communities by report state**, and **`summary` says whether
   anything wrote `entity.summary`**, which has no producer at release 1 (06:176-181): a row that
   has one is a warning, because nothing should have written it.

## Over billed runs that ran (D735)

10. **A clamped item is one item, not two.** The sink writes it at `INFERRED` (`n_items`) and keeps
    the over-claim as an `OW_GRAPH_TRUST_CLAMPED` row (`n_quarantined`). So admitted items are
    `n_items + n_quarantined` less the clamp rows, and the quarantine rate counts the rows that
    refused an item, not the ones that annotate it. 06:892's table says so: a clamp rate of 1.00
    beside a quarantine p50 of 24 per 1,000. Counting both made a model's run read 0.50 clamped
    and over 500 quarantined per 1,000.
11. **The billed signals are the sink's billed runs**: `billed_api` runs on a Segment. The LLM
    band's run is `billed_api` and corpus-grained, and its merges never reach the sink, so neither
    the clamp nor grounding applies to them. Counting them made a store whose only billed run was
    the band's read "0.00 clamped: the clamp is not running", the one check that fails.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from omniweave_core.model.enums import AnchorKind

from omniweave.sdk.reports import DoctorFinding, GraphDoctorReport

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    "CHECKS",
    "COVER_EMPTY_WARN",
    "QUARANTINE_WARN",
    "UNGROUNDED_WARN",
    "UNRESOLVED_WARN",
    "doctor",
]

UNRESOLVED_WARN: Final = 0.35
"""`ref_unresolved` as a share of `ref_site` rows (06:891)."""
QUARANTINE_WARN: Final = 80.0
"""`quarantine` rows per 1,000 admitted items (06:892)."""
UNGROUNDED_WARN: Final = 0.15
"""`OW_GRAPH_UNGROUNDED` as a share of billed items, F12's first threshold (06:893)."""
COVER_EMPTY_WARN: Final = 0.98
"""`cover_empty` as a share of `derive_cover` rows, GR3's (06:894)."""

_RESIDUE: Final = "ow graph residue"
_BILLED: Final = "cost_class = 'billed_api' AND segment_id IS NOT NULL"
"""Ruling 11: the billed runs the sink judged, on a Segment (D735)."""
_CLAMPED: Final = "OW_GRAPH_TRUST_CLAMPED"
_CLAMPED_SQL: Final = "SELECT count(*) FROM quarantine WHERE code = ?"
_CLAMPED_BILLED_SQL: Final = (
    "SELECT count(*) FROM quarantine AS q JOIN derive_run AS r ON r.run_id = q.run_id"
    " WHERE q.code = ? AND r.cost_class = 'billed_api' AND r.segment_id IS NOT NULL"
)
"""Ruling 10's clamp rows, over ruling 11's runs: `_BILLED`, spelled out for one join."""


def _ok(check: str, detail: str) -> DoctorFinding:
    return DoctorFinding(check=check, detail=detail, severity="ok", fix="")


def _warn(check: str, detail: str, fix: str) -> DoctorFinding:
    return DoctorFinding(check=check, detail=detail, severity="warning", fix=fix)


def _one(connection: Any, sql: str, *params: Any) -> int:
    [(value,)] = connection.execute(sql, params).fetchall()
    return int(value or 0)


def _admitted(connection: Any, *, billed: bool) -> int:
    """Ruling 4, and ruling 10: a clamped item counted once."""
    where = f" WHERE {_BILLED}" if billed else ""
    handed = _one(connection, f"SELECT sum(n_items + n_quarantined) FROM derive_run{where}")  # noqa: S608
    clamped = _one(connection, _CLAMPED_BILLED_SQL if billed else _CLAMPED_SQL, _CLAMPED)
    return handed - clamped


def _billed_rows(connection: Any, code: str) -> int:
    return _one(
        connection,
        f"SELECT count(*) FROM quarantine AS q JOIN derive_run AS r ON r.run_id = q.run_id"  # noqa: S608
        f" WHERE q.code = ? AND r.{_BILLED}",
        code,
    )


def _unresolved(connection: Any) -> DoctorFinding:
    sites = _one(connection, "SELECT count(*) FROM ref_site")
    if not sites:
        return _ok("unresolved", "no reference sites yet")
    unresolved = _one(connection, "SELECT count(*) FROM ref_unresolved")
    share = unresolved / sites
    detail = (
        f"{unresolved} of {sites} reference sites unresolved: {share:.2f} "
        f"(warns above {UNRESOLVED_WARN})"
    )
    return (
        _warn("unresolved", detail, _RESIDUE)
        if share > UNRESOLVED_WARN
        else _ok("unresolved", detail)
    )


def _quarantine(connection: Any) -> DoctorFinding:
    rows = _one(connection, "SELECT count(*) FROM quarantine WHERE code <> ?", _CLAMPED)
    admitted = _admitted(connection, billed=False)
    if not admitted:
        return _ok("quarantine", f"nothing admitted yet; {rows} quarantine rows")
    rate = 1000 * rows / admitted
    detail = (
        f"{rows} quarantine rows per {admitted} admitted items: {rate:.1f} per 1,000 "
        f"(warns above {QUARANTINE_WARN:g})"
    )
    return (
        _warn("quarantine", detail, _RESIDUE)
        if rate > QUARANTINE_WARN
        else _ok("quarantine", detail)
    )


def _ungrounded(connection: Any) -> DoctorFinding:
    billed = _admitted(connection, billed=True)
    if not billed:
        return _ok("ungrounded", "no billed pass has run")
    rows = _billed_rows(connection, "OW_GRAPH_UNGROUNDED")
    share = rows / billed
    detail = (
        f"{rows} of {billed} billed items ungrounded: {share:.2f} (warns above {UNGROUNDED_WARN})"
    )
    return (
        _warn("ungrounded", detail, _RESIDUE)
        if share > UNGROUNDED_WARN
        else _ok("ungrounded", detail)
    )


def _cover_empty(connection: Any) -> DoctorFinding:
    rows = _one(connection, "SELECT count(*) FROM derive_cover")
    if not rows:
        return _ok("cover_empty", "no cover rows yet")
    empty = _one(connection, "SELECT count(*) FROM derive_cover WHERE empty_reason IS NOT NULL")
    share = empty / rows
    detail = (
        f"{empty} of {rows} cover rows covered ground and emitted nothing: {share:.2f} "
        f"(warns above {COVER_EMPTY_WARN})"
    )
    if share <= COVER_EMPTY_WARN:
        return _ok("cover_empty", detail)
    return _warn(
        "cover_empty",
        detail,
        "a free pass that claims ground and finds nothing is silent recall loss (GR3): check its "
        "driver against a document it should match",
    )


def _trust_clamped(connection: Any) -> DoctorFinding:
    billed = _admitted(connection, billed=True)
    if not billed:
        return _ok("trust_clamped", "no billed pass has run")
    rows = _billed_rows(connection, _CLAMPED)
    if not rows:
        return DoctorFinding(
            check="trust_clamped",
            detail=f"0.00 of {billed} billed items clamped: the clamp is not running (06:899-901)",
            severity="error",
            fix="ow store verify   # the generated MAX_TRUST_BY_METHOD triggers",
        )
    return _ok(
        "trust_clamped",
        f"{rows / billed:.2f} of {billed} billed items clamped (1.00 expected; never thresholded)",
    )


def _dangling_tmp(connection: Any) -> DoctorFinding:
    rows = _one(connection, "SELECT count(*) FROM quarantine WHERE code = 'OW_GRAPH_DANGLING_TMP'")
    if not rows:
        return _ok("dangling_tmp", "no Segment's drafts referenced an undefined TmpRef")
    return _warn(
        "dangling_tmp",
        f"{rows} Segment(s) quarantined whole: their drafts referenced a TmpRef never defined",
        _RESIDUE,
    )


def _entropy(connection: Any) -> DoctorFinding:
    from omniweave.graph import fuzzy  # noqa: PLC0415 -- the doctor's import stays light

    keys = [
        str(key)
        for (key,) in connection.execute(
            "SELECT e.key FROM entity AS e JOIN etype_vocab AS v ON v.etype = e.etype"
            " WHERE e.state = 0 AND v.resolution = 'fuzzy'"
        )
    ]
    if not keys:
        return _ok("entropy", "no live entity of a fuzzy etype")
    below = sum(fuzzy.entropy(key) < fuzzy.ENTROPY_MIN for key in keys)
    return _ok(
        "entropy",
        f"{below} of {len(keys)} live entities of fuzzy etypes ({below / len(keys):.2f}) never "
        f"enter blocking: their key is below {fuzzy.ENTROPY_MIN} bits",
    )


def _anchors(connection: Any) -> DoctorFinding:
    counts = {
        str(akind): int(n)
        for akind, n in connection.execute(
            "SELECT n.akind, count(*) FROM anchor AS n"
            " JOIN doc AS d ON d.doc_ord = n.doc_ord AND n.gen = d.gen GROUP BY n.akind"
        )
    }
    return _ok(
        "anchors", " · ".join(f"{kind.value} {counts.get(kind.value, 0)}" for kind in AnchorKind)
    )


def _candidate_pairs(connection: Any) -> DoctorFinding:
    from omniweave.graph.resolve import MAX_CANDIDATE_PAIRS  # noqa: PLC0415

    rows = connection.execute(
        "SELECT etype, sum(n * (n - 1) / 2) AS pairs FROM"
        " (SELECT etype, count(*) AS n FROM entity_band GROUP BY band, bucket, etype)"
        " GROUP BY etype ORDER BY pairs DESC, etype"
    ).fetchall()
    if not rows:
        return _ok("candidate_pairs", "no entity is banded")
    total = sum(int(pairs) for _, pairs in rows)
    etype, most = str(rows[0][0]), int(rows[0][1])
    detail = (
        f"at most {total} candidate pairs from the persisted bands (the ceiling is "
        f"{MAX_CANDIDATE_PAIRS}); the most from {etype}, {most}"
    )
    if total <= MAX_CANDIDATE_PAIRS:
        return _ok("candidate_pairs", detail)
    return _warn(
        "candidate_pairs",
        detail,
        f"set etype_vocab.resolution = 'exact_only' for {etype}, "
        f"then: ow graph types --promote {etype}",
    )


def _stale_reports(connection: Any) -> DoctorFinding:
    states = dict(
        connection.execute(
            "SELECT r.report_state, count(*) FROM community AS c"
            " JOIN community_report AS r ON r.community_id = c.community_id"
            " WHERE c.state = 0 GROUP BY r.report_state"
        ).fetchall()
    )
    return _ok(
        "stale_reports",
        " · ".join(f"{state} {int(states.get(state, 0))}" for state in ("stale", "absent", "fresh"))
        + " live community report(s)",
    )


def _summary(connection: Any) -> DoctorFinding:
    written = _one(connection, "SELECT count(*) FROM entity WHERE summary IS NOT NULL")
    if not written:
        return _ok(
            "summary", "entity.summary has no producer at release 1, and is NULL on every row"
        )
    return _warn(
        "summary",
        f"{written} entities carry a summary, which nothing at release 1 writes (06:176-181)",
        "ow store verify",
    )


_CHECKERS: Final[dict[str, Callable[[Any], DoctorFinding]]] = {
    "unresolved": _unresolved,
    "quarantine": _quarantine,
    "ungrounded": _ungrounded,
    "cover_empty": _cover_empty,
    "trust_clamped": _trust_clamped,
    "dangling_tmp": _dangling_tmp,
    "entropy": _entropy,
    "anchors": _anchors,
    "candidate_pairs": _candidate_pairs,
    "stale_reports": _stale_reports,
    "summary": _summary,
}
CHECKS: Final = tuple(_CHECKERS)
"""Ruling 1: the eleven, in the order they run and print."""


def doctor(connection: Any, *, checks: Sequence[str] | None = None) -> GraphDoctorReport:
    """Rulings 1-9.

    Raises:
        ValueError: a check `CHECKS` does not hold.
    """
    wanted = set(CHECKS if checks is None else checks)
    unknown = sorted(wanted - set(CHECKS))
    if unknown:
        msg = f"{', '.join(unknown)} is not a graph check: {', '.join(CHECKS)}"
        raise ValueError(msg)
    found = [_CHECKERS[name](connection) for name in CHECKS if name in wanted]
    return GraphDoctorReport(
        ok=tuple(f for f in found if f.severity == "ok"),
        warned=tuple(f for f in found if f.severity == "warning"),
        failed=tuple(f for f in found if f.severity == "error"),
    )
