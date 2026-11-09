# 결정 기록 (decisions.md)

개발 중에 묻지 않고 내린 결정과 그 이유를 적는다. 새 결정은 아래에 번호를 이어 붙인다.
형식: **결정** — 이유 / 대안 / 되돌리려면.

---

## D1. 공통 스키마는 JSON Schema 한 파일 + 자체 코드 생성기
- **결정**: `shared/schema.json`(JSON Schema `$defs`)을 원본으로 두고, `shared/codegen.py`(표준 라이브러리만 사용)가 `server/app/schemas/generated.py`(Pydantic v2)와 `web/src/lib/api-types.gen.ts`(TS)를 만든다. `make lint`가 `--check`로 생성 파일이 최신인지 확인한다.
- **이유**: datamodel-code-generator·json-schema-to-typescript는 출력 이름 규칙·enum 표현이 서로 달라 두 쪽 타입을 같게 맞추기 번거롭다. 우리가 쓰는 범위(object, enum, nullable, 길이 제약)는 작아서 200줄 생성기로 충분하고, 결과가 결정적이다.
- **대안**: OpenAPI를 서버에서 뽑아 TS로 변환. 서버가 원본이 되어 "공통 스키마는 shared/" 요구와 맞지 않는다.

## D2. Next.js 15.5 + TypeScript 5.9 + Tailwind 4
- **결정**: Next 16이 나와 있지만 15.5 최신 패치(15.5.29)를 쓴다. TypeScript 7(네이티브 컴파일러)도 나왔지만 5.9를 쓴다.
- **이유**: 15.5는 아직 보안 패치가 나오고, App Router·rewrites·instrumentation 동작이 안정적이다. TS 7은 Next 15의 타입 검사 연동이 검증되지 않았다.
- **되돌리려면**: `web/package.json`의 버전만 올리면 된다. Next 16에서는 `middleware`가 `proxy`로 바뀌지만 이 앱은 middleware를 쓰지 않는다.

## D3. 한국어 토크나이저: kiwi(정확) + lite(가벼움) 두 가지
- **결정**: `YEOUN_TOKENIZER=auto|kiwi|lite`. 로컬·유료 서버는 kiwipiepy, Render 무료(512MB)는 lite(규칙 기반 조사·어미 떼기 + 글자 2-gram).
- **이유**: kiwipiepy 기본 모델(cong)은 한 프로세스에서 약 350MB를 쓴다(직접 측정: 로드 241MB → 토큰화 후 351MB). 512MB 인스턴스에서 FastAPI·Pillow·ffmpeg와 함께 돌리면 메모리 초과 위험이 크다.
- **검증**: `make eval`이 두 토크나이저 모두의 top-3 정확도를 보고한다.

## D4. DB는 PostgreSQL만 지원 (테스트도 PostgreSQL)
- **결정**: SQLite 대체 경로를 두지 않는다. 테스트는 `yeoun_test` DB를 쓴다.
- **이유**: 작업 큐에 `FOR UPDATE SKIP LOCKED`, 메타데이터에 JSONB를 쓴다. 배포 환경과 같은 DB로 테스트해야 마이그레이션 문제를 미리 잡는다.

## D5. 쿠키 세션 + CSRF 헤더
- **결정**: 로그인은 HttpOnly·SameSite=Lax 쿠키(서버에는 토큰의 sha256만 저장). 쓰기 요청(POST/PATCH/PUT/DELETE)은 `x-yeoun-request: 1` 헤더가 없으면 거절한다.
- **이유**: 브라우저는 Next rewrites로 같은 출처의 `/api`만 부르므로 쿠키가 1st-party다. 다른 사이트의 form은 사용자 정의 헤더를 붙일 수 없어 CSRF를 막는다.

## D6. 파일 암호화: 공간별 데이터 키(봉투 암호화), 한 번에 암호화
- **결정**: 공간마다 32바이트 DEK를 만들고 `YEOUN_MASTER_KEY`에서 HKDF로 유도한 키로 감싸 저장한다. 파일은 AES-256-GCM 한 덩어리로 암호화하고 저장소 키를 AAD로 묶는다.
- **이유**: 파일 크기 상한(무료 25MB)이 있어 스트리밍 암호화가 꼭 필요하지 않다. 공간을 지우면 감싼 키도 사라져 저장소에 사본이 남아도 복호화할 수 없다(crypto-shredding).
- **주의**: 마스터 키를 바꾸거나 잃으면 기존 파일을 모두 읽을 수 없다. 키 교체 기능은 아직 없다(STATUS.md).
- **자막·태그는 DB에 평문**: 검색하려면 자막 텍스트가 필요하다. DB 접근 통제와 삭제로 보호한다.

## D7. API 오류는 한 가지 형식
- **결정**: 모든 오류는 `{"error": {"code", "message_ko"}}`. 검증 오류(422)도 `invalid_input`으로 바꾸고 입력값은 로그에 남기지 않는다.

## D8. 로그에 민감 정보 남기지 않기
- **결정**: uvicorn 접근 로그를 끄고, 실제 경로 대신 라우트 템플릿(`/api/spaces/{space_id}/clips`)만 남긴다. 토큰·키 모양 문자열은 로그 필터가 가린다. 파일명·자막은 로그 메시지에 넣지 않는다(ID만).
