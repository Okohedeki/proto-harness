"""Reads KiCad netlists (.net, as written by KiCad, SKiDL or atopile) and checks them.

These are design checks ERC does not do: footprints for fab, dangling nets, missing rails,
decoupling, I2C pull-ups, and whether the board and device.yaml agree on the parts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import Device

PART_FIELD_NAMES = ("mpn", "mfr part", "manufacturer part number", "manufacturer_part_number", "part number")
BOM_CATEGORIES = {"ic", "module", "sensor", "connector", "display", "radio"}


# --- s-expression reader ----------------------------------------------------------------------

_TOKEN = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+')


def parse_sexpr(text: str) -> list[Any]:
    stack: list[list[Any]] = [[]]
    for tok in _TOKEN.findall(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced ')' in netlist")
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(tok[1:-1].replace('\\"', '"').replace("\\\\", "\\"))
        else:
            stack[-1].append(tok)
    if len(stack) != 1:
        raise ValueError("unbalanced '(' in netlist")
    return stack[0]


def _children(node: list[Any], key: str) -> list[list[Any]]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == key]


def _value(node: list[Any], key: str, default: str = "") -> str:
    hit = _children(node, key)
    return str(hit[0][1]) if hit and len(hit[0]) > 1 and not isinstance(hit[0][1], list) else default


# --- model -------------------------------------------------------------------------------------


@dataclass
class Component:
    ref: str
    value: str
    footprint: str
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def mpn(self) -> str | None:
        for k, v in self.fields.items():
            if k.lower() in PART_FIELD_NAMES and v:
                return v
        return None

    @property
    def prefix(self) -> str:
        return re.match(r"[A-Za-z_#]*", self.ref).group(0).upper()


@dataclass
class Node:
    ref: str
    pin: str
    function: str = ""
    pintype: str = ""


@dataclass
class Net:
    name: str
    nodes: list[Node]

    def refs(self) -> set[str]:
        return {n.ref for n in self.nodes}


@dataclass
class Netlist:
    components: dict[str, Component]
    nets: list[Net]

    def nets_of(self, ref: str) -> list[Net]:
        return [n for n in self.nets if ref in n.refs()]


def load_netlist(path: Path | str) -> Netlist:
    tree = parse_sexpr(Path(path).read_text(encoding="utf-8"))
    root = next((n for n in tree if isinstance(n, list) and n and n[0] == "export"), None)
    if root is None:
        raise ValueError(f"{path} is not a KiCad netlist (no export section)")
    comps: dict[str, Component] = {}
    for section in _children(root, "components"):
        for c in _children(section, "comp"):
            fields = {}
            for fs in _children(c, "fields"):
                for f in _children(fs, "field"):
                    name = _value(f, "name")
                    rest = [x for x in f[1:] if not isinstance(x, list)]
                    fields[name] = str(rest[0]) if rest else ""
            ref = _value(c, "ref")
            comps[ref] = Component(ref, _value(c, "value"), _value(c, "footprint"), fields)
    nets = []
    for section in _children(root, "nets"):
        for n in _children(section, "net"):
            nodes = [Node(_value(x, "ref"), _value(x, "pin"), _value(x, "pinfunction"), _value(x, "pintype"))
                     for x in _children(n, "node")]
            nets.append(Net(_value(n, "name"), nodes))
    return Netlist(comps, nets)


# --- checks ------------------------------------------------------------------------------------


def rail_key(name: str) -> str:
    """'+3V3', '3.3V', '3v3', 'VCC_3V3' -> '3v3'; '+5V', '5v' -> '5'; other names lowercased."""
    s = str(name).lower().strip().lstrip("+/")
    for prefix in ("vcc_", "vdd_", "v_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    s = s.replace(".", "v")
    return s.rstrip("v") if re.fullmatch(r"\d+(v\d*)?v?", s) else s


POWER_NAME = re.compile(r"^/?(\+.*|(vbus|vbat|vin|vsys|vcc|vdd)(_?\d.*)?)$", re.IGNORECASE)


def is_ground(name: str) -> bool:
    return bool(re.fullmatch(r"/?(a|d|p)?gnd\w*|/?vss\w*|/?0v", name.lower()))


def check_netlist(d: Device, board_id: str, nl: Netlist, report) -> None:
    """`report(level, message)` receives each finding."""
    tag = f"board '{board_id}'"
    for c in nl.components.values():
        if not c.footprint:
            report("error", f"{tag}: {c.ref} ({c.value}) has no footprint; it cannot be laid out or assembled")
    for net in nl.nets:
        if len(net.nodes) == 1 and not net.name.lower().startswith(("unconnected", "nc", "/nc")):
            n = net.nodes[0]
            report("warn", f"{tag}: net {net.name} only touches {n.ref} pin {n.pin}")

    rails = {rail_key(r["id"]): r["id"] for r in d.power.get("rails") or [] if r.get("id")}
    by_key = {rail_key(n.name): n for n in nl.nets}
    power_nets = [n for n in nl.nets if rail_key(n.name) in rails or POWER_NAME.match(n.name)]
    has_ics = any(c.prefix in ("U", "IC") for c in nl.components.values())
    if has_ics and not any(is_ground(n.name) for n in nl.nets):
        report("error", f"{tag}: no ground net (GND)")
    for key, rid in rails.items():
        if key not in by_key and len(d.boards) == 1:
            report("warn", f"{tag}: power rail '{rid}' from device.yaml has no matching net (e.g. +{rid.upper()})")

    for c in nl.components.values():
        if c.prefix not in ("U", "IC"):
            continue
        for pn in [n for n in power_nets if c.ref in n.refs()]:
            if not any(nl.components.get(r) and nl.components[r].prefix == "C" for r in pn.refs()):
                report("warn", f"{tag}: {c.ref} ({c.value}) has no capacitor on {pn.name}; add local decoupling")

    for net in nl.nets:
        if not re.search(r"(^|[_/])(SDA|SCL)(\d*$|_)", net.name.upper()):
            continue
        pulled = False
        for ref in net.refs():
            comp = nl.components.get(ref)
            if comp and comp.prefix == "R":
                others = [n for n in nl.nets_of(ref) if n is not net]
                pulled |= any(n in power_nets for n in others)
        if not pulled:
            report("warn", f"{tag}: I2C net {net.name} has no pull-up resistor to a power rail")


def check_bom_agreement(d: Device, netlists: dict[str, Netlist], report) -> None:
    """device.yaml parts and board netlists must name the same chips."""
    on_boards: dict[str, str] = {}
    for bid, nl in netlists.items():
        for c in nl.components.values():
            for name in filter(None, (c.mpn, c.value)):
                on_boards.setdefault(name.upper(), f"{bid}:{c.ref}")
    known = {str(p.get("mpn", "")).upper() for p in d.parts}
    for p in d.parts:
        mpn = str(p.get("mpn") or "")
        if str(p.get("category", "")).lower() in BOM_CATEGORIES and mpn and mpn.upper() != "TBD" \
                and mpn.upper() not in on_boards and not p.get("off_board"):
            report("warn", f"part '{p.get('id')}' ({mpn}) is in device.yaml but on no board netlist "
                           f"(set off_board: true if that's intended)")
    for bid, nl in netlists.items():
        for c in nl.components.values():
            if c.mpn and c.mpn.upper() not in known:
                report("warn", f"board '{bid}': {c.ref} ({c.mpn}) is not in device.yaml parts, so it is not costed or sourced")
