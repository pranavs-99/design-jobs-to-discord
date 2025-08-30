import os, time, json, requests, feedparser
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

# ----------------------------
# Sources (public, ToS-friendly)
# ----------------------------
RSS_FEEDS = [
    # Design-heavy boards
    "https://dribbble.com/jobs.rss",
    "https://www.smashingmagazine.com/jobs/feed/",
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
    "https://jobicy.com/feed/job_feed",
    # Remotive (all jobs RSS; we’ll filter by keywords + US)
    "https://remotive.com/feed",
]

JSON_SOURCES = [
    # Remote OK (24h delayed free API; still useful signal)
    "https://remoteok.com/api"
]

# ----------------------------
# Filters
# ----------------------------
KEYWORDS = [
    "ux", "user experience", "product designer", "product design",
    "ui", "user interface", "ui/ux", "interaction designer",
    "web designer", "visual designer", "design intern", "ux intern",
    "ui intern", "product design intern", "internship"
]

# Location filter (USA only)
USA_ONLY = True  # set to False to disable later

US_TERMS = {
    "united states", "u.s.", "u.s.a", "usa", "us only", "us-only",
    "authorized to work in the us", "eligible to work in the us",
    "within the us", "based in the us", "north america"  # include if NA-only is OK
}

US_STATES = [
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada","new hampshire",
    "new jersey","new mexico","new york","north carolina","north dakota","ohio",
    "oklahoma","oregon","pennsylvania","rhode island","south carolina","south dakota",
    "tennessee","texas","utah","vermont","virginia","washington","west virginia",
    "wisconsin","wyoming","district of columbia","washington dc","dc"
]

NON_US_HINTS = [
    "europe","emea","uk","united kingdom","canada","canada only","mexico","latam",
    "apac","australia","new zealand","singapore","india","germany","france","spain",
    "italy","netherlands","sweden","norway","denmark","finland","ireland","switzerland",
    "poland","romania","czech","slovakia","hungary","portugal","belgium","austria",
    "greece","turkey","uae","saudi","qatar","nigeria","south africa","philippines",
    "pakistan","bangladesh","indonesia","vietnam","thailand","japan","korea","china",
    "hong kong","taiwan","malaysia","brazil","argentina","chile","colombia","peru"
]

# Extra US location check for ATS "location" strings (e.g., "New York, NY")
US_HINTS = [
    "united states", "u.s.", "usa", "u.s.a.", "us-based", "us based",
    "anywhere in the us", "united states of america",
    ", AL", ", AK", ", AZ", ", AR", ", CA", ", CO", ", CT", ", DC", ", DE", ", FL", ", GA",
    ", HI", ", IA", ", ID", ", IL", ", IN", ", KS", ", KY", ", LA", ", MA", ", MD", ", ME",
    ", MI", ", MN", ", MO", ", MS", ", MT", ", NC", ", ND", ", NE", ", NH", ", NJ", ", NM",
    ", NV", ", NY", ", OH", ", OK", ", OR", ", PA", ", PR", ", RI", ", SC", ", SD", ", TN",
    ", TX", ", UT", ", VA", ", VT", ", WA", ", WI", ", WV"
]

def is_us_location(text: str) -> bool:
    t = (text or "").lower()
    return any(h.lower() in t for h in US_HINTS)

def is_us_only(text: str) -> bool:
    """Heuristic: include if text explicitly mentions US/USA or any US state.
       Exclude if it mentions non-US-only regions. Unknown => exclude (strict)."""
    t = (text or "").lower()
    if any(h in t for h in NON_US_HINTS):
        return False
    if any(term in t for term in US_TERMS):
        return True
    if any(state in t for state in US_STATES):
        return True
    return False  # strict: if we can't tell, skip

# ----------------------------
# Posting window & limits
# ----------------------------
WINDOW_MINUTES = 1440  # 24 hours for backfill; change to 30 later
MAX_POSTS = 10         # avoid spamming a channel

def now_utc():
    return datetime.now(timezone.utc)

def within_window(dt):
    try:
        return (now_utc() - dt) <= timedelta(minutes=WINDOW_MINUTES)
    except Exception:
        return False

def match_keywords(text):
    t = (text or "").lower()
    return any(k in t for k in KEYWORDS)

# ----------------------------
# Parsers (RSS / JSON)
# ----------------------------
def parse_rss(url):
    out = []
    feed = feedparser.parse(url)
    for e in feed.entries:
        title = e.get("title", "")
        link  = e.get("link", "")
        summ  = e.get("summary", "") or e.get("description", "")
        rawdt = e.get("published") or e.get("updated") or ""
        try:
            dt = dateparser.parse(rawdt)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(timezone.utc)
        except Exception:
            dt = now_utc()  # fallback

        if match_keywords(f"{title} {summ}") and within_window(dt):
            # USA filter for RSS sources (title/summary usually include location)
            if USA_ONLY and not is_us_only(f"{title} {summ}"):
                continue
            out.append({
                "title": title.strip(),
                "url": link,
                "summary": summ,
                "source": url.split("/")[2],
                "published": dt.isoformat()
            })
    return out

def parse_remoteok(url):
    out = []
    try:
        data = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=20).json()
        for item in data:
            if not isinstance(item, dict):
                continue
            title = item.get("position") or item.get("title") or ""
            company = item.get("company") or ""
            link = item.get("url") or item.get("apply_url") or ""
            tags = " ".join(item.get("tags") or [])
            desc = item.get("description") or ""
            text = f"{title} {company} {tags} {desc}"

            # Dates
            rawdt = item.get("date") or item.get("created_at") or ""
            try:
                dt = dateparser.parse(rawdt)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
            except Exception:
                dt = now_utc()

            # USA filter using whatever location hints exist
            loc_blob = " ".join([
                title or "", company or "", tags or "",
                item.get("location","") or "",
                item.get("region","") or "",
                item.get("country","") or "",
                desc or ""
            ])
            if USA_ONLY and not is_us_only(loc_blob):
                continue

            if match_keywords(text) and within_window(dt):
                out.append({
                    "title": f"{title} — {company}".strip(" —"),
                    "url": link or "https://remoteok.com/",
                    "summary": (item.get("description") or "")[:300],
                    "source": "remoteok.com",
                    "published": dt.isoformat()
                })
    except Exception:
        pass
    return out

# ----------------------------
# Company ATS fetchers (optional)
# ----------------------------
def fetch_greenhouse_jobs(board_token: str):
    """Public Greenhouse Job Board API (read-only per company)."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"
    try:
        data = requests.get(url, timeout=20).json()
    except Exception:
        return []
    out = []
    for job in data.get("jobs", []):
        title = job.get("title", "") or ""
        loc   = (job.get("location") or {}).get("name", "") or ""
        link  = job.get("absolute_url")
        desc  = (job.get("content") or "")[:1000]
        if not link:
            continue
        if USA_ONLY and not is_us_location(loc + " " + desc):
            continue
        if not match_keywords(f"{title} {desc}"):
            continue
        out.append({
            "title": f"{title} — {board_token}",
            "url": link,
            "summary": f"{loc}".strip(),
            "source": "Greenhouse",
            "published": now_utc().isoformat(),
        })
    return out

def fetch_lever_jobs(company_slug: str):
    """Public Lever postings JSON per company."""
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    try:
        data = requests.get(url, timeout=20).json()
    except Exception:
        return []
    out = []
    for job in data or []:
        title = job.get("text", "") or ""
        cats  = job.get("categories") or {}
        loc   = cats.get("location", "") or ""
        link  = job.get("hostedUrl") or job.get("applyUrl") or job.get("url")
        desc  = (job.get("descriptionPlain") or job.get("description") or "")[:1000]
        if not link:
            continue
        if USA_ONLY and not is_us_location(loc + " " + desc):
            continue
        if not match_keywords(f"{title} {desc}"):
            continue
        out.append({
            "title": f"{title} — {company_slug}",
            "url": link,
            "summary": f"{loc}".strip(),
            "source": "Lever",
            "published": now_utc().isoformat(),
        })
    return out

# ----------------------------
# Gather everything
# ----------------------------
def gather():
    items = []

    # 1) Public sources
    for f in RSS_FEEDS:
        items += parse_rss(f)
    for j in JSON_SOURCES:
        items += parse_remoteok(j)

    # 2) Company ATS (read from env; empty is fine)
    GH_COMPANIES    = [s.strip() for s in os.getenv("GH_COMPANIES", "").split(",") if s.strip()]
    LEVER_COMPANIES = [s.strip() for s in os.getenv("LEVER_COMPANIES", "").split(",") if s.strip()]

    for token in GH_COMPANIES:
        items += fetch_greenhouse_jobs(token)
    for slug in LEVER_COMPANIES:
        items += fetch_lever_jobs(slug)

    # 3) De-dupe by URL and sort newest first
    dedup = {}
    for i in items:
        if not i.get("url"):
            continue
        dedup[i["url"]] = i
    items = list(dedup.values())
    items.sort(key=lambda x: x.get("published",""), reverse=True)
    return items[:MAX_POSTS]

# ----------------------------
# Discord posting
# ----------------------------
def post_to_discord(items):
    # Always post something so you know it ran
    if not items:
        requests.post(WEBHOOK, json={
            "content": f"No new design jobs in the last {WINDOW_MINUTES} minutes."
        }, timeout=20).raise_for_status()
        return

    embeds = []
    for it in items:
        embeds.append({
            "title": it["title"][:256],
            "url": it["url"],
            "description": (it.get("summary") or "")[:300],
            "timestamp": it.get("published"),
            "footer": {"text": f"{it.get('source','')}"}
        })

    payload = {
        "content": f"**New design jobs ({len(items)})**",
        "embeds": embeds[:10]  # Discord allows up to 10 embeds per message
    }
    requests.post(WEBHOOK, json=payload, timeout=20).raise_for_status()

# ----------------------------
# Entry point
# ----------------------------
if __name__ == "__main__":
    items = gather()
    post_to_discord(items)
