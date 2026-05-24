"""
RAG 엔진 — 정보검색 프로젝트 수상 구조.

  검색: BM25 (sparse) + bge-m3 (dense) + bge-reranker-v2-m3 (cross-encoder)
  생성: Qwen2.5-7B-Instruct (4bit GPU)
  출력: 5개 chunk_id + 근거 기반 답변 (모르면 "모른다")

  ★ 점수 구조상 chunk_id 5개 정확도 > LLM 품질 → reranker 가중치 우선.

GPU 필수 (CUDA). LLM 로드 실패 시 추출형 답변 fallback.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("auraview.qa")

# ─── 설정 ─────────────────────────────────────────────────────────────
DEVICE = os.getenv("QA_DEVICE", "cuda")             # cuda 강제 (CPU 시 명시적 fallback)
EMB_MODEL = os.getenv("QA_EMB_MODEL", "BAAI/bge-m3")
RERANKER_MODEL = os.getenv("QA_RERANKER", "BAAI/bge-reranker-v2-m3")
LLM_MODEL = os.getenv("QA_LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
LLM_4BIT = os.getenv("QA_LLM_4BIT", "1") == "1"      # bitsandbytes 4bit
TOP_K_BM25 = int(os.getenv("QA_TOPK_BM25", "30"))    # BM25 1차 후보
TOP_K_DENSE = int(os.getenv("QA_TOPK_DENSE", "30"))  # dense 1차 후보
TOP_K_RERANK = int(os.getenv("QA_TOPK_RERANK", "20"))   # cross-encoder 입력
TOP_K_FINAL = int(os.getenv("QA_TOPK_FINAL", "5"))      # 최종 5개 (정답)
RRF_K = 60                                              # Reciprocal Rank Fusion 상수

INDEX_DIR = Path(os.getenv("QA_INDEX_DIR",
                           str(Path(__file__).resolve().parents[3] / "models" / "qa")))
INDEX_DIR.mkdir(parents=True, exist_ok=True)

# 글로벌 싱글톤 — lazy init
_state_lock = threading.Lock()
_state: Dict[str, Any] = {
    "ready": False,
    "device": None,
    "chunks": [],            # [{chunk_id, doc_id, text, meta}]
    "bm25": None,
    "embedder": None,
    "reranker": None,
    "llm_tokenizer": None,
    "llm_model": None,
    "embeddings": None,      # np.ndarray (n_chunks, dim)
    "load_errors": [],
    "loaded_at": None,
}


# ─── 데이터 모델 ──────────────────────────────────────────────────────
@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id,
                "text": self.text, "meta": self.meta}


@dataclass
class QAResponse:
    query: str
    chunk_ids: List[str]               # 정확히 5개 (정답 항목)
    evidence: List[Dict[str, Any]]     # 5개 chunk + score
    answer: str                        # LLM 생성 또는 추출형 fallback
    confidence: float                  # 0~1
    knows: bool                        # False 면 "모른다"
    timing_ms: Dict[str, float]
    backend: str                       # "qwen-7b" | "extractive-fallback"


# ─── 한국어 토큰화 (BM25용) ───────────────────────────────────────────
_kiwi = None
def _korean_tokenize(text: str) -> List[str]:
    """Kiwi 형태소 분리 (BM25 한국어 정확도). 미설치 시 공백 분리 fallback."""
    global _kiwi
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        except Exception:
            _kiwi = False
    if _kiwi:
        try:
            return [t.form for t in _kiwi.tokenize(text)
                    if len(t.form) >= 2 and t.tag.startswith(("N", "V", "SL", "SN", "MA"))]
        except Exception:
            pass
    # fallback: 영숫자·한글 단어 추출
    return re.findall(r"[A-Za-z0-9가-힣_]{2,}", text.lower())


# ─── 인덱싱 ───────────────────────────────────────────────────────────
def _save_chunks(chunks: List[Chunk]) -> Path:
    p = INDEX_DIR / "chunks.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
    return p


def _load_chunks() -> List[Chunk]:
    p = INDEX_DIR / "chunks.jsonl"
    if not p.exists():
        return []
    out = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                out.append(Chunk(d["chunk_id"], d["doc_id"], d["text"], d.get("meta", {})))
            except Exception:
                continue
    return out


def _build_bm25(chunks: List[Chunk]):
    """rank_bm25 인덱스 구축. CPU 빠름."""
    from rank_bm25 import BM25Okapi
    tokens_list = [_korean_tokenize(c.text) for c in chunks]
    return BM25Okapi(tokens_list)


def _build_embeddings(chunks: List[Chunk], embedder):
    """bge-m3 dense 임베딩 — GPU 권장, 배치 처리."""
    import numpy as np
    texts = [c.text for c in chunks]
    embs = embedder.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return np.asarray(embs, dtype="float32")


def index_corpus(chunks: List[Chunk], *, persist: bool = True) -> Dict[str, Any]:
    """corpus 를 받아서 BM25 + dense 인덱스 구축. 메모리/디스크 보관."""
    t0 = time.time()
    if not chunks:
        raise ValueError("empty corpus")

    # 라이브러리 lazy import (서버 부팅 가속)
    embedder = _load_embedder()
    bm25 = _build_bm25(chunks)
    embeddings = _build_embeddings(chunks, embedder)

    with _state_lock:
        _state["chunks"] = chunks
        _state["bm25"] = bm25
        _state["embeddings"] = embeddings
        _state["ready"] = True
        _state["loaded_at"] = time.time()

    if persist:
        import numpy as np
        _save_chunks(chunks)
        np.save(INDEX_DIR / "embeddings.npy", embeddings)

    return {
        "chunks": len(chunks),
        "embedding_dim": int(embeddings.shape[1]),
        "elapsed_s": round(time.time() - t0, 2),
    }


def restore_index() -> bool:
    """디스크에서 인덱스 복구 — 컨테이너 재시작 후."""
    chunks = _load_chunks()
    if not chunks:
        return False
    emb_p = INDEX_DIR / "embeddings.npy"
    if not emb_p.exists():
        return False
    import numpy as np
    embeddings = np.load(str(emb_p))
    if embeddings.shape[0] != len(chunks):
        return False
    bm25 = _build_bm25(chunks)
    with _state_lock:
        _state["chunks"] = chunks
        _state["bm25"] = bm25
        _state["embeddings"] = embeddings
        _state["ready"] = True
        _state["loaded_at"] = time.time()
    log.info("qa: index restored from disk — %d chunks", len(chunks))
    return True


# ─── 모델 로더 ────────────────────────────────────────────────────────
def _resolve_device() -> str:
    """GPU 강제 — CUDA 미사용 시 명시적 경고 (점수 영향)."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    log.warning("qa: CUDA unavailable — falling back to CPU (성능 저하 · 점수 영향).")
    return "cpu"


def _load_embedder():
    if _state["embedder"] is not None:
        return _state["embedder"]
    with _state_lock:
        if _state["embedder"] is not None:
            return _state["embedder"]
        try:
            from sentence_transformers import SentenceTransformer
            dev = _resolve_device()
            log.info("qa: loading embedder %s on %s", EMB_MODEL, dev)
            m = SentenceTransformer(EMB_MODEL, device=dev)
            _state["embedder"] = m
            _state["device"] = dev
            return m
        except Exception as exc:
            log.exception("qa: embedder load failed")
            _state["load_errors"].append(f"embedder: {exc}")
            raise


def _load_reranker():
    if _state["reranker"] is not None:
        return _state["reranker"]
    with _state_lock:
        if _state["reranker"] is not None:
            return _state["reranker"]
        try:
            from sentence_transformers import CrossEncoder
            dev = _resolve_device()
            log.info("qa: loading reranker %s on %s", RERANKER_MODEL, dev)
            m = CrossEncoder(RERANKER_MODEL, device=dev, max_length=512)
            _state["reranker"] = m
            return m
        except Exception as exc:
            log.exception("qa: reranker load failed")
            _state["load_errors"].append(f"reranker: {exc}")
            raise


def _load_llm() -> Tuple[Any, Any]:
    """Qwen2.5-7B-Instruct + 4bit 양자화 (bitsandbytes). GPU 필수."""
    if _state["llm_model"] is not None:
        return _state["llm_tokenizer"], _state["llm_model"]
    with _state_lock:
        if _state["llm_model"] is not None:
            return _state["llm_tokenizer"], _state["llm_model"]
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer

            if not torch.cuda.is_available():
                raise RuntimeError("Qwen2.5-7B 는 GPU 필수 — CUDA 미사용. CPU 추론 비현실.")

            log.info("qa: loading LLM %s (4bit=%s)", LLM_MODEL, LLM_4BIT)
            tok = AutoTokenizer.from_pretrained(LLM_MODEL, trust_remote_code=True)

            quant_config = None
            if LLM_4BIT:
                try:
                    from transformers import BitsAndBytesConfig
                    quant_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.bfloat16,
                        bnb_4bit_use_double_quant=True,
                        bnb_4bit_quant_type="nf4",
                    )
                except Exception as exc:
                    log.warning("qa: bitsandbytes unavailable, fp16 fallback (%s)", exc)

            model = AutoModelForCausalLM.from_pretrained(
                LLM_MODEL,
                quantization_config=quant_config,
                torch_dtype=torch.bfloat16,
                device_map="auto",
                trust_remote_code=True,
            )
            model.eval()
            _state["llm_tokenizer"] = tok
            _state["llm_model"] = model
            return tok, model
        except Exception as exc:
            log.exception("qa: LLM load failed")
            _state["load_errors"].append(f"llm: {exc}")
            raise


# ─── 검색 ──────────────────────────────────────────────────────────────
def _bm25_search(query: str, top_k: int) -> List[Tuple[int, float]]:
    bm25 = _state["bm25"]
    if bm25 is None:
        return []
    tokens = _korean_tokenize(query)
    if not tokens:
        return []
    scores = bm25.get_scores(tokens)
    # top_k 인덱스
    import numpy as np
    arr = np.asarray(scores)
    if arr.size == 0:
        return []
    idx = np.argsort(-arr)[:top_k]
    return [(int(i), float(arr[i])) for i in idx if arr[i] > 0]


def _dense_search(query: str, top_k: int) -> List[Tuple[int, float]]:
    emb_matrix = _state["embeddings"]
    if emb_matrix is None:
        return []
    embedder = _load_embedder()
    import numpy as np
    q = embedder.encode([query], normalize_embeddings=True, convert_to_numpy=True)[0]
    sims = emb_matrix @ q   # cosine (둘 다 normalized)
    idx = np.argsort(-sims)[:top_k]
    return [(int(i), float(sims[i])) for i in idx]


def _rrf_fuse(results: List[List[Tuple[int, float]]], k: int = RRF_K) -> Dict[int, float]:
    """Reciprocal Rank Fusion — BM25/dense 점수 스케일 차이 무관하게 결합."""
    fused: Dict[int, float] = {}
    for rs in results:
        for rank, (idx, _) in enumerate(rs):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank + 1)
    return fused


def _rerank(query: str, candidates: List[Tuple[int, float]],
            top_k: int) -> List[Tuple[int, float]]:
    if not candidates:
        return []
    chunks = _state["chunks"]
    pairs = [(query, chunks[i].text) for i, _ in candidates]
    try:
        reranker = _load_reranker()
        scores = reranker.predict(pairs, batch_size=16, show_progress_bar=False)
        ranked = sorted(zip([c[0] for c in candidates], [float(s) for s in scores]),
                        key=lambda x: -x[1])
        return ranked[:top_k]
    except Exception as exc:
        log.warning("qa: reranker failed (%s) — RRF fallback", exc)
        # fallback: RRF 점수 그대로
        return sorted(candidates, key=lambda x: -x[1])[:top_k]


def hybrid_search(query: str, top_k: int = TOP_K_FINAL) -> List[Tuple[int, float]]:
    """BM25 + dense → RRF → cross-encoder rerank → top_k."""
    if not _state["ready"]:
        return []
    bm = _bm25_search(query, TOP_K_BM25)
    de = _dense_search(query, TOP_K_DENSE)
    fused_dict = _rrf_fuse([bm, de])
    fused_list = sorted(fused_dict.items(), key=lambda x: -x[1])[:TOP_K_RERANK]
    reranked = _rerank(query, fused_list, top_k=top_k)
    return reranked


# ─── 생성 (Qwen) ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """당신은 신뢰 가능한 한국어 정보 도우미입니다.
반드시 [근거] 영역의 chunk 만을 인용해 답하세요.
근거에 답이 없으면 "모르겠습니다"라고 답하고 추측하지 마세요.
숫자·고유명사는 그대로 인용하세요. 200자 이내로 간결하게."""


def _build_prompt(query: str, evidence_chunks: List[Chunk]) -> str:
    blocks = []
    for c in evidence_chunks:
        blocks.append(f"[chunk_id={c.chunk_id}] {c.text}")
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"[근거]\n" + "\n\n".join(blocks) +
        f"\n\n[질문]\n{query}\n\n"
        f"[답변]\n"
    )


def _llm_generate(query: str, evidence: List[Chunk]) -> Tuple[str, str]:
    """Qwen2.5-7B 추론. 실패 시 추출형 fallback."""
    try:
        tok, model = _load_llm()
        import torch
        prompt = _build_prompt(query, evidence)
        # Qwen chat template 사용
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": "[근거]\n" +
                        "\n\n".join(f"[chunk_id={c.chunk_id}] {c.text}" for c in evidence) +
                        f"\n\n[질문] {query}"},
        ]
        text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tok(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(
                **inputs,
                max_new_tokens=256,
                do_sample=False,
                temperature=0.0,
                repetition_penalty=1.05,
                pad_token_id=tok.eos_token_id,
            )
        gen = tok.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return gen.strip(), "qwen-7b"
    except Exception as exc:
        log.warning("qa: LLM gen failed (%s) — extractive fallback", exc)
        # 추출형 fallback: 가장 score 높은 chunk 의 첫 문장
        if evidence:
            sent = re.split(r"[\.\!\?。\n]", evidence[0].text)
            for s in sent:
                s = s.strip()
                if len(s) >= 10:
                    return s, "extractive-fallback"
        return "모르겠습니다", "extractive-fallback"


# ─── 메인 API ─────────────────────────────────────────────────────────
def ask(query: str) -> QAResponse:
    """질의 → 5 chunk_id + 근거 답변. 메인 진입점."""
    timing: Dict[str, float] = {}
    t0 = time.time()

    if not _state["ready"]:
        return QAResponse(
            query=query, chunk_ids=[], evidence=[],
            answer="인덱스가 아직 구축되지 않았습니다. POST /qa/index 로 corpus 를 업로드하세요.",
            confidence=0.0, knows=False, timing_ms={},
            backend="not-ready",
        )

    # 1) 하이브리드 검색 → 5개 (정답)
    t = time.time()
    final = hybrid_search(query, top_k=TOP_K_FINAL)
    timing["search_ms"] = round((time.time() - t) * 1000, 2)

    chunks_list = _state["chunks"]
    evidence_chunks = [chunks_list[i] for i, _ in final]
    chunk_ids = [c.chunk_id for c in evidence_chunks]
    evidence = [
        {"chunk_id": c.chunk_id, "doc_id": c.doc_id,
         "score": round(score, 4),
         "text": c.text[:300] + ("…" if len(c.text) > 300 else ""),
         "meta": c.meta}
        for c, (_, score) in zip(evidence_chunks, final)
    ]

    # 2) 신뢰도: top1 점수 + top1~top5 변동량
    if final:
        top_score = final[0][1]
        score_var = max(0.0, final[0][1] - final[-1][1]) if len(final) >= 2 else 0.0
        confidence = max(0.0, min(1.0, 0.4 + 0.4 * (top_score / 10.0) + 0.2 * (score_var / 5.0)))
    else:
        confidence = 0.0

    # 3) LLM 생성 (없으면 추출형)
    t = time.time()
    answer, backend = _llm_generate(query, evidence_chunks)
    timing["gen_ms"] = round((time.time() - t) * 1000, 2)

    knows = ("모르" not in answer[:6]) and len(answer.strip()) >= 4 and bool(evidence_chunks)
    timing["total_ms"] = round((time.time() - t0) * 1000, 2)

    return QAResponse(
        query=query,
        chunk_ids=chunk_ids[:TOP_K_FINAL],
        evidence=evidence[:TOP_K_FINAL],
        answer=answer,
        confidence=round(confidence, 3),
        knows=knows,
        timing_ms=timing,
        backend=backend,
    )


def get_status() -> Dict[str, Any]:
    """인덱스 + 모델 상태 — /qa/health 전용."""
    cuda_info = {"available": False, "device": "cpu"}
    try:
        import torch
        if torch.cuda.is_available():
            cuda_info = {
                "available": True,
                "device": "cuda",
                "name": torch.cuda.get_device_name(0),
                "memory_gb": round(torch.cuda.get_device_properties(0).total_memory / 1e9, 2),
            }
    except Exception:
        pass

    return {
        "ready": _state["ready"],
        "device": _state.get("device") or cuda_info["device"],
        "cuda": cuda_info,
        "chunks": len(_state["chunks"]),
        "embedding_loaded": _state["embedder"] is not None,
        "reranker_loaded": _state["reranker"] is not None,
        "llm_loaded": _state["llm_model"] is not None,
        "config": {
            "embedder": EMB_MODEL,
            "reranker": RERANKER_MODEL,
            "llm": LLM_MODEL,
            "llm_4bit": LLM_4BIT,
            "top_k_final": TOP_K_FINAL,
            "top_k_bm25": TOP_K_BM25,
            "top_k_dense": TOP_K_DENSE,
        },
        "load_errors": _state["load_errors"],
        "loaded_at": _state["loaded_at"],
    }


# ─── 자동 시드 (AuraView 자체 docs 를 corpus 로 부트스트랩) ───────────
def autoseed_from_project_docs() -> int:
    """startup 시 docs/*.md + README + WHITEPAPER 를 chunk 로 인덱싱."""
    if _state["ready"]:
        return len(_state["chunks"])
    # 디스크 복구 우선
    if restore_index():
        return len(_state["chunks"])

    # docs 에서 fresh build
    proj_root = Path(__file__).resolve().parents[3]
    targets = [
        proj_root / "README.md",
        proj_root / "CHANGELOG.md",
        proj_root / "docs" / "WHITEPAPER_KR.md",
        proj_root / "docs" / "DATASETS.md",
        proj_root / "docs" / "ROADMAP.md",
        proj_root / "docs" / "PRESS_KIT.md",
        proj_root / "docs" / "REPRODUCIBILITY.md",
        proj_root / "docs" / "PRESENTATION_SCRIPT.md",
    ]
    chunks: List[Chunk] = []
    for p in targets:
        if not p.exists():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        # 섹션(##) 단위 분할 → 너무 길면 1000자로 cap
        doc_id = p.stem
        sections = re.split(r"\n(?=#{1,3}\s)", text)
        for i, sec in enumerate(sections):
            sec = sec.strip()
            if len(sec) < 60:
                continue
            for j, sub in enumerate(_split_long(sec, 1000)):
                cid = f"{doc_id}_{i:03d}_{j:02d}"
                chunks.append(Chunk(
                    chunk_id=cid,
                    doc_id=doc_id,
                    text=sub,
                    meta={"path": str(p.relative_to(proj_root)), "section": i, "part": j},
                ))
    if not chunks:
        return 0
    try:
        info = index_corpus(chunks, persist=True)
        log.info("qa: autoseed indexed %d chunks (%.2fs)", info["chunks"], info["elapsed_s"])
        return info["chunks"]
    except Exception:
        log.exception("qa: autoseed failed")
        return 0


def _split_long(text: str, max_len: int) -> List[str]:
    if len(text) <= max_len:
        return [text]
    out = []
    cur = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > max_len and cur:
            out.append("".join(cur))
            cur = [line]
            cur_len = len(line)
        else:
            cur.append(line)
            cur_len += len(line)
    if cur:
        out.append("".join(cur))
    return out
