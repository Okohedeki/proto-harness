from pathlib import Path

import pytest

from protoharness.checks import ERROR, current_stage, run_all, run_stage
from protoharness.cli import main
from protoharness.compliance import required_certifications
from protoharness.model import Device, bom_total, price_at
from protoharness.power import PowerTree

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def errors(result):
    return [f.message for f in result.findings if f.level == ERROR]


def battery_device(regulator="ldo", capacity=1000, life=None):
    return Device({
        "requirements": {"battery_life_days": life},
        "blocks": [{"id": "mcu", "kind": "compute"}],
        "power": {
            "sources": [{"id": "b", "kind": "battery", "voltage_v": 3.7, "min_voltage_v": 3.0, "capacity_mah": capacity}],
            "rails": [{"id": "3v3", "from": "b", "voltage_v": 3.3, "regulator": regulator, "max_current_ma": 500}],
            "loads": [{"block": "mcu", "rail": "3v3", "active_ma": 100, "sleep_ma": 0.01, "duty": 0.01}],
        },
    }, ".")


def test_ldo_dropout_is_caught():
    r = run_stage(battery_device("ldo"), "power")
    assert any("drops out" in m for m in errors(r))


def test_buck_boost_avoids_dropout():
    assert run_stage(battery_device("buck-boost"), "power").passed


def test_battery_life_math():
    tree = PowerTree(battery_device("ldo"))
    _, avg = tree.source_draw("b")
    assert avg == pytest.approx(100 * 0.01 + 0.01 * 0.99)
    assert tree.battery_life_days("b") == pytest.approx(1000 * 0.8 / avg / 24)


def test_battery_life_requirement():
    r = run_stage(battery_device("buck-boost", capacity=100, life=365), "power")
    assert any("battery life" in m for m in errors(r))


def test_rail_over_limit():
    d = battery_device("buck-boost")
    d.data["power"]["loads"][0]["peak_ma"] = 900
    assert any("exceeds regulator limit" in m for m in errors(run_stage(d, "power")))


def test_switching_rail_draws_less_from_higher_source():
    d = Device({"power": {
        "sources": [{"id": "s", "voltage_v": 12}],
        "rails": [{"id": "r", "from": "s", "voltage_v": 3.3, "regulator": "buck", "efficiency": 0.9}],
        "loads": [{"block": "x", "rail": "r", "active_ma": 100}],
    }}, ".")
    peak, _ = PowerTree(d).source_draw("s")
    assert peak == pytest.approx(100 * 3.3 / (12 * 0.9))


def test_logic_level_mismatch():
    d = Device({"blocks": [{"id": "a", "kind": "compute", "io_v": 3.3}, {"id": "b", "kind": "sensor", "io_v": 5}],
                "interfaces": [{"from": "a", "to": "b", "kind": "i2c"}]}, ".")
    assert not run_stage(d, "architecture").passed
    d.data["interfaces"][0]["level_shift"] = True
    assert run_stage(d, "architecture").passed


def test_price_breaks():
    part = {"unit_cost_usd": {1: 2.0, 100: 1.5, 1000: 1.0}}
    assert price_at(part, 1) == 2.0
    assert price_at(part, 250) == 1.5
    assert price_at(part, 5000) == 1.0


def test_bom_over_target_blocks():
    d = Device({"requirements": {"quantity": 10, "target_unit_cost_usd": 1},
                "parts": [{"id": "p", "mpn": "X", "qty": 2, "unit_cost_usd": 1, "suppliers": ["a", "b"], "lifecycle": "active"}]}, ".")
    assert bom_total(d) == 2
    assert not run_stage(d, "parts").passed


def test_fit_with_rotation():
    d = Device({"requirements": {}, "parts": [{"id": "cell", "dims_mm": [50, 10, 30]}],
                "mechanical": [{"id": "box", "process": "fdm", "material": "PLA", "inner_mm": [12, 52, 32], "holds": ["cell"]}]}, ".")
    assert run_stage(d, "mechanical").passed
    d.data["mechanical"][0]["inner_mm"] = [12, 40, 32]
    assert not run_stage(d, "mechanical").passed


def test_compliance_follows_markets_and_features():
    d = Device({"requirements": {"markets": ["US", "EU"]}, "boards": [{"id": "m"}],
                "parts": [{"id": "r", "features": ["radio-wifi"], "certified": True}],
                "power": {"sources": [{"id": "b", "kind": "battery", "chemistry": "li-ion"}]}}, ".")
    names = [n for n, _ in required_certifications(d)]
    assert "FCC modular grant reuse" in names
    assert "Radio equipment rules (EU, RED/RER)" in names
    assert "UN 38.3" in names
    assert "FCC Part 15 Subpart C" not in names


def test_malformed_input_fails_gate_instead_of_crashing():
    d = Device({"blocks": [{"id": "a", "kind": "compute"}],
                "power": {"sources": [{"id": "s"}], "rails": [{"id": "r", "from": "s", "max_current_ma": "lots"}],
                          "loads": [{"block": "a", "rail": "r", "active_ma": 1}]}}, ".")
    assert any("must be a number" in m for m in errors(run_stage(d, "power")))
    d.data["power"]["loads"][0]["active_ma"] = "some"
    assert not run_stage(d, "power").passed


@pytest.mark.parametrize("name", ["soil-sensor", "pan-tilt-mount"])
def test_examples_load_and_report(name, tmp_path):
    d = Device.load(EXAMPLES / name)
    results = run_all(d)
    assert current_stage(results) is not None
    assert main(["report", str(EXAMPLES / name), "-o", str(tmp_path / "r.md")]) == 0
    assert "## Gates" in (tmp_path / "r.md").read_text(encoding="utf-8")


def test_init_creates_project(tmp_path):
    assert main(["init", str(tmp_path / "dev"), "--name", "Thing"]) == 0
    assert (tmp_path / "dev" / ".claude" / "skills" / "hw" / "SKILL.md").exists()
    d = Device.load(tmp_path / "dev")
    assert d.name == "Thing"
    assert current_stage(run_all(d)).stage == "spec"
    assert main(["init", str(tmp_path / "dev")]) == 1
