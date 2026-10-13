"""`compile.pptx.native`'s lowering: owsvg/1 to DrawingML, a family module a `maps_to` prefix.

09-generation.md section 12.1: "`lower/drawingml/` per DrawingML family ... `pack.py` builds the
part graph and calls `write_opc()`". Each module here is one family a `maps_to` names
(`lower.shapes:rect`), and `_pack.build()` is the compile. D795 lands the slide, groups, preset
shapes, solid paint, lines and transforms, D796 freeforms (paths, polygons and polylines), and
D797 text, D798 gradients and patterns, D799 shadows, glows and line ends, and D800 pictures
and clips. `<use>`, links and citations are later cells, and until each lands preflight check 1
refuses a unit that uses it.
"""
