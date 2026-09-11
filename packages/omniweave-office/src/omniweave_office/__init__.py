"""parse.office.anydoc across seam S1: the office family decoded over firecrawl-anydoc,
in process under DR9's five conditions, one call per document.

DISCOVERY READS `driver.toml` FROM THIS PACKAGE WITHOUT IMPORTING IT (INV-4), so nothing here may
import `anydoc` or `omniweave_office.driver`. The entry point in `pyproject.toml` names this package
and nothing deeper; `activate()` resolves the card's `entrypoint` later, and only after the card has
been read and filtered.

Specified in 02-architecture.md section 2 row 41 and 04-driver-system.md section 10.1.
"""
