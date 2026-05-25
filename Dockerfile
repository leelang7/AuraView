# AuraView K-Perception backend — single-stage image with optional GPU LLM stack.
# 시연·검증: `docker compose up` 한 줄로 백엔드 + 정적 자산 가동.
# RAG (Qwen2.5-7B + bge-m3 + bge-reranker-v2-m3): GPU 필수 (CUDA 12+), 4bit 양자화 ~5GB VRAM.
# 빌드 모드:
#   ARG ENABLE_LLM=false    (기본 — 가벼움, RAG 엔드포인트는 /qa/health 만 동작)
#   ARG ENABLE_LLM=true     (GPU 운영 — torch+transformers+bitsandbytes 추가 설치)

ARG ENABLE_LLM=false

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/hf-cache \
    TRANSFORMERS_CACHE=/models/hf-cache \
    QA_INDEX_DIR=/models/qa

# 시연 영상 트랜스코드 + 한글 폰트
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 — ML 무거운 패키지 우선 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install -r requirements.txt

# ── GPU LLM 스택 옵션 (Qwen2.5-7B-Instruct + 4bit) ──
# 빌드: docker build --build-arg ENABLE_LLM=true -t auraview/qa:gpu .
# 런: docker run --gpus all -v hf_cache:/models/hf-cache -v qa_index:/models/qa ...
ARG ENABLE_LLM
RUN if [ "$ENABLE_LLM" = "true" ]; then \
      pip install --no-cache-dir torch>=2.1 transformers>=4.45 accelerate>=0.30 bitsandbytes>=0.43 ; \
    fi

# 모델/인덱스 mount 포인트 (volume 권장)
RUN mkdir -p /models/hf-cache /models/qa

# 코드 복사
COPY backend ./backend
COPY static ./static
COPY frontend_pwa ./frontend_pwa
COPY models ./models
COPY landing ./landing
COPY scripts ./scripts
COPY .env.example ./.env.example

# 업로드/리포트/시나리오 디렉토리 (run-time 생성도 되지만 미리)
RUN mkdir -p backend/uploads backend/uploads/scenarios backend/uploads/showreel \
             backend/uploads/reports backend/fleet dsz_exports

EXPOSE 8000

# Health check — /healthz
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

WORKDIR /app/backend
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
