"""Offline catalog (split-zip reading, lookups, search) and the `ph ui` server."""

import io
import json
import shutil
import sqlite3
import struct
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from protoharness import catalog, ui
from protoharness.sources import SourceError

ROOT = Path(__file__).resolve().parents[1]
SOIL = ROOT / "examples" / "soil-sensor"

SCHEMA = """CREATE TABLE jlc_components (lcsc INTEGER PRIMARY KEY, mfr TEXT, manufacturer TEXT, package TEXT,
  library_type TEXT, stock INTEGER, price TEXT, description TEXT, datasheet TEXT, category TEXT)"""
ROWS = [
    (1001, "ABC123-X", "Maker A", "SOT-23-5", "base", 5000, "1-9:0.10,10-:0.08", "3.3V 300mA LDO regulator", "", "Power"),
    (1002, "ABC123-Y", "Maker A", "SOT-23-5", "expand", 0, "1-:0.12", "3.3V 300mA LDO regulator", "", "Power"),
    (1003, "ABC999", "Maker B", "SOIC-8", "expand", 40, "1-:0.50", "temperature sensor I2C", "", "Sensors"),
]


@pytest.fixture()
def fake_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("PH_CACHE_DIR", str(tmp_path))
    with sqlite3.connect(tmp_path / catalog.DB_NAME) as con:
        con.execute(SCHEMA)
        con.executemany("INSERT INTO jlc_components VALUES (?,?,?,?,?,?,?,?,?,?)", ROWS)
    (tmp_path / catalog.META_NAME).write_text(json.dumps({"downloaded_at": time.time(), "parts": len(ROWS)}))
    return tmp_path


def test_cache_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PH_CACHE_DIR", str(tmp_path / "c"))
    assert catalog.cache_dir() == tmp_path / "c"


def test_lookup_exact_by_mpn_and_code(fake_catalog):
    offers = catalog.lookup({"mpn": "abc123-x"})
    assert [(o.sku, o.stock, o.price_breaks[0]) for o in offers] == [("C1001", 5000, (1, 0.10))]
    assert offers[0].supplier == "JLCPCB"
    assert [o.mpn for o in catalog.lookup({"mpn": "ignored", "lcsc": "C1003"})] == ["ABC999"]
    assert catalog.lookup({"mpn": "ABC123"}) == []  # a prefix is not a match


def test_search_prefix_and_words(fake_catalog):
    assert [r["mpn"] for r in catalog.search("ABC123")] == ["ABC123-X"]  # in stock only
    assert {r["mpn"] for r in catalog.search("ABC123", in_stock=False)} == {"ABC123-X", "ABC123-Y"}
    hit = catalog.search("sensor I2C")
    assert [r["mpn"] for r in hit] == ["ABC999"] and hit[0]["library"] == "extended"


def test_missing_or_stale_catalog(fake_catalog):
    meta = fake_catalog / catalog.META_NAME
    meta.write_text(json.dumps({"downloaded_at": time.time() - 90 * 86400, "parts": 3}))
    with pytest.raises(SourceError, match="days old"):
        catalog.lookup({"mpn": "ABC123-X"})
    meta.unlink()
    assert not catalog.available()
    with pytest.raises(SourceError, match="catalog update"):
        catalog.lookup({"mpn": "ABC123-X"})


def test_extract_split_zip(tmp_path):
    payload = bytes(range(256)) * 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("cache.sqlite3", payload)
    data = buf.getvalue()
    eocd = data.rfind(b"PK\x05\x06")
    cd_size, cd_offset = struct.unpack("<II", data[eocd + 12:eocd + 20])
    # Three volumes: the member spans the first two, the central directory sits in the last one,
    # with its offset counted from the start of that volume as in a real split archive.
    tail = bytearray(data[cd_offset:])
    end = len(tail) - (len(data) - eocd)
    tail[end + 4:end + 8] = struct.pack("<HH", 2, 2)
    tail[end + 16:end + 20] = struct.pack("<I", 0)
    pieces = [data[:3000], data[3000:cd_offset], bytes(tail)]
    paths = []
    for i, piece in enumerate(pieces):
        p = tmp_path / f"part{i}"
        p.write_bytes(piece)
        paths.append(p)
    out = tmp_path / "out.sqlite3"
    catalog.extract(paths, out)
    assert out.read_bytes() == payload


def test_snapshot_of_example():
    snap = ui.snapshot(SOIL)
    assert snap["ok"] and snap["name"] == "Soil Sensor"
    assert [s["stage"] for s in snap["stages"]][0] == "spec" and len(snap["stages"]) == 9
    assert snap["current"] == "power"
    assert snap["power"]["sources"][0]["life_days"] < 180
    assert any(p["id"] == "temp-sensor" for p in snap["parts"])
    json.dumps(snap, default=str)


def test_snapshot_reports_broken_yaml(tmp_path):
    (tmp_path / "device.yaml").write_text("name: [unclosed\n")
    snap = ui.snapshot(tmp_path)
    assert not snap["ok"] and snap["error"]


def test_signature_changes_with_files(tmp_path):
    shutil.copy(SOIL / "device.yaml", tmp_path / "device.yaml")
    before = ui.signature(tmp_path)
    (tmp_path / "hardware").mkdir()
    (tmp_path / "hardware" / "board.py").write_text("# circuit\n")
    assert ui.signature(tmp_path) != before
    (tmp_path / "hardware" / "fab").mkdir()
    after = ui.signature(tmp_path)
    (tmp_path / "hardware" / "fab" / "out.gbr").write_text("x")
    assert ui.signature(tmp_path) == after  # build outputs don't trigger redraws


@pytest.fixture()
def server():
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ui.make_handler(SOIL, ui.Job()))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _get(url, **headers):
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30)


def test_server_page_and_state(server):
    assert b"proto-harness" in _get(server + "/").read()
    state = json.loads(_get(server + "/api/state").read())
    assert state["ok"] and state["name"] == "Soil Sensor"


def test_server_refuses_foreign_host_and_bare_posts(server):
    with pytest.raises(urllib.error.HTTPError) as err:
        _get(server + "/api/state", Host="attacker.example")
    assert err.value.code == 403
    req = urllib.request.Request(server + "/api/run/parts", data=b"", method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req, timeout=10)
    assert err.value.code == 403
