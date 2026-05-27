import csv
import io
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import requests

from .text_normalize import normalize_name, token_set

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None  # type: ignore


DEFAULT_SDN_URLS: Sequence[str] = (
    # OFAC Sanctions List Service (preferred; most up-to-date)
    "https://sanctionslist.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
    # Legacy endpoints (may redirect / be retired depending on OFAC changes)
    "https://www.treasury.gov/ofac/downloads/sdn.csv",
)

DEFAULT_ALT_URLS: Sequence[str] = (
    "https://sanctionslist.ofac.treas.gov/api/PublicationPreview/exports/ALT.CSV",
    "https://www.treasury.gov/ofac/downloads/alt.csv",
)


@dataclass(frozen=True)
class OfacEntry:
    ent_num: str
    name: str
    sdn_type: str
    programs: str
    remarks: str


@dataclass(frozen=True)
class OfacMatch:
    query: str
    matched_name: str
    ent_num: str
    score: int
    sdn_type: str
    programs: str
    remarks: str


def _download_first_ok(
    urls: Sequence[str],
    timeout_s: int = 60,
    user_agent: str = "Mozilla/5.0 (PortfolioRiskRadar/0.1)",
) -> Tuple[str, str]:
    last_err = None
    for url in urls:
        try:
            r = requests.get(url, timeout=timeout_s, headers={"User-Agent": user_agent})
            r.raise_for_status()
            txt = r.text
            # SDN.CSV is large; guard against HTML error pages.
            if "<!doctype html" in txt[:400].lower() or "<html" in txt[:200].lower():
                raise RuntimeError("Received HTML instead of CSV.")
            return url, txt
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    raise RuntimeError(f"Failed to download OFAC data from any URL. Last error: {last_err}")


def _parse_sdn_csv(text: str) -> List[OfacEntry]:
    """
    Parse SDN.CSV in OFAC legacy format.
    Expected columns (varies slightly over time), but typically:
      ent_num, name, sdn_type, program, title, call_sign, vess_type, tonnage,
      grt, vess_flag, vess_owner, remarks
    """
    rows: List[OfacEntry] = []
    reader = csv.reader(io.StringIO(text))
    for parts in reader:
        if not parts:
            continue
        ent_num = (parts[0] or "").strip()
        name = (parts[1] or "").strip() if len(parts) > 1 else ""
        sdn_type = (parts[2] or "").strip() if len(parts) > 2 else ""
        programs = (parts[3] or "").strip() if len(parts) > 3 else ""
        remarks = (parts[-1] or "").strip()
        if not ent_num or not name:
            continue
        rows.append(
            OfacEntry(
                ent_num=ent_num,
                name=name,
                sdn_type=sdn_type,
                programs=programs,
                remarks=remarks,
            )
        )
    return rows


def _parse_alt_csv(text: str) -> Dict[str, List[str]]:
    """
    Parse ALT.CSV (alternate names) mapping ENT_NUM -> list of alt names.
    Typical columns: ent_num, alt_num, alt_type, alt_name, remarks
    """
    alts: Dict[str, List[str]] = {}
    reader = csv.reader(io.StringIO(text))
    for parts in reader:
        if not parts:
            continue
        ent_num = (parts[0] or "").strip()
        alt_name = (parts[3] or "").strip() if len(parts) > 3 else ""
        if not ent_num or not alt_name:
            continue
        alts.setdefault(ent_num, []).append(alt_name)
    return alts


class OfacSdnIndex:
    def __init__(self, entries: List[OfacEntry], alt_names: Optional[Dict[str, List[str]]] = None):
        self.entries = entries
        self.alt_names = alt_names or {}
        self._name_norm: List[str] = []
        self._token_index: Dict[str, List[int]] = {}

        for idx, e in enumerate(self.entries):
            norm = normalize_name(e.name)
            self._name_norm.append(norm)
            for t in token_set(norm):
                self._token_index.setdefault(t, []).append(idx)

    def _candidate_indices(self, query: str) -> List[int]:
        tokens = token_set(query)
        if not tokens:
            return list(range(len(self.entries)))
        candidates = set()
        for t in tokens:
            for idx in self._token_index.get(t, []):
                candidates.add(idx)
        return list(candidates) if candidates else list(range(len(self.entries)))

    def match(
        self,
        query: str,
        min_score: int = 90,
        top_k: int = 3,
    ) -> List[OfacMatch]:
        q = normalize_name(query)
        if not q:
            return []
        if fuzz is None:
            raise ImportError("rapidfuzz is required for OFAC name matching. Install: pip install rapidfuzz")

        candidates = self._candidate_indices(q)
        scored: List[Tuple[int, int]] = []
        for idx in candidates:
            score = int(fuzz.token_set_ratio(q, self._name_norm[idx]))
            if score >= min_score:
                scored.append((idx, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[:top_k]

        matches: List[OfacMatch] = []
        for idx, score in scored:
            e = self.entries[idx]
            matches.append(
                OfacMatch(
                    query=query,
                    matched_name=e.name,
                    ent_num=e.ent_num,
                    score=score,
                    sdn_type=e.sdn_type,
                    programs=e.programs,
                    remarks=e.remarks,
                )
            )
        return matches


def build_ofac_sdn_index(
    sdn_urls: Sequence[str] = DEFAULT_SDN_URLS,
    alt_urls: Optional[Sequence[str]] = DEFAULT_ALT_URLS,
    timeout_s: int = 60,
) -> OfacSdnIndex:
    """
    Download SDN.CSV (and optionally ALT.CSV) and build an index for matching.
    """
    start = time.time()
    _, sdn_text = _download_first_ok(sdn_urls, timeout_s=timeout_s)
    entries = _parse_sdn_csv(sdn_text)

    alt_map = None
    if alt_urls:
        try:
            _, alt_text = _download_first_ok(list(alt_urls), timeout_s=timeout_s)
            alt_map = _parse_alt_csv(alt_text)
        except Exception:
            alt_map = None

    idx = OfacSdnIndex(entries=entries, alt_names=alt_map)
    _ = time.time() - start
    return idx

