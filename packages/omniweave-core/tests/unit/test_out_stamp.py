"""`out.stamp.stamp()`: `data-ow-el` minted once, never renumbered, all units or none (D767).

The bundles are owtext's: the conformance suite's table and the target's own carrier, so what a
stamp writes is read back by the parser the check will use.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave_conform.suites.target.owtext.driver import HERE, OwTextCompiler
from omniweave_conform.suites.target.owtext.normalizers import lower_ascii
from omniweave_core.errors import TargetError
from omniweave_core.out.constructs import ConstructTable
from omniweave_core.out.job import read_il_files
from omniweave_core.out.report import il_digest
from omniweave_core.out.stamp import LOCK_NAME, STALE_LOCK_NS, Stamped, stamp

TABLE = ConstructTable.load(HERE / "constructs.toml", {"lower_ascii": lower_ascii})
NOW = 1_700_000_000_000_000_000


class _Clock:
    def __init__(self, now: int = NOW) -> None:
        self.now = now

    def wall_ns(self) -> int:
        return self.now

    def monotonic_ns(self) -> int:
        return self.now


def _job(tmp_path: Path, **units: str) -> Path:
    il = tmp_path / "il"
    il.mkdir()
    rows = "".join(
        f'\n[[unit]]\nid = "{unit}"\nord = {n}\nfile = "{unit}.html"\n'
        for n, unit in enumerate(units, start=1)
    )
    (il / "il.toml").write_text(
        f'schema = "omniweave.out-il/1"\nil = "owtext/1"\nconstructs_digest = "{TABLE.digest()}"\n'
        + rows,
        encoding="utf-8",
    )
    for unit, text in units.items():
        (il / f"{unit}.html").write_text(text, encoding="utf-8", newline="")
    return tmp_path


def _stamp(job: Path, clock: _Clock | None = None) -> Stamped:
    return stamp(job, carrier=OwTextCompiler().carrier, constructs=TABLE, clock=clock or _Clock())


def _text(job: Path, unit: str) -> str:
    return (job / "il" / f"{unit}.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------------
# Rulings 1-3: what is stamped, with which address, where
# ---------------------------------------------------------------------------------------------


def test_text_bearing_and_cited_elements_are_stamped_in_order_past_the_largest(
    tmp_path: Path,
) -> None:
    job = _job(
        tmp_path,
        u01=(
            '<section data-ow-el="u01/e4">\n  <p>One.</p>\n  <p data-ow-cite="d7#1"></p>\n'
            '  <p class="x">Two <b>bold</b></p>\n  <p data-ow-el="u01/e2">Kept.</p>\n</section>\n'
        ),
    )
    stamped = _stamp(job)
    assert dict(stamped.minted) == {"u01": ("u01/e5", "u01/e6", "u01/e7", "u01/e8")}
    assert stamped.written == ("u01.html",)
    assert _text(job, "u01") == (
        '<section data-ow-el="u01/e4">\n  <p data-ow-el="u01/e5">One.</p>\n'
        '  <p data-ow-cite="d7#1" data-ow-el="u01/e6"></p>\n'
        '  <p class="x" data-ow-el="u01/e7">Two <b data-ow-el="u01/e8">bold</b></p>\n'
        '  <p data-ow-el="u01/e2">Kept.</p>\n</section>\n'
    )


def test_an_unaddressed_unit_starts_at_e1_with_its_root(tmp_path: Path) -> None:
    job = _job(tmp_path, u02="<section>\n  <p>Margins held.</p>\n</section>\n")
    assert dict(_stamp(job).minted) == {"u02": ("u02/e1", "u02/e2")}
    assert _text(job, "u02").startswith('<section data-ow-el="u02/e1">')


def test_an_element_with_no_text_and_no_cite_is_left_alone(tmp_path: Path) -> None:
    job = _job(
        tmp_path, u01='<section>\n  <p>   </p>\n  <p data-ow-cite="d1#2">x</p>\n</section>\n'
    )
    assert dict(_stamp(job).minted) == {"u01": ("u01/e1", "u01/e2")}
    assert "<p>   </p>" in _text(job, "u01")


def test_a_self_closed_cited_element_gets_its_address_before_the_slash(tmp_path: Path) -> None:
    """An HTML void element is the self-closing case; `<p/>` is the carrier's refusal."""
    job = _job(tmp_path, u01='<section>\n  <p>t</p>\n  <img data-ow-cite="d1#1"/>\n</section>\n')
    _stamp(job)
    assert '<img data-ow-cite="d1#1" data-ow-el="u01/e3"/>' in _text(job, "u01")


def test_an_element_the_table_ignores_is_never_stamped(tmp_path: Path) -> None:
    """owtext ignores `html|head` and `html|meta`: text or a cite does not earn them an address."""
    source = (
        '<section>\n  <head>A title</head>\n  <meta data-ow-cite="d1#1" />\n  <p>One.</p>\n'
        "</section>\n"
    )
    job = _job(tmp_path, u01=source)
    assert dict(_stamp(job).minted) == {"u01": ("u01/e1", "u01/e2")}
    assert "<head>A title</head>" in _text(job, "u01")
    assert '<meta data-ow-cite="d1#1" />' in _text(job, "u01")


def test_another_units_address_and_a_malformed_one_are_never_rewritten(tmp_path: Path) -> None:
    """Ruling 2: neither counts toward this unit's ordinal, and neither is touched."""
    source = (
        '<section data-ow-el="u09/e40">\n  <p data-ow-el="banana">a</p>\n  <p>b</p>\n</section>\n'
    )
    job = _job(tmp_path, u01=source)
    assert dict(_stamp(job).minted) == {"u01": ("u01/e1",)}
    assert _text(job, "u01") == source.replace("<p>b</p>", '<p data-ow-el="u01/e1">b</p>')


def test_a_stamp_is_idempotent_and_writes_nothing_the_second_time(tmp_path: Path) -> None:
    job = _job(tmp_path, u01="<section>\n  <p>One.</p>\n</section>\n")
    _stamp(job)
    before = (job / "il" / "u01.html").read_bytes()
    again = _stamp(job)
    assert (dict(again.minted), again.written) == ({}, ())
    assert (job / "il" / "u01.html").read_bytes() == before


def test_a_stamp_moves_il_digest_and_leaves_no_file_behind(tmp_path: Path) -> None:
    job = _job(tmp_path, u01="<section>\n  <p>One.</p>\n</section>\n")
    before = il_digest(read_il_files(job / "il"))
    _stamp(job)
    assert il_digest(read_il_files(job / "il")) != before
    assert sorted(p.name for p in (job / "il").iterdir()) == ["il.toml", "u01.html"]


# ---------------------------------------------------------------------------------------------
# Ruling 4: all units or none
# ---------------------------------------------------------------------------------------------


def test_a_unit_whose_read_recovered_refuses_the_stamp_and_nothing_is_written(
    tmp_path: Path,
) -> None:
    good = "<section>\n  <p>One.</p>\n</section>\n"
    bad = "<section>\n  <p>unclosed\n</section>\n"
    job = _job(tmp_path, u01=good, u02=bad)
    with pytest.raises(TargetError, match=r"il/u02.html: the unit does not reparse") as caught:
        _stamp(job)
    assert caught.value.code() == "OW_TARGET_STAMP_REFUSED"
    assert caught.value.fix == "ow out check --stage unit --unit u02"
    assert (_text(job, "u01"), _text(job, "u02")) == (good, bad)
    assert not (job / "il" / LOCK_NAME).exists()


def test_undecodable_bytes_refuse_the_stamp(tmp_path: Path) -> None:
    job = _job(tmp_path, u01="<section>\n  <p>One.</p>\n</section>\n")
    (job / "il" / "u01.html").write_bytes(b"<section><p>\xff</p></section>")
    with pytest.raises(TargetError, match="does not reparse") as caught:
        _stamp(job)
    assert caught.value.code() == "OW_TARGET_STAMP_REFUSED"


# ---------------------------------------------------------------------------------------------
# Ruling 5: the lock
# ---------------------------------------------------------------------------------------------


def test_a_fresh_lock_refuses_and_is_left_for_its_owner(tmp_path: Path) -> None:
    job = _job(tmp_path, u01="<section>\n  <p>One.</p>\n</section>\n")
    lock = job / "il" / LOCK_NAME
    lock.write_text(f"4242 {NOW - 1}\n", encoding="ascii")
    with pytest.raises(TargetError, match="pid 4242") as caught:
        _stamp(job)
    assert caught.value.code() == "OW_TARGET_STAMP_LOCKED"
    assert lock.read_text(encoding="ascii") == f"4242 {NOW - 1}\n"
    assert "data-ow-el" not in _text(job, "u01")


@pytest.mark.parametrize("held", [f"4242 {NOW - STALE_LOCK_NS}\n", "garbage\n", ""])
def test_a_stale_or_unreadable_lock_is_replaced_and_said(held: str, tmp_path: Path) -> None:
    job = _job(tmp_path, u01="<section>\n  <p>One.</p>\n</section>\n")
    (job / "il" / LOCK_NAME).write_text(held, encoding="ascii")
    stamped = _stamp(job)
    assert stamped.stale_lock
    assert dict(stamped.minted) == {"u01": ("u01/e1", "u01/e2")}
    assert not (job / "il" / LOCK_NAME).exists()


def test_the_lock_holds_the_pid_and_the_clocks_start_while_the_stamp_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _job(tmp_path, u01="<section>\n  <p>One.</p>\n</section>\n")
    seen: list[str] = []
    import omniweave_core.out.stamp as module  # noqa: PLC0415

    original = module.ILBundle.load

    def load(*args: object, **kwargs: object) -> object:
        seen.append((job / "il" / LOCK_NAME).read_text(encoding="ascii"))
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(module.ILBundle, "load", staticmethod(load))
    _stamp(job)
    [held] = seen
    pid, started = held.split()
    assert int(pid) > 0
    assert int(started) == NOW
    assert not (job / "il" / LOCK_NAME).exists()


def test_a_bundle_that_does_not_load_writes_nothing_and_frees_the_lock(tmp_path: Path) -> None:
    """Ruling 6: a row with no file is ILBundle's refusal, and the stamp's too."""
    job = _job(tmp_path, u01="<section>\n  <p>One.</p>\n</section>\n")
    (job / "il" / "u01.html").unlink()
    with pytest.raises(TargetError) as caught:
        _stamp(job)
    assert caught.value.code() == "OW_TARGET_ROSTER_MISMATCH"
    assert not (job / "il" / LOCK_NAME).exists()
