"""규칙 기반 한국어 사전: 사투리 정규화, 개념 묶음(질문 확장·태깅·의도).

AI(LLM·임베딩)가 없어도 검색·태깅이 돌아가게 하는 '규칙 기반' 경로의 핵심이다.
개념 묶음은 특정 샘플이 아니라 가족 녹음에서 흔한 주제(식사, 건강, 시험, 날씨…)를 일반적으로 다룬다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas import TAG_VALUES

# ---------------------------------------------------------------- 사투리·구어 정규화
# 녹음 자막(특히 어르신 말투)과 사용자가 친 글의 표기 차이를 줄인다. 원문은 바꾸지 않고 검색용 사본에만 쓴다.
_DIALECT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"묵(?=[어고었을는으자기게지나])"), "먹"),
    (re.compile(r"할매"), "할머니"),
    (re.compile(r"할배"), "할아버지"),
    (re.compile(r"(?<![가-힣])니(?=[가는를도한의랑 ])"), "너"),
    (re.compile(r"(?<![가-힣])니(?=$)"), "너"),
    (re.compile(r"([다라])꼬(?![가-힣])"), r"\1고"),
    (re.compile(r"(?<=[가-힣])기다(?![가-힣])"), " 거다"),
    (re.compile(r"(?<=[가-힣])끼다(?![가-힣])"), " 거다"),
    (re.compile(r"그기"), "그게"),
    (re.compile(r"아이다"), "아니다"),
    (re.compile(r"아이가"), "아니냐"),
    (re.compile(r"카대"), "하더라"),
    (re.compile(r"단디"), "단단히"),
    (re.compile(r"억수로"), "엄청"),
    (re.compile(r"우째"), "어떻게"),
    (re.compile(r"따신"), "따뜻한"),
    (re.compile(r"중한"), "중요한"),
    (re.compile(r"([가-힣])노\?"), r"\1니?"),
    (re.compile(r"([가-힣])그라(?![가-힣])"), r"\1거라"),
    (re.compile(r"(?<=[가-힣])다메(?![가-힣])"), "다며"),
    (re.compile(r"(?<=[가-힣])제\?"), "지?"),
    (re.compile(r"밤샜"), "밤새웠"),
    (re.compile(r"밤샘"), "밤새"),
    (re.compile(r"(?<=[가-힣])라이(?=[.!?]|$)"), "라"),
]

_SPACES = re.compile(r"\s+")


def normalize_dialect(text: str) -> str:
    out = text
    for pat, repl in _DIALECT:
        out = pat.sub(repl, out)
    return _SPACES.sub(" ", out).strip()


# ---------------------------------------------------------------- 개념 묶음


@dataclass(frozen=True)
class Concept:
    name: str
    pattern: re.Pattern[str]
    expand: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    intent: str | None = None
    # 질문에만 쓰고 태깅에는 쓰지 않는 개념 (예: '어떻게 만들어?' 같은 질문 형태)
    query_only: bool = False
    extra: dict = field(default_factory=dict)


def _c(name, pattern, expand=(), tags=(), intent=None, query_only=False) -> Concept:
    return Concept(name, re.compile(pattern), tuple(expand), tuple(tags), intent, query_only)


CONCEPTS: list[Concept] = [
    # 음식·요리
    _c(
        "meal",
        r"밥|끼니|식사|먹|배고프|배고파|굶|반찬|도시락",
        ["밥", "먹", "끼니", "챙기"],
        ["음식"],
        "food",
    ),
    _c(
        "recipe",
        r"어떻게\s?(끓|만들|담|부치|해)|만드는\s?법|끓이는\s?법|레시피|비법|만들어\s?(줘|봐)|끓였|요리법",
        ["끓이", "넣", "볶", "만들", "먼저"],
        ["요리"],
        "food",
        query_only=True,
    ),
    _c(
        "dish",
        r"찌개|국(?![가-힣]*[민가어])|김치|된장|떡국|송편|식혜|미역국|전|나물|볶음|장아찌|고기",
        [],
        ["음식"],
        "food",
    ),
    _c(
        "signature_dish",
        r"(잘하던|잘하는|자신\s?있는|제일\s?잘\s?(만들|하)|대표)\s?(요리|음식)|요리.*(뭐|무엇)",
        ["자신", "제일"],
        ["요리", "음식"],
        "food",
        query_only=True,
    ),
    # 기념일
    _c("birthday", r"생일|생신|미역국", ["생일", "미역국", "축하"], ["생일"], "celebrate"),
    _c(
        "seollal",
        r"설날|(?<![가-힣])설(?=[에은이도날 ]|$)|새해|떡국|세배",
        ["설", "떡국"],
        ["명절"],
        "celebrate",
    ),
    _c("chuseok", r"추석|송편|한가위|명절|차례|제사|성묘", ["추석", "송편", "명절"], ["명절"], "celebrate"),
    # 건강
    _c(
        "cold",
        r"감기|기침|열이|콧물|몸살|목이\s?(아|쉬)|독감",
        ["감기", "생강차", "땀"],
        ["건강", "걱정"],
        "health",
    ),
    _c(
        "sick",
        r"아프|아파|아팠|아픈|병원|검사|진료|입원|수술|몸이\s?안\s?좋|컨디션",
        ["아프", "병원", "검사", "참"],
        ["건강", "병원"],
        "health",
    ),
    _c(
        "medicine",
        r"약을|약은|약이|약도|약\s?먹|약먹|약\s?챙|영양제|비염|알레르기",
        ["약", "챙기", "때"],
        ["건강"],
        "health",
    ),
    _c(
        "sleep",
        r"밤새|밤을\s?새|잠을\s?못|못\s?자|잠이\s?안|불면|잠\s?좀|잠을|늦게\s?자",
        ["잠", "자", "밤새", "일찍"],
        ["건강", "잔소리"],
        "health",
    ),
    _c("knee", r"무릎|허리|관절|쑤시", ["무릎", "쑤시"], ["건강"], "health"),
    # 공부·일
    _c(
        "exam",
        r"시험|수능|모의고사|중간고사|기말|성적|자격증|공부",
        ["시험", "수능", "풀"],
        ["공부"],
        "cheer",
    ),
    _c(
        "setback",
        r"망쳤|망했|떨어졌|불합격|실패|못\s?봤|못봤|미끄러|틀렸|잘\s?못\s?봤",
        ["못", "미끄러", "괜찮", "기죽"],
        ["위로"],
        "comfort",
    ),
    _c(
        "good_news",
        r"합격|붙었|입학|졸업|승진|해냈|뽑혔|상\s?받",
        ["붙", "장하", "대견", "자랑"],
        ["칭찬"],
        "praise",
    ),
    _c(
        "interview",
        r"면접|취업|채용|지원서|자기소개",
        ["면접", "말하", "보여"],
        ["일", "직장", "응원"],
        "cheer",
    ),
    _c(
        "first_day",
        r"첫\s?출근|첫\s?날|신입|새\s?직장|입사",
        ["첫", "출근", "처음", "서툴"],
        ["직장", "응원"],
        "cheer",
    ),
    _c(
        "work_hard",
        r"회사|직장|상사|그만두|퇴사|사표|일이\s?힘|일하기\s?싫|출근하기\s?싫",
        ["회사", "일", "쉬"],
        ["일", "직장", "위로"],
        "comfort",
    ),
    _c(
        "late_work",
        r"야근|늦게\s?(들어|퇴근|끝|와|가)|퇴근|밤늦게|막차|철야",
        ["퇴근", "밤늦게", "늦게"],
        ["직장", "걱정"],
        "health",
    ),
    _c("salary", r"월급|용돈|보너스|돈", ["월급", "용돈"], ["돈"], None),
    # 마음
    _c(
        "tired",
        r"힘들|힘드|힘겨|지치|지쳤|지친|버티|버겁|고생|번아웃|우울|무기력",
        ["힘들", "고생", "버티", "쉬", "힘내", "응원"],
        ["위로", "응원"],
        "comfort",
    ),
    _c(
        "sad",
        r"속상|눈물|울고|울었|울어|울컥|서럽|서러|슬퍼|슬프|외로",
        ["속상", "울", "참"],
        ["위로"],
        "comfort",
    ),
    _c(
        "self_doubt",
        r"잘\s?하고\s?있|잘할\s?수\s?있|잘\s?될까|잘될까|자신(이|감이)?\s?없|불안|앞날|미래가|걱정돼|걱정이야|못난",
        ["잘하", "잘되", "충분", "잘하고"],
        ["응원", "칭찬"],
        "cheer",
    ),
    _c(
        "fight",
        r"싸웠|다퉜|싸움|다툼|화해|사이가\s?안|삐졌|서운",
        ["싸웠", "미안", "먼저", "연락"],
        ["친구", "조언"],
        "advice",
    ),
    # 날씨·계절
    _c(
        "cold_weather",
        r"춥|추워|추운|추위|영하|한파|얼어|눈\s?와|눈이\s?와|눈이\s?내",
        ["춥", "영하", "내복", "목도리"],
        ["날씨", "계절"],
        None,
    ),
    _c(
        "rain",
        r"비가|비\s?와|비와|비\s?온|장마|우산|소나기|습하|눅눅",
        ["비", "장마", "우산"],
        ["날씨"],
        None,
    ),
    _c("spring", r"봄|벚꽃|꽃이\s?피|꽃\s?피|개나리|진달래|꽃구경", ["봄", "벚꽃", "꽃"], ["계절"], None),
    _c("summer", r"여름|더워|덥|폭염", ["여름", "더위"], ["계절", "날씨"], None),
    # 옛이야기
    _c(
        "how_met",
        r"(할아버지|할머니|엄마|아빠|아버지|어머니)(랑|와|하고|를|는)?.{0,6}(만났|만나|처음)|어떻게\s?만났|첫\s?만남|연애",
        ["처음", "봤", "만나"],
        ["결혼", "배우자", "젊은시절"],
        "story",
        query_only=True,
    ),
    _c(
        "wedding",
        r"결혼|신혼|웨딩|예비\s?(신랑|신부)|상견례|부부",
        ["결혼", "서로", "고맙"],
        ["결혼"],
        "advice",
    ),
    _c(
        "hometown",
        r"고향|어릴\s?(때|적)|어렸을|어린\s?시절|어린시절|바다|바닷가|시골",
        ["고향", "어릴", "바닷가", "바다"],
        ["고향", "어린시절"],
        "story",
    ),
    _c(
        "youth",
        r"젊었을|젊을\s?때|젊은\s?시절|무슨\s?일\s?(했|하)|직업|장사|일하던",
        ["젊", "장사", "시장"],
        ["젊은시절", "일"],
        "story",
    ),
    _c("market", r"시장|장날|장사|장\s?보", ["시장", "장날"], ["시장"], None),
    # 그리움·사랑
    _c(
        "miss",
        r"보고\s?싶|보고싶|그립|그리워|생각나|만나고\s?싶|언제\s?(와|오|내려)",
        ["보고", "싶", "언제", "얼굴"],
        ["그리움", "사랑"],
        "miss",
    ),
    _c("love", r"사랑", ["사랑"], ["사랑"], "miss"),
    _c("thanks", r"고마|감사", ["고맙"], ["감사"], None),
    _c("song", r"노래|노랫|흥얼|트로트|불러\s?줘|부르던", ["노래", "불렀"], ["노래"], None),
    _c("laugh", r"웃|재밌|재미있|웃긴|농담", ["웃"], ["웃음"], None),
    _c("greeting", r"^(안녕|잘\s?지내|잘지내)|뭐\s?하고\s?있|뭐해|잘\s?있어", ["안부"], ["안부"], "greeting"),
    _c("chores", r"빨래|청소|살림|설거지|보일러", ["빨래", "살림"], ["살림"], None),
    _c(
        "advice",
        r"조언|어떻게\s?해야|어떡해|어떻게\s?하지|어쩌지|알려\s?줘",
        [],
        ["조언"],
        "advice",
        query_only=True,
    ),
    _c("friend", r"친구|동료|동기", ["친구"], ["친구"], None),
    _c("grandchild", r"손주|손녀|손자|강아지", [], ["손주"], None),
    _c("farm", r"(?<![가-힣])밭|텃밭|고추|농사|상추", ["밭", "고추"], ["밭"], None),
    _c("home", r"우리\s?집|집에|집\s?앞|이사", ["집"], ["집"], None),
]

# 태그 이름이 질문에 그대로 나오면 그 태그로 본다 (예: "노래", "병원")
_TAG_SET = set(TAG_VALUES)

INTENT_PRIORITY = [
    "comfort",
    "cheer",
    "praise",
    "miss",
    "health",
    "food",
    "celebrate",
    "advice",
    "story",
    "greeting",
]


@dataclass
class Analysis:
    concepts: list[str]
    tags: list[str]
    expand: list[str]
    intent: str


def analyze(text: str, *, for_tagging: bool = False) -> Analysis:
    norm = normalize_dialect(text)
    found: list[Concept] = []
    for c in CONCEPTS:
        if for_tagging and c.query_only:
            continue
        if c.pattern.search(norm) or c.pattern.search(text):
            found.append(c)
    tags: list[str] = []
    expand: list[str] = []
    for c in found:
        for t in c.tags:
            if t not in tags:
                tags.append(t)
        for e in c.expand:
            if e not in expand:
                expand.append(e)
    if not for_tagging:
        for t in _TAG_SET:
            if len(t) >= 2 and t in norm and t not in tags:
                tags.append(t)
    intents = [c.intent for c in found if c.intent]
    intent = "general"
    for cand in INTENT_PRIORITY:
        if cand in intents:
            intent = cand
            break
    return Analysis(
        concepts=[c.name for c in found],
        tags=[t for t in tags if t in _TAG_SET],
        expand=expand,
        intent=intent,
    )


def rule_tags(text: str, limit: int = 5) -> list[str]:
    """클립 자막에서 정해진 태그 목록 안의 태그만 고른다."""
    return analyze(text, for_tagging=True).tags[:limit]
