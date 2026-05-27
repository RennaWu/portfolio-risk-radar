# Portfolio Risk Radar

> A lightweight, LLM-augmented risk monitoring pipeline for any portfolio of companies, suppliers, or vendors. Screens entities against **multi-jurisdictional sanctions lists** + **adverse media**, uses **Claude** to disambiguate false positives, and routes prioritized alerts to **Google Sheets** + **Slack**.

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Claude API](https://img.shields.io/badge/Claude-Sonnet_4-D97757.svg)](https://www.anthropic.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 🎯 Why This Project

Compliance, procurement, and risk teams face the same problem: **too much noise, not enough signal**. A name match on OFAC SDN could be a $50M sanctions exposure — or it could be that "Cascade" the portfolio company shares a name with the Cascade Mountains.

Traditional rule-based screening generates **thousands of false positives per week**. Analysts can't review them all, so they either ignore alerts (creating compliance risk) or burn out reviewing noise (creating operational cost).

**This project's contribution:** an LLM-augmented pipeline that combines deterministic rule-based screening with **Claude-powered entity disambiguation** — keeping the auditability of rules while eliminating the noise that rules can't filter.

---

## 🏗️ Architecture

```
┌──────────────────┐
│ Portfolio Source │ ← CSV file or generic JSON API
│ (any entity list)│
└────────┬─────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│         Risk Monitoring Pipeline           │
│                                            │
│  ┌──────────────────┐  ┌──────────────┐    │
│  │ Official Lists   │  │ News Sources │    │
│  │ (UN/UK/WB/OFAC)  │  │ (RSS/GDELT)  │    │
│  └────────┬─────────┘  └──────┬───────┘    │
│           │                   │            │
│           ▼                   ▼            │
│  ┌──────────────────┐  ┌──────────────┐    │
│  │ Fuzzy Matching   │  │ Rule-Based   │    │
│  │ (rapidfuzz)      │  │ Classifier   │    │
│  └────────┬─────────┘  └──────┬───────┘    │
│           │                   │            │
│           └────────┬──────────┘            │
│                    ▼                       │
│         ┌──────────────────────┐           │
│         │  Claude LLM Filter   │ ← Optional│
│         │  (entity disambig.)  │           │
│         └──────────┬───────────┘           │
│                    ▼                       │
│         ┌──────────────────────┐           │
│         │  Dedupe + Score Sort │           │
│         └──────────┬───────────┘           │
└────────────────────┼───────────────────────┘
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
┌──────────────────┐   ┌──────────────────┐
│ Google Sheets    │   │ Slack Webhook    │
│ (triage queue)   │   │ (high-sev only)  │
└──────────────────┘   └──────────────────┘
```

---

## 🔑 Key Technical Decisions

### 1. LLM as a **post-processing filter**, not a replacement

Rule-based matchers are **fast, deterministic, and auditable** — exactly what compliance teams need. But they generate noise.

Claude runs **after** the rules find candidates, asking two questions for each hit:

1. **Is this headline actually about the portfolio entity, or a false positive?**
2. **If real, what's the investor-facing risk in one sentence?**

This preserves rule auditability ("here's why we flagged it") while removing 60–80% of noise in practice.

```python
# llm_filter.py — graceful degradation
def filter_with_llm(company_name, headlines, api_key, model):
    """
    Returns LLMVerdict per headline.
    If anthropic package missing OR API fails → passthrough (keep all).
    Never blocks the pipeline.
    """
```

**Why it matters:** A compliance pipeline that silently drops events on LLM failure is a liability. We default to *keep more, not fewer* — humans decide which to discard.

### 2. **Fuzzy matching with token-set ratio**, not exact match

Entity names vary wildly across lists:
- *"Acme Corporation"* vs *"ACME CORP."* vs *"Acme Corp Holdings Inc."*
- Order-of-words doesn't matter (token_set_ratio over token_sort_ratio)
- Stop tokens like "Inc", "Ltd", "Corp" removed before matching

```python
# text_normalize.py
_STOP_TOKENS = {"inc", "corp", "ltd", "llc", "plc", "holdings", "group", ...}
```

Tuned thresholds:
- **Official lists** (UN/UK/World Bank): `min_score=97` — high precision, low recall (you don't want false sanctions hits)
- **OFAC SDN**: `min_score=92` with severity downgrade — name collisions common in OFAC data

### 3. **Multi-jurisdictional official lists** by design

Real-world risk requires multiple authorities. The system loads:

| Source | Type | Authority | Why |
|--------|------|-----------|-----|
| UN SC Consolidated | XML | United Nations | Global enforcement |
| UK Sanctions List | CSV | UK FCDO | Post-Brexit independent regime |
| World Bank Debarred Firms | JSON | World Bank | Procurement/anti-corruption |
| OFAC SDN | CSV | US Treasury | US-jurisdictional sanctions |

5,800+ entities cached locally with 48-hour TTL to avoid repeated downloads.

### 4. **Graceful degradation everywhere**

The pipeline never hard-fails on external dependencies:
- LLM unavailable → skip filter, keep all candidates
- GDELT rate-limited → fall back to Google News RSS
- One source down → continue with others
- No API key → still runs (degraded mode)

### 5. **Human-in-the-loop by design**

The system surfaces and packages evidence — it does **not** decide whether to escalate, hold, or exit. This is intentional. Risk tolerance is contextual; false positives have real cost. **AI proposes, human disposes.**

---

## 📊 Multi-Channel Output

| Channel | Use Case | Format |
|---------|----------|--------|
| **HTML Report** | Daily executive summary | Standalone, openable in browser |
| **Google Sheets** | Triage queue (analyst workflow) | Append rows, dedupe by transaction key |
| **Slack** | High-severity real-time alerts | Webhook with severity threshold |
| **CSV/JSON** | Downstream pipelines | Structured event records |

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- (Optional) Anthropic API key for LLM filtering

### Run it

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Dry run with sample portfolio (no Sheets/Slack writes)
python scripts/run_radar.py \
  --portfolio-file data/sample_portfolio.csv \
  --max-companies 25 \
  --official-lists un_sc,uk,worldbank \
  --news-source google_news_rss \
  --dry-run \
  --report

# 3. Live run (writes to Sheets + Slack)
# First: copy config_private.example.json -> config_private.json and fill in credentials
python scripts/run_radar.py \
  --portfolio-file data/sample_portfolio.csv \
  --max-companies 25 \
  --official-lists un_sc,uk,worldbank \
  --news-source google_news_rss \
  --report
```

### Use Your Own Portfolio

**Option A — CSV** (recommended):
```csv
company
Apple
Microsoft
...
```

**Option B — JSON API** (for orgs with internal portfolio services):
```bash
python scripts/run_radar.py \
  --portfolio-api-url https://your-internal-api.example.com/portfolio \
  --portfolio-api-name-field name \
  --portfolio-api-id-field id
```

---

## 🧠 Trade-offs and Production Considerations

| Aspect | This project | Production system would add |
|--------|-------------|-----------------------------|
| **Entity resolution** | Token-set fuzzy match | Embedding-based + entity graph DB |
| **LLM filtering** | Single-pass Claude call | Cached verdicts + confidence calibration |
| **News sources** | Google News RSS, GDELT | Premium feeds (Refinitiv, Dow Jones) |
| **Storage** | Google Sheets | Postgres + warm cache + audit log DB |
| **Compliance** | Best-effort dedupe | Full audit trail, SOC2-aligned retention |
| **Scaling** | Single-process Python | Async workers, queue-backed |

### What breaks at 10× scale

1. **Entity matching quality**: more false positives/negatives with common names and subsidiaries — needs supervised tuning
2. **External API throughput**: Google News, GDELT, World Bank rate limits become the bottleneck — needs async + queueing
3. **Sheets as event store**: noisy, slow, no real query — needs proper database
4. **LLM cost**: at 10×, single-pass Claude becomes $$$ — needs caching layer + smaller models for first-pass filter

---

## 📁 Repo Structure

```
portfolio-risk-radar/
├── README.md
├── LICENSE
├── requirements.txt
├── config_private.example.json
├── data/
│   └── sample_portfolio.csv         # S&P 500 sample for demo
├── docs/
│   └── demo_runbook.md              # How to verify a local run
├── scripts/
│   └── run_radar.py               # CLI entry point
└── src/
    ├── portfolio/
    │   └── portfolio_source.py      # CSV + generic JSON API loaders
    ├── risk_sources/
    │   ├── text_normalize.py        # Entity normalization
    │   ├── classifier.py            # Rule-based risk classifier
    │   ├── official_list_index.py   # Fuzzy matching engine
    │   ├── un_sc_sanctions.py       # UN SC Consolidated (XML)
    │   ├── uk_sanctions.py          # UK Sanctions List (CSV)
    │   ├── worldbank_debarred.py    # World Bank debarment (JSON)
    │   ├── ofac_sdn.py              # US OFAC SDN
    │   ├── google_news_rss.py       # Google News RSS
    │   ├── gdelt.py                 # GDELT (backup news)
    │   └── llm_filter.py            # Claude entity disambiguation
    ├── radar/
    │   ├── models.py                # RiskEvent dataclass
    │   └── pipeline.py              # End-to-end orchestration
    └── integrations/
        ├── google_sheets.py         # gspread writer
        └── slack_webhook.py         # Incoming webhook notifier
```

---

## 📚 What I Learned

- **LLMs as filters, not generators.** The strongest use of LLMs in compliance is *removing* noise, not creating outputs. Determinism remains in the rules; the LLM just answers "is this real?"
- **Graceful degradation is a feature, not an afterthought.** Compliance pipelines can't hard-fail. Every external dependency needs a fallback path.
- **Multi-source matching trumps single-source perfection.** No single sanctions list is comprehensive. Union of UK + UN + World Bank + OFAC catches what any one misses.

---

## 📄 License

MIT — see [LICENSE](LICENSE).
