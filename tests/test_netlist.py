import os
import shutil
from pathlib import Path

import pytest

from protoharness.checks import ERROR, WARN, run_stage
from protoharness.cli import main
from protoharness.model import Device
from protoharness.netlist import Component, Net, Netlist, Node, check_bom_agreement, check_netlist, load_netlist, parse_sexpr, rail_key

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

NETLIST = """(export (version "D")
  (components
    (comp (ref "U1") (value "SENSOR") (footprint "Pkg:DFN4")
      (fields (field (name "MPN") "ABC-123") (field (name "Datasheet"))))
    (comp (ref "R1") (value "4k7") (footprint "R_0402"))
    (comp (ref "C1") (value "100n") (footprint ""))
  )
  (nets
    (net (code "1") (name "+3V3") (node (ref "U1") (pin "1") (pinfunction "VDD")) (node (ref "R1") (pin "1")) (node (ref "C1") (pin "1")))
    (net (code "2") (name "GND") (node (ref "U1") (pin "2")) (node (ref "C1") (pin "2")))
    (net (code "3") (name "I2C_SDA") (node (ref "U1") (pin "3")) (node (ref "R1") (pin "2")))
    (net (code "4") (name "I2C_SCL") (node (ref "U1") (pin "4")))
  ))"""


def findings(device, nl):
    out = []
    check_netlist(device, "b", nl, lambda level, msg: out.append((level, msg)))
    return out


def dev(**extra):
    return Device({"power": {"rails": [{"id": "3v3"}, {"id": "1v8"}]}, "boards": [{"id": "b"}], **extra}, ".")


@pytest.fixture
def nl(tmp_path):
    p = tmp_path / "x.net"
    p.write_text(NETLIST, encoding="utf-8")
    return load_netlist(p)


def test_sexpr_handles_quotes_and_nesting():
    assert parse_sexpr('(a "b c" (d "e\\"f"))') == [["a", "b c", ["d", 'e"f']]]
    with pytest.raises(ValueError):
        parse_sexpr("(a (b)")


def test_load(nl):
    assert set(nl.components) == {"U1", "R1", "C1"}
    assert nl.components["U1"].mpn == "ABC-123"
    assert nl.nets[0].nodes[0].function == "VDD"


@pytest.mark.parametrize("name,key", [("+3V3", "3v3"), ("3.3V", "3v3"), ("VCC_3V3", "3v3"), ("+5V", "5"), ("5v", "5"), ("VBUS", "vbus")])
def test_rail_key(name, key):
    assert rail_key(name) == key


def test_netlist_checks(nl):
    found = findings(dev(), nl)
    msgs = {m for _, m in found}
    assert (ERROR, "board 'b': C1 (100n) has no footprint; it cannot be laid out or assembled") in found
    assert any("net I2C_SCL only touches U1" in m for m in msgs)
    assert any("I2C net I2C_SCL has no pull-up" in m for m in msgs)
    assert not any("I2C net I2C_SDA" in m for m in msgs)       # R1 pulls SDA to +3V3
    assert any("rail '1v8'" in m for m in msgs)                # rail with no net
    assert not any("decoupling" in m for m in msgs)            # C1 sits on +3V3 with U1


def test_missing_decoupling_and_ground():
    nl = Netlist({"U1": Component("U1", "X", "fp")},
                 [Net("+3V3", [Node("U1", "1")]), Net("SIG", [Node("U1", "2")])])
    msgs = [m for _, m in findings(dev(), nl)]
    assert any("no capacitor on +3V3" in m for m in msgs)
    assert any("no ground net" in m for m in msgs)


def test_bom_agreement(nl):
    d = dev(parts=[{"id": "s", "mpn": "ABC-123", "category": "sensor"},
                   {"id": "m", "mpn": "MISSING-1", "category": "ic"},
                   {"id": "x", "mpn": "OFF-1", "category": "module", "off_board": True}])
    nl.components["U2"] = Component("U2", "Y", "fp", {"MPN": "UNKNOWN-9"})
    out = []
    check_bom_agreement(d, {"b": nl}, lambda level, msg: out.append(msg))
    assert any("MISSING-1" in m for m in out)
    assert any("UNKNOWN-9" in m for m in out)
    assert not any("ABC-123" in m or "OFF-1" in m for m in out)


def test_unbuilt_code_board_blocks(tmp_path):
    (tmp_path / "board.py").write_text("", encoding="utf-8")
    d = Device({"boards": [{"id": "b", "source": "board.py", "size_mm": [10, 10], "layers": 2}]}, tmp_path)
    assert any("not built yet" in f.message for f in run_stage(d, "electronics").findings if f.level == ERROR)


def test_stale_netlist_warns(tmp_path):
    (tmp_path / "board.net").write_text(NETLIST, encoding="utf-8")
    (tmp_path / "board.py").write_text("", encoding="utf-8")
    old = (tmp_path / "board.net").stat().st_mtime - 100
    os.utime(tmp_path / "board.net", (old, old))
    d = Device({"boards": [{"id": "b", "source": "board.py", "size_mm": [10, 10], "layers": 2}]}, tmp_path)
    assert any("older than" in f.message for f in run_stage(d, "electronics").findings if f.level == WARN)


def test_example_board_builds_with_skidl(tmp_path):
    pytest.importorskip("skidl")
    dst = tmp_path / "soil"
    shutil.copytree(EXAMPLES / "soil-sensor", dst)
    (dst / "hardware" / "main.net").unlink(missing_ok=True)
    assert main(["build", str(dst)]) == 0
    r = run_stage(Device.load(dst), "electronics")
    assert r.passed
    assert not [f.message for f in r.findings if f.level == WARN and "layout" not in f.message]
