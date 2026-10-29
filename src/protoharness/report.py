"""Renders the whole device as one Markdown page: gates, architecture, power, BOM, certification."""

from __future__ import annotations

import csv
import io
import re

from .checks import ERROR, WARN, StageResult, current_stage
from .compliance import required_certifications
from .model import Device, bom_lines, bom_total
from .power import PowerTree

MARK = {True: "pass", False: "BLOCKED"}


def _node(text: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9_]", "_", str(text))


def mermaid(d: Device) -> str:
    lines = ["flowchart LR"]
    for src in (d.power.get("sources") or []):
        lines.append(f'  {_node(src.get("id"))}[/"{src.get("id")}<br/><small>{src.get("kind", "")}</small>"/]')
    for b in d.blocks:
        label = f"{b.get('id')}<br/><small>{b.get('kind', '')}</small>"
        lines.append(f'  {_node(b.get("id"))}["{label}"]')
    for itf in d.interfaces:
        lines.append(f'  {_node(itf.get("from"))} -- {itf.get("kind", "")} --- {_node(itf.get("to"))}')
    for rail in (d.power.get("rails") or []):
        lines.append(f'  {_node(rail.get("from"))} -. "{rail.get("voltage_v")} V" .-> {_node(rail.get("id"))}(("{rail.get("id")}"))')
    for load in (d.power.get("loads") or []):
        lines.append(f"  {_node(load.get('rail'))} -.-> {_node(load.get('block'))}")
    return "\n".join(lines)


def render(d: Device, results: list[StageResult]) -> str:
    out: list[str] = [f"# {d.name}", ""]
    if d.data.get("summary"):
        out += [str(d.data["summary"]).strip(), ""]
    cur = current_stage(results)
    out.append(f"**Current stage:** {cur.title if cur else 'all gates pass'}  ")
    out.append(f"**Build quantity:** {d.quantity}  ")
    target = d.requirements.get("target_unit_cost_usd")
    out.append(f"**Parts cost:** ${bom_total(d):.2f}/unit" + (f" (target ${float(target):.2f})" if target else ""))
    out += ["", "## Gates", "", "| Stage | Gate | Errors | Warnings |", "|---|---|---|---|"]
    for r in results:
        errs = sum(f.level == ERROR for f in r.findings)
        warns = sum(f.level == WARN for f in r.findings)
        out.append(f"| {r.title} | {MARK[r.passed]} | {errs} | {warns} |")

    if d.blocks:
        out += ["", "## Architecture", "", "```mermaid", mermaid(d), "```"]

    tree = PowerTree(d)
    if tree.rails or tree.sources:
        out += ["", "## Power", "", "| Rail | Volts | Peak mA | Avg mA | Limit mA | Fed from |", "|---|---|---|---|---|---|"]
        try:
            for row in tree.rail_summary():
                limit = f"{row.max_current_ma:.0f}" if row.max_current_ma is not None else "?"
                out.append(f"| {row.rail} | {row.voltage_v} | {row.peak_ma:.1f} | {row.avg_ma:.3f} | {limit} | {row.parent} |")
            for sid, src in tree.sources.items():
                peak, avg = tree.source_draw(sid)
                life = tree.battery_life_days(sid)
                extra = f", about {life:.0f} days" if life else ""
                out.append(f"\nSource **{sid}** ({src.get('kind')}): peak {peak:.0f} mA, average {avg:.3f} mA{extra}")
        except (ValueError, KeyError) as exc:
            out.append(f"\nPower tree could not be computed: {exc}")

    if d.parts:
        out += ["", f"## Bill of materials (priced at {d.quantity} units)", "",
                "| Part | MPN | Category | Qty | Unit $ | Line $ | Suppliers | Lifecycle | Lead wks |",
                "|---|---|---|---|---|---|---|---|---|"]
        for row in bom_lines(d):
            unit = f"{row['unit_cost_usd']:.3f}" if row["unit_cost_usd"] is not None else "?"
            line = f"{row['line_cost_usd']:.2f}" if row["line_cost_usd"] is not None else "?"
            out.append(f"| {row['id']} | {row['mpn']} | {row['category']} | {row['qty']:g} | {unit} | {line} | "
                       f"{', '.join(row['suppliers'])} | {row['lifecycle']} | {row['lead_time_weeks'] or ''} |")
        out.append(f"| **Total** | | | | | **{bom_total(d):.2f}** | | | |")

    certs = required_certifications(d)
    if certs:
        plans = {str(k).lower(): v for k, v in (d.compliance.get("plans") or {}).items()}
        out += ["", "## Certification checklist", "",
                "_Starting checklist, not legal advice. Confirm with an accredited test lab._", "",
                "| Item | Why | Plan |", "|---|---|---|"]
        for name, why in certs:
            out.append(f"| {name} | {why} | {plans.get(name.lower(), '**none yet**')} |")

    out += ["", "## Findings", ""]
    for r in results:
        if not r.findings:
            continue
        out.append(f"### {r.title}")
        for f in r.findings:
            out.append(f"- **{f.level}**: {f.message}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def bom_csv(d: Device) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["id", "mpn", "category", "qty_per_unit", "unit_cost_usd", "line_cost_usd",
                "suppliers", "lifecycle", "lead_time_weeks"])
    for r in bom_lines(d):
        w.writerow([r["id"], r["mpn"], r["category"], r["qty"], r["unit_cost_usd"], r["line_cost_usd"],
                    ";".join(r["suppliers"]), r["lifecycle"], r["lead_time_weeks"]])
    return buf.getvalue()
