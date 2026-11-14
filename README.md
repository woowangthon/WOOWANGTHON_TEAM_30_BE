# 여운 (Yeoun)

여운 — 소중한 사람의 실제 목소리로 남기는 추억 보관 서비스.

소중한 사람의 실제 목소리 녹음을 모아 정리하고, 가족이 메시지를 보내면 메신저처럼 **그분의 답장 하나**가 옵니다(기억 대화). 녹음에 그대로 있는 말이면 **실제 목소리(원본 녹음)** 로 답하고, 녹음에 없는 말이면 녹음에서 뽑은 그분의 말투로 AI가 짧게 만든 답을 **'AI가 만든 말'로 표시하고 근거 녹음과 함께** 보여 줍니다. 근거가 없으면 지어내지 않습니다. 휴대폰에 흩어진 통화 녹음·동영상·음성 메시지에서 그 사람 목소리만 골라 정리하고, 부모님 목소리를 질문 카드로 **미리 남겨 두는** 기능도 있습니다.

> 처음 오셨다면: [docs/STATUS.md](docs/STATUS.md)(된 것·안 된 것) → [docs/DEPLOY.md](docs/DEPLOY.md)(배포) → [docs/TODO-team.md](docs/TODO-team.md)(사람이 할 일)

## 절대 원칙
1. **목소리는 원본만, 만든 말은 표시** — TTS·목소리 복제는 하지 않는다. 녹음에 있는 말은 실제 녹음 클립(원문 자막·날짜·출처)으로 답한다. 녹음에 없는 말을 AI가 만들면 반드시 **'AI가 만든 말'** 로 표시하고 근거 녹음(1~3개)을 붙인다. 근거 녹음이 없으면 만들지 않는다.
2. **AI 출력은 서버가 다시 검사** — LLM 출력은 JSON 스키마로 검증하고, 후보 밖 ID·근거 없는 답·금지 표현은 버린다. 원본 녹음으로 답할 때 자막은 LLM이 옮긴 글자가 아니라 DB 원문을 쓴다.
3. 서비스가 하는 말은 **'여운 안내'** 로 구분한다. 유언·돈·용서·의료·법률처럼 그분이 남긴 말로 대신할 수 없는 주제는 그분 말투로 답하지 않고 여운 안내로 답한다. 위기 신호가 있으면 그분 목소리를 멈추고 상담 번호를 안내한다.
4. 녹음으로 답할 수 없으면 **지어내지 않고** "녹음에 없어서 말을 지어내지 않을게요"라고 안내한다.
5. **AI가 없어도 돈다** — 키·네트워크가 없으면 mock·규칙 기반으로 돌고, 이때 대화는 녹음에 있는 말만 들려준다.

옛 검색형 대화 API(`POST /api/spaces/{id}/chat`, 클립 카드 고르기)는 서버에 남아 있지만 지금 화면은 쓰지 않습니다.
6. **기본은 비공개** — 올린 사람과 초대한 가족만 본다.

## 구성

```
server/    FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 16, ffmpeg, 작업 워커
shared/    공통 스키마(schema.json → Pydantic·TS 코드 생성), 질문 카드 72개
fixtures/  가상 샘플 공간, 골든 세트, 테스트용 합성 오디오와 mock 자막
docs/      결정 기록, 현황, 배포, 개인정보, 생성형 AI 사용 내역, 변경 기록
render.yaml  Render 무료 등급 배포(API, DB는 Neon)
```

저장소는 대회 권장에 따라 셋으로 나눴습니다. 실행되는 AI 코드는 서버 설정·데이터 형식·오디오 처리와 함께 쓰여서 이 BE 저장소의 `server/app/ai`, `search`, `care`에 있습니다.

| 저장소 | 내용 |
|---|---|
| [FE](https://github.com/woowangthon/WOOWANGTHON_TEAM_30_FE) | Next.js 15 + TypeScript + Tailwind 4 — 브라우저는 /api만 부른다 (rewrites → 이 서버) |
| BE (이 저장소) | 서버, 실행되는 AI 코드, DB, 배포 설정 |
| [AI](https://github.com/woowangthon/WOOWANGTHON_TEAM_30_AI) | AI 설계 설명, 평가 질문 세트, 검증 결과 |

로컬에서 화면까지 함께 돌리려면 FE 저장소를 이 저장소 옆에 나란히 clone해 두세요(`make` 명령이 `../WOOWANGTHON_TEAM_30_FE`를 찾습니다. 다른 위치면 `WEB_DIR=경로`).

처리 흐름: 올리기 → 정규화(16kHz mono) → 받아쓰기(STT) → 목소리 나누기 → 문장 클립(2~30초) → 주제 태그 → 색인
처리 흐름에서 통화·영상인데 목소리가 하나로만 나오면, 말한 내용으로 두 사람을 나눈 뒤(`server/app/ai/content_split.py`) 사용자가 '목소리 확인'에서 그분 목소리를 고릅니다.

기억 대화 흐름(`POST /api/spaces/{id}/talk`, `server/app/services/talk.py`):
위기 신호 → 금지 주제 → 그분 목소리로 확인된 녹음만 검색(BM25, 12개) + 녹음 전체에서 뽑은 말투 카드(`services/persona.py`) → LLM이 ① 그대로 답이 되는 원본 녹음 하나를 고르거나 ② 근거 녹음과 함께 1~3문장 답장 → 서버 검증 → 답장 하나 (`original` 실제 목소리 / `generated` AI가 만든 말+근거 / `guide` 여운 안내 / `crisis`)

## 로컬에서 실행

필요한 것: Python 3.12, Node 22, PostgreSQL 16, ffmpeg (선택: Docker로 PostgreSQL 띄우기)

```bash
cp .env.example .env
```

```bash
make db-up        # Docker가 있으면 PostgreSQL 16을 띄운다 (없으면 직접 설치한 PostgreSQL에 yeoun/yeoun_test DB를 만든다)
```

```bash
make dev          # 의존성 설치 → 마이그레이션 → 샘플 공간 → API(8000) + 웹(3000)
```

브라우저에서 http://localhost:3000 을 열고 "가입 없이 샘플 공간 체험하기"를 눌러 보세요. API 문서는 http://localhost:8000/api/docs (개발 환경에서만).

PostgreSQL을 직접 쓸 때 만들 것:

```bash
createuser -P yeoun   # 비밀번호 yeoun
createdb -O yeoun yeoun && createdb -O yeoun yeoun_test
```

## make 명령

| 명령 | 하는 일 |
|---|---|
| `make dev` | API와 웹을 함께 실행 (처음이면 설치·마이그레이션·샘플까지) |
| `make test` | 서버 pytest(PostgreSQL `yeoun_test` 사용) + 웹 vitest |
| `make e2e` | Playwright 브라우저 시나리오 4개 (전용 DB `yeoun_e2e`, mock 공급자) |
| `make seed` | 샘플 공간 "[샘플] 김순자 할머니" 만들기 (`fixtures/demo/demo-XX.m4a`가 있으면 그 녹음 사용) |
| `make eval` | 골든 세트 30문항 top-3 정확도 + '맞는 녹음 없음' 판정 (lite·kiwi 토크나이저 각각) |
| `make lint` | ruff, eslint, tsc, 생성 파일 최신 여부 |
| `make gen` | `shared/schema.json` → `server/app/schemas/generated.py`, FE 저장소의 `src/lib/api-types.gen.ts` |

`make eval` 결과(mock, 2026-11-09, 검색만): lite 96.7% / kiwi 100% top-3, '맞는 녹음 없음' 4/4.

기억 대화 검증(`cd server && python -m app.eval_talk --live <API 주소>`, 2026-11-15, 배포본 샘플 공간·NOVA): 골든 30문항 모두 실제 녹음으로 답함(기대한 녹음 29~30/30), AI가 만든 답 14개 모두 근거 녹음 붙음·사람 판정 문제 3개, 녹음에 없는 질문 4개 중 안내 2, 위기 문장 규칙 감지 15/20(놓침 4), 금지 주제 17/20, 일상 문장 오탐 0. 자세한 표는 [docs/GENAI_USAGE.md](docs/GENAI_USAGE.md).
실제 LLM으로 측정하려면 키를 넣고 `cd server && .venv/bin/python -m app.eval --llm`.

## AI 공급자 (키를 넣으면 바뀐다)

| 기능 | 공급자 | 키 없을 때 |
|---|---|---|
| 받아쓰기(STT) | **nova(Soniox `stt-async-v5`, 화자 분리 포함)**, openai(whisper-1), gemini | mock: 테스트 fixture 자막, 그 외엔 무음 구간만 나누고 자막은 비움(지어내지 않음) |
| 목소리 나누기 | **nova(받아쓰기 결과의 화자를 그대로 씀)**, openai(gpt-4o-transcribe-diarize) | none: 사용자가 '목소리 확인'에서 파일·클립 단위로 고름 |
| LLM(의도·고르기·태깅·말투 요약·답장·내용으로 목소리 나누기) | **nova(`claude-haiku-5-5`)**, anthropic(기본 `claude-haiku-5-5`), openai, gemini, replay | mock: 사투리 정규화 + 개념 사전 + BM25 + 규칙 태깅 |
| 임베딩 | **nova(`text-embedding-3-small`)**, openai, gemini | none: BM25만 |

`auto`는 표의 왼쪽부터 키가 있는 공급자를 씁니다. 지금 배포는 **충북대 NOVA API Gateway** 키 하나(`YEOUN_NOVA_API_KEY`)로 받아쓰기·화자 분리·LLM·임베딩을 모두 처리합니다. NOVA는 팀원마다 월 무료 크레딧이 있어서(11/14 NOVA 콘솔에서 1인 월 5,000 확인), 크레딧이 떨어지면 다른 팀원의 키로 이 값만 바꾸면 됩니다. 크레딧이 없거나 호출이 실패하면 기본 방식(mock)으로 넘어가 서비스는 멈추지 않습니다.

키는 `YEOUN_` 접두사 환경 변수로만 읽습니다(`YEOUN_NOVA_API_KEY`, `YEOUN_ANTHROPIC_API_KEY`, `YEOUN_OPENAI_API_KEY`, `YEOUN_GEMINI_API_KEY`). 입력을 학습에 쓰는 무료 등급(예: Gemini 무료)은 production에서 실제 사용자 자료에 쓰지 않고, staging에서는 사용자가 동의한 경우에만 씁니다. 각 공간의 설정 → 외부 서비스에서 자료가 어디로 가는지 볼 수 있습니다.

## 배포 (Render)

**지금 배포된 주소** (2026-11-13)

| 서비스 | 주소 | 설정 |
|---|---|---|
| 화면 (FE 저장소) | https://yeoun-team30-web.onrender.com | Render `yeoun-team30-web`, Node 22, Free, Singapore |
| API (이 저장소) | https://yeoun-team30-api.onrender.com/api/health | Render `yeoun-team30-api`, Docker, Free, Singapore |
| DB | Neon `yeoun-team30` | Postgres 16, Singapore |

API 주소의 맨 앞(`/`)은 404가 정상입니다. 이 서버는 `/api/...`에만 응답하고 화면은 FE 주소에서 봅니다. Render는 공개 저장소 주소로 연결돼 있어 **push해도 자동 배포되지 않습니다.** main에 머지한 뒤 Render에서 Manual Deploy를 누르세요. (`render.yaml`의 `autoDeploy: true`는 Blueprint로 만들 때만 적용됩니다.)

`render.yaml`로 API(Docker, ffmpeg 포함)가 Render 무료 등급으로 뜨고, DB는 Neon 무료 PostgreSQL을 연결합니다. 화면은 FE 저장소에서 따로 배포합니다. 클릭 순서와 넣을 환경 변수는 [docs/DEPLOY.md](docs/DEPLOY.md)를 보세요.

무료 등급은 15분 동안 요청이 없으면 잠듭니다. 웹이 시작할 때 API를 함께 깨우고, 화면은 "서버를 깨우는 중이에요" 안내와 함께 최대 2분 자동으로 다시 시도합니다.

## 문서

- [docs/STATUS.md](docs/STATUS.md) — 된 것·안 된 것·사람이 할 일
- [docs/decisions.md](docs/decisions.md) — 묻지 않고 내린 결정과 이유
- [docs/DEPLOY.md](docs/DEPLOY.md) — Render 배포
- [docs/TODO-team.md](docs/TODO-team.md) — 샘플 녹음, API 키, R2, Render
- [docs/privacy.md](docs/privacy.md) — 개인정보 처리방침 초안
- [docs/GENAI_USAGE.md](docs/GENAI_USAGE.md) — 생성형 AI 사용 내역(공모전 기획안용)
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — 날짜별 변경 기록
- [docs/demo-recording-script.md](docs/demo-recording-script.md) — 샘플 녹음 대본(가상 인물)
