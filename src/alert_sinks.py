"""Alert delivery: Slack webhook, local file, stdout."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.config import SLACK_WEBHOOK_URL

log = logging.getLogger(__name__)

INCIDENT_LOG_PATH = Path("incidents.log")

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_LEADING_INCIDENT_RE = re.compile(r"^Incident \(job_id=[^)]+\)\s*\n+", re.MULTILINE)


def _to_slack_mrkdwn(text: str) -> str:
    """Convert the diagnosis body to Slack's mrkdwn dialect.

    - **bold** -> *bold* (Slack's single-asterisk bold)
    - Strip the duplicate "Incident (...)" header; the Block Kit header already shows it.
    """
    text = _LEADING_INCIDENT_RE.sub("", text, count=1)
    return _BOLD_RE.sub(r"*\1*", text)


def post_to_slack(
    summary: str,
    blocks: list | None = None,
    timeout: float = 5.0,
) -> bool:
    if not SLACK_WEBHOOK_URL:
        log.info("SLACK_WEBHOOK_URL unset; skipping Slack post")
        return False
    payload: dict = {"text": summary}
    if blocks:
        payload["blocks"] = blocks
    try:
        r = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=timeout)
        if r.status_code >= 300:
            log.warning("slack post returned %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception:
        log.exception("slack post failed")
        return False


def append_to_log(summary: str, path: Path | str = INCIDENT_LOG_PATH) -> None:
    p = Path(path)
    stamp = datetime.now(timezone.utc).isoformat()
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"=== {stamp} ===\n{summary}\n\n")


def print_to_stdout(summary: str) -> None:
    print(summary, flush=True)


def build_slack_blocks(job_id: int | None, status: str, diagnosis: str) -> list[dict]:
    header = f"JobWatch incident — job_id={job_id if job_id is not None else '?'} ({status})"
    body = _to_slack_mrkdwn(diagnosis)
    return [
        {"type": "header", "text": {"type": "plain_text", "text": header}},
        {"type": "section", "text": {"type": "mrkdwn", "text": body}},
    ]


def fan_out(
    summary: str,
    *,
    job_id: int | None = None,
    status: str = "failed",
) -> dict:
    blocks = build_slack_blocks(job_id, status, summary)
    slack_sent = post_to_slack(summary, blocks=blocks)
    append_to_log(summary)
    print_to_stdout(summary)
    return {"slack": slack_sent, "file": True, "stdout": True}
