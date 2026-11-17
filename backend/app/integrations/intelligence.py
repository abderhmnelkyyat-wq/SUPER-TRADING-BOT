from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IntegrationSource, IntelligenceItem
from ..security import uid, now


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)


def clean_text(value: str | None, limit: int = 5000) -> str:
    if not value:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(value)
        text = " ".join(parser.parts)
    except Exception:
        text = re.sub(r"<[^>]*>", " ", value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def safe_external_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if len(value) > 2048:
        return None
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.rstrip('.').lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost")):
        return None
    if parts.port not in (None, 443):
        return None
    if parts.scheme == "http":
        # Links from a feed are display-only, but HTTPS is preferred and required for feed endpoints.
        return None
    return value


def parse_datetime(value: str | None) -> datetime:
    if value:
        from email.utils import parsedate_to_datetime
        try:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass
    return now()


def add_intelligence_item(
    db: Session,
    source: IntegrationSource,
    *,
    external_id: str,
    item_type: str,
    title: str,
    summary: str = "",
    url: str | None = None,
    published_at: datetime | None = None,
    symbols: list[str] | None = None,
) -> tuple[IntelligenceItem, bool]:
    title = clean_text(title, 300)
    summary = clean_text(summary, 5000)
    if not title:
        raise ValueError("العنوان مطلوب")
    if item_type not in {"news", "market_event", "bot_message"}:
        raise ValueError("نوع المحتوى غير مسموح")

    external_id = (external_id or "").strip()
    if len(external_id) > 200:
        external_id = hashlib.sha256(external_id.encode("utf-8")).hexdigest()
    if not external_id:
        external_id = hashlib.sha256(f"{title}|{summary}|{url or ''}".encode("utf-8")).hexdigest()
    existing = db.scalar(select(IntelligenceItem).where(
        IntelligenceItem.source_id == source.id,
        IntelligenceItem.external_id == external_id,
    ))
    if existing:
        source.last_seen_at = now()
        return existing, True

    normalized_symbols: list[str] = []
    for symbol in symbols or []:
        token = re.sub(r"[^A-Za-z0-9._-]", "", str(symbol).upper())[:40]
        if token and token not in normalized_symbols:
            normalized_symbols.append(token)
        if len(normalized_symbols) >= 20:
            break

    item = IntelligenceItem(
        id=uid(), source_id=source.id, external_id=external_id,
        item_type=item_type, title=title, summary=summary,
        url=safe_external_url(url), symbols_json=json.dumps(normalized_symbols),
        published_at=published_at or now(), received_at=now(),
        trust_status="unverified_external",
    )
    db.add(item)
    source.last_seen_at = now()
    return item, False


def item_view(item: IntelligenceItem, source_name: str) -> dict:
    try:
        symbols = json.loads(item.symbols_json or "[]")
    except Exception:
        symbols = []
    return {
        "id": item.id,
        "type": item.item_type,
        "title": item.title,
        "summary": item.summary,
        "url": item.url,
        "symbols": symbols,
        "source": source_name,
        "published_at": item.published_at.isoformat(),
        "received_at": item.received_at.isoformat(),
        "trust_status": item.trust_status,
        "can_trigger_trades": False,
    }
