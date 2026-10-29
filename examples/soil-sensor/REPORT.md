# Soil Sensor

A battery-powered stake that measures soil moisture and temperature in a garden bed and reports over Wi-Fi a few times an hour.

**Current stage:** Power budget  
**Build quantity:** 200  
**Parts cost:** $10.20/unit (target $18.00)

## Gates

| Stage | Gate | Errors | Warnings |
|---|---|---|---|
| Requirements | pass | 0 | 0 |
| Architecture and interfaces | pass | 0 | 0 |
| Power budget | BLOCKED | 1 | 0 |
| Parts and BOM | pass | 0 | 1 |
| Boards | BLOCKED | 1 | 0 |
| Enclosure and mechanics | BLOCKED | 1 | 0 |
| Firmware | BLOCKED | 1 | 0 |
| Certification | BLOCKED | 6 | 0 |
| Manufacturing and supply | BLOCKED | 2 | 1 |

## Architecture

```mermaid
flowchart LR
  n_batt[/"batt<br/><small>battery</small>"/]
  n_mcu["mcu<br/><small>compute</small>"]
  n_moisture["moisture<br/><small>sensor</small>"]
  n_temp["temp<br/><small>sensor</small>"]
  n_charger["charger<br/><small>power</small>"]
  n_regulator["regulator<br/><small>power</small>"]
  n_usb["usb<br/><small>electronics</small>"]
  n_housing["housing<br/><small>mechanical</small>"]
  n_mcu -- i2c --- n_temp
  n_mcu -- analog --- n_moisture
  n_usb -- power --- n_charger
  n_charger -- power --- n_regulator
  n_regulator -- power --- n_mcu
  n_batt -. "3.3 V" .-> n_3v3(("3v3"))
  n_3v3 -.-> n_mcu
  n_3v3 -.-> n_moisture
  n_3v3 -.-> n_temp
  n_batt -.-> n_usb
```

## Power

| Rail | Volts | Peak mA | Avg mA | Limit mA | Fed from |
|---|---|---|---|---|---|
| 3v3 | 3.3 | 353.5 | 0.375 | 800 | batt |

Source **batt** (battery): peak 358 mA, average 0.383 mA, about 105 days

## Bill of materials (priced at 200 units)

| Part | MPN | Category | Qty | Unit $ | Line $ | Suppliers | Lifecycle | Lead wks |
|---|---|---|---|---|---|---|---|---|
| wifi-module | EXAMPLE-WIFI-MODULE | module | 1 | 2.600 | 2.60 | distributor-a, distributor-b | active | 3 |
| moisture-afe | EXAMPLE-OPAMP | ic | 1 | 0.350 | 0.35 | distributor-a, distributor-b | active | 2 |
| temp-sensor | EXAMPLE-TEMP-I2C | sensor | 1 | 0.800 | 0.80 | distributor-a, distributor-b | active | 4 |
| charger-ic | EXAMPLE-CHARGER | ic | 1 | 0.600 | 0.60 | distributor-a, distributor-b | active | 2 |
| buck-boost | EXAMPLE-BUCKBOOST | ic | 1 | 1.400 | 1.40 | distributor-a | active | 6 |
| usb-c-receptacle | EXAMPLE-USBC-16P | connector | 1 | 0.250 | 0.25 | distributor-a, distributor-b | active | 2 |
| cell | EXAMPLE-LIION-1200 | battery | 1 | 2.900 | 2.90 | cell-vendor-a, cell-vendor-b | active | 5 |
| passives | EXAMPLE-PASSIVE-KIT | passive | 1 | 0.400 | 0.40 | distributor-a | active | 1 |
| pcb | EXAMPLE-PCB-2L | pcb | 1 | 0.900 | 0.90 | fab-a, fab-b | active | 1 |
| **Total** | | | | | **10.20** | | | |

## Certification checklist

_Starting checklist, not legal advice. Confirm with an accredited test lab._

| Item | Why | Plan |
|---|---|---|
| FCC Part 15 Subpart B | any digital electronics sold in the US (unintentional emissions) | pre-scan first prototype, then accredited lab |
| FCC modular grant reuse | pre-certified radio module: follow its integration rules and label 'Contains FCC ID' | follow module integration guide, label with module FCC ID |
| CE marking + Declaration of Conformity | any electrical product sold in the EU | compile technical file after RED testing |
| RoHS (EU) | restricted substances in electrical products | **none yet** |
| WEEE (EU) | take-back registration for electrical products | **none yet** |
| Radio equipment rules (EU, RED/RER) | radio product; covers EMC, safety and spectrum | **none yet** |
| Battery regulation (EU) | product contains a battery | **none yet** |
| UN 38.3 | shipping lithium cells or packs | **none yet** |
| IEC 62133-2 | lithium cell/pack safety, usually supplied by the cell vendor | **none yet** |

## Findings

### Power budget
- **info**: battery 'batt': average 0.383 mA, about 105 days
- **error**: battery life about 105 days, requirement is 180 days

### Parts and BOM
- **warn**: part 'buck-boost': single source (distributor-a)
- **info**: parts cost $10.20/unit at 200 units (target $18.00)

### Boards
- **error**: board 'main': source hardware/main not found

### Enclosure and mechanics
- **error**: mechanical 'housing': source mechanical/housing.py not found

### Firmware
- **error**: firmware 'fw': path firmware not found

### Certification
- **error**: no plan for RoHS (EU) (restricted substances in electrical products)
- **error**: no plan for WEEE (EU) (take-back registration for electrical products)
- **error**: no plan for Radio equipment rules (EU, RED/RER) (radio product; covers EMC, safety and spectrum)
- **error**: no plan for Battery regulation (EU) (product contains a battery)
- **error**: no plan for UN 38.3 (shipping lithium cells or packs)
- **error**: no plan for IEC 62133-2 (lithium cell/pack safety, usually supplied by the cell vendor)
- **info**: this list is a starting checklist, not legal advice; confirm with an accredited test lab

### Manufacturing and supply
- **error**: manufacturing.assembly missing: who builds the units (in-house, PCBA house, contract manufacturer)?
- **error**: manufacturing.pcb_fab missing: which board house
- **info**: longest part lead time: 6 weeks
- **warn**: manufacturing.test_plan missing: how is each unit tested before it ships?
