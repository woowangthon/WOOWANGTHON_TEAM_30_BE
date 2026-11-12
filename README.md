# 여운 (Yeoun)

여운 — 소중한 사람의 실제 목소리로 남기는 추억 보관 서비스.

소중한 사람의 실제 목소리 녹음을 모아 정리하고, 말을 걸면 **새 문장을 지어내지 않고** 그 사람이 실제로 했던 말(원본 녹음)을 찾아 들려줍니다. 휴대폰에 흩어진 통화 녹음·동영상·음성 메시지에서 그 사람 목소리만 골라 정리하고, 부모님 목소리를 질문 카드로 **미리 남겨 두는** 기능도 있습니다.

> 처음 오셨다면: [docs/STATUS.md](docs/STATUS.md)(된 것·안 된 것) → [docs/DEPLOY.md](docs/DEPLOY.md)(배포) → [docs/TODO-team.md](docs/TODO-team.md)(사람이 할 일)

## 절대 원칙
1. **말은 원본만** — TTS, 목소리 복제, 그 사람인 척하는 LLM 응답을 만들지 않는다. 답은 언제나 실제 녹음 클립(원문 자막·날짜·출처).
2. **AI는 찾고 고르기만** — LLM은 후보 중 무엇을 들려줄지 고르고 이유를 말하는 데만 쓴다. 출력은 JSON 스키마로 검증하고, 후보 밖 ID·지어낸 인용은 버린다.
3. 서비스가 하는 말은 **'여운 안내'** 로 구분한다.
4. 맞는 녹음이 없으면 **"딱 맞는 녹음은 없어요"** 라고 말하고 가까운 추억을 보여 준다.
5. **AI가 없어도 돈다** — 키·네트워크가 없으면 mock·규칙 기반으로 전체 흐름이 동작한다.
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
대화 흐름: 위기 신호 검사 → 의도·키워드 → BM25(+임베딩) 후보 20개 → LLM이 최대 3개 고르기(검증) → 클립 카드 + 여운 안내

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

`make eval` 결과(mock, 2026-11-09): lite 96.7% / kiwi 100% top-3, '맞는 녹음 없음' 4/4.
실제 LLM으로 측정하려면 키를 넣고 `cd server && .venv/bin/python -m app.eval --llm`.

## AI 공급자 (키를 넣으면 바뀐다)

| 기능 | 공급자 | 키 없을 때 |
|---|---|---|
| 받아쓰기(STT) | openai(whisper-1), gemini | mock: 테스트 fixture 자막, 그 외엔 무음 구간만 나누고 자막은 비움(지어내지 않음) |
| 목소리 나누기 | openai(gpt-4o-transcribe-diarize) | none: 사용자가 '목소리 확인'에서 파일·클립 단위로 고름 |
| LLM(의도·고르기·태깅) | anthropic(기본 `claude-haiku-5-5`), openai, gemini, replay | mock: 사투리 정규화 + 개념 사전 + BM25 + 규칙 태깅 |
| 임베딩 | openai, gemini | none: BM25만 |

키는 `YEOUN_` 접두사 환경 변수로만 읽습니다(`YEOUN_ANTHROPIC_API_KEY`, `YEOUN_OPENAI_API_KEY`, `YEOUN_GEMINI_API_KEY`). 입력을 학습에 쓰는 무료 등급(예: Gemini 무료)은 production에서 실제 사용자 자료에 쓰지 않고, staging에서는 사용자가 동의한 경우에만 씁니다. 각 공간의 설정 → 외부 서비스에서 자료가 어디로 가는지 볼 수 있습니다.

## 배포 (Render)

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
