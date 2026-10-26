"""Ruling 1's review page, tested as a program: `tools/label_review.py`. **D980.**

Three things are worth holding here.

1. **The committed labels agree with the committed bytes.** D913 drafted all 110 from the
   generators' text functions, and this file reads them back off the fixtures through readers that
   import no omniweave driver. A drafted claim that the file contradicts is a defect to mend before
   a reviewer ever sees it, so it fails here rather than waiting for the review.
2. **`agrees` is not `checked`.** Nothing in the tool writes a signature. `apply_verdicts` takes a
   reviewer's file, refuses any value but section 8.1's two, refuses an id the sidecar does not
   carry, and stages every write so a refusal leaves the tree untouched.
3. **A signature does not reformat the sidecar.** The files are hand-written and commented, and
   `autocrlf=true` leaves them CRLF in the working tree, so `_stamp` edits the signed row's lines
   and leaves every other byte -- line ending included -- where it was.

Loaded by file path under a private name at module scope, as `test_gate_measured_on.py` loads its
gate.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[4]


def _load() -> ModuleType:
    path = REPO / "tools" / "label_review.py"
    spec = importlib.util.spec_from_file_location("_owtool_label_review", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load()

SIDECAR = """# a sidecar, with the comments a reviewer reads.
schema = "omniweave.assertions/1"

[[assertion]]
id = "first"
type = "present"
page = 1
text = "Hello"
slices = ["x/y"]

[[assertion]]
id = "second"
type = "absent"
text = "Nowhere"
slices = ["x/y"]
"""


def _claim(**body: object) -> object:
    return TOOL.Claim(Path("s.toml"), Path("f.txt"), 1, body)


def _evidence(*runs: str, grid: tuple[tuple[str, ...], ...] = ()) -> object:
    return TOOL.Evidence("a test", runs=runs, pages=(runs,), grid=grid)


# 1 -- the committed labels, against the committed bytes.


def test_every_drafted_label_has_evidence_and_agrees() -> None:
    rows = TOOL.review(REPO)
    assert rows, "no *.assertions.toml found -- the glob or the tree moved"
    blind = [row.claim.id for row in rows if row.agrees is None]
    assert blind == [], f"no evidence for {blind}: a reviewer would have to take those on trust"
    wrong = [
        f"{row.claim.fixture.name}:{row.claim.id} -- {row.why}" for row in rows if not row.agrees
    ]
    assert wrong == [], "drafted labels the fixture bytes contradict:\n" + "\n".join(wrong)


def test_every_fixture_with_labels_has_an_independent_reader() -> None:
    rows = TOOL.review(REPO)
    suffixes = {row.claim.fixture.suffix for row in rows}
    unreadable = {row.claim.fixture.suffix for row in rows if row.evidence.unreadable is not None}
    assert unreadable == set(), (
        f"no independent reader for {sorted(unreadable)} of {sorted(suffixes)}"
    )


def test_nothing_in_the_tree_is_signed_yet_or_is_signed_only_the_two_ways() -> None:
    """A signature is the user's. This test does not demand there be none -- only that each is one
    of the two values section 8.1 allows, so a typo cannot quietly become a third state."""
    for claim in TOOL.claims(REPO):
        assert claim.checked in (None, *TOOL.VERDICTS), f"{claim.id}: {claim.checked!r}"


# 2 -- the arithmetic, on its own terms.


def test_present_finds_and_misses() -> None:
    evidence = _evidence("a heading", "some body text")
    assert TOOL.judge(_claim(id="a", type="present", page=1, text="body"), evidence).agrees is True
    missed = TOOL.judge(_claim(id="a", type="present", page=1, text="absent"), evidence)
    assert missed.agrees is False
    assert "no run on that page" in missed.why


def test_order_holds_only_in_the_drawn_direction() -> None:
    evidence = _evidence("first", "second")
    assert TOOL.judge(
        _claim(id="a", type="order", page=1, before="first", after="second"), evidence
    ).agrees
    backwards = TOOL.judge(
        _claim(id="a", type="order", page=1, before="second", after="first"), evidence
    )
    assert backwards.agrees is False
    assert "does NOT precede" in backwards.why


def test_order_with_a_missing_side_names_the_side() -> None:
    row = TOOL.judge(
        _claim(id="a", type="order", page=1, before="first", after="gone"), _evidence("first")
    )
    assert row.agrees is False
    assert "'gone'" in row.why


def test_absent_is_over_the_whole_document_not_one_page() -> None:
    evidence = TOOL.Evidence(
        "a test", runs=("page one", "page two"), pages=(("page one",), ("page two",))
    )
    assert TOOL.judge(_claim(id="a", type="absent", text="page three"), evidence).agrees is True
    assert (
        TOOL.judge(_claim(id="a", type="absent", page=1, text="page two"), evidence).agrees is False
    )


def test_table_walks_the_grid_in_four_directions() -> None:
    grid = (("Region", "Units"), ("north", "17"))
    evidence = _evidence("Region", "Units", "north", "17", grid=grid)
    assert TOOL.judge(
        _claim(id="a", type="table", page=1, cell="north", right="17", up="Region"), evidence
    ).agrees
    assert TOOL.judge(
        _claim(id="a", type="table", page=1, cell="17", left="north", up="Units"), evidence
    ).agrees
    wrong = TOOL.judge(_claim(id="a", type="table", page=1, cell="north", right="99"), evidence)
    assert wrong.agrees is False
    assert "is '17', not '99'" in wrong.why


def test_table_off_the_edge_disagrees_rather_than_raising() -> None:
    evidence = _evidence("only", grid=(("only",),))
    row = TOOL.judge(_claim(id="a", type="table", page=1, cell="only", right="anything"), evidence)
    assert row.agrees is False


def test_a_row_with_no_evidence_is_neither_true_nor_false() -> None:
    row = TOOL.judge(
        _claim(id="a", type="present", page=1, text="x"), TOOL.Evidence("x", unreadable="no reader")
    )
    assert row.agrees is None
    assert "no evidence" in row.why


def test_a_table_claim_without_a_grid_is_unknown_not_false() -> None:
    row = TOOL.judge(_claim(id="a", type="table", page=1, cell="x", right="y"), _evidence("x", "y"))
    assert row.agrees is None


# 3 -- the readers, on the fixtures' own escapes.


def test_pdf_literals_come_back_unescaped() -> None:
    assert TOOL.unescape(rb"(a \(b\) c)") == "a (b) c"
    assert TOOL.unescape(rb"(a \\ b)") == "a \\ b"


def test_the_pdf_reader_finds_one_page_per_kid() -> None:
    fixture = REPO / "packages" / "omniweave-pdf" / "fixtures" / "gen04p.pdf"
    pages = TOOL.pdf_pages(fixture)
    assert len(pages) == 4, "gen04p.pdf draws four pages"
    assert pages[0][0].startswith("Article 1."), pages[0][:2]


# 4 -- the signature: the user's, written where it belongs and nowhere else.


def test_stamp_appends_to_the_right_row_only() -> None:
    signed = TOOL._stamp(SIDECAR, "first", "verified")
    assert 'id = "first"' in signed
    assert signed.count("checked") == 1
    head, _, tail = signed.partition('[[assertion]]\nid = "second"')
    assert 'checked = "verified"' in head
    assert "checked" not in tail


def test_stamp_replaces_an_existing_signature() -> None:
    once = TOOL._stamp(SIDECAR, "second", "rejected")
    twice = TOOL._stamp(once, "second", "verified")
    assert twice.count("checked") == 1
    assert 'checked = "verified"' in twice


def test_stamp_keeps_crlf_where_the_file_has_it() -> None:
    """`autocrlf=true` leaves these files CRLF in the working tree (D>=CRLF ruling): a signature
    that wrote a bare LF into a CRLF file would show up as a whole-file diff."""
    signed = TOOL._stamp(SIDECAR.replace("\n", "\r\n"), "first", "verified")
    assert 'checked = "verified"\r\n' in signed
    assert "\n\n" not in signed.replace("\r\n", "\n").replace("\n\n", "")


def test_apply_writes_only_the_reviewers_two_values(tmp_path: Path) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "f.txt.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(SIDECAR.encode("utf-8"))
    relative = "packages/p/fixtures/f.txt.assertions.toml"
    written = TOOL.apply_verdicts(tmp_path, {relative: {"first": "verified", "second": "rejected"}})
    assert written == [f"{Path(relative)}: 2 signed"]
    rows = {row["id"]: row.get("checked") for row in _rows(sidecar)}
    assert rows == {"first": "verified", "second": "rejected"}


@pytest.mark.parametrize(
    ("verdicts", "message"),
    [
        ({"first": "approved"}, "is not one of"),
        ({"first": True}, "is not one of"),
        ({"third": "verified"}, "no such assertion id"),
    ],
)
def test_apply_refuses_and_leaves_the_file_byte_identical(
    tmp_path: Path, verdicts: dict[str, object], message: str
) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "f.txt.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(SIDECAR.encode("utf-8"))
    before = sidecar.read_bytes()
    with pytest.raises(SystemExit, match=message):
        TOOL.apply_verdicts(tmp_path, {"packages/p/fixtures/f.txt.assertions.toml": verdicts})
    assert sidecar.read_bytes() == before


def test_apply_refuses_an_unknown_sidecar(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="no such sidecar"):
        TOOL.apply_verdicts(tmp_path, {"nowhere.assertions.toml": {"first": "verified"}})


def test_one_bad_sidecar_stops_the_whole_write(tmp_path: Path) -> None:
    """Two sidecars, the second unsignable: the first must not be written either."""
    first = tmp_path / "packages" / "a" / "fixtures" / "f.txt.assertions.toml"
    second = tmp_path / "packages" / "b" / "fixtures" / "g.txt.assertions.toml"
    for path in (first, second):
        path.parent.mkdir(parents=True)
        path.write_bytes(SIDECAR.encode("utf-8"))
    before = first.read_bytes()
    with pytest.raises(SystemExit, match="no such assertion id"):
        TOOL.apply_verdicts(
            tmp_path,
            {
                "packages/a/fixtures/f.txt.assertions.toml": {"first": "verified"},
                "packages/b/fixtures/g.txt.assertions.toml": {"nope": "verified"},
            },
        )
    assert first.read_bytes() == before


def _rows(sidecar: Path) -> list[dict[str, object]]:
    return tomllib.loads(sidecar.read_text(encoding="utf-8"))["assertion"]


# 5 -- the bundle and the page.


def test_the_bundle_carries_every_label_and_says_what_agrees_means() -> None:
    data = TOOL.bundle(TOOL.review(REPO))
    assert data["schema"] == "omniweave.label-review/1"
    assert "not a reviewer's verdict" in data["note"]
    counted = sum(len(group["labels"]) for group in data["fixtures"])
    assert counted == len(TOOL.claims(REPO))


def test_the_page_names_every_label_and_disclaims_the_arithmetic() -> None:
    data = TOOL.bundle(TOOL.review(REPO))
    page = TOOL.page_html(data)
    assert "<title>" in page
    assert "not a verdict" in page
    for group in data["fixtures"]:
        for label in group["labels"]:
            assert label["id"] in page


def test_the_page_escapes_what_a_fixture_wrote() -> None:
    data = {
        "fixtures": [
            {
                "fixture": "f.txt",
                "sidecar": "f.txt.assertions.toml",
                "origin": "a test",
                "labels": [
                    {
                        "id": "x",
                        "type": "present",
                        "page": 1,
                        "claim": '<script>alert("x")</script>',
                        "toml": {},
                        "slices": [],
                        "checked": None,
                        "agrees": True,
                        "why": "ok",
                        "excerpt": ["<b>not markup</b>"],
                    }
                ],
            }
        ]
    }
    page = TOOL.page_html(data)
    assert "<script>" not in page
    assert "&lt;b&gt;not markup" in page


# 6 -- the program's exits.


def test_main_exits_clean_over_the_tree(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "bundle.json"
    page = tmp_path / "review.html"
    assert (
        TOOL.main(["--root", str(REPO), "--json", str(out), "--page", str(page)]) == TOOL.EXIT_CLEAN
    )
    printed = capsys.readouterr().out
    assert "carry a reviewer's signature" in printed
    assert json.loads(out.read_text(encoding="utf-8"))["fixtures"]
    assert page.read_text(encoding="utf-8").startswith("<title>")


def test_main_exits_two_when_a_row_has_no_evidence(tmp_path: Path) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "f.unknownext.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(SIDECAR.encode("utf-8"))
    (sidecar.parent / "f.unknownext").write_bytes(b"")
    assert TOOL.main(["--root", str(tmp_path)]) == TOOL.EXIT_NO_EVIDENCE


def test_main_exits_one_when_a_claim_contradicts_the_bytes(tmp_path: Path) -> None:
    sidecar = tmp_path / "packages" / "p" / "fixtures" / "rows.csv.assertions.toml"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(
        b'schema = "omniweave.assertions/1"\n\n[[assertion]]\nid = "wrong"\n'
        b'type = "present"\npage = 1\ntext = "not in the file"\nslices = ["x"]\n'
    )
    (sidecar.parent / "rows.csv").write_bytes(b"a,b\n1,2\n")
    assert TOOL.main(["--root", str(tmp_path)]) == TOOL.EXIT_DISAGREES
