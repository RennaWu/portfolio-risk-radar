from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

try:
    from rapidfuzz import fuzz  # type: ignore
except Exception:  # pragma: no cover
    fuzz = None  # type: ignore

from .text_normalize import normalize_name, token_set


@dataclass(frozen=True)
class OfficialListEntry:
    list_name: str
    entry_id: str
    name: str
    source_url: str


@dataclass(frozen=True)
class OfficialListMatch:
    query: str
    matched_name: str
    list_name: str
    entry_id: str
    score: int
    source_url: str


class OfficialListIndex:
    def __init__(self, entries: Sequence[OfficialListEntry]):
        if fuzz is None:
            raise ImportError("rapidfuzz is required for official-list matching. Install: pip install rapidfuzz")

        self.entries: List[OfficialListEntry] = list(entries)
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

    def match(self, query: str, min_score: int = 95, top_k: int = 2) -> List[OfficialListMatch]:
        q = normalize_name(query)
        if not q:
            return []

        candidates = self._candidate_indices(q)
        scored: List[Tuple[int, int]] = []
        for idx in candidates:
            score = int(fuzz.token_set_ratio(q, self._name_norm[idx]))
            if score >= int(min_score):
                scored.append((idx, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        scored = scored[: max(1, int(top_k))]

        out: List[OfficialListMatch] = []
        for idx, score in scored:
            e = self.entries[idx]
            out.append(
                OfficialListMatch(
                    query=query,
                    matched_name=e.name,
                    list_name=e.list_name,
                    entry_id=e.entry_id,
                    score=score,
                    source_url=e.source_url,
                )
            )
        return out

