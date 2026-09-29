"""The scripted agent's Cassette site, `bench.agent` (ADR-14 D14.4).

13-quality.md:1402 puts *"every model call"* through a Cassette, *"the scripted agent included"*,
and 13 section 7.3 records at exactly two framework seams, neither of which an agent's own turns
pass through. ADR-14 D14.4 resolves it: a third site, reachable only from `bench/`, that shares
everything with the framework's but the seam.

Shared with `omniweave_core.cassette`, by import:
- the key recipe, `sha256_canonical` over 13:978's six fields;
- `CassetteMode`'s three modes, with `required` never calling the provider;
- `MAX_CASSETTE_BYTES` per file (256 KiB), refused at record time as `OW-Q-017`;
- the `<service>/<key[:2]>/<key>.json` layout, under `fixtures/cassettes/`.

Its own: the record envelope. Core's `Interaction` and `ContractIdentity` are typed to the two
framework seams, and widening them is ADR-14's rejected alternative. A record holds the key's
inputs and the model's `Turn`, never the request body: that is re-derivable from the fixtures and
the harness, and a request carrying page images would breach the per-file cap for no reviewer's
benefit. No header is recorded, so no key can be.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from models import ModelRequest, Turn, canonical_request, turn_from_json, turn_json
from omniweave_core.canonical import sha256_canonical
from omniweave_core.cassette import MAX_CASSETTE_BYTES, CassetteMode

__all__ = [
    "CASSETTE_ROOT",
    "HARNESS_MAJOR",
    "PROMPT_VERSION",
    "RECORD_VERSION",
    "SEAM",
    "SERVICE",
    "AgentCassette",
    "CassetteMissError",
    "CassetteOversizeError",
    "request_key",
]

SERVICE: Final[str] = "agent"
SEAM: Final[str] = "bench.agent"
HARNESS_MAJOR: Final[int] = 1
"""The site's `contract_major`. Bumped when the loop's wire to the model changes meaning."""

PROMPT_VERSION: Final[str] = "agent-prompt/2"
"""The system prompt's version. 13:984: a recording whose prompt version no longer matches is a
MISS, never a hit."""

RECORD_VERSION: Final[int] = 1
CASSETTE_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes"


class CassetteMissError(LookupError):
    """`OW-Q-004`: a `required` run found no recording. Never followed by a live call."""


class CassetteOversizeError(ValueError):
    """`OW-Q-017`: a recording over `MAX_CASSETTE_BYTES`, refused at record time."""


def request_key(request: ModelRequest, *, model_key: str) -> tuple[str, dict[str, Any]]:
    """13:978's six fields for one agent turn, and their `sha256_canonical`."""
    conversation = canonical_request(request)
    images = [
        image
        for message in conversation["messages"]
        if message["role"] == "tool"
        for image in message["images"]
    ]
    inputs: dict[str, Any] = {
        "contract": [SEAM, HARNESS_MAJOR],
        "model_key": model_key,
        "payload_digest": hashlib.sha256("\n".join(images).encode()).hexdigest(),
        "prompt_digest": sha256_canonical(conversation),
        "sampling": {
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            **dict(request.sampling),
        },
        "service": SERVICE,
    }
    return sha256_canonical(inputs), inputs


@dataclass
class AgentCassette:
    """One run's view of the agent recordings: a mode, a root, and the ledger of what it did."""

    mode: CassetteMode
    root: Path = CASSETTE_ROOT

    def __post_init__(self) -> None:
        self.hits: list[str] = []
        self.recorded: list[str] = []
        self.live_calls = 0

    def path_for(self, key: str) -> Path:
        return self.root / SERVICE / key[:2] / f"{key}.json"

    def turn(
        self,
        request: ModelRequest,
        *,
        model_key: str,
        live: Callable[[ModelRequest], Turn] | None,
    ) -> Turn:
        """Replay, record, or refuse -- 13:982's three modes, in the order that guarantees them."""
        key, inputs = request_key(request, model_key=model_key)
        if self.mode is CassetteMode.OFF:
            return self._live(request, live, key)
        found = self._load(key, inputs)
        if found is not None:
            self.hits.append(key)
            return found
        if self.mode is CassetteMode.REQUIRED:
            raise CassetteMissError(
                f"OW-Q-004 cassette miss for {SERVICE} key {key} (model {model_key}). The "
                "conversation differs from every committed recording -- an answer, a tool "
                "description or the prompt changed. Re-record with cassette = allow and a "
                "provider (bench/serve/agent.toml), or restore the change"
            )
        turn = self._live(request, live, key)
        self._save(key, inputs, turn)
        return turn

    def _live(
        self, request: ModelRequest, live: Callable[[ModelRequest], Turn] | None, key: str
    ) -> Turn:
        if live is None:
            raise CassetteMissError(
                f"key {key} needs a live model call and no provider was configured; set "
                "provider and its key in bench/serve/agent.toml, or use cassette = required"
            )
        self.live_calls += 1
        return live(request)

    def _load(self, key: str, inputs: dict[str, Any]) -> Turn | None:
        path = self.path_for(key)
        if not path.is_file():
            return None
        record = json.loads(path.read_bytes())
        if (
            record.get("record_version") != RECORD_VERSION
            or record.get("key") != key
            or record.get("seam") != SEAM
            or record.get("contract_major") != HARNESS_MAJOR
            or record.get("prompt_version") != PROMPT_VERSION
            or record.get("inputs") != inputs
        ):
            return None
        return turn_from_json(record["turn"])

    def _save(self, key: str, inputs: dict[str, Any], turn: Turn) -> None:
        record = {
            "record_version": RECORD_VERSION,
            "key": key,
            "seam": SEAM,
            "contract_major": HARNESS_MAJOR,
            "prompt_version": PROMPT_VERSION,
            "inputs": inputs,
            "turn": turn_json(turn),
        }
        raw = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
        if len(raw) > MAX_CASSETTE_BYTES:
            raise CassetteOversizeError(
                f"OW-Q-017 cassette {key} is {len(raw)} bytes, over MAX_CASSETTE_BYTES "
                f"({MAX_CASSETTE_BYTES}); re-record against a smaller fixture"
            )
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.recorded.append(key)
