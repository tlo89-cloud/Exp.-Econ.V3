"""
Experience Economy Map — Daily News Scraper v2
Runs at 7am EST (12:00 UTC) via GitHub Actions.

Improvements over v1:
- 25+ sources including NYT Arts, Rolling Stone, Pitchfork, LA Times
- Cultural signal detection (album announcements, tours, surprise appearances)
- Smarter scoring with moment-type detection
- Less aggressive noise filtering
- Better company/entity extraction
"""

import feedparser
import json
import os
import re
import hashlib
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from urllib.error import URLError
import ssl

# ── CONFIGURATION ─────────────────────────────────────────────────────

OUTPUT_FILE = "events.json"
MAX_EVENTS = 60
MAX_PER_LAYER = 8
MIN_SCORE = 3

# ── NEWS SOURCES ──────────────────────────────────────────────────────

SOURCES = [
    # ── Tier 1: Sports & Entertainment Business (core) ────────────────
    {"url": "https://www.sportico.com/feed/",                        "name": "Sportico"},
    {"url": "https://www.sportsbusinessjournal.com/rss.aspx",        "name": "SBJ"},
    {"url": "https://frontofficesports.com/feed/",                   "name": "Front Office Sports"},
    {"url": "https://www.theathletic.com/rss/",                      "name": "The Athletic"},

    # ── Tier 2: Music & Live Entertainment ───────────────────────────
    {"url": "https://www.billboard.com/feed/",                       "name": "Billboard"},
    {"url": "https://variety.com/v/music/feed/",                     "name": "Variety Music"},
    {"url": "https://variety.com/v/biz/feed/",                       "name": "Variety Biz"},
    {"url": "https://pollstar.com/rss/news",                         "name": "Pollstar"},
    {"url": "https://www.rollingstone.com/music/feed/",              "name": "Rolling Stone Music"},
    {"url": "https://www.rollingstone.com/music/music-news/feed/",   "name": "Rolling Stone News"},
    {"url": "https://pitchfork.com/rss/news/feed/oid.xml",           "name": "Pitchfork News"},
    {"url": "https://www.musicweek.com/rss",                         "name": "Music Week"},
    {"url": "https://www.nme.com/news/music/feed",                   "name": "NME"},
    {"url": "https://www.loudwire.com/feed/",                        "name": "Loudwire"},

    # ── Tier 3: Culture & Arts (where Coachella/NYT live) ────────────
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Arts.xml",         "name": "NYT Arts"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Music.xml",        "name": "NYT Music"},
    {"url": "https://rss.nytimes.com/services/xml/rss/nyt/Sports.xml",       "name": "NYT Sports"},
    {"url": "https://www.latimes.com/entertainment-arts/music/rss2.0.xml",   "name": "LA Times Music"},
    {"url": "https://www.latimes.com/sports/rss2.0.xml",                     "name": "LA Times Sports"},
    {"url": "https://www.theguardian.com/music/rss",                         "name": "Guardian Music"},
    {"url": "https://www.theguardian.com/sport/rss",                         "name": "Guardian Sport"},
    {"url": "https://www.vulture.com/music/rss",                             "name": "Vulture Music"},

    # ── Tier 4: Finance / Deals / PE ──────────────────────────────────
    {"url": "https://pitchbook.com/news/rss",                        "name": "PitchBook"},
    {"url": "https://www.pehub.com/feed/",                           "name": "PE Hub"},
    {"url": "https://www.wsj.com/xml/rss/3_7085.xml",                "name": "WSJ Sports"},
    {"url": "https://www.wsj.com/xml/rss/3_7014.xml",                "name": "WSJ Biz"},

    # ── Tier 5: Venue & Infrastructure ────────────────────────────────
    {"url": "https://www.venuestoday.com/rss",                       "name": "Venues Today"},
    {"url": "https://stadiumsarenas.com/feed/",                      "name": "Stadiums & Arenas"},

    # ── Tier 6: Ticketing & Distribution ──────────────────────────────
    {"url": "https://www.ticketnews.com/feed/",                      "name": "Ticket News"},
    {"url": "https://www.broadwayworld.com/rss/news.cfm",            "name": "Broadway World"},

    # ── Tier 7: Tech & Data ────────────────────────────────────────────
    {"url": "https://www.sporttechie.com/feed/",                     "name": "Sport Techie"},
]

# ── MOMENT TYPES ──────────────────────────────────────────────────────
# High-signal event types that are always relevant to the Experience Economy
# Each detected moment adds +4 to the score

MOMENT_PATTERNS = {
    "album_announcement":   [r"announces? (?:new )?album", r"new album", r"dropping .+ album", r"album (?:out|release|date)"],
    "tour_announcement":    [r"announces? (?:world )?tour", r"announces? (?:concert|stadium) tour", r"tour dates", r"going on tour"],
    "surprise_appearance":  [r"surprise (?:guest|appearance|set|performance)", r"brings? out", r"joins? .+ on stage", r"special guest"],
    "record_deal":          [r"signs? (?:with|to) .+(?:records?|label|music)", r"record deal", r"label deal"],
    "acquisition":          [r"acquires?|acquired|acquisition|merges?|merger"],
    "funding_round":        [r"raises? \$[\d\.]+[bm]", r"series [a-d] funding", r"raises? .+ million", r"raises? .+ billion"],
    "valuation":            [r"valued at \$", r"\$[\d\.]+[bm] valuation", r"valuation of \$"],
    "rights_deal":          [r"media rights", r"broadcast rights", r"streaming rights", r"tv deal", r"rights deal"],
    "ipo":                  [r"\bipo\b", r"goes public", r"public offering", r"stock listing"],
    "venue_announcement":   [r"new (?:stadium|arena|venue)", r"stadium (?:deal|plan|project|opens?)", r"arena (?:deal|plan|opens?)"],
    "festival_headliner":   [r"headlin(?:es?|ing)", r"festival (?:lineup|headliner)", r"coachella|glastonbury|lollapalooza|bonnaroo|acl"],
    "record_breaking":      [r"record-breaking|sets? record|highest.grossing|most.watched|largest ever|all.time high"],
    "pe_investment":        [r"private equity", r"pe (?:firm|fund|investment)", r"institutional investor"],
    "streaming_milestone":  [r"billion streams?", r"million listeners?", r"spotify|apple music.+record"],
}

# ── KEYWORD SCORING ───────────────────────────────────────────────────

HIGH_VALUE = [
    # Business events (+3)
    "acquisition", "acquires", "merger", "valuation", "funding",
    "raises", "series a", "series b", "series c", "ipo", "goes public",
    "private equity", "investment", "media rights", "rights deal",
    "billion", "stadium", "arena", "venue", "franchise", "ownership",
    "partnership", "expansion", "antitrust", "doj", "lawsuit",
    # Live entertainment business (+3)
    "tour", "touring", "concert", "festival", "headline", "headlining",
    "ticket sales", "sold out", "gross", "grossed", "revenue",
    "streaming deal", "broadcast", "record deal", "label",
    "album", "release", "drops", "announcement",
]

LAYER_KEYWORDS = {
    1: [  # Content & IP
        "nfl", "nba", "mlb", "nhl", "mls", "premier league", "formula one", "f1",
        "ufc", "wwe", "tko", "wnba", "nwsl", "sports franchise", "league",
        "music rights", "touring", "artist", "concert", "festival",
        "coachella", "glastonbury", "lollapalooza", "bonnaroo",
        "spotify", "universal music", "warner music", "sony music",
        "record label", "album", "tour announcement",
        "sports ip", "media rights", "broadcast rights", "streaming rights",
        "arctos", "redbird", "sixth street", "ares management", "liberty media",
        "comedy", "theater", "broadway", "immersive",
        "madonna", "taylor swift", "beyonce",  # major artists as signals
        "surprise guest", "surprise appearance", "brings out",
    ],
    2: [  # Physical Infrastructure
        "stadium", "arena", "venue", "sphere entertainment", "cosm",
        "topgolf", "puttshack", "competitive socializing", "theme park",
        "disney parks", "universal studios", "six flags", "oak view group",
        "legends global", "aeg", "msg entertainment", "intuit dome",
        "mixed-use", "entertainment district", "real estate", "development",
        "rebuild", "renovation", "new arena", "new stadium",
        "meow wolf", "immersive venue", "festival grounds",
    ],
    3: [  # Operators & Distribution
        "live nation", "ticketmaster", "aeg presents", "ticketing",
        "stubhub", "seatgeek", "viagogo", "secondary market",
        "netflix", "amazon prime", "apple tv", "espn",
        "dazn", "streaming deal", "broadcast", "discovery",
        "fever", "eventbrite", "bandsintown",
        "doj", "antitrust", "ticket fees", "junk fees",
        "promoter", "concert promotion",
    ],
    4: [  # Service Providers
        "caa", "wme", "uta", "talent agency", "representation",
        "learfield", "playfly", "college sports rights",
        "on location", "hospitality", "premium seating", "vip",
        "aramark", "sodexo", "delaware north",
        "tait", "nep group", "prg", "production", "staging",
        "sponsorship", "two circles", "sportfive", "nielsen sports",
        "wasserman", "octagon", "img",
    ],
    5: [  # Technology Enablers
        "sportradar", "genius sports", "hawk-eye", "betting data",
        "sports betting", "wagering", "sportsbook", "kambi",
        "fan engagement", "fan app", "venue technology", "smart stadium",
        "wicket", "biometric", "facial recognition",
        "greenfly", "content technology", "broadcast technology",
        "fanatics", "merchandise",
        "sports analytics", "data platform", "ai sports",
        "appetize", "pos", "mobile ordering", "venue software",
    ],
}

# Noise filters — much more targeted than v1, only true noise
NOISE_KEYWORDS = [
    "injury report", "day-to-day", "out for season",
    "fantasy football", "fantasy baseball", "fantasy points",
    "betting odds", "point spread", "over/under",
    "mock draft", "nfl draft picks", "prospect ranking",
    "power rankings", "how to watch", "stream free",
    "recipe", "horoscope", "crossword",
]

ACCESS_HINTS = {
    "public":  ["nyse", "nasdaq", "stock", "shares", "public company", "publicly traded", "earnings"],
    "pe":      ["private equity", "pe firm", "buyout", "acquisition", "family office", "institutional"],
    "venture": ["venture", "series a", "series b", "series c", "seed round", "startup", "vc"],
}

# ── SCORING ENGINE ────────────────────────────────────────────────────

def detect_moments(text):
    """Detect high-signal moment types. Returns list of detected moments."""
    detected = []
    text_lower = text.lower()
    for moment_type, patterns in MOMENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text_lower):
                detected.append(moment_type)
                break  # one match per type is enough
    return detected


def score_article(title, summary=""):
    """Score an article for relevance. Returns (score, layer, access, moments)."""
    text = (title + " " + summary).lower()

    # Instant disqualify — noise
    for noise in NOISE_KEYWORDS:
        if noise in text:
            return -10, 0, "pe", []

    score = 0

    # Moment detection (+4 per moment)
    moments = detect_moments(text)
    score += len(moments) * 4

    # High-value business keywords (+3 each, capped at 5)
    hv_matches = sum(1 for kw in HIGH_VALUE if kw in text)
    score += min(hv_matches, 5) * 3

    # Layer matching (+2 each)
    layer_scores = {}
    for layer, keywords in LAYER_KEYWORDS.items():
        layer_score = sum(2 for kw in keywords if kw in text)
        if layer_score > 0:
            layer_scores[layer] = layer_score
        score += layer_score

    best_layer = max(layer_scores, key=layer_scores.get) if layer_scores else 0

    # Access type detection
    access = "pe"
    for atype, hints in ACCESS_HINTS.items():
        if any(h in text for h in hints):
            access = atype
            break

    return score, best_layer, access, moments


def clean_text(text, max_len=130):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(' ', 1)[0] + '...'
    return text


def extract_company(title):
    """Extract the primary entity/company from article title."""
    patterns = [
        # "Company raises $X" or "Company acquires Y"
        r'^([A-Z][A-Za-z0-9\s&\'\.\-]+?)\s+(?:raises?|acquires?|launches?|signs?|announces?|closes?|opens?|joins?|brings? out)',
        # "Company: headline"
        r'^([A-Z][A-Za-z0-9\s&\'\.\-]+?):',
        # Known entities in title
    ]
    for pattern in patterns:
        match = re.match(pattern, title)
        if match:
            company = match.group(1).strip().rstrip('.,')
            if 2 < len(company) < 45:
                return company

    # Fallback: extract first proper noun cluster
    words = title.split()
    caps = []
    for word in words[:6]:
        clean = re.sub(r'[^\w]', '', word)
        if clean and clean[0].isupper() and len(clean) > 1:
            caps.append(word.rstrip('.,'))
        elif caps:
            break
    if caps and len(' '.join(caps)) < 45:
        return ' '.join(caps)

    return ""


def format_date(entry):
    try:
        if hasattr(entry, 'published_parsed') and entry.published_parsed:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.strftime("%b %d, %y")
    except Exception:
        pass
    return datetime.now(timezone.utc).strftime("%b %d, %y")


def article_id(title, url):
    key = (title + url).encode('utf-8')
    return hashlib.md5(key).hexdigest()[:12]

# ── FETCHING ──────────────────────────────────────────────────────────

def fetch_feed(source):
    articles = []
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        req = Request(
            source["url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; ExperienceEconBot/2.0)"}
        )
        raw = urlopen(req, context=ctx, timeout=15).read()
        feed = feedparser.parse(raw)

        for entry in feed.entries[:40]:
            title = clean_text(getattr(entry, 'title', ''), 150)
            summary = clean_text(
                getattr(entry, 'summary', '') or getattr(entry, 'description', ''), 400
            )
            link = getattr(entry, 'link', '')

            if not title:
                continue

            score, layer, access, moments = score_article(title, summary)

            if score >= MIN_SCORE and layer > 0:
                articles.append({
                    "id": article_id(title, link),
                    "title": title,
                    "summary": summary[:200] if summary else "",
                    "company": extract_company(title),
                    "link": link,
                    "date": format_date(entry),
                    "source": source["name"],
                    "layer": layer,
                    "access": access,
                    "score": score,
                    "moments": moments,
                })

        if articles:
            print(f"  ✓ {source['name']}: {len(articles)} signals")
        else:
            print(f"  · {source['name']}: 0 signals")

    except URLError as e:
        print(f"  ✗ {source['name']}: {e.reason if hasattr(e, 'reason') else e}")
    except Exception as e:
        print(f"  ✗ {source['name']}: {type(e).__name__}")

    return articles

# ── MAIN ──────────────────────────────────────────────────────────────

def run():
    print(f"\n=== Experience Economy Scraper v2 — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    def dedupe_articles(articles):
        """
        Remove duplicates.
        Prefer the highest-signal version (more moments, higher score).
        Dedupe primarily by link (stable), falling back to id.
        """
        best_by_key = {}
        for a in articles:
            key = (a.get("link") or "").strip() or a["id"]
            prev = best_by_key.get(key)
            if not prev:
                best_by_key[key] = a
                continue

            prev_rank = (len(prev.get("moments", [])), prev.get("score", 0))
            a_rank = (len(a.get("moments", [])), a.get("score", 0))
            if a_rank > prev_rank:
                best_by_key[key] = a

        return list(best_by_key.values())

    # Build a fresh snapshot each run (prevents stale metadata like month-only dates)
    existing = []
    existing_ids = set()

    # Fetch all sources
    print("Fetching sources...")
    all_articles = []
    for source in SOURCES:
        articles = fetch_feed(source)
        all_articles.extend(articles)

    print(f"\nTotal relevant articles (pre-dedupe): {len(all_articles)}")
    all_articles = dedupe_articles(all_articles)
    print(f"Total relevant articles (post-dedupe): {len(all_articles)}")

    # Deduplicate against existing
    new_articles = [a for a in all_articles if a["id"] not in existing_ids]
    print(f"New articles: {len(new_articles)}")

    # Sort: moments first (highest signal), then by score
    new_articles.sort(key=lambda x: (len(x.get('moments', [])), x['score']), reverse=True)

    # Print top 10 for visibility in Actions logs
    print("\nTop signals today:")
    for a in new_articles[:10]:
        moments_str = f" [{', '.join(a['moments'])}]" if a.get('moments') else ""
        print(f"  [{a['score']}] L{a['layer']} {a['source']}: {a['title'][:80]}{moments_str}")

    # Cap per layer
    layer_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    filtered = []
    for article in new_articles:
        layer = article["layer"]
        if layer_counts.get(layer, 0) < MAX_PER_LAYER:
            filtered.append(article)
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

    print(f"\nAfter per-layer cap: {len(filtered)} new events")

    # Merge and trim
    combined = filtered + existing
    combined = dedupe_articles(combined)
    combined = combined[:MAX_EVENTS]

    output = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "total": len(combined),
        "scraped": combined
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n✅ Wrote {len(combined)} total events to {OUTPUT_FILE}")
    print("=== Done ===\n")


if __name__ == "__main__":
    run()
