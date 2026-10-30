"""`ph ui`: a local live dashboard for one device.

A standard-library HTTP server on 127.0.0.1. It serves one page, a JSON snapshot of the whole
device (gates, findings, architecture, power, BOM, certification, boards) and a server-sent event
stream that fires whenever a project file changes, so the page redraws while you or an agent edit
device.yaml, refresh parts or rebuild boards. Two buttons run `ph parts` and `ph build` in the
background and stream their output.
"""

from __future__ import annotations

import contextlib
import io
import json
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__, build, catalog, tools
from .checks import ERROR, WARN, current_stage, run_all
from .compliance import required_certifications
from .model import DEVICE_FILE, LOCK_FILE, Device, age_days, bom_lines, bom_total
from .netlist import load_netlist
from .power import PowerTree

WATCH_DIRS = ("hardware", "mechanical", "firmware", "docs")
SKIP_DIRS = {"fab", ".git", "__pycache__", "node_modules", ".venv"}
POLL_SECONDS = 0.7


def signature(root: Path) -> tuple:
    """Cheap fingerprint of every file the dashboard depends on."""
    files = [root / DEVICE_FILE, root / LOCK_FILE]
    for sub in WATCH_DIRS:
        base = root / sub
        if base.is_dir():
            files += [p for p in base.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(base).parts)]
    out = []
    for f in files:
        with contextlib.suppress(OSError):
            st = f.stat()
            out.append((str(f), st.st_mtime_ns, st.st_size))
    return tuple(sorted(out))


def _power(d: Device) -> dict[str, Any]:
    tree = PowerTree(d)
    out: dict[str, Any] = {"rails": [], "sources": [], "error": None}
    try:
        out["rails"] = [vars(r) for r in tree.rail_summary()]
        for sid, src in tree.sources.items():
            peak, avg = tree.source_draw(sid)
            out["sources"].append({"id": sid, "kind": src.get("kind"), "voltage_v": src.get("voltage_v"),
                                   "capacity_mah": src.get("capacity_mah"), "peak_ma": peak, "avg_ma": avg,
                                   "life_days": tree.battery_life_days(sid)})
    except (ValueError, KeyError, TypeError) as exc:
        out["error"] = str(exc)
    return out


def _parts(d: Device) -> list[dict[str, Any]]:
    rows = []
    for part, line in zip(d.parts, bom_lines(d)):
        entry = d.live(part)
        offers = (entry or {}).get("offers") or []
        line.update({
            "live": entry is not None,
            "stock": sum(int(o.get("stock") or 0) for o in offers) if entry else None,
            "need": int(float(part.get("qty", 1) or 1) * d.quantity),
            "age_days": age_days(entry) if entry else None,
            "offers": [{k: o.get(k) for k in ("supplier", "sku", "stock", "url")} for o in offers],
            "placeholder": bool(part.get("no_lookup")),
        })
        rows.append(line)
    return rows


def _boards(d: Device) -> list[dict[str, Any]]:
    out = []
    for board in d.boards:
        info: dict[str, Any] = {"id": board.get("id"), "generator": build.generator(d, board),
                                "source": board.get("source"), "layout": [p.name for p in build.layout_files(d, board)]}
        path = build.netlist_path(d, board)
        if path and path.exists():
            with contextlib.suppress(Exception):
                nl = load_netlist(path)
                info.update(components=len(nl.components), nets=len(nl.nets),
                            netlist_age_s=time.time() - path.stat().st_mtime)
        out.append(info)
    return out


def snapshot(root: Path, job: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        d = Device.load(root)
    except Exception as exc:  # show a broken device.yaml in the page instead of failing the request
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "root": str(root), "job": job}
    results = run_all(d)
    cur = current_stage(results)
    req = d.requirements
    return {
        "ok": True,
        "version": __version__,
        "root": str(root.resolve()),
        "name": d.name,
        "summary": d.data.get("summary"),
        "quantity": d.quantity,
        "requirements": {k: req.get(k) for k in ("battery_life_days", "target_unit_cost_usd", "markets", "size_mm")},
        "current": cur.stage if cur else None,
        "stages": [{"stage": r.stage, "title": r.title, "passed": r.passed,
                    "errors": sum(f.level == ERROR for f in r.findings),
                    "warnings": sum(f.level == WARN for f in r.findings),
                    "findings": [vars(f) for f in r.findings]} for r in results],
        "blocks": d.blocks,
        "interfaces": d.interfaces,
        "power": {**_power(d), "spec": {k: d.power.get(k) for k in ("sources", "rails", "loads")}},
        "parts": _parts(d),
        "cost": bom_total(d),
        "certs": [{"name": n, "why": w, "plan": (d.compliance.get("plans") or {}).get(n)}
                  for n, w in required_certifications(d)],
        "boards": _boards(d),
        "tools": [{"key": t.key, "found": bool(tools.find(t))} for t in tools.TOOLS],
        "catalog": catalog.info(),
        "job": job,
    }


class Job:
    """Runs one `ph` command at a time in a thread and keeps its output for the page."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state: dict[str, Any] | None = None
        self.version = 0

    def start(self, name: str, argv: list[str]) -> bool:
        with self.lock:
            if self.state and self.state["running"]:
                return False
            self.state = {"name": name, "running": True, "ok": None, "log": ""}
            self.version += 1
        threading.Thread(target=self._run, args=(argv,), daemon=True).start()
        return True

    def _run(self, argv: list[str]) -> None:
        from .cli import main  # late import: cli imports this module

        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                code = main(argv)
        except Exception:
            buf.write(traceback.format_exc())
            code = 1
        with self.lock:
            self.state.update(running=False, ok=code == 0, log=buf.getvalue()[-6000:])
            self.version += 1


def make_handler(root: Path, job: Job):
    page = Path(str(resources.files("protoharness") / "templates" / "ui" / "index.html"))

    class Handler(BaseHTTPRequestHandler):
        server_version = "proto-harness"

        def log_message(self, *args) -> None:  # keep the terminal quiet
            pass

        def _local(self) -> bool:
            # Refuse other Host names so a web page elsewhere can't reach this server by DNS rebinding.
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost", "[::1]")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, code: int = 200) -> None:
            self._send(code, json.dumps(data, default=str).encode("utf-8"), "application/json")

        def do_GET(self) -> None:
            if not self._local():
                return self._send(403, b"forbidden", "text/plain")
            url = urlparse(self.path)
            if url.path == "/":
                return self._send(200, page.read_bytes(), "text/html; charset=utf-8")
            if url.path == "/api/state":
                return self._json(snapshot(root, job.state))
            if url.path == "/api/catalog":
                q = parse_qs(url.query).get("q", [""])[0]
                try:
                    return self._json({"results": catalog.search(q, limit=12)})
                except Exception as exc:
                    return self._json({"error": str(exc)}, 400)
            if url.path == "/api/events":
                return self._events()
            self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            # The custom header blocks cross-site form posts: browsers can't add it without CORS.
            if not self._local() or self.headers.get("X-PH") != "1":
                return self._send(403, b"forbidden", "text/plain")
            commands = {"/api/run/parts": ["parts", str(root)], "/api/run/build": ["build", str(root)],
                        "/api/run/report": ["report", str(root)]}
            argv = commands.get(urlparse(self.path).path)
            if not argv:
                return self._send(404, b"not found", "text/plain")
            started = job.start(argv[0], argv)
            self._json({"started": started}, 202 if started else 409)

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last_sig, last_job, last_beat = signature(root), job.version, time.time()
            try:
                while True:
                    time.sleep(POLL_SECONDS)
                    sig = signature(root)
                    if sig != last_sig or job.version != last_job:
                        last_sig, last_job = sig, job.version
                        self.wfile.write(b"event: change\ndata: {}\n\n")
                        self.wfile.flush()
                    elif time.time() - last_beat > 15:
                        self.wfile.write(b": keep-alive\n\n")
                        self.wfile.flush()
                        last_beat = time.time()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return

    return Handler


def serve(root: Path, port: int = 8787, open_browser: bool = True) -> None:
    root = Path(root)
    if not (root / DEVICE_FILE).exists():
        raise FileNotFoundError(f"no {DEVICE_FILE} in {root.resolve()}")
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(root, Job()))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"proto-harness dashboard for {root.resolve()}\n  {url}\nWatching for changes. Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()

