# AuraView K-Perception backend — single-stage minimal image.
# 시연·심사 환경에서 `docker compose up` 한 줄로 백엔드 + 정적 자산 즉시 가동.
# 모델/검출 무거운 의존성(ultralytics, torch)은 빌드 시 옵션 — ENABLE_ML=true 이면 포함.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 시연 영상 트랜스코드 + 한글 폰트
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 — ML 무거운 패키지 우선 설치 (캐시 활용)
COPY requirements.txt .
RUN pip install -r requirements.txt

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
