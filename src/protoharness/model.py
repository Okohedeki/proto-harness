"""Loads device.yaml, the single file that describes a whole device."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

DEVICE_FILE = "device.yaml"
LOCK_FILE = "parts.lock.json"  # live distributor data, written by `ph parts`
STALE_DAYS = 30


class Device:
    def __init__(self, data: dict[str, Any], root: Path | str, lock: dict[str, Any] | None = None):
        self.data = data or {}
        self.root = Path(root)
        self._lock = lock

    @property
    def lock(self) -> dict[str, Any]:
        if self._lock is None:
            p = self.root / LOCK_FILE
            try:
                self._lock = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            except (OSError, json.JSONDecodeError):
                self._lock = {}
        return self._lock

    def live(self, part: dict[str, Any]) -> dict[str, Any] | None:
        """Lock entry for a part, only if it was looked up for the part's current MPN."""
        entry = (self.lock.get("parts") or {}).get(part.get("id"))
        if not entry or str(entry.get("mpn", "")).upper() != str(part.get("mpn", "")).upper():
            return None
        return entry

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


def offer_price(offer: dict[str, Any], units: int) -> float | None:
    breaks = sorted((int(q), float(p)) for q, p in offer.get("price_breaks") or [])
    if not breaks or offer.get("currency", "USD") != "USD":
        return None
    return price_at({"unit_cost_usd": dict(breaks)}, units)


def best_offer(entry: dict[str, Any], units: int) -> tuple[dict[str, Any] | None, float | None]:
    """Cheapest USD offer that can cover `units` from stock, else the cheapest priced offer."""
    priced = [(o, offer_price(o, units)) for o in entry.get("offers") or []]
    priced = [(o, p) for o, p in priced if p is not None]
    if not priced:
        return None, None
    in_stock = [(o, p) for o, p in priced if int(o.get("stock") or 0) >= units]
    return min(in_stock or priced, key=lambda op: op[1])


def age_days(entry: dict[str, Any]) -> float | None:
    try:
        when = datetime.fromisoformat(str(entry.get("looked_up")))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 86400


def bom_lines(device: Device) -> list[dict[str, Any]]:
    """One row per part, priced at the device's build quantity. Live prices win over typed ones."""
    rows = []
    for part in device.parts:
        per_unit = float(part.get("qty", 1) or 1)
        units = int(per_unit * device.quantity)
        price, price_source = price_at(part, units), "typed"
        suppliers = list(part.get("suppliers") or [])
        entry = device.live(part)
        if entry:
            for o in entry.get("offers") or []:
                if int(o.get("stock") or 0) > 0 and o.get("supplier") not in suppliers:
                    suppliers.append(o.get("supplier"))
            offer, live_price = best_offer(entry, units)
            if live_price is not None:
                price = live_price
                price_source = f"{offer.get('supplier')} {str(entry.get('looked_up', ''))[:10]}"
        rows.append({
            "id": part.get("id", "?"),
            "mpn": part.get("mpn", ""),
            "category": part.get("category", ""),
            "qty": per_unit,
            "unit_cost_usd": price,
            "price_source": price_source if price is not None else "",
            "line_cost_usd": None if price is None else price * per_unit,
            "suppliers": suppliers,
            "lifecycle": part.get("lifecycle", ""),
            "lead_time_weeks": part.get("lead_time_weeks"),
        })
    return rows


def bom_total(device: Device) -> float:
    return sum(r["line_cost_usd"] or 0.0 for r in bom_lines(device))
