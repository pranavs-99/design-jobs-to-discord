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
    payload = {
        "content": f"**New design jobs ({len(items)})**",
        "embeds": embeds[:10]  # Discord allows up to 10 embeds per message
    }
    r = requests.post(WEBHOOK, json=payload, timeout=20)
    r.raise_for_status()

if __name__ == "__main__":
    items = gather()
    if items:
        post_to_discord(items)
