"""Derives a starting list of certifications from what the device contains and where it sells.

This is a checklist to start a conversation with a test lab, not legal advice. Rules
differ by product category (medical, toys, automotive, wearables...) and change over time.
"""

from __future__ import annotations

from .model import Device

LITHIUM = ("li-ion", "lipo", "li-po", "lifepo4", "lithium", "li-metal")


def device_traits(device: Device) -> dict[str, bool]:
    features: set[str] = set()
    for part in device.parts:
        features.update(str(f).lower() for f in part.get("features") or [])
    features.update(str(f).lower() for f in device.requirements.get("features") or [])
    radio_parts = [p for p in device.parts
                   if any(str(f).lower().startswith("radio") for f in p.get("features") or [])]
    sources = device.power.get("sources") or []
    return {
        "electronics": bool(device.boards) or any(b.get("kind") in ("electronics", "sensor") for b in device.blocks),
        "radio": any(f.startswith("radio") for f in features),
        "radio_module_certified": bool(radio_parts) and all(p.get("certified") for p in radio_parts),
        "lithium": any(str(s.get("chemistry", "")).lower().startswith(LITHIUM) for s in sources),
        "mains": any(s.get("kind") == "mains" for s in sources),
        "laser": "laser" in features,
        "child": bool(device.requirements.get("for_children")),
    }


def required_certifications(device: Device) -> list[tuple[str, str]]:
    """(name, why) pairs."""
    t = device_traits(device)
    markets = {str(m).upper() for m in device.requirements.get("markets") or []}
    out: list[tuple[str, str]] = []

    def add(name: str, why: str) -> None:
        if name not in (n for n, _ in out):
            out.append((name, why))

    if "US" in markets:
        if t["electronics"]:
            add("FCC Part 15 Subpart B", "any digital electronics sold in the US (unintentional emissions)")
        if t["radio"]:
            if t["radio_module_certified"]:
                add("FCC modular grant reuse", "pre-certified radio module: follow its integration rules and label 'Contains FCC ID'")
            else:
                add("FCC Part 15 Subpart C", "intentional radiator with a custom radio design")
        if t["mains"]:
            add("NRTL safety listing (UL/IEC 62368-1 or category standard)", "mains-powered product")
    if "CA" in markets:
        if t["electronics"]:
            add("ISED ICES-003", "digital electronics sold in Canada")
        if t["radio"]:
            add("ISED radio certification (RSS)", "radio product sold in Canada")
    for region, mark in (("EU", "CE"), ("UK", "UKCA")):
        if region not in markets:
            continue
        add(f"{mark} marking + Declaration of Conformity", f"any electrical product sold in the {region}")
        add(f"RoHS ({region})", "restricted substances in electrical products")
        add(f"WEEE ({region})", "take-back registration for electrical products")
        if t["radio"]:
            add(f"Radio equipment rules ({region}, RED/RER)", "radio product; covers EMC, safety and spectrum")
        elif t["electronics"]:
            add(f"EMC ({region}, e.g. EN 55032/55035)", "electromagnetic compatibility")
        if t["mains"]:
            add(f"Low Voltage / electrical safety ({region})", "mains-powered product")
        if t["lithium"]:
            add(f"Battery regulation ({region})", "product contains a battery")
    if t["lithium"]:
        add("UN 38.3", "shipping lithium cells or packs")
        add("IEC 62133-2", "lithium cell/pack safety, usually supplied by the cell vendor")
    if t["laser"]:
        add("IEC 60825-1 laser classification", "contains a laser")
    if t["child"]:
        add("Toy / child-product safety for each market", "product intended for children")
    return out
