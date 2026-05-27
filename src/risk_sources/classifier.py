from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .text_normalize import normalize_name


@dataclass(frozen=True)
class RiskSignal:
    risk_type: str  # e.g. "sanctions_match", "adverse_media"
    category: str  # e.g. "sanctions", "litigation", "regulatory", "fraud", "cyber", "layoffs"
    severity: str  # "High" | "Medium" | "Low"
    rationale: str
    risk_score: int = 0


_INDICATORS: List[Dict[str, object]] = [
    # Highest weight indicators (true "risk" vs general press)
    # Note: these are NEWS indicators, so we keep scores < official-list matches.
    {"category": "sanctions", "severity": "High", "score": 70, "keywords": ["ofac", "sanction", "designated", "blocked person"]},
    {"category": "financial_crime", "severity": "High", "score": 65, "keywords": ["money laundering", "terror financing", "terrorist financing"]},
    {"category": "fraud_corruption", "severity": "High", "score": 60, "keywords": ["fraud", "bribery", "corruption", "kickback", "embezzlement", "ponzi"]},
    {"category": "criminal", "severity": "High", "score": 55, "keywords": ["indicted", "indictment", "arrested", "charged", "guilty plea", "convicted"]},
    {"category": "bankruptcy", "severity": "High", "score": 55, "keywords": ["bankruptcy", "insolvency", "chapter 11", "receivership"]},

    # Medium weight indicators
    {"category": "regulatory", "severity": "Medium", "score": 40, "keywords": ["investigation", "probe", "regulator", "enforcement", "sec", "ftc", "doj", "fine", "penalty", "settlement"]},
    {"category": "litigation", "severity": "Medium", "score": 35, "keywords": ["lawsuit", "sued", "class action", "litigation", "court filing"]},
    {"category": "cyber", "severity": "Medium", "score": 35, "keywords": ["data breach", "breach", "ransomware", "hacked", "cyberattack"]},
    {"category": "governance", "severity": "Medium", "score": 30, "keywords": ["accounting irregularities", "restatement", "whistleblower", "audit"]},

    # Low weight / watchlist
    {"category": "operational", "severity": "Low", "score": 20, "keywords": ["layoffs", "layoff", "restructuring", "shutdown", "strike", "union dispute"]},
    {"category": "market", "severity": "Low", "score": 15, "keywords": ["down round", "downgrade", "liquidity crunch"]},
]


def classify_adverse_media(title: str, text: str = "") -> RiskSignal:
    blob = normalize_name(f"{title} {text}")

    best: Optional[RiskSignal] = None
    for ind in _INDICATORS:
        kws = ind.get("keywords") or []
        if any(str(k) in blob for k in kws):  # simple substring match (fast + explainable)
            sig = RiskSignal(
                risk_type="adverse_media",
                category=str(ind["category"]),
                severity=str(ind["severity"]),
                rationale=f"Matched indicator keywords for category={ind['category']}.",
                risk_score=int(ind["score"]),
            )
            if best is None or sig.risk_score > best.risk_score:
                best = sig

    if best is not None:
        return best

    # Default: still keep as a low-score signal for human scan (can be disabled later).
    return RiskSignal(
        risk_type="adverse_media",
        category="general",
        severity="Low",
        rationale="No mapped risk indicators found; kept for analyst review.",
        risk_score=5,
    )


def severity_rank(severity: str) -> int:
    s = (severity or "").strip().lower()
    return {"high": 3, "medium": 2, "low": 1}.get(s, 0)


def max_severity(a: str, b: str) -> str:
    return a if severity_rank(a) >= severity_rank(b) else b


def parse_sanctions_signal(score: int, threshold: int) -> Tuple[str, str]:
    """
    Map OFAC fuzzy score to severity and a short rationale.
    """
    if score >= max(97, threshold + 5):
        return "High", "Very strong name match to OFAC SDN list."
    if score >= threshold:
        return "Medium", "Name match above screening threshold; requires human confirmation."
    return "Low", "Below threshold."

