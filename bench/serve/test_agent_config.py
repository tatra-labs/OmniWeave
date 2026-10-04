"""`agent_config.resolve()`: one file, an environment twin and a flag per key (ADR-14 D14.7)."""

from __future__ import annotations

import agent_config as ac
import pytest


def test_the_shipped_file_is_the_defaults_so_the_two_cannot_drift() -> None:
    config = ac.resolve(env={})
    for key, default in ac.DEFAULTS.items():
        setting = config.settings[key]
        assert setting.value == default, key
        assert setting.source is ac.Source.FILE, key


def test_the_default_run_replays_and_needs_no_key() -> None:
    config = ac.resolve(env={})
    assert config.cassette == "required"
    assert config.scale is ac.Scale.FULL
    assert config.model_key == "anthropic/claude-sonnet-5"
    assert config.key_env == "ANTHROPIC_API_KEY"


def test_a_flag_beats_the_environment_which_beats_the_file_which_beats_the_default() -> None:
    config = ac.resolve(
        file_text='[agent]\nmodel = "from-file"\ntool_budget = 8\n[run]\nworkers = 2\n',
        env={"OW_BENCH_MODEL": "from-env", "OW_BENCH_TOOL_BUDGET": "9"},
        flags={"tool_budget": 10},
    )
    assert (config.model, config.settings["model"].source) == ("from-env", ac.Source.ENV)
    assert (config.tool_budget, config.settings["tool_budget"].source) == (10, ac.Source.FLAG)
    assert (config.workers, config.settings["workers"].source) == (2, ac.Source.FILE)
    assert config.settings["provider"].source is ac.Source.DEFAULT


def test_a_none_flag_is_absent_so_argparse_defaults_do_not_shadow_the_file() -> None:
    config = ac.resolve(file_text="[agent]\ntool_budget = 8\n", env={}, flags={"tool_budget": None})
    assert config.settings["tool_budget"] == ac.Setting(8, ac.Source.FILE)


def test_a_local_openai_compatible_server_is_one_line_of_configuration() -> None:
    config = ac.resolve(
        env={
            "OW_BENCH_PROVIDER": "openai",
            "OW_BENCH_MODEL": "qwen3:8b",
            "OW_BENCH_BASE_URL": "http://localhost:11434/v1/",
            "OW_BENCH_CASSETTE": "allow",
        }
    )
    assert config.base_url == "http://localhost:11434/v1"
    assert config.key_env == "OPENAI_API_KEY"
    assert config.model_key == "openai/qwen3:8b"


def test_a_list_knob_reads_a_comma_list_from_the_environment() -> None:
    assert ac.resolve(env={"OW_BENCH_ARMS": "control"}).arms == ("control",)
    assert ac.resolve(env={"OW_BENCH_ARMS": "omniweave, control"}).arms == (
        "omniweave",
        "control",
    )


def test_the_quick_scale_is_the_efficiency_option() -> None:
    config = ac.resolve(env={"OW_BENCH_SCALE": "quick", "OW_BENCH_WORKERS": "4"})
    assert (config.scale, config.workers) == (ac.Scale.QUICK, 4)


@pytest.mark.parametrize(
    ("env", "names"),
    [
        ({"OW_BENCH_PROVIDER": "gemini"}, ("provider", "env", "OW_BENCH_PROVIDER")),
        ({"OW_BENCH_TOOL_BUDGET": "0"}, ("tool_budget", "1 to 64")),
        ({"OW_BENCH_TOOL_BUDGET": "twelve"}, ("tool_budget", "not a int")),
        ({"OW_BENCH_TEMPERATURE": "3"}, ("temperature", "0.0 to 2.0")),
        ({"OW_BENCH_SCALE": "tiny"}, ("scale", "full | quick")),
        ({"OW_BENCH_CASSETTE": "record"}, ("cassette", "allow")),
        ({"OW_BENCH_ARMS": "both"}, ("arms", "omniweave,control")),
    ],
)
def test_an_unusable_value_is_refused_naming_its_key_source_and_fix(
    env: dict[str, str], names: tuple[str, ...]
) -> None:
    with pytest.raises(ac.BenchConfigError) as caught:
        ac.resolve(env=env)
    for name in names:
        assert name in str(caught.value)


def test_a_fractional_integer_is_refused_rather_than_truncated() -> None:
    with pytest.raises(ac.BenchConfigError, match="tool_budget"):
        ac.resolve(file_text="[agent]\ntool_budget = 12.5\n", env={})


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("[agent]\nscale = 'quick'\n", ("[agent] scale", "[agent] holds")),
        ("[models]\nx = 1\n", ("[models]",)),
        ("[agent\n", ("does not parse",)),
    ],
)
def test_a_file_that_misplaces_a_knob_is_refused(text: str, names: tuple[str, ...]) -> None:
    with pytest.raises(ac.BenchConfigError) as caught:
        ac.resolve(file_text=text, env={})
    for name in names:
        assert name in str(caught.value)


def test_an_unknown_flag_is_refused() -> None:
    with pytest.raises(ac.BenchConfigError, match="unknown flag"):
        ac.resolve(env={}, flags={"budget": 3})


def test_the_report_prints_every_knob_with_its_source() -> None:
    lines = ac.resolve(env={"OW_BENCH_WORKERS": "3"}).report_lines()
    assert len(lines) == len(ac.DEFAULTS)
    assert "run.workers = 3  (env)" in lines
    assert "agent.model = 'claude-sonnet-5'  (file)" in lines
    assert "run.arms = omniweave,control  (file)" in lines


@pytest.mark.parametrize(("raw", "expected"), [("default", None), ("DEFAULT", None), ("0.7", 0.7)])
def test_temperature_is_the_word_default_or_a_number(raw: str, expected: float | None) -> None:
    """D650: `"default"` sends none, which the shipped model needs; a number is still a number."""
    config = ac.resolve(env={"OW_BENCH_TEMPERATURE": raw})
    assert config.temperature == expected
    assert ac.resolve(env={}).temperature is None


def test_a_temperature_that_is_neither_is_refused_naming_both_forms() -> None:
    with pytest.raises(ac.BenchConfigError, match=r'"default", or 0.0 to 2.0'):
        ac.resolve(env={"OW_BENCH_TEMPERATURE": "warm"})
