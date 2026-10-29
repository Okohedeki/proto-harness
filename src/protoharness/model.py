"""Loads device.yaml, the single file that describes a whole device."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEVICE_FILE = "device.yaml"


class Device:
    def __init__(self, data: dict[str, Any], root: Path | str):
        self.data = data or {}
        self.root = Path(root)

    @classmethod
    def load(cls, path: Path | str = ".") -> "Device":
        p = Path(path)
        if p.is_dir():
            p = p / DEVICE_FILE
        if not p.exists():
            raise FileNotFoundError(f"No {DEVICE_FILE} in {p.parent}. Run `ph init` first.")
        with p.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{p} must be a YAML mapping at the top level")
        return cls(data, p.parent)

    def _list(self, key: str) -> list[dict[str, Any]]:
        value = self.data.get(key) or []
        return [v for v in value if isinstance(v, dict)]

    def _dict(self, key: str) -> dict[str, Any]:
        value = self.data.get(key) or {}
        return value if isinstance(value, dict) else {}

    @property
    def name(self) -> str:
        return str(self.data.get("name") or self.root.name)

    @property
    def requirements(self) -> dict[str, Any]:
        return self._dict("requirements")

    @property
    def blocks(self) -> list[dict[str, Any]]:
        return self._list("blocks")

    @property
    def interfaces(self) -> list[dict[str, Any]]:
        return self._list("interfaces")

    @property
    def power(self) -> dict[str, Any]:
        return self._dict("power")

    @property
    def parts(self) -> list[dict[str, Any]]:
        return self._list("parts")

    @property
    def boards(self) -> list[dict[str, Any]]:
        return self._list("boards")

    @property
    def mechanical(self) -> list[dict[str, Any]]:
        return self._list("mechanical")

    @property
    def firmware(self) -> list[dict[str, Any]]:
        return self._list("firmware")

    @property
    def compliance(self) -> dict[str, Any]:
        return self._dict("compliance")

    @property
    def manufacturing(self) -> dict[str, Any]:
        return self._dict("manufacturing")

    @property
    def quantity(self) -> int:
        try:
            return max(1, int(self.requirements.get("quantity") or 1))
        except (TypeError, ValueError):
            return 1

    def block(self, block_id: str) -> dict[str, Any] | None:
        return next((b for b in self.blocks if b.get("id") == block_id), None)

    def part(self, part_id: str) -> dict[str, Any] | None:
        return next((p for p in self.parts if p.get("id") == part_id), None)

    def path(self, rel: str) -> Path:
        return self.root / rel


def price_at(part: dict[str, Any], units: int) -> float | None:
    """Unit price for a part when buying `units`. Accepts a number or {break_qty: price}."""
    cost = part.get("unit_cost_usd")
    if cost is None:
        return None
    if isinstance(cost, (int, float)):
        return float(cost)
    if isinstance(cost, dict) and cost:
        breaks = sorted((int(q), float(p)) for q, p in cost.items())
        price = breaks[0][1]
        for qty, p in breaks:
            if units >= qty:
                price = p
        return price
    return None


def bom_lines(device: Device) -> list[dict[str, Any]]:
    """One row per part, priced at the device's build quantity."""
    rows = []
    for part in device.parts:
        per_unit = float(part.get("qty", 1) or 1)
        units = int(per_unit * device.quantity)
        price = price_at(part, units)
        rows.append({
            "id": part.get("id", "?"),
            "mpn": part.get("mpn", ""),
            "category": part.get("category", ""),
            "qty": per_unit,
            "unit_cost_usd": price,
            "line_cost_usd": None if price is None else price * per_unit,
            "suppliers": part.get("suppliers") or [],
            "lifecycle": part.get("lifecycle", ""),
            "lead_time_weeks": part.get("lead_time_weeks"),
        })
    return rows


def bom_total(device: Device) -> float:
    return sum(r["line_cost_usd"] or 0.0 for r in bom_lines(device))
