# Changelog

All notable changes to **AuraView K-Perception** are tracked here.
Format: keep a [keep-a-changelog](https://keepachangelog.com/en/1.1.0/) style + commit SHA.

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
