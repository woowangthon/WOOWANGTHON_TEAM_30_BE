# 변경 기록 (CHANGELOG)

대회 기간 개선 내역의 증빙으로 쓴다. 날짜는 한국 시간 기준.

## 2026-11-09

### 1단계 — 스키마·뼈대·make 명령
- 공통 스키마 `shared/schema.json`과 코드 생성기(`make gen`): Pydantic 모델·TS 타입 자동 생성.
- 서버 뼈대: FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, 설정(YEOUN_ 접두사만 읽음), 공통 오류 형식, 로그 가리기.
- 계정: 이메일+비밀번호(argon2) 가입·로그인, 세션 쿠키, CSRF 헤더 검사, staging 초대 코드.
- 추억 공간 만들기·고치기·삭제(이름 확인), 공간별 데이터 키 봉투 암호화.
- 웹 뼈대: Next.js 15 + Tailwind 4, `/api` rewrites, 잠든 서버 자동 재시도 클라이언트와 안내 배너, web 시작 때 API 깨우기.
- `make dev / test / e2e / seed / eval / lint / gen` 명령.
