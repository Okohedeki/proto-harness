# proto-harness

One place for a whole hardware device. You describe the device in a single `device.yaml`:
requirements, subsystems, interfaces, power, parts, boards, enclosure, firmware, certification
and manufacturing. Every stage has a gate made of deterministic checks, so an AI assistant (or a
person) can propose designs quickly and the harness decides whether they hold up.

```
spec -> architecture -> power -> parts -> electronics -> mechanical -> firmware -> compliance -> manufacturing
```

It works for any device: a sensor, a robot joint, a wearable, a desk gadget, a purely mechanical
product. Stages that don't apply pass with a note.

## Why

Getting hardware made has become fast and cheap. Knowing whether a design will work, fit, last
on its battery, cost what you need, and be legal to sell is still slow and scattered across
datasheets, spreadsheets, CAD files and lab emails. proto-harness keeps all of it in one file and
checks it every time anything changes.

The rule of the harness: **models propose, tools decide.** An AI writes the circuit, the case and
the firmware as code; the gates (power math, fit checks, BOM rules, KiCad ERC/DRC, firmware
builds, certification rules) decide whether a stage is done. A qualified engineer reviews only what
the tools cannot judge, which each stage writes to `docs/review.md`.

## What the gates check

| Stage | Checks |
|---|---|
| spec | summary, functions, build quantity, unit cost target, markets, environment, size limit |
| architecture | blocks and interfaces exist, unconnected blocks, logic-level mismatches without a level shifter |
| power | every powered block has a load, rail peak vs regulator limit (80% warning), LDO dropout at end of battery discharge, source current limits, switching-regulator input current, battery life vs requirement |
| parts | every block has a real part, MPN present, price at build quantity (price breaks), lifecycle (EOL/NRND), supplier count, BOM cost vs target |
| electronics | board size and layers, source exists, **KiCad ERC and DRC** through `kicad-cli` when installed |
| mechanical | process and material set, CAD source exists, boards and parts fit inside with clearance (any rotation), outside size within limit, packing density |
| firmware | target block exists, project exists, **PlatformIO build** when installed |
| compliance | certification checklist derived from markets, radios, pre-certified modules, lithium cells, mains power, lasers; each item needs a plan |
| manufacturing | board fab and assembly chosen, lead times vs schedule, process vs quantity (printing at volume, molding at low volume), per-unit test plan |

Errors block a gate; warnings don't. The certification list is a starting checklist, not legal
advice.

## Install

Needs Python 3.10+ on Windows, macOS or Linux.

```bash
pip install git+https://github.com/Okohedeki/proto-harness
```

Or from a clone:

```bash
pip install -e ".[dev]"
```

The external checkers are optional. Missing tools leave their checks marked as not run, they don't
fail. `ph doctor` shows what is installed and how to get the rest:

| Tool | Used for | Windows | macOS | Linux |
|---|---|---|---|---|
| KiCad 8+ (`kicad-cli`) | ERC, DRC, fab outputs | installer from kicad.org | installer or `brew install --cask kicad` | distro package or Flatpak |
| atopile / SKiDL | circuits as code | `pip install atopile` or `pip install skidl` | same | same |
| KiBot | Gerbers, BOM, pick-and-place | `pip install kibot` | same | same |
| PlatformIO | firmware builds | `pip install platformio` | same | same |
| CadQuery / build123d | enclosures as code | `pip install cadquery` or `pip install build123d` | same | same |
| OpenSCAD | enclosures as code | installer | `brew install --cask openscad` | `apt install openscad` |
| ngspice | analog simulation | installer from ngspice.sourceforge.io | `brew install ngspice` | `apt install ngspice` |
| Freerouting | autorouting | release jar (Java 21+) | same | same |

## Use

```bash
ph init my-device --name "My Device"   # device.yaml, CLAUDE.md, stage skills, folders
cd my-device
ph status                              # which gates pass, what blocks the current stage
ph check --stage power                 # run one gate
ph check                               # run every gate
ph report                              # REPORT.md: the whole device on one page
ph bom -o bom.csv                      # BOM priced at the build quantity
ph doctor                              # installed checkers
```

`ph check` and `ph status` exit non-zero when a gate is blocked, so they work in CI and git hooks.

### With an AI assistant

`ph init` puts a `CLAUDE.md` and one skill per stage in `.claude/skills/`. Open the folder in
Claude Code and run `/hw`. It reads `ph status`, loads the skill for the current stage, does the
work, and loops on `ph check` until the gate passes. The skills are plain Markdown, so other
assistants can follow them too.

The skills ask you only for decisions that are yours (what it must do, budget, quantity, markets,
looks, trade-offs) and research the rest. They never invent part numbers or prices.

## Project layout

```
my-device/
  device.yaml        single source of truth
  REPORT.md          generated overview: gates, block diagram, power, BOM, certification
  hardware/          circuit as code and KiCad output
  mechanical/        enclosure as code, STEP/STL exports
  firmware/          firmware project
  docs/review.md     what a human engineer must check
  docs/rfq/          quote requests for fabs and manufacturers
```

## Examples

Placeholder part numbers and prices; both are partway through, to show how gates block.

- [`examples/soil-sensor`](examples/soil-sensor): battery Wi-Fi sensor. The power gate catches a
  battery life shortfall.
- [`examples/pan-tilt-mount`](examples/pan-tilt-mount): motorized, mostly mechanical. The architecture gate catches
  a 3.3 V / 5 V logic mismatch and the parts gate catches an unchosen motor.

```bash
ph status examples/soil-sensor
ph report examples/pan-tilt-mount
```

## Roadmap

- Live part lookups (stock, price, lifecycle) from distributor APIs
- atopile/SKiDL build step and Freerouting run inside the electronics gate
- KiBot fab package generation and per-fab rule profiles
- Enclosure generator from board outline and connector positions
- ngspice checks for regulators and analog front ends
- RFQ package generator for board houses and contract manufacturers
- Thermal and drop/IP checks in the mechanical gate

## License

MIT
