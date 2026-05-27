from __future__ import annotations

from dataclasses import asdict
from typing import List, Optional

from ..radar.models import RiskEvent


def _require_gspread():
    try:
        import gspread  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ImportError("Missing dependency: gspread. Install: pip install gspread google-auth") from e
    return gspread


RISK_EVENTS_HEADER = [
    "run_utc",
    "company",
    "severity",
    "category",
    "risk_type",
    "risk_score",
    "summary",
    "evidence_url",
    "source",
    "occurred_at_utc",
    "raw_score",
    "details",
    "llm_rationale",
]


def _event_to_row(run_utc: str, e: RiskEvent) -> List[str]:
    d = asdict(e)
    return [
        run_utc,
        d.get("company", ""),
        d.get("severity", ""),
        d.get("category", ""),
        d.get("risk_type", ""),
        "" if d.get("risk_score") is None else str(d.get("risk_score")),
        d.get("summary", ""),
        d.get("evidence_url", ""),
        d.get("source", ""),
        d.get("occurred_at_utc", ""),
        "" if d.get("raw_score") is None else str(d.get("raw_score")),
        d.get("details", ""),
        d.get("llm_rationale", ""),
    ]


def upsert_risk_events_sheet(
    *,
    service_account_json_path: str,
    spreadsheet_id: str,
    worksheet_name: str,
    run_utc: str,
    events: List[RiskEvent],
    create_if_missing: bool = True,
) -> int:
    """
    Append risk events to a worksheet.
    Returns number of appended rows.
    """
    gspread = _require_gspread()
    gc = gspread.service_account(filename=service_account_json_path)
    sh = gc.open_by_key(spreadsheet_id)

    try:
        ws = sh.worksheet(worksheet_name)
    except Exception:
        if not create_if_missing:
            raise
        ws = sh.add_worksheet(title=worksheet_name, rows=1000, cols=len(RISK_EVENTS_HEADER) + 2)

    # Ensure header exists.
    existing = ws.get_values("1:1")
    if not existing or (existing and existing[0] != RISK_EVENTS_HEADER):
        ws.update("A1", [RISK_EVENTS_HEADER])

    if not events:
        return 0

    rows = [_event_to_row(run_utc, e) for e in events]
    ws.append_rows(rows, value_input_option="RAW")
    return len(rows)


def get_spreadsheet_id_from_url(url_or_id: str) -> str:
    """
    Accept either a Google Sheets URL or an ID; return the ID.
    """
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("Missing spreadsheet id or URL.")
    if "/spreadsheets/d/" in s:
        # https://docs.google.com/spreadsheets/d/<ID>/edit...
        return s.split("/spreadsheets/d/")[1].split("/")[0]
    return s

