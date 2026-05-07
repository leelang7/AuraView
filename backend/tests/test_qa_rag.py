"""
RAG 엔드포인트 통합 테스트.

전제: sentence-transformers / rank-bm25 가 설치되지 않은 CI 환경에서도 통과해야 함.
→ qa_engine import 자체는 가벼움 (lazy import). 실제 모델 로드는 skip.

검증 대상:
  1. /qa/health — 인덱스 ready=False, CUDA info 노출
  2. /qa/info — 스택 구성요소 + 출력 계약 명시
  3. /qa/ask (인덱스 비어있을 때) — 'not-ready' 백엔드 응답
"""

from __future__ import annotations

import os

os.environ.setdefault("ALLOW_FALLBACK", "1")
os.environ.setdefault("SERVICE_KEY", "test-stub")

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_qa_health_responds():
    r = client.get("/qa/health")
    assert r.status_code == 200
    j = r.json()
    # 필수 필드
    assert "ready" in j
    assert "cuda" in j
    assert "config" in j
    assert j["config"]["llm"].startswith("Qwen") or "Qwen" in j["config"]["llm"]
    assert j["config"]["top_k_final"] == 5


def test_qa_info_advertises_stack():
    r = client.get("/qa/info")
    assert r.status_code == 200
    j = r.json()
    assert "stack" in j
    stack = j["stack"]
    assert stack["sparse_retrieval"]["algorithm"].startswith("BM25")
    assert "bge-m3" in stack["dense_retrieval"]["model"].lower()
    assert "rerank" in stack["reranker"]["model"].lower()
    assert "Qwen" in stack["generator"]["model"]
    assert stack["fusion"]["method"] == "Reciprocal Rank Fusion (RRF)"
    # 출력 계약 — 점수 평가 핵심
    assert "chunk_ids" in j["output_contract"]
    assert "5" in j["output_contract"]["chunk_ids"] or "default 5" in j["output_contract"]["chunk_ids"]


def test_qa_ask_when_not_ready_returns_safe_message():
    """인덱스 미구축 시 명확한 에러 응답 — 빈 chunk_ids 반환."""
    # health 가 ready=False 면 ask 도 not-ready 응답
    h = client.get("/qa/health").json()
    if h.get("ready"):
        pytest.skip("index already ready in this run — covered by other tests")
    r = client.post("/qa/ask", json={"query": "AuraView 의 핵심 차별화는?"})
    assert r.status_code == 200
    j = r.json()
    assert j["chunk_ids"] == []
    assert j["backend"] == "not-ready"
    assert "인덱스" in j["answer"] or "index" in j["answer"].lower()


def test_qa_index_requires_admin():
    """인덱싱은 관리자 전용."""
    r = client.post("/qa/index", json={
        "chunks": [{"chunk_id": "x", "doc_id": "d", "text": "hi"}],
    })
    assert r.status_code == 401


def test_qa_ask_validates_query_length():
    """빈 query 거부."""
    r = client.post("/qa/ask", json={"query": ""})
    assert r.status_code == 422
