# Render에 배포하기 (친구 테스트용)

이 문서대로 하면 친구들이 링크 하나로 여운을 써 볼 수 있습니다. 처음 해 보는 분도 따라 할 수 있게 클릭 순서대로 적었어요. 30분쯤 걸립니다(대부분 빌드 기다리는 시간).

만들어지는 것 (모두 무료 등급):

| 이름 | 종류 | 하는 일 |
|---|---|---|
| Neon `yeoun` | PostgreSQL (Neon 무료) | 계정·자막·검색 색인, 그리고 암호화된 파일(Render 무료 등급은 디스크가 없어서). Render 밖에서 따로 만든다 |
| `yeoun-api` | Web Service (Docker) | FastAPI 서버 + ffmpeg. 올린 파일 처리도 이 안에서 함 |
| `yeoun-web` | Web Service (Node) | Next.js 화면. 브라우저의 `/api` 요청을 `yeoun-api`로 넘김 |

---

## 0. 준비

1. 이 저장소가 GitHub에 있고, 배포할 브랜치(보통 `main`)에 코드가 합쳐져 있어야 해요.
2. **Neon에서 DB 만들기** (Render 무료 PostgreSQL은 작업 공간당 1개뿐이고 30일 뒤 만료돼서, 만료 없는 Neon 무료 DB를 써요)
   1. https://neon.com 에 GitHub 계정으로 가입해요.
   2. **New Project** → Project name `yeoun`, Postgres version `16`, Region **AWS Asia Pacific (Singapore)** (Render 서버와 같은 지역) → **Create project**.
   3. 대시보드의 **Connect** 버튼 → **Connection pooling을 끈 상태**의 연결 주소(`postgresql://...neon.tech/neondb?sslmode=require...`)를 복사해 둬요. 1단계에서 `YEOUN_DATABASE_URL`에 넣어요. 비밀번호가 들어 있으니 다른 곳에 올리지 마세요.
3. https://render.com 에 GitHub 계정으로 가입하고, Render가 이 저장소를 읽을 수 있게 허용해 주세요.
4. 친구들에게 나눠 줄 **초대 코드**를 하나 정하세요. 예: `yeoun-friends-1109` (여러 개면 쉼표로 `코드1,코드2`)

## 1. Blueprint로 한 번에 만들기

1. Render 대시보드 오른쪽 위 **New +** → **Blueprint**
2. 저장소 `yeoun` 선택 → **Connect**
3. Blueprint Name에 `yeoun` 입력, Branch는 `main`
4. Render가 `render.yaml`을 읽고 `yeoun-api`, `yeoun-web` 두 개를 보여 줍니다. (DB는 0단계의 Neon)
5. 아래쪽에 **직접 넣어야 하는 값**(sync: false) 입력칸이 나와요:

| 변수 | 어디 | 넣을 값 | 필수 |
|---|---|---|---|
| `YEOUN_DATABASE_URL` | yeoun-api | 0단계에서 복사한 Neon 연결 주소 | 필수 |
| `YEOUN_INVITE_CODES` | yeoun-api | 0단계에서 정한 초대 코드 | 필수 |
| `YEOUN_API_ORIGIN` | yeoun-web | `https://yeoun-api.onrender.com` (아래 주의 참고) | 필수 |
| `YEOUN_PUBLIC_WEB_URL` | yeoun-api | 비워 두기 (브라우저 주소를 자동으로 씀) | 선택 |
| `YEOUN_ANTHROPIC_API_KEY` | yeoun-api | Anthropic API 키 (없으면 비워 두기) | 선택 |
| `YEOUN_OPENAI_API_KEY` | yeoun-api | OpenAI API 키 (없으면 비워 두기) | 선택 |
| `YEOUN_GEMINI_API_KEY` | yeoun-api | Gemini API 키 (없으면 비워 두기) | 선택 |

> **주의 — API 주소**: 서비스 이름 `yeoun-api`를 이미 다른 사람이 쓰고 있으면 Render가 `https://yeoun-api-abcd.onrender.com`처럼 뒤에 글자를 붙여요. 일단 위 값으로 넣고, 3단계에서 실제 주소를 확인해 고치면 됩니다.

> **키 없이도 됩니다.** 키를 비워 두면 기본 방식(mock·규칙)으로 모든 기능이 돌아가요. 다만 받아쓰기(음성 인식)가 꺼져 있어 올린 녹음의 자막은 비어 있고, 사용자가 '목소리 확인'에서 직접 적을 수 있어요. 미리 남기기 녹음은 질문과 연결되어 자막 없이도 찾아져요.

6. **Apply** 를 누르면 만들기 시작해요. API는 Docker 이미지를 빌드하느라 5~10분, 웹은 3~5분쯤 걸려요.

`YEOUN_MASTER_KEY`, `YEOUN_SESSION_SECRET`은 Render가 무작위 값으로 자동으로 만들어요(`generateValue`). **마스터 키를 잃거나 바꾸면 저장된 파일을 전혀 읽을 수 없으니**, 만들어진 뒤 yeoun-api → Environment에서 값을 복사해 비밀번호 관리자에 따로 보관해 두세요.

## 2. 기다리는 동안 알아 둘 것

- API 서비스가 시작될 때 자동으로: DB 스키마 적용(`alembic upgrade head`) → 샘플 공간 만들기(`python -m app.seed`) → 서버 시작. (`server/start.sh`)
- 무료 등급 설정은 `render.yaml`에 이미 들어 있어요: `YEOUN_ENV=staging`(초대 코드 필요), `YEOUN_STORAGE=db`, `YEOUN_WORKER_INLINE=true`, `YEOUN_TOKENIZER=lite`, 파일 하나 25MB·공간당 150MB·사용자당 300MB·하루 대화 150회.

## 3. API 주소 확인하고 맞추기

1. 대시보드에서 **yeoun-api**를 누르면 위쪽에 주소가 있어요 (예: `https://yeoun-api.onrender.com`).
2. 그 주소 뒤에 `/api/health`를 붙여 열어 보세요. 이렇게 나오면 정상이에요:
   ```json
   {"ok":true,"version":"0.1.0","db":true}
   ```
3. 주소가 1단계에서 넣은 `YEOUN_API_ORIGIN`과 **다르면**: **yeoun-web** → **Environment** → `YEOUN_API_ORIGIN`을 실제 주소로 고치고 → **Save, rebuild, and deploy**. (웹의 `/api` 연결은 빌드할 때 정해져서, 고친 뒤에는 꼭 다시 배포해야 해요.)

## 4. 배포 뒤 확인 (5분)

**yeoun-web** 주소(예: `https://yeoun-web.onrender.com`)를 열고 차례로 해 보세요.

- [ ] 첫 화면이 뜬다. (처음에는 "서버를 깨우는 중이에요" 띠가 1분쯤 보일 수 있어요)
- [ ] **가입 없이 샘플 공간 체험하기** → "[샘플] 김순자 할머니" 공간이 보인다.
- [ ] 샘플에서 "할머니 김치찌개 어떻게 끓였어?"라고 말을 걸면 김치찌개 이야기 클립과 '샘플 녹음 준비 중'이 보인다.
- [ ] "비트코인 사도 될까?"에는 "딱 맞는 녹음은 없어요"가 나온다.
- [ ] **시작하기**에서 초대 코드 없이 가입하면 "초대 코드가 있어야" 안내가 나오고, 코드를 넣으면 가입된다.
- [ ] 공간을 만들고 짧은 녹음(m4a 등)을 올리면 처리 단계가 하나씩 지나 "준비 완료"가 된다.
- [ ] 목소리 확인 → 대화가 된다.
- [ ] 미리 남기기에서 링크를 만들어 휴대폰으로 열면 큰 글씨 녹음 화면이 나온다.
- [ ] 설정 → 외부 서비스에 지금 쓰는 공급자가 보인다.

API 주소로 직접 확인할 수도 있어요: `https://<api 주소>/api/config` → `"env":"staging"`, `"sample_space_id"`가 `null`이 아니면 샘플까지 준비된 거예요.

## 5. 친구들에게 보내기

웹 주소와 초대 코드를 함께 보내 주세요. 예:

> 여운 테스트 링크: https://yeoun-web.onrender.com
> 가입할 때 초대 코드: yeoun-friends-1109
> 처음 열 때 1분쯤 '서버를 깨우는 중'이 나올 수 있어요. 실제 가족 녹음을 올려도 되지만, 아직 테스트 중이라 꼭 필요한 것만 올려 주세요.

---

## 환경 변수 전체 목록

`render.yaml`에 이미 들어 있는 값은 그대로 두면 됩니다. 바꾸고 싶으면 서비스 → Environment에서 고치고 다시 배포하세요.

### yeoun-api

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

### yeoun-web

| 변수 | 값 | 설명 |
|---|---|---|
| `YEOUN_API_ORIGIN` | `https://<api 주소>` | 필수. 바꾸면 웹을 다시 배포 |
| `NODE_VERSION` | `22` | |

---

## 무료 등급에서 알아 둘 것

- **잠들기**: 15분 동안 요청이 없으면 서비스가 잠들어요. 다시 열면 30초~1분 뒤에 깨어나요. 웹이 깨어날 때 API도 함께 깨우고(`web/src/instrumentation.ts`), 화면은 API가 HTML·502·연결 실패를 돌려주면 "서버를 깨우는 중이에요"를 띄우고 최대 2분 동안 자동으로 다시 시도해요.
- **처리 중에 잠들면**: 올린 파일 처리 중 서버가 잠들거나 다시 시작되면, 다음에 깨어날 때 남은 작업을 이어서 해요(최대 3번). 그래도 안 되면 '실패'로 표시되고 '다시 처리하기'를 누르면 돼요.
- **DB**: Neon 무료 DB는 만료가 없지만 5분 동안 쓰지 않으면 잠들어요(다음 요청 때 1초 안팎으로 깨어남). 무료 계산 시간이 프로젝트당 한 달 100 CU-시간이라, **UptimeRobot 등으로 24시간 깨워 두지 마세요**(한 달 내내 깨어 있으면 넘칩니다). 깨워 둬야 하면 심사 기간처럼 꼭 필요한 며칠만.
- **용량**: Neon 무료 DB는 프로젝트당 1GB예요. 파일도 DB에 넣으므로 공간·사용자 상한을 낮게 잡아 두었어요.
- **사용 시간**: 무료 인스턴스 시간은 워크스페이스 전체에 월 한도가 있어요. 웹·API 두 개가 함께 써요.

## 문제 해결

| 증상 | 확인할 것 |
|---|---|
| 화면에 "서버가 아직 깨어나지 않았어요"가 계속 나온다 | yeoun-api → Logs에서 시작 오류 확인. `/api/health`가 열리는지. `YEOUN_API_ORIGIN`이 실제 API 주소인지 |
| 웹 화면에서 모든 요청이 404 | `YEOUN_API_ORIGIN` 값을 고친 뒤 웹을 **다시 배포**했는지 |
| API 로그에 `YEOUN_MASTER_KEY가 필요합니다` | yeoun-api Environment에 `YEOUN_MASTER_KEY`가 있는지 (Blueprint로 만들면 자동) |
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
