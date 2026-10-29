---
name: hw-parts
description: Pick real, in-stock parts for every block with manufacturer part numbers, price breaks, suppliers, lifecycle and lead time. Use for the parts and BOM stage.
---

# Parts stage

- Every block gets a `part`. Every part gets an `mpn`, `unit_cost_usd` (price breaks as a map),
  `suppliers`, `lifecycle`, `lead_time_weeks`, and `dims_mm` when it matters for fit.
- Look up live data from distributors or the manufacturer. Never invent numbers. Put the source
  and lookup date in the part's `notes`.
- Prefer parts with two or more suppliers, an active lifecycle and healthy stock.
- If the board house offers assembly, prefer parts it stocks to avoid sourcing fees.
- Pre-certified radio modules: set `certified: true` and list `features` such as `radio-wifi`.
- If the BOM breaks the cost target, revisit the architecture before squeezing passives.

Gate: `ph check --stage parts`. `ph bom -o bom.csv` exports the BOM.
