from __future__ import annotations
import httpx
from .config import settings

async def notify_admin(message: str) -> None:
    if not settings.telegram_bot_token or not settings.admin_telegram_chat_id:
        return
    url = f'https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage'
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(url, json={'chat_id': settings.admin_telegram_chat_id, 'text': message, 'disable_web_page_preview': True})
    except Exception:
        # Notification failure must never roll back a committed business transaction.
        return
