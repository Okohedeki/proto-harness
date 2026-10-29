---
name: hw-parts
description: Pick real, in-stock parts for every block with manufacturer part numbers, price breaks, suppliers, lifecycle and lead time. Use for the parts and BOM stage.
---

# Parts stage

- Every block gets a `part`. Every part gets an `mpn`, `unit_cost_usd` (price breaks as a map),
  `suppliers`, `lifecycle`, `lead_time_weeks`, and `dims_mm` when it matters for fit.
- After choosing MPNs, run `ph parts`. It writes live stock, price breaks and lifecycle to
  `parts.lock.json`, and the gate prices the BOM from it. Add `lcsc:` codes for exact LCSC lookups;
  DigiKey and Mouser need the user's API keys in environment variables (never ask for them in chat
  or write them to files). Never invent numbers; typed `unit_cost_usd` is only for parts no source
  carries, marked `no_lookup: true`, with the quote source in `notes`.
- Re-run `ph parts` before ordering and whenever the gate says data is stale.
- Prefer parts with two or more suppliers, an active lifecycle and healthy stock.
- If the board house offers assembly, prefer parts it stocks to avoid sourcing fees.
- Pre-certified radio modules: set `certified: true` and list `features` such as `radio-wifi`.
- If the BOM breaks the cost target, revisit the architecture before squeezing passives.

Gate: `ph check --stage parts`. `ph bom -o bom.csv` exports the BOM.
