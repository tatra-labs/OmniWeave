# `bench/serve/`

The adoption harness of `13-quality.md` section 8.8: 30 scripted tasks, two arms (omniweave and a
no-omniweave control), and two numbers that are only ever reported together —
`source_reread_rate` and `task_accuracy`.

```
bench/serve/
├── serve_harness.py   the instrument: catalogue, transcripts, per-task facts, rates, the Control guard
├── first_answer.py    first_answer_seconds (V01-15): ow install -> ow add -> ow query, timed, reversed
├── test_first_answer.py  its rules: the folder, the judge, the verdict and the exit
├── tasks.toml         the 30-task catalogue. EMPTY until the reference corpora exist (D602)
├── test_harness.py    the rules, pinned over synthetic transcripts before any real one exists
└── conftest.py        --tasks
```

## Running it

```bash
uv run pytest bench/serve -q                # the harness's own rules
uv run pytest bench/serve -q --tasks all    # 16-roadmap.md:745's P7 exit command
uv run python bench/serve/first_answer.py   # V01-15 and P7's demo, over 100 generated documents
```

The second **fails today, on purpose**, and names why: the catalogue holds 0 of 30 tasks (D602) and
no scripted agent is wired to run one. It passes when both land.

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
