from __future__ import annotations

import html
import re
import hashlib
import secrets
import string
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional, cast

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
        write_json_atomic(
            json_abs,
            {"updated_at": now_iso_utc(), "count": len(items), "items": items},
        )
        manifest_payload: Dict[str, Any] = {
            "updated_at": now_iso_utc(),
            "json_path": str(json_abs.relative_to(self.cfg.project_root).as_posix()),
            "count": len(items),
        }
        write_json_atomic(self.cfg.manifest_path, manifest_payload)
        return json_abs

    def _company_counts(self, items: List[Dict[str, Any]]) -> List[Tuple[str, int]]:
        counts: Dict[str, int] = {}
        for it in items:
            c = str(it.get("company", "Unknown"))
            counts[c] = counts.get(c, 0) + 1
        return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

    def _load_summary_json(self) -> Dict[str, Any]:
        p = self.cfg.project_root / "data" / "summary.json"
        if not p.exists():
            return {}
        import json

        with open(p, "r", encoding="utf-8") as f:
            return cast(Dict[str, Any], json.load(f))

    def _render_stats_cards(self, items: List[Dict[str, Any]]) -> str:
        data = self._load_summary_json()
        counts_obj = data.get("company_counts")
        if not isinstance(counts_obj, dict) or not counts_obj:
            return self._render_stats_list(items)
        counts: Dict[str, int] = {str(k): int(v) for k, v in counts_obj.items()}
        if not counts:
            return ""
        maxv = max(counts.values())
        ordered = [c for c in self.cfg.company_order if c in counts]
        tail = [c for c in counts.keys() if c not in ordered]
        ordered += tail
        parts: List[str] = []
        parts.append("<section class='trend-cards'>")
        parts.append("<h2>🔥 Trend Stats</h2>")
        parts.append("<div class='cards'>")
        for c in ordered:
            v = counts.get(c, 0)
            if v <= 0:
                continue
            pct = int(round((v / maxv) * 100)) if maxv > 0 else 0
            parts.append(
                f"""
<div class='stat-card'>
  <div class='stat-head'>
    <span class='stat-title'>{html.escape(c)}</span>
    <span class='stat-value'>{v}</span>
  </div>
  <div class='stat-bar'><div class='stat-bar-fill' style='width:{pct}%;'></div></div>
</div>
""".strip()
            )
        parts.append("</div></section>")
        return "\n".join(parts)

    def _render_stats_list(self, items: List[Dict[str, Any]]) -> str:
        counts = self._company_counts(items)
        if not counts:
            return ""
        parts: List[str] = []
        parts.append("<section class='trend-stats'>")
        parts.append("<h2>🔥 Trend Stats (by company)</h2>")
        parts.append("<ul class='stats-list'>")
        for company, cnt in counts:
            parts.append(f"<li><strong>{html.escape(company)}</strong>: {cnt} posts</li>")
        parts.append("</ul></section>")
        return "\n".join(parts)

    def _render_tabs_and_cards(self, items: List[Dict[str, Any]]) -> str:
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            groups.setdefault(str(it["company"]), []).append(it)

        def dom_id(name: str) -> str:
            return "tab-" + re.sub(r"[^a-zA-Z0-9_-]", "-", name)

        available = [c for c in self.cfg.company_order if c in groups and groups[c]]

        out: List[str] = []
        tabs: List[str] = ["<div class='tab' role='tablist' aria-label='Companies'>"]
        for c in available:
            cid = dom_id(c)
            tabs.append(
                f"<button class='tablink' role='tab' aria-controls='{cid}' onclick=\"openCompany(event,'{cid}')\">{html.escape(c)}</button>"
            )
        tabs.append("</div>")
        out.append("\n".join(tabs))

        panes: List[str] = []
        for c in available:
            cid = dom_id(c)
            panes.append(
                f"<div id='{cid}' class='tabcontent' role='tabpanel' aria-labelledby='{cid}-btn'>"
            )
            panes.append("<div class='grid'>")
            for it in groups[c]:
                title = html.escape(str(it["title"]))
                url = html.escape(str(it["url"]))
                snippet = html.escape(str(it.get("snippet", "")))
                panes.append(
                    "<div class='card'>"
                    f"<div class='item-title'><a href='{url}' target='_blank' rel='noopener'>{title}</a></div>"
                    f"<div class='snippet'>{snippet}</div>"
                    "</div>"
                )
            panes.append("</div></div>")
        out.append("\n".join(panes))
        return "\n".join(out)

    def _render_sample_questions(self, items: List[Dict[str, Any]], limit: int = 6) -> str:
        parts: List[str] = []
        parts.append("<section class='sample-questions'>")
        parts.append("<h2>🔗 Sample Questions</h2>")
        parts.append("<ul>")
        for it in items[:limit]:
            company = html.escape(str(it.get("company", "Unknown")))
            title = html.escape(str(it.get("title", "")).strip())
            url = html.escape(str(it.get("url", "")).strip())
            parts.append(
                f"<li><strong>{company}</strong>: <a href='{url}' target='_blank' rel='noopener'>{title}</a></li>"
            )
        parts.append("</ul></section>")
        return "\n".join(parts)

    def _strip_sample_section(self, md: str) -> str:
        lines = md.splitlines()
        out: List[str] = []
        skipping = False
        for line in lines:
            if not skipping and line.strip().lower().startswith("## sample questions"):
                skipping = True
                continue
            if skipping:
                if line.strip().startswith("## "):
                    skipping = False
                    out.append(line)
                else:
                    continue
            else:
                out.append(line)
        return "\n".join(out)

    def _build_html(self, items: List[Dict[str, Any]], summary_text: Optional[str] = None) -> str:
        head_tpl = read_text(self.cfg.templates_dir / "head.html")
        head = head_tpl.replace("{{PAGE_TITLE}}", html.escape(self.cfg.page_title))
        if self.cfg.page_noindex and 'name="robots"' not in head:
            head = head.replace(
                "</head>", '  <meta name="robots" content="noindex,nofollow">\n</head>'
            )

        parts: List[str] = []
        parts.append(f"<h1>{html.escape(self.cfg.page_title)}</h1>")
        parts.append(f"<div class='time'>Updated at {html.escape(now_iso_utc())}</div>")

        parts.append(self._render_stats_cards(items))
        parts.append(self._render_tabs_and_cards(items))
        parts.append(self._render_sample_questions(items))

        parts.append("<section class='summary-panel'>")
        parts.append("<h2>📊 Daily Summary</h2>")
        parts.append("<div class='summary-content'>")
        md_text: Optional[str] = None
        if summary_text and summary_text.strip():
            md_text = summary_text
        else:
            md_path = self.cfg.project_root / "summary.md"
            if md_path.exists():
                md_text = read_text(md_path)
        if md_text:
            clean = self._strip_sample_section(md_text)
            parts.append(f"<pre class='summary-md'>{html.escape(clean)}</pre>")
        else:
            parts.append("<em>No summary available.</em>")
        parts.append("</div></section>")

        tail_tpl = read_text(self.cfg.templates_dir / "tail.html")
        return head + "\n<body>\n" + "\n".join([p for p in parts if p]) + "\n" + tail_tpl

    def write_html(self, items: List[Dict[str, Any]], summary_text: Optional[str] = None) -> None:
        html_doc = self._build_html(items, summary_text=summary_text)
        self.cfg.output_html.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cfg.output_html, "w", encoding="utf-8") as f:
            f.write(html_doc)
