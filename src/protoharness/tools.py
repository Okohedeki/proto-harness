"""Finds and runs the external open-source tools the harness can use as checkers."""

from __future__ import annotations

import glob
import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Tool:
    key: str
    purpose: str
    commands: tuple[str, ...] = ()
    module: str | None = None
    install: str = ""


TOOLS = [
    Tool("kicad-cli", "Schematic ERC, PCB DRC, Gerber/BOM export", ("kicad-cli",),
         install="Install KiCad 8+ from kicad.org (Windows/macOS installer, Linux package or Flatpak)"),
    Tool("atopile", "Circuits written as code, compiled to KiCad", ("ato",),
         install="pip install atopile"),
    Tool("skidl", "Circuits written in Python, compiled to KiCad netlists", module="skidl",
         install="pip install skidl"),
    Tool("kibot", "One-command fab outputs (Gerbers, BOM, pick-and-place, renders)", ("kibot",),
         install="pip install kibot (needs KiCad)"),
    Tool("ngspice", "Analog circuit simulation", ("ngspice", "ngspice_con"),
         install="Windows: ngspice.sourceforge.io | macOS: brew install ngspice | Linux: apt install ngspice"),
    Tool("freerouting", "PCB autorouter", ("freerouting",),
         install="Download the release from github.com/freerouting/freerouting (needs Java 21+)"),
    Tool("platformio", "Firmware build for most microcontrollers", ("pio", "platformio"),
         install="pip install platformio"),
    Tool("cadquery", "Enclosures and mechanical parts as Python code", module="cadquery",
         install="pip install cadquery"),
    Tool("build123d", "Enclosures and mechanical parts as Python code", module="build123d",
         install="pip install build123d"),
    Tool("openscad", "Enclosures as code (CSG)", ("openscad",),
         install="openscad.org (Windows/macOS installer) or apt install openscad"),
]

# Places installers put binaries without adding them to PATH.
_EXTRA_DIRS = {
    "win32": ["C:/Program Files/KiCad/*/bin", "C:/Program Files/OpenSCAD", "C:/Program Files/ngspice/bin"],
    "darwin": ["/Applications/KiCad/KiCad.app/Contents/MacOS", "/Applications/OpenSCAD.app/Contents/MacOS"],
}


def find(tool: Tool) -> str | None:
    if tool.module:
        return "python module" if importlib.util.find_spec(tool.module) else None
    for cmd in tool.commands:
        hit = shutil.which(cmd)
        if hit:
            return hit
        for pattern in _EXTRA_DIRS.get(sys.platform, []):
            for d in sorted(glob.glob(pattern), reverse=True):
                for name in (cmd, cmd + ".exe"):
                    candidate = Path(d) / name
                    if candidate.exists():
                        return str(candidate)
    return None


def tool(key: str) -> Tool:
    return next(t for t in TOOLS if t.key == key)


def run(args: list[str], cwd: Path | None = None, timeout: int = 600) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
