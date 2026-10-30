"""Builds boards from circuit code (SKiDL, atopile) and exports fab files from KiCad layouts."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import tools
from .model import Device


def generator(d: Device, board: dict[str, Any]) -> str:
    """skidl | atopile | kicad, from `generator:` or the source's file type."""
    if board.get("generator"):
        return str(board["generator"]).lower()
    src = d.path(str(board.get("source", "")))
    if src.suffix == ".py":
        return "skidl"
    if src.suffix == ".ato" or (src.is_dir() and (src / "ato.yaml").exists()):
        return "atopile"
    return "kicad"


def source_dir(d: Device, board: dict[str, Any]) -> Path:
    src = d.path(str(board.get("source", "")))
    return src if src.is_dir() else src.parent


def netlist_path(d: Device, board: dict[str, Any]) -> Path | None:
    if board.get("netlist"):
        return d.path(str(board["netlist"]))
    src = d.path(str(board.get("source", "")))
    if src.suffix == ".py":
        return src.with_suffix(".net")  # SKiDL's default output name
    nets = sorted(source_dir(d, board).glob("*.net")) if source_dir(d, board).exists() else []
    return nets[0] if nets else None


def layout_files(d: Device, board: dict[str, Any]) -> list[Path]:
    if board.get("pcb"):
        return [d.path(str(board["pcb"]))]
    folder = source_dir(d, board)
    return sorted(folder.glob("*.kicad_pcb")) if folder.exists() else []


def schematic_files(d: Device, board: dict[str, Any]) -> list[Path]:
    src = d.path(str(board.get("source", "")))
    if src.suffix == ".kicad_sch":
        return [src]
    folder = source_dir(d, board)
    return sorted(folder.glob("*.kicad_sch")) if folder.exists() else []


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class BoardBuild:
    board: str
    steps: list[Step] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)


def _tail(text: str, lines: int = 12) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def build_board(d: Device, board: dict[str, Any]) -> BoardBuild:
    bid = str(board.get("id", "?"))
    result = BoardBuild(bid)
    src = d.path(str(board.get("source", "")))
    if not board.get("source") or not src.exists():
        result.steps.append(Step("source", False, f"{board.get('source')} not found"))
        return result
    kind = generator(d, board)
    started = time.time()

    if kind == "skidl":
        code, out = tools.run([sys.executable, src.name], cwd=src.parent)
        net = netlist_path(d, board)
        made = net is not None and net.exists() and net.stat().st_mtime >= started - 1
        detail = str(net.relative_to(d.root)) if made else _tail(out) or "no netlist written"
        result.steps.append(Step("skidl netlist", code == 0 and made, detail))
    elif kind == "atopile":
        ato = tools.find(tools.tool("atopile"))
        if not ato:
            result.steps.append(Step("atopile build", False, "ato not found (pip install atopile)"))
        else:
            code, out = tools.run([ato, "build"], cwd=source_dir(d, board), timeout=1800)
            result.steps.append(Step("atopile build", code == 0, _tail(out)))
    if not result.ok:
        return result

    pcbs = [p for p in layout_files(d, board) if p.exists()]
    if not pcbs:
        result.steps.append(Step("fab outputs", True, "skipped: no .kicad_pcb layout yet"))
        return result
    kicad = tools.find(tools.tool("kicad-cli"))
    kibot = tools.find(tools.tool("kibot"))
    fab = d.path("hardware/fab") / bid
    fab.mkdir(parents=True, exist_ok=True)
    configs = sorted(source_dir(d, board).glob("*.kibot.yaml"))
    for pcb in pcbs:
        if kibot and configs:
            code, out = tools.run([kibot, "-c", str(configs[0]), "-b", str(pcb), "-d", str(fab)], timeout=1800)
            result.steps.append(Step(f"kibot {pcb.name}", code == 0, _tail(out) if code else str(fab.relative_to(d.root))))
        elif kicad:
            for label, args in (
                ("gerbers", ["pcb", "export", "gerbers", "--output", str(fab) + "/", str(pcb)]),
                ("drill", ["pcb", "export", "drill", "--output", str(fab) + "/", str(pcb)]),
                ("pick-and-place", ["pcb", "export", "pos", "--format", "csv", "--units", "mm",
                                    "--output", str(fab / f"{pcb.stem}-pos.csv"), str(pcb)]),
            ):
                code, out = tools.run([kicad, *args])
                result.steps.append(Step(f"{label} {pcb.name}", code == 0, _tail(out) if code else str(fab.relative_to(d.root))))
        else:
            result.steps.append(Step("fab outputs", True, "skipped: install KiCad (kicad-cli) or KiBot"))
    return result
