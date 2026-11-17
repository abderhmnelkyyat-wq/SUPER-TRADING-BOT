#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-superbot}" "${POSTGRES_DB:-superbot}" | gzip > "backups/superbot-${stamp}.sql.gz"
echo "Backup written: backups/superbot-${stamp}.sql.gz"
