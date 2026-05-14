# Market Pulse — Daily Market Themes Tracker

A live, theme-clustered visualization of the day in global financial news. Inspired by sell-side themes trackers. Reads from FT, Bloomberg, WSJ, CNBC, Nikkei Asia, SCMP, and BBC RSS — no API keys required.

## What it is

- **6 themes** (gravity wells in the layout): AI, Geopolitics, Macro, Credit & Rates, Sustainability, Tech
- **3 regions** (shown as dashed ring around each bubble): Americas, Europe, Asia
- **Cross-region threads** (dashed arcs) connect stories that share salient entities — visualizing how, e.g., a Trump-Xi summit pulls AI, rates, and sustainability stories together
- **Click any bubble** to open the original article on the publisher's site

## Files

| File | What it does |
|---|---|
| `index.html` | **Self-contained viewer.** Data is embedded inside. Open it directly in any browser — no server needed. |
| `build.py` | Pulls RSS feeds, classifies into themes, computes impact, finds threads. Updates the embedded data inside `index.html` AND writes a separate `data.json` (for any external use). |
| `data.json` | The current dataset, also written separately. Optional. |
| `.github/workflows/refresh.yml` | GitHub Action that re-runs `build.py` 3x daily and commits the refreshed `index.html` |

## Local usage

```bash
pip install feedparser
python build.py            # fetches feeds, refreshes index.html
# Then just double-click index.html to open in your browser. No server.
```

If you prefer a local server (for the `data.json` dev workflow), `python -m http.server 8000` still works fine.

## Deploy to GitHub Pages (recommended)

1. Push this folder to a new GitHub repo
2. **Settings → Pages** → source = `main` branch, root
3. **Actions** tab → run "Daily News Refresh" once manually to generate the first `data.json`
4. Done — the action will refresh 3x daily (09:00 / 15:00 / 21:00 UTC, roughly matching session opens)

Your site lives at `https://<username>.github.io/<repo>/`.

## How classification works

Two-stage pipeline:

**Stage 1 — Regex classifier (always on, free).** Each headline + summary is scored against weighted keyword groups per theme. Highest-scoring theme wins, with two tilt rules:

- **AI** beats Geopolitics when explicit AI signals (Nvidia, OpenAI, LLM, GPU, datacenter) are present — so a Trump-Xi-AI story lands in AI rather than Geopolitics
- **Sustainability** gets a +2 boost on any climate / COP / emissions / net-zero / ESG signal

A junk filter drops obvious noise (sports profiles, recipes, gossip, lifestyle) before classification. Items below a minimum confidence threshold are also dropped.

**Stage 2 — LLM reclassifier (optional, more accurate).** If `ANTHROPIC_API_KEY` is set, the top 80 candidate items are batched and re-labeled by Claude Haiku 4.5 — a fast cheap model that catches semantic edge cases the regex misses (e.g. a Trump-Xi summit story about Apple/Microsoft that the regex pulls into Tech but is really Geopolitics). Items the LLM labels as `none` (lifestyle, sports, etc.) are dropped entirely.

The LLM pass costs roughly ~$0.001 per build (~80 short prompts × Haiku pricing). Failures degrade gracefully back to the regex output.

To enable: set `ANTHROPIC_API_KEY` as a repo secret in **Settings → Secrets and variables → Actions**. The workflow file already wires it in.

Region detection is keyword-based with a publisher-region fallback (Nikkei Asia → asia, BBC → eu, etc.).

**Impact (1-10)** is computed from cross-publisher coverage (does this same story appear in 2+ wires?), recency, and theme-keyword strength. A story Bloomberg, FT *and* WSJ all cover gets a higher impact than a single-source filler piece.

## Tuning

In `build.py`:
- Add/remove feeds in the `FEEDS` list
- Add/edit theme keyword groups in `THEMES`
- Adjust theme/publisher caps in `MAX_PER_THEME`, `MAX_PER_PUBLISHER`, `TARGET_N`
- Change the recency filter (currently 36 hours)

If GitHub Actions is rejected (e.g. on a private repo without minutes), run locally and push manually, or set up a Vercel/Netlify cron, or run `build.py` via your own crontab.
