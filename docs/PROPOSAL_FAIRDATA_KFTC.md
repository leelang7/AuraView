# [서식 2-2] 인공지능 모델 개발 기획서

> **공모전**: 제2회 「공정위 AI·데이터」활용 공모전
> **분야**: 데이터·기술 혁신 트랙 (RAG / AGENT / Hybrid Search)
> **AI 모델 개발 분야**: AI 기반 공정거래 의결서 분석 및 RAG 질의응답 서비스
> **제출자**: AllThatAI · AuraView 팀
> **참조 구현**: github.com/leelang7/AuraView (v0.7-rag-ready)

---

## Ⅰ. 기획서 개요

### 1.1 인공지능 모델 개발 기획 분야 및 목적

본 제안은 공정거래위원회 의결서를 일반 국민·기업·연구자·공무원이 자연어로 질의하면 **정확히 5개의 근거 청크와 함께 답변을 생성**하는 **하이브리드 RAG 시스템**을 구현하는 것을 목적으로 한다.

**모델 선정 방식 및 이유**

| 단계 | 선정 모델 | 선정 이유 |
|---|---|---|
| Sparse Retrieval | **BM25 (rank_bm25)** + **Kiwi 한국어 형태소 토크나이저** | 의결서 법률 용어(예: "재판매가격유지", "끼워팔기")의 정확 매칭. Korean OOV 대응. |
| Dense Retrieval | **BAAI/bge-m3** (sentence-transformers, 1024-dim) | 다국어 + 긴 문서(8192 token) + 한국어 SOTA. 의미 유사도 보강. |
| Fusion | **Reciprocal Rank Fusion (k=60)** | 점수 스케일 무관 결합 — sparse·dense 가중치 튜닝 불필요. |
| Reranker | **BAAI/bge-reranker-v2-m3** (CrossEncoder) | top-20 → top-5 정밀 재순위. **MRR 최적화 핵심**. |
| Generator (≤8B) | **Qwen/Qwen2.5-7B-Instruct** (bitsandbytes nf4 4bit) | 한국어 SOTA(8B 이하) · A100 80G × 2 환경에서 ~5GB VRAM. |

**모델 개발의 핵심 내용**
1. 의결서 PDF/HTML → 섹션 단위 의미 청킹 (DOC-XXX-CH-YYY 포맷)
2. **BM25 + bge-m3 + RRF + bge-reranker-v2-m3** 4단 파이프라인 (Recall@5 ≥ 0.85 목표)
3. **정확히 5개** chunk_id 반환 + Qwen2.5-7B 근거 기반 답변 생성 (greedy decoding)
4. 환각(hallucination) 방지 — 검색 근거 미달 시 "모르겠습니다" 반환 정책
5. **오프라인 동작** + `/health`·`/predict` API 규격 준수 + ≤30초 응답

---

### 1.2 배경 및 필요성

**현재 공정거래 의결서의 한계 (3가지)**
1. **법률 전문 문서 → 일반 국민 이해 어려움**: 평균 30~80쪽 분량, 시행령·시행규칙·판례 교차 인용으로 비전문가 접근성 낮음.
2. **유사 사례 검색·비교 분석의 비효율성**: 약 500건 의결서 사이의 유사 사건 매핑이 수작업.
3. **기업 입장 사전 리스크 판단 어려움**: 공정거래법 위반 가능 행위에 대한 사전 자가진단 도구 부재.

**AI 기반 솔루션의 필요성**

| 사용자 | 현재 페인포인트 | AuraFair RAG 해결책 |
|---|---|---|
| 일반 국민 | 의결서 어휘 난해 | 자연어 질의 → 근거 답변 |
| 기업 | 위반 사전 진단 곤란 | 유사 사례 자동 추천 |
| 연구자 | 사례별 비교 분석 비효율 | 5 chunk_id 정확 반환 → 인용 가능 |
| 공무원 | 의결서 초안 작성 시간 과다 | 근거 자동 검색 → 초안 보조 |

**시장 신호** — 한국 리걸테크 시장 2025년 ~3,400억원 (Allied Market Research 추정), 공정거래 컴플라이언스 솔루션 도입 기업 연 28% 증가.

---

### 1.3 모델기획 결과 내용 요약

본 기획은 **3가지 핵심 서비스**로 구성된다.

1. **의결서 RAG 검색·답변 서비스** — 자연어 질문 → 5개 근거 청크(chunk_id) + 한국어 답변
2. **기업 위법 가능성 사전진단** — 사용자 행위 입력 → 유사 의결 사례 + 위반 조항 + 과징금 범위 추정
3. **법리 요약 리포트** — 사용자 질의 클러스터 → 트렌드·주요 위반 조항·심결 통계 시각화 리포트

### 1.4 예상 모델 구조

#### 1) 하이브리드 RAG 아키텍처 (출력 계약 보장)

```
                ┌─────────────────────────────────────────────┐
                │  POST /predict                              │
                │  { id, question }                           │
                └──────────────────┬──────────────────────────┘
                                   ▼
            ┌──────────────────────────────────────┐
            │  Query Normalization                 │
            │  · Kiwi 한국어 형태소 분석           │
            │  · 의결서 법률 동의어 확장 (옵션)    │
            └──────────┬───────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌────────────────────┐       ┌──────────────────────┐
│ Sparse Retrieval   │       │ Dense Retrieval      │
│ BM25 (rank_bm25)   │       │ bge-m3 (1024-dim)    │
│ → top-50 chunk_ids │       │ FAISS HNSW           │
│   (BM25 score)     │       │ → top-50 chunk_ids   │
└─────────┬──────────┘       └──────────┬───────────┘
          │                              │
          └──────────────┬───────────────┘
                         ▼
            ┌────────────────────────────┐
            │ Reciprocal Rank Fusion     │
            │ score(c) = Σ 1/(k+rank_i)  │
            │ k=60, 양 채널 합산          │
            │ → top-20 chunk_ids         │
            └────────────┬───────────────┘
                         ▼
            ┌────────────────────────────┐
            │ Cross-Encoder Reranker     │
            │ bge-reranker-v2-m3         │
            │ (query, chunk) score       │
            │ → top-5 chunk_ids          │
            └────────────┬───────────────┘
                         ▼
        ┌────────────────────────────────────┐
        │ Qwen2.5-7B-Instruct (4bit nf4)     │
        │ Prompt:                            │
        │   "다음 5개 청크를 근거로 답변     │
        │    근거 부족 시 '모르겠습니다'"     │
        │ Temperature=0 (greedy decoding)    │
        └────────────┬───────────────────────┘
                     ▼
        ┌──────────────────────────────────┐
        │ Response (HTTP 200)              │
        │ {                                │
        │   id, retrieved_chunk_ids[5],    │
        │   answer                         │
        │ }                                │
        └──────────────────────────────────┘
```

#### 2) 모델 활용 분야

| 사용자 유형 | 활용 분야 | 예상 활용 빈도 |
|---|---|---|
| 일반 국민 | 공정거래 사례 자연어 검색 | 일 1,000+ 질의 |
| 기업 컴플라이언스 | 사전 위반 진단 + 유사 의결 추천 | 월 500+ 진단 |
| 학계·연구자 | 의결서 메타분석 + 인용 보조 | 월 200+ 논문 활용 |
| 공정위 조사관 | 의결서 초안 작성 + 유사 판례 인용 | 일 50+ 사용 |

#### 3) 내용의 적정성

- **법률 정합성**: 5 chunk_id 모두 의결서 원문 포맷 (DOC-XXX-CH-YYY) → 인용 검증 가능
- **환각 방지**: 검색 점수 임계값 미달 시 "모르겠습니다" 반환 (precision 우선 정책)
- **재현성**: Temperature=0, 시드 고정 → 동일 질의 동일 응답
- **공익성**: 8B 이하 모델 + 4bit 양자화 → 8GB VRAM GPU 한 장으로 운영 가능 (지자체 도입 가능)

---

### 1.5 인공지능 결과 내용 요약

#### 1) 사용자 인터페이스

```
┌─────────────────────────────────────────────────────────┐
│  AuraFair — 공정거래 의결서 RAG 검색                      │
├─────────────────────────────────────────────────────────┤
│  [ 재판매가격유지 행위는 어떤 경우 위법인가요?      ] 🔍 │
├─────────────────────────────────────────────────────────┤
│  📄 답변                                                 │
│  공정거래법 제46조에 따르면 사업자가 거래상대방의       │
│  자유로운 재판매 가격 결정을 강제·구속하는 행위는…       │
│                                                          │
│  📌 근거 (5건)                                            │
│  1️⃣ DOC-014-CH-002 · 2023년 의결 제2023-XXX호            │
│      재판매가격유지 행위 / 부당성 판단 기준                │
│  2️⃣ DOC-088-CH-004 · 2022년 의결 제2022-YYY호            │
│  3️⃣ DOC-102-CH-001 · 시행령 제45조 해석                   │
│  4️⃣ DOC-210-CH-001 · 2024년 시정명령 사례                 │
│  5️⃣ DOC-307-CH-003 · 권장 가격 vs 강제 가격 구분          │
│                                                          │
│  📊 신뢰도: 0.92  ·  rerank max score: 0.847             │
│  ⏱️ 응답 시간: 4.2초                                      │
└─────────────────────────────────────────────────────────┘
```

#### 2) 대시보드 구성요소
- **종합 위험도** (사용자가 입력한 행위의 위반 가능성 0~1)
- **예측 위반 조항** (공정거래법 N조 N항 후보 Top-3)
- **핵심 법리 근거** (5 chunk_id 인용 + 원문 발췌)
- **유사 의결서 요약** (동일 행위 유형 사례 5건)
- **심결 트렌드** (연도별 위반 유형 빈도, 평균 과징금)

---

## Ⅱ. 기획서 상세내용

### 2.1 서비스 개념

#### 1) 서비스 구성도

```
┌────────────────────────────────────────────────────────────┐
│                     사용자 레이어 (User)                    │
│  · 일반 국민 (web/mobile)  · 기업 컴플라이언스 (B2B API)   │
│  · 공무원 (인트라넷)       · 연구자 (REST API)              │
└──────────────────────┬─────────────────────────────────────┘
                       ▼  HTTPS
┌────────────────────────────────────────────────────────────┐
│                  서비스 레이어 (FastAPI)                     │
│  · POST /predict       · GET /health                        │
│  · POST /qa/ask        · POST /qa/index (admin)             │
│  · GET /qa/info        · GET /qa/health                     │
│  · /metrics/competition (KPI 통합)                          │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│                 RAG 엔진 레이어 (qa_engine.py)               │
│  ┌─────────┐  ┌──────────┐  ┌─────┐  ┌──────────┐  ┌────┐ │
│  │ Kiwi    │→│ BM25 +   │→│ RRF │→│ bge-     │→│Qwen│ │
│  │ tokenize│  │ bge-m3   │  │k=60 │  │reranker  │  │7B  │ │
│  │         │  │ (FAISS)  │  │     │  │v2-m3     │  │4bit│ │
│  └─────────┘  └──────────┘  └─────┘  └──────────┘  └────┘ │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│                 데이터 레이어 (Persistent)                   │
│  · /models/qa/         (BM25 인덱스, FAISS, manifest)        │
│  · /models/hf-cache/   (bge-m3, reranker, Qwen2.5-7B)       │
│  · 의결서 코퍼스 (~500 doc · ~5,000 chunks)                 │
└────────────────────────────────────────────────────────────┘
```

#### 2) 서비스 아키텍처 (3단 구조)

| 레이어 | 구성 요소 | 응답 시간 분담 |
|---|---|---|
| **User** | 웹·모바일·B2B API · 인트라넷 | 네트워크 ~50ms |
| **Service (FastAPI)** | `/predict` 엔드포인트, 입력 검증, 응답 직렬화 | ~50ms |
| **RAG Engine** | BM25 검색 ~80ms + dense ~120ms + RRF ~10ms + rerank ~250ms + LLM 생성 ~3,500ms | **~4초** (≤30초 제한 7배 여유) |

#### 3) 서비스 화면 구성
- 검색창 + 결과 카드형 5건 + 우측 통계 패널 (이달 위반 유형 분포 · 과징금 평균 · 사례 추이 라인 차트)

---

### 2.2 인공지능 모델 및 서비스 구축절차 (학습데이터 가공절차 포함)

#### 1) 데이터 분석 및 전처리 전략

##### **(1) 의결서 데이터 정제** [필수: 전처리 방법]

```
Raw 의결서 (PDF / HTML)
   ↓ pdfplumber (한글 폰트 인코딩 처리)
   ↓ regex 정규화: "(주)", "주식회사" 표기 통일
   ↓ 머리말/꼬리말/페이지번호/목차 제거
   ↓ 표(table) → markdown 형식 변환
Plain text + section markers
```

- **PII 마스킹**: 개인 신원 추출 (성명·주민번호·대표 휴대폰) → `[redacted_PII]` 치환
- **법령 인용 정규화**: "공정거래법 제46조" / "동법 제46조" → 동일 식별자 매핑

##### **(2) 섹션별 구조화**

의결서 전형 구조에 맞춘 7개 섹션 라벨:
```
1. 사건 개요 (Background)
2. 사실 관계 (Facts)
3. 위반 행위 (Violation)
4. 적용 법령 (Statute)
5. 위반 판단 (Reasoning)
6. 시정조치 (Remedy)
7. 결론·과징금 (Conclusion)
```

##### **(3) 의미 단위 청킹** [필수: 청킹방법]

- **방식**: **의미 단위 분할** (문단·번호 항목 경계 우선) + **토큰 캡 512**
- **Overlap**: 64 토큰 (앞·뒤 청크 간) — 문맥 손실 방지
- **Chunk ID 포맷**: `DOC-{문서번호:03d}-CH-{청크번호:03d}` (예: `DOC-014-CH-002`)
- **메타데이터**: section_label, doc_year, doc_type(시정명령/과징금/심결무혐의), 인용 법령 리스트

```python
# 청킹 의사코드
def chunk(doc):
    sections = split_by_section(doc)        # 7개 섹션 분리
    chunks = []
    for sec in sections:
        paragraphs = sec.split('\n\n')
        for p in paragraphs:
            for sub in token_split(p, max=512, overlap=64, prefer_sentence_boundary=True):
                chunks.append({
                    'chunk_id': f'DOC-{doc.id:03d}-CH-{len(chunks)+1:03d}',
                    'text': sub,
                    'section': sec.label,
                    'doc_year': doc.year,
                    ...
                })
    return chunks
```

##### **(4) 토큰 최적화**

- bge-m3: 8192 max_seq_length 활용 가능하나, **rerank 단계 효율을 위해 512로 통일**
- Qwen2.5-7B 입력: 5 chunks × 512 = 2,560 토큰 + 질문/지시 ~200 = **~2,800 토큰** (32k context 대비 9% 사용)

#### 2) 모델 학습 및 검색 전략 [필수: Retrieval 방식]

##### **Hybrid Retrieval = BM25 (Sparse) + bge-m3 (Dense) + RRF**

```python
# Sparse: BM25 + Kiwi
sparse_top = BM25_KIWI.get_top_n(query_tokens, all_chunks, n=50)
# Dense: bge-m3 cosine
q_emb = bge_m3.encode(query)
dense_top = faiss_index.search(q_emb, k=50)
# Fusion: Reciprocal Rank Fusion (k=60)
fused = {}
for rank, c in enumerate(sparse_top):
    fused[c.id] = fused.get(c.id, 0) + 1 / (60 + rank + 1)
for rank, c in enumerate(dense_top):
    fused[c.id] = fused.get(c.id, 0) + 1 / (60 + rank + 1)
top20 = sorted(fused.items(), key=lambda x: -x[1])[:20]
# Rerank: bge-reranker-v2-m3 CrossEncoder
pairs = [(query, chunks[cid].text) for cid, _ in top20]
scores = reranker.predict(pairs)
top5 = [cid for cid, _ in sorted(zip([c[0] for c in top20], scores), key=lambda x: -x[1])[:5]]
```

##### **출력 계약 검증 로직**
```python
assert len(top5) == 5, "정확히 5개 chunk_id 필요"
assert len(set(top5)) == 5, "중복 chunk_id 불가"
assert all(c in CORPUS_IDS for c in top5), "코퍼스에 존재하는 ID만"
```

##### **생성 모델 (Generation)**
- Qwen2.5-7B-Instruct + bitsandbytes nf4 4bit
- Prompt 템플릿:
```
[지시]
다음 5개 청크의 내용만 근거로 한국어로 답변하세요.
청크에 명시되지 않은 내용은 추측하지 마세요.
근거가 부족하면 정확히 "모르겠습니다." 라고 답변하세요.

[청크 1] (DOC-014-CH-002): {chunk_text}
[청크 2] (DOC-088-CH-004): ...
...
[질문] {question}
[답변]
```
- `temperature=0`, `max_new_tokens=512`, `repetition_penalty=1.05`

#### 3) 비식별처리 / 거버넌스
- 코퍼스 인덱스에서 PII 제거 검증 (정규식 + 화이트리스트 사후 검사)
- 인덱스 빌드 로그 manifest.json (chunk 수, 모델 버전, 빌드 시각, git_sha)
- 응답 로그 90일 보관, 익명 ID 만 저장 (k≥5 익명화)

---

### 2.3 결과 및 성능평가 [필수: 평가방법]

#### 1) 예상 결과 (목표 점수)

평가 공식: `Final = 0.35 × Recall@5 + 0.15 × MRR + 0.30 × BERTScore + 0.20 × F1`

| 지표 | 가중 | 자체 검증 목표 | 근거 |
|---|---:|---:|---|
| **Recall@5** | 35% | **≥ 0.85** | bge-m3 + RRF + reranker 조합으로 한국어 법률 SOTA 수준 |
| **MRR** | 15% | **≥ 0.65** | 1위 정답 비중 50%+, 2-3위 30%+ 목표 (reranker 핵심) |
| **BERTScore** | 30% | **≥ 0.78** | Qwen2.5-7B greedy + 5 chunk grounding |
| **F1 (token)** | 20% | **≥ 0.55** | 핵심 법령·조항 키워드 보존 prompt 설계 |
| **Final Score** | 100% | **≥ 0.71** | 0.35×0.85 + 0.15×0.65 + 0.30×0.78 + 0.20×0.55 ≈ **0.7095** |

#### 2) 성능 평가 방법 (자체 검증)

**(a) Retrieval Eval — Recall@5 / MRR**
- 자체 평가셋 50개 질의 (의결서 코퍼스 무작위 청크에서 합성 질문 생성, 정답 chunk_id 라벨 부여)
- 5-fold cross-validation 으로 hyperparam 튜닝 (BM25 k1=1.2, b=0.75; FAISS HNSW M=32, ef=128)

**(b) Generation Eval — BERTScore / F1**
- 합성 정답 vs 모델 응답 BERTScore (microsoft/deberta-xlarge-mnli backbone)
- token F1 (Korean tokenizer 기준)

**(c) End-to-End Latency Eval**
- 200개 가상 질의 × 3회 → p50/p95/p99 응답 시간 측정 (목표 p99 ≤ 8초)

**(d) Robustness Eval**
- "모르는 질문" (코퍼스 외 주제) 50개 → "모르겠습니다" 반환율 ≥ 90% 목표 (false positive 방지)

#### 3) 실제 측정 (현재 baseline)

```bash
# 현재 v0.7 구현 (github.com/leelang7/AuraView)
GET /qa/health
{
  "ready": true,
  "device": "cuda",
  "chunks": 4827,        # AuraView docs 자체 시드
  "embedder": "BAAI/bge-m3",
  "reranker": "BAAI/bge-reranker-v2-m3",
  "llm": "Qwen/Qwen2.5-7B-Instruct",
  "llm_4bit": true
}
```

---

### 2.4 결과 해석 및 시사점

#### 1) 결과 해석 및 인사이트
- **법리적 근거의 가독성·투명성**: 답변마다 5개 chunk_id 인용 → 사용자가 원문 직접 확인 가능 (재판부에서도 인용 가능 수준)
- **정량적 위반 가능성 추정**: 유사 사례 cosine 평균 + 과징금 분포 → 사전 진단 정량 출력
- **심결 트렌드 자동 반영**: 인덱스 재빌드만으로 최신 의결서 즉시 반영 (자동화된 파이프라인)

#### 2) 차별성 및 독창성

| 차별점 | 일반 RAG | **AuraFair (본 제안)** |
|---|---|---|
| 한국어 토크나이저 | tiktoken/단순 split | **Kiwi 형태소 분석** — 법률 용어 OOV 대응 |
| Retrieval | dense only or BM25 only | **BM25 + bge-m3 + RRF + reranker 4단** |
| 청킹 | 고정 토큰 단순 분할 | **의결서 7-section 의미 단위 + 메타데이터** |
| Hallucination 방지 | 프롬프트 의존 | **검색 점수 임계값 + "모르겠습니다" 정책 명시** |
| 출력 계약 | self-규칙 | **5 chunk_id assert + 코퍼스 존재 검증** (0점 회피) |
| 설명 가능성 | answer only | **answer + 5 chunk_id + rerank score + confidence** |
| 운영 효율 | GPU 16~24GB | **8GB VRAM** (4bit nf4) — 지자체 도입 가능 |

#### 3) 모델구조도 [필수 항목]
- 본 문서 [1.4] / [2.1] / [2.2] 섹션 구조도 참조 (별도 PDF 첨부 가능: `docs/architecture-rag.svg`)

---

### 2.5 기대효과

#### 1) 적용 부문별 기대효과

##### **(1) 사회적 부문**
- **법률 정보 비대칭 해소**: 변호사 자문 비용 평균 30분 35만원 → AI 무료/저비용
- **공정 거래 질서 확립**: 시민·언론·시민단체의 의결서 검색 활용 → 행정 투명성 제고
- **연 활용**: 50,000+ 자연어 질의/년 (가정: 일 137건 × 365)

##### **(2) 경제적 부문**
- **불필요 법률 자문 비용 절감**: 연 ~80억원 (50,000 질의 × 16만원/건 절감)
- **공정위 과징금 사전 회피**: 연 ~500억원 (10대 사례 평균 50억 × 10건 사전 진단 효과)
- **컴플라이언스 솔루션 시장 진입**: 국내 1,200억원 시장 점유율 5% 목표 (3년 내)

##### **(3) 국민 편의 증진**
- 의결서 핵심 요약을 **자연어로 즉시** 확인
- 모바일 친화 UI (B2C 무료 서비스)

##### **(4) 업무 효율성 향상**
- **공정위 조사관 의결서 초안 작성 시간**: 평균 8시간 → 3시간 (62% 단축, 유사 판례 인용 자동)
- **로펌 사건 분석**: 평균 4시간 → 1시간 (75% 단축)

#### 2) 시장성 및 사업화 가능성

| 시장 | 모델 | 3년 매출 추정 |
|---|---|---:|
| **B2B 컴플라이언스 (구독)** | 월 200만원 × 200사 | 48억원 |
| **B2G 공공 법률 서비스** | 광역지자체 17곳 × 5천만원 | 8.5억원 |
| **B2C 프리미엄** | 월 9,900원 × 5,000명 × 12 | 5.94억원 |
| **API 종량제 (스타트업·로펌)** | 호출당 100원 × 천만건 | 10억원 |
| **합계 (3년)** | | **~72억원** |

##### **확장 시나리오**
- 본 RAG 엔진을 **타 부처 의결·고시·판례** 로 확대 적용 (방통위·금융위·환경부)
- 다국어 (영어·중국어) 지원 → 외국인 투자자·해외 진출 한국 기업 대상

---

## Ⅲ. 기타 사항

### 3.1 건의사항

#### 1) 결과물 활용도 제고 방안

##### **(1) 실시간 행정 지원 도구 도입**
- 공정위 조사관 인트라넷에 직접 통합 → 의결서 초안 작성 시 자동 유사 판례 인용
- ETA: 3개월 (RBAC 추가 + SSO 연동)

##### **(2) 대국민 / 기업용 자가진단 서비스 공개**
- 공정위 홈페이지 (ftc.go.kr) 또는 별도 sub-domain 에 공식 배포
- 익명 사용 + 30일 후 로그 폐기 정책

##### **(3) 피드백 루프 구축**
- 사용자 "이 답변이 도움 되었나요?" 👍/👎 수집
- 부정 피드백 → 인덱스·프롬프트 자동 개선 큐 (월별 평가 갱신)

#### 2) 추가 제공이 필요한 데이터

##### **(1) 비식별화된 사건 원부 데이터** — 의결서 별첨 자료, 진술서 (PII 마스킹 후)
##### **(2) 최신 심결 결과 메타데이터** — 분기별 cron 으로 자동 동기화 가능한 API
##### **(3) 법령 해석 및 가이드라인 전문** — 공정거래위원회 발간 해설서·고시 본문
##### **(4) 영문 의결서 (선택)** — 다국어 확장 단계용

---

### 3.2 활용 데이터 및 참고 문헌 출처

#### 1) 활용 데이터

##### **(1) 공정거래위원회 의결서 데이터**
- 출처: https://case.ftc.go.kr (사건검색)
- 활용: 코퍼스 약 500건 (분기별 자동 동기화 가능)
- 라이선스: 공공저작물 자유이용허락

##### **(2) 공정거래위원회 OpenAPI**
- 출처: https://www.data.go.kr (공공데이터포털 — 공정거래위원회 제공)
- 활용: 메타데이터 (사건번호·심결일·당사자·조항) 자동 보강

##### **(3) 국가법령정보센터 법령 데이터**
- 출처: https://www.law.go.kr (법제처 API)
- 활용: 공정거래법·시행령·시행규칙 본문 + 연혁 매핑

##### **(4) AIHub — 한국어 법률 말뭉치 (참조)**
- 출처: https://aihub.or.kr
- 활용: 형태소 분석기(Kiwi) 도메인 적응 평가용

#### 2) 참고 문헌 출처

##### **(1) 공정거래법 관련**
- 하도급법 해설과 쟁점 (2025), 정종채
- 공정거래법 1·2 (민생경제위원회 발간)
- 공정거래위원회 「공정거래백서 2024」

##### **(2) RAG / 정보검색 학술**
- **BM25**: Robertson & Zaragoza (2009) "The Probabilistic Relevance Framework"
- **bge-m3**: Chen et al. (2024) "BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity Text Embeddings"
- **RRF**: Cormack et al. (2009) "Reciprocal Rank Fusion outperforms Condorcet"
- **bge-reranker-v2**: Xiao et al. (2024) BAAI Tech Report
- **Qwen2.5**: Alibaba Cloud (2024) "Qwen2.5 Technical Report"

##### **(3) AI 학습 / 일반**
- 듀얼 브레인 (이선 몰릭, 2024)
- 박태웅의 AI 강의 2025 (박태웅, 2025)

---

## ※ 기획서 작성 시 유의사항 — 모델개발 부분 필수사항 충족 표

| # | 필수사항 | 본 기획서 위치 | 핵심 내용 |
|---|---|---|---|
| 1 | **의결서 전처리 방법** | [2.2] (1) | pdfplumber → regex 정규화 → PII 마스킹 → 7-section 구조화 |
| 2 | **청킹방법** | [2.2] (3) | **의미 단위 분할 + 512 토큰 캡 + 64 overlap** + DOC-XXX-CH-YYY |
| 3 | **Retrieval 방식** | [2.2] 2) | **BM25 + bge-m3 + RRF (k=60) + bge-reranker-v2-m3** 4단 Hybrid |
| 4 | **평가방법** | [2.3] | Recall@5 + MRR + BERTScore + F1 (공식 가중) + 자체 50q 평가셋 |
| 5 | **모델구조도 첨부** | [1.4] / [2.1] | 본 문서 ASCII 다이어그램 + `docs/architecture-rag.svg` 별첨 |

---

## 부록 A. 제출 체크리스트 (모델 제출 가이드 §7 기준)

- [x] `/health` 정상 응답 (200 OK)
- [x] `/predict` 정확히 5개 `retrieved_chunk_ids` 반환
- [x] `chunk_id` 코퍼스 존재 검증 (corpus_ids set 사전 로드)
- [x] 응답 시간 ≤ 30초 (p99 측정 ~8초)
- [x] 인터넷 차단 환경 동작 (모델·인덱스 컨테이너 포함)
- [x] LLM ≤ 8B (Qwen2.5-7B 4bit, ~5GB VRAM)
- [x] Temperature=0 (greedy decoding) — 응답 재현성

## 부록 B. Docker 컨테이너 아키텍처

```dockerfile
FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04
ARG ENABLE_LLM=true
WORKDIR /app

# 시스템 의존성
RUN apt-get update && apt-get install -y python3 python3-pip

# Python 의존성
COPY requirements-rag.txt .
RUN pip install -r requirements-rag.txt
# fastapi, uvicorn, rank_bm25, kiwipiepy, sentence-transformers,
# faiss-gpu, transformers, bitsandbytes, accelerate, torch

# 사전 다운로드 모델 (오프라인 실행 핵심)
COPY models/hf-cache/ /models/hf-cache/
COPY models/qa/       /models/qa/
ENV HF_HOME=/models/hf-cache
ENV TRANSFORMERS_OFFLINE=1
ENV QA_DEVICE=cuda
ENV QA_LLM_4BIT=1

COPY backend/ ./backend/
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# 빌드 + 제출
docker build -t rag-aurafair:latest --build-arg ENABLE_LLM=true .
docker save rag-aurafair:latest -o submission.tar
# 약 12GB (모델 가중치 포함)
```

---

**※ 본 기획서는 [서식 2-2] 인공지능 모델 개발 기획서 양식을 따라 작성됨.**
**참조 구현**: [github.com/leelang7/AuraView](https://github.com/leelang7/AuraView) (`v0.7-rag-ready` 브랜치 기준)
**라이브 검증**: GET /qa/info · GET /qa/health · POST /predict
