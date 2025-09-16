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
        return dedup[: self.cfg.max_results]
