"""16:633's `--hypothesis-profile=ci  # derandomize=True @ 200`, registered by `packages/conftest`.

D707: Hypothesis ships a `ci` profile of its own at 100 examples, so the flag ran without the 200
the plan glosses it with. The profile is re-registered on top of the shipped one.
"""

from __future__ import annotations

from hypothesis import settings


def test_the_ci_profile_is_derandomized_at_200_examples() -> None:
    ci = settings.get_profile("ci")
    assert (ci.derandomize, ci.max_examples) == (True, 200)
    assert (ci.deadline, ci.database) == (None, None), "the shipped profile's other settings kept"
