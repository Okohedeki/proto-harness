"""Power tree math: rail currents, source draw and battery life."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .model import Device

LINEAR = {"ldo", "linear", "direct", "switch", "none"}
DEFAULT_EFFICIENCY = 0.85
BATTERY_DERATE = 0.8  # usable fraction of rated capacity (aging, cold, cutoff voltage)


@dataclass
class RailLoad:
    rail: str
    voltage_v: float
    peak_ma: float
    avg_ma: float
    max_current_ma: float | None
    parent: str | None


def load_currents(load: dict[str, Any]) -> tuple[float, float]:
    """(peak_ma, avg_ma) for one load entry."""
    active = float(load.get("active_ma", 0) or 0)
    sleep = float(load.get("sleep_ma", 0) or 0)
    duty = float(load.get("duty", 1 if not sleep else 0) or 0)
    duty = min(max(duty, 0.0), 1.0)
    peak = float(load.get("peak_ma", active) or active)
    return peak, active * duty + sleep * (1 - duty)


class PowerTree:
    def __init__(self, device: Device):
        p = device.power
        self.sources = {s["id"]: s for s in p.get("sources") or [] if isinstance(s, dict) and "id" in s}
        self.rails = {r["id"]: r for r in p.get("rails") or [] if isinstance(r, dict) and "id" in r}
        self.loads = [l for l in p.get("loads") or [] if isinstance(l, dict)]

    def node_voltage(self, node: str) -> float | None:
        if node in self.rails:
            return _num(self.rails[node].get("voltage_v"))
        if node in self.sources:
            return _num(self.sources[node].get("voltage_v"))
        return None

    def rail_output(self, rail_id: str, _seen: frozenset[str] = frozenset()) -> tuple[float, float]:
        """(peak_ma, avg_ma) delivered by a rail: its own loads plus child rails' input draw."""
        if rail_id in _seen:
            raise ValueError(f"power rails form a loop through '{rail_id}'")
        seen = _seen | {rail_id}
        peak = avg = 0.0
        for load in self.loads:
            if load.get("rail") == rail_id:
                lp, la = load_currents(load)
                peak, avg = peak + lp, avg + la
        for child_id, child in self.rails.items():
            if child.get("from") == rail_id:
                cp, ca = self.rail_input(child_id, seen)
                peak, avg = peak + cp, avg + ca
        return peak, avg

    def rail_input(self, rail_id: str, _seen: frozenset[str] = frozenset()) -> tuple[float, float]:
        """(peak_ma, avg_ma) a rail pulls from whatever feeds it."""
        rail = self.rails[rail_id]
        out_peak, out_avg = self.rail_output(rail_id, _seen)
        quiescent = float(rail.get("quiescent_ma", 0) or 0)
        kind = str(rail.get("regulator", "ldo")).lower()
        if kind in LINEAR:
            return out_peak + quiescent, out_avg + quiescent
        vout = _num(rail.get("voltage_v")) or 0.0
        vin = self.node_voltage(str(rail.get("from"))) or vout or 1.0
        eff = float(rail.get("efficiency", DEFAULT_EFFICIENCY) or DEFAULT_EFFICIENCY)
        scale = vout / (vin * eff) if vin else 1.0
        return out_peak * scale + quiescent, out_avg * scale + quiescent

    def rail_summary(self) -> list[RailLoad]:
        rows = []
        for rid, rail in self.rails.items():
            peak, avg = self.rail_output(rid)
            rows.append(RailLoad(rid, _num(rail.get("voltage_v")) or 0.0, peak, avg,
                                 _num(rail.get("max_current_ma")), rail.get("from")))
        return rows

    def source_draw(self, source_id: str) -> tuple[float, float]:
        peak = avg = 0.0
        for rid, rail in self.rails.items():
            if rail.get("from") == source_id:
                rp, ra = self.rail_input(rid)
                peak, avg = peak + rp, avg + ra
        for load in self.loads:
            if load.get("rail") == source_id:
                lp, la = load_currents(load)
                peak, avg = peak + lp, avg + la
        return peak, avg

    def battery_life_days(self, source_id: str) -> float | None:
        src = self.sources[source_id]
        cap = _num(src.get("capacity_mah"))
        if not cap:
            return None
        _, avg = self.source_draw(source_id)
        if avg <= 0:
            return None
        return cap * BATTERY_DERATE / avg / 24.0


def _num(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None
