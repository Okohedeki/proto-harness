"""Offline parts catalog: the open jlcparts database of the whole JLCPCB/LCSC library.

The jlcparts project (https://github.com/yaqwsx/jlcparts, MIT) publishes the full catalog every
day as a split zip of one SQLite file: about 3 million parts with stock, price breaks, package,
category and datasheet links. `ph catalog update` downloads it once (about 250 MB, 2 GB on disk)
into the user cache directory; lookups then run locally, need no key and match part numbers
exactly, which online keyword search cannot do reliably.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from .sources import USER_AGENT, Offer, SourceError, parse_lcsc_prices

BASE_URL = "https://yaqwsx.github.io/jlcparts/data/"
DB_NAME = "cache.sqlite3"
META_NAME = "catalog.json"
MAX_AGE_DAYS = 14
LIBRARY = {"base": "basic", "expand": "extended", "preferred": "preferred"}


def cache_dir() -> Path:
    """Per-user cache folder on Windows, macOS and Linux. PH_CACHE_DIR overrides it."""
    if os.environ.get("PH_CACHE_DIR"):
        return Path(os.environ["PH_CACHE_DIR"])
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "proto-harness" / "jlcparts"


def db_path() -> Path:
    return cache_dir() / DB_NAME


def info() -> dict[str, Any] | None:
    meta = cache_dir() / META_NAME
    if not db_path().exists() or not meta.exists():
        return None
    data = json.loads(meta.read_text(encoding="utf-8"))
    data["age_days"] = (time.time() - data.get("downloaded_at", 0)) / 86400
    data["path"] = str(db_path())
    return data


def available() -> bool:
    return info() is not None


# --- download -------------------------------------------------------------------------------


class _Joined(io.RawIOBase):
    """Reads several files as one stream, so a split zip can be opened as a single archive."""

    def __init__(self, paths: list[Path]):
        self._files = [open(p, "rb") for p in paths]
        self._sizes = [p.stat().st_size for p in paths]
        self._pos = 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = 0) -> int:
        base = {0: 0, 1: self._pos, 2: sum(self._sizes)}[whence]
        self._pos = base + offset
        return self._pos

    def readinto(self, buf) -> int:
        want, done, pos = len(buf), 0, self._pos
        for f, size in zip(self._files, self._sizes):
            if pos >= size:
                pos -= size
                continue
            f.seek(pos)
            chunk = f.read(min(want - done, size - pos))
            buf[done:done + len(chunk)] = chunk
            done += len(chunk)
            pos = 0
            if done >= want:
                break
        self._pos += done
        return done

    def close(self) -> None:
        for f in self._files:
            f.close()
        super().close()


def _fetch(url: str, dest: Path, progress: Callable[[str], None]) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
            shutil.copyfileobj(resp, out, 1 << 20)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise SourceError(f"{url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SourceError(f"{url}: {getattr(exc, 'reason', exc)}") from exc
    progress(f"downloaded {dest.name} ({dest.stat().st_size / 1e6:.0f} MB)")
    return True


def extract(parts: list[Path], dest: Path) -> None:
    """Extract the SQLite file from a split zip (cache.z01, cache.z02, ..., cache.zip)."""
    sizes = [p.stat().st_size for p in parts]
    with zipfile.ZipFile(io.BufferedReader(_Joined(parts), 1 << 20)) as zf:
        member = next(i for i in zf.infolist() if i.filename.endswith(".sqlite3"))
        # zipfile assumes one file and shifts every offset by the size of the earlier volumes;
        # put the member back at its real position in the joined stream.
        member.header_offset += sum(sizes[:member.volume]) - sum(sizes[:-1])
        with zf.open(member) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out, 1 << 22)


def update(progress: Callable[[str], None] = lambda _: None) -> dict[str, Any]:
    folder = cache_dir()
    folder.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    try:
        for n in range(1, 100):
            p = folder / f"cache.z{n:02d}"
            if not _fetch(f"{BASE_URL}{p.name}", p, progress):
                break
            parts.append(p)
        last = folder / "cache.zip"
        if not _fetch(f"{BASE_URL}{last.name}", last, progress):
            raise SourceError("catalog archive not found; the jlcparts data layout may have changed")
        parts.append(last)
        progress("extracting (about 2 GB)")
        tmp = folder / (DB_NAME + ".tmp")
        extract(parts, tmp)
    finally:
        for p in parts:
            p.unlink(missing_ok=True)
    progress("indexing part numbers")
    with sqlite3.connect(tmp) as con:
        con.execute("CREATE INDEX IF NOT EXISTS ph_mfr ON jlc_components (mfr COLLATE NOCASE)")
        count = con.execute("SELECT count(*) FROM jlc_components").fetchone()[0]
    os.replace(tmp, db_path())
    meta = {"source": BASE_URL, "downloaded_at": time.time(), "parts": count}
    (folder / META_NAME).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


# --- lookups --------------------------------------------------------------------------------

_COLUMNS = "lcsc, mfr, manufacturer, package, library_type, stock, price, description, datasheet, category"


def _connect() -> sqlite3.Connection:
    meta = info()
    if meta is None:
        raise SourceError("no offline catalog; run `ph catalog update` first")
    if meta["age_days"] > MAX_AGE_DAYS:
        raise SourceError(f"offline catalog is {meta['age_days']:.0f} days old; run `ph catalog update`")
    con = sqlite3.connect(f"file:{db_path().as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _offer(row: sqlite3.Row) -> Offer:
    code = f"C{row['lcsc']}"
    return Offer(source="jlcparts", supplier="JLCPCB", sku=code, mpn=row["mfr"], stock=int(row["stock"] or 0),
                 price_breaks=parse_lcsc_prices(row["price"]),
                 url=f"https://jlcpcb.com/partdetail/{code}")


def lookup(part: dict[str, Any]) -> list[Offer]:
    """Exact match by LCSC number when the part has one, else by manufacturer part number."""
    with _connect() as con:
        if part.get("lcsc"):
            code = str(part["lcsc"]).upper().lstrip("C")
            rows = con.execute(f"SELECT {_COLUMNS} FROM jlc_components WHERE lcsc = ?",
                               (int(code) if code.isdigit() else -1,)).fetchall()
        else:
            rows = con.execute(f"SELECT {_COLUMNS} FROM jlc_components WHERE mfr = ? COLLATE NOCASE",
                               (str(part.get("mpn", "")),)).fetchall()
    return [_offer(r) for r in rows]


def search(text: str, limit: int = 20, in_stock: bool = True) -> list[dict[str, Any]]:
    """Parts whose number starts with `text`, or whose description holds every word of it."""
    words = [w for w in text.split() if w]
    if not words:
        return []
    with _connect() as con:
        if len(words) == 1:
            sql = f"SELECT {_COLUMNS} FROM jlc_components WHERE mfr LIKE ? COLLATE NOCASE"
            args: list[Any] = [words[0] + "%"]
        else:
            sql = f"SELECT {_COLUMNS} FROM jlc_components WHERE " + " AND ".join(["description LIKE ?"] * len(words))
            args = [f"%{w}%" for w in words]
        if in_stock:
            sql += " AND stock > 0"
        rows = con.execute(sql + " ORDER BY stock DESC LIMIT ?", (*args, limit)).fetchall()
    return [{"lcsc": f"C{r['lcsc']}", "mpn": r["mfr"], "manufacturer": r["manufacturer"], "package": r["package"],
             "library": LIBRARY.get(r["library_type"], r["library_type"]), "stock": r["stock"],
             "price_breaks": parse_lcsc_prices(r["price"]), "description": r["description"],
             "category": r["category"], "datasheet": r["datasheet"]} for r in rows]
