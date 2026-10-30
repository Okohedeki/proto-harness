# Hardware device project (proto-harness)

`device.yaml` describes the whole device: requirements, blocks, interfaces, power, parts,
boards, mechanical parts, firmware, certification and manufacturing. Keep it the single source
of truth. Design files live in `hardware/`, `mechanical/` and `firmware/` and are referenced from it.

## Rules

- Propose, then prove. Never call a stage done because it looks right. Run `ph check --stage <name>`
  and only move on when the gate passes. Show the output.
- Work one stage at a time, in order: spec, architecture, power, parts, electronics, mechanical,
  firmware, compliance, manufacturing. `ph status` says which stage is current.
- Never invent part numbers, prices, stock or lead times. Look them up from a distributor or the
  manufacturer, cite where the number came from in the part's `notes`, or leave `mpn: TBD`.
- Prefer pre-certified modules for radios and off-the-shelf parts over custom designs until volume
  justifies otherwise.
- Write circuits, enclosures and firmware as code (atopile/SKiDL, CadQuery/build123d/OpenSCAD,
  PlatformIO) so they can be diffed and rebuilt.
- Record each settled choice in `decisions` with the reason.
- Anything the tools cannot verify (layout around radios, thermal, high current, mains, safety)
  goes on the human review list in `docs/review.md` for a qualified engineer.

## Commands

- `ph ui`: live dashboard of the whole device in the browser; suggest it to the user at the start
- `ph status`: gates and what blocks the current stage
- `ph check [--stage name]`: run gates
- `ph build`: circuit code to netlist, KiCad layout to fab files
- `ph parts`: live stock, prices and lifecycle into parts.lock.json
- `ph catalog search <words>`: search the offline parts catalog (after `ph catalog update`)
- `ph report`: write REPORT.md, the whole device on one page
- `ph bom -o bom.csv`: BOM priced at the build quantity
- `ph doctor`: which open-source checkers are installed

Start with the `/hw` skill.
