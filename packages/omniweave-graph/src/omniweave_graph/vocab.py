"""The closed vocabularies a Pass names, restated: this package may not import core. **D670.**

`omniweave_core.model.enums.AnchorKind` is the definition; `tests/unit/test_xref_rules.py` holds
`AKINDS` equal to it, so a member added there fails here until it is added here too.
"""

from __future__ import annotations

from typing import Final

__all__ = ["AKINDS"]

AKINDS: Final = frozenset(
    {
        "section",
        "clause",
        "figure",
        "table",
        "equation",
        "citekey",
        "identifier",
        "defined_term",
        "footnote",
        "exhibit",
        "slide",
        "sheet",
        "glossary",
        "bookmark",
    }
)
"""`AnchorKind`'s fourteen values: the `akind` of both `anchor` and `ref_site`."""
