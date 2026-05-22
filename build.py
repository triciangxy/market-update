"""
build.py — Pulls financial news RSS feeds, classifies by theme, writes data.json
Run daily (manually, via cron, or via GitHub Actions).
"""
import feedparser
import urllib.request
import socket
import json
import re
import html as html_module
from datetime import datetime, timezone, timedelta
from collections import Counter
import hashlib
import sys

socket.setdefaulttimeout(20)

# ── feeds: source, url, region hint ──────────────────────────────
FEEDS = [
    # Tier 1 wires (priority)
    ("FT Home",         "https://www.ft.com/?format=rss",                                 "global", "FT"),
    ("FT Markets",      "https://www.ft.com/markets?format=rss",                          "global", "FT"),
    ("FT Companies",    "https://www.ft.com/companies?format=rss",                        "global", "FT"),
    ("FT World",        "https://www.ft.com/world?format=rss",                            "global", "FT"),
    ("Bloomberg Mkts",  "https://feeds.bloomberg.com/markets/news.rss",                   "global", "Bloomberg"),
    ("Bloomberg Tech",  "https://feeds.bloomberg.com/technology/news.rss",                "global", "Bloomberg"),
    ("Bloomberg Green", "https://feeds.bloomberg.com/green/news.rss",                     "global", "Bloomberg"),
    ("Bloomberg Pol",   "https://feeds.bloomberg.com/politics/news.rss",                  "global", "Bloomberg"),
    ("WSJ Markets",     "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",                  "us",     "WSJ"),
    ("WSJ Business",    "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",                "us",     "WSJ"),
    ("WSJ Tech",        "https://feeds.a.dj.com/rss/RSSWSJD.xml",                         "global", "WSJ"),
    ("WSJ World",       "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                    "global", "WSJ"),

    # Reliable secondaries
    ("CNBC Top",        "https://www.cnbc.com/id/100003114/device/rss/rss.html",          "global", "CNBC"),
    ("CNBC World",      "https://www.cnbc.com/id/100727362/device/rss/rss.html",          "global", "CNBC"),
    ("CNBC Tech",       "https://www.cnbc.com/id/19854910/device/rss/rss.html",           "global", "CNBC"),
    ("CNBC Finance",    "https://www.cnbc.com/id/10000664/device/rss/rss.html",           "global", "CNBC"),
    ("MarketWatch",     "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines","us",   "MarketWatch"),
    ("Yahoo Finance",   "https://finance.yahoo.com/news/rssindex",                        "us",     "Yahoo Finance"),
    ("BBC Business",    "https://feeds.bbci.co.uk/news/business/rss.xml",                 "eu",     "BBC"),

    # Asia
    ("Nikkei Asia",     "https://asia.nikkei.com/rss/feed/nar",                           "asia",   "Nikkei Asia"),
    ("SCMP Business",   "https://www.scmp.com/rss/92/feed",                               "asia",   "SCMP"),
]

# ── theme classifier ──────────────────────────────────────────────
# Each theme has keyword groups. We score and pick the highest.
THEMES = {
    "ai": {
        "label": "AI",
        "color": "#b88aff",
        "keywords": [
            (r"\bA\.?I\.?\b|artificial intelligence", 3),
            (r"\bopenai\b|\banthropic\b|\bdeepseek\b|\bperplexity\b|\bmistral\b|\bxAI\b", 3),
            (r"\bnvidia\b|\bH100\b|\bH200\b|\bBlackwell\b|\bGPU\b|chatgpt|claude|gemini|copilot", 3),
            (r"\bLLM\b|large language model|foundation model|generative", 3),
            (r"data cent(er|re)|hyperscaler|inference|training", 2),
            (r"AMD|TSMC|ASML|semiconductor|chip", 2),
            (r"AGI|machine learning|neural network", 2),
        ]
    },
    "geopolitics": {
        "label": "Geopolitics",
        "color": "#ff9558",
        "keywords": [
            (r"\bIran\b|\bIsrael\b|\bGaza\b|\bHamas\b|\bHezbollah\b|\bUkraine\b|\bRussia\b|\bPutin\b|\bZelenskyy\b", 3),
            (r"\btariff\b|trade war|sanction|export control|export restriction", 3),
            (r"Trump-Xi|Xi Jinping|summit|bilateral|geopolit", 3),
            (r"Taiwan|North Korea|South China Sea|Strait of Hormuz", 3),
            (r"NATO|G7|G20|BRICS|UN\b", 2),
            (r"war|conflict|invasion|ceasefire|truce|peace talk|diplomac", 2),
            (r"election|coup|protest|sovereign|regime", 2),
        ]
    },
    "macro": {
        "label": "Macro",
        "color": "#ff6b9d",
        "keywords": [
            (r"\bGDP\b|recession|growth|inflation|deflation|stagflation", 3),
            (r"\bCPI\b|\bPPI\b|\bPCE\b|jobs report|payrolls|unemployment", 3),
            (r"retail sales|consumer confidence|PMI|ISM|housing starts", 3),
            (r"economy|economic outlook|economist|forecast", 1),
            (r"emerging market|developed market|EM\b|DM\b", 2),
            (r"yuan|euro|dollar|pound|yen|FX\b", 2),
        ]
    },
    "rates": {
        "label": "Credit & Rates",
        "color": "#6fa8ff",
        "keywords": [
            (r"\bFed\b|Federal Reserve|FOMC|Jerome Powell|Warsh", 3),
            (r"\bECB\b|\bBOE\b|\bBOJ\b|Bank of England|Bank of Japan|PBOC|ECB", 3),
            (r"rate cut|rate hike|interest rate|basis point|bps", 3),
            (r"Treasur|yield curve|gilt|bund|JGB|sovereign bond", 3),
            (r"\bcredit\b|spread|default|downgrade|rating|junk bond|high yield|investment grade", 3),
            (r"monetary polic|hawkish|dovish|tightening|easing", 3),
            (r"\bbond\b|bond market|fixed income", 2),
        ]
    },
    "sustainability": {
        "label": "Sustainability",
        "color": "#4ade80",
        "keywords": [
            (r"climate|carbon|emissions|net.?zero|decarboni[sz]", 3),
            (r"\bESG\b|sustainab|green bond|green finance", 3),
            (r"renewable|solar|wind|hydrogen|electric vehicle|\bEV\b", 3),
            (r"COP\d+|UN climate|Paris Agreement|climate disclosure", 3),
            (r"transition|clean energy|biodivers|coal phase", 2),
            (r"environment|pollution|recycling", 1),
        ]
    },
    "tech": {
        "label": "Tech",
        "color": "#5cd4e3",
        "keywords": [
            # Crypto & digital assets (strong signal)
            (r"\bbitcoin\b|\bethereum\b|crypto|blockchain|stablecoin|DeFi|tokeni[sz]ation", 4),
            # Cyber
            (r"\bcyber\b|\bhack(ed|ing)?\b|breach|ransomware|zero.day", 3),
            # Hardware / consumer platforms
            (r"\bsmartphone\b|\bwearable\b|VR\b|AR\b|metaverse|gaming|streaming service", 3),
            # Fintech & platforms
            (r"\bfintech\b|payment platform|\bdigital wallet\b|app store", 3),
            # Tech IPOs (but AI IPOs get pulled into AI by the tilt below)
            (r"\bIPO\b.{0,30}(app|platform|software|gaming|streaming|crypto)", 3),
            # Big tech corporate (non-AI angles)
            (r"Apple|Tesla|Meta|Amazon|Microsoft|Samsung|Sony|Netflix|Spotify|Uber|Airbnb", 1),
            (r"\bstartup\b.{0,40}(funding|round|valuation)", 2),
        ]
    },
}

REGION_KEYWORDS = {
    "us":   [r"\bUS\b|\bU\.S\.|America|Wall Street|Washington|New York|S&P|Nasdaq|Dow Jones|Treasury|White House|Trump|Biden|California|Texas"],
    "eu":   [r"\bEU\b|Europe|European|UK|United Kingdom|Britain|British|London|Frankfurt|Paris|Berlin|Brussels|DAX|CAC|FTSE|STOXX|ECB|gilt|bund|euro\b|Starmer|Macron|Scholz|Merz"],
    "asia": [r"China|Chinese|Japan|Japanese|Tokyo|Beijing|Shanghai|Hong Kong|Korea|Korean|Seoul|Taiwan|India|Mumbai|Nikkei|Kospi|Hang Seng|CSI 300|yen|yuan|Xi Jinping|Modi|Kishida|Samsung|TSMC|Alibaba|Tencent"],
}


# ── SUB-THEMES ──────────────────────────────────────────────────────
# Each story rolls up to a top-level theme (THEMES) AND a sub-theme.
# Sub-themes become the bubbles in the viz, sized by story count.
# Each sub-theme: { label, parent_theme, keywords }
SUB_THEMES = {
    # AI sub-themes
    "ai_infra":       {"label": "AI Infra",       "parent": "ai", "keywords": [r"data cent(er|re)|hyperscaler|GPU|H100|H200|Blackwell|AI infrastructure|inference|training cluster"]},
    "ai_chips":       {"label": "AI Chips",       "parent": "ai", "keywords": [r"Nvidia|NVDA|AMD|TSMC|ASML|semiconductor|chipmaker|Cerebras|Hon Hai|silicon"]},
    "ai_models":      {"label": "Foundation Models","parent": "ai", "keywords": [r"\bOpenAI\b|\bAnthropic\b|\bClaude\b|ChatGPT|Gemini|DeepSeek|Mistral|LLM|large language|foundation model|AGI"]},
    "ai_apps":        {"label": "AI Applications","parent": "ai", "keywords": [r"AI tool|AI software|AI assistant|copilot|enterprise AI|AI feature"]},
    "ai_governance":  {"label": "AI Governance",  "parent": "ai", "keywords": [r"AI regulation|AI safety|AI act|AI rules|AI export|AI policy"]},

    # Geopolitics sub-themes
    "us_china":       {"label": "US-China",       "parent": "geopolitics", "keywords": [r"Trump.{0,20}Xi|US.China|China.US|Beijing summit|chip export|Taiwan"]},
    "iran_war":       {"label": "Iran War",       "parent": "geopolitics", "keywords": [r"Iran|Tehran|Strait of Hormuz|Israel|Gaza|Hamas|Hezbollah|Middle East"]},
    "ukraine_russia": {"label": "Ukraine-Russia", "parent": "geopolitics", "keywords": [r"Ukraine|Russia|Putin|Zelenskyy|Kyiv|Moscow|Donbas"]},
    "tariffs":        {"label": "Tariffs & Trade","parent": "geopolitics", "keywords": [r"tariff|trade war|trade deal|export control|sanction|WTO"]},
    "elections":      {"label": "Elections",      "parent": "geopolitics", "keywords": [r"election|vote|ballot|primary|Starmer|leadership bid|coalition"]},

    # Macro sub-themes
    "inflation":      {"label": "Inflation",      "parent": "macro", "keywords": [r"\bCPI\b|\bPPI\b|\bPCE\b|inflation|deflation|price index|disinflation"]},
    "growth_gdp":     {"label": "Growth & GDP",   "parent": "macro", "keywords": [r"\bGDP\b|recession|growth|expansion|contraction|economic output"]},
    "jobs":           {"label": "Labor & Jobs",   "parent": "macro", "keywords": [r"jobs report|payrolls|unemployment|labor market|hiring|layoff|wage"]},
    "commodities":    {"label": "Commodities",    "parent": "macro", "keywords": [r"\boil\b|crude|Brent|WTI|gold|copper|iron ore|commodity|OPEC|IEA"]},
    "fx":             {"label": "FX",             "parent": "macro", "keywords": [r"\bdollar\b|euro\b|\byen\b|yuan|pound|sterling|currency|FX\b|DXY"]},

    # Rates sub-themes
    "fed":            {"label": "Fed",            "parent": "rates", "keywords": [r"\bFed\b|Federal Reserve|FOMC|Powell|Warsh|Fed chair"]},
    "ecb_boe":        {"label": "ECB & BoE",      "parent": "rates", "keywords": [r"\bECB\b|\bBoE\b|Bank of England|European Central Bank|Lagarde|Bailey"]},
    "boj_pboc":       {"label": "BoJ & PBOC",     "parent": "rates", "keywords": [r"\bBoJ\b|\bPBOC\b|Bank of Japan|People's Bank of China"]},
    "treasuries":     {"label": "Treasuries",     "parent": "rates", "keywords": [r"Treasur|10-year|2-year|yield curve|sovereign|repo"]},
    "gilts_bunds":    {"label": "Gilts & Bunds",  "parent": "rates", "keywords": [r"gilt|bund|JGB|UK bond|German bond|Japanese bond"]},
    "credit":         {"label": "Credit",         "parent": "rates", "keywords": [r"\bcredit\b|spread|default|downgrade|high yield|investment grade|private credit|junk bond"]},
    "stablecoin":     {"label": "Stablecoin Rules","parent": "rates","keywords": [r"stablecoin|digital currency rule|CBDC"]},

    # Sustainability sub-themes
    "climate":        {"label": "Climate Policy", "parent": "sustainability", "keywords": [r"climate|COP\d+|UN climate|Paris Agreement|net.?zero"]},
    "ev_transport":   {"label": "EVs",            "parent": "sustainability", "keywords": [r"\bEV\b|electric vehicle|BYD|Tesla.{0,30}EV|battery vehicle"]},
    "renewables":     {"label": "Renewables",     "parent": "sustainability", "keywords": [r"renewable|solar|wind power|hydrogen|clean energy"]},
    "esg":            {"label": "ESG & Green Finance","parent": "sustainability","keywords": [r"\bESG\b|green bond|sustainab|climate risk|green finance"]},
    "carbon":         {"label": "Carbon & Emissions","parent": "sustainability","keywords": [r"carbon|emissions|decarboni[sz]|coal phase"]},

    # Tech sub-themes
    "crypto":         {"label": "Crypto",         "parent": "tech", "keywords": [r"\bbitcoin\b|\bethereum\b|crypto|blockchain|tokeni[sz]"]},
    "cyber":          {"label": "Cyber",          "parent": "tech", "keywords": [r"\bcyber\b|\bhack(ed|ing)?\b|breach|ransomware|zero.day"]},
    "fintech":        {"label": "Fintech",        "parent": "tech", "keywords": [r"\bfintech\b|payment|digital wallet|app store|Klarna|Stripe"]},
    "consumer_tech":  {"label": "Consumer Tech",  "parent": "tech", "keywords": [r"\bsmartphone\b|\bwearable\b|VR\b|AR\b|gaming|streaming"]},
    "big_tech_corp":  {"label": "Big Tech Corp.", "parent": "tech", "keywords": [r"Apple|Tesla|Meta|Amazon|Microsoft|Samsung|Sony|Netflix"]},
}


def score_sub_theme(text, parent_theme):
    """Find best sub-theme match within a parent theme. Returns sub-theme key or None."""
    best_key, best_score = None, 0
    for sub_key, cfg in SUB_THEMES.items():
        if cfg["parent"] != parent_theme:
            continue
        score = sum(1 for pat in cfg["keywords"] if re.search(pat, text, re.IGNORECASE))
        if score > best_score:
            best_key, best_score = sub_key, score
    return best_key  # may be None if no sub-theme matched


def clean_html(s):
    """Strip HTML tags and decode entities."""
    if not s: return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_module.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def score_theme(text):
    """Return (theme_key, score) for best match, or (None, 0) if no signal."""
    scores = {}
    for theme, cfg in THEMES.items():
        s = 0
        for pat, weight in cfg["keywords"]:
            if re.search(pat, text, re.IGNORECASE):
                s += weight
        scores[theme] = s

    # Tilt: AI-specific terms beat generic Geopolitics
    if scores.get("ai", 0) >= 5 and scores["ai"] >= scores.get("geopolitics", 0) - 2:
        scores["ai"] += 2
    # Sustainability hard-wins on climate signals
    if re.search(r"climate|COP\d+|emissions|net.?zero|ESG\b", text, re.IGNORECASE):
        scores["sustainability"] = scores.get("sustainability", 0) + 2

    best = max(scores.items(), key=lambda x: x[1])

    # Minimum confidence threshold — drop weakly-classified noise
    if best[1] < 3:
        return (None, 0)
    return best


# Junk patterns — drop these regardless of any theme score
JUNK_PATTERNS = [
    r"\bburger\b|\brecipe\b|\bcocktail\b|wine review",
    r"\brugby\b|\bfootball\b|\bsoccer\b|\btennis\b|\bgolf\b|\bcricket\b|\bbasketball\b|NBA\b|NFL\b|NHL\b|MLB\b|\bF1\b",
    r"\bcelebrity\b|\bcelebs\b|\bgossip\b|\bdivorce\b|\bwedding\b|\bdating\b",
    r"horoscope|astrology|zodiac",
    r"\bsuperinvestor\b.{0,30}\bsport",  # the Waxman sports investor profile
    r"\bopinion piece\b|\bcolumn\b.{0,20}\bvalentine\b",
    r"how to|life hack|hacks for|best.{0,15}gift",
]
def is_junk(text):
    return any(re.search(p, text, re.IGNORECASE) for p in JUNK_PATTERNS)


def detect_region(text, fallback="global"):
    """Detect region by keyword. If multiple, pick highest-scoring; if none, fallback."""
    scores = {}
    for region, patterns in REGION_KEYWORDS.items():
        s = sum(1 for pat in patterns if re.search(pat, text, re.IGNORECASE))
        scores[region] = s
    best = max(scores.items(), key=lambda x: x[1])
    return best[0] if best[1] > 0 else fallback


def parse_feed(name, url, region_hint, publisher):
    """Fetch and parse one feed, returning list of normalized items."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MarketPulse RSS Aggregator)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except Exception as e:
        print(f"  [WARN] {name}: {str(e)[:80]}", file=sys.stderr)
        return []

    parsed = feedparser.parse(data)
    items = []
    for entry in parsed.entries:
        title = clean_html(entry.get("title", ""))
        summary = clean_html(entry.get("summary", entry.get("description", "")))
        link = entry.get("link", "")

        # parse pubdate
        pub = None
        for k in ("published_parsed", "updated_parsed"):
            if entry.get(k):
                pub = datetime(*entry[k][:6], tzinfo=timezone.utc)
                break

        if not title or not link:
            continue

        full_text = f"{title} {summary}"

        # Drop obvious junk before classification
        if is_junk(full_text):
            continue

        theme, score = score_theme(full_text)
        if theme is None:
            continue

        region = detect_region(full_text, fallback=region_hint if region_hint != "global" else detect_region(full_text, "us"))

        # Find sub-theme within parent theme (may be None if no match)
        sub_theme = score_sub_theme(full_text, theme)

        # build a stable id
        uid = hashlib.md5(link.encode()).hexdigest()[:12]

        items.append({
            "id": uid,
            "title": title,
            "summary": summary[:400],
            "link": link,
            "publisher": publisher,
            "feed": name,
            "pub_iso": pub.isoformat() if pub else None,
            "pub_ts": pub.timestamp() if pub else 0,
            "theme": theme,
            "sub_theme": sub_theme,
            "theme_score": score,
            "region": region,
        })
    return items


def dedupe(items):
    """De-duplicate by URL and by near-identical title."""
    seen_links = set()
    seen_titles = set()
    out = []
    for it in items:
        link_key = it["link"].split("?")[0].rstrip("/").lower()
        # normalize title for fuzzy dedupe
        t = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())
        t = re.sub(r"\s+", " ", t).strip()
        # take first 8 words as fingerprint
        title_key = " ".join(t.split()[:8])
        if link_key in seen_links or (title_key and title_key in seen_titles):
            continue
        seen_links.add(link_key)
        if title_key:
            seen_titles.add(title_key)
        out.append(it)
    return out


def compute_impact(items):
    """
    Impact 1-10 based on: cross-publisher coverage (do multiple wires cover same story),
    theme_score, and recency.
    """
    # Group near-duplicate stories across publishers to count coverage
    # Use a coarse 6-word title fingerprint
    coverage = Counter()
    for it in items:
        t = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())
        key = " ".join(t.split()[:5])
        coverage[key] += 1

    now = datetime.now(timezone.utc).timestamp()
    for it in items:
        t = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())
        key = " ".join(t.split()[:5])
        cov_score = min(coverage[key] - 1, 4)  # 0-4

        # recency: same-day = full; older drops off
        age_h = max(0, (now - it["pub_ts"]) / 3600) if it["pub_ts"] else 24
        rec_score = max(0, 4 - int(age_h / 6))  # 4 if <6h, then -1 per 6h

        theme_score = min(it["theme_score"], 6) / 2  # 0-3

        it["impact"] = max(1, min(10, int(2 + cov_score + rec_score + theme_score)))
    return items


def build_threads(items):
    """
    Build cross-region story threads: pairs of items sharing strong title overlap
    but from different regions, OR sharing strong entity overlap.
    """
    # Simple approach: shared salient tokens between items in different regions
    STOPWORDS = set("the a an and or of to in for on at is are was were be been being with by from as that this it its".split())

    def tokens(s):
        words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", s)
        return {w.lower() for w in words if w.lower() not in STOPWORDS and len(w) >= 4}

    # Pre-compute
    for it in items:
        it["_tokens"] = tokens(it["title"] + " " + it["summary"])

    threads = []
    seen = set()
    for i, a in enumerate(items):
        for b in items[i+1:]:
            if a["region"] == b["region"]:
                continue
            overlap = a["_tokens"] & b["_tokens"]
            if len(overlap) >= 3:
                key = tuple(sorted([a["id"], b["id"]]))
                if key in seen:
                    continue
                seen.add(key)
                threads.append({"from": a["id"], "to": b["id"], "shared": list(overlap)[:5]})

    # Cap per node so it doesn't get spaghetti
    per_node = Counter()
    capped = []
    for t in threads:
        if per_node[t["from"]] >= 3 or per_node[t["to"]] >= 3:
            continue
        per_node[t["from"]] += 1
        per_node[t["to"]] += 1
        capped.append(t)

    # remove _tokens from items before serializing
    for it in items:
        it.pop("_tokens", None)

    return capped


def llm_reclassify(items, api_key, theme_keys):
    """
    Optional second-pass classifier using Anthropic's API.
    Re-labels theme for each item using semantic understanding.
    Falls back gracefully if API call fails.
    """
    import json as _json
    try:
        import urllib.request, urllib.error
    except ImportError:
        return items

    # Batch 20 items at a time to keep prompts tight
    BATCH = 20
    theme_options = ", ".join(theme_keys + ["none"])

    print(f"\n  LLM reclassifying {len(items)} items in batches of {BATCH}...", file=sys.stderr)

    for start in range(0, len(items), BATCH):
        batch = items[start:start + BATCH]
        lines = []
        for i, it in enumerate(batch):
            t = it["title"][:160]
            s = it["summary"][:200]
            lines.append(f"{i}. TITLE: {t}\n   SUMMARY: {s}")
        prompt = (
            f"Classify each financial news headline into EXACTLY ONE theme from: {theme_options}.\n\n"
            "Themes mean:\n"
            "- ai: artificial intelligence, LLMs, GPUs, AI chips, AI infra, foundation models\n"
            "- geopolitics: tariffs, trade wars, summits, conflict, sanctions, election politics affecting markets\n"
            "- macro: GDP, inflation, jobs, retail sales, central bank meetings as economic events, FX moves\n"
            "- rates: monetary policy, bonds, yields, credit markets, Fed/ECB/BOE/BOJ decisions, repo, gilts\n"
            "- sustainability: climate, ESG, green finance, EVs, renewables, emissions, COP\n"
            "- tech: crypto, cyber, big-tech corporate (non-AI), fintech, consumer hardware\n"
            "- none: lifestyle, sports, gossip, recipes, anything not actually about markets or business\n\n"
            "Return ONLY a JSON array of theme strings, one per item, in order. No prose.\n\n"
            "Items:\n" + "\n\n".join(lines)
        )

        try:
            req_body = _json.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}],
            }).encode()
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_body,
                headers={
                    "content-type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = _json.loads(resp.read())
            text = data["content"][0]["text"].strip()
            # extract JSON array
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if not m: continue
            labels = _json.loads(m.group(0))
            for i, label in enumerate(labels):
                if i >= len(batch): break
                if label == "none":
                    batch[i]["_drop"] = True
                elif label in theme_keys:
                    batch[i]["theme"] = label
            print(f"    batch {start//BATCH + 1}: {len(labels)} relabeled", file=sys.stderr)
        except Exception as e:
            print(f"    [WARN] batch {start//BATCH + 1} failed: {str(e)[:80]}", file=sys.stderr)

    # Drop "none"-labeled items
    return [it for it in items if not it.get("_drop")]


# ── Market data (fetched once per build via yfinance) ──────
MARKETS_CONFIG = [
    # Equities
    {"ticker": "^GSPC",    "name": "S&P 500",      "unit": "price", "group": "equities"},
    {"ticker": "^IXIC",    "name": "Nasdaq",       "unit": "price", "group": "equities"},
    {"ticker": "^DJI",     "name": "Dow",          "unit": "price", "group": "equities"},
    {"ticker": "^STOXX",   "name": "STOXX 600",    "unit": "price", "group": "equities"},
    {"ticker": "^N225",    "name": "Nikkei 225",   "unit": "price", "group": "equities"},
    {"ticker": "^HSI",     "name": "Hang Seng",    "unit": "price", "group": "equities"},
    {"ticker": "^STI",     "name": "Straits Times","unit": "price", "group": "equities"},
    # Rates
    {"ticker": "^TNX",     "name": "US 10Y",       "unit": "pct",   "group": "rates"},
    # Commodities
    {"ticker": "GC=F",     "name": "Gold",         "unit": "price", "group": "commod"},
    {"ticker": "BZ=F",     "name": "Brent",        "unit": "price", "group": "commod"},
    {"ticker": "CL=F",     "name": "WTI",          "unit": "price", "group": "commod"},
    # FX
    {"ticker": "DX-Y.NYB", "name": "DXY",          "unit": "price", "group": "fx"},
    {"ticker": "JPY=X",    "name": "USD/JPY",      "unit": "price", "group": "fx"},
    # Crypto
    {"ticker": "BTC-USD",  "name": "Bitcoin",      "unit": "price", "group": "crypto"},
]


def fetch_markets():
    """Pull latest + previous close for each ticker via yfinance.
    Returns list of dicts. Skips silently if yfinance isn't installed
    or a single ticker fails — doesn't break the whole build.
    """
    try:
        import yfinance as yf
    except ImportError:
        print("  [WARN] yfinance not installed — skipping markets data", file=sys.stderr)
        return []

    out = []
    for cfg in MARKETS_CONFIG:
        try:
            tk = yf.Ticker(cfg["ticker"])
            hist = tk.history(period="5d", interval="1d")
            if hist is None or len(hist) == 0:
                print(f"    [skip] {cfg['ticker']}: no history", file=sys.stderr)
                continue
            closes = [float(x) for x in hist["Close"].dropna().tolist()]
            if not closes:
                continue
            price = closes[-1]
            prev = closes[-2] if len(closes) >= 2 else None
            chg = ((price - prev) / prev * 100.0) if (prev and prev != 0) else None
            out.append({
                "ticker": cfg["ticker"],
                "name":   cfg["name"],
                "price":  round(price, 4),
                "prev_close": round(prev, 4) if prev is not None else None,
                "change_pct": round(chg, 3) if chg is not None else None,
                "unit":   cfg["unit"],
                "group":  cfg["group"],
            })
            shown = chg if chg is not None else 0.0
            print(f"    {cfg['name']:14} {price:>12,.2f} ({shown:+.2f}%)", file=sys.stderr)
        except Exception as e:
            print(f"    [skip] {cfg['ticker']}: {str(e)[:80]}", file=sys.stderr)
    return out


def main():
    print("Fetching feeds...", file=sys.stderr)
    all_items = []
    feed_stats = []
    for name, url, region_hint, publisher in FEEDS:
        items = parse_feed(name, url, region_hint, publisher)
        print(f"  {name}: {len(items)} items", file=sys.stderr)
        feed_stats.append({"name": name, "count": len(items), "publisher": publisher})
        all_items.extend(items)

    print(f"\nTotal pre-dedupe: {len(all_items)}", file=sys.stderr)

    cutoff = datetime.now(timezone.utc).timestamp() - 36 * 3600
    all_items = [x for x in all_items if x["pub_ts"] == 0 or x["pub_ts"] >= cutoff]
    print(f"After 36h filter: {len(all_items)}", file=sys.stderr)

    all_items = dedupe(all_items)
    print(f"After dedupe: {len(all_items)}", file=sys.stderr)

    all_items = compute_impact(all_items)
    all_items.sort(key=lambda x: (-x["impact"], -x["pub_ts"]))

    # Optional: LLM second pass on top candidates (cleaner classification)
    import os
    anth_key = os.environ.get("ANTHROPIC_API_KEY")
    if anth_key:
        candidates = all_items[:80]
        candidates = llm_reclassify(candidates, anth_key, list(THEMES.keys()))
        # rebuild the full list: top 80 (relabeled, junk dropped) + the rest
        all_items = candidates + all_items[80:]
        # re-sort, since theme might have changed which affects later selection
        all_items.sort(key=lambda x: (-x["impact"], -x["pub_ts"]))
    else:
        print("\n  (Skipping LLM reclassify — set ANTHROPIC_API_KEY to enable)", file=sys.stderr)

    # Theme-balanced selection: max per theme, max per publisher
    # Higher caps now since stories aggregate into sub-theme bubbles, not 1 story = 1 bubble.
    MAX_PER_THEME = 25
    MAX_PER_PUBLISHER = 40
    MIN_PER_THEME = 6
    TARGET_N = 130

    top = []
    theme_count = Counter()
    pub_count = Counter()

    for it in all_items:
        if len(top) >= TARGET_N:
            break
        if theme_count[it["theme"]] >= MAX_PER_THEME:
            continue
        if pub_count[it["publisher"]] >= MAX_PER_PUBLISHER:
            continue
        top.append(it)
        theme_count[it["theme"]] += 1
        pub_count[it["publisher"]] += 1

    # Backfill thin themes
    for theme in THEMES:
        if theme_count[theme] >= MIN_PER_THEME:
            continue
        need = MIN_PER_THEME - theme_count[theme]
        for it in all_items:
            if need == 0: break
            if it in top: continue
            if it["theme"] != theme: continue
            top.append(it)
            theme_count[theme] += 1
            need -= 1

    # ── Build sub-theme bubbles: aggregate stories by sub-theme ─────
    # Each bubble = one named sub-theme with count + list of underlying story IDs.
    # Stories without a sub-theme match are assigned a fallback bucket per parent theme.
    from collections import defaultdict
    bubble_stories = defaultdict(list)
    for it in top:
        sub = it.get("sub_theme")
        if not sub:
            # Fall back: parent_theme + "_other"
            sub = f"{it['theme']}_other"
        bubble_stories[sub].append(it["id"])

    # Build the bubble list
    bubbles = []
    for sub_key, story_ids in bubble_stories.items():
        if sub_key in SUB_THEMES:
            cfg = SUB_THEMES[sub_key]
            label = cfg["label"]
            parent = cfg["parent"]
        else:
            # _other fallback
            parent = sub_key.replace("_other", "")
            label = f"Other {THEMES[parent]['label']}"
        bubbles.append({
            "id": sub_key,
            "label": label,
            "parent": parent,
            "color": THEMES[parent]["color"],
            "count": len(story_ids),
            "story_ids": story_ids,
        })

    # Drop trivially small bubbles (just 1 story in an "other" bucket can be noise)
    bubbles = [b for b in bubbles if b["count"] >= 1]
    # Sort by count desc
    bubbles.sort(key=lambda b: -b["count"])

    # Build cross-bubble links: when two bubbles share a region focus or have
    # stories with overlapping entities. Simpler: link bubbles whose stories
    # share salient terms.
    bubble_links = []
    bubble_token_sets = {}
    STOPWORDS = set("the a an and or of to in for on at is are was were be been being with by from as that this it its".split())
    for b in bubbles:
        tokens = set()
        for sid in b["story_ids"]:
            story = next((x for x in top if x["id"] == sid), None)
            if not story: continue
            words = re.findall(r"[A-Za-z][A-Za-z0-9]{3,}", story["title"] + " " + story["summary"][:200])
            tokens.update(w.lower() for w in words if w.lower() not in STOPWORDS and len(w) >= 4)
        bubble_token_sets[b["id"]] = tokens

    for i, a in enumerate(bubbles):
        for b in bubbles[i+1:]:
            overlap = bubble_token_sets[a["id"]] & bubble_token_sets[b["id"]]
            if len(overlap) >= 4:  # at least 4 shared salient terms
                bubble_links.append({"from": a["id"], "to": b["id"], "weight": len(overlap)})

    # Stats
    theme_breakdown = Counter(it["theme"] for it in top)
    region_breakdown = Counter(it["region"] for it in top)
    publisher_breakdown = Counter(it["publisher"] for it in top)

    # ── Market data ──
    print("\nFetching markets...", file=sys.stderr)
    markets = fetch_markets()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "themes": {k: {"label": v["label"], "color": v["color"]} for k, v in THEMES.items()},
        "bubbles": bubbles,
        "stories": top,
        "links": bubble_links,
        "markets": markets,
        "stats": {
            "total_stories": len(top),
            "total_bubbles": len(bubbles),
            "total_links": len(bubble_links),
            "by_theme": dict(theme_breakdown),
            "by_region": dict(region_breakdown),
            "by_publisher": dict(publisher_breakdown),
            "feeds_active": sum(1 for f in feed_stats if f["count"] > 0),
            "feeds_total": len(feed_stats),
        }
    }

    with open("data.json", "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Wrote data.json — {len(bubbles)} bubbles, {len(top)} stories, {len(bubble_links)} links", file=sys.stderr)

    # ── ALSO inject into index.html for fully self-contained single-file deploy ──
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html = f.read()

        compact_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        # Replace whatever is currently inside <script id="news-data" ...>...</script>
        new_html, n = re.subn(
            r'(<script id="news-data" type="application/json">)([\s\S]*?)(</script>)',
            lambda m: m.group(1) + "\n" + compact_json + "\n" + m.group(3),
            html,
            count=1,
        )
        if n == 1:
            with open("index.html", "w", encoding="utf-8") as f:
                f.write(new_html)
            print(f"✓ Injected data into index.html (single-file mode)", file=sys.stderr)
        else:
            print("  [WARN] Could not find <script id='news-data'> block in index.html — single-file mode skipped", file=sys.stderr)
    except FileNotFoundError:
        print("  [WARN] index.html not found — single-file injection skipped", file=sys.stderr)

    print(f"  Themes: {dict(theme_breakdown)}", file=sys.stderr)
    print(f"  Regions: {dict(region_breakdown)}", file=sys.stderr)
    print(f"  Publishers: {dict(publisher_breakdown)}", file=sys.stderr)


if __name__ == "__main__":
    main()
