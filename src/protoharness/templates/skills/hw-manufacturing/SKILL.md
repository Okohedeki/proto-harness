---
name: hw-manufacturing
description: Plan board fab, assembly, supply, lead times and per-unit testing for the first real build, and draft quote requests. Use for the manufacturing stage.
---

# Manufacturing stage

- Choose `pcb_fab` and `assembly` for the build quantity. Get at least two quotes for anything
  custom (boards, assembly, enclosure). Draft quote requests in `docs/rfq/` with the BOM CSV, fab
  outputs, STEP files and quantity. The user sends them.
- Check lead times against `schedule_weeks` and order long-lead parts first.
- Write `test_plan`: what every unit is tested for (power-on current, factory test firmware, radio
  check, visual inspection) and who does it.
- The checker flags process and quantity mismatches. Act on them or record why not in `decisions`.

Gate: `ph check --stage manufacturing`. After that, `ph report` is the build package overview.
