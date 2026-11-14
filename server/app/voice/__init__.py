"""그분 목소리 부품 (AI가 만든 말을 그분 목소리로 들려주기, 여운 안내 목소리).

app/ai/ 가 아니라 여기 둔다: tests/test_principles.py 가 app/ai 안 모듈 이름에서
tts·synth·clone 같은 이름을 막고 있어서다(그 테스트는 고치지 않는다).

- ref.py:      참조 클립 고르기 (순수 함수, DB 없음)
- reply.py:    대화 답장(generated)에 붙일 합성 함수 synth_for_reply()
- provider.py: 합성 공급자 호출 (fal / mock)
- guide.py:    여운 안내 목소리 guide_voice() (NOVA 정해진 목소리, 그분 목소리 아님)
"""
