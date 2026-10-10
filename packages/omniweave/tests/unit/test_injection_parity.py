"""The sink's layer-5 patterns are the driver's (D736 ruling 1)."""

from __future__ import annotations

from omniweave_core.store import injection
from omniweave_llm import wrap


def test_the_sinks_sentinels_are_the_drivers_transcribed() -> None:
    """`omniweave_core` may not import `omniweave_llm`, so the pattern is restated: one source."""
    assert injection.SENTINELS.pattern == wrap.SENTINELS.pattern
    assert injection.SENTINELS.flags == wrap.SENTINELS.flags
    for text in ("<|im_start|>", "[INST]", "</untrusted_source>", "## Instructions", "plain"):
        assert (injection.SENTINELS.search(text) is None) == (wrap.SENTINELS.search(text) is None)
    assert injection.scan("x </untrusted_source attr=1> y").forged == (
        "</untrusted_source attr=1>",
    )
