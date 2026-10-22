"""A project's own driver card and route rule, honoured by a real `ow add`. D935.

05:941 gives a project two directories: `.omniweave/drivers/` for cards and `.omniweave/policy.d/`
for route rules that prepend to the builtin's. Before D935 `ow add` read neither: the catalog was
built without the project root, routing compiled the builtin layer alone, and a parse worker was
never told where a non-entry-point card lives. The driver here is the builtin text parser's code
under a project card of its own id, so the only thing that can route a `.txt` to it is the rule.

It spawns workers, so it is the conform tier's by Q-G25's rule.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

import pytest
from omniweave.route.policy import POLICY_D, compile_policy
from omniweave.run.routing import route_layers
from omniweave_core.config import SHIPPED_DRIVERS, load
from omniweave_core.host.subproc import run_captured
from omniweave_core.store import sqlite as ow

pytestmark = pytest.mark.conform

REPO = Path(__file__).resolve().parents[4]
CARD = REPO / "packages/omniweave-office/src/omniweave_office/text/driver.toml"
TEMPLATE = REPO / "packages/omniweave-conform/src/omniweave_conform/template/driver.toml"
PROJECT_DRIVER = "parse.text.project"
RULE = f"""surface = "route"

[[rule]]
id = "project.text"
rung = "DECODE"
when = {{ "unit.format" = {{ in = ["txt"] }} }}
then = {{ driver = "{PROJECT_DRIVER}", terminal = true }}
"""


def _project(
    root: Path, *, rule: bool, card: Path = CARD, card_id: str = "parse.text.builtin"
) -> Path:
    project = root / "project"
    (project / "docs").mkdir(parents=True)
    cards = project / ".omniweave" / "drivers" / "text"
    cards.mkdir(parents=True)
    text = card.read_text(encoding="utf-8")
    assert text.count(f'id = "{card_id}"') == 1
    (cards / "driver.toml").write_text(
        text.replace(f'id = "{card_id}"', f'id = "{PROJECT_DRIVER}"'), encoding="utf-8"
    )
    enabled = ", ".join(f'"{driver}"' for driver in (*SHIPPED_DRIVERS, PROJECT_DRIVER))
    (project / "omniweave.toml").write_text(
        '[corpora.docs]\npath = ".omniweave/docs.owstore"\n[serve]\ndefault_corpus = "docs"\n'
        "[drivers]\nallow_unattested = true\nrequire_lock = false\ninproc = []\n"
        f"enabled = [{enabled}]\n",
        encoding="utf-8",
    )
    if rule:
        (project / POLICY_D).mkdir(parents=True)
        (project / POLICY_D / "10-text.toml").write_text(RULE, encoding="utf-8")
    (project / "docs" / "note.txt").write_text("First paragraph.\n\nSecond.\n", encoding="utf-8")
    return project


def _run(project: Path, verb: str) -> tuple[str, list[str], str]:
    keep = {k: v for k, v in os.environ.items() if k not in {"PYTHONUTF8", "PYTHONIOENCODING"}}
    home = project.parent / "home"
    done = run_captured(
        (sys.executable, "-m", "omniweave", verb, "docs"),
        stdin=b"",
        cwd=str(project),
        env={**keep, "HOME": str(home), "USERPROFILE": str(home), "OMNIWEAVE_HOME": str(home)},
        timeout_s=600,
    )
    shown = (done.stdout + done.stderr).decode("utf-8", "replace")
    assert done.returncode == 0, shown[-3000:]
    connection = ow.connect_readonly(project / ".omniweave" / "docs.owstore")
    try:
        drivers = sorted(
            {str(row[0]) for row in connection.execute("SELECT origin_driver FROM block")}
        )
        (digest,) = connection.execute("SELECT policy_digest FROM run").fetchone()
    finally:
        connection.close()
    return shown, drivers, str(digest)


@pytest.mark.parametrize(
    ("verb", "rule"),
    [("add", False), ("add", True), ("ingest", True)],
    ids=["add-builtin", "add-project-rule", "ingest-project-rule"],
)
def test_a_project_rule_routes_a_format_to_the_projects_own_driver(
    tmp_path: Path, verb: str, rule: bool
) -> None:
    """`ow add` and `ow ingest` both route by it: each passes the project root (D935)."""
    project = _project(tmp_path, rule=rule)
    shown, drivers, digest = _run(project, verb)
    used = PROJECT_DRIVER if rule else "parse.text.builtin"
    assert f"route     1 planned ({used} 1)" in shown, shown[-3000:]
    assert f"parse     1 parsed ({used} 1)" in shown, shown[-3000:]
    assert drivers == [used]
    config = load(cwd=project, env={"OMNIWEAVE_HOME": str(tmp_path / "home")})
    expected = compile_policy(route_layers(config, policy_dir=project / POLICY_D))
    assert digest == expected.policy_digest, "the run's policy_digest covers the project's rules"


def test_the_conformance_template_is_ingested_and_its_byte_spans_re_verify(tmp_path: Path) -> None:
    """D938: the kit's own template under a project card. Its stream page carried a box (D935)
    and its byte origins a bare codec and a kind the decoder refused; each passed all eleven
    suites, and `ow add` refused the document. Now it parses, and every stored `bytes` origin
    decodes from the retained part to its block's text, which is P7 read off the store."""
    project = _project(tmp_path, rule=True, card=TEMPLATE, card_id="parse.text.plain")
    shown, drivers, _digest = _run(project, "add")
    assert f"parse     1 parsed ({PROJECT_DRIVER} 1)" in shown, shown[-3000:]
    assert drivers == [PROJECT_DRIVER]
    connection = ow.connect_readonly(project / ".omniweave" / "docs.owstore")
    try:
        spans = connection.execute(
            "SELECT b.text, b.os_a, b.os_b, b.os_codec, p.store_ref FROM block AS b "
            "JOIN part AS p ON p.doc_ord = b.doc_ord AND p.path = b.os_part "
            "WHERE b.os_codec IS NOT NULL"
        ).fetchall()
    finally:
        connection.close()
    assert spans
    for text, start, length, codec, ref in spans:
        digest = str(ref).removeprefix("cas://").split("/")[-1]
        data = (project / ".omniweave" / "cas" / digest[:2] / digest[2:4] / digest).read_bytes()
        name, errors = str(codec).split("/", 1)
        decoded = data[start : start + length].decode(name, errors)
        assert unicodedata.normalize("NFC", decoded) == text
