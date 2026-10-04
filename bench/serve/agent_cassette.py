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

**The corpora's folder is not in a key (D650).** The system prompt names the corpus folder, and the
model copies it into every Grep and Read it asks for, so a key over the raw conversation held the
recording machine's `--cache` path: the committed set replayed on that machine, at that path, and
missed everywhere else, the nightly job and every contributor included. The key, and the recorded
turn, spell that folder `CORPORA`; a loaded turn gets the replaying machine's folder back.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from urllib.parse import quote

from models import ModelRequest, Turn, canonical_request, turn_from_json, turn_json
from omniweave_core.canonical import sha256_canonical
from omniweave_core.cassette import MAX_CASSETTE_BYTES, CassetteMode
from omniweave_core.host import keystore
from omniweave_core.limits import MAX_CASSETTE_BYTES_TOTAL

__all__ = [
    "CASSETTE_ROOT",
    "CORPORA",
    "HARNESS_MAJOR",
    "PROMPT_VERSION",
    "RECORD_VERSION",
    "SEAM",
    "SERVICE",
    "AgentCassette",
    "CassetteMissError",
    "CassetteOversizeError",
    "audit",
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
CORPORA: Final[str] = "{bench-cache}"
"""How a key and a recorded turn spell the folder the corpora are prepared under (D650)."""
CASSETTE_ROOT: Final[Path] = Path(__file__).resolve().parents[2] / "fixtures" / "cassettes"


class CassetteMissError(LookupError):
    """`OW-Q-004`: a `required` run found no recording. Never followed by a live call."""


class CassetteOversizeError(ValueError):
    """`OW-Q-017`: a recording over `MAX_CASSETTE_BYTES`, refused at record time."""


_SERVICE: Final[str] = re.escape(keystore.SERVICE)
_NAME: Final[str] = r"[A-Za-z0-9_.-]+"
STORE_COMMANDS: Final[re.Pattern[str]] = re.compile(
    rf"cmdkey /generic:{_SERVICE}/(?P<w>{_NAME}) /user:{_SERVICE} /pass"
    rf"|security add-generic-password -s {_SERVICE} -a (?P<m>{_NAME}) -w"
    rf'|secret-tool store --label="{_SERVICE} (?P<l>{_NAME})" service {_SERVICE} name (?P=l)'
)
"""The three platforms' spellings of `keystore.store_command`. **D653.** An answer about an
encrypted file names the command that stores its password on the machine it runs on, which is
right for a user and made the conversation a different one on each OS. A key and a recorded turn
spell it `{store-command:NAME}`, and a replay prints this machine's."""


def _commands(text: str) -> str:
    """`text` with each platform's store command as its machine-free placeholder."""
    return STORE_COMMANDS.sub(
        lambda m: "{store-command:" + (m["w"] or m["m"] or m["l"]) + "}", text
    )


SELF_LENGTH: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(chars=)( *\d+)(/\d+)"),
    re.compile(r"(=)( *\d+)(/\d+ chars)(?!=)"),
)
"""An Answer's own length, as its status and budget lines print it (10:617: `chars= 5682/12000`,
`budget = 5682/12000 chars`). **D653.** The length counts every character, the corpus folder and
the store command included, so it differed by machine after both were placeholders. In a key it is
the length of the document as the key spells it."""


def _relength(raw: str, neutral: str) -> str:
    """`neutral` with each self-reported length lowered by the characters neutralising removed."""
    if "chars" not in neutral:
        return neutral
    removed = len(raw) - len(neutral)
    for pattern in SELF_LENGTH:
        neutral = pattern.sub(lambda m: f"{m[1]}{int(m[2]) - removed:>{len(m[2])}}{m[3]}", neutral)
    return neutral


_COMMAND_TAG: Final[re.Pattern[str]] = re.compile(r"\{store-command:(" + _NAME + r")\}")


def _spellings(root: Path) -> re.Pattern[str]:
    """Every way a conversation spells `root`: either separator, a JSON-escaped backslash, a
    `file:` URI's percent-encoding, and on Windows any case, since the model and a tool may each
    write the folder its own way."""
    parts = [
        "(?:" + "|".join(sorted({re.escape(part), re.escape(quote(part))})) + ")"
        for part in root.resolve().as_posix().split("/")
    ]
    flags = re.IGNORECASE if sys.platform == "win32" else 0
    return re.compile(r"(?:/|\\{1,2})".join(parts), flags)


def _neutral(value: Any, spellings: re.Pattern[str] | None) -> Any:
    """`value` with every spelling of the corpora's folder as `CORPORA`."""
    if isinstance(value, str):
        neutral = _commands(value)
        neutral = neutral if spellings is None else spellings.sub(lambda _m: CORPORA, neutral)
        return _relength(value, neutral)
    if isinstance(value, list):
        return [_neutral(one, spellings) for one in value]
    if isinstance(value, dict):
        return {key: _neutral(one, spellings) for key, one in value.items()}
    return value


def _forms(root: Path) -> dict[str, str]:
    """The spellings of `root` a recorded turn keeps apart, by the placeholder each is stored as.

    A key does not need them: every spelling is `CORPORA` there. A turn does, because its text is
    what the agent answers with: omniweave writes paths case-folded on Windows, and a replay that
    gave them back in the resolved spelling would change an answer that echoes one (the conform
    test of a local model's run caught exactly that). The plain placeholder is the resolved
    spelling, which is all a turn recorded before the tags could hold.
    """
    base = root.resolve().as_posix()
    tags = {
        CORPORA: base,
        "{bench-cache|backslash}": base.replace("/", "\\"),
        "{bench-cache|uri}": quote(base),
    }
    if sys.platform == "win32":
        tags["{bench-cache|casefold}"] = base.casefold()
        tags["{bench-cache|casefold|backslash}"] = base.casefold().replace("/", "\\")
    forms: dict[str, str] = {}
    for tag, spelled in tags.items():
        if spelled not in forms.values():
            forms[tag] = spelled
    return forms


def _tagged(value: Any, root: Path | None) -> Any:
    """`value` with each of `_forms`' spellings as its own placeholder, and any other spelling
    `_spellings` matches as `CORPORA`, for a recorded turn."""
    if isinstance(value, str):
        value = _commands(value)
        if root is None:
            return value
        forms = _forms(root)
        for tag, spelled in sorted(forms.items(), key=lambda item: -len(item[1])):
            value = value.replace(spelled, tag)
        return _spellings(root).sub(lambda _m: CORPORA, value)
    if isinstance(value, list):
        return [_tagged(one, root) for one in value]
    if isinstance(value, dict):
        return {key: _tagged(one, root) for key, one in value.items()}
    return value


def _local(value: Any, root: Path | None) -> Any:
    """`_tagged`'s inverse: each placeholder as this machine's folder, in the spelling it held."""
    if isinstance(value, str):
        value = _COMMAND_TAG.sub(lambda m: keystore.store_command(m[1]), value)
        if root is None:
            return value
        for tag, spelled in _forms(root).items():
            value = value.replace(tag, spelled)
        return value
    if isinstance(value, list):
        return [_local(one, root) for one in value]
    if isinstance(value, dict):
        return {key: _local(one, root) for key, one in value.items()}
    return value


def request_key(
    request: ModelRequest, *, model_key: str, corpora: Path | None = None
) -> tuple[str, dict[str, Any]]:
    """13:978's six fields for one agent turn, and their `sha256_canonical`.

    `corpora` is the folder the corpora are prepared under: spelled `CORPORA`, so the key is the
    same on every machine (D650).
    """
    conversation = _neutral(
        canonical_request(request), None if corpora is None else _spellings(corpora)
    )
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
    corpora: Path | None = None
    """The folder the corpora are prepared under, which no key or record holds (D650)."""

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
        key, inputs = request_key(request, model_key=model_key, corpora=self.corpora)
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
        return turn_from_json(_local(record["turn"], self.corpora))

    def _save(self, key: str, inputs: dict[str, Any], turn: Turn) -> None:
        record = {
            "record_version": RECORD_VERSION,
            "key": key,
            "seam": SEAM,
            "contract_major": HARNESS_MAJOR,
            "prompt_version": PROMPT_VERSION,
            "inputs": inputs,
            "turn": _tagged(turn_json(turn), self.corpora),
        }
        raw = _encode(record)
        if len(raw) > MAX_CASSETTE_BYTES:
            raise CassetteOversizeError(
                f"OW-Q-017 cassette {key} is {len(raw)} bytes, over MAX_CASSETTE_BYTES "
                f"({MAX_CASSETTE_BYTES}); re-record against a smaller fixture"
            )
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.recorded.append(key)


def _encode(record: dict[str, Any]) -> bytes:
    """The one spelling a record is written in, so a hand edit is a difference `audit` sees."""
    return (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def audit(root: Path = CASSETTE_ROOT) -> tuple[int, int, list[str]]:
    """Every committed recording, checked without a corpus, a provider or a model. **D650.**

    The `golden` job's Cassette half (11-repo-layout.md section 6.2), on every pull request. A full
    replay needs the full-scale corpora ingested, which is the nightly two-arm job's (ADR-14
    D14.5), not a four-minute job's. What a pull request can break without touching a model is
    the store itself, and each check here is one way it does:

    - a file that is not one record: it does not decode, or names a version the replay refuses;
    - a key that is not its inputs' `sha256_canonical`, or a file not at `path_for(key)`: replay
      can never find it, so the recording is dead weight a full run would report as a miss;
    - a record not in `_encode`'s spelling: a hand edit, which a review would otherwise not see;
    - a file over `MAX_CASSETTE_BYTES`, or a store over `MAX_CASSETTE_BYTES_TOTAL` (13:614).

    Returns the recording count, the store's bytes, and one line per problem, each naming the file.
    """
    store = AgentCassette(CassetteMode.REQUIRED, root)
    base = root / SERVICE
    problems: list[str] = []
    count = total = 0
    for path in sorted(base.rglob("*")) if base.is_dir() else []:
        if path.is_dir():
            continue
        shown = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        count, total = count + 1, total + len(raw)
        if path.suffix != ".json":
            problems.append(f"{shown}: not a recording (only <key>.json files belong here)")
            continue
        if len(raw) > MAX_CASSETTE_BYTES:
            problems.append(
                f"{shown}: {len(raw)} bytes, over MAX_CASSETTE_BYTES ({MAX_CASSETTE_BYTES})"
            )
        try:
            record = json.loads(raw)
            turn_from_json(record["turn"])
            key, inputs = record["key"], record["inputs"]
        except (ValueError, KeyError, TypeError) as exc:
            problems.append(f"{shown}: not a record ({type(exc).__name__}: {exc})")
            continue
        current = (RECORD_VERSION, SEAM, HARNESS_MAJOR, PROMPT_VERSION)
        found = tuple(
            record.get(name)
            for name in ("record_version", "seam", "contract_major", "prompt_version")
        )
        if found != current:
            problems.append(f"{shown}: written for {found}, and replay reads only {current}")
        if sha256_canonical(inputs) != key:
            problems.append(f"{shown}: its key is not the sha256_canonical of its inputs")
        if path != store.path_for(key):
            problems.append(f"{shown}: filed away from its key; replay reads {key[:2]}/{key}.json")
        if raw != _encode(record):
            problems.append(f"{shown}: not in the spelling a recording is written in (hand edit?)")
    if total > MAX_CASSETTE_BYTES_TOTAL:
        problems.append(
            f"the store is {total} bytes, over MAX_CASSETTE_BYTES_TOTAL "
            f"({MAX_CASSETTE_BYTES_TOTAL})"
        )
    return count, total, problems
