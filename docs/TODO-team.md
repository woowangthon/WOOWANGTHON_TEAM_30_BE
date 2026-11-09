# 사람이 할 일 (TODO-team)

코드로는 할 수 없거나, 사람이 결정·책임져야 하는 일이에요. 위에서부터 순서대로 하면 돼요.

---

## 1. 배포 전에 꼭

- [ ] **Render에 배포하기** — 친구들이 링크로 써 보려면 필요해요.
  - 방법: `docs/DEPLOY.md`를 처음부터 따라 하기 (Blueprint로 DB·API·웹이 한 번에 만들어져요).
  - 넣을 값: `YEOUN_INVITE_CODES`(초대 코드), `YEOUN_API_ORIGIN`(웹 서비스에 API 주소).
- [ ] **초대 코드 정하기** — staging은 초대 코드가 있어야 가입할 수 있어요.
  - 방법: 추측하기 어려운 코드를 2~3개 만들어 `YEOUN_INVITE_CODES`에 쉼표로 넣기 (예: `yeoun-friends-7k2m,yeoun-family-q9x4`).
  - 코드를 바꾸면 Render가 API를 다시 시작해요. 이미 가입한 사람은 영향 없어요.
- [ ] **마스터 키 백업** — `YEOUN_MASTER_KEY`를 잃거나 바꾸면 **저장된 모든 파일을 다시 열 수 없어요.**
  - 방법: Render 대시보드 → yeoun-api → Environment → `YEOUN_MASTER_KEY` 값을 복사해 팀 비밀번호 관리자(1Password 등)에 보관. 채팅·문서·커밋에 붙여 넣지 않기.
- [ ] **무료 데이터베이스 만료 대비** — Render 무료 PostgreSQL은 만든 지 일정 기간(현재 30일)이 지나면 만료돼요.
  - 방법: 테스트 기간을 그 안에 끝내거나, 유료 플랜으로 올리거나, 만료 전에 공지하고 새로 만들기. 만료되면 자료가 모두 사라진다고 친구들에게 미리 알리기.

## 2. 샘플 녹음 (가상 인물 목소리)

- [ ] **샘플 공간 녹음하기** — 지금 샘플 클립은 '샘플 녹음 준비 중'으로 보여요.
  - 대본: `docs/demo-recording-script.md` (40줄, 가상 인물 '김순자 할머니' 연기 — 실존 인물 흉내 금지)
  - 파일: `fixtures/demo/demo-01.m4a` … `demo-40.m4a` (mp3·wav도 됨, 이름만 맞추기)
  - 확인: 로컬에서 `make seed` → 녹음한 클립만 원본으로 바뀌고 나머지는 placeholder로 남아요.
- [ ] **녹음한 팀원의 동의 받기** — 팀원 목소리도 실제 사람의 개인정보예요.
  - 녹음 파일은 기본으로 커밋되지 않아요(`.gitignore`의 `fixtures/demo/*.m4a`, `*.mp3`, `*.wav` 세 줄).
  - Render 샘플에도 쓰려면: 녹음한 사람이 공개에 동의 → `.gitignore`에서 그 세 줄을 지우고 커밋. (`.dockerignore`는 이 파일들을 막지 않아요.) 나중에 빼 달라고 하면 파일을 지우고 다시 배포하기.

## 3. AI 키 (선택이지만 실사용에 필요)

키가 없어도 모든 흐름이 규칙 기반으로 돌아가요. 다만 **받아쓰기는 키가 있어야** 실제 자막이 생겨요(없으면 사용자가 직접 적어야 해요).

- [ ] **OpenAI 키** → `YEOUN_OPENAI_API_KEY`
  - 쓰는 곳: 받아쓰기(`whisper-1`), 화자 분리(`gpt-4o-transcribe-diarize`), 임베딩(`text-embedding-3-small`), 음성으로 말 걸기
- [ ] **Anthropic 키** → `YEOUN_ANTHROPIC_API_KEY`
  - 쓰는 곳: 의도 파악, 클립 고르기, 주제 태깅, 위험 신호 보조 판단 (기본 모델 `claude-haiku-5-5`)
- [ ] (선택) **Gemini 키** → `YEOUN_GEMINI_API_KEY`
  - 유료 등급이면 `YEOUN_GEMINI_TIER=paid`도 넣기. 무료 등급은 입력을 학습에 쓸 수 있어서 staging에서는 동의한 사용자에게만, production에서는 쓰지 않아요.
- [ ] **키 다루는 규칙**
  - 키는 Render 대시보드(Environment)에만 넣기. 코드·`.env`·채팅·이슈에 붙여 넣지 않기.
  - 각 공급자 콘솔에서 **월 사용 한도(spending limit)** 걸기.
- [ ] **키를 넣은 뒤 실제로 확인하기** — 실제 공급자 코드는 개발 환경에서 키로 호출해 보지 못했어요.
  - 로컬: `server/.env` 대신 셸에서 키를 넣고 `cd server && .venv/bin/python -m app.eval --llm` (Makefile의 `make eval`은 옵션을 넘기지 않아요)
  - 실제 통화 녹음(본인 녹음) 하나를 올려 자막·화자 분리·태그가 잘 되는지, 설정 → 외부 서비스에 '사용 중'으로 보이는지 확인
  - 문제가 있으면 `docs/STATUS.md`에 적기

## 4. 실사용 준비

- [ ] **Cloudflare R2로 파일 저장소 바꾸기** — DB 저장(`db`)은 시연용이라 용량이 작아요.
  1. Cloudflare → R2 → 버킷 만들기 (예: `yeoun-files`, 공개 접근 끄기)
  2. R2 → API 토큰 만들기 (그 버킷만 읽기·쓰기)
  3. API 서비스 환경 변수:
     - `YEOUN_STORAGE=s3`
     - `YEOUN_S3_BUCKET=yeoun-files`
     - `YEOUN_S3_ENDPOINT_URL=https://<계정ID>.r2.cloudflarestorage.com`
     - `YEOUN_S3_ACCESS_KEY_ID=…`, `YEOUN_S3_SECRET_ACCESS_KEY=…`
     - `YEOUN_S3_REGION=auto`
     - 필요하면 `YEOUN_SPACE_QUOTA_MB`(0이면 제한 없음), `YEOUN_MAX_FILE_MB` 조정
  4. 주의: 저장소를 바꿔도 **기존 파일은 옮겨지지 않아요.** 테스트 데이터를 지우고 시작하거나 옮기는 스크립트를 따로 만들어야 해요.
- [ ] **메모리가 넉넉한 서버라면 kiwi 켜기** — 검색 정확도가 조금 더 좋아요(eval 100%).
  - Docker 빌드 인자 `WITH_KIWI=true`, 환경 변수 `YEOUN_TOKENIZER=kiwi` (메모리 약 350MB 더 씀)

## 5. 법률·윤리 검토

- [ ] `docs/privacy.md`(개인정보 처리방침 초안) 전문가 검토 — 국외 이전, 위탁, 보관 기간, 만 14세 미만, 고인 정보
- [ ] **이용약관** 새로 쓰기 (아직 없음)
- [ ] 떠난 분의 목소리를 다루는 것에 대한 윤리 검토 (유족 간 의견 차이, 함께 녹음된 사람의 권리)
- [ ] 위기 대응 문구(대화 화면의 도움 안내, `/help` 페이지)를 정신건강 전문가에게 검토받기
- [ ] 상담 번호가 최신인지 확인: 자살예방상담전화 **109**, 정신건강위기상담 **1577-0199**, 긴급 **119·112**
- [ ] 개인정보 처리방침의 운영자·연락처·시행일 자리표시자 채우기 (`web/src/app/privacy/page.tsx`도 함께)

## 6. 실제 기기 테스트

- [ ] **아이폰 사파리**: 미리 남기기 녹음(MediaRecorder가 mp4로 녹음), 클립 재생(Range 요청), 마이크 권한 안내
- [ ] **갤럭시**: 통화 녹음 파일명에서 날짜를 제대로 읽는지(`…_230512_143005.m4a`), amr·m4a 업로드
- [ ] **카카오톡 음성 메시지**: 내보내기 경로 안내 문구가 실제 앱 메뉴와 맞는지 → `web/src/components/FindGuide.tsx` 고치기
- [ ] 부모님 세대 사용성: 큰 글씨 설정, 녹음 화면 버튼 크기, 글자 읽기 쉬운지
- [ ] 잠든 서버: 15분 뒤 접속했을 때 "서버를 깨우는 중이에요"가 뜨고 2분 안에 이어지는지

## 7. 공모전 제출

- [ ] `docs/GENAI_USAGE.md` 검토 후 기획안에 옮기기 (개발에 쓴 AI / 서비스 안 AI 범위)
- [ ] `docs/CHANGELOG.md`를 날짜별 개선 증빙으로 정리 (대회 기간 동안 계속 추가)
- [ ] 시연 영상: 샘플 체험 → 업로드 → 목소리 확인 → 대화 → 미리 남기기 흐름 (가상 인물만 사용)
