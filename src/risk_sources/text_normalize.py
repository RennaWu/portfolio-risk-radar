import re
from typing import Iterable, List, Set


_PUNCT_RE = re.compile(r"[^a-z0-9\\s]+", re.IGNORECASE)
_WS_RE = re.compile(r"\\s+")

# Common legal suffixes / filler tokens that hurt matching.
_STOP_TOKENS: Set[str] = {
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "ltd",
    "limited",
    "llc",
    "plc",
    "lp",
    "holdings",
    "holding",
    "group",
    "sa",
    "sarl",
    "gmbh",
    "ag",
    "bv",
    "oy",
    "pte",
    "pty",
    "the",
    "and",
    "&",
}


def normalize_name(s: str) -> str:
    s = str(s or "").strip().lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def tokenize_name(s: str) -> List[str]:
    s_norm = normalize_name(s)
    tokens = [t for t in s_norm.split(" ") if t and t not in _STOP_TOKENS]
    # Keep only moderately informative tokens.
    tokens = [t for t in tokens if len(t) >= 2]
    return tokens


def token_set(s: str) -> Set[str]:
    return set(tokenize_name(s))


def stable_unique(items: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

