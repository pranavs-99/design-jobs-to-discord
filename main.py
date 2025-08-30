import os, time, json, requests, feedparser
from datetime import datetime, timezone, timedelta
from dateutil import parser as dateparser

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

# Public, ToS-friendly sources
RSS_FEEDS = [
    # Dribbble Jobs (all design roles)
    "https://dribbble.com/jobs.rss",
    # We Work Remotely – design category
    "https://weworkremotely.com/categories/remote-design-jobs.rss",
]
JSON_SOURCES = [
    # Remote OK (24h delayed free API; still useful signal)
    "https://remoteok.com/api"
]

KEYWORDS = [
    "ux", "user experience", "product designer", "product design",
    "ui", "user interface", "ui/ux", "interaction designer",
    "web designer", "visual designer", "design intern", "ux intern",
    "ui intern", "product design intern", "internship"
]
# --- Location filter (USA only) ---
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

def is_us_only(text: str) -> bool:
    """Heuristic: include if the text explicitly mentions US/USA or any US state.
       Exclude if it mentions non-US-only regions. Unknown => exclude (strict)."""
    t = (text or "").lower()
    # Negative hints first: if it says EU/UK/Canada-only etc., drop it.
    if any(h in t for h in NON_US_HINTS):
        return False
    # Positive hints: United States or any state name
    if any(term in t for term in US_TERMS):
        return True
    if any(state in t for state in US_STATES):
        return True
    return False  # strict: if we can't tell, skip

WINDOW_MINUTES = 30   # only post items published in the last N minutes
MAX_POSTS = 8         # avoid spamming a channel

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
            # skip non-job entries that sometimes appear at index 0
            if not isinstance(item, dict): 
                continue
            title = item.get("position") or item.get("title") or ""
            company = item.get("company") or ""
            link = item.get("url") or item.get("apply_url") or ""
            tags = " ".join(item.get("tags") or [])
            desc = item.get("description") or ""
            text = f"{title} {company} {tags} {desc}"
            # Dates: RemoteOK provides 'date' string; attempt parse
            rawdt = item.get("date") or item.get("created_at") or ""
            try:
                dt = dateparser.parse(rawdt)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt = dt.astimezone(timezone.utc)
            except Exception:
                dt = now_utc()
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

def gather():
    items = []
    for f in RSS_FEEDS:
        items += parse_rss(f)
    for j in JSON_SOURCES:
        items += parse_remoteok(j)
    # de-dupe by URL
    dedup = {}
    for i in items:
        dedup[i["url"]] = i
    items = list(dedup.values())
    # sort newest first
    items.sort(key=lambda x: x["published"], reverse=True)
    return items[:MAX_POSTS]

def post_to_discord(items):
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
            "description": (it["summary"] or "")[:300],
            "timestamp": it["published"],
            "footer": {"text": f"{it['source']}"},
        })
    payload = {"content": f"**New design jobs ({len(items)})**","embeds": embeds[:10]}
    requests.post(WEBHOOK, json=payload, timeout=20).raise_for_status()


if __name__ == "__main__":
    items = gather()
    if items:
        post_to_discord(items)
