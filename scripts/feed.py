#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Daily FAANG Discuss aggregator (compliant version).
- Uses Google Programmable Search Engine (CSE) to fetch links/snippets.
- Does NOT crawl leetcode.com directly.
- Groups results by company configured in config/companies.json.
- HTML head/footer and CSS are externalized in templates/ and assets/.
"""

import os
import json
import re
import time
import html
from pathlib import Path
from datetime import datetime, timezone
import urllib.parse
import urllib.request
import urllib.error

def detect_project_root() -> Path:
    # 1) explicit CI hint
    ws = os.environ.get("GITHUB_WORKSPACE")
    if ws and Path(ws).exists():
        return Path(ws).resolve()

    # 2) git toplevel if available (works locally & CI)
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
        if top and Path(top).exists():
            return Path(top).resolve()
    except Exception:
        pass

    # 3) fallback: scripts/..
    return Path(__file__).resolve().parent.parent

PROJECT_ROOT = detect_project_root()

def ensure_exists(p: Path, hint: str):
    if not p.exists():
        raise FileNotFoundError(f"Missing file: {p}\nHint: {hint}")

# ---------- config locations ----------
# Allow explicit env overrides
company_cfg_env = os.getenv("COMPANY_CONFIG")
settings_cfg_env = os.getenv("SETTINGS_CONFIG")

COMPANY_FILE = Path(company_cfg_env) if company_cfg_env else (PROJECT_ROOT / "config" / "companies.json")
SETTINGS_FILE = Path(settings_cfg_env) if settings_cfg_env else (PROJECT_ROOT / "config" / "settings.json")

TEMPLATES_DIR = PROJECT_ROOT / "templates"
ASSETS_DIR    = PROJECT_ROOT / "assets"

ensure_exists(COMPANY_FILE,  "Put companies.json under <repo-root>/config/ or set COMPANY_CONFIG env.")
ensure_exists(SETTINGS_FILE, "Put settings.json under <repo-root>/config/ or set SETTINGS_CONFIG env.")
ensure_exists(TEMPLATES_DIR / "head.html", "Missing templates/head.html under <repo-root>/templates/")
ensure_exists(TEMPLATES_DIR / "tail.html", "Missing templates/tail.html under <repo-root>/templates/")
ensure_exists(ASSETS_DIR / "style.css",    "Missing assets/style.css under <repo-root>/assets/")

# -------- Utilities --------
def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def safe_get(d: dict, keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

# -------- Load Config --------
companies_aliases = load_json(COMPANY_FILE)  # e.g., {"Google": ["google", "goog", ...], ...}
settings = load_json(SETTINGS_FILE)

max_results = int(safe_get(settings, ["query", "max_results"], 40))
companies_for_query = safe_get(settings, ["query", "companies"], ["Google","Meta","Amazon","Apple","Netflix","Microsoft"])
intents_for_query = safe_get(settings, ["query", "intents"], ["interview","onsite","phone","screen","OA","questions"])
site_host = safe_get(settings, ["query", "site"], "leetcode.com/discuss")

path_allow_patterns = safe_get(settings, ["filters", "path_allow"], [
    r"^https?://leetcode\.com/discuss/(?:interview-question|study-guide|general-discussion|interview-experience)/"
])
keywords_words = safe_get(settings, ["filters", "keywords"], ["onsite","phone","screen","oa","interview","experience","question","questions"])

company_order = safe_get(settings, ["page", "company_order"], list(companies_aliases.keys()))
page_title = safe_get(settings, ["page", "title"], "FAANG Discuss Daily")
page_noindex = bool(safe_get(settings, ["page", "noindex"], True))

output_json = Path(safe_get(settings, ["output", "json"], "data/latest.json"))
output_html = Path(safe_get(settings, ["output", "html"], "index.html"))

# Build regexes
COMPANY_REGEX = {c: re.compile(r"|".join(map(re.escape, v)), re.I) for c, v in companies_aliases.items()}
PATH_ALLOW = re.compile("|".join(path_allow_patterns), re.I)
KEYWORDS = re.compile(r"\b(" + "|".join(map(re.escape, keywords_words)) + r")\b", re.I)

# Ensure output dir exists
output_json.parent.mkdir(parents=True, exist_ok=True)

# -------- Query Builder / Fetcher --------
def build_query() -> str:
    """
    Build a Google CSE query string using site restriction and company/intents keywords.
    """
    companies = "(" + " OR ".join(companies_for_query) + ")"
    intents = "(" + " OR ".join(intents_for_query) + ")"
    return f"site:{site_host} {companies} {intents}"

def cse_search(q: str, start: int = 1, num: int = 10) -> dict:
    """
    Call Google Custom Search API.
    """
    params = {
        "key": CSE_KEY,
        "cx": CSE_ID,
        "q": q,
        "start": start,
        "num": num,
        "sort": "date",
        "safe": "off",
    }
    url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def detect_company(text: str):
    """
    Detect company by alias regex matches on title/snippet/link.
    """
    for c, rx in COMPANY_REGEX.items():
        if rx.search(text or ""):
            return c
    return None

def fetch_items() -> list:
    """
    Fetch and filter items from CSE, then deduplicate.
    """
    q = build_query()
    items = []
    start = 1

    while len(items) < max_results and start <= 91:
        try:
            data = cse_search(q, start=start, num=10)
        except urllib.error.HTTPError as e:
            print("HTTPError:", e.read())
            break
        except Exception as e:
            print("Fetch error:", e)
            break

        for it in data.get("items", []):
            link = it.get("link", "")
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
        time.sleep(0.6)  # polite throttling

        if len(items) >= max_results:
            break
        if data.get("searchInformation", {}).get("totalResults") == "0":
            break

    # Deduplicate by URL
    seen, dedup = set(), []
    for it in items:
        u = it["url"]
        if u in seen:
            continue
        seen.add(u)
        dedup.append(it)

    return dedup[:max_results]

# -------- Writers --------
def write_json(items: list):
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(items),
        "items": items
    }
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[ok] wrote {output_json}")

def build_html(items: list) -> str:
    """
    Assemble HTML by stitching head.html + body content + tail.html.
    Company sections are rendered in code; style lives in assets/style.css.
    """
    # Head
    head_tpl = read_text(TEMPLATES_DIR / "head.html")
    head = head_tpl.replace("{{PAGE_TITLE}}", html.escape(page_title))
    if page_noindex:
        # Inject noindex meta if not already present
        if "name=\"robots\"" not in head:
            head = head.replace("</head>", '  <meta name="robots" content="noindex,nofollow">\n</head>')

    # Body header
    updated_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    body_top = []
    body_top.append(f"<h1>{html.escape(page_title)}</h1>")
    body_top.append(f"<div class='time'>Updated at {html.escape(updated_iso)}</div>")

    # Group by company
    groups = {}
    for it in items:
        groups.setdefault(it["company"], []).append(it)

    # Render sections in company_order
    sections = []
    for company in company_order:
        lst = groups.get(company, [])
        if not lst:
            continue
        sections.append(f"<h2><span class='tag'>{html.escape(company)}</span></h2>")
        sections.append("<div class='grid'>")
        for it in lst:
            title = html.escape(it["title"])
            url = html.escape(it["url"])
            snippet = html.escape(it.get("snippet", ""))
            sections.append(
                "<div class='card'>"
                f"<div class='item-title'><a href='{url}' target='_blank' rel='noopener'>{title}</a></div>"
                f"<div class='snippet'>{snippet}</div>"
                "</div>"
            )
        sections.append("</div>")

    # Footer
    tail_tpl = read_text(TEMPLATES_DIR / "tail.html")

    html_doc = head + "\n<body>\n" + "\n".join(body_top) + "\n" + "\n".join(sections) + "\n" + tail_tpl
    return html_doc

def write_html(items: list):
    html_doc = build_html(items)
    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"[ok] wrote {output_html}")

# -------- Main --------
def main():
    items = fetch_items()
    write_json(items)
    write_html(items)

if __name__ == "__main__":
    main()
