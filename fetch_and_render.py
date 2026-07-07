#!/usr/bin/env python3
"""
Fetches current market + crypto data and renders the dashboard HTML.
Run daily via GitHub Actions (see .github/workflows/daily-report.yml).

Env vars required:
  ALPHA_VANTAGE_KEY  - free key from https://www.alphavantage.co/support/#api-key

NOTE on rate limits: Alpha Vantage's free tier allows 25 requests/day and
5 requests/minute. This script makes one request per stock ticker below
(18 total: 3 indices + 15 stocks), spaced 12s apart to stay under the
per-minute limit. That leaves very little daily headroom for manual re-runs
on top of the automatic daily run -- if you add more tickers, watch the
25/day ceiling.
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


def get_alpha_vantage_quote(symbol):
    """Returns (price, pct_change) for a ticker via Alpha Vantage GLOBAL_QUOTE."""
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
    return price, pct


def get_crypto_data():
    """Returns dict: id -> {price, chg}, plus btc dominance, in one batched call."""
    ids = ",".join(c[0] for c in CRYPTO)
    r = requests.get(
        "https://api.coingecko.com/api/v3/simple/price",
        params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
        timeout=20,
    )
    r.raise_for_status()
    prices = r.json()

    r2 = requests.get("https://api.coingecko.com/api/v3/global", timeout=20)
    r2.raise_for_status()
    dominance = r2.json()["data"]["market_cap_percentage"]["btc"]

    return prices, dominance


def get_fear_greed():
    """Returns (value:int, label:str)."""
    r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=20)
    r.raise_for_status()
    d = r.json()["data"][0]
    return int(d["value"]), d["value_classification"]


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


def session_note(sp_chg, nasdaq_chg, dow_chg):
    ups = sum(1 for c in (sp_chg, nasdaq_chg, dow_chg) if c > 0)
    if ups == 3:
        return "Broad-based gains across all three major indices today."
    if ups == 0:
        return "Broad-based losses across all three major indices today."
    return "Mixed session — indices diverged today."


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


def main():
    now = datetime.now(timezone.utc).astimezone()
    updated_at = now.strftime("%b %d, %Y · %I:%M %p %Z")

    # --- Indices + extended stock watchlist (Alpha Vantage; rate-limit safe) ---
    all_symbols = INDICES + STOCKS
    quotes = {}
    for i, (symbol, name) in enumerate(all_symbols):
        price, chg = get_alpha_vantage_quote(symbol)
        quotes[symbol] = {"name": name, "price": price, "chg": chg}
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

    # --- Crypto ---
    prices, dominance = get_crypto_data()
    fng_value, fng_label = get_fear_greed()

    crypto_tiles_parts = []
    crypto_changes = {}
    for cg_id, name, symbol in CRYPTO:
        d = prices.get(cg_id, {})
        price = d.get("usd", 0.0)
        chg = d.get("usd_24h_change", 0.0)
        crypto_changes[cg_id] = chg
        decimals = 2 if price < 1000 else 0
        crypto_tiles_parts.append(tile_html(symbol, name, price, chg, decimals))
    crypto_tiles = "".join(crypto_tiles_parts)

    best_crypto = max(CRYPTO, key=lambda c: crypto_changes[c[0]])
    worst_crypto = min(CRYPTO, key=lambda c: crypto_changes[c[0]])

    btc_price = prices["bitcoin"]["usd"]
    btc_chg = prices["bitcoin"]["usd_24h_change"]
    eth_price = prices["ethereum"]["usd"]
    eth_chg = prices["ethereum"]["usd_24h_change"]

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
        "{{NASDAQ_PRICE}}": fmt_money(nasdaq_price),
        "{{NASDAQ_CHG}}": fmt_pct(nasdaq_chg),
        "{{NASDAQ_CLASS}}": cls_for(nasdaq_chg),
        "{{DOW_PRICE}}": fmt_money(dow_price),
        "{{DOW_CHG}}": fmt_pct(dow_chg),
        "{{DOW_CLASS}}": cls_for(dow_chg),
        "{{SESSION_NOTE}}": session_note(sp_chg, nasdaq_chg, dow_chg),
        "{{BTC_PRICE}}": fmt_money(btc_price, 0),
        "{{BTC_CHG}}": fmt_pct(btc_chg),
        "{{BTC_CLASS}}": cls_for(btc_chg),
        "{{ETH_PRICE}}": fmt_money(eth_price),
        "{{ETH_CHG}}": fmt_pct(eth_chg),
        "{{ETH_CLASS}}": cls_for(eth_chg),
        "{{BTC_DOM}}": f"{dominance:.2f}%",
        "{{FNG_VALUE}}": str(fng_value),
        "{{FNG_LABEL}}": fng_label,
        "{{FNG_PILL}}": "RISK-OFF" if fng_value < 45 else ("NEUTRAL" if fng_value <= 55 else "RISK-ON"),
        "{{FNG_ANGLE}}": str(fng_angle(fng_value)),
        "{{CYCLE_TEXT}}": cycle_read_text(fng_value, btc_chg),
        "{{STOCK_TILES}}": stock_tiles,
        "{{CRYPTO_TILES}}": crypto_tiles,
        "{{MOVERS}}": movers_html,
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
