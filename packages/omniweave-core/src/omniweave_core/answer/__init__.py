"""worth, allocate, dedup, untrusted, render. LAZY. 02-architecture.md section 2 row 28.

**W6.6a** ships the first three of the six modules 11-repo-layout.md:207 lists: `budget` (the five
tiers keyed on indexed blocks, `HARD_CEILING`, and 10:479's clamp), `worth` (the four tables that
penalise BYTE SHARE and not rank) and `allocate` (reserve-then-render, the 15% cliff, and the
`MIN_CHARS` floor). `dedup`, `untrusted` and `render` are W6.6b and W6.6c and are absent, so nothing
here renders yet: `allocate()` returns a byte plan, and `render()` -- which 18:842 makes this
package's one public entry point, and SV19 makes the one implementation three surfaces share -- is
the cell that spends it.

`budget` is a sixth module name. 11:207 lists five and omits it; charter.md:6641 names it, and
so does 02:252 -- *"`budget.py`'s five block-count-tiered budget layers from `[serve.packing]
tier`"* -- and the tiers have to live somewhere `worth` and `allocate` can both read without
importing each other. It is D260's family: two module lists for one package, disagreeing.

Nothing here is eager. G17 asserts a bare `import omniweave_core` loads none of the nine lazy
subpackages, and this one is on the per-turn path of every hook.
"""
