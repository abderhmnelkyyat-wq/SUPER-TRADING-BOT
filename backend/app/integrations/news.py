from __future__ import annotations

import ipaddress
import socket
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import IntegrationSource
from ..security import now
from .intelligence import add_intelligence_item, parse_datetime

MAX_FEED_BYTES = 1_500_000
USER_AGENT = "SuperTradingBot-NewsReader/1.1 (+https://example.invalid; RSS reader)"


def validate_feed_url_syntax(url: str) -> str:
    parts = urlsplit((url or "").strip())
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        raise ValueError("مصدر RSS يجب أن يستخدم رابط HTTPS صالحًا")
    if parts.port not in (None, 443):
        raise ValueError("منافذ RSS المخصصة غير مسموح بها لأسباب أمنية")
    host = parts.hostname.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("اسم المضيف المحلي غير مسموح")
    return url


def _resolve_public_host(host: str) -> None:
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("تعذر التحقق من عنوان مصدر الأخبار") from exc
    if not addresses:
        raise ValueError("مصدر الأخبار لا يملك عنوانًا صالحًا")
    for raw in addresses:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
        if not ip.is_global:
            raise ValueError("مصدر الأخبار يشير إلى عنوان شبكة خاص أو غير عام")


def _download_feed(url: str) -> bytes:
    validate_feed_url_syntax(url)
    host = urlsplit(url).hostname
    assert host
    _resolve_public_host(host)
    chunks: list[bytes] = []
    total = 0
    try:
        with httpx.Client(timeout=httpx.Timeout(12.0, connect=5.0), follow_redirects=False,
                          trust_env=False, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"}) as client:
            with client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise ValueError("تم رفض إعادة توجيه مصدر الأخبار")
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_FEED_BYTES:
                        raise ValueError("حجم موجز الأخبار تجاوز الحد المسموح")
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise ValueError(f"فشل جلب موجز الأخبار: {type(exc).__name__}") from exc
    body = b"".join(chunks)
    upper = body[:100_000].upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ValueError("تم رفض XML يحتوي على تعريفات كيان خارجية")
    return body


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(element: ET.Element, names: set[str]) -> str:
    for child in list(element):
        if _local_name(child.tag) in names:
            if _local_name(child.tag) == "link":
                href = child.attrib.get("href")
                if href:
                    return href
            return "".join(child.itertext()).strip()
    return ""


def parse_feed(body: bytes) -> list[dict]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise ValueError("صيغة موجز RSS/Atom غير صالحة") from exc
    entries = [node for node in root.iter() if _local_name(node.tag) in {"item", "entry"}]
    results: list[dict] = []
    for node in entries[:100]:
        title = _child_text(node, {"title"})
        summary = _child_text(node, {"description", "summary", "content", "encoded"})
        link = _child_text(node, {"link"})
        external_id = _child_text(node, {"guid", "id"}) or link
        published = _child_text(node, {"pubdate", "published", "updated", "date"})
        if title:
            results.append({
                "external_id": external_id,
                "title": title,
                "summary": summary,
                "url": link,
                "published_at": parse_datetime(published),
            })
    return results



def inspect_rss_source(source: IntegrationSource) -> dict:
    """Fetch and parse an RSS/Atom source without persisting its entries."""
    body = _download_feed(source.url or "")
    entries = parse_feed(body)
    return {
        "ok": True,
        "items_found": len(entries),
        "sample": entries[0] if entries else None,
    }


def poll_rss_source(db: Session, source: IntegrationSource) -> dict:
    try:
        body = _download_feed(source.url or "")
        entries = parse_feed(body)
        inserted = 0
        duplicates = 0
        for entry in entries:
            _, duplicate = add_intelligence_item(db, source, item_type="news", symbols=[], **entry)
            duplicates += int(duplicate)
            inserted += int(not duplicate)
        source.last_success_at = now()
        source.last_error = None
        db.commit()
        return {"source_id": source.id, "inserted": inserted, "duplicates": duplicates, "ok": True}
    except Exception as exc:
        db.rollback()
        source = db.get(IntegrationSource, source.id)
        if source:
            source.last_error = str(exc)[:300]
            db.commit()
        return {"source_id": source.id, "inserted": 0, "duplicates": 0, "ok": False, "error": str(exc)[:300]}


def poll_enabled_rss_sources(db: Session) -> list[dict]:
    sources = db.scalars(select(IntegrationSource).where(
        IntegrationSource.enabled.is_(True), IntegrationSource.kind == "rss"
    )).all()
    return [poll_rss_source(db, source) for source in sources]
