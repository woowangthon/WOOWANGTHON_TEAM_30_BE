"""마음 돌봄: 자살·자해 위험 신호 검사.

규칙을 먼저 보고, LLM 분류(선택)가 있으면 더 높은 쪽을 따른다(LLM이 규칙을 낮출 수는 없다).
놓치는 것보다 한 번 더 안내하는 쪽이 낫기 때문에 규칙은 넓게 잡는다.
"""

from __future__ import annotations

import re

from app.schemas import CareNotice, CareResource

_HIGH = [
    r"죽고\s?싶",
    r"죽어\s?버리고\s?싶",
    r"죽어버리",
    r"죽을\s?래",
    r"자살",
    r"자해",
    r"목숨을?\s?끊",
    r"생을?\s?마감",
    r"살기\s?싫",
    r"살고\s?싶지\s?않",
    r"더\s?(이상\s?)?못\s?살겠",
    r"살\s?이유가?\s?없",
    r"사는\s?게\s?의미\s?없",
    r"(따라|곁으로|옆으로|그곳으로|하늘나라로)\s?(가고\s?싶|갈래|가야겠|가면\s?좋|갈까)",
    r"뛰어\s?내리",
    r"투신",
    r"손목을?\s?(긋|그어)",
    r"(약|수면제)을?\s?(잔뜩|한꺼번에|모아|모으|다\s?먹)",
    r"유서",
    r"사라지고\s?싶",
    r"없어지고\s?싶",
    r"세상에\s?없었으면",
]
_WATCH = [
    r"견딜\s?수\s?(가\s?)?없",
    r"버틸\s?수\s?(가\s?)?없",
    r"아무\s?의미\s?없",
    r"(다|모든\s?걸)\s?포기하고\s?싶",
    r"끝내고\s?싶",
    r"잠들고\s?깨지\s?않",
    r"내가\s?없어지면",
    r"살아서\s?뭐",
    r"아무도\s?없",
    r"혼자\s?남",
    r"숨\s?(이|을)?\s?(못|안)\s?쉬",
    r"너무\s?괴로",
    r"만나러\s?(가고\s?싶|갈래)",
]

_HIGH_RE = re.compile("|".join(_HIGH))
_WATCH_RE = re.compile("|".join(_WATCH))
_RANK = {"none": 0, "watch": 1, "high": 2}

RESOURCES = [
    CareResource(
        name="자살예방상담전화",
        phone="109",
        hours="24시간, 무료",
        description="누구나, 언제든 이야기할 수 있어요.",
    ),
    CareResource(
        name="정신건강위기상담",
        phone="1577-0199",
        hours="24시간",
        description="가까운 정신건강복지센터로 연결돼요.",
    ),
    CareResource(
        name="긴급 상황",
        phone="119",
        hours="24시간",
        description="지금 위험하다면 119나 112로 바로 전화하세요.",
    ),
]


def rule_risk(text: str) -> str:
    compact = text.replace("\n", " ")
    if _HIGH_RE.search(compact):
        return "high"
    if _WATCH_RE.search(compact):
        return "watch"
    return "none"


def combine(rule: str, llm: str | None) -> str:
    if llm in _RANK and _RANK[llm] > _RANK[rule]:
        return llm
    return rule


def care_notice(level: str) -> CareNotice | None:
    if level == "high":
        return CareNotice(
            level="high",
            title="혼자 견디지 않아도 돼요",
            message=(
                "지금 많이 힘드신 것 같아요. 그 마음을 들어 줄 사람이 24시간 기다리고 있어요. "
                "아래 번호로 지금 바로 전화해 보세요. 전화가 어렵다면 가까운 사람에게 '나 지금 힘들어'라고만 말해도 괜찮아요."
            ),
            resources=RESOURCES,
        )
    if level == "watch":
        return CareNotice(
            level="watch",
            title="마음이 많이 지치셨나요",
            message="그리움이 너무 무거울 때는 누군가와 나누면 조금 가벼워져요. 이야기 나눌 곳이 언제든 열려 있어요.",
            resources=RESOURCES[:2],
        )
    return None
