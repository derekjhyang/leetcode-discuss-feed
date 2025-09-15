#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FAANG Discuss aggregator (compliant, refactored).
- NO direct scraping of LeetCode pages. Uses Google CSE result links/snippets only.
- Clear separation of concerns:
  * Config: project root detection, config loading, paths, env.
  * Fetcher: build query, call CSE, filter, dedup.
  * Renderer: write randomized JSON (hidden), manifest, and HTML (tabs by company).
- JSON path is randomized in both directory and filename: data/<token>/<token>.json
  * If JSON_SALT is set and json_daily_stable=true, token is stable per UTC-day.
  * Otherwise, token is random per run.
- The HTML page does NOT link or expose the JSON path. A small manifest (data/manifest.json)
  is written for ops/automation to discover the latest JSON path.
"""

from __future__ import annotations

import os
import re
import json
import html
import time
import hashlib
import secrets
import string
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Dict, List, Any


# =====================================================================
# Utilities
# =====================================================================

def die_missing(path: Path, hint: str) -> None:
    """Fail fast with clear error message when a required file is missing."""
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}\nHint: {hint}")

def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path: Path) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)

def now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# =====================================================================
# Config
# =====================================================================

@dataclass(frozen=True)
class Config:
    project_root: Path
    companies_cfg: Path
    settings_cfg: Path
    templates_dir: Path
    assets_dir: Path

    companies_aliases: Dict[str, List[str]]
    settings: Dict[str, Any]

    # derived settings / env
    cse_id: str
    cse_key: str
    page_title: str
    page_noindex: bool
    company_order: List[str]

    site_host: str
    max_results: int
    q_companies: List[str]
    q_intents: List[str]

    allow_patterns: List[str]
    keyword_words: List[str]

    output_html: Path
    manifest_path: Path
    json_randomize: bool
    json_daily_stable: bool
    json_salt: str

    @staticmethod
    def detect_project_root() -> Path:
        """Robust project-root detection for both local and CI."""
        ws = os.environ.get("GITHUB_WORKSPACE")
        if ws and Path(ws).exists():
            return Path(ws).resolve()
        try:
            top = subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stderr=subprocess.DEVNULL
            ).decode().strip()
            if top and Path(top).exists():
                return Path(top).resolve()
        except Exception:
            pass
        return Path(__file__).resolve().parent.parent

    @classmethod
    def load(cls) -> "Config":
        root = cls.detect_project_root()

        companies_cfg = Path(os.getenv("COMPANY_CONFIG", root / "config" / "companies.json"))
        settings_cfg  = Path(os.getenv("SETTINGS_CONFIG", root / "config" / "settings.json"))
        templates_dir = root / "templates"
        assets_dir    = root / "assets"

        die_missing(companies_cfg, "Put companies.json under <repo-root>/config/ or set COMPANY_CONFIG env.")
        die_missing(settings_cfg,  "Put settings.json under <repo-root>/config/ or set SETTINGS_CONFIG env.")
        die_missing(templates_dir / "head.html", "Missing templates/head.html under <repo-root>/templates/")
        die_missing(templates_dir / "tail.html", "Missing templates/tail.html under <repo-root>/templates/")
        die_missing(assets_dir / "style.css",    "Missing assets/style.css under <repo-root>/assets/")

        companies_aliases = read_json(companies_cfg)
        settings = read_json(settings_cfg)

        cse_id  = os.environ["CSE_ID"]
        cse_key = os.environ["CSE_KEY"]

        page_title   = settings.get("page", {}).get("title", "FAANG Discuss Daily")
        page_noindex = bool(settings.get("page", {}).get("noindex", True))
        company_order = settings.get("page", {}).get("company_order", list(companies_aliases.keys()))

        site_host   = settings.get("query", {}).get("site", "leetcode.com/discuss")
        max_results = int(settings.get("query", {}).get("max_results", 40))
        q_companies = settings.get("query", {}).get("companies", list(companies_aliases.keys()))
        q_intents   = settings.get("query", {}).get("intents", ["interview","onsite","phone","screen","OA","questions"])

        allow_patterns = settings.get("filters", {}).get("path_allow", [
            r"^https?://leetcode\.com/discuss/(?:interview-question|study-guide|general-discussion|interview-experience)/"
        ])
        keyword_words  = settings.get("filters", {}).get("keywords", [
            "onsite","phone","screen","oa","interview","experience","question","questions"
        ])

        output_html     = root / Path(settings.get("output", {}).get("html", "index.html"))
        manifest_path   = root / Path(settings.get("output", {}).get("json_manifest", "data/manifest.json"))
        json_randomize  = bool(settings.get("output", {}).get("json_randomize", True))
        json_daily_stable = bool(settings.get("output", {}).get("json_daily_stable", True))
        json_salt       = os.getenv("JSON_SALT", "")

        output_html.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=root,
            companies_cfg=companies_cfg,
            settings_cfg=settings_cfg,
            templates_dir=templates_dir,
            assets_dir=assets_dir,
            companies_aliases=companies_aliases,
            settings=settings,
            cse_id=cse_id,
            cse_key=cse_key,
            page_title=page_title,
            page_noindex=page_noindex,
            company_order=company_order,
            site_host=site_host,
            max_results=max_results,
            q_companies=q_companies,
            q_intents=q_intents,
            allow_patterns=allow_patterns,
            keyword_words=keyword_words,
            output_html=output_html,
            manifest_path=manifest_path,
            json_randomize=json_randomize,
            json_daily_stable=json_daily_stable,
            json_salt=json_salt,
        )


# =====================================================================
# Fetcher
# =====================================================================

@dataclass
class Fetcher:
    cfg: Config

    def _build_query(self) -> str:
        companies = "(" + " OR ".join(self.cfg.q_companies) + ")"
        intents   = "(" + " OR ".join(self.cfg.q_intents)   + ")"
        return f"site:{self.cfg.site_host} {companies} {intents}"

    def _cse(self, q: str, start: int = 1, num: int = 10) -> Dict[str, Any]:
        params = {
            "key": self.cfg.cse_key,
            "cx": self.cfg.cse_id,
            "q": q,
            "start": start,
            "num": num,
            "sort": "date",
            "safe": "off",
        }
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def fetch(self) -> List[Dict[str, Any]]:
        company_rx = {c: re.compile(r"|".join(map(re.escape, v)), re.I)
                      for c, v in self.cfg.companies_aliases.items()}
        allow_rx   = re.compile("|".join(self.cfg.allow_patterns), re.I)
        keywords_rx = re.compile(r"\b(" + "|".join(map(re.escape, self.cfg.keyword_words)) + r")\b", re.I)

        def detect_company(text: str | None) -> str | None:
            s = text or ""
            for c, rx in company_rx.items():
                if rx.search(s):
                    return c
            return None

        q = self._build_query()
        items: List[Dict[str, Any]] = []
        start = 1

        while len(items) < self.cfg.max_results and start <= 91:
            try:
                data = self._cse(q, start=start, num=10)
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
                if not link or not allow_rx.search(link):
                    continue
                combo = f"{title} {snippet} {link}"
                if not keywords_rx.search(combo):
                    continue
                company = detect_company(combo)
                if not company:
                    continue
                items.append({
                    "title": title,
                    "url": link,
                    "snippet": snippet,
                    "company": company,
                    "first_seen": now_iso_utc(),
                })

            start += 10
            time.sleep(0.6)
            if len(items) >= self.cfg.max_results:
                break
            if data.get("searchInformation", {}).get("totalResults") == "0":
                break

        seen, dedup = set(), []
        for it in items:
            u = it["url"]
            if u in seen:
                continue
            seen.add(u)
            dedup.append(it)
        return dedup[: self.cfg.max_results]


# =====================================================================
# Renderer
# =====================================================================

@dataclass
class Renderer:
    cfg: Config

    def _daily_token(self) -> str:
        """Stable per UTC day if JSON_SALT is set; otherwise random per run."""
        if not self.cfg.json_salt:
            alphabet = string.ascii_lowercase + string.digits
            return "".join(secrets.choice(alphabet) for _ in range(16))
        payload = f"{date.today().isoformat()}::{self.cfg.json_salt}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]

    def compute_json_path(self) -> Path:
        if not self.cfg.json_randomize:
            p = self.cfg.project_root / "data" / "latest.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        token = self._daily_token() if self.cfg.json_daily_stable else self._daily_token()
        p = self.cfg.project_root / "data" / token / f"{token}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def write_json_and_manifest(self, items: List[Dict[str, Any]]) -> Path:
        json_abs = self.compute_json_path()
        write_json_atomic(json_abs, {
            "updated_at": now_iso_utc(),
            "count": len(items),
            "items": items
        })
        print(f"[ok] wrote JSON {json_abs}")

        manifest_payload = {
            "updated_at": now_iso_utc(),
            "json_path": str(json_abs.relative_to(self.cfg.project_root).as_posix()),
            "count": len(items)
        }
        write_json_atomic(self.cfg.manifest_path, manifest_payload)
        print(f"[ok] wrote manifest {self.cfg.manifest_path} → {manifest_payload['json_path']}")
        return json_abs

    def _build_html(self, items: List[Dict[str, Any]]) -> str:
        head_tpl = read_text(self.cfg.templates_dir / "head.html")
        head = head_tpl.replace("{{PAGE_TITLE}}", html.escape(self.cfg.page_title))
        if self.cfg.page_noindex and 'name="robots"' not in head:
            head = head.replace("</head>", '  <meta name="robots" content="noindex,nofollow">\n</head>')

        parts: List[str] = []
        parts.append(f"<h1>{html.escape(self.cfg.page_title)}</h1>")
        parts.append(f"<div class='time'>Updated at {html.escape(now_iso_utc())}</div>")

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            groups.setdefault(it["company"], []).append(it)

        def dom_id(name: str) -> str:
            return "tab-" + re.sub(r"[^a-zA-Z0-9_-]", "-", name)

        available = [c for c in self.cfg.company_order if c in groups and groups[c]]

        tabs: List[str] = ["<div class='tab' role='tablist' aria-label='Companies'>"]
        for c in available:
            cid = dom_id(c)
            tabs.append(
                f"<button class='tablink' role='tab' aria-controls='{cid}' onclick=\"openCompany(event,'{cid}')\">{html.escape(c)}</button>"
            )
        tabs.append("</div>")
        parts.append("\n".join(tabs))

        panes: List[str] = []
        for c in available:
            cid = dom_id(c)
            panes.append(f"<div id='{cid}' class='tabcontent' role='tabpanel' aria-labelledby='{cid}-btn'>")
            panes.append("<div class='grid'>")
            for it in groups[c]:
                title = html.escape(it["title"])
                url = html.escape(it["url"])
                snippet = html.escape(it.get("snippet", ""))
                panes.append(
                    "<div class='card'>"
                    f"<div class='item-title'><a href='{url}' target='_blank' rel='noopener'>{title}</a></div>"
                    f"<div class='snippet'>{snippet}</div>"
                    "</div>"
                )
            panes.append("</div></div>")
        parts.append("\n".join(panes))

        tail_tpl = read_text(self.cfg.templates_dir / "tail.html")
        return head + "\n<body>\n" + "\n".join(parts) + "\n" + tail_tpl

    def write_html(self, items: List[Dict[str, Any]]) -> None:
        html_doc = self._build_html(items)
        self.cfg.output_html.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cfg.output_html, "w", encoding="utf-8") as f:
            f.write(html_doc)
        print(f"[ok] wrote HTML {self.cfg.output_html}")


# =====================================================================
# Main
# =====================================================================

def main() -> None:
    cfg = Config.load()
    fetcher = Fetcher(cfg)
    renderer = Renderer(cfg)

    items = fetcher.fetch()
    json_path = renderer.write_json_and_manifest(items)
    renderer.write_html(items)

    rel = json_path.relative_to(cfg.project_root).as_posix()
    print(f"[info] Latest JSON path (not exposed in page): {rel}")

if __name__ == "__main__":
    main()