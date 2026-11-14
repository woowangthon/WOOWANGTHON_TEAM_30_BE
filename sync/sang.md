# sang (상혁 쪽 Claude) 작업 현황

> 마지막 갱신: 2026-11-14 (BE 기억책 제거 완료) · 이 파일은 상혁 쪽만 고친다. 태효 쪽은 `sync/taehyo.md`.
> API 키·음성 파일·개인정보는 적지 않는다.

## 1) 작업 브랜치

| 저장소 | 브랜치 | 상태 |
|---|---|---|
| BE (WOOWANGTHON_TEAM_30_BE) | `feat/persona-talk` | **기억책 제거·기억 대화 정리 완료(커밋 c67bfeb, 푸시됨)**, main 머지 전 |
| FE (WOOWANGTHON_TEAM_30_FE) | `feat/persona-talk` | 작업 중, main 머지 전 |

결정(11/14, 상혁): **우왕톤에서는 기억책을 빼고 '기억 대화'(메신저형, 그분 답장 하나 + 실제 목소리 듣기)만 한다.**
기억책은 창업해커톤 고도화로 미룬다. main에는 기억책이 아직 들어 있다(BE PR #4, FE PR #2로 머지됨) → 이 브랜치에서 지운다.

## 2) 지금 만지는 파일

BE
- `server/app/services/talk.py` (기억 대화 서비스) ✅
- `server/app/services/persona.py` (페르소나 카드) ✅ 새로 만듦
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

BE는 **지움 완료** (c67bfeb). `0003_drop_books.py` 추가, `0002_books.py`는 그대로. FE는 다음 작업 단위.

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
- 파일: `server/app/services/talk.py` **97행** `def generated_reply(...)`
- 시그니처: `generated_reply(db, space, text, source_ids, *, care, provider, user_id) -> TalkResponse`
  - `text`: 이미 검증된 AI 답장 글, `source_ids`: 근거 녹음 clip_id 1~3개 (그 사람 목소리로 확인된 클립만)
- 원본 녹음 답장은 `original_reply()`(같은 파일)로 따로 나간다 → 합성 대상 아님
- `mode == "generated"`인 답은 **반드시 이 함수 한 곳을 거쳐** 나간다. 여기서 태효 쪽 합성 함수를 한 줄로 부르면 된다. **지금은 연결하지 않는다.**
- 합성 결과를 화면에 넘기려면 `TalkResponse`에 필드가 필요할 수 있다 → 아래 "태효에게 요청" 참고.

## 태효에게 요청 / 안내

- 합성 음성을 응답에 싣는 필드 이름·형식을 정해 주면 `TalkResponse`(shared/schema.json)에 상혁 쪽이 추가한다. 예: `synth_audio_url: string | null`. 정해지면 `sync/taehyo.md`에 적어 주세요.
- FE에서 합성 음성 버튼은 `ChatView.tsx`의 generated 말풍선 안에 붙일 수 있게 자리를 비워 둔다(`SynthVoiceReply` 컴포넌트를 넣을 위치를 주석으로 표시 예정).
- 화면의 "AI가 만든 말" 표시와 근거 녹음 보기는 유지해야 한다(심사 기준·윤리 장치). 합성 음성도 같은 말풍선 안에 'AI 합성 음성'으로 표시해 주세요.
