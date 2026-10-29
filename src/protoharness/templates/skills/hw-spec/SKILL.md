---
name: hw-spec
description: Turn a hardware idea into concrete requirements in device.yaml (functions, quantity, cost target, markets, environment, size, battery life, schedule). Use for the spec stage.
---

# Spec stage

Interview the user briefly, then fill `summary` and `requirements`.

- Ask at most five questions at once, and offer sensible defaults they can accept.
- Functions are testable sentences: "logs temperature every 10 minutes for 6 months on one charge".
- Quantity means the first real build, not the dream volume. It sets prices and processes.
- Target unit cost means the cost of one built unit. Parts usually get about half of it.
- Markets drive certification, so settle them now.
- Record open questions as `decisions` entries that start with "open:".

Gate: `ph check --stage spec`.
