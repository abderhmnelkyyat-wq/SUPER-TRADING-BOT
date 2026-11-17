#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then cp .env.example .env; fi
if [ ! -f backend/.env ]; then cp backend/.env.example backend/.env; fi
if grep -q 'REPLACE_WITH_LONG_RANDOM_PASSWORD' .env; then
  pw="$(openssl rand -hex 32)"
  sed -i.bak "s/REPLACE_WITH_LONG_RANDOM_PASSWORD/${pw}/" .env
  rm -f .env.bak
fi
if grep -q 'REPLACE_WITH_64_RANDOM_CHARACTERS_OR_MORE' backend/.env; then
  auth="$(openssl rand -hex 48)"
  license="$(openssl rand -hex 48)"
  sed -i.bak "s/REPLACE_WITH_64_RANDOM_CHARACTERS_OR_MORE/${auth}/" backend/.env
  sed -i.bak "0,/REPLACE_WITH_A_DIFFERENT_64_RANDOM_CHARACTERS_OR_MORE/s//${license}/" backend/.env
  rm -f backend/.env.bak
fi
printf '\nتم إنشاء ملفات .env. عدّل PUBLIC_DOMAIN في .env وPUBLIC_APP_URL في backend/.env ثم راجع باقي إعدادات الإشعارات.\n'
printf 'لا ترفع ملفات .env إلى Git.\n'
