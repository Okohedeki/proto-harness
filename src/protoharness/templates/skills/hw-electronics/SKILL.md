---
name: hw-electronics
description: Write the circuit as code (atopile or SKiDL), build it to KiCad, lay out and route the board, and pass ERC and DRC. Use for the electronics stage.
---

# Electronics stage

- Write the circuit as code in `hardware/` with atopile (`.ato`) or SKiDL (Python). Start from each
  part's datasheet reference circuit and application notes.
- Set the board's `source` to the circuit file and run `ph build`, then `ph check --stage electronics`.
  The gate reads the netlist (footprints, dangling nets, rails, ground, decoupling, I2C pull-ups,
  parts matching device.yaml) and runs KiCad ERC/DRC when `kicad-cli` is installed.
- Put the manufacturer part number in an `MPN` field on every chip and connector so the board and
  device.yaml stay in agreement.
- Layout: place connectors and mounting holes first (the enclosure fixes them), then power parts,
  then the rest. Autoroute with Freerouting, then fix by hand.
- `ph build` exports Gerbers, drill and pick-and-place to `hardware/fab/<board>/` once a
  `.kicad_pcb` exists (KiBot instead, when a `*.kibot.yaml` config is present).
- Put everything the tools cannot judge in `docs/review.md` for a human engineer: antenna
  keep-outs, high-current traces, thermal relief, ESD on external connectors, mains spacing.

Gate: `ph check --stage electronics` (ERC and DRC must be clean).
