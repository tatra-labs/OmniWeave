"""The seven free derive/1 passes: derive.segment.spine, derive.anchor.{native,defterm},
derive.xref.{native,pattern}, derive.entity.{table,gazetteer}. A pass emits
owgraph-items/1; GraphSink is host-side and no pass writes an L3 row.

Specified in 02-architecture.md section 2 row 44 and 06-structure-extraction.md.
"""
