from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Any, Dict, List, cast
from dataclasses import dataclass

from scripts.config_loader import Config, now_iso_utc


@dataclass
class Fetcher:
    cfg: Config

    def _build_query(self) -> str:
        companies = "(" + " OR ".join(self.cfg.q_companies) + ")"
        intents = "(" + " OR ".join(self.cfg.q_intents) + ")"
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
            return cast(Dict[str, Any], json.loads(resp.read().decode("utf-8")))

    def fetch(self) -> List[Dict[str, Any]]:
        company_rx = {
            c: re.compile(r"|".join(map(re.escape, v)), re.I)
            for c, v in self.cfg.companies_aliases.items()
        }
        allow_rx = re.compile("|".join(self.cfg.allow_patterns), re.I)
        keywords_rx = re.compile(
            r"\b(" + "|".join(map(re.escape, self.cfg.keyword_words)) + r")\b", re.I
        )

        def detect_company(text: str | None) -> str | None:
            s = text or ""
            for c, rx in company_rx.items():
                if rx.search(s):
                    return c
            return None

        q = self._build_query()
        items: List[Dict[str, Any]] = []
        start = 1
        cse_failed = False

        while len(items) < self.cfg.max_results and start <= 91:
            try:
                data = self._cse(q, start=start, num=10)
            except urllib.error.HTTPError as e:
                print("HTTPError:", e.read())
                cse_failed = True
                break
            except Exception as e:
                print("Fetch error:", e)
                cse_failed = True
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
                items.append(
                    {
                        "title": title,
                        "url": link,
                        "snippet": snippet,
                        "company": company,
                        "first_seen": now_iso_utc(),
                    }
                )

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
        result = dedup[: self.cfg.max_results]

        # Fallback: if CSE failed or no items, load from manifest
        if cse_failed or not result:
            try:
                manifest_path = self.cfg.manifest_path
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                json_path = manifest.get("json_path")
                if json_path:
                    json_file = self.cfg.project_root / json_path
                    with open(json_file, "r", encoding="utf-8") as jf:
                        payload = json.load(jf)
                    print(f"[fallback] Loaded {len(payload.get('items', []))} items from {json_file}")
                    return payload.get("items", [])
            except Exception as e:
                print(f"[fallback] Failed to load manifest/json: {e}")
                return []
        return result
