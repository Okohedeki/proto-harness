from datetime import datetime, timedelta, timezone

from protoharness.checks import ERROR, WARN, run_stage
from protoharness.lock import update_lock
from protoharness.model import Device, bom_lines
from protoharness.sources import (Offer, SourceError, normalize_lifecycle, parse_digikey, parse_lcsc,
                                  parse_lcsc_prices, parse_mouser)


def msgs(result, level):
    return [f.message for f in result.findings if f.level == level]


def test_lcsc_price_string():
    assert parse_lcsc_prices("1-9:1.5,10-99:1.2,100-:0.9") == [(1, 1.5), (10, 1.2), (100, 0.9)]


def test_lcsc_keeps_only_exact_matches():
    payload = {"components": [
        {"lcsc": 1, "mfr": "UNRELATED-PART", "stock": 5, "price": "1-:1"},
        {"lcsc": 2, "mfr": "ABC-123", "stock": 50, "price": "1-:0.5"},
    ]}
    assert [o.sku for o in parse_lcsc(payload, "abc123", None)] == ["C2"]
    assert [o.sku for o in parse_lcsc(payload, "whatever", "c1")] == ["C1"]


def test_digikey_parse():
    payload = {"Product": {
        "ManufacturerProductNumber": "ABC-123", "QuantityAvailable": 900, "ManufacturerLeadWeeks": "12",
        "ProductStatus": {"Status": "Not For New Designs"}, "ProductUrl": "u",
        "ProductVariations": [{"DigiKeyProductNumber": "1-ABC", "QuantityAvailableforPackageType": 800,
                               "MinimumOrderQuantity": 1,
                               "StandardPricing": [{"BreakQuantity": 10, "UnitPrice": 0.8}, {"BreakQuantity": 1, "UnitPrice": 1.0}]}],
    }}
    [o] = parse_digikey(payload, "ABC-123")
    assert (o.stock, o.lifecycle, o.lead_time_weeks, o.price_breaks) == (800, "nrnd", 12.0, [(1, 1.0), (10, 0.8)])
    assert parse_digikey(payload, "OTHER") == []


def test_mouser_parse():
    payload = {"SearchResults": {"Parts": [{
        "ManufacturerPartNumber": "ABC-123", "MouserPartNumber": "595-ABC", "AvailabilityInStock": "1200",
        "LeadTime": "42 Days", "LifecycleStatus": "End of Life", "Min": "1",
        "PriceBreaks": [{"Quantity": 1, "Price": "$1,234.50", "Currency": "USD"}, {"Quantity": 100, "Price": "$0.90", "Currency": "USD"}],
    }]}}
    [o] = parse_mouser(payload, "ABC-123")
    assert (o.stock, o.lifecycle, o.lead_time_weeks, o.price_breaks) == (1200, "eol", 6.0, [(1, 1234.5), (100, 0.9)])


def test_lifecycle_words():
    assert normalize_lifecycle("Obsolete") == "obsolete"
    assert normalize_lifecycle("Last Time Buy") == "last-time-buy"
    assert normalize_lifecycle("Active") == "active"
    assert normalize_lifecycle(None) is None


def device(**part):
    base = {"id": "p", "mpn": "ABC-123", "qty": 2, "lifecycle": "active"}
    return Device({"requirements": {"quantity": 100, "target_unit_cost_usd": 100}, "parts": [{**base, **part}]}, ".")


def fake(*offers, fail=None):
    def fetch(part):
        if fail:
            raise SourceError(fail)
        return list(offers)
    return fetch


def offer(stock, breaks, supplier="Shop", lifecycle=None):
    return Offer("x", supplier, "SKU", "ABC-123", stock, breaks, lifecycle=lifecycle)


def test_live_price_wins_and_picks_cheapest_in_stock():
    d = device(unit_cost_usd=5)
    update_lock(d, ["a", "b"], fetchers={
        "a": fake(offer(1000, [(1, 1.0), (100, 0.5)], "A")),
        "b": fake(offer(10, [(1, 0.1)], "B")),  # cheaper but cannot cover 200 units
    })
    [row] = bom_lines(d)
    assert row["unit_cost_usd"] == 0.5 and row["price_source"].startswith("A ")
    assert set(row["suppliers"]) == {"A", "B"}
    assert run_stage(d, "parts").passed


def test_out_of_stock_blocks():
    d = device()
    update_lock(d, ["a"], fetchers={"a": fake(offer(0, [(1, 1.0)]))})
    assert any("out of stock" in m for m in msgs(run_stage(d, "parts"), ERROR))


def test_short_stock_warns():
    d = device()
    update_lock(d, ["a"], fetchers={"a": fake(offer(50, [(1, 1.0)]))})
    r = run_stage(d, "parts")
    assert r.passed and any("build needs 200" in m for m in msgs(r, WARN))


def test_live_lifecycle_overrides_typed():
    d = device()
    update_lock(d, ["a"], fetchers={"a": fake(offer(1000, [(1, 1.0)], lifecycle="obsolete"))})
    assert any("lifecycle is obsolete" in m for m in msgs(run_stage(d, "parts"), ERROR))


def test_source_error_is_recorded_not_raised():
    d = device(unit_cost_usd=1, suppliers=["s"])
    lock = update_lock(d, ["a"], fetchers={"a": fake(fail="HTTP 401")})
    assert lock["parts"]["p"]["errors"] == {"a": "HTTP 401"}
    assert any("not found" in m and "HTTP 401" in m for m in msgs(run_stage(d, "parts"), WARN))


def test_mpn_change_invalidates_lock():
    d = device(unit_cost_usd=1, suppliers=["s"])
    update_lock(d, ["a"], fetchers={"a": fake(offer(1000, [(1, 0.2)]))})
    d.data["parts"][0]["mpn"] = "NEW-PART"
    assert bom_lines(d)[0]["price_source"] == "typed"
    assert any("not checked live" in m for m in msgs(run_stage(d, "parts"), WARN))


def test_stale_lock_warns():
    d = device()
    update_lock(d, ["a"], fetchers={"a": fake(offer(1000, [(1, 1.0)]))})
    old = datetime.now(timezone.utc) - timedelta(days=90)
    d.lock["parts"]["p"]["looked_up"] = old.isoformat()
    assert any("days old" in m for m in msgs(run_stage(d, "parts"), WARN))


def test_tbd_and_no_lookup_parts_are_skipped():
    d = Device({"parts": [{"id": "a", "mpn": "TBD"}, {"id": "b", "mpn": "X", "no_lookup": True}]}, ".")
    called = []
    update_lock(d, ["a"], fetchers={"a": lambda p: called.append(p) or []})
    assert called == []
