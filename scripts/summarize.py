#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, cast

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


def load_latest_items() -> List[Dict[str, Any]]:
    with open("data/manifest.json", "r", encoding="utf-8") as f:
        manifest: Dict[str, Any] = json.load(f)
    json_path = Path(str(manifest["json_path"]))
    with open(json_path, "r", encoding="utf-8") as f:
        data: Dict[str, Any] = json.load(f)
    items = cast(List[Dict[str, Any]], data.get("items", []))
    return items


def load_categories() -> Dict[str, List[str]]:
    default: Dict[str, List[str]] = {
        "Graph": ["graph", "bfs", "dfs", "shortest path", "topological", "dijkstra"],
        "DP": ["dp", "dynamic programming", "knapsack", "subproblem", "memoization", "tabulation"],
        "String": ["string", "substring", "palindrome", "anagram", "regex", "rabin-karp", "kmp"],
        "Array": ["array", "prefix sum", "subarray", "interval", "range sum", "matrix"],
        "Greedy": ["greedy", "interval scheduling", "activity selection"],
        "Two Pointers": ["two pointers", "sliding window", "fast slow", "window"],
        "Heap": ["heap", "priority queue", "pq"],
        "Tree": ["tree", "bst", "trie", "segment tree", "fenwick", "binary tree"],
        "SQL": ["sql", "join", "group by", "window function", "cte"],
        "System Design": [
            "design",
            "scaling",
            "cache",
            "shard",
            "load balancer",
            "cdn",
            "rate limit",
            "url shortener",
            "message queue",
        ],
        "Concurrency": [
            "concurrency",
            "mutex",
            "lock",
            "semaphore",
            "deadlock",
            "race condition",
            "thread",
        ],
        "Math": ["math", "prime", "gcd", "lcm", "mod", "probability", "combinatorics"],
        "Sorting": ["sort", "sorting", "quicksort", "mergesort", "bucket", "radix"],
        "Other": [],
    }
    cfg_path = Path("config/categories.json")
    if cfg_path.exists():
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                return cast(Dict[str, List[str]], user_cfg)
        except Exception:
            pass
    return default


def normalize(text: str) -> str:
    return text.lower()


def classify_item(title: str, snippet: str, categories: Dict[str, List[str]]) -> Set[str]:
    text = normalize(f"{title} {snippet}")
    hits: Set[str] = set()
    for cat, kws in categories.items():
        if not kws:
            continue
        for kw in kws:
            if kw.lower() in text:
                hits.add(cat)
                break
    if not hits:
        hits.add("Other")
    return hits


def build_trends(
    items: List[Dict[str, Any]],
    categories: Dict[str, List[str]],
) -> Tuple[Counter[str], Dict[str, Counter[str]]]:
    company_counts: Counter[str] = Counter()
    company_cat_counts: Dict[str, Counter[str]] = defaultdict(Counter)
    for it in items:
        company = str(it.get("company", "Unknown"))
        title = str(it.get("title", ""))
        snippet = str(it.get("snippet", ""))
        company_counts[company] += 1
        cats = classify_item(title, snippet, categories)
        for c in cats:
            company_cat_counts[company][c] += 1
    return company_counts, company_cat_counts


def render_rules_summary(items: List[Dict[str, Any]]) -> str:
    categories = load_categories()
    company_counts, company_cat_counts = build_trends(items, categories)

    lines: List[str] = []
    lines.append("# Daily Interview Feed Summary\n")

    if company_counts:
        lines.append("## Top Companies by Mentions")
        for company, cnt in company_counts.most_common(10):
            lines.append(f"- {company}: {cnt} questions")
        lines.append("")

    if company_cat_counts:
        lines.append("## Trend by Company")
        for company, _ in company_counts.most_common():
            cat_counter = company_cat_counts[company]
            if not cat_counter:
                continue
            lines.append(f"- {company}:")
            for cat, cnt in cat_counter.most_common(5):
                lines.append(f"  - {cat}: {cnt}")
        lines.append("")

    lines.append("## Sample Questions")
    for it in items[:5]:
        title = str(it.get("title", "")).strip()
        url = str(it.get("url", "")).strip()
        company = str(it.get("company", "Unknown"))
        lines.append(f"- {company}: {title} ({url})")

    return "\n".join(lines) + "\n"


def render_openai_summary(items: List[Dict[str, Any]], api_key: str) -> str:
    if OpenAI is None:
        raise RuntimeError("openai package not installed. Run `pip install openai`")

    categories = load_categories()
    company_counts, company_cat_counts = build_trends(items, categories)

    bullets = "\n".join(
        [
            f"- {str(it.get('company', 'Unknown'))}: {str(it.get('title', '')).strip()}"
            for it in items[:15]
        ]
    )

    trend_lines: List[str] = []
    for company, _ in company_counts.most_common():
        cat_counter = company_cat_counts[company]
        if not cat_counter:
            continue
        cats = ", ".join([f"{cat}({cnt})" for cat, cnt in cat_counter.most_common(5)])
        trend_lines.append(f"{company}: {cats}")
    trend_text = "\n".join(trend_lines)

    client = OpenAI(api_key=api_key)
    prompt = f"""
You are an assistant that writes a concise daily report of interview questions found in a forum feed.
First, give a short overview of top companies by volume. Then highlight per-company topic trends (categories and counts).
Finish with 3–5 notable examples from the list.

Topic categories and counts (pre-aggregated):
{trend_text}

Examples:
{bullets}

Write a clean Markdown report with headings and bullet points. Keep it under 250–300 words.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.3,
    )
    return str(resp.choices[0].message.content or "")


def main() -> None:
    items = load_latest_items()
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            summary = render_openai_summary(items, api_key)
            print("[ok] OpenAI summary generated")
        except Exception as e:
            print(f"[warn] OpenAI failed, falling back. Reason: {e}")
            summary = render_rules_summary(items)
    else:
        print("[info] OPENAI_API_KEY not set; using rules-based summary")
        summary = render_rules_summary(items)

    with open("summary.md", "w", encoding="utf-8") as f:
        f.write(summary)
    print("[ok] wrote summary.md")


if __name__ == "__main__":
    main()
