#!/usr/bin/env python3
"""
Fetches current market + crypto data and renders the dashboard HTML.
Run daily via GitHub Actions (see .github/workflows/daily-report.yml).

Env vars required:
  ALPHA_VANTAGE_KEY  - free key from https://www.alphavantage.co/support/#api-key

NOTE on rate limits: Alpha Vantage's free tier allows 25 requests/day and
5 requests/minute. This script makes 18 GLOBAL_QUOTE calls (3 indices + 15
stocks) plus 3 more calls (SECTOR, TOP_GAINERS_LOSERS, TREASURY_YIELD) = 21
requests/day, all spaced 12s apart to stay under the per-minute limit. That
leaves only ~4 requests of daily headroom -- avoid extra manual re-runs on
top of the automatic daily run, and watch the 25/day ceiling if you add more.
"""
import os
import sys
import time
from datetime import datetime, timezone

import requests

ALPHA_VANTAGE_KEY = os.environ.get("ALPHA_VANTAGE_KEY", "")
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "template.html")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "docs")
OUTPUT_PATH = os.path.join(OUTPUT_DIR, "index.html")

INDICES = [
    ("SPY", "S&P 500"),
    ("QQQ", "Nasdaq"),
    ("DIA", "Dow Jones"),
]

STOCKS = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("GOOGL", "Alphabet"),
    ("AMZN", "Amazon"),
    ("NVDA", "Nvidia"),
    ("META", "Meta"),
    ("TSLA", "Tesla"),
    ("JPM", "JPMorgan"),
    ("V", "Visa"),
    ("JNJ", "Johnson & Johnson"),
    ("WMT", "Walmart"),
    ("XOM", "Exxon Mobil"),
    ("UNH", "UnitedHealth"),
    ("PG", "Procter & Gamble"),
    ("HD", "Home Depot"),
]

# CoinGecko ids -> (display name, symbol)
CRYPTO = [
    ("bitcoin", "Bitcoin", "BTC"),
    ("ethereum", "Ethereum", "ETH"),
    ("tether", "Tether", "USDT"),
    ("binancecoin", "BNB", "BNB"),
    ("solana", "Solana", "SOL"),
    ("ripple", "XRP", "XRP"),
    ("usd-coin", "USD Coin", "USDC"),
    ("dogecoin", "Dogecoin", "DOGE"),
    ("cardano", "Cardano", "ADA"),
    ("tron", "TRON", "TRX"),
    ("avalanche-2", "Avalanche", "AVAX"),
    ("chainlink", "Chainlink", "LINK"),
    ("the-open-network", "Toncoin", "TON"),
    ("polkadot", "Polkadot", "DOT"),
    ("litecoin", "Litecoin", "LTC"),
]


def fmt_money(n, decimals=2):
    return f"${n:,.{decimals}f}"


def fmt_pct(n):
    sign = "▲" if n >= 0 else "▼"
    return f"{sign} {abs(n):.2f}%"


def cls_for(n):
    return "up" if n >= 0 else "down"


def fmt_big(n):
    """Formats a large dollar figure as e.g. $2.31T / $89.4B / $412.0M."""
    n = float(n)
    if n >= 1e12:
        return f"${n / 1e12:.2f}T"
    if n >= 1e9:
        return f"${n / 1e9:.1f}B"
    if n >= 1e6:
        return f"${n / 1e6:.1f}M"
    return fmt_money(n)


def fmt_range(low, high, decimals=2):
    return f"{fmt_money(low, decimals)} – {fmt_money(high, decimals)}"


def get_alpha_vantage_quote(symbol):
    """Returns (price, pct_change, high, low) for a ticker via Alpha Vantage GLOBAL_QUOTE."""
    if not ALPHA_VANTAGE_KEY:
        raise RuntimeError("ALPHA_VANTAGE_KEY is not set")
    url = "https://www.alphavantage.co/query"
    params = {"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": ALPHA_VANTAGE_KEY}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json().get("Global Quote", {})
    price = float(data["05. price"])
    pct_raw = data.get("10. change percent", "0%").replace("%", "")
    pct = float(pct_raw)
    high = float(data.get("03. high", price))
    low = float(data.get("04. low", price))
    return price, pct, high, low


def get_crypto_data():
    """Returns (dict: id -> market data, dominance_dict, global_data) using CoinGecko's
    richer /coins/markets endpoint (one batched call) plus /global for aggregate stats."""
    ids = ",".join(c[0] for c in CRYPTO)
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={
            "vs_currency": "usd",
            "ids": ids,
            "order": "market_cap_desc",
            "price_change_percentage": "24h",
            "sparkline": "false",
        },
        timeout=20,
    )
    r.raise_for_status()
    rows = r.json()
    by_id = {row["id"]: row for row in rows}

    r2 = requests.get("https://api.coingecko.com/api/v3/global", timeout=20)
    r2.raise_for_status()
    global_data = r2.json()["data"]

    return by_id, global_data


def get_fear_greed():
    """Returns (value:int, label:str)."""
    r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=20)
    r.raise_for_status()
    d = r.json()["data"][0]
    return int(d["value"]), d["value_classification"]


SECTOR_NAMES = {
    "Information Technology": "Technology",
    "Health Care": "Health Care",
    "Financials": "Financials",
    "Real Estate": "Real Estate",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Communication Services": "Communication Svcs",
    "Energy": "Energy",
    "Industrials": "Industrials",
    "Materials": "Materials",
    "Utilities": "Utilities",
}


def get_sector_performance():
    """Returns list of (sector_name, pct_change:float) sorted best-to-worst, via
    Alpha Vantage SECTOR (one call, covers all 11 GICS sectors' real-time performance)."""
    url = "https://www.alphavantage.co/query"
    params = {"function": "SECTOR", "apikey": ALPHA_VANTAGE_KEY}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    rank = data.get("Rank A: Real-Time Performance", {}) or data.get("Rank B: 1 Day Performance", {})
    out = []
    for raw_name, pct_str in rank.items():
        name = SECTOR_NAMES.get(raw_name, raw_name)
        try:
            pct = float(str(pct_str).replace("%", ""))
        except ValueError:
            continue
        out.append((name, pct))
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def get_top_movers():
    """Returns (gainers, losers, most_active), each a list of up to 5 dicts with
    ticker/price/change_percentage/volume, via Alpha Vantage TOP_GAINERS_LOSERS
    (one call, real market-wide data -- not limited to our watchlist)."""
    url = "https://www.alphavantage.co/query"
    params = {"function": "TOP_GAINERS_LOSERS", "apikey": ALPHA_VANTAGE_KEY}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return (
        data.get("top_gainers", [])[:5],
        data.get("top_losers", [])[:5],
        data.get("most_actively_traded", [])[:5],
    )


def get_treasury_yield():
    """Returns (value:float, date:str) for the most recent 10-year Treasury yield,
    via Alpha Vantage TREASURY_YIELD (one call, key macro/rate indicator)."""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TREASURY_YIELD",
        "interval": "monthly",
        "maturity": "10year",
        "apikey": ALPHA_VANTAGE_KEY,
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    rows = r.json().get("data", [])
    if not rows:
        return None, None
    latest = rows[0]
    return float(latest["value"]), latest["date"]


def cycle_read_text(fng_value, btc_chg):
    trend = "climbing" if btc_chg >= 0 else "pulling back"
    if fng_value <= 24:
        return (
            f"Sentiment is in Extreme Fear while BTC is {trend} — historically these "
            "zones have preceded local bottoms, but timing a turn from sentiment alone "
            "is unreliable. Watch for Fear &amp; Greed climbing back above 40 as an early signal."
        )
    if fng_value <= 44:
        return (
            f"Fear-dominant sentiment with BTC {trend}. Consistent with a risk-off or "
            "early-recovery phase rather than a confirmed bull run."
        )
    if fng_value <= 55:
        return (
            f"Sentiment is roughly neutral with BTC {trend} — no strong directional "
            "signal from crowd psychology right now."
        )
    if fng_value <= 75:
        return (
            f"Greed-dominant sentiment with BTC {trend}, typical of a mid-cycle "
            "bull phase. Watch for overheating if this pushes toward Extreme Greed."
        )
    return (
        f"Extreme Greed with BTC {trend} — these zones have historically coincided "
        "with local tops. Not a timing signal on its own, but worth watching for a "
        "cooldown in sentiment."
    )


def session_note(sp_chg, nasdaq_chg, dow_chg, stocks_up, breadth_total=15):
    ups = sum(1 for c in (sp_chg, nasdaq_chg, dow_chg) if c > 0)
    breadth_desc = (
        f"Under the hood, {stocks_up} of the {breadth_total} individual stocks on the "
        "watchlist traded higher, "
        + (
            "a healthy sign that gains were broad rather than concentrated in a couple of names."
            if stocks_up >= breadth_total * 0.6
            else "suggesting today's index-level move was driven by a narrower group of large-cap names rather than the market as a whole."
            if stocks_up <= breadth_total * 0.4
            else "a fairly even split between advancers and decliners."
        )
    )
    if ups == 3:
        headline = "All three major indices closed higher, a broad-based risk-on session."
    elif ups == 0:
        headline = "All three major indices closed lower, a broad-based risk-off session."
    else:
        headline = "The major indices diverged today, with some up and others down — a mixed, less directional session."
    return f"{headline} {breadth_desc}"


def fng_angle(value):
    return round((value * 1.8) - 90, 1)


def tile_html(symbol, name, price, chg, money_decimals=2):
    return (
        '<div class="tile">'
        f'<div class="tile-top"><span class="tile-sym">{symbol}</span>'
        f'<span class="chg {cls_for(chg)}">{fmt_pct(chg)}</span></div>'
        f'<div class="tile-name">{name}</div>'
        f'<div class="tile-price mono">{fmt_money(price, money_decimals)}</div>'
        "</div>"
    )


def mover_line(label, symbol, chg):
    return (
        f'<div class="mover-item"><span class="mover-label">{label}</span> '
        f'<span class="mover-sym">{symbol}</span> '
        f'<span class="chg {cls_for(chg)}">{fmt_pct(chg)}</span></div>'
    )


def sector_bar_html(name, pct, max_abs):
    max_abs = max(max_abs, 0.5)
    width = min(abs(pct) / max_abs * 100, 100)
    side = "pos" if pct >= 0 else "neg"
    return (
        '<div class="sector-row">'
        f'<div class="sector-name">{name}</div>'
        f'<div class="sector-bar-track"><div class="sector-bar {side}" style="width:{width:.1f}%"></div></div>'
        f'<div class="chg {cls_for(pct)}">{fmt_pct(pct)}</div>'
        "</div>"
    )


def market_row_html(item, show_volume=False):
    ticker = item.get("ticker", "?")
    try:
        price = float(item.get("price", 0))
    except (TypeError, ValueError):
        price = 0.0
    try:
        chg_pct = float(str(item.get("change_percentage", "0%")).replace("%", ""))
    except (TypeError, ValueError):
        chg_pct = 0.0
    extra = ""
    if show_volume:
        try:
            vol = int(float(item.get("volume", 0)))
            extra = f'<span class="mv-vol">{vol:,} vol</span>'
        except (TypeError, ValueError):
            pass
    return (
        '<div class="mv-row">'
        f'<span class="mv-sym">{ticker}</span>'
        f'<span class="mv-price mono">{fmt_money(price)}</span>'
        f'{extra}'
        f'<span class="chg {cls_for(chg_pct)}">{fmt_pct(chg_pct)}</span>'
        "</div>"
    )


def main():
    now = datetime.now(timezone.utc).astimezone()
    updated_at = now.strftime("%b %d, %Y · %I:%M %p %Z")

    # --- Indices + extended stock watchlist (Alpha Vantage; rate-limit safe) ---
    all_symbols = INDICES + STOCKS
    quotes = {}
    for i, (symbol, name) in enumerate(all_symbols):
        price, chg, high, low = get_alpha_vantage_quote(symbol)
        quotes[symbol] = {"name": name, "price": price, "chg": chg, "high": high, "low": low}
        if i < len(all_symbols) - 1:
            time.sleep(12)

    sp_price, sp_chg = quotes["SPY"]["price"], quotes["SPY"]["chg"]
    nasdaq_price, nasdaq_chg = quotes["QQQ"]["price"], quotes["QQQ"]["chg"]
    dow_price, dow_chg = quotes["DIA"]["price"], quotes["DIA"]["chg"]

    stock_tiles = "".join(
        tile_html(sym, quotes[sym]["name"], quotes[sym]["price"], quotes[sym]["chg"])
        for sym, _ in STOCKS
    )
    best_stock = max(STOCKS, key=lambda s: quotes[s[0]]["chg"])
    worst_stock = min(STOCKS, key=lambda s: quotes[s[0]]["chg"])
    stocks_up = sum(1 for sym, _ in STOCKS if quotes[sym]["chg"] > 0)

    # --- Sector performance, real market-wide movers, Treasury yield (3 more calls) ---
    time.sleep(12)
    sectors = get_sector_performance()
    time.sleep(12)
    gainers, losers, most_active = get_top_movers()
    time.sleep(12)
    treasury_value, treasury_date = get_treasury_yield()

    max_sector_abs = max((abs(p) for _, p in sectors), default=1.0)
    sector_html = "".join(sector_bar_html(name, pct, max_sector_abs) for name, pct in sectors)
    gainers_html = "".join(market_row_html(i) for i in gainers) or '<div class="mv-empty">No data returned this run.</div>'
    losers_html = "".join(market_row_html(i) for i in losers) or '<div class="mv-empty">No data returned this run.</div>'
    active_html = "".join(market_row_html(i, show_volume=True) for i in most_active) or '<div class="mv-empty">No data returned this run.</div>'
    treasury_str = f"{treasury_value:.2f}%" if treasury_value is not None else "N/A"

    # --- Crypto (richer per-coin data: market cap, volume, 24h high/low) ---
    by_id, global_data = get_crypto_data()
    fng_value, fng_label = get_fear_greed()

    crypto_tiles_parts = []
    crypto_changes = {}
    total_volume = 0.0
    for cg_id, name, symbol in CRYPTO:
        row = by_id.get(cg_id, {})
        price = row.get("current_price", 0.0) or 0.0
        chg = row.get("price_change_percentage_24h", 0.0) or 0.0
        crypto_changes[cg_id] = chg
        total_volume += row.get("total_volume", 0) or 0
        decimals = 2 if price < 1000 else 0
        crypto_tiles_parts.append(tile_html(symbol, name, price, chg, decimals))
    crypto_tiles = "".join(crypto_tiles_parts)

    best_crypto = max(CRYPTO, key=lambda c: crypto_changes[c[0]])
    worst_crypto = min(CRYPTO, key=lambda c: crypto_changes[c[0]])

    btc_row = by_id.get("bitcoin", {})
    eth_row = by_id.get("ethereum", {})
    btc_price = btc_row.get("current_price", 0.0)
    btc_chg = btc_row.get("price_change_percentage_24h", 0.0) or 0.0
    eth_price = eth_row.get("current_price", 0.0)
    eth_chg = eth_row.get("price_change_percentage_24h", 0.0) or 0.0

    dom = global_data["market_cap_percentage"]
    btc_dom = dom.get("btc", 0.0)
    eth_dom = dom.get("eth", 0.0)
    total_mcap = global_data["total_market_cap"]["usd"]
    mcap_chg = global_data.get("market_cap_change_percentage_24h_usd", 0.0)

    movers_html = (
        mover_line("Top stock", best_stock[0], quotes[best_stock[0]]["chg"])
        + mover_line("Lagging stock", worst_stock[0], quotes[worst_stock[0]]["chg"])
        + mover_line("Top coin", best_crypto[2], crypto_changes[best_crypto[0]])
        + mover_line("Lagging coin", worst_crypto[2], crypto_changes[worst_crypto[0]])
    )

    replacements = {
        "{{UPDATED_AT}}": updated_at,
        "{{SP_PRICE}}": fmt_money(sp_price),
        "{{SP_CHG}}": fmt_pct(sp_chg),
        "{{SP_CLASS}}": cls_for(sp_chg),
        "{{SP_RANGE}}": fmt_range(quotes["SPY"]["low"], quotes["SPY"]["high"]),
        "{{NASDAQ_PRICE}}": fmt_money(nasdaq_price),
        "{{NASDAQ_CHG}}": fmt_pct(nasdaq_chg),
        "{{NASDAQ_CLASS}}": cls_for(nasdaq_chg),
        "{{NASDAQ_RANGE}}": fmt_range(quotes["QQQ"]["low"], quotes["QQQ"]["high"]),
        "{{DOW_PRICE}}": fmt_money(dow_price),
        "{{DOW_CHG}}": fmt_pct(dow_chg),
        "{{DOW_CLASS}}": cls_for(dow_chg),
        "{{DOW_RANGE}}": fmt_range(quotes["DIA"]["low"], quotes["DIA"]["high"]),
        "{{SESSION_NOTE}}": session_note(sp_chg, nasdaq_chg, dow_chg, stocks_up),
        "{{BTC_PRICE}}": fmt_money(btc_price, 0),
        "{{BTC_CHG}}": fmt_pct(btc_chg),
        "{{BTC_CLASS}}": cls_for(btc_chg),
        "{{BTC_RANGE}}": fmt_range(btc_row.get("low_24h", btc_price), btc_row.get("high_24h", btc_price), 0),
        "{{ETH_PRICE}}": fmt_money(eth_price),
        "{{ETH_CHG}}": fmt_pct(eth_chg),
        "{{ETH_CLASS}}": cls_for(eth_chg),
        "{{ETH_RANGE}}": fmt_range(eth_row.get("low_24h", eth_price), eth_row.get("high_24h", eth_price)),
        "{{BTC_DOM}}": f"{btc_dom:.2f}%",
        "{{ETH_DOM}}": f"{eth_dom:.2f}%",
        "{{FNG_VALUE}}": str(fng_value),
        "{{FNG_LABEL}}": fng_label,
        "{{FNG_PILL}}": "RISK-OFF" if fng_value < 45 else ("NEUTRAL" if fng_value <= 55 else "RISK-ON"),
        "{{FNG_ANGLE}}": str(fng_angle(fng_value)),
        "{{CYCLE_TEXT}}": cycle_read_text(fng_value, btc_chg),
        "{{STOCK_TILES}}": stock_tiles,
        "{{CRYPTO_TILES}}": crypto_tiles,
        "{{MOVERS}}": movers_html,
        "{{BREADTH}}": f"{stocks_up}/15",
        "{{BREADTH_CLASS}}": "up" if stocks_up >= 8 else "down",
        "{{TOTAL_MCAP}}": fmt_big(total_mcap),
        "{{MCAP_CHG}}": fmt_pct(mcap_chg),
        "{{MCAP_CLASS}}": cls_for(mcap_chg),
        "{{TOTAL_VOL}}": fmt_big(total_volume),
        "{{COMBINED_DOM}}": f"{btc_dom + eth_dom:.1f}%",
        "{{SECTOR_ROWS}}": sector_html,
        "{{BEST_SECTOR}}": sectors[0][0] if sectors else "N/A",
        "{{WORST_SECTOR}}": sectors[-1][0] if sectors else "N/A",
        "{{GAINERS_ROWS}}": gainers_html,
        "{{LOSERS_ROWS}}": losers_html,
        "{{ACTIVE_ROWS}}": active_html,
        "{{TREASURY_10Y}}": treasury_str,
        "{{TREASURY_DATE}}": treasury_date or "N/A",
    }

    ticker_item = (
        '<span class="ticker-item"><span class="lbl">S&amp;P 500</span> {SP_PRICE} '
        '<span class="{SP_CLASS}">{SP_CHG}</span></span>'
        '<span class="ticker-item"><span class="lbl">NASDAQ</span> {NASDAQ_PRICE} '
        '<span class="{NASDAQ_CLASS}">{NASDAQ_CHG}</span></span>'
        '<span class="ticker-item"><span class="lbl">DOW</span> {DOW_PRICE} '
        '<span class="{DOW_CLASS}">{DOW_CHG}</span></span>'
        '<span class="ticker-item"><span class="lbl">BTC</span> {BTC_PRICE} '
        '<span class="{BTC_CLASS}">{BTC_CHG}</span></span>'
        '<span class="ticker-item"><span class="lbl">ETH</span> {ETH_PRICE} '
        '<span class="{ETH_CLASS}">{ETH_CHG}</span></span>'
        '<span class="ticker-item"><span class="lbl">F&amp;G</span> {FNG_VALUE} '
        '<span class="{FNG_CLASS}">{FNG_LABEL}</span></span>'
        '<span class="ticker-item"><span class="lbl">TOP STOCK</span> {BEST_STOCK_SYM} '
        '<span class="up">{BEST_STOCK_CHG}</span></span>'
        '<span class="ticker-item"><span class="lbl">TOP COIN</span> {BEST_CRYPTO_SYM} '
        '<span class="up">{BEST_CRYPTO_CHG}</span></span>'
    ).format(
        SP_PRICE=replacements["{{SP_PRICE}}"], SP_CLASS=replacements["{{SP_CLASS}}"], SP_CHG=replacements["{{SP_CHG}}"],
        NASDAQ_PRICE=replacements["{{NASDAQ_PRICE}}"], NASDAQ_CLASS=replacements["{{NASDAQ_CLASS}}"], NASDAQ_CHG=replacements["{{NASDAQ_CHG}}"],
        DOW_PRICE=replacements["{{DOW_PRICE}}"], DOW_CLASS=replacements["{{DOW_CLASS}}"], DOW_CHG=replacements["{{DOW_CHG}}"],
        BTC_PRICE=replacements["{{BTC_PRICE}}"], BTC_CLASS=replacements["{{BTC_CLASS}}"], BTC_CHG=replacements["{{BTC_CHG}}"],
        ETH_PRICE=replacements["{{ETH_PRICE}}"], ETH_CLASS=replacements["{{ETH_CLASS}}"], ETH_CHG=replacements["{{ETH_CHG}}"],
        FNG_VALUE=replacements["{{FNG_VALUE}}"], FNG_CLASS=("down" if fng_value < 45 else "up"), FNG_LABEL=fng_label,
        BEST_STOCK_SYM=best_stock[0], BEST_STOCK_CHG=fmt_pct(quotes[best_stock[0]]["chg"]),
        BEST_CRYPTO_SYM=best_crypto[2], BEST_CRYPTO_CHG=fmt_pct(crypto_changes[best_crypto[0]]),
    )
    replacements["{{TICKER_TRACK}}"] = ticker_item

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    for token, value in replacements.items():
        html = html.replace(token, str(value))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
