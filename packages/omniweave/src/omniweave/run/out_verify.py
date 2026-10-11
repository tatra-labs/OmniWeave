"""`verify_artifact()` -- round-trip law R1 over a sealed artefact, and R7 over its rows. **D774.**

09-generation.md section 11.1: *"R1 RETAINED-IL IDENTITY: for every artefact `A` omniweave built
with retained bundle `I`: `compile(I) =_det A`"*, tested by `ow out verify`, and *"R7 TOTAL
CLASSIFICATION: every output unit lands in exactly one `UnitOutcome` and the sum equals
`unit_count`"*. 02-architecture.md section 4.2 row 6 gives verify *"the artefact plus its retained
bundle"* and the comparison *"at the declared `ArtefactDeterminism` classes"*.

## Rulings

1. **R1 recompiles the retained IL, never the JobDir's.** The bundle is fetched out of CAS by the
   sealed row's `il_store_ref` into a scratch JobDir (`out.retain.fetch`, which verifies every
   byte), so an IL edited since the seal cannot pass for the one the gate saw. The scratch is
   removed on every exit path.
2. **The rest of the compile's inputs come from the JobDir, held to the row's purity digests.**
   The retained bundle is the IL alone. The Brief and the clock every OPC timestamp is written
   as live in `job.json`, and the frozen assets in `assets/index.json`. A Brief whose digest is
   not the row's `brief_digest`, or a ledger whose digest is not its `ledger_digest`, is
   `OW_TARGET_VERIFY_INPUTS` (`OW-T-527`), because a recompile over other inputs proves nothing
   about this artefact. So is an installed card or table whose digest is not the row's: R1
   holds one compiler to its own output.
3. **The Plan is the sealed one.** Its generation, delivery and gate are the row's, its digests
   are the row's, and its units take each unit's `nsig` and `manual_reason` from the fetched
   bundle, as `compile_artifact()` takes them (D756).
4. **`=_det` is checked class by class, at the classes the row declares.** `byte` is the sha256
   of the recompiled bytes against the row's `sha256`. `part` is the receipt's `part_digest`
   against the row's. `frame` and `render` need a rendering toolchain no target here has, so
   they are reported `unchecked`, which is not a pass.
5. **R7 is read off the sealed rows**: one `artifact_unit` row per unit of the Plan, in roster
   order. The seal already refuses a row without an outcome, so R7 restates what the store
   holds, against the roster the Brief commissioned.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

from omniweave_core.errors import TargetError
from omniweave_core.out.job import ILBundle, Job
from omniweave_core.out.ledger import ASSET_INDEX, FrozenLedger
from omniweave_core.out.retain import fetch

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from omniweave_core.blobs import BlobStore
    from omniweave_core.out.carrier import CarrierDoc
    from omniweave_core.out.constructs import ConstructTable
    from omniweave_core.store.artifact import ArtifactRow, UnitRow

    from omniweave.run.out_compile import Lowering

__all__ = ["CHECKED_CLASSES", "Held", "Verified", "verify_artifact"]

CHECKED_CLASSES: Final = frozenset({"byte", "part"})
"""Ruling 4: the determinism classes a recompile can compare without a rendering toolchain."""

Held = Literal["held", "differs", "unchecked"]


@dataclass(frozen=True, slots=True)
class Verified:
    """R1 per declared class, and R7's two counts."""

    row: ArtifactRow
    classes: Mapping[str, Held]
    units_sealed: int
    unit_count: int

    @property
    def r1(self) -> bool:
        """Every declared class that can be checked held, and at least one could be."""
        checked = [held for held in self.classes.values() if held != "unchecked"]
        return bool(checked) and all(held == "held" for held in checked)

    @property
    def r7(self) -> bool:
        return self.units_sealed == self.unit_count

    @property
    def passed(self) -> bool:
        return self.r1 and self.r7


def verify_artifact(
    job_dir: Path,
    *,
    row: ArtifactRow,
    units: tuple[UnitRow, ...],
    card_sha256: str,
    constructs: ConstructTable,
    carrier: Callable[[str, str], CarrierDoc],
    blobs: BlobStore,
    lowering: Lowering,
    scratch: Path,
) -> Verified:
    """Rulings 1-5: the sealed artefact recompiled from its retained IL, and compared."""
    job = Job.load(job_dir)
    _held_to(row, job, card_sha256, constructs)
    if scratch.exists():
        shutil.rmtree(scratch)
    try:
        fetch(row.il_store_ref, blobs, scratch / "il")
        index = job_dir / ASSET_INDEX
        if index.exists():
            (scratch / ASSET_INDEX).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(index, scratch / ASSET_INDEX)
        ledger = FrozenLedger.of(scratch, blobs)
        if ledger.digest() != row.ledger_digest:
            raise _inputs(
                f"the JobDir's ledger digests to {ledger.digest()}, and {row.slug}@"
                f"{row.artifact_gen} was sealed over {row.ledger_digest}"
            )
        bundle = ILBundle.load(scratch / "il", carrier=carrier, constructs=constructs)
        plan = replace(
            job.plan,
            artifact_gen=row.artifact_gen,
            delivery=row.delivery,  # type: ignore[arg-type]
            gate_status=row.gate_status,
            il_digest=row.il_digest,
            constructs_digest=row.constructs_digest,
            ledger_digest=row.ledger_digest,
            units=tuple(
                replace(mine, nsig=theirs.nsig, manual_reason=theirs.manual_reason)
                for mine, theirs in zip(job.plan.units, bundle.units, strict=True)
            ),
        )
        replace(job, plan=plan).write(scratch)
        done = lowering(scratch, plan, bundle, ledger)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    sha = hashlib.sha256(done.body).hexdigest()
    compared = {
        "byte": sha == row.sha256.removeprefix("sha256:"),
        "part": done.receipt.part_digest == row.part_digest.removeprefix("sha256:"),
    }
    classes: dict[str, Held] = {
        name: ("held" if compared[name] else "differs") if name in compared else "unchecked"
        for name in row.determinism
    }
    return Verified(row, classes, len(units), plan.unit_count)


def _held_to(row: ArtifactRow, job: Job, card_sha256: str, constructs: ConstructTable) -> None:
    """Ruling 2: the Brief, the card and the table are the ones the row was sealed over."""
    named = f"{row.slug}@{row.artifact_gen}"
    if (job.plan.slug, job.plan.target) != (row.slug, row.target):
        raise _inputs(
            f"the JobDir compiles {job.plan.target} {job.plan.slug}, and {named} is {row.target}"
        )
    if job.plan.brief_digest != row.brief_digest:
        raise _inputs(
            f"the JobDir's Brief digests to {job.plan.brief_digest}, and {named} was sealed "
            f"over {row.brief_digest}"
        )
    if card_sha256 != row.card_sha256:
        raise _inputs(
            f"the installed card is {card_sha256}, and {named} was compiled by {row.card_sha256}"
        )
    if constructs.digest() != row.constructs_digest:
        raise _inputs(
            f"the installed construct table digests to {constructs.digest()}, and {named} was "
            f"compiled against {row.constructs_digest}"
        )


def _inputs(detail: str) -> TargetError:
    return TargetError(
        f"R1 recompiles over the inputs the artefact was sealed over, and {detail}",
        symbol="OW_TARGET_VERIFY_INPUTS",
        fix="ow explain OW-T-527",
    )
