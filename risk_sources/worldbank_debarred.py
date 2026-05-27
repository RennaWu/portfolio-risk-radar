from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Tuple

import requests

from .official_list_index import OfficialListEntry


WORLD_BANK_PAGE = "https://www.worldbank.org/en/projects-operations/procurement/debarred-firms"
WORLD_BANK_API_DEFAULT = "https://apigwext.worldbank.org/dvsvc/v1.0/json/APPLICATION/ADOBE_EXPRNCE_MGR/FIRM/SANCTIONED_FIRM"
WORLD_BANK_SOURCE_URL = WORLD_BANK_PAGE


def _download_if_needed(cache_path: str, url: str, max_age_hours: int = 48) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    if os.path.isfile(cache_path):
        age_s = time.time() - os.path.getmtime(cache_path)
        if age_s < max_age_hours * 3600:
            return cache_path

    r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (PortfolioRiskRadar/0.1)"})
    r.raise_for_status()
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(r.text)
    return cache_path


def _extract_worldbank_api_key(page_html: str) -> Tuple[str, str]:
    """
    World Bank's debarred list page includes a client-side API URL + API key for the table.
    We extract them at runtime to avoid hard-coding secrets in the repo.
    """
    api_url = WORLD_BANK_API_DEFAULT
    m_url = re.search(r'prodtabApi\s*=\s*"([^"]+)"', page_html)
    if m_url:
        api_url = m_url.group(1).strip()

    m_key = re.search(r'propApiKey\s*=\s*"([^"]+)"', page_html)
    if not m_key:
        raise RuntimeError("Could not extract World Bank debarred list API key from page HTML.")
    return api_url, m_key.group(1).strip()


def _fetch_worldbank_debarred_json(api_url: str, api_key: str) -> Dict:
    r = requests.get(
        api_url,
        timeout=60,
        headers={"User-Agent": "Mozilla/5.0 (PortfolioRiskRadar/0.1)", "apikey": api_key},
    )
    r.raise_for_status()
    return r.json()


def load_worldbank_debarred_entities(cache_dir: str = "output/.cache/official_lists") -> List[OfficialListEntry]:
    """
    Load World Bank debarred & cross-debarred firms/individuals as an official list source.

    Source page contains the API endpoint + key used by the table UI.
    """
    html_cache = os.path.join(cache_dir, "worldbank_debarred_page.html")
    _download_if_needed(html_cache, WORLD_BANK_PAGE, max_age_hours=24)
    with open(html_cache, "r", encoding="utf-8", errors="replace") as f:
        page_html = f.read()

    api_url, api_key = _extract_worldbank_api_key(page_html)
    data = _fetch_worldbank_debarred_json(api_url, api_key)

    rows = (((data or {}).get("response") or {}).get("ZPROCSUPP") or [])
    entries: List[OfficialListEntry] = []
    for r in rows:
        try:
            name = str(r.get("SUPP_NAME") or "").strip()
            add = str(r.get("ADD_SUPP_INFO") or "").strip()
            full = (name + add).strip() if add else name
            if not full:
                continue
            entry_id = str(r.get("SUPP_ID") or full).strip()
            entries.append(
                OfficialListEntry(
                    list_name="WORLD_BANK_DEBARRED",
                    entry_id=entry_id,
                    name=full,
                    source_url=WORLD_BANK_SOURCE_URL,
                )
            )
        except Exception:
            continue

    uniq = {(e.list_name, e.entry_id, e.name): e for e in entries}
    return list(uniq.values())

