"""Soil sensor main board as code (SKiDL). `ph build` runs this and writes main.net.

Illustrative only: the connections follow each chip's typical application circuit, but pin
numbers are sequential placeholders, not datasheet pin numbers, and footprints prefixed with
"soil:" are placeholders. Swap in real KiCad symbols and footprints (or check every pin against
the datasheet) before laying out or ordering boards.
"""

from skidl import KICAD8, SKIDL, Net, Part, Pin, generate_netlist

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"


def chip(ref, name, pins, footprint, mpn=None):
    """A part defined in code: no KiCad library needed."""
    template = Part(tool=SKIDL, name=name, ref_prefix=ref, footprint=footprint, dest="TEMPLATE",
                    pins=[Pin(num=str(i + 1), name=p, func=Pin.types.PASSIVE) for i, p in enumerate(pins)])
    part = template()
    if mpn:
        part.fields["MPN"] = mpn
    return part


_two = {}


def passive(ref, value, footprint):
    key = (ref, footprint)
    if key not in _two:
        _two[key] = Part(tool=SKIDL, name=ref, ref_prefix=ref, footprint=footprint, dest="TEMPLATE",
                         pins=[Pin(num="1", func=Pin.types.PASSIVE), Pin(num="2", func=Pin.types.PASSIVE)])
    return _two[key](value=value)


def between(a, b, part):
    a += part[1]
    b += part[2]
    return part


gnd, vbus, vbat, v3 = Net("GND"), Net("VBUS"), Net("VBAT"), Net("+3V3")
sda, scl, moist, vsense = Net("I2C_SDA"), Net("I2C_SCL"), Net("MOIST_ADC"), Net("VBAT_SENSE")

# USB-C power input: 5.1k pull-downs on CC ask the host for 5 V.
usb = chip("J", "USB_C", ["VBUS", "GND", "CC1", "CC2"], "soil:USB_C_16P", mpn="TYPE-C-31-M-12")
vbus += usb["VBUS"]
gnd += usb["GND"]
for pin in ("CC1", "CC2"):
    cc = Net(pin)
    cc += usb[pin]
    between(cc, gnd, passive("R", "5k1", R0402))

# Li-ion charger. PROG resistor sets the charge current.
chg = chip("U", "TP4056", ["VCC", "GND", "PROG", "BAT", "CE", "TEMP"], "soil:ESOP-8", mpn="TP4056")
vbus += chg["VCC"], chg["CE"]
gnd += chg["GND"], chg["TEMP"]
vbat += chg["BAT"]
prog = Net("CHG_PROG")
prog += chg["PROG"]
between(prog, gnd, passive("R", "2k", R0402))
between(vbus, gnd, passive("C", "10u", C0805))
between(vbat, gnd, passive("C", "10u", C0805))

# Battery connector (cell is off-board).
batt = chip("J", "BATT", ["+", "-"], "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal")
vbat += batt["+"]
gnd += batt["-"]

# Buck-boost to 3.3 V so the rail holds up until the cell is empty.
bb = chip("U", "TPS63020", ["VIN", "VINA", "EN", "PS", "L1", "L2", "VOUT", "FB", "GND", "PGND"],
          "soil:VSON-14", mpn="TPS63020DSJR")
vbat += bb["VIN"], bb["VINA"], bb["EN"], bb["PS"]
gnd += bb["GND"], bb["PGND"]
v3 += bb["VOUT"]
sw1, sw2, fb = Net("BB_L1"), Net("BB_L2"), Net("BB_FB")
sw1 += bb["L1"]
sw2 += bb["L2"]
fb += bb["FB"]
between(sw1, sw2, passive("L", "1u5", "Inductor_SMD:L_1210_3225Metric"))
between(v3, fb, passive("R", "1M", R0402))
between(fb, gnd, passive("R", "180k", R0402))
between(vbat, gnd, passive("C", "10u", C0805))
between(v3, gnd, passive("C", "22u", C0805))

# Wi-Fi/BLE module.
mcu = chip("U", "ESP32-C3-MINI-1", ["3V3", "GND", "EN", "IO3", "IO4", "IO6", "IO7"],
           "soil:ESP32-C3-MINI-1", mpn="ESP32-C3-MINI-1-N4")
v3 += mcu["3V3"]
gnd += mcu["GND"]
en = Net("MCU_EN")
en += mcu["EN"]
between(v3, en, passive("R", "10k", R0402))
between(en, gnd, passive("C", "1u", C0402))
between(v3, gnd, passive("C", "10u", C0805))
between(v3, gnd, passive("C", "100n", C0402))
vsense += mcu["IO3"]
moist += mcu["IO4"]
sda += mcu["IO6"]
scl += mcu["IO7"]

# Battery voltage divider for the ADC.
between(vbat, vsense, passive("R", "1M", R0402))
between(vsense, gnd, passive("R", "1M", R0402))

# Temperature/humidity sensor on I2C with pull-ups.
sht = chip("U", "SHT40", ["VDD", "GND", "SDA", "SCL"], "soil:DFN-4_1.5x1.5mm", mpn="SHT40-AD1B-R2")
v3 += sht["VDD"]
gnd += sht["GND"]
sda += sht["SDA"]
scl += sht["SCL"]
between(v3, gnd, passive("C", "100n", C0402))
between(v3, sda, passive("R", "4k7", R0402))
between(v3, scl, passive("R", "4k7", R0402))

# Moisture probe buffered by an op-amp into the ADC.
amp = chip("U", "LMV321", ["V+", "V-", "IN+", "IN-", "OUT"], "Package_TO_SOT_SMD:SOT-23-5", mpn="LMV321IDBVR")
v3 += amp["V+"]
gnd += amp["V-"]
probe = Net("PROBE_SIG")
probe += amp["IN+"]
moist += amp["OUT"], amp["IN-"]
between(v3, gnd, passive("C", "100n", C0402))
jp = chip("J", "PROBE", ["V", "SIG", "GND"], "Connector_JST:JST_PH_S3B-PH-K_1x03_P2.00mm_Horizontal")
v3 += jp["V"]
probe += jp["SIG"]
gnd += jp["GND"]
between(probe, gnd, passive("R", "1M", R0402))

generate_netlist(file_="main.net", tool=KICAD8)
