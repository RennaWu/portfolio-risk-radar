from __future__ import annotations

import csv
import os
import time
from typing import Dict, List, Tuple

import requests

from .official_list_index import OfficialListEntry


UK_SANCTIONS_CSV = "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"
UK_SOURCE_URL = "https://www.gov.uk/government/publications/the-uk-sanctions-list"


def _download_if_needed(cache_path: str, url: str, max_age_hours: int = 48) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    if os.path.isfile(cache_path):
        age_s = time.time() - os.path.getmtime(cache_path)
        if age_s < max_age_hours * 3600:
            return cache_path

    with requests.get(url, timeout=120, headers={"User-Agent": "Mozilla/5.0 (PortfolioRiskRadar/0.1)"}, stream=True) as r:
        r.raise_for_status()
        with open(cache_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 128):
                if chunk:
                    f.write(chunk)
    return cache_path


def _build_name(row: Dict[str, str]) -> str:
    parts = []
    # Name 1..6 are used across formats; sometimes Name 6 contains the full name.
    for k in ("Name 1", "Name 2", "Name 3", "Name 4", "Name 5", "Name 6"):
        v = (row.get(k) or "").strip()
        if v:
            parts.append(v)
    if parts:
        return " ".join(parts).strip()
    return ""


def load_uk_sanctions_entities(cache_dir: str = "output/.cache/official_lists") -> List[OfficialListEntry]:
    """
    Load UK Sanctions List entries (entities only) from official CSV.
    """
    cache_path = os.path.join(cache_dir, "uk_sanctions_list.csv")
    _download_if_needed(cache_path, UK_SANCTIONS_CSV)

    entries: List[OfficialListEntry] = []
    with open(cache_path, "r", encoding="utf-8", errors="replace", newline="") as f:
        lines = f.read().splitlines()
    if not lines:
        return []
    # First line is report date; header starts on line 2.
    reader = csv.DictReader(lines[1:])
    for row in reader:
        if not row:
            continue
        if (row.get("Designation Type") or "").strip() != "Entity":
            continue
        uid = (row.get("Unique ID") or "").strip() or (row.get("OFSI Group ID") or "").strip() or ""
        name_type = (row.get("Name type") or "").strip()
        if name_type not in ("Primary Name", "Alias", "Primary Name Variation"):
            continue
        name = _build_name(row)
        if not name:
            continue
        entries.append(
            OfficialListEntry(
                list_name="UK_SANCTIONS_LIST",
                entry_id=uid or name,
                name=name,
                source_url=UK_SOURCE_URL,
            )
        )

    uniq = {(e.list_name, e.entry_id, e.name): e for e in entries}
    return list(uniq.values())

