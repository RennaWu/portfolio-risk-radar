"""
LLM-powered relevance filter and risk rationale generator.

Uses Claude to:
1. Determine if a news headline is actually about the portfolio company
   (entity disambiguation — e.g., "Cascade" the company vs "Cascade Mountains")
2. Generate a one-sentence risk rationale for relevant headlines
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMVerdict:
    headline: str
    is_relevant: bool
    risk_rationale: str
    confidence: float


_SYSTEM_PROMPT = (
    "You are a portfolio risk analyst at an investment firm. Your job is to review news "
    "headlines that were flagged by an automated monitoring system and determine whether "
    "each headline is genuinely about a specific portfolio company or is a false positive "
    "(e.g., a geographic feature, a common English word, or a different entity that shares "
    "the name)."
)


def _build_prompt(company_name: str, headlines: List[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines))
    return (
        f'The portfolio company is: "{company_name}"\n\n'
        f"Below are news headlines flagged by our monitoring system. For each headline:\n\n"
        f'1. **is_relevant** (bool): Is this headline actually about the portfolio company "{company_name}"? '
        f"Return false if it refers to a geographic feature, a common word, a different company/person, "
        f"or is otherwise unrelated.\n"
        f"2. **risk_rationale** (string): If relevant, write ONE concise sentence explaining the risk "
        f"implication for an investor holding this company. If not relevant, return an empty string.\n"
        f"3. **confidence** (float 0.0–1.0): How confident are you in your relevance judgment?\n\n"
        f"Headlines:\n{numbered}\n\n"
        f"Respond ONLY with a JSON array. Each element: "
        f'{{"index":<1-based>,"is_relevant":<bool>,"risk_rationale":"<string>","confidence":<float>}}'
    )


def _passthrough(headlines: List[str]) -> List[LLMVerdict]:
    return [
        LLMVerdict(headline=h, is_relevant=True, risk_rationale="", confidence=0.0)
        for h in headlines
    ]


def filter_with_llm(
    company_name: str,
    headlines: List[str],
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 2048,
) -> List[LLMVerdict]:
    """
    Call Claude to verify headline relevance and generate risk rationales.
    Gracefully degrades: returns all-relevant verdicts on any failure.
    """
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic package not installed; skipping LLM filter")
        return _passthrough(headlines)

    if not headlines:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(company_name, headlines)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        results = json.loads(raw)
    except Exception as e:
        logger.warning("LLM filter failed for %s: %s — keeping all headlines", company_name, e)
        return _passthrough(headlines)

    verdict_map: Dict[int, LLMVerdict] = {}
    for r in results:
        idx = int(r.get("index", 0))
        if 1 <= idx <= len(headlines):
            verdict_map[idx] = LLMVerdict(
                headline=headlines[idx - 1],
                is_relevant=bool(r.get("is_relevant", True)),
                risk_rationale=str(r.get("risk_rationale", "")),
                confidence=float(r.get("confidence", 0.5)),
            )

    return [
        verdict_map.get(
            i + 1,
            LLMVerdict(headline=h, is_relevant=True, risk_rationale="", confidence=0.0),
        )
        for i, h in enumerate(headlines)
    ]
