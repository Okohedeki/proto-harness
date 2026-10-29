---
name: hw-mechanical
description: Design the enclosure and mechanical parts as code (CadQuery, build123d or OpenSCAD) and prove that boards, battery and parts fit. Use for the mechanical stage.
---

# Mechanical stage

- Write the enclosure as code in `mechanical/`. Take dimensions from the board outline, battery
  and connector positions in device.yaml, not from guesses.
- Match `process` and `material` to the build quantity: printing for tens, urethane casting or CNC
  for hundreds, injection molding for thousands.
- Fill `inner_mm`, `wall_mm`, `holds` and `clearance_mm`. The checker tests fit and the size limit.
- Export STEP and STL next to the source. Design for the process: draft and even walls for molding,
  no unsupported overhangs for printing.
- Note connector cutouts, buttons, light pipes, venting and sealing in `docs/review.md`.

Gate: `ph check --stage mechanical`.
