# Render에 배포하기 (BE)

AI 우왕톤 팀 30의 BE 저장소(`woowangthon/WOOWANGTHON_TEAM_30_BE`)를 Render 무료 등급에 올리는 순서예요. 화면(Next.js)은 [FE 저장소](https://github.com/woowangthon/WOOWANGTHON_TEAM_30_FE)에서 따로 배포하고, 이 문서의 7단계에서 둘을 이어요.

만들어지는 것 (모두 무료 등급):

| 이름 | 종류 | 하는 일 |
|---|---|---|
| Neon `yeoun-team30` | PostgreSQL (Neon 무료) | 계정·자막·검색 색인, 그리고 암호화된 파일(Render 무료 등급은 디스크가 없어서). Render 밖에서 따로 만든다 |
| `yeoun-team30-api` | Web Service (Docker) | FastAPI 서버 + ffmpeg + 실행되는 AI 코드. 올린 파일 처리도 이 안에서 함 |
| (FE 저장소) | Web Service (Node) 또는 Vercel | Next.js 화면. 브라우저의 `/api` 요청을 `yeoun-team30-api`로 넘김 |

---

## 지금 배포 상태 (2026-11-13)

| 항목 | 값 |
|---|---|
| API | `yeoun-team30-api` — https://yeoun-team30-api.onrender.com (Docker `./server/Dockerfile`, 헬스 체크 `/api/health`, Free, Singapore) |
| 화면 | `yeoun-team30-web` — https://yeoun-team30-web.onrender.com (FE 저장소, `npm ci --no-audit --no-fund && npm run build` → `npm run start`, Node 22) |
| DB | Neon 프로젝트 `yeoun-team30` (Singapore, Postgres 16, Connection pooling 끈 직접 연결) |
| 연결 방식 | 두 서비스 모두 **공개 저장소 주소(B)** — 자동 배포 없음. main 머지 뒤 각 서비스에서 **Manual Deploy → Deploy latest commit** |
| API에 넣은 값 | 아래 1·2단계 값 전부 + `YEOUN_PUBLIC_WEB_URL=https://yeoun-team30-web.onrender.com` (비밀 값은 Render Environment에만 있음) |
| 화면에 넣은 값 | `YEOUN_API_ORIGIN=https://yeoun-team30-api.onrender.com`, `NODE_VERSION=22`, `NEXT_TELEMETRY_DISABLED=1` |
| 확인 | `/api/health` ok·db true, `/api/config` staging·샘플 공간 있음, 화면의 샘플 대화에서 클립 카드가 나옴 |
| 남은 일 | 마스터 키 백업. AI 공급자는 NOVA 키(`YEOUN_NOVA_API_KEY`)로 연결됨(11/14 확인) |

아래는 처음부터 다시 만들 때의 순서예요.

## 0. 준비

1. 배포할 코드가 이 저장소의 `main`에 합쳐져 있어야 해요. (팀 룰: main에는 PR로만 합침)
2. **Neon DB**: 이미 쓰던 Neon `yeoun` 프로젝트가 있으면 그대로 써도 돼요. 새로 만들 때는:
   1. https://neon.com → **New Project** → Project name `yeoun`, Postgres `16`, Region **AWS Asia Pacific (Singapore)** → **Create project**
   2. **Connect** → **Connection pooling을 끈** 연결 주소(`postgresql://...neon.tech/neondb?sslmode=require...`)를 복사해요. 비밀번호가 들어 있으니 채팅·문서·저장소에 올리지 마세요.
3. **Render가 woowangthon 조직 저장소를 읽을 수 있게 하기** (둘 중 하나)
   - **A. GitHub 앱 연결 (push하면 자동 배포)**: Render에서 GitHub 연결 설정을 열어 Render GitHub 앱이 `woowangthon` 조직 저장소에 접근하도록 요청해요. 조직 관리자가 아니면 '요청'만 가고, **디스코드에 팀 번호(30)와 저장소 이름을 남기면 운영진이 승인**해 줘요.
   - **B. 공개 저장소 주소로 연결 (승인 없이 바로)**: 저장소가 공개라서 Render의 **Public Git Repository**에 `https://github.com/woowangthon/WOOWANGTHON_TEAM_30_BE`를 넣어 만들 수 있어요. 자동 배포가 안 되니 main이 바뀌면 대시보드에서 **Manual Deploy**를 눌러요. 승인이 나면 A로 바꾸면 돼요.
4. 심사위원·팀원에게 줄 **초대 코드**를 정해요. 예: `yeoun-judge-1115` (여러 개면 쉼표로 `코드1,코드2`)

## 1. 서비스 만들기

**A(앱 연결)인 경우 — Blueprint**
1. Render 대시보드 **New +** → **Blueprint** → `WOOWANGTHON_TEAM_30_BE` 선택 → Branch `main`
2. `render.yaml`을 읽어 `yeoun-team30-api` 하나를 보여 줘요. 아래 2단계 값을 넣고 **Apply**.

**B(공개 주소)인 경우 — Web Service 직접 만들기**
1. **New +** → **Web Service** → **Public Git Repository**에 저장소 주소 → Connect
2. Name `yeoun-team30-api`, Language **Docker**, Branch `main`, Region **Singapore**, Instance **Free**
3. **Advanced**에서 Dockerfile Path `./server/Dockerfile`, Docker Build Context `.`, Health Check Path `/api/health`
4. 환경 변수는 `render.yaml`의 `envVars`를 그대로 옮겨 적고, 아래 2단계 값을 넣어요. `YEOUN_MASTER_KEY`·`YEOUN_SESSION_SECRET`은 **Generate** 버튼으로 무작위 값을 만들어요.

## 2. 직접 넣어야 하는 값

| 변수 | 넣을 값 | 필수 |
|---|---|---|
| `YEOUN_DATABASE_URL` | 0단계 Neon 연결 주소 | 필수 |
| `YEOUN_INVITE_CODES` | 0단계에서 정한 초대 코드 | 필수 |
| `YEOUN_PUBLIC_WEB_URL` | FE 배포 주소 (7단계 뒤에 넣어도 됨) | 권장 |
| `YEOUN_ANTHROPIC_API_KEY` | Anthropic API 키 — 클립 고르기·의도 파악·태깅 | 선택 |
| `YEOUN_OPENAI_API_KEY` | OpenAI API 키 — 받아쓰기·화자 분리·임베딩 | 선택 |
| `YEOUN_GEMINI_API_KEY` | Gemini API 키 | 선택 |

> **키는 대시보드 입력칸에만** 넣어요. 저장소·Notion·디스코드에 붙여 넣지 마세요.

> **키 없이도 뜹니다.** 키가 없으면 기본 방식(mock·규칙)으로 돌아가요. 다만 받아쓰기가 꺼져 올린 녹음의 자막이 비고, 심사 기준 'AI 활용도'에서 실제 AI가 연결됐다고 말할 수 없어요. 제출 전에는 키를 넣어 주세요.

`YEOUN_MASTER_KEY`는 저장된 파일을 여는 열쇠예요. **잃거나 바꾸면 저장된 파일을 전혀 읽을 수 없으니**, 만들어진 뒤 Environment에서 값을 복사해 비밀번호 관리자에 따로 보관하세요. 기존 MVP 배포의 Neon DB를 그대로 쓴다면 **그때의 `YEOUN_MASTER_KEY`를 똑같이** 넣어야 예전 파일이 열려요(새 키를 만들면 예전 파일은 못 엶).

빌드는 Docker 이미지라 5~10분쯤 걸려요. 시작할 때 자동으로 DB 스키마 적용(`alembic upgrade head`) → 샘플 공간 만들기(`python -m app.seed`) → 서버 시작을 해요(`server/start.sh`).

## 3. API 확인

1. 서비스 위쪽 주소(예: `https://yeoun-team30-api.onrender.com`. 이름이 겹치면 뒤에 글자가 붙어요)를 복사해 둬요.
2. `<주소>/api/health` → `{"ok":true,"version":"0.1.0","db":true}`
3. `<주소>/api/config` → `"env":"staging"`, `"sample_space_id"`가 `null`이 아니면 샘플까지 준비된 거예요.
4. 설정 → 외부 서비스(또는 기억 대화 응답의 `provider`)에서 mock이 아니라 실제 공급자가 보이면 AI 키도 연결된 거예요.

## 4. FE와 잇기 (FE 저장소에서)

FE 배포의 환경 변수에 아래를 넣고 다시 배포해요. `/api` 연결은 **빌드할 때** 정해져서 값을 바꾸면 꼭 다시 배포해야 해요.

| 변수 | 값 |
|---|---|
| `YEOUN_API_ORIGIN` | 3단계의 API 주소 (끝에 `/` 없이) |
| `NODE_VERSION` | `22` (Render Node일 때) |

FE 주소가 나오면 이 서비스의 `YEOUN_PUBLIC_WEB_URL`에 넣고 저장해요(녹음·초대 링크가 그 주소로 만들어짐).

## 5. 배포 뒤 확인 (5분)

FE 주소를 열고 차례로 해 보세요.

- [ ] 첫 화면이 뜬다. (처음에는 "서버를 깨우는 중이에요" 띠가 1분쯤 보일 수 있어요)
- [ ] **가입 없이 샘플 공간 체험하기** → "[샘플] 김순자 할머니" 공간이 보인다.
- [ ] 샘플에서 "할머니 김치찌개 어떻게 끓였어?" → 그 녹음이 '실제 목소리' 말풍선으로 나온다(AI 응답이라 'AI가 만든 말'로 나올 수도 있음).
- [ ] "비트코인 사도 될까?"에는 "말을 지어내지 않을게요" 안내가 나온다.
- [ ] 초대 코드 없이 가입하면 안내가 나오고, 코드를 넣으면 가입된다.
- [ ] 공간을 만들고 짧은 녹음(m4a 등)을 올리면 처리 단계가 하나씩 지나 "준비 완료"가 된다.
- [ ] 대화가 되고, 설정 → 외부 서비스에 지금 쓰는 공급자가 보인다.

## 6. 심사 기간 (11/16~11/20)

- 제출한 커밋과 배포된 버전이 같은지 확인해요(Render → Events에 커밋 해시가 보여요).
- 무료 서비스는 15분 동안 요청이 없으면 잠들어요. 심사 기간 며칠만 깨워 두는 방법은 아래 '무료 등급에서 알아 둘 것'을 보세요.

---

## 환경 변수 전체 목록

`render.yaml`에 이미 들어 있는 값은 그대로 두면 됩니다. 바꾸고 싶으면 서비스 → Environment에서 고치고 다시 배포하세요.

### yeoun-team30-api

| 변수 | 기본값(render.yaml) | 설명 |
|---|---|---|
| `YEOUN_DATABASE_URL` | (직접) | Neon 연결 주소. 서버가 `postgresql+psycopg://`로 바꿔 읽어요 |
| `YEOUN_ENV` | `staging` | `staging`: 초대 코드·이용 한도. `production`: 학습에 쓰는 무료 AI 금지 |
| `YEOUN_MASTER_KEY` | 자동 생성 | 파일 암호화 키. **백업 필수, 바꾸지 말 것** |
| `YEOUN_SESSION_SECRET` | 자동 생성 | 서명 URL·세션용 |
| `YEOUN_INVITE_CODES` | (직접) | 쉼표로 여러 개 |
| `YEOUN_STORAGE` | `db` | `db`(무료 시연) / `s3`(R2 등, 실사용) / `local`(개발) |
| `YEOUN_WORKER_INLINE` | `true` | 무료 등급엔 백그라운드 워커가 없어 API 안에서 처리 |
| `YEOUN_TOKENIZER` | `lite` | 메모리 512MB라 lite. 유료 인스턴스면 `kiwi`(이미지 빌드 시 `WITH_KIWI=true`) |
| `YEOUN_MAX_FILE_MB` | `25` | 파일 하나 상한 |
| `YEOUN_SPACE_QUOTA_MB` | `150` | 공간 하나의 저장 상한 (Neon 무료 DB는 프로젝트당 1GB) |
| `YEOUN_USER_UPLOAD_QUOTA_MB` | `300` | 사용자 한 명이 올릴 수 있는 총량 |
| `YEOUN_CHAT_DAILY_LIMIT` | `150` | 사용자당 하루 대화 횟수 |
| `YEOUN_SAMPLE_CHAT_PER_MINUTE` | `60` | 로그인 없는 샘플 체험의 분당 횟수(접속 주소별) |
| `YEOUN_PUBLIC_WEB_URL` | (비움) | 녹음·초대 링크 주소. 비우면 브라우저 주소 |
| `YEOUN_ANTHROPIC_API_KEY` | (선택) | 클립 고르기·태깅·의도 파악 (기본 모델 `claude-haiku-5-5`, `YEOUN_ANTHROPIC_MODEL`로 변경) |
| `YEOUN_NOVA_API_KEY` | (권장) | **충북대 NOVA API Gateway** 키 하나로 받아쓰기(Soniox `stt-async-v5`, 화자 분리 포함)·LLM(`claude-haiku-5-5`)·임베딩(`text-embedding-3-small`). 키가 있으면 다른 공급자보다 먼저 씀. 크레딧이 떨어지면 다른 팀원 키로 바꾸기 |
| `YEOUN_NOVA_LLM_MODEL` 등 | 위 기본값 | `YEOUN_NOVA_BASE_URL`, `YEOUN_NOVA_LLM_MODEL`, `YEOUN_NOVA_EMBEDDING_MODEL`, `YEOUN_NOVA_STT_MODEL`, `YEOUN_NOVA_STT_POLL_SEC`로 바꿀 수 있음 |
| `YEOUN_OPENAI_API_KEY` | (선택) | 받아쓰기 `whisper-1`, 화자 분리 `gpt-4o-transcribe-diarize`, 임베딩 `text-embedding-3-small` |
| `YEOUN_GEMINI_API_KEY` | (선택) | Gemini. 무료 등급(`YEOUN_GEMINI_TIER=free`)은 동의한 사용자에게만 |
| `YEOUN_STT_PROVIDER` 등 | `auto` | `auto`면 키가 있는 공급자를 씀. `mock`으로 강제할 수도 있음 |

R2(실사용 저장소)를 쓸 때 추가: `YEOUN_STORAGE=s3`, `YEOUN_S3_BUCKET`, `YEOUN_S3_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com`, `YEOUN_S3_REGION=auto`, `YEOUN_S3_ACCESS_KEY_ID`, `YEOUN_S3_SECRET_ACCESS_KEY`. 저장소를 바꿔도 이미 올린 파일은 옮겨지지 않아요(새로 올린 것부터 적용).

### yeoun-team30-web (FE 저장소)

| 변수 | 값 | 설명 |
|---|---|---|
| `YEOUN_API_ORIGIN` | `https://<api 주소>` | 필수. 바꾸면 웹을 다시 배포 |
| `NODE_VERSION` | `22` | |

---

## 무료 등급에서 알아 둘 것

- **잠들기**: 15분 동안 요청이 없으면 서비스가 잠들어요. 다시 열면 30초~1분 뒤에 깨어나요. 웹이 깨어날 때 API도 함께 깨우고(FE 저장소 `src/instrumentation.ts`), 화면은 API가 HTML·502·연결 실패를 돌려주면 "서버를 깨우는 중이에요"를 띄우고 최대 2분 동안 자동으로 다시 시도해요.
- **처리 중에 잠들면**: 올린 파일 처리 중 서버가 잠들거나 다시 시작되면, 다음에 깨어날 때 남은 작업을 이어서 해요(최대 3번). 그래도 안 되면 '실패'로 표시되고 '다시 처리하기'를 누르면 돼요.
- **DB**: Neon 무료 DB는 만료가 없지만 5분 동안 쓰지 않으면 잠들어요(다음 요청 때 1초 안팎으로 깨어남). 무료 계산 시간이 프로젝트당 한 달 100 CU-시간이라, **UptimeRobot 등으로 24시간 깨워 두지 마세요**(한 달 내내 깨어 있으면 넘칩니다). 깨워 둬야 하면 심사 기간처럼 꼭 필요한 며칠만.
- **용량**: Neon 무료 DB는 프로젝트당 1GB예요. 파일도 DB에 넣으므로 공간·사용자 상한을 낮게 잡아 두었어요.
- **사용 시간**: 무료 인스턴스 시간은 워크스페이스 전체에 월 한도가 있어요. FE·API 두 서비스가 함께 써요.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 화면에 "서버가 아직 깨어나지 않았어요"가 계속 나온다 | yeoun-team30-api → Logs에서 시작 오류 확인. `/api/health`가 열리는지. `YEOUN_API_ORIGIN`이 실제 API 주소인지 |
| 웹 화면에서 모든 요청이 404 | FE의 `YEOUN_API_ORIGIN` 값을 고친 뒤 FE를 **다시 배포**했는지 |
| API 로그에 `YEOUN_MASTER_KEY가 필요합니다` | yeoun-team30-api Environment에 `YEOUN_MASTER_KEY`가 있는지 (Blueprint로 만들면 자동) |
| 가입이 안 된다 | 초대 코드가 `YEOUN_INVITE_CODES`와 정확히 같은지(대소문자 구분) |
| 업로드가 "파일이 너무 커요" | 25MB 상한. 휴대폰에서 영상 자르기 후 올리기, 또는 `YEOUN_MAX_FILE_MB` 조정 |
| 처리 중 서비스가 재시작된다(메모리) | `YEOUN_TOKENIZER=lite`인지. 큰 영상(25MB 가까이)을 여러 개 동시에 올리지 않기 |
| 녹음 링크 주소가 이상하다 | `YEOUN_PUBLIC_WEB_URL`에 웹 주소를 직접 넣기 |

## 정식 서비스로 키울 때

1. `YEOUN_ENV=production` (학습에 쓰는 무료 AI는 실제 사용자 자료에 쓰지 않음)
2. 저장소를 R2로: `YEOUN_STORAGE=s3` + 위의 S3 변수
3. 유료 인스턴스 + 별도 워커: API에 `YEOUN_WORKER_INLINE=false`, Background Worker 서비스를 같은 Docker 이미지로 만들고 시작 명령 `python -m app.worker`
4. 메모리가 넉넉하면 kiwi: 이미지 빌드 인자 `WITH_KIWI=true`, `YEOUN_TOKENIZER=kiwi`
5. 개인정보 처리방침·이용약관 법률 검토 ([privacy.md](privacy.md))
