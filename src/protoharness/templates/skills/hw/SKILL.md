---
name: hw
description: Drive a hardware device from idea to manufacturable design, one gated stage at a time. Use when starting a device, asking "what's next", or resuming work on device.yaml.
---

# Hardware harness orchestrator

1. Run `ph status`. If there is no `device.yaml`, run `ph init` first.
2. The first BLOCKED stage is the current stage. Load its skill:
   `hw-spec`, `hw-architecture`, `hw-power`, `hw-parts`, `hw-electronics`, `hw-mechanical`,
   `hw-firmware`, `hw-compliance`, `hw-manufacturing`.
3. Do that stage's work, editing `device.yaml` and the design files it points to.
4. Run `ph check --stage <stage>` and show the result. Repeat until the gate passes.
5. Run `ph report` so REPORT.md stays current, then go back to step 1.

Ask the user only for things that are theirs to decide: what the device must do, budget,
quantity, markets, appearance, and trade-offs between cost, size and battery life. Research
everything else yourself.

Going back is normal. A part change can break power, fit or cost; re-run `ph check` on all stages
after any change and fix the earliest broken gate first.
