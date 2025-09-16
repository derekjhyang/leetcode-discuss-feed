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

from scripts.config_loader import Config
from scripts.fetcher import Fetcher
from scripts.renderer import Renderer


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
