"""The conformance-template driver and its fixtures: `parse.text.plain`.

W3.6's deliverable (16-roadmap.md:486), G16's subject (11-repo-layout.md:1133-1136), and the
kit's own first conformance subject -- a green suite over no subject proves nothing.

`driver.py` is the code, `driver.toml` is the card and `fixtures/` holds the inputs. Nothing here
imports `omniweave_core`: the whole point of the template is that a driver's omniweave surface is
`omniweave_ports` and nothing else (04-driver-system.md section 1.6, G4).
"""
