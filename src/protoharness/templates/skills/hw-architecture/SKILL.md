---
name: hw-architecture
description: Break a device into blocks (compute, sensing, actuation, power, radio, enclosure) and the interfaces between them. Use for the architecture stage.
---

# Architecture stage

- One block per subsystem a person could swap independently. Give each a `kind` and `io_v`.
- Add an interface for every connection with its `kind` (i2c, spi, uart, usb, can, gpio, pwm,
  analog, mechanical). Mixed logic levels need a level shifter and `level_shift: true`.
- Choose the least custom path: modules and dev boards first, custom designs only where they pay.
- Compare two or three architectures for anything non-obvious and record the choice in `decisions`.
- Check the pin and bus budget: an MCU with too few UARTs or ADC channels is an architecture bug.

Gate: `ph check --stage architecture`. `ph report` draws the block diagram.
