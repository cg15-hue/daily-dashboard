# Daily Market & Crypto Dashboard

Runs entirely on GitHub's servers on a schedule — no computer needs to be on. Every
morning it fetches fresh market/crypto data and republishes `docs/index.html` via
GitHub Pages.

## What you need to do (one-time setup, ~10 minutes)

1. **Create a GitHub account** if you don't have one: https://github.com/join

2. **Create a new repository** (public or private, either works): https://github.com/new
   - Name it anything, e.g. `daily-dashboard`.

3. **Get one free API key** (this is the only token needed):
   - Go to https://www.alphavantage.co/support/#api-key
   - Enter your email, click "GET FREE API KEY" — it's issued instantly, no email
     verification needed.
   - Copy the key.

4. **Add the key as a repo secret:**
   - In your new GitHub repo, go to Settings → Secrets and variables → Actions →
     "New repository secret".
   - Name: `ALPHA_VANTAGE_KEY`
   - Value: (paste the key from step 3)

5. **Upload these files** to the repo, keeping the folder structure:
   - `fetch_and_render.py`
   - `template.html`
   - `requirements.txt`
   - `.github/workflows/daily-report.yml`
   - (the `docs/` folder will be created automatically by the workflow)

   Easiest way: on the repo page, click "Add file" → "Upload files", drag all of
   them in (make sure `.github/workflows/daily-report.yml` keeps that exact path —
   GitHub's uploader preserves folder structure if you drag the whole folder).

6. **Enable GitHub Pages:**
   - Settings → Pages → under "Build and deployment", set Source to
     "Deploy from a branch", branch `main`, folder `/docs`. Save.
   - GitHub will give you a URL like `https://yourusername.github.io/daily-dashboard/`
     — that's your permanent dashboard link, bookmark it.

7. **Test it immediately** (don't wait for 8am):
   - Go to the "Actions" tab in your repo → click "Daily Market & Crypto Report" →
     "Run workflow" → confirm. Watch it run (~30 seconds), then visit your Pages
     URL to see the dashboard.

That's it. From here on, it fires automatically every day at 8:00 AM ET via the
cron schedule in the workflow file — your computer can be off, it doesn't matter,
GitHub runs it on their infrastructure.

## Data sources (no other keys needed)
- Bitcoin/Ethereum prices + BTC dominance: CoinGecko public API (no key required)
- Fear & Greed Index: alternative.me public API (no key required)
- S&P 500 / Nasdaq / Dow (via SPY/QQQ/DIA ETF proxies): Alpha Vantage (the one free key above)

## Watchlist size & rate limits
The dashboard now tracks 15 stocks (AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, JPM,
V, JNJ, WMT, XOM, UNH, PG, HD) plus the 3 indices (18 Alpha Vantage calls per run),
and 15 crypto coins (one batched CoinGecko call, no limit concern). Alpha Vantage's
free tier allows 25 requests/day, so each automatic daily run uses about 18 of that
25 — leaving very little room for manual "Run workflow" re-triggers on the same day.
If you want a bigger stock watchlist without hitting that ceiling, consider
switching to a provider with a more generous free tier (e.g. Twelve Data, 800
requests/day) — ask me and I can swap it in.

## Changing the schedule
Edit the `cron:` line in `.github/workflows/daily-report.yml`. It's currently
`0 12 * * *` (12:00 UTC = 8:00 AM Eastern Daylight Time). Cron is always UTC on
GitHub Actions, so adjust for your timezone/DST manually if needed.
