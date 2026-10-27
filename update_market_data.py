import csv, io, json, os, time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

API_KEY = os.environ.get("FINNHUB_API_KEY")
if not API_KEY:
    raise SystemExit("Missing FINNHUB_API_KEY GitHub Actions secret")

BASE = "https://finnhub.io/api/v1"
HEADERS = {"X-Finnhub-Token": API_KEY}
DATA_DIR = Path("data")
OUT = DATA_DIR / "latest.json"
UNIVERSE = DATA_DIR / "symbols.json"
STATE = DATA_DIR / "state.json"
# 25 symbols × (quote + metric) = up to 50 calls per run, under the usual 60/min free limit.
BATCH_SIZE = int(os.environ.get("FINNHUB_BATCH_SIZE", "25"))
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def get_json(url, params=None):
    for attempt in range(3):
        r = SESSION.get(url, params=params, timeout=25)
        if r.status_code == 429:
            time.sleep(2 + attempt * 2)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Finnhub rate limit persisted for {url}")


def load_universe():
    if UNIVERSE.exists():
        try:
            arr = json.loads(UNIVERSE.read_text(encoding="utf-8"))
            if isinstance(arr, list) and arr:
                return arr
        except Exception:
            pass
    # Build a broad US-listed symbol universe from Nasdaq Trader symbol directories.
    # The data source is a public listing directory, not a Finnhub quote endpoint.
    items = {}
    urls = [
        ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "Symbol", "Security Name", "ETF"),
        ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "ACT Symbol", "Security Name", "ETF"),
    ]
    for url, symbol_col, name_col, etf_col in urls:
        raw = requests.get(url, timeout=30)
        raw.raise_for_status()
        reader = csv.DictReader(io.StringIO(raw.text), delimiter="|")
        for row in reader:
            symbol = (row.get(symbol_col) or "").strip()
            name = (row.get(name_col) or "").strip()
            if not symbol or symbol in {"File Creation Time", "Symbol", "ACT Symbol"} or symbol.startswith("$"):
                continue
            if row.get("Test Issue", "N").strip().upper() == "Y":
                continue
            if not re_symbol_ok(symbol):
                continue
            items[symbol] = {"symbol": symbol, "name": name, "is_etf": (row.get(etf_col) or "N").strip().upper() == "Y"}
    arr = sorted(items.values(), key=lambda x: x["symbol"])
    if not arr:
        raise RuntimeError("Could not build US symbol universe from Nasdaq Trader directories")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UNIVERSE.write_text(json.dumps(arr, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return arr


def re_symbol_ok(symbol):
    # Permit common class-share punctuation but skip malformed directory footer rows.
    return len(symbol) <= 16 and any(ch.isalnum() for ch in symbol) and all(ch.isalnum() or ch in ".-$^" for ch in symbol)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def get_metric(symbol):
    try:
        result = get_json(f"{BASE}/stock/metric", {"symbol": symbol, "metric": "all"})
        metrics = result.get("metric") or {}
        # Finnhub reports this average-volume metric in millions of shares.
        raw = metrics.get("10DayAverageTradingVolume")
        if raw is None:
            raw = metrics.get("3MonthAverageTradingVolume")
            label = "3-month average volume"
        else:
            label = "10-day average volume"
        if raw is None:
            return None, None
        return float(raw) * 1_000_000, label
    except requests.HTTPError as e:
        # A 403 usually means the endpoint is not included in the user's Finnhub plan.
        if e.response is not None and e.response.status_code == 403:
            print(f"Metric endpoint not available for {symbol}; volume/liquidity proxy omitted")
            return None, None
        print(f"Metric failed for {symbol}: {e}")
        return None, None
    except Exception as e:
        print(f"Metric failed for {symbol}: {e}")
        return None, None


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    universe = load_universe()
    old = load_json(OUT, {})
    by_symbol = {x.get("symbol"): x for x in old.get("stocks", []) if x.get("symbol")}
    state = load_json(STATE, {"cursor": 0})
    cursor = int(state.get("cursor", 0)) % len(universe)
    batch = [universe[(cursor + i) % len(universe)] for i in range(min(BATCH_SIZE, len(universe)))]
    updated = 0
    errors = 0

    # Avoid spending API quota outside regular US market hours; still allow a manual run.
    now_ny = datetime.now(ZoneInfo("America/New_York"))
    is_regular_session = now_ny.weekday() < 5 and ((now_ny.hour > 9 or (now_ny.hour == 9 and now_ny.minute >= 30)) and now_ny.hour < 16)
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    if not is_regular_session and not manual:
        print("Outside regular US session; preserving last quote snapshot.")
        return

    for item in batch:
        symbol = item["symbol"]
        try:
            q = get_json(f"{BASE}/quote", {"symbol": symbol})
            price = q.get("c")
            if not price or float(price) <= 0 or not q.get("t"):
                continue
            avg_volume, volume_basis = get_metric(symbol)
            prev_close = q.get("pc")
            change_pct = q.get("dp")
            if change_pct is None and prev_close:
                change_pct = (float(price) / float(prev_close) - 1) * 100
            row = {
                "symbol": symbol,
                "name": item.get("name", ""),
                "price": round(float(price), 4),
                "day_volume": None,
                "avg_volume_10d": round(avg_volume, 2) if avg_volume is not None else None,
                "dollar_volume": round(float(price) * avg_volume, 2) if avg_volume is not None else None,
                "change_pct": round(float(change_pct), 3) if change_pct is not None else None,
                "bar_time": datetime.fromtimestamp(int(q["t"]), timezone.utc).isoformat(),
                "volume_basis": volume_basis,
                "quote_timestamp": int(q["t"]),
                "is_etf": item.get("is_etf", False),
            }
            by_symbol[symbol] = row
            updated += 1
        except Exception as e:
            print(f"Quote failed for {symbol}: {e}")
            errors += 1
        time.sleep(0.15)

    stocks = sorted(by_symbol.values(), key=lambda x: (x.get("dollar_volume") is not None, x.get("dollar_volume") or 0), reverse=True)
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": "Finnhub API (quotes + average-volume metric where plan permits)",
        "volume_basis": "Estimated average dollar liquidity = latest quote × 10-day average volume (fallback 3-month average). Not current intraday traded value.",
        "feed_note": f"Updated {updated} symbols in this run; {len(stocks)} symbols cached. Free-tier limits mean the universe is refreshed in rotating batches. Current intraday volume is not provided by /quote. If Finnhub denies /stock/metric, liquidity values remain blank.",
        "universe_count": len(universe),
        "cached_count": len(stocks),
        "updated_this_run": updated,
        "errors_this_run": errors,
        "stocks": stocks,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    STATE.write_text(json.dumps({"cursor": (cursor + len(batch)) % len(universe), "last_batch_start": cursor, "last_batch_count": len(batch)}, separators=(",", ":")), encoding="utf-8")
    print(f"Updated {updated}; cached {len(stocks)} symbols; next cursor {(cursor + len(batch)) % len(universe)}")


if __name__ == "__main__":
    import re
    main()
