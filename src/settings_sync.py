"""Sync Telegram /settings from the Cloudflare Worker onto this PC."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import importlib.util

import httpx
import yaml

logger = logging.getLogger(__name__)


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "json_config_to_yaml.py"
    spec = importlib.util.spec_from_file_location("json_config_to_yaml", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.normalize(data)


def _base_url() -> str:
    url = (os.getenv("SETTINGS_CONFIG_URL") or "").strip()
    if not url:
        return ""
    return url[: -len("/config")] if url.endswith("/config") else url.rstrip("/")


def _token() -> str:
    return (os.getenv("SETTINGS_CONFIG_TOKEN") or "").strip()


def settings_enabled() -> bool:
    return bool(_base_url() and _token())


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_token()}"}


def fetch_live_config() -> dict[str, Any] | None:
    if not settings_enabled():
        return None
    url = f"{_base_url()}/config"
    with httpx.Client(timeout=30.0) as client:
        res = client.get(url, headers=_headers())
        res.raise_for_status()
        return res.json()


def fetch_job_config(job_id: str) -> dict[str, Any]:
    url = f"{_base_url()}/job/{job_id}"
    with httpx.Client(timeout=30.0) as client:
        res = client.get(url, headers=_headers())
        res.raise_for_status()
        return res.json()


def write_config_yaml(data: dict[str, Any], path: Path) -> dict[str, Any]:
    normalized = _normalize(data)
    path.write_text(
        yaml.safe_dump(normalized, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return normalized


def sync_shared_settings(config_path: Path) -> int | None:
    """
    Pull Telegram /settings into config.yaml.
    Returns poll_interval_minutes from live settings, or None if sync disabled.
    """
    if not settings_enabled():
        return None
    raw = fetch_live_config()
    if raw is None:
        return None
    normalized = write_config_yaml(raw, config_path)
    interval = int(normalized.get("poll_interval_minutes") or 30)
    logger.info(
        "Synced Telegram /settings → %s (%d searches, %d areas, interval=%d min)",
        config_path.name,
        len(normalized.get("searches") or []),
        len(normalized.get("market_areas") or []),
        interval,
    )
    return interval


def get_pending_scan() -> dict[str, Any] | None:
    if not settings_enabled():
        return None
    url = f"{_base_url()}/pending-scan"
    with httpx.Client(timeout=20.0) as client:
        res = client.get(url, headers=_headers())
        res.raise_for_status()
        data = res.json()
    if not data.get("pending"):
        return None
    return data


def ack_pending_scan(requested_at: Any) -> None:
    if not settings_enabled():
        return
    url = f"{_base_url()}/pending-scan/ack"
    with httpx.Client(timeout=20.0) as client:
        res = client.post(
            url,
            headers={**_headers(), "content-type": "application/json"},
            json={"requested_at": requested_at},
        )
        res.raise_for_status()
