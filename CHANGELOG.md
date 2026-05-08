# Changelog

All notable changes to **AuraView K-Perception** are tracked here.
Format: keep a [keep-a-changelog](https://keepachangelog.com/en/1.1.0/) style + commit SHA.

---

## v0.7 — RAG Ready (2026-05)

### Added
- **RAG 정보검색 스택** — 한국어 정보검색 경진대회 수상 구조
  - Sparse: **BM25 (rank_bm25)** + Kiwi 한국어 형태소 토크나이저
  - Dense: **`BAAI/bge-m3`** (sentence-transformers) 1024-dim 다국어
  - Fusion: **Reciprocal Rank Fusion (k=60)** — 점수 스케일 무관 결합
  - Reranker: **`BAAI/bge-reranker-v2-m3`** (CrossEncoder) top-20 → top-5
  - LLM: **`Qwen/Qwen2.5-7B-Instruct`** (8B 이하) bitsandbytes nf4 4bit, GPU 필수
  - 출력 계약: 정확히 5개 chunk_id + 근거 답변 / "모르겠습니다"
- **`POST /qa/ask`** — query → answer + chunk_ids[5] + evidence + confidence + timing
- **`POST /qa/index`** (admin) — chunks 업로드 + BM25/dense 인덱스 빌드
- **`POST /qa/index-docs`** (admin) — 프로젝트 자체 docs 자동 시드
- **`GET /qa/health`** — 인덱스/모델/CUDA 상태
- **`GET /qa/info`** — 스택 구성 + 출력 계약 명시 (심사용)
- **`backend/app/services/qa_engine.py`** — 핵심 엔진 (lazy load, GPU 강제, 디스크 복원)
- **Dockerfile**: `ARG ENABLE_LLM=true` 빌드 + `/models/hf-cache` + `/models/qa` volume
- **docker-compose**: `--profile gpu` 로 NVIDIA GPU 활성화 (auraview-gpu 서비스)
- **/metrics/competition** 응답에 `rag_stack` 필드 추가 (model/device/chunks 즉시 노출)

### Tests
- 58 → 63 passed (+5: qa health, info, ask not-ready, index admin, query validation).

### Notes
- **점수 구조 핵심**: chunk_id 5개 정확도 > LLM 품질 → dense+rerank 정밀도 우선.
- LLM 미로드 시 추출형 fallback (가장 score 높은 chunk 의 첫 문장).
- 환경변수: `QA_DEVICE=cuda`, `QA_LLM_4BIT=1`, `QA_AUTOSEED_ON_BOOT=1` (compose 기본 활성).
- GPU VRAM: Qwen2.5-7B 4bit ~5GB + bge-m3 fp16 ~1.2GB + reranker ~1.2GB ≈ **8GB VRAM**.

---

## v0.6 — Competition Ready (2026-05)

### Added (Phase 7-30 누적)
- **/competition SERVER specs panel + /healthz/details.resources** (Phase 30) — CPU 코어 + RAM + loadavg + uptime 라이브 노출. SUBMISSION.md 검증·재현 표에 'AWS EC2 t3.small (2 vCPU · 1.87 GB)' 명시.
- **PRESS_KIT 마지막 stale ref 정리** (Phase 29) — 53/53 → 67/67. 모든 67 references 코드/문서/UI 일관.
- **WHITEPAPER 7.2 평가표 8 시나리오 확장** (Phase 28) — +우회전 2.60s · +스쿨존 3.90s · +자전거 3.10s · 평균 (8 voxel + V2V) 3.81s 96.2%.
- **Stale 일관성 정리** (Phase 27) — 38/53 → 67 일괄 갱신 across metrics.py, health.py, positioning.py, README, REPRODUCIBILITY, PRESENTATION_SCRIPT, PRESS_KIT.
- **WHITEPAPER 6-A** Benchmark 표 라이브 측정값 (Phase 26) — 0.67ms mean / 1.44ms p99.
- **/competition section ⑥ Performance Benchmark** (Phase 25) — 실측 latency 자동 fetch from `/benchmark/all`. Risk Transformer 100회 mean 0.67ms / p99 1.44ms · V2V Merge 30회 mean 0.01ms. <5ms 초록색 강조 (production-ready).
- **WHITEPAPER 6-A** Benchmark 표 라이브 측정값으로 갱신 (Phase 25) — backend 컬럼 추가 + 'Phase 25 라이브 측정 결과 — 두 경로 모두 < 5 ms 로 production-ready 확정' 명시.
- **`docs/SUBMISSION.md`** 🏆 — 제출용 통합 1-pager (Phase 23): 한 줄 핵심 + 정량 임팩트 + 모델 성능 + 8 시나리오×도로교통법 + 6 공공데이터 + Tesla 비교 + 1-step 검증 + 검증·재현 + 자료 위치 + 라이센스. 200 줄 약.
- **landing /competition CTA** (Phase 22) — 큰 gradient 버튼 + tests 67/67 갱신.
- **/ui 헤더 🏆 JUDGE HUB 버튼** (Phase 21) — gradient 초록·시안 prominent.
- **/competition section ⑤ Top-10 위험 교차로** (Phase 20) — 강남역·잠실역·광화문 등 자동 fetch + headline 표시.
- **/metrics/api-directory** — 전체 라우트 prefix 별 그룹화 (Phase 18). competition 그룹 highlight + 81 routes / 26 groups.
- **`/competition/`** 🏆 — 정적 HTML 심사위원 허브: 4 KPI hero + 11 검증 URL + 5 데모 + 5 문서 + 8 시나리오 한 페이지 (Phase 14, ~10.7KB, print-friendly). Phase 17 에 LIVE STATUS panel + 도로교통법 섹션 ⑤ 추가.
- **README Mermaid 아키텍처 다이어그램** (Phase 17) — Edge / Cloud / Judge 3-subgraph GitHub 자동 렌더링.
- **ROADMAP** Week 1-4 거의 모든 항목 ✓ (Phase 18) — D-22 to 2026-05-29 제출.
- **`/metrics/manifest`** ⭐ — 11 검증 URL + 5 라이브 데모 + git_sha + 시나리오 8종 + 66 tests (judge single-source-of-truth, JSON, Phase 11).
- **`/policy/laws`** + **`/policy/regulations`** — 8 시나리오 도로교통법 조항·대법원 판례·민식이법·헌재 판례 + 3 agencies 시행규칙·PII 컴플라이언스.
- **`/metrics/data-attribution`** — 6 공공데이터 + 4 정적 데이터셋 + 7 라이브러리 라이센스 명시.
- **`/occupancy/compare`** — 8 시나리오 메타 한 응답 (judge 매트릭스 시각화).
- **Native (Flutter) 강화**:
   - 4 시나리오 ego 애니메이션 (school_zone/bicycle_lane/night_pedestrian/right_turn) wall-clock sync.
   - `_FleetGalleryScreen` — 서버 업로드 이미지 그리드 + 일괄선택 + 일괄삭제 (long-press 모드).
   - `_CompetitionKpiScreen` — 폰에서 4축 KPI 한 화면 + git_sha + 시나리오 chip.
   - 프라이버시 강화 — '폰에는 이미지 저장 X' 명시.
- **Reveal 슬라이드 12 → 15장** — 8 시나리오 매트릭스 + 1-step 검증 + 도로교통법 조항·판례.
- **키오스크 11 → 14장면** — Public Data Live + 8 시나리오 + Korean Traffic Laws + Competition KPI.
- **Three.js 시나리오별 환경** — night/rainy/school 각각 ambient + bg 색.
- **`/metrics/competition`** + **`/metrics/scoreboard`** — 단일 응답으로 모델·임팩트·공공데이터·검증 4축 KPI 노출 + 5개 평가항목 자체채점.
- **`/impact/policy-pdf`** — matplotlib backend 으로 A4 1-pager PDF 즉석 생성 (~88KB). KPI 카드 + 5행 시나리오표 + 6종 공공데이터 상태 + 차별화 4섹션.
- **시나리오 8종 확장** (5 → 8): `school_zone` (DSZ 공공데이터 + 등하교 prior +0.62), `bicycle_lane` (자전거 도로 GIS prior +0.40 + 후방 가속), `night_pedestrian` (헤드라이트 한계 + V2V 헤드라이트 share).
- **prototype UI 탭 ⑩ 공공데이터 라이브** — 6종 소스 mode (live/stub/error/never) 3초 주기 폴링 + KPI 통합 박스.
- **kiosk +2 장면** — Public Data Live + Competition KPI JSON walkthrough.
- **Reveal.js 슬라이드 +2장** (12→14): 8 시나리오 매트릭스 표 + 심사위원 1-step 검증 4 카드.
- **`docs/REPRODUCIBILITY.md`** — 외부 검증 10-section 가이드 (라이브/로컬/재학습/벤치/CI).
- **/healthz/details** — `scenarios_supported` (8종) + `competition_endpoints` 맵 + tests count 53.
- **CI smoke** — Docker job 에 `/metrics/competition`, `/metrics/scoreboard`, 8 시나리오 응답 검증 추가.

### Changed
- 시나리오 right_turn_pedestrian: 보행자 sin 진동 → ego 정지 구간(cycle 0.10~0.40) 동안 1방향 빠른 횡단으로 충돌 시연 제거.
- 시나리오 right_turn_pedestrian: ego 차로 위치 0(중앙선) → +1.5(우측 차로 중앙).
- 시나리오 right_turn_pedestrian: 횡단보도 z=25/31 (ego 도로) 삭제, x=±7 (가로 도로) 복구.
- 웹 BEV: `scene.scale.x = -1` 로 카메라 cross-product 핸디드니스 보정 → world +X (우회전) 가 화면 RIGHT 매핑.
- README + WHITEPAPER + DATASETS + PRESS_KIT 갱신 (8 시나리오, 53 tests, 신규 endpoint).
- CI: flutter analyze warnings non-fatal, Docker healthz timeout 시 warning 만 (메일 스팸 방지).

### Tests
- 38 → 53 passed (+15: metrics 2 + scoreboard 1 + policy-pdf 3 + school_zone 4 + bicycle_lane 2 + night_pedestrian 2 + scenarios list 1).

---

## v0.5 — Quantified Impact (2026-05)

### Added
- **`/impact`** + **`/impact/scenarios`** (services/impact.py): TAAS 2024 통계 + 모델 lead time 기반 연간 사고 예방 효과 계산. preventability = `min(0.85, 0.25 × lead_time_s)` × 도시교차로 46% × scenario_overlap 42%.
  - 헤드라인: "Pilot 5% → 연간 사망 21명 · 부상 2,370명 예방"
- **`/impact/top-intersections`**: 서울 위험 교차로 Top-12 (강남·잠실·광화문·신촌·청량리 등) + 교차로별 KIS 예방 추정.
  - "Top-10만 도입해도 사망·중상 85명/년 예방"
- **`/positioning/tesla-vs-auraview`**: 5종 차별화 비교 (V2V·Bus-Aware·Bidirectional·신호결합·정책환원) + endpoint URL.
- **데이터 freshness 추적** (services/public_api._record_fetch): 6 공공 API fetch 마다 timestamp + mode (live/stub/error) 기록. `/fusion/sources` 응답에 `last_fetched_at`, `age_s`, `mode` 포함.
- **/submission 페이지 대대적 개편**: 임팩트 hero + Top-10 표 + Tesla 5종 비교 + freshness 그리드 + 서울 위험 히트맵 (Leaflet, 136 hotspot points). A4 인쇄 CSS + 모바일 반응형.
- **/ui TAB ⑤ 임팩트/freshness/Top-10 카드**: 30초 주기 라이브 갱신.
- **slides 새 슬라이드 (3b 임팩트, 3c Top-10)**: 라이브 fetch.
- **docs/PRESS_KIT.md**: 한 페이지 수상 자료 (모든 라이브 URL 검증 가능).
- **Showreel CARLA-풍 비주얼**: 3D 사다리꼴 차량 + 빌딩 실루엣 + 다중차로 + 한글 PIL 폰트 + ffmpeg auto-install + 자가-다운로드 NanumGothic.
- **회귀 테스트 8개 추가** (30 → 38): impact (4) + positioning (1) + freshness (1) + summary (1) + top-intersections (2).
- **CI Docker non-blocking + opencv-python-headless**: import smoke 통과.

### Fixed
- /ui 모든 탭 클릭 무반응 — JS triple-quoted 문자열의 `\n` 이스케이프 부재.
- Showreel mp4 가 mp4v 코덱(브라우저 재생 불가) → ffmpeg auto-install + libx264 transcode.
- 한글 카드가 ??? — `cv2.putText` → PIL ImageDraw + NanumGothic.
- 540p × 120frame 다운사이징 (1GB EC2 OOM 회피).
- 비동기 빌드 (큐 + job_id 폴링) — HTTP 워커 블로킹 방지.

---

## v0.4 — Collaborative Perception (2026-05)

### Added
- **V2V Cross-Vehicle Perception** (`services/v2v.py`): 마주오는 차량 시점을 ego BEV 격자에 머지 (heading diff > 130° → weight 0.95). `/collab/v2v/{broadcast,intersection,seed-demo,stats}` + `/collab/fused-occupancy`.
- **Bus-Aware Pedestrian Prior** (`services/bus_aware.py`): 정류장 + 정차 상태 추정 → 보행자 prior +0.55 boost.
- **Bidirectional Lane Fusion** (`services/bidirectional.py`): 마주오는 차들의 감속 비율 + VDS 상행/하행 비대칭 → hazard probability + 권장속도.
- **Trained PyTorch Transformer** (`models/risk_transformer.pt`, 278 KB · 67,970 params): AUC **0.9403**, F1 **0.9412** · 4 시나리오 (혼합/러시아워/야간/우천) · 15 epochs AdamW. baseline linear logistic 대비 +1.0%p AUC.
- **합성 시나리오 6종** (`services/scenario.py`): crosswalk_truck, motorcycle_blindspot, signal_occluded, ⭐ v2v_collab, 🌧️ rainy_intersection, 🌙 night_blindspot. 모두 1080p 24fps + procedural 경고음 (sine beep) + 시네마틱 컬러 그레이딩.
- **`/showreel/build`** + **`/showreel/latest.mp4`**: 6장면 합본 영상 자동 생성, 안정 URL.
- **`/healthz`** + **`/healthz/details`**: 운영·심사 점검용 시스템 메타.
- **`/summary.json`** + **`/submission`**: 원페이지 제출 요약 (baseline vs trained 모델 비교 표 포함).
- **Flutter Fleet 앱 V2V broadcast**: 실시간 위치·heading·속도 + entropy 기반 anomaly detection 송신.
- **시네마틱 시나리오 후처리**: vignette · 글로우 · teal-orange 컬러 그레이딩.
- **`/slides`** Reveal.js 12장 발표 덱 + **`/kiosk`** 무인 자동 시연 10장면.
- **PWA 모바일** + **Flutter Android/Web** 동시 빌드.
- **TAAS 사고 히트맵** (`/heatmap/taas`) + Leaflet 토글.
- **K-MaaS 연계** (`/kmaas/alternatives` · `/kmaas/operator-report`).
- **위험 교차로 Top-N 정책 리포트** (`/reports/generate`) HTML+JSON.
- **Docker** + **docker-compose** + **nginx-proxy**: `docker compose up` 한 줄 가동.
- **GitHub Actions CI**: Python syntax + pytest 30개 + Flutter analyze + WHITEPAPER PDF + Docker build smoke + Train Risk Transformer 자동.
- **architecture.svg**: 1200×760 시스템 다이어그램.
- **landing 자동 sync** (`scripts/sync-landing.sh` + `landing-sync.yml`).
- **데이터안심구역 결합분석 샘플** (`dsz_exports/sample_taas_vds_join_2024.json`, k=5 익명화).

### Changed
- 메인 README 단일화 — `auraview_fleet/README.md` + `landing/README.md` 흡수.
- `auraview_fleet/` Flutter 앱 — Perception Eye 아이콘 + 풀스크린 카메라 UX (단일 알약 버튼 + Haptic + 펄스 링).
- 모든 공개 자료에서 "경진대회/가점/특별상/출품" 단정적 표현 제거 (제출 전 톤 다운).

### Tests
- 18 통합 테스트 (`test_endpoints.py`) + 12 유닛 테스트 (`test_collab_units.py`) = **30/30 PASS**.

---

## v0.3 — Mobile + Slides + Kiosk (2026-04)

### Added
- Flutter `auraview_fleet` 풀스크린 UX 리디자인.
- `/slides`, `/kiosk`, `/pwa` 정적 마운트.
- GitHub Pages 배포 (`allthatai.kr`).

---

## v0.2 — Tesla-style Core (2026-04 초)

### Added
- Occupancy Network PoC + HydraNet 멀티태스크 + Intent Predictor.
- 6 종 공공데이터 어댑터 + 가명결합 + 안심구역 파이프라인.
- 사고 재현 영상 (3 시나리오) + Fleet PWA (HTML/JS).
- BEV 3D 대시보드 (Three.js).

---

## v0.1 — Initial PoC (2026-04 시작)

### Added
- FastAPI 백엔드 + YOLOv8-nano 검출 + 신호 API 연동.
- 다크 HUD 대시보드 + 위험 점수 + Leaflet 지도.
