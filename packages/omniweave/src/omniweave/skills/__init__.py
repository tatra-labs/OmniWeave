"""Skills: the bundles `ow install --skills` and `ow skills install` put into an agent host.

10:1150-1162 lays out the tree and 10 section 5.5 the lockfile and the digest. This package holds
the digest, `hash.py`'s `sha256-bundle-1`, because the install receipt's `dir` row (10:1726) and
`ow skills verify` (10:1368) must compute the same one. The router body, the tier rule and the
`ow skills` verbs are W7.6's (16:720).
"""

from __future__ import annotations

from omniweave.skills.hash import ALGO, Walked, bundle_sha256, first_difference, walk

__all__ = ["ALGO", "Walked", "bundle_sha256", "first_difference", "walk"]
