"""`python -m omniweave_core.host.worker <base address>`: the S4 worker's process entry.

The exit status is set here and nowhere else, because `tools/gate_semgrep.py` exempts exactly
`__main__.py` from the library-code ban on `sys.exit` (02-architecture.md:392): a process entry has
to set its exit status somewhere, and the narrowest place is the file that is only ever run.
"""

from omniweave_core.host.worker import main

raise SystemExit(main())
