#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Optional, List, Dict, Any, Callable
import os

from scripts.config_loader import Config
from scripts.fetcher import Fetcher
from scripts.renderer import Renderer
from scripts.summarize import render_rules_summary, render_openai_summary


def make_summary(items: List[Dict[str, Any]]) -> str:
    api_key: Optional[str] = os.getenv("OPENAI_API_KEY")
    if api_key and render_openai_summary is not None:
        try:
            return render_openai_summary(items, api_key)
        except Exception:
            pass
    if render_rules_summary is not None:
        return render_rules_summary(items)
    return "No AI available. Showing basic counts only."


def main() -> None:
    cfg = Config.load()
    fetcher = Fetcher(cfg)
    renderer = Renderer(cfg)

    items = fetcher.fetch()
    json_path = renderer.write_json_and_manifest(items)

    summary_text = make_summary(items)
    renderer.write_html(items, summary_text=summary_text)

    rel = json_path.relative_to(cfg.project_root).as_posix()
    print(f"[info] Latest JSON path (not exposed in page): {rel}")


if __name__ == "__main__":
    main()
