DSE Pulse — A & B Category Trading Signals
A static dashboard, hosted free on GitHub Pages, showing DSE (Dhaka Stock
Exchange) 'A' and 'B' category stocks with automated technical signals
(mood, entry, stop-loss, exit target) across four timeframes: 3 days, 1
week, 15 days, 1 month.
Data updates automatically via a scheduled GitHub Action — no server needed.
⚠️ Important — read before using
This is not financial advice. The "mood" (Strong Buy / Buy / Neutral /
Sell / Strong Sell) and the entry/stop-loss/exit numbers are produced by a
simple, transparent rule-based formula (see below) applied to real
historical prices. It is automated technical analysis, not a prediction,
not a recommendation, and not a substitute for your own research or a
licensed advisor.
The original blueprint this replaces used random numbers. An earlier
version of this script (random.choice(["Strong Buy", ...])) generated
moods and price targets completely at random while displaying them next to
real tickers and real prices. That's dangerous — it looks like real
analysis but isn't. This version replaces that with genuine calculations
from real price history (moving averages, momentum, RSI, ATR). Nothing
here is random.
DSE's website disallows automated access in its robots.txt. This
project scrapes public pages anyway, the way most open-source DSE tools do
(e.g. the bdshare library this uses), but you should know that going in.
Keep the update frequency reasonable (the default is every 30 minutes,
trading hours only) and treat this as a personal/educational project
rather than a commercial product, to stay respectful of DSE's servers and
reduce the chance of being rate-limited or blocked.
How the signal is calculated
For each timeframe (lookback of N trading days: 3 / 5 / 15 / 22):
Trend — is the current price above or below the N-day simple moving
average?
Momentum — % price change over the last N days, compared against a
threshold that scales with the timeframe.
RSI — Relative Strength Index (period scaled to the timeframe,
capped at 14). RSI > 60 favors buy, RSI < 40 favors sell.
Each factor contributes -1, 0, or +1 to a score from -3 to +3:
Score
Mood
≥ 2
Strong Buy
1
Buy
0
Neutral
-1
Sell
≤ -2
Strong Sell
For non-neutral moods:
Stop Loss = Entry ∓ (ATR14 × 1.5) — falls back to a flat 5% if ATR
isn't available.
Exit Target = Entry ± (risk × 2) — a 1:2 risk-to-reward ratio.
This is a standard, well-known style of rule-based signal — not a secret
formula, and not guaranteed to be profitable. Markets are risky; past
patterns don't guarantee future results.
Project structure
Code
Setup (GitHub, ~5 minutes)
I can't log into your GitHub account for you — I don't have that ability,
even by invitation. But these steps are quick:
Create a new repository on GitHub (public, so Pages can serve it
free), e.g. dse-pulse.
Upload all the files in this folder to the repo, keeping the folder
structure intact (.github/workflows/update-data.yml must stay in
.github/workflows/). Easiest way: on the repo page, "Add file" →
"Upload files", drag the whole folder in, commit.
Or, if you're comfortable with git locally:
Code
Enable GitHub Pages: repo → Settings → Pages → Source: "Deploy from a
branch" → Branch: main, folder: / (root) → Save. Your site will be at
https://<you>.github.io/dse-pulse/.
Run the workflow once manually to populate real data immediately:
repo → Actions tab → "Update DSE A/B Trading Signals" → "Run workflow".
This first run fetches ~5 months of price history per stock, so
real indicators (not just "Neutral / insufficient data") are ready right
away. It can take a few minutes for a few hundred tickers.
After that, the workflow runs automatically every 30 minutes during DSE
trading hours (Sun–Thu) and commits the refreshed data.json.
Local testing (optional)
Code
Limitations to know about
DSE's public pages can change their HTML structure at any time, which can
break the category scraper (fetch_category_tickers in analyzer.py).
If the dashboard stops updating, check the Action's logs first.
The mutual-fund filter is a heuristic (excludes tickers starting with a
digit or containing "MF"), not an official list — double-check if that
matters for your use case.
Category assignments (A/B/G/N/Z) are cached for 24 hours; if DSE
recategorizes a stock, it can take up to a day to show up correctly.
