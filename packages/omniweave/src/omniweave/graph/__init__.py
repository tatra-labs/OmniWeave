"""The host graph passes: the corpus-wide steps a driver cannot take (02 row 38, 11:254).

A driver may not hold a store handle, so a pass that needs the whole corpus's entities is the
host's. `resolve` is `op.resolve` (06 section 5). `op.lexicon` shipped earlier in
`omniweave.run.operators.lexicon`, beside the derive operator it queues rows for (D683).
"""
