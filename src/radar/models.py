from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RiskEvent:
    company: str
    risk_type: str  # "sanctions_match" | "adverse_media"
    category: str
    severity: str  # "High" | "Medium" | "Low"
    risk_score: int
    summary: str
    evidence_url: str = ""
    source: str = ""
    occurred_at_utc: str = ""
    raw_score: Optional[int] = None
    details: str = ""
    llm_rationale: str = ""

