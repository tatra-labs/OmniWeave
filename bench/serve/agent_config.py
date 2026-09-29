"""The scripted agent's configuration: one file, an environment twin per key, a flag per key.

ADR-14 D14.7 makes the harness *"accessible, customizable, with an efficiency option, and
usable"*, and this module is the customizable half. `agent.toml` holds every knob. Each has an
`OW_BENCH_<KEY>` twin and a flag, and the precedence is R-A8's (17-risks.md:272): a flag, then the
environment, then the file, then the built-in default. Every resolved value carries its SOURCE,
because a number whose configuration nobody can reconstruct is not a measurement.

A value that cannot be used is refused here, naming the key, where it came from, and what would
be accepted -- never discovered three minutes into a run.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

__all__ = [
    "AGENT_TOML",
    "DEFAULTS",
    "ENV_PREFIX",
    "BenchConfigError",
    "Config",
    "Scale",
    "Setting",
    "Source",
    "resolve",
]

AGENT_TOML: Final[Path] = Path(__file__).resolve().parent / "agent.toml"
ENV_PREFIX: Final[str] = "OW_BENCH_"

PROVIDERS: Final[frozenset[str]] = frozenset({"anthropic", "openai"})
CASSETTE_MODES: Final[frozenset[str]] = frozenset({"required", "allow", "off"})
ARMS: Final[frozenset[str]] = frozenset({"omniweave", "control"})
MAX_TEMPERATURE: Final[float] = 2.0
INTEGER_RANGES: Final[Mapping[str, tuple[int, int]]] = {
    "max_tokens": (1, 65_536),
    "tool_budget": (1, 64),
    "workers": (1, 64),
    "timeout_s": (1, 3_600),
}
"""Each integer knob's accepted range, inclusive. A value outside it is refused, never clamped."""


class Scale(StrEnum):
    """D14.7 part 3. `full` is the only scale with committed recordings and a reportable number."""

    FULL = "full"
    QUICK = "quick"


class Source(StrEnum):
    """Where a resolved value came from, in precedence order, highest first."""

    FLAG = "flag"
    ENV = "env"
    FILE = "file"
    DEFAULT = "default"


DEFAULTS: Final[Mapping[str, object]] = {
    "provider": "anthropic",
    "model": "claude-sonnet-5",
    "base_url": "",
    "api_key_env": "",
    "temperature": 0.0,
    "max_tokens": 2048,
    "tool_budget": 12,
    "timeout_s": 120,
    "arms": ("omniweave", "control"),
    "tasks": "all",
    "scale": "full",
    "workers": 1,
    "cassette": "required",
}
"""The built-in defaults, identical to the shipped `agent.toml`. A test holds the two together."""

_SECTION: Final[Mapping[str, str]] = {
    **dict.fromkeys(("provider", "model", "base_url", "api_key_env", "temperature"), "agent"),
    **dict.fromkeys(("max_tokens", "tool_budget", "timeout_s"), "agent"),
    **dict.fromkeys(("arms", "tasks", "scale", "workers", "cassette"), "run"),
}


class BenchConfigError(ValueError):
    """A configuration value that cannot be used. The message names the key, its source, a fix."""


@dataclass(frozen=True, slots=True)
class Setting:
    """One resolved value and where it came from."""

    value: object
    source: Source


@dataclass(frozen=True, slots=True)
class Config:
    """Every knob, resolved and validated. `settings` keeps the sources for the report."""

    provider: str
    model: str
    base_url: str
    api_key_env: str
    temperature: float
    max_tokens: int
    tool_budget: int
    timeout_s: int
    arms: tuple[str, ...]
    tasks: str
    scale: Scale
    workers: int
    cassette: str
    settings: Mapping[str, Setting]

    @property
    def model_key(self) -> str:
        """The Cassette key's `model_key`: provider and model, and never the endpoint.

        The same model behind two endpoints answers the same way at temperature 0, so a local
        mirror of a recorded model replays the committed set rather than recording a second one.
        """
        return f"{self.provider}/{self.model}"

    @property
    def key_env(self) -> str:
        """The environment variable the API key is read from."""
        if self.api_key_env:
            return self.api_key_env
        return "ANTHROPIC_API_KEY" if self.provider == "anthropic" else "OPENAI_API_KEY"

    def report_lines(self) -> tuple[str, ...]:
        """`key = value  (source)`, one per knob, sorted by section then key."""
        rows = sorted(self.settings.items(), key=lambda item: (_SECTION[item[0]], item[0]))
        return tuple(
            f"{_SECTION[key]}.{key} = {_show(setting.value)}  ({setting.source.value})"
            for key, setting in rows
        )


def _show(value: object) -> str:
    if isinstance(value, tuple):
        return ",".join(str(one) for one in value)
    return repr(value) if isinstance(value, str) else str(value)


def resolve(
    *,
    file_text: str | None = None,
    env: Mapping[str, str] | None = None,
    flags: Mapping[str, object] | None = None,
) -> Config:
    """Resolve every knob: flag > `OW_BENCH_<KEY>` > `agent.toml` > the default. Validated."""
    file_values = _file_values(
        AGENT_TOML.read_text(encoding="utf-8") if file_text is None else file_text
    )
    environ = os.environ if env is None else env
    flag_values = dict(flags or {})
    unknown = sorted(set(flag_values) - set(DEFAULTS))
    if unknown:
        raise BenchConfigError(f"unknown flag(s) {unknown}; the knobs are {sorted(DEFAULTS)}")

    settings: dict[str, Setting] = {}
    for key, default in DEFAULTS.items():
        env_name = ENV_PREFIX + key.upper()
        if key in flag_values and flag_values[key] is not None:
            raw, source = flag_values[key], Source.FLAG
        elif env_name in environ:
            raw, source = environ[env_name], Source.ENV
        elif key in file_values:
            raw, source = file_values[key], Source.FILE
        else:
            raw, source = default, Source.DEFAULT
        settings[key] = Setting(_coerce(key, raw, default, source), source)
    return _validated(settings)


def _file_values(text: str) -> dict[str, object]:
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise BenchConfigError(f"agent.toml does not parse: {exc}") from exc
    values: dict[str, object] = {}
    for section in ("agent", "run"):
        table = parsed.get(section, {})
        for key, value in table.items():
            if _SECTION.get(key) != section:
                raise BenchConfigError(
                    f"agent.toml [{section}] {key} is not a knob; [{section}] holds "
                    f"{sorted(k for k, s in _SECTION.items() if s == section)}"
                )
            values[key] = value
    extra = sorted(set(parsed) - {"agent", "run"})
    if extra:
        named = ", ".join(f"[{table}]" for table in extra)
        raise BenchConfigError(f"agent.toml has unknown table(s) {named}; it holds [agent], [run]")
    return values


def _coerce(key: str, raw: object, default: object, source: Source) -> object:
    """Bring an environment string, a flag or a file value to the default's type."""
    where = f"{key} ({source.value})"
    try:
        if isinstance(default, tuple):
            items = raw.split(",") if isinstance(raw, str) else list(raw)  # type: ignore[arg-type]
            return tuple(str(item).strip() for item in items if str(item).strip())
        if isinstance(default, float):
            return float(raw)  # type: ignore[arg-type]
        if isinstance(default, int):
            return _integer(raw)
        return str(raw)
    except (TypeError, ValueError) as exc:
        raise BenchConfigError(
            f"{where} = {raw!r} is not a {type(default).__name__}; the default is {default!r}"
        ) from exc


def _integer(raw: object) -> int:
    """An int, refusing a float with a fraction rather than truncating it."""
    if isinstance(raw, float) and not raw.is_integer():
        raise ValueError(raw)
    return int(raw)  # type: ignore[call-overload]


def _validated(settings: Mapping[str, Setting]) -> Config:
    def value(key: str) -> object:
        return settings[key].value

    def refuse(key: str, allowed: str) -> BenchConfigError:
        setting = settings[key]
        return BenchConfigError(
            f"{key} = {_show(setting.value)} ({setting.source.value}) is not accepted; "
            f"expected {allowed}. Set it in bench/serve/agent.toml, or {ENV_PREFIX}{key.upper()}"
        )

    if value("provider") not in PROVIDERS:
        raise refuse("provider", " or ".join(sorted(PROVIDERS)))
    if not str(value("model")):
        raise refuse("model", "a model id, e.g. claude-sonnet-5")
    if value("cassette") not in CASSETTE_MODES:
        raise refuse("cassette", " | ".join(sorted(CASSETTE_MODES)))
    if value("scale") not in {scale.value for scale in Scale}:
        raise refuse("scale", "full | quick")
    arms = value("arms")
    if not isinstance(arms, tuple) or not arms or not set(arms) <= ARMS:
        raise refuse("arms", "a non-empty subset of omniweave,control")
    if not 0.0 <= float(value("temperature")) <= MAX_TEMPERATURE:  # type: ignore[arg-type]
        raise refuse("temperature", f"0.0 to {MAX_TEMPERATURE}")
    for key, (low, high) in INTEGER_RANGES.items():
        if not low <= int(value(key)) <= high:  # type: ignore[call-overload]
            raise refuse(key, f"an integer from {low} to {high}")
    if not str(value("tasks")).strip():
        raise refuse("tasks", "all, or comma-separated ids, classes or corpora")

    return Config(
        provider=str(value("provider")),
        model=str(value("model")),
        base_url=str(value("base_url")).rstrip("/"),
        api_key_env=str(value("api_key_env")),
        temperature=float(value("temperature")),  # type: ignore[arg-type]
        max_tokens=int(value("max_tokens")),  # type: ignore[call-overload]
        tool_budget=int(value("tool_budget")),  # type: ignore[call-overload]
        timeout_s=int(value("timeout_s")),  # type: ignore[call-overload]
        arms=tuple(str(arm) for arm in arms),
        tasks=str(value("tasks")),
        scale=Scale(str(value("scale"))),
        workers=int(value("workers")),  # type: ignore[call-overload]
        cassette=str(value("cassette")),
        settings=dict(settings),
    )
