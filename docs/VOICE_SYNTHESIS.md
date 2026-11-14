# 목소리 합성 부품 안내 (VOICE_SYNTHESIS)

상혁이 기억 대화(`services/talk.py`, FE `ChatView.tsx`)에 붙일 때 보는 안내서이자, 심사·발표용 설계 설명이에요.

> **상태: 부품만 만들었고 어디에도 연결하지 않았어요.** 기존 코드·문서·테스트는 하나도 고치지 않았어요. 그래서 지금 서비스는 기존 원칙대로 목소리를 합성하지 않아요.
> **실제 fal·NOVA 호출은 한 번도 하지 않았어요(키 필요).** 이 문서에서 "미확인"은 공식 문서에서 확인하지 못했거나, 키가 없어 실제로 확인하지 못했다는 뜻이에요. 지연 시간·품질 점수 같은 측정값은 아직 없어요.

---

## 1. 무엇을 만들었나

| | (가) 그분 목소리 합성 | (나) 여운 안내 목소리 |
|---|---|---|
| 하는 일 | 'AI가 만든 말'을 가족이 고른 참조 구간의 목소리(그분 목소리)로 들려줌 | 서비스 안내 문장을 정해진 목소리 하나로 읽어 줌 |
| 쓰는 곳 | fal (음성 복제) | 충북대 NOVA 게이트웨이의 음성 합성 |
| 모델 | Qwen3-TTS 1.7B(기본) 또는 Chatterbox Multilingual | `gemini-3.8-flash-tts`, 목소리 `Schedar` |
| 켜는 법 | 환경변수 `YEOUN_VOICE_SYNTH=on` + `YEOUN_FAL_API_KEY` | 환경변수 `YEOUN_VOICE_GUIDE=on` + `YEOUN_NOVA_API_KEY` |
| 기본값 | **꺼짐** | **꺼짐** |
| 서버에 음성 저장 | 안 함 | 안 함 |
| 밖으로 나가는 데이터 | 참조 음성, 참조 자막, 생성 문장 | 안내 문장 |
| 코드 | BE `server/app/voice/{ref,reply,provider}.py` | BE `server/app/voice/guide.py` |
| 화면 부품(FE) | `VoiceRefPicker.tsx`, `SynthVoiceReply.tsx`, `src/lib/voice-ref.ts` | `GuideVoiceButton.tsx` |

두 부품은 서로 바꿔 쓰지 않아요. 그분 답장이 합성에 실패했을 때 안내 목소리로 대신 읽지 않아요(`reply.py`는 실패하면 `None`만 돌려줘요). 그분 답장이 다른 목소리로 나오면 가족이 헷갈리기 때문이에요. 안내 목소리는 늘 같은 하나라서, 그분 목소리와 항상 달라요.

### NOVA 로 그분 목소리를 만들지 않는 이유

NOVA 음성 합성 문서(<https://docs.mindlogic.ai/docs/general/api-gateway/reference/audio-tts.md>)에는 **정해진 목소리 목록만 있고, 음성 복제나 사용자 목소리 등록에 대한 언급이 없어요.** 문서가 "복제 불가"라고 직접 말한 것은 아니고, 그 기능이 문서에 없다는 것이 확인한 사실이에요. 그래서 (가)에는 쓰지 않고, 정해진 목소리가 필요한 (나)에만 써요. 한국어 지원 여부는 이 문서에 언어 목록이 없어 미확인이에요.

---

## 2. 그분 목소리 합성 (가)

### 2-1. 설계 원칙

1. **기본은 꺼짐.** 환경변수가 `on`이 아니거나 fal 키가 없으면 아무 일도 하지 않고 `None`을 돌려줘요.
2. **가족이 미리 듣고 승인**한 뒤에만 켜는 흐름을 전제로 만들었어요(미리 듣기 화면 부품 `VoiceRefPicker`는 있고, 승인을 저장하는 서버 쪽은 아직 없어요. 6장).
3. **참조가 3초 미만이면 글자만.** 합성하지 않고 답장 글자만 나가요.
4. **서버에 음성을 저장하지 않아요.** 참조 음성도 합성 결과도 메모리에서만 다루고 임시 파일을 만들지 않아요. 결과는 `data:` 주소로 응답에 실려 나가요.
5. **어떤 경우에도 답장을 막지 않아요.** `synth_for_reply()`는 예외를 던지지 않고, 안 되면 `None`이에요. 시간 제한(15초)을 넘으면 합성을 버리고 글자만 나가요.
6. **'AI가 만든 말' 표시를 지우지 않아요.** FE `SynthVoiceReply`는 'AI 합성 음성' 표시를 함께 그리고, 원본 녹음 버튼(주황 계열)과 다른 모양으로 그려요.
7. 로그에는 문장·자막·파일명·키·주소를 남기지 않아요(결과 코드, 클립 수, 길이, 걸린 시간만).

### 2-2. 참조 클립 기준

BE `server/app/voice/ref.py`와 FE `src/lib/voice-ref.ts`가 같은 기준이에요.

> 참조 클립 기준: 자막이 있는 것을 우선하고, 길이 3~15초인 것을 우선하며, 합계 10~15초를 목표로 고른다. 합계가 3초 미만이면 합성 불가다.

고르는 순서(`pick_reference`):

1. 길이가 0 이하(숫자가 아니거나 무한대 포함)인 후보는 뺀다.
2. (우선 후보 → 자막 있음 → 길이 3~15초) 순으로 안정 정렬한다. 같은 순위는 입력 순서를 지킨다.
3. 앞에서부터 더하되, 더해서 합계가 15초를 넘으면 건너뛴다. 아직 아무것도 고르지 않았다면 15초를 넘어도 하나는 고른다.
4. 합계가 10초 이상이 되면 멈춘다.
5. 합계가 3초 이상이면 합성 가능(`usable`)이다.

| 상수 | 값 | 뜻 |
|---|---|---|
| `MIN_TOTAL_SEC` (FE `REF_MIN_SEC`) | 3초 | 합계가 이보다 짧으면 합성 불가 |
| `TARGET_MIN_SEC` (FE `REF_TARGET_MIN_SEC`) | 10초 | 합계가 이 이상이면 그만 고름 |
| `TARGET_MAX_SEC` (FE `REF_TARGET_MAX_SEC`) | 15초 | 더했을 때 넘으면 그 클립은 건너뜀 |
| `CLIP_MIN_SEC` / `CLIP_MAX_SEC` (FE `REF_CLIP_PREFER_MIN_SEC` / `..MAX_SEC`) | 3초 / 15초 | 클립 하나의 선호 길이 |
| `provider.MIN_REF_SEC` | 3초 | 공급자도 참조 음성이 3초 미만이거나 길이를 알 수 없으면 호출하지 않고 `ref_too_short` 로 거절 |

### 2-3. 지금 `reply.py` 가 참조를 고르는 방식

가족이 고른 참조 구간을 받는 경로는 **아직 없어요.** 지금은 `synth_for_reply(db, space, text, source_ids)` 안에서 자동으로 골라요.

1. `services/talk.py`의 `person_clips()`로 "그분으로 확인된(`included_expr()` 기준) 자막이 있는 클립"을 가져와요. 그분을 부르며 시작하는 말은 이미 빠져 있어요.
2. 그중 재생 파일이 준비된 것(`audio_key`가 있고 `audio_status == "ready"`)만 후보로 삼아요.
3. 답장의 근거 녹음(`source_ids`)을 우선 후보로 `pick_reference()`를 불러요.
4. 고른 클립 파일을 기존 경로(`storage.blobstore.load`, 복호화)로 읽고, 파이프라인이 이미 잘라 둔 mp3(24kHz 모노 64kbps)를 MP3 프레임 단위로 이어 붙여 하나의 mp3로 만들어요. 다시 자르지 않아요.
5. 클립 자막은 공백으로 이어 참조 자막으로 써요(Qwen만 받아요).

그래서 "가족이 고른 구간 저장 → reply 에 넘기기"는 상혁이 붙일 때 만들어야 하는 부분이에요(6장).

### 2-4. 모델 두 가지

| 논리 이름 | fal endpoint | 방식 | 참조 자막 |
|---|---|---|---|
| `qwen3-tts` (기본, `reply.DEFAULT_MODEL`) | 1단계 `fal-ai/qwen-3-tts/clone-voice/1.7b` → 2단계 `fal-ai/qwen-3-tts/text-to-speech/1.7b` | 1단계에서 참조 음성으로 화자 임베딩 파일을 만들고, 2단계에서 그 파일로 문장을 합성. 언어 `Korean` | 보냄(선택) |
| `chatterbox` | `fal-ai/chatterbox/text-to-speech/multilingual` | 1단계. 참조 음성 주소를 `voice`로, `custom_audio_language`는 `korean` | 받는 필드가 없어 보내지 않음 |

- 긴 문장은 문장 단위로 묶어 300자 이하 조각으로 나눠 요청하고 결과를 이어 붙여요(`MAX_CHUNK_CHARS`). Chatterbox의 `text`가 최대 300자예요. Qwen의 글자 수 제한은 미확인이라 같은 상한을 보수적으로 써요.
- 호출은 큐 방식이에요: 제출 → 응답이 준 `status_url` 폴링 → `response_url` 결과 → `audio.url` 내려받기 → 삭제 API. 상태·결과 주소는 직접 조립하지 않고 응답이 준 것을 그대로 써요.
- 큐로 부르는 이유는 삭제 API에 필요한 `request_id`를 큐 제출 응답에서 얻기 때문이에요. 동기 주소 응답에서 `request_id`를 얻는 방법은 미확인이에요.
- 하위 경로가 있는 endpoint_id를 큐 제출 주소에 그대로 쓰는 것은 문서 예시 기준이고, 실제 호출로는 **미확인**이에요.
- 두 모델의 참조 음성 형식·길이 제한(Qwen 복제는 최대 300초라고 문서에 있고, Chatterbox는 미확인)과 Qwen 참조 자막 길이 제한은 미확인이에요. Qwen·Chatterbox의 품질 비교는 아직 하지 않았어요(AI 저장소 `eval/tts_compare.py`가 비교 도구이고, 결과 표는 비어 있어요).
- 키가 없을 때 `provider.synthesize()`를 직접 부르면 0.5초 무음 WAV를 돌려주는 mock으로 동작해요(개발·테스트용). `reply.py`는 키가 없으면 공급자를 아예 부르지 않아요.

### 2-5. fal 에 무엇이 얼마 동안 남나

| 데이터 | fal 로 나가나 | fal 쪽에 남는 것 | 줄이려고 한 설정 | 실제 적용 |
|---|---|---|---|---|
| 참조 음성 | 나감 | 요청 기록(JSON 입출력)에 남을 수 있음. 기본 보관은 90일 | 아래 4가지 | **미확인** |
| 참조 자막(Qwen만) | 나감 | 위와 같음 | 위와 같음 | **미확인** |
| 생성 문장 | 나감 | 위와 같음 | 위와 같음 | **미확인** |
| 합성 결과 음성, Qwen 화자 임베딩 파일 | fal 이 만들어 CDN 에 둠 | 계정 설정이 없으면 만료 없음·공개 읽기(기본) | 보관 기간 헤더 + 삭제 API | **미확인** |

코드에서 한 일(`provider.py`):

1. **`X-Fal-Store-IO: 0`** — 모든 fal API 요청에 넣어요. 요청 기록의 JSON 입출력 저장을 끄는 헤더예요(기본은 저장, 90일). **CDN 파일에는 적용되지 않아요.** 적용되는 엔드포인트 범위는 미확인이에요.
2. **`X-Fal-Object-Lifecycle-Preference: {"expiration_duration_seconds": 3600}`** — 생성 파일(CDN)의 보관 기간을 3600초(1시간)로 해요. 값은 문서 예시를 그대로 쓴 것이고, **가능한 최소값은 미확인**이에요(더 짧게 할 수 있는지 모름).
3. **참조 음성을 CDN 에 올리지 않고 요청에 직접 실어요.** `data:<mime>;base64,...` 주소를 입력 파일 자리에 넣어요. 두 모델 API 문서의 Files 절에 "Base64 data URI 를 파일 입력으로 줄 수 있다"고 적혀 있어서 그렇게 했고, 크기 제한은 미확인이에요. 입력은 CDN 에 올라가지 않으니 입력 파일에 대한 삭제는 필요 없어요(삭제 API 도 입력 CDN 파일은 지우지 않아요).
4. **끝난 뒤 삭제 API 를 불러요.** `DELETE https://api.fal.ai/v1/models/requests/{request_id}/payloads`를 요청마다 불러요(실패·시간 초과 뒤에도 시도). 끝나지 않은 요청은 먼저 취소(`PUT cancel_url`)해요. 삭제가 실패해도 예외로 올리지 않고 상태 코드만 로그에 남겨요.
5. **Qwen 2단계에서 생기는 화자 임베딩 파일.** 1단계 결과인 `speaker_embedding`(safetensors)은 fal CDN 에 생기고, 2단계가 그 주소를 받아 써요. 이 파일은 1단계 요청의 출력이라서 위 2번(보관 기간)과 4번(삭제) 대상이에요. 실제로 지워지는지는 **미확인**이에요. Chatterbox는 이 파일이 생기지 않아요.

그 밖에 문서에서 확인하지 못해 미확인으로 남긴 것:

- 보관 기간의 최소값, 계정 기본 설정과 헤더 값이 충돌할 때의 우선순위
- `X-Fal-Store-IO: 0` 이 두 모델 엔드포인트에 실제로 적용되는지
- fal 이 입력 데이터를 모델 개선·학습에 쓰는지 여부(조사에서 다루지 않았어요)
- `X-Fal-Request-Timeout` 헤더(문서에서 확인하지 못해 쓰지 않아요)

### 2-6. 시간 제한 상수와 환경변수

| 이름 | 값 | 어디에 | 뜻 |
|---|---|---|---|
| `VOICE_REPLY_TIMEOUT_SEC` | 15.0초 | `reply.py` | 합성 전체(참조 클립 읽기 + 합성 호출)의 상한. 넘으면 합성을 버리고 `None`(글자만). 넘긴 뒤에도 공급자 스레드는 공급자 자체 시간 제한까지 뒤에서 끝나기를 기다리고 결과는 버려요 |
| `DEFAULT_TIMEOUT_SEC` | 60.0초 | `provider.py` | `synthesize()` 전체 상한 기본값. `reply.py`는 남은 시간을 넘겨요 |
| `HTTP_TIMEOUT_SEC` | 15.0초 | `provider.py` | HTTP 요청 하나의 상한(남은 시간이 더 짧으면 그만큼) |
| `CLEANUP_TIMEOUT_SEC` | 5.0초 | `provider.py` | 취소·삭제 요청 하나의 상한. 전체 상한이 지난 뒤에도 정리는 시도해요 |
| `POLL_INTERVAL_SEC` | 0.5초 | `provider.py` | 상태 폴링 간격 |
| `X-Fal-Request-Start-Timeout` | 남은 시간(초, 올림, 최소 1) | `provider.py` | 처리 시작 전 대기 제한. 만료 시 504 |
| `OBJECT_LIFECYCLE_SEC` | 3600초 | `provider.py` | fal CDN 생성 파일 보관 기간 요청값 |
| `MAX_CHUNK_CHARS` / `MAX_TEXT_CHARS` | 300자 / 300자 | `provider.py` / `reply.py` | 한 번에 보내는 문장 상한 / 답장 글자 상한(`talk.py`가 300자로 자르는 것과 맞춤) |
| `GUIDE_TIMEOUT_SEC` | 20.0초 | `guide.py` | 안내 목소리 요청 하나의 시간 제한 |
| `MAX_INPUT_CHARS` | 4000자 | `guide.py` | 안내 문장 상한. 넘으면 자르지 않고 `None` |

| 환경변수 | 쓰임 |
|---|---|
| `YEOUN_VOICE_SYNTH` | `on` 일 때만 그분 목소리 합성(`reply.py`가 `os.environ`에서 직접 읽어요) |
| `YEOUN_FAL_API_KEY` | fal 키 |
| `YEOUN_VOICE_GUIDE` | `on` 일 때만 안내 목소리(`guide.py`가 `os.environ`에서 직접 읽어요) |
| `YEOUN_NOVA_API_KEY` | NOVA 키(기존 `config.py`의 `nova_api_key`, `api_key("nova")`) |

`config.py`를 고치지 않으려고 `YEOUN_VOICE_SYNTH`, `YEOUN_VOICE_GUIDE`, `YEOUN_FAL_API_KEY`는 부품이 직접 읽어요. `config.py`로 옮길지는 연결할 때 정하면 돼요.

---

## 3. 여운 안내 목소리 (나)

- 주소 `POST https://factchat-cloud.mindlogic.ai/v1/gateway/audio/speech/`, 인증 `Authorization: Bearer <키>`, 모델 `gemini-3.8-flash-tts`(문서의 최신·권장 모델), 목소리 `Schedar`(문서가 30종 중 "차분함"이라고 적은 것은 이것 하나).
- 요청 필드는 `model`, `input`, `voice`만 보내요. 필수 여부는 문서에 명시가 없어서(미확인) 셋을 모두 보내요. `speakers`·`instructions`·`response_format`은 쓰지 않아요.
- 응답은 머리말 없는 원시 PCM(24,000Hz 모노 16비트 리틀 엔디안)이라 표준 `wave` 모듈로 WAV 로 감싸요(ffmpeg 불필요). 응답이 이미 wav/mpeg 이면 그대로 실어요.
- 밖으로 나가는 데이터는 **안내 문장**이에요. 그분의 음성·자막은 나가지 않아요.
- 빈 문장, 4,000자 초과, 키 없음, 403(조직에서 모델 꺼짐), 429(게이트웨이 공통 60초당 120건), 503(점검), 시간 초과, 이상한 응답은 모두 `None`이에요. 예외를 던지지 않아요.
- NOVA 가 서버에 문장을 얼마나 보관하는지는 이 문서 페이지에 없어 미확인이에요(`privacy.md` 6장의 NOVA 행은 `[확인 필요]`로 남아 있어요).

---

## 4. 연결 방법 (상혁용)

모든 부품은 새 파일이고 아직 어디에도 연결하지 않았어요. 연결은 아래 한 줄씩이에요.

### 4-1. BE `services/talk.py`

`generated_reply()`(AI가 만든 답이 나가는 유일한 자리)에서:

```python
from app.voice import guide as voice_guide, reply as voice_reply   # 파일 위쪽 import 에 추가

# generated_reply() 안
synth_audio_url = voice_reply.synth_for_reply(db, space, text, source_ids)
return TalkResponse(mode="generated", text=text, ..., synth_audio_url=synth_audio_url)
```

`_guide()`에서:

```python
def _guide(text, care, provider):
    guide_audio_url = voice_guide.guide_voice(text)
    return TalkResponse(mode="guide", text=text, ..., guide_audio_url=guide_audio_url)
```

주의할 점(코드에서 확인한 것):

- `synth_for_reply()`는 동기 함수라 합성이 끝나거나 시간 제한(15초)이 지날 때까지 답장이 늦어져요. 이 대기를 어떻게 다룰지는 연결할 때 정해야 해요.
- `talk()`의 위기 응답(`mode="crisis"`)은 `_guide()`를 거치지 않고 `TalkResponse`를 직접 만들어요(`talk.py` 148행 부근). 그래서 `_guide()`에 안내 목소리를 붙여도 위기 안내에는 붙지 않아요. 붙일지는 상혁이 정해 주세요.
- 합성은 `mode="generated"`일 때만 해요. 원본(`original`) 답장은 실제 녹음을 그대로 들려주는 것이라 합성하지 않아요.

### 4-2. 응답 스키마

`shared/schema.json`의 `TalkResponse`에 두 필드를 더하고(필수 아님), `schemas/generated.py`와 FE `src/lib/api-types.gen.ts`를 코드 생성기로 다시 만들어요(절차는 `docs/decisions.md` D1).

| 필드 | 타입 | 값 |
|---|---|---|
| `synth_audio_url` | string \| null | `"data:audio/...;base64,..."` 데이터 주소. 꺼져 있거나 실패하면 null |
| `guide_audio_url` | string \| null | 위와 같음 |

mime 은 공급자 결과를 그대로 따라서(`audio/wav`, `audio/mpeg`) 고정이 아니에요. 응답 크기(데이터 주소가 JSON 에 실려요)는 측정하지 않았어요.

### 4-3. FE `ChatView.tsx`

"합성 음성 자리" 주석이 있는 곳(`mode="generated"` 말풍선, `Reply` 컴포넌트)에:

```tsx
<SynthVoiceReply synthAudioUrl={r.synth_audio_url} />   {/* 'AI 합성 음성' 표시가 함께 그려져요 */}
```

`GuideBubble`(여운 안내 말풍선)에 안내 문장 옆으로:

```tsx
<GuideVoiceButton guideAudioUrl={r.guide_audio_url} />
```

값이 null 이면 둘 다 아무것도 그리지 않아요. 두 컴포넌트는 `useAudioToggle`을 함께 써서 한 번에 하나만 재생해요.

### 4-4. 목소리 확인 화면 (`src/app/spaces/[id]/voices/page.tsx`)

`VoiceRefPicker`는 props 로만 동작하고 API 를 부르지 않아요.

```tsx
<VoiceRefPicker
  clips={personClips}                 // 그분으로 확인된 클립 (Clip 을 그대로 넘겨도 돼요)
  selectedIds={selectedIds}
  onSelectedChange={setSelectedIds}
  onPreview={(ids) => { /* 미리 듣기 API 호출 → previewAudioUrl 채우기 */ }}
  onApprove={(ids) => { /* 승인 API 호출 */ }}
  onReject={() => setSelectedIds([])}
  previewStatus={previewStatus}       // "idle" | "loading" | "ready" | "error"
  previewAudioUrl={previewAudioUrl}   // data: 주소
  previewError={previewError}
/>
```

### 4-5. 설정 토글

공간별 "그분 목소리로 답하기" 토글(기본 꺼짐)이 필요해요. 지금은 서버 전체 환경변수 `YEOUN_VOICE_SYNTH`뿐이고, 공간별 값을 어디에 둘지(`models.py`·마이그레이션 등)는 상혁에게 요청한 상태예요. 이 부품은 DB를 고치지 않아요.

### 4-6. 화면 보안 설정(`next.config.ts`)

FE `next.config.ts`는 `Referrer-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Permissions-Policy` 네 가지만 넣어요. **Content-Security-Policy 는 없어요.** 그래서 `data:` 음성 주소를 막는 설정은 지금 없어요. 나중에 CSP 를 넣으면 `media-src` 에 `data:` 를 넣어야 이 음성이 재생돼요.

---

## 5. 연결할 때 함께 바꿔야 하는 것

아래 문서·테스트는 지금 "합성하지 않음"이라고 못 박고 있어서, 연결하면 거짓이 돼요. 이번에는 고치지 않았어요. 방향은 **"기본은 합성하지 않음. 생전 동의와 가족 승인이 있을 때만 켤 수 있음"** 이에요.

| 어디 | 지금 문장 (짧게) | 바꿀 문장 초안 |
|---|---|---|
| BE `README.md` 절대 원칙 1번 (10행) | "말은 원본만 — TTS, 목소리 복제, 그 사람인 척하는 LLM 응답을 만들지 않는다. 답은 언제나 실제 녹음 클립…" | "**말은 원본이 먼저** — 기본은 목소리를 합성하지 않는다. 녹음에 없는 말은 'AI가 만든 말'로 표시하고, 그분 목소리 합성은 생전 동의와 가족의 미리 듣기·승인이 있을 때만 켤 수 있다. 합성 음성에는 언제나 'AI 합성 음성' 표시를 붙이고 서버에 저장하지 않는다." |
| BE `docs/GENAI_USAGE.md` 금지 표 (52행) | "음성 합성(TTS)·목소리 복제 / 해당 기능·경로·어댑터 자체가 없음. 테스트가 경로 이름을 검사" | "음성 합성(TTS)·목소리 복제 / **기본 꺼짐.** 생전 동의와 가족 승인이 있을 때만 켜지고, 합성 음성은 'AI 합성 음성'으로 표시하며 서버에 저장하지 않음. 정해진 안내 목소리(NOVA)는 그분 목소리와 항상 다름" (같은 문서 B 장 한 줄 요약의 "AI가 새로 지어낸 문장이나 음성은 나가지 않아요"와 '데이터 정책', 기능별 표에도 fal·NOVA 음성 합성 행 추가) |
| BE `docs/privacy.md` 1장 (16행) | "그 사람의 목소리·말투로 새 문장이나 새 음성을 만들지 않아요. 음성 합성(TTS), 목소리 복제, 그 사람인 척하는 AI 응답 기능이 없어요." | "기본은 그분의 목소리로 새 음성을 만들지 않아요. 생전 동의가 있고 공간 가족이 미리 듣고 승인한 경우에만 켤 수 있고, 만든 음성은 'AI 합성 음성'으로 표시하며 서버에 저장하지 않아요." |
| BE `docs/privacy.md` 6장 표, 3장 | 외부 처리 위탁 표에 fal 없음. 3장 "쓰지 않아요: …그분의 목소리나 말투를 흉내 내는 콘텐츠 만들기" | fal 행 추가(보내는 데이터: 참조 음성·참조 자막·생성 문장, 보관: 2-5 표 참고하되 미확인 항목은 `[확인 필요]`). NOVA 행에 안내 문장 추가. 3장 문장은 "승인 없이는 …"으로 조정 |
| BE `server/app/routers/ahead.py` 94행 `consent_text()`와 `docs/privacy.md` 8장 | "여운은 이 목소리로 새 말이나 새 음성을 만들지 않아요." (미리 남기기 동의 문구) | 합성을 켜려면 녹음하는 분의 **생전 동의**가 이 문구에서 나와야 해요. 예: "여운은 이 목소리로 새 음성을 만들지 않아요. 다만 {보낸 분}님이 따로 허락하고 가족이 승인한 경우에만, 사라진 말을 AI가 이 목소리로 들려줄 수 있어요." 동의를 어떻게 받을지(별도 체크 등)는 상혁·팀 결정이에요 |
| BE `server/tests/test_timeline_ahead.py` 53행 | `"새 말이나 새 음성을 만들지 않아요" in session["consent_text"]` | `consent_text()`를 바꾸면 같이 바꿔야 해요 |
| BE `server/tests/test_principles.py` `test_no_voice_synthesis_or_impersonation_endpoints` | 앱 경로 이름에 `tts|synth|clone|speak|persona|imperson|generate`가 없고, `app/ai` 모듈 이름에도 없는지 검사 | 지금 부품은 `app/voice/`에 있고 새 경로도 없어서 이 검사에 걸리지 않을 거예요(**DB 가 없어 돌려 보지 못했어요**). 미리 듣기·승인 경로를 만들 때 이름에 위 단어를 피하거나, 테스트를 "합성 경로는 설정이 켜져 있고 승인된 공간에서만 열린다"는 검사로 바꾸세요 |
| FE `src/app/page.tsx` 4행 (첫 화면 "원본이 먼저") | "…그분의 목소리를 합성하지 않아요." | "…기본은 그분의 목소리를 합성하지 않아요. 생전 동의와 가족 승인이 있을 때만 켤 수 있고, 켜면 'AI 합성 음성'으로 표시해요." |
| FE `src/app/help/page.tsx` 33행 | "여운은 그분의 목소리로 새 말을 만들지 않아요. 들려 드리는 건 언제나 실제로 하셨던 말이에요." | "기본은 그분의 목소리로 새 말을 만들지 않아요. 합성은 생전 동의와 가족 승인이 있을 때만 켜지고, 합성한 음성에는 'AI 합성 음성' 표시가 붙어요." |
| FE `src/app/privacy/page.tsx` 22행 | "그분의 목소리나 말투로 새 문장·새 음성을 만들지 않고, 광고나 다른 목적에 쓰지 않아요." | `privacy.md` 1장 새 문장과 같은 내용으로 |

참고: 첫 화면의 "목소리를 합성하지 않아요" 문구는 `page.tsx`뿐 아니라 `help`·`privacy` 페이지에도 같은 뜻으로 있어요(위 표). 기억 대화의 'AI가 만든 말' 표시(`ChatView.tsx`)와 그분 말투로 새 문장을 짧게 답하는 기존 동작은 그대로예요.

---

## 6. 아직 없는 것

| 없는 것 | 지금 상태 |
|---|---|
| 가족이 고른 참조 구간을 저장하고 `reply`에 넘기는 경로 | 없음. `reply.py`가 그분으로 확인된 클립에서 자동으로 골라요(2-3) |
| 미리 듣기 API (고른 구간으로 짧은 문장을 합성해 들려주기) | 없음. FE `VoiceRefPicker`는 `onPreview` 콜백만 있어요 |
| 승인 API와 승인 상태 저장(공간별·참조 구간별) | 없음 |
| 공간별 "그분 목소리로 답하기" 토글 | 없음. 서버 전체 환경변수 `YEOUN_VOICE_SYNTH`뿐이에요 |
| 생전 동의 흐름 | 없음. 지금 미리 남기기 동의 문구는 "새 음성을 만들지 않아요"예요 |
| `TalkResponse`의 `synth_audio_url`·`guide_audio_url` | `schema.json`·생성 파일·FE 타입에 없음 |
| `talk.py`·`ChatView.tsx`·목소리 확인 화면 연결 | 안 함 |
| 개인정보 처리방침·원칙 문구 수정 | 안 함(5장) |
| 실제 fal·NOVA 호출 확인, 지연 시간·품질 측정, 합성 음성 크기 측정 | 안 함(키 없음) |
| Qwen·Chatterbox 품질 비교 | 도구(`AI/eval/tts_compare.py`)만 있고 결과 표는 비어 있음 |

---

## 7. 테스트 현황 (사실만)

| 무엇 | 결과 |
|---|---|
| BE 새 voice 테스트 67개 (`test_voice_ref.py`, `test_voice_reply.py`, `test_voice_provider.py`, `test_voice_guide.py`) | `conftest` 없이 통과 (`pytest --noconftest`). 이 테스트들은 DB 와 실제 fal·NOVA 를 쓰지 않고 가짜 응답으로 돌려요 |
| BE 기존 테스트 63개 (`test_principles`의 합성 경로 검사 포함) | PostgreSQL 이 필요한데 작업 컴퓨터에 DB 가 없어 **돌리지 못했어요** |
| FE vitest 36개, eslint, tsc | 통과 |
| 실제 fal·NOVA 호출 | **하지 않음** (`YEOUN_FAL_API_KEY`, `YEOUN_NOVA_API_KEY` 없음) |

키가 생기면 먼저 할 일: (1) `eval/tts_compare.py`로 두 모델을 팀원 본인 녹음으로 비교, (2) 큐 제출 주소·`data:` 주소 입력·헤더 3종이 실제로 먹는지 확인, (3) fal 에서 요청 기록·CDN 파일이 실제로 남지 않는지 확인.

---

## 8. 발표 부록: 외부 기술 출처

| 기술 | 쓰임 | 출처 |
|---|---|---|
| fal 인증·큐 | 호출 방식 | <https://fal.ai/docs/model-apis/authentication>, <https://fal.ai/docs/model-apis/model-endpoints/queue> |
| fal Qwen3-TTS 1.7B 음성 복제 / 합성 (2단계) | 그분 목소리 합성(기본) | <https://fal.ai/models/fal-ai/qwen-3-tts/clone-voice/1.7b/api>, <https://fal.ai/models/fal-ai/qwen-3-tts/text-to-speech/1.7b/llms.txt> |
| fal Chatterbox Multilingual | 그분 목소리 합성(대안) | <https://fal.ai/models/fal-ai/chatterbox/text-to-speech/multilingual/api> |
| fal 개인정보 설정 | `X-Fal-Store-IO`, 보관 기간, 삭제 API | <https://fal.ai/docs/documentation/model-apis/common-parameters>, <https://fal.ai/docs/documentation/serverless/data-retention>, <https://fal.ai/docs/documentation/model-apis/media-expiration>, <https://fal.ai/docs/platform-apis/v1/models/requests/payloads> |
| 충북대 NOVA 게이트웨이(운영 마인드로직) 음성 합성 | 여운 안내 목소리 | <https://docs.mindlogic.ai/docs/general/api-gateway/reference/audio-tts.md> |

이 출처는 2026-11-14에 공식 문서에서 확인한 내용이에요. 문서가 바뀌었을 수 있어서, 발표 전에 다시 확인하세요.
