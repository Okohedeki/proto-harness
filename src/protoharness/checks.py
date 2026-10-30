"""Stage gates. Each stage runs deterministic checks; an error blocks the gate, a warning does not."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import build, tools
from .compliance import required_certifications
from .lock import needs_lookup
from .model import STALE_DAYS, Device, age_days, bom_lines, bom_total, price_at
from .netlist import check_bom_agreement, check_netlist, load_netlist
from .power import PowerTree

ERROR, WARN, INFO = "error", "warn", "info"
BAD_LIFECYCLE = {"eol", "obsolete", "discontinued"}
RISKY_LIFECYCLE = {"nrnd", "last-time-buy", "ltb"}
PASSIVE = {"passive", "resistor", "capacitor", "inductor", "fastener", "hardware"}
POWERED_KINDS = {"electronics", "sensor", "actuator", "compute", "display", "radio"}


@dataclass
class Finding:
    level: str
    message: str


@dataclass
class StageResult:
    stage: str
    title: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(f.level == ERROR for f in self.findings)

    def error(self, msg: str) -> None:
        self.findings.append(Finding(ERROR, msg))

    def warn(self, msg: str) -> None:
        self.findings.append(Finding(WARN, msg))

    def info(self, msg: str) -> None:
        self.findings.append(Finding(INFO, msg))


def _dims(value) -> list[float] | None:
    try:
        return sorted(float(v) for v in value) if value else None
    except (TypeError, ValueError):
        return None


def _fits(inner: list[float], item: list[float], clearance: float) -> bool:
    """Axis-aligned fit allowing any rotation (both sorted ascending)."""
    item = item + [0.0] * (len(inner) - len(item))
    return all(i + clearance <= o for i, o in zip(sorted(item), inner))


# --- stages -------------------------------------------------------------------------------


def check_spec(d: Device, r: StageResult) -> None:
    if not d.data.get("summary"):
        r.error("summary: say in one or two sentences what the device does and for whom")
    req = d.requirements
    for key, why in (("quantity", "how many units the first real build is for"),
                     ("target_unit_cost_usd", "what one unit may cost to build"),
                     ("markets", "where it will be sold (drives certification)"),
                     ("environment", "where it lives: indoor, outdoor, wearable, vehicle...")):
        if req.get(key) in (None, "", []):
            r.error(f"requirements.{key} missing: {why}")
    if not req.get("size_mm"):
        r.warn("requirements.size_mm not set: no size limit will be checked")
    if not req.get("functions"):
        r.warn("requirements.functions empty: list what the user must be able to do with it")


def check_architecture(d: Device, r: StageResult) -> None:
    if not d.blocks:
        r.error("no blocks: break the device into subsystems (compute, sensing, power, enclosure...)")
        return
    ids = [b.get("id") for b in d.blocks]
    for dup in {i for i in ids if ids.count(i) > 1}:
        r.error(f"block id '{dup}' is used twice")
    for b in d.blocks:
        if not b.get("kind"):
            r.warn(f"block '{b.get('id')}' has no kind")
    for i, itf in enumerate(d.interfaces):
        a, b = itf.get("from"), itf.get("to")
        label = f"interface {a}->{b} ({itf.get('kind', '?')})"
        missing = [x for x in (a, b) if d.block(x) is None]
        if missing:
            r.error(f"{label}: unknown block(s) {', '.join(map(str, missing))}")
            continue
        va, vb = d.block(a).get("io_v"), d.block(b).get("io_v")
        if va is not None and vb is not None and float(va) != float(vb) and not itf.get("level_shift"):
            r.error(f"{label}: logic levels differ ({va} V vs {vb} V); add a level shifter and set level_shift: true")
        if not itf.get("kind"):
            r.warn(f"{label}: no kind (i2c, spi, uart, usb, can, gpio, pwm, analog, mechanical...)")
    linked = {itf.get("from") for itf in d.interfaces} | {itf.get("to") for itf in d.interfaces}
    for b in d.blocks:
        if len(d.blocks) > 1 and b.get("id") not in linked and b.get("kind") != "mechanical":
            r.warn(f"block '{b.get('id')}' connects to nothing")


def check_power(d: Device, r: StageResult) -> None:
    powered = [b for b in d.blocks if b.get("kind") in POWERED_KINDS]
    if not powered:
        r.info("no powered blocks: skipping power")
        return
    tree = PowerTree(d)
    if not tree.sources:
        r.error("power.sources empty: battery, usb, dc or mains?")
        return
    for rid, rail in tree.rails.items():
        if rail.get("from") not in tree.rails and rail.get("from") not in tree.sources:
            r.error(f"rail '{rid}' is fed from unknown '{rail.get('from')}'")
            return
    loaded = {l.get("block") for l in tree.loads}
    for b in powered:
        if b.get("id") not in loaded:
            r.error(f"block '{b.get('id')}' has no entry in power.loads")
    for load in tree.loads:
        if d.block(load.get("block")) is None:
            r.error(f"power load for unknown block '{load.get('block')}'")
        if load.get("rail") not in tree.rails and load.get("rail") not in tree.sources:
            r.error(f"power load '{load.get('block')}' is on unknown rail '{load.get('rail')}'")
    if not r.passed:
        return
    try:
        rows = tree.rail_summary()
    except ValueError as exc:
        r.error(str(exc))
        return
    for row in rows:
        if row.max_current_ma is None and tree.rails[row.rail].get("max_current_ma") is not None:
            r.error(f"rail '{row.rail}': max_current_ma must be a number")
        elif row.max_current_ma is None:
            r.warn(f"rail '{row.rail}' has no max_current_ma: regulator capacity unchecked")
        elif row.peak_ma > row.max_current_ma:
            r.error(f"rail '{row.rail}' peak {row.peak_ma:.0f} mA exceeds regulator limit {row.max_current_ma:.0f} mA")
        elif row.peak_ma > 0.8 * row.max_current_ma:
            r.warn(f"rail '{row.rail}' peak {row.peak_ma:.0f} mA is over 80% of {row.max_current_ma:.0f} mA")
        rail = tree.rails[row.rail]
        if str(rail.get("regulator", "ldo")).lower() in ("ldo", "linear"):
            parent = rail.get("from")
            src = tree.sources.get(parent, {})
            vin_min = src.get("min_voltage_v", tree.node_voltage(parent))
            dropout = float(rail.get("dropout_v", 0.3))
            if vin_min is not None and float(vin_min) < row.voltage_v + dropout:
                r.error(f"rail '{row.rail}' ({row.voltage_v} V LDO) drops out when '{parent}' falls to "
                        f"{vin_min} V; use a buck-boost or a lower rail voltage")
    for sid, src in tree.sources.items():
        peak, avg = tree.source_draw(sid)
        limit = src.get("max_current_ma")
        if limit is not None and peak > float(limit):
            r.error(f"source '{sid}' peak draw {peak:.0f} mA exceeds its {limit} mA limit")
        if src.get("kind") == "battery":
            life = tree.battery_life_days(sid)
            want = d.requirements.get("battery_life_days")
            if life is None:
                r.warn(f"battery '{sid}' has no capacity_mah: battery life unknown")
            else:
                r.info(f"battery '{sid}': average {avg:.3f} mA, about {life:.0f} days")
                if want and life < float(want):
                    r.error(f"battery life about {life:.0f} days, requirement is {want} days")


def check_parts(d: Device, r: StageResult) -> None:
    for b in d.blocks:
        pid = b.get("part")
        if b.get("kind") == "mechanical" and not pid:
            continue
        if not pid:
            r.error(f"block '{b.get('id')}' has no part chosen")
        elif d.part(pid) is None:
            r.error(f"block '{b.get('id')}' uses part '{pid}' which is not in parts")
    for line, part in zip(bom_lines(d), d.parts):
        pid = line["id"]
        if not line["mpn"] or str(line["mpn"]).upper() == "TBD":
            r.error(f"part '{pid}': no manufacturer part number")
        if line["unit_cost_usd"] is None:
            r.error(f"part '{pid}': no price; run `ph parts` or set unit_cost_usd")
        live_life = _check_live(d, part, line, r)
        life = (live_life or str(line["lifecycle"])).lower()
        if life in BAD_LIFECYCLE:
            r.error(f"part '{pid}': lifecycle is {life}")
        elif life in RISKY_LIFECYCLE:
            r.warn(f"part '{pid}': lifecycle is {life}; find a replacement before volume")
        elif not life:
            r.warn(f"part '{pid}': lifecycle unknown")
        if not line["suppliers"]:
            r.error(f"part '{pid}': no supplier with stock")
        elif len(line["suppliers"]) == 1 and str(line["category"]).lower() not in PASSIVE:
            r.warn(f"part '{pid}': single source ({line['suppliers'][0]})")
    total = bom_total(d)
    target = d.requirements.get("target_unit_cost_usd")
    if target:
        target = float(target)
        r.info(f"parts cost ${total:.2f}/unit at {d.quantity} units (target ${target:.2f})")
        if total > target:
            r.error(f"parts alone cost ${total:.2f}, above the ${target:.2f} unit target")
        elif total > 0.6 * target:
            r.warn(f"parts are {total / target:.0%} of the target; assembly, enclosure, packaging and yield usually need the rest")


_LIFE_RANK = {"obsolete": 3, "discontinued": 3, "eol": 3, "nrnd": 2, "last-time-buy": 2, "ltb": 2, "active": 1}


def _check_live(d: Device, part: dict, line: dict, r: StageResult) -> str | None:
    """Checks a part against its parts.lock.json entry. Returns the worst live lifecycle, if any."""
    if not needs_lookup(part):
        return None
    pid = line["id"]
    entry = d.live(part)
    if entry is None:
        r.warn(f"part '{pid}': stock and price not checked live; run `ph parts`")
        return None
    age = age_days(entry)
    if age is not None and age > STALE_DAYS:
        r.warn(f"part '{pid}': live data is {age:.0f} days old; run `ph parts`")
    offers = entry.get("offers") or []
    if not offers:
        where = ", ".join(entry.get("sources") or []) or "any source"
        failed = "; ".join(f"{k}: {v}" for k, v in (entry.get("errors") or {}).items())
        r.warn(f"part '{pid}': {line['mpn']} not found at {where}" + (f" ({failed})" if failed else ""))
        return None
    need = int(float(part.get("qty", 1) or 1) * d.quantity)
    stock = sum(int(o.get("stock") or 0) for o in offers)
    sellers = sorted({o.get("supplier", "?") for o in offers})
    if stock == 0:
        r.error(f"part '{pid}': out of stock at {', '.join(sellers)}")
    elif stock < need:
        r.warn(f"part '{pid}': {stock} in stock across {', '.join(sellers)}, build needs {need}; check factory lead time")
    else:
        r.info(f"part '{pid}': {stock} in stock ({', '.join(sellers)}), ${line['unit_cost_usd'] or 0:.3f} each at {need}")
    typed = price_at(part, need)
    if typed and line["unit_cost_usd"] and abs(line["unit_cost_usd"] - typed) / typed > 0.25:
        r.info(f"part '{pid}': live price ${line['unit_cost_usd']:.3f} differs from typed ${typed:.3f}; live price is used")
    lives = [str(o["lifecycle"]).lower() for o in offers if o.get("lifecycle")]
    return max(lives, key=lambda x: _LIFE_RANK.get(x, 0)) if lives else None


def check_electronics(d: Device, r: StageResult) -> None:
    if not d.boards:
        if any(b.get("kind") in POWERED_KINDS for b in d.blocks):
            r.error("electronics in the architecture but no boards defined")
        else:
            r.info("no boards: purely mechanical device")
        return
    kicad = tools.find(tools.tool("kicad-cli"))
    out_dir = d.path(".ph")
    report = {ERROR: r.error, WARN: r.warn, INFO: r.info}
    netlists = {}
    for board in d.boards:
        bid = board.get("id", "?")
        if not _dims(board.get("size_mm")):
            r.error(f"board '{bid}': size_mm missing")
        if not board.get("layers"):
            r.warn(f"board '{bid}': layer count missing")
        src = board.get("source")
        if not src:
            r.error(f"board '{bid}': no source (KiCad project, .ato or SKiDL file)")
            continue
        path = d.path(src)
        if not path.exists():
            r.error(f"board '{bid}': source {src} not found")
            continue

        kind = build.generator(d, board)
        net = build.netlist_path(d, board)
        if kind in ("skidl", "atopile"):
            if net is None or not net.exists():
                r.error(f"board '{bid}': {kind} circuit not built yet; run `ph build`")
                net = None
            elif path.is_file() and net.stat().st_mtime < path.stat().st_mtime:
                r.warn(f"board '{bid}': netlist is older than {src}; run `ph build`")
        if net is not None and net.exists():
            try:
                netlists[bid] = load_netlist(net)
            except (OSError, ValueError) as exc:
                r.error(f"board '{bid}': cannot read netlist {net.name}: {exc}")
            else:
                nl = netlists[bid]
                r.info(f"board '{bid}': {len(nl.components)} components, {len(nl.nets)} nets in {net.name}")
                check_netlist(d, bid, nl, lambda level, msg: report[level](msg))

        sch, pcb = build.schematic_files(d, board), [p for p in build.layout_files(d, board) if p.exists()]
        if not pcb:
            r.warn(f"board '{bid}': no PCB layout (.kicad_pcb) yet")
        if not sch and not pcb:
            continue
        if not kicad:
            r.warn(f"board '{bid}': kicad-cli not found, ERC/DRC not run (see `ph doctor`)")
            continue
        out_dir.mkdir(exist_ok=True)
        for f in sch + pcb:
            sub = "sch" if f.suffix == ".kicad_sch" else "pcb"
            rule = "erc" if sub == "sch" else "drc"
            rpt = out_dir / f"{f.stem}.{rule}.rpt"
            code, _ = tools.run([kicad, sub, rule, "--exit-code-violations", "-o", str(rpt), str(f)])
            if code == 0:
                r.info(f"board '{bid}': {rule.upper()} clean on {f.name}")
            else:
                r.error(f"board '{bid}': {rule.upper()} violations in {f.name} (report: {rpt.relative_to(d.root)})")
    if netlists:
        check_bom_agreement(d, netlists, lambda level, msg: report[level](msg))


def check_mechanical(d: Device, r: StageResult) -> None:
    if not d.mechanical:
        r.error("no mechanical parts: even a bare board needs a mounting or enclosure decision")
        return
    envelope = _dims(d.requirements.get("size_mm"))
    for m in d.mechanical:
        mid = m.get("id", "?")
        for key in ("process", "material"):
            if not m.get(key):
                r.error(f"mechanical '{mid}': {key} missing")
        if m.get("source") and not d.path(m["source"]).exists():
            r.error(f"mechanical '{mid}': source {m['source']} not found")
        elif not m.get("source"):
            r.warn(f"mechanical '{mid}': no CAD source yet")
        inner = _dims(m.get("inner_mm"))
        wall = float(m.get("wall_mm", 2))
        outer = _dims(m.get("outer_mm")) or ([x + 2 * wall for x in inner] if inner else None)
        if envelope and outer and not _fits(envelope, outer, 0):
            r.error(f"mechanical '{mid}': outside {outer} mm is larger than the size limit {envelope} mm")
        clearance = float(m.get("clearance_mm", 1))
        held_volume = 0.0
        for held in m.get("holds") or []:
            board = next((b for b in d.boards if b.get("id") == held), None)
            if board:
                dims = _dims(list(board.get("size_mm") or []) + [board.get("height_mm", 8)])
            else:
                part = d.part(held) or {}
                dims = _dims(part.get("dims_mm"))
            if dims and len(dims) == 3:
                held_volume += dims[0] * dims[1] * dims[2]
            if not dims:
                r.warn(f"mechanical '{mid}': size of '{held}' unknown, fit unchecked")
            elif not inner:
                r.warn(f"mechanical '{mid}': inner_mm missing, fit of '{held}' unchecked")
            elif not _fits(inner, dims, clearance):
                r.error(f"mechanical '{mid}': '{held}' ({dims} mm) does not fit inside {inner} mm with {clearance} mm clearance")
        if inner and len(inner) == 3 and held_volume > 0.7 * inner[0] * inner[1] * inner[2]:
            r.warn(f"mechanical '{mid}': contents fill over 70% of the inner volume; check the packing in CAD")


def check_firmware(d: Device, r: StageResult) -> None:
    needs_fw = any(b.get("kind") in ("compute", "electronics") and b.get("programmable") for b in d.blocks)
    if not d.firmware:
        (r.error if needs_fw else r.info)("no firmware entries" + (" but a programmable block exists" if needs_fw else ""))
        return
    pio = tools.find(tools.tool("platformio"))
    for fw in d.firmware:
        fid = fw.get("id", "?")
        if d.block(fw.get("target")) is None:
            r.error(f"firmware '{fid}': target block '{fw.get('target')}' not found")
        path = d.path(fw.get("path", ""))
        if not fw.get("path") or not path.exists():
            r.error(f"firmware '{fid}': path {fw.get('path')} not found")
            continue
        if fw.get("framework") == "platformio" and (path / "platformio.ini").exists():
            if not pio:
                r.warn(f"firmware '{fid}': platformio not found, build not checked")
                continue
            code, out = tools.run([pio, "run", "-d", str(path)], timeout=1800)
            (r.info if code == 0 else r.error)(f"firmware '{fid}': build {'passed' if code == 0 else 'failed'}")
        else:
            r.warn(f"firmware '{fid}': no automatic build check for framework '{fw.get('framework')}'")


def check_compliance(d: Device, r: StageResult) -> None:
    plans = {str(k).lower(): v for k, v in (d.compliance.get("plans") or {}).items()}
    needed = required_certifications(d)
    if not needed:
        r.info("no certifications derived; confirm with a test lab for your product category")
    for name, why in needed:
        if name.lower() not in plans:
            r.error(f"no plan for {name} ({why})")
    r.info("this list is a starting checklist, not legal advice; confirm with an accredited test lab")


def check_manufacturing(d: Device, r: StageResult) -> None:
    m = d.manufacturing
    qty = d.quantity
    if not m.get("assembly"):
        r.error("manufacturing.assembly missing: who builds the units (in-house, PCBA house, contract manufacturer)?")
    if d.boards and not m.get("pcb_fab"):
        r.error("manufacturing.pcb_fab missing: which board house")
    slowest = max((p.get("lead_time_weeks") or 0 for p in d.parts), default=0)
    schedule = d.requirements.get("schedule_weeks")
    if schedule and slowest and float(slowest) > float(schedule):
        r.error(f"slowest part lead time {slowest} weeks exceeds the {schedule}-week schedule")
    elif slowest:
        r.info(f"longest part lead time: {slowest} weeks")
    for mech in d.mechanical:
        proc = str(mech.get("process", "")).lower()
        if proc in ("fdm", "sla", "sls", "3d-print", "mjf") and qty > 300:
            r.warn(f"'{mech.get('id')}' is {proc} at {qty} units; quote urethane casting or injection molding")
        if proc in ("injection-molding", "injection") and qty < 1000:
            r.warn(f"'{mech.get('id')}' is injection molded at only {qty} units; tooling may cost more than the run")
    if not m.get("test_plan"):
        r.warn("manufacturing.test_plan missing: how is each unit tested before it ships?")


STAGES: list[tuple[str, str, Callable[[Device, StageResult], None]]] = [
    ("spec", "Requirements", check_spec),
    ("architecture", "Architecture and interfaces", check_architecture),
    ("power", "Power budget", check_power),
    ("parts", "Parts and BOM", check_parts),
    ("electronics", "Boards", check_electronics),
    ("mechanical", "Enclosure and mechanics", check_mechanical),
    ("firmware", "Firmware", check_firmware),
    ("compliance", "Certification", check_compliance),
    ("manufacturing", "Manufacturing and supply", check_manufacturing),
]
STAGE_NAMES = [s[0] for s in STAGES]


def run_stage(d: Device, name: str) -> StageResult:
    for key, title, fn in STAGES:
        if key == name:
            result = StageResult(key, title)
            try:
                fn(d, result)
            except Exception as exc:  # a malformed device.yaml should fail the gate, not crash
                result.error(f"check crashed: {type(exc).__name__}: {exc}")
            return result
    raise KeyError(name)


def run_all(d: Device) -> list[StageResult]:
    return [run_stage(d, name) for name in STAGE_NAMES]


def current_stage(results: list[StageResult]) -> StageResult | None:
    """First stage whose gate is not passed, or None when every gate passes."""
    return next((r for r in results if not r.passed), None)
