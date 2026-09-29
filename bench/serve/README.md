# `bench/serve/`

The adoption harness of `13-quality.md` section 8.8: 30 scripted tasks, two arms (omniweave and a
no-omniweave control), and two numbers that are only ever reported together —
`source_reread_rate` and `task_accuracy`. ADR-14 specifies what it runs on: the corpora, the
tasks, the control arm and the scripted agent.

```
bench/serve/
├── serve_harness.py   the instrument: catalogue, transcripts, per-task facts, rates, the Control guard
├── agent.py           the scripted agent: one loop, two arms, a fixed tool budget (ADR-14 D14.3)
├── agent.toml         every knob of the agent and of a run, each with an OW_BENCH_<KEY> twin
├── agent_config.py    resolves agent.toml: flag > environment > file > default, with sources
├── agent_cassette.py  the bench.agent Cassette site: record, replay, refuse (ADR-14 D14.4)
├── models.py          provider-neutral turns; the anthropic and openai-compatible clients
├── host_tools.py      Read, Grep and a read-only Bash over the corpus, one converter per format
├── smoke.py           the omniweave arm end to end against a real `ow serve`, no model, no key
├── first_answer.py    first_answer_seconds (V01-15): ow install -> ow add -> ow query, timed, reversed
├── tasks.toml         the 30-task catalogue. EMPTY until the reference corpora exist (D602)
├── test_*.py          the rules, pinned offline
└── conftest.py        --tasks
```

## Running it

```bash
uv run pytest bench/serve -q                # the harness's own rules; offline, no key
uv run python bench/serve/smoke.py          # the agent reaches a real `ow serve`; no key
uv run pytest bench/serve -q --tasks all    # 16-roadmap.md:745's P7 exit command
uv run python bench/serve/first_answer.py   # V01-15 and P7's demo, over 100 generated documents
```

`--tasks all` **fails today, on purpose**, and names why: the catalogue holds 0 of 30 tasks (D602).
It passes when the corpora and tasks land (ADR-14 D14.1-D14.2).

## Configuring the agent

Everything is in `agent.toml`. Every key has an environment twin, `OW_BENCH_<KEY>`. The report
prints each resolved value and where it came from.

- **The default needs nothing.** `cassette = "required"` replays the committed recordings under
  `fixtures/cassettes/agent/`, and calls no provider: no key, no network, no GPU.
- **Record with a local model, for free.** Any server that speaks the OpenAI Chat Completions wire
  works, and a local one needs no key:

  ```bash
  OW_BENCH_PROVIDER=openai OW_BENCH_MODEL=qwen3:8b \
  OW_BENCH_BASE_URL=http://localhost:11434/v1 OW_BENCH_CASSETTE=allow ...
  ```

  Ollama is shown; vLLM, llama.cpp and LM Studio work the same way. A model other than the
  committed one records beside the committed set, never over it.
- **Record with Anthropic.** `provider = "anthropic"` reads `ANTHROPIC_API_KEY`, or the variable
  `api_key_env` names. The key never enters a recording.
- **Go faster.** `scale = "quick"` keeps every task and planted fact, and cuts the filler about
  twentyfold. `workers` runs tasks in parallel. A `quick` number is watermarked, and never gates.

## What it measures

- **`source_reread_rate`** — a task rereads when the agent reads an indexed source (`Read`, `Grep`,
  or a shell read) after its first `ow_query`/`ow_open`, or at all if it made neither. "Indexed" is
  the corpus receipt, `omniweave.index.lock`. One rule for both arms (D601).
- **`task_accuracy`** — the fraction of tasks whose final answer is **right**, graded by substrings
  (D600).
- **F19's mis-pick rate** — the first omniweave tool, against `ow_open` for a citation-shaped task
  and `ow_query` for the rest.

Every rate carries its Wilson 95% interval, and every report is sliced by born-digital versus
scanned and by task class. The **Control guard** fails a run whose omniweave arm is less accurate
than the control arm at one-sided exact McNemar `p < 0.01`, and a run whose re-read rate fell while
its accuracy fell with it.

**The two arms differ in one thing** (ADR-14 D14.3). Both have the same model, prompt, budget
(12 tool calls), `Read`/`Grep`/`Bash` and converters: a PDF's text layer via pypdfium2, a page
image where a PDF page has none, and anydoc's markdown for office files. Only the omniweave arm
also has `ow serve`.
