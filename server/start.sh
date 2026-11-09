#!/bin/sh
# 컨테이너 시작 스크립트 (Render)
set -e
alembic upgrade head
python -m app.seed || echo "[yeoun] 샘플 공간 만들기를 건너뜀 (서비스는 계속 시작)"
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" --workers 1 \
  --proxy-headers --forwarded-allow-ips "*" --timeout-keep-alive 75 --no-access-log
