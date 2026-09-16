"""worth, allocate, dedup, untrusted, render. LAZY. 02-architecture.md section 2 row 28.

**W6.6c** completes the six: `render` ships the nine-section document, the two orders (funding and
cut, which disagree on `ow:provenance`), the truncator that cuts whole sections and whole blocks,
and
`SUMMARY_SENTINEL`. `Answer` is re-exported here because `tools/schemagen.py` generates
`schema/answer-v1.json` from `omniweave_core.answer:Answer` and that is the path the inventory
names.

**W6.6a** shipped `budget` (the five tiers keyed on indexed blocks, `HARD_CEILING`, and 10:479's
clamp), `worth` (the four tables that penalise BYTE SHARE and not rank) and `allocate`
(reserve-then-render, the 15% cliff, and the `MIN_CHARS` floor). **W6.6b** adds `untrusted`
(`sanitize_label`'s five steps, defanging by form on a copy, and the one `<ow:untrusted>` frame) and
`dedup` (the emission ledger, and the two facts withholding requires).

`render()` is 18:842's public entry point and SV19's one implementation three surfaces share, so
it is the name this package exists to export. The other five are its inputs.

**The order in this package is not 02:502's.** That row draws `worth -> allocate -> dedup ->
untrusted -> render`; 10:585 makes `ow:sent-earlier` *"charged before allocation"*, which is
impossible unless the withholding decision precedes the allocator. `dedup` runs first here. D277.

`budget` is a sixth module name. 11:207 lists five and omits it; charter.md:6641 names it, and
so does 02:252 -- *"`budget.py`'s five block-count-tiered budget layers from `[serve.packing]
tier`"* -- and the tiers have to live somewhere `worth` and `allocate` can both read without
importing each other. It is D260's family: two module lists for one package, disagreeing.

Nothing here is eager. G17 asserts a bare `import omniweave_core` loads none of the nine lazy
subpackages, and this one is on the per-turn path of every hook.
"""

from omniweave_core.answer.render import (
    Answer,
    ImpactRow,
    LicenceNotice,
    Pointer,
    RenderedBlock,
    render,
)
from omniweave_core.answer.untrusted import sanitize_label, wrap_untrusted

__all__ = [
    "Answer",
    "ImpactRow",
    "LicenceNotice",
    "Pointer",
    "RenderedBlock",
    "render",
    "sanitize_label",
    "wrap_untrusted",
]
"""18:842 homes exactly three names at this package -- `render()`, `wrap_untrusted()` and
`sanitize_label()`. The five shapes are here because `schema/answer-v1.json` is reflected from
`omniweave_core.answer:Answer` and a `$ref` chain that leaves the package would be a second home."""
