"""Live part data from distributors: stock, price breaks, lifecycle, lead time.

Sources:
  lcsc     keyless. Queries a community mirror of the JLCPCB/LCSC catalog. Exact by LCSC number
           (`lcsc: C8734` on the part); by MPN it keeps only exact manufacturer-number matches.
  digikey  needs DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET (free at developer.digikey.com).
  mouser   needs MOUSER_API_KEY (free from your Mouser account, Search API).
  jlcparts keyless and offline. The open jlcparts copy of the whole JLCPCB/LCSC catalog, downloaded
           once with `ph catalog update` (see catalog.py). Exact matches only.

Keys come from environment variables only and are never written to project files.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

TIMEOUT = 20
USER_AGENT = "proto-harness/0.1 (+https://github.com/Okohedeki/proto-harness)"


@dataclass
class Offer:
    source: str
    supplier: str
    sku: str
    mpn: str
    stock: int
    price_breaks: list[tuple[int, float]] = field(default_factory=list)
    currency: str = "USD"
    lifecycle: str | None = None
    lead_time_weeks: float | None = None
    moq: int | None = None
    url: str | None = None

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["price_breaks"] = [list(b) for b in self.price_breaks]
        return d


class SourceError(Exception):
    pass


def _http(url: str, data: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                                          **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise SourceError(f"HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SourceError(str(getattr(exc, "reason", exc))) from exc


def normalize_lifecycle(text: str | None) -> str | None:
    if not text:
        return None
    t = text.lower()
    if "obsolete" in t or "discontinued" in t:
        return "obsolete"
    if "end of life" in t or t == "eol":
        return "eol"
    if "last time" in t:
        return "last-time-buy"
    if "not recommended" in t or "not for new" in t or "nrnd" in t:
        return "nrnd"
    if "active" in t or "new product" in t or "new at" in t:
        return "active"
    return t


def _same_mpn(a: str, b: str) -> bool:
    return re.sub(r"[\s-]", "", a).upper() == re.sub(r"[\s-]", "", b).upper()


# --- LCSC (keyless community mirror) --------------------------------------------------------

LCSC_API = "https://jlcsearch.tscircuit.com/components/list.json"


def parse_lcsc_prices(text: str) -> list[tuple[int, float]]:
    """'1-9:1.69,10-29:1.44,30-:1.28' -> [(1, 1.69), (10, 1.44), (30, 1.28)]"""
    out = []
    for chunk in str(text or "").split(","):
        if ":" not in chunk:
            continue
        rng, price = chunk.split(":", 1)
        try:
            out.append((int(rng.split("-")[0]), float(price)))
        except ValueError:
            continue
    return sorted(out)


def parse_lcsc(payload: Any, mpn: str, lcsc_id: str | None) -> list[Offer]:
    offers = []
    for c in (payload or {}).get("components") or []:
        code = f"C{c.get('lcsc')}"
        if lcsc_id and code.upper() != lcsc_id.upper():
            continue
        if not lcsc_id and not _same_mpn(str(c.get("mfr", "")), mpn):
            continue
        offers.append(Offer(
            source="lcsc", supplier="LCSC", sku=code, mpn=str(c.get("mfr", "")),
            stock=int(c.get("stock") or 0), price_breaks=parse_lcsc_prices(c.get("price", "")),
            url=f"https://www.lcsc.com/product-detail/{code}.html"))
    return offers


def lookup_lcsc(part: dict[str, Any]) -> list[Offer]:
    lcsc_id = str(part["lcsc"]) if part.get("lcsc") else None
    query = lcsc_id or str(part.get("mpn", ""))
    payload = _http(f"{LCSC_API}?{urllib.parse.urlencode({'search': query, 'full': 'true', 'limit': 20})}")
    return parse_lcsc(payload, str(part.get("mpn", "")), lcsc_id)


# --- DigiKey (API v4, client credentials) ---------------------------------------------------

_digikey_token: str | None = None


def _digikey_auth() -> tuple[str, str]:
    global _digikey_token
    cid, secret = os.environ.get("DIGIKEY_CLIENT_ID"), os.environ.get("DIGIKEY_CLIENT_SECRET")
    if not cid or not secret:
        raise SourceError("set DIGIKEY_CLIENT_ID and DIGIKEY_CLIENT_SECRET")
    if _digikey_token is None:
        body = urllib.parse.urlencode({"client_id": cid, "client_secret": secret,
                                       "grant_type": "client_credentials"}).encode()
        tok = _http("https://api.digikey.com/v1/oauth2/token", data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        _digikey_token = (tok or {}).get("access_token")
        if not _digikey_token:
            raise SourceError("DigiKey did not return an access token")
    return cid, _digikey_token


def parse_digikey(payload: Any, mpn: str) -> list[Offer]:
    product = (payload or {}).get("Product") or {}
    if not product or not _same_mpn(str(product.get("ManufacturerProductNumber", "")), mpn):
        return []
    status = (product.get("ProductStatus") or {}).get("Status")
    if product.get("EndOfLife"):
        status = "end of life"
    if product.get("Discontinued"):
        status = "discontinued"
    lead = product.get("ManufacturerLeadWeeks")
    try:
        lead = float(lead) if lead not in (None, "") else None
    except (TypeError, ValueError):
        lead = None
    offers = []
    for var in product.get("ProductVariations") or [{}]:
        breaks = sorted((int(p["BreakQuantity"]), float(p["UnitPrice"]))
                        for p in var.get("StandardPricing") or [] if "BreakQuantity" in p)
        offers.append(Offer(
            source="digikey", supplier="DigiKey", sku=str(var.get("DigiKeyProductNumber", "")),
            mpn=str(product.get("ManufacturerProductNumber", "")),
            stock=int(var.get("QuantityAvailableforPackageType", product.get("QuantityAvailable", 0)) or 0),
            price_breaks=breaks, lifecycle=normalize_lifecycle(status), lead_time_weeks=lead,
            moq=var.get("MinimumOrderQuantity"), url=product.get("ProductUrl")))
    return offers


def lookup_digikey(part: dict[str, Any]) -> list[Offer]:
    cid, token = _digikey_auth()
    mpn = str(part.get("mpn", ""))
    sku = str(part.get("digikey") or mpn)
    payload = _http(f"https://api.digikey.com/products/v4/search/{urllib.parse.quote(sku, safe='')}/productdetails",
                    headers={"Authorization": f"Bearer {token}", "X-DIGIKEY-Client-Id": cid,
                             "X-DIGIKEY-Locale-Currency": "USD"})
    return parse_digikey(payload, mpn)


# --- Mouser (Search API v1) ------------------------------------------------------------------


def _money(text: Any) -> float | None:
    m = re.search(r"[\d.,]+", str(text or ""))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_mouser(payload: Any, mpn: str) -> list[Offer]:
    offers = []
    for p in ((payload or {}).get("SearchResults") or {}).get("Parts") or []:
        if not _same_mpn(str(p.get("ManufacturerPartNumber", "")), mpn):
            continue
        breaks, currency = [], "USD"
        for b in p.get("PriceBreaks") or []:
            price = _money(b.get("Price"))
            if price is not None:
                breaks.append((int(b.get("Quantity") or 1), price))
                currency = b.get("Currency") or currency
        lead = re.search(r"\d+", str(p.get("LeadTime") or ""))
        stock = p.get("AvailabilityInStock") or re.sub(r"\D", "", str(p.get("Availability") or "")) or 0
        offers.append(Offer(
            source="mouser", supplier="Mouser", sku=str(p.get("MouserPartNumber", "")),
            mpn=str(p.get("ManufacturerPartNumber", "")), stock=int(stock), price_breaks=sorted(breaks),
            currency=currency, lifecycle=normalize_lifecycle(p.get("LifecycleStatus") or "active"),
            lead_time_weeks=round(int(lead.group(0)) / 7, 1) if lead else None,
            moq=int(p["Min"]) if str(p.get("Min", "")).isdigit() else None, url=p.get("ProductDetailUrl")))
    return offers


def lookup_mouser(part: dict[str, Any]) -> list[Offer]:
    key = os.environ.get("MOUSER_API_KEY")
    if not key:
        raise SourceError("set MOUSER_API_KEY")
    mpn = str(part.get("mpn", ""))
    body = json.dumps({"SearchByPartRequest": {"mouserPartNumber": str(part.get("mouser") or mpn),
                                               "partSearchOptions": "Exact"}}).encode()
    payload = _http(f"https://api.mouser.com/api/v1/search/partnumber?apiKey={urllib.parse.quote(key)}",
                    data=body, headers={"Content-Type": "application/json"})
    if payload and payload.get("Errors"):
        raise SourceError("; ".join(str(e.get("Message", e)) for e in payload["Errors"]))
    return parse_mouser(payload, mpn)


def lookup_jlcparts(part: dict[str, Any]) -> list[Offer]:
    from . import catalog
    return catalog.lookup(part)


SOURCES = {"lcsc": lookup_lcsc, "jlcparts": lookup_jlcparts, "digikey": lookup_digikey, "mouser": lookup_mouser}


def available_sources() -> list[str]:
    """LCSC always; the offline catalog once downloaded; keyed sources only when their keys are set."""
    from . import catalog
    out = ["lcsc"] + (["jlcparts"] if catalog.available() else [])
    if os.environ.get("DIGIKEY_CLIENT_ID") and os.environ.get("DIGIKEY_CLIENT_SECRET"):
        out.append("digikey")
    if os.environ.get("MOUSER_API_KEY"):
        out.append("mouser")
    return out
