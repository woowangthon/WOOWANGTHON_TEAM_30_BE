# sang (상혁 쪽 Claude) 작업 현황

> 마지막 갱신: 2026-11-15 01시 (기억 대화 보강 머지·배포) · 이 파일은 상혁 쪽만 고친다. 태효 쪽은 `sync/taehyo.md`.
> API 키·음성 파일·개인정보는 적지 않는다.

## 1) 작업 브랜치

| 저장소 | 브랜치 | 상태 |
|---|---|---|
| BE (WOOWANGTHON_TEAM_30_BE) | `main` (feat/persona-talk → PR #5 머지, da773d6) | **main에 머지·Render 배포 완료** |
| FE (WOOWANGTHON_TEAM_30_FE) | `main` (feat/persona-talk → PR #3 머지, 1159327) | **main에 머지·Render 배포 완료** |

결정(11/14, 상혁): **우왕톤에서는 기억책을 빼고 '기억 대화'(메신저형, 그분 답장 하나 + 실제 목소리 듣기)만 한다.**
기억책은 창업해커톤 고도화로 미룬다. main에는 기억책이 아직 들어 있다(BE PR #4, FE PR #2로 머지됨) → 이 브랜치에서 지운다.

## 2) 지금 만지는 파일

BE
- `server/app/services/talk.py` (기억 대화 서비스) ✅
- `server/app/services/persona.py` (페르소나 카드) ✅ 새로 만듦
- `server/app/ai/content_split.py` ✅ (옛 이름 `speaker_split.py`, PR #7에서 이름 바꿈) — 목소리가 하나로 나온 통화·영상을 내용으로 두 사람 나누기 (pipeline/process.py 화자 분리 단계에서 호출)
- `server/app/pipeline/process.py` (화자 분리 단계에 위 호출 추가)
- `server/tests/test_content_split.py` ✅ (옛 이름 `test_speaker_split.py`)
- `server/app/routers/chat.py` (`POST /api/spaces/{id}/talk` 추가)
- `server/app/ai/llm.py` (페르소나 카드·대화 답장 프롬프트, 기억책 프롬프트 제거)
- `shared/schema.json`, `server/app/schemas/generated.py` (코드 생성)
- `server/app/models.py` (Book 모델 제거)
- `server/app/main.py` (라우터 목록에서 book 제거)
- `server/app/errors.py` (기억책 오류 문구 제거)
- `server/tests/test_chat.py` (대화 테스트)

FE
- `src/components/ChatView.tsx` (메신저형 대화 화면)
- `src/components/SpaceNav.tsx` (메뉴에서 기억책 제거)
- `src/app/page.tsx`, `src/components/AskBox.tsx` (첫 화면 문구: "원본이 먼저, 만든 말은 표시")
- `src/lib/api-types.gen.ts` (BE에서 코드 생성)

## 3) 지울 예정 (기억책 관련)

BE **지움 완료** (c67bfeb). `0003_drop_books.py` 추가, `0002_books.py`는 그대로.
FE **지움 완료** (db86fd8).

⚠ BE 브랜치에는 마이그레이션 0003이 있어서, 이 브랜치를 배포한 DB에 예전 main을 다시 배포하면 서버 시작이 실패한다. 배포 확인 → main 머지 → Render 브랜치를 main으로, 이 순서로만 한다.

BE
- `server/app/routers/book.py`
- `server/app/services/book.py` (대화에 필요한 부분은 `talk.py`/`persona.py`로 옮긴 뒤 삭제)
- `server/tests/test_book.py`
- `server/app/models.py` 안의 `Book` 클래스
- schema 정의: `Book`, `BookStatus`, `BookChapter`, `BookParagraph`, `BookParagraphUpdate`, `StoryRequest`, `LLMBookDraft`, `LLMBookChapter`, `LLMBookParagraph`, `LLMStoryDraft`, `LLMCallReply`, `CallMode`·`CallTurn`·`CallRequest`·`CallResponse`(→ Talk*로 이름 변경)
- **`server/alembic/versions/0002_books.py`는 지우지 않는다.** 대신 `0003_drop_books.py`를 새로 만들어 books 표를 지운다.

FE
- `src/components/BookView.tsx`, `src/components/CallView.tsx`
- `src/app/spaces/[id]/book/` (page.tsx, [chapterId]/page.tsx)
- `src/app/sample/book/` (page.tsx, [chapterId]/page.tsx)

## 4) 새로 만들 파일 (성격·말투 분석, 기억 대화)

- `server/app/services/persona.py` — 녹음 전체에서 페르소나 카드(부르는 말·자기 호칭·어미·사투리·자주 쓰는 말·주제)를 뽑아 캐시 (녹음이 바뀌면 다시)
- `server/app/services/talk.py` — 기억 대화 (위기 → 금지 주제 → 원본 녹음 → AI가 만든 답)
- `server/alembic/versions/0003_drop_books.py`
- (테스트는 기존 `server/tests/test_chat.py`에 추가)

태효 쪽 파일(`ai/tts.py`, `services/voice_ref.py`, `test_tts.py`, `test_voice_ref.py`, `docs/VOICE_SYNTHESIS.md`, FE `voice-ref.ts`, `VoiceRefPicker.tsx`, `SynthVoiceReply.tsx`, `tests/voice-ref.test.ts`, AI 저장소 `eval/`)는 만들거나 고치지 않는다.

## 5) 기억 대화: AI가 만든 답을 돌려주는 곳과 응답 형식

**API**: `POST /api/spaces/{space_id}/talk` (읽기 권한, 샘플 공간은 로그인 없이·속도 제한)

요청 `TalkRequest`
```json
{ "message": "보고 싶어요", "history": [{ "role": "user" | "reply", "text": "..." }] }
```

응답 `TalkResponse` (shared/schema.json에서 생성)
```json
{
  "mode": "original" | "generated" | "guide" | "crisis",
  "text": "답장 글. original이면 원본 자막 그대로, generated면 AI가 만든 말",
  "clips":   [ClipCard],  // original: 들려줄 원본 녹음 1개
  "sources": [ClipCard],  // generated: 근거가 된 원본 녹음 1~3개
  "care": CareNotice | null,
  "provider": "nova" | "mock" | "search" | "rule",
  "remaining_today": 123 | null
}
```

**합성 붙일 자리 (한 함수로 모아 둠)** — 브랜치 `feat/persona-talk` 기준
- 파일: `server/app/services/talk.py` **107행** `def generated_reply(...)` (main 기준)
- 시그니처: `generated_reply(db, space, text, source_ids, *, care, provider, user_id) -> TalkResponse`
  - `text`: 이미 검증된 AI 답장 글, `source_ids`: 근거 녹음 clip_id 1~3개 (그 사람 목소리로 확인된 클립만)
- 원본 녹음 답장은 `original_reply()`(같은 파일)로 따로 나간다 → 합성 대상 아님
- `mode == "generated"`인 답은 **반드시 이 함수 한 곳을 거쳐** 나간다. 여기서 태효 쪽 합성 함수를 한 줄로 부르면 된다. **지금은 연결하지 않는다.**
- 합성 결과를 화면에 넘기려면 `TalkResponse`에 필드가 필요할 수 있다 → 아래 "태효에게 요청" 참고.

## 배포 확인 (11/14, Render가 지금 `feat/persona-talk` 브랜치를 배포 중)

- `/api/spaces/{샘플}/talk` 실제 NOVA: original(실제 녹음 답장) · generated(근거 2개) · guide · crisis 모두 정상
- `/api/spaces/{id}/book`은 404 (기억책 제거, 0003 마이그레이션 적용됨)
- 11/14 main 머지 후 Render 두 서비스 모두 main으로 되돌려 배포 완료. 합성 작업은 **main에서 새 브랜치**를 따면 된다(`generated_reply`는 main의 `server/app/services/talk.py`).

## 참고: '그 사람' 클립 고르는 규칙 (참조 클립 고를 때도 같은 기준 권장)

- `services/talk.py`의 `person_clips()` / `addressed_to_person()`:
  목소리 확인에서 그 사람으로 고른 클립 중 '엄마, …', '여보세요, 할머니?'처럼 **그분을 부르며 시작하는 말은 뺀다**
  (목소리 확인이 틀렸을 때 가족 목소리가 섞이는 것 방지). 합성용 참조 클립을 고를 때도 이 함수를 쓰면 같은 기준이 된다.

## 11/14 밤: 원칙 테스트 오탐 수정 (BE PR #7, 브랜치 `fix/principles-module-name`, 머지 안 함)

- `test_no_voice_synthesis_or_impersonation_endpoints`가 main에서 실패하고 있었다: `speak`가 `app/ai/speaker_split.py`(11/14)와 `/speakers/{id}` 주소(11/9)에 걸림.
- 고친 것: 모듈 이름 `speaker_split` → `content_split`, 검사 패턴 `speak` → `speak(?!er)`. 그 밖의 금지어는 그대로.
- 고친 파일: `server/app/ai/content_split.py`(이름 변경), `server/app/pipeline/process.py`(import 한 줄), `server/tests/test_content_split.py`(이름 변경), `server/tests/test_principles.py`(패턴 한 줄).
- 태효 PR #6과 겹치는 파일 없음. 합성 연결 때 `test_principles.py`를 고친다면 PR #7 머지 뒤 그 위에서 고쳐 주세요(같은 줄).

## 11/15 새벽: 합성 제외 결정과 문서 수정 (머지 안 함)

- **결정(상혁): 그분 목소리 합성은 이번 제출에 넣지 않는다.** fal이 유료라서. 태효 PR 초안(BE #6, FE #4, AI #1)은 머지하지 않고 로드맵으로 둔다. 노션 결정 기록에 남김.
- `sync/docs-fix-list.md`의 "빼는 경우" 문장으로 고쳤다. 고마워요.
  - BE PR #8 (`docs/submission-1114`, PR #7 위에 쌓음): README·STATUS·GENAI_USAGE·privacy·decisions(D27~D30)·CHANGELOG·DEPLOY·TODO-team, **미리 남기기 동의 문구**(N-01, 테스트도), 주석 2곳(S-09, S-10), 평가 도구 `server/app/eval_talk.py` + `fixtures/eval/talk_safety.json`
  - FE PR #5 (`docs/copy-1114`): N-02~N-08, S-07, S-09, e2e `ahead.spec.ts`
  - AI PR #2 (`docs/eval-1114`): README 기억 대화 기준, 검증 표, `results/2026-11-15-talk-eval.json`
- **기억 대화 검증 수치(11/15, 배포본 샘플·NOVA)** — 발표 AI 설명에 쓸 수 있음: 골든 30문항 모두 실제 녹음(기대 녹음 30/30·29/30), AI가 만든 답 14개 근거 14/14·사람 판정 문제 3, 녹음에 없는 질문 안내 2/4, 위기 규칙 15/20(놓침 4), 금지 17/20, 일상 오탐 0. 표는 BE `docs/GENAI_USAGE.md`·AI README.
- 태효가 본 "우주여행 → AI가 만든 말", "승진했어 → 답 종류가 갈림"도 이번 측정과 같은 현상(녹음에 없는 질문 4개 중 2개가 말투로 답함). 시연 대본에서는 결과가 정해진 메시지(원본으로 답하는 것)를 쓰는 게 안전.
  - 안 한 것: FE e2e `sample.spec.ts`·`journey.spec.ts`(옛 대화 화면 기준), S-08 코드(공간 삭제 때 말투 캐시 비우기), S-13, FE PR #1의 S-12
- **시연 대본·발표 문장에 영향**: 첫 화면 제목이 "그분이 남긴 말은 그 목소리 그대로, / 없는 말은 'AI가 만든 말'로 표시해요."로 바뀜(FE PR #5). 동의 문구도 바뀜. 대화 동작은 그대로.

## 11/15 00시: 머지·배포 완료

- 머지: BE #7·#8 → main `3930814`, FE #1·#5 → main `4202eef`, AI #2 → main `ff80d1a`. 합성 PR(BE #6, FE #4, AI #1)은 머지하지 않음.
- Render 두 서비스 Manual Deploy 완료(API Live `3930814`). 배포본 샘플 대화 original·generated·guide·crisis 정상, 첫 화면·개인정보·도움말 새 문구 확인.
- **시연 대본·발표에 쓸 지금 문구**: 첫 화면 제목 "그분이 남긴 말은 그 목소리 그대로, / 없는 말은 'AI가 만든 말'로 표시해요." 미리 남기기 동의 문구도 바뀜.

## 11/15 00시 반: 위기 규칙 수정 머지·배포

- BE PR #9 → main `d3ba4d6`, Render API 배포 완료. AI PR #3 → main `bb9dc6a`. FE는 그대로 `4202eef`.
- 고친 것: `server/app/care/crisis.py` 정규식 4줄("더는 못 살겠", "그만 살", "손목을 그었", "수면제를"), `tests/test_care.py` 사례 5개, `eval_talk.py`에 새 위기 문장 10개(crisis_new).
- 배포본: 위 4문장 모두 crisis(상담 번호), 일상 문장은 그대로.
- **발표 AI 설명에 쓸 수치 바뀜**: 위기 문장 20개 15 → 19(같은 문장으로 다시 잼). 규칙을 보지 않고 새로 쓴 위기 문장 10개는 0/10(주의 1) → 규칙만으로는 한계, 다음 단계는 LLM 위험도 판단.
- **지금 제출 기준 커밋**: BE `d3ba4d6`, FE `4202eef`, AI `bb9dc6a`.

## 11/15 01시: 기억 대화 보강 머지·배포 ("대화 엉뚱한 답 보강"은 상혁 쪽에서 끝냄)

- BE PR #10 → 배포 `e18d73f`, 문서 PR #11 → main `ad3fffc`(문서만). FE PR #6(타입만) → `f0a3025` 배포. AI PR #4 → `095a99d`.
- 바뀐 동작
  - 답장 LLM이 위험도도 판단(규칙보다 높일 때만) → 돌려 말한 위기 표현도 위기 전환
  - 경험·사실·조언을 묻는 말인데 관련 녹음이 근거에 없으면 지어내지 않고 안내("에펠탑", "노트북" 같은 질문)
  - "할머니 생일 축하해"를 그분 생일로 읽음
- **시연 대본에 영향**: "우주여행"·"에펠탑"류는 이제 안내로 끝남. "우리 강아지 이름 뭐였지?"도 안내로 끝남(지나치게 엄격한 사례). "할매 보고 싶어", "승진했어!", "비트코인", "유언", "엄마 따라가고 싶어"는 그대로.
- **발표 수치(보강 전 → 후)**: 녹음에 없는 질문 안내 2/4 → 4/4, 새 위기 문장 0/10 → 10/10, 위기 오탐 0(54개), 골든 30/30, 만든 답 중 지어낸 사실·조언 2 → 0. 표는 BE `docs/GENAI_USAGE.md`, AI README.
- **제출 기준 커밋(지금)**: BE `ad3fffc`, FE `f0a3025`, AI `095a99d`.

## 태효에게 요청 / 안내

- 합성 음성을 응답에 싣는 필드 이름·형식을 정해 주면 `TalkResponse`(shared/schema.json)에 상혁 쪽이 추가한다. 예: `synth_audio_url: string | null`. 정해지면 `sync/taehyo.md`에 적어 주세요.
- FE 합성 음성 자리: `src/components/ChatView.tsx`의 `Reply` 안 generated 말풍선, 주석 `합성 음성 자리: 태효 쪽 SynthVoiceReply 컴포넌트를 여기에 붙인다` 위치. 상혁 쪽은 `SynthVoiceReply.tsx`를 만들지 않는다.
- `ChatView.tsx`는 상혁 쪽이 계속 고치는 파일이라, 붙일 때는 이 주석 한 줄만 바꾸는 식으로 해 주세요(충돌 줄이기).
- 화면의 "AI가 만든 말" 표시와 근거 녹음 보기는 유지해야 한다(심사 기준·윤리 장치). 합성 음성도 같은 말풍선 안에 'AI 합성 음성'으로 표시해 주세요.
