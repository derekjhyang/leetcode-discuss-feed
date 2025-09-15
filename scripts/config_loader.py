from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .utils import die_missing, read_json


@dataclass(frozen=True)
class Config:
    project_root: Path
    companies_cfg: Path
    settings_cfg: Path
    templates_dir: Path
    assets_dir: Path

    companies_aliases: Dict[str, List[str]]
    settings: Dict[str, Any]

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
        settings_cfg = Path(os.getenv("SETTINGS_CONFIG", root / "config" / "settings.json"))
        templates_dir = root / "templates"
        assets_dir = root / "assets"

        die_missing(companies_cfg, "Put companies.json under <repo-root>/config/ or set COMPANY_CONFIG env.")
        die_missing(settings_cfg, "Put settings.json under <repo-root>/config/ or set SETTINGS_CONFIG env.")
        die_missing(templates_dir / "head.html", "Missing templates/head.html under <repo-root>/templates/")
        die_missing(templates_dir / "tail.html", "Missing templates/tail.html under <repo-root>/templates/")
        die_missing(assets_dir / "style.css", "Missing assets/style.css under <repo-root>/assets/")

        companies_aliases = read_json(companies_cfg)
        settings = read_json(settings_cfg)

        cse_id = os.environ["CSE_ID"]
        cse_key = os.environ["CSE_KEY"]

        page_title = settings.get("page", {}).get("title", "FAANG Discuss Daily")
        page_noindex = bool(settings.get("page", {}).get("noindex", True))
        company_order = settings.get("page", {}).get("company_order", list(companies_aliases.keys()))

        site_host = settings.get("query", {}).get("site", "leetcode.com/discuss")
        max_results = int(settings.get("query", {}).get("max_results", 40))
        q_companies = settings.get("query", {}).get("companies", list(companies_aliases.keys()))
        q_intents = settings.get("query", {}).get("intents", ["interview", "onsite", "phone", "screen", "OA", "questions"])

        allow_patterns = settings.get("filters", {}).get("path_allow", [
            r"^https?://leetcode\.com/discuss/(?:interview-question|study-guide|general-discussion|interview-experience)/"
        ])
        keyword_words = settings.get("filters", {}).get("keywords", [
            "onsite", "phone", "screen", "oa", "interview", "experience", "question", "questions"
        ])

        output_html = root / Path(settings.get("output", {}).get("html", "index.html"))
        manifest_path = root / Path(settings.get("output", {}).get("json_manifest", "data/manifest.json"))
        json_randomize = bool(settings.get("output", {}).get("json_randomize", True))
        json_daily_stable = bool(settings.get("output", {}).get("json_daily_stable", True))
        json_salt = os.getenv("JSON_SALT", "")

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
