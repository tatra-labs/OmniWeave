"""parse.text.builtin: the ten text formats anydoc does not serve, read with the standard library.

DISCOVERY READS `driver.toml` FROM THIS PACKAGE WITHOUT IMPORTING IT (INV-4), so nothing here may
import `omniweave_office.text.driver`. The second entry point in `omniweave-office`'s
`pyproject.toml` names this package; `activate()` resolves the card's `entrypoint` later.

Specified in 04-driver-system.md section 10.1 and 05-ingest-and-routing.md section 4.4.
"""
