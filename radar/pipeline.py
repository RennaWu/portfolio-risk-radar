from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..portfolio.portfolio_source import (
    PortfolioCompany,
    load_from_csv,
    load_from_json_api,
)
from ..risk_sources.classifier import (
    RiskSignal,
    classify_adverse_media,
    parse_sanctions_signal,
    severity_rank,
)
from ..risk_sources.gdelt import fetch_gdelt_articles
from ..risk_sources.google_news_rss import fetch_google_news_rss
from ..risk_sources.official_list_index import OfficialListIndex
from ..risk_sources.ofac_sdn import OfacSdnIndex, build_ofac_sdn_index
from ..risk_sources.llm_filter import filter_with_llm
from ..risk_sources.text_normalize import token_set
from ..risk_sources.uk_sanctions import load_uk_sanctions_entities
from ..risk_sources.un_sc_sanctions import load_un_consolidated_entities
from ..risk_sources.worldbank_debarred import load_worldbank_debarred_entities
from .models import RiskEvent


@dataclass(frozen=True)
class RadarConfig:
    max_companies: int = 60
    # News source: "google_news_rss" (default) or "gdelt"
    news_source: str = "google_news_rss"
    gdelt_days: int = 7
    gdelt_max_records: int = 10
    # GDELT free endpoint asks for ~1 request / 5 seconds.
    gdelt_sleep_s: float = 6.0
    ofac_min_score: int = 92
    official_lists: str = "un_sc"  # comma-separated: un_sc,uk,worldbank
    official_min_score: int = 97
    slack_min_severity: str = "High"
    # LLM-powered relevance filter (Claude)
    llm_api_key: str = ""
    llm_model: str = "claude-sonnet-4-20250514"


def utc_now_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).replace(microsecond=0).isoformat()


def _dedupe_events(events: List[RiskEvent]) -> List[RiskEvent]:
    seen = set()
    out: List[RiskEvent] = []
    for e in events:
        key = (
            e.company.lower().strip(),
            e.risk_type,
            e.category,
            e.evidence_url.strip(),
            str(e.raw_score or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _llm_filter_events(
    events: List[RiskEvent],
    api_key: str,
    model: str,
) -> List[RiskEvent]:
    """
    Run adverse-media events through Claude for entity-relevance disambiguation
    and risk-rationale generation. Official-list matches are kept as-is.
    """
    from dataclasses import replace

    keep: List[RiskEvent] = []
    adverse: Dict[str, List[RiskEvent]] = {}
    for e in events:
        if e.risk_type != "adverse_media":
            keep.append(e)
        else:
            adverse.setdefault(e.company, []).append(e)

    for company, company_events in adverse.items():
        headlines = [e.summary for e in company_events]
        verdicts = filter_with_llm(company, headlines, api_key, model=model)
        for ev, v in zip(company_events, verdicts):
            if v.is_relevant:
                rationale = v.risk_rationale or ""
                keep.append(replace(ev, llm_rationale=rationale))

    return keep


def _should_notify(severity: str, threshold: str) -> bool:
    return severity_rank(severity) >= severity_rank(threshold)


def run_portfolio_risk_radar(
    *,
    cfg: RadarConfig,
    portfolio_file: Optional[str] = None,
    portfolio_api_url: Optional[str] = None,
    portfolio_api_name_field: str = "name",
    portfolio_api_id_field: Optional[str] = None,
    ofac_index: Optional[OfacSdnIndex] = None,
    official_index: Optional[OfficialListIndex] = None,
    skip_official_lists: bool = False,
    skip_ofac: bool = False,
    skip_gdelt: bool = False,
    meta: Optional[Dict] = None,
) -> List[RiskEvent]:
    """
    Main entry point. Loads portfolio from CSV (preferred) or generic JSON API.

    Either portfolio_file or portfolio_api_url must be provided.
    """
    if portfolio_file:
        companies = load_from_csv(portfolio_file)
    elif portfolio_api_url:
        companies = load_from_json_api(
            portfolio_api_url,
            name_field=portfolio_api_name_field,
            id_field=portfolio_api_id_field,
        )
    else:
        raise ValueError(
            "Must provide either portfolio_file (CSV path) or portfolio_api_url (JSON endpoint)."
        )

    companies = companies[: max(1, int(cfg.max_companies))]
    if meta is not None:
        meta["companies_scanned"] = len(companies)

    idx = ofac_index
    if not skip_ofac and idx is None:
        idx = build_ofac_sdn_index()

    off_idx = official_index
    if not skip_official_lists and off_idx is None:
        enabled = [(x or "").strip().lower() for x in (cfg.official_lists or "").split(",") if (x or "").strip()]
        entries = []
        if "un_sc" in enabled:
            entries.extend(load_un_consolidated_entities())
        if "uk" in enabled:
            entries.extend(load_uk_sanctions_entities())
        if "worldbank" in enabled:
            entries.extend(load_worldbank_debarred_entities())
        if entries:
            if meta is not None:
                counts: Dict[str, int] = {}
                for e in entries:
                    counts[e.list_name] = counts.get(e.list_name, 0) + 1
                meta["official_entries_loaded"] = counts
            off_idx = OfficialListIndex(entries)

    events: List[RiskEvent] = []

    for c in companies:
        name = c.name

        if not skip_official_lists and off_idx is not None:
            matches = off_idx.match(name, min_score=int(cfg.official_min_score), top_k=1)
            for m in matches:
                category = "sanctions_official"
                if "WORLD_BANK" in m.list_name:
                    category = "debarment"
                events.append(
                    RiskEvent(
                        company=name,
                        risk_type="official_list_match",
                        category=category,
                        severity="High",
                        risk_score=100,
                        summary=f"Official list match: {m.list_name} -> {m.matched_name} (score={m.score})",
                        evidence_url=m.source_url,
                        source=m.list_name,
                        occurred_at_utc="",
                        raw_score=int(m.score),
                        details=f"entry_id={m.entry_id}",
                    )
                )

        if not skip_ofac and idx is not None:
            matches = idx.match(name, min_score=int(cfg.ofac_min_score), top_k=1)
            for m in matches:
                sev, rationale = parse_sanctions_signal(int(m.score), int(cfg.ofac_min_score))
                events.append(
                    RiskEvent(
                        company=name,
                        risk_type="sanctions_match",
                        category="sanctions",
                        severity=sev,
                        risk_score=100 if sev == "High" else (80 if sev == "Medium" else 40),
                        summary=f"Potential OFAC SDN match: {m.matched_name} (score={m.score})",
                        evidence_url="https://sanctionslist.ofac.treas.gov/Home/SdnList",
                        source="OFAC SDN",
                        occurred_at_utc="",
                        raw_score=int(m.score),
                        details=f"ENT_NUM={m.ent_num} | Type={m.sdn_type} | Programs={m.programs} | {rationale}",
                    )
                )

        if not skip_gdelt:
            if (cfg.news_source or "").strip().lower() == "gdelt":
                if float(cfg.gdelt_sleep_s) > 0:
                    time.sleep(float(cfg.gdelt_sleep_s))
                articles = fetch_gdelt_articles(
                    name,
                    days=int(cfg.gdelt_days),
                    max_records=int(cfg.gdelt_max_records),
                    sleep_s=float(cfg.gdelt_sleep_s),
                )
                for a in articles:
                    sig: RiskSignal = classify_adverse_media(a.title, a.snippet)
                    events.append(
                        RiskEvent(
                            company=name,
                            risk_type="adverse_media",
                            category=sig.category,
                            severity=sig.severity,
                            risk_score=int(sig.risk_score),
                            summary=a.title,
                            evidence_url=a.url,
                            source=f"GDELT:{a.domain}",
                            occurred_at_utc=a.seen_date_utc,
                            raw_score=None,
                            details=sig.rationale,
                        )
                    )
            else:
                rss_items = fetch_google_news_rss(name, max_records=int(cfg.gdelt_max_records))
                for a in rss_items:
                    company_tokens = token_set(name)
                    title_tokens = token_set(a.title)
                    if company_tokens:
                        overlap = len(company_tokens.intersection(title_tokens))
                        min_overlap = 2 if len(company_tokens) >= 2 else 1
                        if len(company_tokens) == 1:
                            tok = next(iter(company_tokens))
                            if len(tok) < 5:
                                continue
                        if overlap < min_overlap:
                            continue
                    sig: RiskSignal = classify_adverse_media(a.title, "")
                    events.append(
                        RiskEvent(
                            company=name,
                            risk_type="adverse_media",
                            category=sig.category,
                            severity=sig.severity,
                            risk_score=int(sig.risk_score),
                            summary=a.title,
                            evidence_url=a.url,
                            source=f"GoogleNewsRSS:{a.source}",
                            occurred_at_utc=a.published_utc,
                            raw_score=None,
                            details=sig.rationale,
                        )
                    )

    events = _dedupe_events(events)

    if cfg.llm_api_key:
        pre_count = len([e for e in events if e.risk_type == "adverse_media"])
        events = _llm_filter_events(events, cfg.llm_api_key, cfg.llm_model)
        post_count = len([e for e in events if e.risk_type == "adverse_media"])
        if meta is not None:
            meta["llm_filtered"] = pre_count - post_count
            meta["llm_model"] = cfg.llm_model

    events.sort(key=lambda e: (-int(getattr(e, "risk_score", 0) or 0), -severity_rank(e.severity), e.company.lower(), e.risk_type))
    return events


def filter_notifiable_events(events: List[RiskEvent], slack_min_severity: str) -> List[RiskEvent]:
    return [e for e in events if _should_notify(e.severity, slack_min_severity)]
