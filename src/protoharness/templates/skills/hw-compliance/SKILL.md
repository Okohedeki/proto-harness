---
name: hw-compliance
description: Turn the derived certification checklist into a plan per item (test lab, pre-scan, module grants, battery documents, labeling). Use for the compliance stage.
---

# Compliance stage

- Run `ph report` and read the certification checklist. It is derived from markets, radios,
  batteries and mains power. It is a starting point, not legal advice.
- For each item, write a plan in `compliance.plans`, keyed by the item's exact name: test lab,
  pre-scan date, module grant reuse, cell vendor documents, labels and manuals.
- Ask the user about product categories the rules cannot detect (medical, toys, automotive, food
  contact, skin contact) and add those items.
- Pre-scan EMC on the first prototype; fixing emissions after tooling is expensive.

Gate: `ph check --stage compliance`.
