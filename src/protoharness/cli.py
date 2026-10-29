"""`ph` command line."""

from __future__ import annotations

import argparse
import shutil
import sys
from importlib import resources
from pathlib import Path

from . import __version__, tools
from .checks import ERROR, INFO, STAGE_NAMES, current_stage, run_all, run_stage
from .model import DEVICE_FILE, Device
from .report import bom_csv, render

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

    s = sub.add_parser("bom", help="export the BOM as CSV, priced at the build quantity")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_bom)

    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
