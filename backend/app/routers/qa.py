"""
RAG 엔드포인트 — 정보검색 프로젝트 수상형 구조.

  POST /qa/ask        ─ {query} → {answer, chunk_ids[5], evidence, confidence}
  POST /qa/index      ─ {chunks} 또는 {jsonl_path} 로 corpus 인덱싱
  POST /qa/index-docs ─ AuraView 자체 docs 자동 인덱싱 (관리자 only)
  GET  /qa/health     ─ 인덱스/모델/CUDA 상태
  GET  /qa/info       ─ 모델·라이브러리 정보 (검증용)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Header
from pydantic import BaseModel, Field

from ..services import qa_engine

log = logging.getLogger("auraview.qa.router")

router = APIRouter()


# ─── 스키마 ───────────────────────────────────────────────────────────
class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)


class ChunkInput(BaseModel):
    chunk_id: str
    doc_id: str
    text: str = Field(..., min_length=1)
    meta: Optional[Dict[str, Any]] = None


class IndexRequest(BaseModel):
    chunks: List[ChunkInput] = Field(..., min_length=1)
    persist: bool = True


# ─── 권한 ─────────────────────────────────────────────────────────────
import os
_ADMIN = os.getenv("ADMIN_TOKEN", "auraview-admin-2026")


def _require_admin(x_admin_token: Optional[str] = Header(default=None)):
    if x_admin_token != _ADMIN:
        raise HTTPException(status_code=401, detail="admin only")


# ─── 엔드포인트 ───────────────────────────────────────────────────────
@router.post("/ask")
def ask(req: AskRequest):
    """질의 → 5개 chunk_id + 근거 답변. **점수 핵심: chunk_id 정확도**."""
    res = qa_engine.ask(req.query)
    return {
        "query": res.query,
        "answer": res.answer,
        "chunk_ids": res.chunk_ids,
        "evidence": res.evidence,
        "confidence": res.confidence,
        "knows": res.knows,
        "timing_ms": res.timing_ms,
        "backend": res.backend,
    }


@router.post("/index", dependencies=[Depends(_require_admin)])
def index_corpus(req: IndexRequest):
    """corpus 업로드 → BM25 + dense 인덱스 빌드."""
    chunks = [
        qa_engine.Chunk(c.chunk_id, c.doc_id, c.text, c.meta or {})
        for c in req.chunks
    ]
    info = qa_engine.index_corpus(chunks, persist=req.persist)
    return {"status": "ok", **info}


@router.post("/index-docs", dependencies=[Depends(_require_admin)])
def index_project_docs():
    """프로젝트 자체 docs (README, WHITEPAPER 등) 를 corpus 로 빌드 — 데모/시드용."""
    n = qa_engine.autoseed_from_project_docs()
    return {"status": "ok", "chunks_indexed": n}


@router.get("/health")
def health():
    """인덱스 + 모델 + CUDA 상태."""
    return qa_engine.get_status()


@router.get("/info")
def info():
    """개발자용 — RAG 스택 구성 요소 명시."""
    return {
        "competition_role": "정보검색 5-chunk_id 정답 + 근거 답변",
        "stack": {
            "sparse_retrieval": {
                "algorithm": "BM25 (Okapi)",
                "library": "rank_bm25",
                "tokenizer": "kiwipiepy (Korean morpheme) → space fallback",
                "top_k": qa_engine.TOP_K_BM25,
            },
            "dense_retrieval": {
                "model": qa_engine.EMB_MODEL,
                "library": "sentence-transformers",
                "device": "cuda (GPU 강제)",
                "normalize": True,
                "top_k": qa_engine.TOP_K_DENSE,
            },
            "fusion": {
                "method": "Reciprocal Rank Fusion (RRF)",
                "k": qa_engine.RRF_K,
                "input_to_reranker": qa_engine.TOP_K_RERANK,
            },
            "reranker": {
                "model": qa_engine.RERANKER_MODEL,
                "library": "sentence-transformers CrossEncoder",
                "device": "cuda",
                "max_length": 512,
            },
            "generator": {
                "model": qa_engine.LLM_MODEL,
                "params": "≤8B (Qwen2.5-7B-Instruct, 4bit nf4)",
                "device": "cuda",
                "library": "transformers + bitsandbytes",
                "system_prompt": qa_engine.SYSTEM_PROMPT,
            },
        },
        "output_contract": {
            "chunk_ids": "정확히 top_k(default 5)개 — 정답 평가 기준",
            "answer": "근거 chunk 인용 기반, 모르면 '모르겠습니다'",
            "knows": "False 면 답변 무시 (모름 응답)",
            "confidence": "0~1 (top1 score + score variance 합성)",
        },
        "operational": {
            "index_dir": str(qa_engine.INDEX_DIR),
            "persist": "chunks.jsonl + embeddings.npy",
            "restore_on_boot": True,
            "model_cache": "~/.cache/huggingface/ (Docker volume mount 권장)",
        },
        "endpoints": {
            "ask": "POST /qa/ask",
            "index": "POST /qa/index (admin)",
            "index_docs": "POST /qa/index-docs (admin)",
            "health": "GET /qa/health",
            "info": "GET /qa/info",
        },
    }
