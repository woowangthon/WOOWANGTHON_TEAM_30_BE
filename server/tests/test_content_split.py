"""목소리로 못 나눈 녹음을 내용으로 나누기 + 그분을 부르는 말 거르기 (DB 없이)."""

from __future__ import annotations

from app.ai.content_split import split_by_content, to_sentences
from app.schemas import TranscriptSegment
from app.services.talk import addressed_to_person

SEG = [TranscriptSegment(start=0, end=10, text="여보세요, 엄마? 나야. 응, 우리 딸. 밥은 먹었니? 아직.", speaker="S1")]


class FakeLLM:
    name = "nova"

    def __init__(self, labels):
        self.labels = labels

    def split_speakers(self, sentences):
        return {"labels": self.labels}


def test_sentences_keep_time_order():
    s = to_sentences(SEG)
    assert [x.text for x in s] == ["여보세요, 엄마?", "나야.", "응, 우리 딸.", "밥은 먹었니?", "아직."]
    assert s[0].start == 0 and abs(s[-1].end - 10) < 1e-6
    assert all(a.end <= b.start + 1e-6 for a, b in zip(s, s[1:]))


def test_split_assigns_two_speakers():
    out, ok = split_by_content(SEG, FakeLLM(["A", "A", "B", "B", "A"]))
    assert ok and [x.speaker for x in out] == ["S1", "S1", "S2", "S2", "S1"]


def test_split_rejects_bad_or_single_output():
    assert split_by_content(SEG, FakeLLM(["A"]))[1] is False  # 개수가 다름
    assert split_by_content(SEG, FakeLLM(["A"] * 5))[1] is False  # 한 사람
    assert split_by_content(SEG, FakeLLM(["A", "C", "B", "B", "A"]))[1] is False


def test_addressed_lines_are_not_the_persons_words():
    assert addressed_to_person("여보세요, 엄마.")
    assert addressed_to_person("엄마, 나 오늘 면접 보고 왔어.")
    assert addressed_to_person("할머니? 나야")
    assert not addressed_to_person("엄마가 해 줄게.")  # 그분이 자기를 '엄마'라고 부르는 말
    assert not addressed_to_person("할매가 니 편이다.")
    assert not addressed_to_person("그래, 고생 많았다.")
