# taehyo (태효 쪽 Claude) 작업 현황

> 마지막 갱신: 2026-11-14 (검수 2회 반영, PR 초안 3개 생성) · 이 파일은 태효 쪽만 고친다. 상혁 쪽은 `sync/sang.md` (읽기만 함).
> API 키·음성 파일·음성 내용·개인정보는 적지 않는다.

## 11/15 제출 마무리

- 합성은 이번 제출에서 제외한다(상혁 결정과 같음). sang.md의 "합성 음성을 응답에 싣는 필드 이름을 정해 달라"는 요청에 대한 답: 이번 제출에서는 필드를 추가하지 않는다. `TalkResponse`는 그대로 둔다.
- 합성 PR 3개(BE #6, FE #4, AI #1)는 draft로 유지한다. 닫지도 머지하지도 않는다. 11/21 본선 종료 전까지 main에 머지하지 않는다(Render가 main에서 배포된다).
- 태효가 지금 하는 일: 시연 대본(마감 10:00), 발표 AI 설명 2~3장(11:00), 아카이빙 자료(14:00). 기준 커밋은 BE `ad3fffc`, FE `f0a3025`, AI `095a99d`.
- 아래 합성 연결 안내와 "합성을 넣는 경우"를 전제로 한 진행 중 표시는 11/21 이후 검토용이다.

## 상태 한 줄

**연결 가능(부품 기준). 단, 병합 전에 팀 결정 필요 — 원칙 1번 문구와 원칙 테스트 범위(`docs/VOICE_SYNTHESIS.md` 맨 위).** 새 파일만 추가했고 기존 파일은 고치지 않았다. 실제 fal·NOVA 호출은 키가 없어 한 번도 하지 않았다(미확인). PR 초안: BE #6, FE #4, AI #1 (모두 main 대상, 병합하지 않음).
synth_audio_url = reply.synth_for_reply(db, space, text, source_ids)
# talk.py _guide() 안
guide_audio_url = guide.guide_voice(text)
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
- 11/14 1차 검수 지적 수정 푸시: BE a86ecc8(키 없으면 mock 대신 오류, 시간 초과 때 취소→상태 확인→삭제, 내려받은 음성 서명 확인 등)·2740d87(문서), FE e334948(미리 들은 구간만 승인, 접근성), AI 7aa6f0d. 기존 파일 변경 없음.
- 11/14 재검수(독립): BE voice 테스트 78개 통과, conftest 없이 전체 128 통과·63 오류(전부 DB 픽스처 필요, 실패 0), FE vitest 41개·lint·tsc 통과, BE·FE 고르기 기준 25개 경우 동일. 새 지적(FE 승인 흐름 구멍 1건, BE 정리 지연·Qwen 긴 문장 잘림 가능성 등) 수정 중.
- 11/14 재검수 지적 수정 푸시: BE f630a77(정리를 별도 스레드로 — 답장을 늦추지 않음, Qwen 조각 100자, 응답 주소 호스트 확인, 참조 300초 상한)·b9b4fb1(문서), FE cf78b35(승인은 미리 들은 구간과 현재 선택이 같을 때만 — 새 prop `previewIds`), AI 3d5a3d6. 기존 파일 변경 없음(세 저장소 모두 origin/main 대비 추가뿐).
- 11/14 최종 확인(메인이 직접 실행): BE voice 테스트 91개 통과, conftest 없이 전체 141 통과·실패 0, **DB 가 필요한 기존 테스트 63개는 미실행**. FE vitest 49개·eslint·tsc 통과.
- 11/14 PR 초안: https://github.com/woowangthon/WOOWANGTHON_TEAM_30_BE/pull/6 , https://github.com/woowangthon/WOOWANGTHON_TEAM_30_FE/pull/4 , https://github.com/woowangthon/WOOWANGTHON_TEAM_30_AI/pull/1

## 연결 방법 요약 (자세한 것은 BE `docs/VOICE_SYNTHESIS.md` 4장)

1. `shared/schema.json` 의 `TalkResponse` 에 `synth_audio_url`, `guide_audio_url` (string | null) 추가 → 코드 생성.
2. `services/talk.py` `generated_reply()` 안에서 `reply.synth_for_reply(db, space, text, source_ids)`, `_guide()` 안에서 `guide.guide_voice(text)` (`from app.voice import guide, reply`). 둘 다 예외를 던지지 않고 안 되면 `None`.
3. 환경변수: `YEOUN_VOICE_SYNTH=on` + `YEOUN_FAL_API_KEY`, `YEOUN_VOICE_GUIDE=on` + `YEOUN_NOVA_API_KEY`. 기본은 둘 다 꺼짐.
4. FE: `ChatView.tsx` 의 "합성 음성 자리" 주석에 `<SynthVoiceReply synthAudioUrl={r.synth_audio_url} />`, 안내 말풍선 옆에 `<GuideVoiceButton guideAudioUrl={r.guide_audio_url} />`. 목소리 확인 화면에 `VoiceRefPicker` (부모가 `previewAudioUrl` 과 `previewIds` 를 한 쌍으로 넘겨야 승인 버튼이 보임).
5. 함께 바꿀 것: `test_principles.py` 합성 경로 검사, README 원칙 1번, GENAI_USAGE 금지 표, privacy.md, 첫 화면·도움말·개인정보 화면 문구, `routers/ahead.py` 동의 문구와 그 테스트.

연결할 때 주의
- `_guide()` 에 안내 목소리를 붙이면 안내 문장에 든 그분 이름이 NOVA 로 나간다. 위기 응답은 `_guide()` 를 거치지 않는다.
- `synth_for_reply()` 는 동기 함수라 켜져 있으면 답장이 15초 안팎까지 늦어질 수 있다.
- 기존 `ClipPlayer` 와 재생을 함께 관리하지 않아, 합성·안내 음성 재생 중에 원본 녹음을 누르면 소리가 겹칠 수 있다.
- 아직 없는 것: 가족이 고른 참조 구간·승인을 저장하는 API, 공간별 설정, 생전 동의 흐름, 실제 호출 확인.

## 태효 쪽이 맡는 제출물 업무 (11/14 밤~, 코드는 고치지 않음)

상혁이 대화 보강 코드를 작업하는 동안, 코드와 겹치지 않는 제출물 초안을 준비한다. 근거는 origin/main 과 배포본뿐이고, 합성은 "넣는 경우 / 빼는 경우" 두 갈래로 적는다. 초안은 저장소 밖(로컬 `submission-drafts/`)에 두고 커밋하지 않는다.

| 업무 | 결과물 | 상태 |
|---|---|---|
| 시연 시나리오 대본 + 예상 질문 10개 | `demo-script.md` | 초안 끝(문체검수 반영) |
| 발표 자료 초안(대회 양식 10장+부록 2장 기준) + 흐름도 | `presentation-outline.md`, 그림 3개 | 초안 끝(문체검수 반영) |
| 아카이빙 자료(woowangthon/hub, 브랜치 W30) JSON 초안·이미지 규격 | `archive/` | 초안 끝(빈칸 있음) |
| 문서와 실제 동작의 차이 목록(직접 고치지 않음) | `docs-fix-list.md` → 이 브랜치 `sync/docs-fix-list.md` 로 올림 | 올림(43개 항목) |

- 확인한 것: 대회 발표 양식은 Figma Slides 원본(본편 10장·9분 예시 + 부록 2장: 데이터·오픈소스 출처, 실행 링크와 접근 방법). 아카이빙 저장소는 `woowangthon/hub`.
- 상혁이 대화 동작·문구를 바꾸면 대본과 발표 문장이 달라질 수 있으니, main 에 올린 뒤 sang.md 에 한 줄 남겨 주세요.

### 초안 위치와 상혁이 봐야 할 것 (11/14 밤)

초안은 태효 컴퓨터의 `submission-drafts/`(저장소 밖)에 있다. 문서 수정 목록만 이 브랜치 `sync/docs-fix-list.md` 로 올렸다. 나머지는 태효가 노션 업무 페이지로 옮긴다.

상혁이 꼭 볼 것 (코드·문서를 고칠 사람이 상혁이라서)

1. **`sync/docs-fix-list.md`** — 문서와 main 실제 동작이 다른 곳 43개(눈에 띄는 것 30, 사소한 것 13). 그대로 붙여 넣을 문장 초안이 있다. 태효 쪽은 해당 파일을 고치지 않았다.
   - 가장 큰 것: README 원칙 1·2, privacy.md, GENAI_USAGE, AI README, FE 도움말·개인정보·설정 화면이 "AI는 찾고 고르기만, 새 문장을 만들지 않는다"고 쓰는데 main 의 기억 대화는 'AI가 만든 말'을 내보낸다. 합성을 넣든 빼든 고쳐야 한다.
   - 미리 남기기 동의 문구(`routers/ahead.py`)의 "새 말이나 새 음성을 만들지 않아요"도 같은 문제다(그 녹음이 말투 근거로 쓰임).
2. **`test_principles.py` 의 합성·흉내 경로 검사가 main 에서 이미 통과하지 못하는 것으로 보인다.** `app/ai/speaker_split.py` 의 모듈 이름에 `speak` 가 들어 있어 정규식(`tts|synth|clone|speak|...`)에 걸린다. 같은 판정 코드를 따로 돌려 확인했고, 실제 pytest 는 이 컴퓨터에 DB 가 없어 돌리지 못했다. DB 있는 환경에서 `pytest tests/test_principles.py` 한 번 확인해 주세요.
3. **배포본에서 직접 본 대화 동작(11/14 밤, 각 1~2회 관찰)**
   - "우주여행": 노션 기록은 "지어내지 않음"인데 'AI가 만든 말'(근거 2개)로 답했다.
   - "승진했어!": 한 번은 실제 녹음 답장(대학 합격을 축하하는 녹음), 두 번은 'AI가 만든 말'. 같은 문장에 답 종류가 갈린다.
   - 만든 말의 내용 자체는 서버가 검증하지 않는다(근거 ID·근거 0개·거절·금지어만 검사). 지어낸 인용 버리기(guard)는 예전 `/chat` 경로에만 걸려 있다.
   - 위기 판정은 talk 경로에서 규칙만 쓴다(LLM 보조는 예전 `/chat` 에만).
   - 샘플 공간 클립 40개는 모두 소리가 없다(`샘플 녹음 준비 중`). 시연 영상의 원본 재생 장면은 실제 녹음을 올린 공간에서 찍어야 한다.
4. FE e2e 2건(`sample.spec.ts`, `journey.spec.ts`)은 예전 대화 화면 문구와 `article` 을 기다려서 지금 화면과 안 맞아 보인다(실행은 못 함).
5. FE main 에 README 가 없다. `docs/fe-deploy`(PR #1)는 main 과 충돌 없이 병합된다. 병합 전 고칠 줄은 docs-fix-list 의 N-30, S-12.
6. 대화 동작이나 화면 문구를 바꾸면 시연 대본의 메시지 후보와 발표 문장이 달라진다. main 에 올린 뒤 sang.md 에 한 줄 남겨 주세요.

- 11/15 새벽: 노션 업무 3개(시연 대본 YEOUN-25, 발표 AI 설명 YEOUN-24, 아카이빙 YEOUN-16)의 담당을 태효로, 상태를 진행 중으로 두고 초안 요약을 페이지 댓글로 남겼다. 초안 전문은 아직 노션에 붙이지 않았다(태효 컴퓨터의 submission-drafts/ 에 있음). 발표 슬라이드는 대회 양식 Figma 파일이 보기 전용이라 커넥터로 만들지 못했고, 칸별 문장만 준비했다.
