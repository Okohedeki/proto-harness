---
name: hw-power
description: Build the power tree (sources, rails, regulators, loads) and prove peak current, dropout and battery life. Use for the power stage.
---

# Power stage

- List every source: battery (chemistry, nominal `voltage_v`, `min_voltage_v`, `capacity_mah`),
  USB, DC or mains, with `max_current_ma` where the source has a limit.
- One rail per regulated voltage, with `regulator` type, `max_current_ma`, `efficiency` and
  `quiescent_ma` taken from the regulator datasheet, not guessed.
- One load per powered block: `active_ma`, `sleep_ma`, `duty` (fraction of time active) and
  `peak_ma` (radio bursts, motor stall, inrush). Cite datasheet values in the part `notes`.
- The checker computes rail peaks, LDO dropout at end of discharge, source limits and battery life.
  If battery life misses the requirement, the usual fixes are duty cycle, sleep current or a bigger
  cell. Put the trade-off to the user.

Gate: `ph check --stage power`.
