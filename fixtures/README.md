# fixtures

모든 fixture는 가상 데이터다. 실제 사람의 녹음·사진은 넣지 않는다.

- `demo/sample-space.json` — 샘플 공간 "[샘플] 김순자 할머니"(가상 인물)의 클립 40개 자막·사진 설명.
  팀원이 `docs/demo-recording-script.md` 대본을 녹음해 `demo/demo-01.m4a` …를 넣으면 `make seed`가 placeholder 대신 쓴다.
- `eval/queries.json` — top-3 검색 정확도 골든 세트(질문 30개 + 맞는 녹음이 없어야 하는 질문 4개).
- `upload/통화 녹음 엄마_240315_190000.m4a` — ffmpeg로 만든 합성 톤(사람 목소리 아님). 업로드·e2e 테스트용.
- `stt/<sha256>.json` — mock STT가 쓰는 자막. 파일 내용의 sha256이 같을 때만 쓰인다.
- `llm-replay/*.json` — replay LLM 공급자가 돌려주는 녹화된 응답.
