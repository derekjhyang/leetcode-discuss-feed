from __future__ import annotations

import html
import re
import hashlib
import secrets
import string
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

from scripts.config_loader import Config, now_iso_utc, read_text, write_json_atomic


@dataclass
class Renderer:
    cfg: Config

    def _daily_token(self) -> str:
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
        manifest_payload = {
            "updated_at": now_iso_utc(),
            "json_path": str(json_abs.relative_to(self.cfg.project_root).as_posix()),
            "count": len(items)
        }
        write_json_atomic(self.cfg.manifest_path, manifest_payload)
        return json_abs

    def _read_summary_md_as_html(self) -> str:
        md_path = self.cfg.project_root / "summary.md"
        if not md_path.exists():
            return "<em>No summary available.</em>"
        raw = read_text(md_path)
        escaped = html.escape(raw)
        return f"<pre class='summary-md'>{escaped}</pre>"

    def _company_counts(self, items: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
        counts: Dict[str, int] = {}
        for it in items:
            c = it.get("company", "Unknown")
            counts[c] = counts.get(c, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

    def _build_html(self, items: List[Dict[str, Any]]) -> str:
        head_tpl = read_text(self.cfg.templates_dir / "head.html")
        head = head_tpl.replace("{{PAGE_TITLE}}", html.escape(self.cfg.page_title))
        if self.cfg.page_noindex and 'name="robots"' not in head:
            head = head.replace("</head>", '  <meta name="robots" content="noindex,nofollow">\n</head>')

        parts: List[str] = []
        parts.append(f"<h1>{html.escape(self.cfg.page_title)}</h1>")
        parts.append(f"<div class='time'>Updated at {html.escape(now_iso_utc())}</div>")

        parts.append("<section class='summary-panel'>")
        parts.append("<h2>📊 Daily Summary</h2>")
        parts.append("<div class='summary-content'>")
        parts.append(self._read_summary_md_as_html())
        parts.append("</div></section>")

        counts = self._company_counts(items)
        if counts:
            parts.append("<section class='trend-stats'>")
            parts.append("<h2>🔥 Trend Stats (by company)</h2>")
            parts.append("<ul class='stats-list'>")
            for company, cnt in counts:
                parts.append(f"<li><strong>{html.escape(company)}</strong>: {cnt} posts</li>")
            parts.append("</ul></section>")

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
