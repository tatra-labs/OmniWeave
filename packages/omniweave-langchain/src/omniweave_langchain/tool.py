"""`create_omniweave_tool(...)`: a corpus as one LangChain tool, its Answer as the artifact. D909.

`_index/in-04-agentic.md:246`: the model sees the rendered text, *"which is correct, and is what
`cite` is for"*, and the artifact is the real object, which *"rides graph state, is never
serialized into the prompt"*. `ToolMessage.artifact` is the one lossless crossing in LangChain's
own types, so `response_format="content_and_artifact"` is the whole design.

## Rulings

1. **The content is `render(answer)`**, the text `ow query` prints: evidence with cites, the
   verdict, and the trailer that says what was not searched. An agent quoting it can cite.
2. **The artifact is the `Answer` itself**, every block's quote, trust, method and restriction
   included, for the middleware (a later PR) to harvest off the `ToolMessage`.
3. **One argument, `question`.** The tool asks one corpus, as `ow_query` does; a fan-out across
   corpora is deferred past v1.0 (D904), and a tool that silently fanned out would hide the
   incomparability of their scores.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from omniweave_langchain._common import open_corpus

if TYPE_CHECKING:
    from omniweave_core.answer.render import Answer

__all__ = ["DESCRIPTION", "QueryInput", "create_omniweave_tool"]

DESCRIPTION: Final = (
    "Ask the indexed documents a question. Returns cited passages (each cite like d7#12 names "
    "one passage), a verdict, and what was not searched. Quote passages with their cites; an "
    "'absent' verdict means the documents do not say it."
)


class QueryInput(BaseModel):
    """Ruling 3: the tool's one argument."""

    question: str = Field(description="what to look for in the documents, in plain words")


def create_omniweave_tool(
    corpus: str | None = None,
    *,
    config: str | Path | None = None,
    name: str = "omniweave_query",
    description: str = DESCRIPTION,
    k: int = 20,
    max_chars: int = 22_000,
) -> StructuredTool:
    """Rulings 1-3: a `StructuredTool` answering from `corpus`, content and artifact both."""

    def ask(question: str) -> tuple[str, Answer]:
        from omniweave_core.answer.render import render  # noqa: PLC0415

        handle = open_corpus(corpus, config, readonly=True)
        answer = handle.query(question, k=k, max_chars=max_chars)
        return render(answer, max_chars=max_chars), answer

    return StructuredTool.from_function(
        func=ask,
        name=name,
        description=description,
        args_schema=QueryInput,
        response_format="content_and_artifact",
    )
