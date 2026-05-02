"""pytest conftest — 모든 테스트 모듈 import 전에 환경변수 설정."""
import os

# 테스트 환경에서 외부 API 호출은 빠르게 timeout → fallback 으로 떨어지도록
os.environ.setdefault("ALLOW_FALLBACK", "1")
os.environ.setdefault("SERVICE_KEY", "test-stub")
os.environ.setdefault("PUBLIC_API_TIMEOUT", "0.2")

import sys

# backend/ 를 sys.path 에 추가해 `from app.main import app` 가능하게
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
