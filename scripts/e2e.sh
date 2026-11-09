#!/usr/bin/env bash
# 브라우저 시나리오 테스트(Playwright).
# 테스트 전용 DB(yeoun_e2e)와 임시 저장소로 API(8100)·웹(3100)을 띄우고, 끝나면 정리한다.
# AI 공급자는 모두 mock — 키가 없어도 돈다.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export LANG=C.UTF-8 LC_ALL=C.UTF-8   # 한글 파일 경로를 Playwright가 읽을 수 있게
API_PORT=${E2E_API_PORT:-8100}
WEB_PORT=${E2E_WEB_PORT:-3100}
DB_NAME=${E2E_DB_NAME:-yeoun_e2e}
PG_ADMIN_URL=${E2E_PG_ADMIN_URL:-postgresql://yeoun:yeoun@localhost:5432/postgres}
DATA_DIR="$(mktemp -d -t yeoun-e2e-XXXX)"
LOG_DIR="$ROOT/web/test-results"
mkdir -p "$LOG_DIR"

psql "$PG_ADMIN_URL" -q -c "DROP DATABASE IF EXISTS $DB_NAME" -c "CREATE DATABASE $DB_NAME" >/dev/null

export YEOUN_ENV=test
export YEOUN_DATABASE_URL="${PG_ADMIN_URL%/*}/$DB_NAME"
export YEOUN_DATA_DIR="$DATA_DIR"
export YEOUN_STORAGE=local
export YEOUN_MASTER_KEY="ZTJlLW9ubHktbWFzdGVyLWtleS1ub3QtYS1zZWNyZXQhIQ=="
export YEOUN_WORKER_INLINE=true
export YEOUN_WORKER_POLL_SEC=0.3
export YEOUN_STT_PROVIDER=mock YEOUN_LLM_PROVIDER=mock YEOUN_DIARIZATION_PROVIDER=mock YEOUN_EMBEDDING_PROVIDER=none
export YEOUN_TOKENIZER=${YEOUN_TOKENIZER:-lite}
export YEOUN_PUBLIC_WEB_URL="http://localhost:$WEB_PORT"
export YEOUN_SAMPLE_CHAT_PER_MINUTE=200

cleanup() {
  [[ -n "${API_PID:-}" ]] && kill "$API_PID" 2>/dev/null || true
  [[ -n "${WEB_PID:-}" ]] && kill "$WEB_PID" 2>/dev/null || true
  rm -rf "$DATA_DIR"
}
trap cleanup EXIT

cd "$ROOT/server"
.venv/bin/alembic upgrade head >/dev/null
.venv/bin/python -m app.seed --force >/dev/null
# test 환경에서도 인라인 워커를 켠다 (e2e는 실제 서버처럼 돈다)
YEOUN_ENV=development .venv/bin/uvicorn app.main:app --port "$API_PORT" >"$LOG_DIR/api.log" 2>&1 &
API_PID=$!

cd "$ROOT/web"
YEOUN_API_ORIGIN="http://localhost:$API_PORT" npx next build >"$LOG_DIR/web-build.log" 2>&1
YEOUN_API_ORIGIN="http://localhost:$API_PORT" npx next start -p "$WEB_PORT" >"$LOG_DIR/web.log" 2>&1 &
WEB_PID=$!

for i in $(seq 1 60); do
  if curl -sf "http://localhost:$WEB_PORT/api/health" >/dev/null; then break; fi
  sleep 1
done

E2E_BASE_URL="http://localhost:$WEB_PORT" npx playwright test --trace off "$@"
