---
name: hw-electronics
description: Write the circuit as code (atopile or SKiDL), build it to KiCad, lay out and route the board, and pass ERC and DRC. Use for the electronics stage.
---

# Electronics stage

- Write the circuit as code in `hardware/` with atopile (`.ato`) or SKiDL (Python). Start from each
  part's datasheet reference circuit and application notes.
- Build it to a KiCad project, then run `ph check --stage electronics`; it runs KiCad ERC and DRC
  through `kicad-cli`.
- Layout: place connectors and mounting holes first (the enclosure fixes them), then power parts,
  then the rest. Autoroute with Freerouting, then fix by hand.
- Generate fab outputs with KiBot (Gerbers, drill, BOM, pick-and-place) into `hardware/fab/`.
- Put everything the tools cannot judge in `docs/review.md` for a human engineer: antenna
  keep-outs, high-current traces, thermal relief, ESD on external connectors, mains spacing.

Gate: `ph check --stage electronics` (ERC and DRC must be clean).
