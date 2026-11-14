"""자동 생성 파일입니다. 직접 고치지 말고 shared/schema.json을 고친 뒤 `make gen`을 실행하세요."""

# ruff: noqa: E501
from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

__all__ = [
    'Tag',
    'TAG_VALUES',
    'Intent',
    'INTENT_VALUES',
    'CareLevel',
    'CARE_LEVEL_VALUES',
    'AssetKind',
    'ASSET_KIND_VALUES',
    'AssetSource',
    'ASSET_SOURCE_VALUES',
    'OriginLabel',
    'ORIGIN_LABEL_VALUES',
    'AssetStatus',
    'ASSET_STATUS_VALUES',
    'StageName',
    'STAGE_NAME_VALUES',
    'StageState',
    'STAGE_STATE_VALUES',
    'DateSource',
    'DATE_SOURCE_VALUES',
    'SpeakerRole',
    'SPEAKER_ROLE_VALUES',
    'MemberRole',
    'MEMBER_ROLE_VALUES',
    'AudioStatus',
    'AUDIO_STATUS_VALUES',
    'ProviderFunction',
    'PROVIDER_FUNCTION_VALUES',
    'ProviderStatus',
    'PROVIDER_STATUS_VALUES',
    'LinkStatus',
    'LINK_STATUS_VALUES',
    'QuestionCategory',
    'QUESTION_CATEGORY_VALUES',
    'ErrorBody',
    'ErrorResponse',
    'Health',
    'AppLimits',
    'AppConfig',
    'UserPrefs',
    'UserPrefsUpdate',
    'User',
    'SignupRequest',
    'LoginRequest',
    'DeleteAccountRequest',
    'SpaceCounts',
    'Space',
    'SpaceCreate',
    'SpaceUpdate',
    'DeleteSpaceRequest',
    'AssetStage',
    'Asset',
    'AssetUpdate',
    'AssetList',
    'PhotoRef',
    'ClipCard',
    'Clip',
    'ClipUpdate',
    'Speaker',
    'SpeakerUpdate',
    'VoiceReviewAsset',
    'VoiceReview',
    'ClipList',
    'ChatRequest',
    'CareResource',
    'CareNotice',
    'GuideMessage',
    'ChatResponse',
    'TranscribeResponse',
    'TranscriptSegment',
    'LLMIntent',
    'LLMPick',
    'LLMSelection',
    'LLMClipTags',
    'LLMTagging',
    'TimelineItem',
    'TimelineDay',
    'Timeline',
    'FavoriteUpdate',
    'QuestionCard',
    'QuestionCategoryInfo',
    'QuestionDeck',
    'RecordingLinkCreate',
    'LinkQuestion',
    'RecordingLink',
    'RecordingLinkList',
    'RecorderSession',
    'ProviderInfo',
    'ProviderList',
    'Member',
    'MemberList',
    'MemberUpdate',
    'InviteCreate',
    'Invite',
    'InvitePreview',
    'Notice',
    'NoticeList',
    'Collection',
    'CollectionCreate',
    'CollectionUpdate',
    'CollectionList',
    'BookStatus',
    'BOOK_STATUS_VALUES',
    'BookParagraph',
    'BookChapter',
    'Book',
    'BookParagraphUpdate',
    'CallTurn',
    'CallRequest',
    'CallMode',
    'CALL_MODE_VALUES',
    'CallResponse',
    'LLMBookParagraph',
    'LLMBookChapter',
    'LLMBookDraft',
    'LLMCallReply',
    'StoryRequest',
    'LLMPersonaCard',
    'LLMTalkReply',
    'LLMStoryDraft',
]


# 정해진 태그 목록. 태깅(LLM·규칙)은 이 안에서만 고른다.
Tag = Literal['음식', '요리', '건강', '걱정', '공부', '일', '살림', '돈', '칭찬', '응원', '위로', '사랑', '그리움', '명절', '생일', '날씨', '계절', '여행', '어린시절', '젊은시절', '결혼', '조언', '잔소리', '웃음', '안부', '감사', '노래', '아들', '딸', '손주', '배우자', '부모님', '형제자매', '친구', '이웃', '집', '고향', '시장', '병원', '학교', '직장', '바다', '산', '밭']
TAG_VALUES: tuple[str, ...] = ('음식', '요리', '건강', '걱정', '공부', '일', '살림', '돈', '칭찬', '응원', '위로', '사랑', '그리움', '명절', '생일', '날씨', '계절', '여행', '어린시절', '젊은시절', '결혼', '조언', '잔소리', '웃음', '안부', '감사', '노래', '아들', '딸', '손주', '배우자', '부모님', '형제자매', '친구', '이웃', '집', '고향', '시장', '병원', '학교', '직장', '바다', '산', '밭',)


# 대화 의도. 검색 때 관련 태그에 가산점을 준다.
Intent = Literal['comfort', 'cheer', 'praise', 'advice', 'food', 'health', 'miss', 'greeting', 'story', 'celebrate', 'general']
INTENT_VALUES: tuple[str, ...] = ('comfort', 'cheer', 'praise', 'advice', 'food', 'health', 'miss', 'greeting', 'story', 'celebrate', 'general',)


# 마음 돌봄 위험 수준. high면 클립보다 도움 안내를 먼저 보여 준다.
CareLevel = Literal['none', 'watch', 'high']
CARE_LEVEL_VALUES: tuple[str, ...] = ('none', 'watch', 'high',)


AssetKind = Literal['audio', 'video', 'photo']
ASSET_KIND_VALUES: tuple[str, ...] = ('audio', 'video', 'photo',)


# upload: 직접 올림, ahead: 미리 남기기 녹음, sample: 샘플
AssetSource = Literal['upload', 'ahead', 'sample']
ASSET_SOURCE_VALUES: tuple[str, ...] = ('upload', 'ahead', 'sample',)


# 자료 출처 종류(사용자가 고르거나 파일명으로 추정)
OriginLabel = Literal['call', 'video', 'voice_message', 'ahead', 'other']
ORIGIN_LABEL_VALUES: tuple[str, ...] = ('call', 'video', 'voice_message', 'ahead', 'other',)


AssetStatus = Literal['uploaded', 'queued', 'processing', 'ready', 'failed']
ASSET_STATUS_VALUES: tuple[str, ...] = ('uploaded', 'queued', 'processing', 'ready', 'failed',)


StageName = Literal['normalize', 'stt', 'diarize', 'segment', 'tag', 'index']
STAGE_NAME_VALUES: tuple[str, ...] = ('normalize', 'stt', 'diarize', 'segment', 'tag', 'index',)


StageState = Literal['pending', 'running', 'done', 'skipped', 'failed']
STAGE_STATE_VALUES: tuple[str, ...] = ('pending', 'running', 'done', 'skipped', 'failed',)


# 날짜를 어디서 알아냈는지
DateSource = Literal['metadata', 'filename', 'exif', 'user', 'upload', 'unknown']
DATE_SOURCE_VALUES: tuple[str, ...] = ('metadata', 'filename', 'exif', 'user', 'upload', 'unknown',)


SpeakerRole = Literal['person', 'other', 'unknown']
SPEAKER_ROLE_VALUES: tuple[str, ...] = ('person', 'other', 'unknown',)


MemberRole = Literal['owner', 'editor', 'viewer']
MEMBER_ROLE_VALUES: tuple[str, ...] = ('owner', 'editor', 'viewer',)


# ready: 재생 가능, placeholder: 샘플 녹음 준비 중, missing: 파일 없음
AudioStatus = Literal['ready', 'placeholder', 'missing']
AUDIO_STATUS_VALUES: tuple[str, ...] = ('ready', 'placeholder', 'missing',)


ProviderFunction = Literal['stt', 'diarization', 'llm', 'embedding']
PROVIDER_FUNCTION_VALUES: tuple[str, ...] = ('stt', 'diarization', 'llm', 'embedding',)


ProviderStatus = Literal['active', 'not_configured', 'blocked_by_policy', 'needs_consent', 'model_missing']
PROVIDER_STATUS_VALUES: tuple[str, ...] = ('active', 'not_configured', 'blocked_by_policy', 'needs_consent', 'model_missing',)


LinkStatus = Literal['active', 'completed', 'expired', 'revoked']
LINK_STATUS_VALUES: tuple[str, ...] = ('active', 'completed', 'expired', 'revoked',)


QuestionCategory = Literal['childhood', 'youth', 'love_family', 'to_family', 'life_advice', 'food', 'holidays', 'everyday', 'health_heart', 'custom']
QUESTION_CATEGORY_VALUES: tuple[str, ...] = ('childhood', 'youth', 'love_family', 'to_family', 'life_advice', 'food', 'holidays', 'everyday', 'health_heart', 'custom',)


# 기억책 상태. draft는 가족 검수 전, approved는 가족이 승인한 책.
BookStatus = Literal['draft', 'approved']
BOOK_STATUS_VALUES: tuple[str, ...] = ('draft', 'approved',)


# 기억 통화 답의 종류. original: 원본 녹음, generated: AI 생성(근거 표시), guide: 여운 안내, crisis: 위기 전환
CallMode = Literal['original', 'generated', 'guide', 'crisis']
CALL_MODE_VALUES: tuple[str, ...] = ('original', 'generated', 'guide', 'crisis',)


class ErrorBody(BaseModel):
    code: str = Field(description='기계가 읽는 오류 코드 (예: not_found, quota_exceeded)')
    message_ko: str = Field(description='사용자에게 보여 줄 한국어 문구')


class ErrorResponse(BaseModel):
    error: ErrorBody


class Health(BaseModel):
    ok: bool
    version: str
    db: bool


class AppLimits(BaseModel):
    max_file_mb: int
    space_quota_mb: int = Field(description='0이면 제한 없음')
    user_upload_quota_mb: int = Field(description='0이면 제한 없음')
    chat_daily_limit: int = Field(description='0이면 제한 없음')
    allowed_extensions: list[str]


class AppConfig(BaseModel):
    env: Literal['development', 'staging', 'production', 'test']
    signup_requires_invite: bool
    sample_space_id: Optional[str]
    limits: AppLimits
    stt_available: bool = Field(description='음성으로 말 걸기(실제 음성 인식)가 가능한지')


class UserPrefs(BaseModel):
    large_text: bool
    rest_reminder: bool = Field(description='오래 사용하면 쉬어 가기 안내')
    rest_minutes: int = Field(ge=10, le=240)
    consent_training_providers: bool = Field(description='입력을 학습에 쓰는 무료 AI 등급 사용 동의 (staging에서만 의미 있음)')


class UserPrefsUpdate(BaseModel):
    large_text: Optional[bool] = Field(default=None)
    rest_reminder: Optional[bool] = Field(default=None)
    rest_minutes: Optional[int] = Field(default=None, ge=10, le=240)
    consent_training_providers: Optional[bool] = Field(default=None)


class User(BaseModel):
    id: str
    email: str
    display_name: str
    prefs: UserPrefs
    created_at: dt.datetime


class SignupRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=40)
    invite_code: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class DeleteAccountRequest(BaseModel):
    password: str = Field(max_length=200)


class SpaceCounts(BaseModel):
    assets: int
    clips: int
    person_clips: int = Field(description='대화에 쓰이는(그 사람 목소리로 확인된) 클립 수')
    photos: int
    pending_voice: int = Field(description='목소리 확인이 필요한 자료 수')
    processing: int


class Space(BaseModel):
    id: str
    name: str = Field(description='공간 이름 (예: 엄마)')
    person_name: str = Field(description='그 사람의 이름 또는 부르는 말')
    relationship: Optional[str] = Field(default=None)
    birthday: Optional[dt.date] = Field(default=None)
    memorial_day: Optional[dt.date] = Field(default=None)
    note: Optional[str] = Field(default=None)
    is_sample: bool
    role: MemberRole
    counts: SpaceCounts
    storage_bytes: int
    storage_limit_bytes: int = Field(description='0이면 제한 없음')
    created_at: dt.datetime


class SpaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    person_name: str = Field(min_length=1, max_length=40)
    relationship: Optional[str] = Field(default=None, max_length=40)
    birthday: Optional[dt.date] = Field(default=None)
    memorial_day: Optional[dt.date] = Field(default=None)
    note: Optional[str] = Field(default=None, max_length=500)


class SpaceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    person_name: Optional[str] = Field(default=None, min_length=1, max_length=40)
    relationship: Optional[str] = Field(default=None, max_length=40)
    birthday: Optional[dt.date] = Field(default=None)
    memorial_day: Optional[dt.date] = Field(default=None)
    note: Optional[str] = Field(default=None, max_length=500)


class DeleteSpaceRequest(BaseModel):
    confirm_name: str = Field(description='실수 방지를 위해 공간 이름을 그대로 입력')


class AssetStage(BaseModel):
    name: StageName
    state: StageState
    note: Optional[str] = Field(default=None, description="예: '음성 인식 키가 없어 기본 방식으로 처리했어요'")


class Asset(BaseModel):
    id: str
    kind: AssetKind
    source: AssetSource
    origin: OriginLabel
    filename: str
    size_bytes: int
    duration_sec: Optional[float] = Field(default=None)
    recorded_at: Optional[dt.date] = Field(default=None)
    date_source: DateSource
    status: AssetStatus
    stages: list[AssetStage]
    progress: float = Field(description='0~1')
    error: Optional[ErrorBody] = Field(default=None)
    clip_count: int
    thumb_url: Optional[str] = Field(default=None, description='사진일 때 서명된 미리보기 URL')
    created_at: dt.datetime


class AssetUpdate(BaseModel):
    recorded_at: Optional[dt.date] = Field(default=None)
    origin: Optional[OriginLabel] = Field(default=None)


class AssetList(BaseModel):
    assets: list[Asset]


class PhotoRef(BaseModel):
    asset_id: str
    url: str = Field(description='짧게 만료되는 서명 URL')
    date: Optional[dt.date] = Field(default=None)
    caption: Optional[str] = Field(default=None)


class ClipCard(BaseModel):
    """그 사람이 실제로 한 말(원본 녹음 클립). transcript는 언제나 DB에 저장된 원문 자막이며 AI가 만든 문장이 아니다."""

    clip_id: str
    transcript: str
    date: Optional[dt.date] = Field(default=None)
    date_label: Optional[str] = Field(default=None, description='예: 2019년 2월 4일 / 날짜 모름')
    source_label: str = Field(description='예: 통화 녹음 · 2019년 2월')
    audio_url: Optional[str] = Field(default=None)
    audio_status: AudioStatus
    start_sec: float
    end_sec: float
    photos: list[PhotoRef]
    question: Optional[str] = Field(default=None, description='미리 남기기 질문에 대한 답일 때 그 질문')
    tags: list[Tag]
    favorite: bool
    reason: Optional[str] = Field(default=None, description='여운 안내: 이 클립을 고른 이유(그 사람의 말이 아님)')


class Clip(BaseModel):
    id: str
    asset_id: str
    speaker_id: Optional[str] = Field(default=None)
    start_sec: float
    end_sec: float
    text: str
    text_edited: bool
    tags: list[Tag]
    included: bool = Field(description='대화에 쓰이는지(최종 판단)')
    include_override: Optional[bool] = Field(default=None, description='클립별 직접 포함/제외. null이면 화자 선택을 따름')
    audio_url: Optional[str] = Field(default=None)
    audio_status: AudioStatus
    confidence: Optional[float] = Field(default=None)


class ClipUpdate(BaseModel):
    text: Optional[str] = Field(default=None, max_length=1000)
    include_override: Optional[bool] = Field(default=None)
    clear_override: Optional[bool] = Field(default=None, description='true면 클립별 설정을 지우고 화자 선택을 따른다')
    tags: Optional[list[Tag]] = Field(default=None)


class Speaker(BaseModel):
    id: str
    asset_id: str
    label: str = Field(description='예: 목소리 1')
    role: SpeakerRole
    clip_count: int
    total_sec: Optional[float] = Field(default=None)
    samples: list[Clip] = Field(description='대표 구간')


class SpeakerUpdate(BaseModel):
    role: SpeakerRole


class VoiceReviewAsset(BaseModel):
    asset: Asset
    speakers: list[Speaker]
    diarized: bool = Field(description='false면 화자 분리 없이 파일 단위로 고른다')
    needs_review: bool


class VoiceReview(BaseModel):
    person_name: str
    assets: list[VoiceReviewAsset]
    pending_count: int


class ClipList(BaseModel):
    clips: list[Clip]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class CareResource(BaseModel):
    name: str
    phone: str
    hours: str
    description: Optional[str] = Field(default=None)


class CareNotice(BaseModel):
    level: CareLevel
    title: str
    message: str
    resources: list[CareResource]


class GuideMessage(BaseModel):
    """여운 안내: 서비스가 하는 말. 그 사람이 한 말처럼 보이게 쓰지 않는다."""

    text: str


class ChatResponse(BaseModel):
    care: Optional[CareNotice] = Field(default=None)
    guide: GuideMessage
    clips: list[ClipCard] = Field(max_length=3)
    matched: bool = Field(description="false면 '딱 맞는 녹음은 없어요'")
    nearby: list[ClipCard] = Field(description='맞는 녹음이 없을 때 보여 줄 가까운 추억')
    intent: Optional[Intent] = Field(default=None)
    keywords: list[str]
    picker: str = Field(description='클립을 고른 방식 (mock, anthropic 등)')
    remaining_today: Optional[int] = Field(default=None)


class TranscribeResponse(BaseModel):
    text: str


class TranscriptSegment(BaseModel):
    """STT 결과 형식"""

    start: float
    end: float
    text: str
    speaker: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None)


class LLMIntent(BaseModel):
    """LLM 의도 파악 출력. 서버에서 이 스키마로 검증한다."""

    intent: Intent
    keywords: list[Annotated[str, StringConstraints(max_length=20)]] = Field(max_length=8)
    tags: list[Tag] = Field(max_length=5)
    risk: CareLevel


class LLMPick(BaseModel):
    clip_id: str
    reason: str = Field(max_length=120)


class LLMSelection(BaseModel):
    """LLM 클립 고르기 출력. 후보에 없는 clip_id, 지어낸 인용은 서버가 버린다."""

    picks: list[LLMPick] = Field(max_length=3)
    no_good_match: bool
    guide: str = Field(max_length=200)


class LLMClipTags(BaseModel):
    clip_id: str
    tags: list[Tag] = Field(max_length=5)


class LLMTagging(BaseModel):
    clips: list[LLMClipTags]


class TimelineItem(BaseModel):
    kind: Literal['clip', 'photo']
    clip: Optional[ClipCard] = Field(default=None)
    photo: Optional[PhotoRef] = Field(default=None)


class TimelineDay(BaseModel):
    date: Optional[dt.date]
    label: str
    items: list[TimelineItem]


class Timeline(BaseModel):
    days: list[TimelineDay]
    on_this_day: list[TimelineItem] = Field(description='1년 전(또는 그 전) 오늘')
    tag_counts: dict[str, int]
    total: int


class FavoriteUpdate(BaseModel):
    favorite: bool


class QuestionCard(BaseModel):
    id: str
    category: QuestionCategory
    text: str
    tags: list[Tag] = Field(default_factory=list)


class QuestionCategoryInfo(BaseModel):
    id: QuestionCategory
    label: str


class QuestionDeck(BaseModel):
    categories: list[QuestionCategoryInfo]
    cards: list[QuestionCard]


class RecordingLinkCreate(BaseModel):
    question_ids: list[str] = Field(max_length=20)
    custom_questions: list[Annotated[str, StringConstraints(min_length=2, max_length=120)]] = Field(default_factory=list, max_length=5)
    sender_name: Optional[str] = Field(default=None, max_length=40, description='녹음하는 분께 보일 보낸 사람 이름')
    message: Optional[str] = Field(default=None, max_length=300, description='녹음하는 분께 보일 한마디')
    expires_days: int = Field(default=7, ge=1, le=30)


class LinkQuestion(BaseModel):
    id: str
    text: str
    answered: bool
    asset_id: Optional[str] = Field(default=None)


class RecordingLink(BaseModel):
    id: str
    url: Optional[str] = Field(default=None, description='만들 때 한 번만 내려 준다 (토큰은 서버에 해시로만 저장)')
    status: LinkStatus
    sender_name: Optional[str] = Field(default=None)
    questions: list[LinkQuestion]
    answered_count: int
    expires_at: dt.datetime
    created_at: dt.datetime


class RecordingLinkList(BaseModel):
    links: list[RecordingLink]


class RecorderSession(BaseModel):
    """로그인 없이 녹음하는 화면에 내려 주는 정보"""

    sender_name: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)
    questions: list[LinkQuestion]
    expires_at: dt.datetime
    consent_text: str
    max_seconds: int


class ProviderInfo(BaseModel):
    function: ProviderFunction
    provider: str
    display_name: str
    is_external: bool
    trains_on_input: bool = Field(description='입력 데이터를 학습에 쓰는 등급인지')
    data_sent: str = Field(description='이 서비스로 보내는 데이터 (예: 오디오, 자막 텍스트)')
    retention_note: str
    status: ProviderStatus
    note: Optional[str] = Field(default=None)


class ProviderList(BaseModel):
    providers: list[ProviderInfo]
    retention: list[str] = Field(description='여운이 자료를 보관하는 기간 안내')


class Member(BaseModel):
    user_id: str
    display_name: str
    email: str
    role: MemberRole


class MemberList(BaseModel):
    members: list[Member]
    invites: list[Invite]


class MemberUpdate(BaseModel):
    role: MemberRole


class InviteCreate(BaseModel):
    role: MemberRole


class Invite(BaseModel):
    id: str
    role: MemberRole
    url: Optional[str] = Field(default=None)
    expires_at: dt.datetime


class InvitePreview(BaseModel):
    space_name: str
    inviter_name: str
    role: MemberRole


class Notice(BaseModel):
    """앱 안 알림(기일·생일). 밤 늦게(22시~8시) 새로 띄우지 않는다."""

    id: str
    kind: Literal['birthday', 'memorial', 'on_this_day']
    space_id: str
    title: str
    message: str


class NoticeList(BaseModel):
    notices: list[Notice]


class Collection(BaseModel):
    id: str
    title: str
    clip_ids: list[str]
    clips: list[ClipCard] = Field(default_factory=list)
    created_at: dt.datetime


class CollectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=60)
    clip_ids: list[str] = Field(default_factory=list, max_length=200)


class CollectionUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=60)
    clip_ids: Optional[list[str]] = Field(default=None, max_length=200)


class CollectionList(BaseModel):
    collections: list[Collection]


class BookParagraph(BaseModel):
    """책 문단. AI가 쓴 정리 문장이고, clip_ids는 근거가 된 원본 녹음이다. 근거가 없으면 grounded=false로 표시한다."""

    id: str
    text: str
    clip_ids: list[str]
    grounded: bool
    edited: bool = Field(description='가족이 고친 문단')


class BookChapter(BaseModel):
    id: str
    title: str
    period: Optional[str] = Field(default=None, description='예: 1970년대 / 시기 모름')
    paragraphs: list[BookParagraph]
    prompt: Optional[str] = Field(default=None, description='가족이 적은 기억 (이 장을 만든 요청)')


class Book(BaseModel):
    """목소리가 들리는 기억책. clips에는 문단 근거 클립의 카드가 한 번씩 들어 있다."""

    exists: bool
    status: Optional[BookStatus] = Field(default=None)
    title: Optional[str] = Field(default=None)
    chapters: list[BookChapter]
    clips: list[ClipCard]
    generated_by: Optional[str] = Field(default=None)
    updated_at: Optional[dt.datetime] = Field(default=None)
    grounded_ratio: Optional[float] = Field(default=None, description='근거 클립이 붙은 문단 비율')
    can_edit: bool
    source_clip_count: Optional[int] = Field(default=None, description='책을 만들 때 쓸 수 있는 그 사람의 녹음 수')


class BookParagraphUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class CallTurn(BaseModel):
    role: Literal['user', 'reply']
    text: str = Field(max_length=1000)


class CallRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    history: list[CallTurn] = Field(default_factory=list, max_length=12)


class CallResponse(BaseModel):
    mode: CallMode
    text: str = Field(description='generated면 AI가 만든 말(그 사람 말투), 그 밖에는 여운 안내')
    clips: list[ClipCard] = Field(description='original: 들려줄 원본')
    sources: list[ClipCard] = Field(description='generated: 근거가 된 원본')
    care: Optional[CareNotice] = Field(default=None)
    provider: str
    remaining_today: Optional[int] = Field(default=None)


class LLMBookParagraph(BaseModel):
    text: str = Field(max_length=600)
    clip_ids: list[str] = Field(max_length=6)


class LLMBookChapter(BaseModel):
    title: str = Field(max_length=40)
    period: str = Field(max_length=30)
    paragraphs: list[LLMBookParagraph] = Field(max_length=8)


class LLMBookDraft(BaseModel):
    """LLM 이야기 정리 결과. clip_ids는 서버가 받은 목록 안에서만 인정한다."""

    title: str = Field(max_length=40)
    chapters: list[LLMBookChapter] = Field(max_length=8)


class LLMCallReply(BaseModel):
    """기억 통화의 생성 답. source_clip_ids는 이 장의 클립 안에서만 인정하고, 근거가 없으면 refuse=true."""

    refuse: bool
    text: str = Field(max_length=400)
    source_clip_ids: list[str] = Field(max_length=4)


class StoryRequest(BaseModel):
    prompt: str = Field(min_length=2, max_length=300, description='이야기로 만들 기억 (예: 할머니랑 김치찌개 끓이던 기억)')


class LLMPersonaCard(BaseModel):
    """녹음에서 뽑은 그 사람의 말하기 특징 (대화 답의 말투를 맞추는 데만 쓴다)"""

    calls_user: str = Field(max_length=30, description='듣는 가족을 부르는 말 (예: 우리 강아지)')
    self_ref: str = Field(max_length=20, description='자기를 부르는 말 (예: 할매)')
    speech_style: str = Field(max_length=200, description='어미·사투리·말버릇 요약')
    phrases: list[str] = Field(max_length=8, description='자주 쓰는 표현 (자막 그대로)')
    topics: list[str] = Field(max_length=8, description='자주 나오는 이야기 주제')


class LLMTalkReply(BaseModel):
    """대화 답장 하나. use_clip_id가 후보 안의 클립이면 그 원본 녹음을 그대로 답장으로 쓴다."""

    refuse: bool
    use_clip_id: str = Field(description='원본 녹음 하나가 그대로 답이 되면 그 clip_id, 아니면 빈 문자열')
    text: str = Field(max_length=300)
    source_clip_ids: list[str] = Field(max_length=4)


class LLMStoryDraft(BaseModel):
    """가족이 적은 기억 하나로 쓰는 이야기 한 장. 관련 녹음이 없으면 found=false."""

    found: bool
    title: str = Field(max_length=40)
    period: str = Field(max_length=30)
    paragraphs: list[LLMBookParagraph] = Field(max_length=6)


ErrorBody.model_rebuild()
ErrorResponse.model_rebuild()
Health.model_rebuild()
AppLimits.model_rebuild()
AppConfig.model_rebuild()
UserPrefs.model_rebuild()
UserPrefsUpdate.model_rebuild()
User.model_rebuild()
SignupRequest.model_rebuild()
LoginRequest.model_rebuild()
DeleteAccountRequest.model_rebuild()
SpaceCounts.model_rebuild()
Space.model_rebuild()
SpaceCreate.model_rebuild()
SpaceUpdate.model_rebuild()
DeleteSpaceRequest.model_rebuild()
AssetStage.model_rebuild()
Asset.model_rebuild()
AssetUpdate.model_rebuild()
AssetList.model_rebuild()
PhotoRef.model_rebuild()
ClipCard.model_rebuild()
Clip.model_rebuild()
ClipUpdate.model_rebuild()
Speaker.model_rebuild()
SpeakerUpdate.model_rebuild()
VoiceReviewAsset.model_rebuild()
VoiceReview.model_rebuild()
ClipList.model_rebuild()
ChatRequest.model_rebuild()
CareResource.model_rebuild()
CareNotice.model_rebuild()
GuideMessage.model_rebuild()
ChatResponse.model_rebuild()
TranscribeResponse.model_rebuild()
TranscriptSegment.model_rebuild()
LLMIntent.model_rebuild()
LLMPick.model_rebuild()
LLMSelection.model_rebuild()
LLMClipTags.model_rebuild()
LLMTagging.model_rebuild()
TimelineItem.model_rebuild()
TimelineDay.model_rebuild()
Timeline.model_rebuild()
FavoriteUpdate.model_rebuild()
QuestionCard.model_rebuild()
QuestionCategoryInfo.model_rebuild()
QuestionDeck.model_rebuild()
RecordingLinkCreate.model_rebuild()
LinkQuestion.model_rebuild()
RecordingLink.model_rebuild()
RecordingLinkList.model_rebuild()
RecorderSession.model_rebuild()
ProviderInfo.model_rebuild()
ProviderList.model_rebuild()
Member.model_rebuild()
MemberList.model_rebuild()
MemberUpdate.model_rebuild()
InviteCreate.model_rebuild()
Invite.model_rebuild()
InvitePreview.model_rebuild()
Notice.model_rebuild()
NoticeList.model_rebuild()
Collection.model_rebuild()
CollectionCreate.model_rebuild()
CollectionUpdate.model_rebuild()
CollectionList.model_rebuild()
BookParagraph.model_rebuild()
BookChapter.model_rebuild()
Book.model_rebuild()
BookParagraphUpdate.model_rebuild()
CallTurn.model_rebuild()
CallRequest.model_rebuild()
CallResponse.model_rebuild()
LLMBookParagraph.model_rebuild()
LLMBookChapter.model_rebuild()
LLMBookDraft.model_rebuild()
LLMCallReply.model_rebuild()
StoryRequest.model_rebuild()
LLMPersonaCard.model_rebuild()
LLMTalkReply.model_rebuild()
LLMStoryDraft.model_rebuild()
