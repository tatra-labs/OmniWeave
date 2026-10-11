"""owflow/1 to WordprocessingML: one module a construct family, one function a `maps_to` symbol.

09 section 5.2's reference shape for `lower/`. A module's public functions are exactly the symbols
`constructs.toml`'s `maps_to` column names in it, which `test_docx_lower.py` holds both ways
(OUT1). The walk (`_emit`) and the package (`_pack`) are private, so they name no construct.
"""
