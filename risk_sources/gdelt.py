import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import json
import os
import hashlib

import requests
import time


GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


@dataclass(frozen=True)
class GdeltArticle:
    title: str
    url: str
    domain: str
    seen_date_utc: str
    snippet: str = ""


def _timespan(days: int) -> str:
    days = max(1, int(days))
    return f"{days}d"


def fetch_gdelt_articles(
    query: str,
    days: int = 7,
    max_records: int = 20,
    timeout_s: int = 30,
    user_agent: str = "Mozilla/5.0 (PortfolioRiskRadar/0.1)",
    max_retries: int = 3,
    sleep_s: float = 1.0,
    cache_dir: str = "output/.cache/gdelt",
) -> List[GdeltArticle]:
    """
    Fetch recent articles via GDELT 2.1 DOC API.

    We intentionally keep this lightweight and rely on downstream classification.
    """
    q = (query or "").strip()
    if not q:
        return []

    def cache_key(params: Dict[str, str]) -> str:
        raw = json.dumps(params, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]

    def read_cache(key: str) -> Optional[Dict[str, Any]]:
        try:
            path = os.path.join(cache_dir, f"{key}.json")
            if not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def write_cache(key: str, data: Dict[str, Any]) -> None:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            path = os.path.join(cache_dir, f"{key}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            return

    def call_gdelt(query_str: str) -> Dict[str, Any]:
        params = {
            "query": query_str,
            "mode": "ArtList",
            "format": "json",
            "sort": "HybridRel",
            "maxrecords": str(int(max_records)),
            "timespan": _timespan(days),
        }
        key = cache_key(params)
        cached = read_cache(key)
        if cached is not None:
            return cached

        for attempt in range(max(1, int(max_retries))):
            try:
                r = requests.get(GDELT_DOC_API, params=params, timeout=timeout_s, headers={"User-Agent": user_agent})
                if r.status_code == 429:
                    raise requests.HTTPError("429 Too Many Requests", response=r)
                r.raise_for_status()
                data: Dict[str, Any] = r.json()
                write_cache(key, data)
                return data
            except Exception as e:
                # If we're being throttled, respect GDELT guidance (~1 request / 5s).
                backoff = max(6.0, float(sleep_s)) * (2**attempt) if isinstance(e, requests.HTTPError) else max(1.0, float(sleep_s)) * (2**attempt)
                time.sleep(backoff)
        # Soft-fail: don't crash the pipeline on rate limits.
        return {}

    # One request per company to avoid rate-limits; classification happens downstream.
    data = call_gdelt(f'"{q}"')

    articles = data.get("articles") or []

    out: List[GdeltArticle] = []
    for a in articles:
        title = str(a.get("title") or "").strip()
        url = str(a.get("url") or "").strip()
        domain = str(a.get("domain") or "").strip()
        seen = str(a.get("seendate") or "").strip()
        snippet = str(a.get("sourceCountry") or "")  # fallback field; DOC doesn't always provide snippets
        if not title or not url:
            continue
        # Normalize seen date to a stable UTC string when possible.
        try:
            # Example: 20260101000000
            if seen.isdigit() and len(seen) == 14:
                d = dt.datetime.strptime(seen, "%Y%m%d%H%M%S")
                seen = d.replace(tzinfo=dt.timezone.utc).isoformat()
        except Exception:
            pass
        out.append(GdeltArticle(title=title, url=url, domain=domain, seen_date_utc=seen, snippet=snippet))
    return out

