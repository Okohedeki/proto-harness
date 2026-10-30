"""`ph` command line."""

from __future__ import annotations

import argparse
import shutil
import sys
from importlib import resources
from pathlib import Path

from . import __version__, catalog, tools
from .build import build_board, generator
from .checks import ERROR, INFO, STAGE_NAMES, current_stage, run_all, run_stage
from .lock import update_lock, write_lock
from .model import DEVICE_FILE, LOCK_FILE, Device
from .report import bom_csv, render
from .sources import SOURCES, SourceError, available_sources

TAG = {ERROR: "[FAIL]", "warn": "[WARN]", INFO: "[info]"}


def _templates() -> Path:
    return Path(str(resources.files("protoharness") / "templates"))


def cmd_init(args: argparse.Namespace) -> int:
    dest = Path(args.dir)
    dest.mkdir(parents=True, exist_ok=True)
    device = dest / DEVICE_FILE
    if device.exists() and not args.force:
        print(f"{device} already exists (use --force to overwrite)")
        return 1
    tpl = _templates()
    text = (tpl / "device.yaml").read_text(encoding="utf-8")
    device.write_text(text.replace("{{name}}", args.name or dest.resolve().name), encoding="utf-8")
    shutil.copyfile(tpl / "CLAUDE.md", dest / "CLAUDE.md")
    if not (dest / ".gitignore").exists():
        shutil.copyfile(tpl / "gitignore", dest / ".gitignore")
    skills_dst = dest / ".claude" / "skills"
    shutil.copytree(tpl / "skills", skills_dst, dirs_exist_ok=True)
    for sub in ("hardware", "mechanical", "firmware", "docs"):
        (dest / sub).mkdir(exist_ok=True)
    print(f"Created {device}, CLAUDE.md and {len(list(skills_dst.iterdir()))} stage skills in .claude/skills")
    print("Next: open this folder in Claude Code and run /hw, or edit device.yaml and run `ph status`.")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"proto-harness {__version__} on {sys.platform}, Python {sys.version.split()[0]}\n")
    for t in tools.TOOLS:
        where = tools.find(t)
        print(f"{'[ok]  ' if where else '[--]  '}{t.key:<12} {t.purpose}")
        print(f"      {where if where else 'install: ' + t.install}")
    print("\nNone of these are required; missing tools just leave their checks unverified.")
    return 0


def _print_result(r) -> None:
    print(f"\n{'PASS' if r.passed else 'BLOCKED':<8} {r.title}")
    for f in r.findings:
        print(f"  {TAG[f.level]} {f.message}")


def cmd_check(args: argparse.Namespace) -> int:
    d = Device.load(args.dir)
    results = [run_stage(d, args.stage)] if args.stage else run_all(d)
    for r in results:
        _print_result(r)
    return 0 if all(r.passed for r in results) else 1


def cmd_status(args: argparse.Namespace) -> int:
    d = Device.load(args.dir)
    results = run_all(d)
    print(d.name)
    for r in results:
        errs = sum(f.level == ERROR for f in r.findings)
        print(f"  {'[x]' if r.passed else '[ ]'} {r.title:<28} {'' if r.passed else f'{errs} blocking'}")
    cur = current_stage(results)
    if cur is None:
        print("\nAll gates pass. Order prototypes, then re-run after every change.")
        return 0
    print(f"\nCurrent stage: {cur.stage}. Fix first:")
    for f in [f for f in cur.findings if f.level == ERROR][:5]:
        print(f"  - {f.message}")
    return 1


def cmd_report(args: argparse.Namespace) -> int:
    d = Device.load(args.dir)
    out = Path(args.out) if args.out else d.root / "REPORT.md"
    out.write_text(render(d, run_all(d)), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


def cmd_bom(args: argparse.Namespace) -> int:
    d = Device.load(args.dir)
    text = bom_csv(d)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    d = Device.load(args.dir)
    boards = [b for b in d.boards if not args.board or b.get("id") == args.board]
    if not boards:
        print("no matching boards in device.yaml")
        return 1
    ok = True
    for board in boards:
        res = build_board(d, board)
        ok &= res.ok
        print(f"\n{'OK' if res.ok else 'FAILED':<7} board '{res.board}' ({generator(d, board)})")
        for step in res.steps:
            print(f"  {'[ok]' if step.ok else '[FAIL]'} {step.name}")
            for line in step.detail.splitlines():
                print(f"         {line}")
    print("\nNext: `ph check --stage electronics`")
    return 0 if ok else 1


def cmd_parts(args: argparse.Namespace) -> int:
    d = Device.load(args.dir)
    wanted = [s.strip() for s in args.sources.split(",")] if args.sources else available_sources()
    unknown = [s for s in wanted if s not in SOURCES]
    if unknown:
        print(f"unknown source(s): {', '.join(unknown)}; choose from {', '.join(SOURCES)}", file=sys.stderr)
        return 2
    keyed = [s for s in ("digikey", "mouser") if s not in wanted]
    print(f"Sources: {', '.join(wanted)}" + (f"  (add keys to enable {', '.join(keyed)}; see README)" if keyed else ""))
    if "jlcparts" not in wanted and not catalog.available():
        print("Tip: `ph catalog update` adds the offline open catalog (exact matches, no key).")
    only = [p.strip() for p in args.only.split(",")] if args.only else None

    def show(pid: str, entry: dict) -> None:
        offers = entry["offers"]
        if offers:
            stock = sum(o["stock"] for o in offers)
            sellers = ", ".join(sorted({f"{o['supplier']} {o['sku']}" for o in offers}))
            print(f"  [ok]   {pid:<20} {entry['mpn']:<24} stock {stock:>9,}  {sellers}")
        else:
            why = "; ".join(f"{k}: {v}" for k, v in entry["errors"].items()) or "no exact match"
            print(f"  [--]   {pid:<20} {entry['mpn']:<24} not found ({why})")

    lock = update_lock(d, wanted, only, progress=show)
    if args.dry_run:
        print("Dry run: parts.lock.json not written")
    else:
        write_lock(d, lock)
        print(f"Wrote {d.root / LOCK_FILE}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    from .ui import serve
    serve(Path(args.dir), port=args.port, open_browser=not args.no_open)
    return 0


def cmd_catalog(args: argparse.Namespace) -> int:
    if args.action == "update":
        print(f"Downloading the open jlcparts catalog to {catalog.cache_dir()} (about 250 MB, 2 GB once unpacked)")
        meta = catalog.update(progress=lambda msg: print(f"  {msg}"))
        print(f"Catalog ready: {meta['parts']:,} parts. `ph parts` now uses it as the 'jlcparts' source.")
        return 0
    meta = catalog.info()
    if args.action == "info" or not args.text:
        if meta is None:
            print("No offline catalog. Run `ph catalog update` to download it.")
            return 1
        print(f"{meta['parts']:,} parts, {meta['age_days']:.1f} days old")
        print(meta["path"])
        return 0
    rows = catalog.search(" ".join(args.text), limit=args.limit, in_stock=not args.all)
    for r in rows:
        price = f"${r['price_breaks'][0][1]:.4f}" if r["price_breaks"] else "?"
        print(f"{r['lcsc']:<11} {r['mpn']:<26} {r['stock']:>9,} {price:>9}  {r['library']:<9} {r['package']:<18} "
              f"{r['description'][:60]}")
    if not rows:
        print("no matches")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ph", description="One place for a whole hardware device, gated stage by stage.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="start a device project with device.yaml and the stage skills")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--name")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    sub.add_parser("doctor", help="show which open-source checkers are installed").set_defaults(fn=cmd_doctor)

    s = sub.add_parser("check", help="run the stage gates and print every finding")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--stage", choices=STAGE_NAMES)
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("status", help="show which gates pass and what blocks the current stage")
    s.add_argument("dir", nargs="?", default=".")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("report", help="write REPORT.md: the whole device on one page")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("build", help="build boards from circuit code and export fab files from layouts")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--board", help="only this board id")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("parts", help="look up live stock, prices and lifecycle; writes parts.lock.json")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--sources", help=f"comma list from {', '.join(SOURCES)} (default: every source with keys set)")
    s.add_argument("--only", help="comma list of part ids to refresh")
    s.add_argument("--dry-run", action="store_true", help="print results without writing the lock file")
    s.set_defaults(fn=cmd_parts)

    s = sub.add_parser("bom", help="export the BOM as CSV, priced at the build quantity")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_bom)

    s = sub.add_parser("ui", help="live dashboard in the browser; redraws whenever a project file changes")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    s.set_defaults(fn=cmd_ui)

    s = sub.add_parser("catalog", help="offline open parts catalog: update it, or search it for parts and alternates")
    s.add_argument("action", choices=["update", "info", "search"])
    s.add_argument("text", nargs="*", help="search: a part-number prefix, or words from the description")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--all", action="store_true", help="include parts with no stock")
    s.set_defaults(fn=cmd_catalog)

    args = p.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # part descriptions hold symbols a Windows console can't encode
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    try:
        return args.fn(args)
    except SourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
