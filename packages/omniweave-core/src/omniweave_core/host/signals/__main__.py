"""`python -m omniweave_core.host.signals`: a signal provider's child, one request per process.

The exit status is set here and nowhere else, for `host/worker/__main__.py`'s reason: `__main__.py`
is the one file `tools/gate_semgrep.py` exempts from the library-code ban on `sys.exit`.
"""

from omniweave_core.host.signals import main

raise SystemExit(main())
