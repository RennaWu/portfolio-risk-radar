from __future__ import annotations

from typing import Any, Dict, Optional

import requests


def post_slack_webhook(
    webhook_url: str,
    text: str,
    blocks: Optional[list] = None,
    timeout_s: int = 15,
) -> None:
    """
    Post a message to Slack via Incoming Webhook URL.
    """
    if not webhook_url or not webhook_url.strip():
        raise ValueError("Missing Slack webhook_url.")
    payload: Dict[str, Any] = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    r = requests.post(webhook_url, json=payload, timeout=timeout_s)
    r.raise_for_status()


def format_risk_event_slack_text(company: str, severity: str, summary: str, url: str = "") -> str:
    base = f"[{severity}] {company}: {summary}"
    return f"{base}\n{url}".strip() if url else base

