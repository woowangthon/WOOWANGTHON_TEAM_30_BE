# 여운 API 서버 이미지 (Render·로컬 공용)
# 빌드 컨텍스트는 저장소 루트다:  docker build -f server/Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ffmpeg: 오디오 추출·정규화(16kHz mono)·클립 자르기
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/server
COPY server/requirements.lock ./requirements.lock
RUN pip install -r requirements.lock

# 형태소 분석기 kiwi는 메모리를 약 350MB 써서 Render 무료(512MB)에서는 빼고 lite를 쓴다.
# 메모리가 넉넉한 서버라면: docker build --build-arg WITH_KIWI=true ...  그리고 YEOUN_TOKENIZER=kiwi
ARG WITH_KIWI=false
RUN if [ "$WITH_KIWI" = "true" ]; then pip install "kiwipiepy>=0.20"; fi

COPY shared /app/shared
COPY fixtures /app/fixtures
COPY server /app/server
RUN pip install --no-deps -e . \
    && useradd --create-home --uid 10001 yeoun \
    && mkdir -p /app/.data && chown -R yeoun /app/.data

USER yeoun
ENV YEOUN_DATA_DIR=/app/.data PORT=10000
EXPOSE 10000

# 시작할 때: DB 스키마 적용 → 샘플 공간(바뀐 게 없으면 건너뜀) → API (작업은 YEOUN_WORKER_INLINE이면 같은 프로세스에서)
CMD ["sh", "start.sh"]
