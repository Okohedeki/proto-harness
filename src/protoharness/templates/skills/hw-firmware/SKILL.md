---
name: hw-firmware
description: Create and build the firmware project with pin maps taken from the circuit, sleep modes that match the power budget, and a factory test mode. Use for the firmware stage.
---

# Firmware stage

- Create a PlatformIO project in `firmware/` (or another framework, named in `framework`).
- Generate the pin map from the circuit source; never retype it.
- Implement the duty cycle the power budget assumes. Measure it on hardware later and update
  `power.loads` with the real numbers.
- Include a factory test mode that exercises every peripheral; manufacturing depends on it.
- Keep secrets out of the repository; provision them per unit at the factory.

Gate: `ph check --stage firmware` (builds with PlatformIO when it is installed).
