import datetime as dt
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List, Optional

import requests


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


@dataclass(frozen=True)
class RssArticle:
    title: str
    url: str
    published_utc: str
    source: str = ""


def _to_utc_iso(pub_date: str) -> str:
    s = (pub_date or "").strip()
    if not s:
        return ""
    # Example: "Mon, 18 Mar 2026 12:34:56 GMT"
    try:
        d = dt.datetime.strptime(s, "%a, %d %b %Y %H:%M:%S %Z")
        return d.replace(tzinfo=dt.timezone.utc).isoformat()
    except Exception:
        return s


def fetch_google_news_rss(
    query: str,
    max_records: int = 10,
    timeout_s: int = 20,
    user_agent: str = "Mozilla/5.0 (PortfolioRiskRadar/0.1)",
    hl: str = "en-CA",
    gl: str = "CA",
    ceid: str = "CA:en",
) -> List[RssArticle]:
    """
    Fetch recent articles from Google News RSS.
    Free, no API key, but results are best-effort and can include noise.
    """
    q = (query or "").strip()
    if not q:
        return []

    params = {"q": f'"{q}"', "hl": hl, "gl": gl, "ceid": ceid}
    r = requests.get(GOOGLE_NEWS_RSS, params=params, timeout=timeout_s, headers={"User-Agent": user_agent})
    r.raise_for_status()

    root = ET.fromstring(r.text)
    items = root.findall(".//item")
    out: List[RssArticle] = []
    for it in items[: max(0, int(max_records))]:
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        source = (it.findtext("source") or "").strip()
        if not title or not link:
            continue
        out.append(RssArticle(title=title, url=link, published_utc=_to_utc_iso(pub), source=source))
    return out

