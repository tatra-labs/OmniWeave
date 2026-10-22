"""05:941's `project` layer: `.omniweave/policy.d/*.toml`, loaded by routing. D935.

`route_layers()` compiled the builtin layer and `[ingest] max_parts` alone, so a project's own
route rules were read by nothing, though the builtin's `decode.text-native` says a third party's
driver takes a format through exactly such a rule. `project_layers()` loads them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from omniweave.route.policy import (
    POLICY_D,
    builtin_layer,
    compile_policy,
    project_layers,
)
from omniweave.run import routing
from omniweave_core.config import load, project_root
from omniweave_core.errors import RouteError

RULE = """surface = "route"

[[rule]]
id = "{id}"
rung = "DECODE"
when = {{ "unit.format" = {{ in = ["txt"] }} }}
then = {{ driver = "parse.text.plain", terminal = true }}
"""


def _write(directory: Path, name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(text, encoding="utf-8")


def test_no_directory_is_no_project_rules(tmp_path: Path) -> None:
    assert project_layers(tmp_path / "absent") == []


def test_files_load_in_basename_order_and_other_surfaces_are_skipped(tmp_path: Path) -> None:
    """05:950 and 05:952: lexicographic by basename, and a retrieval or graph file in the same
    directory governs nothing here."""
    _write(tmp_path, "20-second.toml", RULE.format(id="project.second"))
    _write(tmp_path, "10-first.toml", RULE.format(id="project.first"))
    _write(tmp_path, "15-retrieval.toml", 'surface = "retrieval"\n[[rule]]\nid = "r"\n')
    _write(tmp_path, "16-graph.toml", 'surface = "graph"\n')
    _write(tmp_path, "notes.md", "not a policy")
    layers = project_layers(tmp_path)
    assert [layer.origin for layer in layers] == [
        ".omniweave/policy.d/10-first.toml",
        ".omniweave/policy.d/20-second.toml",
    ]
    assert all(layer.layer == "project" for layer in layers)
    assert [rule.id for layer in layers for rule in layer.rules] == [
        "project.first",
        "project.second",
    ]
    assert layers[0].rules[0].origin.startswith("project:.omniweave/policy.d/10-first.toml:")


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ('[[rule]]\nid = "x"\n', "declares surface=None"),
        ('surface = "routing"\n', "declares surface='routing'"),
        ("surface = = 1\n", "is not readable TOML"),
    ],
)
def test_a_file_without_a_known_surface_is_refused_by_name(
    tmp_path: Path, text: str, says: str
) -> None:
    """05:951: *"a file without it, or with an unknown surface, fails to load"*."""
    _write(tmp_path, "10-bad.toml", text)
    with pytest.raises(RouteError, match=says) as raised:
        project_layers(tmp_path)
    assert ".omniweave/policy.d/10-bad.toml" in str(raised.value)


def test_a_project_rule_prepends_to_the_builtin_and_moves_the_digest(tmp_path: Path) -> None:
    """05:933: higher prepends, and first match wins; `policy_digest` covers the project's rules.
    The `max_parts` layer stays last, so `[ingest] max_parts` is still the cap."""
    config = load(cwd=tmp_path, env={"OMNIWEAVE_HOME": str(tmp_path / "h")})
    builtin = compile_policy([builtin_layer()])
    assert compile_policy(routing.route_layers(config, policy_dir=None)).policy_digest == (
        builtin.policy_digest
    )
    policy_dir = tmp_path / POLICY_D
    assert compile_policy(routing.route_layers(config, policy_dir=policy_dir)).policy_digest == (
        builtin.policy_digest
    ), "an absent policy.d is the builtin policy"
    _write(policy_dir, "10-plain.toml", RULE.format(id="project.text-plain"))
    layers = routing.route_layers(config, policy_dir=policy_dir)
    assert [layer.layer for layer in layers] == ["builtin", "project", "project"]
    assert layers[2].origin == "[ingest] max_parts"
    compiled = compile_policy(layers)
    decode = [rule.id for rule in compiled.rules if rule.rung.name == "DECODE"]
    assert decode.index("project.text-plain") < decode.index("decode.text-native")
    assert compiled.policy_digest != builtin.policy_digest


def test_the_project_root_is_the_directory_of_the_project_file(tmp_path: Path) -> None:
    """`config.project_root()`, which `ow doctor`, `ow out` and now ingest share (D935)."""
    home = {"OMNIWEAVE_HOME": str(tmp_path / "h")}
    assert project_root(load(cwd=tmp_path, env=home)) is None
    (tmp_path / "omniweave.toml").write_text("[ingest]\nmax_parts = 50\n", encoding="utf-8")
    below = tmp_path / "docs"
    below.mkdir()
    assert project_root(load(cwd=below, env=home)) == tmp_path
