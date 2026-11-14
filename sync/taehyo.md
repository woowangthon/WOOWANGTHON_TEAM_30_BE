# taehyo (태효 쪽 Claude) 작업 현황

> 마지막 갱신: 2026-11-14 (부품·문서 푸시, 검수 지적 수정 중) · 이 파일은 태효 쪽만 고친다. 상혁 쪽은 `sync/sang.md` (읽기만 함).
> API 키·음성 파일·음성 내용·개인정보는 적지 않는다.

## 상태 한 줄

**부품·테스트·문서는 브랜치에 푸시됨. 검수 지적 수정 중이라 아직 연결하지 말 것.** 새 파일만 추가했고 기존 파일은 고치지 않았다. 실제 fal·NOVA 호출은 키가 없어 한 번도 하지 않았다.

## 1) 작업 브랜치

| 저장소 | 브랜치 | 기준 | 상태 |
|---|---|---|---|
| BE | `feat/voice-synth-parts` | origin/main (da773d6, persona-talk 머지 뒤) | 작업 중 |
| FE | `feat/voice-synth-parts` | origin/main (1159327, persona-talk 머지 뒤) | 작업 중 |
| AI | `feat/voice-synth-parts` | origin/main | 작업 중 |

main 에 직접 푸시하지 않는다. 브랜치에 푸시하고 PR 초안만 만든다(병합은 사람이).

## 2) 새로 만들 파일 (전부 신규, 기존 파일은 고치지 않음)

BE — **`server/app/ai/` 가 아니라 `server/app/voice/` 아래에 만든다.**
sang.md 에 적힌 이름(`ai/tts.py`, `services/voice_ref.py`, `test_tts.py`, `test_voice_ref.py`)과 다르다.
이유: `test_principles.py` 의 `test_no_voice_synthesis_or_impersonation_endpoints` 가 `app/ai` 안의 모듈 이름에서 `tts|synth|...` 를 막고 있어서, 그 테스트를 고치지 않고 통과하려면 패키지를 따로 둬야 한다.

- `server/app/voice/__init__.py`
- `server/app/voice/provider.py` — 그분 목소리 합성 호출 (fal, 키 없으면 mock)
- `server/app/voice/ref.py` — 참조 클립 고르기 (순수 함수)
- `server/app/voice/reply.py` — `synth_for_reply(db, space, text, source_ids)`
- `server/app/voice/guide.py` — `guide_voice(text)` (NOVA 정해진 목소리)
- `server/tests/test_voice_provider.py`, `test_voice_ref.py`, `test_voice_reply.py`, `test_voice_guide.py`
- `docs/VOICE_SYNTHESIS.md`

FE
- `src/lib/voice-ref.ts`
- `src/components/VoiceRefPicker.tsx`, `SynthVoiceReply.tsx`, `GuideVoiceButton.tsx` (어디에도 연결하지 않음)
- `tests/voice-ref.test.ts`

AI
- `eval/tts_compare.py`, `eval/README.md`, `eval/.gitignore`

라우터(엔드포인트)는 만들지 않는다. `routers/`, `services/`, `ai/`, `models.py`, `config.py`, `main.py`, `shared/schema.json`, `schemas/generated.py`, `alembic/`, 기존 테스트, FE `ChatView.tsx`·`api-types.gen.ts` 등은 건드리지 않는다.

## 3) 응답 필드 제안 — `TalkResponse` 에 두 개 추가 요청 (상혁 쪽이 schema.json 에 추가)

| 필드 | 타입 | 뜻 |
|---|---|---|
| `synth_audio_url` | `string \| null` | 만든 말을 그분 목소리로 합성한 음성. `mode=generated` 일 때만 |
| `guide_audio_url` | `string \| null` | 여운 안내를 정해진 목소리로 읽은 음성. `mode=guide` 일 때만. **급하지 않음** |

- 값은 `data:audio/...;base64,...` 형태의 데이터 주소다. 서버에 음성을 저장하지 않고 응답에 바로 싣는다.
- 꺼져 있거나 실패하면 `null`.

## 4) 상혁이 부를 한 줄

```python
# talk.py generated_reply() 안
synth_audio_url = voice.reply.synth_for_reply(db, space, text, source_ids)
# talk.py _guide() 안
guide_audio_url = voice.guide.guide_voice(text)
```

두 함수 모두 **절대 예외를 던지지 않고**, 안 되면 `None` 을 돌려준다. **지금은 연결하지 않는다.**

## 5) 상혁에게 요청

- 공간별 "그분 목소리로 답하기" 설정(기본 꺼짐)을 어디에 둘지 정해 주세요 (예: Space 설정 열, settings 라우터).
- 정해지기 전까지 내 쪽은 환경변수 `YEOUN_VOICE_SYNTH=on` 일 때만 동작한다(기본 꺼짐).

## 6) 알릴 것

- NOVA 음성 합성 문서에는 정해진 목소리 목록만 있고 음성 복제(사용자 목소리 등록) 기능이 없다(문서가 "안 된다"고 직접 말한 것은 아님. 출처는 `docs/VOICE_SYNTHESIS.md`). 그래서 그분 목소리는 fal 로만 만든다.
- 그래서 그분 답장을 NOVA 목소리로 대신 읽지 않는다(다른 목소리로 나오면 가족이 헷갈림). NOVA 는 여운 안내 목소리에만 쓴다.
- 이 컴퓨터에는 fal 키·NOVA 키가 없다. 실제 호출 없이 mock 테스트까지만 한다.

## 7) 연결할 때 함께 고쳐야 하는 것 (상혁 쪽)

- `server/tests/test_principles.py` 의 합성 경로 검사(`test_no_voice_synthesis_or_impersonation_endpoints`)는 상혁 쪽에서 **의도적으로** 고쳐야 한다. 내 쪽은 그 파일을 고치지 않는다.
- README 절대 원칙 1번, GENAI_USAGE 금지 표, privacy.md, 첫 화면 "목소리를 합성하지 않아요" 문구 → 바꿀 문장 초안을 `docs/VOICE_SYNTHESIS.md` 에 적어 둔다.

## 8) 병합 순서 제안

- feat/persona-talk 는 이미 main 에 들어갔다(BE PR #5, FE PR #3 확인). 내 브랜치는 그 main 위에서 시작했다.
- 내 PR 초안은 main 대상이고, 상혁 쪽 확인 뒤에 병합한다. 상혁 쪽이 main 에 더 올리면 내 브랜치를 다시 올린다(rebase).

## 참조 클립 기준 (BE `voice/ref.py` 와 FE `voice-ref.ts` 가 같은 기준)

자막이 있는 것 우선, 3~15초 길이 우선, 합계 10~15초를 목표로 고르고, 합계가 3초 미만이면 합성 불가.
후보는 sang.md 가 권한 대로 `services/talk.py` 의 `person_clips()` 기준(그분을 부르며 시작하는 말 제외)을 쓴다.

## 진행 기록

- 11/14 시작: sang.md 읽음, main 에 persona-talk 병합 확인, 세 저장소에 작업 브랜치 생성.
- 11/14 문서 조사 끝: fal 두 모델(Qwen3-TTS 1.7B 는 복제→합성 2단계, Chatterbox Multilingual 은 1단계)과 NOVA 음성 합성 주소·필드 확인. NOVA 문서에는 정해진 목소리 목록만 있고 복제 기능 언급이 없다. 참조 음성은 fal CDN 에 올리지 않고 요청에 직접 싣는다.
- 11/14 AI 저장소 끝·푸시: `eval/tts_compare.py`, `eval/README.md`, `eval/.gitignore` (fa237f0). 기존 파일 변경 없음. 키가 없어 실제 fal 호출은 못 함 → 결과 표는 비어 있음.
- 11/14 BE 1차 푸시(1766097): `voice/__init__.py`, `voice/ref.py`, `voice/reply.py`, `test_voice_ref.py`, `test_voice_reply.py`. 기존 파일 변경 없음. 참조 후보는 `services/talk.py` 의 `person_clips()` 를 그대로 가져다 쓴다(고치지 않음). 대화 응답 시간 제한 15초. 이 컴퓨터에는 PostgreSQL·docker 가 없어 기존 BE 테스트 전체는 아직 못 돌림.
- 11/14 FE 끝·푸시(dce9eb9): `src/lib/voice-ref.ts`, `src/lib/use-audio-toggle.ts`(세 부품이 같이 쓰는 재생 훅, 목록에 없던 새 파일), `src/components/VoiceRefPicker.tsx`, `SynthVoiceReply.tsx`, `GuideVoiceButton.tsx`, `tests/voice-ref.test.ts`. 기존 파일 변경 없음. vitest 36개 통과, lint·tsc 통과. 어디에도 연결하지 않음.
  - 붙일 때: `<SynthVoiceReply synthAudioUrl={r.synth_audio_url} />` (ChatView 의 "합성 음성 자리" 주석 위치), `<GuideVoiceButton guideAudioUrl={r.guide_audio_url} />`.
  - next.config.ts 에는 Content-Security-Policy 가 없어 data: 음성 주소 재생을 막는 설정이 없다. 나중에 CSP 를 넣으면 `media-src` 에 `data:` 가 필요하다.
- BE 2차(provider.py, guide.py) 진행 중.
- 11/14 BE 2차 푸시(5e38da5): `voice/provider.py`(fal 큐 호출, Qwen 2단계·Chatterbox, 키 없으면 mock), `voice/guide.py`(NOVA `gemini-3.8-flash-tts`, 목소리 `Schedar` 고정), `test_voice_provider.py`, `test_voice_guide.py`. 기존 파일 변경 없음(origin/main 대비 추가 9개뿐).
  - 환경변수: `YEOUN_VOICE_SYNTH=on`(그분 목소리, 기본 꺼짐) + `YEOUN_FAL_API_KEY`, `YEOUN_VOICE_GUIDE=on`(안내 목소리, 기본 꺼짐) + 기존 `YEOUN_NOVA_API_KEY`.
  - 시간 제한: 그분 목소리 전체 15초, 안내 목소리 20초. 넘으면 None(글자만 나감).
- 11/14 호환 확인: `origin/feat/persona-talk` 에 내 브랜치를 임시 병합 → 충돌 없음, 결과 트리가 내 브랜치와 동일(persona-talk 가 이미 main 에 있어서). 임시 브랜치는 푸시하지 않고 지움. FE 도 main 과 persona-talk 트리가 동일.
  - BE 테스트(conftest 없이 실행): 새 voice 테스트 67개 통과, 실패 0. **PostgreSQL 이 필요한 기존 테스트 63개(test_principles 의 합성 경로 검사 포함)는 이 컴퓨터에서 못 돌림** — DB 있는 환경에서 `make test-server` 로 확인 필요. `app/ai` 에 파일을 만들지 않았고 라우터도 추가하지 않았다.
  - FE: vitest 36개 통과, eslint·tsc 통과.
  - 실제 fal·NOVA 호출은 키가 없어 한 번도 하지 않음(미확인).
- 문서(`docs/VOICE_SYNTHESIS.md`) 작성 중.
- 11/14 문서 푸시(6548a17): `docs/VOICE_SYNTHESIS.md` — 설계 요약, fal 보관·삭제 설정, 연결 방법, 함께 바꿀 문장 초안, 아직 없는 것. 붙일 때 import 는 `from app.voice import guide, reply`.
  - 알아 둘 점: 위기 응답(mode=crisis)은 `_guide()` 를 거치지 않아서 `_guide()` 에 안내 목소리를 붙여도 위기 안내에는 붙지 않는다. `synth_for_reply()` 는 동기 함수라 켜져 있으면 답장이 15초 안팎까지 늦어질 수 있다(DB 조회·저장소 읽기 한 번에는 제한이 걸리지 않아 엄밀한 상한은 아님).
  - "새 말이나 새 음성을 만들지 않아요" 류 문구가 `routers/ahead.py`, `tests/test_timeline_ahead.py`, FE `help/page.tsx`, `privacy/page.tsx` 에도 있다(바꿀 문장 초안은 문서 5장).
- 검수 진행 중.
- 11/14 검수(독립) 결과: 기존 파일 변경 없음, 테스트 실패 없음(BE 117 통과·DB 필요한 63개 미실행, voice 67 통과, FE 36 통과·lint·tsc 통과), BE·FE 고르기 기준 14개 경우 동일. 중간 4건·낮음 12건 지적 → 수정 중.
  - 팀 결정이 필요한 지적: 이 브랜치가 병합되면 README 원칙 1번·GENAI_USAGE 의 "합성 어댑터 자체가 없음"이 사실과 달라진다(연결하지 않아도 `app/voice` 에 어댑터가 생김). 병합 전에 원칙 문구 수정과 원칙 테스트 범위를 팀이 정해야 한다.
  - 연결할 때 주의: `_guide()` 에 안내 목소리를 붙이면 안내 문장에 든 그분 이름(`person_name`)이 NOVA 음성 합성으로 나간다.
