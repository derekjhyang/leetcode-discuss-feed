#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, time, re, html
from datetime import datetime, timezone
import urllib.parse
import urllib.request

CSE_ID  = os.environ["CSE_ID"]
CSE_KEY = os.environ["CSE_KEY"]
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "40"))
OUTPUT_JSON = "data/latest.json"
OUTPUT_HTML = "index.html"

COMPANY_ALIASES = {
    "Google": ["google", "goog", "alphabet"],
    "Meta": ["meta", "facebook", "fb"],
    "Amazon": ["amazon", "aws", "amzn"],
    "Apple": ["apple"],
    "Netflix": ["netflix", "nflx"],
    "Microsoft": ["microsoft", "msft"],
}
COMPANY_REGEX = {c: re.compile(r"|".join(map(re.escape, v)), re.I) for c, v in COMPANY_ALIASES.items()}

PATH_ALLOW = re.compile(
    r"^https?://leetcode\.com/discuss/(?:interview-question|study-guide|general-discussion|interview-experience)/",
    re.I
)
KEYWORDS = re.compile(r"\b(onsite|phone|screen|oa|interview|experience|questions?)\b", re.I)

def google_cse_search(q, start=1, num=10):
    params = {"key": CSE_KEY, "cx": CSE_ID, "q": q, "start": start, "num": num, "sort": "date", "safe": "off"}
    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def detect_company(text):
    for c, rx in COMPANY_REGEX.items():
        if rx.search(text or ""):
            return c
    return None

def build_query():
    companies = "(Google OR Meta OR Amazon OR Apple OR Netflix OR Microsoft)"
    intents = "(interview OR onsite OR phone OR screen OR OA OR questions)"
    return f'site:leetcode.com/discuss {companies} {intents}'

def fetch_all():
    q = build_query()
    items, start = [], 1
    while len(items) < MAX_RESULTS and start <= 31:
        data = google_cse_search(q, start=start, num=10)
        for it in data.get("items", []):
            link = it.get("link")
            title = it.get("title", "")
            snippet = it.get("snippet", "")
            if not link or not PATH_ALLOW.search(link):
                continue
            combo = f"{title} {snippet} {link}"
            if not KEYWORDS.search(combo):
                continue
            company = detect_company(combo)
            if not company:
                continue
            items.append({
                "title": title,
                "url": link,
                "snippet": snippet,
                "company": company,
                "first_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
        start += 10
        time.sleep(0.7)
        if len(items) >= MAX_RESULTS: break
        if data.get("searchInformation", {}).get("totalResults") == "0": break

    seen, dedup = set(), []
    for it in items:
        if it["url"] in seen: 
            continue
        seen.add(it["url"])
        dedup.append(it)
    return dedup[:MAX_RESULTS]

def write_json(items):
    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(items),
            "items": items
        }, f, ensure_ascii=False, indent=2)

def write_html(items):
    groups = {}
    for it in items:
        groups.setdefault(it["company"], []).append(it)
    order = ["Google", "Meta", "Amazon", "Apple", "Netflix", "Microsoft"]
    parts = []
    parts.append("""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FAANG Discuss Daily</title>
<style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Cantarell,'Noto Sans',sans-serif;background:#0b1020;color:#e9ecf1;margin:0;padding:24px}
h1{font-size:24px;margin:0 0 12px}
.time{opacity:.7;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px}
.card{background:#121936;border:1px solid #243058;border-radius:14px;padding:14px;box-shadow:0 2px 8px rgba(0,0,0,.25)}
.tag{display:inline-block;font-size:12px;padding:3px 8px;border-radius:999px;background:#243058;margin-right:6px}
a{color:#a4c2ff;text-decoration:none}
a:hover{text-decoration:underline}
h2{font-size:18px;margin:22px 0 10px}
.item-title{font-weight:600;margin:0 0 6px;font-size:15px;line-height:1.35}
.snippet{opacity:.85;font-size:13px;line-height:1.4}
.footer{opacity:.6;margin-top:20px;font-size:12px}
</style><body>""")
    parts.append("<h1>FAANG Discuss – Latest Links</h1>")
    parts.append(f"<div class='time'>Updated at {html.escape(datetime.now().isoformat(timespec='seconds'))}</div>")
    for company in order:
        if company not in groups: 
            continue
        parts.append(f"<h2><span class='tag'>{company}</span></h2>")
        parts.append("<div class='grid'>")
        for it in groups[company]:
            parts.append(
                "<div class='card'>"
                f"<div class='item-title'><a href='{html.escape(it['url'])}' target='_blank' rel='noopener'>{html.escape(it['title'])}</a></div>"
                f"<div class='snippet'>{html.escape(it.get('snippet',''))}</div>"
                "</div>"
            )
        parts.append("</div>")
    parts.append("<div class='footer'>Source via Google Programmable Search • Links point to leetcode.com/discuss</div>")
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

def main():
    items = fetch_all()
    write_json(items)
    write_html(items)
    print(f"Generated {len(items)} items.")

if __name__ == "__main__":
    main()
