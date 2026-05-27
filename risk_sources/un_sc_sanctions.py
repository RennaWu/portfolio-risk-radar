from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from typing import List

import requests

from .official_list_index import OfficialListEntry


UN_CONSOLIDATED_XML = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"
UN_SOURCE_URL = "https://www.un.org/securitycouncil/content/un-sc-consolidated-list"


def _download_if_needed(cache_path: str, url: str, max_age_hours: int = 48) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(cache_path)), exist_ok=True)
    if os.path.isfile(cache_path):
        age_s = time.time() - os.path.getmtime(cache_path)
        if age_s < max_age_hours * 3600:
            return cache_path

    r = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0 (PortfolioRiskRadar/0.1)"})
    r.raise_for_status()
    with open(cache_path, "wb") as f:
        f.write(r.content)
    return cache_path


def load_un_consolidated_entities(cache_dir: str = "output/.cache/official_lists") -> List[OfficialListEntry]:
    """
    Load UN SC Consolidated List (entities only) from official XML.
    """
    cache_path = os.path.join(cache_dir, "un_sc_consolidated.xml")
    _download_if_needed(cache_path, UN_CONSOLIDATED_XML)

    root = ET.parse(cache_path).getroot()
    entries: List[OfficialListEntry] = []

    for ent in root.findall(".//ENTITY"):
        dataid = (ent.findtext("DATAID") or "").strip()
        primary = (ent.findtext("FIRST_NAME") or "").strip()
        if primary:
            entries.append(
                OfficialListEntry(
                    list_name="UN_SC_CONSOLIDATED",
                    entry_id=dataid or primary,
                    name=primary,
                    source_url=UN_SOURCE_URL,
                )
            )
        for alias in ent.findall(".//ENTITY_ALIAS"):
            alias_name = (alias.findtext("ALIAS_NAME") or "").strip()
            if alias_name:
                entries.append(
                    OfficialListEntry(
                        list_name="UN_SC_CONSOLIDATED",
                        entry_id=dataid or primary or alias_name,
                        name=alias_name,
                        source_url=UN_SOURCE_URL,
                    )
                )

    # De-dupe by (list_name, entry_id, name)
    uniq = {(e.list_name, e.entry_id, e.name): e for e in entries}
    return list(uniq.values())

