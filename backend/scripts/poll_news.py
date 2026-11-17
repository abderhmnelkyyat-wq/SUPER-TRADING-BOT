#!/usr/bin/env python3
"""Fetch all enabled RSS/Atom feeds once. Intended for cron/systemd timer."""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.db import SessionLocal  # noqa: E402
from app.integrations.news import poll_enabled_rss_sources  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        results = poll_enabled_rss_sources(db)
        for result in results:
            print(result)
        failed = sum(1 for result in results if not result.get('ok'))
        print(f"RSS sources: {len(results)}, failed: {failed}")
        return 1 if failed else 0
    finally:
        db.close()


if __name__ == '__main__':
    raise SystemExit(main())
