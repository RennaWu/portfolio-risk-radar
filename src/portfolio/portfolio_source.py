"""Portfolio source loader.

Supports loading entity lists from CSV (default) or any HTTP JSON endpoint
(for orgs that expose internal portfolio APIs).

Replaces hardcoded vendor-specific endpoints with a config-driven design.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import List, Optional

import requests


@dataclass(frozen=True)
class PortfolioCompany:
    name: str
    entity_id: Optional[str] = None
    source: str = "csv"


def load_from_csv(filepath: str, name_column: str = "company") -> List[PortfolioCompany]:
    """
    Load entities from a CSV file.

    Expected header: `company` column (overridable via name_column).
    """
    names: List[PortfolioCompany] = []
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            name = (row.get(name_column) or "").strip()
            if name:
                names.append(PortfolioCompany(name=name, source="csv"))

    # De-dupe with stable order.
    seen = set()
    out: List[PortfolioCompany] = []
    for c in names:
        key = c.name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def load_from_json_api(
    api_url: str,
    name_field: str = "name",
    id_field: Optional[str] = None,
    timeout_s: int = 30,
    user_agent: str = "Mozilla/5.0 (PortfolioRiskRadar/0.1)",
) -> List[PortfolioCompany]:
    """
    Generic JSON API loader.

    Expects either:
    - A list of dicts: [{"name": "Acme Corp", "id": 123}, ...]
    - Or a list of single-key dicts: [{"Acme Corp": {"id": 123}}, ...]

    Pass the field name via `name_field` / `id_field` for the first format.
    """
    r = requests.get(api_url, timeout=timeout_s, headers={"User-Agent": user_agent})
    r.raise_for_status()
    payload = r.json()

    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON list, got {type(payload).__name__}")

    companies: List[PortfolioCompany] = []
    for item in payload:
        if not isinstance(item, dict) or not item:
            continue

        # Format A: {"name": "Acme", "id": 123}
        if name_field in item:
            name = str(item.get(name_field, "")).strip()
            entity_id = str(item[id_field]) if (id_field and item.get(id_field) is not None) else None
        # Format B: {"Acme Corp": {"id": 123, ...}}
        else:
            name = next(iter(item.keys()))
            meta = item.get(name) or {}
            entity_id = str(meta.get(id_field)) if (id_field and meta.get(id_field) is not None) else None

        name_clean = str(name).strip()
        if not name_clean:
            continue
        companies.append(PortfolioCompany(name=name_clean, entity_id=entity_id, source="json_api"))

    companies = sorted({c.name: c for c in companies}.values(), key=lambda c: c.name.lower())
    return companies
