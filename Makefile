# 여운 — 개발 명령 모음. `make help`로 목록을 볼 수 있다.
SHELL := /bin/bash
.DEFAULT_GOAL := help

# .env가 있으면 읽는다 (YEOUN_ 변수만 쓴다. 키는 커밋하지 말 것)
-include .env
export

PYTHON ?= $(shell command -v python3.12 || command -v python3)
VENV := server/.venv
VPY := $(VENV)/bin/python
UV := $(shell command -v uv)
YEOUN_DATABASE_URL ?= postgresql+psycopg://yeoun:yeoun@localhost:5432/yeoun
export YEOUN_DATABASE_URL
# 화면 코드는 FE 저장소에 있다. 두 저장소를 같은 폴더 아래에 나란히 clone해 두면 그대로 동작한다.
WEB_DIR ?= ../WOOWANGTHON_TEAM_30_FE
export WEB_DIR

.PHONY: help setup setup-server setup-web db-up db-down migrate dev api web test test-server test-web e2e seed eval lint fmt gen gen-check clean

help: ## 명령 목록
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  make %-12s %s\n", $$1, $$2}'

setup: setup-server setup-web ## 서버(Python)·웹(Node) 의존성 설치

setup-server: $(VENV)/.installed
$(VENV)/.installed: server/pyproject.toml
ifdef UV
	cd server && uv venv -p 3.12 .venv -q --allow-existing && uv pip install -q -p .venv/bin/python -e ".[kiwi,s3,dev]"
else
	$(PYTHON) -m venv $(VENV) && $(VPY) -m pip install -q --upgrade pip && $(VPY) -m pip install -q -e "server[kiwi,s3,dev]"
endif
	@touch $@

setup-web: $(WEB_DIR)/node_modules/.installed
$(WEB_DIR)/node_modules/.installed: $(WEB_DIR)/package-lock.json
	cd $(WEB_DIR) && npm ci --no-audit --no-fund
	@touch $@

db-up: ## 로컬 PostgreSQL 16 (docker compose)
	docker compose up -d db

db-down:
	docker compose down

migrate: setup-server ## DB 스키마 적용 (alembic)
	cd server && .venv/bin/alembic upgrade head

dev: setup migrate seed ## API(8000)와 웹(3000)을 함께 실행
	@echo "▶ http://localhost:3000  (API: http://localhost:8000/api/docs)"
	@trap 'kill 0' INT TERM; \
	(cd server && .venv/bin/uvicorn app.main:app --reload --port 8000) & \
	(cd $(WEB_DIR) && npm run dev) & \
	wait

api: setup-server ## API만 실행
	cd server && .venv/bin/uvicorn app.main:app --reload --port 8000

web: setup-web ## 웹만 실행 (FE 저장소, WEB_DIR)
	cd $(WEB_DIR) && npm run dev

test: test-server test-web ## 단위·통합 테스트 (pytest + vitest)

test-server: setup-server
	cd server && .venv/bin/pytest

test-web: setup-web
	cd $(WEB_DIR) && npx vitest run

e2e: setup ## 브라우저 시나리오 테스트 (Playwright, 테스트 DB 사용)
	./scripts/e2e.sh

seed: setup-server ## 샘플 공간 만들기 (fixtures/demo에 녹음이 있으면 placeholder 대신 사용)
	cd server && .venv/bin/python -m app.seed

eval: setup-server ## 골든 세트로 top-3 검색 정확도 측정 (mock에서도 동작)
	cd server && .venv/bin/python -m app.eval

lint: setup gen-check ## 정적 검사 (ruff, eslint, tsc, 생성 파일 최신 여부)
	cd server && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd $(WEB_DIR) && npx eslint . && npx tsc --noEmit

fmt: setup-server ## 서버 코드 정리
	cd server && .venv/bin/ruff check --fix . && .venv/bin/ruff format .

gen: ## shared/schema.json → Pydantic·TS 타입 생성
	$(PYTHON) shared/codegen.py

gen-check:
	$(PYTHON) shared/codegen.py --check

clean:
	rm -rf $(WEB_DIR)/.next $(WEB_DIR)/test-results $(WEB_DIR)/playwright-report server/.pytest_cache server/.ruff_cache
